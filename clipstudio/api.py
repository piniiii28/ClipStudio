"""API HTTP local (FastAPI) y servidor de la interfaz web."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, config, db, importer, pipeline, reframe, subtitles, suggest
from .pipeline import gestor

WEB_DIR = Path(__file__).parent / "web"
EXTENSIONES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".ts", ".flv", ".wmv"}
IDIOMAS = {"auto", "es", "en", "pt", "fr", "it", "de"}
MIN_CLIP_S, MAX_CLIP_S = 1.0, 600.0
HOSTS_LOCALES = {"127.0.0.1", "localhost", "[::1]", "::1"}


@asynccontextmanager
async def _ciclo(_: FastAPI):
    db.iniciar()
    db.marcar_interrumpidos()
    pipeline.limpiar_huerfanos()
    gestor.iniciar()
    yield


app = FastAPI(title="ClipStudio", version=__version__, lifespan=_ciclo, docs_url=None, redoc_url=None)


def _host(valor: str) -> str:
    return (urlparse("//" + valor).hostname or "").lower()


@app.middleware("http")
async def proteger_origen(request: Request, call_next):
    """La API solo acepta peticiones de la propia interfaz local.

    Evita que otra pagina web abierta en el navegador dispare acciones contra
    http://127.0.0.1 (CSRF) o use DNS rebinding para leer datos.
    """
    permitidos = HOSTS_LOCALES | {config.HOST.lower()}
    if _host(request.headers.get("host", "")) not in permitidos:
        return JSONResponse({"detail": "Host no permitido."}, status_code=403)
    origen = request.headers.get("origin")
    if origen and origen != "null":
        o = urlparse(origen)
        if (o.hostname or "").lower() not in permitidos or o.port != request.url.port:
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
    elif origen == "null" and request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
    respuesta = await call_next(request)
    if request.url.path.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


# ---------- utilidades ----------

_transicion = threading.Lock()  # hace atomico "comprobar estado + encolar"

def _proyecto(pid: str) -> dict:
    p = db.obtener("proyectos", pid)
    if p is None:
        raise HTTPException(404, "El proyecto no existe.")
    return p


def _proyecto_listo(pid: str) -> dict:
    p = _proyecto(pid)
    if p["estado"] != "listo":
        raise HTTPException(409, "El proyecto todavia no termino de procesarse.")
    return p


def _clip(cid: str) -> dict:
    c = db.obtener("clips", cid)
    if c is None:
        raise HTTPException(404, "El clip no existe.")
    # Los clips guardados con una version anterior no tienen las claves de estilo nuevas.
    c["estilo"] = subtitles.normalizar_estilo(c["estilo"])
    return c


def _validar_rango(inicio: float, fin: float, duracion: float) -> tuple[float, float]:
    inicio, fin = round(max(0.0, inicio), 3), round(min(fin, duracion), 3)
    if fin - inicio < MIN_CLIP_S:
        raise HTTPException(422, f"El clip debe durar al menos {MIN_CLIP_S:.0f} segundo.")
    if fin - inicio > MAX_CLIP_S:
        raise HTTPException(422, f"El clip no puede durar mas de {MAX_CLIP_S / 60:.0f} minutos.")
    return inicio, fin


def _nombre_seguro(texto: str, respaldo: str = "clip") -> str:
    limpio = re.sub(r"[^\w\- ]+", "", texto, flags=re.UNICODE).strip().replace(" ", "_")[:60]
    return limpio or respaldo


def _detalle(pid: str) -> dict:
    p = _proyecto(pid)
    p["clips"] = db.listar("clips", "proyecto_id = ?", (pid,), "inicio ASC")
    for c in p["clips"]:
        c["estilo"] = subtitles.normalizar_estilo(c["estilo"])
    p["exportaciones"] = db.listar("exportaciones", "proyecto_id = ?", (pid,))
    for e in p["exportaciones"]:
        e.pop("parametros", None)
    p["tiene_video"] = pipeline.ruta_proxy(pid).is_file()
    return p


# ---------- estado ----------

@app.get("/api/estado")
def estado() -> dict:
    libre = shutil.disk_usage(config.DATA_DIR).free
    return {
        "version": __version__,
        "ffmpeg": bool(config.find_tool("ffmpeg") and config.find_tool("ffprobe")),
        "modelo": config.WHISPER_MODEL,
        "dispositivo": config.WHISPER_DEVICE,
        "carpeta_datos": str(config.DATA_DIR),
        "espacio_libre_gb": round(libre / 1024**3, 1),
        "max_subida_gb": round(config.MAX_UPLOAD_BYTES / 1024**3, 1),
        "extensiones": sorted(EXTENSIONES),
    }


# ---------- proyectos ----------

@app.get("/api/proyectos")
def listar_proyectos() -> list[dict]:
    proyectos = db.listar("proyectos")
    for p in proyectos:
        with db.conectar() as con:
            p["n_clips"] = con.execute("SELECT COUNT(*) FROM clips WHERE proyecto_id = ?", (p["id"],)).fetchone()[0]
            p["n_exportaciones"] = con.execute(
                "SELECT COUNT(*) FROM exportaciones WHERE proyecto_id = ? AND estado = 'listo'", (p["id"],)
            ).fetchone()[0]
    return proyectos


def _duracion_clips(min_s: float, max_s: float) -> dict:
    """Valida el rango de duracion deseado para los clips propuestos."""
    if not (3 <= min_s <= 300) or not (5 <= max_s <= 600) or max_s <= min_s:
        raise HTTPException(422, "La duracion de los clips no es valida: el maximo debe ser mayor que el minimo.")
    return {"min_s": float(min_s), "max_s": float(max_s)}


class ProyectoUrl(BaseModel):
    url: str = Field(max_length=2000)
    idioma: str = "auto"
    min_s: float = 15
    max_s: float = 60


@app.post("/api/proyectos/url", status_code=201)
def crear_desde_url(datos: ProyectoUrl) -> dict:
    if datos.idioma not in IDIOMAS:
        raise HTTPException(422, "Idioma no reconocido.")
    duracion = _duracion_clips(datos.min_s, datos.max_s)
    try:
        url = importer.validar_url(datos.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not config.find_tool("ffmpeg"):
        raise HTTPException(503, "FFmpeg no esta instalado. Ejecuta: uv run python scripts/instalar_ffmpeg.py")
    p = db.insertar(
        "proyectos",
        {"nombre": url, "origen": "url", "url": url, "idioma": datos.idioma,
         "estado": "en_cola", "paso": "en_cola", "mensaje": "En cola...", "progreso": 0, **duracion},
    )
    gestor.encolar("proyecto", p["id"])
    return p


@app.put("/api/proyectos/archivo", status_code=201)
async def crear_desde_archivo(
    request: Request, nombre: str, idioma: str = "auto", min_s: float = 15, max_s: float = 60
) -> dict:
    """Recibe el video como cuerpo binario y lo escribe en disco por bloques (sin cargarlo en memoria)."""
    if idioma not in IDIOMAS:
        raise HTTPException(422, "Idioma no reconocido.")
    duracion = _duracion_clips(min_s, max_s)
    nombre = Path(nombre.replace("\\", "/")).name[:150]
    extension = Path(nombre).suffix.lower()
    if extension not in EXTENSIONES:
        raise HTTPException(415, f"Formato no admitido ({extension or 'sin extension'}). Usa: {', '.join(sorted(EXTENSIONES))}")
    if not config.find_tool("ffmpeg"):
        raise HTTPException(503, "FFmpeg no esta instalado. Ejecuta: uv run python scripts/instalar_ffmpeg.py")
    declarado = int(request.headers.get("content-length") or 0)
    limite_gb = config.MAX_UPLOAD_BYTES / 1024**3
    if declarado > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"El archivo supera el limite de {limite_gb:.0f} GB.")
    if declarado and shutil.disk_usage(config.DATA_DIR).free < declarado * 2:
        raise HTTPException(507, "No hay espacio suficiente en el disco de datos para procesar este video.")

    pid = db.nuevo_id()
    carpeta = pipeline.carpeta_proyecto(pid)
    carpeta.mkdir(parents=True)
    temporal = carpeta / "fuente.subiendo"
    recibido = 0
    try:
        with open(temporal, "wb") as f:
            async for bloque in request.stream():
                recibido += len(bloque)
                if recibido > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"El archivo supera el limite de {limite_gb:.0f} GB.")
                await asyncio.to_thread(f.write, bloque)
        if recibido == 0:
            raise HTTPException(400, "El archivo esta vacio.")
        if declarado and recibido != declarado:
            raise HTTPException(400, "La subida se interrumpio antes de terminar.")
        temporal.replace(carpeta / f"fuente{extension}")
        p = db.insertar(
            "proyectos",
            {"id": pid, "nombre": Path(nombre).stem or "Video", "origen": "archivo",
             "archivo_fuente": f"fuente{extension}", "idioma": idioma,
             "estado": "en_cola", "paso": "en_cola", "mensaje": "En cola...", "progreso": 0, **duracion},
        )
    except BaseException:
        # Incluye la desconexion del cliente y un fallo al registrar: no se dejan archivos huerfanos.
        shutil.rmtree(carpeta, ignore_errors=True)
        raise
    gestor.encolar("proyecto", pid)
    return p


@app.get("/api/proyectos/{pid}")
def ver_proyecto(pid: str) -> dict:
    return _detalle(pid)


class ProyectoCambios(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)


@app.patch("/api/proyectos/{pid}")
def renombrar_proyecto(pid: str, datos: ProyectoCambios) -> dict:
    _proyecto(pid)
    db.actualizar("proyectos", pid, nombre=datos.nombre.strip() or "Video")
    return _detalle(pid)


@app.delete("/api/proyectos/{pid}", status_code=204)
def borrar_proyecto(pid: str) -> None:
    _proyecto(pid)
    with _transicion:
        gestor.cancelar(pid)
        for e in db.listar("exportaciones", "proyecto_id = ?", (pid,)):
            gestor.cancelar(e["id"])
        db.borrar("proyectos", pid)
    # Borra ahora, o cuando termine el ultimo trabajo que aun usa la carpeta. Como ultima
    # red, la limpieza de huerfanos al arrancar elimina lo que hubiera quedado.
    gestor.borrar_archivos(pid)


@app.post("/api/proyectos/{pid}/cancelar")
def cancelar_proyecto(pid: str) -> dict:
    with _transicion:
        p = _proyecto(pid)
        # Si esta ejecutandose, el trabajador fija el estado al detenerse; si solo estaba
        # en cola (o no habia trabajo), se marca cancelado de inmediato.
        if p["estado"] in db.ACTIVOS and gestor.cancelar(pid) != "ejecutando":
            db.actualizar("proyectos", pid, estado="cancelado", mensaje="Cancelado.")
    return _detalle(pid)


@app.post("/api/proyectos/{pid}/reintentar")
def reintentar_proyecto(pid: str) -> dict:
    with _transicion:
        p = _proyecto(pid)
        if p["estado"] in db.ACTIVOS or gestor.activo(pid):
            raise HTTPException(409, "El proyecto ya se esta procesando o todavia se esta deteniendo.")
        if p["estado"] == "listo":
            raise HTTPException(409, "El proyecto ya esta listo.")
        db.actualizar("proyectos", pid, estado="en_cola", paso="en_cola", mensaje="En cola...", progreso=0, error=None)
        gestor.encolar("proyecto", pid)
    return _detalle(pid)


@app.get("/api/proyectos/{pid}/transcripcion")
def ver_transcripcion(pid: str) -> dict:
    _proyecto(pid)
    t = pipeline.leer_transcripcion(pid)
    return {"idioma": t.get("idioma"), "frases": suggest.partir_en_frases(t["segmentos"])}


@app.get("/api/proyectos/{pid}/video")
def ver_video(pid: str) -> FileResponse:
    _proyecto(pid)
    ruta = pipeline.ruta_proxy(pid)
    if not ruta.is_file():
        raise HTTPException(404, "La vista previa todavia no esta lista.")
    return FileResponse(ruta, media_type="video/mp4")


class Sugerir(BaseModel):
    min_s: float = Field(15, ge=3, le=300)
    max_s: float = Field(60, ge=5, le=600)


@app.post("/api/proyectos/{pid}/sugerir")
def sugerir(pid: str, datos: Sugerir) -> dict:
    if datos.max_s <= datos.min_s:
        raise HTTPException(422, "La duracion maxima debe ser mayor que la minima.")
    # Bajo el candado: no se mezcla con otra regeneracion ni con "exportar todos".
    with _transicion:
        p = _proyecto_listo(pid)
        pipeline.crear_propuestas(p, pipeline.leer_transcripcion(pid), datos.min_s, datos.max_s)
        db.actualizar("proyectos", pid, min_s=datos.min_s, max_s=datos.max_s)
    return _detalle(pid)


class Dividir(BaseModel):
    duracion_s: float = Field(30, ge=5, le=600)
    ajustar_a_pausas: bool = True


@app.post("/api/proyectos/{pid}/dividir")
def dividir(pid: str, datos: Dividir) -> dict:
    """Crea clips consecutivos que cubren todo el video (reemplaza una division anterior)."""
    with _transicion:
        p = _proyecto_listo(pid)
        if p["duracion"] / datos.duracion_s > 2000:
            raise HTTPException(422, "Saldrian mas de 2000 clips. Elige una duracion mayor por clip.")
        n = pipeline.crear_division(p, pipeline.leer_transcripcion(pid), datos.duracion_s, datos.ajustar_a_pausas)
    detalle = _detalle(pid)
    detalle["creados"] = n
    return detalle


class ExportarVarios(BaseModel):
    origen: str | None = None      # None = todos; o 'sugerido' | 'manual' | 'division'


@app.post("/api/proyectos/{pid}/exportar-todos", status_code=201)
def exportar_todos(pid: str, datos: ExportarVarios) -> dict:
    """Pone en cola la exportacion de todos los clips del proyecto (o los de un origen)."""
    if datos.origen not in (None, "sugerido", "manual", "division"):
        raise HTTPException(422, "Origen no valido.")
    if not config.find_tool("ffmpeg"):
        raise HTTPException(503, "FFmpeg no esta instalado. Ejecuta: uv run python scripts/instalar_ffmpeg.py")
    with _transicion:
        _proyecto_listo(pid)
        clips = db.listar("clips", "proyecto_id = ?", (pid,), "inicio ASC")
        if datos.origen:
            clips = [c for c in clips if c["origen"] == datos.origen]
        if not clips:
            raise HTTPException(409, "No hay clips que exportar.")
        for clip in clips:
            _encolar_exportacion(clip)
    detalle = _detalle(pid)
    detalle["encolados"] = len(clips)
    return detalle


class AplicarEstilo(BaseModel):
    clip_id: str
    que: str = "subtitulos"        # 'subtitulos' = solo el aspecto del texto; 'todo' = estilo completo y encuadre


@app.post("/api/proyectos/{pid}/aplicar-estilo")
def aplicar_estilo(pid: str, datos: AplicarEstilo) -> dict:
    """Copia el estilo de un clip a todos los demas clips del proyecto."""
    if datos.que not in ("subtitulos", "todo"):
        raise HTTPException(422, "Opcion no valida.")
    with _transicion:
        _proyecto_listo(pid)
        origen = _clip(datos.clip_id)
        if origen["proyecto_id"] != pid:
            raise HTTPException(404, "El clip no pertenece a este proyecto.")
        claves = (
            subtitles.CLAVES_SUBTITULOS if datos.que == "subtitulos"
            else [k for k in subtitles.ESTILO_BASE if k not in subtitles.SOLO_DEL_CLIP]
        )
        cambio = {k: origen["estilo"][k] for k in claves}
        aplicados = 0
        for c in db.listar("clips", "proyecto_id = ?", (pid,)):
            if c["id"] == origen["id"]:
                continue
            campos = {"estilo": subtitles.normalizar_estilo({**c["estilo"], **cambio})}
            if datos.que == "todo":
                campos["encuadre"] = origen["encuadre"]
            db.actualizar("clips", c["id"], **campos)
            aplicados += 1
    detalle = _detalle(pid)
    detalle["aplicados"] = aplicados
    return detalle


# ---------- preferencias ----------

@app.get("/api/preferencias/clip")
def ver_preferencias() -> dict:
    return pipeline.preferencias_clip()


class Preferencias(BaseModel):
    estilo: dict[str, Any]
    encuadre: str = "rellenar"


@app.put("/api/preferencias/clip")
def guardar_preferencias(datos: Preferencias) -> dict:
    """Guarda el estilo y el encuadre con los que naceran los clips nuevos."""
    if datos.encuadre not in pipeline.ENCUADRES:
        raise HTTPException(422, "Encuadre no valido.")
    db.guardar_preferencia(
        "clip", {"estilo": subtitles.estilo_para_preferencia(datos.estilo), "encuadre": datos.encuadre}
    )
    return pipeline.preferencias_clip()


@app.post("/api/proyectos/{pid}/abrir-carpeta")
def abrir_carpeta(pid: str) -> dict:
    _proyecto(pid)
    carpeta = pipeline.carpeta_proyecto(pid) / "exportaciones"
    carpeta.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(carpeta)  # type: ignore[attr-defined]
    return {"carpeta": str(carpeta)}


# ---------- clips ----------

class ClipNuevo(BaseModel):
    inicio: float = Field(ge=0)
    fin: float = Field(gt=0)
    titulo: str = Field("", max_length=120)


@app.post("/api/proyectos/{pid}/clips", status_code=201)
def crear_clip(pid: str, datos: ClipNuevo) -> dict:
    p = _proyecto_listo(pid)
    inicio, fin = _validar_rango(datos.inicio, datos.fin, p["duracion"])
    segmentos = pipeline.leer_transcripcion(pid)["segmentos"]
    return pipeline._nuevo_clip(
        p, segmentos, pipeline.preferencias_clip(), inicio, fin,
        datos.titulo.strip() or "Clip manual", "manual", [],
    )


class ClipCambios(BaseModel):
    titulo: str | None = Field(None, max_length=120)
    inicio: float | None = Field(None, ge=0)
    fin: float | None = Field(None, gt=0)
    encuadre: str | None = None
    recorte_x: float | None = Field(None, ge=0, le=1)
    subtitulos: list[dict[str, Any]] | None = None
    estilo: dict[str, Any] | None = None


@app.patch("/api/clips/{cid}")
def editar_clip(cid: str, datos: ClipCambios) -> dict:
    clip = _clip(cid)
    p = _proyecto(clip["proyecto_id"])
    cambios: dict[str, Any] = {}
    if datos.titulo is not None:
        cambios["titulo"] = datos.titulo.strip() or clip["titulo"]
    if datos.encuadre is not None:
        if datos.encuadre not in pipeline.ENCUADRES:
            raise HTTPException(422, "Encuadre no valido.")
        cambios["encuadre"] = datos.encuadre
    if datos.recorte_x is not None:
        cambios["recorte_x"] = round(datos.recorte_x, 4)
    estilo = clip["estilo"]
    if datos.estilo is not None:
        estilo = cambios["estilo"] = subtitles.normalizar_estilo({**clip["estilo"], **datos.estilo})
    inicio, fin = clip["inicio"], clip["fin"]
    cambio_rango = datos.inicio is not None or datos.fin is not None
    if cambio_rango:
        inicio, fin = _validar_rango(
            clip["inicio"] if datos.inicio is None else datos.inicio,
            clip["fin"] if datos.fin is None else datos.fin,
            p["duracion"],
        )
        cambios.update(inicio=inicio, fin=fin)
    if datos.subtitulos is not None:
        try:
            cues = subtitles.validar(datos.subtitulos, p["duracion"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        cambios["subtitulos"] = subtitles.recortar(cues, inicio, fin)
    elif cambio_rango:
        segmentos = pipeline.leer_transcripcion(p["id"])["segmentos"]
        cambios["subtitulos"] = subtitles.sincronizar(clip["subtitulos"], segmentos, inicio, fin, estilo)
    db.actualizar("clips", cid, **cambios)
    return _clip(cid)


@app.delete("/api/clips/{cid}", status_code=204)
def borrar_clip(cid: str) -> None:
    _clip(cid)
    db.borrar("clips", cid)


@app.post("/api/clips/{cid}/subtitulos/regenerar")
def regenerar_subtitulos(cid: str) -> dict:
    clip = _clip(cid)
    segmentos = pipeline.leer_transcripcion(clip["proyecto_id"])["segmentos"]
    db.actualizar("clips", cid, subtitulos=subtitles.generar(segmentos, clip["inicio"], clip["fin"], clip["estilo"]))
    return _clip(cid)


@app.post("/api/clips/{cid}/encuadre-auto")
def encuadre_auto(cid: str) -> dict:
    clip = _clip(cid)
    recorte = reframe.detectar_recorte(pipeline.ruta_proxy(clip["proyecto_id"]), clip["inicio"], clip["fin"])
    if recorte is None:
        return {"detectado": False, "clip": clip}
    # Con el encuadre dividido se conserva el tipo: solo cambia la posicion horizontal.
    encuadre = "dividido" if clip["encuadre"] == "dividido" else "rellenar"
    db.actualizar("clips", cid, recorte_x=recorte, encuadre=encuadre)
    return {"detectado": True, "clip": _clip(cid)}


# ---------- exportaciones ----------

@app.post("/api/clips/{cid}/exportar", status_code=201)
def exportar_clip(cid: str) -> dict:
    if not config.find_tool("ffmpeg"):
        raise HTTPException(503, "FFmpeg no esta instalado. Ejecuta: uv run python scripts/instalar_ffmpeg.py")
    # Mismo candado que el borrado: una exportacion no puede colarse mientras se elimina el proyecto.
    with _transicion:
        clip = _clip(cid)
        _proyecto_listo(clip["proyecto_id"])
        exp = _encolar_exportacion(clip)
    exp.pop("parametros")
    return exp


def _encolar_exportacion(clip: dict) -> dict:
    """Guarda una copia inmutable del clip y la pone en cola. Llamar con `_transicion` tomado."""
    parametros = {k: clip[k] for k in ("inicio", "fin", "encuadre", "recorte_x", "subtitulos", "estilo")}
    exp = db.insertar(
        "exportaciones",
        {"clip_id": clip["id"], "proyecto_id": clip["proyecto_id"], "titulo": clip["titulo"],
         "parametros": parametros, "estado": "en_cola", "progreso": 0},
    )
    gestor.encolar("exportacion", exp["id"])
    return exp


def _exportacion(eid: str) -> dict:
    e = db.obtener("exportaciones", eid)
    if e is None:
        raise HTTPException(404, "La exportacion no existe.")
    return e


@app.post("/api/exportaciones/{eid}/cancelar")
def cancelar_exportacion(eid: str) -> dict:
    with _transicion:
        e = _exportacion(eid)
        if e["estado"] in db.ACTIVOS and gestor.cancelar(eid) != "ejecutando":
            db.actualizar("exportaciones", eid, estado="cancelado")
    return {"ok": True}


@app.delete("/api/exportaciones/{eid}", status_code=204)
def borrar_exportacion(eid: str) -> None:
    e = _exportacion(eid)
    if e["estado"] in db.ACTIVOS:
        raise HTTPException(409, "Cancela la exportacion antes de borrarla.")
    if e["archivo"]:
        (pipeline.carpeta_proyecto(e["proyecto_id"]) / "exportaciones" / Path(e["archivo"]).name).unlink(missing_ok=True)
    db.borrar("exportaciones", eid)


@app.get("/api/exportaciones/{eid}/archivo")
def descargar_exportacion(eid: str, descargar: bool = False) -> FileResponse:
    e = _exportacion(eid)
    if e["estado"] != "listo" or not e["archivo"]:
        raise HTTPException(409, "La exportacion todavia no esta lista.")
    ruta = pipeline.carpeta_proyecto(e["proyecto_id"]) / "exportaciones" / Path(e["archivo"]).name
    if not ruta.is_file():
        raise HTTPException(404, "El archivo exportado ya no existe en el disco.")
    nombre = f"{_nombre_seguro(e['titulo'])}_{eid[:6]}.mp4"
    return FileResponse(ruta, media_type="video/mp4", filename=nombre if descargar else None)


# ---------- fondos del encuadre dividido ----------

def _fondo(nombre: str) -> Path:
    """Devuelve la ruta de un fondo de la carpeta de fondos; 404 si el nombre no es valido o no existe."""
    if nombre != Path(nombre).name:
        raise HTTPException(404, "El fondo no existe.")
    for ruta in pipeline.listar_fondos():
        if ruta.name == nombre:
            return ruta
    raise HTTPException(404, "El fondo no existe.")


@app.get("/api/fondos")
def listar_fondos() -> dict:
    return {
        "carpeta": str(config.FONDOS_DIR),
        "fondos": [
            {"nombre": f.name, "tamano_mb": round(f.stat().st_size / 1024**2, 1)}
            for f in pipeline.listar_fondos()
        ],
    }


@app.get("/api/fondos/{nombre}/video")
def ver_fondo(nombre: str) -> FileResponse:
    return FileResponse(_fondo(nombre))


@app.post("/api/fondos/abrir-carpeta")
def abrir_carpeta_fondos() -> dict:
    config.FONDOS_DIR.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(config.FONDOS_DIR)  # type: ignore[attr-defined]
    return {"carpeta": str(config.FONDOS_DIR)}


# La interfaz web se monta al final para no tapar las rutas de la API.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
