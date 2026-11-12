# Diseño del modo en vivo para ClipStudio

## Estado de esta propuesta (actualizado el 12 de noviembre de 2026)

Este documento conserva el **diseño inicial**, no describe íntegramente el código actual.
El estado operativo y sus pruebas están en [estado.md](estado.md); la guía de uso está en
[README.md](../README.md). Las afirmaciones posteriores sobre funciones o contratos pendientes
pertenecen al momento en que se redactó la propuesta.

| Tema | Implementación actual respecto a la propuesta |
|---|---|
| Captura y proyectos cortos independientes | Implementado en `vivo.py`, con segmentos MPEG-TS y fuentes propias de cada proyecto |
| Organización de módulos | `vivo.py` y `chat.py`, integrados con API/pipeline existentes; no se crearon los cinco módulos `live_*` propuestos |
| Búfer | 60 minutos por defecto, configurable; no tomar los 10 minutos, cuotas y reservas de este diseño como requisitos ya implementados |
| Plataformas | Twitch, YouTube y Kick; lectores públicos y comprobaciones reales documentadas en `estado.md` |
| Clips automáticos | Ráfagas de chat, ventana de 25 s antes/10 s después, desfase de reacción y conversión sin duplicados |
| Audio y chat | Gráficos y momentos separados; la fórmula ponderada y los disparadores combinados de esta propuesta siguen pendientes |
| Imagen y encuadre | Instantánea del búfer, selección de webcam/gameplay y composición vertical del mismo video |
| Cierre | `vivo.detener_todo()`, cierre de colas y motor administrado por `desktop.py` |
| Reconexión | Chat con reconexión y renovación de invitado en Kick; reconexión del video pendiente |
| Esquema y reservas | Consultar `db.py` y `vivo.py`; no todas las tablas, estados, épocas ni reservas propuestos se implementaron |
| Resistencia prolongada | Pruebas de horas, cuotas y simulación acelerada de 24 h pendientes |

Última validación registrada: 156 pruebas automatizadas, 31/31 comprobaciones de directo
simulado y 80/80 del flujo integral con el ejecutable. No implica que se hayan cumplido todas
las metas de este diseño.

## Propuesta original

**Propuesta:** añadir una capa de captura y detección continua que convierta cada momento seleccionado en un **proyecto corto e independiente**, con un archivo fuente estable. Ese proyecto tendrá clips editables y exportables mediante el flujo actual.

La sesión en vivo no debe convertirse en un proyecto cuyo archivo y duración crezcan indefinidamente: eso choca con varias suposiciones de `pipeline.py`, `media.py`, `api.py` y el editor.

Este diseño se basa en la lectura completa de los siete módulos Python solicitados y de la estructura de `clipstudio/web/app.js`; también revisé configuración, arranque y pruebas existentes. No modifiqué archivos ni ejecuté la aplicación, comandos del proyecto o pruebas. Los contratos de Kick y Twitch quedan expresamente pendientes de verificación.

## 1. Modelo de datos

### Decisión de relación con el modelo actual

```text
sesiones_vivo
  ├── segmentos_vivo        archivos temporales del búfer
  └── momentos_vivo
        └── proyecto_id ──► proyectos
                              └── clips
                                    └── exportaciones
```

Una sesión produce muchos momentos. Cada momento materializado produce, inicialmente, un proyecto y un clip principal. Ese proyecto puede recibir más clips manuales, divisiones o propuestas mediante las funciones existentes.

**La fuente del proyecto pertenece al proyecto**, nunca apunta a un segmento del búfer. Borrar o rotar el búfer no puede romper una edición o exportación.

### Tabla `sesiones_vivo`

Todas las tablas nuevas incluirían `id TEXT PRIMARY KEY`, `creado REAL` y `actualizado REAL`, compatibles con `db.insertar()` y `db.actualizar()`.

| Campo | Tipo y finalidad |
|---|---|
| `plataforma` | `TEXT NOT NULL`: `twitch` o `kick` |
| `url` | `TEXT NOT NULL`: enlace público original |
| `canal` | `TEXT`: identificador normalizado, obtenido al resolver |
| `nombre` | `TEXT NOT NULL` |
| `estado` | `TEXT NOT NULL`: `iniciando`, `grabando`, `reconectando`, `deteniendo`, `detenida`, `finalizada`, `error`, `interrumpida` |
| `estado_chat` | `TEXT NOT NULL`: `desactivado`, `conectando`, `conectado`, `reconectando`, `error` |
| `idioma` | `TEXT NOT NULL DEFAULT 'auto'` |
| `configuracion` | `TEXT NOT NULL`: JSON de ventanas, umbrales, cuotas y modo automático |
| `inicio_utc`, `fin_utc` | `REAL`, tiempos de ciclo de vida |
| `ultimo_segmento_utc` | `REAL`, vigilancia de captura |
| `ultimo_chat_utc` | `REAL`, vigilancia del lector |
| `ultimo_media_s` | `REAL`: último extremo multimedia confirmado |
| `desfase_chat_s` | `REAL NOT NULL DEFAULT 0`, corrección descrita en §3 |
| `version_detector` | `INTEGER NOT NULL` |
| `error` | `TEXT`, último fallo relevante |

