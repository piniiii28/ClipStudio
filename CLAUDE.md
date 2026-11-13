# Normas de trabajo en ClipStudio

Válidas para cualquier persona o agente (Claude, Codex u otros) que modifique el proyecto.

## La aplicación de escritorio es la referencia

**Todo cambio se da por terminado solo cuando se ve y funciona en la aplicación de escritorio
de Windows**, no en la versión de navegador (`http://127.0.0.1:8765`).

- Comprueba los cambios de interfaz abriendo la app de escritorio (`iniciar.bat`,
  `uv run python -m clipstudio --escritorio` o el ejecutable compilado), no solo en Chrome.
- La ventana de escritorio usa WebView2, con su propia caché y su propio motor. Algo que se ve
  bien en el navegador puede no verse igual allí (caché de la interfaz, reproductores
  incrustados, diálogos, descargas, cierre de la ventana).
- Para cambios que llegan a usuarios, prueba también el instalador o el portable compilado
  (`scripts/compilar_escritorio.py`), que es lo que reciben las personas.
- Las pruebas en el navegador sin ventana (CDP) sirven como apoyo automático, pero no
  sustituyen la comprobación en la app de escritorio. Si no se pudo comprobar allí, dilo
  explícitamente en el informe.

## Publicar

- Las versiones se publican con `uv run python scripts/publicar_version.py X.Y.Z`; cada versión
  se documenta en `CHANGELOG.md`.
- El repositorio es público: no subas análisis de productos de terceros (`docs/informe-rea.md`,
  `docs/codex/`), rutas personales, correos, compilados (`dist/`, `build/`), restos de pruebas
  ni videos o modelos pesados.
