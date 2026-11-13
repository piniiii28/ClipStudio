"""Fondos de juego alojados en YouTube para el encuadre "dividido".

No se descargan enteros: al exportar solo se baja el tramo (solo video, hasta 1080p) que
cubre la duracion del clip, con yt-dlp y su descarga por secciones. Los tramos bajados se
guardan en una cache con limite de tamano para no repetir la descarga.

En el estilo del clip un fondo remoto se identifica como `yt:<id>` (ver `subtitles`).
La lista de fondos son los dos de serie (que se pueden ocultar pero no borrar) mas los que
la persona anade pegando un enlace de YouTube; se guarda en la preferencia "fondos_remotos".
"""

from __future__ import annotations

import logging
import os
import random
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import config, db, importer
from .media import Cancelacion, Cancelado, ErrorMedia, herramienta, sondear
from .subtitles import PREFIJO_FONDO_REMOTO, es_id_remoto

log = logging.getLogger("clipstudio")

HOSTS_YOUTUBE = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
MAX_ANADIDOS = 30
MARGEN_FINAL_S = 5.0            # el inicio al azar deja al menos esto libre al final del fondo
EXTRA_DESCARGA_S = 20.0         # se baja el clip + esto, para tener algo de margen y variedad
MIN_DURACION_FONDO_S = 30.0     # un fondo mas corto que esto no tiene sentido
LIMITE_CACHE_BYTES = 1024**3    # 1 GB
CACHE_DIR = config.DATA_DIR / "cache_fondos"

# Fondos incluidos en el codigo. La licencia es la que declara cada autor.
SERIE: list[dict] = [
    {
        "id": "eBExtYRpuqI",
        "titulo": "Minecraft parkour",
        "canal": "perpexior",
        "url": "https://www.youtube.com/watch?v=eBExtYRpuqI",
        "duracion": 3487,
        "licencia": "El autor lo declara «No Copyright / Royalty Free / Free to use»",
        "credito": "Fondo: perpexior (YouTube)",
    },
    {
        "id": "HeQQwg_N0Yg",
        "titulo": "Subway Surfers",
        "canal": "OrbitalNCG +",
        "url": "https://www.youtube.com/watch?v=HeQQwg_N0Yg",
        "duracion": 4570,
        "licencia": "Licencia de YouTube Creative Commons con atribución",
        "credito": "Fondo: OrbitalNCG + (YouTube)",
    },
]
_IDS_SERIE = {f["id"] for f in SERIE}
_candado = threading.RLock()


# ---------- ids y URLs ----------

def id_valido(valor: object) -> bool:
    """Un id de video de YouTube: 11 caracteres de [A-Za-z0-9_-]."""
    return es_id_remoto(valor)


def extraer_id(url: str) -> str:
    """Id del video de una URL de YouTube (watch?v=, youtu.be/, /shorts/, /embed/, /live/).

    Rechaza otros dominios, esquemas que no sean http(s), listas de reproduccion y enlaces
    sin un video concreto. Lanza ValueError con un mensaje en espanol.
    """
    url = importer.validar_url(url)          # http(s), sin hosts locales ni IP privadas
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    if host not in HOSTS_YOUTUBE:
        raise ValueError("Solo se admiten enlaces de YouTube (youtube.com o youtu.be).")
    ruta = [p for p in partes.path.split("/") if p]
    consulta = parse_qs(partes.query)
    if host == "youtu.be":
        candidato = ruta[0] if ruta else ""
    elif ruta and ruta[0] == "watch":
        candidato = (consulta.get("v") or [""])[0]
    elif len(ruta) >= 2 and ruta[0] in ("shorts", "embed", "live"):
        candidato = ruta[1]
    elif ruta and ruta[0] in ("playlist", "channel", "c", "user", "feed", "results"):
        raise ValueError("Ese enlace es una lista o un canal. Pega el enlace de un solo video.")
    else:
        candidato = ""
    if not id_valido(candidato):
        raise ValueError("No se reconoce un video de YouTube en ese enlace. Pega el enlace de un solo video.")
    return candidato


