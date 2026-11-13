"""Calidad del bufer en vivo y clips en alta calidad: logica pura (sin red ni FFmpeg)."""

import numpy as np
import pytest

from clipstudio import config, db, vivo, vivo_calidad as vc
from clipstudio.vivo import Seg


# ---------- formato y estimacion ----------

@pytest.mark.parametrize("altura", [480, 720, 1080])
def test_formato_por_calidad(altura):
    f = vc.formato_ytdlp(altura)
    assert f.startswith(f"b[height<={altura}]/bv*[height<={altura}]+ba/")   # combinado y, si no, video + audio aparte
    assert f.count(f"height<={altura}") == 2


def test_formato_de_respaldo_segun_calidad():
    assert vc.formato_ytdlp(1080).endswith("/b/best")       # «original»: lo mejor que haya
    assert vc.formato_ytdlp(480).endswith("/w")             # si no baja de 720, lo mas ligero


def test_estimacion_orientativa_y_medida():
    sin_datos = vc.estimar_calidades(None)
    assert [e["altura"] for e in sin_datos] == [480, 720, 1080] and not any(e["medido"] for e in sin_datos)
    assert sin_datos[0]["gb_hora"] < sin_datos[1]["gb_hora"] < sin_datos[2]["gb_hora"]
    formatos = [
        {"height": 480, "tbr": 1000, "vcodec": "avc1", "acodec": "none"},
        {"height": 720, "tbr": 2400, "vcodec": "avc1", "acodec": "none"},
        {"height": 1080, "tbr": 4400, "vcodec": "avc1", "acodec": "none"},
        {"height": None, "tbr": 128, "vcodec": "none", "acodec": "mp4a"},
    ]
    medido = vc.estimar_calidades(formatos)
    assert all(e["medido"] for e in medido)
    assert medido[1]["kbps"] == 2400 + 128                  # video de 720p + audio
    assert medido[2]["gb_hora"] == vc.gb_por_hora(4400 + 128)


def test_estimacion_con_flujo_combinado_de_twitch():
    formatos = [{"height": 360, "tbr": 630, "vcodec": "avc1", "acodec": "mp4a"},
                {"height": 720, "tbr": 3423, "vcodec": "avc1", "acodec": "mp4a"},
                {"height": 1080, "tbr": 5789, "vcodec": "avc1", "acodec": "mp4a"}]
    est = {e["altura"]: e for e in vc.estimar_calidades(formatos)}
    assert est[480]["kbps"] == 630 and est[720]["kbps"] == 3423 and est[1080]["kbps"] == 5789
    assert est[1080]["gb_hora"] == pytest.approx(5789 * 450000 / 1024**3, abs=0.01)


# ---------- preferencias ----------

def test_preferencias_validas_y_por_defecto(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "d.sqlite")
    monkeypatch.setattr(config, "VIVO_BUFER_MIN", 20.0)
    db.iniciar()
    assert vc.leer_preferencias() == {"calidad": 720, "buffer_min": 20.0, "clip_modo": "preguntar", "clip_altura": None}
    vc.guardar_preferencias({"calidad": 480, "buffer_min": 30, "clip_modo": "alta", "clip_altura": 1080})
    assert vc.leer_preferencias() == {"calidad": 480, "buffer_min": 30.0, "clip_modo": "alta", "clip_altura": 1080}
    db.guardar_preferencia("vivo", {"calidad": 999, "buffer_min": 7, "clip_modo": "x", "clip_altura": "a"})
    assert vc.leer_preferencias()["calidad"] == 720 and vc.leer_preferencias()["buffer_min"] == 20.0


def test_el_buffer_por_defecto_respeta_la_variable_de_entorno(monkeypatch):
    monkeypatch.setattr(config, "VIVO_BUFER_MIN", 45.0)
    assert vc.buffer_min_defecto() == 45.0 and 45.0 in vc.opciones_buffer_min()
    assert vc.normalizar_preferencias(None)["buffer_min"] == 45.0
    monkeypatch.setattr(config, "VIVO_BUFER_MIN", 20.0)
    assert vc.opciones_buffer_min() == [10.0, 20.0, 30.0, 60.0]


