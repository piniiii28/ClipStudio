"""Perfiles de salida y revision del fragmento antes de renderizar."""
from __future__ import annotations

from . import cortes, editorial

# Adaptado de ffmpeg_utils.py de OpenShorts, MIT (ver THIRD_PARTY_NOTICES.md).
METADATOS_LIMPIOS = ["-map_metadata", "-1", "-map_chapters", "-1",
                    "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1"]
NORMALIZAR_AUDIO = "loudnorm=I=-14:TP=-2:LRA=11"

PERFILES = {
    "social": {"nombre": "Social · 1080p", "ancho": 1080, "alto": 1920, "crf": 20, "preset": "veryfast"},
    "calidad": {"nombre": "Máxima calidad · 1080p", "ancho": 1080, "alto": 1920, "crf": 18, "preset": "fast"},
    "borrador": {"nombre": "Borrador · 720p", "ancho": 720, "alto": 1280, "crf": 24, "preset": "veryfast"},
}


def revisar(clip: dict, fuente: dict, perfil: str = "social") -> dict:
    salida = PERFILES[perfil]
    avisos = []
    if fuente["alto"] < 720:
        avisos.append("La fuente tiene menos de 720p. Ampliarla puede reducir la nitidez.")
    if not fuente["tiene_audio"]:
        avisos.append("La fuente no tiene audio.")
    if not clip.get("subtitulos"):
        avisos.append("Este clip se exportará sin subtítulos.")
    if clip["encuadre"] == "stream" and not (clip.get("composicion") or {}).get("camara"):
        avisos.append("La cámara está sin definir. Revisa la composición del stream.")
    revision = editorial.revisar_subtitulos(clip)
    if revision:
        avisos.append(f"Hay {len(revision)} avisos de legibilidad o tiempos en los subtítulos. Revísalos en el editor.")
    return {"fuente": {k: fuente[k] for k in ("ancho", "alto", "tiene_audio", "codec_video")},
            "salida": salida, "duracion": round(cortes.duracion_final(clip["inicio"], clip["fin"], clip.get("cortes") or []), 3),
            "subtitulos": len(clip.get("subtitulos") or []), "cortes": len(clip.get("cortes") or []), "avisos": avisos}
