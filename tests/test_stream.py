"""Regiones del stream, exportaciones reales y foto del bufer."""

import cv2
import numpy as np
import pytest
from pathlib import Path

from clipstudio import config, db, media, pipeline, reframe, vivo


COMPOSICION = {"modo": "mixto", "camara_porcentaje": 30,
               "camara": {"x": .05, "y": .1, "ancho": .25, "alto": .35},
               "juego": {"x": .35, "y": 0, "ancho": .65, "alto": 1}}


def test_modelo_yunet_incluido_funciona_en_opencv():
    modelo = Path(reframe.__file__).parent / "modelos" / "face_detection_yunet_2023mar.onnx"
    detector = cv2.FaceDetectorYN.create(str(modelo), "", (320, 320), .7, .3, 5000)
    _, caras = detector.detect(np.zeros((320, 320, 3), np.uint8))
    assert caras is None or len(caras) == 0


@pytest.mark.parametrize("datos", [[], {"modo": "invalido"}, {"camara_porcentaje": 10},
    {"camara": {"x": .9, "y": 0, "ancho": .2, "alto": .5}},
    {"camara": {"x": float("nan"), "y": 0, "ancho": .2, "alto": .5}},
    {"juego": {"x": 0, "y": 0, "ancho": 0, "alto": 1}}])
def test_regiones_invalidas_se_rechazan(datos):
    with pytest.raises(ValueError):
        reframe.normalizar_composicion(datos)


def test_defaults_y_regiones_independientes():
    c = reframe.normalizar_composicion(None)
    assert c["camara"] is None and c["juego"]["ancho"] == 1
    copia = reframe.normalizar_composicion(COMPOSICION)
    copia["camara"]["x"] = .2
    assert COMPOSICION["camara"]["x"] == .05


@pytest.fixture
def fuente(tmp_path):
    if not config.find_tool("ffmpeg") or not config.find_tool("ffprobe"):
        pytest.skip("Requiere FFmpeg")
    archivo = tmp_path / "stream.mp4"
    media.ejecutar_ffmpeg(
        ["-f", "lavfi", "-i", "color=c=blue:s=640x360:r=10:d=2,drawbox=x=32:y=36:w=160:h=126:color=red:t=fill",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(archivo)],
        2, media.Cancelacion(), lambda _: None,
    )
    return archivo


@pytest.mark.parametrize("modo,cortar", [("mixto", False), ("camara", False), ("gameplay", False), ("mixto", True)])
def test_exportacion_compone_zonas_del_mismo_directo(fuente, tmp_path, modo, cortar):
    destino = tmp_path / "vertical.mp4"
    c = {**COMPOSICION, "modo": modo}
    media.exportar_clip(fuente, destino, 0, 2, "stream", .5, None, media.Cancelacion(), lambda _: None,
                        composicion=c, tiene_audio=False, conservar=[(0, .4), (.8, 2)] if cortar else None)
    info = media.sondear(destino)
    assert (info["ancho"], info["alto"]) == (1080, 1920)
    assert info["duracion"] == pytest.approx(1.6 if cortar else 2, abs=.08)
    cap = cv2.VideoCapture(str(destino))
    try:
        ok, imagen = cap.read()
        assert ok
    finally:
        cap.release()
    arriba = imagen[100:300, 300:700].mean(axis=(0, 1))
    abajo = imagen[1400:1600, 300:700].mean(axis=(0, 1))
    if modo == "gameplay":
        assert arriba[0] > 200 and arriba[2] < 30
    else:
        assert arriba[2] > 200 and arriba[0] < 30
    if modo == "camara":
        assert abajo[2] > 200 and abajo[0] < 30
    else:
        assert abajo[0] > 200 and abajo[2] < 30


def test_vista_del_bufer_y_configuracion_via_api(fuente, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "datos.sqlite")
    monkeypatch.setattr(config, "VIVO_DIR", tmp_path / "vivo")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    db.iniciar()
    fila = db.insertar("sesiones_vivo", {"url": "https://twitch.tv/tenz", "estado": "grabando"})
    s = vivo.Sesion(fila["id"], fila["url"])
    s.carpeta.mkdir(parents=True)
    media.ejecutar_ffmpeg(["-i", str(fuente), "-c", "copy", "-f", "mpegts", str(s.carpeta / "seg.ts")],
                         2, media.Cancelacion(), lambda _: None)
    s.segmentos = [vivo.Seg("seg.ts", 0, 2)]
    monkeypatch.setattr(vivo, "_sesion", s)
    s._actualizar_vista()
    assert s.publico()["vista_version"] == 2
    respuesta = vivo.imagen_directo(s.id)
    assert respuesta.media_type == "image/jpeg"
    imagen = cv2.imdecode(np.frombuffer(respuesta.body, np.uint8), cv2.IMREAD_COLOR)
    assert imagen.shape[1] == 960
    assert respuesta.headers["cache-control"] == "no-store"
    r = vivo.cambiar_encuadre(s.id, vivo.EncuadreVivo(composicion=COMPOSICION))
    assert r["composicion"] == reframe.normalizar_composicion(COMPOSICION)
    c = vivo.EncuadreVivo(composicion={"modo": "invalido"})
    with pytest.raises(vivo.HTTPException) as exc:
        vivo.cambiar_encuadre(s.id, c)
    assert exc.value.status_code == 422


def test_nuevo_clip_hereda_regiones_sin_necesitar_otro_video(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ruta_proxy", lambda _: tmp_path / "inexistente.mp4")
    monkeypatch.setattr(db, "insertar", lambda tabla, datos: datos)
    proyecto = {"id": "p", "encuadre_vivo": COMPOSICION}
    pref = {"encuadre": "rellenar", "estilo": {}}
    clip = pipeline._nuevo_clip(proyecto, [], pref, 0, 10, "Momento", "vivo", [])
    assert clip["encuadre"] == "stream"
    assert clip["composicion"] == reframe.normalizar_composicion(COMPOSICION)
