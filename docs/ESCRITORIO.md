# ClipStudio para Windows

Actualizado: **2026-11-12**. Primera versión de escritorio instalada y comprobada en este
equipo. Estado completo de funciones y pendientes: [estado.md](estado.md).

## Abrir e instalar

Abre `ClipStudio.exe` dentro de la carpeta portable completa, o instala con `ClipStudio-Setup.exe`. Requiere Windows 10/11 x64 y Microsoft Edge WebView2 Runtime (incluido normalmente en Windows 11). Si falta, instala el runtime desde https://developer.microsoft.com/microsoft-edge/webview2/.

Incluye Python, FFmpeg, ffprobe y Node.js. No necesitas abrir una terminal ni instalar Python. El modelo de transcripción se descarga la primera vez que lo necesites; los directos requieren conexión a Internet.

El instalador funciona por usuario y deja el programa en
`%LOCALAPPDATA%\Programs\ClipStudio`. Añade una entrada al menú Inicio y permite crear un
acceso directo en el escritorio; en este equipo ya se creó **ClipStudio**. La versión
portable y el instalador se generan en `dist/`, fuera de Git.

Conserva toda la carpeta portable: `ClipStudio.exe` depende de `_internal`, donde están
Python, la interfaz, los modelos de detección, bibliotecas y herramientas. No es un `.exe`
independiente que puedas mover solo.

## Proyectos, grabación y cierre

Los proyectos, modelos y ajustes permanecen en `%LOCALAPPDATA%\ClipStudio`. La app de escritorio comparte los datos con la versión de navegador. No ejecutes dos motores con esa misma carpeta. Un segundo doble clic muestra la ventana existente.

Minimiza la ventana para que la grabación y las exportaciones continúen. Al cerrar, se guardan los cambios del editor y se avisa antes de parar una grabación o cancelar trabajos. Los clips guardados se conservan; el búfer del directo se elimina al pararlo. Si se conecta a un servidor que ya estaba abierto, cerrar la ventana deja ese servidor funcionando.

Las descargas de clips abren el selector para guardar el archivo. La ventana usa WebView2; la interfaz sigue siendo la misma y el procesamiento es local. Busca actualizaciones al iniciar (ver más abajo) pero nunca instala nada sin tu clic. Esta primera compilación no está firmada digitalmente.

El modo **En vivo** conserva el chat de Twitch, YouTube y Kick, los gráficos, la imagen del
búfer y los encuadres de cámara/gameplay. La imagen se actualiza por segmentos, aproximadamente
cada 6 s; no es reproducción continua. Solo hay una captura activa por motor.

En cada clip, **TikTok → Recomendar hashtags** genera hasta cinco etiquetas temáticas.
Puedes indicar el juego o tema, editar el resultado y copiarlo; contexto y bloque se guardan
con el clip. Funciona localmente a partir de texto y cortes, sin analizar la imagen ni
consultar tendencias. No garantiza alcance ni publica en TikTok.

Desinstalar elimina el programa, pero conserva `%LOCALAPPDATA%\ClipStudio`. Compartir esa
carpeta entre las dos interfaces no crea una copia independiente de tus proyectos.

## Configuración y diagnóstico

Los registros están en `ventana.log` y `escritorio.log`, en la carpeta de datos. El archivo `.env` opcional puede ir junto al ejecutable.

| Síntoma | Comprobación |
|---|---|
| La ventana no aparece o informa de WebView2 | Comprueba el runtime y revisa `ventana.log` |
| La ventana abre, pero el motor no responde | Revisa `escritorio.log`, el puerto 8765 y si otra instancia usa esos datos |
| La imagen del directo sigue esperando | Espera al primer segmento; un servidor antiguo necesita reiniciarse con el código actualizado |
| Los cambios del código no aparecen en la app instalada | Recompila y reinstala; editar Python no modifica el ejecutable |
| Una segunda apertura no crea ventana nueva | Es el comportamiento previsto: activa la existente |
| Cerrar deja un servidor funcionando | La ventana reutilizó un motor previo; detén ese servidor desde su terminal si quieres apagarlo |

