"""Transcripcion local con faster-whisper (tiempos por palabra), por bloques.

El audio se procesa en bloques de unos 30 minutos cortados en el momento mas silencioso
cercano al limite, de modo que no se parte una palabra. Asi un directo de muchas horas no
se carga entero en memoria, el progreso se ve por bloque y, si algo falla, al reintentar
se continua desde el ultimo bloque terminado.

De paso se mide el volumen por segundo para localizar picos (gritos, risas, sobresaltos).
"""

from __future__ import annotations

import json
import threading
import wave
from pathlib import Path
from typing import Callable

from . import config
from .media import Cancelacion, ErrorMedia

FRECUENCIA = 16000
VERSION_PARCIAL = 2         # cambia si cambia el formato del archivo de avance
BLOQUE_S = 30 * 60          # duracion objetivo de cada bloque
BUSQUEDA_S = 30             # ventana antes del limite donde se busca el silencio para cortar
RESTO_MIN_S = 90            # si queda menos que esto, se une al bloque actual

_modelo = None
_modelo_clave: tuple | None = None
_lock = threading.Lock()


def _cargar_modelo():
    """Carga (y descarga la primera vez) el modelo. Se reutiliza entre trabajos."""
    global _modelo, _modelo_clave
    clave = (config.WHISPER_MODEL, config.WHISPER_DEVICE, config.WHISPER_COMPUTE)
    with _lock:
        if _modelo is None or _modelo_clave != clave:
            try:
                from faster_whisper import WhisperModel

                _modelo = WhisperModel(
                    config.WHISPER_MODEL,
                    device=config.WHISPER_DEVICE,
                    compute_type=config.WHISPER_COMPUTE,
                    download_root=str(config.MODELS_DIR),
                )
            except Exception as exc:
                raise ErrorMedia(
                    f"No se pudo cargar el modelo de transcripcion '{config.WHISPER_MODEL}'. "
                    "La primera vez se descarga de internet: revisa tu conexion. "
                    f"Detalle: {exc}"
                ) from exc
            _modelo_clave = clave
        return _modelo


def _leer_tramo(w: wave.Wave_read, desde: int, cuantos: int):
    """Lee `cuantos` cuadros desde `desde` como muestras float32 en [-1, 1]."""
    import numpy as np

    w.setpos(desde)
    return np.frombuffer(w.readframes(cuantos), dtype=np.int16).astype(np.float32) / 32768.0


def _punto_de_corte(muestras, objetivo: int) -> int:
    """Indice (en muestras) del tramo mas silencioso en los ultimos BUSQUEDA_S antes de `objetivo`."""
    import numpy as np

    paso = FRECUENCIA // 5  # ventanas de 0,2 s
    desde = max(0, objetivo - BUSQUEDA_S * FRECUENCIA)
    zona = muestras[desde:objetivo]
    n = len(zona) // paso
    if n < 2:
        return objetivo
    energia = np.sqrt(np.mean(zona[: n * paso].reshape(n, paso) ** 2, axis=1))
    return desde + int(np.argmin(energia)) * paso + paso // 2


def volumen_por_segundo(muestras) -> list[float]:
    """Nivel RMS en dB de cada segundo (minimo -80)."""
    import numpy as np

    n = len(muestras) // FRECUENCIA
    if n == 0:
        return []
    rms = np.sqrt(np.mean(muestras[: n * FRECUENCIA].reshape(n, FRECUENCIA) ** 2, axis=1))
    return [round(float(x), 1) for x in 20 * np.log10(np.maximum(rms, 1e-4))]


