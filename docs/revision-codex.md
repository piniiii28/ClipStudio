# Revisión con Codex

**Nota de actualización — 2026-11-12:** este es el registro histórico de las pasadas formales
2 a 4. Sus recuentos corresponden a esas versiones. Después se implementaron directos con
chat, encuadres de streams y escritorio; la última ronda registra 156 pruebas automatizadas,
31/31 comprobaciones de directo y 80/80 del flujo integral con el ejecutable. Estos resultados
no constituyen otra pasada formal de auditoría. El estado vigente y los riesgos pendientes
se mantienen en [estado.md](estado.md).

Codex CLI 0.167.1, sesión de ChatGPT. Se ejecutó con `codex exec` en modo de solo lectura.
Los informes completos de Codex no se incluyen en el repositorio; aquí está el resumen.

| Pasada | Qué se le pidió | Resultado |
|---|---|---|
| 2 | Revisar el código de ClipStudio buscando defectos | 16 hallazgos |
| 3 | Verificar las correcciones y ejecutar las pruebas | 10 de 16 confirmadas, 21 pruebas pasando, 7 hallazgos nuevos |
| 4 | Verificar esas correcciones y revisar las funciones nuevas | Sin hallazgos altos, 36 pruebas pasando, 13 hallazgos medios o bajos |

## Pasada 2: revisión del código de ClipStudio

| # | Gravedad | Hallazgo | Estado |
|---|---|---|---|
| 1 | Alta | Borrar un proyecto no esperaba a que el trabajador soltara los archivos | **Corregido**: si hay un trabajo en ejecución, la carpeta la borra el trabajador al terminar; una limpieza de huérfanos al arrancar cubre lo que quede |
| 2 | Alta | El autoguardado podía exportar datos anteriores o guardar en orden inverso | **Corregido**: guardados en serie por clip; exportar, regenerar y centrar esperan al guardado y se cancelan si falla |
| 3 | Alta | Un error de SQLite al registrar un fallo podía matar el hilo de la cola | **Corregido**: el bucle captura todo y el registro del resultado se reintenta |
| 4 | Media | La prueba E2E compartía carpeta de datos y marcaba como interrumpidos los trabajos de la app abierta | **Corregido**: la prueba usa una carpeta temporal propia, y la app impide dos instancias sobre los mismos datos |
| 5 | Media | La validación de URL solo filtraba IP literales | **Corregido en parte**: ahora se resuelve el nombre y se rechazan destinos privados. **Pendiente**: no cubre redirecciones ni cambios de DNS posteriores |
| 6 | Media | Varias fases largas no atienden la cancelación | **Corregido en parte**: se comprueba antes de cada fase y entre segmentos. **Pendiente**: la consulta inicial de yt-dlp, la fusión de pistas y la descarga del modelo terminan antes de cancelar |
| 7 | Media | Cancelar un trabajo en cola no cambiaba su estado hasta llegar su turno | **Corregido**: se marca cancelado de inmediato y el trabajador lo descarta |
| 8 | Media | Reintentos simultáneos duplicaban trabajos y cruzaban señales de cancelación | **Corregido**: transición atómica, rechazo de duplicados y una señal propia por entrada de cola |
| 9 | Media | Temporales sin limpiar al fallar o cancelar | **Corregido**: limpieza al terminar cada trabajo y al arrancar |
| 10 | Media | La importación por URL no limitaba bytes ni espacio | **Corregido**: límite por bytes recibidos y control de espacio libre durante la descarga |
| 11 | Media | Navegar rápido podía montar un editor antiguo y dejar temporizadores vivos | **Corregido**: cada navegación tiene un número de generación |
| 12 | Media | El editor ignoraba la respuesta del servidor tras guardar | **Corregido**: se adopta la versión del servidor salvo que haya ediciones locales más nuevas |
| 13 | Media | Al alargar un clip se podía perder la palabra que cruzaba el límite anterior | **Corregido**: mismo criterio (punto medio de la palabra) al generar y al completar |
| 14 | Media | El proxy fallaba con videos de alto impar menor de 720 | **Corregido**: el alto se redondea a par |
| 15 | Media | El análisis descartaba carátulas incrustadas pero FFmpeg podía elegir esa pista | **Corregido**: se usa en FFmpeg la misma pista que eligió el análisis |
| 16 | Baja | La prueba E2E no codificaba el nombre del archivo en la URL | **Corregido** |

