"""Pruebas de cortes internos; no necesitan ejecutar FFmpeg."""

from pathlib import Path

import pytest

from clipstudio import cortes, media


def tramo(a, b, **otros):
    return {"inicio": a, "fin": b, **otros}


def test_normalizar_ordena_fusiona_recorta_y_descarta():
    entrada = [tramo(8, 14), tramo(4, 6), tramo(3, 5), tramo(-3, 1), tramo(7, 7.04)]
    assert cortes.normalizar(entrada, 0, 10) == [tramo(0, 1), tramo(3, 6), tramo(8, 10)]
    assert entrada[0]["fin"] == 14
    assert cortes.normalizar([tramo(3, 3.05)], 0, 10) == [tramo(3, 3.05)]
    assert cortes.normalizar([tramo(20, 30)], 0, 10) == []


@pytest.mark.parametrize("entrada", [None, {}, [1], [{}], [tramo("1", 2)], [tramo(True, 2)],
                                    [tramo(0, float("nan"))], [tramo(0, float("inf"))],
                                    [tramo(2, 1)], [tramo(1, 1)], [tramo(0, 1)] * 201])
def test_normalizar_rechaza_entradas_invalidas(entrada):
    with pytest.raises(ValueError):
        cortes.normalizar(entrada, 0, 10)


def test_minimo_util():
    assert cortes.normalizar([tramo(1, 10)], 0, 10) == [tramo(1, 10)]
    with pytest.raises(ValueError, match="1 segundo"):
        cortes.normalizar([tramo(.9, 10)], 0, 10)


def test_conservados_y_duracion():
    lista = [tramo(12, 14), tramo(16, 18)]
    assert cortes.tramos_conservados(10, 20, lista) == [[10, 12], [14, 16], [18, 20]]
    assert cortes.duracion_final(10, 20, lista) == 6
    assert cortes.tramos_conservados(10, 20, []) == [[10, 20]]


@pytest.mark.parametrize("t, esperado", [(9, 0), (11, 1), (12, 2), (13, 2), (14, 2), (15, 3), (19, 5)])
def test_tiempo_final(t, esperado):
    assert cortes.a_tiempo_final(t, 10, [tramo(12, 14), tramo(16, 18)]) == esperado


def test_remapear_subtitulos():
    cues = [tramo(12, 13, texto="fuera"), tramo(11, 13, texto="borde"),
            tramo(13, 15, texto="otro"), tramo(15, 19, texto="cruza"), tramo(19.98, 22, texto="breve")]
    assert cortes.remapear_subtitulos(cues, 10, 20, [tramo(12, 14), tramo(16, 18)]) == [
        tramo(1, 2, texto="borde"), tramo(2, 3, texto="otro"), tramo(3, 5, texto="cruza")]
    assert cues[0]["inicio"] == 12


def test_remapear_palabras():
    palabras = [tramo(11, 11.4, texto="uno"), tramo(12, 13, texto="fuera"),
                tramo(14, 14.4, texto="dos"), tramo(11.8, 12.1, texto="borde")]
    salida = cortes.remapear_palabras(palabras, 10, [tramo(12, 14)])
    assert [p["texto"] for p in salida] == ["uno", "dos", "borde"]
    assert salida[1]["inicio"] == 2
    assert salida[-1]["fin"] == 2


def test_silencios_con_margen_y_limites():
    segmentos = [{"palabras": [tramo(1, 2), tramo(2.3, 3), tramo(5, 6)]}]
    assert cortes.silencios(segmentos, 0, 7) == [tramo(.12, .88), tramo(3.12, 4.88), tramo(6.12, 6.88)]
    assert cortes.silencios([], 0, 7) == []
    assert cortes.silencios([{"palabras": []}], 0, 7) == []
    assert cortes.silencios([{"palabras": [tramo(0, 10), tramo(2, 3)]}], 0, 10) == []


