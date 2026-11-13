# ClipStudio

**Aplicación de escritorio para Windows:** abre `dist/ClipStudio/ClipStudio.exe` o instala
`dist/ClipStudio-Setup.exe`. Incluye Python, FFmpeg y Node.js. Los datos y proyectos existentes
se conservan en `%LOCALAPPDATA%\ClipStudio`. Más información en [ESCRITORIO.md](docs/ESCRITORIO.md).
Para desarrollar, `iniciar.bat` abre ahora la ventana nativa; el comando sin `--escritorio`
conserva el modo de navegador.

Convierte videos largos en clips verticales 9:16 con subtítulos, **en tu propio equipo**: sin
cuentas, sin nube y sin costos por uso.

1. Sube un video o pega un enlace (YouTube y otras plataformas compatibles con yt-dlp).
2. ClipStudio extrae el audio y lo transcribe con tiempos por palabra, por bloques de 30 minutos
   para aguantar videos de muchas horas.
3. Propone fragmentos (o **divide el video completo** en partes de la duración que elijas) y te
   deja ajustar su inicio y fin.
4. Reencuadra a vertical: rellenar con recorte, ajustar con fondo difuminado o de color, o
   **pantalla dividida** con el video arriba y un video de juego abajo.
   El recorte puede seguir el rostro con movimientos suaves, tanto en la vista previa como
   en el MP4. En «Encuadre y estilo» pulsa **Seguir el rostro** para activarlo en clips existentes.
   **Usar encuadre fijo** o mover la posición horizontal desactiva el seguimiento. Si cambias
   los límites del clip, vuelve a pulsar «Seguir el rostro» para calcularlo sobre el nuevo tramo.
5. Genera subtítulos que puedes editar: texto, tiempos, estilos prefabricados, palabra resaltada,
   caja de fondo, palabras por línea, tamaño, color y posición.
6. Añade un título gancho con la duración que quieras.
7. Previsualiza y exporta un MP4 real (1080×1920, H.264 + AAC), de uno en uno o todos a la vez.

También puedes quitar frases y silencios del medio del clip, añadir una marca de agua y
aplicar el estilo a otros clips. En **En vivo**, captura Twitch, YouTube o Kick, revisa una
imagen reciente y crea clips por picos del chat. El encuadre **Stream (cámara y gameplay)**
compone ambas zonas del mismo video; **Dividido** utiliza un video externo de fondo.

Estado de implementación, pruebas y pendientes: [docs/estado.md](docs/estado.md).


Historial de versiones: [CHANGELOG.md](CHANGELOG.md).

## Hashtags para TikTok

Abre un clip y entra en la pestaña **TikTok → Recomendar hashtags**. Propone hasta cinco
etiquetas temáticas basadas en el título, el gancho y los subtítulos editados; sin subtítulos
usa la transcripción del fragmento. Excluye contenido fuera del clip y tramos eliminados.
No reconoce el juego por la imagen: puedes indicar **Juego o tema**, por ejemplo
`Valorant, Jett, clutch`. También admite temas indicados manualmente fuera del catálogo.

El bloque se puede editar y copiar, y se guarda con ese clip junto con el tema indicado.
Generar de nuevo reemplaza ese bloque; vuelve a hacerlo si cambias el contenido. No publica
en TikTok. Funciona localmente, sin cuentas, claves ni consultas automáticas de tendencias.
Incluye un enlace a Creative Center para consultarlas manualmente.

