"""Encuadre alternativo por planos, con zona de tolerancia y reinicio en cortes.

Adapta las reglas de SmoothedCameraman de OpenShorts (MIT). Usa YuNet local
y PySceneDetect. La trayectoria resultante sirve a la vista previa y al MP4.
"""
from __future__ import annotations

import math
import json
from pathlib import Path
import statistics

from . import media, reframe


class CamaraEstable:
    def __init__(self, ancho_visible: float):
        self.centro = None
        self.tolerancia = ancho_visible * .25
        self.pendiente = None
        self.confirmaciones = 0

    def actualizar(self, objetivo: float | None, intervalo: float) -> float:
        if self.centro is None:
            if objetivo is None:
                return .5
            self.centro = objetivo
        if objetivo is None:
            self.pendiente = None
            self.confirmaciones = 0
            return self.centro
        delta = objetivo - self.centro
        if abs(delta) <= self.tolerancia:
            self.pendiente = None
            self.confirmaciones = 0
            return self.centro
        if self.pendiente is None or abs(objetivo - self.pendiente) > self.tolerancia:
            self.confirmaciones = 0
        self.pendiente = objetivo
        self.confirmaciones += 1
        if self.confirmaciones >= 3:
            limite = .18 * intervalo
            self.centro += max(-limite, min(limite, delta))
        return self.centro


def detectar_planos(video: Path, inicio: float, fin: float, cancel=None, progreso=None) -> list[tuple[float, float]]:
    from scenedetect import ContentDetector, FrameTimecode, SceneManager, open_video

    fuente = open_video(str(video))
    fuente.seek(FrameTimecode(float(inicio), fuente.frame_rate))
    gestor = SceneManager()
    class DetectorCancelable(ContentDetector):
        def process_frame(self, frame_num, frame_img):
            if cancel and cancel.activa:
                gestor.stop()
            if progreso:
                tiempo = frame_num.seconds if hasattr(frame_num, "seconds") else frame_num / fuente.frame_rate
                progreso(max(0, min(1, (tiempo - inicio) / (fin - inicio))))
            return super().process_frame(frame_num, frame_img)
    gestor.add_detector(DetectorCancelable(threshold=27, min_scene_len=max(1, round(fuente.frame_rate * .8))))
    gestor.detect_scenes(fuente, end_time=FrameTimecode(float(fin), fuente.frame_rate))
    if cancel:
        cancel.comprobar()
    planos = [(max(inicio, a.seconds), min(fin, b.seconds))
              for a, b in gestor.get_scene_list(start_in_scene=True)]
    return [(a, b) for a, b in planos if b > a] or [(inicio, fin)]