def url_canonica(id_: str) -> str:
    return f"https://www.youtube.com/watch?v={id_}"


# ---------- catalogo ----------

def _estado() -> dict:
    datos = db.leer_preferencia("fondos_remotos", {}) or {}
    anadidos = [f for f in datos.get("anadidos", []) if isinstance(f, dict) and id_valido(f.get("id"))]
    ocultos = [i for i in datos.get("ocultos", []) if id_valido(i)]
    return {"anadidos": anadidos, "ocultos": ocultos}


def _guardar(estado: dict) -> None:
    db.guardar_preferencia("fondos_remotos", estado)


def _publico(f: dict, de_serie: bool, oculto: bool) -> dict:
    return {
        "id": f["id"],
        "valor": PREFIJO_FONDO_REMOTO + f["id"],
        "titulo": str(f.get("titulo") or f["id"]),
        "canal": str(f.get("canal") or ""),
        "url": url_canonica(f["id"]),
        "duracion": float(f.get("duracion") or 0),
        "licencia": str(f.get("licencia") or ""),
        "credito": str(f.get("credito") or ""),
        "de_serie": de_serie,
        "oculto": oculto,
    }


def catalogo(incluir_ocultos: bool = False) -> list[dict]:
    """Fondos remotos (de serie y anadidos), con `oculto` marcado."""
    with _candado:
        estado = _estado()
    ocultos = set(estado["ocultos"])
    lista = [_publico(f, True, f["id"] in ocultos) for f in SERIE]
    lista += [_publico(f, False, False) for f in estado["anadidos"] if f["id"] not in _IDS_SERIE]
    return lista if incluir_ocultos else [f for f in lista if not f["oculto"]]


def visibles() -> list[dict]:
    return catalogo(False)


def buscar(id_: str) -> dict | None:
    """Un fondo conocido por su id (aunque este oculto: un clip ya guardado puede usarlo)."""
    return next((f for f in catalogo(True) if f["id"] == id_), None)


def credito_de(valor: str) -> str:
    """Texto de credito de un fondo del estilo (`yt:<id>`); "" si no es remoto o no hay."""
    if not valor.startswith(PREFIJO_FONDO_REMOTO):
        return ""
    f = buscar(valor[len(PREFIJO_FONDO_REMOTO):])
    return f["credito"] if f else ""


def _limpio(texto: object, largo: int) -> str:
    return " ".join(str(texto or "").split())[:largo]


def consultar(id_: str) -> dict:
    """Pide a YouTube los datos del video SIN descargarlo. Lanza ErrorMedia si no sirve."""
    import yt_dlp

    opciones = importer._opciones(Path("."))
    opciones.pop("outtmpl", None)
    opciones["socket_timeout"] = 20
    importer.comprobar_destino_publico(url_canonica(id_))
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url_canonica(id_), download=False)
    except Exception as exc:
        raise ErrorMedia(_mensaje_descarga(exc)) from exc
    if not isinstance(info, dict) or info.get("_type") == "playlist":
        raise ErrorMedia("El enlace es una lista de reproducción. Pega el enlace de un solo video.")
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise ErrorMedia("No se pueden usar transmisiones en vivo como fondo.")
    duracion = float(info.get("duration") or 0)
    if duracion < MIN_DURACION_FONDO_S:
        raise ErrorMedia(f"El video dura {duracion:.0f} s: para un fondo hace falta que dure al menos {MIN_DURACION_FONDO_S:.0f} s.")
    canal = _limpio(info.get("channel") or info.get("uploader"), 80) or "YouTube"
    return {
        "id": id_,
        "titulo": _limpio(info.get("title"), 120) or id_,
        "canal": canal,
        "duracion": round(duracion, 1),
        "licencia": _limpio(info.get("license"), 120) or "Licencia estándar de YouTube",
        "credito": f"Fondo: {canal} (YouTube)",
    }


