"""Fondos de YouTube para el encuadre dividido y credito del autor (todo sin red)."""

import os
import random
import re
import time

import pytest
from fastapi.testclient import TestClient

from clipstudio import config, db, fondos_remotos, pipeline, subtitles
from clipstudio.api import app
from clipstudio.media import ErrorMedia

ID_MINECRAFT, ID_SUBWAY = "eBExtYRpuqI", "HeQQwg_N0Yg"


# ---------- ids y URLs ----------

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=eBExtYRpuqI",
    "http://youtube.com/watch?v=eBExtYRpuqI&t=30s",
    "https://m.youtube.com/watch?v=eBExtYRpuqI",
    "https://youtu.be/eBExtYRpuqI",
    "https://youtu.be/eBExtYRpuqI?si=abc",
    "https://www.youtube.com/shorts/eBExtYRpuqI",
    "https://www.youtube.com/watch?v=eBExtYRpuqI&list=PL123",   # el video suelto, sin la lista
])
def test_extraer_id_acepta_videos_de_youtube(url):
    assert fondos_remotos.extraer_id(url) == "eBExtYRpuqI"


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/playlist?list=PLabc",
    "https://www.youtube.com/channel/UC1234567890123456789012",
    "https://www.youtube.com/watch",
    "https://www.youtube.com/watch?v=corto",
    "https://www.youtube.com/watch?v=eBExtYRpuqI%00%00",
    "https://youtu.be/",
    "https://vimeo.com/123456789",
    "https://www.youtube.com.evil.com/watch?v=eBExtYRpuqI",
    "https://evil.com/?u=youtube.com/watch?v=eBExtYRpuqI",
    "https://localhost/watch?v=eBExtYRpuqI",
    "ftp://youtube.com/watch?v=eBExtYRpuqI",
    "prueba:mi_directo.mp4",
    "file:///C:/video.mp4",
    "",
])
def test_extraer_id_rechaza_listas_otros_dominios_y_esquemas(url):
    with pytest.raises(ValueError):
        fondos_remotos.extraer_id(url)


def test_id_valido():
    assert fondos_remotos.id_valido("eBExtYRpuqI") and fondos_remotos.id_valido("HeQQwg_N0Yg") and fondos_remotos.id_valido("a-b_c-d_e-f")
    for malo in ("", "corto", "demasiado_largo_", "eBExtYRpuq!", "eBExtYRpuq ", "../../etc/p", None, 123):
        assert not fondos_remotos.id_valido(malo)


# ---------- estilo ----------

def test_normalizar_estilo_acepta_yt_valido_e_invalido():
    ok = subtitles.normalizar_estilo({"fondo_juego": "yt:eBExtYRpuqI"})["fondo_juego"]
    assert ok == "yt:eBExtYRpuqI"
    for malo in ("yt:", "yt:corto", "yt:eBExtYRpuqI1", "yt:eBExtYRpuq/", "yt:../..", "yt:eBExtYRpuq\\", "YT:eBExtYRpuqI", "yt: eBExtYRpuq"):
        assert subtitles.normalizar_estilo({"fondo_juego": malo})["fondo_juego"] == "", malo


def test_nombres_de_archivo_maliciosos_siguen_rechazados():
    for malo in ("../x.mp4", "..\\x.mp4", "a/b.mp4", "C:\\x.mp4", "C:/x.mp4", "C:x.mp4", "", "..", "x" * 151, None, 5, ["a.mp4"]):
        assert subtitles.normalizar_estilo({"fondo_juego": malo})["fondo_juego"] == ""
    assert subtitles.normalizar_estilo({"fondo_juego": "gameplay.mp4"})["fondo_juego"] == "gameplay.mp4"


def test_estilo_credito_por_defecto_y_limites():
    base = subtitles.normalizar_estilo({})
    assert base["credito_fondo"] is False and base["credito_tamano"] == 28
    assert subtitles.normalizar_estilo({"credito_tamano": 5})["credito_tamano"] == 16
    assert subtitles.normalizar_estilo({"credito_tamano": 500})["credito_tamano"] == 60
    assert subtitles.normalizar_estilo({"credito_tamano": "40"})["credito_tamano"] == 40
    assert subtitles.normalizar_estilo({"credito_fondo": 1})["credito_fondo"] is True
    # viaja con las preferencias
    assert subtitles.estilo_para_preferencia({"credito_fondo": True, "credito_tamano": 33})["credito_tamano"] == 33


# ---------- inicio al azar ----------

