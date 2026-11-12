"""Relevancia del fragmento final y persistencia por clip, sin red ni tendencias inventadas."""
import re

import pytest
from fastapi.testclient import TestClient

from clipstudio import config, db, hashtags, pipeline
from clipstudio.api import app


def clip(**cambios):
    return {"titulo": "Momento", "inicio": 10, "fin": 20, "subtitulos": [], "cortes": [], "estilo": {}, **cambios}


def tags(resultado):
    return [h["etiqueta"] for h in resultado["hashtags"]]


def test_contexto_explicito_juego_jugada_y_agente_sin_relleno_viral():
    r = hashtags.sugerir(clip(), {"es_clip_vivo": 1}, [], "Valorant, Jett, clutch")
    assert tags(r) == ["#Valorant", "#Clutch", "#Jett", "#ValorantClips", "#Gaming"]
    assert r["texto"] == " ".join(tags(r))
    assert all(h["motivo"] for h in r["hashtags"])
    assert "no garantizan" in r["aviso"]


def test_no_infiere_valorant_por_nombre_del_creador():
    r = hashtags.sugerir(clip(titulo="TenZ (live) – últimos 30 s"), {"es_clip_vivo": 1}, [])
    assert tags(r) == ["#ClipsDeStream"]
    assert r["necesita_contexto"]


def test_ignora_temas_fuera_del_clip_y_en_tramos_eliminados():
    c = clip(cortes=[{"inicio": 14, "fin": 17}])
    segmentos = [{"inicio": 0, "fin": 30, "palabras": [
        {"inicio": 0, "fin": 1, "texto": "Fortnite"},
        {"inicio": 11, "fin": 12, "texto": "Minecraft"},
        {"inicio": 15, "fin": 16, "texto": "Valorant"},
        {"inicio": 25, "fin": 26, "texto": "Roblox"},
    ]}]
    r = hashtags.sugerir(c, {"nombre": "Fortnite y Valorant"}, segmentos)
    assert "#Minecraft" in tags(r)
    assert not {"#Fortnite", "#Valorant", "#Roblox"} & set(tags(r))


def test_usa_subtitulos_editados_y_descarta_cues_cortados():
    c = clip(cortes=[{"inicio": 14, "fin": 17}], subtitulos=[
        {"inicio": 11, "fin": 12, "texto": "Programación con Python"},
        {"inicio": 14, "fin": 17, "texto": "Valorant"}])
    r = hashtags.sugerir(c, {}, [{"inicio": 10, "fin": 20, "texto": "Minecraft"}])
    assert tags(r) == ["#Programacion"]


@pytest.mark.parametrize("contexto", ["Python", "Ajedrez", "Crochet, Bordado", "  #Valorant, valorant, VALORANT ", "<script>alert(1)</script>", "", "fyp, viral"])
def test_etiquetas_acotadas_y_sin_duplicados(contexto):
    r = hashtags.sugerir(clip(), {}, [], contexto)
    assert len(r["hashtags"]) <= 5
    assert len({t.casefold() for t in tags(r)}) == len(tags(r))
    assert all(re.fullmatch(r"#[A-Za-z][A-Za-z0-9]{1,40}", t) for t in tags(r))
    assert not {"#Fyp", "#Viral", "#ParaTi", "#ForYou"} & set(tags(r))


def test_no_confunde_palabras_comunes_con_juegos_o_jugadas():
    r = hashtags.sugerir(clip(titulo="Amazing ace performance, lol"), {}, [])
    assert not tags(r)
    assert r["necesita_contexto"]


def test_api_persistencia_y_migracion_de_clips_existentes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    db.iniciar()
    # Simula la base anterior y comprueba que la migracion es repetible.
    with db.conectar() as con:
        con.execute("ALTER TABLE clips DROP COLUMN tiktok")
    p = db.insertar("proyectos", {"nombre": "Directo", "origen": "archivo", "estado": "listo", "duracion": 30})
    a = db.insertar("clips", {"proyecto_id": p["id"], "titulo": "Valorant clutch", "inicio": 0, "fin": 10})
    b = db.insertar("clips", {"proyecto_id": p["id"], "titulo": "Otro", "inicio": 10, "fin": 20})
    db.iniciar()
    db.iniciar()
    assert db.obtener("clips", a["id"])["tiktok"] == {}
    monkeypatch.setattr(pipeline, "leer_transcripcion", lambda _: {"segmentos": []})
    cliente = TestClient(app, base_url="http://127.0.0.1:8765")
    r = cliente.post(f'/api/clips/{a["id"]}/hashtags', json={"contexto": "Valorant"})
    assert r.status_code == 200 and "#Valorant" in tags(r.json())
    assert db.obtener("clips", a["id"])["tiktok"] == {}  # sugerir no guarda sin elegir
    publicacion = {"contexto": "Valorant", "texto": "#Valorant #Clutch"}
    r = cliente.patch(f'/api/clips/{a["id"]}', json={"tiktok": publicacion})
    assert r.status_code == 200 and r.json()["tiktok"] == publicacion
    assert db.obtener("clips", a["id"])["tiktok"] == publicacion
    assert db.obtener("clips", b["id"])["tiktok"] == {}
    assert cliente.post(f'/api/clips/{a["id"]}/hashtags', json={"contexto": "x" * 201}).status_code == 422
    assert cliente.patch(f'/api/clips/{a["id"]}', json={"tiktok": {"texto": "x" * 1001}}).status_code == 422
    assert cliente.post('/api/clips/no-existe/hashtags', json={}).status_code == 404
