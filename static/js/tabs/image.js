// WaifuStudio — Pestaña de Generación de Imagen
// Qué hace: selección de checkpoint Anima, sliders de sampling, I2I y ejecución.
// Qué no hace: no procesa vídeo Wan/H3 ni tareas de inpainting del editor.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import {
  state,
  STARTUP_DEFAULTS,
  LLM_STATUS_LABELS,
} from "../state.js";
import {
  $,
  on,
  setStatus,
  option,
  setSelectValue,
  readFileBase64,
  applyRandomSeed,
  setProgress,
  setVideoProgress,
} from "../dom.js";
import { api, postJson, pollJob, cancelJob, enqueueJobs } from "../api.js";
import { ResolutionKit } from "../components/resolution_kit.js";
import {
  collectPromptZoneTags,
  applyZonesPayload,
  renderZoneEditor,
  resetPromptZones,
  flushPendingZoneInputs,
  updateGenerateState,
  composePrompt,
} from "../components/prompt_zones.js";
import {
  readLorasPayload,
  applyLorasSelection,
  loadLoras,
} from "../components/loras.js";
import { applyVideoEngine } from "./video.js";
import { fillEditorSizes } from "./editor.js";
import { attachReferenceFromUrl } from "../components/prompt_popover.js";
import { openOcSaveModal } from "../components/oc_picker.js";
import {
  selectedImageView,
  loadImageViewer,
  reloadImageViewerFirstPage,
} from "./image_viewer.js";
import {
  openVisionModal,
  closeVisionModal,
} from "../components/vision.js";
import {
  openPrepromptModal,
  closePrepromptModal,
} from "../components/preprompts.js";

let enhanceResetTimer = null;
let refObjectUrl = null;
let imageResolutionKit = null;

const PROMPT_PROFILE_PLACEHOLDERS = {
  anima: "Tags Danbooru, artista @ (ej.: 1girl, solo, looking at viewer, @artist)",
  sdxl_tags: "Tags descriptivos sin score/@ (ej.: 1girl, solo, portrait, soft lighting, 8k)",
  sdxl_natural: "Frase en lenguaje natural (ej.: A serene portrait of a young woman in a sunlit garden)",
  qwen_edit: "Instrucción de edición o generación (ej.: Change expression to a gentle smile, sunset background)",
};

function isTagPromptProfile(profile) {
  return profile === "anima" || profile === "sdxl_tags";
}

async function loadParams() {
  const data = await api("/api/params");
  state.params = data;
  const sampler = $("sampler");
  sampler.replaceChildren();
  for (const name of data.samplers) {
    sampler.appendChild(option(name, name));
  }
  setSelectValue(sampler, data.default_sampler);
  const scheduler = $("scheduler");
  scheduler.replaceChildren();
  for (const name of data.schedulers) {
    scheduler.appendChild(option(name, name));
  }
  setSelectValue(scheduler, data.default_scheduler);
}

async function loadFormats() {
  const data = await api("/api/formats");
  state.formats = data.formats || [];
  state.formatsById = {};
  const select = $("size");
  select.replaceChildren();
  for (const format of state.formats) {
    state.formatsById[format.id] = format;
    select.appendChild(option(format.id, format.label));
  }
  select.appendChild(option("manual", "Manual"));
  if (state.formatsById[data.default]) {
    select.value = data.default;
  }
  applySizeSelection();
  fillEditorSizes();
}

function applySizeSelection() {
  const format = state.formatsById[$("size").value];
  if (format) {
    $("width").value = format.width;
    $("height").value = format.height;
    $("manual-size").classList.add("hidden");
    if (imageResolutionKit) {
      imageResolutionKit.syncFromDimensions(format.width, format.height);
    }
  } else {
    $("manual-size").classList.remove("hidden");
    if (imageResolutionKit) {
      imageResolutionKit.syncFromDimensions($("width").value, $("height").value);
    }
  }
}