def argumentos(monkeypatch, tmp_path, **opciones):
    capturado = {}
    def capturar(args, duracion, cancel, progreso, cwd=None):
        capturado.update(args=args, duracion=duracion)
    monkeypatch.setattr(media, "ejecutar_ffmpeg", capturar)
    media.exportar_clip(tmp_path / "fuente.mp4", tmp_path / "salida.mp4", 10, 20,
                        opciones.pop("encuadre", "rellenar"), .5, None, media.Cancelacion(), lambda _: None, **opciones)
    args = capturado["args"]
    return args, args[args.index("-filter_complex") + 1], capturado["duracion"]


def test_argumentos_con_cortes(monkeypatch, tmp_path):
    args, grafo, duracion = argumentos(monkeypatch, tmp_path, conservar=[(0, 2), (5, 8)])
    seleccion = "between(t,0.000,2.000)+between(t,5.000,8.000)"
    assert f"select='{seleccion}'" in grafo and f"aselect='{seleccion}'" in grafo
    assert "fps=30" in grafo and "setpts=N/30/TB" in grafo and "asetpts=N/SR/TB[a]" in grafo
    assert args[args.index("-map", args.index("-map") + 1) + 1] == "[a]"
    assert args[-3:-1] == ["-t", "5.000"] and duracion == 5
    assert args[:4] == ["-ss", "10.000", "-t", "10.000"]


def test_sin_cortes_grafo_y_argumentos_iguales(monkeypatch, tmp_path):
    args, grafo, duracion = argumentos(monkeypatch, tmp_path)
    assert grafo == "[0:v:0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:(iw-1080)*0.5000:(ih-1920)/2,setsar=1[v0];[v0]null[v]"
    assert "0:a:0?" in args and "[a]" not in args and duracion == 10
    assert argumentos(monkeypatch, tmp_path, conservar=[(0, 10)])[0] == args


def test_cortes_sin_audio(monkeypatch, tmp_path):
    args, grafo, _ = argumentos(monkeypatch, tmp_path, conservar=[(2, 5)], tiene_audio=False)
    assert "aselect" not in grafo and "[0:a" not in grafo
    assert "0:a:0?" in args


def test_dividido_solo_corta_arriba(monkeypatch, tmp_path):
    _, grafo, _ = argumentos(monkeypatch, tmp_path, encuadre="dividido", juego=Path("juego.mp4"), conservar=[(0, 2), (5, 8)])
    arriba, abajo, resto = grafo.split(";", 2)
    assert "select=" in arriba and arriba.endswith("[top]")
    assert abajo.startswith("[1:v:0]") and "select" not in abajo and "setpts" not in abajo
    assert resto.startswith("[top][bot]vstack")


def test_migracion_y_lectura_de_clips_antiguos(monkeypatch, tmp_path):
    from clipstudio import config, db
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "datos.sqlite")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    with db.conectar() as con:
        con.executescript(db.SCHEMA)
    db.iniciar()
    db.iniciar()
    p = db.insertar("proyectos", {"nombre": "Prueba", "origen": "archivo", "estado": "listo"})
    c = db.insertar("clips", {"proyecto_id": p["id"], "titulo": "Antiguo", "inicio": 0, "fin": 10})
    assert db.obtener("clips", c["id"])["cortes"] == []
    assert db.obtener("clips", c["id"])["trayectoria"] == []
    puntos = [{"tiempo": 0, "centro_x": .3}, {"tiempo": 10, "centro_x": .7}]
    db.actualizar("clips", c["id"], trayectoria=puntos)
    assert db.obtener("clips", c["id"])["trayectoria"] == puntos
    db.actualizar("clips", c["id"], cortes=[tramo(2, 4)])
    assert db.obtener("clips", c["id"])["cortes"] == [tramo(2, 4)]


