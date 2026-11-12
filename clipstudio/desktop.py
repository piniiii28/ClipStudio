"""Ventana Windows y ciclo de vida del servidor local que le pertenece."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from urllib.request import Request, ProxyHandler, build_opener

from . import actualizaciones, config

log = logging.getLogger("clipstudio.desktop")
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def comando(*argumentos: str) -> list[str]:
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "clipstudio"]
    return base + list(argumentos)


def peticion(url: str, ruta: str, token: str | None = None):
    req = Request(url + ruta, data=b"" if token else None,
                  headers={"X-ClipStudio-Token": token} if token else {})
    with build_opener(ProxyHandler({})).open(req, timeout=3) as respuesta:
        contenido = respuesta.read(65536)
    return json.loads(contenido) if contenido else None


def mensaje_cierre(actividad: dict | None, propio: bool) -> str | None:
    if not propio:
        return ("Esta ventana usa un servidor que ya estaba abierto. Al cerrarla, ese servidor "
                "seguirá funcionando. ¿Cerrar la ventana?")
    if actividad is None:
        return "¿Cerrar ClipStudio y detener su servidor? Minimiza la ventana para dejarlo funcionando."
    partes = []
    if actividad.get("grabando"):
        partes.append("Se detendrá el directo y se borrará su búfer temporal. Los clips ya guardados se conservan.")
    if actividad.get("trabajos"):
        partes.append("Se cancelarán los trabajos que siguen en curso o en cola.")
    if not partes:
        return None
    return "\n\n".join(partes + ["Puedes minimizar la ventana para que continúen. ¿Cerrar de todos modos?"])


class Motor:
    def __init__(self, url: str):
        self.url = url
        self.token = secrets.token_urlsafe(32)
        self.proc: subprocess.Popen | None = None
        self.cerrado = threading.Event()
        self._lock = threading.Lock()

    def preparar(self) -> None:
        from .__main__ import instancia_disponible

        if instancia_disponible(self.url):
            return
        with self._lock:
            if self.cerrado.is_set():
                return
            entorno = os.environ.copy()
            entorno.update(CLIPSTUDIO_DESKTOP_TOKEN=self.token, CLIPSTUDIO_PARENT_PID=str(os.getpid()))
            self.proc = subprocess.Popen(comando("--servidor-escritorio"), env=entorno,
                                         cwd=str(config.ROOT), stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=SIN_VENTANA)
        for _ in range(300):
            if self.cerrado.wait(.15):
                return
            if self.proc.poll() is not None:
                # Otro doble clic pudo ganar el bloqueo al mismo tiempo.
                if instancia_disponible(self.url):
                    self.proc = None
                    return
                raise RuntimeError("No se pudo iniciar el motor. Revisa escritorio.log en la carpeta de datos.")
            if instancia_disponible(self.url):
                return
        raise RuntimeError("El motor tardó demasiado en arrancar. Revisa escritorio.log en la carpeta de datos.")

    def cerrar(self) -> None:
        self.cerrado.set()
        with self._lock:
            proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            peticion(self.url, "/api/escritorio/cerrar", self.token)
        except Exception:
            log.warning("No se pudo solicitar el cierre del motor", exc_info=True)
        try:
            proc.wait(timeout=35)
        except subprocess.TimeoutExpired:
            # Solo el arbol que creo esta ventana; nunca otras sesiones de Python/ClipStudio.
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           creationflags=SIN_VENTANA, capture_output=True, timeout=10)
            proc.wait(timeout=10)


def _ventana_unica(titulo: str):
    """El mutex dura toda la ventana y es independiente del bloqueo del servidor."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    clave = hashlib.sha256(str(config.DATA_DIR).lower().encode()).hexdigest()[:24]
    handle = kernel.CreateMutexW(None, False, "Local\\ClipStudioDesktop-" + clave)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() != 183:
        return kernel, handle
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    for _ in range(20):
        ventana = user.FindWindowW(None, titulo)
        if ventana:
            user.ShowWindow(ventana, 9)
            user.SetForegroundWindow(ventana)
            break
        time.sleep(.1)
    kernel.CloseHandle(handle)
    return None


def _vigilar_padre(pid: int, servidor) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    padre = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not padre:
        servidor.should_exit = True
        return
    try:
        kernel.WaitForSingleObject(padre, 0xFFFFFFFF)
        servidor.should_exit = True
    finally:
        kernel.CloseHandle(padre)


