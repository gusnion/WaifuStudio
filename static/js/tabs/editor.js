// WaifuStudio — Pestaña de Editor (Qwen-Image 2.1)
// Qué hace: lienzo interactivo, inpaint/outpaint, capas de referencia y minigalería.
// Qué no hace: no interfiere con los modelos de Anima de la pestaña de imagen.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import {
  state,
  EDITOR_REF_LIMIT,
  EDITOR_GALLERY_PAGE_SIZE,
  EDITOR_SIZE_MIN,
  EDITOR_SIZE_MAX,
  EDITOR_SIZE_STEP,
} from "../state.js";
import {
  $,
  on,
  readFileBase64,
  isVideoUrl,
  formatGalleryDate,
  option,
  setSelectValue,
  applyRandomSeed,
  toggleThumbs,
  setEditorStatus,
  setProgress,
  refFilename,
  downloadUrlFor,
  getThumbsCapacity,
} from "../dom.js";
import { api, postJson, pollJob } from "../api.js";
import { openLightbox } from "../components/lightbox.js";
import {
  setEditorCompareSlot2,
  applyEditorCompare,
  editorCompareActive,
  editorCompareSelecting,
  setEditorCompareEnabled,
  updateEditorCompare,
  editorCompareUrls,
  editorCurrentPreviewUrl,
} from "../components/compare.js";
import { reloadImageViewerFirstPage, selectedImageView, imageViewUrl } from "./image_viewer.js";
import { loadGalleryTab, openGalleryModal } from "./gallery.js";
import { switchTab } from "../main.js";


function setEditorBanner(installed) {
  const el = $("editor-banner");
  el.classList.toggle("ok", Boolean(installed));
  el.textContent = installed
    ? "Qwen-Image 2.1 instalado — listo para generar"
    : "Qwen-Image 2.1 no instalado — faltan archivos del modelo";
}

async function loadEditorStatus() {
  const data = await api("/api/editor/status");
  state.editorInstalled = Boolean(data.installed);
  setEditorBanner(state.editorInstalled);
  updateEditorControls();
  return data;
}

function updateEditorControls() {
  $("btn-editor-generate").disabled =
    state.editorBusy ||
    !state.editorInstalled ||
    !$("editor-prompt").value.trim();
}

function updateEditorRefs() {
  const box = $("editor-refs-preview");
  box.textContent = "";
  state.editorRefs.forEach((ref, index) => {
    const item = document.createElement("div");
    item.className = "editor-ref";
    const img = document.createElement("img");
    img.src = ref.url;
    img.alt = ref.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Quitar";
    remove.addEventListener("click", () => removeEditorRef(index));
    item.append(img, remove);
    box.appendChild(item);
  });
  updateEditorPreview();
}

function removeEditorRef(index) {
  const removed = state.editorRefs.splice(index, 1)[0];
  if (removed && removed.url) {
    URL.revokeObjectURL(removed.url);
  }
  updateEditorRefs();
  setEditorStatus(`Referencias: ${state.editorRefs.length}/${EDITOR_REF_LIMIT}`);
}

async function addEditorRefs(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) {
    return;
  }
  const room = Math.max(0, EDITOR_REF_LIMIT - state.editorRefs.length);
  if (files.length > room) {
    setEditorStatus(
      `Máximo ${EDITOR_REF_LIMIT} imágenes de referencia`,
      true
    );
  }
  for (const file of files.slice(0, room)) {
    const originalPath = file.path || file.webkitRelativePath || file.name;
    if (state.localFilesOriginalPaths) {
      state.localFilesOriginalPaths.set(file.name, originalPath);
    }
    const b64 = await readFileBase64(file);
    state.editorRefs.push({
      name: file.name,
      originalPath,
      b64,
      url: URL.createObjectURL(file),
    });
  }
  $("editor-refs").value = "";
  updateEditorRefs();
  if (files.length <= room) {
    setEditorStatus(`Referencias: ${state.editorRefs.length}/${EDITOR_REF_LIMIT}`);
  }
}

