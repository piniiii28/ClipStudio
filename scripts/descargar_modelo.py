"""Descarga por adelantado el modelo de transcripcion (opcional).

Si no lo haces, ClipStudio lo descarga solo al procesar el primer video; este script solo
sirve para ver el progreso y no esperar dentro de la aplicacion.

Uso:  uv run python scripts/descargar_modelo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipstudio import config  # noqa: E402  (ajusta variables de entorno antes de importar el resto)


def main() -> int:
    from faster_whisper.utils import download_model

    config.ensure_dirs()
    print(f"Descargando el modelo '{config.WHISPER_MODEL}' en {config.MODELS_DIR} ...")
    ruta = download_model(config.WHISPER_MODEL, cache_dir=str(config.MODELS_DIR))
    print("Modelo listo en:", ruta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
