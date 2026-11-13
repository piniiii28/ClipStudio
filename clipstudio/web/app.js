// ClipStudio - interfaz. Sin dependencias ni compilacion.
// Todo el texto que viene del servidor se inserta con textContent (nunca innerHTML).

import { vistaVivo } from "./vivo.js";
import { crearSelectorStream, dibujarStream } from "./encuadre-stream.js";
import { iniciarActualizaciones } from "./actualizaciones.js";

const vista = document.getElementById("vista");
const ACTIVOS = ["en_cola", "procesando"];
const ESTADOS = { en_cola: "En cola", procesando: "Procesando", listo: "Listo", error: "Error", cancelado: "Cancelado" };
const IDIOMAS = [["auto", "Detectar idioma"], ["es", "Español"], ["en", "Inglés"], ["pt", "Portugués"], ["fr", "Francés"], ["it", "Italiano"], ["de", "Alemán"]];

// Estilos prefabricados de subtitulos: cambian solo el aspecto, no el texto ni el gancho.
const PREAJUSTES = {
  "Clásico blanco": { color: "#FFFFFF", color_borde: "#000000", borde: 5, tamano: 64, mayusculas: true, caja: false, resaltar: false },
  "Amarillo impacto": { color: "#FFE600", color_borde: "#000000", borde: 6, tamano: 74, mayusculas: true, caja: false, resaltar: false },
  "Palabra resaltada": { color: "#FFFFFF", color_borde: "#000000", borde: 5, tamano: 68, mayusculas: true, caja: false, resaltar: true, color_resalte: "#37E06B" },
  "Caja negra": { color: "#FFFFFF", color_borde: "#000000", tamano: 54, mayusculas: false, caja: true, resaltar: false },
  "Caja blanca": { color: "#111111", color_borde: "#FFFFFF", tamano: 54, mayusculas: false, caja: true, resaltar: false },
  "Discreto": { color: "#FFFFFF", color_borde: "#000000", borde: 3, tamano: 46, mayusculas: false, caja: false, resaltar: false, posicion: 82 },
};

let temporizador = null;   // sondeo de la vista actual
let limpiarVista = null;   // funcion de limpieza de la vista actual
let generacion = 0;        // cambia en cada navegacion; las vistas viejas se descartan
window.clipstudioGuardarAntesDeCerrar = async () => true;

// ---------- utilidades ----------

function h(etiqueta, props = {}, ...hijos) {
  const el = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const hijo of hijos.flat()) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.append(hijo.nodeType ? hijo : document.createTextNode(String(hijo)));
  }
  return el;
}

async function api(metodo, ruta, cuerpo) {
  let resp;
  try {
    resp = await fetch("/api" + ruta, {
      method: metodo,
      headers: cuerpo ? { "Content-Type": "application/json" } : undefined,
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
  } catch {
    throw new Error("No se pudo conectar con ClipStudio. ¿Sigue abierta la aplicación?");
  }
  if (resp.status === 204) return null;
  const datos = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error(mensajeError(datos, resp.status));
  return datos;
}

function mensajeError(datos, estado) {
  const d = datos && datos.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) return "Dato no válido: " + (d[0].msg || "revisa los campos.");
  return `Error del servidor (${estado}).`;
}

function avisar(texto, tipo = "") {
  const el = h("div", { class: "aviso " + tipo, role: tipo === "error" ? "alert" : "status" }, texto);
  document.getElementById("avisos").append(el);
  setTimeout(() => el.remove(), tipo === "error" ? 9000 : 4000);
}

async function intentar(fn) {
  try { return await fn(); } catch (e) { avisar(e.message, "error"); return undefined; }
}

function fmt(t, decimales = 1) {
  const factor = 10 ** decimales;
  t = Math.round(Math.max(0, Number(t) || 0) * factor) / factor;
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(decimales).padStart(decimales ? 3 + decimales : 2, "0")}`;
}

function leerTiempo(texto) {
  const partes = String(texto).trim().replace(",", ".").split(":").map(Number);
  if (!partes.length || partes.some((n) => !Number.isFinite(n) || n < 0)) return null;
  return partes.reduce((total, n) => total * 60 + n, 0);
}

function fmtDuracion(s) {
  if (!s) return "";
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min ${Math.round(s % 60)} s`;
}

// ---------- enrutado ----------

function navegar() {
  generacion += 1;
  clearInterval(temporizador);
  temporizador = null;
  if (limpiarVista) { limpiarVista(); limpiarVista = null; }
  vista.replaceChildren();
  const enVivo = location.hash === "#/vivo";
  const enYouTube = location.hash === "#/youtube";
  const m = location.hash.match(/^#\/p\/([0-9a-f]{32})$/);
  vista.className = enVivo || enYouTube ? "vista-vivo" : m ? "vista-editor" : "vista-proyectos";
  for (const enlace of document.querySelectorAll(".barra nav a")) {
    if (enlace.hash === (enVivo ? "#/vivo" : enYouTube ? "#/youtube" : "#/")) enlace.setAttribute("aria-current", m ? "location" : "page");
    else enlace.removeAttribute("aria-current");
  }
  if (enVivo) return vistaVivo(contextoVista());
  if (enYouTube) return vistaYouTube(contextoVista());
  if (m) vistaEditor(m[1], generacion); else vistaProyectos();
}
window.addEventListener("hashchange", navegar);

// Utilidades que se pasan a las vistas de otros modulos (por ejemplo vivo.js).
function contextoVista() {
  const miGeneracion = generacion;
  return {
    h, api, avisar, intentar, vista,
    vigente: () => miGeneracion === generacion,
    sondear: (fn, ms) => { clearInterval(temporizador); temporizador = setInterval(fn, ms); },
    alLimpiar: (fn) => { limpiarVista = fn; },
  };
}

async function estadoSistema() {
  const el = document.getElementById("estado-sistema");
  const e = await intentar(() => api("GET", "/estado"));
  if (!e) return;
  el.classList.toggle("mal", !e.ffmpeg);
  el.textContent = e.ffmpeg
    ? `Transcripción local: ${e.modelo} (${e.dispositivo}) · ${e.espacio_libre_gb} GB libres`
    : "Falta FFmpeg: ejecuta «uv run python scripts/instalar_ffmpeg.py»";
  el.title = "Datos en " + e.carpeta_datos;
  return e;
}

function vistaYouTube({ vigente }) {
  const region = h("select", { "aria-label": "Región de YouTube" },
    [["CO", "Colombia"], ["MX", "México"], ["AR", "Argentina"], ["ES", "España"], ["US", "Estados Unidos"]]
      .map(([codigo, pais]) => h("option", { value: codigo }, pais)));
  const estado = h("p", { class: "tenue", role: "status" });
  const lista = h("div", { class: "youtube-lista" });
  const actualizar = h("button", { onclick: cargar }, "Actualizar");
  vista.append(
    h("header", { class: "portada portada-vivo" }, h("h1", {}, "Tendencias de YouTube"),
      h("p", { class: "tenue" }, "Explora videos populares por país y lleva un enlace a Proyectos.")),
    h("div", { class: "fila youtube-filtros" }, region, actualizar), estado, lista);
  region.addEventListener("change", cargar);

  let consulta = 0;
  async function cargar() {
    const actual = ++consulta;
    actualizar.disabled = true;
    estado.textContent = "Cargando videos…";
    lista.replaceChildren();
    try {
      const datos = await api("GET", `/youtube/tendencias?region=${region.value}`);
      if (!vigente() || actual !== consulta) return;
      if (!datos.configurado) {
        estado.textContent = "Para cargar tendencias, configura CLIPSTUDIO_YOUTUBE_API_KEY en el archivo .env y reinicia ClipStudio.";
        lista.append(h("a", { class: "boton", href: "https://charts.youtube.com/", target: "_blank", rel: "noopener" }, "Abrir YouTube Charts"));
        return;
      }
      estado.textContent = datos.videos.length ? "" : "YouTube no devolvió videos para esta región.";
      lista.append(...datos.videos.map((video) =>
        h("article", { class: "panel youtube-video" },
          h("img", { src: video.miniatura, alt: "", loading: "lazy", referrerPolicy: "no-referrer" }),
          h("div", { class: "youtube-video-info" }, h("h2", {}, video.titulo), h("p", { class: "tenue" }, video.canal),
            h("div", { class: "fila" },
              h("button", { class: "primario", onclick: () => {
                enlaceTendencia = video.url;
                location.hash = "#/";
              } }, "Usar enlace"),
              h("a", { class: "boton", href: video.url, target: "_blank", rel: "noopener" }, "Ver en YouTube"))))));
    } catch (error) {
      if (vigente() && actual === consulta) estado.textContent = error.message;
    } finally {
      if (actual === consulta) actualizar.disabled = false;
    }
  }
  cargar();
}

let enlaceTendencia = "";

// ---------- vista: proyectos ----------

function vistaProyectos() {
  const lista = h("div", { class: "lista-proyectos", "aria-labelledby": "titulo-proyectos" });
  const conteo = h("span", { class: "conteo-proyectos" });
  const selIdioma = () => h("select", { "aria-label": "Idioma del video" }, IDIOMAS.map(([v, t]) => h("option", { value: v }, t)));

  // Duracion deseada de los clips propuestos (vale para archivo y para enlace)
  const minClip = h("input", { type: "number", min: 3, max: 300, value: 15, style: "width:70px", "aria-label": "Duración mínima de los clips en segundos" });
  const maxClip = h("input", { type: "number", min: 5, max: 600, value: 60, style: "width:70px", "aria-label": "Duración máxima de los clips en segundos" });
  function duracionClips() {
    const min_s = Number(minClip.value), max_s = Number(maxClip.value);
    if (!(min_s >= 3 && max_s <= 600 && max_s > min_s)) {
      avisar("Revisa la duración de los clips: el máximo debe ser mayor que el mínimo (entre 3 y 600 s).", "error");
      return null;
    }
    return { min_s, max_s };
  }

  // Subir archivo
  const idiomaArchivo = selIdioma();
  const entrada = h("input", { type: "file", accept: "video/*,.mkv,.ts,.flv", hidden: true });
  const progresoSubida = h("div", { class: "progreso", hidden: true }, h("div"));
  const textoSubida = h("p", { class: "tenue pequeno" });
  let subida = null;
  const zona = h("div", { class: "soltar", tabIndex: 0, role: "button" },
    h("span", { class: "icono icono-subir", "aria-hidden": "true" }),
    h("strong", {}, "Arrastra un video aquí"), h("span", {}, "o haz clic para elegirlo"));
  zona.addEventListener("click", () => entrada.click());
  zona.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); entrada.click(); } });
  zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("encima"); });
  zona.addEventListener("dragleave", () => zona.classList.remove("encima"));
  zona.addEventListener("drop", (e) => { e.preventDefault(); zona.classList.remove("encima"); if (e.dataTransfer.files[0]) subir(e.dataTransfer.files[0]); });
  entrada.addEventListener("change", () => { if (entrada.files[0]) subir(entrada.files[0]); entrada.value = ""; });
  const cancelarSubida = h("button", { class: "mini", hidden: true, onclick: () => subida && subida.abort() }, "Cancelar subida");

  function subir(archivo) {
    if (subida) return avisar("Ya hay una subida en curso.", "error");
    const d = duracionClips();
    if (!d) return;
    const xhr = new XMLHttpRequest();
    subida = xhr;
    xhr.open("PUT", `/api/proyectos/archivo?nombre=${encodeURIComponent(archivo.name)}&idioma=${idiomaArchivo.value}&min_s=${d.min_s}&max_s=${d.max_s}`);
    progresoSubida.hidden = cancelarSubida.hidden = false;
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      progresoSubida.firstChild.style.width = (e.loaded / e.total * 100) + "%";
      textoSubida.textContent = `Subiendo ${archivo.name}: ${Math.round(e.loaded / e.total * 100)} %`;
    };
    const fin = (mensaje, tipo) => {
      subida = null;
      progresoSubida.hidden = cancelarSubida.hidden = true;
      progresoSubida.firstChild.style.width = "0";
      textoSubida.textContent = "";
      if (mensaje) avisar(mensaje, tipo);
      refrescar();
    };
    xhr.onload = () => {
      if (xhr.status === 201) return fin("Video subido. Empezó el procesamiento.");
      let datos = null;
      try { datos = JSON.parse(xhr.responseText); } catch { /* respuesta no JSON */ }
      fin(mensajeError(datos, xhr.status), "error");
    };
    xhr.onerror = () => fin("La subida falló. Comprueba que ClipStudio sigue abierto.", "error");
    xhr.onabort = () => fin("Subida cancelada.");
    xhr.send(archivo);
  }

  // Importar por enlace
  const idiomaUrl = selIdioma();
  const url = h("input", { type: "url", class: "crece", value: enlaceTendencia, placeholder: "https://www.youtube.com/watch?v=…", "aria-label": "Enlace del video" });
  enlaceTendencia = "";
  const audioOriginal = () => h("option", { value: "" }, "Audio predeterminado");
  const audio = h("select", { "aria-label": "Idioma de audio", hidden: true }, audioOriginal());
  const estadoAudio = h("span", { class: "tenue pequeno", role: "status" });
  const nombreIdioma = typeof Intl.DisplayNames === "function"
    ? new Intl.DisplayNames(["es"], { type: "language", fallback: "code" }) : null;
  const consultarAudio = h("button", { type: "button", onclick: async () => {
    const enlace = url.value.trim();
    if (!enlace || consultarAudio.disabled) return;
    consultarAudio.disabled = true;
    estadoAudio.textContent = "Buscando pistas…";
    audio.hidden = true;
    audio.replaceChildren(audioOriginal());
    try {
      const datos = await api("POST", "/youtube/audio", { url: enlace });
      if (url.value.trim() !== enlace || !url.isConnected) return;
      for (const codigo of datos.idiomas) {
        let nombre = codigo;
        try { nombre = nombreIdioma?.of(codigo) || codigo; } catch { /* código de la plataforma */ }
        audio.append(h("option", { value: codigo }, nombre));
      }
      audio.hidden = !datos.idiomas.length;
      estadoAudio.textContent = datos.idiomas.length ? "" : "YouTube no expuso pistas con idioma para este enlace.";
    } catch (error) {
      if (url.value.trim() === enlace && url.isConnected) estadoAudio.textContent = error.message;
    } finally {
      consultarAudio.disabled = false;
    }
  } }, "Buscar pistas de audio");
  function limpiarAudio() {
    audio.replaceChildren(audioOriginal());
    audio.hidden = true;
    estadoAudio.textContent = "";
  }
  url.addEventListener("input", limpiarAudio);
  const botonUrl = h("button", { class: "primario" }, "Importar");
  const formularioUrl = h("form", { class: "fila", onsubmit: async (e) => {
    e.preventDefault();
    if (!url.value.trim()) return;
    const d = duracionClips();
    if (!d) return;
    botonUrl.disabled = true;
    const p = await intentar(() => api("POST", "/proyectos/url", { url: url.value.trim(), idioma: idiomaUrl.value, audio_idioma: audio.value || null, ...d }));
    botonUrl.disabled = false;
    if (p) { url.value = ""; limpiarAudio(); avisar("Importación en cola."); refrescar(); }
  } }, url, botonUrl);

  vista.append(
    h("header", { class: "portada portada-proyectos" },
      h("div", { class: "portada-texto" },
        h("h1", {}, "Convierte tus videos en clips verticales"),
        h("p", { class: "tenue" }, "Importa un video para generar clips con subtítulos. El procesamiento se hace en tu equipo.")),
      h("div", { class: "composicion", "aria-hidden": "true" },
        h("div", { class: "composicion-fuente" }, h("div", { class: "composicion-pista" })),
        h("div", { class: "composicion-clip" }, h("div", { class: "composicion-subtitulos" })))),
    h("section", { class: "importacion", "aria-labelledby": "titulo-importacion" },
      h("h2", { id: "titulo-importacion", class: "titulo-lista" }, "Nuevo proyecto"),
      h("div", { class: "nuevo" },
        h("section", { class: "panel fuente" },
          h("div", { class: "fuente-cabecera" }, h("span", { class: "icono icono-video", "aria-hidden": "true" }),
            h("div", {}, h("h3", {}, "Archivo local"), h("p", { class: "tenue pequeno" }, "Importa un video de tu equipo."))),
          zona, entrada,
          h("div", { class: "fila fuente-opciones" }, h("span", { class: "tenue pequeno" }, "Idioma hablado"), idiomaArchivo, cancelarSubida),
          progresoSubida, textoSubida),
        h("section", { class: "panel fuente" },
          h("div", { class: "fuente-cabecera" }, h("span", { class: "icono icono-enlace", "aria-hidden": "true" }),
            h("div", {}, h("h3", {}, "Enlace de video"), h("p", { class: "tenue pequeno" }, "YouTube y otras plataformas compatibles con yt-dlp."))),
          h("div", { class: "fuente-enlace" }, formularioUrl,
            h("div", { class: "fila" }, consultarAudio, audio, estadoAudio),
            h("p", { class: "tenue pequeno" }, "Importa videos propios o que tengas permiso para usar.")),
          h("div", { class: "fila fuente-opciones" }, h("span", { class: "tenue pequeno" }, "Idioma para transcribir"), idiomaUrl))),
      h("div", { class: "fila ajuste-inicial" }, h("strong", {}, "Duración de los clips sugeridos"), minClip, "a", maxClip, "s")),
    h("div", { class: "cabecera-lista" },
      h("h2", { id: "titulo-proyectos", class: "titulo-lista" }, "Tus proyectos"), conteo),
    lista);

  async function refrescar() {
    const proyectos = await intentar(() => api("GET", "/proyectos"));
    if (!proyectos || !lista.isConnected) return;
    conteo.textContent = proyectos.length;
    lista.replaceChildren(...(proyectos.length ? proyectos.map(tarjeta) : [
      h("div", { class: "panel vacio" }, h("span", { class: "icono icono-proyectos", "aria-hidden": "true" }),
        h("strong", {}, "Todavía no hay proyectos"), h("p", {}, "Importa un archivo o un enlace para empezar."))]));
  }

  function tarjeta(p) {
    const activo = ACTIVOS.includes(p.estado);
    const accion = (texto, fn, clase = "") => h("button", { class: clase, onclick: async () => { await intentar(fn); refrescar(); } }, texto);
    return h("article", { class: "panel proyecto" },
      h("span", { class: "icono icono-video", "aria-hidden": "true" }),
      h("div", { class: "proyecto-datos" },
        h("h3", {}, p.nombre),
        h("div", { class: "fila pequeno tenue", style: "margin-top:4px" },
          h("span", { class: "etiqueta " + p.estado }, ESTADOS[p.estado] || p.estado),
          h("span", {}, p.origen === "url" ? "Enlace" : "Archivo"),
          p.duracion ? h("span", {}, fmtDuracion(p.duracion)) : null,
          p.estado === "listo" ? h("span", {}, `${p.n_clips} clip(s) · ${p.n_exportaciones} exportado(s)`) : null),
        activo ? h("div", {}, h("div", { class: "progreso" }, h("div", { style: `width:${p.progreso}%` })),
          h("p", { class: "tenue pequeno", style: "margin-top:4px" }, `${p.mensaje || ""} ${Math.round(p.progreso)} %`)) : null,
        p.estado === "error" ? h("p", { class: "mensaje-error pequeno", style: "margin-top:6px" }, p.error || "Error desconocido.") : null,
        p.estado === "listo" && p.mensaje ? h("p", { class: "tenue pequeno", style: "margin-top:4px" }, p.mensaje) : null),
      h("div", { class: "fila proyecto-acciones" },
        p.estado === "listo" ? h("a", { class: "boton", href: "#/p/" + p.id }, "Abrir") : null,
        activo ? accion("Cancelar", () => api("POST", `/proyectos/${p.id}/cancelar`)) : null,
        ["error", "cancelado"].includes(p.estado) ? accion("Reintentar", () => api("POST", `/proyectos/${p.id}/reintentar`)) : null,
        accion("Eliminar", async () => {
          if (confirm(`¿Eliminar «${p.nombre}» con sus clips y exportaciones?`)) await api("DELETE", `/proyectos/${p.id}`);
        }, "peligro")));
  }

  refrescar();
  temporizador = setInterval(refrescar, 2000);
  limpiarVista = () => { if (subida) subida.abort(); };
}

