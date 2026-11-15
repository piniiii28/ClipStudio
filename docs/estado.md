# Estado del proyecto y próximos pasos

Actualizado el **2026-11-15**. Este archivo resume la implementación actual. Los informes de
análisis y las propuestas iniciales se conservan como referencias históricas.


> **Norma:** las funciones se dan por verificadas solo cuando se comprueban en la aplicación de
> escritorio. Las pruebas en navegador son apoyo; ver [AGENTS.md](../AGENTS.md).

## Situación actual

### Versión 0.4.0

El editor incorpora sugerencias de títulos a partir del texto conservado, revisión de
legibilidad y búsqueda de momentos por palabras del tema. Funcionan localmente.
La revisión del ancho es aproximada y las propuestas de títulos son extractivas.

El historial conserva hasta 50 cambios por clip, permite deshacer y rehacer entre
reinicios y elimina la rama de rehacer al editar de nuevo. Las ediciones usan una revisión
para detectar cambios concurrentes. Los borradores de guardados sin confirmar se pueden
recuperar o descartar al volver al editor.

Seguir por planos se ejecuta en una cola con progreso y cancelación. Al reintentar se
reutilizan las tomas completadas para la misma fuente y rango. Los trabajos interrumpidos
se muestran como recuperables al abrir. El resultado se aplica si el clip conserva la
revisión analizada.

El encuadre Stream admite hasta 100 intervalos sin solapamiento que alternan cámara,
gameplay y mixto. Los tiempos corresponden al video fuente. La protección HUD amplía la
región del juego para incluir la zona marcada. Las regiones se comparten entre intervalos.
La vista previa y el MP4 utilizan las mismas decisiones de composición.

### Versión 0.3.5

Corregido el cierre durante la actualización. La señal de instalación sobrevive al
lanzamiento del instalador y el proceso devuelve el código que espera la ventana.
El instalador cierra también ventanas de versiones anteriores que esperan confirmación.
La interfaz guarda los cambios antes de instalar y evita avisos repetidos de conexión
durante ese cierre. Se verificó una reproducción de 0.2.3 con instalador precargado y
datos aislados, que se actualizó a 0.3.5 y conservó el proyecto. Regresión de 383 pruebas
aprobadas y una omitida.

### Versión 0.3.4

Publicada como actualización estable con instalador Windows y archivo SHA-256.
La prueba del actualizador, simulando una versión local 0.2.3, detectó 0.3.4 y comprobó
que la huella publicada coincide con el paquete generado. La instalación local informó
0.3.4 y se abrió en WebView2. Batería de 383 pruebas aprobadas y una omitida.

