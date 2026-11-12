"""Cola de trabajos y flujo de procesamiento: importar -> audio -> proxy -> transcribir -> proponer.

Dos hilos de trabajo: uno para procesar proyectos y otro para exportar clips, de modo que
una exportacion no espere detras de una transcripcion larga. Dentro de cada cola los
trabajos se ejecutan de uno en uno para no saturar la CPU.
"""

from __future__ import annotations

import json
import logging
import queue
import random
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from . import config, db, importer, media, reframe, subtitles, suggest, transcribe
from .media import Cancelacion, Cancelado, ErrorMedia

log = logging.getLogger("clipstudio")


def carpeta_proyecto(proyecto_id: str) -> Path:
    return config.PROJECTS_DIR / proyecto_id


def ruta_fuente(proyecto: dict) -> Path | None:
    if not proyecto.get("archivo_fuente"):
        return None
    return carpeta_proyecto(proyecto["id"]) / proyecto["archivo_fuente"]


def ruta_proxy(proyecto_id: str) -> Path:
    return carpeta_proyecto(proyecto_id) / "proxy.mp4"


def ruta_transcripcion(proyecto_id: str) -> Path:
    return carpeta_proyecto(proyecto_id) / "transcripcion.json"


def leer_transcripcion(proyecto_id: str) -> dict:
    ruta = ruta_transcripcion(proyecto_id)
    if not ruta.is_file():
        return {"idioma": None, "segmentos": [], "picos": []}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos.setdefault("picos", [])
    return datos


def preferencias_clip() -> dict:
    """Estilo y encuadre con los que nacen los clips nuevos (guardados por la persona usuaria)."""
    pref = db.leer_preferencia("clip", {}) or {}
    encuadre = pref.get("encuadre")
    return {
        "estilo": subtitles.estilo_para_preferencia(pref.get("estilo")),
        "encuadre": encuadre if encuadre in ENCUADRES else "rellenar",
    }


ENCUADRES = ("rellenar", "ajustar", "dividido")
EXTENSIONES_FONDO = (".mp4", ".mov", ".mkv", ".webm", ".m4v")


def listar_fondos() -> list[Path]:
    """Videos de la carpeta de fondos (gameplay para el encuadre dividido), ordenados por nombre."""
    if not config.FONDOS_DIR.is_dir():
        return []
    return sorted(
        (f for f in config.FONDOS_DIR.iterdir() if f.is_file() and f.suffix.lower() in EXTENSIONES_FONDO),
        key=lambda f: f.name.lower(),
    )


def _fondo_para(estilo: dict) -> Path:
    """El fondo elegido en el estilo si existe; si no, uno al azar de la carpeta de fondos."""
    elegido = estilo.get("fondo_juego")
    if elegido and (config.FONDOS_DIR / elegido).is_file():
        return config.FONDOS_DIR / elegido
    fondos = listar_fondos()
    if not fondos:
        raise ErrorMedia(
            "No hay videos de fondo. Añade alguno en la carpeta de fondos "
            "(pestaña Encuadre y estilo → Abrir carpeta de fondos)."
        )
    return random.choice(fondos)


def _nuevo_clip(proyecto: dict, segmentos: list[dict], pref: dict, inicio: float, fin: float,
                titulo: str, origen: str, motivos: list[str], detectar_rostro: bool = True) -> dict:
    """Inserta un clip con subtitulos generados y, si procede, el recorte centrado en el rostro."""
    proxy = ruta_proxy(proyecto["id"])
    recorte = reframe.detectar_recorte(proxy, inicio, fin) if detectar_rostro and proxy.is_file() else None
    motivos = list(motivos)
    if recorte is not None and origen != "manual":
        motivos.append("Encuadre centrado en el rostro detectado")
    return db.insertar(
        "clips",
        {
            "proyecto_id": proyecto["id"],
            "titulo": titulo,
            "inicio": round(inicio, 3),
            "fin": round(fin, 3),
            "encuadre": pref["encuadre"],
            "recorte_x": 0.5 if recorte is None else recorte,
            "subtitulos": subtitles.generar(segmentos, inicio, fin, pref["estilo"]),
            "estilo": dict(pref["estilo"]),
            "origen": origen,
            "motivos": motivos,
        },
    )


