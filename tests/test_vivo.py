"""Pruebas del modo en vivo que no necesitan FFmpeg ni red: detector, segmentos, bufer y modo de pruebas."""

import random

import pytest

from clipstudio import vivo
from clipstudio.media import ErrorMedia
from clipstudio.vivo import Seg


def _ruido(n, base=-40.0, seed=1):
    rnd = random.Random(seed)
    return [base + rnd.uniform(-1.5, 1.5) for _ in range(n)]


# ---------- detector ----------

def test_pico_claro_se_detecta_con_motivo():
    db = _ruido(60)
    db[45] = -15.0
    momentos = vivo.detectar_momentos(db)
    assert len(momentos) == 1
    assert momentos[0]["tiempo"] == 45
    assert momentos[0]["motivo"].startswith("Pico de volumen: +")
    assert "sobre el minuto anterior" in momentos[0]["motivo"]
    assert momentos[0]["exceso_db"] >= 9


def test_ruido_constante_no_da_picos():
    assert vivo.detectar_momentos(_ruido(300, base=-30.0)) == []


def test_pico_bajo_el_suelo_no_cuenta():
    # Mucho mas fuerte que el entorno, pero por debajo de -35 dB.
    db = [-70.0] * 60
    db[40] = -40.0
    assert vivo.detectar_momentos(db) == []


def test_enfriamiento_evita_momentos_seguidos():
    db = _ruido(120)
    for i in (50, 52, 60, 69):   # todos dentro de los 20 s posteriores al primero
        db[i] = -12.0
    momentos = vivo.detectar_momentos(db)
    assert [m["tiempo"] for m in momentos] == [50]
    db[75] = -12.0               # pasado el enfriamiento (>= 20 s) vuelve a marcar
    assert [m["tiempo"] for m in vivo.detectar_momentos(db)] == [50, 75]


def test_pico_al_principio_sin_historia_suficiente():
    db = _ruido(60)
    db[5] = -10.0
    assert vivo.detectar_momentos(db) == []
    db2 = _ruido(60)
    db2[vivo.HISTORIA_MIN_S] = -10.0
    assert [m["tiempo"] for m in vivo.detectar_momentos(db2)] == [vivo.HISTORIA_MIN_S]


def test_detector_es_causal():
    # Lo que ocurre despues del segundo evaluado no cambia la decision.
    db = _ruido(80)
    db[50] = -12.0
    antes = vivo.evaluar_segundo(db[:51], 50, None)
    despues = vivo.evaluar_segundo(db, 50, None)
    assert antes == despues and antes is not None


# ---------- segmentos ----------

SEGS = [Seg(f"seg_{i:06d}.ts", i * 6.0, (i + 1) * 6.0, 1000) for i in range(10)]   # 0..60 s


def test_segmentos_que_cubren_un_tramo():
    nombres = [s.nombre for s in vivo.segmentos_que_cubren(SEGS, 7, 20)]
    assert nombres == ["seg_000001.ts", "seg_000002.ts", "seg_000003.ts"]   # 6-12, 12-18, 18-24
    # Un tramo que termina justo en un limite no arrastra el segmento siguiente.
    assert [s.nombre for s in vivo.segmentos_que_cubren(SEGS, 6, 12)] == ["seg_000001.ts"]
    assert vivo.segmentos_que_cubren(SEGS, 100, 120) == []


def test_plan_recorte_calcula_desfase_y_duracion():
    cubiertos, desfase, duracion = vivo.plan_recorte(SEGS, 7, 20)
    assert len(cubiertos) == 3
    assert desfase == pytest.approx(1.0)
    assert duracion == pytest.approx(13.0)


def test_plan_recorte_se_ajusta_a_lo_grabado():
    _, desfase, duracion = vivo.plan_recorte(SEGS, -10, 200)
    assert desfase == 0 and duracion == pytest.approx(60.0)


def test_plan_recorte_sin_material_o_demasiado_corto():
    with pytest.raises(ErrorMedia):
        vivo.plan_recorte(SEGS, 100, 130)
    with pytest.raises(ErrorMedia):
        vivo.plan_recorte(SEGS, 59, 70)   # solo 1 s utilizable


def test_leer_lista_csv():
    segs = vivo.leer_lista_csv("seg_000000.ts,0.000000,6.040000\nseg_000001.ts,6.040000,12.000000\nbasura\n")
    assert [(s.nombre, s.inicio, s.fin) for s in segs] == [
        ("seg_000000.ts", 0.0, 6.04), ("seg_000001.ts", 6.04, 12.0)]


# ---------- politica del bufer ----------

def test_bufer_borra_solo_lo_que_sale_de_la_ventana():
    # 60 s de segmentos y bufer de 30 s: sobran los que terminan antes del segundo 30.
    borrar = vivo.segmentos_a_borrar(SEGS, 30)
    assert [s.nombre for s in borrar] == [f"seg_{i:06d}.ts" for i in range(5)]
    assert vivo.segmentos_a_borrar(SEGS, 3600) == []
    assert vivo.segmentos_a_borrar([], 30) == []


# ---------- modo de pruebas ----------

