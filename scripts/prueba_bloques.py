"""Prueba la transcripcion por bloques y la reanudacion con un video largo.

Repite el video de prueba hasta superar los 30 minutos (dos bloques), transcribe,
interrumpe a mitad del segundo bloque y comprueba que al reintentar se continua desde el
primer bloque ya guardado y que el resultado no tiene huecos ni palabras desordenadas.

Uso:  uv run python scripts/prueba_bloques.py RUTA_VIDEO_CORTO
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipstudio import config, media, suggest, transcribe  # noqa: E402
from clipstudio.media import Cancelacion, Cancelado  # noqa: E402

fallas = 0


def comprobar(condicion: bool, texto: str) -> None:
    global fallas
    fallas += 0 if condicion else 1
    print(("  [OK]    " if condicion else "  [FALLA] ") + texto, flush=True)


def main() -> int:
    corto = Path(sys.argv[1])
    carpeta = config.DATA_DIR / "pruebas" / "bloques"
    carpeta.mkdir(parents=True, exist_ok=True)
    wav, parcial = carpeta / "largo.wav", carpeta / "parcial.json"
    parcial.unlink(missing_ok=True)
    duracion_corto = media.sondear(corto)["duracion"]
    repeticiones = int(transcribe.BLOQUE_S * 1.25 // duracion_corto) + 1
    subprocess.run(
        [media.herramienta("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-stream_loop", str(repeticiones - 1),
         "-i", str(corto), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
        check=True,
    )
    total = media.sondear_audio(wav)
    duracion_corto = total / repeticiones  # la pista de audio es algo mas corta que la de video
    print(f"Audio de prueba: {total / 60:.1f} min ({repeticiones} repeticiones)")

    avisos: list[str] = []
    # 1. Se interrumpe cuando el progreso pasa del 90 % (ya dentro del segundo bloque).
    cancel = Cancelacion()
    t0 = time.time()
    try:
        transcribe.transcribir(wav, total, "es", cancel, lambda f: f > 0.9 and cancel.cancelar(), avisos.append, parcial)
        comprobar(False, "La transcripcion debia interrumpirse")
    except Cancelado:
        pass
    t_primera = time.time() - t0
    comprobar(any("bloque 1 de 2" in a for a in avisos) and any("bloque 2 de 2" in a for a in avisos),
              f"El aviso informa del bloque en curso: {[a for a in avisos if 'bloque' in a]}")
    comprobar(parcial.is_file(), "Tras interrumpir queda guardado el avance")
    guardado = json.loads(parcial.read_text(encoding="utf-8"))
    corte = guardado["hasta"] / transcribe.FRECUENCIA
    comprobar(abs(corte - transcribe.BLOQUE_S) <= transcribe.BUSQUEDA_S + 1,
              f"El primer bloque se corto en {corte:.1f} s (objetivo {transcribe.BLOQUE_S} s, dentro de la ventana de busqueda)")

    # 2. Al reintentar se reanuda desde el bloque guardado.
    avisos.clear()
    t0 = time.time()
    r = transcribe.transcribir(wav, total, "es", Cancelacion(), lambda f: None, avisos.append, parcial)
    t_segunda = time.time() - t0
    comprobar(not any("bloque 1 de 2" in a for a in avisos), "Al reintentar no se repite el primer bloque")
    comprobar(t_segunda < t_primera * 0.6, f"La reanudacion tarda menos ({t_segunda:.0f} s frente a {t_primera:.0f} s hasta la interrupcion)")
    comprobar(not parcial.exists(), "El archivo de avance se borra al terminar")

    # 3. El resultado es continuo.
    palabras = [p for s in r["segmentos"] for p in s["palabras"]]
    comprobar(all(a["inicio"] <= b["inicio"] + 0.01 for a, b in zip(palabras, palabras[1:])), "Las palabras estan en orden temporal")
    comprobar(palabras[-1]["fin"] > total - 15, f"La transcripcion llega al final ({palabras[-1]['fin']:.0f} de {total:.0f} s)")
    cerca = [p for p in palabras if abs(p["inicio"] - corte) < 20]
    hueco = max((b["inicio"] - a["fin"] for a, b in zip(cerca, cerca[1:])), default=99)
    comprobar(len(cerca) > 20 and hueco < 4, f"No hay hueco alrededor del corte entre bloques (pausa maxima {hueco:.1f} s)")
    por_repeticion = len(palabras) / repeticiones
    primera = len([p for p in palabras if p["fin"] <= duracion_corto])
    comprobar(abs(por_repeticion - primera) / primera < 0.08,
              f"No se pierden ni duplican palabras: {por_repeticion:.0f} por repeticion frente a {primera} en la primera")
    frases = suggest.partir_en_frases(r["segmentos"])
    partes = suggest.dividir(r["segmentos"], total, 30)
    comprobar(len(partes) >= total / 40, f"Dividir el video largo: {len(partes)} partes de ~30 s; {len(frases)} frases; {len(r['picos'])} picos de volumen")
    wav.unlink(missing_ok=True)
    print("Todo correcto." if not fallas else f"{fallas} comprobacion(es) fallida(s).")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
