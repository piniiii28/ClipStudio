# Registro de cambios

Formato: una entrada por versión publicada, con lo añadido, lo corregido y lo que se sabe
que falta. El detalle técnico y las pruebas de cada función están en
[docs/estado.md](docs/estado.md).

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