def test_inicio_dentro_de_rango():
    azar = random.Random(1)
    for _ in range(300):
        inicio = fondos_remotos.elegir_inicio(3487, 40, azar)
        assert 0 <= inicio <= 3487 - 40 - 5


def test_inicio_con_clip_mas_largo_que_el_fondo_es_cero():
    assert fondos_remotos.elegir_inicio(60, 120) == 0.0
    assert fondos_remotos.elegir_inicio(60, 56) == 0.0       # no deja los 5 s finales
    assert fondos_remotos.elegir_inicio(100, 95) == 0.0


def test_tramo_a_bajar_no_pasa_del_final():
    desde, hasta = fondos_remotos.tramo_a_bajar(3487, 30, 100)
    assert (desde, hasta) == (100, 150)                     # clip + 20 s de margen
    desde, hasta = fondos_remotos.tramo_a_bajar(3487, 30, 3470)
    assert hasta == 3487
    desde, hasta = fondos_remotos.tramo_a_bajar(60, 300, 0)  # clip mas largo: se baja el fondo entero
    assert (desde, hasta) == (0, 60)


# ---------- cache ----------

def _crear(carpeta, nombre, tamano, antiguedad):
    f = carpeta / nombre
    f.write_bytes(b"x" * tamano)
    t = time.time() - antiguedad
    os.utime(f, (t, t))
    return f


def test_poda_borra_los_mas_antiguos_hasta_caber(tmp_path):
    viejo = _crear(tmp_path, f"{ID_MINECRAFT}_0_40.mp4", 400, 300)
    medio = _crear(tmp_path, f"{ID_MINECRAFT}_100_40.mp4", 400, 200)
    nuevo = _crear(tmp_path, f"{ID_SUBWAY}_5_40.mp4", 400, 100)
    borrados = fondos_remotos.podar_cache(tmp_path, limite=900)
    assert borrados == [viejo] and not viejo.exists() and medio.exists() and nuevo.exists()
    borrados = fondos_remotos.podar_cache(tmp_path, limite=400)
    assert [b.name for b in borrados] == [medio.name] and nuevo.exists()


def test_poda_conserva_el_que_se_acaba_de_guardar_y_no_hace_nada_si_cabe(tmp_path):
    a = _crear(tmp_path, f"{ID_MINECRAFT}_0_40.mp4", 500, 300)
    b = _crear(tmp_path, f"{ID_SUBWAY}_0_40.mp4", 500, 100)
    assert fondos_remotos.podar_cache(tmp_path, limite=5000) == []
    fondos_remotos.podar_cache(tmp_path, limite=10, conservar=a)
    assert a.exists() and not b.exists()
    assert fondos_remotos.podar_cache(tmp_path / "no_existe") == []


def test_limite_de_la_cache_es_1_gb():
    assert fondos_remotos.LIMITE_CACHE_BYTES == 1024**3


def test_buscar_en_cache_exige_tramo_suficiente_del_mismo_video(tmp_path):
    _crear(tmp_path, f"{ID_MINECRAFT}_0_45.mp4", 10, 10)
    _crear(tmp_path, f"{ID_SUBWAY}_0_300.mp4", 10, 10)
    (tmp_path / f"{ID_MINECRAFT}_9_99.mp4").write_bytes(b"")            # vacio: no sirve
    (tmp_path / "otra_cosa.mp4").write_bytes(b"x")
    ruta, largo = fondos_remotos.buscar_en_cache(ID_MINECRAFT, 30, tmp_path)
    assert ruta.name == f"{ID_MINECRAFT}_0_45.mp4" and largo == 45
    assert fondos_remotos.buscar_en_cache(ID_MINECRAFT, 40, tmp_path) is None     # 45 < 40 + 10
    assert fondos_remotos.buscar_en_cache(ID_SUBWAY, 200, tmp_path)[1] == 300
    assert fondos_remotos.buscar_en_cache("zzzzzzzzzzz", 5, tmp_path) is None


def test_obtener_tramo_usa_la_cache_sin_descargar(tmp_path, monkeypatch):
    monkeypatch.setattr(fondos_remotos, "CACHE_DIR", tmp_path)
    guardado = _crear(tmp_path, f"{ID_MINECRAFT}_50_60.mp4", 10, 50)
    monkeypatch.setattr(fondos_remotos, "descargar_tramo", lambda *a, **k: pytest.fail("no debe descargar"))
    fondo = {"id": ID_MINECRAFT, "duracion": 3487}
    ruta, inicio = fondos_remotos.obtener_tramo(fondo, 20, tmp_path / "trabajo", None)
    assert ruta == guardado and 0 <= inicio <= 60 - 20
    assert time.time() - guardado.stat().st_mtime < 5       # marcado como usado ahora


