"""Encuadre vertical: propone la posicion horizontal del recorte 9:16 buscando rostros.

Metodo: se muestrean fotogramas del fragmento, se detecta el rostro mas grande con el
clasificador Haar frontal de OpenCV y se usa la mediana de su posicion horizontal.
Limitaciones: el recorte es fijo durante todo el clip (no sigue a quien se mueve ni
cambia entre hablantes), solo detecta rostros de frente y puede fallar con poca luz.
Si no hay detecciones suficientes devuelve None y se usa el centro.
"""

from __future__ import annotations

import statistics
from pathlib import Path

MUESTRAS = 24
MIN_PROPORCION = 0.3


def recorte_desde_centro(centro_x: float, ancho: int, alto: int) -> float:
    """Convierte un centro horizontal (0..1 del ancho) en la posicion del recorte (0..1)."""
    ancho_recorte = alto * 9 / 16
    if ancho <= ancho_recorte + 1:
        return 0.5
    izquierda = centro_x * ancho - ancho_recorte / 2
    return max(0.0, min(1.0, izquierda / (ancho - ancho_recorte)))


def detectar_recorte(video: Path, inicio: float, fin: float) -> float | None:
    """Devuelve recorte_x (0..1) centrado en el rostro predominante, o None."""
    try:
        import cv2
    except Exception:
        return None
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            return None
        clasificador = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if clasificador.empty():
            return None
        centros: list[float] = []
        ancho = alto = 0
        total = 0
        paso = (fin - inicio) / MUESTRAS
        for i in range(MUESTRAS):
            cap.set(cv2.CAP_PROP_POS_MSEC, (inicio + paso * (i + 0.5)) * 1000)
            ok, cuadro = cap.read()
            if not ok or cuadro is None:
                continue
            total += 1
            alto, ancho = cuadro.shape[:2]
            gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)
            lado_min = max(40, int(alto * 0.12))
            rostros = clasificador.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=6, minSize=(lado_min, lado_min))
            if len(rostros):
                x, _, w, _ = max(rostros, key=lambda r: r[2] * r[3])
                centros.append((x + w / 2) / ancho)
        if total == 0 or len(centros) < max(2, total * MIN_PROPORCION):
            return None
        return round(recorte_desde_centro(statistics.median(centros), ancho, alto), 3)
    except Exception:
        return None
    finally:
        cap.release()
