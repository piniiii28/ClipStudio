"""Carpetas configurables: validacion, copia de exportaciones y rutas de la API."""

from pathlib import Path

import pytest

from clipstudio import ajustes, config, db


@pytest.fixture(autouse=True)
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "datos.sqlite")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "datos")
    monkeypatch.setattr(config, "ROOT", tmp_path / "app")
    monkeypatch.setattr(config, "BUNDLE_DIR", tmp_path / "app")
    monkeypatch.setattr(config, "FONDOS_DIR", tmp_path / "datos" / "fondos")
    monkeypatch.setattr(config, "VIVO_DIR", tmp_path / "datos" / "vivo")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "datos" / "proyectos")
    db.iniciar()
    ajustes._elegidas.clear()
    yield
    ajustes._elegidas.clear()


# ---------- validacion ----------

def test_carpeta_que_no_existe_se_crea(tmp_path):
    destino = tmp_path / "videos" / "exportados"
    assert not destino.exists()
    assert ajustes.validar_carpeta(str(destino)) == destino
    assert destino.is_dir()
    assert list(destino.iterdir()) == []          # el archivo de prueba de escritura no queda


def test_carpeta_inexistente_sin_crear_se_rechaza(tmp_path):
    with pytest.raises(ValueError, match="no existe"):
        ajustes.validar_carpeta(str(tmp_path / "nada"), crear=False)


def test_rechaza_vacia_relativa_y_archivos(tmp_path):
    with pytest.raises(ValueError, match="Escribe o elige"):
        ajustes.validar_carpeta("   ")
    with pytest.raises(ValueError, match="ruta completa"):
        ajustes.validar_carpeta("videos\\clips")
    archivo = tmp_path / "x.txt"
    archivo.write_text("a")
    with pytest.raises(ValueError, match="archivo, no una carpeta"):
        ajustes.validar_carpeta(str(archivo))


def test_sin_permiso_de_escritura(tmp_path, monkeypatch):
    def prohibido(carpeta):
        raise PermissionError(13, "Acceso denegado")
    monkeypatch.setattr(ajustes, "_probar_escritura", prohibido)
    with pytest.raises(ValueError, match="No se puede escribir"):
        ajustes.validar_carpeta(str(tmp_path / "solo_lectura"))


def test_no_se_puede_crear(tmp_path):
    archivo = tmp_path / "bloqueo"
    archivo.write_text("a")
    with pytest.raises(ValueError):
        ajustes.validar_carpeta(str(archivo / "dentro"))      # el padre es un archivo


def test_rechaza_la_raiz_de_un_disco(tmp_path):
    with pytest.raises(ValueError, match="raíz de un disco"):
        ajustes.validar_carpeta(tmp_path.anchor)


def test_rechaza_carpetas_de_la_aplicacion(tmp_path):
    (tmp_path / "app").mkdir()
    with pytest.raises(ValueError, match="carpeta de la aplicación"):
        ajustes.validar_carpeta(str(tmp_path / "app"))
    with pytest.raises(ValueError, match="carpeta de la aplicación"):
        ajustes.validar_carpeta(str(tmp_path / "app" / "videos"))
    assert not (tmp_path / "app" / "videos").exists()


def test_la_carpeta_de_datos_dentro_de_la_app_si_vale(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "app" / "datos")
    assert ajustes.validar_carpeta(str(tmp_path / "app" / "datos" / "fondos")).is_dir()


# ---------- nombres y copia ----------

def test_nombre_legible_sanea_el_titulo():
    assert ajustes.nombre_legible("Gol: ¡el mejor?", "abcdef1234") == "Gol ¡el mejor_abcdef12.mp4"
    assert ajustes.nombre_legible('a<b>c|d"e/f\\g*h', "1") == "a b c d e f g h_1.mp4"
    assert ajustes.nombre_legible("CON", "xyz") == "clip_xyz.mp4"
    assert ajustes.nombre_legible("...", "xyz") == "clip_xyz.mp4"
    assert ajustes.nombre_legible("", "") == "clip_x.mp4"
    assert len(ajustes.nombre_legible("a" * 300, "12345678")) <= 80 + len("_12345678.mp4")


def test_copia_sin_pisar_archivos(tmp_path):
    origen = tmp_path / "salida.mp4"
    origen.write_bytes(b"uno")
    destino = tmp_path / "exportados"
    primera = ajustes.copiar_exportacion(origen, "Mi clip", "abc12345xyz", destino)
    assert primera == destino / "Mi clip_abc12345.mp4"
    origen.write_bytes(b"dos")
    segunda = ajustes.copiar_exportacion(origen, "Mi clip", "abc12345xyz", destino)
    tercera = ajustes.copiar_exportacion(origen, "Mi clip", "abc12345xyz", destino)
    assert segunda.name == "Mi clip_abc12345 (2).mp4" and tercera.name == "Mi clip_abc12345 (3).mp4"
    assert primera.read_bytes() == b"uno" and segunda.read_bytes() == b"dos"
    assert sorted(p.name for p in destino.iterdir()) == sorted([primera.name, segunda.name, tercera.name])  # sin temporales


def test_copia_sin_carpeta_elegida_no_hace_nada(tmp_path):
    origen = tmp_path / "salida.mp4"
    origen.write_bytes(b"x")
    assert ajustes.carpeta_exportaciones() is None
    assert ajustes.copiar_exportacion(origen, "t", "i") is None