def test_prueba_se_rechaza_fuera_del_modo_de_pruebas(monkeypatch, tmp_path):
    monkeypatch.delenv("CLIPSTUDIO_VIVO_PRUEBAS", raising=False)
    archivo = tmp_path / "v.mp4"
    archivo.write_bytes(b"x")
    with pytest.raises(ErrorMedia):
        vivo.archivo_de_prueba(f"prueba:{archivo}")
    with pytest.raises(ErrorMedia):
        vivo.resolver_directo(f"prueba:{archivo}")


def test_prueba_en_modo_de_pruebas(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPSTUDIO_VIVO_PRUEBAS", "1")
    archivo = tmp_path / "mi_directo.mp4"
    archivo.write_bytes(b"x")
    assert vivo.archivo_de_prueba(f"prueba:{archivo}") == archivo
    datos = vivo.resolver_directo(f"prueba:{archivo}")
    assert datos["prueba"] is True and datos["titulo"] == "mi_directo"
    with pytest.raises(ErrorMedia):
        vivo.archivo_de_prueba(f"prueba:{tmp_path / 'no_existe.mp4'}")
    assert vivo.archivo_de_prueba("https://kick.com/canal") is None


def test_chat_tiene_lectores_para_twitch_y_youtube(tmp_path):
    from clipstudio import chat
    estado = lambda *args: None
    assert isinstance(chat.crear_lector("https://www.twitch.tv/tenz", tmp_path, estado), chat.LectorTwitch)
    assert isinstance(chat.crear_lector("https://www.youtube.com/watch?v=video", tmp_path, estado), chat.LectorYouTube)


@pytest.fixture
def sesion_marcadores(tmp_path, monkeypatch):
    from clipstudio import config, db
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "datos.sqlite")
    monkeypatch.setattr(config, "VIVO_DIR", tmp_path)
    db.iniciar()
    db.insertar("sesiones_vivo", {"id": "prueba", "url": "https://twitch.tv/prueba", "estado": "grabando"})
    sesion = vivo.Sesion("prueba", "https://twitch.tv/prueba", automaticos=True)
    sesion.estado = "grabando"
    sesion.segmentos = list(SEGS)
    return sesion


def test_marcador_persiste_nota_sobre_video_disponible_sin_automatizar(sesion_marcadores):
    from clipstudio import db
    s = sesion_marcadores
    fila = s.marcar_momento("  Buena jugada  ")
    guardado = db.obtener("momentos_vivo", fila["id"])
    assert guardado["tiempo"] == 60
    assert guardado["motivo"] == "Buena jugada"
    assert guardado["origen"] == "manual"
    assert guardado["estado"] == "nuevo"
    assert s._clips_pendientes.empty()


def test_marcador_rechaza_sin_video_y_no_oculta_fallo_de_guardado(sesion_marcadores, monkeypatch):
    s = sesion_marcadores
    monkeypatch.setattr(vivo.db, "insertar", lambda *a, **kw: (_ for _ in ()).throw(OSError()))
    with pytest.raises(ErrorMedia, match="guardar"):
        s.marcar_momento("")
    s.segmentos = []
    with pytest.raises(ErrorMedia, match="Espera"):
        s.marcar_momento("")


def test_momentos_caducados_y_convertidos(sesion_marcadores):
    s = sesion_marcadores
    s.segmentos = SEGS[5:]
    s.momentos = [
        {"id": "viejo", "tiempo": 29, "proyecto_id": None},
        {"id": "limite", "tiempo": 30, "proyecto_id": None},
        {"id": "guardado", "tiempo": 10, "proyecto_id": "p"},
    ]
    publico = s.publico()
    assert publico["buffer_inicio_s"] == 30
    assert [m["caducado"] for m in publico["momentos"]] == [True, False, False]


def test_recorte_rechaza_huecos_pero_tolera_redondeo_de_segmentos():
    with pytest.raises(ErrorMedia, match="Falta vídeo"):
        vivo.plan_recorte([Seg("a.ts", 0, 6, 1), Seg("b.ts", 12, 18, 1)], 0, 18)
    cubiertos, desfase, duracion = vivo.plan_recorte([Seg("a.ts", 0, 6, 1), Seg("b.ts", 6.001, 12, 1)], 0, 12)
    assert len(cubiertos) == 2 and desfase == 0 and duracion == 12


def test_api_marcador_valida_nota_y_sesion_y_rechaza_caducado(sesion_marcadores, monkeypatch):
    from fastapi.testclient import TestClient
    from clipstudio.api import app
    s = sesion_marcadores
    monkeypatch.setattr(vivo, "sesion_actual", lambda: s)
    cliente = TestClient(app, base_url="http://localhost")
    assert cliente.post("/api/vivo/otra/momentos", json={}).status_code == 404
    assert cliente.post("/api/vivo/prueba/momentos", json={"nota": "x" * 161}).status_code == 422
    respuesta = cliente.post("/api/vivo/prueba/momentos", json={"nota": " "})
    assert respuesta.status_code == 201
    assert respuesta.json()["motivo"] == "Marcador manual"
    s.momentos.append({"id": "caducado", "tiempo": 10, "proyecto_id": None})
    s.segmentos = SEGS[5:]
    respuesta = cliente.post("/api/vivo/prueba/clip", json={"momento_id": "caducado"})
    assert respuesta.status_code == 409 and "fuera del búfer" in respuesta.json()["detail"]
    s.estado = "detenido"
    assert cliente.post("/api/vivo/prueba/momentos", json={}).status_code == 409
