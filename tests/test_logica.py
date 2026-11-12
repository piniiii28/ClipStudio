"""Pruebas de la logica pura: propuestas, subtitulos, filtros y validaciones."""

import re

import pytest

from clipstudio import importer, media, reframe, subtitles, suggest


def _segmento(inicio, frases):
    """Crea un segmento con una palabra cada 0.4 s; `frases` es una lista de textos."""
    palabras, t = [], inicio
    for frase in frases:
        for w in frase.split():
            palabras.append({"inicio": round(t, 2), "fin": round(t + 0.3, 2), "texto": w})
            t += 0.4
        t += 1.0  # pausa entre frases
    return {"inicio": inicio, "fin": t, "texto": " ".join(frases), "palabras": palabras}


FRASES = [
    "¿Sabias que perdemos 2 horas al dia cambiando de tarea?",
    "Ese cambio constante tiene un costo real para tu atencion.",
    "La solucion es agrupar tareas parecidas en bloques de tiempo.",
    "El primer consejo es planear la semana el domingo.",
    "Escribe las tres cosas mas importantes que quieres terminar.",
    "Cuando todo es prioridad nada lo es.",
    "El segundo consejo es proteger las mananas para el trabajo dificil.",
    "Deja las reuniones para despues del almuerzo.",
]


def test_partir_en_frases_respeta_puntuacion():
    frases = suggest.partir_en_frases([_segmento(0, FRASES)])
    assert len(frases) == len(FRASES)
    assert frases[0]["texto"].startswith("¿Sabias")
    assert all(f["cierra"] for f in frases)
    assert all(a["fin"] <= b["inicio"] for a, b in zip(frases, frases[1:]))


def test_propuestas_dentro_de_rango_y_sin_solapes():
    seg = _segmento(0, FRASES * 3)
    clips = suggest.proponer_clips([seg], seg["fin"], min_s=8, max_s=20)
    assert clips
    for c in clips:
        assert 8 <= c["fin"] - c["inicio"] <= 20
        assert c["motivos"]
    assert all(a["fin"] <= b["inicio"] for a, b in zip(clips, clips[1:]))


def test_propuestas_empiezan_y_terminan_en_limite_de_frase():
    seg = _segmento(0, FRASES * 2)
    frases = suggest.partir_en_frases([seg])
    inicios, fines = {f["inicio"] for f in frases}, {f["fin"] for f in frases}
    for c in suggest.proponer_clips([seg], seg["fin"], min_s=8, max_s=20):
        assert c["inicio"] in inicios and c["fin"] in fines


def test_sin_transcripcion_no_hay_propuestas():
    assert suggest.proponer_clips([], 100) == []


def test_video_corto_devuelve_un_fragmento():
    seg = _segmento(0, FRASES[:1])
    clips = suggest.proponer_clips([seg], seg["fin"], min_s=15, max_s=60)
    assert len(clips) == 1


def test_agrupar_respeta_limite_de_caracteres():
    palabras = _segmento(0, FRASES[:2])["palabras"]
    cues = subtitles.agrupar(palabras, max_caracteres=18)
    assert cues
    assert all(len(c["texto"]) <= 18 or " " not in c["texto"] for c in cues)
    assert all(a["fin"] <= b["inicio"] for a, b in zip(cues, cues[1:]))
    assert " ".join(c["texto"] for c in cues) == " ".join(p["texto"] for p in palabras)


def test_generar_solo_incluye_el_rango():
    seg = _segmento(0, FRASES)
    cues = subtitles.generar([seg], 5.0, 12.0)
    assert cues and all(5.0 <= c["inicio"] and c["fin"] <= 12.0 for c in cues)


def test_sincronizar_conserva_ediciones_y_completa_el_tramo_nuevo():
    seg = _segmento(0, FRASES)
    cues = subtitles.generar([seg], 5.0, 12.0)
    cues[0]["texto"] = "EDITADO"
    nuevos = subtitles.sincronizar(cues, [seg], 5.0, 18.0)
    assert nuevos[0]["texto"] == "EDITADO"
    assert nuevos[-1]["fin"] > 12.5
    assert all(a["fin"] <= b["inicio"] + 1e-6 for a, b in zip(nuevos, nuevos[1:]))


def test_ass_tiempos_relativos_y_texto_saneado():
    cues = [{"inicio": 10.5, "fin": 11.75, "texto": "hola {\\b1}mundo"}]
    ass = subtitles.a_ass(cues, 10.0, 20.0, {"mayusculas": True})
    linea = [l for l in ass.splitlines() if l.startswith("Dialogue:")][0]
    assert "0:00:00.50,0:00:01.75" in linea
    assert linea.endswith("HOLA (/B1)MUNDO")
    assert "PlayResY: 1920" in ass