El estado del chat se separa del de grabación: perder el chat no debe detener el video.

No persistir direcciones multimedia firmadas, cookies ni tokens dentro de `configuracion`. Resolverlas en memoria y ocultarlas en logs.

### Tabla `segmentos_vivo`

| Campo | Tipo y finalidad |
|---|---|
| `sesion_id` | FK a `sesiones_vivo`, `ON DELETE CASCADE` |
| `epoca` | `INTEGER NOT NULL`: cambia al reiniciarse timestamps o cambiar la continuidad |
| `secuencia` | `INTEGER NOT NULL`: contador local creciente |
| `archivo` | `TEXT NOT NULL`: ruta relativa dentro de la sesión |
| `inicio_s`, `fin_s` | `REAL NOT NULL`: intervalo en la línea temporal de la sesión |
| `pts_inicio_s`, `pts_fin_s` | `REAL`: coordenadas originales para reconstruir el mapeo |
| `capturado_utc` | `REAL NOT NULL` |
| `programa_utc` | `REAL`: timestamp del contenido, solo si existe y resulta fiable |
| `bytes` | `INTEGER NOT NULL` |
| `estado` | `TEXT NOT NULL`: `cerrado`, `eliminando`, `borrado`, `invalido` |
| `discontinuidad` | `INTEGER NOT NULL DEFAULT 0` |
| `perfil_media` | `TEXT`: firma de codecs, resolución y pistas |
| `posible_anuncio` | `INTEGER NOT NULL DEFAULT 0`, indicio, no certeza |

Restricción única: `(sesion_id, epoca, secuencia)`. Índice de búsqueda: `(sesion_id, inicio_s, fin_s)`.

Registrar como `cerrado` únicamente un archivo terminado y validado. El archivo que FFmpeg está escribiendo no es elegible para recortar.

Los huecos de red se representan como huecos temporales; no se comprimen silenciosamente sumando duraciones.

### Tabla `momentos_vivo`

| Campo | Tipo y finalidad |
|---|---|
| `sesion_id` | FK a `sesiones_vivo`, `ON DELETE CASCADE` |
| `pico_s` | `REAL NOT NULL`, tiempo multimedia estimado del acontecimiento |
| `detectado_utc` | `REAL NOT NULL` |
| `inicio_s`, `fin_s` | `REAL NOT NULL`, ventana solicitada del clip |
| `fuente_inicio_s`, `fuente_fin_s` | `REAL`, cobertura materializada con margen |
| `estado` | `TEXT NOT NULL`: `esperando_video`, `guardando`, `disponible`, `convirtiendo`, `convertido`, `descartado`, `expirado`, `error` |
| `puntuacion` | `REAL NOT NULL` |
| `metricas` | `TEXT NOT NULL`, JSON con mensajes/s, z-score, emotes, dB y disponibilidad de señales |
| `motivos` | `TEXT NOT NULL`, JSON de explicaciones legibles |
| `desfase_aplicado_s` | `REAL NOT NULL`, copia de la corrección utilizada |
| `incertidumbre_s` | `REAL`, calidad de la alineación temporal |
| `version_detector` | `INTEGER NOT NULL` |
| `archivo_reserva` | `TEXT`, fuente corta conservada antes de convertir |
| `reserva_hasta_utc` | `REAL`, vencimiento de esa reserva |
| `proyecto_id` | FK nullable a `proyectos`, `ON DELETE SET NULL` |
| `clip_id` | FK nullable a `clips`, `ON DELETE SET NULL` |
| `error` | `TEXT` |

Índice: `(sesion_id, pico_s)`. Las transiciones de estado deben ser condicionales para impedir dos conversiones simultáneas.

### Protección de segmentos

Añadir una tabla auxiliar:

```text
reservas_segmentos_vivo(
    momento_id REFERENCES momentos_vivo(id) ON DELETE CASCADE,
    segmento_id REFERENCES segmentos_vivo(id) ON DELETE CASCADE,
    PRIMARY KEY(momento_id, segmento_id)
)
```

El recolector solo elimina segmentos sin reservas. La selección y reserva deben ejecutarse bajo el mismo bloqueo que usa el recolector, junto con una transacción SQLite.

Al confirmar un candidato se reservan los segmentos anteriores existentes; los posteriores se reservan conforme se cierran. Una vez creada su fuente corta, se liberan las reservas.

### Cambios mínimos en tablas actuales

En `proyectos`:

- `sesion_vivo_id TEXT REFERENCES sesiones_vivo(id) ON DELETE SET NULL`.
- `fuente_inicio_vivo_s REAL`: origen temporal del archivo corto dentro de la sesión.
- `estado_subtitulos TEXT NOT NULL DEFAULT 'completo'`: `pendiente`, `en_cola`, `procesando`, `completo`, `error`.
- `error_subtitulos TEXT`.

Usar `proyectos.origen = 'vivo'` y `clips.origen = 'vivo'`. Son convenciones nuevas; actualmente esos campos no tienen restricciones `CHECK`.

Esto permite conservar los momentos al ejecutar `pipeline.crear_propuestas()`, que solo borra clips con `origen = 'sugerido'`.

### Encaje con `COLUMNAS_NUEVAS`

En `db.py`:

1. Añadir tablas nuevas e índices de esas tablas a `SCHEMA`.
2. Extender `COLUMNAS_NUEVAS["proyectos"]` con los campos anteriores.
3. Crear cualquier índice sobre columnas añadidas **después** del bucle de `ALTER TABLE` de `db.iniciar()`.
4. Extender `JSON_FIELDS` con `configuracion` y `metricas`; `motivos` ya existe.
5. Añadir funciones transaccionales específicas para reservar, reclamar conversiones y publicar proyecto/clip.

`db.insertar()` abre una conexión por operación: no basta para insertar proyecto, clip y vínculo del momento de forma atómica. Tampoco conviene ampliar `db.ACTIVOS` con estados de sesiones: sus consumidores actuales presuponen trabajos finitos.

## 2. Componentes y ciclo de vida

### Organización propuesta

```text
Resolver de directo
       │
       ▼
Grabador FFmpeg ──► segmentos cerrados ──► medidor RMS
       │                    │                   │
       │                    ▼                   ▼
       │              búfer circular       detector
       │                                        ▲
       └────────────────────────────── lector de chat
                                                │
                                                ▼
                                  momento + reserva de segmentos
                                                │
                                                ▼
                                  fuente corta conservada
                                                │
                                      automático / botón
                                                ▼
                                  proyecto + proxy + clip
                                                │
                                  transcripción opcional
                                                │
                                      exportación actual
```

Propondría módulos nuevos `live.py`, `live_capture.py`, `live_chat.py`, `live_detect.py` y `live_materialize.py`. Todos los nombres de funciones nuevos que siguen son contratos propuestos.

### Resolver del directo

Crear `importer.resolver_directo()` separado de `importer.descargar()`:

- Reutilizar `validar_url()` y `comprobar_destino_publico()`.
- Validar explícitamente plataforma y formato de enlace admitido.
- Obtener la entrada multimedia y los datos necesarios para FFmpeg.
- Resolver nuevamente cuando caduque el acceso.
- Distinguir directo activo, canal desconectado, acceso denegado y fallo transitorio.

**No quitar el rechazo `is_live` de `descargar()`:** esa función sigue siendo el importador de videos terminados.

`importer._opciones()` selecciona video y audio posiblemente separados y espera producir un archivo final. No debe reutilizarse completa para captura continua. El resolver necesita un perfil específico que priorice una entrada compatible y de costo predecible.

**Pendiente de verificar:** qué expone la versión instalada de yt-dlp para los directos públicos de cada plataforma, formatos disponibles, cabeceras, caducidad, autenticación y restricciones. No se presupone ningún endpoint externo.

### Grabador y búfer

Un subproceso FFmpeg por sesión, supervisado por un hilo:

- Escribe segmentos MPEG-TS y un manifiesto local.
- Objetivo inicial de **4 segundos por segmento**.
- Preferir copia de pistas para evitar recodificar el directo completo.
- Registrar duración real: con copia, los límites dependen de los fotogramas clave y no serán exactamente de cuatro segundos.
- Nombres únicos por época y secuencia; nunca sobrescribir un archivo reservado.
- Captura y temporales bajo `DATA_DIR/vivo/<sesion_id>/`, fuera de `PROJECTS_DIR`.

El búfer circular se implementa eliminando los segmentos antiguos elegibles, no mediante sobrescritura ciega:

- Retención objetivo: **10 minutos**.
- Cuota inicial de búfer: **2 GiB**.
- Reserva mínima de espacio libre: **2 GiB**.
- Si la cuota reduce la cobertura por debajo de la ventana necesaria, rechazar esa configuración o mostrar degradación explícita.

Como referencia de dimensionamiento, a 6 Mbit/s diez minutos de video ocupan aproximadamente 450 MB, antes de otros archivos.

La eliminación debe admitir fallos por archivos abiertos en Windows: marcar `eliminando`, intentar borrar y reintentar sin perder el registro.

Reutilizar `media.herramienta()` y la creación sin ventana de `media.py`. Crear un supervisor específico: `ejecutar_ffmpeg()` bloquea hasta terminar y su progreso proporcional a una duración total no describe una captura indefinida.

### Lector de chat

Interfaz común propuesta:

```python
class LectorChat:
    def conectar(self, canal, credencial): ...
    def leer(self, cancelacion): ...   # produce EventoChat normalizado
    def cerrar(self): ...
```

Evento normalizado:

```text
id_externo
enviado_utc: opcional
recibido_utc
recibido_monotonic
usuario_hash: opcional
cantidad_emotes
tipo
```

Implementaciones: `LectorTwitch`, `LectorKick` y `LectorChatSimulado`.

Responsabilidades:

- Reconexión con espera exponencial y variación aleatoria.
- Deduplicación por identificador externo, con caché acotada.
- Normalización de emotes.
- Cola acotada y contador visible de descartes.
- Señalar intervalos sin cobertura; no tratarlos como cero mensajes.
- Procesar mensajes entrantes, sin enviar mensajes al canal.

No hace falta persistir todo el texto del chat. Basta con agregados por segundo y evidencia del momento.

**Verificación obligatoria por plataforma:** transporte admitido, autenticación, permisos, recepción desde una app local sin servidor público, identificadores, timestamps, metadatos de emotes, límites, reconexión y condiciones de acceso. La viabilidad de Kick y Twitch debe aprobarse por separado.

