# Estado del proyecto y próximos pasos

Actualizado: 2026-11-11.

## Cómo arrancarlo

```powershell
cd ruta\a\ClipStudio
uv run python -m clipstudio
```

O doble clic en `iniciar.bat`. Se abre en `http://127.0.0.1:8765`. Los datos (videos, modelos,
FFmpeg) están en `%LOCALAPPDATA%\ClipStudio`, fuera de OneDrive. Todo está ya instalado.


## Qué se añadió el 11 de noviembre

A partir de una reseña en video de un editor comercial de clips y de lo pedido:

| Función | Dónde está | Estado |
|---|---|---|
| **Dividir todo el video** en clips consecutivos de N segundos, con cortes en pausas para no partir frases | Panel «Clips» → «Partes de N s» → «Dividir todo el video» | Verificado |
| **Exportar todos** los clips de una vez | Pestaña «Exportar» → «Exportar todos (N)» | Verificado |
| Elegir la **duración de los clips** al crear el proyecto | Pantalla «Proyectos», encima de los dos paneles | Verificado |
| **Estilos prefabricados** de subtítulos (6) | «Encuadre y estilo» → «Elegir un estilo prefabricado» | Verificado |
| **Palabra resaltada** mientras se dice, con color a elegir | «Encuadre y estilo» → «Resaltar la palabra dicha» | Verificado |
| **Caja de fondo** en los subtítulos | «Encuadre y estilo» → «Caja de fondo» | Verificado |
| **Palabras y letras por subtítulo** | «Encuadre y estilo» (se aplica al pulsar «Regenerar») | Verificado |
| **Título gancho** con duración, posición, tamaño y colores | «Encuadre y estilo» → «Título gancho» | Verificado |
| **Fondo de color sólido** en el encuadre «Ajustar» | «Encuadre y estilo» → «Fondo» | Verificado |
| **Guardar el estilo** para los clips nuevos | «Encuadre y estilo» → «Usar este estilo en los clips nuevos» | Verificado |
| **Pantalla dividida**: video arriba y video de juego abajo (en bucle, mudo, inicio al azar) | «Encuadre y estilo» → «Dividido»; fondos en `%LOCALAPPDATA%\ClipStudioondos` | Verificado (implementado por Haiku, revisado y probado después) |
| **Transcripción por bloques** de 30 min, reanudable si se interrumpe | Automático | Verificado con 38 min de audio |
| **Picos de volumen** (gritos, risas) como motivo de las propuestas | Automático; aparece como motivo en el clip | Verificado solo con datos sintéticos |
| Límite de duración subido de 4 a **12 horas** | `CLIPSTUDIO_MAX_DURATION_MIN` | No probado con un video de esa duración |

El título gancho resuelve la queja del autor del video: aquí sí se puede decidir cuántos segundos
permanece en pantalla (0 = todo el clip).

## Pruebas ejecutadas con el código final

| Prueba | Resultado |
|---|---|
| Pruebas unitarias (`uv run pytest`) | 45 de 45 |
| Extremo a extremo (`scripts/prueba_e2e.py`), video propio de 88 s | 62 de 62 |
| Interfaz en Chrome sin ventana, pantalla dividida | 11 de 11, sin errores de consola |
| Interfaz en Chrome sin ventana, flujo original | 17 de 17, sin errores de consola |
| Interfaz en Chrome sin ventana, funciones nuevas | 15 de 15, sin errores de consola |
| Transcripción por bloques y reanudación (`scripts/prueba_bloques.py`), 38 min | 11 de 11 |

Lo que comprueba la prueba de extremo a extremo sobre los MP4 exportados: resolución 1080×1920,
H.264 + AAC, audio audible, duración exacta del corte, subtítulo visible y sincronizado (35 de 35
coinciden a ±0,6 s con lo que se oye), título gancho visible al principio y ausente después de su
duración, palabra resaltada en el color elegido, fondo de color sólido, y que las partes de una
división suman exactamente la duración del video.

