"""Prueba con red real de los fondos de YouTube del encuadre "dividido".

Exporta de verdad un clip dividido con cada fondo remoto de serie (dos descargas de un tramo
de ~35 s, solo video) y comprueba: MP4 de 1080x1920 con la duracion del clip, franja inferior
con contenido (ni negra ni de un solo color), audio del clip, tramo guardado en la cache y
credito del autor visible (esquina inferior izquierda de la franja) solo cuando se activa.
La segunda exportacion de cada fondo debe salir de la cache, sin otra descarga.

Uso:
    uv run python scripts/prueba_fondos_remotos.py [RUTA_VIDEO] [--conservar]

Arranca su propio servidor en el puerto 8797 con una carpeta de datos temporal; el video de
entrada (por defecto %LOCALAPPDATA%/ClipStudio/pruebas/video_prueba.mp4) solo se lee.
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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from clipstudio import config as _real  # noqa: E402

SALIDA = _real.DATA_DIR / "pruebas"
VIDEO_POR_DEFECTO = SALIDA / "video_prueba.mp4"      # solo lectura
# Tramos ya bajados en una ejecucion anterior: se copian a la cache de la prueba para no volver a
# descargar (--sin-semilla fuerza la descarga real; lo que se baje se guarda aqui al terminar).
SEMILLA = SALIDA / "cache_fondos_semilla"
SALIDA.mkdir(parents=True, exist_ok=True)
DATOS_PRUEBA = Path(tempfile.mkdtemp(prefix="fondos-", dir=SALIDA))
os.environ["CLIPSTUDIO_MODELS_DIR"] = str(_real.MODELS_DIR)
_ffmpeg = _real.find_tool("ffmpeg")
if _ffmpeg:
    os.environ["CLIPSTUDIO_FFMPEG_DIR"] = str(Path(_ffmpeg).parent)
os.environ["CLIPSTUDIO_DATA_DIR"] = str(DATOS_PRUEBA)

import importlib  # noqa: E402

config = importlib.reload(_real)
from clipstudio import media  # noqa: E402

PUERTO = 8797
BASE = f"http://127.0.0.1:{PUERTO}"
FONDOS = [("eBExtYRpuqI", "Minecraft parkour", "Fondo: perpexior (YouTube)"),
          ("HeQQwg_N0Yg", "Subway Surfers", "Fondo: OrbitalNCG + (YouTube)")]
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


def esperar_proyecto(pid: str, limite_s: int = 1800) -> dict:
    fin = time.time() + limite_s
    while time.time() < fin:
        _, p = api("GET", f"/proyectos/{pid}")
        if p["estado"] not in ("en_cola", "procesando"):
            return p
        time.sleep(1.5)
    raise TimeoutError("El proyecto no termino a tiempo")


def exportar(pid: str, clip_id: str, limite_s: int = 900) -> tuple[Path | None, float, str | None]:
    """Exporta y devuelve (mp4, segundos que tardo, error)."""
    t0 = time.time()
    _, e = api("POST", f"/clips/{clip_id}/exportar")
    fin = time.time() + limite_s
    while time.time() < fin:
        _, p = api("GET", f"/proyectos/{pid}")
        x = next(v for v in p["exportaciones"] if v["id"] == e["id"])
        if x["estado"] not in ("en_cola", "procesando"):
            if x["estado"] != "listo":
                return None, time.time() - t0, x.get("error")
            return config.PROJECTS_DIR / pid / "exportaciones" / x["archivo"], time.time() - t0, None
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


def fotograma(ruta: Path, t: float, destino: Path) -> Path:
    subprocess.run(
        [media.herramienta("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(ruta),
         "-frames:v", "1", str(destino)],
        check=True,
    )
    return destino


def fotogramas(ruta: Path, tiempos: list[float], prefijo: str):
    import cv2

    return [cv2.imread(str(fotograma(ruta, t, SALIDA / f"{prefijo}_{int(t)}.png"))) for t in tiempos]


def pixeles_de_texto(imgs, x0: int, x1: int, y0: int, y1: int) -> int:
    """Pixeles casi blancos en TODOS los fotogramas de la caja: lo que no cambia es texto, no juego."""
    import numpy as np

    caja = np.stack([i[y0:y1, x0:x1].min(axis=2) for i in imgs])        # brillo minimo por canal
    return int((caja.min(axis=0) > 235).sum())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path, nargs="?", default=VIDEO_POR_DEFECTO)
    ap.add_argument("--conservar", action="store_true")
    ap.add_argument("--sin-semilla", action="store_true", help="No reutilizar tramos de ejecuciones anteriores: descarga de verdad")
    args = ap.parse_args()
    if not args.video.is_file():
        print("No existe el video:", args.video)
        return 2

    import cv2
    import numpy as np

    cache = config.DATA_DIR / "cache_fondos"
    sembrados: set[str] = set()
    if not args.sin_semilla and SEMILLA.is_dir():
        cache.mkdir(parents=True, exist_ok=True)
        for f in SEMILLA.glob("*.mp4"):
            shutil.copyfile(f, cache / f.name)
            sembrados.add(f.name[:11])
        print(f"(Se reutilizan los tramos de {len(sembrados)} fondo(s) bajados antes: esta ejecucion no descarga esos)")

    entorno = {**os.environ, "CLIPSTUDIO_PORT": str(PUERTO), "PYTHONIOENCODING": "utf-8"}
    servidor = subprocess.Popen([sys.executable, "-m", "clipstudio", "--no-abrir"], cwd=RAIZ, env=entorno)
    pid = None
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

        print("1. Catalogo y API (sin descargar)")
        _, f = api("GET", "/fondos")
        comprobar([x["id"] for x in f["remotos"]] == [i for i, _, _ in FONDOS] and f["locales"] == [] and f["fondos"] == [],
                  "GET /api/fondos trae los dos remotos de serie y ningun local")
        codigo, r = api("POST", "/fondos/remotos", {"url": "https://vimeo.com/123"})
        comprobar(codigo == 422, "Rechaza un enlace que no es de YouTube (422)")
        codigo, r = api("POST", "/fondos/remotos", {"url": "https://www.youtube.com/playlist?list=PLabc"})
        comprobar(codigo == 422, "Rechaza una lista de reproduccion (422)")
        codigo, r = api("POST", "/fondos/remotos", {"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"})
        comprobar(codigo == 502 and "dura" in (r or {}).get("detail", ""),
                  f"Consulta real sin descargar: un video de 19 s no sirve de fondo ({(r or {}).get('detail')})")

        print("2. Proyecto de prueba")
        t0 = time.time()
        consulta = urllib.parse.urlencode({"nombre": args.video.name, "idioma": "auto"})
        _, p = api("PUT", f"/proyectos/archivo?{consulta}", binario=args.video)
        pid = p["id"]
        p = esperar_proyecto(pid)
        if not comprobar(p["estado"] == "listo", f"Proyecto listo en {time.time() - t0:.0f} s"):
            print("    Error:", p.get("error"))
            return 1

        ini, fin = 2.0, 17.0
        estilo_base = {"titulo_gancho": "", "marca": "", "juego_proporcion": 45, "posicion": 50, "credito_fondo": False,
                       "credito_tamano": 40}
        _, ref = api("POST", f"/proyectos/{pid}/clips", {"inicio": ini, "fin": fin, "titulo": "Referencia"})
        api("PATCH", f"/clips/{ref['id']}", {"encuadre": "rellenar", "subtitulos": []})
        mp4_ref, _, _ = exportar(pid, ref["id"])
        vol_ref = volumen_medio(mp4_ref) if mp4_ref else -999.0
        _, clip = api("POST", f"/proyectos/{pid}/clips", {"inicio": ini, "fin": fin, "titulo": "Dividido remoto"})
        codigo, c = api("PATCH", f"/clips/{clip['id']}", {"encuadre": "dividido", "subtitulos": [], "estilo": estilo_base})
        comprobar(codigo == 200 and c["encuadre"] == "dividido" and c["estilo"]["credito_fondo"] is False, "Clip dividido preparado (sin subtitulos)")

        tiempos = [3.0, 6.0, 9.0, 12.0]
        for id_, nombre, credito in FONDOS:
            print(f"3. Fondo remoto: {nombre}")
            codigo, c = api("PATCH", f"/clips/{clip['id']}",
                            {"estilo": {"fondo_juego": "yt:" + id_, "credito_fondo": False}})
            comprobar(codigo == 200 and c["estilo"]["fondo_juego"] == "yt:" + id_, "El estilo guarda el fondo yt:<id>")
            antes = {x.name for x in cache.glob("*.mp4")} if cache.is_dir() else set()
            sin_credito, seg1, error = exportar(pid, clip["id"])
            sembrado = id_ in sembrados
            if not comprobar(sin_credito is not None, f"Exportacion {'con el tramo de la cache' if sembrado else 'con descarga del tramo'} terminada en {seg1:.0f} s" + (f": {error}" if error else "")):
                continue
            nuevos = [x for x in cache.glob("*.mp4") if x.name not in antes]
            if sembrado:
                nuevos = [x for x in cache.glob(f"{id_}_*.mp4")]
                comprobar(len(nuevos) == 1 and len(list(cache.glob("*.mp4"))) == len(antes), "No hubo descarga nueva: se uso el tramo de la cache")
            else:
                comprobar(len(nuevos) == 1, f"El tramo bajado queda en la cache ({nuevos[0].name if nuevos else '-'})")
            if nuevos:
                info_t = ffprobe(nuevos[0])
                peso = nuevos[0].stat().st_size / 1024**2
                dur_t = float(info_t["format"]["duration"])
                alto_t = next(s for s in info_t["streams"] if s["codec_type"] == "video")["height"]
                sin_audio = not any(s["codec_type"] == "audio" for s in info_t["streams"])
                print(f"      Tramo: {dur_t:.1f} s, {peso:.1f} MB, {alto_t}p, descarga + exportacion {seg1:.0f} s")
                comprobar(sin_audio and dur_t <= 40 and alto_t <= 1080, "El tramo es solo video, dura <= 40 s y hasta 1080p")
            info = ffprobe(sin_credito)
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            audios = [s for s in info["streams"] if s["codec_type"] == "audio"]
            dur = float(info["format"]["duration"])
            comprobar(v["width"] == 1080 and v["height"] == 1920 and abs(dur - (fin - ini)) <= 0.15,
                      f"Sale {v['width']}x{v['height']} y dura {dur:.2f} s (clip de {fin - ini:.0f} s)")
            vol = volumen_medio(sin_credito)
            comprobar(len(audios) == 1 and vol > -50 and abs(vol - vol_ref) <= 1.5,
                      f"Un solo audio, el del clip ({vol:.1f} dB frente a {vol_ref:.1f} dB del mismo clip sin fondo)")
            imgs = fotogramas(sin_credito, tiempos, f"remoto_{id_}")
            franja = np.stack([i[int(1920 * 0.60):int(1920 * 0.97)] for i in imgs])
            media_f, desv = float(franja.mean()), float(franja.std(axis=(1, 2, 3)).mean())
            colores = len({tuple(px) for px in franja[0][::40, ::40].reshape(-1, 3).tolist()})
            comprobar(media_f > 20 and desv > 12 and colores > 30,
                      f"La franja inferior tiene contenido (brillo {media_f:.0f}, variacion {desv:.0f}, {colores} colores)")
            texto_sin = pixeles_de_texto(imgs, 20, 760, 1920 - 24 - 80, 1920 - 20)

            codigo, c = api("PATCH", f"/clips/{clip['id']}", {"estilo": {"credito_fondo": True, "credito_tamano": 40}})
            en_cache = {x.name for x in cache.glob("*.mp4")}
            con_credito, seg2, error = exportar(pid, clip["id"])
            if not comprobar(con_credito is not None, f"Exportacion con credito activado terminada en {seg2:.0f} s" + (f": {error}" if error else "")):
                continue
            comprobar({x.name for x in cache.glob("*.mp4")} == en_cache and (sembrado or seg2 < seg1),
                      f"La segunda exportacion sale de la cache, sin otra descarga ({seg2:.0f} s frente a {seg1:.0f} s)")
            imgs2 = fotogramas(con_credito, tiempos, f"remoto_credito_{id_}")
            texto_con = pixeles_de_texto(imgs2, 20, 760, 1920 - 24 - 80, 1920 - 20)
            texto_der = pixeles_de_texto(imgs2, 640, 1060, 1920 - 24 - 80, 1920 - 20)
            texto_arriba = pixeles_de_texto(imgs2, 20, 760, int(1920 * 0.62), int(1920 * 0.62) + 100)
            comprobar(texto_con > 1200 and texto_sin < texto_con * 0.25,
                      f"Con el credito aparece texto en la esquina inferior izquierda de la franja ({texto_con} px blancos fijos frente a {texto_sin} sin credito)")
            comprobar(texto_der < texto_con * 0.25 and texto_arriba < texto_con * 0.25,
                      f"El credito no sale en la esquina derecha ni arriba de la franja ({texto_der} y {texto_arriba} px)")
            info2 = ffprobe(con_credito)
            comprobar(abs(float(info2["format"]["duration"]) - (fin - ini)) <= 0.15, "Con credito sigue durando lo que el clip")
            print(f"      Credito esperado: «{credito}»; fotogramas en {SALIDA}")
            api("PATCH", f"/clips/{clip['id']}", {"estilo": {"credito_fondo": False}})

        print("4. Ocultar un fondo de serie")
        codigo, r = api("DELETE", f"/fondos/remotos/{FONDOS[1][0]}")
        comprobar(codigo == 200 and r["resultado"] == "oculto" and [x["id"] for x in r["remotos"]] == [FONDOS[0][0]],
                  "Ocultar un fondo de serie lo saca de la lista")
    finally:
        if pid:
            api("DELETE", f"/proyectos/{pid}")
        servidor.terminate()
        try:
            servidor.wait(timeout=10)
        except subprocess.TimeoutExpired:
            servidor.kill()
        guardados = list((config.DATA_DIR / "cache_fondos").glob("*.mp4"))
        if guardados:
            SEMILLA.mkdir(parents=True, exist_ok=True)
            for f in guardados:
                if not (SEMILLA / f.name).exists():
                    shutil.copyfile(f, SEMILLA / f.name)
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
