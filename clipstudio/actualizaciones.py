"""Buscar actualizaciones al iniciar (y aplicarlas solo cuando la persona lo pide).

Hay tres modos de instalacion:
- instalada: aplicacion empaquetada. Se compara `__version__` con la ultima GitHub Release
  y se puede descargar y ejecutar `ClipStudio-Setup.exe`.
- git: copia del codigo con `.git`. Se compara el commit local con `main` remota
  y se puede hacer `git pull --ff-only` + `uv sync` si el arbol esta limpio.
- zip: sin `.git` y sin empaquetar. Solo se avisa con un enlace a las releases.

Nada se descarga, instala ni ejecuta sin un clic explicito. Solo se habla con api.github.com
y, para descargar, con las URL `browser_download_url` de la release del propio repositorio.
Las funciones puras (sin red ni disco) estan arriba para poder probarlas aisladas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import __version__, config, db

log = logging.getLogger("clipstudio.actualizaciones")

REPO = "piniiii28/ClipStudio"
URL_REPO = f"https://github.com/{REPO}"
URL_RELEASES = f"{URL_REPO}/releases"
API = f"https://api.github.com/repos/{REPO}"
PREFIJO_DESCARGA = f"/{REPO}/releases/download/"
NOMBRE_INSTALADOR = "ClipStudio-Setup.exe"
NOMBRE_SHA256 = NOMBRE_INSTALADOR + ".sha256"
INTERVALO_S = 6 * 3600            # como mucho una consulta cada 6 horas
TIMEOUT_S = 5                     # espera de red de cada peticion
MAX_RESPUESTA = 2 * 1024 * 1024   # tope de una respuesta de la API
MAX_INSTALADOR = 2 * 1024**3      # tope razonable del instalador
MAX_NOTAS = 6000
PREFERENCIA = "buscar_actualizaciones"
CODIGO_SALIDA = 75                # el motor termina con este codigo para que la ventana se cierre
ARGS_INSTALADOR = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOSTS_REDIRECCION = {"api.github.com", "github.com", "objects.githubusercontent.com",
                     "release-assets.githubusercontent.com"}

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256 = re.compile(r"\b([0-9a-fA-F]{64})\b")


# ---------- funciones puras ----------

def parsear_version(texto: Any) -> tuple[int, int, int] | None:
    """'v0.2.0' o '0.2.0' -> (0, 2, 0). Cualquier otra forma (prerelease, basura) -> None."""
    if not isinstance(texto, str):
        return None
    m = _VERSION.match(texto.strip())
    return tuple(int(g) for g in m.groups()) if m else None  # type: ignore[return-value]


def es_version_nueva(local: str, remota: str) -> bool:
    """Comparacion semantica. Una etiqueta invalida o de prerelease nunca se ofrece."""
    a, b = parsear_version(local), parsear_version(remota)
    return a is not None and b is not None and b > a


def elegir_recurso(release: dict, nombre: str) -> dict | None:
    """Recurso de la release con ese nombre exacto (y una URL de descarga), o None."""
    for recurso in release.get("assets") or []:
        if isinstance(recurso, dict) and recurso.get("name") == nombre and isinstance(recurso.get("browser_download_url"), str):
            return recurso
    return None


def modo_instalacion(empaquetada: bool, tiene_git: bool) -> str:
    if empaquetada:
        return "instalada"
    return "git" if tiene_git else "zip"


def toca_consultar(cache: Any, ahora: float, clave: str, forzar: bool = False) -> bool:
    """False si hay una consulta reciente (menos de 6 h) para esta misma version/commit."""
    if forzar or not isinstance(cache, dict) or cache.get("clave") != clave:
        return True
    marca = cache.get("ultima_consulta")
    if not isinstance(marca, (int, float)) or isinstance(marca, bool):
        return True
    edad = ahora - marca
    return edad < 0 or edad >= INTERVALO_S   # reloj retrocedido: se vuelve a consultar


def interpretar_compare(datos: Any) -> bool:
    """True si el commit remoto trae cambios nuevos respecto al local.

    Se consulta `compare/{local}...{remoto}`: la base es el local y la cabeza el remoto,
    asi que `ahead` significa que el remoto va por delante (hay actualizacion). `behind`
    (el local tiene commits que GitHub no tiene), `diverged` e `identical` no se ofrecen.
    """
    return isinstance(datos, dict) and datos.get("status") == "ahead"


def url_descarga_valida(url: Any) -> bool:
    """Solo https://github.com/piniiii28/ClipStudio/releases/download/..."""
    if not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        p = urlparse(url)
        puerto = p.port
    except ValueError:
        return False
    if p.scheme != "https" or p.hostname != "github.com" or puerto is not None or p.username or p.password:
        return False
    ruta = p.path
    if ".." in ruta.split("/") or "%2e" in ruta.lower() or "\\" in ruta:
        return False
    return ruta.lower().startswith(PREFIJO_DESCARGA.lower()) and len(ruta) > len(PREFIJO_DESCARGA)


