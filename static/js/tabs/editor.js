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
import { api, postJson, pollJob, enqueueJobs } from "../api.js";
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
import { ResolutionKit } from "../components/resolution_kit.js";
import {
  openPoseLibrary,
  registerPoseCallback,
  poseToDataUrl,
} from "../components/pose_library.js";
import { runMultiviewGeneration, renderSheet } from "../components/editor_multiview.js";
import { triggerLoraUpload, uploadLocalLora } from "../components/loras.js";
import { t } from "../i18n.js";

let editorResolutionKit = null;
let pendingEditorLoras = null;
let editorLorasLoaded = false;
const EDITOR_LORA_FAMILIES = new Set(["qwen", "qwen-image", "qwen_image", "editor"]);
const MULTIVIEW_PRESET_PROMPTS = {
  l0_editorial: "natural dynamic standing anime pose, balanced full-body composition, clean 2D linework",
  l1_open: "glamour standing pose, expressive posture, full-body composition",
  l2_bold_nsfw: "bold low-angle camera perspective, confident posture, full-body turnaround",
  l3_extreme: "close-up framing, detailed character study, consistent lighting",
};

function buildMultiviewBasePrompt(rawPrompt, posePreset) {
  const cleanPrompt = String(rawPrompt || "").trim();
  const presetText = posePreset && MULTIVIEW_PRESET_PROMPTS[posePreset] ? MULTIVIEW_PRESET_PROMPTS[posePreset] : "";
  if (cleanPrompt && presetText) {
    return `${cleanPrompt}, ${presetText}`;
  }
  return cleanPrompt || presetText;
}

function getEditorGenerateLabel() {
  if (state.activeJobsCount > 0) {
    return `${t("queue_prefix")} (${state.activeJobsCount})`;
  }
  const mode = $("editor-mode")?.value;
  if (mode === "multiview") {
    const count = Number($("editor-multiview-views")?.value || 4);
    return `Generar ${count} vistas`;
  }
  return t("generate");
}

function isEditorLora(item) {
  const family = String(item?.family || "").toLowerCase();
  if (EDITOR_LORA_FAMILIES.has(family)) return true;
  return /qwen/i.test(`${item?.file || ""} ${item?.display_name || ""} ${item?.id || ""}`);
}

async function loadEditorLoras(scan = false) {
  const select = $("editor-loras");
  if (!select) {
    return;
  }
  try {
    const data = await api(scan ? "/api/loras?scan=1" : "/api/loras?scan=0");
    const items = Array.isArray(data) ? data : data?.items || [];
    const currentSelected = new Set(
      pendingEditorLoras !== null
        ? pendingEditorLoras
        : [...select.selectedOptions].map((o) => o.value)
    );
    select.replaceChildren();
    const seen = new Set();
    for (const item of items) {
      if (!item || !item.id || seen.has(item.id) || !isEditorLora(item)) {
        continue;
      }
      seen.add(item.id);
      const opt = option(item.id, item.display_name || item.id);
      if (currentSelected.has(item.id)) {
        opt.selected = true;
      }
      select.appendChild(opt);
    }
  } catch (_error) {
    select.replaceChildren();
  } finally {
    const emptyHint = $("editor-loras-empty");
    if (emptyHint) {
      emptyHint.classList.toggle("hidden", select.options.length > 0);
    }
    editorLorasLoaded = true;
    pendingEditorLoras = null;
  }
}

async function uploadEditorLora(file) {
  return uploadLocalLora(file, {
    scope: "editor",
    family: "qwen",
    input: $("editor-lora-import-file"),
    onStatus: setEditorStatus,
    onUploaded: async () => {
      await loadEditorLoras(true);
    },
  });
}


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
  setEditorLicense(data.license);
  updateEditorControls();
  return data;
}

function setEditorLicense(info) {
  state.editorLicenseAccepted = Boolean(info && info.accepted);
  const box = $("editor-license");
  if (box) {
    box.classList.toggle("hidden", state.editorLicenseAccepted);
  }
  const check = $("editor-license-check");
  const button = $("btn-editor-license");
  if (check) {
    check.checked = state.editorLicenseAccepted;
    if (button) {
      button.disabled = state.editorLicenseAccepted ? true : !check.checked;
    }
  }
  updateEditorControls();
}

