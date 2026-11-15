"""Regresiones del motor alternativo y sus cortes en la exportación real."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from clipstudio import api, media, reframe, reframe_planos


def test_camara_rechaza_salto_aislado_y_conserva_zona():
    camara = reframe_planos.CamaraEstable(.32)
    assert camara.actualizar(None, .25) == .5
    assert camara.actualizar(.2, .25) == .2
    assert camara.actualizar(.24, .25) == .2
    assert camara.actualizar(.8, .25) == .2
    assert camara.actualizar(.2, .25) == .2
    for _ in range(3):
        ultimo = camara.actualizar(.8, .25)
    assert .2 < ultimo <= .245001
    assert camara.actualizar(None, .25) == ultimo


def test_planos_reales_reinician_encuadre_y_exportan(tmp_path, monkeypatch):
    video = tmp_path / "tomas.mp4"
    escritor = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 20, (640, 360))
    for i in range(80):
        cuadro = np.zeros((360, 640, 3), np.uint8)
        cuadro[:] = (0, 0, 220) if i < 40 else (220, 0, 0)
        escritor.write(cuadro)
    escritor.release()
    planos = reframe_planos.detectar_planos(video, .5, 3.5)
    assert len(planos) == 2
    assert abs(planos[1][0] - 2) < .1
    completos = reframe_planos.detectar_planos(video, 0, 4)
    assert completos[0][0] == 0 and completos[-1][1] == 4
    monkeypatch.setattr(reframe, "_crear_yunet", lambda _: object())
    monkeypatch.setattr(reframe, "_rostros_yunet", lambda _, c:
        [(80 if c[0, 0, 2] > c[0, 0, 0] else 490, 60, 60, 60)])
    r = reframe_planos.detectar(video, .5, 3.5)
    assert r["planos"] == 2 and r["cobertura"] == 1
    puntos = r["trayectoria"]
    antes, despues = [(a, b) for a, b in zip(puntos, puntos[1:]) if b["centro_x"] - a["centro_x"] > .5][0]
    assert 0 < despues["tiempo"] - antes["tiempo"] <= .001001
    assert all(a["tiempo"] < b["tiempo"] for a, b in zip(puntos, puntos[1:]))
    salida = tmp_path / "salida.mp4"
    media.exportar_clip(video, salida, .5, 3.5, "rellenar", r["recorte_x"], None,
        media.Cancelacion(), lambda _: None, trayectoria=puntos, tiene_audio=False, perfil="borrador")
    assert media.sondear(salida)["alto"] == 1280


def test_sin_caras_no_cambia_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_clip", lambda _: {"proyecto_id":"p", "inicio":0, "fin":5})
    monkeypatch.setattr(api, "_proyecto_listo", lambda _: {})
    monkeypatch.setattr(reframe_planos, "detectar", lambda *_: None)
    monkeypatch.setattr(api.db, "actualizar", lambda *_a, **_k: pytest.fail("No debe guardar sin detecciones"))
    assert api.encuadre_planos("c")["detectado"] is False


def test_sesenta_planos_se_analizan_y_exportan(tmp_path, monkeypatch):
    video = tmp_path / "sesenta.mp4"
    escritor = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
    for plano in range(60):
        cuadro = np.zeros((180, 320, 3), np.uint8)
        cuadro[:] = (0, 0, 220) if plano % 2 == 0 else (220, 0, 0)
        for _ in range(10):
            escritor.write(cuadro)
    escritor.release()
    monkeypatch.setattr(reframe, "_crear_yunet", lambda _: object())
    monkeypatch.setattr(reframe, "_rostros_yunet", lambda _, c:
        [(30 if c[0, 0, 2] > c[0, 0, 0] else 250, 30, 30, 30)])
    resultado = reframe_planos.detectar(video, 0, 60)
    assert resultado["planos"] == 60
    assert resultado["cobertura"] == 1
    trayectoria = resultado["trayectoria"]
    assert len(trayectoria) >= 60 * 4
    assert all(a["tiempo"] < b["tiempo"] for a, b in zip(trayectoria, trayectoria[1:]))
    cambios = [b for a, b in zip(trayectoria, trayectoria[1:]) if abs(b["centro_x"] - a["centro_x"]) > .5]
    assert len(cambios) == 59
    salida = tmp_path / "sesenta-vertical.mp4"
    media.exportar_clip(video, salida, 0, 60, "rellenar", resultado["recorte_x"], None,
        media.Cancelacion(), lambda _: None, trayectoria=trayectoria, tiene_audio=False, perfil="borrador")
    assert media.sondear(salida)["duracion"] == pytest.approx(60, abs=.1)


def test_exportacion_extensa_usa_archivo_y_lo_limpia(tmp_path):
    video = tmp_path / "origen.mp4"
    media.ejecutar_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=5", "-t", "1",
        "-c:v", "libx264", str(video)], 1, media.Cancelacion(), lambda _: None)
    puntos = [{"tiempo": i / 1000, "centro_x": .2 if i % 2 == 0 else .8} for i in range(1000)]
    assert len(reframe.expresion_centro(puntos)) > 32767
    salida = tmp_path / "extensa.mp4"
    media.exportar_clip(video, salida, 0, 1, "rellenar", .5, None,
        media.Cancelacion(), lambda _: None, trayectoria=puntos, tiene_audio=False, perfil="borrador")
    assert media.sondear(salida)["alto"] == 1280
    assert not list(tmp_path.glob("filtro-*"))


def test_filtro_temporal_se_limpia_si_falla_exportacion(tmp_path, monkeypatch):
    puntos = [{"tiempo": i / 1000, "centro_x": .2 if i % 2 == 0 else .8} for i in range(1000)]
    def fallar(args, *_a, **_k):
        ruta = Path(args[args.index("-/filter_complex") + 1])
        assert ruta.is_file()
        raise media.ErrorMedia("Fallo simulado")
    monkeypatch.setattr(media, "ejecutar_ffmpeg", fallar)
    with pytest.raises(media.ErrorMedia):
        media.exportar_clip(tmp_path / "origen.mp4", tmp_path / "fallo.mp4", 0, 1, "rellenar", .5, None,
            media.Cancelacion(), lambda _: None, trayectoria=puntos, tiene_audio=False)
    assert not list(tmp_path.glob("filtro-*"))


def test_cambio_concurrente_de_limites_se_rechaza(monkeypatch):
    clips = iter([{"proyecto_id":"p", "inicio":0, "fin":5}, {"inicio":1,"fin":5}])
    monkeypatch.setattr(api, "_clip", lambda _: next(clips))
    monkeypatch.setattr(api, "_proyecto_listo", lambda _: {})
    monkeypatch.setattr(reframe_planos, "detectar", lambda *_: {"recorte_x":.5,"trayectoria":[]})
    with pytest.raises(api.HTTPException) as e:
        api.encuadre_planos("c")
    assert e.value.status_code == 409


@pytest.mark.parametrize("inicio,fin", [(0,601),(0,float("nan")),(5,4)])
def test_limites_invalidos(inicio, fin):
    with pytest.raises(media.ErrorMedia):
        reframe_planos.detectar(Path("inexistente.mp4"), inicio, fin)