def redireccion_permitida(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" and (p.hostname or "") in HOSTS_REDIRECCION


def extraer_sha256(texto: str) -> str | None:
    """Saca el hash de un `.sha256` ('hash  archivo' o solo 'hash')."""
    m = _SHA256.search(texto or "")
    return m.group(1).lower() if m else None


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def verificar_sha256(ruta: Path, esperado: str) -> bool:
    return sha256_archivo(ruta) == (esperado or "").strip().lower()


def limpiar_notas(texto: Any) -> str:
    """Las notas son texto plano: sin caracteres de control y con tope de longitud."""
    if not isinstance(texto, str):
        return ""
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", texto.replace("\r\n", "\n"))
    return texto[:MAX_NOTAS]


# ---------- red (unica puerta: se sustituye en las pruebas) ----------

class _SoloGitHub(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not redireccion_permitida(newurl):
            raise HTTPError(newurl, 403, "Redireccion a un servidor no permitido.", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _abrir(url: str, timeout: float = TIMEOUT_S):
    """Abre una URL de GitHub y devuelve la respuesta (HTTPError si el estado no es 2xx)."""
    peticion = Request(url, headers={"User-Agent": f"ClipStudio/{__version__}",
                                     "Accept": "application/vnd.github+json" if url.startswith(API) else "application/octet-stream"})
    return build_opener(_SoloGitHub).open(peticion, timeout=timeout)


def _get_json(url: str) -> tuple[int, Any]:
    """GET a la API. Devuelve (estado, json). Lanza OSError si no hay red o la respuesta no es valida."""
    try:
        with _abrir(url) as r:
            estado, cuerpo = r.status, r.read(MAX_RESPUESTA + 1)
    except HTTPError as exc:
        return exc.code, None
    if len(cuerpo) > MAX_RESPUESTA:
        raise OSError("Respuesta de GitHub demasiado grande.")
    try:
        return estado, json.loads(cuerpo)
    except ValueError as exc:
        raise OSError("Respuesta de GitHub no valida.") from exc


def _get_texto(url: str) -> str:
    if not url_descarga_valida(url):
        raise OSError("URL de descarga no permitida.")
    with _abrir(url) as r:
        return r.read(65536).decode("utf-8", "replace")


# ---------- git ----------

def _git(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    entorno = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", *args], cwd=config.ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=SIN_VENTANA, env=entorno)


def _commit_local() -> str | None:
    try:
        r = _git("rev-parse", "HEAD", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def _rama_actual() -> str | None:
    try:
        r = _git("rev-parse", "--abbrev-ref", "HEAD", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _arbol_limpio() -> bool | None:
    """True si no hay cambios sin guardar (lo ignorado por .gitignore no cuenta). None si no se pudo saber."""
    try:
        r = _git("status", "--porcelain", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return (not r.stdout.strip()) if r.returncode == 0 else None


def modo_actual() -> str:
    return modo_instalacion(bool(getattr(sys, "frozen", False)), (config.ROOT / ".git").exists())


# ---------- estado y cache ----------

_lock = threading.RLock()
_estado: dict[str, Any] = {"resultado": None, "error": None, "comprobando": False, "ultima_consulta": None}
_descarga: dict[str, Any] = {"estado": "inactiva"}   # inactiva | descargando | lista | error
_pendiente: dict[str, Any] = {"ruta": None}          # instalador a lanzar al terminar el motor


def _ruta_cache() -> Path:
    return config.DATA_DIR / "actualizaciones.json"


def _carpeta() -> Path:
    return config.DATA_DIR / "actualizaciones"


def _leer_cache() -> dict | None:
    try:
        datos = json.loads(_ruta_cache().read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else None
    except (OSError, ValueError):
        return None


def _guardar_cache(datos: dict) -> None:
    try:
        config.ensure_dirs()
        temporal = _ruta_cache().with_suffix(".tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        temporal.replace(_ruta_cache())
    except OSError:
        log.warning("No se pudo guardar la cache de actualizaciones", exc_info=True)


def _clave(modo: str) -> str | None:
    """Identifica lo que hay instalado: la version (empaquetada/zip) o el commit (git)."""
    if modo == "git":
        sha = _commit_local()
        return f"git:{sha}" if sha else None
    return f"{modo}:{__version__}"


def activada() -> bool:
    if not config.BUSCAR_ACTUALIZACIONES:
        return False
    try:
        return db.leer_preferencia(PREFERENCIA, True) is not False
    except Exception:   # base de datos aun sin crear o bloqueada: por defecto, activada
        return True


def _consultar_release(modo: str) -> dict:
    estado, datos = _get_json(f"{API}/releases/latest")
    base = {"modo": modo, "hay_actualizacion": False, "version_actual": __version__, "url_pagina": URL_RELEASES}
    if estado == 404:
        return {**base, "sin_versiones": True}     # aun no hay ninguna release publicada
    if estado != 200 or not isinstance(datos, dict):
        raise OSError(f"GitHub respondio {estado} al buscar la ultima version.")
    etiqueta = datos.get("tag_name")
    if datos.get("draft") or datos.get("prerelease") or parsear_version(etiqueta) is None:
        return base
    nueva = es_version_nueva(__version__, etiqueta)
    resultado = {**base, "hay_actualizacion": nueva, "version_nueva": etiqueta.lstrip("v"),
                 "url_pagina": datos.get("html_url") if isinstance(datos.get("html_url"), str) and datos["html_url"].startswith(URL_RELEASES) else URL_RELEASES}
    if nueva:
        resultado["notas"] = limpiar_notas(datos.get("body"))
        instalador = elegir_recurso(datos, NOMBRE_INSTALADOR)
        if instalador and url_descarga_valida(instalador["browser_download_url"]):
            sha = elegir_recurso(datos, NOMBRE_SHA256)
            resultado["instalador"] = {
                "url": instalador["browser_download_url"],
                "tamano": instalador.get("size") if isinstance(instalador.get("size"), int) else None,
                "sha256_url": sha["browser_download_url"] if sha and url_descarga_valida(sha["browser_download_url"]) else None,
            }
    return resultado


def _consultar_git(modo: str, local: str) -> dict:
    base = {"modo": modo, "hay_actualizacion": False, "version_actual": __version__, "url_pagina": URL_RELEASES,
            "git": {"local": local[:7]}}
    rama = _rama_actual()
    if rama != "main":
        log.info("Actualizaciones: la rama actual es %r, no main; no se ofrece actualizar.", rama)
        return base
    estado, datos = _get_json(f"{API}/commits/main")
    if estado != 200 or not isinstance(datos, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(datos.get("sha", ""))):
        raise OSError(f"GitHub respondio {estado} al buscar el ultimo commit.")
    remoto = datos["sha"]
    base["git"]["remoto"] = remoto[:7]
    if remoto == local:
        return base
    estado, comp = _get_json(f"{API}/compare/{local}...{remoto}")
    if estado == 404:
        return base     # el commit local no existe en GitHub (trabajo propio sin publicar)
    if estado != 200:
        raise OSError(f"GitHub respondio {estado} al comparar commits.")
    base["git"]["estado"] = comp.get("status") if isinstance(comp, dict) else None
    base["hay_actualizacion"] = interpretar_compare(comp)
    if base["hay_actualizacion"] and isinstance(comp, dict):
        base["git"]["commits"] = comp.get("ahead_by") if isinstance(comp.get("ahead_by"), int) else None
        mensajes = [c.get("commit", {}).get("message", "").split("\n")[0] for c in (comp.get("commits") or [])[-10:] if isinstance(c, dict)]
        base["notas"] = limpiar_notas("\n".join("- " + m for m in reversed(mensajes) if m))
    return base


def consultar(forzar: bool = False) -> dict:
    """Consulta GitHub si toca (o si se fuerza) y devuelve el estado publico. Nunca lanza por errores de red."""
    modo = modo_actual()
    with _lock:
        if _estado["comprobando"]:
            return estado_publico()
        clave = _clave(modo)
        if clave is None:
            log.warning("Actualizaciones: no se pudo leer el commit local (git no disponible).")
            _estado["error"] = "No se pudo leer el estado de git en esta copia."
            return estado_publico()
        cache = _leer_cache()
        if not toca_consultar(cache, time.time(), clave, forzar):
            if _estado["resultado"] is None and isinstance(cache, dict) and isinstance(cache.get("resultado"), dict):
                _estado.update(resultado=cache["resultado"], ultima_consulta=cache.get("ultima_consulta"))
            return estado_publico()
        _estado.update(comprobando=True, error=None)
    try:
        resultado = _consultar_git(modo, clave[4:]) if modo == "git" else _consultar_release(modo)
        ahora = time.time()
        with _lock:
            _estado.update(resultado=resultado, ultima_consulta=ahora)
        _guardar_cache({"ultima_consulta": ahora, "clave": clave, "modo": modo, "resultado": resultado})
        log.info("Actualizaciones: consulta hecha (modo %s, hay_actualizacion=%s).", modo, resultado["hay_actualizacion"])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Sin red, 403 por limite de peticiones, etc.: se registra y se sigue sin molestar.
        log.warning("Actualizaciones: no se pudo consultar GitHub: %s", exc)
        with _lock:
            _estado["error"] = "No se pudo consultar GitHub. Comprueba tu conexion e intentalo mas tarde."
    finally:
        with _lock:
            _estado["comprobando"] = False
    return estado_publico()


def iniciar_en_segundo_plano() -> None:
    """Se llama al arrancar: lanza la comprobacion en un hilo y vuelve de inmediato."""
    try:
        if not activada():
            log.info("Actualizaciones: busqueda al iniciar desactivada.")
            return
    except Exception:
        log.warning("Actualizaciones: no se pudo leer la preferencia.", exc_info=True)
        return
    threading.Thread(target=_hilo_inicial, name="actualizaciones", daemon=True).start()


def _hilo_inicial() -> None:
    try:
        consultar(forzar=False)
    except Exception:
        log.exception("Actualizaciones: error inesperado en la comprobacion inicial")


def estado_publico() -> dict:
    with _lock:
        resultado = _estado["resultado"]
        publico = {
            "modo": modo_actual(),
            "version_actual": __version__,
            "activada": activada(),
            "desactivada_por_entorno": not config.BUSCAR_ACTUALIZACIONES,
            "comprobando": _estado["comprobando"],
            "ultima_consulta": _estado["ultima_consulta"],
            "error": _estado["error"],
            "resultado": resultado,
            "descarga": dict(_descarga),
            "url_releases": URL_RELEASES,
        }
    if resultado and resultado.get("modo") == "git" and resultado.get("hay_actualizacion"):
        publico["comandos"] = COMANDOS_MANUALES
    return publico


# ---------- descarga e instalacion (modo instalada) ----------

COMANDOS_MANUALES = ["git pull --ff-only origin main", "uv sync"]


def _fallo_descarga(mensaje: str) -> None:
    with _lock:
        _descarga.clear()
        _descarga.update(estado="error", mensaje=mensaje)


def _descargar(instalador: dict, version: str) -> None:
    try:
        destino_dir = _carpeta()
        if destino_dir.exists():
            shutil.rmtree(destino_dir, ignore_errors=True)   # versiones anteriores ya descargadas
        destino_dir.mkdir(parents=True, exist_ok=True)
        parcial = destino_dir / (NOMBRE_INSTALADOR + ".part")
        esperado = None
        if instalador.get("sha256_url"):
            esperado = extraer_sha256(_get_texto(instalador["sha256_url"]))
            if not esperado:
                return _fallo_descarga("El archivo de verificacion SHA-256 de la publicacion no es valido. No se instalara nada.")
        total = instalador.get("tamano")
        if total and total > MAX_INSTALADOR:
            return _fallo_descarga("El instalador publicado es demasiado grande.")
        with _abrir(instalador["url"], timeout=30) as r, open(parcial, "wb") as f:
            cabecera = r.headers.get("Content-Length") if getattr(r, "headers", None) else None
            if cabecera and cabecera.isdigit():
                total = int(cabecera)
            if total and total > MAX_INSTALADOR:
                return _fallo_descarga("El instalador publicado es demasiado grande.")
            recibido = 0
            with _lock:
                _descarga.update(total=total, recibido=0)
            while True:
                bloque = r.read(256 * 1024)
                if not bloque:
                    break
                recibido += len(bloque)
                if recibido > MAX_INSTALADOR:
                    return _fallo_descarga("El instalador publicado es demasiado grande.")
                f.write(bloque)
                with _lock:
                    _descarga["recibido"] = recibido
        if total and recibido != total:
            parcial.unlink(missing_ok=True)
            return _fallo_descarga("La descarga se interrumpio antes de terminar. Vuelve a intentarlo.")
        if esperado and not verificar_sha256(parcial, esperado):
            parcial.unlink(missing_ok=True)
            return _fallo_descarga("La suma SHA-256 del instalador no coincide con la publicada. Se descartó el archivo.")
        final = destino_dir / NOMBRE_INSTALADOR
        parcial.replace(final)
        with _lock:
            _descarga.clear()
            _descarga.update(estado="lista", ruta=str(final), version=version, recibido=recibido, total=recibido,
                             verificado=bool(esperado), sha256=esperado,
                             mensaje=("Integridad verificada con SHA-256." if esperado else
                                      "La publicación no incluye suma SHA-256: no se pudo verificar la integridad del instalador."))
    except Exception as exc:
        log.warning("Actualizaciones: fallo la descarga: %s", exc)
        _fallo_descarga("No se pudo descargar el instalador. Comprueba tu conexion e intentalo de nuevo.")


def iniciar_descarga() -> dict:
    with _lock:
        resultado = _estado["resultado"]
        if modo_actual() != "instalada":
            raise HTTPException(409, "La descarga del instalador solo existe en la aplicación instalada.")
        if not resultado or not resultado.get("hay_actualizacion") or not resultado.get("instalador"):
            raise HTTPException(409, "No hay un instalador publicado para descargar.")
        if _descarga.get("estado") == "descargando":
            return estado_publico()
        _descarga.clear()
        _descarga.update(estado="descargando", recibido=0, total=resultado["instalador"].get("tamano"))
        hilo = threading.Thread(target=_descargar, args=(resultado["instalador"], resultado["version_nueva"]),
                                name="descarga-actualizacion", daemon=True)
    hilo.start()
    return estado_publico()


def _actividad() -> dict:
    from . import vivo
    from .pipeline import gestor
    sesion = vivo.sesion_actual()
    return {"grabando": bool(sesion and sesion.estado in ("conectando", "grabando")),
            "trabajos": gestor.cantidad_activos()}


def hay_instalacion_pendiente() -> bool:
    return bool(_pendiente["ruta"])


def lanzar_instalador_pendiente() -> None:
    """Se llama cuando el motor ya paro sus trabajos: arranca el instalador (una sola vez)."""
    ruta = _pendiente["ruta"]
    _pendiente["ruta"] = None
    if not ruta:
        return
    try:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([ruta, *ARGS_INSTALADOR], cwd=str(Path(ruta).parent), close_fds=True, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info("Actualizaciones: instalador lanzado.")
    except OSError:
        log.exception("Actualizaciones: no se pudo ejecutar el instalador")


def _terminar_motor() -> None:
    time.sleep(.5)   # deja responder a la peticion antes de parar
    from .api import app
    parar = getattr(app.state, "desktop_shutdown", None)
    if parar:
        parar()
    else:
        signal.raise_signal(signal.SIGINT)   # servidor lanzado sin ventana (uvicorn en el hilo principal)


def preparar_instalacion(confirmado: bool) -> JSONResponse | dict:
    with _lock:
        if modo_actual() != "instalada":
            raise HTTPException(409, "Instalar solo es posible en la aplicación instalada.")
        ruta = _descarga.get("ruta") if _descarga.get("estado") == "lista" else None
        verificado = bool(_descarga.get("verificado"))
        esperado = _descarga.get("sha256")
    if not ruta or Path(ruta).resolve().parent != _carpeta().resolve() or not Path(ruta).is_file():
        raise HTTPException(409, "Primero descarga el instalador.")
    if verificado and not verificar_sha256(Path(ruta), esperado):
        raise HTTPException(409, "El instalador descargado ya no coincide con su suma SHA-256. Descárgalo de nuevo.")
    if not confirmado:
        from . import desktop
        aviso = desktop.mensaje_cierre(_actividad(), True)
        if aviso:
            aviso = aviso.replace("Puedes minimizar la ventana para que continúen. ¿Cerrar de todos modos?",
                                  "¿Instalar y reiniciar de todos modos?")
            return JSONResponse({"detail": aviso, "requiere_confirmacion": True}, status_code=409)
    _pendiente["ruta"] = ruta
    threading.Thread(target=_terminar_motor, name="cierre-actualizacion", daemon=True).start()
    return {"ok": True, "mensaje": "Instalando. ClipStudio se cerrará y volverá a abrirse solo."}


# ---------- actualizacion de la copia del codigo (modo git) ----------

def _cola(texto: str, n: int = 800) -> str:
    return texto.strip()[-n:]


def actualizar_codigo() -> dict:
    if modo_actual() != "git":
        raise HTTPException(409, "Esta copia no usa git.")
    with _lock:
        resultado = _estado["resultado"]
    if not resultado or not resultado.get("hay_actualizacion") or resultado.get("modo") != "git":
        raise HTTPException(409, "No hay una actualización pendiente.")
    limpio = _arbol_limpio()
    if limpio is None:
        raise HTTPException(500, "No se pudo leer el estado de git.")
    if not limpio:
        return {"ok": False, "motivo": "cambios_locales", "comandos": COMANDOS_MANUALES,
                "mensaje": "Hay cambios sin guardar en git en esta copia, así que no se actualiza automáticamente. "
                           "Guárdalos (commit) o apártalos (git stash) y ejecuta estas órdenes en la carpeta del proyecto."}
    try:
        pull = _git("pull", "--ff-only", "origin", "main", timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(500, f"No se pudo ejecutar git: {exc}") from exc
    if pull.returncode != 0:
        return {"ok": False, "motivo": "git", "comandos": COMANDOS_MANUALES,
                "mensaje": "git no pudo actualizar sin conflictos. " + _cola(pull.stderr or pull.stdout)}
    uv = shutil.which("uv")
    if not uv:
        mensaje = "Código actualizado, pero no se encontró uv. Ejecuta «uv sync» en la carpeta del proyecto y reinicia ClipStudio."
        motivo, comandos = "sin_uv", ["uv sync"]
    else:
        try:
            sync = subprocess.run([uv, "sync"], cwd=config.ROOT, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=900, creationflags=SIN_VENTANA)
        except (OSError, subprocess.SubprocessError) as exc:
            sync = None
            error_sync = str(exc)
        if sync is not None and sync.returncode == 0:
            mensaje, motivo, comandos = "Actualizado. Cierra y vuelve a abrir ClipStudio para usar la versión nueva.", None, []
        else:
            detalle = _cola(sync.stderr or sync.stdout) if sync is not None else error_sync
            mensaje = f"Código actualizado, pero «uv sync» falló: {detalle} Ejecútalo a mano y reinicia ClipStudio."
            motivo, comandos = "uv", ["uv sync"]
    with _lock:
        _estado["resultado"] = {**resultado, "hay_actualizacion": False}
    _ruta_cache().unlink(missing_ok=True)
    log.info("Actualizaciones: codigo actualizado (%s).", motivo or "ok")
    return {"ok": motivo is None, "motivo": motivo, "comandos": comandos, "mensaje": mensaje, "reiniciar": True}


# ---------- API ----------

router = APIRouter(prefix="/api/actualizaciones")


class PreferenciaActualizaciones(BaseModel):
    activada: bool


class Instalar(BaseModel):
    confirmado: bool = False


@router.get("")
def ver_actualizaciones() -> dict:
    return estado_publico()


@router.post("/buscar")
def buscar_actualizaciones() -> dict:
    return consultar(forzar=True)


@router.post("/descargar")
def descargar_actualizacion() -> dict:
    return iniciar_descarga()


@router.post("/instalar")
def instalar_actualizacion(datos: Instalar = Instalar()):
    return preparar_instalacion(datos.confirmado)


@router.post("/actualizar-codigo")
def actualizar_codigo_ruta() -> dict:
    return actualizar_codigo()


@router.put("/preferencia")
def guardar_preferencia(datos: PreferenciaActualizaciones) -> dict:
    db.guardar_preferencia(PREFERENCIA, datos.activada)
    return estado_publico()