async function acceptEditorLicense() {
  const check = $("editor-license-check");
  if (!check || !check.checked) {
    setEditorStatus("Marca la casilla para aceptar la licencia", true);
    return;
  }
  try {
    const data = await postJson("/api/editor/license", { accepted: true });
    setEditorLicense(data.license);
    setEditorStatus("Licencia de Qwen-Image 2.1 aceptada");
  } catch (error) {
    setEditorStatus(error.message, true);
  }
}

function updateEditorControls() {
  const mode = $("editor-mode")?.value;
  const multiview = mode === "multiview";
  const hasPrompt = Boolean($("editor-prompt")?.value.trim());
  const hasPreset = Boolean($("editor-pose-preset")?.value);
  const btn = $("btn-editor-generate");
  if (!btn) {
    return;
  }
  btn.textContent = getEditorGenerateLabel();
  btn.disabled =
    state.editorBusy ||
    !state.editorInstalled ||
    !state.editorLicenseAccepted ||
    (!multiview && !hasPrompt && !hasPreset);
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
    if (typeof removed.url === "string" && removed.url.startsWith("blob:")) {
      URL.revokeObjectURL(removed.url);
    }
  }
  updateEditorRefs();
  setEditorStatus(`Referencias: ${state.editorRefs.length}/${EDITOR_REF_LIMIT}`);
}

