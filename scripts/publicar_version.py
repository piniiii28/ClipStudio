"""Publica una version nueva de ClipStudio (para el mantenedor).

Uso:
    uv run python scripts/publicar_version.py 0.2.0 [--notas ARCHIVO.md] [--sin-publicar]

Pasos: comprueba que el arbol de git esta limpio, sube la version en clipstudio/__init__.py y
pyproject.toml, ejecuta las pruebas, compila con scripts/compilar_escritorio.py, calcula el SHA-256
del instalador, crea el commit y la etiqueta v0.2.0 y publica la release con `gh`.

Pide confirmacion por consola antes de cada paso que publica algo (git push y gh release create).
Con --sin-publicar se detiene tras crear el commit y la etiqueta locales.
Requisitos: Windows, git, gh (con sesion iniciada), Inno Setup (iscc o CLIPSTUDIO_ISCC) y las
dependencias de desarrollo (uv sync).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
INIT = RAIZ / "clipstudio" / "__init__.py"
PYPROJECT = RAIZ / "pyproject.toml"
DIST = RAIZ / "dist"
INSTALADOR = DIST / "ClipStudio-Setup.exe"
SHA256 = DIST / "ClipStudio-Setup.exe.sha256"
RAMA = "main"


def parsear(version: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not m:
        raise SystemExit(f"Version no valida: {version!r}. Usa el formato 0.2.0 (sin prefijo v ni sufijos).")
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def ejecutar(*cmd: str, capturar: bool = False) -> str:
    print("$ " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=RAIZ, check=True, text=True, encoding="utf-8", capture_output=capturar)
    return (r.stdout or "").strip() if capturar else ""


def confirmar(pregunta: str) -> None:
    if input(f"\n{pregunta} [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
        raise SystemExit("Cancelado. Nada mas se ha publicado.")


def version_actual() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', INIT.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("No se encontro __version__ en clipstudio/__init__.py.")
    return m.group(1)


def escribir_version(version: str) -> None:
    for ruta, patron, nuevo in (
        (INIT, r'(__version__\s*=\s*")[^"]+(")', rf'\g<1>{version}\g<2>'),
        (PYPROJECT, r'(?m)^(version\s*=\s*")[^"]+(")', rf'\g<1>{version}\g<2>'),
    ):
        texto = ruta.read_text(encoding="utf-8", newline="")
        cambiado, n = re.subn(patron, nuevo, texto, count=1)
        if n != 1:
            raise SystemExit(f"No se pudo actualizar la version en {ruta.name}.")
        ruta.write_text(cambiado, encoding="utf-8", newline="")


def notas_por_defecto(version: str) -> Path:
    """Borrador con los asuntos de los commits desde la ultima etiqueta; se revisa antes de publicar."""
    try:
        ultima = ejecutar("git", "describe", "--tags", "--abbrev=0", capturar=True)
        rango = [f"{ultima}..HEAD"]
    except subprocess.CalledProcessError:
        rango = []
    asuntos = ejecutar("git", "log", "--pretty=- %s", *rango, capturar=True)
    DIST.mkdir(exist_ok=True)
    ruta = DIST / f"notas-v{version}.md"
    ruta.write_text(f"Novedades de ClipStudio {version}\n\n{asuntos}\n", encoding="utf-8")
    return ruta


def main() -> int:
    ap = argparse.ArgumentParser(description="Publica una version nueva de ClipStudio.")
    ap.add_argument("version", help="version nueva, por ejemplo 0.2.0")
    ap.add_argument("--notas", type=Path, help="archivo con las notas de la release (texto o Markdown)")
    ap.add_argument("--sin-publicar", action="store_true", help="crea commit y etiqueta locales y se detiene")
    args = ap.parse_args()

    nueva = parsear(args.version)
    actual = version_actual()
    if nueva <= parsear(actual):
        raise SystemExit(f"La version nueva ({args.version}) debe ser mayor que la actual ({actual}).")
    etiqueta = f"v{args.version}"
    for herramienta in ("git", "gh"):
        if not shutil.which(herramienta):
            raise SystemExit(f"Falta {herramienta} en el PATH.")
    if ejecutar("git", "status", "--porcelain", capturar=True):
        raise SystemExit("El arbol de git no esta limpio. Guarda o descarta los cambios primero.")
    if ejecutar("git", "rev-parse", "--abbrev-ref", "HEAD", capturar=True) != RAMA:
        raise SystemExit(f"Publica desde la rama {RAMA}.")
    if ejecutar("git", "tag", "--list", etiqueta, capturar=True):
        raise SystemExit(f"La etiqueta {etiqueta} ya existe.")
    if args.notas and not args.notas.is_file():
        raise SystemExit(f"No existe el archivo de notas: {args.notas}")

    originales = {ruta: ruta.read_bytes() for ruta in (INIT, PYPROJECT)}
    try:
        escribir_version(args.version)
        ejecutar(sys.executable, "-m", "pytest", "-q")
        INSTALADOR.unlink(missing_ok=True)
        ejecutar(sys.executable, str(RAIZ / "scripts" / "compilar_escritorio.py"))
        if not INSTALADOR.is_file():
            raise SystemExit("No se genero dist/ClipStudio-Setup.exe. Define CLIPSTUDIO_ISCC (o pon iscc en el PATH) y reintenta.")
    except BaseException:
        for ruta, contenido in originales.items():   # deja la version como estaba si algo falla
            ruta.write_bytes(contenido)
        raise

    hash_ = hashlib.sha256(INSTALADOR.read_bytes()).hexdigest()
    SHA256.write_text(f"{hash_}  {INSTALADOR.name}\n", encoding="utf-8")
    print(f"\nSHA-256 del instalador: {hash_}")

    notas = args.notas or notas_por_defecto(args.version)
    print(f"Notas de la release: {notas}")
    if not args.notas:
        print("Es un borrador con los asuntos de los commits. Editalo ahora si quieres cambiarlo.")
    confirmar(f"Crear el commit «Version {args.version}» y la etiqueta {etiqueta} (solo local)?")
    ejecutar("git", "add", str(INIT), str(PYPROJECT))
    ejecutar("git", "commit", "-m", f"Version {args.version}")
    ejecutar("git", "tag", "-a", etiqueta, "-m", f"ClipStudio {args.version}")
    if args.sin_publicar:
        print(f"Listo en local. Para publicar: git push origin {RAMA} {etiqueta} y gh release create {etiqueta} ...")
        return 0

    confirmar(f"PUBLICAR: git push origin {RAMA} {etiqueta} (sube el commit y la etiqueta a GitHub)?")
    ejecutar("git", "push", "origin", RAMA, etiqueta)
    confirmar(f"PUBLICAR: crear la release {etiqueta} en GitHub con el instalador y su SHA-256?")
    ejecutar("gh", "release", "create", etiqueta, str(INSTALADOR), str(SHA256),
             "--title", f"ClipStudio {args.version}", "--notes-file", str(notas))
    print(f"\nRelease {etiqueta} publicada. Las instalaciones la veran en su proxima busqueda (como mucho en 6 h).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