**Velocidad medida en este equipo:** 30 minutos de audio se transcriben en unos 3 minutos
(modelo `small`, CPU). Un directo de 6 horas tardaría alrededor de 40 minutos solo en transcribir,
más la descarga y la vista previa.

## Lo que NO está verificado

- **Twitch y Kick.** yt-dlp trae extractores para VOD y clips de ambas, pero no los probé porque
  necesito enlaces reales. Solo está verificado YouTube.
- **Picos de volumen con audio real.** La voz sintética del video de prueba no tiene gritos ni
  risas, así que la detección dio 0 picos ahí; solo está comprobada con datos fabricados. Hay
  que ajustarla con un directo de verdad.
- **Videos de varias horas.** El más largo probado dura 38 minutos.
- **Centrado en el rostro.** El video de prueba no tiene caras; funciona el flujo pero no está
  comprobado el acierto con una persona real.
- **Última ronda de correcciones.** Las correcciones a la cuarta revisión de Codex pasaron mis
  pruebas pero Codex no las ha vuelto a revisar.
- El repositorio git está inicializado **sin ningún commit**.

## Limitaciones conocidas

- Las propuestas son una heurística (pausas, cierres de frase, ritmo, preguntas, cifras, picos de
  volumen). No entiende el contenido ni mira la imagen. Detecta momentos intensos, no
  necesariamente buenos.
- El resaltado de palabra usa los tiempos reales de la transcripción si no editaste el texto; si
  lo editaste, reparte el tiempo según el largo de cada palabra. La vista previa siempre usa el
  reparto aproximado.
- «Dividir» no busca rostros si salen más de 60 partes (tardaría demasiado); esas partes nacen
  con el recorte centrado.
- El centrado en el rostro es fijo para todo el clip; no sigue a quien se mueve.
- Cancelar no es inmediato durante la carga del modelo, la consulta inicial de yt-dlp ni la
  fusión de pistas.
- La protección contra enlaces hacia la red local no cubre redirecciones.
- La vista previa de «Ajustar» con fondo difuminado muestra fondo negro; el MP4 sí lo lleva.

## Del video de reseña, lo que queda fuera por ahora

| Función vista en editores comerciales | Por qué no está |
|---|---|
| Quitar frases del medio de un clip | Requiere unir varios tramos y recalcular los tiempos de los subtítulos. Es el siguiente candidato natural |
| Música de fondo y efectos de sonido | Necesita una biblioteca de audio con licencia, o que subas tus propios archivos |
| B-roll (videos de fondo relacionados) | Necesita un banco de video con licencia o una API de pago |
| Transiciones, memes, videos superpuestos | Necesitan material propio; se puede añadir «sube tu archivo» |
| Llamada a la acción y pantalla final | Factible sin material externo; no se hizo todavía |
| Puntuación de viralidad | Descartado a propósito: sería un número inventado |
| Publicar y programar en redes | Requiere registrar una aplicación en cada plataforma |

## Próximos pasos propuestos

1. **Probar con enlaces reales de Twitch y Kick** (VOD). Pásame uno de cada una y ajusto lo que
   falle.
2. **Ajustar los picos de volumen con un directo real** y añadir un modo «momentos» que proponga
   clips alrededor de cada pico.
3. **Picos de actividad del chat** de Twitch (mensajes por segundo, emotes) combinados con el
   audio. En Kick depende de una vía no oficial.
4. **Quitar frases del medio de un clip.**
5. **Subir tu propia música** de fondo, con control de volumen.
6. Directos en curso (grabar por tramos mientras ocurre).
7. Pasada final de Codex y primer commit.

## Archivos de referencia

- [README.md](../README.md): instalación, uso, configuración y arquitectura.
- [revision-codex.md](revision-codex.md): las cuatro pasadas de Codex y qué se corrigió.
- Pruebas:
  - `uv run pytest`
  - `uv run python scripts/prueba_e2e.py "$env:LOCALAPPDATA\ClipStudio\pruebas\video_prueba.mp4"`
  - `uv run python scripts/prueba_bloques.py "$env:LOCALAPPDATA\ClipStudio\pruebas\video_prueba.mp4"`