function applyPoseToEditorRef(pose) {
  if (!pose) return;
  if (state.editorRefs.length >= EDITOR_REF_LIMIT) {
    setEditorStatus(`Máximo ${EDITOR_REF_LIMIT} referencias (quita alguna)`, true);
    return;
  }
  // C-33: convierte el esqueleto dibujado a PNG (dataURL) y adjúntalo como referencia para Qwen; no requiere los PNG originales
  const dataUrl = poseToDataUrl(pose);
  const b64 = dataUrl.includes(",") ? dataUrl.split(",", 2)[1] : dataUrl;
  const refName = `pose_${pose.id || "skeleton"}.png`;
  state.editorRefs.push({
    name: refName,
    b64,
    url: dataUrl,
  });
  updateEditorRefs();
  setEditorStatus(`Pose «${pose.clase_es || pose.id}» adjuntada como referencia (${state.editorRefs.length}/${EDITOR_REF_LIMIT})`);
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
    if (ref.url && typeof ref.url === "string" && ref.url.startsWith("blob:")) {
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
  const mode = $("editor-mode").value;
  const edit = mode === "edit";
  const multiview = mode === "multiview";
  const panel = $("panel-editor");
  if (panel) {
    panel.dataset.editorMode = mode;
  }
  const editHint = $("editor-edit-hint");
  if (editHint) {
    editHint.classList.toggle("hidden", !edit);
  }
  const field = $("editor-refs-field");
  if (field) {
    field.style.display = edit ? "none" : "";
  }
  const multiviewField = $("editor-multiview-field");
  if (multiviewField) multiviewField.classList.toggle("hidden", !multiview);
  const multiviewResults = $("editor-multiview-results");
  if (multiviewResults && !multiview) multiviewResults.classList.add("hidden");
  const poseLabel = $("editor-pose-preset-label");
  if (poseLabel) {
    poseLabel.textContent = multiview ? "Ángulo / Preset (L0..L3)" : "Ángulo / Preset de Pose (L0..L3)";
  }
  const promptAdvanced = $("editor-prompt-advanced");
  if (promptAdvanced) {
    promptAdvanced.open = !multiview;
  }
  const paramsAdvanced = $("editor-params-advanced");
  if (paramsAdvanced) {
    paramsAdvanced.open = !multiview;
  }
  const preserveField = $("editor-preserve-structure-field");
  if (preserveField) {
    preserveField.classList.toggle("hidden", multiview);
  }
  const lorasField = $("editor-loras-field");
  if (lorasField) {
    lorasField.classList.toggle("hidden", multiview);
  }
  if (multiview) {
    setSelectValue($("editor-res-orientation"), "original");
    setSelectValue($("editor-size"), "original");
  }
  const hint = $("editor-refs-hint");
  if (hint) {
    hint.textContent = multiview
      ? "Referencias (hasta 10): la multivista usa la primera y el mismo seed para todas las vistas."
      : edit
      ? "En «Editar» se trabaja sobre la imagen seleccionada en el visor de Imagen (o clic en la galería de abajo); describe el cambio."
      : "Referencias (hasta 10): en «Generar» guían estilo/composición; clic en la galería de abajo para añadirlas.";
  }
  if (edit && options.sync !== false) {
    syncEditorEditSource();
  }
  applyEditorSizeSelection();
  updateEditorControls();
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
  const url = edit
    ? (refUrl || state.editorResultUrl || "")
    : (state.editorResultUrl || refUrl || "");
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
  if (meta.loras != null) {
    const rawLoras = Array.isArray(meta.loras) ? meta.loras : [meta.loras];
    const loraIds = rawLoras
      .map((entry) => {
        if (typeof entry === "string") return entry;
        if (entry && (entry.id != null || entry.lora_name != null)) {
          return String(entry.id != null ? entry.id : entry.lora_name);
        }
        return null;
      })
      .filter(Boolean);
    const select = $("editor-loras");
    if (!editorLorasLoaded || !select || select.options.length === 0) {
      pendingEditorLoras = loraIds;
    } else {
      const idSet = new Set(loraIds);
      for (const opt of select.options) {
        opt.selected = idSet.has(opt.value);
      }
    }
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
  if (editorResolutionKit) {
    editorResolutionKit.syncFromDimensions(width, height);
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

function getDefaultEditorFormat() {
  const validFormats = (state.formats || []).filter((f) => {
    const { width, height } = f;
    return (
      width >= EDITOR_SIZE_MIN &&
      height >= EDITOR_SIZE_MIN &&
      width <= EDITOR_SIZE_MAX &&
      height <= EDITOR_SIZE_MAX &&
      width % EDITOR_SIZE_STEP === 0 &&
      height % EDITOR_SIZE_STEP === 0
    );
  });
  const square = validFormats.find((f) => f.width === 1024 && f.height === 1024);
  if (square) return square;
  if (validFormats.length) return validFormats[0];
  return { id: "cuadro_hd", width: 1024, height: 1024, label: "Cuadrado 1024x1024" };
}

function selectDefaultValidFormat(select) {
  if (!select) return;
  const defaultFmt = getDefaultEditorFormat();
  if (defaultFmt && [...select.options].some((item) => item.value === defaultFmt.id)) {
    select.value = defaultFmt.id;
  } else {
    const firstOption = [...select.options].find((opt) => opt.value !== "original" && opt.value !== "manual");
    if (firstOption) {
      select.value = firstOption.value;
    }
  }
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
  const isGenerate = $("editor-mode")?.value === "generate";
  const hasRefs = Boolean(state.editorRefs && state.editorRefs.length > 0);
  if (isGenerate && !hasRefs && select.value === "original") {
    selectDefaultValidFormat(select);
  }
  applyEditorSizeSelection();
}

function applyEditorSizeSelection() {
  const select = $("editor-size");
  const isGenerate = $("editor-mode")?.value === "generate";
  const hasRefs = Boolean(state.editorRefs && state.editorRefs.length > 0);
  if (isGenerate && !hasRefs && select && select.value === "original") {
    selectDefaultValidFormat(select);
  }
  const val = select ? select.value : "manual";
  const manual = val === "manual";
  $("editor-manual-size").classList.toggle("hidden", !manual);
  if (val === "original") {
    const badge = $("editor-res-badge");
    if (badge) {
      badge.textContent = "Original (1ª ref)";
    }
    const qual = $("editor-res-quality");
    if (qual) qual.disabled = true;
    if (editorResolutionKit) {
      editorResolutionKit.syncFromDimensions("original", "original");
    }
  } else if (!manual) {
    const qual = $("editor-res-quality");
    if (qual) qual.disabled = false;
    const preset = state.formatsById ? state.formatsById[val] : null;
    if (preset) {
      $("editor-width").value = String(preset.width);
      $("editor-height").value = String(preset.height);
      if (editorResolutionKit) {
        editorResolutionKit.syncFromDimensions(preset.width, preset.height);
      }
    }
  } else {
    const qual = $("editor-res-quality");
    if (qual) qual.disabled = false;
    if (editorResolutionKit) {
      const w = Number($("editor-width").value);
      const h = Number($("editor-height").value);
      if (w && h) {
        editorResolutionKit.syncFromDimensions(w, h);
      }
    }
  }
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
    if (ref.url && typeof ref.url === "string" && ref.url.startsWith("blob:")) {
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
  if (!state.editorLicenseAccepted) {
    setEditorStatus("Acepta la licencia de Qwen-Image 2.1 antes de generar", true);
    return;
  }
  if ($("editor-mode").value === "multiview") {
    if (!state.editorRefs.length) {
      setEditorStatus("Añade al menos una referencia para la multivista", true);
      return;
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
    const seed = Number.isFinite(seedValue) ? Math.trunc(seedValue) : 42;
    const count = Number($("editor-multiview-views")?.value || 4);
    const rawPrompt = $("editor-prompt")?.value.trim() || "";
    const posePreset = $("editor-pose-preset")?.value || "";
    const basePrompt = buildMultiviewBasePrompt(rawPrompt, posePreset);
    const refs = state.editorRefs.slice(0, 1).map((ref) => ref.b64);
    state.editorBusy = true;
    updateEditorControls();
    setEditorStatus(`Generando ${count} vistas con seed ${seed}…`);
    try {
      const entries = await runMultiviewGeneration({
        refs,
        prompt: basePrompt,
        negative: $("editor-negative")?.value || "",
        count,
        seed,
        steps,
        cfg,
        onProgress: (msg) => setEditorStatus(msg),
        onViewGenerated: async (entry) => {
          if (entry && entry.url) {
            state.editorResultUrl = entry.url;
            updateEditorPreview();
          }
        },
      });
      renderSheet(entries, "editor-multiview-results");
      if (entries.length) {
        const last = entries[entries.length - 1];
        if (last.url) {
          state.editorResultUrl = last.url;
          $("editor-result")?.classList.remove("hidden");
          updateEditorPreview();
        }
      }
      await reloadImageViewerFirstPage();
      await loadEditorGallery(1);
      setEditorStatus(`Multivista lista (${entries.length} vistas)`);
    } catch (error) {
      setEditorStatus(error.message, true);
    } finally {
      state.editorBusy = false;
      updateEditorControls();
    }
    return;
  }
  const prompt = $("editor-prompt").value.trim();
  const posePreset = $("editor-pose-preset")?.value || "";
  if (!prompt && !posePreset) {
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
  const orientSelect = $("editor-res-orientation");
  const sizeSelect = $("editor-size");
  const isOriginal = (orientSelect && orientSelect.value === "original") || (sizeSelect && sizeSelect.value === "original");
  const hasRefs = Boolean(state.editorRefs && state.editorRefs.length > 0);
  let sizePayload;
  if (isOriginal && !hasRefs) {
    const defaultFmt = getDefaultEditorFormat();
    const width = defaultFmt ? defaultFmt.width : 1024;
    const height = defaultFmt ? defaultFmt.height : 1024;
    sizePayload = { width, height };
    if (sizeSelect) {
      if (defaultFmt && [...sizeSelect.options].some((opt) => opt.value === defaultFmt.id)) {
        sizeSelect.value = defaultFmt.id;
      }
      applyEditorSizeSelection();
    }
  } else if (isOriginal) {
    sizePayload = { original: true };
  } else {
    const sizeChoice = sizeSelect ? sizeSelect.value : "manual";
    const preset =
      sizeChoice && sizeChoice !== "manual" ? (state.formatsById ? state.formatsById[sizeChoice] : null) : null;
    const rawWidth = preset ? preset.width : Math.trunc(Number($("editor-width").value));
    const rawHeight = preset ? preset.height : Math.trunc(Number($("editor-height").value));
    const width = Math.round(rawWidth / 16) * 16;
    const height = Math.round(rawHeight / 16) * 16;
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

  const recipeMode = $("editor-recipe-mode")?.value || "standard_sfw";
  const preserveStructure = Boolean($("editor-preserve-structure")?.checked);
  let samplerName = "euler";
  let scheduler = "simple";
  if (recipeMode === "pose_nsfw") {
    samplerName = "er_sde";
    scheduler = "beta";
  }

  const payload = {
    prompt,
    mode: $("editor-mode").value,
    negative: $("editor-negative").value,
    steps,
    cfg,
    size: sizePayload,
    seed: Number.isFinite(seedValue) ? Math.trunc(seedValue) : 42,
    sampler_name: samplerName,
    scheduler,
    preserve_structure: preserveStructure,
  };
  if (posePreset) {
    payload.pose_preset = posePreset;
  }
  const loras = [...$("editor-loras").selectedOptions].map((o) => ({ id: o.value, weight: 1.0 }));
  if (loras.length) {
    payload.loras = loras;
  }
  if (state.editorRefs.length) {
    payload.ref_images_b64 = state.editorRefs.map((ref) => ref.b64);
  }
  const btn = $("btn-editor-generate");
  if (btn) btn.disabled = true;
  setEditorStatus("Encolando...");
  try {
    const data = await postJson("/api/editor/generate", payload);
    loadEditorGallery(1).catch(() => {});
    await enqueueJobs(data.job_id, {
      statusFn: setEditorStatus,
      onDone: async (job) => {
        showEditorResult(job);
        await reloadImageViewerFirstPage();
        await loadEditorGallery(1);
      },
      progressFn: setEditorProgress,
      manageCancel: false,
    });
  } catch (error) {
    setEditorStatus(error.message, true);
  } finally {
    updateEditorControls();
    if (btn) {
      btn.textContent = getEditorGenerateLabel();
    }
  }
}


function initEditorTab() {
  on("editor-mode", "change", () => updateEditorMode());
  on("editor-multiview-views", "change", updateEditorControls);
  on("editor-prompt", "input", updateEditorControls);
  on("editor-pose-preset", "change", updateEditorControls);
  on("editor-cfg", "input", updateEditorCfgNote);
  on("editor-recipe-mode", "change", () => {
    const mode = $("editor-recipe-mode")?.value;
    if (mode === "pose_nsfw") {
      $("editor-cfg").value = "3.0";
      updateEditorCfgNote();
    } else if (mode === "standard_sfw") {
      $("editor-cfg").value = "1.0";
      updateEditorCfgNote();
    }
  });
  on("editor-refs", "change", (event) => {
    addEditorRefs(event.target.files).catch((error) =>
      setEditorStatus(error.message, true)
    );
  });
  on("btn-editor-poses", "click", () => openPoseLibrary("editor"));
  registerPoseCallback("editor", applyPoseToEditorRef);
  on("btn-editor-generate", "click", generateEditor);
  on("editor-license-check", "change", () => {
    const check = $("editor-license-check");
    const button = $("btn-editor-license");
    if (button) button.disabled = !check?.checked;
  });
  on("btn-editor-license", "click", acceptEditorLicense);
  on("editor-size", "change", applyEditorSizeSelection);
  on("btn-editor-lora-import", "click", () => triggerLoraUpload("qwen"));
  on("editor-lora-import-file", "change", (event) => {
    const file = event.target?.files?.[0] || null;
    uploadEditorLora(file).catch((error) => setEditorStatus(error.message, true));
  });
  window.addEventListener("waifu:lora-uploaded", () => {
    loadEditorLoras(true).catch((error) => setEditorStatus(error.message, true));
  });
  loadEditorLoras().catch(() => {});

  const orient = $("editor-res-orientation");
  const qual = $("editor-res-quality");
  if (orient && qual) {
    editorResolutionKit = new ResolutionKit({
      orientationSelect: orient,
      qualitySelect: qual,
      widthInput: $("editor-width"),
      heightInput: $("editor-height"),
      badgeEl: $("editor-res-badge"),
      defaultOrientation: "original",
      defaultQuality: "fhd",
      onChange: ({ orientation, width, height }) => {
        const sizeSelect = $("editor-size");
        if (orientation === "original") {
          if (sizeSelect) sizeSelect.value = "original";
          applyEditorSizeSelection();
          return;
        }
        const w16 = Math.round(width / 16) * 16;
        const h16 = Math.round(height / 16) * 16;
        if ($("editor-width")) $("editor-width").value = String(w16);
        if ($("editor-height")) $("editor-height").value = String(h16);
        const match = (state.formats || []).find((f) => f.width === w16 && f.height === h16);
        if (sizeSelect) {
          sizeSelect.value = match ? match.id : "manual";
        }
        applyEditorSizeSelection();
      },
    });
  }

  on("editor-width", "input", () => {
    if (editorResolutionKit) {
      editorResolutionKit.syncFromDimensions($("editor-width").value, $("editor-height").value);
    }
  });
  on("editor-height", "input", () => {
    if (editorResolutionKit) {
      editorResolutionKit.syncFromDimensions($("editor-width").value, $("editor-height").value);
    }
  });
  on("btn-editor-open-gallery", "click", openEditorResultInGallery);
  window.addEventListener("waifu:queue-updated", () => {
    const btn = $("btn-editor-generate");
    if (btn) {
      btn.textContent = getEditorGenerateLabel();
    }
  });
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
  getEditorGenerateLabel,
  buildMultiviewBasePrompt,
  applyPoseToEditorRef,
  uploadEditorLora,
  initEditorTab,
  loadEditorLoras,
};
