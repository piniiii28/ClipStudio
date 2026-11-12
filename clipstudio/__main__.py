"""Arranque: `uv run python -m clipstudio`."""

from __future__ import annotations

import logging
import sys
import threading
import webbrowser

import uvicorn

from . import config


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for ruidoso in ("httpx", "httpcore", "huggingface_hub", "faster_whisper"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    config.ensure_dirs()
    if not config.bloquear_instancia():
        print(f"ClipStudio ya esta abierto con la carpeta de datos {config.DATA_DIR}. Cierra la otra ventana primero.")
        return 1
    if not (config.find_tool("ffmpeg") and config.find_tool("ffprobe")):
        print("AVISO: no se encontro FFmpeg. Ejecuta primero: uv run python scripts/instalar_ffmpeg.py")
    host_url = "127.0.0.1" if config.HOST in ("0.0.0.0", "::") else config.HOST
    url = f"http://{host_url}:{config.PORT}"
    print(f"ClipStudio en {url}   (datos en {config.DATA_DIR})")
    if "--no-abrir" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run("clipstudio.api:app", host=config.HOST, port=config.PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
