"""Calidad del búfer en vivo y clips en alta calidad pedidos a la plataforma.

Dos ideas:
  - El búfer se graba a 480p, 720p o 1080p (formato pedido a yt-dlp) y por una duración elegida.
  - Para un clip, además de cortarlo del búfer, a veces se puede pedir ese tramo del pasado a la
    propia plataforma en mejor calidad:
      * YouTube en directo con DVR: la lista HLS del directo guarda la última hora (con la hora real
        de cada segmento en EXT-X-PROGRAM-DATE-TIME).
      * Twitch / Kick: el VOD en curso del canal (con su propia lista HLS).
    Se descarga SOLO ese tramo con yt-dlp (`download_ranges`, como `fondos_remotos`) y se alinea con
    el búfer comparando el audio, de modo que el corte sea exacto aunque la hora de reloj tenga
    unos segundos de error.

Las funciones puras (formato, estimaciones, ventana HLS, alineación, decisión de opciones) no
necesitan red ni FFmpeg y se prueban en `tests/test_vivo_calidad.py`.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from calendar import timegm
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import config, db, fondos_remotos, importer, media
from .media import Cancelacion, Cancelado, ErrorMedia

log = logging.getLogger("clipstudio")

ALTURAS_BUFER = (480, 720, 1080)
CALIDAD_DEFECTO = 720
OPCIONES_BUFER_MIN = (10, 20, 30, 60)
BUFER_MIN_DEFECTO = 20
MODOS_CLIP = ("preguntar", "buffer", "alta")

# Bitrate orientativo (kbit/s, video + audio) cuando la plataforma no lo dice.
KBPS_ORIENTATIVO = {480: 1100, 720: 2800, 1080: 6000}

# Segundos que el contenido tarda en llegar al búfer respecto a la hora real de emisión.
LATENCIA_S = {"youtube": 30.0, "twitch": 12.0, "kick": 12.0, "otra": 12.0}
PAD_ALTA_S = 20.0               # margen que se descarga a cada lado para poder alinear con el audio
MIN_SCORE_ALINEAR = 0.5         # correlación normalizada mínima para fiarse del alineado
AUDIO_HZ = 8000


# ---------- preferencias ----------

def buffer_min_defecto() -> float:
    return float(config.VIVO_BUFER_MIN)


def opciones_buffer_min() -> list[float]:
    """10, 20, 30 y 60 minutos (más el valor de CLIPSTUDIO_VIVO_BUFER_MIN si es otro)."""
    base = [float(n) for n in OPCIONES_BUFER_MIN]
    if buffer_min_defecto() not in base:
        base = sorted(base + [buffer_min_defecto()])
    return base


def preferencias_por_defecto() -> dict:
    return {"calidad": CALIDAD_DEFECTO, "buffer_min": buffer_min_defecto(), "clip_modo": "preguntar", "clip_altura": None}


def normalizar_preferencias(datos: dict | None) -> dict:
    """Devuelve las preferencias válidas; lo que no se reconoce vuelve al valor por defecto."""
    base = preferencias_por_defecto()
    datos = datos if isinstance(datos, dict) else {}
    if datos.get("calidad") in ALTURAS_BUFER:
        base["calidad"] = datos["calidad"]
    minutos = datos.get("buffer_min")
    if isinstance(minutos, (int, float)) and not isinstance(minutos, bool) and float(minutos) in opciones_buffer_min():
        base["buffer_min"] = float(minutos)
    if datos.get("clip_modo") in MODOS_CLIP:
        base["clip_modo"] = datos["clip_modo"]
    altura = datos.get("clip_altura")
    if isinstance(altura, int) and not isinstance(altura, bool) and 144 <= altura <= 2160:
        base["clip_altura"] = altura
    return base


def leer_preferencias() -> dict:
    try:
        return normalizar_preferencias(db.leer_preferencia("vivo", {}))
    except Exception:
        log.warning("No se pudieron leer las preferencias del modo en vivo", exc_info=True)
        return preferencias_por_defecto()


def guardar_preferencias(cambios: dict) -> dict:
    nuevas = normalizar_preferencias({**leer_preferencias(), **{k: v for k, v in cambios.items() if v is not None}})
    db.guardar_preferencia("vivo", nuevas)
    return nuevas


# ---------- formato y estimación ----------

def formato_ytdlp(altura: int) -> str:
    """Formato de yt-dlp para grabar el búfer a esa altura máxima, sin recodificar después.

    Un solo flujo con video y audio si existe (Kick, Twitch); si no, video y audio por separado
    (YouTube los entrega así). Si ninguno llega a esa calidad, se toma el más cercano.
    """
    altura = int(altura)
    respaldo = "b/best" if altura >= 1080 else "w"
    return f"b[height<={altura}]/bv*[height<={altura}]+ba/{respaldo}"


def gb_por_hora(kbps: float) -> float:
    return round(float(kbps) * 1000 / 8 * 3600 / 1024**3, 2)


def estimar_calidades(formatos: list[dict] | None) -> list[dict]:
    """Consumo por hora de cada calidad del búfer.

    Con la lista de formatos de yt-dlp se usa el bitrate real (`tbr`) del formato que se
    elegiría; si no se conoce, una estimación orientativa (`medido: False`).
    """
    formatos = [f for f in (formatos or []) if isinstance(f, dict)]
    resultado = []
    for altura in ALTURAS_BUFER:
        kbps, medido = KBPS_ORIENTATIVO[altura], False
        combinados = [f for f in formatos if f.get("height") and f["height"] <= altura and f.get("tbr")
                      and f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none")]
        solo_video = [f for f in formatos if f.get("height") and f["height"] <= altura and f.get("tbr")
                      and f.get("vcodec") not in (None, "none") and f.get("acodec") in (None, "none")]
        audios = [f for f in formatos if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none") and f.get("tbr")]
        if combinados:
            kbps, medido = float(max(combinados, key=lambda f: f["height"])["tbr"]), True
        elif solo_video:
            kbps = float(max(solo_video, key=lambda f: f["height"])["tbr"]) + (float(max(a["tbr"] for a in audios)) if audios else 128.0)
            medido = True
        resultado.append({"altura": altura, "kbps": round(kbps), "gb_hora": gb_por_hora(kbps), "medido": medido})
    return resultado


# ---------- HLS y reloj ----------

def parsear_hls(texto: str) -> dict:
    """De una lista HLS: hora de reloj (epoch) del primer segmento, duración total y nº de segmentos.

    `inicio` es None si la lista no trae EXT-X-PROGRAM-DATE-TIME. Twitch añade además
    EXT-X-TWITCH-ELAPSED-SECS / TOTAL-SECS; no hacen falta: la hora de reloj basta.
    """
    inicio, total, n = None, 0.0, 0
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if linea.startswith("#EXT-X-PROGRAM-DATE-TIME:") and inicio is None:
            inicio = _epoch_iso(linea.split(":", 1)[1])
        elif linea.startswith("#EXTINF:"):
            try:
                total += float(linea[8:].split(",", 1)[0])
                n += 1
            except ValueError:
                continue
    return {"inicio": inicio, "duracion": total, "segmentos": n}


def _epoch_iso(texto: str) -> float | None:
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$", texto.strip())
    if not m:
        return None
    a, mes, d, hh, mm, ss, frac, zona = m.groups()
    epoch = timegm((int(a), int(mes), int(d), int(hh), int(mm), int(ss)))
    if frac:
        epoch += float("0." + frac)
    if zona and zona != "Z":
        signo = 1 if zona[0] == "+" else -1
        z = zona[1:].replace(":", "")
        epoch -= signo * (int(z[:2]) * 3600 + int(z[2:]) * 60)
    return float(epoch)


def reloj_de(segmentos, t: float) -> float | None:
    """Hora de reloj (epoch) a la que se grabó el instante `t` del búfer.

    Cada segmento recuerda el reloj en que se vio cerrado (`reloj`); dentro de él se retrocede
    lo que falta hasta su final. Devuelve None si ningún segmento tiene reloj.
    """
    con_reloj = [s for s in segmentos if getattr(s, "reloj", 0) > 0]
    if not con_reloj:
        return None
    dentro = [s for s in con_reloj if s.inicio <= t <= s.fin]
    ref = dentro[0] if dentro else min(con_reloj, key=lambda s: min(abs(s.inicio - t), abs(s.fin - t)))
    return ref.reloj - (ref.fin - t)


def latencia_de(plataforma: str) -> float:
    return LATENCIA_S.get(plataforma, LATENCIA_S["otra"])


def calcular_tramo(sondeo: dict, a_reloj: float, b_reloj: float, plataforma: str,
                   pad: float = PAD_ALTA_S, ahora: float | None = None) -> dict:
    """Tramo a pedir a la plataforma, en segundos desde el inicio de su lista, y si es posible.

    Devuelve {"ok", "motivo", "desde", "hasta", "inicio_ventana", "fin_ventana"}. `a_reloj` y `b_reloj`
    son la hora de reloj de grabación del tramo; se les resta la latencia de la plataforma.
    """
    ahora = time.time() if ahora is None else ahora
    inicio, duracion = sondeo["inicio"], sondeo["duracion"]
    fin = inicio + duracion
    a_emision, b_emision = a_reloj - latencia_de(plataforma), b_reloj - latencia_de(plataforma)
    base = {"inicio_ventana": inicio, "fin_ventana": fin, "ok": False, "motivo": None, "desde": 0.0, "hasta": 0.0}
    if b_emision > fin + 2:
        base["motivo"] = "El tramo aún no está disponible en la plataforma. Prueba en unos minutos."
        return base
    if a_emision - 2 < inicio:
        base["motivo"] = ("La plataforma ya no conserva el principio de ese tramo (solo guarda los últimos "
                          f"{int(duracion // 60)} min del directo).")
        return base
    desde = max(0.0, a_emision - pad - inicio)
    hasta = min(duracion, b_emision + pad - inicio)
    return {**base, "ok": True, "desde": round(desde, 2), "hasta": round(hasta, 2),
            "t0": inicio + desde, "t1": inicio + hasta, "a_emision": a_emision, "b_emision": b_emision}


def decidir_opciones(buffer_alto: int | None, sondeo: dict | None, tramo: dict | None = None) -> dict:
    """Qué opciones de calidad se ofrecen para un tramo.

    `sondeo` es el resultado de `sondear_plataforma` (o None si no se pudo consultar) y `tramo` el de
    `calcular_tramo`. El búfer siempre se ofrece. La alta calidad solo si la plataforma lo permite
    y mejora lo que ya hay en el búfer.
    """
    buffer = {"disponible": True, "alto": buffer_alto}
    if sondeo is None:
        alta = {"disponible": False, "motivo": "No se pudo consultar a la plataforma.", "alturas": []}
    elif not sondeo.get("ok"):
        alta = {"disponible": False, "motivo": sondeo.get("motivo") or "La plataforma no permite pedir ese tramo.", "alturas": []}
    else:
        alturas = sorted({a for a in sondeo.get("alturas", []) if a >= 360 and a <= 1080 and (buffer_alto is None or a > buffer_alto)}, reverse=True)
        if not alturas:
            alta = {"disponible": False, "alturas": [],
                    "motivo": "El búfer ya tiene la mayor calidad que ofrece la plataforma."}
        elif tramo is not None and not tramo.get("ok"):
            alta = {"disponible": False, "motivo": tramo.get("motivo") or "Ese tramo no está disponible.", "alturas": alturas}
        else:
            alta = {"disponible": True, "motivo": None, "alturas": alturas}
    return {"buffer": buffer, "alta": alta}


# ---------- alineación por audio ----------

def desplazamiento_audio(ref, largo, hz: int = AUDIO_HZ) -> tuple[float, float, float]:
    """Busca `ref` (audio del búfer) dentro de `largo` (audio descargado).

    Devuelve (posición en segundos donde empieza `ref` dentro de `largo`, puntuación 0..1,
    puntuación del mejor candidato alternativo). Correlación cruzada normalizada con FFT.
    """
    import numpy as np

    ref = np.asarray(ref, dtype=np.float64)
    largo = np.asarray(largo, dtype=np.float64)
    n, m = len(ref), len(largo)
    if n < hz or m < n:
        return 0.0, 0.0, 0.0
    ref = ref - ref.mean()
    energia_ref = float(np.sqrt(np.sum(ref * ref)))
    if energia_ref < 1e-6:
        return 0.0, 0.0, 0.0
    tam = 1 << int(np.ceil(np.log2(n + m)))
    cruzada = np.fft.irfft(np.fft.rfft(largo, tam) * np.conj(np.fft.rfft(ref, tam)), tam)[: m - n + 1]
    cuadrados = np.concatenate(([0.0], np.cumsum(largo * largo)))
    suma = np.concatenate(([0.0], np.cumsum(largo)))
    energia = cuadrados[n:] - cuadrados[:-n]
    media = (suma[n:] - suma[:-n]) / n
    # Varianza de cada ventana: sum(x^2) - n*media^2
    var = np.maximum(energia - n * media * media, 1e-9)
    puntos = cruzada / (np.sqrt(var) * energia_ref)
    mejor = int(np.argmax(puntos))
    score = float(puntos[mejor])
    margen = int(0.5 * hz)
    resto = np.concatenate((puntos[: max(0, mejor - margen)], puntos[mejor + margen + 1:]))
    segundo = float(resto.max()) if len(resto) else 0.0
    return mejor / hz, score, segundo


def alineado_fiable(score: float, segundo: float) -> bool:
    return score >= MIN_SCORE_ALINEAR and segundo <= 0.9 * score


def leer_audio_pcm(ruta: Path, hz: int = AUDIO_HZ, ss: float | None = None, t: float | None = None,
                   entrada_extra: list[str] | None = None):
    """Audio mono de un archivo (o lista concat) como vector float32, vía FFmpeg por stdout."""
    import numpy as np

    cmd = [media.herramienta("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error"]
    cmd += entrada_extra or []
    cmd += ["-i", str(ruta)]
    if ss:
        cmd += ["-ss", f"{ss:.3f}"]
    if t:
        cmd += ["-t", f"{t:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(hz), "-f", "s16le", "pipe:1"]
    res = subprocess.run(cmd, capture_output=True, creationflags=media._SIN_VENTANA, timeout=300)
    if res.returncode != 0 or not res.stdout:
        raise ErrorMedia("No se pudo leer el audio para alinear el clip.")
    return np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def desfase_audio(ruta: Path) -> float:
    """Segundos entre el inicio del archivo (primer flujo) y la primera muestra de audio.

    El audio leído por stdout empieza en su primera muestra; el corte con `-ss` cuenta desde el
    primer instante del archivo. Esta diferencia convierte una posición de uno en la del otro.
    """
    import json

    res = subprocess.run(
        [media.herramienta("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", str(ruta)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=media._SIN_VENTANA)
    try:
        flujos = json.loads(res.stdout or "{}").get("streams", [])
        inicios = [float(x["start_time"]) for x in flujos if x.get("start_time") not in (None, "N/A")]
        audio = next(float(x["start_time"]) for x in flujos
                     if x.get("codec_type") == "audio" and x.get("start_time") not in (None, "N/A"))
        return max(0.0, audio - min(inicios))
    except (ValueError, StopIteration, KeyError):
        return 0.0


# ---------- consulta a la plataforma (red) ----------

def plataforma_de(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith(("youtube.com", "youtu.be")):
        return "youtube"
    if host.endswith("twitch.tv"):
        return "twitch"
    if host.endswith("kick.com"):
        return "kick"
    return "otra"


def _canal(url: str) -> str:
    partes = [p for p in urlparse(url).path.split("/") if p]
    return partes[0] if partes else ""


def _opciones_consulta(extra: dict | None = None) -> dict:
    opciones: dict = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "socket_timeout": 20, "retries": 2, "ignore_no_formats_error": True,
    }
    if node := config.find_tool("node"):
        opciones["js_runtimes"] = {"node": {"path": node}}
    if config.YTDLP_COOKIES_BROWSER:
        opciones["cookiesfrombrowser"] = (config.YTDLP_COOKIES_BROWSER,)
    opciones.update(extra or {})
    return opciones


def _extraer(url: str, **extra) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL(_opciones_consulta(extra)) as ydl:
        info = ydl.extract_info(url, download=False)
    return info or {}


def _formatos_hls(info: dict) -> list[dict]:
    return [f for f in info.get("formats") or [] if str(f.get("protocol") or "").startswith("m3u8") and f.get("url")]


def _leer_lista_hls(formato: dict, cabeceras: dict) -> dict:
    from urllib.request import Request, urlopen

    req = Request(formato["url"], headers={**cabeceras, **(formato.get("http_headers") or {})})
    with urlopen(req, timeout=20) as r:  # noqa: S310 - URL de CDN devuelta por yt-dlp
        return parsear_hls(r.read(8 * 1024 * 1024).decode("utf-8", "replace"))


def _ventana_de(info: dict) -> tuple[dict | None, list[int], str | None]:
    """(ventana HLS {inicio, duracion}, alturas, motivo si no hay) de un resultado de yt-dlp."""
    hls = _formatos_hls(info)
    if not hls:
        return None, [], "La plataforma no entrega este directo en un formato que permita pedir tramos."
    alturas = sorted({int(f["height"]) for f in hls if f.get("height")}, reverse=True)
    ligero = min((f for f in hls if f.get("height")), key=lambda f: f["height"], default=hls[0])
    ventana = _leer_lista_hls(ligero, info.get("http_headers") or {})
    if ventana["inicio"] is None:
        marca = info.get("timestamp")
        if not marca or not info.get("is_live"):
            return None, alturas, "La plataforma no indica la hora del video, así que no se puede alinear el tramo."
        ventana = {**ventana, "inicio": float(marca), "duracion": time.time() - float(marca)}
    if ventana["duracion"] < 20:
        return None, alturas, "La plataforma guarda muy poco directo hacia atrás (no permite retroceder)."
    return ventana, alturas, None


def sondear_plataforma(url: str) -> dict:
    """Consulta (sin descargar) si la plataforma permite pedir tramos del pasado del directo.

    Devuelve {"plataforma", "ok", "motivo", "url", "inicio", "duracion", "alturas"}. Nunca lanza:
    los fallos se resumen en `motivo` con lenguaje claro.
    """
    plataforma = plataforma_de(url)
    res = {"plataforma": plataforma, "ok": False, "motivo": None, "url": url, "inicio": None, "duracion": 0.0, "alturas": []}
    try:
        if plataforma == "youtube":
            info = _extraer(url)
            if info.get("live_status") != "is_live":
                res["motivo"] = "Este directo no está en curso ahora mismo."
                return res
            ventana, alturas, motivo = _ventana_de(info)
            res["url"] = info.get("webpage_url") or url
            if ventana is None:
                res["motivo"] = motivo
                return res
        elif plataforma in ("twitch", "kick"):
            canal = _canal(url)
            if not canal:
                res["motivo"] = "No se reconoce el canal en el enlace."
                return res
            en_vivo = _extraer(f"https://{'www.twitch.tv' if plataforma == 'twitch' else 'kick.com'}/{canal}")
            if not (en_vivo.get("is_live") or en_vivo.get("live_status") == "is_live"):
                res["motivo"] = "El canal no está en directo ahora mismo."
                return res
            vod = _buscar_vod(plataforma, canal, en_vivo.get("timestamp") or en_vivo.get("release_timestamp"))
            if vod is None:
                res["motivo"] = ("Este canal no guarda VOD del directo (o el VOD aún no está disponible). "
                                 "Solo se puede usar el búfer.")
                return res
            ventana, alturas, motivo = _ventana_de(vod)
            res["url"] = vod.get("webpage_url") or vod.get("original_url") or url
            if ventana is None:
                res["motivo"] = motivo
                return res
        else:
            res["motivo"] = "Esta plataforma no permite pedir tramos anteriores del directo."
            return res
        res.update(ok=True, inicio=ventana["inicio"], duracion=ventana["duracion"], alturas=alturas)
        return res
    except Exception as exc:  # noqa: BLE001 - se explica en lenguaje claro
        log.info("No se pudo consultar la alta calidad de %s: %s", plataforma, exc)
        res["motivo"] = f"No se pudo consultar a la plataforma: {importer._mensaje(exc)}"[:200]
        return res


def _buscar_vod(plataforma: str, canal: str, inicio_directo: float | None) -> dict | None:
    """VOD en curso del canal (el que corresponde al directo actual), con sus formatos."""
    if plataforma == "twitch":
        lista = f"https://www.twitch.tv/{canal}/videos?filter=archives&sort=time"
    else:
        lista = f"https://kick.com/{canal}/videos"
    plano = _extraer(lista, extract_flat="in_playlist", playlistend=3)
    for entrada in (plano.get("entries") or [])[:3]:
        url = entrada.get("url") or entrada.get("webpage_url")
        if not url:
            continue
        info = _extraer(url)
        if not (info.get("is_live") or info.get("live_status") == "is_live"):
            continue
        marca = info.get("timestamp")
        if inicio_directo and marca and abs(float(marca) - float(inicio_directo)) > 600:
            continue
        return info
    return None


# ---------- descarga del tramo ----------

_ETIQUETAS_SEGMENTO = ("#EXTINF:", "#EXT-X-BYTERANGE:", "#EXT-X-DISCONTINUITY")


def _absolutizar_uri(linea: str, base: str) -> str:
    """Convierte a absoluto el URI="..." de una etiqueta (EXT-X-MAP, EXT-X-KEY)."""
    from urllib.parse import urljoin

    return re.sub(r'URI="([^"]*)"', lambda m: f'URI="{urljoin(base, m.group(1))}"', linea)


def recortar_lista_hls(texto: str, base_url: str, t0: float, t1: float, inicio: float | None = None) -> dict | None:
    """Lista HLS local con solo los segmentos que cubren [t0, t1] (hora de reloj, epoch).

    Cada segmento recibe su hora de reloj de EXT-X-PROGRAM-DATE-TIME (o, si la lista no la trae,
    de `inicio` más las duraciones acumuladas). Los URI se hacen absolutos para poder leer la
    lista desde un archivo local. Devuelve {"texto", "inicio", "fin", "segmentos"} o None si
    ningún segmento cae en ese tramo.

    Por qué no `-ss` sobre la lista remota: en un directo la ventana se desplaza y el video y el
    audio de YouTube son listas distintas que empiezan en segmentos distintos (5 s de diferencia
    comprobada), así que el mismo `-ss` sacaba video y audio de momentos diferentes.
    """
    from urllib.parse import urljoin

    reloj, mapa, llave, pendientes = inicio, None, None, []
    elegidos: list[tuple[float, float, list[str], str | None, str | None]] = []
    for crudo in (texto or "").splitlines():
        linea = crudo.strip()
        if not linea:
            continue
        if linea.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            marca = _epoch_iso(linea.split(":", 1)[1])
            if marca is not None:
                reloj = marca
        elif linea.startswith("#EXT-X-MAP:"):
            mapa = _absolutizar_uri(linea, base_url)
        elif linea.startswith("#EXT-X-KEY:"):
            llave = _absolutizar_uri(linea, base_url)
        elif linea.startswith(_ETIQUETAS_SEGMENTO):
            pendientes.append(linea)
        elif not linea.startswith("#"):
            duracion = 0.0
            for etiqueta in pendientes:
                if etiqueta.startswith("#EXTINF:"):
                    try:
                        duracion = float(etiqueta[8:].split(",", 1)[0])
                    except ValueError:
                        duracion = 0.0
            if reloj is not None and duracion > 0 and reloj + duracion > t0 and reloj < t1:
                elegidos.append((reloj, reloj + duracion, pendientes + [urljoin(base_url, linea)], mapa, llave))
            if reloj is not None:
                reloj += duracion
            pendientes = []
    if not elegidos:
        return None
    anchos = max(1, int(max(e[1] - e[0] for e in elegidos) + 1))
    lineas = ["#EXTM3U", "#EXT-X-VERSION:6", f"#EXT-X-TARGETDURATION:{anchos}", "#EXT-X-MEDIA-SEQUENCE:0"]
    mapa_actual = llave_actual = None
    for _, _, bloque, m, k in elegidos:
        if k and k != llave_actual:
            lineas.append(k)
            llave_actual = k
        if m and m != mapa_actual:
            lineas.append(m)
            mapa_actual = m
        lineas += bloque
    lineas.append("#EXT-X-ENDLIST")
    return {"texto": "\n".join(lineas) + "\n", "inicio": elegidos[0][0], "fin": elegidos[-1][1], "segmentos": len(elegidos)}


def _mensaje_descarga(exc: BaseException) -> str:
    bajo = str(exc).lower()
    if any(x in bajo for x in ("getaddrinfo", "timed out", "timeout", "connection", "network is unreachable", "resolve")):
        return "Sin conexión: no se pudo descargar el tramo en alta calidad."
    if any(x in bajo for x in ("403", "429", "forbidden", "too many requests", "sign in", "subscriber", "login")):
        return "La plataforma rechazó la descarga del tramo (acceso restringido o demasiadas peticiones)."
    return f"No se pudo descargar el tramo en alta calidad: {importer._mensaje(exc)}"[:300]


def _resolver_flujos(url: str, altura: int) -> list[dict]:
    """Formatos HLS (video y audio, o uno solo con ambos) para esa altura, sin descargar nada."""
    info = _extraer(url, format=f"bv*[height<={altura}]+ba/b[height<={altura}]/b", ignore_no_formats_error=False)
    formatos = info.get("requested_formats") or ([info] if info.get("url") else [])
    flujos = []
    for f in formatos:
        if not str(f.get("protocol") or "").startswith("m3u8") or not f.get("url"):
            raise ErrorMedia("La plataforma no entrega este tramo en un formato descargable por segmentos.")
        flujos.append({"url": f["url"], "cabeceras": {**(info.get("http_headers") or {}), **(f.get("http_headers") or {})},
                       "video": f.get("vcodec") not in (None, "none"), "audio": f.get("acodec") != "none"})   # acodec None = no declarado (audio de YouTube)
    if not flujos:
        raise ErrorMedia("La plataforma no ofrece esa calidad para este tramo.")
    return flujos


def descargar_tramo_hls(url: str, altura: int, t0: float, t1: float, destino: Path, cancel: Cancelacion,
                        progreso: Callable[[float], None] | None = None, inicio_vod: float | None = None) -> tuple[Path, float]:
    """Descarga solo los segmentos de [t0, t1] (hora de reloj) de la lista HLS de la plataforma, con audio.

    Resuelve los formatos con yt-dlp (sin descargar) y lee solo los segmentos necesarios con FFmpeg
    (sin recodificar), uniendo video y audio en un archivo. Devuelve (archivo, hora de reloj en
    que empieza el archivo). Cada formato usa su propia lista: ver `recortar_lista_hls`.
    """
    from urllib.request import Request, urlopen

    destino.mkdir(parents=True, exist_ok=True)
    importer.comprobar_destino_publico(url)
    cancel.comprobar()
    try:
        flujos = _resolver_flujos(url, altura)
        cancel.comprobar()
        recortadas = []
        for flujo in flujos:
            req = Request(flujo["url"], headers=flujo["cabeceras"])
            with urlopen(req, timeout=20) as r:  # noqa: S310 - URL de CDN devuelta por yt-dlp
                texto = r.read(16 * 1024 * 1024).decode("utf-8", "replace")
            corte = recortar_lista_hls(texto, flujo["url"], t0, t1, inicio_vod)
            if corte is None:
                raise ErrorMedia("Ese tramo ya no está (o aún no está) en la lista de la plataforma.")
            recortadas.append(corte)
    except (Cancelado, ErrorMedia):
        raise
    except Exception as exc:  # noqa: BLE001 - se explica en lenguaje claro
        raise ErrorMedia(_mensaje_descarga(exc)) from exc
    # Todas las pistas empiezan en el mismo instante: el más tardío de los primeros segmentos.
    comun = max(c["inicio"] for c in recortadas)
    entradas: list[str] = []
    for k, (flujo, corte) in enumerate(zip(flujos, recortadas)):
        lista = destino / f"lista{k}.m3u8"
        lista.write_text(corte["texto"], encoding="utf-8")
        # Sin "-headers": con una lista local FFmpeg no lo admite y los segmentos de estas CDN son URL firmadas.
        entradas += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto,data", "-rw_timeout", "20000000"]
        if comun - corte["inicio"] > 0.01:
            entradas += ["-ss", f"{comun - corte['inicio']:.3f}"]
        entradas += ["-i", str(lista)]
    mapas = []
    for k, flujo in enumerate(flujos):
        if flujo["video"]:
            mapas += ["-map", f"{k}:v:0"]
        if flujo["audio"]:
            mapas += ["-map", f"{k}:a:0"]
    salida = destino / "alta.mkv"
    esperado = max(1.0, min(c["fin"] for c in recortadas) - comun)
    try:
        media.ejecutar_ffmpeg([*entradas, *mapas, "-c", "copy", "-f", "matroska", str(salida)], esperado, cancel, progreso)
    except ErrorMedia as exc:
        raise ErrorMedia(_mensaje_descarga(exc)) from exc
    if not salida.is_file() or salida.stat().st_size == 0:
        raise ErrorMedia("La descarga terminó pero no se encontró el archivo de video.")
    return salida, comun
