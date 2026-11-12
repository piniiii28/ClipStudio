"""Lectura del chat publico y deteccion causal de rafagas, sin guardar el texto."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import socket
import ssl
import statistics
import subprocess
import sys
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import config, media


class ErrorChat(Exception):
    pass


@dataclass
class EventoChat:
    id: str
    usuario: str
    enviado: float


def mensaje_twitch(linea: str) -> EventoChat | None:
    etiquetas = {}
    if linea.startswith("@"):
        tags, _, linea = linea.partition(" ")
        etiquetas = dict(tag.partition("=")[::2] for tag in tags[1:].split(";"))
    if " PRIVMSG #" not in linea:
        return None
    usuario = etiquetas.get("user-id") or linea.split("!", 1)[0].lstrip(":")
    try:
        enviado = float(etiquetas.get("tmi-sent-ts", "0")) / 1000 or time.time()
    except ValueError:
        enviado = time.time()
    return EventoChat(etiquetas.get("id", ""), usuario, enviado)


def mensajes_youtube(accion: dict) -> Iterator[EventoChat]:
    # yt-dlp normaliza el chat en vivo con el mismo envoltorio que las repeticiones.
    repeticion = accion.get("replayChatItemAction")
    if repeticion:
        for interna in repeticion.get("actions", []):
            yield from mensajes_youtube(interna)
        return
    item = accion.get("addChatItemAction", {}).get("item", {})
    for nombre in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer", "liveChatMembershipItemRenderer"):
        datos = item.get(nombre)
        if not datos:
            continue
        try:
            enviado = int(datos.get("timestampUsec", 0)) / 1_000_000
        except (ValueError, TypeError):
            continue
        if not datos.get("id") or not enviado:
            continue
        yield EventoChat(datos["id"], datos.get("authorExternalChannelId", ""), enviado)


def mensaje_kick(publicacion: dict | str) -> EventoChat | None:
    """Normaliza publicaciones publicas y conserva solo identidad y tiempo."""
    try:
        datos = json.loads(publicacion) if isinstance(publicacion, str) else publicacion
        if not isinstance(datos, dict) or datos.get("event") != "App\\Events\\ChatMessageEvent":
            return None
        mensaje = datos.get("data")
        mensaje = json.loads(mensaje) if isinstance(mensaje, str) else mensaje
        if not isinstance(mensaje, dict) or not isinstance(mensaje.get("id"), str) or not mensaje["id"]:
            return None
        remitente = mensaje.get("sender") or {}
        usuario = remitente.get("id") or remitente.get("username")
        if not isinstance(usuario, (str, int)) or not str(usuario):
            return None
        enviado = datetime.fromisoformat(mensaje["created_at"].replace("Z", "+00:00"))
        if enviado.tzinfo is None:
            enviado = enviado.replace(tzinfo=timezone.utc)
        return EventoChat(mensaje["id"], str(usuario), enviado.timestamp())
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


class DetectorChat:
    """Compara ventanas de 3 s con el minuto anterior y limita el spam por usuario."""

    def __init__(self) -> None:
        self.segundos: dict[int, dict[str, int]] = {}
        self.ids: OrderedDict[str, None] = OrderedDict()
        self.cobertura: dict[int, bool] = {}
        self.ultimo: int | None = None
        self.consecutivos = 0

    def agregar(self, segundo: int, evento: EventoChat) -> None:
        if segundo < 0 or (evento.id and evento.id in self.ids):
            return
        if evento.id:
            self.ids[evento.id] = None
            if len(self.ids) > 10000:
                self.ids.popitem(last=False)
        usuarios = self.segundos.setdefault(segundo, {})
        # Tambien acota el numero de usuarios de un segundo excepcionalmente concurrido.
        if len(usuarios) < 3000 or evento.usuario in usuarios:
            usuarios[evento.usuario] = min(5, usuarios.get(evento.usuario, 0) + 1)

    def evaluar(self, segundo: int, conectado: bool) -> dict | None:
        self.cobertura[segundo] = conectado
        self.segundos = {s: v for s, v in self.segundos.items() if s >= segundo - 125}
        self.cobertura = {s: v for s, v in self.cobertura.items() if s >= segundo - 125}
        if not all(self.cobertura.get(s, False) for s in range(segundo - 2, segundo + 1)):
            self.consecutivos = 0
            return None
        historia = [sum(self.segundos.get(s, {}).values()) for s in range(max(0, segundo - 65), segundo - 5)
                    if self.cobertura.get(s, False)]
        if len(historia) < 20:
            return None
        ventana = [self.segundos.get(s, {}) for s in range(segundo - 2, segundo + 1)]
        ritmo = sum(sum(usuarios.values()) for usuarios in ventana) / 3
        media_base = statistics.mean(historia)
        z = (ritmo - media_base) / max(1, statistics.pstdev(historia))
        usuarios = set().union(*(set(u) for u in ventana))
        pico = ritmo >= 3 and ritmo >= media_base * 2 and z >= 3 and len(usuarios) >= 3
        self.consecutivos = self.consecutivos + 1 if pico else 0
        if self.consecutivos < 2 or (self.ultimo is not None and segundo - self.ultimo < 60):
            return None
        self.ultimo = segundo
        return {"tiempo": float(segundo), "motivo": f"Pico de chat: {ritmo:.1f} mensajes/s (media anterior {media_base:.1f})"}

    def actividad(self, segundo: int) -> list[int]:
        return [sum(self.segundos.get(s, {}).values()) for s in range(max(0, segundo - 119), segundo + 1)]


class LectorChat:
    def __init__(self, estado: Callable[[str, str | None], None]) -> None:
        self.estado = estado

    def leer(self, parar: threading.Event) -> Iterator[EventoChat]:
        raise NotImplementedError

    def cerrar(self) -> None:
        pass


class LectorTwitch(LectorChat):
    def __init__(self, canal: str, estado: Callable) -> None:
        super().__init__(estado)
        self.canal = canal
        self.conexion: ssl.SSLSocket | None = None

    def leer(self, parar: threading.Event) -> Iterator[EventoChat]:
        if parar.is_set():
            return
        raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=5)
        try:
            self.conexion = ssl.create_default_context().wrap_socket(raw, server_hostname="irc.chat.twitch.tv")
            self.conexion.settimeout(1)
            if parar.is_set():
                return
            nick = f"justinfan{secrets.randbelow(90000000) + 10000000}"
            self.conexion.sendall(("CAP REQ :twitch.tv/tags twitch.tv/commands\r\n"
                                   f"PASS SCHMOOPIIE\r\nNICK {nick}\r\nJOIN #{self.canal}\r\n").encode())
            buffer = b""
            unido = False
            inicio = time.monotonic()
            while not parar.is_set():
                if not unido and time.monotonic() - inicio > 20:
                    raise ErrorChat("Twitch no confirmó la conexión al chat.")
                try:
                    bloque = self.conexion.recv(65536)
                except socket.timeout:
                    continue
                if not bloque:
                    raise ErrorChat("Se cerró la conexión con el chat de Twitch.")
                buffer += bloque
                if len(buffer) > 1024 * 1024:
                    raise ErrorChat("Respuesta de chat demasiado grande.")
                while b"\r\n" in buffer:
                    linea, buffer = buffer.split(b"\r\n", 1)
                    texto = linea.decode("utf-8", "replace")
                    if texto.startswith("PING "):
                        self.conexion.sendall(("PONG " + texto[5:] + "\r\n").encode())
                    if " RECONNECT" in texto or "authentication failed" in texto.lower():
                        raise ErrorChat("Twitch solicitó reconectar el chat.")
                    if " 366 " in texto or f" ROOMSTATE #{self.canal}" in texto:
                        unido = True
                        self.estado("conectado", None)
                    evento = mensaje_twitch(texto)
                    if evento:
                        yield evento
        finally:
            raw.close()
            self.cerrar()

    def cerrar(self) -> None:
        if self.conexion:
            try:
                self.conexion.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.conexion.close()


class LectorKick(LectorChat):
    """Lee el chat publico de Kick por Centrifugo con sesion de invitado renovable."""

    def __init__(self, canal: str, estado: Callable) -> None:
        super().__init__(estado)
        self.canal = canal
        self.conexion = None
        self._cerrado = threading.Event()

    def _peticion(self, url: str, datos: dict | None = None) -> dict:
        cabeceras = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                     "Origin": "https://kick.com", "Referer": f"https://kick.com/{self.canal}"}
        cuerpo = None
        if datos is not None:
            cabeceras["Content-Type"] = "application/json"
            cuerpo = json.dumps(datos).encode()
        with urlopen(Request(url, data=cuerpo, headers=cabeceras), timeout=5) as respuesta:
            return json.loads(respuesta.read(2 * 1024 * 1024))

    def _token(self, cliente: str) -> str:
        respuesta = self._peticion("https://web.kick.com/api/v1/realtime/auth/connection", {"client_id": cliente})
        token = respuesta.get("data", {}).get("token")
        if not isinstance(token, str) or not token:
            raise ErrorChat("Kick no pudo abrir la sesión pública del chat.")
        return token

    def leer(self, parar: threading.Event) -> Iterator[EventoChat]:
        import websocket

        def detenido() -> bool:
            return parar.is_set() or self._cerrado.is_set()

        if detenido():
            return
        datos = self._peticion(f"https://kick.com/api/v2/channels/{self.canal}")
        if detenido():
            return
        try:
            canal_id = int(datos["id"])
            chat_id = int(datos["chatroom"]["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ErrorChat("Kick no devolvió un chat público disponible para ese canal.") from exc
        cliente = str(uuid.uuid4())
        respuesta = self._peticion(f"https://web.kick.com/api/v1/realtime/channels/{canal_id}/chat/connection", {
            "client": {"id": cliente, "type": "web"},
            "capabilities": {"accepted_providers": [{"provider": "centrifugo"}]},
        })
        if detenido():
            return
        conexion = next((c for c in respuesta.get("data", {}).get("connections", [])
                         if c.get("provider") == "centrifugo"), None)
        url = (conexion or {}).get("credentials", {}).get("url", "")
        destino = urlparse(url)
        if destino.scheme != "wss" or not re.fullmatch(r"realtime\.[a-z0-9-]+\.platform\.kick\.com", destino.hostname or ""):
            raise ErrorChat("Kick devolvió un servicio de chat incompatible.")
        token = self._token(cliente)
        if detenido():
            return
        try:
            self.conexion = websocket.create_connection(url, timeout=5, origin="https://kick.com", enable_multithread=True)
            self.conexion.settimeout(1)
            if detenido():
                return
            self.conexion.send(json.dumps({"id": 1, "connect": {"token": token, "name": "js"}}))
            conectado = False
            limite_conexion = time.monotonic() + 15
            ultimo_paquete = time.monotonic()
            espera_ping = None
            renovar = None
            secuencia = 2
            renovacion_pendiente = None
            limite_renovacion = None
            canal_chat = f"chatrooms.{chat_id}.v2"
            while not detenido():
                ahora = time.monotonic()
                if not conectado and ahora > limite_conexion:
                    raise ErrorChat("Kick no confirmó la conexión al chat.")
                if espera_ping and ahora - ultimo_paquete > espera_ping:
                    raise ErrorChat("El chat de Kick dejó de responder. Se reconectará.")
                if limite_renovacion is not None and ahora > limite_renovacion:
                    raise ErrorChat("Kick no confirmó la renovación del chat. Se reconectará.")
                if conectado and renovar is not None and ahora >= renovar and renovacion_pendiente is None:
                    token = self._token(cliente)
                    if detenido():
                        return
                    secuencia += 1
                    renovacion_pendiente = secuencia
                    limite_renovacion = time.monotonic() + 10
                    self.conexion.send(json.dumps({"id": secuencia, "refresh": {"token": token}}))
                try:
                    paquete = self.conexion.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not paquete:
                    raise ErrorChat("Se cerró la conexión con el chat de Kick.")
                if len(paquete) > 1024 * 1024:
                    raise ErrorChat("Kick devolvió un paquete de chat demasiado grande.")
                ultimo_paquete = time.monotonic()
                for linea in paquete.splitlines():
                    mensaje = json.loads(linea)
                    if mensaje == {}:
                        self.conexion.send("{}")
                        continue
                    if mensaje.get("error"):
                        codigo = mensaje["error"].get("code", "desconocido")
                        raise ErrorChat(f"Kick rechazó una operación del chat ({codigo}). Se reintentará.")
                    if mensaje.get("id") == 1 and "connect" in mensaje:
                        confirmacion = mensaje["connect"]
                        ping = confirmacion.get("ping", 0)
                        espera_ping = max(30, ping * 2.5) if ping else None
                        ttl = confirmacion.get("ttl", 0)
                        renovar = time.monotonic() + max(1, ttl - 60) if confirmacion.get("expires") and ttl else None
                        self.conexion.send(json.dumps({"id": 2, "subscribe": {"channel": canal_chat}}))
                    elif mensaje.get("id") == 2 and "subscribe" in mensaje:
                        conectado = True
                        self.estado("conectado", None)
                    elif renovacion_pendiente is not None and mensaje.get("id") == renovacion_pendiente and "refresh" in mensaje:
                        confirmacion = mensaje["refresh"]
                        ttl = confirmacion.get("ttl", 0)
                        renovar = time.monotonic() + max(1, ttl - 60) if confirmacion.get("expires") and ttl else None
                        renovacion_pendiente, limite_renovacion = None, None
                    push = mensaje.get("push", {})
                    if "disconnect" in push or "unsubscribe" in push:
                        raise ErrorChat("Kick cerró la suscripción del chat. Se reconectará.")
                    if push.get("channel") == canal_chat and "pub" in push:
                        evento = mensaje_kick(push["pub"].get("data"))
                        if evento:
                            yield evento
        finally:
            self.cerrar()

    def cerrar(self) -> None:
        self._cerrado.set()
        if self.conexion:
            self.conexion.close(timeout=1)


class LectorYouTube(LectorChat):
    def __init__(self, url: str, carpeta: Path, estado: Callable) -> None:
        super().__init__(estado)
        self.url, self.carpeta = url, carpeta
        self.proc: subprocess.Popen | None = None

    def leer(self, parar: threading.Event) -> Iterator[EventoChat]:
        if parar.is_set():
            return
        self.proc = subprocess.Popen(
            ([sys.executable, "--worker-youtube"] if getattr(sys, "frozen", False)
             else [sys.executable, "-u", "-m", "clipstudio.chat"]) + [self.url, str(self.carpeta)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            cwd=str(config.ROOT), creationflags=media._SIN_VENTANA,
        )
        try:
            if parar.is_set():
                return
            assert self.proc.stdout is not None
            ultimo_error = "Se interrumpió la lectura del chat de YouTube."
            for linea in self.proc.stdout:
                if parar.is_set():
                    return
                datos = json.loads(linea)
                if "estado" in datos:
                    if datos.get("error"):
                        ultimo_error = datos["error"]
                    self.estado(datos["estado"], datos.get("error"))
                else:
                    yield EventoChat(**datos)
            raise ErrorChat(ultimo_error)
        finally:
            self.cerrar()

    def cerrar(self) -> None:
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            if self.proc.stdout:
                self.proc.stdout.close()


def crear_lector(url: str, carpeta: Path, estado: Callable) -> LectorChat:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    canal = parsed.path.strip("/")
    if host in ("twitch.tv", "www.twitch.tv", "m.twitch.tv") and re.fullmatch(r"[a-zA-Z0-9_]{1,25}", canal):
        return LectorTwitch(canal.lower(), estado)
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        return LectorYouTube(url, carpeta, estado)
    if host in ("kick.com", "www.kick.com") and re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", canal):
        return LectorKick(canal.lower(), estado)
    raise ErrorChat("El chat automático está disponible para canales de Twitch, Kick y directos de YouTube.")


def _youtube_worker(url: str, carpeta: Path) -> None:
    """Aisla el lector de yt-dlp para poder detenerlo incluso durante una espera de red."""
    from dataclasses import asdict
    import yt_dlp
    from yt_dlp.downloader.youtube_live_chat import YoutubeLiveChatFD

    inicio = time.time()

    class DescargadorChat(YoutubeLiveChatFD):
        def _append_fragment(self, ctx, frag_content):
            print(json.dumps({"estado": "conectado"}), flush=True)
            for linea in frag_content.splitlines():
                for evento in mensajes_youtube(json.loads(linea)):
                    if evento.enviado >= inicio:
                        print(json.dumps(asdict(evento)), flush=True)
            # Se conserva solo el fragmento actual, nunca un registro creciente del chat.
            super()._append_fragment(ctx, b"")

        def _finish_frag_download(self, ctx, info_dict):
            ctx["dest_stream"].close()
            Path(ctx["tmpfilename"]).unlink(missing_ok=True)
            return True

    opciones = {"skip_download": True, "quiet": True, "no_warnings": True, "noprogress": True,
                "socket_timeout": 15, "retries": 2, "fragment_retries": 2, "noplaylist": True,
                "ignore_no_formats_error": True,
                "extractor_args": {"youtube": {"skip": ["dash", "hls"]}}}
    if node := config.find_tool("node"):
        opciones["js_runtimes"] = {"node": {"path": node}}
    if config.YTDLP_COOKIES_BROWSER:
        opciones["cookiesfrombrowser"] = (config.YTDLP_COOKIES_BROWSER,)
    carpeta.mkdir(parents=True, exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url, download=False)
            subtitulos = (info or {}).get("subtitles", {}).get("live_chat", [])
            datos = next((s for s in subtitulos if s.get("protocol") == "youtube_live_chat"), None)
            if datos is None:
                raise ErrorChat("El directo no tiene un chat público activo disponible.")
            datos = {**datos, "http_headers": info.get("http_headers", {})}
            DescargadorChat(ydl, opciones).real_download(str(carpeta / "chat.json"), datos)
    except Exception as exc:
        mensaje = str(exc) if isinstance(exc, ErrorChat) else "No se pudo leer el chat público de YouTube. Comprueba que esté activo y accesible."
        print(json.dumps({"estado": "error", "error": mensaje}), flush=True)


if __name__ == "__main__":
    _youtube_worker(sys.argv[1], Path(sys.argv[2]))
