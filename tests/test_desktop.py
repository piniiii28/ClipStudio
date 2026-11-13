"""Propiedad del servidor, aislamiento entre ventanas y cierre de tareas reales."""
import subprocess
import threading

from fastapi.testclient import TestClient

from clipstudio import config, desktop, pipeline
from clipstudio.api import app


def test_reutilizar_servidor_no_lo_cierra(monkeypatch):
    from clipstudio import __main__
    monkeypatch.setattr(__main__, "instancia_disponible", lambda url: True)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Segundo servidor")))
    motor = desktop.Motor("http://127.0.0.1:8765")
    motor.preparar()
    monkeypatch.setattr(desktop, "peticion", lambda *a: (_ for _ in ()).throw(AssertionError("Cerro servidor ajeno")))
    motor.cerrar()
    assert motor.proc is None


def test_cierre_requiere_token_del_dueno():
    cerrados = []
    app.state.desktop_token = "secreto-de-la-ventana"
    app.state.desktop_shutdown = lambda: cerrados.append(True)
    try:
        cliente = TestClient(app, base_url="http://127.0.0.1:8765")
        assert cliente.post("/api/escritorio/cerrar").status_code == 403
        assert cliente.post("/api/escritorio/cerrar", headers={"X-ClipStudio-Token": "otro"}).status_code == 403
        assert not cerrados
        assert cliente.post("/api/escritorio/cerrar", headers={"X-ClipStudio-Token": app.state.desktop_token}).status_code == 204
        assert cerrados == [True]
    finally:
        del app.state.desktop_token
        del app.state.desktop_shutdown


def test_aviso_segun_actividad_y_propiedad():
    assert desktop.mensaje_cierre({"grabando": False, "trabajos": 0}, True) is None
    assert "búfer" in desktop.mensaje_cierre({"grabando": True}, True)
    assert "cancelarán" in desktop.mensaje_cierre({"trabajos": 2}, True)
    assert "seguirá funcionando" in desktop.mensaje_cierre({"grabando": True}, False)


def test_apagar_cola_cancela_ejecucion_y_no_deja_hilos(monkeypatch):
    gestor = pipeline.Gestor()
    iniciado, terminado = threading.Event(), threading.Event()

    def ejecutar(tabla, tipo, funcion, id_, cancel):
        iniciado.set()
        while not cancel.activa:
            terminado.wait(.01)
        terminado.set()

    monkeypatch.setattr(gestor, "_ejecutar", ejecutar)
    gestor.iniciar()
    assert gestor.encolar("proyecto", "proyecto")
    assert iniciado.wait(2)
    gestor.detener(timeout=2)
    assert terminado.is_set()
    assert not gestor._hilos
    assert not gestor.cantidad_activos()
    assert not gestor.encolar("proyecto", "nuevo")
    gestor.iniciar()
    assert gestor.encolar("proyecto", "nuevo")
    gestor.detener(timeout=2)


def test_limpia_cache_de_webview_solo_al_cambiar_de_version(tmp_path, monkeypatch):
    from clipstudio import desktop

    perfil = tmp_path / "EBWebView" / "Default"
    for nombre in ("Cache", "Code Cache", "Local Storage"):
        (perfil / nombre).mkdir(parents=True)
        (perfil / nombre / "dato").write_text("x")
    monkeypatch.setattr(desktop, "__version__", "9.9.9")
    assert desktop.limpiar_cache_si_cambio_version(tmp_path) is True
    assert not (perfil / "Cache").exists() and not (perfil / "Code Cache").exists()
    assert (perfil / "Local Storage" / "dato").exists()  # las preferencias de la ventana se conservan
    (perfil / "Cache").mkdir()
    assert desktop.limpiar_cache_si_cambio_version(tmp_path) is False  # misma version: no toca nada
    assert (perfil / "Cache").exists()
    monkeypatch.setattr(desktop, "__version__", "9.9.10")
    assert desktop.limpiar_cache_si_cambio_version(tmp_path) is True