async function addEditorRefFromUrl(url, name) {
  const source = String(url || "");
  if (!source) {
    return;
  }
  if (state.editorRefs.length >= EDITOR_REF_LIMIT) {
    setEditorStatus(`Máximo ${EDITOR_REF_LIMIT} referencias (quita alguna)`, true);
    return;
  }
  const response = await fetch(source);
  if (!response.ok) {
    throw new Error(`No se pudo cargar la imagen (HTTP ${response.status})`);
  }
  const blob = await response.blob();
  if (state.editorRefs.length >= EDITOR_REF_LIMIT) {
    setEditorStatus(`Máximo ${EDITOR_REF_LIMIT} referencias (quita alguna)`, true);
    return;
  }
  const refName = name || refFilename({ url: source });
  const b64 = await readFileBase64(
    new File([blob], refName, { type: blob.type || "image/png" })
  );
  state.editorRefs.push({
    name: refName,
    b64,
    url: URL.createObjectURL(blob),
  });
  updateEditorRefs();
  setEditorStatus(`Referencias: ${state.editorRefs.length}/${EDITOR_REF_LIMIT}`);
}

async function setEditorEditSource(url, item) {
  const source = String(url || "");
  if (!source) {
    return;
  }
  for (const ref of state.editorRefs) {
    if (ref.url) {
      URL.revokeObjectURL(ref.url);
    }
  }
  state.editorRefs = [];
  await addEditorRefFromUrl(source, "visor");
  if (item) {
    applyEditorMetadata({
      ...(item.params || {}),
      prompt: item.prompt,
      negative: item.negative,
    });
  }
  setEditorStatus("Imagen del visor cargada para editar");
}

function syncEditorEditSource() {
  const item = selectedImageView();
  const url = item ? imageViewUrl(item) : null;
  if (!url) {
    if (!state.editorRefs.length) {
      setEditorStatus(
        "Editar usa la imagen seleccionada en el visor de Imagen",
        true
      );
    }
    return;
  }
  setEditorEditSource(url, item).catch((error) => setEditorStatus(error.message, true));
}

function updateEditorMode(options = {}) {
  const edit = $("editor-mode").value === "edit";
  const field = $("editor-refs-field");
  if (field) {
    field.style.display = edit ? "none" : "";
  }
  const hint = $("editor-refs-hint");
  if (hint) {
    hint.textContent = edit
      ? "En «Editar» se trabaja sobre la imagen seleccionada en el visor de Imagen (o clic en la galería de abajo); describe el cambio."
      : "Referencias (hasta 10): en «Generar» guían estilo/composición; clic en la galería de abajo para añadirlas.";
  }
  if (edit && options.sync !== false) {
    syncEditorEditSource();
  }
  updateEditorPreview();
}

function updateEditorPreview() {
  const box = $("editor-preview");
  if (!box) {
    return;
  }
  const image = $("editor-preview-img");
  const empty = $("editor-preview-empty");
  const edit = $("editor-mode").value === "edit";
  const refUrl = state.editorRefs.length ? state.editorRefs[0].url : "";
  const url = refUrl || state.editorResultUrl || "";
  if (url) {
    if (editorCompareActive) {
      image.removeAttribute("src");
      image.classList.add("hidden");
    } else {
      image.src = url;
      image.classList.remove("hidden");
    }
    empty.classList.add("hidden");
    box.classList.add("has-image");
    updateEditorCompare();
    return;
  }
  image.removeAttribute("src");
  image.classList.add("hidden");
  box.classList.remove("has-image");
  empty.textContent = edit
    ? "Selecciona una imagen en el visor de Imagen o en la galería"
    : "Carga referencias (archivo local o clic en la galería)";
  empty.classList.remove("hidden");
  updateEditorCompare();
}