function setSizeFromDefaults(width, height) {
  const match = state.formats.find(
    (format) => format.width === width && format.height === height
  );
  if (match) {
    $("size").value = match.id;
  } else if (width != null || height != null) {
    $("size").value = "manual";
    if (width != null) {
      $("width").value = width;
    }
    if (height != null) {
      $("height").value = height;
    }
  }
  applySizeSelection();
  if (imageResolutionKit && width != null && height != null) {
    imageResolutionKit.syncFromDimensions(width, height);
  }
}

async function refreshModelsCatalog() {
  const models = await api("/api/models?scan=1");
  state.models = models || [];
  const select = $("model");
  if (!select) {
    return;
  }
  const previous = select.value;
  select.replaceChildren();
  for (const model of state.models) {
    select.appendChild(option(model.id, model.display_name || model.id));
  }
  if (previous && state.models.some((m) => m.id === previous)) {
    select.value = previous;
  }
}

async function loadModels() {
  state.models = await api("/api/models?scan=1");
  const select = $("model");
  select.replaceChildren();
  for (const model of state.models) {
    select.appendChild(option(model.id, model.display_name || model.id));
  }
  if (state.models.length) {
    try {
      await applyModel(state.models[0].id);
    } catch (error) {
      setStatus(`Modelo: ${error.message}`, true);
      throw error;
    }
  }
}

async function loadPrepromptOptions() {
  const family = state.family || "anima";
  const data = await api(`/api/preprompts?family=${encodeURIComponent(family)}`);
  state.customPreprompts = data.custom || [];
  const custom = new Set(state.customPreprompts);
  const select = $("preprompt");
  const previous = select.value;
  select.replaceChildren();
  for (const name of data.names || []) {
    select.appendChild(option(name, custom.has(name) ? `${name} (propio)` : name));
  }
  setSelectValue(select, previous);
  return data;
}


async function applyModel(modelId) {
  const model = state.models.find((item) => item.id === modelId);
  if (!model) {
    return;
  }
  state.family = model.family || "anima";
  state.prompt_profile =
    model.prompt_profile || (state.family === "anima" ? "anima" : "sdxl_tags");

  // 1. Placeholder del prompt general según el perfil
  const promptGeneral = $("prompt-general");
  if (promptGeneral) {
    promptGeneral.placeholder =
      PROMPT_PROFILE_PLACEHOLDERS[state.prompt_profile] || PROMPT_PROFILE_PLACEHOLDERS.sdxl_tags;
  }

  // 2. Visibilidad de zonas de tags según el perfil
  const showZones = isTagPromptProfile(state.prompt_profile);
  const zonesCard = $("image-block-zones");
  if (zonesCard) {
    zonesCard.classList.toggle("hidden", !showZones);
  }
  const zonesSection = $("section-zones");
  if (zonesSection) {
    zonesSection.classList.toggle("hidden", !showZones);
  }

  // 3. Preprompt y opciones
  const data = await loadPrepromptOptions();
  const select = $("preprompt");
  if (model.preprompt && data.names.includes(model.preprompt)) {
    select.value = model.preprompt;
  } else if (!showZones && data.names.includes("ninguno")) {
    select.value = "ninguno";
  } else {
    select.value = data.default;
  }

  // 4. Defaults de generación
  const defaults = model.defaults || {};
  const hasDefaultSize = defaults.width != null && defaults.height != null;
  $("steps").value = defaults.steps != null ? defaults.steps : 30;
  $("cfg").value = defaults.cfg != null ? defaults.cfg : 6.0;
  setSelectValue($("sampler"), defaults.sampler_name || "euler");
  setSelectValue($("scheduler"), defaults.scheduler || "normal");
  setSizeFromDefaults(
    hasDefaultSize ? defaults.width : 1024,
    hasDefaultSize ? defaults.height : 1024
  );
  if ($("seed")) {
    $("seed").value = defaults.seed != null ? defaults.seed : 42;
  }
  await loadLoras();

  // 5. Negativo actualizado al cambiar de modelo
  state.negativeTouched = false;
  await refreshNegative();

  // 6. Estado del botón generar
  updateGenerateButtonState();
}