### Medidor de audio

Para el mínimo útil, analizar cada segmento cerrado:

1. Decodificar únicamente audio a PCM mono, 16 kHz y 16 bits.
2. Usar `transcribe.volumen_por_segundo()` para obtener RMS en dB.
3. Mapear las muestras a la línea temporal de la sesión.
4. Conservar el sobrante entre segmentos para no perder o desplazar segundos.

Esto añade latencia de segmentación, pero evita una segunda conexión al directo. El trabajo debe terminar más rápido de lo que llegan segmentos. Si se acumula retraso, degradar el medidor y comunicarlo; nunca bloquear al grabador.

No reutilizar directamente `transcribe.detectar_picos()`: utiliza contexto futuro de ±45 segundos y un percentil global del video. Se necesita una versión causal.

### Detector: fórmula inicial

Evaluación cada segundo. Son parámetros iniciales de producto, ajustables tras medir falsos positivos.

**Chat:**

- `m(t)`: mensajes válidos recibidos en el segundo `t`.
- Limitar la contribución de un usuario a cinco mensajes/s cuando exista identificador.
- `x(t) = [m(t) + m(t−1) + m(t−2)] / 3`.
- Media `μ` y desviación `σ` de `x` en los 120 segundos anteriores, excluyendo los diez segundos más recientes.
- Solo utilizar intervalos con cobertura de chat válida.

```text
z_m = max(0, (x(t) − μ) / max(σ, 1))
```

Calentamiento mínimo: 30 segundos válidos. Antes se permite detección por audio.

Sea `e(t)` la fracción de mensajes de los últimos tres segundos que contienen al menos un emote. Cada mensaje cuenta una vez, aunque repita cien emotes:

```text
C = min(6, z_m × (1 + 0.5 × e(t)))
```

Si la plataforma no entrega emotes fiables, usar `e=0` y marcar esa métrica como no disponible.

**Audio:**

- `L(t)`: RMS del segundo en dB.
- `B(t)`: mediana de los últimos 90 segundos válidos, excluyendo los cinco últimos.
- `Δ(t) = max(0, L(t) − B(t))`.
- Calentamiento mínimo: 20 segundos válidos.

```text
A = min(6, Δ(t) / 3)   si L(t) ≥ −35 dB
A = 0                 en otro caso

S = 0.7 × C + 0.3 × A
```

**Se abre candidato si ocurre cualquiera:**

| Disparador | Condición |
|---|---|
| Ráfaga de chat | `z_m ≥ 3`, `C ≥ 4`, `x ≥ 3 mensajes/s`, durante dos evaluaciones consecutivas |
| Audio | `Δ ≥ 9 dB` y `L ≥ −35 dB`, en al menos un segundo |
| Combinado | `z_m ≥ 2`, `A ≥ 2` y `S ≥ 2.5`, durante dos evaluaciones consecutivas |

Una señal ausente no equivale a cero observado: se desactiva su disparador y se informa de la cobertura. Audio puede seguir disparando sin chat, y viceversa.

**Agrupación y enfriamiento:**

- Agrupar picos separados por hasta cuatro segundos.
- Una vez abierto el momento, mantener durante diez segundos la búsqueda de un máximo más fuerte.
- Reservar desde el primer disparo el material potencialmente necesario.
- Enfriamiento de 30 segundos desde el pico final.
- Durante ese periodo, añadir evidencia al momento existente.
- Rearmar después del enfriamiento y cinco segundos consecutivos por debajo de los umbrales.
- No ampliar indefinidamente un candidato por una ráfaga sostenida.

Ejemplo de motivo guardado: «18 mensajes/s; base 4; z=3,8; 62 % con emotes; audio +10 dB». Guardar también la versión y configuración del detector.

### Recortador e integración con el flujo actual

Crear `live_materialize.conservar_momento()` para convertir los segmentos reservados en una fuente corta estable **antes de esperar por Whisper**.

Después, `convertir_momento()`:

1. Reclamar el momento de forma atómica.
2. Crear una fuente local con margen de edición.
3. Validar continuidad, pistas, duración y dimensiones.
4. Publicar el archivo con cambio de nombre atómico.
5. Dar de alta proyecto y clip.
6. Preparar proxy y, opcionalmente, transcribir.
7. Liberar reservas y eliminar temporales.

Para concatenar, no asumir que unir bytes TS produce una fuente correcta. Verificar codecs, timestamps y discontinuidades. Usar remultiplexado cuando sea seguro; si hace falta normalizar, recodificar **solo ese fragmento**.

Reutilización concreta:

| Función actual | Uso propuesto |
|---|---|
| `pipeline.carpeta_proyecto()` y `ruta_fuente()` | Ubicación estable de la fuente materializada |
| `media.sondear()` | Validación de la fuente ya cerrada |
| `media.crear_proxy()` | Previsualización del proyecto corto |
| `pipeline.preferencias_clip()` | Estilo y encuadre iniciales |
| `pipeline._nuevo_clip()` | Creación del clip con `origen='vivo'` y motivos del detector |
| `media.extraer_audio()` y `transcribe.transcribir()` | Subtítulos del fragmento cerrado |
| `pipeline.exportar()` | Exportación actual sin dependencia del búfer |
| `api._encolar_exportacion()` | Mantener la copia inmutable de parámetros |

