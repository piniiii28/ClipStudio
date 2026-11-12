"""Seguimiento horizontal de rostros con detectores locales de frente y perfil.

Suaviza una trayectoria compartida por la vista previa y la exportacion. Con varias
personas prioriza la continuidad espacial. No identifica al hablante por el audio.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path

MUESTRAS = 24
MIN_PROPORCION = 0.3


def normalizar_composicion(datos: dict | None) -> dict:
    """Regiones relativas al video completo, independientes de su resolucion."""
    datos = {} if datos is None else datos
    if not isinstance(datos, dict):
        raise ValueError("El encuadre debe ser un objeto.")
    modo = datos.get("modo", "mixto")
    if modo not in ("mixto", "camara", "gameplay"):
        raise ValueError("Elige cámara, gameplay o cámara y gameplay.")
    salida = {"modo": modo}
    for nombre in ("camara", "juego"):
        region = datos.get(nombre)
        if region is None:
            salida[nombre] = None if nombre == "camara" else {"x": 0, "y": 0, "ancho": 1, "alto": 1}
            continue
        claves = ("x", "y", "ancho", "alto")
        if not isinstance(region, dict) or any(
            not isinstance(region.get(k), (int, float)) or isinstance(region[k], bool)
            or not math.isfinite(region[k]) for k in claves
        ):
            raise ValueError("Cada zona necesita x, y, ancho y alto numéricos.")
        x, y, ancho, alto = (float(region[k]) for k in claves)
        if x < 0 or y < 0 or ancho < .02 or alto < .02 or x + ancho > 1.000001 or y + alto > 1.000001:
            raise ValueError("Las zonas deben quedar dentro de la imagen y medir al menos un 2 %.")
        salida[nombre] = dict(zip(claves, (x, y, min(ancho, 1 - x), min(alto, 1 - y))))
    proporcion = datos.get("camara_porcentaje", 30)
    if not isinstance(proporcion, (int, float)) or not math.isfinite(proporcion) or not 20 <= proporcion <= 50:
        raise ValueError("La cámara debe ocupar entre el 20 y el 50 % del alto.")
    salida["camara_porcentaje"] = int(proporcion)
    return salida


def detectar_camara(video: Path, inicio: float, fin: float) -> dict | None:
    """Busca una cara persistente con YuNet y estima una zona con cabeza y hombros."""
    modelo = Path(__file__).parent / "modelos" / "face_detection_yunet_2023mar.onnx"
    if modelo.is_file() and math.isfinite(inicio) and math.isfinite(fin) and fin > inicio:
        import cv2

        cap = cv2.VideoCapture(str(video))
        try:
            detector = cv2.FaceDetectorYN.create(str(modelo), "", (640, 360), .7, .3, 5000)
            grupos = []
            validos = 0
            for i in range(16):
                cap.set(cv2.CAP_PROP_POS_MSEC, (inicio + (fin - inicio) * (i + .5) / 16) * 1000)
                ok, cuadro = cap.read()
                if not ok:
                    continue
                validos += 1
                escala = min(1, 640 / cuadro.shape[1])
                cuadro = cv2.resize(cuadro, (round(cuadro.shape[1] * escala), round(cuadro.shape[0] * escala)))
                h, w = cuadro.shape[:2]
                detector.setInputSize((w, h))
                _, rostros = detector.detect(cuadro)
                for rostro in ([] if rostros is None else rostros):
                    x, y, ancho, alto = (float(v) for v in rostro[:4])
                    if ancho < 12 or alto < 12:
                        continue
                    caja = (max(0, x / w), max(0, y / h), ancho / w, alto / h)
                    cx, cy = caja[0] + caja[2] / 2, caja[1] + caja[3] / 2
                    grupo = next((g for g in grupos if abs(g[0][1][0] + g[0][1][2] / 2 - cx) < .08
                                  and abs(g[0][1][1] + g[0][1][3] / 2 - cy) < .1), None)
                    if grupo is None:
                        grupo = []
                        grupos.append(grupo)
                    grupo.append((i, caja))
            estables = [g for g in grupos if len({i for i, _ in g}) >= max(3, validos * .3)]
            if estables:
                mejor = max(estables, key=lambda g: len({i for i, _ in g}) * statistics.median(c[2] * c[3] for _, c in g))
                return _region_camara([c for _, c in mejor])
        except (cv2.error, OSError):
            pass
        finally:
            cap.release()
    resultado = detectar_seguimiento(video, inicio, fin)
    return resultado.get("camara") if resultado else None


def _region_camara(caras: list[tuple]) -> dict:
    fx, fy, fw, fh = (statistics.median(c[i] for c in caras) for i in range(4))
    x, y = max(0, fx - fw * 1.5), max(0, fy - fh * .6)
    return {"x": x, "y": y, "ancho": min(1 - x, fw * 4), "alto": min(1 - y, fh * 3.6)}


def suavizar_trayectoria(muestras: list[dict]) -> list[dict]:
    """Elimina detecciones aisladas y limita la velocidad del movimiento horizontal."""
    salida = []
    for i, muestra in enumerate(muestras):
        vecinos = muestras[max(0, i - 1):i + 2]
        centro = statistics.median(p["centro_x"] for p in vecinos)
        if salida:
            anterior = salida[-1]
            # Zona muerta para evitar vibraciones y velocidad maxima de 18 % del ancho/s.
            delta = centro - anterior["centro_x"]
            limite = 0.18 * (muestra["tiempo"] - anterior["tiempo"])
            centro = anterior["centro_x"] + (max(-limite, min(limite, delta)) if abs(delta) > 0.015 else 0)
        salida.append({"tiempo": round(muestra["tiempo"], 3), "centro_x": round(centro, 5)})
    return salida


def expresion_centro(trayectoria: list[dict], inicio: float = 0) -> str:
    """Interpolacion lineal para FFmpeg, evaluada antes de quitar tramos del clip."""
    partes = [f"{trayectoria[0]['centro_x']:.5f}"]
    for a, b in zip(trayectoria, trayectoria[1:]):
        delta = b["centro_x"] - a["centro_x"]
        if abs(delta) >= 0.00001:
            partes.append(
                f"({delta:.5f})*clip((t-({a['tiempo'] - inicio:.3f}))/"
                f"{b['tiempo'] - a['tiempo']:.3f},0,1)"
            )
    # Una suma larga sin agrupar agota la profundidad del analizador de FFmpeg.
    # Agrupar por pares mantiene la profundidad logaritmica con 120 muestras.
    while len(partes) > 1:
        partes = ["(" + "+".join(partes[i:i + 2]) + ")" for i in range(0, len(partes), 2)]
    return partes[0]


def recorte_desde_centro(centro_x: float, ancho: int, alto: int) -> float:
    """Convierte un centro horizontal (0..1 del ancho) en la posicion del recorte (0..1)."""
    ancho_recorte = alto * 9 / 16
    if ancho <= ancho_recorte + 1:
        return 0.5
    izquierda = centro_x * ancho - ancho_recorte / 2
    return max(0.0, min(1.0, izquierda / (ancho - ancho_recorte)))


def detectar_recorte(video: Path, inicio: float, fin: float) -> float | None:
    """Devuelve recorte_x (0..1) centrado en el rostro predominante, o None."""
    resultado = detectar_seguimiento(video, inicio, fin)
    return resultado["recorte_x"] if resultado else None


def detectar_seguimiento(video: Path, inicio: float, fin: float) -> dict | None:
    """Muestrea hasta 120 fotogramas y sigue el rostro mas cercano al anterior.

    Los tiempos son absolutos respecto del video fuente. Mantiene la posicion durante
    perdidas breves y vuelve al centro tras 1,5 s. Prioriza la continuidad entre rostros.
    """
    if not math.isfinite(inicio) or not math.isfinite(fin) or fin <= inicio:
        return None
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
        perfil = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
        muestras = []
        anterior = None
        ultimo_rostro = inicio
        detecciones = 0
        caras = []
        ancho = alto = 0
        total = 0
        cantidad = max(MUESTRAS, min(120, math.ceil((fin - inicio) * 2)))
        paso = (fin - inicio) / cantidad
        for i in range(cantidad):
            tiempo = inicio + paso * (i + 0.5)
            cap.set(cv2.CAP_PROP_POS_MSEC, tiempo * 1000)
            ok, cuadro = cap.read()
            if not ok or cuadro is None:
                continue
            total += 1
            alto, ancho = cuadro.shape[:2]
            # Limita el coste de deteccion incluso si el proxy es de alta resolucion.
            escala = min(1.0, 640 / ancho)
            cuadro = cv2.resize(cuadro, (round(ancho * escala), round(alto * escala)))
            gris = cv2.equalizeHist(cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY))
            lado_min = max(20, int(gris.shape[0] * 0.06))
            rostros = clasificador.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=6, minSize=(lado_min, lado_min))
            if not len(rostros) and not perfil.empty():
                rostros = list(perfil.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=5, minSize=(lado_min, lado_min)))
                invertidos = perfil.detectMultiScale(cv2.flip(gris, 1), scaleFactor=1.1, minNeighbors=5, minSize=(lado_min, lado_min))
                rostros.extend((gris.shape[1] - x - w, y, w, h) for x, y, w, h in invertidos)
            if len(rostros):
                mayor = max(r[2] * r[3] for r in rostros)
                candidatos = [r for r in rostros if r[2] * r[3] >= mayor * 0.4]
                if anterior is None:
                    rostro = max(candidatos, key=lambda r: r[2] * r[3])
                else:
                    rostro = min(candidatos, key=lambda r: abs((r[0] + r[2] / 2) / gris.shape[1] - anterior))
                x, _, w, _ = rostro
                rx, ry, rw, rh = rostro
                caras.append((float(rx / gris.shape[1]), float(ry / gris.shape[0]),
                              float(rw / gris.shape[1]), float(rh / gris.shape[0])))
                anterior = (x + w / 2) / gris.shape[1]
                ultimo_rostro = tiempo
                detecciones += 1
            elif tiempo - ultimo_rostro > 1.5:
                anterior = None
            if anterior is not None or muestras:
                muestras.append({"tiempo": tiempo, "centro_x": anterior if anterior is not None else 0.5})
        if total == 0 or detecciones < max(2, total * MIN_PROPORCION):
            return None
        trayectoria = suavizar_trayectoria(muestras)
        centro = statistics.median(p["centro_x"] for p in trayectoria)
        # Incluye margen lateral, cabeza y hombros; la region se puede corregir a mano.
        camara = _region_camara(caras)
        return {"recorte_x": round(recorte_desde_centro(centro, ancho, alto), 3),
                "trayectoria": trayectoria, "camara": camara}
    except Exception:
        return None
    finally:
        cap.release()
