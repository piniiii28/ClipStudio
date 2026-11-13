// ClipStudio - pantalla «En vivo». Módulo independiente: app.js le pasa las utilidades.
// Todo el texto que viene del servidor se inserta con textContent (nunca innerHTML).
import { crearSelectorStream } from "./encuadre-stream.js";

function fmtReloj(s) {
  s = Math.max(0, Math.floor(Number(s) || 0));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hh ? `${hh}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;
}

const ETIQUETAS = { conectando: "CONECTANDO", grabando: "GRABANDO", detenido: "DETENIDO", error: "ERROR" };

export function vistaVivo(ctx) {
  const { h, api, avisar, intentar, vista, vigente, sondear, alLimpiar } = ctx;
  let sesion = null;
  let consultando = false;
  let ocupado = false;          // hay un clip en preparación: se desactivan los botones
  let claveMomentos = "";
  let ultimoClip = null;
  let selectorSesion = null;
  let versionVista = "";
  let cambiosEncuadre = false;

  // ---- sin sesión: formulario ----
  const url = h("input", {
    type: "url", class: "crece", "aria-label": "Enlace del directo",
    placeholder: "https://kick.com/canal · https://www.twitch.tv/canal · enlace de un directo de YouTube",
  });
  const botonConectar = h("button", { class: "primario", type: "submit" }, "Conectar");
  const usarChat = h("input", { type: "checkbox", checked: true });
  const automaticos = h("input", { type: "checkbox", checked: true });
  const desfase = h("input", { type: "number", min: 0, max: 30, step: 1, value: 3, "aria-label": "Retraso de reacción del chat en segundos" });
  const formulario = h("form", { class: "fila", onsubmit: async (e) => {
    e.preventDefault();
    if (!url.value.trim()) return;
    botonConectar.disabled = true;
    const s = await intentar(() => api("POST", "/vivo", {
      url: url.value.trim(), usar_chat: usarChat.checked, automaticos: automaticos.checked,
      desfase_chat_s: Number(desfase.value),
    }));
    botonConectar.disabled = false;
    if (s) { url.value = ""; sesion = s; pintar(); avisar("Conectando con el directo…"); }
  } }, url, botonConectar);
  const panelConectar = h("section", { class: "panel conectar-vivo" },
    h("h2", {}, "Conectar con un directo"), formulario,
    h("div", { class: "fila", style: "margin-top:12px" },
      h("label", {}, usarChat, " Leer chat (Twitch / YouTube / Kick)"),
      h("label", {}, automaticos, " Crear clips automáticamente por picos del chat"),
      h("label", {}, "Retraso de reacción del chat (s) ", desfase)),
    h("p", { class: "tenue pequeno", style: "margin-top:10px" },
      "Pega el enlace de un directo que esté en curso. ClipStudio lo graba en este equipo (solo se guarda la última hora), " +
      "detecta subidas de volumen y picos de actividad del chat. Los clips automáticos guardan 25 segundos anteriores y 10 posteriores al momento. " +
      "Graba solo directos propios o que tengas permiso para usar."));

  // ---- con sesión ----
  const etiqueta = h("span", { class: "etiqueta" });
  const tiempo = h("strong", { class: "reloj-vivo" });
  const titulo = h("span", { class: "tenue" });
  const bufer = h("p", { class: "tenue pequeno" });
  const mensaje = h("p", { class: "mensaje-error pequeno", hidden: true });
  const estadoChat = h("p", { class: "pequeno" });
  const errorChat = h("p", { class: "mensaje-error pequeno", hidden: true });
  const actividadChat = h("canvas", { class: "volumen-vivo", width: 720, height: 90, "aria-label": "Actividad del chat de los últimos 2 minutos" });
  const lienzo = h("canvas", { class: "volumen-vivo", width: 720, height: 90, "aria-label": "Volumen de los últimos 2 minutos" });
  const botonesUltimos = [30, 60, 90].map((n) =>
    h("button", { class: "primario", onclick: () => crearClip({ segundos: n }, `últimos ${n} s`) }, `Clip de los últimos ${n} s`));
  const nota = h("input", { maxLength: 160, placeholder: "Nota del momento (opcional)", "aria-label": "Nota del marcador" });
  const marcar = h("button", { onclick: async () => {
    if (!sesion || marcar.disabled) return;
    marcar.disabled = true;
    const r = await intentar(() => api("POST", `/vivo/${sesion.id}/momentos`, { nota: nota.value.trim() }));
    if (r && vigente()) { nota.value = ""; avisar("Momento marcado sobre el último vídeo grabado."); }
    if (vigente()) { await consultar(); pintar(); }
  } }, "Marcar momento");
  const filtroMomentos = h("select", { "aria-label": "Filtrar momentos", onchange: () => { claveMomentos = ""; pintarMomentos(); } },
    ...[["todos", "Todos"], ["pendientes", "Pendientes"], ["manual", "Manuales"], ["chat", "Chat"], ["audio", "Audio"]].map(([value, label]) => h("option", { value }, label)));
  const listaMomentos = h("div", { class: "lista-momentos" });
  const enlaceClip = h("p", { class: "pequeno", hidden: true });
  const botonParar = h("button", { class: "peligro", onclick: parar }, "Parar");
  const imagen = h("img", { alt: "Imagen reciente del directo grabado", draggable: false, hidden: true });
  const esperaImagen = h("p", { class: "tenue pequeno" }, "Esperando el primer segmento de video…");
  const estadoEncuadre = h("span", { class: "tenue pequeno", role: "status" });
  const aplicarEncuadre = h("button", { type: "button", class: "primario", disabled: true, onclick: async () => {
    if (!sesion) return;
    const id = sesion.id;
    aplicarEncuadre.disabled = true;
    selector.elemento.inert = true;
    const r = await intentar(() => api("PUT", `/vivo/${id}/encuadre`, { composicion: selector.configuracion() }));
    if (!vigente() || sesion?.id !== id) return;
    selector.elemento.inert = false;
    if (r) { sesion = r; cambiosEncuadre = false; estadoEncuadre.textContent = "Se aplicará a los próximos clips."; }
    else { aplicarEncuadre.disabled = false; estadoEncuadre.textContent = "Cambios sin guardar."; }
  } }, "Aplicar a los próximos clips");
  const selector = crearSelectorStream({ h, fuente: imagen, textoAutomatico: "Detectar cámara en los clips",
    alCambiar: () => { cambiosEncuadre = true; aplicarEncuadre.disabled = false; estadoEncuadre.textContent = "Cambios sin aplicar."; } });

  const panelVivo = h("div", { class: "cuadricula-vivo", hidden: true },
    h("section", { class: "panel" },
      h("div", { class: "fila" }, etiqueta, tiempo, titulo, h("span", { class: "crece" }), botonParar),
      bufer, mensaje,
      h("h3", { style: "margin-top:14px" }, "Volumen (últimos 2 minutos)"), lienzo,
      h("div", { class: "fila", style: "margin-top:14px" }, botonesUltimos),
      enlaceClip),
    h("section", { class: "panel" },
      h("h2", {}, "Vista del directo y encuadre"),
      h("p", { class: "tenue pequeno" }, "La imagen se actualiza con los segmentos grabados y lleva unos segundos de retraso."),
      esperaImagen, selector.elemento,
      h("div", { class: "fila", style: "margin-top:12px" }, aplicarEncuadre, estadoEncuadre)),
    h("section", { class: "panel" },
      h("h2", {}, "Momentos"),
      h("div", { class: "fila" }, nota, marcar, filtroMomentos),
      h("p", { class: "tenue pequeno" }, "Se marcan subidas de volumen y aumentos de actividad del chat respecto al minuto anterior."),
      listaMomentos),
    h("section", { class: "panel" },
      h("h3", {}, "Señales del chat"),
      estadoChat, errorChat, actividadChat));

  vista.append(
    h("header", { class: "portada portada-vivo" },
      h("h1", {}, "En vivo"),
      h("p", { class: "tenue" }, "Graba un directo, sigue la actividad del chat y envía los mejores momentos a Proyectos.")),
    panelConectar, panelVivo);

  async function crearClip(cuerpo, descripcion) {
    if (!sesion || ocupado) return;
    ocupado = true;
    pintar();
    avisar(`Preparando el clip (${descripcion})…`);
    const r = await intentar(() => api("POST", `/vivo/${sesion.id}/clip`, cuerpo));
    ocupado = false;
    if (r && vigente()) {
      ultimoClip = r;
      avisar("Clip creado. Ya está en la cola de Proyectos.");
    }
    if (vigente()) { await consultar(); pintar(); }
  }

  async function parar() {
    if (!sesion) return;
    if (!confirm("¿Parar la grabación? Se borrará el búfer y ya no podrás sacar clips de este directo.")) return;
    const id = sesion.id;
    await intentar(() => api("POST", `/vivo/${id}/parar`));
    sesion = null; ultimoClip = null;
    if (vigente()) { pintar(); avisar("Grabación detenida."); }
  }

  function dibujar() {
    const datos = (sesion && sesion.volumen) || [];
    const g = lienzo.getContext("2d");
    const css = getComputedStyle(document.documentElement);
    const color = (n, defecto) => css.getPropertyValue(n).trim() || defecto;
    g.clearRect(0, 0, lienzo.width, lienzo.height);
    g.fillStyle = color("--panel-2", "#1f232c");
    g.fillRect(0, 0, lienzo.width, lienzo.height);
    const ancho = lienzo.width / 120;
    const momentos = new Set((sesion.momentos || []).map((m) => Math.floor(m.tiempo)));
    const primero = (sesion.segundos || datos.length) - datos.length;
    datos.forEach((db, i) => {
      const alto = Math.max(1, ((Math.max(-80, Math.min(0, db)) + 80) / 80) * lienzo.height);
      g.fillStyle = momentos.has(primero + i) ? color("--error", "#f27272") : color("--acento", "#f5b83d");
      // El volumen más reciente queda a la derecha.
      g.fillRect((120 - datos.length + i) * ancho, lienzo.height - alto, Math.max(1, ancho - 1), alto);
    });
  }

  function pintarMomentos() {
    const momentos = [...(sesion.momentos || [])].reverse().filter((m) =>
      filtroMomentos.value === "todos" || (filtroMomentos.value === "pendientes"
        ? !m.proyecto_id && !m.caducado : m.origen === filtroMomentos.value));
    const clave = momentos.map((m) => m.id + m.estado + m.caducado).join() + "|" + ocupado;
    if (clave === claveMomentos) return;
    claveMomentos = clave;
    listaMomentos.replaceChildren(...(momentos.length ? momentos.map((m) =>
      h("div", { class: "momento" },
        h("strong", { class: "tiempo-momento" }, fmtReloj(m.tiempo)),
        h("span", { class: "crece" }, m.motivo),
        m.error ? h("span", { class: "mensaje-error pequeno" }, m.error) : null,
        m.estado === "convertido" ? h("a", { href: `#/p/${m.proyecto_id}` }, "Abrir clip") :
          ["esperando_video", "creando"].includes(m.estado)
            ? h("span", { class: "etiqueta" }, m.estado === "creando" ? "Creando clip…" : "Esperando vídeo…")
            : m.caducado ? h("span", { class: "etiqueta" }, "Fuera del búfer")
            : h("button", { disabled: ocupado, onclick: () => crearClip({ momento_id: m.id }, `momento ${fmtReloj(m.tiempo)}`) }, "Crear clip")))
      : [h("p", { class: "tenue" }, "Todavía no se ha detectado ningún momento.")]));
  }

  function pintar() {
    const hay = !!sesion;
    panelConectar.hidden = hay;
    panelVivo.hidden = !hay;
    if (!hay) { claveMomentos = ""; return; }
    if (selectorSesion !== sesion.id) {
      selectorSesion = sesion.id;
      selector.actualizar(sesion.composicion);
      selector.elemento.inert = false;
      cambiosEncuadre = false;
      aplicarEncuadre.disabled = true;
      estadoEncuadre.textContent = "";
      versionVista = "";
      imagen.hidden = true;
      esperaImagen.hidden = false;
    } else if (!cambiosEncuadre && JSON.stringify(selector.configuracion()) !== JSON.stringify(sesion.composicion || {})) {
      selector.actualizar(sesion.composicion);
    }
    if (sesion.vista_version && versionVista !== `${sesion.id}-${sesion.vista_version}`) {
      versionVista = `${sesion.id}-${sesion.vista_version}`;
      imagen.src = `/api/vivo/${sesion.id}/vista.jpg?v=${sesion.vista_version}`;
      imagen.hidden = false;
      esperaImagen.hidden = true;
    }
    if (!sesion.vista_version) {
      esperaImagen.textContent = "vista_version" in sesion
        ? "Esperando el primer segmento de video…"
        : "Reinicia ClipStudio cerrando su ventana de inicio y vuelve a abrirlo para activar la vista del directo.";
    }
    etiqueta.textContent = ETIQUETAS[sesion.estado] || sesion.estado;
    etiqueta.className = "etiqueta vivo-" + sesion.estado;
    tiempo.textContent = fmtReloj(sesion.segundos);
    titulo.textContent = sesion.titulo || "";
    const partes = [`Búfer en disco: ${sesion.tamano_mb} MB`];
    if (sesion.estimado_buffer_gb) partes.push(`el búfer de ${sesion.buffer_min} min usará aprox. ${sesion.estimado_buffer_gb} GB`);
    bufer.textContent = partes.join(" · ");
    mensaje.hidden = !sesion.error;
    mensaje.textContent = sesion.error || "";
    const estadosChat = { conectando: "Conectando", conectado: "Conectado", reconectando: "Reconectando", desactivado: "Desactivado", detenido: "Detenido", error: "Error" };
    const actividad = sesion.chat_actividad || [];
    estadoChat.textContent = `Chat · ${estadosChat[sesion.chat_estado] || "Desactivado"} · ${actividad.at(-1) || 0} mensajes/s` +
      (sesion.automaticos ? " · Clips automáticos activados" : " · Creación manual de clips");
    errorChat.hidden = !sesion.chat_error;
    errorChat.textContent = sesion.chat_error || "";
    const g = actividadChat.getContext("2d");
    g.clearRect(0, 0, actividadChat.width, actividadChat.height);
    g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--acento").trim() || "#f5b83d";
    const maximo = Math.max(5, ...actividad);
    actividad.forEach((n, i) => {
      const alto = n / maximo * actividadChat.height;
      g.fillRect((120 - actividad.length + i) * 6, actividadChat.height - alto, 5, alto);
    });
    const puede = !ocupado && sesion.cobertura_s >= 5;
    marcar.disabled = sesion.estado !== "grabando" || !sesion.n_segmentos;
    botonesUltimos.forEach((b, i) => {
      b.disabled = !puede;
      const pedido = [30, 60, 90][i];
      const disponibles = Math.floor(Math.max(0, sesion.cobertura_s - (sesion.buffer_inicio_s || 0)));
      b.textContent = disponibles < pedido ? `Clip de ${disponibles} s disponibles (máx. ${pedido} s)` : `Clip de los últimos ${pedido} s`;
    });
    enlaceClip.hidden = !ultimoClip;
    if (ultimoClip) {
      enlaceClip.replaceChildren(`Clip creado: «${ultimoClip.nombre}». `, h("a", { href: `#/p/${ultimoClip.proyecto_id}` }, "Abrir clip"));
    }
    pintarMomentos();
    dibujar();
  }

  async function consultar() {
    if (consultando) return;
    consultando = true;
    try {
      const s = await api("GET", "/vivo");
      if (!vigente()) return;
      sesion = s;
      pintar();
    } catch { /* un fallo puntual de red no debe llenar la pantalla de avisos */ }
    finally { consultando = false; }
  }

  consultar();
  sondear(consultar, 1500);
  alLimpiar(() => { /* navegar fuera no para la grabación: sigue en segundo plano */ });
}