@pytest.fixture
def api_clip(monkeypatch):
    from clipstudio import api
    c = {"id": "clip", "proyecto_id": "proyecto", "titulo": "Prueba", "inicio": 10, "fin": 20,
         "cortes": [tramo(12, 14)], "subtitulos": [], "estilo": {}, "encuadre": "rellenar", "recorte_x": .5}
    monkeypatch.setattr(api.db, "obtener", lambda tabla, id_: dict(c) if tabla == "clips" else {"id": "proyecto", "duracion": 30})
    monkeypatch.setattr(api.db, "actualizar", lambda tabla, id_, **campos: c.update(campos))
    monkeypatch.setattr(api.pipeline, "leer_transcripcion", lambda _: {"segmentos": []})
    return api, c


def test_api_valida_y_renormaliza_rangos(api_clip):
    api, c = api_clip
    api.editar_clip("clip", api.ClipCambios(inicio=13))
    assert c["cortes"] == [tramo(13, 14)]
    api.editar_clip("clip", api.ClipCambios(fin=14))
    assert c["cortes"] == []
    with pytest.raises(api.HTTPException) as exc:
        api.editar_clip("clip", api.ClipCambios(cortes=[tramo(13, 14)]))
    assert exc.value.status_code == 422


def test_api_silencios_y_copia_de_exportacion(api_clip, monkeypatch):
    api, c = api_clip
    with pytest.raises(api.HTTPException) as exc:
        api.quitar_silencios("clip")
    assert exc.value.status_code == 409
    monkeypatch.setattr(api.pipeline, "leer_transcripcion", lambda _: {"segmentos": [
        {"palabras": [tramo(10, 11), tramo(15, 20)]} ]})
    nuevo = api.quitar_silencios("clip", api.QuitarSilencios())
    assert nuevo["cortes"] == [tramo(11.12, 14.88)]
    import copy
    monkeypatch.setattr(api.db, "insertar", lambda tabla, campos: {"id": "exp", **copy.deepcopy(campos)})
    monkeypatch.setattr(api.gestor, "encolar", lambda *args: True)
    exp = api._encolar_exportacion(c)
    c["cortes"].clear()
    assert exp["parametros"]["cortes"] == [tramo(11.12, 14.88)]


def test_encuadre_manual_y_rango_desactivan_seguimiento(api_clip):
    api, c = api_clip
    puntos = [{"tiempo": 10, "centro_x": .3}, {"tiempo": 20, "centro_x": .7}]
    for cambios in ({"recorte_x": .2}, {"inicio": 11}, {"seguimiento": False}):
        c["trayectoria"] = puntos
        api.editar_clip("clip", api.ClipCambios(**cambios))
        assert c["trayectoria"] == []


def test_exportacion_guarda_copia_del_seguimiento(api_clip, monkeypatch):
    import copy
    api, c = api_clip
    c["trayectoria"] = [{"tiempo": 10, "centro_x": .3}, {"tiempo": 20, "centro_x": .7}]
    monkeypatch.setattr(api.db, "insertar", lambda tabla, campos: {"id": "exp", **copy.deepcopy(campos)})
    monkeypatch.setattr(api.gestor, "encolar", lambda *args: True)
    exp = api._encolar_exportacion(c)
    c["trayectoria"].clear()
    assert len(exp["parametros"]["trayectoria"]) == 2