class _Progreso:
    """Escribe el progreso en la base de datos como mucho dos veces por segundo."""

    def __init__(self, tabla: str, id_: str) -> None:
        self.tabla, self.id = tabla, id_
        self._ultimo = 0.0

    def tramo(self, desde: float, hasta: float) -> Callable[[float], None]:
        def informar(fraccion: float) -> None:
            ahora = time.monotonic()
            if ahora - self._ultimo >= 0.5 or fraccion >= 1:
                self._ultimo = ahora
                db.actualizar(self.tabla, self.id, progreso=round(desde + (hasta - desde) * fraccion, 1))

        return informar


class Gestor:
    """Cola por tipo de trabajo. Cada entrada lleva su propia senal de cancelacion, de modo
    que cancelar y volver a encolar el mismo id no confunde una ejecucion con otra."""

    def __init__(self) -> None:
        self._colas = {"proyecto": queue.Queue(), "exportacion": queue.Queue()}
        self._cancelaciones: dict[str, Cancelacion] = {}
        self._ejecutando: set[str] = set()
        self._usos: dict[str, int] = {}          # proyecto -> trabajos que usan su carpeta ahora
        self._por_borrar: set[str] = set()       # proyectos eliminados a la espera de quedar libres
        self._lock = threading.Lock()
        self._iniciado = False

    def iniciar(self) -> None:
        if self._iniciado:
            return
        self._iniciado = True
        for tipo in self._colas:
            threading.Thread(target=self._bucle, args=(tipo,), daemon=True, name=f"cola-{tipo}").start()

    def encolar(self, tipo: str, id_: str) -> bool:
        """Devuelve False si ese id ya esta en cola o ejecutandose."""
        cancel = Cancelacion()
        with self._lock:
            if id_ in self._cancelaciones:
                return False
            self._cancelaciones[id_] = cancel
        self._colas[tipo].put((id_, cancel))
        return True

    def cancelar(self, id_: str) -> str:
        """'ejecutando': se detendra en breve y el trabajador fijara el estado.
        'pendiente': estaba en cola y ya no se ejecutara. 'ninguno': no habia trabajo."""
        with self._lock:
            cancel = self._cancelaciones.get(id_)
            if cancel is None:
                return "ninguno"
            ejecutando = id_ in self._ejecutando
            if not ejecutando:
                del self._cancelaciones[id_]
        cancel.cancelar()
        return "ejecutando" if ejecutando else "pendiente"

    def activo(self, id_: str) -> bool:
        with self._lock:
            return id_ in self._cancelaciones

    def borrar_archivos(self, proyecto_id: str) -> None:
        """Borra la carpeta del proyecto ahora, o en cuanto termine el ultimo trabajo que la usa."""
        with self._lock:
            if self._usos.get(proyecto_id, 0) > 0:
                self._por_borrar.add(proyecto_id)
                return
        borrar_archivos_proyecto(proyecto_id)

    def _usar(self, proyecto_id: str) -> None:
        with self._lock:
            self._usos[proyecto_id] = self._usos.get(proyecto_id, 0) + 1

    def _soltar(self, proyecto_id: str) -> None:
        with self._lock:
            restantes = self._usos.get(proyecto_id, 1) - 1
            if restantes > 0:
                self._usos[proyecto_id] = restantes
                return
            self._usos.pop(proyecto_id, None)
            borrar = proyecto_id in self._por_borrar
            self._por_borrar.discard(proyecto_id)
        if borrar:
            borrar_archivos_proyecto(proyecto_id)

    def _bucle(self, tipo: str) -> None:
        tabla = "proyectos" if tipo == "proyecto" else "exportaciones"
        funcion = procesar_proyecto if tipo == "proyecto" else exportar
        while True:
            id_, cancel = self._colas[tipo].get()
            try:
                with self._lock:
                    if cancel.activa or self._cancelaciones.get(id_) is not cancel:
                        continue  # se cancelo mientras esperaba; la API ya fijo su estado
                    self._ejecutando.add(id_)
                self._ejecutar(tabla, tipo, funcion, id_, cancel)
            except Exception:
                # Nada debe matar el hilo de la cola (por ejemplo, SQLite sin espacio en disco).
                log.error("Fallo en la cola %s con %s\n%s", tipo, id_, traceback.format_exc())
            finally:
                with self._lock:
                    self._ejecutando.discard(id_)
                    if self._cancelaciones.get(id_) is cancel:
                        del self._cancelaciones[id_]

    @staticmethod
    def _registrar(tabla: str, id_: str, **campos) -> None:
        """Guarda el resultado del trabajo; si la base de datos falla, se reintenta y se registra."""
        for intento in range(3):
            try:
                db.actualizar(tabla, id_, **campos)
                return
            except Exception:
                log.error("No se pudo guardar el estado de %s (intento %d)", id_, intento + 1, exc_info=True)
                time.sleep(1)

    def _ejecutar(self, tabla: str, tipo: str, funcion, id_: str, cancel: Cancelacion) -> None:
        fila = db.obtener(tabla, id_)
        if fila is None:
            return
        proyecto_id = id_ if tipo == "proyecto" else fila["proyecto_id"]
        self._usar(proyecto_id)
        try:
            db.actualizar(tabla, id_, estado="procesando", error=None)
            funcion(id_, cancel)
        except Cancelado:
            self._registrar(tabla, id_, estado="cancelado", error=None, **_extra(tabla, "Cancelado."))
        except ErrorMedia as exc:
            self._registrar(tabla, id_, estado="error", error=str(exc))
        except Exception as exc:  # error inesperado: se registra y se muestra resumido
            log.error("Fallo inesperado en %s %s\n%s", tipo, id_, traceback.format_exc())
            self._registrar(tabla, id_, estado="error", error=f"Error inesperado: {exc}")
        finally:
            if tipo == "proyecto":
                limpiar_temporales(id_)
            # Si el proyecto se elimino mientras tanto, su carpeta se borra cuando el ultimo
            # trabajo que la usaba (este u otro) la suelta.
            self._soltar(proyecto_id)


