// Test de verificación profunda para el comparador en pestaña Upscaler
import assert from "node:assert/strict";

// Mock del DOM
class MockElement {
  constructor(id, tagName = "div") {
    this.id = id;
    this.tagName = tagName;
    this.className = "";
    this.classList = {
      _classes: new Set(),
      add: (c) => this.classList._classes.add(c),
      remove: (c) => this.classList._classes.delete(c),
      toggle: (c, val) => {
        if (val === undefined) {
          if (this.classList._classes.has(c)) this.classList._classes.delete(c);
          else this.classList._classes.add(c);
        } else if (val) {
          this.classList._classes.add(c);
        } else {
          this.classList._classes.delete(c);
        }
      },
      contains: (c) => this.classList._classes.has(c),
    };
    this.attributes = new Map();
    this.style = {};
    this.textContent = "";
    this.disabled = false;
    this.value = "";
    this.src = "";
    this.alt = "";
    this.children = [];
    this.listeners = new Map();
  }
  setAttribute(k, v) { this.attributes.set(k, String(v)); }
  getAttribute(k) { return this.attributes.get(k) || null; }
  removeAttribute(k) { this.attributes.delete(k); }
  addEventListener(event, fn) {
    if (!this.listeners.has(event)) this.listeners.set(event, []);
    this.listeners.get(event).push(fn);
  }
  dispatchEvent(event) {
    const list = this.listeners.get(event.type) || [];
    for (const fn of list) fn(event);
  }
  replaceChildren(...children) {
    this.children = children;
  }
  appendChild(child) {
    this.children.push(child);
  }
  pause() {}
  load() {}
  getBoundingClientRect() {
    return { left: 0, top: 0, width: 400, height: 300 };
  }
}

const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    elements.set(id, new MockElement(id));
  }
  return elements.get(id);
}

globalThis.document = {
  getElementById: (id) => getEl(id),
  createElement: (tag) => new MockElement("elem_" + Math.random(), tag),
  addEventListener: () => {},
};
globalThis.window = {
  addEventListener: () => {},
};
const OriginalURL = globalThis.URL;
OriginalURL.createObjectURL = (f) => "blob:mock-" + (f ? f.name : "file");
OriginalURL.revokeObjectURL = () => {};

globalThis.fetch = async (url) => {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      items: state.upscaleGallery.items || [],
      count: (state.upscaleGallery.items || []).length,
    }),
  };
};

// Importar módulos
const { state } = await import("../static/js/state.js");
const {
  updateUpscaleCompare,
  updateUpscaleActions,
  updateUpscaleSourceView,
  getUpscaleCompareUrls,
  setUpscaleCompareActive,
  selectUpscaleSource,
  resolveItemImageUrl,
  clearUpscaleSelection,
  clearUpscaleLocalFile,
  finishUpscale,
} = await import("../static/js/tabs/upscaler.js");

// Reset de estado inicial
function resetAll() {
  clearUpscaleSelection();
  state.upscalers = [];
  state.upscaleSources = [];
  state.upscaleSourceId = null;
  state.upscaleLocalFile = null;
  state.upscaleCompareSlot2 = null;
  state.upscaleLastSourceUrl = null;
  state.upscaleLastResultUrl = null;
  state.upscaleLastResultId = null;
  getEl("upscale-kind").value = "image";
  getEl("btn-upscale-compare").disabled = true;
  getEl("btn-upscale-compare").textContent = "Comparar";
}

console.log("=== Ejecutando pruebas unitarias de lógica Upscaler Compare ===");

// Test 1: Sin imagen seleccionada, el botón debe estar deshabilitado
resetAll();
updateUpscaleActions();
assert.equal(getEl("btn-upscale-compare").disabled, true, "Test 1 Falló: Botón debe estar deshabilitado sin imagen");
console.log("✔ Test 1: Botón deshabilitado cuando no hay imagen");

// Test 2: Al seleccionar imagen normal de galería, el botón se habilita
resetAll();
const normalItem = {
  id: 10,
  kind: "image",
  params: { prompt: "chica anime" },
  urls: ["/media/10/img_10.png"],
  outputs: ["img_10.png"],
};
state.upscaleSources = [normalItem];
state.upscaleGallery.items = [normalItem];
selectUpscaleSource(10);
assert.equal(getEl("btn-upscale-compare").disabled, false, "Test 2 Falló: Botón debe habilitarse al seleccionar imagen");
assert.equal(getEl("btn-upscale-compare").textContent, "Comparar", "Test 2 Falló: Texto debe ser 'Comparar'");
console.log("✔ Test 2: Botón habilitado al seleccionar imagen normal");