def test_obtener_tramo_descarga_guarda_en_cache_y_poda(tmp_path, monkeypatch):
    monkeypatch.setattr(fondos_remotos, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fondos_remotos, "LIMITE_CACHE_BYTES", 100)
    peticiones = []

    def falso(id_, desde, hasta, destino, cancel, progreso=None):
        peticiones.append((id_, desde, hasta))
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "fondo.mp4").write_bytes(b"v" * 80)
        return destino / "fondo.mp4"

    monkeypatch.setattr(fondos_remotos, "descargar_tramo", falso)
    monkeypatch.setattr(fondos_remotos, "sondear", lambda ruta: {"duracion": 35.0})
    class Cancel:
        def comprobar(self): pass
    fondo = {"id": ID_MINECRAFT, "duracion": 3487}
    ruta, inicio = fondos_remotos.obtener_tramo(fondo, 15, tmp_path / "t1", Cancel())
    assert inicio == 0.0 and ruta.parent == tmp_path / "cache" and ruta.read_bytes() == b"v" * 80
    assert len(peticiones) == 1 and peticiones[0][2] - peticiones[0][1] == 35        # clip 15 s + 20 s
    # segunda vez: sale de la cache (35 >= 15 + 10), no hay otra descarga
    fondos_remotos.obtener_tramo(fondo, 15, tmp_path / "t2", Cancel())
    assert len(peticiones) == 1
    # otro fondo: se descarga y la poda (limite 100 B) borra el anterior
    otro = {"id": ID_SUBWAY, "duracion": 4570}
    ruta2, _ = fondos_remotos.obtener_tramo(otro, 15, tmp_path / "t3", Cancel())
    assert ruta2.exists() and not ruta.exists()


# ---------- credito en el ASS ----------

def _lineas_credito(ass):
    return [l for l in ass.splitlines() if l.startswith("Dialogue") and ",Credito," in l]


def test_credito_se_dibuja_abajo_a_la_izquierda_de_la_franja():
    for prop in (25, 45, 60):
        ass = subtitles.a_ass([], 0, 10, {"credito_fondo": True, "juego_proporcion": prop}, credito="Fondo: perpexior (YouTube)")
        (linea,) = _lineas_credito(ass)
        x, y = map(int, re.search(r"\\pos\((\d+),(\d+)\)", linea).groups())
        franja = int(config.OUT_H * prop / 100) // 2 * 2
        assert "\\an1" in linea                                   # ancla inferior izquierda
        assert x == 24 and y == config.OUT_H - 24                 # a 24 px de los bordes
        assert config.OUT_H - franja <= y <= config.OUT_H         # dentro de la franja del juego
        assert linea.endswith("Fondo: perpexior (YouTube)")
        assert ",0:00:00.00,0:00:10.00," in linea                 # todo el clip


def test_credito_tamano_y_estilo():
    ass = subtitles.a_ass([], 0, 5, {"credito_fondo": True, "credito_tamano": 40}, credito="Fondo: x (YouTube)")
    estilo = next(l for l in ass.splitlines() if l.startswith("Style: Credito"))
    campos = estilo.split(",")
    assert campos[1] == "Arial" and campos[2] == "40"
    assert campos[3] == "&H00FFFFFF" and campos[5] == "&H00000000"      # blanco con contorno negro
    assert float(campos[16]) <= 3                                      # contorno fino


def test_credito_se_sanea():
    ass = subtitles.a_ass([], 0, 5, {"credito_fondo": True}, credito="Fondo: {\\an8\\pos(0,0)}hack\nseguido (YouTube)")
    (linea,) = _lineas_credito(ass)
    texto = linea.split("}", 1)[1]
    assert "{" not in texto and "}" not in texto and "\\" not in texto and "\n" not in texto
    assert linea.count("\\pos(") == 1 and "\\an8" not in linea
    largo = subtitles.a_ass([], 0, 5, {"credito_fondo": True}, credito="x" * 500)
    assert len(_lineas_credito(largo)[0].split("}", 1)[1]) <= 100


