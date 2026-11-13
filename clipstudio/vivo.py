"""Graba un directo en un bufer, detecta audio/chat y guarda clips como proyectos editables.

Piezas:
  - resolver_directo(): yt-dlp -> URL del flujo (o el modo de pruebas `prueba:<archivo>`).
  - Un unico subproceso FFmpeg por sesion con dos salidas: segmentos MPEG-TS sin recodificar
    y audio PCM por stdout (para medir el volumen por segundo).
  - Bufer circular: solo se conservan los ultimos CLIPSTUDIO_VIVO_BUFER_MIN minutos.
  - Detector causal de momentos (funciones puras, probables sin FFmpeg).
  - Recorte de un tramo a un MP4 y alta de un proyecto normal en la cola de siempre.
  - APIRouter con las rutas /api/vivo.
"""

from __future__ import annotations

import csv
import logging
import os
import math
import queue
import shutil
import statistics
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import chat, config, db, importer, media, pipeline, reframe
from .media import Cancelacion, ErrorMedia

log = logging.getLogger("clipstudio")

# ---------- parametros ----------

SEGMENTO_S = 6                 # duracion aproximada de cada segmento del bufer
VENTANA_BASE_S = 60            # historia sobre la que se mide el "volumen normal"
HISTORIA_MIN_S = 20            # sin al menos tanta historia no se detectan picos
UMBRAL_EXCESO_DB = 9.0         # cuanto debe superar a la mediana para ser pico
SUELO_DB = -35.0               # por debajo de este nivel nunca hay pico
ENFRIAMIENTO_S = 20            # tras un momento no se marca otro durante este tiempo
ANTES_S, DESPUES_S = 25.0, 10.0   # ventana por defecto alrededor de un momento
ULTIMOS_S = (30, 60, 90)
VOLUMEN_MOSTRADO_S = 120       # segundos de volumen que se devuelven a la interfaz
MIN_CLIP_S = 3.0
ESPERA_POSTERIOR_S = 25.0      # cuanto se espera a que lleguen los segmentos posteriores al pico
MIN_LIBRE_BYTES = 2 * 1024**3
PREFIJO_PRUEBA = "prueba:"


# ---------- modo de pruebas ----------

def modo_pruebas() -> bool:
    return os.environ.get("CLIPSTUDIO_VIVO_PRUEBAS") == "1"


def archivo_de_prueba(url: str) -> Path | None:
    """Si `url` es `prueba:<archivo>` y el modo de pruebas esta activo, devuelve el archivo.

    Devuelve None si no es un enlace de prueba. Fuera del modo de pruebas, `prueba:` se rechaza.
    """
    if not (url or "").strip().lower().startswith(PREFIJO_PRUEBA):
        return None
    if not modo_pruebas():
        raise ErrorMedia("Ese enlace no es valido. Pega la direccion completa del directo (https://...).")
    ruta = Path(url.strip()[len(PREFIJO_PRUEBA):].strip().strip('"'))
    if not ruta.is_file():
        raise ErrorMedia("El archivo de prueba no existe.")
    return ruta


# ---------- resolver el directo ----------