function applyEditorMetadata(meta) {
  if (!meta || typeof meta !== "object") {
    return;
  }
  if (typeof meta.prompt === "string" && meta.prompt.trim()) {
    $("editor-prompt").value = meta.prompt;
  }
  const seed = Number(meta.seed);
  if (meta.seed != null && Number.isFinite(seed)) {
    $("editor-seed").value = String(Math.trunc(seed));
  }
  if (typeof meta.negative === "string") {
    $("editor-negative").value = meta.negative;
  }
  const steps = Number(meta.steps);
  if (meta.steps != null && Number.isFinite(steps)) {
    $("editor-steps").value = String(Math.trunc(steps));
  }
  const cfg = Number(meta.cfg);
  if (meta.cfg != null && Number.isFinite(cfg)) {
    $("editor-cfg").value = String(cfg);
    updateEditorCfgNote();
  }
  if (meta.original_size === true) {
    setSelectValue($("editor-size"), "original");
    applyEditorSizeSelection();
    return;
  }
  const width = Number(meta.width);
  const height = Number(meta.height);
  if (!Number.isInteger(width) || !Number.isInteger(height)) {
    return;
  }
  const preset = (state.formats || []).find(
    (format) => format.width === width && format.height === height
  );
  if (preset) {
    setSelectValue($("editor-size"), preset.id);
  } else {
    setSelectValue($("editor-size"), "manual");
    $("editor-width").value = String(width);
    $("editor-height").value = String(height);
  }
  applyEditorSizeSelection();
}



function updateEditorCfgNote() {
  const cfg = Number($("editor-cfg").value);
  const note = $("editor-cfg-note");
  if (!note) {
    return;
  }
  note.classList.toggle("hidden", !(Number.isFinite(cfg) && cfg > 1));
}

function validEditorSize(value) {
  return (
    Number.isInteger(value) &&
    value >= EDITOR_SIZE_MIN &&
    value <= EDITOR_SIZE_MAX &&
    value % EDITOR_SIZE_STEP === 0
  );
}

function setEditorProgress(progress) {
  setProgress(progress, "editor");
}

function fillEditorSizes() {
  const select = $("editor-size");
  if (!select) {
    return;
  }
  const previous = select.value;
  select.replaceChildren();
  for (const format of state.formats || []) {
    const { width, height } = format;
    if (
      width < EDITOR_SIZE_MIN ||
      height < EDITOR_SIZE_MIN ||
      width > EDITOR_SIZE_MAX ||
      height > EDITOR_SIZE_MAX ||
      width % EDITOR_SIZE_STEP !== 0 ||
      height % EDITOR_SIZE_STEP !== 0
    ) {
      continue;
    }
    select.appendChild(option(format.id, format.label));
  }
  select.appendChild(option("original", "Original (1ª referencia)"));
  select.appendChild(option("manual", "Manual"));
  if (previous && [...select.options].some((item) => item.value === previous)) {
    select.value = previous;
  } else {
    select.value = "original";
  }
  applyEditorSizeSelection();
}

function applyEditorSizeSelection() {
  const select = $("editor-size");
  const manual = !select || select.value === "manual";
  $("editor-manual-size").classList.toggle("hidden", !manual);
}

function renderEditorGallery() {
  const viewer = state.editorGallery;
  const container = $("editor-gallery-thumbs");
  if (!container) {
    return;
  }
  container.replaceChildren();
  if (!viewer.items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin generaciones.";
    container.appendChild(empty);
  }
  for (const item of viewer.items) {
    const url = imageViewUrl(item);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "image-thumb";
    button.title = `Usar generación #${item.id} como referencia`;
    button.setAttribute("aria-label", `Usar generación #${item.id} como referencia`);
    if (url) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = item.prompt || `Generación #${item.id}`;
      img.loading = "lazy";
      button.appendChild(img);
      button.addEventListener("click", () => {
        if (editorCompareActive || editorCompareSelecting) {
          setEditorCompareSlot2(url);
          return;
        }
        if ($("editor-mode").value === "edit") {
          setEditorEditSource(url, item).catch((error) =>
            setEditorStatus(error.message, true)
          );
        } else {
          addEditorRefFromUrl(url).catch((error) =>
            setEditorStatus(error.message, true)
          );
        }
      });
    } else {
      const missing = document.createElement("span");
      missing.className = "thumb-missing";
      missing.textContent = item.status === "error" ? "Error" : "Sin resultado";
      button.appendChild(missing);
      button.disabled = true;
    }
    container.appendChild(button);
  }
  $("editor-gallery-info").textContent = `página ${viewer.page} de ${viewer.total}`;
  $("editor-gallery-prev").disabled = viewer.page <= 1;
  $("editor-gallery-next").disabled = viewer.page >= viewer.total;
}

