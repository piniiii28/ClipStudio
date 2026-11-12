"""Mensajes de Kick y contrato del transporte Centrifugo sin acceso a la red."""

from datetime import datetime, timezone
import json
import threading

import pytest
import websocket

from clipstudio import chat


def publicacion(id="m1", usuario=99, evento="App\\Events\\ChatMessageEvent", texto_json=True):
    datos = {"id": id, "sender": {"id": usuario, "username": "persona"},
             "created_at": "2026-11-12T14:48:54+00:00", "content": "Mensaje que no se guarda"}
    return {"event": evento, "data": json.dumps(datos) if texto_json else datos}


@pytest.mark.parametrize("texto_json", [True, False])
def test_kick_normaliza_mensajes_y_no_conserva_texto(texto_json):
    evento = chat.mensaje_kick(publicacion(texto_json=texto_json))
    assert evento == chat.EventoChat("m1", "99", datetime(2026, 11, 12, 14, 48, 54, tzinfo=timezone.utc).timestamp())
    assert not hasattr(evento, "content")
    assert chat.mensaje_kick(publicacion(evento="App\\Events\\ChatroomClearEvent")) is None


@pytest.mark.parametrize("datos", [None, "malformado", {}, {"event": "App\\Events\\ChatMessageEvent", "data": "{}"},
    {"event": "App\\Events\\ChatMessageEvent", "data": {"id": "m", "sender": {"id": 1}, "created_at": "fecha inválida"}}])
def test_kick_descarta_publicaciones_sin_identidad_o_tiempo(datos):
    assert chat.mensaje_kick(datos) is None


@pytest.fixture
def lector(monkeypatch):
    estados = []
    l = chat.LectorKick("pirutastic", lambda estado, error: estados.append((estado, error)))
    tokens = []

    def peticion(url, datos=None):
        if "/api/v2/channels/" in url:
            return {"id": 10, "chatroom": {"id": 20}}
        if url.endswith("/auth/connection"):
            tokens.append(datos["client_id"])
            return {"data": {"token": f"invitado-{len(tokens)}"}}
        return {"data": {"connections": [{"provider": "centrifugo", "credentials": {
            "url": "wss://realtime.sa-east-1.platform.kick.com/connection/websocket"}}]}}

    monkeypatch.setattr(l, "_peticion", peticion)
    return l, estados, tokens


class Conexion:
    def __init__(self, paquetes):
        self.paquetes = iter(paquetes)
        self.enviados = []
        self.cerrada = False

    def settimeout(self, segundos):
        pass

    def send(self, datos):
        self.enviados.append(json.loads(datos))

    def recv(self):
        paquete = next(self.paquetes)
        return paquete() if callable(paquete) else paquete

    def close(self, timeout=1):
        self.cerrada = True


def push():
    return json.dumps({"push": {"channel": "chatrooms.20.v2", "pub": {"data": publicacion()}}})


def test_kick_suscripcion_ping_y_paquetes_con_varias_lineas(lector, monkeypatch):
    l, estados, tokens = lector
    conexion = Conexion([json.dumps({"id": 1, "connect": {"ping": 25}}),
                         '{"id":2,"subscribe":{}}\n{}\n' + push()])
    monkeypatch.setattr(websocket, "create_connection", lambda *args, **kwargs: conexion)
    eventos = l.leer(threading.Event())
    try:
        assert next(eventos).id == "m1"
        assert estados == [("conectado", None)]
        assert conexion.enviados[0]["connect"]["token"] == "invitado-1"
        assert conexion.enviados[1] == {"id": 2, "subscribe": {"channel": "chatrooms.20.v2"}}
        assert conexion.enviados[2] == {}
    finally:
        eventos.close()
    assert conexion.cerrada


def test_kick_renueva_la_misma_sesion_antes_de_caducar(lector, monkeypatch):
    l, estados, tokens = lector
    reloj = [0]
    monkeypatch.setattr(chat.time, "monotonic", lambda: reloj[0])

    def suscrito():
        reloj[0] = 2
        return '{"id":2,"subscribe":{}}'

    conexion = Conexion(['{"id":1,"connect":{"expires":true,"ttl":61}}', suscrito,
                         '{"id":3,"refresh":{"expires":true,"ttl":2700}}', push()])
    monkeypatch.setattr(websocket, "create_connection", lambda *args, **kwargs: conexion)
    eventos = l.leer(threading.Event())
    try:
        assert next(eventos).usuario == "99"
        assert len(tokens) == 2 and tokens[0] == tokens[1]
        assert conexion.enviados[2] == {"id": 3, "refresh": {"token": "invitado-2"}}
    finally:
        eventos.close()


def test_kick_rechazo_cierra_la_conexion(lector, monkeypatch):
    l, estados, tokens = lector
    conexion = Conexion(['{"id":1,"connect":{}}', '{"id":2,"error":{"code":103}}'])
    monkeypatch.setattr(websocket, "create_connection", lambda *args, **kwargs: conexion)
    with pytest.raises(chat.ErrorChat, match="103"):
        list(l.leer(threading.Event()))
    assert conexion.cerrada and estados == []


def test_kick_cancelado_no_abre_conexiones(lector, monkeypatch):
    l, _, _ = lector
    monkeypatch.setattr(l, "_peticion", lambda *args: pytest.fail("Se abrio una peticion cancelada"))
    parar = threading.Event()
    parar.set()
    assert list(l.leer(parar)) == []


def test_factory_admite_canales_kick(tmp_path):
    assert isinstance(chat.crear_lector("https://kick.com/Pirutastic/", tmp_path, lambda *args: None), chat.LectorKick)
    with pytest.raises(chat.ErrorChat):
        chat.crear_lector("https://kick.com/pirutastic/videos/123", tmp_path, lambda *args: None)
