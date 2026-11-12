"""Buscar actualizaciones: logica pura y API con un GitHub simulado (sin red real)."""
import hashlib
import io
import json
import subprocess
import threading
import time
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from clipstudio import __version__, actualizaciones as act, config, db
from clipstudio.api import app

DESCARGA = "https://github.com/piniiii28/ClipStudio/releases/download/v0.99.0/"
LOCAL = "a" * 40
REMOTO = "b" * 40


# ---------- funciones puras ----------

def test_comparar_versiones():
    assert act.es_version_nueva("0.1.0", "v0.2.0")
    assert act.es_version_nueva("0.2.0", "0.10.0")          # semantica, no de texto
    assert act.es_version_nueva("v0.1.0", "0.1.1")
    assert not act.es_version_nueva("0.2.0", "0.2.0")
    assert not act.es_version_nueva("0.10.0", "0.2.0")
    assert act.parsear_version("v1.2.3") == (1, 2, 3) == act.parsear_version("1.2.3")


@pytest.mark.parametrize("etiqueta", ["v0.2.0-rc1", "0.2.0-beta.1", "0.2.0+build", "0.2", "latest", "", "v", "vv0.2.0", "0.2.x", None, 5])
def test_etiquetas_invalidas_o_prerelease_no_se_ofrecen(etiqueta):
    assert act.parsear_version(etiqueta) is None
    assert not act.es_version_nueva("0.1.0", etiqueta)


def test_elegir_recurso():
    release = {"assets": [
        {"name": "ClipStudio-Setup.exe.sha256", "browser_download_url": DESCARGA + "ClipStudio-Setup.exe.sha256"},
        {"name": "ClipStudio-Setup.exe", "browser_download_url": DESCARGA + "ClipStudio-Setup.exe"},
        {"name": "otro.zip", "browser_download_url": DESCARGA + "otro.zip"},
        "basura",
    ]}
    assert act.elegir_recurso(release, "ClipStudio-Setup.exe")["browser_download_url"].endswith("/ClipStudio-Setup.exe")
    assert act.elegir_recurso(release, "ClipStudio-Setup.exe.sha256")["name"].endswith(".sha256")
    assert act.elegir_recurso({"assets": [{"name": "ClipStudio-Setup.exe"}]}, "ClipStudio-Setup.exe") is None  # sin URL
    assert act.elegir_recurso({"assets": None}, "ClipStudio-Setup.exe") is None
    assert act.elegir_recurso({}, "ClipStudio-Setup.exe") is None


def test_modo_de_instalacion():
    assert act.modo_instalacion(True, False) == "instalada"
    assert act.modo_instalacion(True, True) == "instalada"
    assert act.modo_instalacion(False, True) == "git"
    assert act.modo_instalacion(False, False) == "zip"


def test_cache_de_seis_horas():
    ahora = 1_000_000.0
    cache = {"clave": "k", "ultima_consulta": ahora - 3600}
    assert not act.toca_consultar(cache, ahora, "k")
    assert act.toca_consultar(cache, ahora, "k", forzar=True)
    assert act.toca_consultar({"clave": "k", "ultima_consulta": ahora - 6 * 3600}, ahora, "k")
    assert not act.toca_consultar({"clave": "k", "ultima_consulta": ahora - 6 * 3600 + 1}, ahora, "k")
    assert act.toca_consultar(cache, ahora, "otra-version")          # cambio la version/commit local
    assert act.toca_consultar({"clave": "k", "ultima_consulta": ahora + 500}, ahora, "k")   # reloj retrocedido
    for roto in (None, {}, [], {"clave": "k"}, {"clave": "k", "ultima_consulta": "ayer"}, {"clave": "k", "ultima_consulta": True}):
        assert act.toca_consultar(roto, ahora, "k")


def test_interpretar_compare():
    # Base = commit local, cabeza = remoto: "ahead" es que el remoto trae cambios.
    assert act.interpretar_compare({"status": "ahead"})
    for status in ("behind", "diverged", "identical", "otra-cosa", None):
        assert not act.interpretar_compare({"status": status})
    assert not act.interpretar_compare(None)
    assert not act.interpretar_compare("ahead")


