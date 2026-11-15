// Controles de salida compartidos por exportacion individual y por lotes.
export function crearEntrega({ h, api, clip, video, vaciar, avisar, vigente }) {
  let preferencias = {};
  try { preferencias = JSON.parse(localStorage.getItem("clipstudio.entrega") || "{}"); } catch { /* usar valores iniciales */ }
  const perfil = h("select", { "aria-label": "Perfil de exportación" },
    h("option", { value: "social" }, "Social · 1080p"),
    h("option", { value: "calidad" }, "Máxima calidad · 1080p"),
    h("option", { value: "borrador" }, "Borrador · 720p"));
  perfil.value = ["social", "calidad", "borrador"].includes(preferencias.perfil) ? preferencias.perfil : "social";
  const normalizar = h("input", { type: "checkbox", checked: preferencias.normalizar_audio === true });
  const opciones = () => ({ perfil: perfil.value, normalizar_audio: normalizar.checked });
  const recordar = () => { try { localStorage.setItem("clipstudio.entrega", JSON.stringify(opciones())); } catch { /* almacenamiento lleno */ } };
  perfil.addEventListener("change", recordar);
  normalizar.addEventListener("change", recordar);
  const revision = h("div", { class: "revision-salida", role: "status" });
  const revisar = h("button", { disabled: !clip, onclick: async () => {
    revisar.disabled = true;
    try {
      if (!(await vaciar())) return avisar("Guarda los cambios pendientes antes de revisar.", "error");
      const r = await api("GET", `/clips/${clip.id}/revision?perfil=${perfil.value}`);
      if (!vigente() || !revision.isConnected) return;
      revision.replaceChildren(h("strong", {}, `${r.salida.ancho} × ${r.salida.alto} · ${r.duracion.toFixed(1)} s`),
        h("p", { class: "tenue pequeno" }, `Fuente ${r.fuente.ancho} × ${r.fuente.alto} · ${r.subtitulos} subtítulos · ${r.cortes} cortes`),
        ...r.avisos.map(a => h("p", { class: "aviso-calidad" }, a)),
        !r.avisos.length ? h("p", { class: "tenue pequeno" }, "Fuente y parámetros listos para exportar.") : null);
    } catch (e) { avisar(e.message, "error"); }
    finally { revisar.disabled = !clip; }
  } }, "Revisar antes de exportar");
  perfil.addEventListener("change", () => revision.replaceChildren());
  const imagen = h("img", { class: "portada-preview", hidden: true, alt: "Portada vertical con el fotograma completo" });
  const descargar = h("a", { class: "boton", hidden: true, download: "portada.jpg" }, "Descargar portada JPG");
  const nota = h("p", { class: "tenue pequeno", role: "status" });
  const portada = h("button", { disabled: !clip, onclick: async () => {
    portada.disabled = true;
    nota.textContent = "Preparando fotograma…";
    try {
      if (!(await vaciar())) throw new Error("Guarda los cambios pendientes antes de preparar la portada.");
      const momento = video.currentTime;
      const ruta = `/api/clips/${clip.id}/portada.jpg?momento=${momento.toFixed(3)}`;
      const respuesta = await fetch(ruta);
      if (!respuesta.ok) {
        const e = await respuesta.json().catch(() => ({}));
        throw new Error(e.detail || "No se pudo generar la portada.");
      }
      if (!vigente() || !nota.isConnected) return;
      imagen.src = ruta; imagen.hidden = false;
      descargar.href = ruta + "&descargar=true"; descargar.hidden = false;
      nota.textContent = "720 × 1280 · Fotograma completo con fondo difuminado.";
    } catch (e) { nota.textContent = e.message; }
    finally { portada.disabled = !clip; }
  } }, "Usar fotograma actual");
  return { opciones, panel: h("div", { class: "entrega-panel" },
    h("h3", {}, "Calidad de salida"), h("label", {}, "Perfil", perfil),
    h("label", { class: "fila" }, normalizar, "Uniformar volumen de voz"),
    h("p", { class: "tenue pequeno" }, "La normalización ajusta el nivel del audio durante la exportación."), revisar, revision,
    h("details", { class: "portada-selector" }, h("summary", {}, "Portada vertical"),
      h("p", { class: "tenue pequeno" }, "Sitúa la reproducción en el fotograma que quieres usar."), portada, nota, imagen, descargar)) };
}

export function crearOnda({ h, clip, video }) {
  const posicion = h("input", { type: "range", min: clip.inicio, max: clip.fin, step: .01, value: clip.inicio,
    "aria-label": "Buscar en la forma de onda", class: "onda-posicion" });
  const imagen = h("img", { src: `/api/clips/${clip.id}/onda.png?v=${clip.inicio}-${clip.fin}`, alt: "Forma de onda del audio", loading: "lazy" });
  const estado = h("span", { class: "tenue pequeno" });
  imagen.addEventListener("error", () => { imagen.hidden = true; estado.textContent = "Forma de onda no disponible para este audio."; });
  posicion.addEventListener("input", () => { video.currentTime = Number(posicion.value); });
  const onda = h("div", { class: "onda-editor" }, imagen, posicion, estado);
  const actualizar = () => {
    if (!onda.isConnected) { video.removeEventListener("timeupdate", actualizar); return; }
    posicion.value = Math.min(clip.fin, Math.max(clip.inicio, video.currentTime));
  };
  video.addEventListener("timeupdate", actualizar);
  return onda;
}
