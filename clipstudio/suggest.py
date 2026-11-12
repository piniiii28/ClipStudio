"""Propuesta automatica de fragmentos a partir de la transcripcion.

Metodo (heuristico y transparente, NO predice viralidad):
  1. Se parte la transcripcion en frases usando la puntuacion y las pausas del habla.
  2. Se generan ventanas candidatas que empiezan y terminan en limite de frase y cuya
     duracion cae dentro del rango pedido.
  3. Cada candidata recibe puntos por rasgos observables: empieza tras una pausa, termina
     en cierre de frase seguido de pausa, tiene poca proporcion de silencio, su ritmo de
     habla es alto respecto al video, abre con una pregunta o un dato, contiene un pico
     de volumen (grito, risa, sobresalto) y se acerca a la duracion objetivo.
  4. Se eligen las mejores sin solaparse.

Limitaciones: no entiende el contenido ni la imagen, depende de la calidad de la
transcripcion y de su puntuacion, y un rasgo como "abre con una pregunta" no garantiza
que el fragmento sea interesante. Los motivos se muestran para que la persona decida.
"""

from __future__ import annotations

import bisect
import re
import statistics

FIN_FRASE = (".", "?", "!", "…")
PAUSA_FRASE = 0.7       # una pausa asi de larga tambien separa frases
PAUSA_INICIO = 0.6
PAUSA_CIERRE = 0.4
MAX_PALABRAS_FRASE = 60  # corta frases interminables cuando falta puntuacion


def partir_en_frases(segmentos: list[dict]) -> list[dict]:
    """Agrupa las palabras en frases: [{indice, inicio, fin, texto, n_palabras, cierra}]."""
    palabras = [p for s in segmentos for p in s.get("palabras", [])]
    frases: list[dict] = []
    actual: list[dict] = []

    def cerrar() -> None:
        if not actual:
            return
        texto = " ".join(p["texto"] for p in actual).strip()
        frases.append(
            {
                "indice": len(frases),
                "inicio": actual[0]["inicio"],
                "fin": actual[-1]["fin"],
                "texto": texto,
                "n_palabras": len(actual),
                "cierra": texto.endswith(FIN_FRASE),
            }
        )
        actual.clear()

    for i, p in enumerate(palabras):
        actual.append(p)
        siguiente = palabras[i + 1] if i + 1 < len(palabras) else None
        pausa = (siguiente["inicio"] - p["fin"]) if siguiente else 0.0
        if (
            p["texto"].endswith(FIN_FRASE)
            or siguiente is None
            or pausa >= PAUSA_FRASE
            or len(actual) >= MAX_PALABRAS_FRASE
        ):
            cerrar()
    return frases


def _puntuar(
    frases: list[dict], i: int, j: int, objetivo: float, ritmo_medio: float, total: float,
    picos: list[float] | None = None,
):
    primera, ultima = frases[i], frases[j]
    inicio, fin = primera["inicio"], ultima["fin"]
    duracion = fin - inicio
    n_palabras = sum(f["n_palabras"] for f in frases[i : j + 1])
    hablado = sum(f["fin"] - f["inicio"] for f in frases[i : j + 1])
    pausa_antes = inicio - (frases[i - 1]["fin"] if i > 0 else 0.0)
    pausa_despues = (frases[j + 1]["inicio"] if j + 1 < len(frases) else total) - fin

    puntos = 0.0
    motivos: list[str] = []

    if i == 0 or pausa_antes >= PAUSA_INICIO:
        puntos += 1.0
        motivos.append("Empieza tras una pausa")
    if ultima["cierra"]:
        puntos += 1.0
        if j + 1 >= len(frases) or pausa_despues >= PAUSA_CIERRE:
            puntos += 0.5
            motivos.append("Termina en cierre de frase con pausa")
        else:
            motivos.append("Termina en cierre de frase")

    silencio = 1.0 - (hablado / duracion if duracion > 0 else 0.0)
    puntos += max(0.0, 1.0 - silencio * 2.5)
    if silencio <= 0.15:
        motivos.append("Pocas pausas internas")

    ritmo = n_palabras / duracion if duracion > 0 else 0.0
    if ritmo_medio > 0:
        puntos += max(0.0, min(1.0, ritmo / ritmo_medio - 0.5))
        if ritmo >= ritmo_medio * 1.1:
            motivos.append("Ritmo de habla por encima de la media del video")

    apertura = primera["texto"]
    if "?" in apertura:
        puntos += 0.75
        motivos.append("Abre con una pregunta")
    elif re.search(r"\d", apertura):
        puntos += 0.4
        motivos.append("Abre con una cifra")

    if picos:
        n_picos = bisect.bisect_right(picos, fin) - bisect.bisect_left(picos, inicio)
        if n_picos:
            puntos += min(2.0, 1.25 * n_picos)
            motivos.append(
                "Contiene un pico de volumen (posible reaccion)" if n_picos == 1
                else f"Contiene {n_picos} picos de volumen (posibles reacciones)"
            )

    puntos += max(0.0, 1.0 - abs(duracion - objetivo) / objetivo)
    return puntos, motivos


