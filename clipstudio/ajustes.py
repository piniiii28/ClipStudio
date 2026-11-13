"""Carpetas configurables (pantalla «Ajustes»): exportaciones, búfer en vivo y fondos.

Las rutas elegidas se guardan en las preferencias (base de datos) y se mantienen en memoria
para que el resto de módulos las consulten sin tocar la base. Proyectos, transcripciones y
modelos siguen siempre en la carpeta de datos de la aplicación.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import config, db

log = logging.getLogger("clipstudio")

CLAVES = ("exportaciones", "vivo", "fondos")
SUBCARPETA_BUFER = "ClipStudio-bufer"   # el búfer elegido vive en una subcarpeta propia: nunca se borra nada ajeno
RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

_elegidas: dict[str, str] = {}


# ---------- estado en memoria ----------

def cargar() -> None:
    """Lee de las preferencias las carpetas elegidas (al arrancar)."""
    guardado = db.leer_preferencia("carpetas", {})
    _elegidas.clear()
    if isinstance(guardado, dict):
        for clave in CLAVES:
            valor = guardado.get(clave)
            if isinstance(valor, str) and valor.strip():
                _elegidas[clave] = valor


def _guardar() -> None:
    db.guardar_preferencia("carpetas", dict(_elegidas))


def elegida(clave: str) -> Path | None:
    valor = _elegidas.get(clave)
    return Path(valor) if valor else None


def carpeta_exportaciones() -> Path | None:
    """Carpeta donde se copia cada MP4 terminado, si la persona eligió una."""
    return elegida("exportaciones")


def carpeta_fondos() -> Path:
    return elegida("fondos") or config.FONDOS_DIR


def carpeta_vivo() -> Path:
    """Carpeta que contiene las carpetas temporales de cada sesión en vivo."""
    base = elegida("vivo")
    return base / SUBCARPETA_BUFER if base else config.VIVO_DIR


def predeterminada(clave: str) -> Path:
    return {"exportaciones": config.DATA_DIR / "proyectos" / "<proyecto>" / "exportaciones",
            "vivo": config.VIVO_DIR, "fondos": config.FONDOS_DIR}[clave]


# ---------- validación ----------

def _dentro(ruta: Path, base: Path) -> bool:
    try:
        ruta.relative_to(base)
        return True
    except ValueError:
        return False


def carpetas_de_la_aplicacion() -> list[Path]:
    """Carpetas que no se aceptan como destino: la aplicación instalada y las de Windows."""
    candidatas = [config.ROOT, config.BUNDLE_DIR]
    for variable in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            candidatas.append(Path(os.environ[variable]))
    return [Path(os.path.normcase(os.path.abspath(c))) for c in candidatas]


def _probar_escritura(carpeta: Path) -> None:
    prueba = carpeta / f".clipstudio-prueba-{uuid.uuid4().hex[:8]}"
    with open(prueba, "xb") as f:
        f.write(b"ok")
    prueba.unlink(missing_ok=True)


def validar_carpeta(ruta: str, crear: bool = True) -> Path:
    """Devuelve la ruta normalizada o lanza ValueError con un mensaje en español."""
    texto = (ruta or "").strip().strip('"').strip()
    if not texto:
        raise ValueError("Escribe o elige una carpeta.")
    if len(texto) > 400 or "\0" in texto:
        raise ValueError("La ruta no es válida.")
    candidata = Path(os.path.expandvars(os.path.expanduser(texto)))
    if not candidata.is_absolute():
        raise ValueError("Escribe la ruta completa de la carpeta (por ejemplo D:\\Videos\\ClipStudio).")
    candidata = Path(os.path.abspath(candidata))
    if candidata == Path(candidata.anchor):
        raise ValueError("No uses la raíz de un disco: elige o crea una carpeta dentro de él.")
    normal = Path(os.path.normcase(candidata))
    if not _dentro(normal, Path(os.path.normcase(config.DATA_DIR))):
        for app in carpetas_de_la_aplicacion():
            if _dentro(normal, app):
                raise ValueError("No uses una carpeta de la aplicación ni del sistema: se perdería al actualizarla. Elige otra.")
    if candidata.exists() and not candidata.is_dir():
        raise ValueError("Esa ruta es un archivo, no una carpeta.")
    if not candidata.exists():
        if not crear:
            raise ValueError("La carpeta no existe.")
        try:
            candidata.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"No se pudo crear la carpeta: {exc.strerror or exc}.") from exc
    try:
        _probar_escritura(candidata)
    except OSError as exc:
        raise ValueError(f"No se puede escribir en esa carpeta ({exc.strerror or exc}). Elige otra o revisa los permisos.") from exc
    return candidata


def libre_gb(ruta: Path) -> float | None:
    """Espacio libre del disco que contiene `ruta` (o de su primer ancestro existente)."""
    actual = ruta
    while not actual.exists() and actual != actual.parent:
        actual = actual.parent
    try:
        return round(shutil.disk_usage(actual).free / 1024**3, 1)
    except OSError:
        return None


# ---------- copia de las exportaciones ----------

def nombre_legible(titulo: str, id_corto: str) -> str:
    """`<título saneado>_<id corto>.mp4`: sin caracteres prohibidos en Windows ni nombres reservados."""
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", titulo or "")
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")[:80].strip(" .")
    if not limpio or limpio.upper() in RESERVADOS:
        limpio = "clip"
    corto = re.sub(r"[^0-9A-Za-z]", "", id_corto or "")[:8] or "x"
    return f"{limpio}_{corto}.mp4"


def copiar_exportacion(origen: Path, titulo: str, id_corto: str, destino: Path | None = None) -> Path | None:
    """Copia un MP4 terminado a la carpeta elegida. Nunca pisa archivos: añade « (2)», « (3)»…

    Devuelve la ruta de la copia, o None si no hay carpeta elegida. Lanza OSError si falla.
    """
    destino = destino if destino is not None else carpeta_exportaciones()
    if destino is None:
        return None
    destino.mkdir(parents=True, exist_ok=True)
    nombre = Path(nombre_legible(titulo, id_corto))
    temporal = destino / f".{uuid.uuid4().hex[:8]}.copiando"
    try:
        shutil.copyfile(origen, temporal)
        for n in range(1, 1000):
            final = destino / (nombre.name if n == 1 else f"{nombre.stem} ({n}){nombre.suffix}")
            try:
                os.link(temporal, final)       # falla si ya existe: no se pisa nada, ni con dos copias a la vez
            except FileExistsError:
                continue
            except OSError:
                # Sistemas de archivos sin enlaces duros: se comprueba y se renombra.
                if final.exists():
                    continue
                os.rename(temporal, final)
                return final
            return final
        raise OSError("Hay demasiados archivos con ese nombre en la carpeta de exportaciones.")
    finally:
        temporal.unlink(missing_ok=True)


# ---------- API ----------

router = APIRouter(prefix="/api/ajustes")

ETIQUETAS = {"exportaciones": "Carpeta de exportaciones", "vivo": "Carpeta del búfer en vivo", "fondos": "Carpeta de fondos"}


def _ficha(clave: str) -> dict:
    elegida_ = elegida(clave)
    efectiva = {"exportaciones": elegida_, "vivo": carpeta_vivo(), "fondos": carpeta_fondos()}[clave]
    if clave == "exportaciones" and efectiva is None:
        efectiva = config.PROJECTS_DIR
    return {
        "clave": clave,
        "etiqueta": ETIQUETAS[clave],
        "ruta": str(efectiva),
        "personalizada": elegida_ is not None,
        "predeterminada": str(predeterminada(clave)),
        "existe": efectiva.is_dir(),
        "libre_gb": libre_gb(efectiva),
    }


def _listado() -> dict:
    return {
        "carpetas": [_ficha(c) for c in CLAVES],
        "datos": {"ruta": str(config.DATA_DIR), "libre_gb": libre_gb(config.DATA_DIR)},
    }


@router.get("")
def ver() -> dict:
    return _listado()


class CarpetaNueva(BaseModel):
    ruta: str = Field(max_length=500)


def _clave(clave: str) -> str:
    if clave not in CLAVES:
        raise HTTPException(404, "Esa carpeta no existe.")
    return clave


def _aviso(clave: str) -> str | None:
    if clave != "vivo":
        return None
    from . import vivo

    s = vivo.sesion_actual()
    if s is not None and s.estado in ("conectando", "grabando"):
        return "Hay una grabación en curso: la nueva carpeta del búfer se usará al volver a conectar."
    return None


@router.put("/carpetas/{clave}")
def elegir(clave: str, datos: CarpetaNueva) -> dict:
    _clave(clave)
    try:
        ruta = validar_carpeta(datos.ruta)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _elegidas[clave] = str(ruta)
    _guardar()
    return {**_listado(), "aviso": _aviso(clave)}


@router.delete("/carpetas/{clave}")
def restablecer(clave: str) -> dict:
    _clave(clave)
    _elegidas.pop(clave, None)
    _guardar()
    return {**_listado(), "aviso": _aviso(clave)}


@router.post("/abrir/{clave}")
def abrir(clave: str) -> dict:
    """Abre en el Explorador una de las carpetas conocidas (nunca una ruta que llegue en la petición)."""
    if clave == "datos":
        carpeta = config.DATA_DIR
    else:
        carpeta = Path(_ficha(_clave(clave))["ruta"])
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(409, f"No se pudo abrir la carpeta: {exc.strerror or exc}.") from exc
    if hasattr(os, "startfile"):
        os.startfile(carpeta)  # type: ignore[attr-defined]
    return {"carpeta": str(carpeta)}
