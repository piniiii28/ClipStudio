"""Sugerencias tematicas locales: sin promesas de alcance ni datos de tendencias."""
from __future__ import annotations

import re
import unicodedata

from . import cortes

AVISO = "Los hashtags ayudan a describir el clip; no garantizan visitas ni aparecer en Para ti. No se consultan tendencias en tiempo real."


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in texto if not unicodedata.combining(c))))


# Cada juego/tema requiere una mencion explicita; un creador no implica un juego.
JUEGOS = (
    ("Valorant", ("valorant",)),
    ("CounterStrike2", ("counter strike", "counterstrike", "cs2", "csgo")),
    ("Fortnite", ("fortnite",)),
    ("Minecraft", ("minecraft",)),
    ("LeagueOfLegends", ("league of legends", "leagueoflegends")),
    ("GTA", ("gta", "grand theft auto")),
    ("CallOfDuty", ("call of duty", "warzone")),
    ("ApexLegends", ("apex legends",)),
    ("RocketLeague", ("rocket league",)),
    ("Roblox", ("roblox",)),
    ("Overwatch", ("overwatch",)),
    ("MarvelRivals", ("marvel rivals",)),
    ("Dota2", ("dota 2", "dota2")),
    ("FreeFire", ("free fire",)),
    ("EAFC", ("ea fc", "eafc", "fifa")),
)
TEMAS = (
    ("Productividad", ("productividad", "productivity", "time blocking", "gestion del tiempo")),
    ("Programacion", ("programacion", "programming", "javascript", "python", "desarrollo web")),
    ("Tecnologia", ("tecnologia", "technology", "inteligencia artificial")),
    ("Recetas", ("receta", "recetas", "recipe", "recipes", "cocinar")),
    ("Fitness", ("fitness", "entrenamiento", "workout", "gimnasio")),
    ("Futbol", ("futbol", "soccer", "football")),
    ("Baloncesto", ("baloncesto", "basketball", "nba")),
    ("Ajedrez", ("ajedrez", "chess")),
    ("Musica", ("musica", "music", "guitarra", "piano")),
    ("Crochet", ("crochet", "ganchillo")),
    ("Bordado", ("bordado", "embroidery")),
)


def texto_del_clip(clip: dict, segmentos: list[dict]) -> str:
    """Usa subtitulos editados; sin ellos, el audio transcrito dentro del corte final."""
    inicio, fin = clip["inicio"], clip["fin"]
    tramos = cortes.tramos_conservados(inicio, fin, clip.get("cortes") or [])

    def visible(cue):
        return any(min(cue["fin"], b) - max(cue["inicio"], a) >= .05 for a, b in tramos)

    cues = clip.get("subtitulos") or []
    if cues:
        return " ".join(c["texto"] for c in cues if visible(c))[:30000]
    textos = []
    for segmento in segmentos:
        palabras = segmento.get("palabras") or []
        if palabras:
            textos.extend(p["texto"] for p in palabras if any(a <= (p["inicio"] + p["fin"]) / 2 < b for a, b in tramos))
        # Sin tiempos por palabra solo se toma un segmento completamente conservado.
        elif any(a <= segmento["inicio"] and segmento["fin"] <= b for a, b in tramos):
            textos.append(segmento.get("texto", ""))
    return " ".join(textos)[:30000]


def sugerir(clip: dict, proyecto: dict, segmentos: list[dict], contexto: str = "") -> dict:
    fuentes = [(contexto, 8, "el tema que indicaste"),
               (clip["titulo"], 4, "el título del clip"),
               (texto_del_clip(clip, segmentos), 3, "el contenido conservado del clip"),
               ((clip.get("estilo") or {}).get("titulo_gancho", ""), 2, "el título en pantalla")]
    fuentes = [(_normalizar(texto), peso, motivo) for texto, peso, motivo in fuentes if texto.strip()]

    def coincidencia(variantes):
        for texto, peso, motivo in fuentes:
            for variante in variantes:
                if re.search(r"(?<!\w)" + re.escape(variante) + r"(?!\w)", texto):
                    return peso, motivo
        return None

    opciones = []

    def agregar(etiqueta, puntuacion, motivo):
        opciones.append({"etiqueta": "#" + etiqueta, "motivo": motivo, "puntuacion": puntuacion})

    juegos = []
    for etiqueta, variantes in JUEGOS:
        if match := coincidencia(variantes):
            juegos.append((etiqueta, *match))
    juegos.sort(key=lambda j: -j[1])
    # Un solo juego principal: evita llenar el bloque con comparaciones secundarias.
    if juegos:
        juego, peso, motivo = juegos[0]
        agregar(juego, 100 + peso, "Juego mencionado en " + motivo + ".")
        agregar(juego + "Clips", 70, "Relaciona el fragmento con clips de ese juego.")
    gaming = bool(juegos or coincidencia(("gaming", "gameplay", "videojuegos", "videojuego")))
    for etiqueta, variantes in TEMAS:
        if match := coincidencia(variantes):
            peso, motivo = match
            agregar(etiqueta, 80 + peso, "Tema mencionado en " + motivo + ".")
    if gaming:
        for etiqueta, variantes in (("Clutch", ("clutch",)), ("Ace", ("ace",)),
                                    ("Headshot", ("headshot", "headshots")),
                                    ("TutorialGaming", ("tutorial", "guia", "how to"))):
            if match := coincidencia(variantes):
                agregar(etiqueta, 90 + match[0], "Tipo de jugada o contenido mencionado en " + match[1] + ".")
        if juegos and juegos[0][0] == "Valorant":
            for agente in ("Jett", "Reyna", "Raze", "Sova", "Sage", "Omen", "Yoru", "Cypher", "Killjoy", "Clove"):
                if coincidencia((agente.lower(),)):
                    agregar(agente, 85, "Agente mencionado en el contexto de Valorant.")
        agregar("Gaming", 40, "Categoría general del contenido de videojuegos.")

    # Un tema explicito fuera del catalogo tambien puede ser util, sin extraer palabras
    # de relleno de la transcripcion ni inventar entidades o tendencias.
    for tema in re.split(r"[,;#]", contexto):
        palabras = _normalizar(tema).split()
        if 1 <= len(palabras) <= 3 and all(len(p) > 1 and not p.isdigit() for p in palabras):
            etiqueta = "".join(p.capitalize() for p in palabras)
            if len(etiqueta) <= 32 and _normalizar(etiqueta) not in {"fyp", "viral", "foryou", "parati"}:
                # No duplicar un tema ya reconocido por una variante del catalogo.
                if not any(coincidencia(variantes) and _normalizar(tema) in variantes
                           for _, variantes in JUEGOS + TEMAS):
                    agregar(etiqueta, 75, "Tema que indicaste manualmente; comprueba que describe el clip.")
    if proyecto.get("es_clip_vivo"):
        agregar("ClipsDeStream", 30, "El proyecto procede de un directo.")

    resultado, vistas = [], set()
    for opcion in sorted(opciones, key=lambda o: -o["puntuacion"]):
        clave = _normalizar(opcion["etiqueta"])
        if clave not in vistas:
            vistas.add(clave)
            resultado.append({k: v for k, v in opcion.items() if k != "puntuacion"})
        if len(resultado) == 5:
            break
    return {"hashtags": resultado, "texto": " ".join(h["etiqueta"] for h in resultado),
            "aviso": AVISO, "necesita_contexto": not juegos and not any(o["puntuacion"] >= 75 for o in opciones)}