async function applyStartupDefaults() {
  const modelSelect = $("model");
  const hasModel = Array.from(modelSelect.options).some(
    (opt) => opt.value === STARTUP_DEFAULTS.model
  );
  if (hasModel) {
    modelSelect.value = STARTUP_DEFAULTS.model;
    await applyModel(STARTUP_DEFAULTS.model);
  }
  setSelectValue($("preprompt"), STARTUP_DEFAULTS.preprompt);
  $("rating").value = STARTUP_DEFAULTS.rating;
  $("steps").value = STARTUP_DEFAULTS.steps;
  $("cfg").value = STARTUP_DEFAULTS.cfg;
  setSelectValue($("sampler"), STARTUP_DEFAULTS.sampler);
  setSelectValue($("scheduler"), STARTUP_DEFAULTS.scheduler);
  setSizeFromDefaults(STARTUP_DEFAULTS.width, STARTUP_DEFAULTS.height);
  if ($("seed")) {
    $("seed").value = STARTUP_DEFAULTS.seed != null ? STARTUP_DEFAULTS.seed : 42;
  }
  const sizeSquare = $("size-square");
  if (sizeSquare) {
    if (sizeSquare.type === "radio" || sizeSquare.type === "checkbox") {
      sizeSquare.checked = true;
    } else {
      sizeSquare.value = "cuadro_hd";
    }
  }
  const imageSize = $("image-size");
  if (imageSize) {
    imageSize.value = "1024x1024";
  }
  state.negativeTouched = false;
  state.negativeBase = STARTUP_DEFAULTS.negative;
  $("negative").value = STARTUP_DEFAULTS.negative;
  try {
    await refreshNegative();
  } catch (error) {
    console.error("defaults: negativo dinamico no disponible", error);
  }
  $("video-engine").value = STARTUP_DEFAULTS.video_engine;
  applyVideoEngine();
}

function readBaseParams() {
  const toNumber = (id, fallback) => {
    const value = Number($(id).value);
    return Number.isFinite(value) ? value : fallback;
  };
  return {
    seed: Math.trunc(toNumber("seed", 42)),
    steps: Math.trunc(toNumber("steps", 20)),
    cfg: toNumber("cfg", 4),
    sampler_name: $("sampler").value || state.params.default_sampler,
    scheduler: $("scheduler").value || state.params.default_scheduler,
  };
}

function validSize(value) {
  return Number.isInteger(value) && value >= 64 && value <= 4096 && value % 8 === 0;
}

function readSizePayload() {
  const sizeId = $("size").value;
  if (sizeId && sizeId !== "manual") {
    return { size: sizeId };
  }
  return {
    width: Math.trunc(Number($("width").value)),
    height: Math.trunc(Number($("height").value)),
  };
}


async function refreshNegative() {
  if (state.negativeTouched) {
    return;
  }
  const preprompt =
    $("preprompt").value || (state.family === "sdxl" ? "sdxl_default" : "glossy");
  const family = state.family || "anima";
  const data = await api(
    `/api/negative?preprompt=${encodeURIComponent(preprompt)}&family=${encodeURIComponent(family)}`
  );
  state.negativeBase = data.negative || "";
  $("negative").value = state.negativeBase;
}

async function restoreNegative() {
  state.negativeTouched = false;
  try {
    await refreshNegative();
    setStatus("Negativo restaurado");
  } catch (error) {
    setStatus(error.message, true);
  }
}


