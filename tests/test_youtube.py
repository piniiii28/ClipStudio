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


def test_selector_doblaje_admite_video_muxado_y_no_elige_su_audio():
    formatos = [
        {"format_id": "mux-en", "vcodec": "h264", "acodec": "aac", "height": 720, "language": "en", "protocol": "https"},
        {"format_id": "es", "vcodec": "none", "acodec": "aac", "language": "es", "protocol": "https"},
    ]
    selector = importer.selector_audio("es")
    elegido = list(selector({"formats": formatos}))[0]
    assert [f["format_id"] for f in elegido["requested_formats"]] == ["mux-en", "es"]
    assert elegido["requested_formats"][0]["acodec"] == "none"
    assert formatos[0]["acodec"] == "aac"  # no mutar metadatos originales
    assert list(selector({"formats": formatos[:1]})) == []
    assert list(selector({"formats": [{**formatos[0], "language": "es"}]}))[0]["language"] == "es"


def test_descarga_local_real_ytdlp_conserva_solo_el_doblaje_elegido(tmp_path):
    import shutil
    import subprocess
    import numpy as np
    from yt_dlp import YoutubeDL

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Requiere FFmpeg")
    video, audio = tmp_path / "en.mp4", tmp_path / "es.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=160x90:r=5", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libx264", "-c:a", "aac", str(video)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880", "-t", "1", "-c:a", "aac", str(audio)], check=True)
    salida = tmp_path / "elegido.mp4"
    formatos = [
        {"format_id": "mux-en", "url": video.as_uri(), "vcodec": "h264", "acodec": "aac", "height": 90, "language": "en", "ext": "mp4"},
        {"format_id": "audio-es", "url": audio.as_uri(), "vcodec": "none", "acodec": "aac", "language": "es", "ext": "m4a"},
    ]
    with YoutubeDL({"quiet": True, "enable_file_urls": True, "format": importer.selector_audio("es"), "outtmpl": str(salida), "merge_output_format": "mp4"}) as ydl:
        ydl.process_ie_result({"id": "doblaje", "title": "Doblaje", "formats": formatos}, download=True)
    pistas = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(salida)]))["streams"]
    assert sum(p["codec_type"] == "audio" for p in pistas) == 1
    pcm = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(salida), "-map", "0:a:0", "-f", "f32le", "-ac", "1", "-ar", "8000", "-"])
    onda = np.frombuffer(pcm, dtype="float32")
    frecuencia = np.fft.rfftfreq(len(onda), 1 / 8000)[np.argmax(abs(np.fft.rfft(onda)))]
    assert frecuencia == pytest.approx(880, abs=5)
