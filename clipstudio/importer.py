"""Importacion de videos por URL con yt-dlp (YouTube y otras plataformas compatibles)."""

from __future__ import annotations

import ipaddress
import re
import shutil
import socket
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import config
from .media import Cancelacion, Cancelado, ErrorMedia, herramienta


def validar_url(url: str) -> str:
    """Solo http(s) hacia hosts publicos. Lanza ValueError con mensaje en espanol."""
    url = (url or "").strip()
    if len(url) > 2000:
        raise ValueError("La URL es demasiado larga.")
    partes = urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise ValueError("Escribe una URL completa que empiece por http:// o https://")
    host = partes.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("No se permiten direcciones locales.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url
    if not ip.is_global:
        raise ValueError("No se permiten direcciones locales o privadas.")
    return url


def comprobar_destino_publico(url: str) -> None:
    """Resuelve el nombre y rechaza destinos locales o privados.

    Es una defensa razonable para una app local, no una garantia: no cubre redirecciones
    posteriores ni cambios de DNS entre esta comprobacion y la descarga.
    """
    host = urlparse(url).hostname or ""
    try:
        direcciones = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError as exc:
        raise ErrorMedia("No se pudo resolver la direccion. Revisa el enlace y tu conexion a internet.") from exc
    for d in direcciones:
        if not ipaddress.ip_address(d.split("%")[0]).is_global:
            raise ErrorMedia("El enlace apunta a una direccion local o privada, y no se permite.")


def _opciones(destino: Path, hook=None) -> dict:
    opciones: dict = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(destino / "fuente.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 3,
        "ffmpeg_location": str(Path(herramienta("ffmpeg")).parent),
        "max_filesize": config.MAX_UPLOAD_BYTES,
        "overwrites": True,
    }
    if node := config.find_tool("node"):
        # YouTube necesita un motor de JavaScript para resolver los formatos.
        opciones["js_runtimes"] = {"node": {"path": node}}
    if config.YTDLP_COOKIES_BROWSER:
        opciones["cookiesfrombrowser"] = (config.YTDLP_COOKIES_BROWSER,)
    if hook:
        opciones["progress_hooks"] = [hook]
    return opciones


def _mensaje(exc: Exception) -> str:
    texto = str(exc).replace("ERROR: ", "").strip()
    bajo = texto.lower()
    if "unsupported url" in bajo:
        return "Esa pagina no es compatible o no contiene un video que se pueda descargar."
    if "private" in bajo or "sign in" in bajo or "login" in bajo or "cookies" in bajo:
        return (
            "El video es privado o la plataforma exige iniciar sesion. Prueba con un video publico "
            "o configura CLIPSTUDIO_YTDLP_COOKIES_BROWSER en el archivo .env."
        )
    if "unavailable" in bajo or "not available" in bajo or "removed" in bajo:
        return "El video no esta disponible (eliminado, bloqueado en tu region o restringido)."
    if "live" in bajo:
        return "No se pueden importar transmisiones en vivo."
    if "timed out" in bajo or "getaddrinfo" in bajo or "connection" in bajo:
        return "No se pudo conectar con la plataforma. Revisa tu conexion a internet."
    return f"No se pudo descargar el video: {texto[:300]}"


def formato_audio(idioma: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,35}", idioma):
        raise ValueError("Idioma de audio no válido.")
    return f'bv[height<=1080]+ba[language="{idioma}"]/b[height<=1080][language="{idioma}"]'


def idiomas_audio(url: str) -> list[str]:
    import yt_dlp

    comprobar_destino_publico(url)
    opciones = {**_opciones(Path(".")), "ignore_no_formats_error": True}
    opciones.pop("format")
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise ErrorMedia(_mensaje(exc)) from exc
    return sorted({
        f["language"] for f in (info.get("formats") or [])
        if f.get("acodec") not in (None, "none")
        and re.fullmatch(r"[a-zA-Z0-9-]{1,35}", f.get("language") or "")
    })


def descargar(
    url: str,
    destino: Path,
    cancel: Cancelacion,
    progreso: Callable[[float], None],
    audio_idioma: str | None = None,
) -> tuple[Path, str]:
    """Descarga el video a `destino`. Devuelve (ruta del archivo, titulo)."""
    import yt_dlp

    fallo: list[Exception] = []  # yt-dlp puede envolver lo que lanza un hook: se guarda aparte
    terminados = 0
    limite_gb = config.MAX_UPLOAD_BYTES / 1024**3

    def hook(d: dict) -> None:
        nonlocal terminados
        if cancel.activa:
            fallo.append(Cancelado())
            raise fallo[-1]
        estado = d.get("status")
        if estado not in ("downloading", "finished"):
            return
        # Una pista ya descargada en un intento anterior llega como "finished" solo con total_bytes.
        bajado = d.get("downloaded_bytes") or (d.get("total_bytes") or 0 if estado == "finished" else 0)
        acumulado = terminados + bajado
        if estado == "finished":
            terminados = acumulado
        # Limite real por bytes recibidos (video y audio se descargan por separado).
        if acumulado > config.MAX_UPLOAD_BYTES:
            fallo.append(ErrorMedia(f"El video supera el limite de {limite_gb:.0f} GB (CLIPSTUDIO_MAX_UPLOAD_GB)."))
            raise fallo[-1]
        if shutil.disk_usage(destino).free < 1024**3:
            fallo.append(ErrorMedia("Se esta agotando el espacio en el disco de datos. Se detuvo la descarga."))
            raise fallo[-1]
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total and estado == "downloading":
            progreso(min(1.0, bajado / total))

    comprobar_destino_publico(url)
    cancel.comprobar()
    try:
        with yt_dlp.YoutubeDL(_opciones(destino)) as ydl:
            info = ydl.extract_info(url, download=False)
        cancel.comprobar()
        if info.get("_type") == "playlist":
            raise ErrorMedia("La URL es una lista de reproduccion. Pega el enlace de un solo video.")
        if info.get("is_live"):
            raise ErrorMedia("No se pueden importar transmisiones en vivo.")
        duracion = info.get("duration") or 0
        if duracion and duracion > config.MAX_DURATION_S:
            raise ErrorMedia(
                f"El video dura {duracion / 60:.0f} min y el limite es {config.MAX_DURATION_S / 60:.0f} min "
                "(CLIPSTUDIO_MAX_DURATION_MIN)."
            )
        estimado = info.get("filesize") or info.get("filesize_approx") or 0
        if estimado and shutil.disk_usage(destino).free < estimado * 3:
            raise ErrorMedia("No hay espacio suficiente en el disco de datos para descargar y procesar este video.")
        titulo = str(info.get("title") or "Video importado")[:120]
        opciones = _opciones(destino, hook)
        if audio_idioma:
            opciones["format"] = formato_audio(audio_idioma)
        with yt_dlp.YoutubeDL(opciones) as ydl:
            ydl.extract_info(url, download=True)
    except (Cancelado, ErrorMedia):
        raise
    except Exception as exc:
        if fallo:
            raise fallo[-1] from exc
        if cancel.activa:
            raise Cancelado() from exc
        if audio_idioma and "requested format is not available" in str(exc).lower():
            raise ErrorMedia(f"La pista de audio {audio_idioma} ya no está disponible. Prueba otra pista.") from exc
        raise ErrorMedia(_mensaje(exc)) from exc

    cancel.comprobar()
    archivos = [
        p for p in destino.glob("fuente.*")
        if p.is_file() and p.suffix.lower() not in (".part", ".ytdl", ".tmp")
    ]
    if not archivos:
        raise ErrorMedia("La descarga termino pero no se encontro el archivo de video.")
    return max(archivos, key=lambda p: p.stat().st_size), titulo