async function loadEditorGallery(page = 1) {
  const viewer = state.editorGallery;
  const pageSize = getThumbsCapacity("editor-gallery-thumbs");
  viewer.pageSize = pageSize;
  const wanted = Math.max(1, Math.trunc(Number(page)) || 1);
  const offset = (wanted - 1) * pageSize;
  try {
    const data = await api(
      `/api/gallery?kind=image&limit=${pageSize}&offset=${offset}`
    );
    const items = data.items || [];
    const count = Number(data.count);
    const total = Number.isFinite(count) && count > 0 ? count : items.length;
    viewer.total = Math.max(1, Math.ceil(total / pageSize));
    if (wanted > viewer.total) {
      return await loadEditorGallery(viewer.total);
    }
    viewer.page = wanted;
    viewer.items = items;
    renderEditorGallery();
  } catch (error) {
    setEditorStatus(error.message, true);
  }
}

function showEditorResult(job) {
  const output = ((job && job.outputs) || [])[0];
  const box = $("editor-result");
  if (!output || !output.url || !box) {
    return;
  }
  state.editorResultUrl = output.url;
  state.editorResultMeta =
    job && typeof job === "object"
      ? { ...(job.params || {}), prompt: job.prompt, negative: job.negative }
      : null;
  box.classList.remove("hidden");
  updateEditorPreview();
}

async function openEditorResultInGallery() {
  switchTab("gallery");
  await loadGalleryTab(1);
  const resultUrl = state.editorResultUrl;
  const item = (state.galleryTab.items || []).find((entry) =>
    (entry.urls || []).some((candidate) => candidate === resultUrl)
  );
  if (item) {
    openGalleryModal(item);
  }
}

async function editEditorResult() {
  const url = state.editorResultUrl;
  if (!url) {
    setEditorStatus("No hay resultado del editor para editar", true);
    return;
  }
  for (const ref of state.editorRefs) {
    if (ref.url) {
      URL.revokeObjectURL(ref.url);
    }
  }
  state.editorRefs = [];
  updateEditorRefs();
  await addEditorRefFromUrl(url);
  applyEditorMetadata(state.editorResultMeta);
  $("editor-mode").value = "edit";
  setSelectValue($("editor-size"), "original");
  applyEditorSizeSelection();
  updateEditorMode({ sync: false });
  setEditorStatus("Resultado cargado como referencia; describe el cambio");
  $("editor-prompt").focus();
}

function downloadEditorResult() {
  const downloadUrl = downloadUrlFor(state.editorResultUrl);
  if (!downloadUrl) {
    setEditorStatus("No hay resultado para descargar", true);
    return;
  }
  window.location.href = downloadUrl;
}

