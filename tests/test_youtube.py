import io
import json

import pytest

from clipstudio import importer, youtube


@pytest.mark.parametrize("url", [
    "https://youtu.be/abcdefghijk?t=12",
    "https://www.youtube.com/shorts/abcdefghijk",
    "https://m.youtube.com/watch?v=abcdefghijk&list=abc",
])
def test_normaliza_enlace_de_un_video(url):
    assert youtube.url_video(url) == "https://www.youtube.com/watch?v=abcdefghijk"


def test_rechaza_otros_destinos():
    with pytest.raises(ValueError):
        youtube.url_video("https://youtube.com.example.com/watch?v=abcdefghijk")


def test_tendencias_usa_region_y_no_incluye_directos(monkeypatch):
    respuesta = {"items": [
        {"id": "abcdefghijk", "snippet": {"title": "Video", "channelTitle": "Canal"}},
        {"id": "mnopqrstuvw", "snippet": {"liveBroadcastContent": "live"}},
    ]}

    def abrir(solicitud, timeout):
        assert "regionCode=CO" in solicitud.full_url
        assert "chart=mostPopular" in solicitud.full_url
        assert "clave-prueba" not in solicitud.full_url
        assert solicitud.get_header("X-goog-api-key") == "clave-prueba"
        return io.BytesIO(json.dumps(respuesta).encode())

    monkeypatch.setattr(youtube, "urlopen", abrir)
    assert youtube.tendencias("CO", "clave-prueba") == [
        {"titulo": "Video", "canal": "Canal", "url": "https://www.youtube.com/watch?v=abcdefghijk",
         "miniatura": "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"},
    ]


def test_audio_selecciona_la_pista_sin_sustituir_otro_idioma():
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True}) as ydl:
        selector = ydl.build_format_selector(importer.formato_audio("es-419"))
        formatos = [
            {"format_id": "v", "vcodec": "avc1", "acodec": "none", "height": 720, "ext": "mp4"},
            {"format_id": "es", "vcodec": "none", "acodec": "aac", "language": "es-419", "ext": "m4a"},
            {"format_id": "en", "vcodec": "none", "acodec": "aac", "language": "en", "ext": "m4a"},
        ]
        for formato in formatos:
            formato["protocol"] = "https"
        elegidos = list(selector({"formats": formatos}))
        assert [f["format_id"] for f in elegidos[0]["requested_formats"]] == ["v", "es"]
        assert list(selector({"formats": formatos[::2], "incomplete_formats": False})) == []
    with pytest.raises(ValueError):
        importer.formato_audio('es"]/b')


def test_api_persiste_audio_para_reintentos(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from clipstudio import api, config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "datos.sqlite")
    monkeypatch.setattr(config, "find_tool", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(api.gestor, "encolar", lambda *_: None)
    monkeypatch.setattr(config, "YOUTUBE_API_KEY", "")
    db.iniciar()
    cliente = TestClient(api.app, base_url="http://localhost")
    assert cliente.get("/api/youtube/tendencias").json() == {"configurado": False, "videos": []}
    datos = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "audio_idioma": "es-419"}
    respuesta = cliente.post("/api/proyectos/url", json=datos)
    assert respuesta.status_code == 201
    proyecto = db.obtener("proyectos", respuesta.json()["id"])
    assert proyecto["audio_idioma"] == "es-419"
    assert proyecto["idioma"] == "auto"