async function refreshLlmStatus() {
  const el = $("llm-status");
  if (!el) {
    return;
  }
  el.classList.remove("is-ok", "is-warn", "is-off");
  let data = null;
  try {
    data = await api("/api/llm/status");
  } catch (_error) {
    data = null;
  }
  const state = data && typeof data.state === "string" ? data.state : "";
  const entry = LLM_STATUS_LABELS[state];
  el.textContent = entry ? entry[0] : "LLM: ?";
  if (entry) {
    el.classList.add(entry[1]);
  }
  const bits = [];
  if (data && data.detail) {
    bits.push(String(data.detail));
  }
  if (data && data.url) {
    bits.push(String(data.url));
  }
  el.title = bits.join(" · ");
}

async function enhancePrompt() {
  if (state.pendingEnhance) {
    return;
  }
  const generalField = $("prompt-general");
  const text = String(generalField.value || "").trim();
  if (!text) {
    setStatus("Escribe una descripción en el prompt general", true);
    generalField.focus();
    return;
  }
  const button = $("btn-enhance");
  state.pendingEnhance = true;
  button.disabled = true;
  button.textContent = "Generando…";
  setStatus("Generando prompt...");
  const startedAt = performance.now();
  try {
    const data = await postJson("/api/prompt/enhance_zones", {
      text,
      strength: $("enhance-strength").value,
      rating: $("rating").value,
      tags: collectPromptZoneTags(),
    });
    const elapsedMs = performance.now() - startedAt;
    applyZonesPayload(data.zones || []);
    const negative = String(data.negative || "").trim();
    if (negative) {
      $("negative").value = negative;
      state.negativeTouched = false;
    }
    renderZoneEditor();
    button.textContent = "Generado ✓";
    setStatus(`Prompt generado ✓ · ${(elapsedMs / 1000).toFixed(1)} s`);
  } catch (error) {
    button.textContent = "Error";
    setStatus(error.message, true);
  } finally {
    state.pendingEnhance = false;
    button.disabled = false;
    if (enhanceResetTimer) {
      clearTimeout(enhanceResetTimer);
    }
    enhanceResetTimer = setTimeout(() => {
      if (!state.pendingEnhance) {
        button.textContent = "Generar prompt";
      }
    }, 1600);
    refreshLlmStatus();
  }
}


async function startNewGeneration() {
  resetPromptZones();
  $("prompt-general").value = "";
  clearReference();
  await applyStartupDefaults();
  if (!state.seedRandom) {
    $("seed").value = $("seed").defaultValue || "42";
  }
  renderZoneEditor();
  setStatus("Nuevo: opciones por defecto");
}

function updateGenerateButtonState() {
  updateGenerateState();
  const btn = $("btn-generate");
  if (!btn) {
    return;
  }
  const showZones = isTagPromptProfile(state.prompt_profile);
  if (!showZones) {
    const text = ($("prompt-general")?.value || "").trim();
    if (state.activeJobsCount <= 0) {
      btn.disabled = !text;
    }
  }
}

async function generate() {
  flushPendingZoneInputs();
  let prompt = composePrompt();
  const showZones = isTagPromptProfile(state.prompt_profile);
  if (!showZones || !prompt) {
    const generalText = $("prompt-general") ? $("prompt-general").value.trim() : "";
    if (generalText && (!showZones || !prompt)) {
      prompt = generalText;
    }
  }
  if (!prompt) {
    updateGenerateButtonState();
    setStatus("El prompt no puede estar vacío", true);
    return;
  }
  const sizePayload = readSizePayload();
  if (
    sizePayload.width != null &&
    (!validSize(sizePayload.width) || !validSize(sizePayload.height))
  ) {
    setStatus("Medidas fuera de [64, 4096] o no múltiplos de 8", true);
    return;
  }
  applyRandomSeed();
  const payload = {
    model_id: $("model").value,
    prompt,
    negative: $("negative").value,
    preprompt: $("preprompt").value,
    rating: $("rating").value,
    loras: readLorasPayload(),
    params: readBaseParams(),
    ...sizePayload,
  };
  const batchEl = $("batch-size");
  const batchSize = batchEl ? Math.min(4, Math.max(1, Number(batchEl.value) || 1)) : 1;
  if (batchSize > 1) {
    payload.batch_size = batchSize;
  }
  const file = $("ref-image").files[0];
  if (file) {
    payload.ref_image_b64 = await readFileBase64(file);
    payload.strength = Number($("strength").value);
  }
  const btn = $("btn-generate");
  if (btn) btn.disabled = true;
  setStatus("Encolando...");
  try {
    const data = await postJson("/api/generate", payload);
    const ids = Array.isArray(data.job_ids) && data.job_ids.length ? data.job_ids : [data.job_id];
    reloadImageViewerFirstPage().catch(() => {});
    await enqueueJobs(ids, { statusFn: setStatus, onDone: reloadImageViewerFirstPage });
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    updateGenerateButtonState();
  }
}



