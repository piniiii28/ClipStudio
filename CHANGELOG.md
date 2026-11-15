# Registro de cambios

Formato de entradas por versión, con lo añadido, lo corregido y lo que se sabe
que falta. El detalle técnico y las pruebas de cada función están en
[docs/estado.md](docs/estado.md).

## 0.3.5 — 2026-11-15

- La señal de instalación permanece disponible después de lanzar el instalador,
  para que la ventana reciba el código de salida de actualización y se cierre.
- El instalador usa Restart Manager para cerrar los procesos que utilizan el ejecutable
  sustituido, incluidas ventanas de versiones antiguas bloqueadas en un diálogo de cierre.

## 0.3.4 — 2026-11-15

Actualización que agrupa las mejoras de biblioteca, entrega, seguimiento por planos
y tema morado verificadas en las compilaciones locales 0.3.0 a 0.3.3.
Incluye el instalador Windows y su comprobación SHA-256 para el actualizador.

## 0.3.3 — 2026-11-15

- El botón del encuadre alternativo pasa a llamarse **Seguir por planos**.

## 0.3.2 — 2026-11-15

- Seguimiento por planos con presupuesto de muestreo adaptado al número y duración
  de las tomas. Procesa todas las tomas de clips de hasta 10 minutos.
- Exportación de trayectorias extensas mediante archivo temporal de filtros de FFmpeg,
  para admitir grafos que superan la longitud de la línea de comandos de Windows.
- Pruebas de análisis y exportación de 60 tomas sintéticas, trayectoria de 1000 puntos
  y secuencia repetida con 80 planos y detección facial real. Regresión de 383 pruebas
  aprobadas y una omitida.
- Corregida una comprobación inestable de duración en las pruebas de fondos remotos,
  usando tolerancia numérica para decimales.

## 0.3.1 — 2026-11-15

- Acento morado en navegación, botones, selección y forma de onda.
- Segundo botón **Seguir por planos · OpenShorts** junto al seguimiento clásico.
  Usa PySceneDetect y YuNet, con zona de tolerancia, confirmación de desplazamientos
  grandes y reinicio al cambiar de toma. Comparte trayectoria entre vista previa y MP4.
- El análisis admite clips de hasta 10 minutos y 30 planos. Un resultado sin rostros
  suficientes conserva el encuadre anterior. Los límites modificados durante el análisis
  se detectan antes de guardar el resultado.
- Batería de regresión de 381 pruebas aprobadas, con detección y exportación real entre
  dos tomas y prueba de seguimiento sobre un fragmento local de TenZ.

## 0.3.0 — 2026-11-15

Compilación e instalación local verificadas en Windows.

### Añadido

- Biblioteca con miniaturas, búsqueda sin acentos, filtro por estado, ordenación y resumen.
- Tema oscuro con acento menta, navegación lateral y distribución adaptable del editor.
- Forma de onda con navegación temporal mediante ratón y teclado.
- Perfiles Social y Calidad a 1080 × 1920, y Borrador a 720 × 1280, para exportación individual y por lote.
- Normalización opcional de volumen y limpieza de metadatos del archivo exportado.
- Revisión previa de resolución, audio, duración, subtítulos, cortes y cámara pendiente.
- Portadas JPG verticales a partir de un fotograma, con fondo difuminado.
- Aviso de pérdida de conexión con el motor en En vivo y atajo Alt+M para marcar momentos.

### Corregido

- Guardado de cambios al cerrar la ventana desde una dirección con versión en la URL.
- Caché auxiliar acotada, escritura atómica y entrega de imágenes protegida frente a limpieza concurrente.

### Verificación

373 pruebas aprobadas y una omitida. Flujo integral de 81 comprobaciones desde fuente,
46 comprobaciones de captura simulada con el portable y captura real breve en Twitch
bystaxx y Kick rowmeister. Veinte iteraciones y alcance detallados en
[docs/iteraciones-openshorts.md](docs/iteraciones-openshorts.md).