async function generateEditor() {
  if (state.editorBusy) {
    return;
  }
  const prompt = $("editor-prompt").value.trim();
  if (!prompt) {
    setEditorStatus("El prompt no puede estar vacío", true);
    return;
  }
  if ($("editor-mode").value === "edit" && !state.editorRefs.length) {
    setEditorStatus(
      "Editar necesita una imagen: selecciónala en el visor de Imagen o en la galería",
      true
    );
    return;
  }
  const sizeSelect = $("editor-size");
  const sizeChoice = sizeSelect ? sizeSelect.value : "manual";
  let sizePayload;
  if (sizeChoice === "original") {
    sizePayload = { original: true };
  } else {
    const preset =
      sizeChoice && sizeChoice !== "manual" ? state.formatsById[sizeChoice] : null;
    const width = preset ? preset.width : Math.trunc(Number($("editor-width").value));
    const height = preset ? preset.height : Math.trunc(Number($("editor-height").value));
    if (!validEditorSize(width) || !validEditorSize(height)) {
      setEditorStatus(
        `Medidas fuera de [${EDITOR_SIZE_MIN}, ${EDITOR_SIZE_MAX}] o no múltiplos de ${EDITOR_SIZE_STEP}`,
        true
      );
      return;
    }
    sizePayload = { width, height };
  }
  const steps = Number($("editor-steps").value);
  if (!Number.isInteger(steps) || steps < 10 || steps > 50) {
    setEditorStatus("Pasos fuera de [10, 50]", true);
    return;
  }
  const cfg = Number($("editor-cfg").value);
  if (!Number.isFinite(cfg) || cfg < 1 || cfg > 10) {
    setEditorStatus("CFG fuera de [1, 10]", true);
    return;
  }
  applyRandomSeed("editor-seed");
  const seedValue = Number($("editor-seed").value);
  const payload = {
    prompt,
    mode: $("editor-mode").value,
    negative: $("editor-negative").value,
    steps,
    cfg,
    size: sizePayload,
    seed: Number.isFinite(seedValue) ? Math.trunc(seedValue) : 42,
  };
  if (state.editorRefs.length) {
    payload.ref_images_b64 = state.editorRefs.map((ref) => ref.b64);
  }
  state.editorBusy = true;
  updateEditorControls();
  setEditorStatus("Encolando...");
  try {
    const data = await postJson("/api/editor/generate", payload);
    await pollJob(
      data.job_id,
      setEditorStatus,
      async (job) => {
        showEditorResult(job);
        await reloadImageViewerFirstPage();
        await loadEditorGallery(1);
      },
      setEditorProgress,
      false
    );
  } catch (error) {
    setEditorStatus(error.message, true);
  } finally {
    state.editorBusy = false;
    updateEditorControls();
  }
}


function initEditorTab() {
  on("editor-mode", "change", () => updateEditorMode());
  on("editor-prompt", "input", updateEditorControls);
  on("editor-cfg", "input", updateEditorCfgNote);
  on("editor-refs", "change", (event) => {
    addEditorRefs(event.target.files).catch((error) =>
      setEditorStatus(error.message, true)
    );
  });
  on("btn-editor-generate", "click", generateEditor);
  on("editor-size", "change", applyEditorSizeSelection);
  on("btn-editor-open-gallery", "click", openEditorResultInGallery);
  on("btn-editor-compare", "click", () =>
    setEditorCompareEnabled(!editorCompareActive)
  );
  on("btn-toggle-editor-thumbs", "click", () =>
    toggleThumbs("editor-gallery", "btn-toggle-editor-thumbs")
  );
  on("btn-editor-edit-result", "click", () => {
    editEditorResult().catch((error) => setEditorStatus(error.message, true));
  });
  on("btn-editor-download", "click", downloadEditorResult);
  on("editor-gallery-prev", "click", () => {
    loadEditorGallery(state.editorGallery.page - 1);
  });
  on("editor-gallery-next", "click", () => {
    loadEditorGallery(state.editorGallery.page + 1);
  });
  on("editor-preview", "click", () => {
    const image = $("editor-preview-img");
    if (!image || image.classList.contains("hidden")) {
      return;
    }
    const url = image.getAttribute("src");
    if (url) {
      openLightbox(url, "Imagen del editor");
    }
  });
}

export {
  setEditorStatus,
  setEditorBanner,
  loadEditorStatus,
  updateEditorControls,
  updateEditorRefs,
  removeEditorRef,
  addEditorRefs,
  addEditorRefFromUrl,
  setEditorEditSource,
  syncEditorEditSource,
  updateEditorMode,
  updateEditorPreview,
  applyEditorMetadata,
  editorCurrentPreviewUrl,
  editorCompareUrls,
  updateEditorCfgNote,
  validEditorSize,
  setEditorProgress,
  fillEditorSizes,
  applyEditorSizeSelection,
  renderEditorGallery,
  loadEditorGallery,
  showEditorResult,
  openEditorResultInGallery,
  editEditorResult,
  downloadEditorResult,
  generateEditor,
  initEditorTab,
};
