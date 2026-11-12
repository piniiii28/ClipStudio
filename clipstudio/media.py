"""Envoltorios de FFmpeg / ffprobe: sondeo, audio, proxy de previsualizacion y exportacion."""

from __future__ import annotations

import json
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable

from . import config

Progreso = Callable[[float], None]

_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ErrorMedia(Exception):
    """Error con un mensaje pensado para mostrarse a la persona usuaria."""


class Cancelado(Exception):
    pass


class Cancelacion:
    """Senal de cancelacion que ademas termina el subproceso en curso."""

    def __init__(self) -> None:
        self._evento = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def cancelar(self) -> None:
        self._evento.set()
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.kill()

    @property
    def activa(self) -> bool:
        return self._evento.is_set()

    def comprobar(self) -> None:
        if self.activa:
            raise Cancelado()

    def adjuntar(self, proc: subprocess.Popen | None) -> None:
        with self._lock:
            self._proc = proc
            if proc and self.activa and proc.poll() is None:
                proc.kill()


def herramienta(nombre: str) -> str:
    ruta = config.find_tool(nombre)
    if not ruta:
        raise ErrorMedia(
            f"No se encontro {nombre}. Ejecuta: uv run python scripts/instalar_ffmpeg.py"
        )
    return ruta


def sondear(ruta: Path) -> dict:
    """Devuelve duracion, dimensiones (ya rotadas) y si hay audio."""
    cmd = [
        herramienta("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(ruta),
    ]
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, creationflags=_SIN_VENTANA,
        )
    except subprocess.TimeoutExpired as exc:
        raise ErrorMedia("El analisis del archivo tardo demasiado. Puede estar danado.") from exc
    if res.returncode != 0:
        raise ErrorMedia("El archivo no es un video valido o esta danado.")
    datos = json.loads(res.stdout or "{}")
    streams = datos.get("streams", [])
    pistas_video = [s for s in streams if s.get("codec_type") == "video"]
    # Las caratulas incrustadas cuentan como pista de video: se descartan y se recuerda
    # la posicion de la pista real para que ffmpeg use exactamente la misma.
    video = next((s for s in pistas_video if not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ErrorMedia("El archivo no contiene una pista de video.")
    try:
        duracion = float(datos.get("format", {}).get("duration") or video.get("duration") or 0)
    except ValueError:
        duracion = 0.0
    if duracion <= 0:
        raise ErrorMedia("No se pudo determinar la duracion del video.")
    ancho, alto = int(video.get("width") or 0), int(video.get("height") or 0)
    rotacion = 0
    for extra in video.get("side_data_list", []) or []:
        if "rotation" in extra:
            rotacion = int(float(extra["rotation"]))
    if abs(rotacion) % 180 == 90:
        ancho, alto = alto, ancho
    if ancho <= 0 or alto <= 0:
        raise ErrorMedia("No se pudieron leer las dimensiones del video.")
    return {
        "duracion": duracion,
        "ancho": ancho,
        "alto": alto,
        "tiene_audio": audio is not None,
        "codec_video": video.get("codec_name"),
        "pista_video": pistas_video.index(video),
    }


def sondear_audio(ruta: Path) -> float:
    """Duracion en segundos de un archivo de audio."""
    res = subprocess.run(
        [herramienta("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
        capture_output=True, text=True, timeout=120, creationflags=_SIN_VENTANA,
    )
    try:
        return float(res.stdout.strip())
    except ValueError as exc:
        raise ErrorMedia("No se pudo leer la duracion del audio.") from exc


def ejecutar_ffmpeg(
    args: list[str],
    duracion: float,
    cancel: Cancelacion,
    progreso: Progreso | None = None,
    cwd: Path | None = None,
) -> None:
    """Ejecuta ffmpeg informando progreso (0..1) y permitiendo cancelar."""
    cancel.comprobar()
    cmd = [
        herramienta("ffmpeg"), "-hide_banner", "-nostdin", "-y",
        "-loglevel", "error", "-progress", "pipe:1", "-nostats", *args,
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", cwd=str(cwd) if cwd else None,
        creationflags=_SIN_VENTANA,
    )
    cancel.adjuntar(proc)
    errores: deque[str] = deque(maxlen=40)

    def leer_errores() -> None:
        assert proc.stderr is not None
        for linea in proc.stderr:
            errores.append(linea.rstrip())

    hilo = threading.Thread(target=leer_errores, daemon=True)
    hilo.start()
    try:
        assert proc.stdout is not None
        for linea in proc.stdout:
            if linea.startswith("out_time_us=") and progreso and duracion > 0:
                try:
                    seg = int(linea.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                progreso(max(0.0, min(1.0, seg / duracion)))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        hilo.join(timeout=5)
        cancel.adjuntar(None)
    if cancel.activa:
        raise Cancelado()
    if proc.returncode != 0:
        detalle = "\n".join(errores)[-1500:]
        raise ErrorMedia(f"FFmpeg no pudo procesar el video.\n{detalle}".strip())


def extraer_audio(fuente: Path, destino: Path, duracion: float, cancel: Cancelacion, progreso: Progreso) -> None:
    """Audio mono a 16 kHz, el formato que espera el transcriptor."""
    ejecutar_ffmpeg(
        ["-i", str(fuente), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(destino)],
        duracion, cancel, progreso,
    )


def crear_proxy(
    fuente: Path, destino: Path, duracion: float, cancel: Cancelacion, progreso: Progreso, pista_video: int = 0
) -> None:
    """MP4 H.264 ligero para previsualizar en el navegador con busqueda rapida."""
    ejecutar_ffmpeg(
        ["-i", str(fuente), "-map", f"0:v:{pista_video}", "-map", "0:a:0?",
         # Dimensiones pares: libx264 con yuv420p no admite alto o ancho impar.
         "-vf", "scale=-2:'max(2,trunc(min(720,ih)/2)*2)',setsar=1", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "26", "-pix_fmt", "yuv420p", "-g", "30", "-c:a", "aac", "-b:a", "128k",
         "-ac", "2", "-movflags", "+faststart", str(destino)],
        duracion, cancel, progreso,
    )


def filtro_encuadre(
    encuadre: str, recorte_x: float, con_subtitulos: bool, archivo_ass: str = "subs.ass", pista_video: int = 0,
    color_fondo: str | None = None,
    proporcion_juego: int = 45,
    efecto_fondo: str = "difuminado",
    difuminado: int = 24,
) -> str:
    """Construye el filter_complex para una salida vertical 9:16."""
    w, h = config.OUT_W, config.OUT_H
    x = max(0.0, min(1.0, float(recorte_x)))
    if encuadre == "dividido":
        # Video del clip arriba y video de juego (entrada 1) abajo. Las alturas son pares.
        prop = max(25, min(60, int(proporcion_juego)))
        hb = int(h * prop / 100) // 2 * 2
        ht = h - hb
        grafo = (
            f"[0:v:{pista_video}]scale={w}:{ht}:force_original_aspect_ratio=increase,"
            f"crop={w}:{ht}:(iw-{w})*{x:.4f}:(ih-{ht})/2,setsar=1[top];"
            f"[1:v:0]scale={w}:{hb}:force_original_aspect_ratio=increase,crop={w}:{hb},setsar=1[bot];"
            f"[top][bot]vstack=inputs=2[v0]"
        )
    elif encuadre == "ajustar" and color_fondo:
        # Video completo centrado sobre un color solido (#RRGGBB ya validado).
        grafo = (
            f"[0:v:{pista_video}]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x{color_fondo.lstrip('#')},setsar=1[v0]"
        )
    elif encuadre == "ajustar":
        # Fondo: copia del propio video ampliada y desenfocada, opcionalmente oscurecida o en gris.
        radio = max(4, min(50, int(difuminado)))
        extra = {"difuminado_oscuro": ",eq=brightness=-0.22", "difuminado_gris": ",hue=s=0"}.get(efecto_fondo, "")
        grafo = (
            f"[0:v:{pista_video}]split=2[fa][fb];"
            f"[fa]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur={radio}:2{extra}[bg];"
            f"[fb]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v0]"
        )
    else:
        grafo = (
            f"[0:v:{pista_video}]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:(iw-{w})*{x:.4f}:(ih-{h})/2,setsar=1[v0]"
        )
    if con_subtitulos:
        grafo += f";[v0]subtitles={archivo_ass}[v]"
    else:
        grafo += ";[v0]null[v]"
    return grafo


def exportar_clip(
    fuente: Path,
    destino: Path,
    inicio: float,
    fin: float,
    encuadre: str,
    recorte_x: float,
    archivo_ass: Path | None,
    cancel: Cancelacion,
    progreso: Progreso,
    pista_video: int = 0,
    color_fondo: str | None = None,
    juego: Path | None = None,
    juego_inicio: float = 0.0,
    proporcion_juego: int = 45,
    efecto_fondo: str = "difuminado",
    difuminado: int = 24,
) -> None:
    """Corta [inicio, fin], reencuadra a 1080x1920, quema subtitulos y codifica H.264 + AAC."""
    duracion = fin - inicio
    if duracion <= 0:
        raise ErrorMedia("El clip no tiene duracion: el fin debe ser mayor que el inicio.")
    if encuadre == "dividido" and juego is None:
        raise ErrorMedia("El encuadre dividido necesita un video de fondo. Añade alguno en la carpeta de fondos.")
    # ffmpeg se ejecuta en la carpeta del .ass y lo referencia por nombre: asi se evita
    # el escapado de rutas de Windows (C:\...) dentro del filtro "subtitles".
    cwd = archivo_ass.parent if archivo_ass else destino.parent
    entradas = ["-ss", f"{inicio:.3f}", "-t", f"{duracion:.3f}", "-i", str(fuente)]
    if encuadre == "dividido":
        # El juego se repite en bucle; el -t de salida corta la salida. Su audio no se mapea.
        entradas += ["-stream_loop", "-1", "-ss", f"{juego_inicio:.3f}", "-i", str(juego)]
    grafo = filtro_encuadre(
        encuadre, recorte_x, archivo_ass is not None, archivo_ass.name if archivo_ass else "",
        pista_video, color_fondo, proporcion_juego, efecto_fondo, difuminado,
    )
    ejecutar_ffmpeg(
        [*entradas,
         "-filter_complex", grafo, "-map", "[v]", "-map", "0:a:0?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart",
         "-t", f"{duracion:.3f}", str(destino)],
        duracion, cancel, progreso, cwd=cwd,
    )