async function applySavedReference(params) {
  const saved = params ? params.ref_image : null;
  const name = typeof saved === "string" ? saved.trim() : "";
  if (!name) {
    if ($("ref-image").files.length) {
      clearReference();
    }
    return;
  }
  try {
    await attachReferenceFromUrl(`/api/refs/${encodeURIComponent(name)}`, name);
  } catch (error) {
    clearReference();
    throw new Error(`referencia guardada no disponible (${error.message})`);
  }
  const strength = Number(params.strength);
  if (Number.isFinite(strength)) {
    const clamped = Math.max(0.05, Math.min(1, strength));
    $("strength").value = String(clamped);
    $("strength-value").textContent = clamped.toFixed(2);
  }
}

async function reuseGeneration(item) {
  if (!item) return;
  const params = item.params || {};
  const isOtherTask = Boolean(params.task === "upscale" || params.task === "editor");
  const isKnownModel = Boolean(
    item.model_id &&
    Array.isArray(state.models) &&
    state.models.some((model) => model.id === item.model_id)
  );
  if (isOtherTask || !isKnownModel) {
    const taskName = isOtherTask
      ? (params.task === "upscale" ? "Upscaler" : "Editor")
      : (params.task || item.model_id || "otra tarea");
    setStatus(`Resultado de ${taskName}; ábrelo en su pestaña`, true);
    return;
  }
  const savedPrompt = String(item.prompt || "");
  if (savedPrompt) {
    const data = await postJson("/api/prompt/zones", { text: savedPrompt });
    applyZonesPayload(data.zones || [], { replace: true });
  } else {
    resetPromptZones();
    renderZoneEditor();
  }
  if (typeof item.negative === "string") {
    $("negative").value = item.negative;
    state.negativeTouched = true;
  }
  const modelId = item.model_id;
  if (modelId && state.models.some((model) => model.id === modelId)) {
    $("model").value = modelId;
    await applyModel(modelId);
  }
  if (typeof params.preprompt === "string") {
    setSelectValue($("preprompt"), params.preprompt);
  }
  if (params.rating === "sfw" || params.rating === "nsfw") {
    $("rating").value = params.rating;
  }
  if (params.seed != null) {
    $("seed").value = params.seed;
  }
  if (params.steps != null) {
    $("steps").value = params.steps;
  }
  if (params.cfg != null) {
    $("cfg").value = params.cfg;
  }
  setSelectValue($("sampler"), params.sampler_name);
  setSelectValue($("scheduler"), params.scheduler);
  if (params.width != null || params.height != null) {
    setSizeFromDefaults(params.width, params.height);
  }
  applyLorasSelection(Array.isArray(params.loras) ? params.loras : []);
  let warning = "";
  try {
    await applySavedReference(params);
  } catch (error) {
    warning = error.message;
  }
  // BUG-IMAGE-01: Usar general_prompt si es string; de lo contrario dejarlo vacío
  const promptGeneral = $("prompt-general");
  if (promptGeneral) {
    promptGeneral.value = typeof params.general_prompt === "string" ? params.general_prompt : "";
  }
  if (warning) {
    setStatus(`Cargado #${item.id} · ${warning}`, true);
  } else {
    setStatus(`Cargado #${item.id}`);
  }
}