def anadir(url: str) -> dict:
    """Valida el enlace, consulta el video y lo guarda. Devuelve el fondo (con `valor`)."""
    id_ = extraer_id(url)
    with _candado:
        estado = _estado()
        if id_ in _IDS_SERIE:                 # volver a pegar uno de serie lo vuelve a mostrar
            estado["ocultos"] = [i for i in estado["ocultos"] if i != id_]
            _guardar(estado)
            return buscar(id_)  # type: ignore[return-value]
        if any(f["id"] == id_ for f in estado["anadidos"]):
            return buscar(id_)  # type: ignore[return-value]
        if len(estado["anadidos"]) >= MAX_ANADIDOS:
            raise ValueError(f"Ya hay {MAX_ANADIDOS} fondos añadidos. Quita alguno antes de añadir otro.")
    datos = consultar(id_)                    # red: fuera del candado
    with _candado:
        estado = _estado()
        if not any(f["id"] == id_ for f in estado["anadidos"]):
            estado["anadidos"].append(datos)
            _guardar(estado)
    return buscar(id_)  # type: ignore[return-value]


def quitar(id_: str) -> str:
    """Quita un fondo anadido o oculta uno de serie. Devuelve 'quitado' | 'oculto' | 'ninguno'."""
    with _candado:
        estado = _estado()
        if id_ in _IDS_SERIE:
            if id_ not in estado["ocultos"]:
                estado["ocultos"].append(id_)
                _guardar(estado)
            return "oculto"
        antes = len(estado["anadidos"])
        estado["anadidos"] = [f for f in estado["anadidos"] if f["id"] != id_]
        if len(estado["anadidos"]) == antes:
            return "ninguno"
        _guardar(estado)
        return "quitado"


# ---------- tramo al azar ----------

def elegir_inicio(duracion_fondo: float, duracion_clip: float, azar: random.Random | None = None) -> float:
    """Inicio al azar en [0, duracion_fondo - duracion_clip - 5]; 0 si el clip no cabe."""
    tope = float(duracion_fondo) - float(duracion_clip) - MARGEN_FINAL_S
    if tope <= 0:
        return 0.0
    return (azar or random).uniform(0.0, tope)


def tramo_a_bajar(duracion_fondo: float, duracion_clip: float, inicio: float) -> tuple[float, float]:
    """(inicio, fin) a descargar: el clip mas un margen, sin pasar del final del fondo."""
    fin = min(float(duracion_fondo), inicio + float(duracion_clip) + EXTRA_DESCARGA_S)
    return round(inicio, 2), round(max(fin, inicio + 1.0), 2)


# ---------- cache de tramos ----------

_NOMBRE_CACHE = re.compile(r"^(?P<id>[A-Za-z0-9_-]{11})_(?P<inicio>\d+)_(?P<largo>\d+)\.mp4$")


def nombre_cache(id_: str, inicio: float, largo: float) -> str:
    return f"{id_}_{int(inicio)}_{int(largo)}.mp4"


def buscar_en_cache(id_: str, duracion_clip: float, carpeta: Path | None = None) -> tuple[Path, float] | None:
    """Un tramo ya bajado de ese video que sea lo bastante largo. Devuelve (ruta, duracion del tramo)."""
    carpeta = carpeta or CACHE_DIR
    if not carpeta.is_dir():
        return None
    candidatos = []
    for f in carpeta.glob(f"{id_}_*.mp4"):
        m = _NOMBRE_CACHE.match(f.name)
        if m and f.is_file() and f.stat().st_size > 0 and int(m["largo"]) >= duracion_clip + 10:
            candidatos.append((f, float(m["largo"])))
    return random.choice(candidatos) if candidatos else None


def podar_cache(carpeta: Path | None = None, limite: int | None = None, conservar: Path | None = None) -> list[Path]:
    """Borra los tramos usados hace mas tiempo hasta que la cache cabe en `limite` bytes.

    Nunca borra `conservar` (el que se acaba de guardar o se va a usar). Devuelve lo borrado.
    """
    carpeta = carpeta or CACHE_DIR
    limite = LIMITE_CACHE_BYTES if limite is None else limite
    if not carpeta.is_dir():
        return []
    archivos = [f for f in carpeta.iterdir() if f.is_file() and f.suffix == ".mp4"]
    for resto in carpeta.glob("*.tmp"):
        try:
            if time.time() - resto.stat().st_mtime > 3600:
                resto.unlink()
        except OSError:
            pass
    total = sum(f.stat().st_size for f in archivos)
    borrados: list[Path] = []
    for f in sorted(archivos, key=lambda x: x.stat().st_mtime):
        if total <= limite:
            break
        if conservar is not None and f == conservar:
            continue
        try:
            tamano = f.stat().st_size
            f.unlink()
        except OSError:
            continue
        total -= tamano
        borrados.append(f)
    return borrados


