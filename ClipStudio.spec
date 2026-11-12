# Compilar con: uv run pyinstaller --noconfirm ClipStudio.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

raiz = Path(SPECPATH)
datos = [(str(raiz / 'clipstudio' / 'web'), 'clipstudio/web'),
         (str(raiz / 'clipstudio' / 'modelos'), 'clipstudio/modelos'),
         (str(raiz / 'build' / 'assets'), 'assets')]
for paquete in ('faster_whisper', 'yt_dlp', 'certifi'):
    datos += collect_data_files(paquete)
datos += collect_data_files('cv2', includes=['data/*.xml'])
for paquete in ('pywebview', 'yt-dlp', 'faster-whisper'):
    datos += copy_metadata(paquete)
binarios = [(str(raiz / 'build' / 'bin' / nombre), 'bin') for nombre in ('ffmpeg.exe', 'ffprobe.exe', 'node.exe')]
ocultos = collect_submodules('uvicorn') + collect_submodules('yt_dlp')
ocultos += ['webview.platforms.winforms', 'webview.platforms.edgechromium', 'clr_loader', 'pythonnet', 'cv2.data']
a = Analysis([str(raiz / 'scripts' / 'desktop_entry.py')], pathex=[str(raiz)],
             binaries=binarios, datas=datos, hiddenimports=ocultos,
             excludes=['pytest', 'tkinter', 'matplotlib', 'torch', 'scipy', 'IPython', 'notebook'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ClipStudio',
          console=False, icon=str(raiz / 'build' / 'assets' / 'clipstudio.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ClipStudio')