Extraería de `pipeline.procesar_proyecto()` una preparación común que permita omitir transcripción y propuestas. Para una fuente de vivo, crear inicialmente proxy, transcripción vacía y clip; marcar el proyecto `listo`. La detección ya eligió el momento y no necesita pasar por `crear_propuestas()`.

### Hilos, colas y parada

Añadir `GestorVivo`, separado del `Gestor` actual:

- Un supervisor por sesión.
- Un lector de chat por sesión.
- Un trabajador de análisis de segmentos.
- Un detector que recibe métricas mediante colas acotadas.
- Una cola de conservación/materialización, con un trabajador inicial.
- Subprocesos FFmpeg para captura y operaciones multimedia.

**Límite inicial: una sesión activa.**

No introducir la grabación en `_colas["proyecto"]`: ocuparía el trabajador durante horas.

`media.Cancelacion` mantiene un solo `_proc`. Cada operación finita puede conservar esa clase; el supervisor necesita un evento común y un registro de todos los procesos hijos, conexiones e hilos.

Parada normal:

1. Pasar a `deteniendo`; dejar de aceptar candidatos.
2. Cerrar chat y detener reconexiones.
3. Solicitar al grabador cierre ordenado.
4. Esperar, por ejemplo, cinco segundos; terminar forzosamente si no responde.
5. Validar el último segmento; descartar el incompleto.
6. Conservar candidatos pendientes con el material disponible.
7. Liberar recursos y unir hilos con plazo.
8. Marcar `detenida`.

El grabador necesita su propio mecanismo de cierre ordenado: `ejecutar_ffmpeg()` usa `-nostdin` y `Cancelacion.cancelar()` mata directamente.

Añadir cierre en el `finally` de `api._ciclo()`, que actualmente solo arranca servicios. Para muerte abrupta en Windows, valorar un Job Object con cierre de procesos hijos; no confiar en que los hilos `daemon` limpien FFmpeg.

## 3. Retraso entre video y chat

### Tres relojes distintos

Mantener separados:

- **Tiempo multimedia:** posición del contenido.
- **UTC:** persistencia y correlación externa.
- **Monotónico:** esperas, enfriamiento y vigilancia durante una ejecución.

La hora de descarga del segmento no es la hora del acontecimiento. Tampoco debe calcularse el tiempo multimedia como `secuencia × 4`.

Cada época mantiene un mapeo entre PTS y tiempo de sesión, más anclas UTC cuando existan. Tras reconectar, registrar nueva época y preservar el hueco conocido.

### Convención del desfase

Definir:

```text
desfase_chat_s > 0:
el chat reacciona después del acontecimiento de video

pico_video_estimado = mapear_timestamp_chat_a_media() − desfase_chat_s
```

El mapeo debe considerar el retraso de llegada del video. Restar un número a la hora local del mensaje, sin ese mapeo, no resuelve la sincronización.

Cuando no existan timestamps fiables, usar llegada local y mostrar una incertidumbre mayor.

Configuración inicial:

- Desfase manual predeterminado de **5 s**, presentado como hipótesis.
- Ajuste permitido entre **−30 y +60 s**.
- Botones de ajuste rápido y vista previa del fragmento conservado.
- Guardar el desfase aplicado en cada momento; cambiarlo afecta a detecciones futuras.

Más adelante puede estimarse una corrección mediante correlación de ráfagas de chat y picos de audio en varios minutos. Solo aplicarla con coincidencias suficientes y confianza visible.

### Ventana alrededor del pico

Valores iniciales:

- Clip: **20 s antes y 15 s después**.
- Fuente conservada: **10 s adicionales por cada lado**.
- Resultado habitual: clip de 35 s dentro de una fuente de 55 s.

Si la fuente empieza en `F`:

```text
clip.inicio = inicio_sesion_del_clip − F
clip.fin    = fin_sesion_del_clip − F
```

Los tiempos de palabras, subtítulos y picos también deben expresarse respecto a esa fuente. `pipeline.exportar()` ya aplica después la conversión de subtítulos al rango exportado.

Esperar hasta tener segmentos cerrados que cubran el final de la fuente. Si el contenido todavía no llegó, mantener `esperando_video`.

Al inicio o fin de la sesión puede faltar contexto: recortar al material disponible, señalarlo y exigir al menos el mínimo admitido por `api._validar_rango()`. No unir los dos lados de un corte de red como si fueran continuos.

## 4. API HTTP e interfaz

Las siguientes son **rutas locales nuevas propuestas**, no APIs de las plataformas.

### Crear sesión

`POST /api/vivo/sesiones`

```json
{
  "url": "https://...",
  "plataforma": "twitch",
  "idioma": "auto",
  "chat": true,
  "antes_s": 20,
  "despues_s": 15,
  "desfase_chat_s": 5,
  "buffer_s": 600,
  "buffer_max_bytes": 2147483648,
  "convertir_automaticamente": false,
  "transcribir": "bajo_demanda"
}
```

Respuesta `201`:

```json
{
  "id": "uuid",
  "estado": "iniciando",
  "estado_chat": "conectando",
  "configuracion": {
    "antes_s": 20,
    "despues_s": 15,
    "desfase_chat_s": 5
  }
}
```

La resolución sucede en segundo plano. Crear la sesión no confirma todavía que el directo pueda capturarse.

### Consultas y acciones

| Ruta | Cuerpo o parámetros | Respuesta |
|---|---|---|
| `GET /api/vivo/sesiones` | `limit`, cursor | Sesiones paginadas |
| `GET /api/vivo/sesiones/{sid}` | — | Estado, cobertura, búfer, retrasos y errores |
| `GET /api/vivo/sesiones/{sid}/momentos` | Cursor estable, `limit ≤ 100` | Momentos paginados |
| `PATCH /api/vivo/sesiones/{sid}` | Desfase, sensibilidad, modo automático | Configuración efectiva y revisión |
| `POST /api/vivo/sesiones/{sid}/parar` | `{}` | `202`, estado `deteniendo`; idempotente |
| `POST /api/vivo/momentos/{mid}/convertir` | `{"titulo":"Reacción","transcribir":false}` | `202`, estado y recurso de seguimiento |
| `GET /api/vivo/momentos/{mid}` | — | Progreso, `proyecto_id`, `clip_id`, motivos |
| `POST /api/vivo/momentos/{mid}/descartar` | `{}` | Estado actualizado; libera su reserva |
| `POST /api/proyectos/{pid}/transcribir` | `{}` | `202`, enriquecimiento en cola |

Una conversión repetida devuelve el mismo trabajo o proyecto. Reclamarla mediante cambio condicional de estado dentro de una transacción; el bloqueo `_transicion` por sí solo no da durabilidad.

Ejemplo de momento:

```json
{
  "id": "uuid",
  "pico_s": 812.5,
  "inicio_s": 792.5,
  "fin_s": 827.5,
  "estado": "disponible",
  "motivos": ["Ráfaga de chat", "Audio 10 dB sobre el entorno"],
  "metricas": {
    "mensajes_s": 18,
    "z_m": 3.8,
    "fraccion_emotes": 0.62,
    "exceso_db": 10
  },
  "incertidumbre_s": 5,
  "proyecto_id": null,
  "clip_id": null
}
```

Errores: `404` inexistente, `409` transición incompatible o sesión activa adicional, `410` material expirado, `422` configuración inválida, `503` dependencia ausente y `507` espacio insuficiente.

Reutilizar `api.proteger_origen()`. Las URL multimedia firmadas y las credenciales nunca aparecen en las respuestas.

### Interfaz sin compilación

En `web/app.js`:

- Extender `navegar()` con `#/vivo/<id>`.
- Añadir formulario «Directo en vivo» en `vistaProyectos()`.
- Crear `vistaVivo(sid, miGeneracion)`.
- Reutilizar `h()`, `api()`, `intentar()` y `avisar()`.
- Consultar estado y momentos cada dos segundos, evitando peticiones solapadas.
- Usar `generacion` y `limpiarVista` para descartar respuestas antiguas y cancelar consultas al navegar.

Mostrar:

- Estado de captura y chat por separado.
- Minutos realmente disponibles en el búfer.
- Espacio usado, retraso del análisis y trabajos pendientes.
- Lista de momentos con hora, motivo, puntuación, disponibilidad y vencimiento.
- «Convertir en clip», «Descartar», «Abrir editor» y «Parar sesión».
- Modo automático opcional: conserva y convierte candidatos con los mismos límites.

Navegar fuera de la vista **no para la sesión**.

En `vistaEditor()`:

- Conservar su requisito `proyecto.estado === "listo"`.
- Añadir `vivo: "En vivo"` a `ORIGENES`.
- Mostrar estado de subtítulos y acción de transcribir.
- Mantener `vaciar()` antes de operaciones que alteren contenido.

La llegada de una transcripción no debe sobrescribir subtítulos editados. Guardar la transcripción y ofrecer regeneración explícita mediante `api.regenerar_subtitulos()`. Esta decisión también respeta las exportaciones ya encoladas, cuyos parámetros son inmutables.

## 5. Fallos y límites

| Situación | Comportamiento propuesto |
|---|---|
| Corte de red | Detectar falta de avance; cerrar el proceso bloqueado; reconectar con esperas 1, 2, 4… hasta 30 s y variación aleatoria. Abrir nueva época y registrar hueco. |
| URL multimedia caducada | Resolver nuevamente desde el enlace original; no reiniciar indefinidamente con la misma URL. |
| Fin del directo | Diferenciar fin confirmado de error transitorio. Finalizar pendientes y marcar `finalizada`. |
| Chat desconectado | Continuar por audio; suspender estadísticas del intervalo sin cobertura. |
| Reconexión del chat | Deduplicar mensajes repetidos; no interpretar un lote atrasado como una ráfaga actual. |
| Anuncios | Marcar si existen señales verificadas; suspender detección automática en esos intervalos. Sin señales, mostrar incertidumbre: el volumen también puede dispararse por un anuncio. |
| Cambio de resolución o codec | Nueva época/perfil. No concatenar por copia a través del cambio sin validar o normalizar. |
| Disco bajo | Comprobar periódicamente y antes de conservar/convertir. Limpiar solo material prescindible; detener captura si no puede mantenerse la reserva mínima. |
| SQLite sin espacio | Detener nuevos trabajos y captura; conservar archivos válidos. Recuperar al arrancar aunque no se haya podido registrar el error. |
| Segmento dañado | Marcar inválido, excluirlo y señalar cobertura incompleta. |
| Cierre abrupto | Marcar sesión `interrumpida`, reconciliar archivos y reservas, recuperar fuentes terminadas y retirar temporales incompletos. |
| Borrado de proyecto | Mantener el diferimiento de `Gestor.borrar_archivos()` para trabajos que usan su carpeta; desvincular el momento sin borrar otros proyectos. |