def detectar(video: Path, inicio: float, fin: float, *, cancel=None, progreso=None, checkpoint: Path | None = None) -> dict | None:
    import cv2

    if not math.isfinite(inicio) or not math.isfinite(fin) or not 0 < fin - inicio <= 600:
        raise media.ErrorMedia("El seguimiento por planos admite clips de hasta 10 minutos.")
    if not video.is_file():
        raise media.ErrorMedia("El video del proyecto todavía no está disponible.")
    cancel = cancel or media.Cancelacion()
    progreso = progreso or (lambda _: None)
    cancel.comprobar()
    cache = {"planos": [], "resultados": []}
    if checkpoint and checkpoint.is_file():
        try:
            anterior_cache = json.loads(checkpoint.read_text(encoding="utf-8"))
            planos_cache = anterior_cache["planos"]
            resultados_cache = anterior_cache["resultados"]
            validos = isinstance(planos_cache, list) and isinstance(resultados_cache, list)
            validos = validos and len(resultados_cache) <= len(planos_cache)
            validos = validos and all(inicio <= a < b <= fin for a, b in planos_cache)
            for resultado_cache in resultados_cache:
                validos = validos and 0 <= resultado_cache["rostros"] <= resultado_cache["total"]
                validos = validos and resultado_cache["ancho"] > 0 and resultado_cache["alto"] > 0
                validos = validos and all(inicio <= p["tiempo"] <= fin and 0 <= p["centro_x"] <= 1
                                          for p in resultado_cache["muestras"])
            if validos:
                cache = anterior_cache
        except (OSError, ValueError, KeyError, TypeError):
            pass
    def guardar_checkpoint():
        if checkpoint:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temporal = checkpoint.with_suffix(".tmp")
            temporal.write_text(json.dumps(cache), encoding="utf-8")
            temporal.replace(checkpoint)
    try:
        planos = cache["planos"] or detectar_planos(video, inicio, fin, cancel, lambda p: progreso(p * .35))
        cache["planos"] = planos
        guardar_checkpoint()
    except (OSError, ValueError, cv2.error) as exc:
        raise media.ErrorMedia("No se pudieron analizar los planos del video.") from exc
    detector = reframe._crear_yunet(cv2)
    if detector is None:
        raise media.ErrorMedia("Falta el detector YuNet incluido con ClipStudio. Reinstala la aplicación.")
    cap = cv2.VideoCapture(str(video))
    trayectoria, rostros = [], 0
    total = 0
    ancho = alto = 0
    # Repartir el análisis entre todas las tomas y aumentar el presupuesto con
    # su cantidad. Cada toma conserva muestras suficientes para confirmar movimiento.
    presupuesto = max(96, min(1200, len(planos) * 8))
    try:
        for numero, (comienzo, final) in enumerate(planos):
            cancel.comprobar()
            if numero < len(cache["resultados"]):
                resultado = cache["resultados"][numero]
                muestras = resultado["muestras"]
                rostros += resultado["rostros"]
                total += resultado["total"]
                ancho, alto = resultado["ancho"], resultado["alto"]
                if trayectoria and muestras:
                    trayectoria.append({"tiempo": round(comienzo - .001, 3), "centro_x": trayectoria[-1]["centro_x"]})
                trayectoria.extend(muestras)
                progreso(.35 + .65 * (numero + 1) / len(planos))
                continue
            muestras = []
            caras_plano = total_plano = 0
            anterior = None
            cantidad = max(4, min(math.ceil((final - comienzo) * 4),
                                  int(presupuesto * (final - comienzo) / (fin - inicio))))
            paso = (final - comienzo) / cantidad
            camara = None
            for i in range(cantidad):
                cancel.comprobar()
                progreso(.35 + .65 * (numero + i / cantidad) / len(planos))
                tiempo = comienzo + i * paso
                cap.set(cv2.CAP_PROP_POS_MSEC, tiempo * 1000)
                ok, cuadro = cap.read()
                if not ok:
                    continue
                alto, ancho = cuadro.shape[:2]
                escala = min(1, 640 / max(ancho, alto))
                cuadro = cv2.resize(cuadro, (round(ancho * escala), round(alto * escala)))
                h, w = cuadro.shape[:2]
                candidatos = [(x / w, y / h, rw / w, rh / h)
                              for x, y, rw, rh in reframe._rostros_yunet(detector, cuadro)]
                rostro = reframe._elegir_rostro(candidatos, anterior, paso)
                if rostro is None and i * paso >= 1.5:
                    rostro = reframe._elegir_rostro(candidatos, None, paso)
                if rostro is not None:
                    anterior = rostro
                    caras_plano += 1
                total_plano += 1
                if camara is None:
                    camara = CamaraEstable(min(1, alto * 9 / 16 / ancho))
                centro = camara.actualizar(reframe._centro(rostro)[0] if rostro else None, paso)
                muestras.append({"tiempo": round(tiempo, 3), "centro_x": round(centro, 5)})
            rostros += caras_plano
            total += total_plano
            cache["resultados"].append({"muestras": muestras, "rostros": caras_plano,
                                        "total": total_plano, "ancho": ancho, "alto": alto})
            guardar_checkpoint()
            if muestras:
                # Mantener el plano hasta el corte. La transición de 1 ms comparte
                # el mismo contrato de interpolación del reproductor y FFmpeg.
                if trayectoria:
                    trayectoria.append({"tiempo": round(comienzo - .001, 3),
                                        "centro_x": trayectoria[-1]["centro_x"]})
                trayectoria.extend(muestras)
        cancel.comprobar()
        progreso(1)
        if rostros < max(2, total * .3):
            return None
        centro = statistics.median(p["centro_x"] for p in trayectoria)
        return {"recorte_x": reframe.recorte_desde_centro(centro, ancho, alto),
                "trayectoria": trayectoria, "cobertura": round(rostros / total, 2),
                "planos": len(planos)}
    except cv2.error as exc:
        raise media.ErrorMedia("No se pudo completar el seguimiento por planos.") from exc
    finally:
        cap.release()
