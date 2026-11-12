// ClipStudio - aviso de actualizaciones en la barra superior. Módulo independiente: app.js le pasa las utilidades.
// Todo el texto que viene del servidor (incluidas las notas de la versión) se inserta con textContent, nunca innerHTML.

const PREFIJO_ENLACE = "https://github.com/piniiii28/ClipStudio/";
const MODOS = { instalada: "Aplicación instalada", git: "Copia del código (git)", zip: "Copia del código sin git" };

function mb(n) { return (n / 1024 / 1024).toFixed(1) + " MB"; }

export function iniciarActualizaciones({ h, api, avisar }) {
  const sitio = document.getElementById("estado-sistema");
  if (!sitio) return;
  let e = null;               // último estado recibido de /api/actualizaciones
  let abierto = false;
  let ocupado = false;        // hay una petición de la persona en curso
  let tras = "";              // mensaje de la última acción manual (buscar, actualizar código)
  let sondeo = null;
  let resultadoCodigo = null; // respuesta de «Actualizar» en modo git

  const boton = h("button", { class: "mini actualizacion-boton", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false", onclick: alternar }, "Actualizaciones");
  const panel = h("div", { class: "actualizacion-panel", role: "dialog", "aria-label": "Actualizaciones", hidden: true });
  const caja = h("div", { class: "actualizacion" }, boton, panel);
  sitio.after(caja);

  function alternar() {
    abierto = !abierto;
    panel.hidden = !abierto;
    boton.setAttribute("aria-expanded", String(abierto));
    if (abierto) pintar();
  }
  document.addEventListener("click", (ev) => { if (abierto && !ev.composedPath().includes(caja)) alternar(); });
  document.addEventListener("keydown", (ev) => { if (abierto && ev.key === "Escape") { alternar(); boton.focus(); } });

  function enlace(url, texto) {
    const valido = typeof url === "string" && url.startsWith(PREFIJO_ENLACE);
    return h("a", { href: valido ? url : PREFIJO_ENLACE + "releases", target: "_blank", rel: "noopener noreferrer" }, texto);
  }

  async function cargar() {
    try { e = await api("GET", "/actualizaciones"); } catch { return; }   // sin avisos: la comprobación es discreta
    const r = e.resultado;
    const hay = !!(r && r.hay_actualizacion);
    boton.textContent = hay ? `Versión ${r.version_nueva || "nueva"} disponible` : "Actualizaciones";
    boton.classList.toggle("hay", hay);
    pintar();
    programarSondeo();
  }

  // Mientras se comprueba o se descarga se vuelve a preguntar; después, nada.
  function programarSondeo() {
    clearTimeout(sondeo);
    const descargando = e && e.descarga && e.descarga.estado === "descargando";
    if (e && (e.comprobando || descargando)) sondeo = setTimeout(cargar, descargando ? 800 : 2000);
  }

  async function accion(fn) {
    if (ocupado) return;
    ocupado = true; pintar();
    try { await fn(); } catch (err) { avisar(err.message, "error"); }
    ocupado = false;
    await cargar();
  }

  const buscar = () => accion(async () => {
    resultadoCodigo = null;
    const nuevo = await api("POST", "/actualizaciones/buscar");
    tras = nuevo.error ? nuevo.error : "";
    if (!nuevo.error && !(nuevo.resultado && nuevo.resultado.hay_actualizacion)) {
      tras = nuevo.resultado && nuevo.resultado.sin_versiones ? "Todavía no hay versiones publicadas." : "ClipStudio está al día.";
    }
  });

  const descargar = () => accion(async () => { tras = ""; await api("POST", "/actualizaciones/descargar"); });

  const actualizarCodigo = () => accion(async () => {
    tras = "";
    resultadoCodigo = await api("POST", "/actualizaciones/actualizar-codigo");
  });

  async function instalar() {
    if (ocupado) return;
    const d = e && e.descarga;
    if (d && d.verificado === false &&
        !confirm("La publicación no incluye suma SHA-256, así que no se pudo verificar la integridad del instalador. ¿Instalar de todos modos?")) return;
    ocupado = true; pintar();
    try {
      let confirmado = false;
      for (let intento = 0; intento < 2; intento++) {
        let resp;
        try {
          resp = await fetch("/api/actualizaciones/instalar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmado }) });
        } catch { throw new Error("No se pudo conectar con ClipStudio."); }
        const datos = await resp.json().catch(() => null);
        if (resp.ok) { tras = (datos && datos.mensaje) || "Instalando…"; return; }
        if (resp.status === 409 && datos && datos.requiere_confirmacion && !confirmado) {
          if (!confirm(datos.detail)) return;   // avisa de grabación en vivo o trabajos activos
          confirmado = true;
          continue;
        }
        throw new Error(datos && typeof datos.detail === "string" ? datos.detail : `Error del servidor (${resp.status}).`);
      }
    } catch (err) { avisar(err.message, "error"); }
    finally { ocupado = false; pintar(); }
  }

  const preferencia = (activada) => accion(async () => { await api("PUT", "/actualizaciones/preferencia", { activada }); });

  function bloqueVersion(r) {
    const nodos = [h("h3", {}, `Versión ${r.version_nueva || "nueva"} disponible`)];
    if (r.notas) nodos.push(h("pre", { class: "notas-actualizacion" }, r.notas));   // texto plano
    if (r.modo === "instalada") nodos.push(...bloqueInstalada(r));
    else if (r.modo === "git") nodos.push(...bloqueGit());
    else nodos.push(h("p", { class: "tenue pequeno" }, "Esta copia no usa git. Descarga la versión nueva desde "), h("p", {}, enlace(r.url_pagina, "la página de versiones")));
    return nodos;
  }

  function bloqueInstalada(r) {
    const d = e.descarga || {};
    if (!r.instalador) return [h("p", { class: "tenue" }, "Esta versión todavía no tiene un instalador publicado."), h("p", {}, enlace(r.url_pagina, "Ver la página de versiones"))];
    if (d.estado === "descargando") {
      const pct = d.total ? Math.min(100, Math.round((d.recibido || 0) / d.total * 100)) : null;
      const barra = h("div", { class: "progreso" }, h("div", { style: `width:${pct ?? 5}%` }));
      return [h("p", { class: "pequeno" }, `Descargando… ${pct !== null ? pct + " % (" + mb(d.recibido || 0) + " de " + mb(d.total) + ")" : mb(d.recibido || 0)}`), barra];
    }
    if (d.estado === "lista") {
      return [
        h("p", { class: "pequeno " + (d.verificado ? "ok" : "advertencia") }, d.mensaje || ""),
        h("button", { class: "primario", type: "button", disabled: ocupado, onclick: instalar }, "Instalar y reiniciar"),
        h("p", { class: "tenue pequeno" }, "ClipStudio se cerrará, se instalará la versión nueva y volverá a abrirse. Tus proyectos se conservan."),
      ];
    }
    return [
      d.estado === "error" ? h("p", { class: "pequeno error-texto" }, d.mensaje || "No se pudo descargar.") : null,
      h("button", { class: "primario", type: "button", disabled: ocupado, onclick: descargar }, d.estado === "error" ? "Reintentar descarga" : "Descargar"),
      h("p", { class: "tenue pequeno" }, "No se instala nada hasta que pulses «Instalar y reiniciar»."),
    ];
  }

  function bloqueGit() {
    const nodos = [h("button", { class: "primario", type: "button", disabled: ocupado, onclick: actualizarCodigo }, "Actualizar")];
    if (!resultadoCodigo) {
      nodos.push(h("p", { class: "tenue pequeno" }, "Ejecuta «git pull --ff-only» y «uv sync». Solo si no hay cambios sin guardar en git."));
      return nodos;
    }
    nodos.push(h("p", { class: "pequeno " + (resultadoCodigo.ok ? "ok" : "advertencia") }, resultadoCodigo.mensaje));
    if (resultadoCodigo.comandos && resultadoCodigo.comandos.length) {
      nodos.push(h("pre", { class: "notas-actualizacion" }, resultadoCodigo.comandos.join("\n")));
    }
    return nodos;
  }

  function pintar() {
    if (!abierto || !e) return;
    const r = e.resultado;
    const nodos = [
      h("h2", {}, "Actualizaciones"),
      h("p", { class: "tenue pequeno" }, `Versión instalada: ${e.version_actual} · ${MODOS[e.modo] || e.modo}`),
    ];
    if (r && r.hay_actualizacion) nodos.push(...bloqueVersion(r));
    else if (!tras) nodos.push(h("p", { class: "pequeno" }, e.comprobando ? "Buscando…" : r ? (r.sin_versiones ? "Todavía no hay versiones publicadas." : "ClipStudio está al día.") : "Aún no se ha buscado."));
    if (tras) nodos.push(h("p", { class: "pequeno " + (e.error ? "error-texto" : "") }, tras));
    if (e.ultima_consulta) nodos.push(h("p", { class: "tenue pequeno" }, "Última búsqueda: " + new Date(e.ultima_consulta * 1000).toLocaleString("es")));
    const casilla = h("input", { type: "checkbox", checked: e.activada, disabled: e.desactivada_por_entorno || ocupado, onchange: (ev) => preferencia(ev.target.checked) });
    nodos.push(
      h("div", { class: "fila-actualizacion" },
        h("label", {}, casilla, " Buscar actualizaciones al iniciar"),
        h("button", { class: "mini", type: "button", disabled: ocupado || e.comprobando, onclick: buscar }, ocupado || e.comprobando ? "Buscando…" : "Buscar ahora")),
      e.desactivada_por_entorno ? h("p", { class: "tenue pequeno" }, "Desactivado por CLIPSTUDIO_BUSCAR_ACTUALIZACIONES=0.") : null,
      h("p", { class: "tenue pequeno" }, "Solo se consulta api.github.com, sin datos personales. Nada se descarga ni instala sin tu clic."),
    );
    panel.replaceChildren(...nodos.flat().filter(Boolean));
  }

  cargar();
}
