"""Prueba de extremo a extremo contra un servidor real de ClipStudio.

Recorre: subir video -> procesar -> revisar transcripcion y propuestas -> editar clip
(limites y subtitulos) -> exportar -> verificar el MP4 (resolucion, audio, duracion del
corte y sincronia de subtitulos).

Uso:
    uv run python scripts/prueba_e2e.py RUTA_VIDEO [--url URL] [--conservar]

Arranca su propio servidor en el puerto 8799 con una carpeta de datos temporal propia,
para no tocar los proyectos ni los trabajos de un ClipStudio que ya este abierto. Solo
reutiliza FFmpeg y el modelo de transcripcion ya descargados.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from clipstudio import config as _real  # noqa: E402

# Carpeta de datos aislada para la prueba; FFmpeg y modelos se comparten con la instalacion real.
SALIDA = _real.DATA_DIR / "pruebas"
SALIDA.mkdir(parents=True, exist_ok=True)
DATOS_PRUEBA = Path(tempfile.mkdtemp(prefix="e2e-", dir=SALIDA))
os.environ["CLIPSTUDIO_MODELS_DIR"] = str(_real.MODELS_DIR)
_ffmpeg = _real.find_tool("ffmpeg")
if _ffmpeg:
    os.environ["CLIPSTUDIO_FFMPEG_DIR"] = str(Path(_ffmpeg).parent)
os.environ["CLIPSTUDIO_DATA_DIR"] = str(DATOS_PRUEBA)

import importlib  # noqa: E402

config = importlib.reload(_real)
from clipstudio import media  # noqa: E402

PUERTO = 8799
BASE = f"http://127.0.0.1:{PUERTO}"
resultados: list[tuple[bool, str]] = []


def comprobar(condicion: bool, texto: str) -> bool:
    resultados.append((bool(condicion), texto))
    print(("  [OK]    " if condicion else "  [FALLA] ") + texto, flush=True)
    return bool(condicion)


def api(metodo: str, ruta: str, cuerpo=None, binario: Path | None = None):
    datos, cabeceras = None, {}
    if binario is not None:
        datos = binario.read_bytes()
        cabeceras["Content-Type"] = "application/octet-stream"
    elif cuerpo is not None:
        datos = json.dumps(cuerpo).encode()
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + "/api" + ruta, data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            contenido = r.read()
            return r.status, (json.loads(contenido) if contenido else None)
    except urllib.error.HTTPError as e:
        contenido = e.read()
        try:
            return e.code, json.loads(contenido)
        except ValueError:
            return e.code, None


def esperar_proyecto(pid: str, limite_s: int = 3600) -> dict:
    fin = time.time() + limite_s
    ultimo = ""
    while time.time() < fin:
        _, p = api("GET", f"/proyectos/{pid}")
        linea = f"{p['estado']} / {p['paso']} / {p['progreso']:.0f}% / {p['mensaje']}"
        if linea != ultimo:
            print("    ", linea, flush=True)
            ultimo = linea
        if p["estado"] not in ("en_cola", "procesando"):
            return p
        time.sleep(1.5)
    raise TimeoutError("El proyecto no termino a tiempo")


def esperar_exportacion(pid: str, eid: str, limite_s: int = 1800) -> dict:
    fin = time.time() + limite_s
    while time.time() < fin:
        _, p = api("GET", f"/proyectos/{pid}")
        e = next(x for x in p["exportaciones"] if x["id"] == eid)
        if e["estado"] not in ("en_cola", "procesando"):
            return e
        time.sleep(1)
    raise TimeoutError("La exportacion no termino a tiempo")


def ffprobe(ruta: Path) -> dict:
    out = subprocess.run(
        [media.herramienta("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(ruta)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def volumen_medio(ruta: Path) -> float:
    err = subprocess.run(
        [media.herramienta("ffmpeg"), "-hide_banner", "-i", str(ruta), "-vn", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", err)
    return float(m.group(1)) if m else -999.0


def fotograma(ruta: Path, t: float, destino: Path) -> None:
    subprocess.run(
        [media.herramienta("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(ruta),
         "-frames:v", "1", str(destino)],
        check=True,
    )


def diferencia_franja(a: Path, b: Path, y0: float, y1: float) -> float:
    """Diferencia media de brillo entre dos imagenes en una franja horizontal (0..255)."""
    import cv2
    import numpy as np

    ia, ib = cv2.imread(str(a), cv2.IMREAD_GRAYSCALE), cv2.imread(str(b), cv2.IMREAD_GRAYSCALE)
    alto = ia.shape[0]
    fa, fb = ia[int(alto * y0):int(alto * y1)], ib[int(alto * y0):int(alto * y1)]
    return float(np.mean(np.abs(fa.astype(int) - fb.astype(int))))


def contar_pixeles(imagen: Path, y0: float, y1: float, condicion) -> int:
    """Cuenta pixeles de una franja horizontal que cumplen `condicion(b, g, r)` (matrices numpy)."""
    import cv2

    img = cv2.imread(str(imagen))
    alto = img.shape[0]
    franja = img[int(alto * y0):int(alto * y1)].astype(int)
    return int(condicion(franja[..., 0], franja[..., 1], franja[..., 2]).sum())


def exportar_y_esperar(pid: str, clip_id: str) -> Path | None:
    _, e = api("POST", f"/clips/{clip_id}/exportar")
    e = esperar_exportacion(pid, e["id"])
    if e["estado"] != "listo":
        print("    Exportacion fallida:", e.get("error"))
        return None
    return config.PROJECTS_DIR / pid / "exportaciones" / e["archivo"]


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in texto if unicodedata.category(c) != "Mn"))


def sincronia(mp4: Path, cues: list[dict], inicio_clip: float, idioma: str | None) -> tuple[int, int]:
    """Transcribe el MP4 exportado y cuenta cuantos subtitulos coinciden en texto y tiempo."""
    from clipstudio import transcribe

    wav = mp4.with_suffix(".verif.wav")
    subprocess.run(
        [media.herramienta("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4), "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )
    try:
        t = transcribe.transcribir(wav, 0, idioma or "auto", media.Cancelacion(), lambda _: None)
    finally:
        wav.unlink(missing_ok=True)
    palabras = [(p["inicio"], normalizar(p["texto"])) for s in t["segmentos"] for p in s["palabras"]]
    aciertos = 0
    for c in cues:
        primera = normalizar(c["texto"].split()[0])
        esperado = c["inicio"] - inicio_clip
        if any(w == primera and abs(tw - esperado) <= 0.6 for tw, w in palabras):
            aciertos += 1
    return aciertos, len(cues)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--url", help="Ademas, prueba la importacion de esta URL")
    ap.add_argument("--conservar", action="store_true", help="No borrar los proyectos de prueba")
    args = ap.parse_args()
    if not args.video.is_file():
        print("No existe el video:", args.video)
        return 2

    entorno = {**os.environ, "CLIPSTUDIO_PORT": str(PUERTO), "PYTHONIOENCODING": "utf-8"}
    servidor = subprocess.Popen([sys.executable, "-m", "clipstudio", "--no-abrir"], cwd=RAIZ, env=entorno)
    creados: list[str] = []
    salida = SALIDA
    try:
        for _ in range(60):
            try:
                if api("GET", "/estado")[0] == 200:
                    break
            except OSError:
                time.sleep(0.5)
        estado = api("GET", "/estado")[1]
        if servidor.poll() is not None or Path(estado["carpeta_datos"]) != config.DATA_DIR:
            print(f"El puerto {PUERTO} lo ocupa otro servidor; la prueba no continua para no tocar sus datos.")
            return 2
        print("1. Entorno")
        comprobar(estado["ffmpeg"], "FFmpeg y ffprobe disponibles")

        print("2. Seguridad y validaciones")
        req = urllib.request.Request(BASE + "/api/proyectos", headers={"Origin": "https://ejemplo.com"})
        try:
            codigo = urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            codigo = e.code
        comprobar(codigo == 403, "Rechaza peticiones con Origin ajeno (403)")
        comprobar(api("POST", "/proyectos/url", {"url": "http://127.0.0.1/x"})[0] == 422, "Rechaza URL local (422)")
        codigo, cuerpo = api("PUT", "/proyectos/archivo?nombre=nota.txt", binario=Path(__file__))
        comprobar(codigo == 415, "Rechaza extension no admitida (415)")
        falso = salida / "falso.mp4"
        falso.write_bytes(b"esto no es un video" * 50)
        codigo, p = api("PUT", "/proyectos/archivo?nombre=falso.mp4", binario=falso)
        creados.append(p["id"])
        p = esperar_proyecto(p["id"])
        comprobar(p["estado"] == "error" and "valido" in (p["error"] or ""), f"Archivo corrupto termina en error legible: «{p['error']}»")
        falso.unlink()

        print("3. Subida y procesamiento")
        t0 = time.time()
        consulta = urllib.parse.urlencode({"nombre": args.video.name, "idioma": "auto"})
        codigo, p = api("PUT", f"/proyectos/archivo?{consulta}", binario=args.video)
        comprobar(codigo == 201, "Subida aceptada (201)")
        pid = p["id"]
        creados.append(pid)
        p = esperar_proyecto(pid)
        comprobar(p["estado"] == "listo", f"Proyecto listo en {time.time() - t0:.0f} s (video de {p.get('duracion') or 0:.0f} s)")
        if p["estado"] != "listo":
            print("    Error:", p.get("error"))
            return 1
        comprobar(p["tiene_video"], "Vista previa (proxy) generada")
        req = urllib.request.Request(f"{BASE}/api/proyectos/{pid}/video", headers={"Range": "bytes=0-1023"})
        with urllib.request.urlopen(req) as r:
            comprobar(r.status == 206 and len(r.read()) == 1024, "La vista previa admite peticiones por rango (206)")

        print("4. Transcripcion y propuestas")
        _, t = api("GET", f"/proyectos/{pid}/transcripcion")
        comprobar(len(t["frases"]) >= 3, f"Transcripcion con tiempos: {len(t['frases'])} frases, idioma «{t['idioma']}»")
        for f in t["frases"][:3]:
            print(f"      [{f['inicio']:6.2f}-{f['fin']:6.2f}] {f['texto']}")
        comprobar(len(p["clips"]) >= 1, f"{len(p['clips'])} clip(s) propuesto(s)")
        for c in p["clips"]:
            print(f"      {c['inicio']:6.2f}-{c['fin']:6.2f}  {c['titulo']}  | {'; '.join(c['motivos'])}")
        comprobar(all(c["subtitulos"] for c in p["clips"]), "Cada propuesta trae subtitulos")

        print("5. Edicion del clip")
        clip = p["clips"][0]
        nuevo_fin = round(min(p["duracion"], clip["fin"] + 3.0), 3)
        nuevo_inicio = round(clip["inicio"] + 0.0, 3)
        codigo, c2 = api("PATCH", f"/clips/{clip['id']}", {"inicio": nuevo_inicio, "fin": nuevo_fin})
        comprobar(codigo == 200 and c2["fin"] == nuevo_fin, f"Limites ajustados a {nuevo_inicio}-{nuevo_fin} s")
        subs = c2["subtitulos"]
        original = subs[1]["texto"]
        subs[1]["texto"] = "TEXTO EDITADO"
        codigo, c3 = api("PATCH", f"/clips/{clip['id']}", {"subtitulos": subs, "estilo": {"tamano": 80, "color": "#FFE600"}})
        comprobar(codigo == 200 and c3["subtitulos"][1]["texto"] == "TEXTO EDITADO" and c3["estilo"]["tamano"] == 80,
                  f"Subtitulo editado («{original}» -> «TEXTO EDITADO») y estilo cambiado")
        comprobar(api("PATCH", f"/clips/{clip['id']}", {"inicio": 5, "fin": 5.2})[0] == 422, "Rechaza un clip de menos de 1 s (422)")
        comprobar(api("PATCH", f"/clips/{clip['id']}", {"subtitulos": [{"inicio": 9, "fin": 3, "texto": "x"}]})[0] == 422,
                  "Rechaza subtitulos con tiempos invertidos (422)")
        codigo, manual = api("POST", f"/proyectos/{pid}/clips", {"inicio": 2, "fin": 12, "titulo": "Manual"})
        comprobar(codigo == 201 and manual["origen"] == "manual", "Clip manual creado")

        print("6. Exportacion (rellenar, con subtitulos)")
        codigo, e = api("POST", f"/clips/{clip['id']}/exportar")
        comprobar(codigo == 201, "Exportacion en cola")
        e = esperar_exportacion(pid, e["id"])
        comprobar(e["estado"] == "listo", "Exportacion terminada" + ("" if e["estado"] == "listo" else f": {e['error']}"))
        mp4 = config.PROJECTS_DIR / pid / "exportaciones" / e["archivo"]
        info = ffprobe(mp4)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
        dur = float(info["format"]["duration"])
        esperado = c3["fin"] - c3["inicio"]
        comprobar(v["width"] == 1080 and v["height"] == 1920, f"Video vertical {v['width']}x{v['height']}")
        comprobar(v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p", f"Codec {v['codec_name']} / {v['pix_fmt']}")
        comprobar(a is not None and a["codec_name"] == "aac", "Pista de audio AAC presente")
        vol = volumen_medio(mp4)
        comprobar(vol > -50, f"El audio no esta en silencio (volumen medio {vol:.1f} dB)")
        comprobar(abs(dur - esperado) <= 0.15, f"Duracion {dur:.2f} s frente a {esperado:.2f} s del clip")
        with urllib.request.urlopen(f"{BASE}/api/exportaciones/{e['id']}/archivo?descargar=true") as r:
            comprobar(r.status == 200 and "attachment" in r.headers.get("content-disposition", ""), "Descarga del MP4 por la API")

        print("7. Subtitulos visibles y sincronizados")
        # Un clip gemelo sin subtitulos sirve de referencia para comparar fotogramas.
        _, gemelo = api("POST", f"/proyectos/{pid}/clips", {"inicio": c3["inicio"], "fin": c3["fin"], "titulo": "Sin subtitulos"})
        api("PATCH", f"/clips/{gemelo['id']}", {"subtitulos": [], "recorte_x": c3["recorte_x"]})
        _, e2 = api("POST", f"/clips/{gemelo['id']}/exportar")
        e2 = esperar_exportacion(pid, e2["id"])
        mp4_sin = config.PROJECTS_DIR / pid / "exportaciones" / e2["archivo"]
        cues = c3["subtitulos"]
        cue = cues[1]
        t_cue = (cue["inicio"] + cue["fin"]) / 2 - c3["inicio"]
        huecos = [(x["fin"], y["inicio"]) for x, y in zip(cues, cues[1:]) if y["inicio"] - x["fin"] >= 0.5]
        fa, fb = salida / "con_subtitulos.png", salida / "sin_subtitulos.png"
        fotograma(mp4, t_cue, fa)
        fotograma(mp4_sin, t_cue, fb)
        pos = c3["estilo"]["posicion"] / 100
        d_cue = diferencia_franja(fa, fb, pos - 0.06, pos + 0.06)
        comprobar(d_cue > 3, f"Durante un subtitulo la franja de texto difiere del video sin subtitulos (dif. {d_cue:.1f})")
        if huecos:
            t_hueco = (huecos[0][0] + huecos[0][1]) / 2 - c3["inicio"]
            ga, gb = salida / "hueco_con.png", salida / "hueco_sin.png"
            fotograma(mp4, t_hueco, ga)
            fotograma(mp4_sin, t_hueco, gb)
            d_hueco = diferencia_franja(ga, gb, pos - 0.06, pos + 0.06)
            comprobar(d_hueco < d_cue / 3, f"En una pausa sin subtitulo la franja coincide (dif. {d_hueco:.1f})")
        else:
            print("  [--]    No hay pausas de 0,5 s entre subtitulos para la comprobacion inversa")
        sin_editar = [c for c in cues if c["texto"] != "TEXTO EDITADO"]
        ok, total = sincronia(mp4, sin_editar, c3["inicio"], p.get("idioma_detectado"))
        comprobar(total > 0 and ok / total >= 0.7,
                  f"Sincronia: {ok}/{total} subtitulos coinciden (±0,6 s) con lo que se oye en el MP4 exportado")
        print(f"      Fotogramas guardados en {salida}")

        print("8. Exportacion (ajustar, fondo difuminado) y cancelacion")
        api("PATCH", f"/clips/{manual['id']}", {"encuadre": "ajustar"})
        _, e3 = api("POST", f"/clips/{manual['id']}/exportar")
        e3 = esperar_exportacion(pid, e3["id"])
        comprobar(e3["estado"] == "listo", "Exportacion con encuadre «ajustar» terminada")
        if e3["estado"] == "listo":
            fotograma(config.PROJECTS_DIR / pid / "exportaciones" / e3["archivo"], 3.0, salida / "ajustar.png")
        _, e4 = api("POST", f"/clips/{clip['id']}/exportar")
        _, e5 = api("POST", f"/clips/{clip['id']}/exportar")  # queda en cola detras de e4
        api("POST", f"/exportaciones/{e5['id']}/cancelar")
        _, pe = api("GET", f"/proyectos/{pid}")
        comprobar(next(x for x in pe["exportaciones"] if x["id"] == e5["id"])["estado"] == "cancelado",
                  "Cancelar una exportacion en cola la marca cancelada de inmediato")
        api("POST", f"/exportaciones/{e4['id']}/cancelar")
        e4 = esperar_exportacion(pid, e4["id"])
        time.sleep(0.5)
        restos = list((config.PROJECTS_DIR / pid / "exportaciones").glob("*.tmp"))
        comprobar(e4["estado"] == "cancelado" and not restos, "Cancelar una exportacion en curso la detiene y no deja temporales")
        codigo, _ = api("POST", f"/proyectos/{pid}/reintentar")
        comprobar(codigo == 409, "Reintentar un proyecto ya listo se rechaza (409)")

        print("9. Dividir todo el video")
        codigo, d = api("POST", f"/proyectos/{pid}/dividir", {"duracion_s": 20, "ajustar_a_pausas": True})
        partes = [c for c in d["clips"] if c["origen"] == "division"]
        comprobar(codigo == 200 and len(partes) == d["creados"] >= 3, f"Dividir en partes de ~20 s crea {len(partes)} clips")
        comprobar(
            partes[0]["inicio"] == 0 and abs(partes[-1]["fin"] - p["duracion"]) < 0.01
            and all(a["fin"] == b["inicio"] for a, b in zip(partes, partes[1:])),
            "Las partes cubren el video completo, sin huecos ni solapes",
        )
        duraciones = [round(x["fin"] - x["inicio"], 1) for x in partes]
        comprobar(all(14 <= x <= 33.1 for x in duraciones), f"Duraciones cercanas al objetivo: {duraciones}")
        frases = t["frases"]
        comprobar(
            not any(f["inicio"] + 0.05 < x["fin"] < f["fin"] - 0.05 for x in partes[:-1] for f in frases),
            "Ningun corte cae en mitad de una frase",
        )
        comprobar(all(x["subtitulos"] for x in partes), "Cada parte trae sus subtitulos")
        codigo, d2 = api("POST", f"/proyectos/{pid}/dividir", {"duracion_s": 40, "ajustar_a_pausas": False})
        partes2 = [c for c in d2["clips"] if c["origen"] == "division"]
        ids_viejos = {x["id"] for x in partes}
        comprobar(
            not any(c["id"] in ids_viejos for c in d2["clips"]) and any(c["origen"] == "manual" for c in d2["clips"])
            and partes2[1]["inicio"] == 40.0,
            f"Repetir la division la reemplaza ({len(partes2)} partes exactas de 40 s) y conserva los clips manuales",
        )

        print("10. Titulo gancho, palabra resaltada, fondo de color y preferencias")
        parte = partes2[0]
        estilo = {"titulo_gancho": "TITULO DE PRUEBA", "gancho_segundos": 3, "gancho_posicion": 14,
                  "resaltar": True, "color_resalte": "#FF0000"}
        codigo, parte = api("PATCH", f"/clips/{parte['id']}", {"estilo": estilo})
        comprobar(codigo == 200 and parte["estilo"]["titulo_gancho"] == "TITULO DE PRUEBA" and parte["estilo"]["resaltar"],
                  "El estilo acepta titulo gancho y resaltado")
        con = exportar_y_esperar(pid, parte["id"])
        api("PATCH", f"/clips/{parte['id']}", {"estilo": {"titulo_gancho": "", "resaltar": False}})
        sin = exportar_y_esperar(pid, parte["id"])
        comprobar(con is not None and sin is not None, "Exportaciones con y sin gancho/resaltado terminadas")
        if con and sin:
            blanco = lambda b, g, r: (b > 235) & (g > 235) & (r > 235)  # noqa: E731
            rojo = lambda b, g, r: (r > 200) & (g < 70) & (b < 70)  # noqa: E731
            g1, g2, g3 = salida / "gancho_visible.png", salida / "gancho_fuera.png", salida / "gancho_sin.png"
            fotograma(con, 1.5, g1)
            fotograma(con, 6.0, g2)
            fotograma(sin, 1.5, g3)
            n1, n2, n3 = (contar_pixeles(x, 0.10, 0.18, blanco) for x in (g1, g2, g3))
            comprobar(n1 > 8000 and n1 > 5 * max(n3, 1), f"El titulo gancho se ve al principio ({n1} px blancos frente a {n3} sin gancho)")
            comprobar(n2 < n1 / 5, f"El titulo gancho desaparece tras 3 s ({n2} px blancos)")
            cue = parte["subtitulos"][2]
            t_cue = (cue["inicio"] + cue["fin"]) / 2 - parte["inicio"]
            r1, r2 = salida / "resaltado_con.png", salida / "resaltado_sin.png"
            fotograma(con, t_cue, r1)
            fotograma(sin, t_cue, r2)
            pos = parte["estilo"]["posicion"] / 100
            a, b = contar_pixeles(r1, pos - 0.05, pos + 0.05, rojo), contar_pixeles(r2, pos - 0.05, pos + 0.05, rojo)
            comprobar(a - b > 300, f"Una palabra del subtitulo sale resaltada en rojo ({a} px rojos frente a {b} sin resaltar)")

        api("PATCH", f"/clips/{manual['id']}", {"encuadre": "ajustar", "estilo": {"fondo": "color", "color_fondo": "#00FF00"}})
        verde_mp4 = exportar_y_esperar(pid, manual["id"])
        if comprobar(verde_mp4 is not None, "Exportacion con fondo de color solido terminada"):
            fv = salida / "fondo_color.png"
            fotograma(verde_mp4, 3.0, fv)
            verde = lambda b, g, r: (g > 200) & (r < 80) & (b < 80)  # noqa: E731
            arriba = contar_pixeles(fv, 0.02, 0.12, verde)
            comprobar(arriba > 0.9 * 1080 * int(1920 * 0.10), f"La franja superior es del color elegido ({arriba} px verdes)")

        codigo, pref = api("PUT", "/preferencias/clip", {"estilo": {"tamano": 90, "caja": True, "titulo_gancho": "no debe guardarse"}, "encuadre": "ajustar"})
        comprobar(codigo == 200 and pref["estilo"]["tamano"] == 90 and pref["estilo"]["titulo_gancho"] == "",
                  "Las preferencias guardan el estilo sin el texto del gancho")
        _, nuevo = api("POST", f"/proyectos/{pid}/clips", {"inicio": 20, "fin": 30, "titulo": "Con preferencias"})
        comprobar(nuevo["estilo"]["tamano"] == 90 and nuevo["estilo"]["caja"] and nuevo["encuadre"] == "ajustar",
                  "Un clip nuevo nace con el estilo y el encuadre guardados")

        print("10b. Pantalla dividida con video de juego abajo")
        _, fondos = api("GET", "/fondos")
        comprobar(fondos["fondos"] == [] and Path(fondos["carpeta"]) == config.FONDOS_DIR, "La carpeta de fondos de la prueba empieza vacia")
        codigo, div = api("PATCH", f"/clips/{clip['id']}", {"encuadre": "dividido", "estilo": {"juego_proporcion": 45, "posicion": 55}})
        comprobar(codigo == 200 and div["encuadre"] == "dividido", "El clip acepta el encuadre «dividido»")
        _, e_sin = api("POST", f"/clips/{clip['id']}/exportar")
        e_sin = esperar_exportacion(pid, e_sin["id"])
        comprobar(e_sin["estado"] == "error" and "fondo" in (e_sin["error"] or "").lower(),
                  f"Sin videos de fondo la exportacion falla con un mensaje claro: «{e_sin['error']}»")
        # Fondo de prueba generado aqui mismo: 12 s (mas corto que el clip, para probar el bucle),
        # rojo puro y con un tono de audio que NO debe oirse en el resultado.
        config.FONDOS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [media.herramienta("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:duration=12",
             "-f", "lavfi", "-i", "sine=frequency=3000:duration=12",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(config.FONDOS_DIR / "juego_prueba.mp4")],
            check=True,
        )
        (config.FONDOS_DIR / "notas.txt").write_text("esto no es un video", encoding="utf-8")
        _, fondos = api("GET", "/fondos")
        comprobar([f["nombre"] for f in fondos["fondos"]] == ["juego_prueba.mp4"], "La lista de fondos muestra solo los videos de la carpeta")
        with urllib.request.urlopen(f"{BASE}/api/fondos/juego_prueba.mp4/video") as r:
            comprobar(r.status == 200, "El video de fondo se sirve para la vista previa")
        comprobar(api("GET", "/fondos/notas.txt/video")[0] == 404 and api("GET", "/fondos/..%5Cclipstudio.db/video")[0] == 404,
                  "No se sirven archivos que no sean fondos (404)")
        dividido = exportar_y_esperar(pid, clip["id"])
        if comprobar(dividido is not None, "Exportacion en pantalla dividida terminada"):
            info_d = ffprobe(dividido)
            vd = next(x for x in info_d["streams"] if x["codec_type"] == "video")
            dur_d = float(info_d["format"]["duration"])
            comprobar(vd["width"] == 1080 and vd["height"] == 1920 and abs(dur_d - (div["fin"] - div["inicio"])) <= 0.15,
                      f"Sale 1080x1920 y con la duracion del clip ({dur_d:.2f} s)")
            rojo = lambda b, g, r: (r > 200) & (g < 60) & (b < 60)  # noqa: E731
            area_abajo = 1080 * int(1920 * 0.40)
            for etiqueta, t_f in (("al principio", 2.0), ("tras repetirse el fondo en bucle", 30.0)):
                fd = salida / f"dividido_{int(t_f)}.png"
                fotograma(dividido, t_f, fd)
                abajo, arriba = contar_pixeles(fd, 0.58, 0.98, rojo), contar_pixeles(fd, 0.02, 0.50, rojo)
                comprobar(abajo > 0.95 * area_abajo and arriba < 0.02 * area_abajo,
                          f"El juego ocupa la parte de abajo y el video la de arriba, {etiqueta} ({abajo} px del fondo abajo, {arriba} arriba)")
            n_audio = len([x for x in info_d["streams"] if x["codec_type"] == "audio"])
            sin_d = [c for c in div["subtitulos"] if c["texto"] != "TEXTO EDITADO"]
            ok_d, total_d = sincronia(dividido, sin_d, div["inicio"], p.get("idioma_detectado"))
            comprobar(n_audio == 1 and total_d > 0 and ok_d / total_d >= 0.7,
                      f"El audio es el del video (se reconocen {ok_d}/{total_d} subtitulos) y el del juego no se mezcla")
        api("PATCH", f"/clips/{clip['id']}", {"encuadre": "rellenar"})

        print("10c. Efectos de fondo y copiar el estilo a todos los clips")
        import cv2
        import numpy as np

        def franja_superior(mp4_path: Path, nombre: str):
            destino_png = salida / nombre
            fotograma(mp4_path, 3.0, destino_png)
            img = cv2.imread(str(destino_png)).astype(float)
            return img[int(1920 * 0.03):int(1920 * 0.25)]

        medidas = {}
        for efecto in ("difuminado", "difuminado_oscuro", "difuminado_gris"):
            api("PATCH", f"/clips/{manual['id']}", {"encuadre": "ajustar", "estilo": {"fondo": efecto, "difuminado": 30}})
            mp4_efecto = exportar_y_esperar(pid, manual["id"])
            if mp4_efecto is None:
                continue
            f = franja_superior(mp4_efecto, f"fondo_{efecto}.png")
            medidas[efecto] = {"brillo": float(f.mean()), "saturacion": float((f.max(axis=2) - f.min(axis=2)).mean())}
        comprobar(len(medidas) == 3, "Exportaciones con los tres fondos difuminados terminadas")
        if len(medidas) == 3:
            comprobar(medidas["difuminado"]["brillo"] > 25 and medidas["difuminado"]["saturacion"] > 20,
                      f"El fondo difuminado muestra el video, no negro (brillo {medidas['difuminado']['brillo']:.0f})")
            comprobar(medidas["difuminado_oscuro"]["brillo"] < medidas["difuminado"]["brillo"] * 0.8,
                      f"El fondo oscurecido es mas oscuro ({medidas['difuminado_oscuro']['brillo']:.0f} frente a {medidas['difuminado']['brillo']:.0f})")
            comprobar(medidas["difuminado_gris"]["saturacion"] < 6,
                      f"El fondo en blanco y negro no tiene color (saturacion {medidas['difuminado_gris']['saturacion']:.1f} frente a {medidas['difuminado']['saturacion']:.0f})")

        api("PATCH", f"/clips/{manual['id']}", {"encuadre": "ajustar", "estilo": {
            "tamano": 101, "color": "#00FFAA", "caja": True, "fondo": "difuminado_oscuro", "titulo_gancho": "Solo de este clip"}})
        _, antes_ap = api("GET", f"/proyectos/{pid}")
        codigo, ap = api("POST", f"/proyectos/{pid}/aplicar-estilo", {"clip_id": manual["id"], "que": "subtitulos"})
        otros = [c for c in ap["clips"] if c["id"] != manual["id"]]
        previos = {c["id"]: c for c in antes_ap["clips"]}
        comprobar(codigo == 200 and ap["aplicados"] == len(otros) and all(
            c["estilo"]["tamano"] == 101 and c["estilo"]["color"] == "#00FFAA" and c["estilo"]["caja"] for c in otros),
            f"«Aplicar subtitulos a todos» copia el aspecto del texto a {ap.get('aplicados')} clips")
        comprobar(all(
            c["estilo"]["titulo_gancho"] == previos[c["id"]]["estilo"]["titulo_gancho"]
            and c["estilo"]["fondo"] == previos[c["id"]]["estilo"]["fondo"]
            and c["encuadre"] == previos[c["id"]]["encuadre"]
            and c["subtitulos"] == previos[c["id"]]["subtitulos"] for c in otros),
            "…sin tocar el titulo gancho, el fondo, el encuadre ni el texto de cada clip")
        codigo, ap2 = api("POST", f"/proyectos/{pid}/aplicar-estilo", {"clip_id": manual["id"], "que": "todo"})
        otros2 = [c for c in ap2["clips"] if c["id"] != manual["id"]]
        comprobar(codigo == 200 and all(
            c["encuadre"] == "ajustar" and c["estilo"]["fondo"] == "difuminado_oscuro"
            and c["estilo"]["titulo_gancho"] == previos[c["id"]]["estilo"]["titulo_gancho"]
            and c["recorte_x"] == previos[c["id"]]["recorte_x"] for c in otros2),
            "«Aplicar estilo y encuadre a todos» copia tambien el fondo y el encuadre, y conserva gancho y recorte")
        comprobar(api("POST", f"/proyectos/{pid}/aplicar-estilo", {"clip_id": "no-existe", "que": "todo"})[0] == 404,
                  "Aplicar el estilo de un clip inexistente se rechaza (404)")
        # se deja la division en "rellenar" para la prueba de exportar todos
        for c in otros2:
            api("PATCH", f"/clips/{c['id']}", {"encuadre": "rellenar"})

        print("11. Exportar todos")
        _, antes_todos = api("GET", f"/proyectos/{pid}")
        codigo, lote = api("POST", f"/proyectos/{pid}/exportar-todos", {"origen": "division"})
        comprobar(codigo == 201 and lote["encolados"] == len(partes2), f"Exportar todos pone en cola {lote.get('encolados')} clips de la division")
        nuevas = [e for e in lote["exportaciones"] if e["id"] not in {x["id"] for x in antes_todos["exportaciones"]}]
        finales = [esperar_exportacion(pid, e["id"]) for e in nuevas]
        comprobar(len(finales) == len(partes2) and all(e["estado"] == "listo" for e in finales), "Todas las exportaciones del lote terminan")
        total_s = sum(float(ffprobe(config.PROJECTS_DIR / pid / "exportaciones" / e["archivo"])["format"]["duration"]) for e in finales)
        comprobar(abs(total_s - p["duracion"]) < 0.5 * len(finales), f"La suma de las partes exportadas ({total_s:.1f} s) equivale al video completo ({p['duracion']:.1f} s)")

        if args.url:
            print("12. Importacion por URL")
            codigo, pu = api("POST", "/proyectos/url", {"url": args.url, "idioma": "auto"})
            comprobar(codigo == 201, "Importacion en cola")
            creados.append(pu["id"])
            pu = esperar_proyecto(pu["id"])
            comprobar(pu["estado"] == "listo", f"Proyecto desde URL listo: «{pu['nombre']}»" if pu["estado"] == "listo" else f"Importacion fallida: {pu['error']}")

        print("13. Borrado")
        if not args.conservar:
            for id_ in creados:
                api("DELETE", f"/proyectos/{id_}")
            comprobar(all(not (config.PROJECTS_DIR / i).exists() for i in creados), "Eliminar proyectos borra sus archivos")
            creados.clear()
    finally:
        servidor.terminate()
        try:
            servidor.wait(timeout=10)
        except subprocess.TimeoutExpired:
            servidor.kill()
        if args.conservar:
            print("Datos de la prueba conservados en", DATOS_PRUEBA)
        else:
            shutil.rmtree(DATOS_PRUEBA, ignore_errors=True)

    fallas = [t for ok, t in resultados if not ok]
    print(f"\nResultado: {len(resultados) - len(fallas)}/{len(resultados)} comprobaciones correctas.")
    for t in fallas:
        print("  FALLA:", t)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