@pytest.mark.parametrize("con_cortes", [True, False])
def test_pipeline_remapea_ass_y_admite_exportaciones_antiguas(monkeypatch, tmp_path, con_cortes):
    from clipstudio import pipeline, subtitles
    fuente = tmp_path / "fuente.mp4"
    fuente.touch()
    clip = {"inicio": 10, "fin": 20, "encuadre": "rellenar", "recorte_x": .5,
            "estilo": {"resaltar": True, "marca": "Canal", "titulo_gancho": "Titulo", "gancho_segundos": 0},
            "subtitulos": [tramo(14, 16, texto="palabra")]}
    if con_cortes:
        clip["cortes"] = [tramo(12, 14)]
    exp = {"proyecto_id": "p", "parametros": clip}
    monkeypatch.setattr(pipeline.db, "obtener", lambda tabla, _: exp if tabla == "exportaciones" else {"id": "p"})
    monkeypatch.setattr(pipeline.db, "actualizar", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "ruta_fuente", lambda _: fuente)
    monkeypatch.setattr(pipeline, "carpeta_proyecto", lambda _: tmp_path)
    monkeypatch.setattr(pipeline, "leer_transcripcion", lambda _: {"segmentos": [{"palabras": [tramo(14, 16, texto="palabra")]}]})
    monkeypatch.setattr(media, "sondear", lambda _: {"pista_video": 0, "tiene_audio": False})
    real = subtitles.a_ass
    capturado = {}
    def ass(cues, inicio, fin, estilo, palabras):
        capturado.update(cues=cues, inicio=inicio, fin=fin, palabras=palabras)
        return real(cues, inicio, fin, estilo, palabras)
    monkeypatch.setattr(subtitles, "a_ass", ass)
    def exportar(fuente, destino, inicio, fin, encuadre, recorte, archivo, *args, **kwargs):
        contenido = archivo.read_text(encoding="utf-8")
        esperado = "0:00:08.00" if con_cortes else "0:00:10.00"
        assert esperado + ",Gancho" in contenido and esperado + ",Marca" in contenido
        assert kwargs["tiene_audio"] is False
        assert kwargs["conservar"] == ([(0, 2), (4, 10)] if con_cortes else None)
        destino.touch()
    monkeypatch.setattr(media, "exportar_clip", exportar)
    pipeline.exportar("exp", media.Cancelacion())
    assert capturado["inicio"] == (0 if con_cortes else 10)
    assert capturado["fin"] == (8 if con_cortes else 20)
    assert capturado["cues"][0]["inicio"] == (2 if con_cortes else 14)
    assert capturado["palabras"][0]["inicio"] == (2 if con_cortes else 14)


def test_api_descarga_srt_con_cortes_y_duplica_clip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from clipstudio import api, config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "datos.sqlite")
    db.iniciar()
    proyecto = db.insertar("proyectos", {"nombre": "Prueba", "origen": "archivo",
                                        "duracion": 30, "estado": "listo"})
    clip = db.insertar("clips", {
        "proyecto_id": proyecto["id"], "titulo": "Edición", "inicio": 10, "fin": 20,
        "cortes": [tramo(12, 14)], "origen": "sugerido",
        "subtitulos": [
            {**tramo(11, 15), "texto": "Línea\n\nDos"},
            {**tramo(12.5, 13.5), "texto": "Eliminado"},
        ],
        "estilo": {"tamano": 74}, "encuadre": "dividido", "recorte_x": 0.7,
        "tiktok": {"contexto": "Tema", "texto": "#edicion"},
    })
    cliente = TestClient(api.app, base_url="http://localhost")
    url = f'/api/clips/{clip["id"]}'
    respuesta = cliente.get(url + "/subtitulos.srt")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-disposition"] == "attachment; filename*=UTF-8''Edici%C3%B3n.srt"
    assert respuesta.content.decode("utf-8") == "1\n00:00:01,000 --> 00:00:03,000\nLínea\nDos\n"

    respuesta = cliente.post(url + "/duplicar")
    assert respuesta.status_code == 201
    copia = respuesta.json()
    assert copia["id"] != clip["id"]
    assert copia["titulo"] == "Edición (copia)"
    assert copia["origen"] == "manual"
    for campo in ("encuadre", "recorte_x", "cortes", "subtitulos", "tiktok"):
        assert copia[campo] == clip[campo]
    assert copia["estilo"]["tamano"] == 74
    assert db.listar("exportaciones") == []

    assert cliente.patch(f'/api/clips/{copia["id"]}', json={"titulo": "Otra", "subtitulos": []}).status_code == 200
    assert cliente.get(f'/api/clips/{copia["id"]}/subtitulos.srt').status_code == 409
    assert cliente.get(url + "/subtitulos.srt").status_code == 200

    db.actualizar("clips", clip["id"], cortes=[])
    assert "00:00:01,000 --> 00:00:05,000" in cliente.get(url + "/subtitulos.srt").text