La actualización se obtiene desde **Actualizaciones**, descargando el paquete desde la
propia app y usando después **Instalar y reiniciar**. La búsqueda automática consulta
como máximo cada seis horas y la búsqueda manual puede forzarse desde el panel.
[Release 0.3.4](https://github.com/piniiii28/ClipStudio/releases/tag/v0.3.4).

### Versión 0.3.3

El botón del motor alternativo se llama **Seguir por planos**. Las instrucciones de uso
de README y de escritorio utilizan este nombre.

### Versión 0.3.2

El seguimiento por planos procesa todas las tomas de clips de hasta 10 minutos.
El presupuesto de muestras crece con la cantidad de planos y se reparte por duración,
con un mínimo de cuatro muestras por toma. Los grafos extensos de exportación se
entregan a FFmpeg mediante un archivo temporal para admitir trayectorias grandes en Windows.

La regresión pasa 383 pruebas y omite una. Incluye análisis y exportación de 60 tomas
sintéticas, exportación de 1000 puntos de seguimiento y limpieza del archivo temporal
tras éxito o fallo. Una secuencia de 128 segundos construida repitiendo el fragmento
local de TenZ produjo 80 planos, 624 puntos y cobertura facial completa de las muestras.
La misma secuencia se analizó desde el botón de la ventana del portable 0.3.2 y se exportó
con el perfil Borrador. La interfaz mostró la exportación lista y el instalador actualizó
la app a 0.3.2. El ejecutable instalado coincide con el portable probado.

### Versión 0.3.1

El acento de la interfaz y la forma de onda pasan a morado. **Seguir por planos ·
OpenShorts** añade una alternativa al motor clásico en los encuadres Rellenar y Dividido.
Usa PySceneDetect para cortes y YuNet para rostros, con reinicio por toma, zona de tolerancia
y confirmación de movimientos grandes. La trayectoria se guarda con el clip y se comparte
entre vista previa y exportación. Admite hasta 10 minutos y 30 planos por análisis.
La selección de hablante mediante audio y los cambios automáticos de composición siguen
pendientes. El modo Stream conserva sus controles de cámara y gameplay.

La batería de regresión de esta versión pasa 381 pruebas, incluida detección de cortes
con tiempos enteros y decimales, estabilidad de cámara, protección frente a cambios
concurrentes y exportación real de la trayectoria entre dos tomas.
En el portable 0.3.1 se comprobó el botón alternativo con un fragmento aislado de TenZ,
con tres planos y cobertura facial completa de las muestras. La exportación desde el
motor compilado terminó correctamente. El instalador actualizó la app y la biblioteca
existente se abrió con el tema morado.

### Versión 0.3.0

Compilada, instalada y abierta en Windows. La biblioteca incorpora miniaturas, búsqueda sin
acentos, filtros, ordenación y contadores. El editor muestra la forma de onda y permite
elegir perfiles de exportación, normalizar volumen, revisar la salida y generar portadas JPG.
La navegación y el formulario En vivo se comprobaron también en una ventana de 1020 × 760.
Se corrigió el guardado al cerrar con la URL versionada, con verificación del dato persistido.

La revisión de OpenShorts y las veinte iteraciones están documentadas en
[iteraciones-openshorts.md](iteraciones-openshorts.md). Se mantienen JavaScript modular y
WebView2, aprovechando el motor local y las funciones existentes.

- Batería actual de 373 pruebas aprobadas y una omitida.
- Flujo integral con voz real de 81 comprobaciones sobre el servidor desde fuente.
- Captura simulada de 46 comprobaciones con el portable compilado.
- Twitch bystaxx y Kick rowmeister entregaron captura, imagen, conexión al chat y clips
  breves. Twitch recibió tres mensajes e incluyó publicidad. Kick recibió cero durante
  la muestra. El clip de Kick se exportó a 720 × 1280 con normalización.

La continuidad durante sesiones largas y la descarga de alta calidad de Kick requieren
pruebas adicionales. Durante la revisión, una ventana de prueba vacía al restaurarse
recuperó el contenido tras reiniciarse. La instalación final se abrió correctamente.

### Funciones disponibles

ClipStudio permite importar videos, crear clips verticales, editar subtítulos y encuadres,
y exportar MP4. Captura un directo de Twitch, YouTube o Kick, muestra una imagen reciente
del búfer y puede crear clips por aumentos de actividad del chat.

La primera versión de escritorio para Windows está compilada, instalada y verificada en
este equipo. Conserva la interfaz y los proyectos de la versión de navegador. No inicia
ninguna grabación automáticamente al abrirse.

## Arranque y datos

| Modalidad | Arranque |
|---|---|
| App instalada | Acceso directo **ClipStudio** en el escritorio o menú Inicio |
| Ejecutable instalado | `%LOCALAPPDATA%\Programs\ClipStudio\ClipStudio.exe` |
| Portable | `dist/ClipStudio/ClipStudio.exe`, junto a toda su carpeta `_internal` |
| Instalador generado | `dist/ClipStudio-Setup.exe` |
| Escritorio desde el código | `iniciar.bat` o `uv run python -m clipstudio --escritorio` |
| Navegador desde el código | `uv run python -m clipstudio` |
| Solo servidor | `uv run python -m clipstudio --no-abrir` |

El servidor usa por defecto `http://127.0.0.1:8765`. Proyectos, exportaciones, modelos,
ajustes, fondos y búferes permanecen en **`%LOCALAPPDATA%\ClipStudio`**, fuera de OneDrive.
La instalación y los datos son independientes; desinstalar conserva los proyectos.

La app incluye Python, FFmpeg, ffprobe y Node.js. Requiere Windows 10/11 x64 y WebView2;
la primera transcripción necesita descargar el modelo si aún no está disponible.

### Ventanas y cierre

- Un segundo doble clic activa la ventana existente. Otro bloqueo evita dos motores
  escribiendo sobre la misma carpeta de datos.
- **Minimizar mantiene la grabación y las exportaciones.**
- Al cerrar desde el editor se espera al guardado de cambios. Si falla, la ventana permanece
  abierta para reintentarlo.
- Si hay una grabación o trabajos activos, se avisa antes de detenerlos. Parar el directo
  elimina su búfer temporal; los clips ya guardados se conservan.
- El servidor creado por la ventana se detiene al cerrarla. Un servidor que ya estaba abierto
  se reutiliza y permanece funcionando; el aviso de cierre explica esta situación.
- Para motores independientes hacen falta carpetas de datos y puertos distintos.

Detalles de instalación, registros y compilación: [ESCRITORIO.md](ESCRITORIO.md).

## Funciones implementadas

| Área | Qué está disponible |
|---|---|
| Importación | Archivos y enlaces compatibles con yt-dlp; progreso, límites, cancelación y reintento |
| Transcripción | faster-whisper local, tiempos por palabra, bloques de unos 30 min y avance recuperable |
| Clips | Propuestas por pausas, frases, ritmo y volumen; creación manual y división completa con cortes ajustables a pausas |
| Edición | Inicio/fin, texto y tiempos de subtítulos, quitar frases, cortes internos y detección de silencios |
| Estilo | Seis preajustes, palabra resaltada, caja, colores, tamaño, posición, título gancho con duración y marca de agua |
| Preferencias | Guardar estilo para clips nuevos y aplicar subtítulos o estilo/encuadre a otros clips |
| Encuadre | Rellenar, ajustar con fondos, dividido con video externo, seguimiento del rostro y composición de streams |
| Exportación | MP4 1080×1920 H.264 + AAC, subtítulos incrustados, tiempos recalculados tras cortes y exportación por lotes |
| Directos | Búfer circular, volumen, chat, momentos, clips manuales/automáticos e imagen reciente |
| Escritorio | WebView2, motor local administrado, ventana única, cierre controlado, portable e instalador por usuario |
| TikTok | Hasta cinco hashtags temáticos por clip, contexto opcional, motivos, bloque editable/copiable y guardado por clip |

### Hashtags para TikTok

Pestaña **TikTok → Recomendar hashtags**. Analiza título, gancho y subtítulos editados del
fragmento conservado; sin subtítulos usa la transcripción dentro de sus límites y cortes.
Permite indicar juego o tema cuando no se menciona y explica las etiquetas propuestas.
No asume que TenZ u otro creador está jugando un título concreto. El bloque y el contexto
se guardan por clip en `clips.tiktok` (JSON, migración compatible con bases existentes).

Es una heurística local con catálogo de juegos/temas y contexto manual, sin análisis visual,
modelo generativo ni datos de tendencias. No garantiza alcance ni publica en TikTok.
Se pueden editar/copiar las etiquetas y consultar Creative Center mediante un enlace.
Recomendar de nuevo reemplaza el bloque; los cambios de contenido requieren regenerarlo.

La batería actual pasa **169/169 pruebas**. Las nuevas cubren tramos eliminados, límites del
clip, subtítulos editados, ausencia de inferencias por creador, etiquetas duplicadas,
persistencia independiente por clip, migración repetible y validación de la API.
Se comprobó además con el ejecutable, en un proyecto aislado, la generación desde la pestaña,
el aviso de copia y la persistencia en SQLite después de cerrar la ventana. Se recompiló el
paquete y se instaló la actualización conservando los diez proyectos existentes. La API
del ejecutable instalado se comprobó sin modificar el clip; estas pruebas no envían nada a TikTok.

### Encuadre y cámara

Hay dos composiciones distintas:

- **Dividido:** clip arriba y video de juego abajo, en bucle y sin mezclar su audio. El
  fondo puede ser local (`%LOCALAPPDATA%\ClipStudio\fondos`) o **de YouTube sin descargar**:
  la vista previa usa el reproductor incrustado y al exportar se baja solo el tramo
  necesario (unos 40 MB por clip, caché de 1 GB en `cache_fondos`). Catálogo de serie:
  Minecraft parkour (perpexior) y Subway Surfers (OrbitalNCG +); se pueden añadir más con un
  enlace. Crédito del autor opcional y con tamaño, dibujado en la esquina de la franja.
- **Stream (cámara y gameplay):** ambas zonas proceden del mismo video. Permite cámara arriba
  y gameplay abajo, solo cámara o gameplay completo. El área de juego se conserva completa
  dentro del panel, con fondo difuminado para llenar el espacio.

En **En vivo → Vista del directo y encuadre** se marcan cámara y gameplay por arrastre,
se ajusta la altura de cámara (30 % inicial) y se aplica la composición a los próximos clips.
Los existentes se corrigen en **Encuadre y estilo → Stream (cámara y gameplay)**.
Sin cámara detectada o marcada se muestra el gameplay completo.

La detección de webcam usa YuNet local, incluido con licencia MIT en `clipstudio/modelos`.
Se verificó sobre la cámara de perfil de TenZ. Estima una región fija por clip, corregible a
mano. El seguimiento horizontal usa detección frontal/de perfil de OpenCV, suavizado y
vuelta al centro tras perder el rostro durante 1,5 s. OpenCV está fijado a 4.x porque la
versión 5 probada carecía de `CascadeClassifier`.

## Modo en vivo

1. Pegar el enlace y elegir lectura de chat, clips automáticos y retraso de reacción.
2. Conectar. Se captura un directo a la vez; el búfer retiene por defecto los últimos 60 min.
3. Revisar imagen, volumen, actividad del chat y momentos detectados.
4. Guardar los últimos 30/60/90 s, convertir un momento o usar los clips automáticos del chat.
5. Abrir el proyecto resultante para editar, transcribir y exportar.

La imagen es una **instantánea del último segmento cerrado**, actualizada aproximadamente
cada 6 s. No es un reproductor continuo ni otra conexión a la plataforma. Puede tardar en
aparecer al conectar, hasta que haya un segmento utilizable.

### Calidad del búfer y clips en alta calidad
- `clipstudio/vivo_calidad.py`: formato de yt-dlp por calidad (`b[height<=N]/bv*[height<=N]+ba/...`),
  estimaciones GB/h, preferencias (`vivo` en la tabla de preferencias), lectura de listas HLS y
  alineación por correlación cruzada del audio. Rutas nuevas: `GET/PUT /api/vivo/preferencias`,
  `GET /api/vivo/calidades?url=`, `GET /api/vivo/{id}/opciones-clip`, `POST /api/vivo/{id}/clip`
  (`calidad: buffer|alta`, `altura`, `recordar`; `alta` devuelve 202 con `descarga_id`) y
  `POST /api/vivo/{id}/descargas/{did}/cancelar|usar-bufer`.
- Alta calidad, hechos comprobados con red real (13/11/2026): YouTube con DVR expone en HLS la última
  hora con `EXT-X-PROGRAM-DATE-TIME`; Twitch tiene un VOD en curso (`twitch:videos`, `is_live`) con
  hora por segmento. El video y el audio de YouTube son listas HLS distintas que empiezan en segmentos
  distintos (5 s), por eso no se usa `download_ranges`/`-ss` sobre la lista remota: se recorta cada lista
  por hora de reloj y FFmpeg lee solo esos segmentos (sin recodificar). Kick: se usa `kick:videos`, sin
  probar con un directo real. Un anuncio de Twitch en el búfer impide alinear (se rechaza y se ofrece el búfer).
- Riesgo conocido: en YouTube el búfer lee video y audio de dos listas y puede arrastrar hasta un segmento
  (5 s) de desfase entre ambos; el clip en alta calidad sale sincronizado.

### Carpetas (Ajustes)
- `clipstudio/ajustes.py` guarda `carpetas` en preferencias: exportaciones (copia además de la interna;
  columnas `copia` y `aviso` en `exportaciones`), búfer en vivo (subcarpeta `ClipStudio-bufer` de la elegida)
  y fondos. Validación: ruta absoluta, existe o se crea, es carpeta, se puede escribir, no es raíz de disco
  ni carpeta de la aplicación/Windows. El búfer nuevo se aplica al reconectar.

### Plataformas y automatización

| Plataforma | Lectura del chat | Evidencia durante la implementación |
|---|---|---|
| Twitch | IRC seguro, acceso público | TenZ: captura, mensajes reales, imagen y recorte MP4 |
| YouTube | Lector de yt-dlp en un subproceso cancelable | Mensajes en un chat activo; captura real verificada en la fase inicial |
| Kick | Centrifugo público y sesión de invitado renovable | Pirutastic: captura, mensajes, imagen, detección de cámara y exportación vertical |

Los lectores se reconectan independientemente del grabador. Un fallo de chat se muestra y
no detiene el video. No se conserva un registro del contenido del chat; se usan identificadores,
usuarios y tiempos para deduplicación y métricas.

El disparador pide al menos 3 mensajes/s en la ventana suavizada, duplicar la media anterior,
z-score ≥ 3, tres usuarios y dos evaluaciones consecutivas. Requiere al menos 20 s válidos
de historial (aproximadamente 25–30 s desde la conexión), limita la aportación por usuario
y espera 60 s entre picos.

Cada clip automático incluye **25 s anteriores y 10 posteriores**. Espera al material posterior,
serializa conversiones y reutiliza el proyecto si se repite la petición del mismo momento.
Se restan por defecto 3 s de reacción del chat, ajustables al conectar. Los picos de audio
se ofrecen como momentos para conversión manual; combinar chat y audio en un disparador
ponderado sigue pendiente.

### Correcciones de integración

- Flujo completo de chat a momento, proyecto y clip editable, conservando el fragmento entero.
- Imagen del búfer y selección de zonas compartidas entre vivo, editor y exportación.
- Validación del encuadre y pruebas de geometrías inválidas para evitar errores al guardar.
- Extracción JPEG buscando después de abrir el segmento TS, para evitar imágenes vacías.
- Aviso cuando la interfaz nueva se conecta a un servidor antiguo sin soporte para la imagen.
  Actualizar Python requiere reiniciar el motor; antes hay que parar la captura y guardar clips.
- Worker de YouTube adaptado al ejecutable sin consola, registro de Uvicorn sin dependencia
  de terminal y empaquetado de interfaz, modelos y herramientas.

## Verificación disponible

Resultados registrados el **12 de noviembre**. La batería automatizada se repitió al añadir
hashtags; las dos pruebas integrales corresponden a la ronda anterior de escritorio:

| Comprobación | Resultado y alcance |
|---|---|
| `pytest` | **169/169**; arranque, chat, Kick, cortes, encuadre, directos, escritorio y hashtags |
| `prueba_vivo.py --ejecutable …` | **31/31**; directo simulado con FFmpeg, momentos, clips, segunda sesión rechazada y parada/limpieza |
| `prueba_e2e.py VIDEO --ejecutable …` | **80/80**; video de 90 s, transcripción, edición, estilos, cortes, fondos, audio, sincronización y lotes |
| Ventana Windows instalada | Proyectos, editor y reproducción; segundo arranque; cierre desde el editor y reapertura |
| Instalador | Instalación por usuario, acceso directo, ejecutable idéntico al portable y sin reinicio de Windows |

La prueba integral comprueba resolución/codecs, audio audible, duración, subtítulos visibles y
sincronizados dentro de tolerancia, gancho, palabra resaltada, marca de agua, fondos, pantalla
dividida, cortes, silencios y suma de duraciones de las partes exportadas.

Evidencia anterior: bloques/reanudación con 38 min de audio, interfaz en Chrome, exportaciones
con seguimiento de hasta 120 puntos y composición de stream en tres modos. Las comprobaciones
reales anteriores de plataformas no equivalen a una nueva prueba de red desde el instalador
ni a una prueba sostenida durante horas.

Medición histórica: unos 3 min para transcribir 30 min de audio con `small` en CPU en este equipo.
Es orientativa; descarga, proxy y exportación añaden tiempo.

## Limitaciones y pendientes reales

- **Reconexión del video:** no recupera automáticamente una captura perdida o una dirección
  multimedia caducada. Quedan mejoras de alineación temporal y discontinuidades.
- **Sesiones prolongadas:** no se verificaron emisiones de varias horas, renovación real de Kick
  durante toda una sesión larga ni consumo sostenido de memoria/disco. La prueba de bloques
  más larga fue de 38 min; el límite configurado de video es 12 h.
- **Plataformas:** faltan pruebas amplias de VOD/clips de Twitch y Kick y canales con distintos
  ritmos. Los servicios públicos y yt-dlp pueden cambiar; no se garantiza todo enlace.
- **Momentos:** las propuestas son heurísticas, sin puntuación de viralidad ni comprensión
  semántica. Falta calibrar falsos positivos con directos reales y combinar chat/audio.
- **Rostros:** faltan más pruebas con varias personas, oclusiones, giros y poca luz. La webcam
  no sigue cambios de layout automáticamente. El seguimiento muestrea hasta 120 fotogramas
  y puede elegir a otra persona; al dividir más de 60 partes no busca rostros automáticamente.
- **Subtítulos:** después de editar texto, el resaltado aproxima los tiempos por palabra;
  la vista previa también aproxima ese reparto. La transcripción puede requerir correcciones.
- **Cancelación:** carga del modelo, consulta inicial y fusión de yt-dlp pueden tardar en
  atenderla. El escritorio tiene esperas limitadas y cierre forzado del árbol propio como respaldo.
- **Seguridad:** el filtro de destinos privados no cubre todas las redirecciones ni cambios
  posteriores de DNS. La app no está preparada como servicio público en Internet.
- **Distribución:** no tiene firma digital. Busca actualizaciones al iniciar (módulo `actualizaciones.py`, ver ESCRITORIO.md); la instalación real de una versión nueva con el instalador actualizado aún no se ha probado. Falta probarla en
  Windows limpio y sin WebView2. Antes de distribuir a terceros hay que revisar las licencias.
- **Revisión y Git:** las revisiones formales antiguas se conservan en `revision-codex.md`;
  las pruebas no sustituyen una auditoría completa. Los cambios por versión se registran en
  [CHANGELOG.md](../CHANGELOG.md); la 0.2.0 es la primera publicada con instalador.
- **Fondos de YouTube:** dependen de yt-dlp y de que YouTube permita la descarga; un video
  del catálogo puede desaparecer. No se probó añadir un fondo propio ni cancelar su descarga
  con clics reales. La vista previa incrustada se verificó en Chrome, no en la ventana WebView2.

## Próximos pasos propuestos

1. Reconectar la captura y tratar latencia/discontinuidades sin perder la sesión.
2. Probar sesiones largas en las tres plataformas, renovación del chat y recursos sostenidos.
3. Calibrar disparadores con canales reales y combinar señales de chat y audio.
4. Verificar VOD/clips de Twitch y Kick, y más layouts de webcam/gameplay.
5. Probar Windows limpio; preparar firma, actualizaciones y distribución del instalador.
6. Publicar una 0.2.1 para probar la actualización real desde una 0.2.0 instalada.

Funciones todavía fuera del alcance: música propia con control de volumen, B-roll,
transiciones/superposiciones, llamada a la acción, pantalla final y publicación/programación
en redes. Quitar frases, grabar directos y crear clips por chat ya están implementados.

## Referencias y comandos

- [README.md](../README.md): uso, configuración y arquitectura.
- [ESCRITORIO.md](ESCRITORIO.md): instalación, cierre, registros y compilación.
- [diseno-modo-en-vivo.md](diseno-modo-en-vivo.md): propuesta original y diferencias actuales.
- [revision-codex.md](revision-codex.md): revisiones formales históricas.
- [informe-rea.md](informe-rea.md): investigación inicial del producto de referencia.

```powershell
uv run pytest -q
uv run python scripts/prueba_vivo.py --ejecutable dist/ClipStudio/ClipStudio.exe
uv run python scripts/prueba_e2e.py RUTA_VIDEO --ejecutable dist/ClipStudio/ClipStudio.exe
uv run python scripts/prueba_bloques.py RUTA_VIDEO
```

Las pruebas de directo e integral usan puertos 8798/8799 y datos temporales separados.
Usar un video con voz de unos 90 s para la prueba integral: las comprobaciones de división
necesitan duración suficiente. Sin `--ejecutable` se prueba el servidor desde Python.