La muestra de Twitch incluyó publicidad. Kick conectó el chat sin recibir mensajes durante
la muestra. La continuidad de sesiones largas y la descarga de alta calidad de Kick
requieren pruebas adicionales. Se conservan los pendientes de sincronización de YouTube.

## 0.2.3 — 2026-11-13

### Añadido
- **Búfer del directo más ligero**: al conectar se elige la calidad (480p, 720p —predeterminada—
  o 1080p «Original») y la duración (10, 20 —predeterminada—, 30 o 60 min). Se muestra el consumo
  estimado por hora (medido con el bitrate del directo cuando yt-dlp lo da; si no, orientativo).
  Ambas elecciones se recuerdan. `CLIPSTUDIO_VIVO_BUFER_MIN` sigue valiendo como valor por defecto.
- **Elegir la calidad al obtener el clip**: un diálogo ofrece «Del búfer (inmediato)» con su
  resolución real y, si la plataforma lo permite, «Alta calidad desde la plataforma»
  (YouTube con retroceso: última hora de la lista HLS; Twitch y Kick: VOD en curso). Solo se
  descarga ese tramo, se alinea con el búfer comparando el audio y se muestra el progreso con
  opción de cancelar o de usar el búfer si falla. Cuando no está disponible se explica el motivo.
  La elección puede recordarse («Al crear un clip»).
- **Ajustes**: carpeta de exportaciones (copia legible `<título>_<id>.mp4` de cada MP4, sin pisar
  archivos), carpeta del búfer en vivo y carpeta de fondos, con selector nativo de carpetas en la
  app de escritorio y validación en el servidor. Proyectos, transcripciones y modelos siguen en la
  carpeta de datos de la aplicación (cambiarla entera queda fuera de esta versión).

### Problemas conocidos
- YouTube: en el búfer del directo el video puede ir unos 5 s desfasado respecto al audio
  (video y audio llegan en listas separadas). Pendiente de corregir.
- Twitch con anuncios al conectar: no se puede alinear la alta calidad; se ofrece el búfer.
- Kick: la alta calidad no se ha probado con un directo real.

## 0.2.2 — 2026-11-13

### Corregido
- Tras instalar una versión nueva, la ventana de escritorio seguía mostrando la interfaz de la
  anterior (caché de WebView2). Ahora la interfaz se revalida siempre y la caché de la ventana
  se vacía automáticamente al cambiar de versión. Se conservan las preferencias de la ventana.

### Documentación
- Norma del proyecto: todo cambio debe comprobarse en la aplicación de escritorio, no solo en
  la versión de navegador ([AGENTS.md](AGENTS.md)).

## 0.2.1 — 2026-11-13

- Interfaz rediseñada.
- Subtítulos: exportar a SRT. Clips: duplicar y atajos de teclado en el editor.
- Tendencias de YouTube, selección de la pista de audio (doblajes) y posiciones de encuadre.
- Seguimiento facial y controles de vista previa mejorados.
- Directos: marcadores manuales con nota, filtros por origen y pendientes, aviso de
  momentos fuera del búfer y acceso directo al proyecto creado.
- La captura de los últimos segundos muestra la duración realmente disponible;
  los recortes que atraviesan una interrupción del vídeo se rechazan con explicación.
- Transcripción: búsqueda sin distinguir acentos y escucha de frases o selección
  fuera del clip activo, sin cambiar sus límites ni aplicar sus cortes.
- Seguimiento: mantiene la identidad candidata con dos caras de tamaño parecido.
  Continúa siendo seguimiento espacial; no reconoce al hablante.
- Doblaje por enlace: acepta vídeo con audio incorporado junto a la pista elegida y
  descarta el audio predeterminado al mezclarlos.
- Compilación de escritorio verificable mediante GitHub Actions: portable,
  instalador, SHA-256 y captura simulada con el ejecutable. No publica una release.

Detalle, referencias y pendientes: [rondas de mejora](docs/rondas-mejora.md).

## 0.2.0 — 2026-11-12

Primera versión distribuida con instalador para Windows y aviso de actualizaciones.

### Añadido

**Aplicación de escritorio**
- Ventana propia (WebView2), instalador por usuario `ClipStudio-Setup.exe` y versión portable.
  Incluye Python, FFmpeg y Node.js: no hace falta instalar nada más.
