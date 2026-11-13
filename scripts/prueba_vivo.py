"""Prueba de extremo a extremo del modo en vivo, sin red ni plataformas reales.

Arranca un servidor propio en el puerto 8798 con una carpeta de datos temporal y
CLIPSTUDIO_VIVO_PRUEBAS=1. Genera con FFmpeg un video de ~40 s con un tono bajo y un estallido
de volumen en el segundo 28, lo "emite" como si fuera un directo (prueba:<archivo>) y comprueba:
grabacion, segmentos, deteccion del momento, clips, segunda sesion (409) y parada limpia.

Uso:
    uv run python scripts/prueba_vivo.py [--conservar]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from clipstudio import config as _real  # noqa: E402

SALIDA = _real.DATA_DIR / "pruebas"
SALIDA.mkdir(parents=True, exist_ok=True)
DATOS_PRUEBA = Path(tempfile.mkdtemp(prefix="vivo-", dir=SALIDA))
os.environ["CLIPSTUDIO_MODELS_DIR"] = str(_real.MODELS_DIR)   # modelos compartidos: no se descarga nada
_ffmpeg = _real.find_tool("ffmpeg")
if _ffmpeg:
    os.environ["CLIPSTUDIO_FFMPEG_DIR"] = str(Path(_ffmpeg).parent)
os.environ["CLIPSTUDIO_DATA_DIR"] = str(DATOS_PRUEBA)

import importlib  # noqa: E402

config = importlib.reload(_real)
from clipstudio import media  # noqa: E402

PUERTO = 8798
BASE = f"http://127.0.0.1:{PUERTO}"
SEGUNDO_ESTALLIDO = 28
resultados: list[tuple[bool, str]] = []


def comprobar(condicion: bool, texto: str) -> bool:
    resultados.append((bool(condicion), texto))
    print(("  [OK]    " if condicion else "  [FALLA] ") + texto, flush=True)
    return bool(condicion)


def api(metodo: str, ruta: str, cuerpo=None):
    datos, cabeceras = None, {}
    if cuerpo is not None:
        datos = json.dumps(cuerpo).encode()
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + "/api" + ruta, data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            contenido = r.read()
            return r.status, (json.loads(contenido) if contenido else None)
    except urllib.error.HTTPError as e:
        contenido = e.read()
        try:
            return e.code, json.loads(contenido)
        except ValueError:
            return e.code, None


def esperar(condicion, limite_s: float, paso: float = 0.5):
    fin = time.time() + limite_s
    while time.time() < fin:
        valor = condicion()
        if valor:
            return valor
        time.sleep(paso)
    return None


def ffprobe(ruta: Path) -> dict:
    out = subprocess.run(
        [media.herramienta("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(ruta)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def generar_video(destino: Path) -> None:
    """40 s: tono bajo (~-31 dB), estallido fuerte de 2 s en el segundo 28, tono bajo otra vez."""
    subprocess.run(
        [media.herramienta("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
         "-f", "lavfi", "-i", f"sine=frequency=220:duration={SEGUNDO_ESTALLIDO}",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-f", "lavfi", "-i", f"sine=frequency=220:duration={40 - SEGUNDO_ESTALLIDO - 2}",
         "-filter_complex",
         "[1:a]volume=0.4[a1];[2:a]volume=6[a2];[3:a]volume=0.4[a3];[a1][a2][a3]concat=n=3:v=0:a=1[a]",
         "-map", "0:v", "-map", "[a]", "-t", "40", "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(destino)],
        check=True,
    )


def proceso_vivo(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return f'"{pid}"' in out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--conservar", action="store_true", help="No borrar la carpeta de datos de la prueba")
    ap.add_argument("--ejecutable", type=Path, help="Probar una compilacion de escritorio en lugar del Python local")
    args = ap.parse_args()

    video = DATOS_PRUEBA / "directo_prueba.mp4"
    generar_video(video)

    entorno = {**os.environ, "CLIPSTUDIO_PORT": str(PUERTO), "PYTHONIOENCODING": "utf-8",
               "CLIPSTUDIO_VIVO_PRUEBAS": "1"}
    comando = [str(args.ejecutable.resolve())] if args.ejecutable else [sys.executable, "-m", "clipstudio"]
    servidor = subprocess.Popen(comando + ["--no-abrir"], cwd=RAIZ, env=entorno)
    proyectos: list[str] = []
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

        print("1. Validaciones")
        comprobar(estado["ffmpeg"], "FFmpeg y ffprobe disponibles")
        comprobar(api("GET", "/vivo")[1] is None, "Sin sesion activa, GET /api/vivo devuelve null")
        comprobar(api("POST", "/vivo", {"url": "http://127.0.0.1/x"})[0] == 422, "Rechaza una URL local (422)")
        comprobar(api("POST", "/vivo", {"url": "prueba:C:/no_existe.mp4"})[0] == 422, "Rechaza un archivo de prueba inexistente (422)")

        print("2. Conexion y grabacion")
        codigo, s = api("POST", "/vivo", {"url": f"prueba:{video}"})
        comprobar(codigo == 201, "POST /api/vivo crea la sesion (201)")
        sid = s["id"]
        carpeta = config.VIVO_DIR / sid
        s = esperar(lambda: (lambda x: x if x and x["estado"] == "grabando" else None)(api("GET", "/vivo")[1]), 20)
        comprobar(s is not None, "La sesion pasa a «grabando»")
        codigo2, cuerpo2 = api("POST", "/vivo", {"url": f"prueba:{video}"})
        comprobar(codigo2 == 409, f"Una segunda sesion simultanea da 409 ({(cuerpo2 or {}).get('detail')})")

        inicial = esperar(lambda: (lambda x: x if x and x["n_segmentos"] >= 1 else None)(api("GET", "/vivo")[1]), 25)
        comprobar(inicial is not None, "Aparece el primer segmento")
        t0 = time.time()
        a = api("GET", "/vivo")[1]
        time.sleep(8)
        b = api("GET", "/vivo")[1]
        comprobar(b["segundos"] > a["segundos"] and b["n_segmentos"] >= a["n_segmentos"] and b["tamano_mb"] >= a["tamano_mb"],
                  f"Crecen los segundos ({a['segundos']} -> {b['segundos']}) y el bufer ({b['n_segmentos']} segmentos, {b['tamano_mb']} MB)")
        comprobar(len(list(carpeta.glob("seg_*.ts"))) >= 1, "Hay archivos seg_XXXXXX.ts en la carpeta del bufer")
        comprobar(len(b["volumen"]) > 0, "Se devuelve la serie de volumen")
        pid_ffmpeg = b["pid"]
        comprobar(bool(pid_ffmpeg) and proceso_vivo(pid_ffmpeg), "FFmpeg esta en marcha")

        print("3. Deteccion de momentos")
        s = esperar(lambda: (lambda x: x if x and x["momentos"] else None)(api("GET", "/vivo")[1]), 40)
        comprobar(s is not None, "Se detecta un momento")
        if s:
            m = s["momentos"][0]
            comprobar(abs(m["tiempo"] - SEGUNDO_ESTALLIDO) <= 3, f"El momento esta cerca del estallido (t={m['tiempo']:.0f} s, esperado ~{SEGUNDO_ESTALLIDO})")
            comprobar("Pico de volumen" in m["motivo"], f"Motivo: «{m['motivo']}»")

        print("4. Marcadores y clips")
        codigo, marcador = api("POST", f"/vivo/{sid}/momentos", {"nota": "  Buena jugada  "})
        comprobar(codigo == 201, "Marcador manual creado (201)")
        if codigo == 201:
            comprobar(marcador["origen"] == "manual" and marcador["motivo"] == "Buena jugada", "El marcador conserva origen y nota")
            comprobar(marcador["estado"] == "nuevo", "El marcador no crea un clip automático")
        comprobar(api("POST", f"/vivo/{sid}/momentos", {"nota": "x" * 161})[0] == 422, "La nota del marcador tiene un límite")
        s = esperar(lambda: (lambda x: x if x and x["cobertura_s"] >= 40 else None)(api("GET", "/vivo")[1]), 40)
        comprobar(s is not None, "Hay al menos 40 s de segmentos cerrados")
        codigo, r = api("POST", f"/vivo/{sid}/clip", {"segundos": 45})
        comprobar(codigo == 422, "Rechaza segundos distintos de 30/60/90 (422)")
        codigo, r = api("POST", f"/vivo/{sid}/clip", {"segundos": 30})
        comprobar(codigo == 201, f"Clip de los ultimos 30 s creado ({codigo})")
        if codigo == 201:
            proyectos.append(r["proyecto_id"])
            _, p = api("GET", f"/proyectos/{r['proyecto_id']}")
            comprobar(p["origen"] == "archivo", "El proyecto es de origen «archivo»")
            fuente = config.PROJECTS_DIR / p["id"] / p["archivo_fuente"]
            comprobar(fuente.is_file(), f"Existe el archivo fuente ({p['nombre']})")
            if fuente.is_file():
                info = ffprobe(fuente)
                tipos = {x["codec_type"] for x in info["streams"]}
                dur = float(info["format"]["duration"])
                comprobar(abs(dur - 30) <= 1.5, f"Dura ~30 s ({dur:.2f} s)")
                comprobar({"video", "audio"} <= tipos, "Tiene video y audio")
        _, s = api("GET", "/vivo")[0], api("GET", "/vivo")[1]
        if s and s["momentos"]:
            m = s["momentos"][0]
            codigo, r = api("POST", f"/vivo/{sid}/clip", {"momento_id": m["id"]})
            comprobar(codigo == 201, f"Clip desde el momento creado ({codigo})")
            if codigo == 201:
                proyectos.append(r["proyecto_id"])
                fuente = config.PROJECTS_DIR / r["proyecto_id"] / "fuente.mp4"
                if fuente.is_file():
                    dur = float(ffprobe(fuente)["format"]["duration"])
                    comprobar(25 <= dur <= 36.5, f"El clip del momento dura ~25-35 s ({dur:.2f} s)")
                else:
                    comprobar(False, "Existe la fuente del clip del momento")
        comprobar(api("POST", f"/vivo/{sid}/clip", {})[0] == 422, "Pedir un clip sin segundos ni momento da 422")

        print("5. Limpieza de los proyectos de prueba")
        for pid in proyectos:
            api("POST", f"/proyectos/{pid}/cancelar")
            api("DELETE", f"/proyectos/{pid}")
        comprobar(esperar(lambda: all(not (config.PROJECTS_DIR / i).exists() for i in proyectos), 30) is not None,
                  "Los proyectos de prueba se cancelan y se borran")
        proyectos.clear()

        print("6. Parada")
        codigo, _ = api("POST", f"/vivo/{sid}/parar")
        comprobar(codigo == 200, "POST parar (200)")
        comprobar(esperar(lambda: not proceso_vivo(pid_ffmpeg), 10) is not None, "FFmpeg ya no esta en ejecucion")
        comprobar(not carpeta.exists(), "Se borro la carpeta del bufer")
        comprobar(api("GET", "/vivo")[1] is None, "Sin sesion activa tras parar")
        comprobar(api("POST", f"/vivo/{sid}/parar")[0] == 404, "Parar de nuevo da 404")
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