def _anotar_volumen(db: list[float], muestras, inicio: int) -> None:
    """Anade a `db` el volumen de los segundos ABSOLUTOS completos de este bloque.

    `db[i]` es siempre el segundo i del video. Como los bloques no empiezan en un segundo
    exacto, se descarta la fraccion inicial y el segundo partido entre dos bloques se
    rellena con el valor anterior; asi los tiempos no se desplazan en videos largos.
    """
    primero = -(-inicio // FRECUENCIA)                  # primer segundo completo del bloque
    salto = primero * FRECUENCIA - inicio
    while len(db) < primero:
        db.append(db[-1] if db else -80.0)
    db.extend(volumen_por_segundo(muestras[salto:]))


def detectar_picos(db: list[float], maximo: int = 200) -> list[dict]:
    """Segundos cuyo volumen sobresale del entorno: [{t, exceso_db}].

    Un pico es un segundo al menos 9 dB por encima de la mediana del minuto y medio que lo
    rodea, que ademas esta entre el 15 % mas alto del video. Detecta gritos, risas o golpes
    de sonido; no sabe si el momento es interesante.
    """
    import numpy as np

    if len(db) < 20:
        return []
    arr = np.asarray(db, dtype=np.float32)
    umbral_global = max(float(np.percentile(arr, 85)), -35.0)
    radio = 45
    candidatos = []
    for i, valor in enumerate(arr):
        if valor < umbral_global:
            continue
        entorno = arr[max(0, i - radio): i + radio + 1]
        exceso = float(valor - np.median(entorno))
        if exceso >= 9.0:
            candidatos.append((i, exceso))
    # Picos a menos de 4 s se consideran el mismo momento: queda el mas fuerte.
    picos: list[tuple[int, float]] = []
    for i, exceso in candidatos:
        if picos and i - picos[-1][0] <= 4:
            if exceso > picos[-1][1]:
                picos[-1] = (i, exceso)
        else:
            picos.append((i, exceso))
    picos.sort(key=lambda p: p[1], reverse=True)
    return sorted(({"t": float(i) + 0.5, "exceso_db": round(e, 1)} for i, e in picos[:maximo]), key=lambda p: p["t"])


def _transcribir_bloque(modelo, muestras, desfase: float, idioma: str | None, cancel: Cancelacion, avance):
    """Transcribe un bloque y devuelve (segmentos con tiempos absolutos, idioma detectado)."""
    segmentos_iter, info = modelo.transcribe(
        muestras,
        language=idioma,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        beam_size=5,
        condition_on_previous_text=False,
    )
    segmentos = []
    for seg in segmentos_iter:
        cancel.comprobar()
        palabras = [
            {"inicio": round(desfase + float(p.start), 3), "fin": round(desfase + float(p.end), 3), "texto": p.word.strip()}
            for p in (seg.words or [])
            if p.word.strip()
        ]
        texto = seg.text.strip()
        if not palabras and texto:
            palabras = _repartir_palabras(texto, desfase + float(seg.start), desfase + float(seg.end))
        if texto:
            segmentos.append(
                {"inicio": round(desfase + float(seg.start), 3), "fin": round(desfase + float(seg.end), 3),
                 "texto": texto, "palabras": palabras}
            )
        avance(float(seg.end))
    return segmentos, info.language


def transcribir(
    audio: Path,
    duracion: float,
    idioma: str,
    cancel: Cancelacion,
    progreso: Callable[[float], None],
    aviso: Callable[[str], None] | None = None,
    parcial: Path | None = None,
    identidad: str = "",
) -> dict:
    """Devuelve {'idioma', 'segmentos': [{inicio, fin, texto, palabras}], 'picos': [{t, exceso_db}]}.

    `parcial` es un archivo donde se guarda el avance tras cada bloque para poder reanudar;
    solo se reutiliza si coincide `identidad` (tamano y fecha del video de origen), ademas
    del modelo, el idioma y la longitud del audio.
    `duracion` se ignora (se toma del propio audio); se mantiene por compatibilidad.
    """
    decir = aviso or (lambda _m: None)
    decir(f"Cargando modelo de transcripcion ({config.WHISPER_MODEL})...")
    modelo = _cargar_modelo()
    cancel.comprobar()
    idioma_pedido = None if idioma in ("", "auto") else idioma

    try:
        w = wave.open(str(audio), "rb")
    except (wave.Error, OSError) as exc:
        raise ErrorMedia("No se pudo leer el audio extraido del video.") from exc
    with w:
        if w.getnchannels() != 1 or w.getframerate() != FRECUENCIA or w.getsampwidth() != 2:
            raise ErrorMedia("El audio extraido no tiene el formato esperado (mono, 16 kHz, 16 bits).")
        total = w.getnframes()
        clave = [VERSION_PARCIAL, config.WHISPER_MODEL, idioma_pedido, total, identidad]
        estado = {"clave": clave, "hasta": 0, "bloques": 0, "idioma": idioma_pedido, "segmentos": [], "db": []}
        if parcial and parcial.is_file():
            try:
                previo = json.loads(parcial.read_text(encoding="utf-8"))
                if previo.get("clave") == clave and 0 < previo.get("hasta", 0) <= total:
                    estado = previo
            except (ValueError, OSError):
                pass  # avance ilegible: se empieza de cero

        # Mismo criterio que el bucle: el resto corto se une al ultimo bloque.
        n_bloques = max(1, -(-(total / FRECUENCIA - RESTO_MIN_S) // BLOQUE_S))
        n_bloques = int(n_bloques)
        try:
            while estado["hasta"] < total:
                cancel.comprobar()
                inicio = estado["hasta"]
                restante = total - inicio
                objetivo = BLOQUE_S * FRECUENCIA
                if restante <= objetivo + RESTO_MIN_S * FRECUENCIA:
                    muestras = _leer_tramo(w, inicio, restante)
                else:
                    muestras = _leer_tramo(w, inicio, objetivo)
                    muestras = muestras[: _punto_de_corte(muestras, objetivo)]
                if len(muestras) == 0:
                    # Audio truncado: declara mas muestras de las que tiene. Sin esto no habria avance.
                    raise ErrorMedia("El audio extraido esta incompleto. Reintenta el proyecto.")
                desfase = inicio / FRECUENCIA
                numero = estado["bloques"] + 1
                n_bloques = max(n_bloques, numero)
                decir(
                    "Transcribiendo el audio..." if n_bloques == 1
                    else f"Transcribiendo el audio (bloque {numero} de {n_bloques})..."
                )
                segmentos, detectado = _transcribir_bloque(
                    modelo, muestras, desfase, estado["idioma"], cancel,
                    lambda seg_fin, d=desfase: progreso(min(1.0, (d * FRECUENCIA + seg_fin * FRECUENCIA) / total)),
                )
                estado["segmentos"].extend(segmentos)
                estado["bloques"] = numero
                _anotar_volumen(estado["db"], muestras, inicio)
                # El idioma detectado en el primer bloque se mantiene en los siguientes.
                estado["idioma"] = estado["idioma"] or detectado
                estado["hasta"] = inicio + len(muestras)
                progreso(min(1.0, estado["hasta"] / total))
                if parcial and estado["hasta"] < total:
                    tmp = parcial.with_suffix(".tmp")
                    tmp.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(parcial)
        except ErrorMedia:
            raise
        except Exception as exc:
            if cancel.activa:
                raise
            raise ErrorMedia(f"La transcripcion fallo: {exc}") from exc

    if parcial:
        parcial.unlink(missing_ok=True)
    return {"idioma": estado["idioma"], "segmentos": estado["segmentos"], "picos": detectar_picos(estado["db"])}


def _repartir_palabras(texto: str, inicio: float, fin: float) -> list[dict]:
    """Respaldo si el modelo no devuelve tiempos por palabra: reparto uniforme."""
    trozos = texto.split()
    if not trozos:
        return []
    paso = max(0.01, (fin - inicio) / len(trozos))
    return [
        {"inicio": round(inicio + i * paso, 3), "fin": round(inicio + (i + 1) * paso, 3), "texto": t}
        for i, t in enumerate(trozos)
    ]