def test_sin_credito_o_con_la_casilla_apagada_no_se_dibuja():
    assert _lineas_credito(subtitles.a_ass([], 0, 5, {"credito_fondo": True}, credito="")) == []
    assert _lineas_credito(subtitles.a_ass([], 0, 5, {"credito_fondo": True})) == []
    assert _lineas_credito(subtitles.a_ass([], 0, 5, {"credito_fondo": False}, credito="Fondo: x (YouTube)")) == []
    assert _lineas_credito(subtitles.a_ass([], 0, 5, None, credito="Fondo: x (YouTube)")) == []


def test_tiene_contenido_con_credito():
    assert not subtitles.tiene_contenido([], {"credito_fondo": True})
    assert not subtitles.tiene_contenido([], {"credito_fondo": False}, "Fondo: x (YouTube)")
    assert subtitles.tiene_contenido([], {"credito_fondo": True}, "Fondo: x (YouTube)")


# ---------- catalogo, API y eleccion del fondo ----------

@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(config, "FONDOS_DIR", tmp_path / "fondos")
    db.iniciar()
    return TestClient(app, base_url="http://127.0.0.1:8765")


def _falso_consultar(id_):
    return {"id": id_, "titulo": "Video nuevo", "canal": "Canal X", "duracion": 900.0,
            "licencia": "Licencia estándar de YouTube", "credito": "Fondo: Canal X (YouTube)"}


def test_catalogo_inicial_y_datos_de_serie(cliente):
    r = cliente.get("/api/fondos").json()
    assert r["locales"] == [] and r["fondos"] == [] and "carpeta" in r and r["ocultos"] == []
    por_id = {f["id"]: f for f in r["remotos"]}
    assert set(por_id) == {ID_MINECRAFT, ID_SUBWAY}
    m, s = por_id[ID_MINECRAFT], por_id[ID_SUBWAY]
    assert (m["titulo"], m["canal"], m["duracion"], m["credito"]) == ("Minecraft parkour", "perpexior", 3487, "Fondo: perpexior (YouTube)")
    assert (s["titulo"], s["canal"], s["duracion"], s["credito"]) == ("Subway Surfers", "OrbitalNCG +", 4570, "Fondo: OrbitalNCG + (YouTube)")
    assert m["valor"] == "yt:" + ID_MINECRAFT and m["url"].endswith("eBExtYRpuqI") and m["de_serie"]
    assert "Creative Commons" in s["licencia"] and "Royalty Free" in m["licencia"]


def test_anadir_y_quitar_un_fondo(cliente, monkeypatch):
    monkeypatch.setattr(fondos_remotos, "consultar", _falso_consultar)
    r = cliente.post("/api/fondos/remotos", json={"url": "https://youtu.be/abcdefghijk"})
    assert r.status_code == 201 and r.json()["fondo"]["valor"] == "yt:abcdefghijk"
    ids = [f["id"] for f in r.json()["remotos"]]
    assert ids == [ID_MINECRAFT, ID_SUBWAY, "abcdefghijk"]
    assert cliente.post("/api/fondos/remotos", json={"url": "https://youtu.be/abcdefghijk"}).status_code == 201
    assert len(cliente.get("/api/fondos").json()["remotos"]) == 3                     # sin duplicados
    d = cliente.delete("/api/fondos/remotos/abcdefghijk")
    assert d.status_code == 200 and d.json()["resultado"] == "quitado"
    assert [f["id"] for f in cliente.get("/api/fondos").json()["remotos"]] == [ID_MINECRAFT, ID_SUBWAY]
    assert cliente.delete("/api/fondos/remotos/abcdefghijk").status_code == 404
    assert cliente.delete("/api/fondos/remotos/no-valido").status_code == 404


def test_los_de_serie_se_ocultan_y_se_vuelven_a_mostrar(cliente):
    d = cliente.delete(f"/api/fondos/remotos/{ID_SUBWAY}").json()
    assert d["resultado"] == "oculto"
    assert [f["id"] for f in d["remotos"]] == [ID_MINECRAFT] and [f["id"] for f in d["ocultos"]] == [ID_SUBWAY]
    assert fondos_remotos.buscar(ID_SUBWAY)["oculto"] is True
    r = cliente.post("/api/fondos/remotos", json={"url": f"https://www.youtube.com/watch?v={ID_SUBWAY}"})
    assert r.status_code == 201 and [f["id"] for f in r.json()["remotos"]] == [ID_MINECRAFT, ID_SUBWAY]


def test_anadir_rechaza_enlaces_no_validos(cliente, monkeypatch):
    monkeypatch.setattr(fondos_remotos, "consultar", lambda _id: pytest.fail("no debe consultar"))
    for url in ("https://vimeo.com/1", "https://www.youtube.com/playlist?list=PL1", "prueba:x.mp4",
                "http://127.0.0.1/watch?v=abcdefghijk", "no es una url"):
        r = cliente.post("/api/fondos/remotos", json={"url": url})
        assert r.status_code == 422, url
        assert r.json()["detail"]


