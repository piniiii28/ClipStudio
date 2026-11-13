"""Regresión de interfaz real con Chromium; requiere pip install playwright y FFmpeg.
Ejecutar desde raíz: .venv/bin/python tests/browser/workflows.py
Datos temporales aislados; no consulta plataformas ni descarga modelos.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    with tempfile.TemporaryDirectory(prefix="clipstudio-browser-") as carpeta:
        os.environ["CLIPSTUDIO_DATA_DIR"] = carpeta
        os.environ["CLIPSTUDIO_BUSCAR_ACTUALIZACIONES"] = "0"
        from clipstudio import api, db, pipeline, vivo
        import uvicorn
        from playwright.sync_api import sync_playwright, expect

        db.iniciar()
        proyecto = db.insertar("proyectos", {"nombre": "Prueba navegador", "origen": "archivo", "estado": "listo", "duracion": 12, "ancho": 320, "alto": 180})
        pid = proyecto["id"]
        trabajo = pipeline.carpeta_proyecto(pid)
        trabajo.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=10", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(trabajo / "proxy.mp4")], check=True)
        frases = [{"inicio": 0, "fin": 2, "texto": "Inicio tranquilo."}, {"inicio": 8, "fin": 10, "texto": "Acción lejana."}]
        segmentos = [{**f, "palabras": [{"inicio": f["inicio"], "fin": f["fin"], "texto": f["texto"]}]} for f in frases]
        (trabajo / "transcripcion.json").write_text(json.dumps({"idioma": "es", "segmentos": segmentos}))
        original = pipeline._nuevo_clip(proyecto, segmentos, pipeline.preferencias_clip(), 0, 3, "Clip original", "manual", [], detectar_rostro=False)
        fila = db.insertar("sesiones_vivo", {"url": "https://twitch.tv/prueba", "estado": "grabando"})
        sesion = vivo.Sesion(fila["id"], fila["url"])
        sesion.estado = "grabando"
        sesion.segmentos = [vivo.Seg("dummy.ts", 30, 60, 100)]
        sesion.momentos = [{"id": "caducado", "tiempo": 10, "motivo": "Momento antiguo", "estado": "nuevo", "origen": "audio", "proyecto_id": None}]
        vivo._sesion = sesion
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            puerto = sock.getsockname()[1]
        servidor = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=puerto, lifespan="off", log_level="error"))
        hilo = threading.Thread(target=servidor.run, daemon=True)
        hilo.start()
        try:
            for _ in range(100):
                if servidor.started:
                    break
                time.sleep(.05)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium"), headless=True, args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errores = []
                page.on("pageerror", lambda e: errores.append(str(e)))
                page.goto(f"http://127.0.0.1:{puerto}/#/p/{pid}")
                page.get_by_role("tab", name="Transcripción", exact=True).click()
                buscar = page.get_by_role("searchbox", name="Buscar en la transcripción")
                buscar.fill("accion")
                expect(page.locator(".fila-frase:visible")).to_have_count(1)
                page.get_by_role("button", name="0:08 Acción lejana.").click()
                page.get_by_role("button", name="Escuchar selección", exact=True).click()
                page.wait_for_function("document.querySelector('video').currentTime > 8.1 && !document.querySelector('video').paused")
                page.wait_for_function("document.querySelector('video').paused && document.querySelector('video').currentTime < 8.1")
                assert db.obtener("clips", original["id"])["fin"] == 3
                page.get_by_role("button", name="Crear clip con la selección").click()
                expect(page.get_by_role("tab", name="Subtítulos", exact=True)).to_have_attribute("aria-selected", "true")
                clips = db.listar("clips", "proyecto_id = ?", (pid,))
                assert any(c["inicio"] == 8 and c["fin"] == 10 for c in clips)
                page.goto(f"http://127.0.0.1:{puerto}/#/vivo")
                expect(page.get_by_text("Fuera del búfer", exact=True)).to_be_visible()
                page.get_by_role("textbox", name="Nota del marcador").fill("Buena jugada")
                page.get_by_role("button", name="Marcar momento", exact=True).click()
                expect(page.get_by_text("Buena jugada", exact=True)).to_be_visible()
                page.get_by_label("Filtrar momentos").select_option("manual")
                expect(page.get_by_text("Momento antiguo", exact=True)).not_to_be_visible()
                assert sesion.momentos[-1]["origen"] == "manual"
                assert not errores, errores
                browser.close()
                print("PASS: búsqueda sin acentos, escucha fuera del clip, límites de frase, creación de clip, marcador, filtro y caducidad; sin errores JS")
        finally:
            servidor.should_exit = True
            hilo.join(timeout=10)
            vivo._sesion = None


if __name__ == "__main__":
    main()
