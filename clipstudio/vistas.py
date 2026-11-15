"""Fotogramas, portadas y ondas locales con cache acotada por proyecto."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import threading

from . import cortes, media

_CANDADOS = [threading.Lock() for _ in range(16)]
_TRABAJOS = threading.BoundedSemaphore(2)
_LIMPIEZA = threading.Lock()
MAX_ARCHIVOS = 80


def momento_conservado(clip: dict, momento: float | None = None) -> float:
    tramos = cortes.tramos_conservados(clip["inicio"], clip["fin"], clip.get("cortes") or [])
    if not tramos:
        raise ValueError("El clip no conserva ningún fotograma.")
    if momento is None:
        a, b = tramos[0]
        return (a + b) / 2
    if not any(a <= momento < b for a, b in tramos):
        raise ValueError("Elige un fotograma dentro del clip y fuera de sus cortes.")
    return momento


def imagen(fuente: Path, carpeta: Path, tipo: str, momento: float = 0,
           inicio: float = 0, fin: float = 0) -> bytes:
    """La onda usa tiempos de fuente, igual que la linea de tiempo del editor."""
    if not fuente.is_file():
        raise media.ErrorMedia("La vista previa todavía no está disponible.")
    if tipo not in ("miniatura", "portada", "onda"):
        raise ValueError("Tipo de imagen no válido.")
    stat = fuente.stat()
    clave = hashlib.sha256(json.dumps([2, stat.st_size, stat.st_mtime_ns, tipo, round(momento, 3), inicio, fin]).encode()).hexdigest()[:24]
    cache = carpeta / "vistas"
    destino = cache / (clave + (".png" if tipo == "onda" else ".jpg"))
    with _CANDADOS[int(clave[:4], 16) % len(_CANDADOS)]:
        with _LIMPIEZA:
            if destino.is_file():
                return destino.read_bytes()
        with _TRABAJOS:
            cache.mkdir(parents=True, exist_ok=True)
            temporal = destino.with_name(destino.stem + ".tmp" + destino.suffix)
            cmd = [media.herramienta("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
            if tipo == "onda":
                if not 0 < fin - inicio <= 600:
                    raise ValueError("La onda admite fragmentos de hasta 600 segundos.")
                cmd += ["-ss", str(inicio), "-t", str(fin - inicio), "-i", str(fuente),
                        "-filter_complex", "[0:a:0]aformat=channel_layouts=mono,showwavespic=s=1000x100:colors=0xc4a5ff[v]",
                        "-map", "[v]"]
            else:
                cmd += ["-i", str(fuente), "-ss", str(momento)]
                filtro = "scale=480:-2" if tipo == "miniatura" else (
                    "split[bg][fg];[bg]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=20:2[blur];"
                    "[fg]scale=720:1280:force_original_aspect_ratio=decrease[front];[blur][front]overlay=(W-w)/2:(H-h)/2")
                cmd += ["-filter_complex", filtro]
            cmd += ["-frames:v", "1", "-threads", "1", "-update", "1", str(temporal)]
            try:
                resultado = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=media._SIN_VENTANA)
                if resultado.returncode or not temporal.is_file() or temporal.stat().st_size == 0:
                    raise media.ErrorMedia("No se pudo generar la imagen. Comprueba que el fragmento contiene la pista necesaria.")
                temporal.replace(destino)
            except subprocess.TimeoutExpired as exc:
                raise media.ErrorMedia("La generación de la imagen tardó demasiado. Puedes reintentarlo.") from exc
            finally:
                temporal.unlink(missing_ok=True)
            # Solo auxiliares propios, nunca fuentes o exportaciones del proyecto.
            with _LIMPIEZA:
                archivos = sorted((p for p in cache.iterdir() if p.suffix in (".jpg", ".png") and ".tmp" not in p.name), key=lambda p: p.stat().st_mtime)
                for antiguo in archivos[:max(0, len(archivos) - MAX_ARCHIVOS)]:
                    if antiguo != destino:
                        try:
                            antiguo.unlink()
                        except OSError:
                            pass
                return destino.read_bytes()