def test_anadir_muestra_el_error_de_red_en_espanol(cliente, monkeypatch):
    def sin_red(_id):
        raise ErrorMedia("Sin conexión: no se pudo descargar el fondo de YouTube.")
    monkeypatch.setattr(fondos_remotos, "consultar", sin_red)
    r = cliente.post("/api/fondos/remotos", json={"url": "https://youtu.be/abcdefghijk"})
    assert r.status_code == 502 and "Sin conexión" in r.json()["detail"]


def test_limite_de_fondos_anadidos(cliente, monkeypatch):
    monkeypatch.setattr(fondos_remotos, "consultar", _falso_consultar)
    for i in range(fondos_remotos.MAX_ANADIDOS):
        assert cliente.post("/api/fondos/remotos", json={"url": f"https://youtu.be/video{i:06d}"}).status_code == 201
    assert cliente.post("/api/fondos/remotos", json={"url": "https://youtu.be/otroOtroOtr"}).status_code == 422


def test_los_fondos_locales_siguen_en_fondos_y_en_locales(cliente, tmp_path):
    (tmp_path / "fondos").mkdir()
    (tmp_path / "fondos" / "mio.mp4").write_bytes(b"1234")
    (tmp_path / "fondos" / "notas.txt").write_text("no")
    r = cliente.get("/api/fondos").json()
    assert [f["nombre"] for f in r["fondos"]] == ["mio.mp4"] == [f["nombre"] for f in r["locales"]]
    assert cliente.get("/api/fondos/notas.txt/video").status_code == 404


def test_mensajes_de_error_de_descarga():
    m = fondos_remotos._mensaje_descarga
    assert "Sin conexión" in m(Exception("<urlopen error [Errno 11001] getaddrinfo failed>"))
    assert "ya no está disponible" in m(Exception("ERROR: [youtube] x: Video unavailable"))
    assert "ya no está disponible" in m(Exception("Private video"))
    assert "bloqueando" in m(Exception("ERROR: Sign in to confirm you're not a bot"))
    assert "bloqueando" in m(Exception("HTTP Error 403: Forbidden"))


def test_elegir_fondo_remoto_local_y_al_azar(cliente, tmp_path):
    # Sin locales: "al azar" elige entre los remotos visibles y trae su credito.
    f = pipeline._elegir_fondo({"fondo_juego": ""})
    assert f["remoto"]["id"] in (ID_MINECRAFT, ID_SUBWAY) and f["credito"].startswith("Fondo: ")
    f = pipeline._elegir_fondo({"fondo_juego": "yt:" + ID_SUBWAY})
    assert f["remoto"]["id"] == ID_SUBWAY and f["credito"] == "Fondo: OrbitalNCG + (YouTube)"
    # Un id desconocido vuelve al azar entre los visibles.
    assert pipeline._elegir_fondo({"fondo_juego": "yt:zzzzzzzzzzz"})["remoto"]["id"] in (ID_MINECRAFT, ID_SUBWAY)
    # Un oculto no se usa aunque el clip lo guardara.
    fondos_remotos.quitar(ID_SUBWAY)
    for _ in range(10):
        assert pipeline._elegir_fondo({"fondo_juego": "yt:" + ID_SUBWAY})["remoto"]["id"] == ID_MINECRAFT
    # Con locales, "al azar" prefiere los locales (sin credito).
    (tmp_path / "fondos").mkdir()
    (tmp_path / "fondos" / "mio.mp4").write_bytes(b"1234")
    f = pipeline._elegir_fondo({"fondo_juego": ""})
    assert f["ruta"].name == "mio.mp4" and f["credito"] == ""
    assert pipeline._elegir_fondo({"fondo_juego": "mio.mp4"})["ruta"].name == "mio.mp4"
    f = pipeline._elegir_fondo({"fondo_juego": "yt:" + ID_MINECRAFT})        # el elegido manda
    assert f["remoto"]["id"] == ID_MINECRAFT


def test_sin_fondos_el_error_es_claro(cliente):
    fondos_remotos.quitar(ID_MINECRAFT)
    fondos_remotos.quitar(ID_SUBWAY)
    with pytest.raises(ErrorMedia, match="fondo"):
        pipeline._elegir_fondo({"fondo_juego": ""})