Reiniciar el motor interrumpe una captura. Guarda primero los clips necesarios y para el
directo; el búfer no se recupera después de pararlo. La app no reanuda grabaciones por sí sola.

Para actualizar la instalación, cierra la app, genera el paquete nuevo y vuelve a ejecutar
el instalador. Los proyectos permanecen en la carpeta de datos. El `.env` del desarrollo se
lee desde la raíz del proyecto; el del paquete se lee junto al ejecutable.

## Desarrollo

Instala las dependencias con `uv sync` y después abre `iniciar.bat`, o ejecuta:

```powershell
uv run python -m clipstudio --escritorio
```

`uv run python -m clipstudio` conserva el modo de navegador y `--no-abrir` arranca solo el
servidor. Desde el código se necesitan FFmpeg/ffprobe disponibles y Node.js para los usos de
YouTube que lo requieran; la versión empaquetada los incluye.

Para compilar: `uv run python scripts/compilar_escritorio.py`. Necesita FFmpeg, ffprobe y Node disponibles. Genera `dist/ClipStudio/ClipStudio.exe` con sus dependencias. Con `CLIPSTUDIO_ISCC` apuntando a ISCC.exe de Inno Setup también genera el instalador. No se debe distribuir el ejecutable portable sin su carpeta `_internal`.

Ejemplo para generar también el instalador con un compilador Inno Setup disponible:

```powershell
$env:CLIPSTUDIO_ISCC = 'RUTA\A\ISCC.exe'
uv run python scripts/compilar_escritorio.py
```

`ClipStudio.spec` incluye interfaz, YuNet, clasificadores XML de OpenCV, assets de Whisper,
WebView2 y módulos dinámicos de Uvicorn/yt-dlp. `scripts/desktop_entry.py` es la entrada del
ejecutable y `scripts/instalador.iss` define la instalación por usuario.

El proceso de ventana administra un servidor hijo. El cierre HTTP del motor propio requiere
un token aleatorio y el servidor vigila la salida de su padre. Los lectores de YouTube usan
un modo worker del mismo ejecutable; el resto del flujo conserva la API local existente.

## Verificación y límites de esta entrega

La última ronda del 12 de noviembre pasó **156 pruebas automatizadas**, **31/31** comprobaciones
de directo simulado y **80/80** del flujo integral, las dos últimas usando `--ejecutable`:

Después, la batería automatizada se amplió a **169/169** al añadir hashtags y persistencia
por clip. Las cifras de 31/80 corresponden a la ronda anterior de escritorio.

```powershell
uv run pytest -q
uv run python scripts/prueba_vivo.py --ejecutable dist/ClipStudio/ClipStudio.exe
uv run python scripts/prueba_e2e.py RUTA_VIDEO --ejecutable dist/ClipStudio/ClipStudio.exe
```

Para la prueba integral completa usa un video con voz de unos 90 s. Las pruebas aíslan sus
datos y usan puertos 8798/8799. Se comprobaron visualmente proyectos, editor y reproducción,
apertura duplicada, cierre desde el editor y reapertura de la app instalada. El ejecutable
instalado coincide con el portable y la instalación terminó sin reiniciar Windows.

Quedan pendientes pruebas en Windows limpio, ausencia de WebView2, uso prolongado, firma y
actualizaciones. Las verificaciones reales de Twitch/YouTube/Kick de la implementación anterior
no se repitieron como prueba de red del instalador. La reconexión automática de la captura de
video sigue pendiente aunque los lectores de chat sí se reconectan.

Las licencias de dependencias están en `_internal/assets/licencias`; FFmpeg usa la licencia de su compilación. Para redistribuir, conserva sus avisos y proporciona acceso al código fuente correspondiente, según su licencia. Esta compilación está preparada para uso local.

## Actualizaciones

