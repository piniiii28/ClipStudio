// ClipStudio - pantalla «Ajustes». El servidor aporta las rutas y las valida.
export async function vistaAjustes({ h, api, avisar, intentar, vista, vigente }) {
  const NOMBRES = {
    exportaciones: ["Exportaciones", "Dónde se guardan los MP4 terminados."],
    vivo: ["Búfer de directos", "Grabación temporal de los directos; puedes usar otro disco."],
    fondos: ["Fondos", "Videos de fondo para la pantalla dividida."],
  };
  const contenido = h("div", { class: "ajustes-contenido" });
  const estado = h("p", { class: "tenue", role: "status" }, "Cargando carpetas…");
  vista.append(h("header", { class: "ajustes-cabecera" }, h("h1", {}, "Ajustes"),
    h("p", { class: "tenue" }, "Elige dónde guardar tus videos y archivos temporales.")), estado, contenido);

  function espacio(datos) {
    return h("p", { class: "tenue pequeno" }, datos.libre_gb == null
      ? "Espacio libre no disponible." : `${datos.libre_gb.toLocaleString("es")} GB libres`);
  }

  function mostrar(datos) {
    if (!vigente()) return;
    estado.hidden = true;
    contenido.replaceChildren(h("section", { "aria-labelledby": "ajustes-carpetas" },
      h("h2", { id: "ajustes-carpetas", class: "titulo-lista" }, "Carpetas"),
      h("div", { class: "ajustes-carpetas" }, datos.carpetas.map(tarjeta))));
    const datosApp = datos.datos;
    contenido.append(h("section", { class: "panel ajustes-datos", "aria-labelledby": "ajustes-datos" },
      h("h2", { id: "ajustes-datos" }, "Datos de la aplicación"),
      h("p", { class: "tenue" }, "Los proyectos, las transcripciones y los modelos se guardan en la carpeta de datos de la aplicación. Esta carpeta no se puede cambiar desde aquí."),
      h("p", { class: "ajustes-ruta" }, datosApp.ruta), espacio(datosApp),
      h("button", { onclick: () => intentar(() => api("POST", "/ajustes/abrir/datos")) }, "Abrir")));
    if (datos.aviso) estadoAviso(datos.aviso);
  }

  function estadoAviso(texto) {
    estado.textContent = texto;
    estado.hidden = false;
    avisar(texto);
  }

  function tarjeta(carpeta) {
    const [nombre, descripcion] = NOMBRES[carpeta.clave] || [carpeta.etiqueta, ""];
    const error = h("p", { class: "mensaje-error pequeno", role: "alert", hidden: true });
    const entrada = h("input", { type: "text", value: carpeta.ruta, "aria-label": `Ruta de ${nombre}`, spellcheck: false });
    const formulario = h("form", { class: "ajustes-editar", hidden: true,
      onsubmit: (evento) => { evento.preventDefault(); ejecutar("PUT", { ruta: entrada.value }); } },
      h("label", {}, "Pega la ruta completa de la carpeta", entrada),
      h("div", { class: "fila" }, h("button", { type: "submit", class: "primario" }, "Guardar"),
        h("button", { type: "button", onclick: () => { formulario.hidden = true; elegir.focus(); } }, "Cancelar")));
    const elegir = h("button", { class: "primario", onclick: async () => {
      const selector = window.pywebview?.api?.elegir_carpeta;
      if (typeof selector !== "function") {
        formulario.hidden = false;
        entrada.focus();
        entrada.select();
        return;
      }
      await actuar(async () => {
        const ruta = await window.pywebview.api.elegir_carpeta(`Elegir carpeta: ${nombre}`);
        if (ruta != null) mostrar(await api("PUT", `/ajustes/carpetas/${carpeta.clave}`, { ruta }));
      });
    } }, "Elegir carpeta…");
    const panel = h("article", { class: "panel ajustes-carpeta", "data-carpeta": carpeta.clave },
      h("div", { class: "fila" }, h("h3", {}, nombre),
        !carpeta.personalizada ? h("span", { class: "etiqueta" }, "Predeterminada") : null),
      h("p", { class: "tenue" }, descripcion), h("p", { class: "ajustes-ruta" }, carpeta.ruta), espacio(carpeta),
      carpeta.aviso ? h("p", { class: "tenue pequeno" }, carpeta.aviso) : null,
      h("div", { class: "fila" }, elegir,
        h("button", { onclick: () => actuar(() => api("POST", `/ajustes/abrir/${carpeta.clave}`)) }, "Abrir"),
        carpeta.personalizada ? h("button", { onclick: () => ejecutar("DELETE") }, "Restablecer") : null),
      formulario, error);

    async function actuar(accion) {
      const botones = panel.querySelectorAll("button");
      botones.forEach((boton) => { boton.disabled = true; });
      error.hidden = true;
      try { await accion(); }
      catch (e) {
        if (vigente()) { error.textContent = e.message; error.hidden = false; avisar(e.message, "error"); }
      } finally { botones.forEach((boton) => { boton.disabled = false; }); }
    }

    function ejecutar(metodo, cuerpo) {
      return actuar(async () => mostrar(await api(metodo, `/ajustes/carpetas/${carpeta.clave}`, cuerpo)));
    }
    return panel;
  }

  const datos = await intentar(() => api("GET", "/ajustes"));
  if (!vigente()) return;
  if (datos) mostrar(datos);
  else {
    estado.textContent = "No se pudieron cargar las carpetas.";
    contenido.append(h("button", { onclick: async () => {
      const nuevos = await intentar(() => api("GET", "/ajustes"));
      if (nuevos) mostrar(nuevos);
    } }, "Reintentar"));
  }
}