- Ventana única, cierre controlado (espera al guardado y avisa si hay grabaciones o
  exportaciones activas). Los datos siguen en `%LOCALAPPDATA%\ClipStudio`.
- **Buscar actualizaciones al iniciar**: consulta las versiones publicadas en GitHub como mucho
  cada 6 horas, en segundo plano. Nada se descarga ni se instala sin un clic. Con el
  instalador: descarga la versión nueva, comprueba su SHA-256 y la instala. Con una copia de
  git: `git pull --ff-only` + `uv sync` si no hay cambios locales. Se puede desactivar.

**Modo en vivo**
- Captura de directos de Twitch, YouTube y Kick con búfer circular (60 min por defecto).
- Momentos por picos de volumen y por actividad del chat; clips automáticos por chat;
  «clip de los últimos 30 / 60 / 90 s». Cada clip entra como un proyecto normal.
- Imagen reciente del directo y marcado de las zonas de cámara y gameplay.

**Edición**
- Quitar frases del medio de un clip y «Quitar silencios»; la vista previa salta los tramos
  quitados y el MP4 sale compactado con los subtítulos recalculados.
- Marca de agua con el nombre del canal (texto, esquina, tamaño, opacidad y color).
- Aplicar el estilo de subtítulos, o el estilo y el encuadre, a todos los clips.
- Fondos del encuadre «Ajustar»: difuminado, oscurecido, blanco y negro o color, con
  intensidad, también en la vista previa.
- Encuadre «Stream»: cámara y gameplay del mismo video; detección de webcam (YuNet) y
  seguimiento horizontal del rostro.
- Hashtags sugeridos para TikTok (heurística local, editables).

**Pantalla dividida con juego**
- Fondos desde YouTube sin descargarlos: la vista previa usa el reproductor incrustado y al
  exportar se descarga solo el tramo necesario (caché local de hasta 1 GB).
- Incluye Minecraft parkour (perpexior) y Subway Surfers (OrbitalNCG +); se pueden añadir
  otros pegando un enlace de YouTube.
- Crédito del autor del fondo opcional y con tamaño ajustable.

**Interfaz**
- Diseño renovado: panel por secciones, etiquetas por tipo de clip, pestañas más claras.

### Corregido
- El grabador en vivo no recibía nada de Twitch (FFmpeg releía la lista HLS en bucle).
- El grabador en vivo fallaba con YouTube, que entrega video y audio por separado.
- Los nombres de fondo locales con `:` podían salirse de la carpeta de fondos en Windows.
- Varias condiciones de carrera del guardado automático y de la cola de trabajos señaladas
  en las revisiones de Codex.

### Verificación
- 281 pruebas unitarias; 81/81 en la prueba de extremo a extremo; 31/31 en la del modo en
  vivo (directo simulado); 31/31 en la de fondos de YouTube (dos exportaciones reales).
- Directos reales probados: YouTube (Lofi Girl) y Twitch (caramelooficial), con clip de 30 s
  1080p con video y audio.

### Sin verificar o pendiente
- La actualización real de una versión instalada a otra (requiere publicar una 0.2.1).
- Sesiones en vivo de varias horas y reconexión automática si el flujo se corta.
- Añadir un fondo de YouTube propio y cancelar su descarga desde la interfaz.
- Instalación en un Windows limpio y sin WebView2. El instalador no tiene firma digital:
  Windows puede mostrar el aviso de SmartScreen.

### Créditos de los fondos incluidos en el catálogo
Los videos no se distribuyen con la aplicación; se reproducen y descargan desde YouTube al usarlos.
- Minecraft parkour — canal *perpexior* (el autor lo declara libre de uso).
- Subway Surfers — canal *OrbitalNCG +* (licencia Creative Commons con atribución).

## 0.1.0 — 2026-11-11

Primera versión pública del código (sin instalador): importación de archivos y enlaces,
transcripción local, propuesta y división de clips, encuadres rellenar/ajustar/dividido,
subtítulos editables con estilos, título gancho y exportación MP4.