Codex también señaló como bien resuelto: subida por bloques con límite real, FFmpeg sin shell y
con `subs.ass` relativo (evita el escapado de rutas de Windows), texto no confiable insertado
como nodos de texto (sin XSS), saneamiento del texto ASS, lectura de `stderr` en paralelo, y la
validación de Host y Origin.

## Pasada 3: verificación y ejecución de pruebas

Codex ejecutó `.venv\Scripts\python.exe -m pytest -q`: **21 pruebas correctas**. Dio por
corregidos 10 de los 16 hallazgos, parciales 5 y sin corregir 1 (la cancelación inmediata de
fases largas, que queda como limitación conocida). Encontró 7 problemas nuevos en lo que se
había cambiado:

| # | Gravedad | Hallazgo | Estado |
|---|---|---|---|
| 1 | Alta | Una exportación podía colarse mientras se borraba el proyecto | **Corregido** (confirmado por Codex en la pasada 4): el borrado se centraliza y espera al último trabajo que usa la carpeta |
| 2 | Media | Un guardado fallido se olvidaba y se podía exportar sin los cambios | **Corregido** en la pasada 4 (ver abajo) |
| 3 | Media | El vaciado de guardados podía terminar con ediciones pendientes | **Corregido** en la pasada 4 |
| 4 | Media | Editar subtítulos mientras se ampliaba el clip perdía los subtítulos nuevos | **Corregido**: el panel se bloquea mientras el servidor los recalcula |
| 5 | Media | Regenerar o centrar el rostro pisaba ediciones hechas durante la espera | **Corregido**: solo se aplican los campos de esa operación y la edición queda bloqueada mientras dura |
| 6 | Media | Pistas ya descargadas no contaban para el límite de tamaño | **Corregido**. Pendiente: no se vigila el espacio durante la fusión de pistas |
| 7 | Media | La prueba E2E podía hablar con otro servidor que ocupara su puerto | **Corregido** (confirmado por Codex) |

## Pasada 4: funciones nuevas (división, bloques, picos, estilos)

Codex ejecutó las pruebas: **36 correctas**. No encontró nada de gravedad alta.

| # | Gravedad | Hallazgo | Estado |
|---|---|---|---|
| 1 | Media | Un guardado fallido se perdía si ya se estaba editando otro clip | **Corregido**: los cambios pendientes se llevan por clip y solo se retiran cuando el servidor confirma |
| 2 | Media | Exportar podía adelantarse a un guardado recién encolado | **Corregido**: el vaciado comprueba que no se encoló nada más mientras esperaba |
| 3 | Media | El bloqueo del panel podía levantarse antes de enviar un cambio de límites | **Corregido**: los cambios de límites cuentan desde que se encolan |
| 4 | Media | Regenerar podía borrar subtítulos de una ampliación simultánea | **Corregido**: los controles de inicio y fin se bloquean mientras se regenera |
| 5 | Media | Dos divisiones a la vez podían mezclarse, y «exportar todos» leer a medias | **Corregido**: dividir, volver a proponer y exportar comparten el mismo candado; la división nueva se crea antes de retirar la anterior |
| 6 | Media | Dividir con partes de 600 s podía crear un clip de 800 s | **Corregido**: ninguna parte supera el máximo por clip |
| 7 | Media | El avance guardado de una transcripción no identificaba el video | **Corregido**: la clave incluye tamaño y fecha del video y una versión de formato |
| 8 | Media | Un sondeo antiguo podía ocultar una exportación recién creada | **Corregido**: se descarta la respuesta si la lista cambió entretanto |
| 9 | Baja | Los tiempos de los picos se desplazaban en videos de muchos bloques | **Corregido**: el volumen se anota por segundo absoluto del video |
| 10 | Baja | El número de bloque mostrado era incorrecto | **Corregido** |
| 11 | Baja | La prueba de bloques tolera pequeñas pérdidas de palabras | **Pendiente**: la prueba compara conteos con un margen, no palabra a palabra |
| 12 | Baja | Se aceptaban subtítulos solapados | **Corregido**: el anterior termina donde empieza el siguiente |
| 13 | Duda | Un audio truncado podía dejar el bucle sin avanzar | **Corregido**: una lectura vacía se trata como error |

No se registra aquí una nueva pasada formal que vuelva a auditar todas las correcciones de
la pasada 4 y las funciones añadidas después. Las verificaciones de implementación y pruebas
posteriores se documentan en [estado.md](estado.md).