// ---------- vista: editor ----------

async function vistaEditor(pid, miGeneracion) {
  const vigente = () => miGeneracion === generacion;
  let proyecto = await intentar(() => api("GET", `/proyectos/${pid}`));
  if (!vigente()) return;
  if (!proyecto) { vista.append(h("p", {}, h("a", { href: "#/" }, "← Volver a proyectos"))); return; }
  if (proyecto.estado !== "listo") { location.hash = "#/"; return; }
  const transcripcion = (await intentar(() => api("GET", `/proyectos/${pid}/transcripcion`))) || { frases: [] };
  if (!vigente()) return;
  // Videos de fondo para el encuadre "dividido" (se piden una vez al abrir el editor).
  let fondos = (await intentar(() => api("GET", "/fondos"))) || { carpeta: "", fondos: [], locales: [], remotos: [], ocultos: [] };
  if (!vigente()) return;

  let clip = proyecto.clips[0] || null;
  let pestana = "subtitulos";
  let seleccion = null;      // [indice, indice] de frases elegidas en la transcripcion
  let cancelado = false;
  const sugerenciasTikTok = new Map();
  const peticionesTikTok = new Map();

  const video = h("video", { src: `/api/proyectos/${pid}/video`, playsInline: true, preload: "auto" });
  // Franja inferior del encuadre "dividido": video de juego en bucle, siempre sin audio.
  const juego = h("video", { muted: true, loop: true, playsInline: true, preload: "metadata" });
  const juegoVacio = h("div", { class: "juego-vacio" }, "Fondo de juego");
  // Fondo de YouTube: reproductor incrustado (sin descargar nada), recortado tipo "cover" por CSS.
  const juegoWeb = h("iframe", { class: "juego-web", title: "Vista previa del fondo de YouTube", hidden: true, tabindex: "-1",
    allow: "autoplay; encrypted-media", referrerpolicy: "strict-origin-when-cross-origin", "aria-hidden": "true" });
  const juegoSinConexion = h("div", { class: "juego-vacio", hidden: true }, "Vista previa no disponible (sin conexión)");
  const franjaJuego = h("div", { class: "franja-juego", hidden: true, "aria-hidden": "true" }, juego, juegoWeb, juegoSinConexion, juegoVacio);
  const subInterior = h("span", {});
  const subVista = h("div", { class: "subtitulo-vista" }, subInterior);
  const ganchoInterior = h("span", {});
  const ganchoVista = h("div", { class: "gancho-vista", hidden: true }, ganchoInterior);
  const marcaInterior = h("span", {});
  const marcaVista = h("div", { class: "marca-vista", hidden: true }, marcaInterior);
  // Fondo del encuadre "ajustar": copia pequena del fotograma actual, ampliada y desenfocada con CSS.
  const fondoVista = h("canvas", { class: "fondo-vista", width: 90, height: 160, hidden: true, "aria-hidden": "true" });
  const fondoCtx = fondoVista.getContext("2d");
  const streamVista = h("canvas", { class: "stream-vista", width: 360, height: 640, hidden: true });
  let fuenteStream = null;
  const creditoVista = h("div", { class: "credito-vista", hidden: true });
  let creditoFondo = "";   // texto de credito del fondo que se previsualiza ("" si no tiene)
  const telefono = h("div", { class: "telefono" }, fondoVista, video, streamVista, franjaJuego, ganchoVista, subVista, marcaVista, creditoVista);
  const listaClips = h("div", { class: "lista-clips" });
  const panelDerecho = h("div", {});
  const controles = h("div", { class: "controles" });
  const guardado = h("span", { class: "tenue pequeno", role: "status" });
  const velocidad = h("select", { "aria-label": "Velocidad de reproducción de la vista previa" },
    [0.5, 0.75, 1, 1.25, 1.5, 2].map((tasa) =>
      h("option", { value: tasa, selected: tasa === 1 }, `${String(tasa).replace(".", ",")}×`)));
  velocidad.addEventListener("change", () => {
    const tasa = Number(velocidad.value);
    video.playbackRate = tasa;
    juego.playbackRate = tasa;
  });
  const tituloPrevio = h("h2", {}, "Vista previa");
  const zonaSegura = h("div", { class: "zona-segura", hidden: true, "aria-hidden": "true" });
  telefono.append(zonaSegura);
  const mostrarGuia = h("button", { class: "mini", "aria-pressed": "false",
    title: "Guía orientativa para mantener el texto lejos de los controles de redes sociales",
    onclick: () => {
      zonaSegura.hidden = !zonaSegura.hidden;
      mostrarGuia.setAttribute("aria-pressed", String(!zonaSegura.hidden));
    } }, "Zona segura");

  // --- guardado con retraso ---
  // Los cambios se acumulan POR CLIP y se envian de uno en uno, en orden. Un cambio solo
  // deja de estar pendiente cuando el servidor confirma que lo guardo; si falla, vuelve a
  // la lista de su clip. `vaciar()` termina cuando no queda nada pendiente ni en curso,
  // para que exportar o regenerar nunca trabajen con datos anteriores.
  const pendientes = new Map();   // id de clip -> cambios todavia sin enviar
  const enCola = new Map();       // id de clip -> guardados enviados y aun sin respuesta
  let reloj = null;
  let cadena = Promise.resolve(true);
  let rangosActivos = 0;          // cambios de inicio/fin encolados o en curso
  let operaciones = 0;            // regenerar / centrar rostro en curso
  const esRango = (c) => "inicio" in c || "fin" in c;

  // Mientras el servidor recalcula los subtitulos (al mover los limites, regenerar o centrar)
  // el panel derecho no admite ediciones: asi no se envia una lista de subtitulos anticuada.
  // Durante regenerar/centrar tampoco se pueden mover los limites del clip.
  function actualizarBloqueo() {
    const rangoPendiente = [...pendientes.values()].some(esRango);
    const bloquear = rangosActivos > 0 || operaciones > 0 || rangoPendiente;
    panelDerecho.inert = bloquear;
    panelDerecho.style.opacity = bloquear ? "0.6" : "";
    controles.inert = operaciones > 0;
    controles.style.opacity = operaciones > 0 ? "0.6" : "";
  }

  async function enviarCambios(id, cambios) {
    guardado.textContent = "Guardando…";
    const nuevo = await intentar(() => api("PATCH", `/clips/${id}`, cambios));
    if (esRango(cambios)) rangosActivos -= 1;
    enCola.set(id, enCola.get(id) - 1);
    if (!nuevo) {
      // Fallo: los cambios vuelven a los pendientes de SU clip, sin pisar ediciones posteriores.
      pendientes.set(id, { ...cambios, ...(pendientes.get(id) || {}) });
      if (!cancelado) { guardado.textContent = "No se guardó"; actualizarBloqueo(); }
      return false;
    }
    if (cancelado) return true;
    guardado.textContent = "Guardado";
    const local = proyecto.clips.find((c) => c.id === id);
    const hayMasNuevos = "subtitulos" in (pendientes.get(id) || {}) || enCola.get(id) > 0;
    // Los subtitulos que devuelve el servidor (recortados, ordenados o completados al mover
    // los limites) se adoptan siempre que no haya una edicion local de subtitulos mas nueva.
    if (local && ("subtitulos" in cambios || esRango(cambios)) && !hayMasNuevos) {
      const cambio = JSON.stringify(local.subtitulos) !== JSON.stringify(nuevo.subtitulos);
      local.subtitulos = nuevo.subtitulos;
      if (cambio && clip && clip.id === id && pestana === "subtitulos") pintarDerecha();
    }
    if (esRango(cambios) && clip?.id === id && pestana === "aspecto") { ajustarVideo(); pintarDerecha(); }
    actualizarBloqueo();
    pintarClips();
    return true;
  }
  function encolarPendiente() {
    clearTimeout(reloj);
    reloj = null;
    for (const [id, cambios] of [...pendientes]) {
      pendientes.delete(id);
      enCola.set(id, (enCola.get(id) || 0) + 1);
      if (esRango(cambios)) rangosActivos += 1;   // cuenta desde que se encola, no desde que se envia
      cadena = cadena.then(() => enviarCambios(id, cambios));
    }
    actualizarBloqueo();
  }
  // Resuelve a true solo cuando no queda NADA por guardar: ni pendiente ni en curso.
  // Si un guardado falla resuelve a false y sus cambios siguen pendientes para reintentar.
  async function vaciar() {
    for (;;) {
      encolarPendiente();
      const esperada = cadena;
      const ok = await esperada;
      if (!ok) return false;
      // Si mientras se esperaba se encolo otro guardado, la cadena cambio: se repite.
      if (pendientes.size === 0 && cadena === esperada) return true;
    }
  }
  window.clipstudioGuardarAntesDeCerrar = vaciar;
  function guardar(cambios) {
    if (esRango(cambios) || "recorte_x" in cambios || cambios.seguimiento === false) clip.trayectoria = [];
    Object.assign(clip, cambios);
    pendientes.set(clip.id, { ...(pendientes.get(clip.id) || {}), ...cambios });
    clearTimeout(reloj);
    reloj = setTimeout(encolarPendiente, 450);
    actualizarBloqueo();
  }
  // Ejecuta una operacion del servidor sobre un clip con la edicion bloqueada y aplica solo
  // los campos que esa operacion cambia, sin tocar otras ediciones locales.
  async function operar(ruta, campos) {
    const id = clip.id;
    operaciones += 1;
    actualizarBloqueo();
    try {
      if (!(await vaciar())) { avisar(AVISO_GUARDADO, "error"); return null; }
      const r = await intentar(() => api("POST", `/clips/${id}/${ruta}`));
      if (!r) return null;
      const nuevo = r.clip || r;
      const local = proyecto.clips.find((c) => c.id === id);
      if (local) for (const k of campos) local[k] = nuevo[k];
      return r;
    } finally {
      operaciones -= 1;
      actualizarBloqueo();
    }
  }
  const AVISO_GUARDADO = "No se pudieron guardar los últimos cambios. Vuelve a intentarlo.";

  const cortesDel = (c = clip) => c?.cortes || [];
  const segundosQuitados = (c = clip) => cortesDel(c).reduce((n, t) => n + Math.max(0, Math.min(c.fin, t.fin) - Math.max(c.inicio, t.inicio)), 0);
  const estaCortado = (f) => cortesDel().some((c) => c.inicio <= f.inicio && c.fin >= f.fin);
  const corteEn = (t) => cortesDel().find((c) => c.inicio <= t && t < c.fin);
  const textoDuracion = () => `Duración: ${fmt(clip.fin - clip.inicio - segundosQuitados())}` +
    (cortesDel().length ? ` (${cortesDel().length} cortes, −${segundosQuitados().toFixed(2)} s)` : "");
  function unirCortes(lista, inicio = clip.inicio, fin = clip.fin) {
    const salida = [];
    for (const c of lista.map((c) => ({ inicio: Math.max(inicio, c.inicio), fin: Math.min(fin, c.fin) }))
      .filter((c) => c.fin - c.inicio >= 0.05 - 1e-9).sort((a, b) => a.inicio - b.inicio)) {
      const ultimo = salida[salida.length - 1];
      if (ultimo && c.inicio <= ultimo.fin) ultimo.fin = Math.max(ultimo.fin, c.fin);
      else salida.push(c);
    }
    return salida;
  }
  function cambiarCortes(lista) {
    const cortes = unirCortes(lista);
    if (cortes.length > 200) return avisar("No se permiten más de 200 cortes por clip.", "error");
    if (clip.fin - clip.inicio - cortes.reduce((n, c) => n + c.fin - c.inicio, 0) < 1 - 1e-9)
      return avisar("El clip debe conservar al menos 1 segundo útil.", "error");
    guardar({ cortes });
    pintarControles(); pintarClips(); pintarDerecha(); pintarSubtitulo();
  }

  // --- vista previa ---
  // Porcentaje del alto que ocupa el video de juego en "dividido" (predeterminado 45).
  const proporcionJuego = () => clip.estilo.juego_proporcion || 45;
  function posicionHorizontal(ancho, visible) {
    const puntos = clip.trayectoria || [];
    if (!puntos.length) return -(ancho - visible) * clip.recorte_x;
    const tiempo = video.currentTime;
    const siguiente = puntos.findIndex((p) => p.tiempo > tiempo);
    let centro = puntos[0].centro_x;
    if (siguiente === -1) centro = puntos[puntos.length - 1].centro_x;
    else if (siguiente > 0) {
      const a = puntos[siguiente - 1], b = puntos[siguiente];
      centro = a.centro_x + (b.centro_x - a.centro_x) * (tiempo - a.tiempo) / (b.tiempo - a.tiempo);
    }
    return -Math.max(0, Math.min(ancho - visible, ancho * centro - visible / 2));
  }
  function ajustarVideo() {
    if (!clip) return;
    const dividido = clip.encuadre === "dividido";
    telefono.classList.toggle("ajustar", clip.encuadre === "ajustar");
    const e = clip.estilo;
    const conFondoVideo = clip.encuadre === "ajustar" && e.fondo !== "color";
    telefono.style.background = clip.encuadre === "ajustar" && e.fondo === "color" ? e.color_fondo : "";
    fondoVista.hidden = !conFondoVideo;
    if (conFondoVideo) {
      // El desenfoque se escala al tamano de la vista previa para parecerse al del MP4 (1080x1920).
      const px = Math.max(2, e.difuminado * telefono.clientHeight / 1920 * 1.4);
      const extra = e.fondo === "difuminado_oscuro" ? " brightness(0.55)" : e.fondo === "difuminado_gris" ? " grayscale(1)" : "";
      fondoVista.style.filter = `blur(${px.toFixed(1)}px)${extra}`;
      pintarFondo();
    }
    video.removeAttribute("style");
    pintarFranjaJuego();
    streamVista.hidden = clip.encuadre !== "stream";
    if (clip.encuadre === "stream") {
      video.style.opacity = "0";
      pintarStream();
      return;
    }
    if (clip.encuadre === "ajustar") return;
    const cw = telefono.clientWidth, ch = telefono.clientHeight;
    // En "dividido" el video se recorta a la franja de arriba; la franja de abajo lo cubre.
    const F = dividido ? ch * (100 - proporcionJuego()) / 100 : ch;
    const aspecto = proyecto.ancho / proyecto.alto;
    if (aspecto > (dividido ? cw / F : 9 / 16)) {
      const w = F * aspecto;
      video.style.cssText = `height:${F}px;width:${w}px;top:0;left:${posicionHorizontal(w, cw)}px`;
    } else {
      const alto = cw / aspecto;
      video.style.cssText = `width:${cw}px;height:${alto}px;left:0;top:${-(alto - F) / 2}px`;
    }
  }
  function pintarStream() {
    if (!clip || clip.encuadre !== "stream" || video.readyState < 2) return;
    dibujarStream(streamVista, video, clip.composicion || {});
    if (fuenteStream) fuenteStream.getContext("2d").drawImage(video, 0, 0, fuenteStream.width, fuenteStream.height);
  }
  // Dibuja el fotograma actual recortado a 9:16 (cubriendo todo el lienzo) como fondo.
  function pintarFondo() {
    if (fondoVista.hidden || video.readyState < 2 || !video.videoWidth) return;
    const vw = video.videoWidth, vh = video.videoHeight, cw = fondoVista.width, ch = fondoVista.height;
    const escala = Math.max(cw / vw, ch / vh);
    const sw = cw / escala, sh = ch / escala;
    try { fondoCtx.drawImage(video, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, cw, ch); } catch { /* fotograma aun no disponible */ }
  }
  // Muestra u oculta la franja de juego y elige el video que se previsualiza en ella.
  const inicioVistaWeb = new Map();   // id de YouTube -> segundo desde el que se ve la vista previa
  const sondaConexion = { cuando: 0, ok: true };
  async function hayConexion() {
    // Una peticion "no-cors" a YouTube solo falla si no hay red: basta para elegir el mensaje.
    if (navigator.onLine === false) return false;
    if (Date.now() - sondaConexion.cuando < 30000) return sondaConexion.ok;
    try {
      await fetch("https://www.youtube-nocookie.com/favicon.ico", { mode: "no-cors", cache: "no-store" });
      sondaConexion.ok = true;
    } catch { sondaConexion.ok = false; }
    sondaConexion.cuando = Date.now();
    return sondaConexion.ok;
  }
  function quitarVistaWeb() {
    if (juegoWeb.getAttribute("src")) juegoWeb.removeAttribute("src");
    juegoWeb.hidden = true;
    juegoSinConexion.hidden = true;
  }
  function mostrarVistaWeb(remoto) {
    juego.pause();
    if (juego.getAttribute("src")) { juego.removeAttribute("src"); juego.load(); }
    juego.hidden = true;
    juegoVacio.hidden = true;
    if (!inicioVistaWeb.has(remoto.id)) inicioVistaWeb.set(remoto.id, Math.floor(Math.random() * Math.max(1, remoto.duracion - 180)));
    const inicio = inicioVistaWeb.get(remoto.id);
    const src = `https://www.youtube-nocookie.com/embed/${remoto.id}?autoplay=1&mute=1&controls=0&loop=1&playlist=${remoto.id}&start=${inicio}&playsinline=1&modestbranding=1&rel=0`;
    // Recorte "cover": el reproductor es 16:9 y se amplia hasta cubrir la franja (con un poco de margen
    // para esconder los bordes de la interfaz de YouTube); sin interaccion (pointer-events:none).
    const cw = telefono.clientWidth, ch = telefono.clientHeight * proporcionJuego() / 100;
    const ancho = Math.max(cw, ch * 16 / 9) * 1.12, alto = ancho * 9 / 16;
    juegoWeb.style.cssText = `width:${ancho}px;height:${alto}px;left:${(cw - ancho) / 2}px;top:${(ch - alto) / 2}px`;
    if (juegoWeb.dataset.id === remoto.id && (juegoWeb.getAttribute("src") || !juegoSinConexion.hidden)) return;
    juegoWeb.dataset.id = remoto.id;
    quitarVistaWeb();
    hayConexion().then((ok) => {
      // La seleccion pudo cambiar mientras se comprobaba la conexion.
      if (cancelado || juegoWeb.dataset.id !== remoto.id) return;
      if (!ok) { juegoSinConexion.hidden = false; return; }
      juegoWeb.hidden = false;
      juegoWeb.setAttribute("src", src);
    });
  }
  // Fondo que se previsualiza: el elegido en el estilo; con "al azar" (o uno que ya no existe), el primero
  // de los locales y, si no hay, el primero de YouTube (el MP4 elige al exportar).
  function fondoDeVista() {
    const elegido = clip.estilo.fondo_juego;
    const remoto = fondos.remotos.find((f) => f.valor === elegido);
    if (remoto) return { remoto };
    const locales = fondos.locales.map((f) => f.nombre);
    if (locales.includes(elegido)) return { local: elegido };
    if (locales.length) return { local: locales[0] };
    if (fondos.remotos.length) return { remoto: fondos.remotos[0] };
    return {};
  }
  function pintarFranjaJuego() {
    const dividido = clip.encuadre === "dividido";
    franjaJuego.hidden = !dividido;
    if (!dividido) { juego.pause(); quitarVistaWeb(); delete juegoWeb.dataset.id; creditoFondo = ""; return; }
    franjaJuego.style.top = (100 - proporcionJuego()) + "%";
    franjaJuego.style.height = proporcionJuego() + "%";
    const { remoto, local } = fondoDeVista();
    creditoFondo = remoto ? remoto.credito : "";
    if (remoto) { mostrarVistaWeb(remoto); return; }
    quitarVistaWeb();
    delete juegoWeb.dataset.id;
    if (!local) {
      if (juego.getAttribute("src")) { juego.removeAttribute("src"); juego.load(); }
      juego.hidden = true;
      juegoVacio.hidden = false;
      return;
    }
    juego.hidden = false;
    juegoVacio.hidden = true;
    const src = `/api/fondos/${encodeURIComponent(local)}/video`;
    if (juego.getAttribute("src") !== src) {
      juego.setAttribute("src", src);
      if (!video.paused) juego.play().catch(() => {});
    }
  }
  async function recargarFondos() {
    fondos = (await intentar(() => api("GET", "/fondos"))) || fondos;
  }
  // Crédito del autor del fondo: esquina inferior izquierda de la franja del juego, a 24 px de los bordes.
  function pintarCredito(e, escala) {
    const ver = clip.encuadre === "dividido" && e.credito_fondo && !!creditoFondo;
    creditoVista.hidden = !ver;
    if (!ver) return;
    if (creditoVista.textContent !== creditoFondo) creditoVista.textContent = creditoFondo;
    creditoVista.style.left = `${24 * escala}px`;
    creditoVista.style.bottom = `${24 * escala}px`;
    creditoVista.style.fontSize = (e.credito_tamano * escala) + "px";
  }
  let claveSub = "";
  function pintarSubtitulo() {
    if (!clip) { subInterior.textContent = ""; claveSub = ""; ganchoVista.hidden = true; marcaVista.hidden = true; creditoVista.hidden = true; return; }
    const t = video.currentTime, e = clip.estilo, escala = telefono.clientHeight / 1920;
    pintarCredito(e, escala);
    const cue = corteEn(t) ? null : clip.subtitulos.find((c) => t >= c.inicio && t < c.fin);
    const trozos = cue ? (e.mayusculas ? cue.texto.toUpperCase() : cue.texto).split(/\s+/).filter(Boolean) : [];
    // Palabra activa: el tiempo del subtitulo se reparte segun el largo de cada palabra
    // (el MP4 usa los tiempos reales de la transcripcion cuando el texto no se edito).
    let activa = -1;
    if (cue && e.resaltar && trozos.length) {
      const total = trozos.reduce((n, p) => n + p.length + 1, 0);
      const fraccion = (t - cue.inicio) / (cue.fin - cue.inicio);
      let acumulado = 0;
      activa = trozos.length - 1;
      for (let i = 0; i < trozos.length; i++) {
        acumulado += trozos[i].length + 1;
        if (fraccion < acumulado / total) { activa = i; break; }
      }
    }
    const clave = cue ? `${cue.inicio}|${trozos.join(" ")}|${activa}|${e.color_resalte}` : "";
    if (clave !== claveSub) {
      claveSub = clave;
      subInterior.replaceChildren(...trozos.flatMap((p, i) => [i ? " " : "", i === activa ? h("span", { style: `color:${e.color_resalte}` }, p) : p]));
    }
    subVista.style.top = e.posicion + "%";
    subVista.style.fontSize = (e.tamano * escala) + "px";
    subVista.style.color = e.color;
    subVista.style.webkitTextStroke = e.caja ? "0" : `${e.borde * 2 * escala}px ${e.color_borde}`;
    subInterior.style.background = e.caja && trozos.length ? e.color_borde : "";
    subInterior.style.padding = e.caja ? `${10 * escala}px ${18 * escala}px` : "";
    // Titulo gancho
    const tRel = t - clip.inicio - cortesDel().reduce((n, c) => n + Math.max(0, Math.min(t, c.fin) - c.inicio), 0);
    const visible = !!e.titulo_gancho && tRel >= -0.1 && (e.gancho_segundos === 0 || tRel < e.gancho_segundos);
    ganchoVista.hidden = !visible;
    if (visible) {
      if (ganchoInterior.textContent !== e.titulo_gancho) ganchoInterior.textContent = e.titulo_gancho;
      ganchoVista.style.top = e.gancho_posicion + "%";
      ganchoVista.style.fontSize = (e.gancho_tamano * escala) + "px";
      ganchoInterior.style.color = e.gancho_color;
      ganchoInterior.style.background = e.gancho_fondo;
      ganchoInterior.style.padding = `${12 * escala}px ${22 * escala}px`;
    }
    // Marca de agua: durante todo el clip, en la esquina elegida a 40 px de los bordes.
    marcaVista.hidden = !e.marca;
    if (e.marca) {
      if (marcaInterior.textContent !== e.marca) marcaInterior.textContent = e.marca;
      const arriba = e.marca_posicion.startsWith("arriba"), izquierda = e.marca_posicion.endsWith("izquierda");
      marcaVista.style.top = arriba ? `${40 * escala}px` : "auto";
      marcaVista.style.bottom = arriba ? "auto" : `${40 * escala}px`;
      marcaVista.style.left = izquierda ? `${40 * escala}px` : "auto";
      marcaVista.style.right = izquierda ? "auto" : `${40 * escala}px`;
      marcaVista.style.fontSize = (e.marca_tamano * escala) + "px";
      marcaVista.style.color = e.marca_color;
      marcaVista.style.opacity = e.marca_opacidad / 100;
    }
  }
  let cuadro = 0;
  function bucle() {
    if (cancelado) return;
    if (clip && !video.paused) {
      const corte = corteEn(video.currentTime);
      if (corte) video.currentTime = corte.fin;
    }
    if (clip && !video.paused && video.currentTime >= clip.fin) { video.pause(); video.currentTime = clip.inicio; }
    pintarSubtitulo();
    pintarFondo();
    pintarStream();
    if (clip?.trayectoria?.length && !["ajustar", "stream"].includes(clip.encuadre)) {
      video.style.left = `${posicionHorizontal(parseFloat(video.style.width), telefono.clientWidth)}px`;
    }
    moverCabezal();
    marcarCueActivo();
    cuadro = requestAnimationFrame(bucle);
  }
  function reproducir() {
    if (!clip) return;
    if (video.paused) {
      if (video.currentTime < clip.inicio - 0.05 || video.currentTime >= clip.fin - 0.05) video.currentTime = clip.inicio;
      const corte = corteEn(video.currentTime);
      if (corte) video.currentTime = corte.fin;
      video.play().catch(() => avisar("El navegador no pudo reproducir la vista previa.", "error"));
    } else video.pause();
  }
  video.addEventListener("click", reproducir);
  streamVista.addEventListener("click", reproducir);
  // El video de juego acompana al principal: suena igual de "play" y "pause" (siempre mudo).
  video.addEventListener("play", () => { if (clip && clip.encuadre === "dividido" && juego.getAttribute("src")) juego.play().catch(() => {}); });
  video.addEventListener("pause", () => juego.pause());
  video.addEventListener("error", () => avisar("No se pudo cargar la vista previa del video.", "error"));
  const alRedimensionar = () => { ajustarVideo(); };
  window.addEventListener("resize", alRedimensionar);

  // --- barra de recorte ---
  const barra = h("div", { class: "recorte-barra", role: "group", "aria-label": "Inicio y fin del clip" });
  const zona = h("div", { class: "recorte-zona" });
  const asaInicio = h("div", { class: "recorte-asa", title: "Inicio" });
  const asaFin = h("div", { class: "recorte-asa", title: "Fin" });
  const cabezal = h("div", { class: "recorte-cabezal" });
  barra.append(zona, asaInicio, asaFin, cabezal);
  let ventana = [0, 1];
  function calcularVentana() {
    const margen = Math.max(10, (clip.fin - clip.inicio) * 0.5);
    ventana = [Math.max(0, clip.inicio - margen), Math.min(proyecto.duracion, clip.fin + margen)];
  }
  const aPct = (t) => ((t - ventana[0]) / (ventana[1] - ventana[0])) * 100;
  function pintarBarra() {
    barra.querySelectorAll(".recorte-corte").forEach((n) => n.remove());
    for (const c of unirCortes(cortesDel())) barra.insertBefore(h("div", { class: "recorte-corte",
      style: `left:${aPct(c.inicio)}%;width:${aPct(c.fin) - aPct(c.inicio)}%` }), asaInicio);
    zona.style.left = aPct(clip.inicio) + "%";
    zona.style.width = (aPct(clip.fin) - aPct(clip.inicio)) + "%";
    asaInicio.style.left = aPct(clip.inicio) + "%";
    asaFin.style.left = aPct(clip.fin) + "%";
  }
  function moverCabezal() {
    if (!clip) return;
    const p = aPct(video.currentTime);
    cabezal.style.display = p < 0 || p > 100 ? "none" : "";
    cabezal.style.left = p + "%";
  }
  function tiempoEn(evento) {
    const r = barra.getBoundingClientRect();
    return ventana[0] + Math.max(0, Math.min(1, (evento.clientX - r.left) / r.width)) * (ventana[1] - ventana[0]);
  }
  function fijarRango(inicio, fin, mover) {
    inicio = Math.max(0, Math.min(inicio, proyecto.duracion - 1));
    fin = Math.max(inicio + 1, Math.min(fin, proyecto.duracion));
    if (fin - inicio > 600) { if (mover === "inicio") inicio = fin - 600; else fin = inicio + 600; }
    inicio = Math.round(inicio * 1000) / 1000;
    fin = Math.round(fin * 1000) / 1000;
    let cortes = unirCortes(cortesDel(), inicio, fin);
    if (fin - inicio - cortes.reduce((n, c) => n + c.fin - c.inicio, 0) < 1 - 1e-9) cortes = [];
    guardar({ inicio, fin, cortes });
    pintarBarra();
    if (entradaInicio) { entradaInicio.value = fmt(clip.inicio, 2); entradaFin.value = fmt(clip.fin, 2); duracionClip.textContent = textoDuracion(); }
  }
  barra.addEventListener("pointerdown", (e) => {
    if (!clip) return;
    const cual = e.target === asaInicio ? "inicio" : e.target === asaFin ? "fin" : null;
    barra.setPointerCapture(e.pointerId);
    video.pause();
    const mover = (ev) => {
      const t = tiempoEn(ev);
      if (cual === "inicio") { fijarRango(Math.min(t, clip.fin - 1), clip.fin, "inicio"); video.currentTime = clip.inicio; }
      else if (cual === "fin") { fijarRango(clip.inicio, Math.max(t, clip.inicio + 1), "fin"); video.currentTime = Math.max(clip.inicio, clip.fin - 0.05); }
      else video.currentTime = t;
    };
    mover(e);
    const soltar = () => {
      barra.removeEventListener("pointermove", mover);
      barra.removeEventListener("pointerup", soltar);
      barra.removeEventListener("pointercancel", soltar);
      if (cual) { calcularVentana(); pintarBarra(); }
    };
    barra.addEventListener("pointermove", mover);
    barra.addEventListener("pointerup", soltar);
    barra.addEventListener("pointercancel", soltar);
  });

  let entradaInicio = null, entradaFin = null, duracionClip = null;
  function marcarDesdeCabezal(clave) {
    const t = video.currentTime;
    if (clave === "inicio") fijarRango(t, Math.max(clip.fin, t + 1), "fin");
    else fijarRango(Math.min(clip.inicio, t - 1), t, "inicio");
    calcularVentana();
    pintarBarra();
  }

  function atajoEditor(e) {
    if (!clip || operaciones || e.defaultPrevented || e.isComposing || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
    if (e.target.closest("input, textarea, select, button, a, [role=button], [contenteditable]")) return;
    const tecla = e.key.toLowerCase();
    if (![" ", "arrowleft", "arrowright", "i", "o"].includes(tecla)) return;
    e.preventDefault();
    if (e.repeat && !tecla.startsWith("arrow")) return;
    if (tecla === " ") reproducir();
    else if (tecla === "i" || tecla === "o") marcarDesdeCabezal(tecla === "i" ? "inicio" : "fin");
    else {
      video.pause();
      const direccion = tecla === "arrowright" ? 1 : -1;
      const t = Math.max(clip.inicio, Math.min(clip.fin, video.currentTime + direccion));
      const corte = corteEn(t);
      video.currentTime = corte ? (direccion > 0 ? corte.fin : Math.max(clip.inicio, corte.inicio - 0.01)) : t;
    }
  }

  function pintarControles() {
    controles.replaceChildren();
    if (!clip) return;
    calcularVentana();
    pintarBarra();
    const campoTiempo = (clave) => {
      const entrada = h("input", { value: fmt(clip[clave], 2), "aria-label": clave === "inicio" ? "Inicio del clip" : "Fin del clip" });
      entrada.addEventListener("change", () => {
        const t = leerTiempo(entrada.value);
        if (t === null) { entrada.value = fmt(clip[clave], 2); return avisar("Escribe el tiempo como minutos:segundos, por ejemplo 1:23.5", "error"); }
        if (clave === "inicio") fijarRango(t, Math.max(clip.fin, t + 1), "fin"); else fijarRango(Math.min(clip.inicio, t - 1), t, "inicio");
        calcularVentana(); pintarBarra(); video.currentTime = clip.inicio;
      });
      return entrada;
    };
    entradaInicio = campoTiempo("inicio");
    entradaFin = campoTiempo("fin");
    duracionClip = h("span", { class: "tenue pequeno" }, textoDuracion());
    const ajuste = (clave, delta) => h("button", { class: "mini", "aria-label": `${delta > 0 ? "Sumar" : "Restar"} medio segundo al ${clave}`, onclick: () => {
      if (clave === "inicio") fijarRango(clip.inicio + delta, clip.fin, "inicio"); else fijarRango(clip.inicio, clip.fin + delta, "fin");
      calcularVentana(); pintarBarra();
    } }, delta > 0 ? "+0,5" : "−0,5");
    const aqui = (clave) => h("button", { class: "mini", onclick: () => marcarDesdeCabezal(clave) }, "Usar posición actual");
    controles.append(
      h("div", { class: "fila transporte" },
        h("button", { class: "primario", onclick: reproducir }, "Reproducir / pausar"),
        h("button", { onclick: () => { video.currentTime = clip.inicio; } }, "Ir al inicio"),
        velocidad, duracionClip, guardado),
      h("details", { class: "atajos-editor" }, h("summary", {}, "Atajos de teclado"),
        h("p", { class: "tenue pequeno" }, "Espacio: reproducir o pausar · ←/→: mover 1 s · I/O: fijar inicio o fin")),
      h("div", { class: "linea-tiempo" }, h("h3", {}, "Línea de tiempo"), barra),
      h("div", { class: "tiempos" },
        h("div", {}, h("label", {}, "Inicio"), h("div", { class: "fila" }, entradaInicio, ajuste("inicio", -0.5), ajuste("inicio", 0.5)), h("div", { style: "margin-top:5px" }, aqui("inicio"))),
        h("div", {}, h("label", {}, "Fin"), h("div", { class: "fila" }, entradaFin, ajuste("fin", -0.5), ajuste("fin", 0.5)), h("div", { style: "margin-top:5px" }, aqui("fin")))));
  }

  // --- lista de clips ---
  function elegirClip(c) {
    encolarPendiente();
    clip = c;
    video.pause();
    if (clip) video.currentTime = clip.inicio;
    pintarTodo();
  }
  function pintarClips() {
    listaClips.replaceChildren(...proyecto.clips.map((c) =>
      h("button", { class: "clip-item" + (clip && c.id === clip.id ? " activo" : ""), onclick: () => elegirClip(c) },
        h("strong", {}, c.titulo),
        h("span", { class: "clip-meta" },
          h("span", { class: "tenue pequeno" }, `${fmt(c.inicio, 0)} – ${fmt(c.fin, 0)} · ${Math.round(c.fin - c.inicio - segundosQuitados(c))} s`),
          h("span", { class: "etiqueta origen-" + (c.origen || "manual") }, ORIGENES[c.origen] || "Manual")),
        c.motivos && c.motivos.length ? h("ul", { class: "motivos" }, c.motivos.map((m) => h("li", {}, m))) : null)));
    if (!proyecto.clips.length) listaClips.append(h("p", { class: "tenue" }, "No hay clips. Crea uno desde la transcripción o con el botón «Nuevo clip»."));
  }

  const ORIGENES = { sugerido: "Propuesto", manual: "Manual", division: "División", vivo: "En vivo" };

  // --- panel derecho ---
  const PESTANAS = [["subtitulos", "Subtítulos"], ["aspecto", "Encuadre y estilo"], ["transcripcion", "Transcripción"], ["exportar", "Exportar"], ["tiktok", "TikTok"]];
  function marcarCueActivo() {
    if (pestana !== "subtitulos" || !clip) return;
    const t = video.currentTime;
    panelDerecho.querySelectorAll(".cue").forEach((fila, i) => {
      const c = clip.subtitulos[i];
      fila.classList.toggle("activo", !!c && t >= c.inicio && t < c.fin);
    });
  }
  function pintarDerecha() {
    fuenteStream = null;
    const barraPestanas = h("div", { class: "pestanas", role: "tablist" }, PESTANAS.map(([id, texto]) =>
      h("button", { class: pestana === id ? "activa" : "", role: "tab", "aria-selected": String(pestana === id), onclick: () => { pestana = id; pintarDerecha(); } },
        id === "exportar" && proyecto.exportaciones.length ? `${texto} (${proyecto.exportaciones.length})` : texto)));
    let cuerpo;
    if (pestana === "transcripcion") cuerpo = panelTranscripcion();
    else if (pestana === "exportar") cuerpo = panelExportar();
    else if (!clip) cuerpo = h("p", { class: "tenue" }, "Elige o crea un clip.");
    else if (pestana === "tiktok") cuerpo = panelTikTok();
    else cuerpo = pestana === "subtitulos" ? panelSubtitulos() : panelAspecto();
    panelDerecho.replaceChildren(barraPestanas, cuerpo);
  }

  function panelSubtitulos() {
    const filas = clip.subtitulos.map((c, i) => {
      const tiempo = (clave) => {
        const entrada = h("input", { value: fmt(c[clave], 2), "aria-label": clave === "inicio" ? "Inicio del subtítulo" : "Fin del subtítulo" });
        entrada.addEventListener("change", () => {
          const t = leerTiempo(entrada.value);
          const otros = { ...c, [clave]: t };
          if (t === null || otros.fin <= otros.inicio) { entrada.value = fmt(c[clave], 2); return avisar("El fin del subtítulo debe ser mayor que su inicio.", "error"); }
          c[clave] = t;
          guardar({ subtitulos: clip.subtitulos });
        });
        return entrada;
      };
      const texto = h("input", { class: "texto", value: c.texto, maxLength: 200, "aria-label": "Texto del subtítulo" });
      texto.addEventListener("input", () => { c.texto = texto.value; guardar({ subtitulos: clip.subtitulos }); });
      texto.addEventListener("focus", () => { video.pause(); video.currentTime = c.inicio + 0.01; });
      return h("div", { class: "cue" + (estaCortado(c) ? " cue-cortado" : "") }, tiempo("inicio"), tiempo("fin"), texto,
        h("button", { class: "mini peligro", "aria-label": "Eliminar subtítulo", onclick: () => {
          clip.subtitulos.splice(i, 1); guardar({ subtitulos: clip.subtitulos }); pintarDerecha();
        } }, "✕"));
    });
    return h("div", {},
      h("div", { class: "fila", style: "margin-bottom:10px" },
        h("button", { onclick: async () => {
          const id = clip.id, antes = cortesDel().map((c) => ({ ...c })), quitados = segundosQuitados();
          const r = await operar("quitar-silencios", ["cortes"]);
          if (!r) return;
          const anadidos = r.cortes.filter((c) => !antes.some((a) => a.inicio <= c.inicio && a.fin >= c.fin)).length;
          const segundos = segundosQuitados(r) - quitados;
          if (clip?.id === id) { pintarControles(); pintarClips(); pintarDerecha(); }
          avisar(`${anadidos} cortes añadidos; ${segundos.toFixed(2)} s adicionales eliminados.`);
        } }, "Quitar silencios"),
        cortesDel().length ? h("button", { onclick: () => cambiarCortes([]) }, "Restaurar todo") : null),
      h("div", { class: "fila", style: "margin-bottom:10px" },
        h("button", { onclick: () => {
          const t = Math.max(clip.inicio, Math.min(video.currentTime, clip.fin - 0.3));
          clip.subtitulos.push({ inicio: Math.round(t * 100) / 100, fin: Math.round(Math.min(clip.fin, t + 1.5) * 100) / 100, texto: "Nuevo texto" });
          clip.subtitulos.sort((a, b) => a.inicio - b.inicio);
          guardar({ subtitulos: clip.subtitulos }); pintarDerecha();
        } }, "Añadir en la posición actual"),
        h("button", { onclick: async () => {
          if (!confirm("Se reemplazarán los subtítulos de este clip por los de la transcripción. ¿Continuar?")) return;
          if (await operar("subtitulos/regenerar", ["subtitulos"])) pintarDerecha();
        } }, "Regenerar")),
      filas.length ? h("div", { class: "desplazable" }, filas)
        : h("p", { class: "tenue" }, "Este clip no tiene subtítulos. Añade uno o regenera desde la transcripción."));
  }

  function panelAspecto() {
    const e = clip.estilo;
    const estilo = (cambio) => { Object.assign(clip.estilo, cambio); guardar({ estilo: clip.estilo }); };
    const rango = (etiqueta, clave, min, max, objeto = e, alCambiar = null) => {
      const valor = h("span", {}, String(Math.round(objeto[clave] * (clave === "recorte_x" ? 100 : 1))));
      const entrada = h("input", { type: "range", min, max, value: clave === "recorte_x" ? objeto[clave] * 100 : objeto[clave] });
      entrada.addEventListener("input", () => {
        const v = Number(entrada.value);
        valor.textContent = String(v);
        if (alCambiar) alCambiar(v); else estilo({ [clave]: v });
      });
      if (clave === "recorte_x") entrada.addEventListener("change", pintarDerecha);
      return h("div", { class: "campo" }, h("label", {}, etiqueta, ": ", valor), entrada);
    };
    const encuadre = h("select", { "aria-label": "Tipo de encuadre" },
      h("option", { value: "rellenar" }, "Rellenar (recorta los lados)"),
      h("option", { value: "ajustar" }, "Ajustar (video completo con fondo)"),
      h("option", { value: "stream" }, "Stream (cámara y gameplay)"),
      h("option", { value: "dividido" }, "Dividido (video arriba y juego abajo)"));
    encuadre.value = clip.encuadre;
    encuadre.addEventListener("change", () => {
      // Los subtitulos no pueden quedar dentro del juego: se suben a la union de las dos mitades.
      if (encuadre.value === "dividido" && e.posicion > 100 - proporcionJuego()) estilo({ posicion: 100 - proporcionJuego() });
      guardar({ encuadre: encuadre.value }); ajustarVideo(); pintarDerecha();
    });
    const nombresFondo = fondos.locales.map((f) => f.nombre);
    const valoresRemotos = fondos.remotos.map((f) => f.valor);
    const fondoJuego = h("select", { "aria-label": "Video de fondo" },
      h("option", { value: "" }, "Al azar"),
      fondos.locales.length ? h("optgroup", { label: "En tu equipo" },
        fondos.locales.map((f) => h("option", { value: f.nombre }, f.nombre))) : null,
      fondos.remotos.length ? h("optgroup", { label: "Desde YouTube (se descarga solo el tramo al exportar)" },
        fondos.remotos.map((f) => h("option", { value: f.valor }, `${f.titulo} — ${f.canal}`))) : null);
    fondoJuego.value = nombresFondo.includes(e.fondo_juego) || valoresRemotos.includes(e.fondo_juego) ? e.fondo_juego : "";
    fondoJuego.addEventListener("change", () => { estilo({ fondo_juego: fondoJuego.value }); ajustarVideo(); });
    const abrirFondos = h("button", { title: fondos.carpeta, onclick: async () => {
      await intentar(() => api("POST", "/fondos/abrir-carpeta"));
      await recargarFondos();
      ajustarVideo(); pintarDerecha();
    } }, "Abrir carpeta de fondos");
    // Fondos de YouTube: se consultan sin descargar; los de serie solo se ocultan.
    const enlaceFondo = h("input", { type: "url", placeholder: "https://www.youtube.com/watch?v=…", maxLength: 2000,
      style: "flex:1;min-width:0", "aria-label": "Enlace de YouTube para añadir un fondo" });
    const botonAnadir = h("button", { onclick: async () => {
      const url = enlaceFondo.value.trim();
      if (!url) return avisar("Pega el enlace de un video de YouTube.", "error");
      botonAnadir.disabled = true;
      botonAnadir.textContent = "Consultando…";
      const r = await intentar(() => api("POST", "/fondos/remotos", { url }));
      botonAnadir.disabled = false;
      botonAnadir.textContent = "Añadir";
      if (!r || !clip) return;
      fondos = r;
      estilo({ fondo_juego: r.fondo.valor });
      avisar(`Fondo añadido: ${r.fondo.titulo} (${r.fondo.canal}).`);
      ajustarVideo(); pintarDerecha();
    } }, "Añadir");
    enlaceFondo.addEventListener("keydown", (ev) => { if (ev.key === "Enter") botonAnadir.click(); });
    const quitarFondo = async (f) => {
      const r = await intentar(() => api("DELETE", `/fondos/remotos/${f.id}`));
      if (!r || !clip) return;
      fondos = r;
      if (clip.estilo.fondo_juego === f.valor) estilo({ fondo_juego: "" });
      ajustarVideo(); pintarDerecha();
    };
    const mostrarFondo = async (f) => {
      const r = await intentar(() => api("POST", "/fondos/remotos", { url: f.url }));
      if (!r || !clip) return;
      fondos = r;
      ajustarVideo(); pintarDerecha();
    };
    const enlaceAccion = (texto, alClic, titulo) => h("button", { class: "enlace", title: titulo, onclick: alClic }, texto);
    const listaRemotos = fondos.remotos.length || fondos.ocultos.length ? h("ul", { class: "fondos-remotos" },
      fondos.remotos.map((f) => h("li", {},
        h("span", { title: f.licencia }, `${f.titulo} — ${f.canal}`),
        enlaceAccion(f.de_serie ? "Ocultar" : "Quitar", () => quitarFondo(f), f.de_serie ? "Deja de mostrarlo en la lista" : "Quita este fondo de la lista"))),
      fondos.ocultos.map((f) => h("li", { class: "tenue" },
        h("span", {}, `${f.titulo} (oculto)`),
        enlaceAccion("Mostrar", () => mostrarFondo(f))))) : null;
    const bloqueDividido = clip.encuadre === "dividido" ? h("div", {},
      h("div", { class: "campo" }, fondoJuego),
      h("div", { class: "campo" }, h("label", {}, "Añadir fondo de YouTube"),
        h("div", { class: "fila" }, enlaceFondo, botonAnadir)),
      listaRemotos,
      rango("Alto del juego (% de la pantalla)", "juego_proporcion", 25, 60, { juego_proporcion: proporcionJuego() },
        (v) => { estilo({ juego_proporcion: v }); ajustarVideo(); }),
      h("div", { class: "campo fila" }, abrirFondos),
      fondos.locales.length || fondos.remotos.length ? null : h("p", { class: "tenue pequeno" }, "No hay videos de fondo. Copia alguno en la carpeta de fondos o añade un enlace de YouTube.")) : null;
    const color = (etiqueta, clave, despues = null) => {
      const entrada = h("input", { type: "color", value: e[clave] });
      entrada.addEventListener("input", () => { estilo({ [clave]: entrada.value.toUpperCase() }); if (despues) despues(); });
      return h("div", {}, h("label", {}, etiqueta), entrada);
    };
    const casilla = (etiqueta, clave, repintar = false) => {
      const entrada = h("input", { type: "checkbox", checked: e[clave] });
      entrada.addEventListener("change", () => { estilo({ [clave]: entrada.checked }); if (repintar) pintarDerecha(); });
      return h("label", { class: "fila", style: "color:var(--texto);font-size:14px;margin:0" }, entrada, etiqueta);
    };
    const bloqueCredito = clip.encuadre === "dividido" ? h("div", {},
      h("div", { class: "campo" }, casilla("Mostrar crédito del fondo", "credito_fondo", true)),
      e.credito_fondo ? rango("Tamaño del crédito", "credito_tamano", 16, 60) : null,
      h("p", { class: "tenue pequeno" }, "Algunos fondos piden dar crédito al autor (licencia Creative Commons con atribución). Puedes mostrarlo aquí o en la descripción de tu publicación.")) : null;
    const preajuste = h("select", { "aria-label": "Estilo prefabricado" },
      h("option", { value: "" }, "Elegir un estilo prefabricado…"),
      Object.keys(PREAJUSTES).map((nombre) => h("option", { value: nombre }, nombre)));
    preajuste.addEventListener("change", () => {
      if (!PREAJUSTES[preajuste.value]) return;
      estilo({ ...PREAJUSTES[preajuste.value] });
      pintarDerecha();
    });
    const fondo = h("select", { "aria-label": "Fondo del encuadre" },
      h("option", { value: "difuminado" }, "Fondo: video difuminado"),
      h("option", { value: "difuminado_oscuro" }, "Fondo: difuminado y oscurecido"),
      h("option", { value: "difuminado_gris" }, "Fondo: difuminado en blanco y negro"),
      h("option", { value: "color" }, "Fondo: color sólido"));
    fondo.value = e.fondo;
    fondo.addEventListener("change", () => { estilo({ fondo: fondo.value }); ajustarVideo(); pintarDerecha(); });
    const gancho = h("input", { value: e.titulo_gancho, maxLength: 80, style: "width:100%", placeholder: "Ej.: 3 errores al planear tu semana", "aria-label": "Texto del título gancho" });
    gancho.addEventListener("input", () => estilo({ titulo_gancho: gancho.value }));
    // Los controles del gancho aparecen o desaparecen al escribir la primera letra o borrar todo.
    gancho.addEventListener("change", () => pintarDerecha());
    const marca = h("input", { value: e.marca, maxLength: 40, style: "width:100%", placeholder: "@tucanal", "aria-label": "Texto de la marca de agua" });
    marca.addEventListener("input", () => estilo({ marca: marca.value }));
    // Igual que el gancho: los controles de la marca aparecen al escribir la primera letra o al borrar todo.
    marca.addEventListener("change", () => pintarDerecha());
    const posicionMarca = h("select", { "aria-label": "Posición de la marca de agua" },
      h("option", { value: "arriba_izquierda" }, "Arriba a la izquierda"),
      h("option", { value: "arriba_derecha" }, "Arriba a la derecha"),
      h("option", { value: "abajo_izquierda" }, "Abajo a la izquierda"),
      h("option", { value: "abajo_derecha" }, "Abajo a la derecha"));
    posicionMarca.value = e.marca_posicion;
    posicionMarca.addEventListener("change", () => estilo({ marca_posicion: posicionMarca.value }));
    const predeterminado = h("button", { onclick: async () => {
      if (!(await vaciar())) return avisar(AVISO_GUARDADO, "error");
      const r = await intentar(() => api("PUT", "/preferencias/clip", { estilo: clip.estilo, encuadre: clip.encuadre, composicion: clip.composicion || {} }));
      if (r) avisar("Guardado: los clips nuevos nacerán con este estilo y encuadre.");
    } }, "Usar este estilo en los clips nuevos");
    // Copia el estilo de este clip a todos los demas del proyecto.
    const aplicarATodos = (que, texto, pregunta) => h("button", { disabled: proyecto.clips.length < 2, onclick: async (ev) => {
      const boton = ev.currentTarget, id = clip.id;
      if (!confirm(pregunta)) return;
      boton.disabled = true;
      if (!(await vaciar())) { boton.disabled = false; return avisar(AVISO_GUARDADO, "error"); }
      const p = await intentar(() => api("POST", `/proyectos/${pid}/aplicar-estilo`, { clip_id: id, que }));
      boton.disabled = false;
      if (!p) return;
      // Se actualizan los mismos objetos de clip para no perder la seleccion actual.
      for (const nuevo of p.clips) {
        const local = proyecto.clips.find((c) => c.id === nuevo.id);
        if (local) { local.estilo = nuevo.estilo; local.encuadre = nuevo.encuadre; local.composicion = nuevo.composicion; }
      }
      pintarClips(); ajustarVideo();
      avisar(`Estilo aplicado a ${p.aplicados} clip(s).`);
    } }, texto);
    let bloqueStream = null;
    if (clip.encuadre === "stream") {
      fuenteStream = h("canvas", { width: 640, height: Math.max(2, Math.round(640 * proyecto.alto / proyecto.ancho)) });
      const selector = crearSelectorStream({ h, fuente: fuenteStream, composicion: clip.composicion,
        alCambiar: (composicion) => { guardar({ composicion }); pintarStream(); },
        alAutomatico: async () => {
          const r = await operar("camara-auto", ["composicion", "encuadre"]);
          if (!r) return;
          if (!r.detectado) return avisar("No se detectó la cámara. Puedes marcarla sobre la imagen.");
          ajustarVideo(); pintarDerecha();
        } });
      bloqueStream = selector.elemento;
      pintarStream();
    }
    const otros = Math.max(0, proyecto.clips.length - 1);
    const ancho = proyecto.ancho / proyecto.alto > 9 / 16;
    const recorteVisible = (clip.encuadre === "rellenar" || clip.encuadre === "dividido") && ancho;
    const seccion = (titulo, ...hijos) => h("section", { class: "seccion" }, h("h3", {}, titulo), ...hijos);
    return h("div", { class: "secciones" },
      seccion("Encuadre 9:16",
        h("div", { class: "campo" }, encuadre),
        bloqueDividido,
        bloqueCredito,
        bloqueStream,
        recorteVisible ? h("div", { class: "fila campo", role: "group", "aria-label": "Posiciones de encuadre fijo" },
          ...[[0, "Izquierda"], [.5, "Centro"], [1, "Derecha"]].map(([posicion, texto]) =>
            h("button", { class: "mini", onclick: () => {
              guardar({ recorte_x: posicion });
              ajustarVideo();
              pintarDerecha();
            } }, texto))) : null,
        recorteVisible ? rango("Posición horizontal del recorte (0 izquierda – 100 derecha)", "recorte_x", 0, 100, clip,
          (v) => { guardar({ recorte_x: v / 100 }); ajustarVideo(); }) : null,
        recorteVisible ? h("div", { class: "campo" }, h("button", { onclick: async (event) => {
          const boton = event.currentTarget;
          boton.textContent = "Analizando rostro…";
          const r = await operar("encuadre-auto", ["recorte_x", "encuadre", "trayectoria"]);
          boton.textContent = "Seguir el rostro";
          if (!r) return;
          if (!r.detectado) return avisar("No se detectó un rostro con suficiente continuidad. Ajusta la posición a mano.");
          if (!vigente()) return;
          ajustarVideo();
          pintarDerecha();
          const cobertura = r.cobertura == null ? "" : ` Rostro detectado en el ${Math.round(r.cobertura * 100)} % de las muestras.`;
          avisar("Seguimiento del rostro activado." + cobertura);
        } }, "Seguir el rostro"),
        clip.trayectoria?.length ? h("button", { onclick: () => {
          guardar({ seguimiento: false }); ajustarVideo(); pintarDerecha();
        } }, "Usar encuadre fijo") : null,
        h("p", { class: "ayuda" }, clip.trayectoria?.length
          ? "Seguimiento activo. Ajustar la posición o los límites del clip lo desactiva."
          : "El seguimiento adapta el recorte al movimiento del rostro.")) : null,
        clip.encuadre === "ajustar" ? h("div", { class: "campo fila" }, fondo, e.fondo === "color" ? color("Color", "color_fondo", ajustarVideo) : null) : null,
        clip.encuadre === "ajustar" && e.fondo !== "color"
          ? rango("Intensidad del difuminado", "difuminado", 4, 50, e, (v) => { estilo({ difuminado: v }); ajustarVideo(); }) : null),
      seccion("Subtítulos",
        h("div", { class: "campo" }, preajuste),
        rango("Tamaño", "tamano", 24, 140),
        rango("Altura en pantalla (% desde arriba)", "posicion", 5, 95),
        e.caja ? null : rango("Grosor del borde", "borde", 0, 12),
        h("div", { class: "fila campo" }, color("Texto", "color"), color(e.caja ? "Caja" : "Borde", "color_borde"),
          e.resaltar ? color("Resalte", "color_resalte") : null),
        h("div", { class: "fila campo", style: "gap:16px" }, casilla("Mayúsculas", "mayusculas"), casilla("Caja de fondo", "caja", true), casilla("Resaltar la palabra dicha", "resaltar", true)),
        rango("Palabras por subtítulo (se aplica al pulsar Regenerar)", "max_palabras", 1, 8),
        rango("Letras por subtítulo (se aplica al pulsar Regenerar)", "max_caracteres", 8, 42)),
      seccion("Título gancho",
        h("div", { class: "campo" }, gancho),
        e.titulo_gancho ? rango("Segundos en pantalla (0 = todo el clip)", "gancho_segundos", 0, 30) : null,
        e.titulo_gancho ? rango("Altura en pantalla (% desde arriba)", "gancho_posicion", 4, 90) : null,
        e.titulo_gancho ? rango("Tamaño", "gancho_tamano", 24, 140) : null,
        e.titulo_gancho ? h("div", { class: "fila campo" }, color("Texto", "gancho_color"), color("Fondo", "gancho_fondo")) : null),
      seccion("Marca de agua",
        h("div", { class: "campo" }, marca),
        e.marca ? h("div", { class: "campo" }, posicionMarca) : null,
        e.marca ? rango("Tamaño", "marca_tamano", 16, 80) : null,
        e.marca ? rango("Opacidad (%)", "marca_opacidad", 10, 100) : null,
        e.marca ? h("div", { class: "fila campo" }, color("Color", "marca_color")) : null),
      seccion("Aplicar a otros clips",
        h("div", { class: "botones-columna" },
          aplicarATodos("subtitulos", `Aplicar estos subtítulos a todos los clips (${otros})`,
            `El tamaño, los colores, la posición y el resto del aspecto de los subtítulos de este clip se copiarán a los otros ${otros} clips. El texto de cada clip no cambia. ¿Continuar?`),
          aplicarATodos("todo", `Aplicar estilo y encuadre a todos los clips (${otros})`,
            `El estilo completo (subtítulos, fondo, pantalla dividida) y el tipo de encuadre de este clip se copiarán a los otros ${otros} clips. El título gancho y la posición del recorte de cada clip no cambian. ¿Continuar?`),
          predeterminado),
        h("p", { class: "tenue pequeno", style: "margin-top:10px" }, "La vista previa es aproximada: el MP4 usa la fuente Arial en negrita y puede variar ligeramente el ajuste de línea, el desenfoque del fondo y el momento exacto del resaltado.")));
  }

  function panelTranscripcion() {
    if (!transcripcion.frases.length) return h("p", { class: "tenue" }, "Este video no tiene transcripción (sin audio o sin voz detectada).");
    const crear = h("button", { class: "primario", disabled: !seleccion, onclick: async () => {
      const [a, b] = seleccion;
      const nuevo = await intentar(() => api("POST", `/proyectos/${pid}/clips`, {
        inicio: transcripcion.frases[a].inicio, fin: transcripcion.frases[b].fin, titulo: transcripcion.frases[a].texto.slice(0, 60),
      }));
      if (nuevo) { seleccion = null; proyecto.clips.push(nuevo); proyecto.clips.sort((x, y) => x.inicio - y.inicio); pestana = "subtitulos"; elegirClip(nuevo); }
    } }, "Crear clip con la selección");
    const info = h("span", { class: "tenue pequeno" }, seleccion
      ? `${fmt(transcripcion.frases[seleccion[0]].inicio, 0)} – ${fmt(transcripcion.frases[seleccion[1]].fin, 0)}`
      : "Haz clic en una frase y luego Mayús+clic en otra para elegir un tramo.");
    const filas = transcripcion.frases.map((f, i) =>
      h("div", { class: "fila-frase" + (clip && estaCortado(f) ? " frase-cortada" : "") },
      h("button", { class: "frase" + (seleccion && i >= seleccion[0] && i <= seleccion[1] ? " elegida" : ""), onclick: (ev) => {
        if (ev.shiftKey && seleccion) seleccion = [Math.min(seleccion[0], i), Math.max(seleccion[0], i)];
        else seleccion = [i, i];
        video.pause(); video.currentTime = f.inicio;
        const tope = panelDerecho.querySelector(".desplazable").scrollTop;
        pintarDerecha();
        panelDerecho.querySelector(".desplazable").scrollTop = tope;
      } }, h("span", { class: "tenue pequeno" }, fmt(f.inicio, 0)), h("span", {}, f.texto)),
      clip && f.inicio >= clip.inicio && f.fin <= clip.fin ? h("button", { class: "mini", onclick: (ev) => {
        ev.stopPropagation();
        if (estaCortado(f)) {
          // Restaurar solo esta frase, incluso si su corte se fusiono con otros.
          cambiarCortes(cortesDel().flatMap((c) => c.fin <= f.inicio || c.inicio >= f.fin ? [c] :
            [{ inicio: c.inicio, fin: f.inicio }, { inicio: f.fin, fin: c.fin }]).filter((c) => c.fin > c.inicio));
        } else cambiarCortes([...cortesDel(), { inicio: f.inicio, fin: f.fin }]);
      } }, estaCortado(f) ? "Restaurar" : "Quitar") : null));
    return h("div", {}, h("div", { class: "fila", style: "margin-bottom:10px" }, crear, info), h("div", { class: "desplazable" }, filas));
  }

  function panelTikTok() {
    const id = clip.id;
    const datos = () => clip.tiktok || { contexto: "", texto: "" };
    const firma = () => JSON.stringify([clip.titulo, clip.inicio, clip.fin, clip.cortes, clip.subtitulos, clip.estilo.titulo_gancho]);
    const contexto = h("input", { value: datos().contexto || "", maxLength: 200,
      placeholder: "Ej.: Valorant, Jett, clutch", "aria-label": "Juego o tema del clip" });
    const texto = h("textarea", { value: datos().texto || "", maxLength: 1000, rows: 4,
      "aria-label": "Hashtags para TikTok", placeholder: "Genera sugerencias o escribe tus hashtags." });
    const cambiar = (cambio) => { if (clip?.id === id) guardar({ tiktok: { ...datos(), ...cambio } }); };
    contexto.addEventListener("input", () => cambiar({ contexto: contexto.value }));
    texto.addEventListener("input", () => cambiar({ texto: texto.value }));
    const generar = h("button", { class: "primario", onclick: async () => {
      if (clip?.id !== id) return;
      generar.disabled = true;
      generar.textContent = "Buscando temas…";
      const tema = contexto.value;
      const base = firma();
      const anterior = datos().texto || "";
      const peticion = (peticionesTikTok.get(id) || 0) + 1;
      peticionesTikTok.set(id, peticion);
      try {
        if (!(await vaciar())) return avisar(AVISO_GUARDADO, "error");
        const resultado = await intentar(() => api("POST", `/clips/${id}/hashtags`, { contexto: tema }));
        if (!resultado || !vigente() || clip?.id !== id || peticionesTikTok.get(id) !== peticion) return;
        if ((datos().contexto || "") !== tema || (datos().texto || "") !== anterior || firma() !== base) return avisar("El clip, tema o texto cambió. Vuelve a generar las sugerencias.");
        sugerenciasTikTok.set(id, resultado);
        cambiar({ texto: resultado.texto, contexto: tema });
        if (pestana === "tiktok") pintarDerecha();
      } finally {
        generar.disabled = false;
        generar.textContent = "Recomendar hashtags";
      }
    } }, "Recomendar hashtags");
    const copiar = h("button", { onclick: async () => {
      if (!texto.value.trim()) return avisar("Primero genera o escribe tus hashtags.");
      try {
        await navigator.clipboard.writeText(texto.value.trim());
        avisar("Hashtags copiados.");
      } catch {
        texto.focus(); texto.select();
        avisar("Texto seleccionado. Pulsa Ctrl+C para copiarlo.");
      }
    } }, "Copiar hashtags");
    const resultado = sugerenciasTikTok.get(id);
    return h("section", { class: "hashtags-tiktok" },
      h("h2", {}, "Hashtags para TikTok"),
      h("p", { class: "tenue pequeno" }, "Sugerencias según el título y el contenido que conserva este clip. Si el juego o tema no se menciona, indícalo para afinar."),
      h("label", {}, "Juego o tema (opcional)", contexto),
      h("div", { class: "fila" }, generar),
      resultado?.necesita_contexto ? h("p", { class: "tenue pequeno", role: "status" }, "No identifiqué un tema concreto. Añade el juego o tema; no puedo reconocerlo solo por la imagen.") : null,
      h("label", {}, "Hashtags editables", texto),
      h("div", { class: "fila" }, copiar),
      h("p", { class: "tenue pequeno" }, "Se guardan con este clip. Vuelve a generar si cambias su contenido. Generar reemplaza el bloque de hashtags."),
      resultado?.hashtags.length ? h("ul", { class: "motivos" }, resultado.hashtags.map(x => h("li", {}, h("strong", {}, x.etiqueta), " · ", x.motivo))) : null,
      h("p", { class: "tenue pequeno" }, "Los hashtags no garantizan visitas ni aparecer en Para ti. Son sugerencias temáticas locales, sin datos de tendencias en tiempo real."),
      h("a", { href: "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag", target: "_blank", rel: "noopener", class: "pequeno" }, "Consultar tendencias en TikTok Creative Center"));
  }

  function panelExportar() {
    const exportar = h("button", { class: "primario", disabled: !clip, onclick: async () => {
      const id = clip.id;
      exportar.disabled = true;
      // Primero se guarda todo; si falla, no se exporta una version anterior.
      if (!(await vaciar())) { exportar.disabled = false; return avisar(AVISO_GUARDADO, "error"); }
      const e = await intentar(() => api("POST", `/clips/${id}/exportar`));
      exportar.disabled = false;
      if (e) { proyecto.exportaciones.unshift(e); pintarDerecha(); }
    } }, "Exportar este clip a MP4");
    const descargarSrt = h("button", { disabled: !clip, onclick: async () => {
      const id = clip.id;
      descargarSrt.disabled = true;
      try {
        if (!(await vaciar())) return avisar(AVISO_GUARDADO, "error");
        if (!vigente()) return;
        const enlace = h("a", { href: `/api/clips/${id}/subtitulos.srt`, download: "" });
        const respuesta = await fetch(enlace.href);
        if (!respuesta.ok) throw new Error(mensajeError(await respuesta.json().catch(() => null), respuesta.status));
        const nombre = respuesta.headers.get("Content-Disposition")?.split("UTF-8''")[1];
        enlace.download = nombre ? decodeURIComponent(nombre) : "subtitulos.srt";
        const url = URL.createObjectURL(await respuesta.blob());
        enlace.href = url;
        enlace.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (e) { avisar(e.message, "error"); }
      finally { descargarSrt.disabled = false; }
    } }, "Descargar subtítulos SRT");
    const todos = h("button", { disabled: !proyecto.clips.length, onclick: async () => {
      const n = proyecto.clips.length;
      if (!confirm(`Se exportarán los ${n} clips del proyecto, uno tras otro. ¿Continuar?`)) return;
      todos.disabled = true;
      if (!(await vaciar())) { todos.disabled = false; return avisar(AVISO_GUARDADO, "error"); }
      const p = await intentar(() => api("POST", `/proyectos/${pid}/exportar-todos`, {}));
      todos.disabled = false;
      if (p) { proyecto.exportaciones = p.exportaciones; pintarDerecha(); avisar(`${p.encolados} exportaciones en cola.`); }
    } }, `Exportar todos (${proyecto.clips.length})`);
    const listas = proyecto.exportaciones.filter((x) => x.estado === "listo").length;
    const enCurso = proyecto.exportaciones.filter((x) => ACTIVOS.includes(x.estado)).length;
    const items = proyecto.exportaciones.map((e) => {
      const activo = ACTIVOS.includes(e.estado);
      return h("div", { class: "exportacion" },
        h("div", { class: "fila" }, h("strong", { class: "crece" }, e.titulo), h("span", { class: "etiqueta " + e.estado }, ESTADOS[e.estado] || e.estado)),
        activo ? h("div", { class: "progreso" }, h("div", { style: `width:${e.progreso}%` })) : null,
        e.estado === "error" ? h("p", { class: "mensaje-error pequeno", style: "margin-top:6px" }, e.error || "Error desconocido.") : null,
        h("div", { class: "fila", style: "margin-top:8px" },
          e.estado === "listo" ? h("a", { class: "boton", href: `/api/exportaciones/${e.id}/archivo?descargar=true` }, "Descargar") : null,
          e.estado === "listo" ? h("a", { class: "boton", href: `/api/exportaciones/${e.id}/archivo`, target: "_blank", rel: "noopener" }, "Ver") : null,
          activo ? h("button", { onclick: async () => { await intentar(() => api("POST", `/exportaciones/${e.id}/cancelar`)); sondear(); } }, "Cancelar") : null,
          !activo ? h("button", { class: "peligro", onclick: async () => {
            await intentar(() => api("DELETE", `/exportaciones/${e.id}`));
            proyecto.exportaciones = proyecto.exportaciones.filter((x) => x.id !== e.id); pintarDerecha();
          } }, "Eliminar") : null));
    });
    return h("div", {},
      h("div", { class: "fila", style: "margin-bottom:6px" }, exportar, descargarSrt, todos,
        h("button", { onclick: () => intentar(() => api("POST", `/proyectos/${pid}/abrir-carpeta`)) }, "Abrir carpeta")),
      h("p", { class: "tenue pequeno" }, "Salida: 1080×1920, H.264 + AAC, con los subtítulos incrustados." +
        (proyecto.exportaciones.length ? ` ${listas} lista(s)` + (enCurso ? `, ${enCurso} en curso o en cola.` : ".") : "")),
      h("div", { class: "desplazable" }, items.length ? items : h("p", { class: "tenue" }, "Aún no has exportado ningún clip.")));
  }

  function pintarTodo() {
    pintarClips(); pintarControles(); pintarDerecha(); ajustarVideo();
    titulo.value = clip ? clip.titulo : "";
    titulo.disabled = !clip;
    duplicar.disabled = !clip || operaciones > 0;
  }

  // --- sondeo de exportaciones ---
  async function sondear() {
    if (!proyecto.exportaciones.some((e) => ACTIVOS.includes(e.estado))) return;
    const lista = proyecto.exportaciones, cuantas = lista.length;
    const p = await api("GET", `/proyectos/${pid}`).catch(() => null);
    if (!p || cancelado) return;
    // Si la lista cambio mientras llegaba la respuesta (nueva exportacion, borrado, otro
    // proyecto cargado), esta respuesta es antigua: se espera al siguiente sondeo.
    if (proyecto.exportaciones !== lista || lista.length !== cuantas) return;
    const antes = JSON.stringify(proyecto.exportaciones);
    proyecto.exportaciones = p.exportaciones;
    if (pestana === "exportar" && antes !== JSON.stringify(p.exportaciones)) pintarDerecha();
    const previas = JSON.parse(antes);
    const activasAntes = previas.filter((x) => ACTIVOS.includes(x.estado)).length;
    for (const e of p.exportaciones) {
      const previo = previas.find((x) => x.id === e.id);
      if (!previo || !ACTIVOS.includes(previo.estado)) continue;
      // En una exportacion en lote no se avisa clip por clip, solo los fallos y el final.
      if (e.estado === "listo" && activasAntes <= 3) avisar(`Exportación lista: ${e.titulo}`);
      if (e.estado === "error") avisar(`La exportación de «${e.titulo}» falló: ${e.error || ""}`, "error");
    }
    if (activasAntes > 3 && !p.exportaciones.some((x) => ACTIVOS.includes(x.estado))) avisar("Terminaron todas las exportaciones.");
  }

  // --- acciones de cabecera ---
  const nuevoClip = h("button", { onclick: async () => {
    const inicio = Math.min(video.currentTime, Math.max(0, proyecto.duracion - 1));
    const nuevo = await intentar(() => api("POST", `/proyectos/${pid}/clips`, { inicio, fin: Math.min(proyecto.duracion, inicio + 30), titulo: "" }));
    if (nuevo) { proyecto.clips.push(nuevo); proyecto.clips.sort((a, b) => a.inicio - b.inicio); elegirClip(nuevo); }
  }, title: "Crea un clip de hasta 30 segundos desde la posición actual" }, "+ Nuevo clip");
  const duplicar = h("button", { disabled: !clip, onclick: async () => {
    const original = clip.id;
    duplicar.disabled = true;
    const copia = await operar("duplicar", []);
    duplicar.disabled = !clip;
    if (!copia || !vigente()) return;
    proyecto.clips.push(copia);
    proyecto.clips.sort((a, b) => a.inicio - b.inicio);
    if (clip?.id === original) elegirClip(copia);
    else pintarClips();
    avisar("Clip duplicado.");
  } }, "Duplicar clip");
  const borrarClip = h("button", { class: "peligro", onclick: async () => {
    if (!clip || !confirm(`¿Eliminar el clip «${clip.titulo}»?`)) return;
    const id = clip.id;
    await vaciar();
    if ((await intentar(() => api("DELETE", `/clips/${id}`))) === undefined) return;
    proyecto.clips = proyecto.clips.filter((c) => c.id !== id);
    elegirClip(proyecto.clips[0] || null);
  } }, "Eliminar clip");
  const minS = h("input", { type: "number", min: 3, max: 300, value: proyecto.min_s || 15, style: "width:64px", "aria-label": "Duración mínima en segundos" });
  const maxS = h("input", { type: "number", min: 5, max: 600, value: proyecto.max_s || 60, style: "width:64px", "aria-label": "Duración máxima en segundos" });
  const parteS = h("input", { type: "number", min: 5, max: 600, value: 30, style: "width:64px", "aria-label": "Duración de cada parte en segundos" });
  const enPausas = h("input", { type: "checkbox", checked: true });
  const dividir = h("button", { onclick: async () => {
    const duracion_s = Number(parteS.value);
    if (!(duracion_s >= 5 && duracion_s <= 600)) return avisar("La duración de cada parte debe estar entre 5 y 600 segundos.", "error");
    const partes = Math.max(1, Math.round(proyecto.duracion / duracion_s));
    const yaHay = proyecto.clips.some((c) => c.origen === "division");
    if (!confirm(`Se crearán unos ${partes} clips que cubren todo el video.` + (yaHay ? " Se reemplazará la división anterior." : "") + " ¿Continuar?")) return;
    if (!(await vaciar())) return avisar(AVISO_GUARDADO, "error");
    dividir.disabled = true;
    const p = await intentar(() => api("POST", `/proyectos/${pid}/dividir`, { duracion_s, ajustar_a_pausas: enPausas.checked }));
    dividir.disabled = false;
    if (p) { proyecto = p; elegirClip(p.clips.find((c) => c.origen === "division") || p.clips[0] || null); avisar(`Video dividido en ${p.creados} clips.`); }
  } }, "Dividir todo el video");
  const proponer = h("button", { onclick: async () => {
    if (!confirm("Se reemplazarán los clips propuestos (los manuales se conservan). ¿Continuar?")) return;
    if (!(await vaciar())) return avisar(AVISO_GUARDADO, "error");
    proponer.disabled = true;
    const p = await intentar(() => api("POST", `/proyectos/${pid}/sugerir`, { min_s: Number(minS.value), max_s: Number(maxS.value) }));
    proponer.disabled = false;
    if (p) { proyecto = p; elegirClip(p.clips[0] || null); avisar("Propuestas actualizadas."); }
  } }, "Volver a proponer");
  const titulo = h("input", { class: "crece", maxLength: 120, "aria-label": "Título del clip" });
  titulo.addEventListener("input", () => { if (clip && titulo.value.trim()) { guardar({ titulo: titulo.value.trim() }); } });

  vista.append(
    h("div", { class: "editor-cabecera" }, h("a", { class: "boton", href: "#/" }, "← Proyectos"), h("h1", {}, proyecto.nombre),
      h("span", { class: "tenue pequeno" }, `${fmtDuracion(proyecto.duracion)} · ${proyecto.ancho}×${proyecto.alto}` + (proyecto.idioma_detectado ? ` · idioma: ${proyecto.idioma_detectado}` : ""))),
    h("div", { class: "editor" },
      h("section", { class: "panel panel-clips" }, h("h2", {}, "Clips"), listaClips,
        h("div", { class: "herramientas" },
          h("div", { class: "botones-columna" }, nuevoClip, duplicar, borrarClip),
          h("div", { class: "grupo" },
            h("h3", {}, "Proponer clips"),
            h("div", { class: "fila pequeno" }, "Entre", minS, "y", maxS, "s", proponer),
            h("p", { class: "tenue pequeno" }, "Se eligen por pausas, cierres de frase, ritmo del habla y picos de volumen. No miden interés ni predicen resultados.")),
          h("div", { class: "grupo" },
            h("h3", {}, "Dividir el video completo"),
            h("div", { class: "fila pequeno" }, "Partes de", parteS, "s", dividir),
            h("label", { class: "fila pequeno", style: "margin:6px 0 0" }, enPausas, "Mover cada corte a la pausa más cercana para no partir frases")))),
      h("section", { class: "centro panel", "aria-label": "Vista previa del clip" },
        h("div", { class: "monitor-cabecera" }, tituloPrevio, h("div", { class: "fila" }, mostrarGuia, h("span", { class: "etiqueta" }, "9:16"))),
        h("div", { class: "monitor" }, telefono),
        h("label", { class: "titulo-clip" }, "Título del clip", titulo),
        controles),
      h("section", { class: "panel inspector", "aria-label": "Ajustes del clip" }, panelDerecho)));

  video.addEventListener("loadedmetadata", () => { if (clip) video.currentTime = clip.inicio; ajustarVideo(); });
  pintarTodo();
  document.addEventListener("keydown", atajoEditor);
  cuadro = requestAnimationFrame(bucle);
  temporizador = setInterval(sondear, 1500);
  limpiarVista = () => {
    encolarPendiente();
    cancelado = true;
    cancelAnimationFrame(cuadro);
    window.removeEventListener("resize", alRedimensionar);
    document.removeEventListener("keydown", atajoEditor);
    video.pause();
    video.removeAttribute("src");
    video.load();
    juego.pause();
    juego.removeAttribute("src");
    juego.load();
    juegoWeb.removeAttribute("src");
  };
}

estadoSistema();
iniciarActualizaciones({ h, api, avisar });
navegar();