### CPU y transcripción mientras se graba

La detección de audio no debe esperar a Whisper.

Primera versión:

- Transcribir únicamente fuentes cortas conservadas.
- Una sola inferencia Whisper a la vez para toda la app.
- Añadir un bloqueo de inferencia: `transcribe._lock` actualmente protege la carga del modelo, no todas las llamadas a transcribir.
- Limitar hilos de FFmpeg e inferencia según configuración.
- Mostrar tiempo pendiente; si hay sobrecarga, posponer transcripción y proxy, conservando primero la fuente.

Para compartir la cola existente, refactorizar `Gestor.encolar()` y `_bucle()` para admitir una operación finita adicional de enriquecimiento. Su fallo debe actualizar `estado_subtitulos`, **sin convertir un proyecto editable en `error`**.

Un proyecto VOD largo que ya se está transcribiendo puede bloquear esa cola durante mucho tiempo. La primera fase debe reconocer esa limitación y permitir clips sin transcripción. Una fase posterior puede dividir el trabajo en unidades menores y priorizar vivo entre unidades; una `PriorityQueue` no interrumpe una inferencia ya iniciada.

### Sesiones de muchas horas

La memoria y el disco deben depender de las cuotas, no de las horas emitidas:

- Búfer de diez minutos, dos GiB como configuración inicial.
- Reservas pendientes con cuota independiente, por ejemplo un GiB y vencimiento de 30 minutos.
- Proyectos convertidos bajo una cuota separada de sesión, por ejemplo diez GiB.
- Al alcanzar la cuota persistente, desactivar conversión automática y avisar; no borrar proyectos editados.
- Anillos de métricas acotados; agregados históricos por minuto.
- Purgar filas de segmentos borrados cuando ya no hagan falta para recuperación.
- Paginar sesiones y momentos.

`db.listar()` hace `fetchall()`: crear consultas paginadas específicas para vivo. La materialización automática también aumentará `proyectos`; conviene paginar `api.listar_proyectos()`, que hoy carga todos y ejecuta consultas de conteo por proyecto.

### Recuperación de arranque

Extender `db.marcar_interrumpidos()` con estados propios de vivo y añadir `GestorVivo.recuperar()` antes de iniciar sesiones nuevas.

No reutilizar `pipeline.limpiar_huerfanos()` para el directorio vivo: actualmente interpreta cada carpeta bajo `PROJECTS_DIR` como un proyecto.

La recuperación debe resolver, al menos:

- Archivo final sin vínculo confirmado.
- Registro de reserva cuyo archivo nunca se terminó.
- Segmentos marcados `eliminando` que siguen presentes.
- Reservas de conversiones abandonadas.
- Proyecto publicado cuya respuesta HTTP nunca llegó al cliente.

No reanudar automáticamente la captura de un canal tras un cierre: ofrecer iniciar otra sesión y conservar la anterior como historial.

## 6. Plan por fases y pruebas

Estimación orientativa para una persona familiarizada con este código. Incluye implementación, pruebas y revisión; las integraciones externas pueden ampliar los plazos.

| Fase | Alcance y entrega | Tamaño |
|---|---|---|
| 0 | Modelo de datos, reloj y simuladores; verificar resolución de video y viabilidad de chat de ambas plataformas | 3–5 días |
| 1 | Una sesión, búfer, detección solo por audio, conservación, conversión manual/automática, editor/exportación actual y parada/recuperación | 10–15 días |
| 2 | Chat Twitch normalizado, ráfagas/emotes, compensación temporal, reconexión y deduplicación | 5–8 días, después de verificar acceso |
| 3 | Chat Kick mediante la misma interfaz, fixtures y degradación por audio | 5–10 días, sujeto a viabilidad |
| 4 | Priorización de CPU, transcripción por unidades, alineación asistida y endurecimiento para sesiones largas | 5–8 días |

**Mínimo útil de fase 1:** pegar un enlace admitido, grabar con disco acotado, detectar picos de audio y convertirlos en clips editables mientras la emisión continúa. Los subtítulos pueden solicitarse después.

La compatibilidad de captura de cada plataforma debe declararse según la verificación de fase 0; no prometer ambas por utilizar yt-dlp.

### Pruebas automáticas sin un directo real

Las pruebas actuales de `tests/test_logica.py` cubren principalmente lógica pura. Añadiría:

| Área | Simulación y resultado exigido |
|---|---|
| Detector | Reloj falso y métricas sintéticas: silencio, volumen constante, grito aislado, ráfaga sostenida, emotes repetidos, poco chat y señales ausentes |
| Estadística | Varianza cero, calentamiento, exclusión de intervalos desconectados y ausencia de uso de muestras futuras |
| Agrupación | Varios picos cercanos producen un momento; enfriamiento y rearme evitan duplicados |
| Chat | Adaptador falso con duplicados, mensajes atrasados, reconexión, orden alterado y saturación |
| Segmentos | Publicador falso con duración variable, archivo abierto, segmento perdido, PTS reiniciado, cambio de perfil y archivo dañado |
| Búfer | Rotación simultánea con reserva; ningún segmento reservado se elimina |
| Tiempo | Desfase positivo/negativo, video retrasado, salto del reloj UTC y reconexión con hueco |
| Conversión | Dos solicitudes simultáneas producen un solo proyecto; reintento tras perder la respuesta devuelve el mismo resultado |
| SQLite | Migrar una base antigua dos veces; comprobar claves foráneas y publicación transaccional |
| Cancelación | Parar durante resolución, escritura, reconexión y conversión; comprobar liberación de reservas y recursos |
| Recuperación | Simular caída entre cada transición de archivo y DB; arrancar dos veces sin duplicar proyectos |
| API | `TestClient` con capturador falso; comprobar estados, paginación, límites y protección de origen |
| Interfaz | Respuestas antiguas al cambiar de vista, doble clic en convertir y llegada de transcripción durante edición |

Para integración multimedia, usar fixtures locales cortos con contador visual y audio de pulsos. Esas pruebas verificarían duración, sincronización y límites del fragmento tras remultiplexar o recodificar. Serían pruebas futuras, ejecutables sin red ni plataformas reales.

Añadir una simulación acelerada de 24 horas que compruebe memoria acotada, tamaño del búfer, purga de registros y número de procesos activos.

## 7. Riesgos concretos del código actual

| Archivo y función | Supuesto o riesgo | Cambio necesario |
|---|---|---|
| `importer.descargar()` | Rechaza explícitamente `is_live`; espera una descarga final | Resolver y capturar mediante un camino nuevo |
| `importer._opciones()` | Puede seleccionar pistas separadas; usa nombre fijo y límites de archivo completo | Perfil específico para directo |
| `importer.comprobar_destino_publico()` | Su documentación reconoce que no cubre redirecciones ni cambios posteriores de DNS | Mantener validaciones y revisar destinos derivados, manifiestos y protocolos permitidos |
| `media.sondear()` | Exige duración positiva y dimensiones válidas | Aplicarlo a fuentes/segmentos cerrados, no a la emisión indefinida |
| `media.ejecutar_ffmpeg()` | Bloquea hasta terminar y calcula progreso sobre duración total | Supervisor de captura independiente con vigilancia de avance |
| `media.Cancelacion` | Controla un solo subproceso y lo mata directamente | Cancelación agrupada y parada ordenada para vivo |
| `pipeline.Gestor._bucle()` | Solo distingue proyecto y exportación; cualquier otro tipo cae en la segunda rama | Despacho explícito para operaciones nuevas |
| `pipeline.Gestor.iniciar()` | Hilos `daemon`, sin protocolo de cierre ni referencias para unirlos | Añadir cierre controlado |
| `pipeline.procesar_proyecto()` | Proxy completo, extracción completa, transcripción y propuestas antes de `listo` | Separar preparación editable y enriquecimiento |
| `pipeline.procesar_proyecto()` | Comprueba espacio en un punto del procesamiento | Vigilancia continua y cuotas para vivo |
| `transcribe.transcribir()` | Lee un WAV cerrado; identidad parcial basada en longitud y archivo estable | Usarlo sobre fuentes cortas inmutables |
| `transcribe.detectar_picos()` | Usa contexto futuro y estadísticas globales | Detector causal nuevo |
| `transcribe._cargar_modelo()` | El bloqueo protege carga, no toda inferencia | Serializar inferencia si se añaden trabajadores |
| `suggest.proponer_clips()` | Sin frases devuelve vacío; selecciona mejores candidatos de un video terminado | Detector de vivo independiente; reutilizar frases solo para refinamiento posterior |
| `pipeline.crear_propuestas()` | Borra propuestas anteriores de origen `sugerido` | Reservar `origen='vivo'` para momentos |
| `api._proyecto_listo()` y `web/app.js:vistaEditor()` | Edición/exportación dependen de `listo` y duración fija | Publicar proyectos cortos completos, separados de la sesión |
| `db.insertar()` y `actualizar()` | Una conexión por operación | Funciones transaccionales para cambios de varias entidades |
| `db.marcar_interrumpidos()` | Solo trata proyectos y exportaciones activos | Recuperación específica de sesiones y momentos |
| `pipeline.limpiar_huerfanos()` | Borra carpetas de proyectos desconocidos | Directorio y reconciliación independientes para vivo |
| `api._ciclo()` | No contiene cierre posterior a `yield` | Detener gestores y procesos en `finally` |

La frontera principal del diseño queda así: **captura continua y detección trabajan sobre una sesión con búfer acotado; edición, subtítulos y exportación trabajan sobre fuentes cortas e inmutables**. Esa separación permite incorporar el modo en vivo conservando las funciones actuales que ya resuelven bien los clips de videos terminados.