// Test 3: Al seleccionar ítem que es resultado previo de upscale, compara original (#source_gen) vs escalada (#item.id)
resetAll();
const srcItem = {
  id: 5,
  kind: "image",
  urls: ["/media/5/source.png"],
  outputs: ["source.png"],
};
const upscaleItem = {
  id: 8,
  kind: "image",
  params: {
    task: "upscale",
    source_gen: 5,
    source_file: "source.png",
  },
  urls: ["/media/8/upscaled.png"],
  outputs: ["upscaled.png"],
};
state.upscaleSources = [upscaleItem, srcItem];
state.upscaleGallery.items = [upscaleItem, srcItem];
selectUpscaleSource(8);
const urlsT3 = getUpscaleCompareUrls();
assert.equal(urlsT3.canCompare, true, "Test 3 Falló: canCompare debe ser true");
assert.equal(urlsT3.before, "/media/5/source.png", "Test 3 Falló: before debe ser /media/5/source.png");
assert.equal(urlsT3.after, "/media/8/upscaled.png", "Test 3 Falló: after debe ser /media/8/upscaled.png");
assert.match(urlsT3.label, /#5.*#8/, "Test 3 Falló: label debe mencionar #5 y #8");
console.log("✔ Test 3: Resolución de par previo original vs escalada con source_gen");

// Test 4: Clic en Comparar activa el visor interactivo y cambia texto a 'Cerrar comparación'
setUpscaleCompareActive(true);
assert.equal(getEl("btn-upscale-compare").textContent, "Cerrar comparación", "Test 4 Falló: Texto debe cambiar a 'Cerrar comparación'");
assert.equal(getEl("btn-upscale-compare").getAttribute("aria-pressed"), "true", "Test 4 Falló: aria-pressed debe ser true");
assert.equal(getEl("upscale-compare").classList.contains("hidden"), false, "Test 4 Falló: upscale-compare no debe tener clase hidden");
assert.equal(getEl("upscale-compare-before").src, "/media/5/source.png", "Test 4 Falló: before img src incorrecto");
assert.equal(getEl("upscale-compare-after").src, "/media/8/upscaled.png", "Test 4 Falló: after img src incorrecto");
console.log("✔ Test 4: Activación de visor interactivo antes/después");

// Test 5: Cerrar comparación restaura texto a 'Comparar' y oculta el visor comparador
setUpscaleCompareActive(false);
assert.equal(getEl("btn-upscale-compare").textContent, "Comparar", "Test 5 Falló: Texto debe volver a 'Comparar'");
assert.equal(getEl("btn-upscale-compare").getAttribute("aria-pressed"), "false", "Test 5 Falló: aria-pressed debe ser false");
assert.equal(getEl("upscale-compare").classList.contains("hidden"), true, "Test 5 Falló: upscale-compare debe tener clase hidden");
console.log("✔ Test 5: Cierre de comparación restaura estado");

// Test 6: Comparación interactiva entre dos imágenes normales
resetAll();
const itemA = { id: 1, urls: ["/media/1/a.png"], outputs: ["a.png"] };
const itemB = { id: 2, urls: ["/media/2/b.png"], outputs: ["b.png"] };
const itemC = { id: 3, urls: ["/media/3/c.png"], outputs: ["c.png"] };
state.upscaleSources = [itemA, itemB, itemC];
state.upscaleGallery.items = [itemA, itemB, itemC];
selectUpscaleSource(1);
setUpscaleCompareActive(true);
// Mientras compara A vs B, usuario hace clic en miniatura C -> C se convierte en Slot 2
selectUpscaleSource(3);
assert.equal(getEl("upscale-compare-before").src, "/media/1/a.png", "Test 6 Falló: before debe seguir siendo A");
assert.equal(getEl("upscale-compare-after").src, "/media/3/c.png", "Test 6 Falló: after debe actualizarse a C");
console.log("✔ Test 6: Cambio interactivo de Slot 2 al hacer clic en otra miniatura");

// Test 7: En modo vídeo, el botón Comparar permanece deshabilitado
resetAll();
getEl("upscale-kind").value = "video";
state.upscaleSources = [{ id: 99, kind: "video", urls: ["/media/99/v.mp4"] }];
state.upscaleSourceId = 99;
updateUpscaleActions();
assert.equal(getEl("btn-upscale-compare").disabled, true, "Test 7 Falló: Botón debe estar deshabilitado en modo vídeo");
console.log("✔ Test 7: Comparar deshabilitado en vídeo");

// Test 8: Finalización de trabajo de upscale con archivo local
resetAll();
state.upscaleLocalFile = { name: "local.png", url: "blob:mock-local", b64: "dGVzdA==" };
updateUpscaleSourceView();
assert.equal(getEl("btn-upscale-compare").disabled, false, "Test 8 Falló: Botón habilitado con archivo local");
state.upscaleLastSourceUrl = "blob:mock-local";
state.imageViewer.selectedId = 20;
const resultItemLocal = { id: 20, urls: ["/media/20/res.png"], outputs: ["res.png"] };
state.upscaleGallery.items = [resultItemLocal];
state.upscaleSources = [resultItemLocal];
await finishUpscale({ outputs: [{ url: "/media/20/res.png" }] });
assert.equal(state.upscaleSourceId, 20, "Test 8 Falló: upscaleSourceId debe apuntar al nuevo resultado");
assert.equal(state.upscaleLocalFile, null, "Test 8 Falló: upscaleLocalFile debe limpiarse");
assert.equal(getEl("btn-upscale-compare").disabled, false, "Test 8 Falló: Botón debe estar habilitado tras finishUpscale");
const urlsT8 = getUpscaleCompareUrls();
assert.equal(urlsT8.canCompare, true, "Test 8 Falló: canCompare debe ser true");
assert.equal(urlsT8.before, "blob:mock-local", "Test 8 Falló: before debe ser el blob local preservado");
assert.equal(urlsT8.after, "/media/20/res.png", "Test 8 Falló: after debe ser el resultado escalado");
console.log("✔ Test 8: finishUpscale preserva origen local y habilita comparación con resultado");

// Test 9: Caso borde con una única imagen en el sistema (solo image)
resetAll();
const singleItem = { id: 77, urls: ["/media/77/solo.png"], outputs: ["solo.png"] };
state.upscaleSources = [singleItem];
state.upscaleGallery.items = [singleItem];
selectUpscaleSource(77);
assert.equal(getEl("btn-upscale-compare").disabled, false, "Test 9 Falló: Botón debe habilitarse incluso con una única imagen");
const urlsT9 = getUpscaleCompareUrls();
assert.equal(urlsT9.canCompare, true, "Test 9 Falló: canCompare debe ser true con una única imagen");
assert.equal(urlsT9.solo, true, "Test 9 Falló: solo flag debe ser true");
setUpscaleCompareActive(true);
assert.equal(getEl("btn-upscale-compare").textContent, "Cerrar comparación", "Test 9 Falló: Debe permitir activar modo comparación");
setUpscaleCompareActive(false);
console.log("✔ Test 9: Caso borde con una única imagen (solo image) habilitado y manejado limpiamente");

// Test 10: Invalidación de caché de trabajo previo si el usuario selecciona una imagen no relacionada
resetAll();
state.upscaleLastSourceUrl = "/media/1/a.png";
state.upscaleLastResultUrl = "/media/2/b.png";
state.upscaleLastResultId = 2;
const unrelatedItem = { id: 99, urls: ["/media/99/z.png"], outputs: ["z.png"] };
const otherUnrelated = { id: 98, urls: ["/media/98/y.png"], outputs: ["y.png"] };
state.upscaleSources = [unrelatedItem, otherUnrelated];
state.upscaleGallery.items = [unrelatedItem, otherUnrelated];
selectUpscaleSource(99);
const urlsT10 = getUpscaleCompareUrls();
assert.equal(urlsT10.before, "/media/99/z.png", "Test 10 Falló: No debe usar el trabajo previo stale para imagen no relacionada");
assert.equal(urlsT10.after, "/media/98/y.png", "Test 10 Falló: Debe comparar con el candidato de la imagen no relacionada");
console.log("✔ Test 10: Caché stale de upscale previo no interfiere con selección no relacionada");

console.log("=== TODOS LOS 10 TESTS DE LÓGICA PASARON EXITOSAMENTE ===");