def test_ass_color_en_orden_bgr():
    ass = subtitles.a_ass([{"inicio": 0, "fin": 1, "texto": "x"}], 0, 5, {"color": "#FF8000"})
    assert "&H000080FF" in ass


def test_validar_subtitulos_rechaza_tiempos_invertidos():
    with pytest.raises(ValueError):
        subtitles.validar([{"inicio": 5, "fin": 4, "texto": "x"}], 100)
    assert subtitles.validar([{"inicio": 1, "fin": 2, "texto": "  a\nb "}], 100) == [
        {"inicio": 1.0, "fin": 2.0, "texto": "a b"}
    ]


def test_estilo_se_acota():
    e = subtitles.normalizar_estilo({"tamano": 9999, "color": "rojo", "posicion": -4, "otro": 1})
    assert e["tamano"] == 140 and e["color"] == "#FFFFFF" and e["posicion"] == 5 and "otro" not in e


def test_filtro_rellenar_y_ajustar():
    rellenar = media.filtro_encuadre("rellenar", 0.25, True, "subs.ass")
    assert "crop=1080:1920:(iw-1080)*0.2500" in rellenar and rellenar.endswith("subtitles=subs.ass[v]")
    ajustar = media.filtro_encuadre("ajustar", 0.5, False)
    assert "boxblur" in ajustar and "overlay" in ajustar and "subtitles" not in ajustar


def test_recorte_desde_centro():
    assert reframe.recorte_desde_centro(0.5, 1920, 1080) == pytest.approx(0.5)
    assert reframe.recorte_desde_centro(0.0, 1920, 1080) == 0.0
    assert reframe.recorte_desde_centro(1.0, 1920, 1080) == 1.0
    assert reframe.recorte_desde_centro(0.2, 1080, 1920) == 0.5  # ya es vertical


@pytest.mark.parametrize(
    "url",
    [
        "ftp://x.com/a",
        "file:///c:/a.mp4",
        "http://localhost/a",
        "http://127.0.0.1:8765/api",
        "http://192.168.1.4/v",
        "sin-esquema",
    ],
)
def test_url_rechazada(url):
    with pytest.raises(ValueError):
        importer.validar_url(url)


def test_url_aceptada():
    assert importer.validar_url(" https://www.youtube.com/watch?v=abc ") == "https://www.youtube.com/watch?v=abc"


# ---------- division del video completo ----------

def test_dividir_cubre_todo_sin_huecos():
    seg = _segmento(0, FRASES * 6)
    total = seg["fin"] + 3
    partes = suggest.dividir([seg], total, objetivo_s=30)
    assert partes[0]["inicio"] == 0 and partes[-1]["fin"] == round(total, 3)
    assert all(a["fin"] == b["inicio"] for a, b in zip(partes, partes[1:]))
    # cada parte queda cerca del objetivo (la ultima puede absorber el resto)
    assert all(30 * 0.7 <= p["fin"] - p["inicio"] <= 30 * 1.3 for p in partes[:-1])
    assert partes[-1]["fin"] - partes[-1]["inicio"] <= 30 * 1.4 + 30 * 0.25
    assert partes[0]["titulo"].startswith(f"Parte 1 de {len(partes)}")


def test_dividir_corta_en_pausas_y_no_dentro_de_una_frase():
    seg = _segmento(0, FRASES * 6)
    frases = suggest.partir_en_frases([seg])
    for p in suggest.dividir([seg], seg["fin"], objetivo_s=30)[:-1]:
        assert not any(f["inicio"] < p["fin"] < f["fin"] for f in frases)


def test_dividir_sin_transcripcion_usa_cortes_exactos():
    partes = suggest.dividir([], 95, objetivo_s=30, ajustar=True)
    assert [p["inicio"] for p in partes] == [0, 30, 60]
    assert partes[-1]["fin"] == 95 and partes[1]["titulo"] == "Parte 2 de 3"


def test_dividir_video_mas_corto_que_el_objetivo():
    partes = suggest.dividir([], 20, objetivo_s=30)
    assert len(partes) == 1 and partes[0]["fin"] == 20


# ---------- picos de volumen ----------

def test_detectar_picos_encuentra_el_grito_y_no_el_ruido_de_fondo():
    from clipstudio import transcribe

    db = [-30.0 + (i % 3) * 0.5 for i in range(300)]
    db[120] = -8.0
    db[121] = -10.0   # mismo momento: debe fundirse con el anterior
    db[250] = -12.0
    picos = transcribe.detectar_picos(db)
    assert [p["t"] for p in picos] == [120.5, 250.5]
    assert picos[0]["exceso_db"] > 15