Los hashtags no aseguran visitas ni aparecer en Para ti. Se prioriza relevancia y no se
añaden `#FYP`/`#viral` como fórmula de alcance: [orientación de TikTok para creadores](https://newsroom.tiktok.com/5-tips-for-tiktok-creators?lang=en).

## Instalación de escritorio

Si ya está instalada, abre el acceso directo **ClipStudio** del escritorio o menú Inicio.
El instalador `dist/ClipStudio-Setup.exe` instala por usuario, sin permisos de administrador,
en `%LOCALAPPDATA%\Programs\ClipStudio`. Los proyectos quedan en otra carpeta y se conservan
al desinstalar. También puedes abrir la versión portable conservando toda `dist/ClipStudio`.

Requiere Windows 10/11 x64 y Microsoft Edge WebView2 Runtime. Python, FFmpeg, ffprobe y Node.js
van incluidos. Solo el modelo de transcripción se descarga al necesitarlo por primera vez.
Para archivos locales, una vez disponible el modelo, el procesamiento puede hacerse sin Internet.
Los enlaces y directos necesitan conexión.

**Minimizar mantiene el trabajo.** Cerrar espera el guardado del editor y avisa antes de
detener una grabación o cancelar trabajos. El búfer del directo se descarta al pararlo;
los clips guardados permanecen. Un segundo doble clic activa la ventana existente.
Si reutiliza un servidor que ya estaba abierto, la ventana no lo detiene al cerrar.

Consulta [docs/ESCRITORIO.md](docs/ESCRITORIO.md) para compilación y solución de problemas.
La primera compilación no está firmada. Para las actualizaciones, ver [Actualizaciones](#actualizaciones).

## Actualizaciones

Al iniciar, ClipStudio busca en segundo plano (como mucho cada 6 horas) si hay una versión nueva en
GitHub y lo indica en la barra superior. Nunca descarga ni instala nada sin que pulses el botón.
En la aplicación instalada baja el instalador, comprueba su SHA-256 si la release lo incluye y lo
ejecuta con **Instalar y reiniciar**; en una copia con git ofrece `git pull --ff-only` + `uv sync`
si no tienes cambios sin guardar; en un ZIP solo enlaza a las releases. Se desactiva con la casilla
de la interfaz o con `CLIPSTUDIO_BUSCAR_ACTUALIZACIONES=0`. Detalles y cómo publicar una versión en
[ESCRITORIO.md](docs/ESCRITORIO.md).

## Requisitos para desarrollar desde el código

> **Norma del proyecto:** todo cambio se comprueba en la **aplicación de escritorio**, no solo en
> la versión de navegador. La ventana usa WebView2 y puede comportarse distinto. Ver [AGENTS.md](AGENTS.md).

- Windows 10/11 de 64 bits (probado en Windows 11).
- [uv](https://docs.astral.sh/uv/) para gestionar Python. uv descarga Python 3.12 por su cuenta.
- [Node.js](https://nodejs.org/) solo si vas a importar desde YouTube (yt-dlp lo usa para resolver
  los formatos). La subida de archivos locales no lo necesita.
- Conexión a internet la primera vez (dependencias, FFmpeg y modelo de transcripción, ~0,5 GB).
  Después, los archivos locales se procesan sin conexión.
- Espacio en disco: cada proyecto ocupa aproximadamente el tamaño del video original más una
  copia ligera para la vista previa.

No hace falta tarjeta gráfica: la transcripción corre en CPU.

## Instalación de dependencias desde el código

Desde la carpeta `ClipStudio`, en PowerShell:

```powershell
uv sync
uv run python scripts/instalar_ffmpeg.py
```

El segundo comando descarga `ffmpeg.exe` y `ffprobe.exe` a `%LOCALAPPDATA%\ClipStudio\bin`. Si ya
tienes FFmpeg en el PATH, lo detecta y no descarga nada.

Opcional, para no esperar dentro de la aplicación la primera vez (descarga ~465 MB):

```powershell
uv run python scripts/descargar_modelo.py
```

## Arranque desde el código

Ventana de escritorio:

```powershell
uv run python -m clipstudio --escritorio
```

O haz doble clic en `iniciar.bat`. Para abrir la interfaz en el navegador:

```powershell
uv run python -m clipstudio
```

Este último comando abre `http://127.0.0.1:8765` en el navegador. Para detener ese servidor,
pulsa `Ctrl+C` en su terminal. Añade `--no-abrir` para arrancar solo el servidor.

La primera transcripción descarga el modelo (`small`) si falta. Solo puede haber un motor
por carpeta de datos. Puedes abrir su página en varias pestañas del navegador; `iniciar.bat`
abre o activa la ventana de escritorio y reutiliza el servidor compatible si ya existe.
Para servidores independientes, configura carpetas de datos y puertos diferentes.

## Configuración

Todo es opcional. Copia `.env.example` como `.env` y cambia lo que necesites:

Desde el código, `.env` se lee en la raíz del proyecto. En el paquete de escritorio se lee
junto a `ClipStudio.exe`. Los cambios en Python o configuración requieren reiniciar el motor;
antes, para el directo y guarda los clips que quieras conservar.

| Variable | Por defecto | Para qué |
|---|---|---|
| `CLIPSTUDIO_DATA_DIR` | `%LOCALAPPDATA%\ClipStudio` | Dónde se guardan videos, exportaciones, modelos y FFmpeg |
| `CLIPSTUDIO_PORT` | `8765` | Puerto local |
| `CLIPSTUDIO_HOST` | `127.0.0.1` | Dirección de escucha; mantener local para uso normal |
| `CLIPSTUDIO_WHISPER_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3` (más grande = más preciso y lento) |
| `CLIPSTUDIO_MAX_UPLOAD_GB` | `8` | Tamaño máximo de archivo |
| `CLIPSTUDIO_MAX_DURATION_MIN` | `720` | Duración máxima del video (12 horas) |
| `CLIPSTUDIO_YTDLP_COOKIES_BROWSER` | vacío | `chrome`, `edge` o `firefox` para videos que exigen sesión |
| `CLIPSTUDIO_VIVO_BUFER_MIN` | `60` | Minutos de directo conservados temporalmente |
| `CLIPSTUDIO_MODELS_DIR` | `DATA_DIR/modelos` | Carpeta de modelos de transcripción |
| `CLIPSTUDIO_FONDOS_DIR` | `DATA_DIR/fondos` | Videos externos para «Dividido» |
| `CLIPSTUDIO_FFMPEG_DIR` | búsqueda automática | Instalación propia de FFmpeg/ffprobe |

Los datos se guardan **fuera** de la carpeta del proyecto a propósito: esta carpeta está dentro de
OneDrive y no conviene que intente sincronizar videos de varios gigas.

## Cómo se proponen los clips

No hay "puntuación de viralidad". El método es una heurística sobre la transcripción:

1. Se parte el texto en frases según la puntuación y las pausas del habla.
2. Se generan ventanas que empiezan y terminan en límite de frase, dentro de la duración pedida.
3. Cada ventana suma puntos por rasgos observables: empieza tras una pausa, termina en cierre de
   frase, tiene pocas pausas internas, su ritmo de habla supera la media del video, abre con una
   pregunta o una cifra, contiene un pico de volumen, y se acerca a la duración objetivo.
4. Se eligen las mejores sin solaparse, y se muestran los motivos de cada una.

Un **pico de volumen** es un segundo que suena al menos 9 dB por encima de su entorno (grito,
risa, sobresalto). Sirve sobre todo en directos y reacciones.

**Dividir todo el video** no elige nada: crea clips consecutivos de la duración pedida que cubren
el video entero. Si marcas la opción, cada corte se mueve (hasta un 25 %) a la pausa más cercana
para no partir una frase.

**Limitaciones:** no entiende el contenido ni mira la imagen; depende de que la transcripción y su
puntuación sean buenas; un fragmento bien delimitado no es necesariamente interesante. Úsalo como
punto de partida y ajusta a mano. En videos sin voz no propone nada.

## Modo en vivo

En la barra superior, **En vivo**: pega el enlace de un directo en curso y pulsa «Conectar».
ClipStudio graba la última hora en un búfer en disco (configurable con `CLIPSTUDIO_VIVO_BUFER_MIN`),
marca momentos cuando el volumen se dispara y te deja sacar un clip de los últimos 30, 60 o 90
segundos, o de cualquier momento marcado. Cada clip entra como un proyecto normal.

Puedes activar **Leer chat** y **Crear clips automáticamente por picos del chat** antes de
conectar. Se detectan ráfagas de al menos 3 mensajes/s respecto al minuto anterior, con
participación de varias personas, al menos 20 s válidos de historial (unos 25–30 s desde la
conexión) y un minuto entre clips automáticos.
Se deduplican mensajes y se limita la aportación de cada usuario para reducir disparos por spam.
Los picos de audio siguen disponibles como momentos que puedes convertir manualmente.

Cada clip automático guarda 25 s anteriores y 10 posteriores al momento, espera a que el video
esté en el búfer y aparece en **Proyectos**, con el fragmento completo preparado para editar y
exportar. El ajuste **Retraso de reacción del chat** resta por defecto 3 s para compensar la
reacción de los espectadores. Los gráficos muestran por separado volumen y actividad del chat.

Twitch lee el chat público mediante IRC seguro, YouTube reutiliza el lector de chat de yt-dlp
y Kick usa su conexión pública Centrifugo con una sesión de invitado renovable.
La lectura se reconecta automáticamente si falla. Si el chat no está disponible, su error aparece
en la pantalla y la grabación continúa. Se sigue un directo a la vez.

La reconexión anterior corresponde al **chat**. La captura de video no se recupera sola si
caduca su dirección multimedia o se interrumpe. Al parar se elimina el búfer, no los proyectos
ya creados. La detección no garantiza que un momento sea interesante.

Verificado con el directo de Twitch de TenZ (grabación, mensajes reales y recorte MP4) y con un
chat real activo de YouTube. También se comprobó Pirutastic en Kick con grabación, mensajes
reales, imagen actualizada, detección de cámara y exportación vertical 1080×1920. La detección
automática y la conversión completa tienen pruebas reproducibles con ráfagas simuladas.
El lector de Kick utiliza el servicio público de su web, cuyo contrato puede cambiar.

### Vista del directo y encuadre de streams

El panel **En vivo** muestra una imagen reciente del video que está grabando. Se actualiza al
cerrarse cada segmento, aproximadamente cada 6 s, con el retraso propio de la captura.

Para clips de juegos recomiendo **Cámara arriba + gameplay abajo**, la opción inicial. También
puedes elegir **Gameplay completo** o **Solo cámara**. Ambas zonas proceden del mismo directo.
El gameplay conserva el área seleccionada completa, con un fondo difuminado que llena el espacio.

Pulsa **Marcar cámara** o **Marcar gameplay** y arrastra un rectángulo sobre la imagen. Después
pulsa **Aplicar a los próximos clips**. Si dejas la cámara automática, se intenta detectar al
creador cuando se prepara cada clip. Cuando no se detecta, se muestra el gameplay completo y
puedes marcar la webcam manualmente. La altura inicial de la cámara es un 30 %, ajustable.

En clips ya creados, elige **Encuadre y estilo → Stream (cámara y gameplay)**. Allí puedes
corregir las zonas, detectar la cámara y ver la composición mientras reproduces el clip. La
exportación usa las mismas regiones que la vista previa.

La detección de cámara usa el modelo local YuNet de OpenCV, de 232 589 bytes, incluido con su
licencia MIT en `clipstudio/modelos`. El modelo tiene SHA-256
`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.
[Modelo y licencia de origen](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)

## Pantalla dividida con video de juego

En «Encuadre y estilo» elige **Dividido**: el clip va arriba y un video de fondo abajo, en bucle,
sin sonido y empezando en un punto al azar. Puedes elegir qué fondo usar (o «Al azar») y qué
porcentaje de la pantalla ocupa.

**Fondos de YouTube sin descargar:** el selector incluye Minecraft parkour y Subway Surfers, y
puedes añadir cualquier video de YouTube pegando su enlace. La vista previa se reproduce desde
YouTube y, al exportar, ClipStudio descarga solo el tramo que necesita el clip (hace falta
internet). Puedes mostrar el crédito del autor del fondo, con el tamaño que quieras.

También puedes usar videos propios: los fondos locales son los archivos (`.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`) que haya en
`%LOCALAPPDATA%\ClipStudio\fondos`; el botón «Abrir carpeta de fondos» la abre. Copia ahí lo que
quieras usar. **El material es tu responsabilidad:** las grabaciones de juegos comerciales tienen
derechos de autor, y la etiqueta «sin copyright» de quien sube un video a YouTube no es una
licencia del dueño del juego. Si la licencia pide atribución, da crédito al publicar.

## Arquitectura

```
Ventana Windows (pywebview/WebView2) o navegador
        │  HTTP en 127.0.0.1
FastAPI ── SQLite (proyectos, clips, exportaciones, sesiones y momentos)
        │
Dos colas de trabajo en hilos (procesar / exportar)
        ├─ yt-dlp ........ importar por enlace
        ├─ ffprobe/FFmpeg  analizar, vista previa, audio, exportar
        ├─ faster-whisper  transcribir en CPU
        ├─ OpenCV/YuNet ... seguimiento del rostro y región de webcam
        └─ vivo/chat ...... segmentos, imagen, métricas y clips por ráfagas
```

Por qué así:

- **Motor local sin servicio permanente**: la ventana administra su propio proceso de servidor
  y lo detiene al cerrar. FFmpeg y el lector de YouTube usan subprocesos. El modo de navegador
  puede arrancar el servidor directamente.
- **FFmpeg** hace todo el trabajo de video: es el estándar, exporta MP4 real y quema subtítulos
  con libass. El navegador no codifica nada, solo previsualiza.
- **faster-whisper en CPU**: sin claves ni costos, y los videos no salen del equipo. Este equipo
  tiene GPU AMD (sin CUDA), así que la CPU es la opción directa.
- **SQLite + carpetas por proyecto**: nada que administrar y fácil de borrar.
- **Frontend sin compilación**: no hay `npm install` ni paso de build.

## Estructura

```
clipstudio/
  __main__.py     Arranque web, escritorio y workers del paquete
  desktop.py      Ventana Windows, instancia única y ciclo de vida del motor
  api.py          Rutas HTTP y validaciones
  pipeline.py     Colas de trabajo y flujo de procesamiento
  media.py        FFmpeg / ffprobe
  transcribe.py   faster-whisper
  suggest.py      Propuesta de fragmentos
  hashtags.py     Sugerencias temáticas de TikTok sobre el fragmento conservado
  subtitles.py    Agrupación de palabras y archivo ASS
  reframe.py      Detección de rostro para el recorte
  cortes.py       Cortes internos y remapeo de tiempos
  vivo.py         Captura, búfer, imagen, momentos y API de directos
  chat.py         Twitch, YouTube, Kick y detector de ráfagas
  importer.py     yt-dlp
  db.py           SQLite
  config.py       Variables de entorno
  modelos/        YuNet y su licencia
  web/            Interfaz, panel en vivo y selector de cámara/gameplay
scripts/
  compilar_escritorio.py    Empaqueta herramientas, recursos y ejecutable
  desktop_entry.py          Entrada de PyInstaller
  instalador.iss           Instalador Inno Setup por usuario
  instalar_ffmpeg.py        Descarga FFmpeg
  descargar_modelo.py       Descarga el modelo de transcripción por adelantado
  crear_video_prueba.ps1    Genera un video de prueba con voz sintética
  prueba_e2e.py             Prueba de extremo a extremo
  prueba_vivo.py            Captura y clips con un directo simulado
  prueba_bloques.py         Prueba de la transcripción por bloques y su reanudación
tests/            Pruebas unitarias
docs/             Revisión de Codex y estado del proyecto
ClipStudio.spec   Configuración del paquete de PyInstaller
dist/             Portable e instalador generados (fuera de Git)
```

## Pruebas

```powershell
uv run pytest
powershell -ExecutionPolicy Bypass -File scripts\crear_video_prueba.ps1
uv run python scripts/prueba_e2e.py "$env:LOCALAPPDATA\ClipStudio\pruebas\video_prueba.mp4"
```

La prueba de extremo a extremo arranca su propio servidor en el puerto 8799, recorre todo el flujo
y verifica el MP4 exportado. Añade `--url <enlace>` para probar también la importación.

Para comprobar la versión empaquetada:

```powershell
uv run python scripts/prueba_vivo.py --ejecutable dist/ClipStudio/ClipStudio.exe
uv run python scripts/prueba_e2e.py RUTA_VIDEO --ejecutable dist/ClipStudio/ClipStudio.exe
```

Usa un video con voz de unos 90 s para la prueba integral completa. El comprobador de vivo
usa el puerto 8798 y una emisión simulada. Ambos aíslan sus datos de los proyectos normales.
Última batería del 12 de noviembre: **169 pruebas automatizadas**, incluidas las de hashtags.
La ronda anterior de escritorio pasó **31/31 de directo y 80/80 del flujo integral** con el
ejecutable; esas dos baterías no se repitieron para el cambio de hashtags. Consulta el alcance
en `docs/estado.md`.

## Problemas frecuentes

| Síntoma | Qué hacer |
|---|---|
| "Falta FFmpeg" en la barra superior | `uv run python scripts/instalar_ffmpeg.py` |
| "No se pudo cargar el modelo de transcripción" | La primera vez necesita internet para descargarlo |
| Un enlace falla con "exige iniciar sesión" | Configura `CLIPSTUDIO_YTDLP_COOKIES_BROWSER` o usa un video público |
| Un enlace de YouTube falla sin motivo claro | Actualiza yt-dlp: `uv lock --upgrade-package yt-dlp` y luego `uv sync` |
| El puerto está ocupado | Cambia `CLIPSTUDIO_PORT` en `.env` |
| La ventana nativa no arranca | Comprueba WebView2 y consulta `ventana.log`/`escritorio.log` en la carpeta de datos |
| La imagen del directo sigue esperando | Espera al primer segmento cerrado; si se avisa de servidor antiguo, para el directo y reinicia el motor actualizado |
| «Encuadre no válido» al marcar una zona | Revisa la selección sobre la imagen y actualiza/reinicia el motor si está cargando una versión anterior |
| Cambiar Python no cambia la app instalada | Recompila y reinstala; recargar la interfaz no actualiza el motor ni el ejecutable |

Consulta `docs/estado.md` para lo verificado, las limitaciones y lo pendiente.

## Uso responsable

Importa solo videos propios o que tengas permiso para reutilizar. Descargar o republicar contenido
ajeno puede infringir derechos de autor y las condiciones de la plataforma de origen.

### YouTube: tendencias y pistas de audio

Para habilitar **YouTube → Tendencias**, activa YouTube Data API v3 en tu proyecto de
Google Cloud, crea una clave restringida a esa API y ponla en `.env` como
`CLIPSTUDIO_YOUTUBE_API_KEY`. Reinicia ClipStudio. La clave se usa en el servidor
local. El listado se obtiene de `videos.list` con `chart=mostPopular` para el país elegido.

En **Proyectos → Enlace de video**, pega una URL de YouTube y usa **Buscar pistas de audio**.
Si yt-dlp encuentra pistas con idioma, puedes elegir cuál descargar antes de importar.
Esto usa los doblajes disponibles en el video. El selector **Idioma para transcribir**
controla el reconocimiento de voz y se puede dejar en detección automática.
