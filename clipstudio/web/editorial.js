// Ayudas locales del editor. Las decisiones se aplican al elegir una propuesta.
export function crearAyudasEditoriales({ h, api, avisar, getClip, pid, video, vaciar, guardar, repintar, crearClip }) {
  const modos = [["mixto", "Cámara y gameplay"], ["camara", "Solo cámara"], ["gameplay", "Gameplay completo"]];
  const selectorModo = () => h("select", { "aria-label": "Composición del intervalo" }, modos.map(([value, texto]) => h("option", { value }, texto)));
  function consulta(texto, ruta, mostrar) {
    const salida = h("div", { class: "resultados-editoriales", role: "status" });
    const boton = h("button", { onclick: async () => {
      const id = getClip()?.id;
      if (!id || !(await vaciar())) return;
      boton.disabled = true;
      try {
        const datos = await api("GET", `/clips/${id}/${ruta}`);
        if (getClip()?.id === id) mostrar(salida, datos);
      } catch (e) { avisar(e.message, "error"); }
      finally { boton.disabled = false; }
    } }, texto);
    return h("div", { class: "ayuda-editorial" }, boton, salida);
  }
  function titulos() {
    return consulta("Sugerir títulos", "titulos", (salida, datos) => {
      salida.replaceChildren(h("p", { class: "tenue pequeno" }, datos.sugerencias.length ? "Propuestas extraídas de los subtítulos conservados" : "Añade subtítulos o una transcripción para obtener títulos."),
        ...datos.sugerencias.map(s => h("button", { class: "propuesta-titulo", onclick: () => { guardar({ titulo: s.titulo }); repintar(); } }, s.titulo)));
    });
  }
  function revision() {
    return consulta("Revisar legibilidad", "subtitulos/revision", (salida, datos) => {
      salida.replaceChildren(h("p", { class: "tenue pequeno" }, datos.avisos.length ? `${datos.avisos.length} avisos. El ancho es una estimación.` : "Sin avisos de legibilidad."),
        ...datos.avisos.map(a => h("button", { class: "aviso-subtitulo", onclick: () => { video.pause(); video.currentTime = a.inicio; } }, `Subtítulo ${a.indice + 1} · ${a.motivo}`)));
    });
  }
  function tema(duraciones) {
    const entrada = h("input", { placeholder: "Tema o palabras", maxLength: 150, "aria-label": "Tema para buscar clips" });
    const salida = h("div", { class: "resultados-editoriales", role: "status" });
    const boton = h("button", { onclick: async () => {
      if (entrada.value.trim().length < 2) return avisar("Escribe al menos dos caracteres para buscar.", "error");
      boton.disabled = true;
      try {
        const datos = await api("POST", `/proyectos/${pid}/buscar-tema`, { tema: entrada.value.trim(), ...duraciones() });
        salida.replaceChildren(h("p", { class: "tenue pequeno" }, datos.candidatos.length ? "Coincidencias de palabras en la transcripción" : "Sin coincidencias para este tema."),
          ...datos.candidatos.map(c => h("div", { class: "candidato-tema" }, h("p", {}, c.evidencia), h("button", { onclick: async (e) => {
            e.currentTarget.disabled = true;
            try {
              const nuevo = await api("POST", `/proyectos/${pid}/clips`, { inicio: c.inicio, fin: c.fin, titulo: c.titulo });
              crearClip(nuevo);
            } catch (error) { avisar(error.message, "error"); e.currentTarget.disabled = false; }
          } }, `Crear clip · ${Math.round(c.fin - c.inicio)} s`))));
      } catch (e) { avisar(e.message, "error"); }
      finally { boton.disabled = false; }
    } }, "Buscar por tema");
    return h("div", { class: "ayuda-editorial" }, entrada, boton, salida);
  }
  function intervalos() {
    const clip = getClip();
    const tramos = clip.composicion?.tramos || [];
    const inicio = h("input", { type: "number", step: .1, min: clip.inicio, max: clip.fin, value: Math.max(clip.inicio, Math.min(video.currentTime, clip.fin - .1)).toFixed(1), "aria-label": "Inicio del intervalo en segundos de la fuente" });
    const fin = h("input", { type: "number", step: .1, min: clip.inicio, max: clip.fin, value: clip.fin, "aria-label": "Fin del intervalo en segundos de la fuente" });
    const modo = selectorModo();
    function aplicar(lista) { guardar({ composicion: { ...clip.composicion, tramos: lista } }); repintar(); }
    const agregar = h("button", { onclick: () => {
      const a = Number(inicio.value), b = Number(fin.value);
      if (!(a >= clip.inicio && b <= clip.fin && b > a)) return avisar("El intervalo debe quedar dentro del clip.", "error");
      if (tramos.some(t => a < t.fin && b > t.inicio)) return avisar("Los intervalos no pueden solaparse.", "error");
      if (tramos.length >= 100) return avisar("Admite hasta 100 intervalos por clip.", "error");
      aplicar([...tramos, { inicio: a, fin: b, modo: modo.value }].sort((a, b) => a.inicio - b.inicio));
    } }, "Añadir intervalo");
    return h("details", { class: "intervalos-stream" }, h("summary", {}, "Composición por intervalos"),
      h("p", { class: "tenue pequeno" }, "Tiempos en segundos del video fuente. Fuera de estos intervalos se usa la composición general."),
      h("label", {}, "Inicio", inicio), h("label", {}, "Fin", fin), modo, agregar,
      ...tramos.map((t, i) => h("div", { class: "fila" }, `${t.inicio.toFixed(1)}–${t.fin.toFixed(1)} s · ${modos.find(m => m[0] === t.modo)[1]}`,
        h("button", { class: "mini", onclick: () => aplicar(tramos.filter((_, n) => n !== i)) }, "Quitar intervalo"))));
  }
  return { titulos, revision, tema, intervalos };
}
