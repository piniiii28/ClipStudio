"""Regresiones de las ayudas editoriales, historial y análisis recuperable."""
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from clipstudio import api, config, db, editorial, media, pipeline, reframe, reframe_planos


@pytest.fixture
def clip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "datos.sqlite")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "proyectos")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    db.iniciar()
    p = db.insertar("proyectos", {"nombre": "Prueba", "origen": "archivo", "estado": "listo", "duracion": 60, "ancho": 640, "alto": 360})
    c = db.insertar("clips", {"proyecto_id": p["id"], "titulo": "Original", "inicio": 0, "fin": 30})
    carpeta = pipeline.carpeta_proyecto(p["id"])
    carpeta.mkdir(parents=True)
    (carpeta / "transcripcion.json").write_text(json.dumps({"segmentos": [{"inicio": 0, "fin": 4, "texto": "Python facilita programar videos."}]}), encoding="utf-8")
    return db.obtener("clips", c["id"])


def test_historial_persistente_rehacer_y_rama_nueva(clip):
    cid = clip["id"]
    a = db.editar_clip(cid, {"titulo": "Primero"}, 0)
    b = db.editar_clip(cid, {"titulo": "Segundo"}, a["revision"])
    c = db.mover_historial(cid, False, b["revision"])
    assert c["titulo"] == "Primero"
    d = db.mover_historial(cid, True, c["revision"])
    assert d["titulo"] == "Segundo"
    e = db.mover_historial(cid, False, d["revision"])
    f = db.editar_clip(cid, {"titulo": "Otra rama"}, e["revision"])
    assert db.mover_historial(cid, True, f["revision"])["titulo"] == "Otra rama"
    with pytest.raises(db.ConflictoRevision):
        db.editar_clip(cid, {"titulo": "Obsoleto"}, 0)
    assert db.obtener("clips", cid)["titulo"] == "Otra rama"


def test_historial_acotado_y_sin_ediciones_vacias(clip):
    for i in range(60):
        db.actualizar("clips", clip["id"], titulo=str(i))
    with db.conectar() as con:
        assert con.execute("SELECT COUNT(*) FROM historial_clips").fetchone()[0] == 50
    c = db.obtener("clips", clip["id"])
    assert db.editar_clip(c["id"], {"titulo": c["titulo"]})["revision"] == c["revision"]
    for _ in range(50):
        c = db.mover_historial(c["id"], False, c["revision"])
    assert c["historial_pos"] == 0 and c["titulo"] == "9"


def test_ayudas_tienen_texto_conservado_y_avisos():
    c = {"inicio": 0, "fin": 10, "cortes": [{"inicio": 4, "fin": 8}], "estilo": {"tamano": 64},
         "subtitulos": [{"inicio": 0, "fin": .1, "texto": "¿Cómo programar un video en Python?"},
                        {"inicio": 5, "fin": 6, "texto": "Frase eliminada del video"}]}
    opciones = editorial.titulos(c, [])
    assert opciones and all("eliminada" not in s["titulo"] for s in opciones)
    codigos = {a["codigo"] for a in editorial.revisar_subtitulos(c)}
    assert {"duracion", "lectura", "ancho", "corte"} <= codigos
    assert editorial.buscar_tema([{"inicio": 10, "fin": 12, "texto": "Programación con Python"}], 60, "python", 15, 30)
    assert not editorial.buscar_tema([], 60, "python", 15, 30)


def test_api_revision_ayudas_y_analisis_sin_duplicados(clip, monkeypatch):
    monkeypatch.setattr(api.gestor, "encolar", lambda *_: True)
    monkeypatch.setattr(api.gestor, "cancelar", lambda *_: "pendiente")
    client = TestClient(api.app, base_url="http://127.0.0.1")
    cid, pid = clip["id"], clip["proyecto_id"]
    assert client.patch(f"/api/clips/{cid}", json={"titulo": "Nuevo", "revision": 0}).status_code == 200
    assert client.patch(f"/api/clips/{cid}", json={"titulo": "Viejo", "revision": 0}).status_code == 409
    assert client.get(f"/api/clips/{cid}/titulos").json()["sugerencias"]
    assert client.post(f"/api/proyectos/{pid}/buscar-tema", json={"tema": "python"}).json()["candidatos"]
    a = client.post(f"/api/clips/{cid}/analisis-planos").json()
    assert client.post(f"/api/clips/{cid}/analisis-planos").json()["id"] == a["id"]
    assert client.post(f"/api/analisis/{a['id']}/cancelar").json()["estado"] == "cancelado"
    assert client.post(f"/api/clips/{cid}/analisis-planos").json()["id"] != a["id"]
    db.marcar_interrumpidos()
    assert all(a["estado"] not in db.ACTIVOS for a in db.listar("analisis"))