# ---------- descarga del tramo ----------

def _mensaje_descarga(exc: BaseException) -> str:
    bajo = str(exc).lower()
    if any(x in bajo for x in ("getaddrinfo", "timed out", "timeout", "connection", "network is unreachable",
                               "name or service", "temporary failure", "no route", "urlopen error", "resolve")):
        return "Sin conexión: no se pudo descargar el fondo de YouTube. Revisa tu conexión a internet e inténtalo de nuevo."
    if any(x in bajo for x in ("private", "removed", "deleted", "no longer available", "does not exist",
                               "video unavailable", "been terminated", "not available")):
        return "El video de fondo ya no está disponible en YouTube (eliminado, privado o bloqueado en tu región). Elige otro fondo."
    if any(x in bajo for x in ("sign in", "confirm you", "bot", "403", "429", "too many requests", "forbidden")):
        return ("YouTube está bloqueando la descarga del fondo (pide comprobar que no eres un robot o limita las "
                "peticiones). Espera unos minutos, elige otro fondo o configura CLIPSTUDIO_YTDLP_COOKIES_BROWSER en el archivo .env.")
    return f"No se pudo descargar el fondo de YouTube: {importer._mensaje(exc)}"[:400]


def _ffmpeg_en_el_path() -> None:
    """yt-dlp comprueba "hay ffmpeg" solo en el PATH (ignora ffmpeg_location) antes de bajar un tramo."""
    carpeta = str(Path(herramienta("ffmpeg")).parent)
    partes = os.environ.get("PATH", "").split(os.pathsep)
    if carpeta not in partes:
        os.environ["PATH"] = os.pathsep.join([carpeta, *partes])


def _opciones_tramo(destino: Path, inicio: float, fin: float, hook) -> dict:
    from yt_dlp.utils import download_range_func

    _ffmpeg_en_el_path()

    opciones = importer._opciones(destino, hook)
    opciones.update({
        # Solo video (sin audio), hasta 1080p; mejor H.264 por compatibilidad con la vista previa y FFmpeg.
        "format": "bv[height<=1080][vcodec^=avc1]/bv[height<=1080]/bv/b[height<=1080]/b",
        "outtmpl": str(destino / "fondo.%(ext)s"),
        "download_ranges": download_range_func(None, [(inicio, fin)]),
        "force_keyframes_at_cuts": True,
        "concurrent_fragment_downloads": 4,
        "merge_output_format": "mp4",
        "max_filesize": 1024**3,
    })
    return opciones


def descargar_tramo(id_: str, inicio: float, fin: float, destino: Path, cancel: Cancelacion,
                    progreso: Callable[[float], None] | None = None) -> Path:
    """Descarga solo [inicio, fin] (s) del video, sin audio, a `destino`. Devuelve el archivo.

    Se ejecuta en un hilo para poder responder a la cancelacion sin esperar a yt-dlp.
    """
    import yt_dlp

    destino.mkdir(parents=True, exist_ok=True)
    abortar = threading.Event()
    resultado: dict = {}

    def hook(d: dict) -> None:
        if abortar.is_set():
            raise Cancelado()
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if progreso and total and d.get("status") == "downloading":
            progreso(min(1.0, (d.get("downloaded_bytes") or 0) / total))

    def trabajo() -> None:
        try:
            with yt_dlp.YoutubeDL(_opciones_tramo(destino, inicio, fin, hook)) as ydl:
                ydl.extract_info(url_canonica(id_), download=True)
        except BaseException as exc:  # noqa: BLE001 - se re-lanza en el hilo que espera
            resultado["error"] = exc

    importer.comprobar_destino_publico(url_canonica(id_))
    cancel.comprobar()
    hilo = threading.Thread(target=trabajo, daemon=True, name=f"fondo-{id_}")
    hilo.start()
    while hilo.is_alive():
        hilo.join(0.3)
        if cancel.activa:
            abortar.set()
            raise Cancelado()
    if "error" in resultado:
        if cancel.activa or isinstance(resultado["error"], Cancelado):
            raise Cancelado()
        raise ErrorMedia(_mensaje_descarga(resultado["error"])) from resultado["error"]
    archivos = [p for p in destino.glob("fondo.*")
                if p.is_file() and p.suffix.lower() not in (".part", ".ytdl", ".tmp") and p.stat().st_size > 0]
    if not archivos:
        raise ErrorMedia("La descarga del fondo terminó pero no se encontró el archivo de video.")
    return max(archivos, key=lambda p: p.stat().st_size)


