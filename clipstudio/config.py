"""Configuracion leida de variables de entorno (y de un archivo .env opcional)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT))


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Descarga del modelo por HTTPS normal: el transporte "xet" de Hugging Face se queda
# colgado en algunas redes. Tambien se silencia un aviso de enlaces simbolicos de Windows.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ClipStudio"
    return Path.home() / ".clipstudio"


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


DATA_DIR = Path(os.environ.get("CLIPSTUDIO_DATA_DIR") or _default_data_dir()).resolve()
PROJECTS_DIR = DATA_DIR / "proyectos"
MODELS_DIR = Path(os.environ.get("CLIPSTUDIO_MODELS_DIR") or DATA_DIR / "modelos").resolve()
FONDOS_DIR = Path(os.environ.get("CLIPSTUDIO_FONDOS_DIR") or DATA_DIR / "fondos").resolve()
BIN_DIR = DATA_DIR / "bin"
VIVO_DIR = DATA_DIR / "vivo"            # buferes temporales del modo en vivo (uno por sesion)
DB_PATH = DATA_DIR / "clipstudio.db"

HOST = os.environ.get("CLIPSTUDIO_HOST", "127.0.0.1")
PORT = int(_float("CLIPSTUDIO_PORT", 8765))

WHISPER_MODEL = os.environ.get("CLIPSTUDIO_WHISPER_MODEL", "small")
WHISPER_COMPUTE = os.environ.get("CLIPSTUDIO_WHISPER_COMPUTE", "int8")
WHISPER_DEVICE = os.environ.get("CLIPSTUDIO_WHISPER_DEVICE", "cpu")

MAX_UPLOAD_BYTES = int(_float("CLIPSTUDIO_MAX_UPLOAD_GB", 8) * 1024**3)
MAX_DURATION_S = _float("CLIPSTUDIO_MAX_DURATION_MIN", 720) * 60

# Minutos de directo que se conservan en disco mientras se graba (modo en vivo).
VIVO_BUFER_MIN = max(1.0, _float("CLIPSTUDIO_VIVO_BUFER_MIN", 60))

YOUTUBE_API_KEY = os.environ.get("CLIPSTUDIO_YOUTUBE_API_KEY", "").strip()
YTDLP_COOKIES_BROWSER = os.environ.get("CLIPSTUDIO_YTDLP_COOKIES_BROWSER", "").strip()

# Buscar actualizaciones al iniciar (consulta a api.github.com como mucho cada 6 h). 0 = desactivado.
BUSCAR_ACTUALIZACIONES = os.environ.get("CLIPSTUDIO_BUSCAR_ACTUALIZACIONES", "1").strip().lower() not in ("0", "false", "no", "off")

OUT_W, OUT_H = 1080, 1920


def ensure_dirs() -> None:
    for d in (DATA_DIR, PROJECTS_DIR, MODELS_DIR, FONDOS_DIR, BIN_DIR):
        d.mkdir(parents=True, exist_ok=True)


_bloqueo = None


def bloquear_instancia() -> bool:
    """Impide dos ClipStudio sobre la misma carpeta de datos (se pisarian los trabajos).

    Devuelve False si otra instancia ya tiene el bloqueo. El bloqueo dura lo que el proceso.
    """
    global _bloqueo
    ensure_dirs()
    archivo = open(DATA_DIR / "clipstudio.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt

            archivo.seek(0)
            msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        archivo.close()
        return False
    _bloqueo = archivo
    return True


def find_tool(name: str) -> str | None:
    """Busca ffmpeg/ffprobe: carpeta configurada, carpeta de datos y luego el PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    candidates = []
    custom = os.environ.get("CLIPSTUDIO_FFMPEG_DIR")
    if custom:
        candidates.append(Path(custom) / exe)
    candidates.append(BIN_DIR / exe)
    candidates.append(BUNDLE_DIR / "bin" / exe)
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which(name)