def servidor() -> int:
    import uvicorn
    from .api import app

    config.ensure_dirs()
    logging.basicConfig(filename=config.DATA_DIR / "escritorio.log", encoding="utf-8",
                        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.pop("CLIPSTUDIO_DESKTOP_TOKEN", "")
    pid = int(os.environ.pop("CLIPSTUDIO_PARENT_PID", "0"))
    if not token or pid <= 0 or not config.bloquear_instancia():
        return 1
    server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=config.PORT,
                                         log_config=None, log_level="warning"))
    app.state.desktop_token = token
    app.state.desktop_shutdown = lambda: setattr(server, "should_exit", True)
    threading.Thread(target=_vigilar_padre, args=(pid, server), daemon=True).start()
    server.run()
    # Si la persona pidio instalar una actualizacion, la ventana se cierra al ver este codigo.
    return actualizaciones.CODIGO_SALIDA if actualizaciones.hay_instalacion_pendiente() else 0


def main() -> int:
    config.ensure_dirs()
    logging.basicConfig(filename=config.DATA_DIR / "ventana.log", encoding="utf-8",
                        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    titulo = "ClipStudio" if config.PORT == 8765 else f"ClipStudio · {config.PORT}"
    bloqueo = _ventana_unica(titulo)
    if bloqueo is None:
        return 0
    motor = Motor(f"http://127.0.0.1:{config.PORT}")
    try:
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["ALLOW_FILE_URLS"] = False
        ventana = webview.create_window(titulo, html=_pantalla("Iniciando ClipStudio…"),
                                        width=1440, height=940, min_size=(1000, 700),
                                        background_color="#0f1115", text_select=True)
        permiso = threading.Event()
        cerrando = threading.Lock()

        def terminar():
            try:
                if ventana.get_current_url() == motor.url + "/" or (ventana.get_current_url() or "").startswith(motor.url + "/#"):
                    guardado = threading.Event()
                    resultado = []
                    ventana.evaluate_js("Promise.resolve(window.clipstudioGuardarAntesDeCerrar?.() ?? true)",
                                        lambda ok: (resultado.append(ok), guardado.set()))
                    if not guardado.wait(15) or not resultado or resultado[0] is not True:
                        ventana.create_confirmation_dialog("Cambios pendientes", "No se pudieron guardar los últimos cambios. La ventana permanecerá abierta para que puedas reintentarlo.")
                        return
                try:
                    actividad = peticion(motor.url, "/api/escritorio/actividad")
                except Exception:
                    actividad = None
                mensaje = mensaje_cierre(actividad, motor.proc is not None)
                if mensaje and not ventana.create_confirmation_dialog("Cerrar ClipStudio", mensaje):
                    return
                permiso.set()
                ventana.destroy()
            except Exception:
                log.exception("Error al cerrar la ventana")
            finally:
                cerrando.release()

        def al_cerrar():
            if permiso.is_set():
                return True
            if cerrando.acquire(blocking=False):
                threading.Thread(target=terminar, daemon=True).start()
            return False

        def vigilar_actualizacion(proc):
            # El motor sale con un codigo propio cuando va a instalar una actualizacion: cierra la ventana sin preguntar.
            if proc.wait() == actualizaciones.CODIGO_SALIDA and not motor.cerrado.is_set():
                permiso.set()
                ventana.destroy()

        def preparar():
            try:
                motor.preparar()
                if motor.proc is not None:
                    threading.Thread(target=vigilar_actualizacion, args=(motor.proc,), daemon=True).start()
                if not motor.cerrado.is_set():
                    ventana.load_url(motor.url)
            except Exception as exc:
                log.exception("No se pudo abrir ClipStudio")
                if not motor.cerrado.is_set():
                    ventana.load_html(_pantalla(str(exc)))

        ventana.events.closing += al_cerrar
        ventana.events.closed += motor.cerrado.set
        webview.start(preparar, gui="edgechromium", private_mode=False,
                      storage_path=str(config.DATA_DIR / "webview"),
                      icon=str(config.BUNDLE_DIR / "assets" / "clipstudio.ico") if (config.BUNDLE_DIR / "assets" / "clipstudio.ico").exists() else None,
                      localization={"global.quitConfirmation": "¿Cerrar ClipStudio?"})
        return 0
    except Exception as exc:
        log.exception("Fallo de la aplicación de escritorio")
        ctypes.windll.user32.MessageBoxW(None, f"No se pudo abrir ClipStudio.\n\n{exc}\n\nComprueba que Microsoft Edge WebView2 esté instalado. Consulta ventana.log en {config.DATA_DIR}.", "ClipStudio", 0x10)
        return 1
    finally:
        motor.cerrar()
        bloqueo[0].CloseHandle(bloqueo[1])


def _pantalla(texto: str) -> str:
    return ('<!doctype html><html lang="es"><meta charset="utf-8"><title>ClipStudio</title>'
            '<body style="margin:0;background:#0f1115;color:#eee;font:18px Segoe UI;display:grid;'
            'place-content:center;height:100vh;text-align:center"><h1 style="color:#f9be36">ClipStudio</h1>'
            f'<p style="max-width:620px">{html.escape(texto)}</p></body></html>')