def test_detectar_picos_sin_variacion_no_devuelve_nada():
    from clipstudio import transcribe

    assert transcribe.detectar_picos([-25.0] * 200) == []
    assert transcribe.detectar_picos([-25.0] * 5) == []


def test_un_pico_de_volumen_sube_la_propuesta_y_se_explica():
    # Frases parecidas entre si (sin preguntas ni cifras): lo que decide es el pico.
    seg = _segmento(0, FRASES[1:3] * 12)
    sin = suggest.proponer_clips([seg], seg["fin"], min_s=8, max_s=20, maximo=1)[0]
    t_pico = sin["fin"] + 40 if sin["fin"] + 60 < seg["fin"] else sin["inicio"] - 40
    con = suggest.proponer_clips([seg], seg["fin"], min_s=8, max_s=20, maximo=1,
                                 picos=[{"t": t_pico, "exceso_db": 15}])[0]
    assert con["inicio"] <= t_pico <= con["fin"]
    assert any("pico de volumen" in m for m in con["motivos"])
    assert not any("pico de volumen" in m for m in sin["motivos"])


# ---------- estilo: resaltado, caja, gancho, fondo ----------

def test_resaltado_usa_tiempos_reales_si_el_texto_no_cambio():
    palabras = [
        {"inicio": 10.0, "fin": 10.2, "texto": "hola"},
        {"inicio": 10.9, "fin": 11.2, "texto": "mundo"},
    ]
    cue = {"inicio": 10.0, "fin": 11.5, "texto": "Hola mundo"}
    assert subtitles.tiempos_de_palabras(cue, palabras) == [(10.0, "Hola"), (10.9, "mundo")]
    editado = {"inicio": 10.0, "fin": 11.5, "texto": "Adios mundo cruel"}
    reparto = subtitles.tiempos_de_palabras(editado, palabras)
    assert [t for _, t in reparto] == ["Adios", "mundo", "cruel"]
    assert reparto[0][0] == 10.0 and reparto[0][0] < reparto[1][0] < reparto[2][0] < 11.5


def test_ass_con_resaltado_emite_un_evento_por_palabra():
    cues = [{"inicio": 10.0, "fin": 11.5, "texto": "hola mundo"}]
    ass = subtitles.a_ass(cues, 10.0, 20.0, {"resaltar": True, "color_resalte": "#FF0000", "mayusculas": False})
    lineas = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(lineas) == 2
    assert r"{\c&H0000FF&}hola{\c&HFFFFFF&} mundo" in lineas[0]
    assert r"hola {\c&H0000FF&}mundo{\c&HFFFFFF&}" in lineas[1]
    # los dos eventos cubren el subtitulo sin solaparse
    assert lineas[0].split(",")[2] == lineas[1].split(",")[1]


def test_ass_titulo_gancho_con_duracion_y_sin_subtitulos():
    ass = subtitles.a_ass([], 0, 30, {"titulo_gancho": "Mira {esto}", "gancho_segundos": 4})
    linea = [l for l in ass.splitlines() if l.startswith("Dialogue:")][0]
    assert ",Gancho," in linea and "0:00:00.00,0:00:04.00" in linea and linea.endswith("Mira (esto)")
    todo = subtitles.a_ass([], 0, 30, {"titulo_gancho": "Hola", "gancho_segundos": 0})
    assert "0:00:00.00,0:00:30.00" in todo
    assert subtitles.tiene_contenido([], {"titulo_gancho": "x"}) and not subtitles.tiene_contenido([], {})


def test_ass_caja_usa_borde_opaco():
    ass = subtitles.a_ass([{"inicio": 0, "fin": 1, "texto": "x"}], 0, 5, {"caja": True, "color_borde": "#112233"})
    estilo = [l for l in ass.splitlines() if l.startswith("Style: Clip")][0].split(",")
    assert estilo[15] == "3" and estilo[5] == "&H00332211"


def test_preferencia_no_arrastra_el_titulo_gancho():
    pref = subtitles.estilo_para_preferencia({"titulo_gancho": "solo este clip", "tamano": 90, "resaltar": True})
    assert pref["titulo_gancho"] == "" and pref["tamano"] == 90 and pref["resaltar"] is True


