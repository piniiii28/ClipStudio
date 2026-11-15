# Mejoras de ClipStudio a partir de OpenShorts

Trabajo iniciado el 15 de noviembre de 2026 sobre ClipStudio 0.2.3.

Se revisaron README, AGENTS, CHANGELOG, estado, guía de escritorio y rondas anteriores.
La versión resultante es 0.3.0, compilada e instalada localmente en Windows. Se conservan
los módulos JavaScript y WebView2 para aprovechar el editor y sus controles existentes.

## Referencias

OpenShorts se distribuye bajo MIT. Se revisaron `ffmpeg_utils.py`, `quality_probe.py`,
`thumbnail.py`, `scene_detection.py`, `punch_in.py`, `panel_layout.py`, `screencast_layout.py`
y `twitch_signals.py`. Sus rutas de Gemini, TransNetV2 y Helix implican dependencias o
credenciales adicionales. Las incorporaciones elegidas aprovechan el motor local de ClipStudio.

- https://github.com/mutonby/openshorts
- https://github.com/mutonby/openshorts/blob/main/ffmpeg_utils.py
- https://github.com/mutonby/openshorts/blob/main/quality_probe.py
- https://github.com/mutonby/openshorts/blob/main/thumbnail.py

## Registro de veinte iteraciones

Las veinte iteraciones se completaron con las comprobaciones indicadas.

| Iteración | Trabajo | Estado y evidencia |
|---|---|---|
| 01 | Revisión de documentación y referencia, batería inicial | Completada. Documentación del proyecto y ocho módulos de referencia revisados. Base de 366 pruebas aprobadas y una omitida. |
| 02 | Atribución MIT y adaptación del tratamiento de metadatos | Completada. Aviso MIT incluido en fuente y paquete. Exportación real comprobada con metadatos de origen eliminados. |
| 03 | Normalización opcional de volumen | Completada. Loudnorm a −14 LUFS integrado con audio, cortes y exportación. Prueba con señal de bajo volumen. |
| 04 | Perfiles de exportación | Completada. Social y Calidad a 1080 × 1920, Borrador a 720 × 1280. Los tres se renderizan en pruebas reales. |
| 05 | Comprobación de calidad previa a exportar | Completada. Dimensiones, audio, subtítulos, cortes y cámara pendiente. Pruebas de avisos y API sobre clip real. |
| 06 | Panel de revisión de salida | Completada. Perfil y normalización aplicables a un clip o lote. Revisión visible en la ventana Windows. |
| 07 | Miniaturas con caché acotada | Completada. Miniaturas de proyectos, límite de 80 auxiliares por proyecto y dos procesos generadores simultáneos. Prueba concurrente de seis peticiones. |
| 08 | Portadas verticales descargables | Completada. JPG de 720 × 1280 del fotograma elegido, ajustado con fondo difuminado. Generación y enlace comprobados en escritorio, respuesta JPG validada por API. |
| 09 | Forma de onda del fragmento | Completada. PNG de audio del clip, generado con FFmpeg y visible en el editor Windows. |
| 10 | Navegación precisa desde la forma de onda | Completada. Control temporal sincronizado con el reproductor. Clic y tecla de dirección verificados, posición de 5,94 s y subtítulos correspondientes visibles. |
| 11 | Búsqueda y filtros de biblioteca | Completada. Búsqueda sin acentos y filtro por estado. En Windows, «camara» encuentra «cámara». |
| 12 | Ordenación y resumen de proyectos | Completada. Orden por fecha, nombre o cantidad de clips, contadores y actualización sin reconstruir tarjetas idénticas. Biblioteca real instalada con 15 proyectos y 62 clips. |
| 13 | Diseño visual de navegación y biblioteca | Completada. Navegación lateral, miniaturas, tarjetas y tema oscuro con acento menta. Inspección visual de la app instalada. |
| 14 | Diseño del espacio de edición | Completada. Paneles, vista vertical y controles de entrega revisados en el editor de escritorio. |
| 15 | Jerarquía visual y estados del panel en vivo | Completada. Panel de conexión y controles reorganizados. Aviso tras fallos de consulta y recuperación al reconectar. Formulario comprobado en ventana nativa compacta. |
| 16 | Accesibilidad, teclado y tamaños de ventana | Completada. Etiquetas de controles, foco y movimiento reducido. Marcador Alt+M con protección en campos de texto. Navegación y formulario comprobados a 1020 × 760, biblioteca instalada a tamaño normal. |
| 17 | Fallos, concurrencia e integridad de archivos auxiliares | Completada. Escritura atómica y entrega de bytes para evitar carreras de limpieza. Corregido guardado al cerrar con URL versionada, comprobado mediante edición, cierre inmediato y lectura del dato persistido. |
| 18 | Pruebas de Twitch bystaxx y Kick rowmeister | Completada. Ambos entregaron captura, imagen, conexión al chat y un clip de unos 18 s. Twitch recibió tres mensajes, Kick cero durante la muestra. |
| 19 | Regresión multimedia e integración de escritorio | Completada. 373 pruebas aprobadas, una omitida. Flujo con voz real de 81 comprobaciones sobre servidor desde fuente. Captura simulada de 46 comprobaciones con el portable compilado. |
| 20 | Portable, instalador, documentación y verificación final | Completada. Versión 0.3.0 compilada con Inno Setup, instalada y abierta en Windows. Guías, estado y cambios actualizados. |

## Alcance de las comprobaciones

El código de tratamiento de metadatos y el filtro de normalización adaptan ideas de
`ffmpeg_utils.py`, con atribución en [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
La revisión de salida, las miniaturas y las portadas se implementan sobre el motor local
de ClipStudio. Las rutas de modelos y servicios externos de OpenShorts quedan como referencia.

La portada representa un fotograma completo con fondo difuminado. La composición, el gancho
y los subtítulos del MP4 se revisan desde el editor. La onda representa el audio de origen
entre los límites del clip, con su posición temporal original.

Los canales estaban emitiendo durante la prueba del 15 de noviembre. En Twitch apareció
publicidad al inicio. Kick conectó el chat y no recibió mensajes durante la muestra breve.
Se comprobó además una exportación del clip de Kick a 720 × 1280 con normalización.
La continuidad durante sesiones largas y la descarga de alta calidad de Kick requieren
comprobaciones adicionales. Los resultados de servidor y portable se indican por separado
en la tabla. Los registros, medios y datos de prueba permanecen en carpetas ignoradas por Git.

La interfaz se comprobó en WebView2 desde fuente, con datos de prueba aislados, y en la
instalación 0.3.0 con la biblioteca existente. Una ventana de prueba que quedó vacía al
restaurarse recuperó el contenido al reiniciar. La biblioteca instalada renderizó tras
la instalación. El instalador y el portable se generaron localmente.
