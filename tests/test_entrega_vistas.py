"""Regresiones multimedia de perfiles, audio, cache y limites de fotogramas."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

import pytest

from clipstudio import entrega, media, vistas


@pytest.fixture
def fuente(tmp_path):
    try:
        ffmpeg = media.herramienta("ffmpeg")
    except media.ErrorMedia:
        pytest.skip("Requiere FFmpeg")
    ruta = tmp_path / "fuente.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-af", "volume=0.02",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-metadata", "comment=origen de prueba",
        "-shortest", str(ruta)], check=True, capture_output=True)
    return ruta


@pytest.mark.parametrize("perfil,alto", [("social", 1920), ("calidad", 1920), ("borrador", 1280)])
def test_mp4_perfil_audio_y_metadatos(fuente, tmp_path, perfil, alto):
    salida = tmp_path / (perfil + ".mp4")
    media.exportar_clip(fuente, salida, 0, 3, "ajustar", .5, None,
        media.Cancelacion(), lambda _: None, perfil=perfil, normalizar_audio=True,
        conservar=[(0,1),(2,3)], efecto_fondo="color", color_fondo="#000000")
    info = media.sondear(salida)
    assert info["alto"] == alto
    assert info["ancho"] == (720 if alto == 1280 else 1080)
    assert abs(info["duracion"] - 2) < .2
    r = subprocess.run([media.herramienta("ffprobe"), "-v", "error", "-show_format", "-of", "json", str(salida)], capture_output=True, check=True)
    assert "comment" not in json.loads(r.stdout)["format"].get("tags", {})
    vol = subprocess.run([media.herramienta("ffmpeg"), "-hide_banner", "-i", str(salida), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, check=True)
    import re
    nivel = float(re.search(rb"mean_volume: ([\d.-]+)", vol.stderr)[1])
    assert nivel > -25  # la fuente deliberadamente muy baja se eleva


def test_portada_onda_miniatura_y_cache_concurrente(fuente, tmp_path):
    with ThreadPoolExecutor(max_workers=6) as pool:
        miniaturas = list(pool.map(lambda _: vistas.imagen(fuente, tmp_path, "miniatura", 1), range(6)))
    assert all(x == miniaturas[0] for x in miniaturas)
    assert len(list((tmp_path / "vistas").glob("*.jpg"))) == 1
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(miniaturas[0])).width == 480
    portada = vistas.imagen(fuente, tmp_path, "portada", 1)
    assert Image.open(io.BytesIO(portada)).size == (720,1280)
    onda = vistas.imagen(fuente, tmp_path, "onda", inicio=0, fin=3)
    assert Image.open(io.BytesIO(onda)).size == (1000,100)
    assert not list((tmp_path / "vistas").glob("*.tmp.*"))


def test_portadas_rechazan_cortes_y_limites():
    c = {"inicio": 10, "fin": 30, "cortes": [{"inicio": 12, "fin": 20}]}
    assert vistas.momento_conservado(c) == 11
    assert vistas.momento_conservado(c, 21) == 21
    for tiempo in (0, 15, 30):
        with pytest.raises(ValueError):
            vistas.momento_conservado(c, tiempo)


def test_revision_comunica_ausencia_de_audio_y_baja_resolucion():
    r = entrega.revisar({"inicio":0,"fin":10,"encuadre":"stream","composicion":{},"subtitulos":[],"cortes":[]},
        {"ancho":320,"alto":180,"tiene_audio":False,"codec_video":"h264"}, "borrador")
    assert len(r["avisos"]) == 4
    assert r["salida"]["alto"] == 1280


def test_guardado_de_escritorio_admite_version_en_la_url():
    from clipstudio.desktop import es_pagina_motor
    base = "http://127.0.0.1:8765"
    assert es_pagina_motor(base + "/?v=0.3.0#/p/123", base)
    assert es_pagina_motor(base + "/#/", base)
    assert not es_pagina_motor("http://otro.example/?v=0.3.0", base)
    assert not es_pagina_motor(base + "/api/estado", base)
