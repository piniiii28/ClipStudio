@echo off
rem Arranca ClipStudio en su propia ventana de escritorio.
cd /d "%~dp0"
uv run python -m clipstudio --escritorio
pause
