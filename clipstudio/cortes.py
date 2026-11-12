"""Cortes internos y conversion de tiempos, sin acceso a archivos ni procesos."""

from __future__ import annotations

import math


def normalizar(cortes, inicio, fin):
    """Valida, recorta y fusiona los tramos eliminados del video fuente."""
    if not isinstance(cortes, list):
        raise ValueError("Los cortes deben ser una lista.")
    if len(cortes) > 200:
        raise ValueError("No se permiten mas de 200 cortes por clip.")
    tramos = []
    for c in cortes:
        if not isinstance(c, dict) or any(
            not isinstance(c.get(k), (int, float)) or isinstance(c.get(k), bool)
            or not math.isfinite(c[k]) for k in ("inicio", "fin")
        ):
            raise ValueError("Cada corte necesita inicio y fin numericos finitos.")
        if c["fin"] <= c["inicio"]:
            raise ValueError("El fin de cada corte debe ser mayor que el inicio.")
        a, b = max(inicio, c["inicio"]), min(fin, c["fin"])
        if b - a >= 0.05 - 1e-9:
            tramos.append({"inicio": a, "fin": b})
    salida = []
    for c in sorted(tramos, key=lambda c: c["inicio"]):
        if salida and c["inicio"] <= salida[-1]["fin"]:
            salida[-1]["fin"] = max(salida[-1]["fin"], c["fin"])
        else:
            salida.append(dict(c))
    if duracion_final(inicio, fin, salida) < 1 - 1e-9:
        raise ValueError("El clip debe conservar al menos 1 segundo util.")
    return salida


def tramos_conservados(inicio, fin, cortes):
    """Complemento de los cortes normalizados dentro del clip."""
    salida, cursor = [], inicio
    for c in cortes:
        a, b = max(inicio, c["inicio"]), min(fin, c["fin"])
        if b <= cursor or a >= fin:
            continue
        if a > cursor:
            salida.append([cursor, a])
        cursor = max(cursor, b)
    if cursor < fin:
        salida.append([cursor, fin])
    return salida


def duracion_final(inicio, fin, cortes):
    return sum(b - a for a, b in tramos_conservados(inicio, fin, cortes))


def a_tiempo_final(t, inicio, cortes):
    """Un tiempo eliminado se pega al borde donde se unen los tramos."""
    return max(0.0, t - inicio - sum(
        max(0.0, min(t, c["fin"]) - max(inicio, c["inicio"])) for c in cortes
    ))


def remapear_subtitulos(cues, inicio, fin, cortes):
    salida = []
    for c in cues:
        a = a_tiempo_final(max(inicio, c["inicio"]), inicio, cortes)
        b = a_tiempo_final(min(fin, c["fin"]), inicio, cortes)
        if b - a >= 0.05 - 1e-9:
            salida.append({**c, "inicio": a, "fin": b})
    return salida


def remapear_palabras(palabras, inicio, cortes):
    # El punto medio decide si una palabra esta eliminada, igual que palabras_en_rango.
    conservadas = [p for p in palabras if not any(
        c["inicio"] <= (p["inicio"] + p["fin"]) / 2 < c["fin"] for c in cortes
    )]
    return remapear_subtitulos(conservadas, inicio, float("inf"), cortes)


def silencios(segmentos, inicio, fin, minimo_s=0.6, margen_s=0.12):
    """Huecos sin palabras; sin transcripcion no se supone que todo sea silencio."""
    palabras = sorted((p for s in segmentos for p in s.get("palabras", [])
                       if p["fin"] > inicio and p["inicio"] < fin), key=lambda p: p["inicio"])
    if not palabras:
        return []
    salida, cursor = [], inicio
    for p in palabras + [{"inicio": fin, "fin": fin}]:
        a = max(inicio, min(fin, p["inicio"]))
        if a - cursor > minimo_s and a - cursor - 2 * margen_s >= 0.05:
            salida.append({"inicio": cursor + margen_s, "fin": a - margen_s})
        cursor = max(cursor, min(fin, p["fin"]))
    return salida