def test_validacion_de_calidad_y_duracion(tmp_path, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "d.sqlite")
    db.iniciar()
    monkeypatch.delenv("CLIPSTUDIO_VIVO_PRUEBAS", raising=False)
    assert vivo._validar_calidad_y_duracion(None, None) == (720, config.VIVO_BUFER_MIN)
    assert vivo._validar_calidad_y_duracion(1080, 10) == (1080, 10.0)
    with pytest.raises(HTTPException):
        vivo._validar_calidad_y_duracion(360, 20)
    with pytest.raises(HTTPException):
        vivo._validar_calidad_y_duracion(720, 5)          # fuera de 10/20/30/60
    monkeypatch.setenv("CLIPSTUDIO_VIVO_PRUEBAS", "1")
    assert vivo._validar_calidad_y_duracion(720, 0.5) == (720, 0.5)   # el modo de pruebas admite buferes cortos


# ---------- HLS, reloj y alineacion ----------

HLS_YOUTUBE = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:5
#EXT-X-PROGRAM-DATE-TIME:2026-11-13T11:53:26.407+00:00
#EXTINF:5.000,
a.ts
#EXTINF:5.000,
b.ts
#EXT-X-PROGRAM-DATE-TIME:2026-11-13T11:53:36.407+00:00
#EXTINF:4.500,
c.ts
"""


def test_parsear_hls_con_hora_de_reloj():
    r = vc.parsear_hls(HLS_YOUTUBE)
    assert r["segmentos"] == 3 and r["duracion"] == 14.5
    assert r["inicio"] == pytest.approx(1794570806.407, abs=0.001)    # 2026-11-13T11:53:26.407Z


def test_parsear_hls_sin_hora_ni_segmentos():
    assert vc.parsear_hls("#EXTM3U\n#EXTINF:6.0,\nx.ts\n")["inicio"] is None
    assert vc.parsear_hls("")["duracion"] == 0
    assert vc._epoch_iso("2026-11-13T07:48:03.139Z") == pytest.approx(1794556083.139, abs=0.001)
    assert vc._epoch_iso("2026-11-13T09:48:03+02:00") == vc._epoch_iso("2026-11-13T07:48:03Z")
    assert vc._epoch_iso("no es una fecha") is None


def segs(reloj0=1000.0):
    # 4 segmentos de 6 s; cada uno se "vio cerrado" justo al terminar.
    return [Seg(f"s{i}.ts", 6 * i, 6 * i + 6, 1, reloj0 + 6 * i + 6) for i in range(4)]


def test_reloj_de_un_instante_del_bufer():
    s = segs()
    assert vc.reloj_de(s, 6.0) == pytest.approx(1006.0)
    assert vc.reloj_de(s, 9.0) == pytest.approx(1009.0)
    assert vc.reloj_de(s, 30.0) == pytest.approx(1030.0)          # mas alla del final: se extrapola
    assert vc.reloj_de([Seg("a", 0, 6, 1)], 3.0) is None          # sin reloj registrado


def sondeo(inicio, duracion, alturas=(1080, 720, 480), ok=True, plataforma="twitch"):
    return {"ok": ok, "plataforma": plataforma, "inicio": inicio, "duracion": duracion, "alturas": list(alturas),
            "motivo": None if ok else "No hay VOD"}


def test_calcular_tramo_alineado_con_el_vod():
    # VOD empezo a las 10:00:00 (epoch 5000) y lleva 600 s. El tramo se grabo entre 5300 y 5330 (reloj).
    t = vc.calcular_tramo(sondeo(5000, 600), 5300.0, 5330.0, "twitch", pad=10, ahora=5600)
    lat = vc.latencia_de("twitch")
    assert t["ok"] and t["desde"] == pytest.approx(300 - lat - 10) and t["hasta"] == pytest.approx(330 - lat + 10)


def test_calcular_tramo_aun_no_esta_en_el_vod():
    t = vc.calcular_tramo(sondeo(5000, 300), 5300.0, 5330.0, "twitch", ahora=5330)
    assert not t["ok"] and "aún no está disponible" in t["motivo"] and "unos minutos" in t["motivo"]


def test_calcular_tramo_anterior_a_lo_que_guarda_la_plataforma():
    t = vc.calcular_tramo(sondeo(5000, 3600, plataforma="youtube"), 4990.0, 5030.0, "youtube", ahora=8600)
    assert not t["ok"] and "ya no conserva" in t["motivo"]


def test_calcular_tramo_recorta_el_margen_a_la_ventana():
    t = vc.calcular_tramo(sondeo(5000, 400), 5000 + 30 + 8, 5000 + 60 + 8, "twitch", pad=50, ahora=5400)
    assert t["ok"] and t["desde"] == 0.0 and t["hasta"] <= 400


def test_decidir_opciones_siempre_ofrece_el_bufer():
    o = vc.decidir_opciones(720, None)
    assert o["buffer"]["disponible"] and o["buffer"]["alto"] == 720 and not o["alta"]["disponible"]


def test_decidir_opciones_alta_con_alturas_mejores_que_el_bufer():
    ok = sondeo(5000, 600)
    tramo = {"ok": True}
    o = vc.decidir_opciones(720, ok, tramo)
    assert o["alta"] == {"disponible": True, "motivo": None, "alturas": [1080]}
    assert vc.decidir_opciones(480, ok, tramo)["alta"]["alturas"] == [1080, 720]
    # El bufer ya es lo mejor que hay.
    a = vc.decidir_opciones(1080, ok, tramo)["alta"]
    assert not a["disponible"] and "mayor calidad" in a["motivo"]


def test_decidir_opciones_explica_por_que_no():
    sin_vod = sondeo(None, 0, ok=False)
    sin_vod["motivo"] = "Este canal no guarda VOD del directo."
    a = vc.decidir_opciones(720, sin_vod)["alta"]
    assert not a["disponible"] and a["motivo"] == "Este canal no guarda VOD del directo."
    pronto = {"ok": False, "motivo": "El tramo aún no está disponible en la plataforma. Prueba en unos minutos."}
    a = vc.decidir_opciones(720, sondeo(5000, 600), pronto)["alta"]
    assert not a["disponible"] and "unos minutos" in a["motivo"] and a["alturas"] == [1080]


def test_alturas_inutiles_no_se_ofrecen():
    a = vc.decidir_opciones(480, sondeo(0, 100, alturas=(1440, 1080, 160, 360)), {"ok": True})["alta"]
    assert a["alturas"] == [1080]       # >1080 se descarta; <360 y <= bufer tampoco


def test_plataformas():
    assert vc.plataforma_de("https://www.youtube.com/@LofiGirl/live") == "youtube"
    assert vc.plataforma_de("https://youtu.be/abc") == "youtube"
    assert vc.plataforma_de("https://www.twitch.tv/gaules") == "twitch"
    assert vc.plataforma_de("https://kick.com/xqc") == "kick"
    assert vc.plataforma_de("https://example.com/v") == "otra"
    assert vc._canal("https://www.twitch.tv/gaules/videos") == "gaules"


def test_sondeo_de_otra_plataforma_explica_que_no(monkeypatch):
    monkeypatch.setattr(vc, "_extraer", lambda *a, **k: pytest.fail("no debe consultar nada"))
    r = vc.sondear_plataforma("https://example.com/directo")
    assert not r["ok"] and "no permite" in r["motivo"]


def test_sondeo_twitch_sin_vod(monkeypatch):
    def extraer(url, **extra):
        if "/videos" in url:
            return {"entries": []}
        return {"is_live": True, "live_status": "is_live", "timestamp": 1000}
    monkeypatch.setattr(vc, "_extraer", extraer)
    r = vc.sondear_plataforma("https://www.twitch.tv/canal")
    assert not r["ok"] and "no guarda VOD" in r["motivo"]


def test_sondeo_twitch_con_vod_en_curso(monkeypatch):
    def extraer(url, **extra):
        if "/videos?" in url:
            return {"entries": [{"url": "https://www.twitch.tv/videos/1"}]}
        if "/videos/1" in url:
            return {"is_live": True, "live_status": "is_live", "timestamp": 1005, "webpage_url": "https://www.twitch.tv/videos/1",
                    "formats": [{"protocol": "m3u8_native", "url": "http://x/720.m3u8", "height": 720},
                                {"protocol": "m3u8_native", "url": "http://x/1080.m3u8", "height": 1080},
                                {"protocol": "m3u8_native", "url": "http://x/audio.m3u8", "height": None}]}
        return {"is_live": True, "live_status": "is_live", "timestamp": 1000}
    monkeypatch.setattr(vc, "_extraer", extraer)
    monkeypatch.setattr(vc, "_leer_lista_hls", lambda f, c: {"inicio": 1000.0, "duracion": 500.0, "segmentos": 50})
    r = vc.sondear_plataforma("https://www.twitch.tv/canal")
    assert r["ok"] and r["alturas"] == [1080, 720] and r["url"].endswith("/videos/1") and r["duracion"] == 500.0


def test_sondeo_twitch_ignora_un_vod_de_otra_emision(monkeypatch):
    def extraer(url, **extra):
        if "/videos?" in url:
            return {"entries": [{"url": "https://www.twitch.tv/videos/9"}]}
        if "/videos/9" in url:
            return {"is_live": True, "live_status": "is_live", "timestamp": 99999, "formats": []}
        return {"is_live": True, "live_status": "is_live", "timestamp": 1000}
    monkeypatch.setattr(vc, "_extraer", extraer)
    assert not vc.sondear_plataforma("https://www.twitch.tv/canal")["ok"]


def test_sondeo_youtube_sin_dvr(monkeypatch):
    info = {"live_status": "is_live", "is_live": True, "webpage_url": "https://www.youtube.com/watch?v=x",
            "formats": [{"protocol": "m3u8_native", "url": "http://x/a.m3u8", "height": 1080}]}
    monkeypatch.setattr(vc, "_extraer", lambda *a, **k: info)
    monkeypatch.setattr(vc, "_leer_lista_hls", lambda f, c: {"inicio": 1000.0, "duracion": 12.0, "segmentos": 2})
    r = vc.sondear_plataforma("https://www.youtube.com/watch?v=x")
    assert not r["ok"] and "no permite retroceder" in r["motivo"]


def test_sondeo_youtube_con_dvr(monkeypatch):
    info = {"live_status": "is_live", "is_live": True, "webpage_url": "https://www.youtube.com/watch?v=x",
            "formats": [{"protocol": "m3u8_native", "url": "http://x/a.m3u8", "height": h} for h in (144, 720, 1080)]}
    monkeypatch.setattr(vc, "_extraer", lambda *a, **k: info)
    monkeypatch.setattr(vc, "_leer_lista_hls", lambda f, c: {"inicio": 1000.0, "duracion": 3600.0, "segmentos": 720})
    r = vc.sondear_plataforma("https://www.youtube.com/watch?v=x")
    assert r["ok"] and r["alturas"] == [1080, 720, 144] and r["duracion"] == 3600.0


def test_sondeo_youtube_que_no_esta_en_directo(monkeypatch):
    monkeypatch.setattr(vc, "_extraer", lambda *a, **k: {"live_status": "was_live"})
    assert "no está en curso" in vc.sondear_plataforma("https://www.youtube.com/watch?v=x")["motivo"]


def test_sondeo_nunca_lanza(monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("HTTP Error 403: Forbidden")
    monkeypatch.setattr(vc, "_extraer", falla)
    r = vc.sondear_plataforma("https://kick.com/canal")
    assert not r["ok"] and r["motivo"].startswith("No se pudo consultar")


# ---------- alineacion por audio ----------

def senal(n, semilla=1):
    return np.random.default_rng(semilla).standard_normal(n).astype(np.float32)


def test_alineacion_encuentra_el_desfase_exacto():
    hz = vc.AUDIO_HZ
    largo = senal(hz * 40)                      # 40 s descargados
    ref = largo[int(hz * 13.25): int(hz * 13.25) + hz * 15]     # el clip del bufer empieza en 13,25 s
    pos, score, segundo = vc.desplazamiento_audio(ref, largo)
    assert pos == pytest.approx(13.25, abs=1 / hz) and score > 0.99 and segundo < 0.2
    assert vc.alineado_fiable(score, segundo)


def test_alineacion_tolera_ruido_y_codec_distinto():
    hz = vc.AUDIO_HZ
    largo = senal(hz * 40, 2)
    ref = largo[hz * 7: hz * 7 + hz * 12] * 0.6 + 0.15 * senal(hz * 12, 3)
    pos, score, segundo = vc.desplazamiento_audio(ref, largo)
    assert pos == pytest.approx(7.0, abs=2 / hz) and vc.alineado_fiable(score, segundo)


def test_alineacion_rechaza_audio_que_no_coincide_o_silencio():
    hz = vc.AUDIO_HZ
    largo = senal(hz * 40, 4)
    otro = senal(hz * 12, 5)                    # otro contenido (p. ej. un anuncio)
    pos, score, segundo = vc.desplazamiento_audio(otro, largo)
    assert not vc.alineado_fiable(score, segundo)
    assert vc.desplazamiento_audio(np.zeros(hz * 12), largo)[1] == 0.0
    assert vc.desplazamiento_audio(largo[: hz * 5], largo[: hz * 5])[1] > 0.99   # misma longitud: unica posicion
    assert vc.desplazamiento_audio(largo, largo[: hz * 3]) == (0.0, 0.0, 0.0)    # la referencia no cabe


def test_alineacion_de_musica_repetitiva_no_se_da_por_fiable():
    hz = vc.AUDIO_HZ
    t = np.arange(hz * 40) / hz
    tono = np.sin(2 * np.pi * 220 * t).astype(np.float32)     # tono puro: cualquier desfase multiplo del periodo encaja
    pos, score, segundo = vc.desplazamiento_audio(tono[hz * 5: hz * 15], tono)
    assert not vc.alineado_fiable(score, segundo)


# ---------- lista HLS recortada por hora de reloj ----------

def test_recortar_lista_hls_elige_segmentos_por_hora_y_hace_absolutos_los_uri():
    texto = ("#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXT-X-MEDIA-SEQUENCE:9\n"
             "#EXT-X-PROGRAM-DATE-TIME:2026-11-13T12:00:00.000Z\n"
             "#EXTINF:5.0,\ns1.ts\n#EXTINF:5.0,\ns2.ts\n#EXTINF:5.0,\ns3.ts\n#EXTINF:5.0,\ns4.ts\n")
    base = vc._epoch_iso("2026-11-13T12:00:00Z")
    r = vc.recortar_lista_hls(texto, "https://cdn.example/a/lista.m3u8", base + 6, base + 12)
    assert r["segmentos"] == 2 and r["inicio"] == base + 5 and r["fin"] == base + 15
    assert "https://cdn.example/a/s2.ts" in r["texto"] and "s1.ts" not in r["texto"] and r["texto"].rstrip().endswith("#EXT-X-ENDLIST")
    assert vc.recortar_lista_hls(texto, "https://x/l.m3u8", base + 100, base + 110) is None


def test_recortar_lista_hls_sin_hora_usa_el_inicio_dado_y_conserva_el_map():
    texto = '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:10.0,\na.m4s\n#EXTINF:10.0,\nb.m4s\n'
    r = vc.recortar_lista_hls(texto, "https://v/x/p.m3u8", 1010, 1015, inicio=1000)
    assert r["segmentos"] == 1 and r["inicio"] == 1010
    assert 'URI="https://v/x/init.mp4"' in r["texto"] and "b.m4s" in r["texto"]
    assert vc.recortar_lista_hls(texto, "https://v/x/p.m3u8", 1010, 1015) is None   # sin hora no hay como ubicarlo
