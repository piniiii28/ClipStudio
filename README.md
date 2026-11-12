# ClipStudio

Convierte videos largos en clips verticales 9:16 con subtítulos, **en tu propio equipo**: sin
cuentas, sin nube y sin costos por uso.

1. Sube un video o pega un enlace (YouTube y otras plataformas compatibles con yt-dlp).
2. ClipStudio extrae el audio y lo transcribe con tiempos por palabra, por bloques de 30 minutos
   para aguantar videos de muchas horas.
3. Propone fragmentos (o **divide el video completo** en partes de la duración que elijas) y te
   deja ajustar su inicio y fin.
4. Reencuadra a vertical: rellenar con recorte, ajustar con fondo difuminado o de color, o
   **pantalla dividida** con el video arriba y un video de juego abajo.
5. Genera subtítulos que puedes editar: texto, tiempos, estilos prefabricados, palabra resaltada,
   caja de fondo, palabras por línea, tamaño, color y posición.
6. Añade un título gancho con la duración que quieras.
7. Previsualiza y exporta un MP4 real (1080×1920, H.264 + AAC), de uno en uno o todos a la vez.

## Requisitos

- Windows 10/11 de 64 bits (probado en Windows 11).
- [uv](https://docs.astral.sh/uv/) para gestionar Python. uv descarga Python 3.12 por su cuenta.
- [Node.js](https://nodejs.org/) solo si vas a importar desde YouTube (yt-dlp lo usa para resolver
  los formatos). La subida de archivos locales no lo necesita.
- Conexión a internet la primera vez (dependencias, FFmpeg y modelo de transcripción, ~0,5 GB).
  Después, los archivos locales se procesan sin conexión.
- Espacio en disco: cada proyecto ocupa aproximadamente el tamaño del video original más una
  copia ligera para la vista previa.

No hace falta tarjeta gráfica: la transcripción corre en CPU.

## Instalación

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

## Uso

```powershell
uv run python -m clipstudio
```

O haz doble clic en `iniciar.bat`. Se abre `http://127.0.0.1:8765` en el navegador. Para
detenerlo, pulsa `Ctrl+C` en la terminal. Añade `--no-abrir` si no quieres que abra el navegador.

La primera transcripción descarga el modelo (`small`) si no lo descargaste antes. Solo puede
haber un ClipStudio abierto por carpeta de datos.

## Configuración

Todo es opcional. Copia `.env.example` como `.env` y cambia lo que necesites:

| Variable | Por defecto | Para qué |
|---|---|---|
| `CLIPSTUDIO_DATA_DIR` | `%LOCALAPPDATA%\ClipStudio` | Dónde se guardan videos, exportaciones, modelos y FFmpeg |
| `CLIPSTUDIO_PORT` | `8765` | Puerto local |
| `CLIPSTUDIO_WHISPER_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3` (más grande = más preciso y lento) |
| `CLIPSTUDIO_MAX_UPLOAD_GB` | `8` | Tamaño máximo de archivo |
| `CLIPSTUDIO_MAX_DURATION_MIN` | `720` | Duración máxima del video (12 horas) |
| `CLIPSTUDIO_YTDLP_COOKIES_BROWSER` | vacío | `chrome`, `edge` o `firefox` para videos que exigen sesión |

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

## Pantalla dividida con video de juego

En «Encuadre y estilo» elige **Dividido**: el clip va arriba y un video de fondo abajo, en bucle,
sin sonido y empezando en un punto al azar. Puedes elegir qué fondo usar (o «Al azar») y qué
porcentaje de la pantalla ocupa.

Los fondos son los videos (`.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`) que haya en
`%LOCALAPPDATA%\ClipStudioondos`; el botón «Abrir carpeta de fondos» la abre. Copia ahí lo que
quieras usar. **El material es tu responsabilidad:** las grabaciones de juegos comerciales tienen
derechos de autor, y la etiqueta «sin copyright» de quien sube un video a YouTube no es una
licencia del dueño del juego. Si la licencia pide atribución, da crédito al publicar.

## Arquitectura

```
Navegador (HTML + JS sin compilación)
        │  HTTP en 127.0.0.1
FastAPI ── SQLite (proyectos, clips, exportaciones)
        │
Dos colas de trabajo en hilos (procesar / exportar)
        ├─ yt-dlp ........ importar por enlace
        ├─ ffprobe/FFmpeg  analizar, vista previa, audio, exportar
        ├─ faster-whisper  transcribir en CPU
        └─ OpenCV ........ detectar rostro para centrar el recorte
```

Por qué así:

- **Un solo proceso local** que se arranca con un comando; no hay servicios que instalar.
- **FFmpeg** hace todo el trabajo de video: es el estándar, exporta MP4 real y quema subtítulos
  con libass. El navegador no codifica nada, solo previsualiza.
- **faster-whisper en CPU**: sin claves ni costos, y los videos no salen del equipo. Este equipo
  tiene GPU AMD (sin CUDA), así que la CPU es la opción directa.
- **SQLite + carpetas por proyecto**: nada que administrar y fácil de borrar.
- **Frontend sin compilación**: no hay `npm install` ni paso de build.

## Estructura

```
clipstudio/
  api.py          Rutas HTTP y validaciones
  pipeline.py     Colas de trabajo y flujo de procesamiento
  media.py        FFmpeg / ffprobe
  transcribe.py   faster-whisper
  suggest.py      Propuesta de fragmentos
  subtitles.py    Agrupación de palabras y archivo ASS
  reframe.py      Detección de rostro para el recorte
  importer.py     yt-dlp
  db.py           SQLite
  config.py       Variables de entorno
  web/            Interfaz (index.html, app.js, estilos.css)
scripts/
  instalar_ffmpeg.py        Descarga FFmpeg
  descargar_modelo.py       Descarga el modelo de transcripción por adelantado
  crear_video_prueba.ps1    Genera un video de prueba con voz sintética
  prueba_e2e.py             Prueba de extremo a extremo
  prueba_bloques.py         Prueba de la transcripción por bloques y su reanudación
tests/            Pruebas unitarias
docs/             Revisión de Codex y estado del proyecto
```

## Pruebas

```powershell
uv run pytest
powershell -ExecutionPolicy Bypass -File scripts\crear_video_prueba.ps1
uv run python scripts/prueba_e2e.py "$env:LOCALAPPDATA\ClipStudio\pruebas\video_prueba.mp4"
```

La prueba de extremo a extremo arranca su propio servidor en el puerto 8799, recorre todo el flujo
y verifica el MP4 exportado. Añade `--url <enlace>` para probar también la importación.

## Problemas frecuentes

| Síntoma | Qué hacer |
|---|---|
| "Falta FFmpeg" en la barra superior | `uv run python scripts/instalar_ffmpeg.py` |
| "No se pudo cargar el modelo de transcripción" | La primera vez necesita internet para descargarlo |
| Un enlace falla con "exige iniciar sesión" | Configura `CLIPSTUDIO_YTDLP_COOKIES_BROWSER` o usa un video público |
| Un enlace de YouTube falla sin motivo claro | Actualiza yt-dlp: `uv lock --upgrade-package yt-dlp` y luego `uv sync` |
| El puerto está ocupado | Cambia `CLIPSTUDIO_PORT` en `.env` |

Consulta `docs/estado.md` para lo verificado, las limitaciones y lo pendiente.

## Uso responsable

Importa solo videos propios o que tengas permiso para reutilizar. Descargar o republicar contenido
ajeno puede infringir derechos de autor y las condiciones de la plataforma de origen.
