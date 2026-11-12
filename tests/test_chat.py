"""Contratos de chat, detector causal y conversion automatica sin red."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from clipstudio import chat, config, db, media, pipeline, vivo


def evento(id="mensaje", usuario="persona", enviado=100):
    return chat.EventoChat(id, usuario, enviado)


def test_twitch_normaliza_y_descarta_comandos():
    assert chat.mensaje_twitch("PING :tmi.twitch.tv") is None
    mensaje = chat.mensaje_twitch("@id=abc;user-id=42;tmi-sent-ts=100000;emotes=25:0-4 :persona!persona@host PRIVMSG #tenz :Kappa")
    assert mensaje == chat.EventoChat("abc", "42", 100)
    assert not hasattr(mensaje, "texto")


def test_youtube_lee_envoltorio_sin_conservar_el_contenido():
    accion = {"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {
        "liveChatTextMessageRenderer": {"id": "abc", "authorExternalChannelId": "42", "timestampUsec": "100000000",
                                        "message": {"runs": [{"emoji": {"emojiId": "risa"}}]}}
    }}}]}}
    assert list(chat.mensajes_youtube(accion)) == [chat.EventoChat("abc", "42", 100)]
    assert list(chat.mensajes_youtube({"removeChatItemAction": {"targetItemId": "abc"}})) == []


def test_detector_rafaga_causal_y_enfriamiento():
    detector = chat.DetectorChat()
    momentos = []
    for segundo in range(130):
        cantidad = 15 if 30 <= segundo < 40 or 110 <= segundo < 115 else 1
        for i in range(cantidad):
            detector.agregar(segundo, evento(f"{segundo}-{i}", f"u{i % 5}"))
        momento = detector.evaluar(segundo, True)
        if momento:
            momentos.append(momento)
    assert len(momentos) == 2
    assert 30 <= momentos[0]["tiempo"] <= 33
    assert momentos[1]["tiempo"] - momentos[0]["tiempo"] >= 60


def test_detector_deduplica_y_limita_spam():
    detector = chat.DetectorChat()
    detector.agregar(0, evento())
    detector.agregar(0, evento())
    assert detector.actividad(0) == [1]
    for segundo in range(60):
        for i in range(100):
            detector.agregar(segundo, evento(f"{segundo}-{i}", "un_bot"))
        assert detector.evaluar(segundo, True) is None
        assert detector.segundos[segundo]["un_bot"] <= 5


def test_no_detector_sin_cobertura_ni_historia():
    detector = chat.DetectorChat()
    for segundo in range(25):
        for i in range(30):
            detector.agregar(segundo, evento(f"{segundo}-{i}", f"u{i}"))
        assert detector.evaluar(segundo, False) is None
    assert detector.evaluar(25, True) is None


def test_evaluacion_retrasada_conserva_mensajes_recientes_y_acota_memoria():
    detector = chat.DetectorChat()
    for segundo in range(300):
        detector.agregar(segundo, evento(str(segundo)))
        if segundo >= 5:
            detector.evaluar(segundo - 5, True)
        assert segundo in detector.segundos
    assert len(detector.segundos) <= 131
    assert len(detector.actividad(299)) == 120


@pytest.fixture
def sesion(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "datos.sqlite")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "proyectos")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(config, "VIVO_DIR", tmp_path / "vivo")
    db.iniciar()
    fila = db.insertar("sesiones_vivo", {"url": "https://twitch.tv/tenz", "estado": "grabando"})
    s = vivo.Sesion(fila["id"], fila["url"])
    s.estado, s.estado_chat = "grabando", "conectado"
    return s


def test_rafaga_encola_clip_automatico_y_ignora_historial_viejo(sesion, monkeypatch):
    monkeypatch.setattr(vivo.time, "time", lambda: 1000)
    for segundo in range(46):
        sesion._nuevo_segundo(-50)
        if 30 <= segundo <= 33:
            for i in range(15):
                sesion._recibir_chat(evento(f"{segundo}-{i}", f"u{i % 5}", 1000))
    momentos = [m for m in sesion.momentos if m["origen"] == "chat"]
    assert len(momentos) == 1
    assert momentos[0]["estado"] == "esperando_video"
    assert sesion._clips_pendientes.get_nowait() == momentos[0]["id"]
    assert 27 <= momentos[0]["tiempo"] <= 31
    antes = sesion.publico()["chat_actividad"]
    sesion._recibir_chat(evento("viejo", "usuario", 900))
    assert sesion.publico()["chat_actividad"] == antes


def test_conversion_concurrente_y_reintento_crean_un_solo_proyecto(sesion, monkeypatch):
    sesion._registrar_momento({"tiempo": 40, "motivo": "Chat"}, "chat")
    mid = sesion.momentos[0]["id"]
    llamadas = []
    monkeypatch.setattr(sesion, "esperar_cobertura", lambda *args: None)

    def crear(a, b, nombre):
        llamadas.append((a, b))
        return db.insertar("proyectos", {"nombre": nombre, "origen": "archivo", "estado": "en_cola"})

    monkeypatch.setattr(sesion, "crear_clip", crear)
    with ThreadPoolExecutor(max_workers=2) as pool:
        proyectos = list(pool.map(sesion.convertir_momento, [mid, mid]))
    assert llamadas == [(15, 50)]
    assert proyectos[0]["id"] == proyectos[1]["id"]
    assert sesion.momentos[0]["estado"] == "convertido"


def test_cola_automatica_materializa_momento(sesion, monkeypatch):
    sesion._registrar_momento({"tiempo": 40, "motivo": "Chat"}, "chat")
    monkeypatch.setattr(sesion, "esperar_cobertura", lambda *args: None)
    monkeypatch.setattr(sesion, "crear_clip", lambda a, b, nombre:
                        db.insertar("proyectos", {"nombre": nombre, "origen": "archivo", "estado": "en_cola"}))
    hilo = threading.Thread(target=sesion._procesar_automaticos)
    hilo.start()
    try:
        limite = time.monotonic() + 3
        while sesion.momentos[0]["estado"] != "convertido" and time.monotonic() < limite:
            time.sleep(.01)
        assert sesion.momentos[0]["proyecto_id"]
    finally:
        sesion.parar.set()
        hilo.join(timeout=3)
    assert not hilo.is_alive()


def test_modo_manual_no_encola_y_fallo_no_rompe_sesion(sesion, monkeypatch):
    sesion.automaticos = False
    sesion._registrar_momento({"tiempo": 40, "motivo": "Chat"}, "chat")
    assert sesion._clips_pendientes.empty()
    assert sesion.momentos[0]["estado"] == "nuevo"
    monkeypatch.setattr(sesion, "esperar_cobertura", lambda *args: None)
    monkeypatch.setattr(sesion, "crear_clip", lambda *args: (_ for _ in ()).throw(vivo.ErrorMedia("Sin espacio")))
    with pytest.raises(vivo.ErrorMedia, match="Sin espacio"):
        sesion.convertir_momento(sesion.momentos[0]["id"])
    assert sesion.estado == "grabando"
    assert sesion.momentos[0]["estado"] == "error"


@pytest.mark.skipif(not config.find_tool("ffmpeg") or not config.find_tool("ffprobe"), reason="Requiere FFmpeg")
def test_chat_a_clip_real_y_editor_conserva_el_momento_completo(sesion, monkeypatch):
    sesion.carpeta.mkdir(parents=True)
    media.ejecutar_ffmpeg(
        ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=5", "-t", "45",
         "-c:v", "libx264", "-g", "30", "-preset", "ultrafast", "-f", "segment",
         "-segment_time", "6", "-reset_timestamps", "1", "-segment_list", str(sesion.carpeta / "lista.csv"),
         "-segment_list_type", "csv", str(sesion.carpeta / "seg_%06d.ts")],
        45, media.Cancelacion(), lambda _: None,
    )
    sesion._leer_lista()
    assert sesion.cobertura() == pytest.approx(45)
    encolados = []
    monkeypatch.setattr(pipeline.gestor, "encolar", lambda tipo, pid: encolados.append((tipo, pid)))
    monkeypatch.setattr(vivo.time, "time", lambda: 1000)
    for segundo in range(46):
        sesion._nuevo_segundo(-50)
        if 30 <= segundo <= 33:
            for i in range(15):
                sesion._recibir_chat(evento(f"{segundo}-{i}", f"u{i % 5}", 1000))
    assert sesion._clips_pendientes.qsize() == 1
    hilo = threading.Thread(target=sesion._procesar_automaticos)
    hilo.start()
    try:
        limite = time.monotonic() + 15
        while sesion.momentos[0]["estado"] not in ("convertido", "error") and time.monotonic() < limite:
            time.sleep(.02)
        assert sesion.momentos[0]["estado"] == "convertido", sesion.momentos[0]
    finally:
        sesion.parar.set()
        hilo.join(timeout=5)
    assert len(encolados) == 1
    pid = encolados[0][1]
    proyecto = db.obtener("proyectos", pid)
    assert proyecto["es_clip_vivo"] == 1
    assert media.sondear(pipeline.ruta_fuente(proyecto))["duracion"] == pytest.approx(35, abs=.3)
    pipeline.procesar_proyecto(pid, media.Cancelacion())
    assert db.obtener("proyectos", pid)["estado"] == "listo"
    clips = db.listar("clips", "proyecto_id = ?", (pid,))
    assert len(clips) == 1
    assert clips[0]["origen"] == "vivo"
    assert clips[0]["inicio"] == 0
    assert clips[0]["fin"] == pytest.approx(35, abs=.3)
