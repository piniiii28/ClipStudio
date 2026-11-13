"""Regresiones del seguimiento y de sus tiempos en la exportacion."""

from pathlib import Path
import math

import cv2
import numpy as np
import pytest

from clipstudio import config, media, reframe


def test_detector_instalado_incluye_clasificadores():
    frontal = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    perfil = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    assert not frontal.empty() and not perfil.empty()


def test_suavizado_rechaza_un_salto_y_limita_velocidad():
    puntos = [{"tiempo": i, "centro_x": x} for i, x in enumerate([.2, .2, .9, .2, .2, .8, .8, .8])]
    salida = reframe.suavizar_trayectoria(puntos)
    assert salida[2]["centro_x"] == .2
    assert salida[-1]["centro_x"] > .6
    assert all(abs(b["centro_x"] - a["centro_x"]) <= .18001 for a, b in zip(salida, salida[1:]))


def test_deteccion_sigue_movimiento_y_conserva_posicion_si_se_pierde(monkeypatch):
    class Captura:
        liberada = False

        def isOpened(self):
            return True

        def set(self, *args):
            pass

        def read(self):
            return True, np.zeros((360, 640, 3), dtype=np.uint8)

        def release(self):
            self.liberada = True

    class Clasificador:
        perdida = range(10, 13)

        def __init__(self, ruta):
            self.perfil = "profileface" in ruta
            self.indice = 0

        def empty(self):
            return False

        def detectMultiScale(self, *args, **kwargs):
            if self.perfil:
                return []
            i = self.indice
            self.indice += 1
            if i in self.perdida:
                return []
            # El segundo rostro cambia de tamano, pero no debe robar el seguimiento.
            return [(80 + i * 12, 60, 60, 60), (560, 60, 65 + i % 2 * 10, 65)]

    monkeypatch.setattr(reframe, "_crear_yunet", lambda _: None)
    captura = Captura()
    monkeypatch.setattr(cv2, "VideoCapture", lambda _: captura)
    monkeypatch.setattr(cv2, "CascadeClassifier", Clasificador)
    # Elige inicialmente el segundo rostro, que es mayor, y conserva esa identidad.
    resultado = reframe.detectar_seguimiento(Path("prueba.mp4"), 10, 16)
    assert resultado is not None
    assert all(p["centro_x"] > .85 for p in resultado["trayectoria"])
    assert captura.liberada

    # Una sola persona se desplaza de izquierda a derecha.
    original = Clasificador.detectMultiScale

    def una_persona(self, *args, **kwargs):
        return original(self, *args, **kwargs)[:1]

    monkeypatch.setattr(Clasificador, "detectMultiScale", una_persona)
    resultado = reframe.detectar_seguimiento(Path("prueba.mp4"), 10, 16)
    puntos = resultado["trayectoria"]
    assert puntos[-1]["centro_x"] - puntos[0]["centro_x"] > .35
    assert len(puntos) == 24
    assert puntos[10]["centro_x"] == puntos[11]["centro_x"]
    Clasificador.perdida = range(10, 18)
    puntos = reframe.detectar_seguimiento(Path("prueba.mp4"), 10, 16)["trayectoria"]
    assert abs(puntos[17]["centro_x"] - .5) < abs(puntos[10]["centro_x"] - .5)
    Clasificador.perdida = range(0, 23)
    assert reframe.detectar_seguimiento(Path("prueba.mp4"), 10, 16) is None


@pytest.mark.parametrize("encuadre", ["rellenar", "dividido"])
def test_filtro_usa_tiempo_fuente_antes_de_eliminar_tramos(encuadre):
    puntos = [{"tiempo": 10, "centro_x": .2}, {"tiempo": 15, "centro_x": .8}]
    grafo = media.filtro_encuadre(encuadre, .5, False, trayectoria=puntos, inicio=10, conservar=[(0, 2), (4, 6)])
    assert "clip((t-(0.000))/5.000,0,1)" in grafo
    assert grafo.index("crop=") < grafo.index("select=")
    assert "max(0,min(iw-1080" in grafo
    if encuadre == "dividido":
        assert "clip(" not in grafo.split(";")[1]


def test_video_sin_rostros_y_rango_invalido(tmp_path):
    assert reframe.detectar_seguimiento(tmp_path / "ausente.mp4", 0, 10) is None
    assert reframe.detectar_seguimiento(tmp_path / "ausente.mp4", 10, 10) is None


@pytest.mark.skipif(not config.find_tool("ffmpeg") or not config.find_tool("ffprobe"), reason="Requiere FFmpeg")
def test_exportacion_real_con_120_puntos_no_agota_el_analizador(tmp_path):
    fuente, destino = tmp_path / "fuente.mp4", tmp_path / "salida.mp4"
    cancel = media.Cancelacion()
    media.ejecutar_ffmpeg(
        ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=5", "-t", "1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(fuente)],
        1, cancel, lambda _: None,
    )
    puntos = [{"tiempo": i * .5, "centro_x": .5 + .2 * math.sin(i * .3)} for i in range(120)]
    media.exportar_clip(fuente, destino, 0, 1, "rellenar", .5, None, cancel, lambda _: None, trayectoria=puntos)
    info = media.sondear(destino)
    assert (info["ancho"], info["alto"]) == (1080, 1920)
    assert info["duracion"] == pytest.approx(1, abs=.05)


def test_yunet_local_procesa_un_fotograma():
    detector = reframe._crear_yunet(cv2)
    assert detector is not None
    assert reframe._rostros_yunet(detector, np.zeros((160, 320, 3), dtype=np.uint8)) == []


def test_asociacion_rechaza_rostro_lejano_o_en_otra_altura():
    anterior = (.2, .2, .08, .12)
    cercano = (.24, .21, .08, .12)
    intruso = (.2, .65, .15, .18)
    assert reframe._elegir_rostro([intruso, cercano], anterior, .25) == cercano
    assert reframe._elegir_rostro([intruso], anterior, .25) is None
    assert reframe._elegir_rostro([intruso, cercano], None, 0) == intruso


def test_seguimiento_no_arranca_con_una_deteccion_aislada(monkeypatch):
    class Captura:
        def isOpened(self):
            return True

        def set(self, *args):
            pass

        def read(self):
            return True, np.zeros((160, 320, 3), dtype=np.uint8)

        def release(self):
            pass

    detecciones = iter([[(280, 30, 32, 32)], [], *([[(48, 30, 24, 28)]] * 22)])
    monkeypatch.setattr(cv2, "VideoCapture", lambda _: Captura())
    monkeypatch.setattr(reframe, "_crear_yunet", lambda _: object())
    monkeypatch.setattr(reframe, "_rostros_yunet", lambda *_: next(detecciones))
    resultado = reframe.detectar_seguimiento(Path("prueba.mp4"), 0, 6)
    assert resultado is not None
    assert resultado["cobertura"] == .88
    assert all(p["centro_x"] < .25 for p in resultado["trayectoria"])
