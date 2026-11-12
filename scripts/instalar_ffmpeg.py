"""Descarga FFmpeg (ffmpeg.exe y ffprobe.exe) a la carpeta de datos de ClipStudio.

Uso:  uv run python scripts/instalar_ffmpeg.py
"""

from __future__ import annotations

import io
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipstudio import config  # noqa: E402

FUENTES = [
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]


def descargar(url: str) -> bytes:
    print(f"Descargando {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "ClipStudio-setup"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        leido = 0
        while chunk := resp.read(1024 * 1024):
            buf.write(chunk)
            leido += len(chunk)
            if total:
                print(f"\r  {leido * 100 // total}% ", end="", flush=True)
        print()
        return buf.getvalue()


def main() -> int:
    config.ensure_dirs()
    if config.find_tool("ffmpeg") and config.find_tool("ffprobe"):
        print("FFmpeg ya esta disponible:", config.find_tool("ffmpeg"))
        return 0
    if sys.platform != "win32":
        print("Instala FFmpeg con el gestor de paquetes de tu sistema.")
        return 1
    ultimo_error: Exception | None = None
    for url in FUENTES:
        try:
            datos = descargar(url)
            with zipfile.ZipFile(io.BytesIO(datos)) as z:
                for miembro in z.namelist():
                    nombre = Path(miembro).name
                    if nombre in ("ffmpeg.exe", "ffprobe.exe"):
                        destino = config.BIN_DIR / nombre
                        destino.write_bytes(z.read(miembro))
                        print("Instalado:", destino)
            break
        except Exception as exc:  # se intenta la siguiente fuente
            ultimo_error = exc
            print("  Fallo:", exc)
    ffmpeg = config.find_tool("ffmpeg")
    if not ffmpeg or not config.find_tool("ffprobe"):
        print("No se pudo instalar FFmpeg:", ultimo_error)
        return 1
    salida = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True).stdout
    print(salida.splitlines()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