Al iniciar, en segundo plano y como mucho cada 6 horas, ClipStudio consulta `api.github.com`
(User-Agent `ClipStudio/<versión>`, sin datos personales, espera de red de 5 s). Si no hay red o
GitHub responde con error, lo registra en el log y sigue sin avisar. El resultado y la marca de
tiempo se guardan en `actualizaciones.json`, en la carpeta de datos. Si hay una versión nueva,
aparece «Versión X disponible» en la barra superior; ahí también están la casilla **Buscar
actualizaciones al iniciar** (se guarda en las preferencias), el botón **Buscar ahora** (ignora la
caché) y las novedades de la versión. Para desactivarlo desde el entorno:
`CLIPSTUDIO_BUSCAR_ACTUALIZACIONES=0` (ver `.env.example`).

Según cómo esté instalada:

- **Aplicación instalada:** compara `__version__` con la última GitHub Release (las versiones con
  sufijo de prerelease no se ofrecen). «Descargar» baja `ClipStudio-Setup.exe` a
  `actualizaciones/` dentro de la carpeta de datos, con progreso, y comprueba su SHA-256 si la
  release incluye `ClipStudio-Setup.exe.sha256`; si no lo incluye, la interfaz lo dice y no lo da
  por verificado. Solo «Instalar y reiniciar» ejecuta el instalador (`/SILENT /SUPPRESSMSGBOXES
  /NORESTART /CLOSEAPPLICATIONS`): antes avisa si hay grabación en vivo o trabajos activos, el
  motor se detiene de forma ordenada, el instalador sustituye los archivos y ClipStudio se
  vuelve a abrir. Los proyectos no se tocan.
- **Copia del código con `.git`:** compara el commit local con `main` en GitHub. «Actualizar» hace
  `git pull --ff-only origin main` y `uv sync`, solo si `git status --porcelain` está vacío; si hay
  cambios sin guardar, no toca nada y muestra las órdenes. Después hay que reiniciar la app a mano.
- **Copia sin `.git` (ZIP de GitHub):** solo avisa y enlaza a la página de releases.

## Publicar una versión nueva

Para el mantenedor, en Windows con `git`, `gh` (con sesión iniciada) e Inno Setup (`iscc` en el
PATH o `CLIPSTUDIO_ISCC`):

1. Parte de `main` con el árbol de git limpio y las pruebas en verde.
2. Escribe las notas de la versión (opcional; si no, el script genera un borrador con los commits).
3. `uv run python scripts/publicar_version.py 0.2.0 [--notas notas.md]`. El script sube la versión
   en `clipstudio/__init__.py` y `pyproject.toml`, ejecuta las pruebas, compila el instalador,
   calcula `dist/ClipStudio-Setup.exe.sha256`, crea el commit «Version 0.2.0» y la etiqueta
   `v0.2.0`, y pide confirmación antes de `git push` y antes de `gh release create v0.2.0
   dist/ClipStudio-Setup.exe dist/ClipStudio-Setup.exe.sha256 --notes-file ...`. Con
   `--sin-publicar` se detiene tras el commit y la etiqueta locales.
4. Las instalaciones antiguas verán la versión nueva en su próxima búsqueda (como mucho 6 h).

La release debe ser pública, no ser borrador ni prerelease, y llamar exactamente
`ClipStudio-Setup.exe` y `ClipStudio-Setup.exe.sha256` a sus recursos. Las instalaciones que no
traen esta función (la 0.1.0 original) no se actualizan solas: instálales la primera versión con
actualizaciones a mano.


## Compilación de revisión en GitHub Actions

El workflow `Tests and Windows desktop preview` prueba el código y genera un
instalador y portable para revisar los PR hacia `main` o `feature/youtube-discovery`.
En la ejecución completada, descarga `ClipStudio-Windows-preview-<número>` desde
Artifacts. Incluye SHA-256 y commit de origen; caduca a los 14 días.
No publica releases ni cambia el canal estable. Valida el arranque, instalación y
reinicio en Windows antes de publicar una versión nueva. Detalles de alcance y
pruebas en [rondas-mejora.md](rondas-mejora.md).