# ---------- rutas efectivas y API ----------

def test_rutas_efectivas(tmp_path):
    assert ajustes.carpeta_fondos() == config.FONDOS_DIR
    assert ajustes.carpeta_vivo() == config.VIVO_DIR
    ajustes._elegidas.update(fondos=str(tmp_path / "f"), vivo=str(tmp_path / "v"))
    assert ajustes.carpeta_fondos() == tmp_path / "f"
    assert ajustes.carpeta_vivo() == tmp_path / "v" / ajustes.SUBCARPETA_BUFER   # subcarpeta propia


def test_los_fondos_se_listan_desde_la_carpeta_elegida(tmp_path):
    from clipstudio import pipeline
    carpeta = tmp_path / "mis_fondos"
    carpeta.mkdir()
    (carpeta / "juego.mp4").write_bytes(b"x")
    (carpeta / "nota.txt").write_text("x")
    ajustes._elegidas["fondos"] = str(carpeta)
    assert [f.name for f in pipeline.listar_fondos()] == ["juego.mp4"]


def test_api_elegir_restablecer_y_persistencia(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from clipstudio.api import app
    abiertas = []
    monkeypatch.setattr("os.startfile", abiertas.append, raising=False)
    c = TestClient(app, base_url="http://localhost")
    base = c.get("/api/ajustes").json()
    assert [x["clave"] for x in base["carpetas"]] == ["exportaciones", "vivo", "fondos"]
    assert not any(x["personalizada"] for x in base["carpetas"]) and base["datos"]["ruta"] == str(config.DATA_DIR)

    destino = tmp_path / "salida" / "mp4"
    r = c.put("/api/ajustes/carpetas/exportaciones", json={"ruta": str(destino)})
    assert r.status_code == 200 and destino.is_dir()
    ficha = next(x for x in r.json()["carpetas"] if x["clave"] == "exportaciones")
    assert ficha["personalizada"] and ficha["ruta"] == str(destino) and ficha["libre_gb"] is not None
    assert db.leer_preferencia("carpetas") == {"exportaciones": str(destino)}

    ajustes._elegidas.clear()
    ajustes.cargar()                                   # como al arrancar la app
    assert ajustes.carpeta_exportaciones() == destino

    assert c.put("/api/ajustes/carpetas/exportaciones", json={"ruta": "relativa"}).status_code == 422
    assert c.put("/api/ajustes/carpetas/otra", json={"ruta": str(destino)}).status_code == 404
    assert c.post("/api/ajustes/abrir/exportaciones").json()["carpeta"] == str(destino)
    assert c.post("/api/ajustes/abrir/datos").json()["carpeta"] == str(config.DATA_DIR)
    assert abiertas == [destino, config.DATA_DIR]

    r = c.delete("/api/ajustes/carpetas/exportaciones")
    assert not next(x for x in r.json()["carpetas"] if x["clave"] == "exportaciones")["personalizada"]
    assert ajustes.carpeta_exportaciones() is None and db.leer_preferencia("carpetas") == {}


def test_api_avisa_si_se_cambia_el_bufer_con_una_sesion_activa(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from clipstudio import vivo
    from clipstudio.api import app
    c = TestClient(app, base_url="http://localhost")
    monkeypatch.setattr(vivo, "sesion_actual", lambda: SimpleNamespace(estado="grabando"))
    r = c.put("/api/ajustes/carpetas/vivo", json={"ruta": str(tmp_path / "bufer")})
    assert "al volver a conectar" in r.json()["aviso"]
    r = c.put("/api/ajustes/carpetas/fondos", json={"ruta": str(tmp_path / "fondos")})
    assert r.json()["aviso"] is None


def test_exportar_copia_a_la_carpeta_elegida(tmp_path, monkeypatch):
    """pipeline.exportar deja la copia interna y una copia legible en la carpeta elegida."""
    from clipstudio import media, pipeline
    fuente = tmp_path / "fuente.mp4"
    fuente.touch()
    clip = {"inicio": 0, "fin": 10, "encuadre": "rellenar", "recorte_x": .5, "estilo": {}, "subtitulos": []}
    exp = {"id": "e1", "clip_id": "clip1234abcd", "titulo": "Mi: clip", "proyecto_id": "p", "parametros": clip}
    cambios = {}
    monkeypatch.setattr(pipeline.db, "obtener", lambda tabla, _: exp if tabla == "exportaciones" else {"id": "p"})
    monkeypatch.setattr(pipeline.db, "actualizar", lambda tabla, id_, **kw: cambios.update(kw))
    monkeypatch.setattr(pipeline, "ruta_fuente", lambda _: fuente)
    monkeypatch.setattr(pipeline, "carpeta_proyecto", lambda _: tmp_path / "proy")
    monkeypatch.setattr(media, "sondear", lambda _: {"pista_video": 0, "tiene_audio": False})
    monkeypatch.setattr(media, "exportar_clip", lambda fuente, destino, *a, **k: destino.write_bytes(b"mp4"))
    elegida = tmp_path / "elegida"
    ajustes._elegidas["exportaciones"] = str(elegida)
    pipeline.exportar("e1", media.Cancelacion())
    assert (tmp_path / "proy" / "exportaciones" / "e1.mp4").read_bytes() == b"mp4"
    copia = Path(cambios["copia"])
    assert copia == elegida / "Mi clip_clip1234.mp4" and copia.read_bytes() == b"mp4" and cambios["aviso"] is None
