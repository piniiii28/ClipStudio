"""Construye la carpeta portable y, si ISCC esta disponible, el instalador Windows."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clipstudio import __version__, config


def main() -> int:
    from PIL import Image, ImageDraw

    if sys.platform != 'win32':
        raise SystemExit('Esta compilacion se ejecuta en Windows x64.')
    assets = ROOT / 'build' / 'assets'
    binarios = ROOT / 'build' / 'bin'
    assets.mkdir(parents=True, exist_ok=True)
    binarios.mkdir(parents=True, exist_ok=True)
    for nombre in ('ffmpeg', 'ffprobe', 'node'):
        origen = config.find_tool(nombre)
        if not origen:
            raise SystemExit(f'Falta {nombre}. Instalalo antes de compilar.')
        shutil.copy2(origen, binarios / (nombre + '.exe'))
    icono = Image.new('RGBA', (256, 256), (15, 17, 21, 255))
    dibujo = ImageDraw.Draw(icono)
    dibujo.rounded_rectangle((56, 16, 200, 240), radius=44, fill='#f9be36')
    dibujo.polygon([(108, 84), (108, 172), (170, 128)], fill='#171a20')
    icono.save(assets / 'clipstudio.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    # Conserva avisos de licencias y versiones de los componentes redistribuidos.
    licencias = assets / 'licencias'
    licencias.mkdir(exist_ok=True)
    versiones = {}
    for distribucion in importlib.metadata.distributions():
        nombre = distribucion.metadata['Name']
        versiones[nombre] = distribucion.version
        for archivo in distribucion.files or []:
            if any(p.lower().startswith(('license', 'copying', 'notice')) for p in archivo.parts):
                fuente = Path(distribucion.locate_file(archivo))
                if fuente.is_file():
                    destino = licencias / nombre / str(archivo)
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(fuente, destino)
    (assets / 'componentes.json').write_text(json.dumps(versiones, indent=2), encoding='utf-8')
    shutil.copy2(ROOT / 'docs' / 'ESCRITORIO.md', assets / 'LEEME.md')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(ROOT / 'ClipStudio.spec')], cwd=ROOT, check=True)
    iscc = os.environ.get('CLIPSTUDIO_ISCC') or shutil.which('iscc')
    if iscc:
        subprocess.run([iscc, f'/DVersion={__version__}', str(ROOT / 'scripts' / 'instalador.iss')], cwd=ROOT, check=True)
    else:
        print('Portable listo: dist/ClipStudio/ClipStudio.exe. Para instalador: define CLIPSTUDIO_ISCC y vuelve a compilar.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
