"""Subtitulos: agrupacion de palabras en lineas cortas y generacion del archivo ASS.

Los tiempos de los subtitulos de un clip se guardan en el tiempo del video fuente; al
exportar se trasladan al tiempo del clip.

El "estilo" de un clip es un diccionario que tambien guarda el titulo gancho y el fondo
del encuadre, para que todo lo visual viaje junto y se pueda guardar como preferencia.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from . import config

FIN_FRASE = (".", "?", "!", "…")
MARGEN_CREDITO = 24   # px entre el credito del fondo y los bordes de la franja del juego

ESTILO_BASE = {
    # Subtitulos
    "tamano": 64,                # px sobre un lienzo de 1080x1920
    "color": "#FFFFFF",
    "color_borde": "#000000",
    "borde": 5,
    "posicion": 72,              # % desde arriba donde va el centro del texto
    "mayusculas": True,
    "caja": False,               # True: texto dentro de una caja del color del borde
    "max_caracteres": 18,        # por subtitulo al generar
    "max_palabras": 4,           # por subtitulo al generar
    "resaltar": False,           # colorea la palabra que se esta diciendo
    "color_resalte": "#FFE600",
    # Titulo gancho (texto fijo arriba del clip)
    "titulo_gancho": "",
    "gancho_segundos": 4,        # 0 = durante todo el clip
    "gancho_posicion": 14,       # % desde arriba
    "gancho_tamano": 58,
    "gancho_color": "#000000",
    "gancho_fondo": "#FFFFFF",
    # Marca de agua (nombre del canal, visible durante todo el clip)
    "marca": "",
    "marca_posicion": "abajo_derecha",   # arriba_izquierda | arriba_derecha | abajo_izquierda | abajo_derecha
    "marca_tamano": 34,
    "marca_opacidad": 70,        # % de opacidad
    "marca_color": "#FFFFFF",
    # Fondo del encuadre "ajustar"
    "fondo": "difuminado",       # difuminado | difuminado_oscuro | difuminado_gris | color
    "difuminado": 24,            # intensidad del desenfoque del fondo
    "color_fondo": "#000000",
    # Video de juego de abajo (encuadre "dividido")
    "fondo_juego": "",           # archivo de la carpeta de fondos, o "yt:<id>" (YouTube); "" = al azar
    "juego_proporcion": 45,      # % del alto que ocupa el juego
    # Credito del autor del fondo (esquina inferior izquierda de la franja del juego)
    "credito_fondo": False,      # el texto sale del fondo usado; un fondo local no tiene credito
    "credito_tamano": 28,
}
LIMITES = {
    "tamano": (24, 140), "borde": (0, 12), "posicion": (5, 95), "max_caracteres": (8, 42),
    "max_palabras": (1, 8), "gancho_segundos": (0, 600), "gancho_posicion": (4, 90),
    "gancho_tamano": (24, 140), "juego_proporcion": (25, 60), "difuminado": (4, 50),
    "marca_tamano": (16, 80), "marca_opacidad": (10, 100), "credito_tamano": (16, 60),
}
MARCA_POSICIONES = ("arriba_izquierda", "arriba_derecha", "abajo_izquierda", "abajo_derecha")
FONDOS =("difuminado", "difuminado_oscuro", "difuminado_gris", "color")
# Claves que describen solo el aspecto de los subtitulos (para copiarlas entre clips).
CLAVES_SUBTITULOS = (
    "tamano", "color", "color_borde", "borde", "posicion", "mayusculas", "caja",
    "max_caracteres", "max_palabras", "resaltar", "color_resalte",
)
COLORES = ("color", "color_borde", "color_resalte", "gancho_color", "gancho_fondo", "color_fondo", "marca_color")
BOOLEANOS = ("mayusculas", "caja", "resaltar", "credito_fondo")
# Lo que NO se guarda como preferencia para clips futuros: es propio de cada clip.
SOLO_DEL_CLIP = ("titulo_gancho",)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Un fondo de YouTube se guarda como "yt:" + id de 11 caracteres. Los dos puntos no pueden
# estar en un nombre de archivo de Windows, asi que nunca se confunde con un fondo local.
PREFIJO_FONDO_REMOTO = "yt:"
_ID_REMOTO = re.compile(r"^[A-Za-z0-9_-]{11}$")


def normalizar_estilo(estilo: dict | None) -> dict:
    """Devuelve un estilo completo y valido; ignora claves desconocidas y valores fuera de rango."""
    final = dict(ESTILO_BASE)
    for clave, valor in (estilo or {}).items():
        if clave in LIMITES:
            try:
                lo, hi = LIMITES[clave]
                final[clave] = int(max(lo, min(hi, float(valor))))
            except (TypeError, ValueError):
                pass
        elif clave in COLORES:
            if isinstance(valor, str) and _HEX.match(valor):
                final[clave] = valor.upper()
        elif clave in BOOLEANOS:
            final[clave] = bool(valor)
        elif clave == "fondo":
            if valor in FONDOS:
                final[clave] = valor
        elif clave == "titulo_gancho":
            final[clave] = " ".join(str(valor or "").split())[:80]
        elif clave == "marca":
            final[clave] = " ".join(str(valor or "").split())[:40]
        elif clave == "marca_posicion":
            if valor in MARCA_POSICIONES:
                final[clave] = valor
        elif clave == "fondo_juego":
            final[clave] = _nombre_fondo(valor)
    return final


def es_id_remoto(valor: object) -> bool:
    return isinstance(valor, str) and bool(_ID_REMOTO.fullmatch(valor))


def _nombre_fondo(valor: object) -> str:
    """Fondo valido: `yt:<id>` o nombre de archivo simple (sin rutas); si no lo es, devuelve ""."""
    if isinstance(valor, str) and valor.startswith(PREFIJO_FONDO_REMOTO):
        return valor if es_id_remoto(valor[len(PREFIJO_FONDO_REMOTO):]) else ""
    if (
        isinstance(valor, str) and 0 < len(valor) <= 150 and valor == Path(valor).name
        and "/" not in valor and "\\" not in valor and ".." not in valor and ":" not in valor
    ):
        return valor
    return ""


def estilo_para_preferencia(estilo: dict | None) -> dict:
    """Estilo reutilizable en clips futuros (sin el texto propio de un clip)."""
    final = normalizar_estilo(estilo)
    for clave in SOLO_DEL_CLIP:
        final[clave] = ESTILO_BASE[clave]
    return final


def palabras_en_rango(segmentos: list[dict], inicio: float, fin: float) -> list[dict]:
    """Palabras cuyo punto medio cae dentro de [inicio, fin]."""
    return [
        p
        for s in segmentos
        for p in s.get("palabras", [])
        if inicio <= (p["inicio"] + p["fin"]) / 2 <= fin
    ]


def agrupar(palabras: list[dict], max_caracteres: int = 18, max_palabras: int = 4) -> list[dict]:
    """Agrupa palabras en subtitulos cortos: [{inicio, fin, texto}]."""
    cues: list[dict] = []
    actual: list[dict] = []

    def cerrar() -> None:
        if actual:
            cues.append(
                {
                    "inicio": actual[0]["inicio"],
                    "fin": max(actual[-1]["fin"], actual[0]["inicio"] + 0.25),
                    "texto": " ".join(p["texto"] for p in actual),
                }
            )
            actual.clear()

    for p in palabras:
        if actual:
            largo = len(" ".join(x["texto"] for x in actual)) + 1 + len(p["texto"])
            pausa = p["inicio"] - actual[-1]["fin"]
            if (
                largo > max_caracteres
                or len(actual) >= max_palabras
                or pausa > 0.5
                or actual[-1]["texto"].endswith(FIN_FRASE)
            ):
                cerrar()
        actual.append(p)
    cerrar()
    # Evita solapes y rellena huecos muy pequenos para que no parpadee.
    for a, b in zip(cues, cues[1:]):
        if a["fin"] > b["inicio"] or b["inicio"] - a["fin"] < 0.12:
            a["fin"] = b["inicio"]
    return [{"inicio": round(c["inicio"], 3), "fin": round(c["fin"], 3), "texto": c["texto"]} for c in cues]


def generar(segmentos: list[dict], inicio: float, fin: float, estilo: dict | None = None) -> list[dict]:
    est = normalizar_estilo(estilo)
    palabras = palabras_en_rango(segmentos, inicio, fin)
    return recortar(agrupar(palabras, est["max_caracteres"], est["max_palabras"]), inicio, fin)


def recortar(cues: list[dict], inicio: float, fin: float) -> list[dict]:
    """Deja solo los subtitulos que tocan el rango y los ajusta a sus bordes."""
    out = []
    for c in cues:
        a, b = max(c["inicio"], inicio), min(c["fin"], fin)
        if b - a >= 0.05 and str(c.get("texto", "")).strip():
            out.append({"inicio": round(a, 3), "fin": round(b, 3), "texto": c["texto"]})
    return out


def sincronizar(cues: list[dict], segmentos: list[dict], inicio: float, fin: float, estilo: dict | None = None) -> list[dict]:
    """Al mover el inicio/fin de un clip: conserva lo ya editado y completa lo nuevo.

    Se mantienen los subtitulos existentes que siguen dentro del rango y se generan desde
    la transcripcion solo los tramos que quedaron sin cubrir al principio o al final.
    """
    conservados = recortar(cues, inicio, fin)
    if not conservados:
        return generar(segmentos, inicio, fin, estilo)
    est = normalizar_estilo(estilo)
    primero, ultimo = conservados[0]["inicio"], conservados[-1]["fin"]
    # Mismo criterio que al generar (punto medio de la palabra): una palabra que cruza el
    # limite anterior del clip no queda fuera ni duplicada.
    palabras = palabras_en_rango(segmentos, inicio, fin)
    medio = lambda p: (p["inicio"] + p["fin"]) / 2  # noqa: E731
    limites = est["max_caracteres"], est["max_palabras"]
    antes = agrupar([p for p in palabras if medio(p) < primero], *limites)
    despues = agrupar([p for p in palabras if medio(p) > ultimo], *limites)
    return recortar(antes, inicio, primero) + conservados + recortar(despues, ultimo, fin)


def validar(cues: object, duracion_total: float) -> list[dict]:
    """Valida subtitulos recibidos del cliente. Lanza ValueError con mensaje en espanol."""
    if not isinstance(cues, list):
        raise ValueError("Los subtitulos deben ser una lista.")
    if len(cues) > 2000:
        raise ValueError("Demasiados subtitulos en un solo clip.")
    out = []
    for c in cues:
        try:
            a, b = float(c["inicio"]), float(c["fin"])
            texto = str(c["texto"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Cada subtitulo necesita inicio, fin y texto.") from exc
        if not (0 <= a < b <= duracion_total + 1):
            raise ValueError("Un subtitulo tiene tiempos invalidos (el fin debe ser mayor que el inicio).")
        texto = " ".join(texto.replace("\r", " ").replace("\n", " ").split())[:200]
        if texto:
            out.append({"inicio": round(a, 3), "fin": round(b, 3), "texto": texto})
    out.sort(key=lambda c: c["inicio"])
    # Dos subtitulos no pueden verse a la vez (se dibujarian uno encima del otro): el
    # anterior termina donde empieza el siguiente.
    for a, b in zip(out, out[1:]):
        if a["fin"] > b["inicio"]:
            a["fin"] = b["inicio"]
    return [c for c in out if c["fin"] - c["inicio"] >= 0.05]


# ---------- tiempos por palabra dentro de un subtitulo (para resaltar) ----------

def _simple(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in texto if unicodedata.category(c) != "Mn"))


def tiempos_de_palabras(cue: dict, palabras: list[dict] | None = None) -> list[tuple[float, str]]:
    """Devuelve [(inicio, palabra)] para cada palabra del subtitulo.

    Si el texto sigue coincidiendo con la transcripcion se usan sus tiempos reales; si el
    subtitulo se edito, el tiempo se reparte en proporcion al largo de cada palabra.
    """
    trozos = str(cue["texto"]).split()
    if not trozos:
        return []
    if palabras:
        dentro = [p for p in palabras if cue["inicio"] - 0.02 <= (p["inicio"] + p["fin"]) / 2 <= cue["fin"] + 0.02]
        if len(dentro) == len(trozos) and all(_simple(p["texto"]) == _simple(t) for p, t in zip(dentro, trozos)):
            tiempos = [max(cue["inicio"], min(p["inicio"], cue["fin"])) for p in dentro]
            tiempos[0] = cue["inicio"]
            return list(zip(tiempos, trozos))
    pesos = [len(t) + 1 for t in trozos]
    total, duracion = sum(pesos), cue["fin"] - cue["inicio"]
    out, acumulado = [], 0
    for peso, t in zip(pesos, trozos):
        out.append((cue["inicio"] + duracion * acumulado / total, t))
        acumulado += peso
    return out


# ---------- ASS ----------

def a_srt(cues: list[dict]) -> str:
    """Serializa subtítulos que ya están en el tiempo del clip exportado."""
    def tiempo(segundos: float) -> str:
        segundos, milisegundos = divmod(round(segundos * 1000), 1000)
        minutos, segundos = divmod(segundos, 60)
        horas, minutos = divmod(minutos, 60)
        return f"{horas:02d}:{minutos:02d}:{segundos:02d},{milisegundos:03d}"

    bloques = []
    for numero, cue in enumerate(sorted(cues, key=lambda c: c["inicio"]), 1):
        texto = "\n".join(linea for linea in cue["texto"].splitlines() if linea.strip())
        bloques.append(f'{numero}\n{tiempo(cue["inicio"])} --> {tiempo(cue["fin"])}\n{texto}\n')
    return "\n".join(bloques)


def _tiempo_ass(seg: float) -> str:
    cs = max(0, int(round(seg * 100)))
    h, resto = divmod(cs, 360000)
    m, resto = divmod(resto, 6000)
    s, cs = divmod(resto, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _color_ass(hex_color: str) -> str:
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H00{b}{g}{r}".upper()


def _texto_ass(texto: str) -> str:
    # Sin llaves ni barras invertidas: asi el texto no puede inyectar etiquetas ASS.
    return texto.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def tiene_contenido(cues: list[dict], estilo: dict | None, credito: str = "") -> bool:
    """True si hay algo que dibujar sobre el video (subtitulos, titulo gancho, marca o credito)."""
    est = normalizar_estilo(estilo)
    return bool(cues) or bool(est["titulo_gancho"]) or bool(est["marca"]) or _hay_credito(est, credito)


def _texto_credito(credito: str) -> str:
    return _texto_ass(" ".join(str(credito or "").split())[:100])


def _hay_credito(est: dict, credito: str) -> bool:
    return bool(est["credito_fondo"]) and bool(_texto_credito(credito))


def _anclaje_marca(posicion: str, w: int, h: int) -> tuple[int, int, int]:
    """Alineacion ASS (\\an), x e y de la marca, a 40 px de los bordes."""
    an = {"arriba_izquierda": 7, "arriba_derecha": 9, "abajo_izquierda": 1, "abajo_derecha": 3}[posicion]
    x = w - 40 if posicion.endswith("derecha") else 40
    y = 40 if posicion.startswith("arriba") else h - 40
    return an, x, y


def _alfa_marca(opacidad: int) -> str:
    """Canal alfa ASS (00 = opaco, FF = transparente) en hexadecimal de dos digitos.

    Redondeo hacia arriba en la mitad (opacidad 70 -> 4D), con enteros para no depender de float.
    """
    return f"{(255 * (100 - opacidad) + 50) // 100:02X}"


def a_ass(
    cues: list[dict],
    inicio_clip: float,
    fin_clip: float,
    estilo: dict | None = None,
    palabras: list[dict] | None = None,
    credito: str = "",
) -> str:
    """Archivo ASS con tiempos relativos al inicio del clip, para un lienzo 1080x1920.

    `palabras` son las palabras de la transcripcion (tiempo del video fuente); solo se usan
    para afinar el resaltado palabra a palabra. `credito` es el texto de credito del fondo
    que se usa en esta exportacion (depende del fondo elegido, por eso no va en el estilo);
    solo se dibuja si el estilo tiene activado `credito_fondo`.
    """
    est = normalizar_estilo(estilo)
    w, h = config.OUT_W, config.OUT_H
    x, y = w // 2, int(h * est["posicion"] / 100)
    primario, borde = _color_ass(est["color"]), _color_ass(est["color_borde"])
    # BorderStyle 3 dibuja una caja opaca del color del borde detras del texto.
    estilo_borde, grosor = (3, max(est["borde"], 10)) if est["caja"] else (1, est["borde"])
    formato = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    cabecera = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
{formato}
Style: Clip,Arial,{est["tamano"]},{primario},{primario},{borde},&H00000000,-1,0,0,0,100,100,0,0,{estilo_borde},{grosor},0,5,60,60,0,1
Style: Gancho,Arial,{est["gancho_tamano"]},{_color_ass(est["gancho_color"])},{_color_ass(est["gancho_color"])},{_color_ass(est["gancho_fondo"])},&H00000000,-1,0,0,0,100,100,0,0,3,16,0,5,90,90,0,1
Style: Marca,Arial,{est["marca_tamano"]},{_color_ass(est["marca_color"])},{_color_ass(est["marca_color"])},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
Style: Credito,Arial,{est["credito_tamano"]},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,1,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = []
    duracion = fin_clip - inicio_clip
    pos = f"{{\\an5\\pos({x},{y})}}"

    def preparar(texto: str) -> str:
        texto = _texto_ass(texto)
        return texto.upper() if est["mayusculas"] else texto

    for c in recortar(cues, inicio_clip, fin_clip):
        a = max(0.0, c["inicio"] - inicio_clip)
        b = min(duracion, c["fin"] - inicio_clip)
        if b <= a or not preparar(c["texto"]):
            continue
        if not est["resaltar"]:
            lineas.append(f"Dialogue: 0,{_tiempo_ass(a)},{_tiempo_ass(b)},Clip,,0,0,0,,{pos}{preparar(c['texto'])}")
            continue
        # Un evento por palabra: mismo texto, con la palabra activa en el color de resalte.
        marcas = tiempos_de_palabras(c, palabras)
        trozos = [preparar(t) for _, t in marcas]
        resalte = "{\\c" + _color_ass(est["color_resalte"])[:2] + _color_ass(est["color_resalte"])[4:] + "&}"
        normal = "{\\c" + primario[:2] + primario[4:] + "&}"
        for i, (t_ini, _) in enumerate(marcas):
            t_fin = marcas[i + 1][0] if i + 1 < len(marcas) else c["fin"]
            ia, ib = max(a, t_ini - inicio_clip), min(b, t_fin - inicio_clip)
            if ib - ia < 0.01 or not trozos[i]:
                continue
            texto = " ".join(
                (resalte + t + normal) if j == i else t for j, t in enumerate(trozos) if t
            )
            lineas.append(f"Dialogue: 0,{_tiempo_ass(ia)},{_tiempo_ass(ib)},Clip,,0,0,0,,{pos}{texto}")

    gancho = _texto_ass(est["titulo_gancho"])
    if gancho:
        hasta = duracion if est["gancho_segundos"] == 0 else min(duracion, est["gancho_segundos"])
        gy = int(h * est["gancho_posicion"] / 100)
        lineas.append(
            f"Dialogue: 1,{_tiempo_ass(0)},{_tiempo_ass(hasta)},Gancho,,0,0,0,,"
            f"{{\\an5\\pos({x},{gy})\\fad(150,200)}}{gancho}"
        )
    marca = _texto_ass(est["marca"])
    if marca and duracion > 0:
        an, mx, my = _anclaje_marca(est["marca_posicion"], w, h)
        lineas.append(
            f"Dialogue: 2,{_tiempo_ass(0)},{_tiempo_ass(duracion)},Marca,,0,0,0,,"
            f"{{\\an{an}\\pos({mx},{my})\\alpha&H{_alfa_marca(est['marca_opacidad'])}&}}{marca}"
        )
    if _hay_credito(est, credito) and duracion > 0:
        # Esquina inferior izquierda de la franja del juego (que llega hasta el borde inferior), a 24 px.
        lineas.append(
            f"Dialogue: 3,{_tiempo_ass(0)},{_tiempo_ass(duracion)},Credito,,0,0,0,,"
            f"{{\\an1\\pos({MARGEN_CREDITO},{h - MARGEN_CREDITO})}}{_texto_credito(credito)}"
        )
    return cabecera + "\n".join(lineas) + "\n"