@pytest.mark.parametrize("url", [
    DESCARGA + "ClipStudio-Setup.exe",
    "https://github.com/piniiii28/ClipStudio/releases/download/v1.0.0/ClipStudio-Setup.exe.sha256",
])
def test_url_de_descarga_valida(url):
    assert act.url_descarga_valida(url)


@pytest.mark.parametrize("url", [
    "https://github.com/otro/ClipStudio/releases/download/v1/ClipStudio-Setup.exe",           # otro repo
    "https://github.com/piniiii28/OtroRepo/releases/download/v1/ClipStudio-Setup.exe",
    "https://github.com/piniiii28/ClipStudio/releases/latest",                                 # no es una descarga
    "https://github.com/piniiii28/ClipStudio/releases/download/",                              # sin archivo
    "https://evil.example/piniiii28/ClipStudio/releases/download/v1/x.exe",                    # otro dominio
    "https://objects.githubusercontent.com/piniiii28/ClipStudio/releases/download/v1/x.exe",
    "https://github.com.evil.example/piniiii28/ClipStudio/releases/download/v1/x.exe",
    "https://github.com@evil.example/piniiii28/ClipStudio/releases/download/v1/x.exe",
    "https://user:pw@github.com/piniiii28/ClipStudio/releases/download/v1/x.exe",
    "https://github.com:8443/piniiii28/ClipStudio/releases/download/v1/x.exe",
    "http://github.com/piniiii28/ClipStudio/releases/download/v1/x.exe",                       # sin https
    "https://github.com/piniiii28/ClipStudio/releases/download/../../../evil/x.exe",
    "file:///C:/x.exe", "", None, 5,
])
def test_url_de_descarga_rechazada(url):
    assert not act.url_descarga_valida(url)


def test_redirecciones_solo_a_github():
    assert act.redireccion_permitida("https://objects.githubusercontent.com/abc")
    assert not act.redireccion_permitida("https://evil.example/abc")
    assert not act.redireccion_permitida("http://objects.githubusercontent.com/abc")


def test_sha256_de_un_archivo(tmp_path):
    archivo = tmp_path / "instalador.exe"
    archivo.write_bytes(b"contenido del instalador")
    esperado = hashlib.sha256(b"contenido del instalador").hexdigest()
    assert act.sha256_archivo(archivo) == esperado
    assert act.verificar_sha256(archivo, esperado)
    assert act.verificar_sha256(archivo, esperado.upper() + "\n")
    assert not act.verificar_sha256(archivo, "0" * 64)
    assert act.extraer_sha256(f"{esperado}  ClipStudio-Setup.exe\n") == esperado
    assert act.extraer_sha256(esperado.upper()) == esperado
    assert act.extraer_sha256("no es un hash") is None


def test_notas_en_texto_plano():
    sucio = "<img src=x onerror=alert(1)>\x00\x07 hola\r\nmundo"
    limpio = act.limpiar_notas(sucio)
    assert "\x00" not in limpio and "\x07" not in limpio and "\r" not in limpio
    assert "<img" in limpio                      # no se interpreta: el navegador lo pinta con textContent
    assert len(act.limpiar_notas("x" * 100_000)) == act.MAX_NOTAS
    assert act.limpiar_notas(None) == ""


# ---------- API con GitHub simulado ----------

class Resp:
    def __init__(self, cuerpo=b"", status=200, headers=None):
        self.cuerpo, self.status, self.headers = io.BytesIO(cuerpo), status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.cuerpo.read(n)


