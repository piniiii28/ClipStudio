"""Arranque: `uv run python -m clipstudio`."""

from __future__ import annotations

import logging
import json
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import uvicorn

from . import config


def instancia_disponible(url: str) -> bool:
    """Comprueba que el puerto pertenece a ClipStudio con esta misma carpeta de datos."""
    try:
        cliente = build_opener(ProxyHandler({}))
        with cliente.open(url + "/api/estado", timeout=.5) as respuesta:
            estado = json.loads(respuesta.read(65536))
        carpeta = estado.get("carpeta_datos") if isinstance(estado, dict) else None
        return isinstance(carpeta, str) and bool(carpeta) and Path(carpeta).resolve() == config.DATA_DIR
    except (URLError, OSError, ValueError, TypeError):
        return False


def main() -> int:
    if "--worker-youtube" in sys.argv:
        if sys.stdout is None:
            # El bootloader windowed no crea sys.stdout, aunque Popen le pase una tuberia.
            import ctypes
            import io
            import os
            import msvcrt
            obtener = ctypes.windll.kernel32.GetStdHandle
            obtener.restype = ctypes.c_void_p
            descriptor = msvcrt.open_osfhandle(obtener(-11), os.O_WRONLY | os.O_BINARY)
            sys.stdout = io.TextIOWrapper(io.FileIO(descriptor, "w"), encoding="utf-8", write_through=True)
        from .chat import _youtube_worker
        i = sys.argv.index("--worker-youtube")
        _youtube_worker(sys.argv[i + 1], Path(sys.argv[i + 2]))
        return 0
    if "--servidor-escritorio" in sys.argv:
        from .desktop import servidor
        return servidor()
    if "--escritorio" in sys.argv or (getattr(sys, "frozen", False) and "--no-abrir" not in sys.argv):
        from .desktop import main as escritorio
        return escritorio()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for ruidoso in ("httpx", "httpcore", "huggingface_hub", "faster_whisper"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    config.ensure_dirs()
    host_url = "127.0.0.1" if config.HOST in ("0.0.0.0", "::") else config.HOST
    url = f"http://{host_url}:{config.PORT}"
    if not config.bloquear_instancia():
        # La primera ventana puede seguir arrancando cuando llega el segundo doble clic.
        for _ in range(10):
            if instancia_disponible(url):
                print(f"ClipStudio ya esta funcionando en {url}")
                if "--no-abrir" not in sys.argv:
                    webbrowser.open(url)
                return 0
            time.sleep(.2)
        print(f"ClipStudio ya esta abierto con la carpeta de datos {config.DATA_DIR}. Cierra la otra ventana primero.")
        return 1
    if not (config.find_tool("ffmpeg") and config.find_tool("ffprobe")):
        print("AVISO: no se encontro FFmpeg. Ejecuta primero: uv run python scripts/instalar_ffmpeg.py")
    print(f"ClipStudio en {url}   (datos en {config.DATA_DIR})")
    if "--no-abrir" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    opciones = {"log_config": None} if getattr(sys, "frozen", False) else {}
    uvicorn.run("clipstudio.api:app", host=config.HOST, port=config.PORT, log_level="warning", **opciones)
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
