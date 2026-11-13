"""Selector nativo: superficie mínima, cancelación y aislamiento del motor local."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipstudio.desktop import SelectorCarpeta


@pytest.fixture
def selector(monkeypatch):
    llamadas = []
    ventana = SimpleNamespace(
        get_current_url=lambda: "http://127.0.0.1:8795/?v=1.0#/ajustes",
        create_file_dialog=lambda tipo: llamadas.append(tipo) or ("D:\\Videos",),
    )
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(FOLDER_DIALOG=30))
    return SelectorCarpeta("http://127.0.0.1:8795", lambda: ventana), ventana, llamadas


def test_solo_expone_elegir_carpeta(selector):
    api, _, _ = selector
    assert [nombre for nombre in dir(api) if not nombre.startswith("_")] == ["elegir_carpeta"]


@pytest.mark.parametrize("resultado,esperado", [
    (("D:\\Videos",), "D:\\Videos"), ([Path("D:/Fondos")], str(Path("D:/Fondos"))),
    (None, None), ((), None), ([], None),
])
def test_resultado_del_dialogo(selector, resultado, esperado):
    api, ventana, llamadas = selector

    def dialogo(tipo):
        llamadas.append(tipo)
        return resultado

    ventana.create_file_dialog = dialogo
    assert api.elegir_carpeta("Elegir carpeta") == esperado
    assert llamadas == [30]


@pytest.mark.parametrize("url", [
    None, "about:blank", "file:///C:/index.html", "https://example.org/",
    "http://127.0.0.1:8765/", "http://127.0.0.1:8795.ejemplo.org/",
    "http://127.0.0.1:8795@ejemplo.org/", "http://127.0.0.1:8795/otra",
    "https://127.0.0.1:8795/",
])
def test_rechaza_paginas_ajenas(selector, url):
    api, ventana, llamadas = selector
    ventana.get_current_url = lambda: url
    with pytest.raises(PermissionError, match="página local de ClipStudio"):
        api.elegir_carpeta()
    assert llamadas == []