def _extra(tabla: str, mensaje: str) -> dict:
    return {"mensaje": mensaje} if tabla == "proyectos" else {}


gestor = Gestor()


def _paso(proyecto_id: str, paso: str, mensaje: str, progreso: float) -> None:
    db.actualizar("proyectos", proyecto_id, paso=paso, mensaje=mensaje, progreso=progreso)


def procesar_proyecto(proyecto_id: str, cancel: Cancelacion) -> None:
    proyecto = db.obtener("proyectos", proyecto_id)
    assert proyecto is not None
    carpeta = carpeta_proyecto(proyecto_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    prog = _Progreso("proyectos", proyecto_id)
    es_url = proyecto["origen"] == "url"
    base = 20.0 if es_url else 0.0

    # 1. Obtener el video
    fuente = ruta_fuente(proyecto)
    if fuente is None or not fuente.is_file():
        if not es_url:
            raise ErrorMedia("No se encontro el archivo subido. Vuelve a crear el proyecto.")
        _paso(proyecto_id, "descarga", "Descargando el video...", 1)
        fuente, titulo = importer.descargar(proyecto["url"], carpeta, cancel, prog.tramo(1, base))
        cambios = {"archivo_fuente": fuente.name}
        if proyecto["nombre"] == proyecto["url"]:
            cambios["nombre"] = titulo
        db.actualizar("proyectos", proyecto_id, **cambios)

    # 2. Analizar
    _paso(proyecto_id, "analisis", "Analizando el archivo...", base)
    info = media.sondear(fuente)
    if info["duracion"] > config.MAX_DURATION_S:
        raise ErrorMedia(
            f"El video dura {info['duracion'] / 60:.0f} min y el limite es "
            f"{config.MAX_DURATION_S / 60:.0f} min (CLIPSTUDIO_MAX_DURATION_MIN)."
        )
    duracion = info["duracion"]
    db.actualizar("proyectos", proyecto_id, duracion=duracion, ancho=info["ancho"], alto=info["alto"])
    libre = shutil.disk_usage(carpeta).free
    if libre < 2 * 1024**3:
        raise ErrorMedia("Queda menos de 2 GB libres en el disco de datos. Libera espacio e intentalo de nuevo.")
    cancel.comprobar()

    tramo = (100 - base) / 100  # reparte el resto del progreso

    def p(valor: float) -> float:
        return base + valor * tramo

    # 3. Proxy de previsualizacion
    _paso(proyecto_id, "proxy", "Preparando la vista previa...", p(2))
    proxy_tmp = carpeta / "proxy.tmp.mp4"
    media.crear_proxy(fuente, proxy_tmp, duracion, cancel, prog.tramo(p(2), p(35)), info["pista_video"])
    proxy_tmp.replace(ruta_proxy(proyecto_id))

    # 4. Audio + transcripcion
    transcripcion = {"idioma": None, "segmentos": [], "picos": []}
    if info["tiene_audio"]:
        _paso(proyecto_id, "audio", "Extrayendo el audio...", p(35))
        audio = carpeta / "audio.wav"
        media.extraer_audio(fuente, audio, duracion, cancel, prog.tramo(p(35), p(40)))
        _paso(proyecto_id, "transcripcion", "Transcribiendo el audio...", p(40))
        transcripcion = transcribe.transcribir(
            audio, duracion, proyecto["idioma"], cancel, prog.tramo(p(40), p(94)),
            aviso=lambda m: db.actualizar("proyectos", proyecto_id, mensaje=m),
            parcial=carpeta / "transcripcion.parcial.json",
            identidad=f"{fuente.stat().st_size}-{fuente.stat().st_mtime_ns}",
        )
        audio.unlink(missing_ok=True)
    tmp = ruta_transcripcion(proyecto_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(transcripcion, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ruta_transcripcion(proyecto_id))
    db.actualizar("proyectos", proyecto_id, idioma_detectado=transcripcion["idioma"])
    cancel.comprobar()

    # 5. Propuestas de clips
    _paso(proyecto_id, "propuestas", "Buscando fragmentos...", p(94))
    actual = db.obtener("proyectos", proyecto_id)
    assert actual is not None
    n = crear_propuestas(actual, transcripcion, actual.get("min_s") or 15, actual.get("max_s") or 60, cancel=cancel)
    if not info["tiene_audio"]:
        mensaje = "Listo. El video no tiene audio: no hay transcripcion ni subtitulos automaticos."
    elif not transcripcion["segmentos"]:
        mensaje = "Listo. No se detecto voz: crea los clips manualmente."
    else:
        mensaje = f"Listo. {n} fragmento(s) propuesto(s)."
    db.actualizar("proyectos", proyecto_id, estado="listo", paso="listo", progreso=100, mensaje=mensaje, error=None)


def crear_propuestas(
    proyecto: dict,
    transcripcion: dict,
    min_s: float = 15,
    max_s: float = 60,
    cancel: Cancelacion | None = None,
) -> int:
    """Reemplaza los clips sugeridos (los manuales se conservan). Devuelve cuantos creo."""
    propuestas = suggest.proponer_clips(
        transcripcion["segmentos"], proyecto["duracion"], min_s, max_s, picos=transcripcion.get("picos")
    )
    db.borrar_donde("clips", "proyecto_id = ? AND origen = 'sugerido'", (proyecto["id"],))
    pref = preferencias_clip()
    for prop in propuestas:
        if cancel:
            cancel.comprobar()
        _nuevo_clip(proyecto, transcripcion["segmentos"], pref, prop["inicio"], prop["fin"],
                    prop["titulo"], "sugerido", prop["motivos"])
    return len(propuestas)


MAX_ROSTROS_DIVISION = 60  # por encima de esto, la division no busca rostros (tardaria demasiado)


def crear_division(proyecto: dict, transcripcion: dict, objetivo_s: float, ajustar: bool) -> int:
    """Reemplaza los clips de una division anterior por otra que cubre todo el video."""
    partes = suggest.dividir(transcripcion["segmentos"], proyecto["duracion"], objetivo_s, ajustar)
    pref = preferencias_clip()
    con_rostro = len(partes) <= MAX_ROSTROS_DIVISION
    motivo = "Division del video completo" + (" (cortes en pausas del habla)" if ajustar else "")
    anteriores = [c["id"] for c in db.listar("clips", "proyecto_id = ? AND origen = 'division'", (proyecto["id"],))]
    # Primero se crean las partes nuevas y solo despues se retiran las anteriores: si algo
    # falla a mitad, no se pierde la division que ya habia.
    for parte in partes:
        _nuevo_clip(proyecto, transcripcion["segmentos"], pref, parte["inicio"], parte["fin"],
                    parte["titulo"], "division", [motivo], detectar_rostro=con_rostro)
    for clip_id in anteriores:
        db.borrar("clips", clip_id)
    return len(partes)


def exportar(exportacion_id: str, cancel: Cancelacion) -> None:
    exp = db.obtener("exportaciones", exportacion_id)
    assert exp is not None
    proyecto = db.obtener("proyectos", exp["proyecto_id"])
    if proyecto is None:
        raise ErrorMedia("El proyecto de este clip ya no existe.")
    fuente = ruta_fuente(proyecto)
    if fuente is None or not fuente.is_file():
        raise ErrorMedia("No se encontro el video original del proyecto.")
    clip = exp["parametros"]
    carpeta = carpeta_proyecto(proyecto["id"]) / "exportaciones"
    carpeta.mkdir(parents=True, exist_ok=True)
    trabajo = carpeta / f"{exportacion_id}.tmp"
    trabajo.mkdir(exist_ok=True)
    try:
        cues = subtitles.recortar(clip["subtitulos"], clip["inicio"], clip["fin"])
        estilo = subtitles.normalizar_estilo(clip["estilo"])
        archivo_ass = None
        if subtitles.tiene_contenido(cues, estilo):
            palabras = None
            if estilo["resaltar"]:
                segmentos = leer_transcripcion(proyecto["id"])["segmentos"]
                palabras = subtitles.palabras_en_rango(segmentos, clip["inicio"], clip["fin"])
            archivo_ass = trabajo / "subs.ass"
            archivo_ass.write_text(
                subtitles.a_ass(cues, clip["inicio"], clip["fin"], estilo, palabras), encoding="utf-8"
            )
        juego, juego_inicio = None, 0.0
        if clip["encuadre"] == "dividido":
            juego = _fondo_para(estilo)
            duracion_fondo = media.sondear(juego)["duracion"]
            # Cada exportacion empieza el juego en un punto distinto del video de fondo.
            juego_inicio = random.uniform(0, max(0.0, duracion_fondo - (clip["fin"] - clip["inicio"])))
        temporal = trabajo / "salida.mp4"
        prog = _Progreso("exportaciones", exportacion_id)
        pista = media.sondear(fuente)["pista_video"]
        media.exportar_clip(
            fuente, temporal, clip["inicio"], clip["fin"], clip["encuadre"], clip["recorte_x"],
            archivo_ass, cancel, prog.tramo(0, 99), pista,
            estilo["color_fondo"] if estilo["fondo"] == "color" else None,
            juego=juego, juego_inicio=juego_inicio, proporcion_juego=estilo["juego_proporcion"],
        )
        final = carpeta / f"{exportacion_id}.mp4"
        temporal.replace(final)
        db.actualizar("exportaciones", exportacion_id, estado="listo", progreso=100, archivo=final.name, error=None)
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


TEMPORALES = ("audio.wav", "proxy.tmp.mp4", "transcripcion.tmp", "fuente.subiendo")


def limpiar_temporales(proyecto_id: str) -> None:
    """Borra los archivos intermedios que quedan si un paso falla o se cancela."""
    carpeta = carpeta_proyecto(proyecto_id)
    for nombre in TEMPORALES:
        try:
            (carpeta / nombre).unlink(missing_ok=True)
        except OSError:
            log.warning("No se pudo borrar el temporal %s de %s", nombre, proyecto_id)


def borrar_archivos_proyecto(proyecto_id: str) -> bool:
    """Borra la carpeta del proyecto. Devuelve False si quedaron archivos (p. ej. en uso)."""
    carpeta = carpeta_proyecto(proyecto_id).resolve()
    # Solo se borra si la carpeta esta realmente dentro de la carpeta de proyectos.
    if carpeta.parent != config.PROJECTS_DIR.resolve() or not carpeta.is_dir():
        return True
    shutil.rmtree(carpeta, ignore_errors=True)
    if carpeta.exists():
        log.warning("Quedaron archivos sin borrar en %s; se reintentara al arrancar.", carpeta)
        return False
    return True


def limpiar_huerfanos() -> None:
    """Al arrancar: borra carpetas sin proyecto (subidas interrumpidas, borrados incompletos)
    y los temporales de los proyectos que quedaron a medias."""
    if not config.PROJECTS_DIR.is_dir():
        return
    conocidos = {p["id"] for p in db.listar("proyectos")}
    for carpeta in config.PROJECTS_DIR.iterdir():
        if not carpeta.is_dir():
            continue
        if carpeta.name not in conocidos:
            shutil.rmtree(carpeta, ignore_errors=True)
            continue
        limpiar_temporales(carpeta.name)
        for resto in (carpeta / "exportaciones").glob("*.tmp"):
            shutil.rmtree(resto, ignore_errors=True)
