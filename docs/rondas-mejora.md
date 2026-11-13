# Rondas de mejora de ClipStudio

Fecha: 2026-11-13. Base: `feature/youtube-discovery`.
Rama: `improve/live-import-workflows`.

## Investigación y contraste

Se delegaron en paralelo tres revisiones independientes (directos, vídeos grabados y
código). La integración y las pruebas se hicieron sobre el código compartido. Se
priorizaron problemas reproducibles frente a funciones que ClipStudio ya ofrecía.
Las comparaciones siguientes describen documentación de los proveedores, no una
prueba de rendimiento ni de calidad de sus modelos.

| Referencia primaria consultada | Hallazgo contrastado con ClipStudio | Decisión |
| --- | --- | --- |
| [Twitch: Stream Markers](https://dev.twitch.tv/docs/api/markers) | Marcadores temporales con descripción. ClipStudio tenía audio/chat, pero no marcador manual. | Marcar localmente sobre el último segmento cerrado y guardar una nota. No requiere cuenta Twitch. |
| [OBS: Replay Buffer](https://obsproject.com/kb/OBS-Studio-Overview) | Búfer de repetición y guardado por atajo. Ya existían botones de 30/60/90 s. | Mostrar la duración disponible y conservar los botones; atajos pendientes. |
| [Eklipse: getting started](https://eklipse.gg/help/getting-started-with-eklipse/) | El proveedor documenta highlights automáticos y biblioteca de procesados. ClipStudio ya automatizaba por chat. | Organizar por origen/pendientes y distinguir lo que salió del búfer. |
| [Premiere: Text-Based Editing](https://helpx.adobe.com/premiere/desktop/edit-projects/edit-video-using-text-based-editing/overview-of-text-based-editing.html) | Navegación y selección desde texto. ClipStudio tenía selección, sin búsqueda, y no dejaba escuchar fuera del clip. | Búsqueda sin acentos, escucha de selección y vuelta explícita al clip. |
| [Premiere: vídeo y forma de onda](https://helpx.adobe.com/premiere/desktop/add-audio-effects/basic-audio-editing/view-audio-and-video-waveforms-in-the-source-monitor.html) | Onda como ayuda para ajustar tiempos. No hay onda ni miniaturas en nuestra línea de tiempo. | Posponer: requieren generación y caché acotadas para vídeos largos. |
| [OpusClip: layouts](https://help.opus.pro/docs/article/apply-the-layouts) y [subject tracking](https://help.opus.pro/docs/article/subject-tracking) | Variantes de composición y elección de sujeto. Ya hay rellenar/ajustar/dividido/stream, copia de estilo y duplicación de clips. | Corregir antes la continuidad reproducible de dos rostros; no prometer identificación del hablante. |
| [Premiere: audio multicanal](https://helpx.adobe.com/premiere/desktop/edit-projects/edit-video-using-text-based-editing/multichannel-audio-support-in-text-based-editing.html) | Selección de canal para transcribir. Los canales no equivalen a pistas de doblaje. | Revisar coherencia entre transcripción, proxy y exportación; selección local multitrack pendiente. |
| [yt-dlp: selección de formatos](https://github.com/yt-dlp/yt-dlp#format-selection) | `bv` excluye vídeo muxado; cambiar a `bv*` por sí solo puede conservar el audio incorrecto. Se contrastó con el selector y mezclador reales. | Selector estricto por idioma que elimina el audio del contenedor de vídeo antes de mezclar. |

## Rondas y evidencia

1. **Momentos de directo.** Se reproducía un botón de conversión para momentos ya
   borrados del búfer. Ahora se avisa de caducidad, se filtran pendientes y orígenes,
   y los convertidos abren su proyecto. Marcadores con nota de hasta 160 caracteres,
   persistencia, validación de sesión y error de guardado visible. No se automatizan
   aunque esté activada la creación por chat. Pruebas del módulo: **18 pasaron**.
2. **Localizar y escuchar contexto.** Una frase a 8–10 s con un clip activo a 0–3 s
   volvía al inicio del clip al reproducirse. Se añadió búsqueda sin acentos y límites
   independientes de escucha. La selección conserva índices de la transcripción
   completa aunque esté filtrada; crear un clip no cambia el anterior. Salir de la
   pestaña o elegir otro clip recupera reproducción normal. Batería: **295 pasaron**;
   recorrido real en Chromium, sin errores JS.
3. **Dos personas.** Alternar tamaños de dos caras persistentes impedía confirmar
   ninguna y devolvía ausencia de seguimiento. Ahora se asocia la candidata entre
   muestras antes de volver a elegir la cara mayor. Batería: **296 pasaron**. El caso
   usa detecciones controladas y captura simulada; no mide precisión con rostros reales.
4. **Doblaje de vídeo importado.** Un vídeo muxado en inglés más una pista española
   disponible era rechazado. El selector conserva exclusivamente el audio solicitado.
   Regresión real de yt-dlp + FFmpeg con tonos de 440/880 Hz: un solo stream de audio
   y frecuencia de 880 Hz en la salida. No cambia silenciosamente de idioma si falta.
   Batería: **298 pasaron**.
5. **Integridad del búfer.** Segmentos 0–6 y 12–18 s se trataban como 18 s continuos.
   Ahora se rechazan huecos mayores de 100 ms (se tolera redondeo de timestamps).
   Los botones muestran segundos disponibles si son menos de los pedidos. La
   caducidad se comprueba también en la conversión compartida por botones/cola.
   Batería: **300 pasaron**; navegador repetido; emisión simulada y recortes reales:
   **35/35 comprobaciones correctas**.

## Reproducir

```bash
uv sync --locked
uv run --locked pytest -q
uv pip install playwright==1.65.1
# Chromium instalado; CHROMIUM_PATH permite indicar otra ubicación.
uv run --no-sync python tests/browser/workflows.py
uv run --locked python scripts/prueba_vivo.py
node --input-type=module --check < clipstudio/web/app.js
node --input-type=module --check < clipstudio/web/vivo.js
uv lock --check
```

Los recorridos usan carpetas temporales aisladas. El del navegador no consulta
plataformas ni descarga modelos. La prueba histórica de directo puede descargar el
modelo al preparar los proyectos creados, aunque cancela ese procesamiento y no
verifica su transcripción. No se ejecutó la batería integral con voz real de
`scripts/prueba_e2e.py`.

## Escritorio y distribución

`ClipStudio.spec` incluye la interfaz compartida: estos cambios entran también en
el paquete Windows. El entorno de trabajo actual es Linux y el compilador del
proyecto exige Windows x64.

El workflow `.github/workflows/desktop-preview.yml` ejecuta pruebas en Linux y
Windows; compila portable e instalador con Inno Setup; prueba captura simulada
con el ejecutable; guarda instalador, SHA-256, ZIP portable y commit de origen
como artefacto durante 14 días. Se activa con un PR hacia `main` o
`feature/youtube-discovery`, o manualmente. Los artefactos son de revisión:
conservan la versión del código y no se publican como actualización estable.

Se corrigió además la versión raíz atrasada en `uv.lock` (seguía en 0.1.0 frente a
0.2.0 de `pyproject.toml`). El script de publicación ahora actualiza y confirma el
lock junto con la nueva versión, y lo restaura si falla la compilación.

Tras validar y fusionar los cambios en `main`, publicar desde Windows con
`scripts/publicar_version.py` y una versión superior a 0.2.0. Esa publicación es
la que hará que las instalaciones existentes ofrezcan actualizarse. Este PR
borrador no etiqueta ni publica una release.

## Pendientes verificables

- Resultado del workflow de Windows, arranque visual WebView2, foco, minimizar,
  cierre con guardado, instalación/reinstalación y actualización con reinicio.
- Flujo integral de importación/transcripción/exportación con voz real empaquetada.
- YouTube real: descubrimiento con clave/cuota, idiomas regionales de doblaje,
  formatos HLS/DASH y autenticación/cookies. La prueba de audio usa archivos locales
  sintéticos, no acredita descargas actuales de YouTube.
- Fuentes reales Twitch/YouTube/Kick y sesiones largas con rotación de búfer.
- Cruces/oclusiones de personas reales y selección manual de sujeto inicial. El
  algoritmo sigue continuidad espacial y no identifica hablante.
- Selector de pistas locales: hoy se usa la primera pista; completarlo exige
  persistir índice y aplicarlo por igual a audio, proxy y exportación.
- Miniaturas/onda con caché acotada, atajos de captura y navegación entre resultados
  de búsqueda. Las variantes actuales pueden hacerse duplicando un clip y
  cambiando encuadre; no se añadió otra función redundante.