def proponer_clips(
    segmentos: list[dict],
    duracion_total: float,
    min_s: float = 15.0,
    max_s: float = 60.0,
    maximo: int | None = None,
    picos: list[dict] | None = None,
) -> list[dict]:
    """Devuelve hasta `maximo` propuestas [{inicio, fin, titulo, motivos, indices_frases}].

    Sin `maximo` se propone aproximadamente un clip por cada 3 minutos (entre 8 y 40).
    `picos` son los picos de volumen detectados al transcribir: [{t, exceso_db}].
    """
    if maximo is None:
        maximo = int(max(8, min(40, round(duracion_total / 180))))
    tiempos_picos = sorted(p["t"] for p in (picos or []))
    min_s = max(3.0, float(min_s))
    max_s = max(min_s + 1.0, float(max_s))
    frases = partir_en_frases(segmentos)
    if not frases:
        return []
    objetivo = (min_s + max_s) / 2
    ritmos = [f["n_palabras"] / (f["fin"] - f["inicio"]) for f in frases if f["fin"] - f["inicio"] > 0.3]
    ritmo_medio = statistics.median(ritmos) if ritmos else 0.0

    candidatas = []
    for i in range(len(frases)):
        for j in range(i, len(frases)):
            dur = frases[j]["fin"] - frases[i]["inicio"]
            if dur > max_s:
                break
            if dur < min_s:
                continue
            puntos, motivos = _puntuar(frases, i, j, objetivo, ritmo_medio, duracion_total, tiempos_picos)
            candidatas.append((puntos, i, j, motivos))

    if not candidatas:
        # El video es mas corto que el minimo o no hay cortes posibles: un unico fragmento.
        inicio = frases[0]["inicio"]
        fin = min(frases[-1]["fin"], inicio + max_s)
        ultimos = [f["indice"] for f in frases if f["fin"] <= fin + 1e-6]
        return [
            {
                "inicio": inicio,
                "fin": fin,
                "titulo": _titulo(frases[0]["texto"]),
                "motivos": ["Unico fragmento posible con la duracion pedida"],
                "indices_frases": ultimos,
            }
        ]

    candidatas.sort(key=lambda c: c[0], reverse=True)
    elegidas: list[tuple] = []
    for cand in candidatas:
        _, i, j, _ = cand
        if all(j < ei or i > ej for _, ei, ej, _ in elegidas):
            elegidas.append(cand)
            if len(elegidas) >= maximo:
                break
    elegidas.sort(key=lambda c: c[1])
    return [
        {
            "inicio": frases[i]["inicio"],
            "fin": frases[j]["fin"],
            "titulo": _titulo(frases[i]["texto"]),
            "motivos": motivos or ["Fragmento con limites de frase"],
            "indices_frases": list(range(i, j + 1)),
        }
        for _, i, j, motivos in elegidas
    ]


def _titulo(texto: str, limite: int = 60) -> str:
    texto = " ".join(texto.split())
    if len(texto) <= limite:
        return texto or "Clip"
    return texto[:limite].rsplit(" ", 1)[0] + "…"


MAX_PARTE_S = 600.0   # mismo limite que un clip editado a mano
MIN_PARTE_S = 1.0


def dividir(segmentos: list[dict], duracion_total: float, objetivo_s: float = 30.0, ajustar: bool = True) -> list[dict]:
    """Divide TODO el video en clips consecutivos de unos `objetivo_s` segundos.

    Con `ajustar`, cada corte se mueve (hasta un 25 % de la duracion objetivo) a la pausa
    mas larga entre frases que haya cerca, para no partir una frase. Sin transcripcion o
    sin `ajustar`, los cortes son exactos. Devuelve [{inicio, fin, titulo}] sin huecos.
    """
    objetivo_s = max(5.0, min(MAX_PARTE_S, float(objetivo_s)))
    frases = partir_en_frases(segmentos) if segmentos else []
    # Candidatos de corte: el punto medio de cada pausa entre frases, con su duracion.
    pausas = [
        ((a["fin"] + b["inicio"]) / 2, b["inicio"] - a["fin"])
        for a, b in zip(frases, frases[1:])
        if b["inicio"] > a["fin"]
    ]
    tiempos = [t for t, _ in pausas]
    tolerancia = objetivo_s * 0.25
    cortes = [0.0]
    # El ultimo tramo absorbe el resto si es corto, pero nunca supera el maximo por clip.
    while duracion_total - cortes[-1] > min(objetivo_s * 1.4, MAX_PARTE_S):
        ideal = cortes[-1] + objetivo_s
        corte = ideal
        if ajustar and pausas:
            a = bisect.bisect_left(tiempos, ideal - tolerancia)
            b = bisect.bisect_right(tiempos, ideal + tolerancia)
            if b > a:
                # La pausa mas larga; a igualdad, la mas cercana al punto ideal.
                corte = max(pausas[a:b], key=lambda p: (round(p[1], 1), -abs(p[0] - ideal)))[0]
        corte = min(corte, cortes[-1] + MAX_PARTE_S)
        cortes.append(round(corte, 3))
    if duracion_total - cortes[-1] >= MIN_PARTE_S or len(cortes) == 1:
        cortes.append(round(duracion_total, 3))
    # (un resto menor de un segundo no forma un clip valido: queda fuera)

    inicios_frases = [f["inicio"] for f in frases]
    partes = []
    total = len(cortes) - 1
    for k in range(total):
        inicio, fin = cortes[k], cortes[k + 1]
        i = bisect.bisect_left(inicios_frases, inicio - 0.05)
        texto = frases[i]["texto"] if i < len(frases) and frases[i]["inicio"] < fin else ""
        etiqueta = f"Parte {k + 1} de {total}"
        partes.append(
            {"inicio": inicio, "fin": fin, "titulo": f"{etiqueta}: {_titulo(texto, 44)}" if texto else etiqueta}
        )
    return partes