def resolver_directo(url: str) -> dict:
    """Devuelve {"entrada", "cabeceras", "titulo", "prueba"} para que FFmpeg lea el directo."""
    prueba = archivo_de_prueba(url)
    if prueba is not None:
        return {"entrada": str(prueba), "entrada_audio": None, "cabeceras": {}, "titulo": prueba.stem[:120], "prueba": True}

    try:
        url = importer.validar_url(url)
    except ValueError as exc:
        raise ErrorMedia(str(exc)) from exc
    importer.comprobar_destino_publico(url)

    import yt_dlp

    opciones: dict = {
        # Un solo flujo con video y audio si existe (Kick, Twitch); si no, video y audio
        # por separado (YouTube los entrega asi), hasta 1080p.
        "format": "b[height<=1080]/bv*[height<=1080]+ba/b/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    if node := config.find_tool("node"):
        opciones["js_runtimes"] = {"node": {"path": node}}
    if config.YTDLP_COOKIES_BROWSER:
        opciones["cookiesfrombrowser"] = (config.YTDLP_COOKIES_BROWSER,)
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        bajo = str(exc).lower()
        if "not currently live" in bajo or "offline" in bajo or "is not live" in bajo or "no esta en directo" in bajo:
            raise ErrorMedia("Ese canal no está en directo ahora mismo.") from exc
        raise ErrorMedia(importer._mensaje(exc)) from exc
    if not info or info.get("_type") == "playlist":
        raise ErrorMedia("Pega el enlace de un solo canal o directo.")
    if not (info.get("is_live") or info.get("live_status") == "is_live"):
        raise ErrorMedia("Ese canal no está en directo ahora mismo.")
    flujo, audio_aparte = info.get("url"), None
    formatos = info.get("requested_formats") or []
    # Con video y audio separados mandan los formatos pedidos, aunque exista una URL general.
    if formatos and (len(formatos) > 1 or not flujo):
        video = next((f for f in formatos if f.get("vcodec") not in (None, "none")), formatos[0])
        flujo = video.get("url")
        # El formato de audio puede venir sin codec declarado: basta con que no sea el de video.
        sonido = next((f for f in formatos if f is not video and f.get("acodec") != "none"), None)
        audio_aparte = sonido.get("url") if sonido else None
    if not flujo:
        raise ErrorMedia("No se pudo obtener el flujo de ese directo.")
    return {
        "entrada": flujo,
        "entrada_audio": audio_aparte,
        "cabeceras": dict(info.get("http_headers") or (formatos[0].get("http_headers") if formatos else None) or {}),
        "titulo": str(info.get("title") or "Directo")[:120],
        "prueba": False,
    }


# ---------- detector de momentos (puro) ----------

def evaluar_segundo(db_lista: list[float], i: int, ultimo: float | None) -> dict | None:
    """Decide si el segundo `i` es un pico. Causal: solo mira los segundos anteriores.

    Un segundo es pico si su volumen supera en >= 9 dB la mediana de los 60 s anteriores,
    es mayor que -35 dB y han pasado al menos 20 s desde el ultimo momento.
    """
    if i < HISTORIA_MIN_S:
        return None
    valor = db_lista[i]
    if valor <= SUELO_DB:
        return None
    if ultimo is not None and i - ultimo < ENFRIAMIENTO_S:
        return None
    historia = db_lista[max(0, i - VENTANA_BASE_S): i]
    exceso = valor - statistics.median(historia)
    if exceso < UMBRAL_EXCESO_DB:
        return None
    return {
        "tiempo": float(i),
        "exceso_db": round(exceso, 1),
        "motivo": f"Pico de volumen: +{exceso:.0f} dB sobre el minuto anterior",
    }


def detectar_momentos(db_lista: list[float]) -> list[dict]:
    """Aplica `evaluar_segundo` a toda la lista de dB (un valor por segundo)."""
    momentos: list[dict] = []
    ultimo: float | None = None
    for i in range(len(db_lista)):
        m = evaluar_segundo(db_lista, i, ultimo)
        if m:
            momentos.append(m)
            ultimo = m["tiempo"]
    return momentos


# ---------- segmentos y bufer (puro) ----------

@dataclass
class Seg:
    nombre: str
    inicio: float      # segundos desde el inicio de la grabacion
    fin: float
    bytes: int = 0


def segmentos_que_cubren(segmentos: list[Seg], a: float, b: float) -> list[Seg]:
    """Segmentos que se solapan con el tramo [a, b], en orden temporal."""
    return sorted((s for s in segmentos if s.fin > a and s.inicio < b), key=lambda s: s.inicio)


def plan_recorte(segmentos: list[Seg], a: float, b: float) -> tuple[list[Seg], float, float]:
    """(segmentos a unir, desfase de inicio dentro de la union, duracion real del tramo).

    El tramo se ajusta a lo que hay grabado. Lanza ErrorMedia si no queda nada utilizable.
    """
    cubiertos = segmentos_que_cubren(segmentos, a, b)
    if not cubiertos:
        raise ErrorMedia("Ese tramo ya no está en el búfer o todavía no se ha grabado.")
    if any(siguiente.inicio - previo.fin > .1 for previo, siguiente in zip(cubiertos, cubiertos[1:])):
        raise ErrorMedia("Falta vídeo en ese tramo del búfer. Elige un momento posterior a la interrupción.")
    a = max(a, cubiertos[0].inicio)
    b = min(b, cubiertos[-1].fin)
    if b - a < MIN_CLIP_S:
        raise ErrorMedia("Todavía no hay suficiente vídeo grabado para ese clip. Espera unos segundos.")
    return cubiertos, a - cubiertos[0].inicio, b - a


def segmentos_a_borrar(segmentos: list[Seg], max_s: float) -> list[Seg]:
    """Segmentos que quedan fuera del bufer: terminan antes de (ultimo extremo - max_s)."""
    if not segmentos:
        return []
    limite = max(s.fin for s in segmentos) - max_s
    return [s for s in segmentos if s.fin <= limite]


def leer_lista_csv(texto: str) -> list[Seg]:
    """Interpreta lineas `nombre,inicio,fin` de la lista de segmentos de FFmpeg."""
    resultado = []
    for fila in csv.reader(texto.splitlines()):
        if len(fila) < 3:
            continue
        try:
            resultado.append(Seg(fila[0], float(fila[1]), float(fila[2])))
        except ValueError:
            continue
    return resultado


# ---------- sesion ----------

def _ruta_sesion(sid: str) -> Path:
    return config.VIVO_DIR / sid


def _borrar_carpeta(carpeta: Path) -> None:
    """Borra una carpeta de bufer (con reintentos: en Windows un archivo recien cerrado puede tardar)."""
    for _ in range(5):
        shutil.rmtree(carpeta, ignore_errors=True)
        if not carpeta.exists():
            return
        time.sleep(0.3)
    log.warning("No se pudo borrar por completo %s; se reintentara al arrancar.", carpeta)


def _guardar(tabla: str, id_: str, **campos) -> None:
    try:
        db.actualizar(tabla, id_, **campos)
    except Exception:
        log.error("No se pudo guardar el estado de %s", id_, exc_info=True)


class Sesion:
    def __init__(self, id_: str, url: str, usar_chat: bool = True,
                 automaticos: bool = True, desfase_chat_s: float = 3.0,
                 composicion: dict | None = None) -> None:
        self.id = id_
        self.url = url
        self.titulo = ""
        self.estado = "conectando"        # conectando | grabando | detenido | error
        self.error: str | None = None
        self.carpeta = _ruta_sesion(id_)
        self.db: list[float] = []         # volumen (dB) de cada segundo grabado
        self.segmentos: list[Seg] = []
        self.momentos: list[dict] = []
        self.proc: subprocess.Popen | None = None
        self.parar = threading.Event()
        self.lock = threading.RLock()     # estado compartido
        self.lock_archivos = threading.RLock()   # recortes vs borrado del bufer
        self._offset: float | None = None
        self._pos_lista = 0
        self._entrada = ""
        self._stderr: deque[str] = deque(maxlen=40)
        self._ultimo_momento: float | None = None
        self._hilos: list[threading.Thread] = []
        self.usar_chat = usar_chat
        self.automaticos = automaticos
        self.desfase_chat_s = desfase_chat_s
        self.estado_chat = "conectando" if usar_chat else "desactivado"
        self.error_chat: str | None = None
        self._lector_chat: chat.LectorChat | None = None
        self._parar_chat = threading.Event()
        self._detector_chat = chat.DetectorChat()
        self._clips_pendientes: queue.Queue[str] = queue.Queue(maxsize=3)
        self._conversion_lock = threading.Lock()
        self._cancel_clip = Cancelacion()
        self.composicion = reframe.normalizar_composicion(composicion)
        self._vista_version = 0.0
        self._lock_vista = threading.Lock()
        self._cancel_vista = Cancelacion()

    # -- vida --

    def iniciar(self) -> None:
        hilo = threading.Thread(target=self._arrancar, daemon=True, name=f"vivo-{self.id[:6]}")
        self._hilos.append(hilo)
        hilo.start()

    def _fallar(self, mensaje: str) -> None:
        with self.lock:
            if self.estado in ("detenido", "error"):
                return
            self.estado, self.error = "error", mensaje
        _guardar("sesiones_vivo", self.id, estado="error", error=mensaje)

    def _arrancar(self) -> None:
        try:
            datos = resolver_directo(self.url)
            if self.parar.is_set():
                return
            self.titulo = datos["titulo"]
            self._entrada = datos["entrada"]
            self.carpeta.mkdir(parents=True, exist_ok=True)
            cmd = self._comando(datos)
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                cwd=str(self.carpeta), creationflags=media._SIN_VENTANA,
            )
        except ErrorMedia as exc:
            self._fallar(str(exc))
            return
        except Exception as exc:
            log.error("No se pudo arrancar la grabacion en vivo\n", exc_info=True)
            self._fallar(f"No se pudo iniciar la grabación: {exc}")
            return
        with self.lock:
            if self.parar.is_set():
                self._matar()
                return
            self.estado = "grabando"
        _guardar("sesiones_vivo", self.id, estado="grabando", titulo=self.titulo)
        for objetivo, nombre in ((self._leer_audio, "audio"), (self._leer_stderr, "stderr"), (self._vigilar, "bufer")):
            hilo = threading.Thread(target=objetivo, daemon=True, name=f"vivo-{nombre}-{self.id[:6]}")
            self._hilos.append(hilo)
            hilo.start()
        if self.usar_chat and not datos["prueba"]:
            self._iniciar_hilo(self._leer_chat, "chat")
        else:
            self._estado_chat("desactivado", None)
        self._iniciar_hilo(self._procesar_automaticos, "clips")

    def _iniciar_hilo(self, objetivo, nombre: str) -> None:
        hilo = threading.Thread(target=objetivo, daemon=True, name=f"vivo-{nombre}-{self.id[:6]}")
        self._hilos.append(hilo)
        hilo.start()

    def _comando(self, datos: dict) -> list[str]:
        cmd = [media.herramienta("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "warning", "-nostats"]
        # Algunas plataformas dan el audio en un flujo aparte: entonces hay dos entradas.
        entradas = [datos["entrada"]] + ([datos["entrada_audio"]] if datos.get("entrada_audio") else [])
        for entrada in entradas:
            if datos["prueba"]:
                # Lee el archivo a velocidad real y en bucle, como si fuera un directo.
                cmd += ["-re", "-stream_loop", "-1"]
            else:
                # Sin "-reconnect": con listas HLS (Twitch) hace que FFmpeg relea la lista en
                # bucle al llegar a su final y nunca llegue al video. El lector HLS ya recarga
                # la lista por su cuenta; solo se limita cuanto espera a la red.
                cmd += ["-rw_timeout", "20000000"]
                if datos["cabeceras"]:
                    cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in datos["cabeceras"].items())]
            cmd += ["-i", entrada]
        audio = f"{len(entradas) - 1}:a:0"
        # Salida 1: segmentos MPEG-TS sin recodificar, con lista CSV de inicio y fin reales.
        cmd += [
            "-map", "0:v:0?", "-map", audio + "?", "-c", "copy",
            "-f", "segment", "-segment_time", str(SEGMENTO_S), "-segment_format", "mpegts",
            "-reset_timestamps", "1", "-segment_list", "lista.csv", "-segment_list_type", "csv",
            "seg_%06d.ts",
        ]
        # Salida 2: audio mono 16 kHz por stdout para medir el volumen.
        cmd += ["-map", audio, "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]
        return cmd

    def _matar(self) -> None:
        proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def detener(self, borrar: bool = True) -> None:
        """Para la grabacion, espera a los hilos y (por defecto) borra el bufer."""
        self.parar.set()
        self._parar_chat.set()
        if self._lector_chat:
            self._lector_chat.cerrar()
        self._cancel_clip.cancelar()
        self._cancel_vista.cancelar()
        self._matar()
        for hilo in self._hilos:
            if hilo is not threading.current_thread():
                hilo.join(timeout=8)
        for tubo in (getattr(self.proc, "stdout", None), getattr(self.proc, "stderr", None)):
            try:
                if tubo:
                    tubo.close()
            except OSError:
                pass
        with self.lock:
            if self.estado != "error":
                self.estado = "detenido"
        _guardar("sesiones_vivo", self.id, estado=self.estado if self.estado == "error" else "detenido")
        if borrar:
            with self.lock_archivos:
                _borrar_carpeta(self.carpeta)

    # -- hilos --

    def _leer_stderr(self) -> None:
        proc = self.proc
        assert proc is not None and proc.stderr is not None
        try:
            for linea in proc.stderr:
                self._stderr.append(linea.decode("utf-8", "replace").rstrip())
        except (OSError, ValueError):
            pass

    def _leer_audio(self) -> None:
        import numpy as np

        proc = self.proc
        assert proc is not None and proc.stdout is not None
        por_segundo = 16000 * 2
        try:
            while not self.parar.is_set():
                bloque = proc.stdout.read(por_segundo)
                if len(bloque) < por_segundo:
                    break
                muestras = np.frombuffer(bloque, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(muestras ** 2)))
                nivel = round(20 * float(np.log10(max(rms, 1e-4))), 1)
                self._nuevo_segundo(nivel)
        except (OSError, ValueError):
            pass
        self._fin_proceso()

    def _nuevo_segundo(self, nivel: float) -> None:
        with self.lock:
            self.db.append(nivel)
            i = len(self.db) - 1
            momento = evaluar_segundo(self.db, i, self._ultimo_momento)
            if momento is not None:
                self._ultimo_momento = momento["tiempo"]
            # Da tiempo a que lleguen los lotes del chat sin convertirlos en falsas rafagas.
            momento_chat = self._detector_chat.evaluar(i - 5, self.estado_chat == "conectado") if i >= 5 else None
        if momento:
            self._registrar_momento(momento, "audio")
        if momento_chat:
            momento_chat["tiempo"] = max(0, momento_chat["tiempo"] - self.desfase_chat_s)
            self._registrar_momento(momento_chat, "chat")

    def _registrar_momento(self, momento: dict, origen: str) -> dict | None:
        automatico = origen == "chat" and self.automaticos
        estado = "esperando_video" if automatico else "nuevo"
        try:
            fila = db.insertar(
                "momentos_vivo",
                {"sesion_id": self.id, "tiempo": momento["tiempo"], "motivo": momento["motivo"],
                 "estado": estado, "origen": origen},
            )
        except Exception:
            log.error("No se pudo guardar el momento", exc_info=True)
            return None
        with self.lock:
            self.momentos.append({
                "id": fila["id"], "tiempo": momento["tiempo"], "motivo": momento["motivo"],
                "estado": estado, "proyecto_id": None, "origen": origen, "error": None,
            })
        if automatico:
            try:
                self._clips_pendientes.put_nowait(fila["id"])
            except queue.Full:
                self._estado_momento(fila["id"], estado="error", error="La cola automática está llena. Puedes crear este clip manualmente.")

        return dict(fila)

    def marcar_momento(self, nota: str) -> dict:
        with self.lock:
            if self.estado != "grabando" or not self.segmentos:
                raise ErrorMedia("Espera a que haya vídeo grabado para marcar un momento.")
            tiempo = max(s.fin for s in self.segmentos)
            fila = self._registrar_momento({"tiempo": tiempo, "motivo": nota.strip() or "Marcador manual"}, "manual")
            if fila is None:
                raise ErrorMedia("No se pudo guardar el momento. Inténtalo de nuevo.")
            return fila

    def _estado_chat(self, estado: str, error: str | None) -> None:
        with self.lock:
            self.estado_chat, self.error_chat = estado, error

    def _leer_chat(self) -> None:
        espera = 1
        while not self._parar_chat.is_set():
            try:
                self._estado_chat("conectando", None)
                lector = chat.crear_lector(self.url, self.carpeta / "chat", self._estado_chat)
                self._lector_chat = lector
                if self._parar_chat.is_set():
                    return
                for evento in lector.leer(self._parar_chat):
                    self._recibir_chat(evento)
                    espera = 1
                if self._parar_chat.is_set():
                    break
                raise chat.ErrorChat("Se perdió la conexión con el chat.")
            except Exception as exc:
                if self._parar_chat.is_set():
                    break
                mensaje = str(exc) if isinstance(exc, chat.ErrorChat) else "No se pudo conectar con el chat. Se reintentará automáticamente."
                self._estado_chat("reconectando", mensaje)
                if self._parar_chat.wait(espera):
                    break
                espera = min(30, espera * 2)
        self._estado_chat("detenido", None)

    def _recibir_chat(self, evento: chat.EventoChat) -> None:
        edad = time.time() - evento.enviado
        if not math.isfinite(edad) or edad < -5 or edad > 30:
            return
        with self.lock:
            if not self.db or self.parar.is_set():
                return
            segundo = max(0, len(self.db) - 1 - round(max(0, edad)))
            self._detector_chat.agregar(segundo, evento)

    def _estado_momento(self, mid: str, **campos) -> None:
        with self.lock:
            momento = next((m for m in self.momentos if m["id"] == mid), None)
            if momento is not None:
                momento.update(campos)
        _guardar("momentos_vivo", mid, **campos)

    def _procesar_automaticos(self) -> None:
        while not self.parar.is_set():
            try:
                mid = self._clips_pendientes.get(timeout=.5)
            except queue.Empty:
                if self.estado in ("detenido", "error"):
                    return
                continue
            try:
                self.convertir_momento(mid)
            except Exception as exc:
                mensaje = str(exc) if isinstance(exc, ErrorMedia) else "No se pudo crear el clip automático. Puedes reintentarlo."
                self._estado_momento(mid, estado="error", error=mensaje)
                log.warning("No se pudo crear un clip automatico", exc_info=True)
            finally:
                self._clips_pendientes.task_done()

    def convertir_momento(self, mid: str) -> dict:
        # La cola y los botones comparten esta conversion para impedir proyectos duplicados.
        with self._conversion_lock:
            with self.lock:
                momento = next((m for m in self.momentos if m["id"] == mid), None)
                if momento is None:
                    raise ErrorMedia("Ese momento no existe.")
                if momento.get("proyecto_id"):
                    proyecto = db.obtener("proyectos", momento["proyecto_id"])
                    if proyecto:
                        return proyecto
                if momento["tiempo"] < min((seg.inicio for seg in self.segmentos), default=0.0):
                    raise ErrorMedia("Ese momento ya está fuera del búfer.")
                a, b = max(0.0, momento["tiempo"] - ANTES_S), momento["tiempo"] + DESPUES_S
            self.esperar_cobertura(b, ESPERA_POSTERIOR_S)
            if self.parar.is_set():
                raise ErrorMedia("Se detuvo la grabación antes de crear el clip.")
            self._estado_momento(mid, estado="creando", error=None)
            nombre = f"{(self.titulo or 'Directo')[:80]} – momento {_mmss(momento['tiempo'])}"
            try:
                proyecto = self.crear_clip(a, b, nombre)
            except Exception:
                self._estado_momento(mid, estado="error", error="No se pudo crear el clip. Puedes reintentarlo.")
                raise
            self._estado_momento(mid, estado="convertido", proyecto_id=proyecto["id"], error=None)
            return proyecto

    def _fin_proceso(self) -> None:
        proc = self.proc
        assert proc is not None
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if self.parar.is_set():
            return
        self._parar_chat.set()
        if self._lector_chat:
            self._lector_chat.cerrar()
        self._leer_lista()
        time.sleep(0.2)
        detalle = " ".join(list(self._stderr)[-3:]).replace(self._entrada, "<flujo>")[-300:]
        if proc.returncode == 0:
            with self.lock:
                if self.estado == "grabando":
                    self.estado, self.error = "detenido", "El directo terminó."
            _guardar("sesiones_vivo", self.id, estado="detenido", error="El directo terminó.")
        else:
            self._fallar("Se perdió la conexión con el directo." + (f" ({detalle})" if detalle else ""))

    def _vigilar(self) -> None:
        """Lee los segmentos cerrados y borra los que salen del bufer."""
        ultimo_estado_disco = 0.0
        while not self.parar.is_set() and (self.proc is not None and self.proc.poll() is None):
            self._leer_lista()
            self._recortar_bufer()
            self._actualizar_vista()
            if time.monotonic() - ultimo_estado_disco > 30:
                ultimo_estado_disco = time.monotonic()
                try:
                    if shutil.disk_usage(self.carpeta).free < 512 * 1024**2:
                        self._fallar("Se agotó el espacio en el disco. Se detuvo la grabación.")
                        self._matar()
                        return
                except OSError:
                    pass
            self.parar.wait(1.0)

    def _actualizar_vista(self) -> None:
        """Extrae una imagen por segmento cerrado, sin volver a descargar el directo."""
        with self.lock_archivos:
            with self.lock:
                ultimo = max(self.segmentos, key=lambda s: s.fin, default=None)
                if ultimo is None or ultimo.fin <= self._vista_version:
                    return
            temporal = self.carpeta / "vista.tmp.jpg"
            try:
                media.ejecutar_ffmpeg(
                    ["-i", str(self.carpeta / ultimo.nombre),
                     "-ss", f"{max(0, ultimo.fin - ultimo.inicio - 1):.3f}", "-frames:v", "1",
                     "-vf", "scale=960:-2", "-q:v", "4", "-update", "1", str(temporal)],
                    1, self._cancel_vista,
                )
                if temporal.is_file():
                    with self._lock_vista:
                        temporal.replace(self.carpeta / "vista.jpg")
                    with self.lock:
                        self._vista_version = ultimo.fin
            except (ErrorMedia, OSError, media.Cancelado):
                log.debug("No se pudo actualizar la imagen del directo", exc_info=True)
            finally:
                temporal.unlink(missing_ok=True)

    def _leer_lista(self) -> None:
        lista = self.carpeta / "lista.csv"
        try:
            with open(lista, "rb") as f:
                f.seek(self._pos_lista)
                datos = f.read()
        except OSError:
            return
        fin = datos.rfind(b"\n")
        if fin < 0:
            return
        completo = datos[: fin + 1]
        nuevos = leer_lista_csv(completo.decode("utf-8", "replace"))
        with self.lock:
            self._pos_lista += len(completo)
            for s in nuevos:
                if self._offset is None:
                    self._offset = s.inicio
                s.inicio -= self._offset
                s.fin -= self._offset
                try:
                    s.bytes = (self.carpeta / s.nombre).stat().st_size
                except OSError:
                    s.bytes = 0
                self.segmentos.append(s)

    def _recortar_bufer(self) -> None:
        with self.lock:
            sobran = segmentos_a_borrar(self.segmentos, config.VIVO_BUFER_MIN * 60)
        if not sobran:
            return
        borrados = set()
        with self.lock_archivos:
            for s in sobran:
                try:
                    (self.carpeta / s.nombre).unlink(missing_ok=True)
                    borrados.add(s.nombre)
                except OSError:
                    pass   # abierto por otro proceso: se reintenta en la siguiente vuelta
        if borrados:
            with self.lock:
                self.segmentos = [s for s in self.segmentos if s.nombre not in borrados]

    # -- consulta --

    def cobertura(self) -> float:
        with self.lock:
            return max((s.fin for s in self.segmentos), default=0.0)

    def publico(self) -> dict:
        with self.lock:
            tamano = sum(s.bytes for s in self.segmentos)
            segundos = len(self.db)
            estimado = None
            if segundos >= 10 and self.segmentos:
                dur = max(s.fin for s in self.segmentos) - min(s.inicio for s in self.segmentos)
                if dur > 0:
                    estimado = round(tamano / dur * config.VIVO_BUFER_MIN * 60 / 1024**3, 2)
            return {
                "id": self.id,
                "titulo": self.titulo,
                "estado": self.estado,
                "error": self.error,
                "segundos": segundos,
                "cobertura_s": round(max((s.fin for s in self.segmentos), default=0.0), 1),
                "n_segmentos": len(self.segmentos),
                "tamano_mb": round(tamano / 1024**2, 1),
                "buffer_min": config.VIVO_BUFER_MIN,
                "estimado_buffer_gb": estimado,
                "volumen": self.db[-VOLUMEN_MOSTRADO_S:],
                "buffer_inicio_s": min((s.inicio for s in self.segmentos), default=0.0),
                "momentos": [{**m, "caducado": not m.get("proyecto_id") and
                              m["tiempo"] < min((s.inicio for s in self.segmentos), default=0.0)}
                             for m in self.momentos],
                "pid": self.proc.pid if self.proc else None,
                "chat_estado": self.estado_chat,
                "chat_error": self.error_chat,
                "chat_actividad": self._detector_chat.actividad(segundos - 1),
                "automaticos": self.automaticos,
                "desfase_chat_s": self.desfase_chat_s,
                "composicion": self.composicion.copy(),
                "vista_version": self._vista_version,
            }

    # -- clips --

    def esperar_cobertura(self, hasta: float, limite_s: float) -> None:
        fin = time.monotonic() + limite_s
        while self.cobertura() < hasta and time.monotonic() < fin:
            if self.parar.is_set() or self.estado in ("error", "detenido"):
                return
            self.parar.wait(0.5)

    def crear_clip(self, a: float, b: float, nombre: str) -> dict:
        """Recorta [a, b] del bufer a un MP4 y crea un proyecto normal en la cola de siempre."""
        if not config.find_tool("ffmpeg"):
            raise ErrorMedia("FFmpeg no está instalado. Ejecuta: uv run python scripts/instalar_ffmpeg.py")
        if shutil.disk_usage(config.DATA_DIR).free < MIN_LIBRE_BYTES:
            raise ErrorMedia("Queda menos de 2 GB libres en el disco de datos. Libera espacio e inténtalo de nuevo.")
        pid = db.nuevo_id()
        carpeta = pipeline.carpeta_proyecto(pid)
        carpeta.mkdir(parents=True)
        with self.lock:
            composicion = reframe.normalizar_composicion(self.composicion)
        try:
            with self.lock_archivos:
                with self.lock:
                    segmentos = list(self.segmentos)
                cubiertos, desfase, duracion = plan_recorte(segmentos, a, b)
                lista = self.carpeta / f"concat_{pid[:8]}.txt"
                lineas = []
                for s in cubiertos:
                    ruta = (self.carpeta / s.nombre).resolve().as_posix().replace("'", "'\\''")
                    lineas.append(f"file '{ruta}'")
                lista.write_text("\n".join(lineas) + "\n", encoding="utf-8")
                temporal = carpeta / "fuente.subiendo"
                try:
                    # Se recodifica solo este fragmento: asi el corte es exacto y no hay
                    # fotogramas rotos al principio (con -c copy empezaria en un fotograma clave).
                    media.ejecutar_ffmpeg(
                        ["-f", "concat", "-safe", "0", "-i", str(lista),
                         "-ss", f"{desfase:.3f}", "-t", f"{duracion:.3f}",
                         "-map", "0:v:0", "-map", "0:a:0?",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-f", "mp4", str(temporal)],
                        duracion, self._cancel_clip,
                    )
                finally:
                    lista.unlink(missing_ok=True)
            temporal.replace(carpeta / "fuente.mp4")
            proyecto = db.insertar(
                "proyectos",
                {"id": pid, "nombre": nombre[:120], "origen": "archivo", "archivo_fuente": "fuente.mp4",
                 "idioma": "auto", "estado": "en_cola", "paso": "en_cola", "mensaje": "En cola...",
                 "progreso": 0, "min_s": 15.0, "max_s": 60.0, "es_clip_vivo": 1,
                 "encuadre_vivo": composicion},
            )
        except BaseException:
            shutil.rmtree(carpeta, ignore_errors=True)
            raise
        pipeline.gestor.encolar("proyecto", pid)
        return proyecto


# ---------- estado global ----------

_sesion: Sesion | None = None
_candado = threading.Lock()


def _activa(s: Sesion | None) -> bool:
    return s is not None and s.estado in ("conectando", "grabando")


def iniciar_sesion(url: str, usar_chat: bool = True, automaticos: bool = True,
                   desfase_chat_s: float = 3.0, composicion: dict | None = None) -> Sesion:
    """Crea una sesion y empieza a conectar. Lanza HTTPException si ya hay una activa."""
    global _sesion
    url = (url or "").strip()
    if not url:
        raise HTTPException(422, "Pega el enlace del directo.")
    try:
        composicion = reframe.normalizar_composicion(composicion)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(url) > 2000:
        raise HTTPException(422, "La URL es demasiado larga.")
    try:
        if archivo_de_prueba(url) is None:
            importer.validar_url(url)
    except ErrorMedia as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not config.find_tool("ffmpeg"):
        raise HTTPException(503, "FFmpeg no esta instalado. Ejecuta: uv run python scripts/instalar_ffmpeg.py")
    config.VIVO_DIR.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(config.VIVO_DIR).free < MIN_LIBRE_BYTES:
        raise HTTPException(507, "Queda menos de 2 GB libres en el disco de datos. Libera espacio para grabar.")
    with _candado:
        if _activa(_sesion):
            raise HTTPException(409, "Ya hay una grabación en vivo en curso. Páralo antes de conectar otro directo.")
        anterior = _sesion
        fila = db.insertar("sesiones_vivo", {"url": url, "estado": "conectando"})
        _sesion = Sesion(fila["id"], url, usar_chat, automaticos, desfase_chat_s, composicion)
    if anterior is not None:
        anterior.detener()
    _sesion.iniciar()
    return _sesion


def sesion_actual() -> Sesion | None:
    return _sesion


def parar_sesion() -> None:
    """Para la grabacion y borra el bufer. Sin sesion, no hace nada."""
    global _sesion
    with _candado:
        s, _sesion = _sesion, None
    if s is not None:
        s.detener()


def recuperar() -> None:
    """Al arrancar: sesiones que quedaron grabando -> interrumpidas, y se borran los buferes huerfanos."""
    try:
        with db.conectar() as con:
            con.execute(
                "UPDATE sesiones_vivo SET estado = 'interrumpida', actualizado = ? WHERE estado IN ('conectando', 'grabando')",
                (time.time(),),
            )
    except Exception:
        log.error("No se pudieron marcar las sesiones en vivo interrumpidas", exc_info=True)
    activas = {_sesion.id} if _sesion else set()
    if config.VIVO_DIR.is_dir():
        for carpeta in config.VIVO_DIR.iterdir():
            if carpeta.is_dir() and carpeta.name not in activas:
                _borrar_carpeta(carpeta)


def detener_todo() -> None:
    """Al cerrar la aplicacion: no deja FFmpeg grabando ni carpetas de bufer."""
    try:
        parar_sesion()
    except Exception:
        log.error("Fallo al detener el modo en vivo", exc_info=True)


# ---------- API ----------

router = APIRouter(prefix="/api/vivo")


class SesionNueva(BaseModel):
    url: str = Field(max_length=2000)
    usar_chat: bool = True
    automaticos: bool = True
    desfase_chat_s: float = Field(3, ge=0, le=30, allow_inf_nan=False)
    composicion: dict | None = None


class ClipVivo(BaseModel):
    segundos: int | None = None
    momento_id: str | None = Field(None, max_length=64)


def _mmss(t: float) -> str:
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


@router.post("", status_code=201)
def crear_sesion(datos: SesionNueva) -> dict:
    return iniciar_sesion(datos.url, datos.usar_chat, datos.automaticos, datos.desfase_chat_s, datos.composicion).publico()


@router.get("")
def ver_sesion() -> dict | None:
    s = sesion_actual()
    return s.publico() if s else None


def _sesion_por_id(sid: str) -> Sesion:
    s = sesion_actual()
    if s is None or s.id != sid:
        raise HTTPException(404, "Esa sesión en vivo ya no existe.")
    return s


@router.get("/{sid}/vista.jpg")
def imagen_directo(sid: str) -> Response:
    s = _sesion_por_id(sid)
    with s._lock_vista:
        try:
            imagen = (s.carpeta / "vista.jpg").read_bytes()
        except OSError as exc:
            raise HTTPException(404, "Todavía no hay una imagen del directo.") from exc
    return Response(imagen, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


class EncuadreVivo(BaseModel):
    composicion: dict


@router.put("/{sid}/encuadre")
def cambiar_encuadre(sid: str, datos: EncuadreVivo) -> dict:
    s = _sesion_por_id(sid)
    try:
        composicion = reframe.normalizar_composicion(datos.composicion)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with s.lock:
        s.composicion = composicion
    return s.publico()


class MarcadorVivo(BaseModel):
    nota: str = Field("", max_length=160)


@router.post("/{sid}/momentos", status_code=201)
def marcar_momento(sid: str, datos: MarcadorVivo) -> dict:
    try:
        return _sesion_por_id(sid).marcar_momento(datos.nota)
    except ErrorMedia as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{sid}/clip", status_code=201)
def crear_clip(sid: str, datos: ClipVivo) -> dict:
    s = _sesion_por_id(sid)
    if (datos.segundos is None) == (datos.momento_id is None):
        raise HTTPException(422, "Indica los segundos o el momento, pero no los dos.")
    titulo = (s.titulo or "Directo")[:80]
    try:
        if datos.momento_id is not None:
            with s.lock:
                momento = next((m for m in s.momentos if m["id"] == datos.momento_id), None)
            if momento is None:
                raise HTTPException(404, "Ese momento no existe.")
            proyecto = s.convertir_momento(datos.momento_id)
        else:
            if datos.segundos not in ULTIMOS_S:
                raise HTTPException(422, "Elige 30, 60 o 90 segundos.")
            momento = None
            b = s.cobertura()
            a = max(0.0, b - datos.segundos)
            nombre = f"{titulo} – últimos {datos.segundos} s"
            proyecto = s.crear_clip(a, b, nombre)
    except ErrorMedia as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"proyecto_id": proyecto["id"], "nombre": proyecto["nombre"]}


@router.post("/{sid}/parar")
def parar(sid: str) -> dict:
    _sesion_por_id(sid)
    parar_sesion()
    return {"ok": True}