def obtener_tramo(fondo: dict, duracion_clip: float, trabajo: Path, cancel: Cancelacion,
                  progreso: Callable[[float], None] | None = None) -> tuple[Path, float]:
    """Archivo de video del fondo remoto listo para FFmpeg y el segundo donde empezar a usarlo.

    Usa la cache si ya hay un tramo suficiente; si no, descarga uno nuevo con inicio al azar
    (a `trabajo`, que el llamador borra) y lo guarda en la cache.
    """
    id_ = fondo["id"]
    cache = buscar_en_cache(id_, duracion_clip)
    if cache:
        ruta, largo = cache
        try:
            os.utime(ruta)                                    # "usado ahora": la poda borra los mas viejos
            return ruta, random.uniform(0.0, max(0.0, largo - duracion_clip - 1.0))
        except OSError:
            pass
    inicio = elegir_inicio(fondo["duracion"], duracion_clip)
    desde, hasta = tramo_a_bajar(fondo["duracion"], duracion_clip, inicio)
    bajado = descargar_tramo(id_, desde, hasta, trabajo / "fondo_remoto", cancel, progreso)
    cancel.comprobar()
    info = sondear(bajado)               # valida que sea un video legible
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        final = CACHE_DIR / nombre_cache(id_, desde, info["duracion"])
        temporal = final.with_suffix(".tmp")
        shutil.copyfile(bajado, temporal)
        temporal.replace(final)
        podar_cache(conservar=final)
        return final, 0.0
    except OSError:
        log.warning("No se pudo guardar el fondo en la cache", exc_info=True)
        return bajado, 0.0


# ---------- API ----------

router = APIRouter()


class NuevoFondo(BaseModel):
    url: str = Field(max_length=2000)


def _locales() -> list[dict]:
    from . import pipeline

    return [{"nombre": f.name, "tamano_mb": round(f.stat().st_size / 1024**2, 1)} for f in pipeline.listar_fondos()]


def _carpeta_fondos() -> Path:
    from . import ajustes

    return ajustes.carpeta_fondos()


def _listado() -> dict:
    locales = _locales()
    todos = catalogo(True)
    return {
        "carpeta": str(_carpeta_fondos()),
        "locales": locales,
        "fondos": locales,               # nombre anterior de la lista de locales (compatibilidad)
        "remotos": [f for f in todos if not f["oculto"]],
        "ocultos": [f for f in todos if f["oculto"]],
    }


@router.get("/api/fondos")
def listar_fondos() -> dict:
    return _listado()


@router.post("/api/fondos/remotos", status_code=201)
def anadir_fondo(datos: NuevoFondo) -> dict:
    try:
        fondo = anadir(datos.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ErrorMedia as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"fondo": fondo, **_listado()}


@router.delete("/api/fondos/remotos/{id_}")
def quitar_fondo(id_: str) -> dict:
    if not id_valido(id_):
        raise HTTPException(404, "El fondo no existe.")
    resultado = quitar(id_)
    if resultado == "ninguno":
        raise HTTPException(404, "El fondo no existe.")
    return {"resultado": resultado, **_listado()}