function updateReferencePreview() {
  const file = $("ref-image").files[0];
  if (file && state.localFilesOriginalPaths) {
    const originalPath = file.path || file.webkitRelativePath || file.name;
    state.localFilesOriginalPaths.set(file.name, originalPath);
  }
  if (refObjectUrl) {
    URL.revokeObjectURL(refObjectUrl);
    refObjectUrl = null;
  }
  if (!file) {
    $("ref-thumb").removeAttribute("src");
    $("ref-preview").classList.add("hidden");
    return;
  }
  refObjectUrl = URL.createObjectURL(file);
  $("ref-thumb").src = refObjectUrl;
  $("ref-preview").classList.remove("hidden");
}

function clearReference() {
  $("ref-image").value = "";
  updateReferencePreview();
  setStatus("Referencia quitada");
}



function initImageTab() {
  on("btn-enhance", "click", enhancePrompt);
  on("btn-generate", "click", generate);
  on("btn-cancel", "click", cancelJob);
  on("btn-new-generation", "click", () => {
    startNewGeneration().catch((error) => setStatus(error.message, true));
  });
  on("btn-save-to-oc", "click", () => {
    const item = selectedImageView();
    if (!item) {
      return;
    }
    openOcSaveModal(item).catch((error) => setStatus(error.message, true));
  });
  on("btn-negative-restore", "click", restoreNegative);
  on("btn-ref-clear", "click", clearReference);
  on("size", "change", applySizeSelection);
  on("preprompt", "change", () => {
    refreshNegative().catch((error) => setStatus(error.message, true));
  });
  on("negative", "input", () => {
    state.negativeTouched = true;
  });
  on("ref-image", "change", updateReferencePreview);
  on("model", "change", (event) => {
    applyModel(event.target.value).catch((error) => setStatus(error.message, true));
  });
  on("strength", "input", (event) => {
    $("strength-value").textContent = Number(event.target.value).toFixed(2);
  });
  const orient = $("image-res-orientation");
  const qual = $("image-res-quality");
  if (orient && qual) {
    imageResolutionKit = new ResolutionKit({
      orientationSelect: orient,
      qualitySelect: qual,
      widthInput: $("width"),
      heightInput: $("height"),
      badgeEl: $("image-res-badge"),
      onChange: ({ width, height }) => {
        const match = (state.formats || []).find((f) => f.width === width && f.height === height);
        const sizeSelect = $("size");
        if (sizeSelect) {
          sizeSelect.value = match ? match.id : "manual";
        }
      },
    });
  }

  const catPrompting = $("image-cat-prompting");
  const catConfig = $("image-cat-config");
  if (catPrompting && catConfig) {
    catPrompting.addEventListener("toggle", () => {
      if (catPrompting.open) {
        catConfig.open = false;
      }
    });
    catConfig.addEventListener("toggle", () => {
      if (catConfig.open) {
        catPrompting.open = false;
      }
    });
  }
  window.addEventListener("waifu:models-refresh", () => {
    refreshModelsCatalog().catch((err) => console.warn("models refresh:", err));
  });
  window.addEventListener("waifu:queue-updated", () => {
    updateGenerateState();
  });
  on("btn-reload", "click", () => {
    refreshModelsCatalog().catch((err) => console.warn("models reload:", err));
    loadLoras({ preserveSelection: true }).catch((err) =>
      console.warn("loras reload:", err)
    );
  });
}

export {
  loadParams,
  loadFormats,
  applySizeSelection,
  setSizeFromDefaults,
  refreshModelsCatalog,
  loadModels,
  loadPrepromptOptions,
  applyModel,
  applyStartupDefaults,
  readBaseParams,
  validSize,
  readSizePayload,
  refreshNegative,
  restoreNegative,
  refreshLlmStatus,
  enhancePrompt,
  startNewGeneration,
  generate,
  setProgress,
  applySavedReference,
  reuseGeneration,
  updateReferencePreview,
  clearReference,
  initImageTab,
};