def test_hud_intervalos_y_limites(clip):
    c = reframe.normalizar_composicion({"juego": {"x": .3, "y": .3, "ancho": .4, "alto": .4},
         "hud": {"x": 0, "y": 0, "ancho": .2, "alto": .1},
         "tramos": [{"inicio": 5, "fin": 15, "modo": "camara"}]})
    assert c["juego"]["x"] == 0 and c["juego"]["ancho"] == pytest.approx(.7)
    with pytest.raises(ValueError):
        reframe.normalizar_composicion({"tramos": [{"inicio": 0, "fin": 5, "modo": "camara"}, {"inicio": 4, "fin": 6, "modo": "gameplay"}]})
    client = TestClient(api.app, base_url="http://127.0.0.1")
    client.patch(f"/api/clips/{clip['id']}", json={"composicion": c})
    respuesta = client.patch(f"/api/clips/{clip['id']}", json={"inicio": 10, "fin": 20}).json()
    assert respuesta["composicion"]["tramos"][0]["inicio"] == 10


def test_exporta_intervalos_con_tiempo_de_fuente(tmp_path):
    fuente, destino = tmp_path / "fuente.mp4", tmp_path / "vertical.mp4"
    media.ejecutar_ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=640x360:r=10:d=4,drawbox=x=0:y=0:w=160:h=180:color=red:t=fill", "-c:v", "libx264", str(fuente)], 4, media.Cancelacion(), lambda _: None)
    c = {"modo": "gameplay", "camara": {"x": 0, "y": 0, "ancho": .25, "alto": .5},
         "tramos": [{"inicio": 2, "fin": 3, "modo": "camara"}, {"inicio": 3, "fin": 4, "modo": "mixto"}]}
    media.exportar_clip(fuente, destino, 1, 4, "stream", .5, None, media.Cancelacion(), lambda _: None,
                        composicion=c, tiene_audio=False, perfil="borrador")
    cap = cv2.VideoCapture(str(destino))
    try:
        colores = []
        for segundo in (.3, 1.3, 2.3):
            cap.set(cv2.CAP_PROP_POS_MSEC, segundo * 1000)
            ok, imagen = cap.read()
            assert ok
            colores.append(imagen[80:160, 200:400].mean(axis=(0, 1)))
        assert colores[0][0] > colores[0][2]
        assert colores[1][2] > 200 and colores[2][2] > 200
    finally:
        cap.release()


def test_cancelacion_checkpoint_y_reanudacion(tmp_path, monkeypatch):
    fuente = tmp_path / "tomas.mp4"
    escritor = cv2.VideoWriter(str(fuente), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
    for i in range(40):
        escritor.write(np.full((180, 320, 3), 220 if i < 20 else 20, np.uint8))
    escritor.release()
    monkeypatch.setattr(reframe, "_crear_yunet", lambda _: object())
    monkeypatch.setattr(reframe, "_rostros_yunet", lambda *_: [(50, 30, 40, 40)])
    cancel = media.Cancelacion()
    checkpoint = tmp_path / "analisis.json"
    def progreso(p):
        if p > .7:
            cancel.cancelar()
    with pytest.raises(media.Cancelado):
        reframe_planos.detectar(fuente, 0, 4, cancel=cancel, progreso=progreso, checkpoint=checkpoint)
    assert json.loads(checkpoint.read_text())["resultados"]
    r = reframe_planos.detectar(fuente, 0, 4, checkpoint=checkpoint)
    assert r["planos"] == 2 and r["trayectoria"]


def test_trabajo_publica_solo_revision_analizada(clip, monkeypatch):
    fuente = pipeline.ruta_proxy(clip['proyecto_id'])
    fuente.touch()
    resultado = {'recorte_x': .2, 'trayectoria': [{'tiempo': 0, 'centro_x': .3}], 'planos': 2}
    monkeypatch.setattr(reframe_planos, 'detectar', lambda *a, **k: resultado)
    def trabajo(revision):
        return db.insertar('analisis', {'clip_id': clip['id'], 'proyecto_id': clip['proyecto_id'], 'estado': 'en_cola',
            'parametros': {'inicio': 0, 'fin': 30, 'encuadre': 'rellenar', 'revision': revision}})
    a = trabajo(0)
    pipeline.analizar_clip(a['id'], media.Cancelacion())
    assert db.obtener('analisis', a['id'])['progreso'] == 100
    assert db.obtener('clips', clip['id'])['recorte_x'] == .2
    a = trabajo(0)
    with pytest.raises(db.ConflictoRevision):
        pipeline.analizar_clip(a['id'], media.Cancelacion())
    assert db.obtener('clips', clip['id'])['revision'] == 1

def test_preferencia_global_conserva_regiones_sin_tiempos(clip):
    client = TestClient(api.app, base_url='http://127.0.0.1')
    r = client.put('/api/preferencias/clip', json={'estilo': {}, 'encuadre': 'stream',
        'composicion': {'tramos': [{'inicio': 0, 'fin': 3, 'modo': 'camara'}]}})
    assert r.status_code == 200
    assert not r.json()['composicion'].get('tramos')
    assert pipeline._extra('analisis', 'Cancelado.') == {'mensaje': 'Cancelado.'}