class GitHub:
    """Sustituye a `_abrir`: responde segun la URL y cuenta las peticiones."""

    def __init__(self):
        self.rutas: dict[str, tuple[int, bytes]] = {}
        self.peticiones: list[str] = []
        self.fallo: Exception | None = None

    def json(self, sufijo, datos, status=200):
        self.rutas[act.API + sufijo] = (status, json.dumps(datos).encode())

    def archivo(self, url, cuerpo, status=200):
        self.rutas[url] = (status, cuerpo)

    def __call__(self, url, timeout=5):
        self.peticiones.append(url)
        if self.fallo:
            raise self.fallo
        status, cuerpo = self.rutas.get(url, (404, b"{}"))
        if status >= 400:
            raise HTTPError(url, status, "x", {}, io.BytesIO(cuerpo))
        return Resp(cuerpo, status, {"Content-Length": str(len(cuerpo))})


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "clipstudio.db")
    monkeypatch.setattr(config, "ensure_dirs", lambda: tmp_path.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(config, "BUSCAR_ACTUALIZACIONES", True)
    with db.conectar() as con:
        con.executescript(db.SCHEMA)
    monkeypatch.setattr(act, "_estado", {"resultado": None, "error": None, "comprobando": False, "ultima_consulta": None})
    monkeypatch.setattr(act, "_descarga", {"estado": "inactiva"})
    monkeypatch.setattr(act, "_pendiente", {"ruta": None})
    monkeypatch.setattr(act, "modo_actual", lambda: "instalada")
    github = GitHub()
    monkeypatch.setattr(act, "_abrir", github)
    cliente = TestClient(app, base_url="http://127.0.0.1:8765")
    return cliente, github, tmp_path


def release(version="v0.99.0", instalador=True, sha=True, **extra):
    assets = []
    if instalador:
        assets.append({"name": "ClipStudio-Setup.exe", "size": 11, "browser_download_url": DESCARGA + "ClipStudio-Setup.exe"})
    if sha:
        assets.append({"name": "ClipStudio-Setup.exe.sha256", "browser_download_url": DESCARGA + "ClipStudio-Setup.exe.sha256"})
    return {"tag_name": version, "body": "Novedades <b>reales</b>", "html_url": act.URL_RELEASES + "/tag/" + version,
            "draft": False, "prerelease": False, "assets": assets, **extra}


def test_sin_releases_publicadas_no_es_un_error(entorno):
    cliente, github, _ = entorno
    r = cliente.post("/api/actualizaciones/buscar").json()          # 404: aun no hay ninguna release
    assert r["error"] is None
    assert r["resultado"]["sin_versiones"] is True and r["resultado"]["hay_actualizacion"] is False
    assert github.peticiones == [act.API + "/releases/latest"]


def test_version_nueva_instalada_y_cache(entorno):
    cliente, github, datos = entorno
    github.json("/releases/latest", release())
    r = cliente.post("/api/actualizaciones/buscar").json()
    res = r["resultado"]
    assert res["hay_actualizacion"] and res["version_nueva"] == "0.99.0" and res["version_actual"] == __version__
    assert res["notas"] == "Novedades <b>reales</b>"                # texto tal cual; la interfaz usa textContent
    assert res["instalador"]["sha256_url"].endswith(".sha256")
    cache = json.loads((datos / "actualizaciones.json").read_text(encoding="utf-8"))
    assert cache["clave"] == f"instalada:{__version__}" and cache["resultado"]["hay_actualizacion"]
    # Sin forzar, una consulta reciente no vuelve a llamar a GitHub.
    assert act.consultar(forzar=False)["resultado"]["hay_actualizacion"]
    assert len(github.peticiones) == 1
    # «Buscar ahora» ignora la cache.
    cliente.post("/api/actualizaciones/buscar")
    assert len(github.peticiones) == 2


def test_cache_en_disco_se_usa_al_reiniciar(entorno):
    cliente, github, datos = entorno
    github.json("/releases/latest", release())
    cliente.post("/api/actualizaciones/buscar")
    act._estado.update(resultado=None, ultima_consulta=None)       # como si arrancara de nuevo
    assert act.consultar()["resultado"]["hay_actualizacion"]
    assert len(github.peticiones) == 1


def test_misma_version_o_prerelease_no_se_ofrecen(entorno):
    cliente, github, _ = entorno
    for etiqueta, extra in ((f"v{__version__}", {}), ("v9.9.9-rc1", {}), ("v9.9.9", {"prerelease": True}), ("v9.9.9", {"draft": True})):
        github.json("/releases/latest", release(etiqueta, **extra))
        assert cliente.post("/api/actualizaciones/buscar").json()["resultado"]["hay_actualizacion"] is False


@pytest.mark.parametrize("fallo", [OSError("sin red"), HTTPError("u", 403, "rate limit", {}, io.BytesIO(b"{}"))])
def test_error_de_red_o_limite_no_molesta(entorno, fallo, caplog):
    cliente, github, datos = entorno
    github.fallo = fallo
    r = cliente.post("/api/actualizaciones/buscar")
    assert r.status_code == 200 and r.json()["resultado"] is None
    assert not (datos / "actualizaciones.json").exists()             # un fallo no cuenta como consulta
    github.fallo = None
    github.json("/releases/latest", {}, status=403)                  # 403 devuelto por la API
    r = cliente.post("/api/actualizaciones/buscar").json()
    assert r["error"] and r["resultado"] is None and not r["comprobando"]


def test_preferencia_y_variable_de_entorno(entorno, monkeypatch):
    cliente, _, _ = entorno
    assert cliente.get("/api/actualizaciones").json()["activada"] is True
    assert cliente.put("/api/actualizaciones/preferencia", json={"activada": False}).json()["activada"] is False
    assert db.leer_preferencia("buscar_actualizaciones") is False
    hilos = []
    monkeypatch.setattr(act.threading, "Thread", lambda *a, **k: hilos.append(1))
    act.iniciar_en_segundo_plano()
    assert not hilos                                                 # desactivada: no se consulta
    cliente.put("/api/actualizaciones/preferencia", json={"activada": True})
    monkeypatch.setattr(config, "BUSCAR_ACTUALIZACIONES", False)
    e = cliente.get("/api/actualizaciones").json()
    assert e["activada"] is False and e["desactivada_por_entorno"] is True


def test_inicio_lanza_hilo_sin_bloquear(entorno, monkeypatch):
    lanzados = []

    class Falso:
        def __init__(self, target, **k):
            self.target = target

        def start(self):
            lanzados.append(self.target)

    monkeypatch.setattr(act.threading, "Thread", Falso)
    act.iniciar_en_segundo_plano()
    assert lanzados == [act._hilo_inicial]


def test_descarga_verifica_sha256_e_instala(entorno, monkeypatch):
    cliente, github, datos = entorno
    cuerpo = b"instalador!"
    github.json("/releases/latest", release())
    github.archivo(DESCARGA + "ClipStudio-Setup.exe", cuerpo)
    github.archivo(DESCARGA + "ClipStudio-Setup.exe.sha256", f"{hashlib.sha256(cuerpo).hexdigest()}  ClipStudio-Setup.exe\n".encode())
    assert cliente.post("/api/actualizaciones/instalar").status_code == 409      # nada descargado todavia
    cliente.post("/api/actualizaciones/buscar")
    cliente.post("/api/actualizaciones/descargar")
    for _ in range(200):                                                          # el hilo de descarga es breve
        d = cliente.get("/api/actualizaciones").json()["descarga"]
        if d["estado"] != "descargando":
            break
        time.sleep(.01)
    assert d["estado"] == "lista" and d["verificado"] is True
    assert (datos / "actualizaciones" / "ClipStudio-Setup.exe").read_bytes() == cuerpo

    terminados = []
    monkeypatch.setattr(act, "_terminar_motor", lambda: terminados.append(1))
    monkeypatch.setattr(act, "_actividad", lambda: {"grabando": True, "trabajos": 2})
    r = cliente.post("/api/actualizaciones/instalar")                            # aviso de grabacion/trabajos activos
    assert r.status_code == 409 and r.json()["requiere_confirmacion"] is True and "directo" in r.json()["detail"]
    assert not act.hay_instalacion_pendiente()
    assert cliente.post("/api/actualizaciones/instalar", json={"confirmado": True}).status_code == 200
    assert act.hay_instalacion_pendiente()
    for hilo in threading.enumerate():
        if hilo.name == "cierre-actualizacion":
            hilo.join(2)

    lanzados = []
    monkeypatch.setattr(act.subprocess, "Popen", lambda cmd, **k: lanzados.append((cmd, k)))
    act.lanzar_instalador_pendiente()
    cmd, k = lanzados[0]
    assert cmd[0] == str(datos / "actualizaciones" / "ClipStudio-Setup.exe")
    assert {"/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"} <= set(cmd[1:])
    act.lanzar_instalador_pendiente()
    assert len(lanzados) == 1                                                    # una sola vez


def test_sha256_distinto_descarta_el_instalador(entorno):
    cliente, github, datos = entorno
    github.json("/releases/latest", release())
    github.archivo(DESCARGA + "ClipStudio-Setup.exe", b"instalador!")
    github.archivo(DESCARGA + "ClipStudio-Setup.exe.sha256", b"0" * 64)
    cliente.post("/api/actualizaciones/buscar")
    act._descargar(act._estado["resultado"]["instalador"], "0.99.0")
    d = act._descarga
    assert d["estado"] == "error" and "SHA-256" in d["mensaje"]
    assert not (datos / "actualizaciones" / "ClipStudio-Setup.exe").exists()
    assert cliente.post("/api/actualizaciones/instalar").status_code == 409


def test_sin_sha256_publicado_no_se_da_por_verificado(entorno):
    cliente, github, datos = entorno
    github.json("/releases/latest", release(sha=False))
    github.archivo(DESCARGA + "ClipStudio-Setup.exe", b"instalador!")
    cliente.post("/api/actualizaciones/buscar")
    assert act._estado["resultado"]["instalador"]["sha256_url"] is None
    act._descargar(act._estado["resultado"]["instalador"], "0.99.0")
    assert act._descarga["estado"] == "lista" and act._descarga["verificado"] is False
    assert "no incluye" in act._descarga["mensaje"]


def test_release_sin_instalador_no_permite_descargar(entorno):
    cliente, github, _ = entorno
    github.json("/releases/latest", release(instalador=False, sha=False))
    cliente.post("/api/actualizaciones/buscar")
    assert cliente.post("/api/actualizaciones/descargar").status_code == 409


def test_url_de_otro_repo_en_la_release_se_descarta(entorno):
    cliente, github, _ = entorno
    r = release()
    r["assets"][0]["browser_download_url"] = "https://github.com/otro/repo/releases/download/v1/ClipStudio-Setup.exe"
    github.json("/releases/latest", r)
    res = cliente.post("/api/actualizaciones/buscar").json()["resultado"]
    assert res["hay_actualizacion"] and "instalador" not in res


# ---- modo git y modo zip ----

@pytest.fixture
def git(entorno, monkeypatch):
    cliente, github, datos = entorno
    monkeypatch.setattr(act, "modo_actual", lambda: "git")
    monkeypatch.setattr(act, "_commit_local", lambda: LOCAL)
    monkeypatch.setattr(act, "_rama_actual", lambda: "main")
    github.json("/commits/main", {"sha": REMOTO})
    return cliente, github, datos


def test_git_hay_actualizacion_si_el_remoto_va_por_delante(git):
    cliente, github, _ = git
    github.json(f"/compare/{LOCAL}...{REMOTO}", {"status": "ahead", "ahead_by": 2, "commits": [
        {"commit": {"message": "Primero\ncuerpo"}}, {"commit": {"message": "Segundo"}}]})
    res = cliente.post("/api/actualizaciones/buscar").json()
    assert res["resultado"]["hay_actualizacion"] and res["resultado"]["git"]["commits"] == 2
    assert "- Segundo" in res["resultado"]["notas"]
    assert res["comandos"] == ["git pull --ff-only origin main", "uv sync"]


@pytest.mark.parametrize("status", ["behind", "diverged", "identical"])
def test_git_otros_estados_no_ofrecen(git, status):
    cliente, github, _ = git
    github.json(f"/compare/{LOCAL}...{REMOTO}", {"status": status})
    assert cliente.post("/api/actualizaciones/buscar").json()["resultado"]["hay_actualizacion"] is False


def test_git_mismo_commit_no_compara(git):
    cliente, github, _ = git
    github.json("/commits/main", {"sha": LOCAL})
    assert cliente.post("/api/actualizaciones/buscar").json()["resultado"]["hay_actualizacion"] is False
    assert not any("/compare/" in u for u in github.peticiones)


def test_git_commit_local_desconocido_en_github_no_ofrece(git):
    cliente, _, _ = git                                              # compare devuelve 404 si GitHub no conoce el commit local
    r = cliente.post("/api/actualizaciones/buscar").json()
    assert r["resultado"]["hay_actualizacion"] is False and r["error"] is None


def test_git_fuera_de_main_no_ofrece(git, monkeypatch):
    cliente, github, _ = git
    monkeypatch.setattr(act, "_rama_actual", lambda: "mi-rama")
    assert cliente.post("/api/actualizaciones/buscar").json()["resultado"]["hay_actualizacion"] is False
    assert github.peticiones == []


def test_git_con_cambios_locales_no_actualiza(git, monkeypatch):
    cliente, github, _ = git
    github.json(f"/compare/{LOCAL}...{REMOTO}", {"status": "ahead", "ahead_by": 1})
    cliente.post("/api/actualizaciones/buscar")
    llamadas = []
    monkeypatch.setattr(act, "_arbol_limpio", lambda: False)
    monkeypatch.setattr(act, "_git", lambda *a, **k: llamadas.append(a))
    r = cliente.post("/api/actualizaciones/actualizar-codigo").json()
    assert r["ok"] is False and r["motivo"] == "cambios_locales" and "cambios sin guardar" in r["mensaje"]
    assert r["comandos"] and not llamadas                             # no se ejecuto ni git pull


def test_git_arbol_limpio_hace_pull_y_uv_sync(git, monkeypatch):
    cliente, github, _ = git
    github.json(f"/compare/{LOCAL}...{REMOTO}", {"status": "ahead", "ahead_by": 1})
    cliente.post("/api/actualizaciones/buscar")
    monkeypatch.setattr(act, "_arbol_limpio", lambda: True)
    ordenes = []
    monkeypatch.setattr(act, "_git", lambda *a, **k: ordenes.append(("git",) + a) or subprocess.CompletedProcess(a, 0, "ok", ""))
    monkeypatch.setattr(act.shutil, "which", lambda nombre: "C:/uv.exe")
    monkeypatch.setattr(act.subprocess, "run", lambda cmd, **k: ordenes.append(tuple(cmd)) or subprocess.CompletedProcess(cmd, 0, "", ""))
    r = cliente.post("/api/actualizaciones/actualizar-codigo").json()
    assert r["ok"] and r["reiniciar"]
    assert ordenes == [("git", "pull", "--ff-only", "origin", "main"), ("C:/uv.exe", "sync")]
    assert cliente.get("/api/actualizaciones").json()["resultado"]["hay_actualizacion"] is False


def test_git_sin_uv_muestra_las_ordenes(git, monkeypatch):
    cliente, github, _ = git
    github.json(f"/compare/{LOCAL}...{REMOTO}", {"status": "ahead"})
    cliente.post("/api/actualizaciones/buscar")
    monkeypatch.setattr(act, "_arbol_limpio", lambda: True)
    monkeypatch.setattr(act, "_git", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(act.shutil, "which", lambda nombre: None)
    r = cliente.post("/api/actualizaciones/actualizar-codigo").json()
    assert r["ok"] is False and r["motivo"] == "sin_uv" and r["comandos"] == ["uv sync"]


def test_git_pull_fallido_no_sigue(git, monkeypatch):
    cliente, github, _ = git
    github.json(f"/compare/{LOCAL}...{REMOTO}", {"status": "ahead"})
    cliente.post("/api/actualizaciones/buscar")
    monkeypatch.setattr(act, "_arbol_limpio", lambda: True)
    monkeypatch.setattr(act, "_git", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "fatal: no es posible fast-forward"))
    monkeypatch.setattr(act.subprocess, "run", lambda *a, **k: pytest.fail("No debe ejecutar uv tras un pull fallido"))
    r = cliente.post("/api/actualizaciones/actualizar-codigo").json()
    assert r["ok"] is False and r["motivo"] == "git"


def test_zip_solo_avisa_con_enlace(entorno, monkeypatch):
    cliente, github, _ = entorno
    monkeypatch.setattr(act, "modo_actual", lambda: "zip")
    github.json("/releases/latest", release())
    e = cliente.post("/api/actualizaciones/buscar").json()
    assert e["resultado"]["hay_actualizacion"] and e["resultado"]["url_pagina"].startswith(act.URL_RELEASES)
    assert cliente.post("/api/actualizaciones/descargar").status_code == 409
    assert cliente.post("/api/actualizaciones/actualizar-codigo").status_code == 409
    assert cliente.post("/api/actualizaciones/instalar").status_code == 409


def test_peticiones_solo_a_la_api_y_con_user_agent_generico(monkeypatch):
    visto = {}

    class Opener:
        def open(self, peticion, timeout):
            visto.update(url=peticion.full_url, agente=peticion.get_header("User-agent"), timeout=timeout)
            return Resp(b"{}")

    monkeypatch.setattr(act, "build_opener", lambda *a: Opener())
    act._abrir(act.API + "/releases/latest")
    assert visto["agente"] == f"ClipStudio/{__version__}" and visto["timeout"] == 5
    assert visto["url"].startswith("https://api.github.com/")
