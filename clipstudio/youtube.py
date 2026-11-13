"""Consulta de videos populares y validación de enlaces de YouTube."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


class ErrorYouTube(Exception):
    pass


def url_video(url: str) -> str:
    partes = urlparse(url.strip())
    host = partes.hostname
    rutas = partes.path.strip("/").split("/")
    video_id = ""
    if host == "youtu.be" and len(rutas) == 1:
        video_id = rutas[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if partes.path == "/watch":
            video_id = parse_qs(partes.query).get("v", [""])[0]
        elif len(rutas) == 2 and rutas[0] in {"shorts", "live", "embed"}:
            video_id = rutas[1]
    if partes.scheme not in {"http", "https"} or not re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
        raise ValueError("Pega el enlace de un solo video de YouTube.")
    return f"https://www.youtube.com/watch?v={video_id}"


def tendencias(region: str, clave: str) -> list[dict]:
    consulta = urlencode({"part": "snippet", "chart": "mostPopular", "regionCode": region, "maxResults": 12})
    solicitud = Request(f"https://www.googleapis.com/youtube/v3/videos?{consulta}",
                        headers={"X-Goog-Api-Key": clave})
    try:
        with urlopen(solicitud, timeout=10) as respuesta:
            datos = json.load(respuesta)
    except HTTPError as exc:
        raise ErrorYouTube(f"YouTube respondió con HTTP {exc.code}. Revisa la clave, la región y la cuota de la API.") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise ErrorYouTube("No se pudo consultar YouTube. Vuelve a intentarlo.") from exc

    videos = []
    for item in datos.get("items", []):
        video_id = item.get("id", "")
        ficha = item.get("snippet") or {}
        if not re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id) or ficha.get("liveBroadcastContent") in {"live", "upcoming"}:
            continue
        videos.append({"titulo": ficha.get("title", "Video de YouTube"), "canal": ficha.get("channelTitle", ""),
                       "url": f"https://www.youtube.com/watch?v={video_id}",
                       "miniatura": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"})
    return videos
