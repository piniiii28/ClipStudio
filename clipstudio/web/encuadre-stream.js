// Las mismas regiones se usan en el directo, el editor y el render de FFmpeg.
export function crearSelectorStream({ h, fuente, composicion, alCambiar, alAutomatico, textoAutomatico = "Cámara automática" }) {
  let config = {};
  let destino = "camara";
  let arrastre = null;
  const modo = h("select", { "aria-label": "Composición del stream" },
    h("option", { value: "mixto" }, "Cámara arriba + gameplay abajo"),
    h("option", { value: "gameplay" }, "Gameplay completo"),
    h("option", { value: "camara" }, "Solo cámara"));
  const proporcion = h("input", { type: "range", min: 20, max: 50, value: 30, "aria-label": "Altura de la cámara" });
  const valor = h("span", {}, "30 %");
  const ayuda = h("p", { class: "tenue pequeno" });
  const camara = h("div", { class: "region-stream region-camara", hidden: true }, h("span", {}, "Cámara"));
  const juego = h("div", { class: "region-stream region-juego" }, h("span", {}, "Juego"));
  const marco = h("div", { class: "selector-stream", "aria-label": "Seleccionar zonas del stream" }, fuente, juego, camara);
  const emitir = () => alCambiar(structuredClone(config));
  function dibujar(region, caja) {
    caja.hidden = !region;
    if (region) caja.style.cssText = `left:${region.x * 100}%;top:${region.y * 100}%;width:${region.ancho * 100}%;height:${region.alto * 100}%`;
  }
  function pintar() {
    dibujar(config.camara, camara);
    dibujar(config.juego, juego);
    modo.value = config.modo;
    proporcion.value = config.camara_porcentaje;
    valor.textContent = `${config.camara_porcentaje} %`;
    ayuda.textContent = config.camara
      ? "Puedes volver a marcar las zonas cuando cambie la distribución del directo."
      : "Cámara sin definir. Se muestra el gameplay completo hasta detectar o seleccionar la cámara.";
  }
  function actualizar(nueva) {
    config = { modo: "mixto", camara: null, juego: { x: 0, y: 0, ancho: 1, alto: 1 }, camara_porcentaje: 30, ...structuredClone(nueva || {}) };
    pintar();
  }
  modo.addEventListener("change", () => { config.modo = modo.value; emitir(); });
  proporcion.addEventListener("input", () => { config.camara_porcentaje = Number(proporcion.value); valor.textContent = `${proporcion.value} %`; emitir(); });
  function elegir(nombre) {
    destino = nombre;
    ayuda.textContent = `Arrastra sobre la imagen para marcar ${nombre === "camara" ? "la cámara del creador" : "el gameplay"}.`;
  }
  function punto(evento) {
    const caja = marco.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (evento.clientX - caja.left) / caja.width)),
      y: Math.max(0, Math.min(1, (evento.clientY - caja.top) / caja.height)) };
  }
  function region(evento) {
    const fin = punto(evento);
    return { x: Math.min(arrastre.x, fin.x), y: Math.min(arrastre.y, fin.y),
      ancho: Math.abs(fin.x - arrastre.x), alto: Math.abs(fin.y - arrastre.y) };
  }
  marco.addEventListener("pointerdown", (evento) => {
    if (evento.button !== 0 || marco.clientHeight < 10) return;
    evento.preventDefault();
    marco.setPointerCapture(evento.pointerId);
    arrastre = punto(evento);
  });
  marco.addEventListener("pointermove", (evento) => {
    if (arrastre) dibujar(region(evento), destino === "camara" ? camara : juego);
  });
  marco.addEventListener("pointerup", (evento) => {
    if (!arrastre) return;
    const nueva = region(evento);
    arrastre = null;
    if (nueva.ancho < .02 || nueva.alto < .02) { pintar(); return; }
    config[destino] = nueva;
    pintar(); emitir();
  });
  marco.addEventListener("pointercancel", () => { arrastre = null; pintar(); });
  const elemento = h("div", { class: "encuadre-stream" },
    h("div", { class: "campo" }, h("label", {}, "Composición de los clips"), modo),
    h("div", { class: "fila" },
      h("button", { type: "button", onclick: () => elegir("camara") }, "Marcar cámara"),
      h("button", { type: "button", onclick: () => elegir("juego") }, "Marcar gameplay"),
      h("button", { type: "button", onclick: async () => {
        if (alAutomatico) await alAutomatico();
        else { config.camara = null; pintar(); emitir(); }
      } }, textoAutomatico),
      h("button", { type: "button", onclick: () => { config.juego = { x: 0, y: 0, ancho: 1, alto: 1 }; pintar(); emitir(); } }, "Juego completo")),
    ayuda, marco,
    h("label", { class: "campo" }, "Altura de la cámara ", valor, proporcion));
  actualizar(composicion);
  return { elemento, actualizar, configuracion: () => structuredClone(config) };
}

export function dibujarStream(canvas, fuente, composicion) {
  if (!fuente.videoWidth || fuente.readyState < 2) return;
  const c = { modo: "mixto", camara: null, juego: { x: 0, y: 0, ancho: 1, alto: 1 }, camara_porcentaje: 30, ...composicion };
  const g = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
  function dibujar(region, y, alto, ajustar = false, alineacion = .5) {
    const sx = region.x * fuente.videoWidth, sy = region.y * fuente.videoHeight;
    const sw = region.ancho * fuente.videoWidth, sh = region.alto * fuente.videoHeight;
    const escala = ajustar ? Math.min(w / sw, alto / sh) : Math.max(w / sw, alto / sh);
    const anchoDibujo = sw * escala, altoDibujo = sh * escala;
    g.save();
    g.beginPath(); g.rect(0, y, w, alto); g.clip();
    g.drawImage(fuente, sx, sy, sw, sh, (w - anchoDibujo) / 2, y + (alto - altoDibujo) * alineacion, anchoDibujo, altoDibujo);
    g.restore();
  }
  g.clearRect(0, 0, w, h);
  if (c.modo === "camara" && c.camara) { dibujar(c.camara, 0, h, false, .25); return; }
  const altura = c.modo === "mixto" && c.camara ? Math.floor(h * c.camara_porcentaje / 100) : 0;
  if (altura) dibujar(c.camara, 0, altura, false, .25);
  g.save();
  g.filter = `blur(${24 * w / 1080}px)`;
  dibujar(c.juego, altura, h - altura);
  g.restore();
  dibujar(c.juego, altura, h - altura, true);
}