def test_estilo_nuevo_se_valida():
    e = subtitles.normalizar_estilo({"max_palabras": 99, "fondo": "raro", "color_fondo": "#abcdef",
                                     "titulo_gancho": "  a\n b  " + "x" * 200, "gancho_segundos": -3})
    assert e["max_palabras"] == 8 and e["fondo"] == "difuminado" and e["color_fondo"] == "#ABCDEF"
    assert e["titulo_gancho"].startswith("a b") and len(e["titulo_gancho"]) == 80 and e["gancho_segundos"] == 0


def test_agrupar_respeta_palabras_por_subtitulo():
    palabras = _segmento(0, FRASES[:2])["palabras"]
    assert all(len(c["texto"].split()) <= 2 for c in subtitles.agrupar(palabras, 40, 2))


def test_filtro_ajustar_con_color_solido():
    f = media.filtro_encuadre("ajustar", 0.5, True, "subs.ass", 0, "#102030")
    assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x102030" in f and "boxblur" not in f
    assert f.endswith("subtitles=subs.ass[v]")


# ---------- correcciones tras la tercera revision ----------

def test_dividir_nunca_supera_el_maximo_por_clip():
    partes = suggest.dividir([], 1400, objetivo_s=600)
    assert all(p["fin"] - p["inicio"] <= 600 for p in partes)
    assert partes[0]["inicio"] == 0 and partes[-1]["fin"] == 1400
    assert all(a["fin"] == b["inicio"] for a, b in zip(partes, partes[1:]))


def test_dividir_descarta_un_resto_menor_de_un_segundo():
    partes = suggest.dividir([], 1200.4, objetivo_s=600)
    assert [(p["inicio"], p["fin"]) for p in partes] == [(0.0, 600.0), (600.0, 1200.0)]


def test_validar_recorta_subtitulos_solapados():
    cues = subtitles.validar([{"inicio": 0, "fin": 2, "texto": "uno"}, {"inicio": 1, "fin": 3, "texto": "dos"}], 10)
    assert cues == [{"inicio": 0.0, "fin": 1.0, "texto": "uno"}, {"inicio": 1.0, "fin": 3.0, "texto": "dos"}]


def test_volumen_mantiene_tiempos_absolutos_entre_bloques():
    import numpy as np

    from clipstudio import transcribe

    f = transcribe.FRECUENCIA
    audio = np.full(10 * f, 0.01, dtype=np.float32)
    audio[7 * f: 8 * f] = 0.5            # el segundo 7 del "video" es el fuerte
    corte = int(3.4 * f)                 # los bloques no cortan en un segundo exacto
    db: list[float] = []
    transcribe._anotar_volumen(db, audio[:corte], 0)
    transcribe._anotar_volumen(db, audio[corte:], corte)
    assert len(db) == 10 and db.index(max(db)) == 7


# ---------- encuadre dividido (video arriba y juego abajo) ----------

def test_filtro_dividido_alturas_pares_y_suma_1920():
    f = media.filtro_encuadre("dividido", 0.5, True, "subs.ass", 0, None, 45)
    assert "vstack=inputs=2" in f and "[1:v:0]" in f
    alturas = [int(a) for a in re.findall(r"scale=1080:(\d+)", f)]  # [arriba, abajo]
    assert sum(alturas) == 1920 and all(a % 2 == 0 for a in alturas)
    assert alturas == [1056, 864]
    assert f.endswith("subtitles=subs.ass[v]")


def test_filtro_dividido_sin_subtitulos_termina_en_null():
    f = media.filtro_encuadre("dividido", 0.5, False, "", 0, None, 30)
    assert f.endswith("[v0]null[v]") and "vstack=inputs=2" in f


def test_exportar_dividido_sin_fondo_da_error_claro(tmp_path):
    cancel = media.Cancelacion()
    with pytest.raises(media.ErrorMedia, match="fondo"):
        media.exportar_clip(tmp_path / "a.mp4", tmp_path / "b.mp4", 0, 10, "dividido", 0.5, None, cancel, lambda _: None)


def test_normalizar_estilo_limita_juego_proporcion():
    assert subtitles.normalizar_estilo({})["juego_proporcion"] == 45
    assert subtitles.normalizar_estilo({"juego_proporcion": 99})["juego_proporcion"] == 60
    assert subtitles.normalizar_estilo({"juego_proporcion": 1})["juego_proporcion"] == 25


def test_normalizar_estilo_rechaza_rutas_en_fondo_juego():
    for malo in ("../x.mp4", "a/b.mp4", "a\\b.mp4", "..", "x" * 151 + ".mp4", 123):
        assert subtitles.normalizar_estilo({"fondo_juego": malo})["fondo_juego"] == ""
    assert subtitles.normalizar_estilo({"fondo_juego": "gameplay.mp4"})["fondo_juego"] == "gameplay.mp4"
