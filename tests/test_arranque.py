"""Abrir una instancia existente conserva un solo servidor y la carpeta correcta."""

import io
import json

import pytest

from clipstudio import __main__ as arranque


@pytest.mark.parametrize("sin_navegador", [False, True])
def test_segundo_arranque_reutiliza_servidor(monkeypatch, sin_navegador):
    monkeypatch.setattr(arranque.config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(arranque.config, "bloquear_instancia", lambda: False)
    monkeypatch.setattr(arranque, "instancia_disponible", lambda _: True)
    monkeypatch.setattr(arranque.sys, "argv", ["clipstudio"] + (["--no-abrir"] if sin_navegador else []))
    abiertas = []
    monkeypatch.setattr(arranque.webbrowser, "open", abiertas.append)
    monkeypatch.setattr(arranque.uvicorn, "run", lambda *args, **kwargs: pytest.fail("Se creo un segundo servidor"))
    assert arranque.main() == 0
    assert len(abiertas) == (0 if sin_navegador else 1)


@pytest.mark.parametrize("misma_carpeta", [False, True])
def test_reutiliza_solo_la_misma_carpeta(monkeypatch, tmp_path, misma_carpeta):
    monkeypatch.setattr(arranque.config, "DATA_DIR", tmp_path)

    class Cliente:
        def open(self, url, timeout):
            carpeta = tmp_path if misma_carpeta else tmp_path / "otra"
            return io.BytesIO(json.dumps({"carpeta_datos": str(carpeta)}).encode())

    monkeypatch.setattr(arranque, "build_opener", lambda *args: Cliente())
    assert arranque.instancia_disponible("http://127.0.0.1:8765") is misma_carpeta
