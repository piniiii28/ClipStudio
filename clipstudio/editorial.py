"""Ayudas editoriales locales basadas en el texto conservado de los clips."""
from __future__ import annotations

from collections import Counter
import re
import unicodedata

from . import hashtags, suggest

VACIAS = set("a al algo ante como con cuando de del el ella en es esta este esto fue ha hay la las lo los me mi muy ni no nos o para pero por que se si sin sobre su sus te tiene tu un una unos unas y ya the a an and are as at be but by for from i in is it of on or that this to was we with you".split())


def palabras(texto: str) -> set[str]:
    normal = unicodedata.normalize("NFKD", texto.casefold())
    normal = "".join(c for c in normal if not unicodedata.combining(c))
    return {p for p in re.findall(r"\w+", normal) if len(p) > 2 and p not in VACIAS}


def titulos(clip: dict, segmentos: list[dict]) -> list[dict]:
    texto = " ".join(hashtags.texto_del_clip(clip, segmentos).split())
    if not texto:
        return []
    frases = re.split(r"(?<=[.!?…])\s+", texto)
    opciones = []
    for frase in frases:
        partes = frase.split()
        for i in range(0, len(partes), 14):
            candidato = suggest._titulo(" ".join(partes[i:i + 14]), 90)
            if len(candidato) >= 8:
                opciones.append(candidato)
    frecuencias = Counter(p for frase in frases for p in palabras(frase))
    opciones = list(dict.fromkeys(opciones))
    opciones.sort(key=lambda t: ("?" in t, sum(frecuencias[p] for p in palabras(t)), -abs(len(t) - 55)), reverse=True)
    return [{"titulo": t, "motivo": "Pregunta de los subtítulos" if "?" in t else "Frase del texto conservado",
             "evidencia": t} for t in opciones[:5]]


def revisar_subtitulos(clip: dict) -> list[dict]:
    avisos = []
    anterior = None
    for indice, cue in enumerate(clip.get("subtitulos") or []):
        duracion = cue["fin"] - cue["inicio"]
        texto = cue["texto"].strip()
        motivos = []
        if duracion < .25:
            motivos.append(("duracion", "Duración inferior a 0,25 s"))
        if len(texto.replace("\n", "")) / max(.01, duracion) > 22:
            motivos.append(("lectura", "Velocidad superior a 22 caracteres por segundo"))
        tamano = (clip.get("estilo") or {}).get("tamano", 64)
        if len(max(texto.splitlines() or [""], key=len)) * tamano * .55 > 972:
            motivos.append(("ancho", "Posible desbordamiento de línea con el tamaño elegido"))
        if anterior is not None and cue["inicio"] < anterior["fin"] - .001:
            motivos.append(("solapamiento", "Se solapa con el subtítulo anterior"))
        if any(c["inicio"] < cue["fin"] and c["fin"] > cue["inicio"] for c in clip.get("cortes") or []):
            motivos.append(("corte", "El subtítulo atraviesa un tramo eliminado"))
        avisos.extend({"indice": indice, "inicio": cue["inicio"], "fin": cue["fin"],
                       "codigo": codigo, "motivo": motivo} for codigo, motivo in motivos)
        anterior = cue
    return avisos


def buscar_tema(segmentos: list[dict], duracion: float, tema: str, minimo: float, maximo: float) -> list[dict]:
    consulta = palabras(tema)
    if not consulta or duracion < minimo:
        return []
    frases = suggest.partir_en_frases(segmentos)
    if not frases:
        frases = [s for s in segmentos if s.get("texto", "").strip()]
    resultados = []
    for frase in frases:
        coincidencias = consulta & palabras(frase["texto"])
        if not coincidencias:
            continue
        inicio = max(0, frase["inicio"] - 2)
        fin = min(duracion, max(frase["fin"] + 2, inicio + minimo), inicio + maximo)
        inicio = max(0, min(inicio, fin - minimo))
        if fin - inicio < 1:
            continue
        resultados.append({"inicio": round(inicio, 3), "fin": round(fin, 3),
                            "titulo": suggest._titulo(frase["texto"]), "evidencia": frase["texto"],
                            "coincidencias": sorted(coincidencias), "motivos": ["Coincidencia con el tema indicado"]})
    resultados.sort(key=lambda r: (-len(r["coincidencias"]), r["inicio"]))
    elegidos = []
    for resultado in resultados:
        if not any(min(resultado["fin"], r["fin"]) > max(resultado["inicio"], r["inicio"]) for r in elegidos):
            elegidos.append(resultado)
        if len(elegidos) == 12:
            break
    return elegidos
