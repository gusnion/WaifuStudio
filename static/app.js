"use strict";

const GROUP_LABELS = {
  hair: "Pelo",
  eyes: "Ojos",
  face: "Cara",
  body: "Cuerpo",
  outfit: "Vestuario",
  expression: "Expresión",
  accessories: "Accesorios",
  setting: "Entorno",
  action: "Acción",
  meta: "Meta",
};

const ZONE_LABELS = {
  quality: "Calidad/meta",
  safety: "Safety",
  subject: "Sujeto",
  character: "Personaje",
  general: "General",
};

const PAGE_SIZE = 6;

const TRAIN_PAGE = 24;
const TRAIN_MIN = 10;
const TRAIN_MAX = 50;
const TRAIN_TRIGGER_RE = /^[a-z0-9_-]{2,32}$/;

const state = {
  models: [],
  family: "anima",
  params: {
    samplers: [],
    schedulers: [],
    default_sampler: "euler",
    default_scheduler: "sgm_uniform",
  },
  formats: [],
  formatsById: {},
  negativeBase: "",
  negativeTouched: false,
  enhanceResult: null,
  pendingEnhance: false,
  videoNegative: "",
  galleryItems: [],
  videoItems: [],
  imagePager: null,
  videoPager: null,
  activeJobId: null,
  busy: false,
  characters: [],
  activeCharacterId: null,
  ocSelectedTags: [],
  ocCatalogItems: [],
  ocEditingId: null,
  ocPrepromptDefault: "",
  characterRefs: [],
  ocSaveGenId: null,
  loras: [],
  loraControls: {},
  customPreprompts: [],
  trainCharacterId: null,
  trainItems: [],
  trainSelected: new Set(),
  trainOffset: 0,
  trainBusy: false,
  trainJobId: null,
};

let enhanceResetTimer = null;
let refObjectUrl = null;
let ocSearchTimer = null;
let promptZonesTimer = null;
let promptZonesSeq = 0;
let zoneInsertTarget = null;
let zonePopoverOptions = null;
let zonePopoverSubcat = null;
let zonePopoverSelected = new Set();
let zonePopoverSeq = 0;

const $ = (id) => document.getElementById(id);

function setStatus(text, isError = false) {
  const el = $("job-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setVideoStatus(text, isError = false) {
  const el = $("video-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data = null;
  try {
    data = await response.json();
  } catch (_error) {
    data = null;
  }
  if (!response.ok) {
    throw new Error(data && data.error ? data.error : `HTTP ${response.status}`);
  }
  return data;
}

function postJson(path, payload) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function option(value, text) {
  const el = document.createElement("option");
  el.value = value;
  el.textContent = text;
  return el;
}

function setSelectValue(select, value) {
  if (!value) {
    return;
  }
  const exists = Array.from(select.options).some((opt) => opt.value === value);
  if (exists) {
    select.value = value;
  }
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
}

function applySizeSelection() {
  const format = state.formatsById[$("size").value];
  if (format) {
    $("width").value = format.width;
    $("height").value = format.height;
    $("manual-size").classList.add("hidden");
  } else {
    $("manual-size").classList.remove("hidden");
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
}

async function loadModels() {
  state.models = await api("/api/models");
  const select = $("model");
  select.replaceChildren();
  for (const model of state.models) {
    select.appendChild(option(model.id, model.display_name || model.id));
  }
  if (state.models.length) {
    await applyModel(state.models[0].id);
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

async function loadLoras() {
  const family = state.family || "anima";
  const data = await api(`/api/loras?family=${encodeURIComponent(family)}`);
  state.loras = data.items || [];
  renderLoras();
}

function renderLoras() {
  const container = $("loras-list");
  state.loraControls = {};
  container.replaceChildren();
  if (!state.loras.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Aún no hay LoRAs de imagen (llegan con las descargas M10)";
    container.appendChild(empty);
    return;
  }
  for (const lora of state.loras) {
    const row = document.createElement("div");
    row.className = "lora-row";
    const label = document.createElement("label");
    label.className = "lora-check";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.loraId = lora.id;
    const name = document.createElement("span");
    name.textContent = lora.display_name || lora.id;
    name.title = lora.trigger ? `${lora.id} · trigger: ${lora.trigger}` : lora.id;
    label.append(check, name);
    const weightBox = document.createElement("div");
    weightBox.className = "lora-weight";
    const weight = document.createElement("input");
    weight.type = "range";
    weight.min = "0";
    weight.max = "2";
    weight.step = "0.05";
    weight.value = String(lora.default_weight);
    weight.dataset.loraWeight = lora.id;
    const value = document.createElement("output");
    value.className = "lora-weight-value";
    value.textContent = Number(lora.default_weight).toFixed(2);
    weight.addEventListener("input", () => {
      value.textContent = Number(weight.value).toFixed(2);
    });
    weightBox.append(weight, value);
    row.append(label, weightBox);
    container.appendChild(row);
    state.loraControls[lora.id] = { check, weight, value };
  }
}

function readLorasPayload() {
  const selection = [];
  for (const lora of state.loras) {
    const controls = state.loraControls[lora.id];
    if (!controls || !controls.check.checked) {
      continue;
    }
    const weight = Number(controls.weight.value);
    selection.push({
      id: lora.id,
      weight: Number.isFinite(weight) ? weight : lora.default_weight,
    });
  }
  return selection;
}

function applyLorasSelection(loras) {
  const wanted = new Map();
  for (const item of loras || []) {
    if (item && typeof item.id === "string") {
      wanted.set(item.id, Number(item.weight));
    }
  }
  for (const lora of state.loras) {
    const controls = state.loraControls[lora.id];
    if (!controls) {
      continue;
    }
    if (!wanted.has(lora.id)) {
      controls.check.checked = false;
      controls.weight.value = String(lora.default_weight);
      controls.value.textContent = Number(lora.default_weight).toFixed(2);
      continue;
    }
    const weight = wanted.get(lora.id);
    controls.check.checked = true;
    if (Number.isFinite(weight)) {
      controls.weight.value = String(weight);
      controls.value.textContent = weight.toFixed(2);
    }
  }
}

async function applyModel(modelId) {
  const model = state.models.find((item) => item.id === modelId);
  if (!model) {
    return;
  }
  state.family = model.family || "anima";
  const data = await loadPrepromptOptions();
  const select = $("preprompt");
  select.value =
    model.preprompt && data.names.includes(model.preprompt) ? model.preprompt : data.default;
  const defaults = model.defaults || {};
  if (defaults.steps != null) {
    $("steps").value = defaults.steps;
  }
  if (defaults.cfg != null) {
    $("cfg").value = defaults.cfg;
  }
  setSelectValue($("sampler"), defaults.sampler_name);
  setSelectValue($("scheduler"), defaults.scheduler);
  setSizeFromDefaults(defaults.width, defaults.height);
  await loadLoras();
  if (!state.negativeTouched) {
    await refreshNegative();
  }
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

function readFileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || "");
      resolve(text.includes(",") ? text.split(",", 2)[1] : text);
    };
    reader.onerror = () => reject(new Error("No se pudo leer la imagen"));
    reader.readAsDataURL(file);
  });
}

async function refreshNegative() {
  if (state.negativeTouched) {
    return;
  }
  const preprompt = $("preprompt").value || "glossy";
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

function showEnhanceResult(data) {
  $("enhance-positive").textContent = data.positive || "";
  $("enhance-negative").textContent = data.negative || "";
  $("enhance-result").classList.remove("hidden");
}

function hideEnhanceResult() {
  $("enhance-result").classList.add("hidden");
}

function useEnhanceResult() {
  if (!state.enhanceResult) {
    return;
  }
  $("prompt").value = state.enhanceResult.positive || "";
  $("negative").value = state.enhanceResult.negative || "";
  state.negativeTouched = true;
  state.enhanceResult = null;
  hideEnhanceResult();
  refreshPromptZones();
  setStatus("Propuesta aplicada");
}

function discardEnhanceResult() {
  state.enhanceResult = null;
  hideEnhanceResult();
}

async function enhancePrompt() {
  if (state.pendingEnhance) {
    return;
  }
  const text = $("prompt").value.trim();
  if (!text) {
    setStatus("Escribe un prompt para mejorarlo", true);
    return;
  }
  const button = $("btn-enhance");
  state.pendingEnhance = true;
  button.disabled = true;
  button.textContent = "Mejorando…";
  setStatus("Mejorando prompt...");
  try {
    const data = await postJson("/api/enhance", {
      text,
      preprompt: $("preprompt").value,
      rating: $("rating").value,
      strength: $("enhance-strength").value,
    });
    state.enhanceResult = data;
    showEnhanceResult(data);
    button.textContent = "Listo ✓";
    setStatus("Prompt mejorado");
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
        button.textContent = "Mejorar prompt";
      }
    }, 1600);
  }
}

async function generate() {
  if (state.busy) {
    return;
  }
  const prompt = $("prompt").value.trim();
  if (!prompt) {
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
  const file = $("ref-image").files[0];
  if (file) {
    payload.ref_image_b64 = await readFileBase64(file);
    payload.strength = Number($("strength").value);
  }
  state.busy = true;
  $("btn-generate").disabled = true;
  setStatus("Encolando...");
  try {
    const data = await postJson("/api/generate", payload);
    await pollJob(data.job_id);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.busy = false;
    $("btn-generate").disabled = false;
  }
}

function setProgress(progress) {
  const box = $("job-progress");
  const fill = $("job-progress-fill");
  const text = $("job-progress-text");
  if (!progress) {
    box.classList.add("hidden");
    fill.style.width = "0%";
    text.textContent = "paso -/-";
    return;
  }
  const percent = progress.percent == null ? 0 : Number(progress.percent);
  const clamped = Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : 0;
  fill.style.width = `${clamped}%`;
  const step = progress.step == null ? "-" : progress.step;
  const total = progress.total == null ? "-" : progress.total;
  let label = `paso ${step}/${total}`;
  if (progress.node) {
    label += ` · nodo ${progress.node}`;
  }
  text.textContent = label;
  box.classList.remove("hidden");
}

function setCancelVisible(visible) {
  $("btn-cancel").classList.toggle("hidden", !visible);
}

async function cancelJob() {
  const jobId = state.activeJobId;
  if (!jobId) {
    return;
  }
  const button = $("btn-cancel");
  button.disabled = true;
  try {
    await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
    setStatus("Cancelado");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function pollJob(
  jobId,
  statusFn = setStatus,
  onDone = reloadGalleryFirstPage,
  progressFn = setProgress,
  manageCancel = true
) {
  if (manageCancel) {
    state.activeJobId = jobId;
    setCancelVisible(true);
  }
  try {
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (job.status === "queued" || job.status === "running") {
        if (progressFn) {
          progressFn(job.progress);
        }
        statusFn(job.status === "running" ? "Generando..." : "En cola...");
        continue;
      }
      if (job.status === "error") {
        statusFn(`Error: ${job.error || "desconocido"}`, true);
        await onDone();
        return;
      }
      if (job.status === "cancelled") {
        statusFn("Cancelado");
        await onDone();
        return;
      }
      statusFn("Listo");
      await onDone();
      return;
    }
  } finally {
    if (manageCancel) {
      state.activeJobId = null;
      setCancelVisible(false);
    }
    if (progressFn) {
      progressFn(null);
    }
  }
}

function isVideoUrl(url) {
  return /\.(mp4|webm)$/i.test(String(url || ""));
}

function openLightbox(url, alt) {
  const image = $("lightbox-img");
  image.src = url;
  image.alt = alt || "";
  $("lightbox").classList.remove("hidden");
}

function closeLightbox() {
  $("lightbox").classList.add("hidden");
  $("lightbox-img").removeAttribute("src");
}

function reuseGeneration(item) {
  $("prompt").value = item.prompt || "";
  if (typeof item.negative === "string") {
    $("negative").value = item.negative;
    state.negativeTouched = true;
  }
  const params = item.params || {};
  applyLorasSelection(Array.isArray(params.loras) ? params.loras : []);
  refreshPromptZones();
  setStatus(`Reusado #${item.id}`);
}

function galleryCard(item) {
  const card = document.createElement("figure");
  card.className = "card";
  if (item.urls && item.urls.length) {
    const url = item.urls[0];
    if (isVideoUrl(url)) {
      const video = document.createElement("video");
      video.src = url;
      video.controls = true;
      video.preload = "metadata";
      card.appendChild(video);
    } else {
      const img = document.createElement("img");
      img.src = url;
      img.alt = item.prompt || `Generación ${item.id}`;
      img.loading = "lazy";
      img.addEventListener("click", () => openLightbox(url, img.alt));
      card.appendChild(img);
    }
  } else {
    const missing = document.createElement("div");
    missing.className = "card-missing";
    missing.textContent = item.status === "error" ? "Error" : "Sin resultado";
    card.appendChild(missing);
  }
  const params = item.params || {};
  const bits = [];
  if (params.seed != null) {
    bits.push(`seed ${params.seed}`);
  }
  if (params.steps != null) {
    bits.push(`${params.steps} pasos`);
  }
  if (params.cfg != null) {
    bits.push(`cfg ${params.cfg}`);
  }
  if (params.strength != null) {
    bits.push(`fuerza ${params.strength}`);
  }
  if (Array.isArray(params.loras)) {
    for (const lora of params.loras) {
      bits.push(`lora ${lora.id} @ ${lora.weight}`);
    }
  }
  const caption = document.createElement("figcaption");
  const title = document.createElement("strong");
  title.textContent = `#${item.id} · ${item.kind || "image"} · ${item.model_id}`;
  const prompt = document.createElement("span");
  prompt.textContent = item.prompt || "";
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = bits.join(" · ");
  caption.append(title, prompt, meta);
  if (item.kind !== "video") {
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const reuse = document.createElement("button");
    reuse.type = "button";
    reuse.className = "card-action";
    reuse.textContent = "Reusar";
    reuse.addEventListener("click", () => reuseGeneration(item));
    const saveOc = document.createElement("button");
    saveOc.type = "button";
    saveOc.className = "card-action";
    saveOc.textContent = "Guardar en OC";
    saveOc.addEventListener("click", () => {
      openOcSaveModal(item).catch((error) => setStatus(error.message, true));
    });
    actions.append(reuse, saveOc);
    caption.appendChild(actions);
  }
  card.appendChild(caption);
  return card;
}

function renderGallery(container, items, emptyText, pager) {
  container.replaceChildren();
  const total = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  pager.page = Math.min(Math.max(1, pager.page), total);
  const slice = items.slice((pager.page - 1) * PAGE_SIZE, pager.page * PAGE_SIZE);
  if (!slice.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = emptyText;
    container.appendChild(empty);
  } else {
    for (const item of slice) {
      container.appendChild(galleryCard(item));
    }
  }
  pager.label.textContent = `página ${pager.page} de ${total}`;
  pager.prev.disabled = pager.page <= 1;
  pager.next.disabled = pager.page >= total;
}

function renderGalleries() {
  renderGallery(
    $("gallery"),
    state.galleryItems,
    "Sin generaciones todavía.",
    state.imagePager
  );
  renderGallery(
    $("video-gallery"),
    state.videoItems,
    "Sin videos todavía.",
    state.videoPager
  );
}

async function loadGallery() {
  try {
    const data = await api("/api/gallery?limit=24");
    const items = data.items || [];
    state.galleryItems = items.filter((item) => item.kind !== "video");
    state.videoItems = items.filter((item) => item.kind === "video");
    renderGalleries();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function reloadGalleryFirstPage() {
  if (state.imagePager) {
    state.imagePager.page = 1;
  }
  if (state.videoPager) {
    state.videoPager.page = 1;
  }
  await loadGallery();
}

function makePager(prefix) {
  return {
    page: 1,
    prev: $(`${prefix}-prev`),
    next: $(`${prefix}-next`),
    label: $(`${prefix}-page`),
  };
}

function updateReferencePreview() {
  const file = $("ref-image").files[0];
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

async function generateMotion() {
  const text = $("video-motion").value.trim();
  if (!text) {
    setVideoStatus("Escribe el movimiento a generar", true);
    return;
  }
  setVideoStatus("Generando motion...");
  try {
    const data = await postJson("/api/motion", {
      text,
      rating: $("video-rating").value,
    });
    $("video-motion-positive").value = data.motion_positive;
    state.videoNegative = data.motion_negative || "";
    if ($("video-engine").value === "h3" && !$("video-prompt").value.trim()) {
      $("video-prompt").value = data.motion_positive;
    }
    setVideoStatus("Motion listo");
  } catch (error) {
    setVideoStatus(error.message, true);
  }
}

function readVideoSeed() {
  const value = Number($("video-seed").value);
  return Number.isFinite(value) ? Math.trunc(value) : 42;
}

async function generateVideo() {
  if (state.busy) {
    return;
  }
  const engine = $("video-engine").value;
  const file = $("video-image").files[0];
  if (!file) {
    setVideoStatus("Sube la imagen fuente", true);
    return;
  }
  const payload = {
    engine,
    aspect: $("video-aspect").value,
    seed: readVideoSeed(),
  };
  try {
    payload.image_b64 = await readFileBase64(file);
    if (engine === "wan") {
      const positive = $("video-motion-positive").value.trim();
      if (!positive) {
        setVideoStatus("Genera o escribe el motion positivo", true);
        return;
      }
      payload.motion_positive = positive;
      payload.motion_negative = state.videoNegative || "";
    } else {
      const last = $("video-last-image").files[0];
      if (!last) {
        setVideoStatus("H3 requiere el último frame", true);
        return;
      }
      const prompt =
        $("video-prompt").value.trim() || $("video-motion-positive").value.trim();
      if (!prompt) {
        setVideoStatus("H3 requiere el prompt", true);
        return;
      }
      payload.last_image_b64 = await readFileBase64(last);
      payload.prompt = prompt;
    }
  } catch (error) {
    setVideoStatus(error.message, true);
    return;
  }
  state.busy = true;
  $("btn-video-generate").disabled = true;
  setVideoStatus("Encolando...");
  try {
    const data = await postJson("/api/video/generate", payload);
    await pollJob(
      data.job_id,
      setVideoStatus,
      reloadGalleryFirstPage,
      null,
      false
    );
  } catch (error) {
    setVideoStatus(error.message, true);
  } finally {
    state.busy = false;
    $("btn-video-generate").disabled = false;
  }
}

function applyVideoEngine() {
  const isWan = $("video-engine").value === "wan";
  $("video-aspect-field").style.display = isWan ? "" : "none";
  $("video-motion-positive-field").style.display = isWan ? "" : "none";
  $("video-prompt-field").style.display = isWan ? "none" : "";
  $("video-last-field").style.display = isWan ? "none" : "";
}

function setOcStatus(text, isError = false) {
  const el = $("oc-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setOcSaveStatus(text, isError = false) {
  const el = $("oc-save-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function normalizeTags(tags) {
  const merged = [];
  const seen = new Set();
  for (const raw of tags) {
    const tag = String(raw || "").trim();
    if (!tag) {
      continue;
    }
    const folded = tag.toLowerCase();
    if (seen.has(folded)) {
      continue;
    }
    seen.add(folded);
    merged.push(tag);
  }
  return merged;
}

function promptFromTags(tags) {
  return normalizeTags(tags).join(", ");
}

function mergeIntoPrompt(text, addition) {
  return promptFromTags([
    ...String(text || "").split(","),
    ...String(addition || "").split(","),
  ]);
}

function renderPromptZones(zones) {
  const preview = $("prompt-zones-preview");
  const legend = $("prompt-zones-legend");
  preview.replaceChildren();
  legend.replaceChildren();
  let any = false;
  for (const zone of zones) {
    const tags = zone.tags || [];
    for (const tag of tags) {
      if (any) {
        preview.appendChild(document.createTextNode(", "));
      }
      const span = document.createElement("span");
      span.className = `zone-tag zone-${zone.id}`;
      span.textContent = tag;
      preview.appendChild(span);
      any = true;
    }
    const item = document.createElement("span");
    item.className = "zone-legend-item";
    const swatch = document.createElement("span");
    swatch.className = `zone-swatch zone-${zone.id}`;
    const label = document.createElement("span");
    label.textContent = zone.label;
    item.append(swatch, label);
    legend.appendChild(item);
  }
  if (!any) {
    const empty = document.createElement("span");
    empty.className = "empty";
    empty.textContent = "Sin tags todavía.";
    preview.appendChild(empty);
  }
}

async function refreshPromptZones() {
  const text = $("prompt").value;
  const seq = ++promptZonesSeq;
  try {
    const data = await postJson("/api/prompt/zones", { text });
    if (seq !== promptZonesSeq) {
      return;
    }
    renderPromptZones(data.zones || []);
  } catch (error) {
    if (seq === promptZonesSeq) {
      renderPromptZones([]);
    }
  }
}

function schedulePromptZones() {
  if (promptZonesTimer) {
    clearTimeout(promptZonesTimer);
  }
  promptZonesTimer = setTimeout(() => {
    promptZonesTimer = null;
    refreshPromptZones();
  }, 300);
}

function zoneSubcatLocked(subcat) {
  return subcat === "rasgos" && Boolean(state.activeCharacterId);
}

function zonePopoverGroup() {
  if (!zonePopoverOptions) {
    return null;
  }
  if (zoneInsertTarget === "general") {
    return (
      zonePopoverOptions.find((group) => group.id === zonePopoverSubcat) || null
    );
  }
  return zonePopoverOptions[0] || null;
}

function defaultGeneralSubcat() {
  const ids = zonePopoverOptions.map((group) => group.id);
  if (!state.activeCharacterId && ids.includes("rasgos")) {
    return "rasgos";
  }
  const other = ids.find((id) => id !== "rasgos");
  return other || ids[0] || null;
}

function renderZonePopoverTabs() {
  const container = $("zone-popover-tabs");
  container.replaceChildren();
  if (zoneInsertTarget !== "general") {
    return;
  }
  for (const group of zonePopoverOptions || []) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "zone-tab";
    tab.textContent = group.label;
    const locked = zoneSubcatLocked(group.id);
    tab.classList.toggle("active", group.id === zonePopoverSubcat);
    tab.classList.toggle("locked", locked);
    tab.disabled = locked;
    tab.title = locked ? "Fijado por el OC" : group.label;
    if (!locked) {
      tab.addEventListener("click", () => {
        zonePopoverSubcat = group.id;
        renderZonePopoverTabs();
        renderZonePopoverGroups();
      });
    }
    container.appendChild(tab);
  }
}

function renderZonePopoverGroups() {
  const container = $("zone-popover-groups");
  const note = $("zone-popover-note");
  container.replaceChildren();
  const lockedNote =
    zoneInsertTarget === "general" && Boolean(state.activeCharacterId);
  note.classList.toggle("hidden", !lockedNote);
  if (lockedNote) {
    note.textContent =
      "Rasgos fijados por el OC activo (Fijado por el OC): no se editan aquí.";
  }
  const group = zonePopoverGroup();
  if (!group) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent =
      zoneInsertTarget === "character"
        ? "Los personajes (OC) llegan en M9-B3; añade el tag a mano."
        : "Sin opciones.";
    container.appendChild(empty);
    return;
  }
  const query = $("zone-popover-search").value.trim().toLowerCase();
  const tags = (group.tags || []).filter(
    (item) =>
      !query ||
      item.tag.toLowerCase().includes(query) ||
      String(item.label || "").toLowerCase().includes(query)
  );
  if (!tags.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin resultados.";
    container.appendChild(empty);
    return;
  }
  for (const item of tags) {
    const row = document.createElement("label");
    row.className = "zone-option";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = zonePopoverSelected.has(item.tag);
    box.addEventListener("change", () => {
      if (box.checked) {
        zonePopoverSelected.add(item.tag);
      } else {
        zonePopoverSelected.delete(item.tag);
      }
      renderZonePopoverSelected();
    });
    const text = document.createElement("span");
    text.className = "zone-option-text";
    text.textContent = item.tag;
    const label = document.createElement("span");
    label.className = "zone-option-label";
    label.textContent = item.label || item.tag;
    row.append(box, text, label);
    container.appendChild(row);
  }
}

function renderZonePopoverSelected() {
  const container = $("zone-popover-selected");
  container.replaceChildren();
  if (!zonePopoverSelected.size) {
    const empty = document.createElement("span");
    empty.className = "empty";
    empty.textContent = "Sin selección.";
    container.appendChild(empty);
    return;
  }
  for (const tag of zonePopoverSelected) {
    const chip = document.createElement("span");
    chip.className = "zone-selected-chip";
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "zone-selected-remove";
    remove.textContent = "×";
    remove.title = "Quitar";
    remove.addEventListener("click", () => {
      zonePopoverSelected.delete(tag);
      renderZonePopoverSelected();
      renderZonePopoverGroups();
    });
    chip.append(text, remove);
    container.appendChild(chip);
  }
}

async function openZoneInsert(zone) {
  if (!ZONE_LABELS[zone]) {
    return;
  }
  zoneInsertTarget = zone;
  zonePopoverOptions = null;
  zonePopoverSubcat = null;
  zonePopoverSelected = new Set();
  $("zone-popover").classList.remove("hidden");
  $("zone-popover-title").textContent = ZONE_LABELS[zone];
  $("zone-popover-search").value = "";
  $("zone-popover-note").classList.add("hidden");
  $("zone-insert-input").value = "";
  $("zone-popover-tabs").replaceChildren();
  $("zone-popover-groups").replaceChildren();
  renderZonePopoverSelected();
  const seq = ++zonePopoverSeq;
  try {
    const data = await api(
      `/api/prompt/options?zone=${encodeURIComponent(zone)}`
    );
    if (seq !== zonePopoverSeq || zoneInsertTarget !== zone) {
      return;
    }
    zonePopoverOptions = data.subgroups || [];
    if (zone === "general") {
      zonePopoverSubcat = defaultGeneralSubcat();
    }
    renderZonePopoverTabs();
    renderZonePopoverGroups();
  } catch (error) {
    if (seq === zonePopoverSeq) {
      setStatus(error.message, true);
    }
  }
}

function closeZoneInsert() {
  zoneInsertTarget = null;
  zonePopoverOptions = null;
  zonePopoverSubcat = null;
  zonePopoverSelected = new Set();
  $("zone-popover").classList.add("hidden");
  $("zone-popover-search").value = "";
  $("zone-popover-tabs").replaceChildren();
  $("zone-popover-groups").replaceChildren();
  $("zone-popover-selected").replaceChildren();
  $("zone-popover-note").classList.add("hidden");
  $("zone-insert-input").value = "";
}

function submitZoneInsert(event) {
  event.preventDefault();
  const input = $("zone-insert-input");
  const raw = input.value.trim();
  if (!raw || !zoneInsertTarget) {
    return;
  }
  for (const part of raw.split(",")) {
    const tag = part.trim();
    if (tag) {
      zonePopoverSelected.add(tag);
    }
  }
  input.value = "";
  renderZonePopoverSelected();
  renderZonePopoverGroups();
}

function clearZoneSelection() {
  zonePopoverSelected = new Set();
  renderZonePopoverSelected();
  renderZonePopoverGroups();
}

async function insertZoneSelection() {
  const zone = zoneInsertTarget;
  const tags = Array.from(zonePopoverSelected);
  if (!zone) {
    return;
  }
  if (!tags.length) {
    setStatus("Selecciona o añade algún tag antes de insertar", true);
    return;
  }
  let text = $("prompt").value;
  for (const tag of tags) {
    const data = await postJson("/api/prompt/insert", { text, tag, zone });
    text = data.text || text;
  }
  $("prompt").value = text;
  closeZoneInsert();
  await refreshPromptZones();
  setStatus(`Insertados ${tags.length} tag(s)`);
}

async function attachReferenceFromUrl(url, name) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`No se pudo cargar la referencia (HTTP ${response.status})`);
  }
  const blob = await response.blob();
  const file = new File([blob], name || "reference.png", {
    type: blob.type || "image/png",
  });
  const transfer = new DataTransfer();
  transfer.items.add(file);
  $("ref-image").files = transfer.files;
  updateReferencePreview();
}

function isOcTagSelected(tag) {
  const folded = tag.toLowerCase();
  return state.ocSelectedTags.some((item) => item.toLowerCase() === folded);
}

function renderOcCatalogResults() {
  const container = $("oc-catalog-results");
  container.replaceChildren();
  if (!state.ocCatalogItems.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin resultados.";
    container.appendChild(empty);
    return;
  }
  for (const item of state.ocCatalogItems) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "oc-chip";
    chip.textContent =
      item.label && item.label !== item.tag
        ? `${item.label} · ${item.tag}`
        : item.tag;
    chip.title = item.tag;
    chip.classList.toggle("selected", isOcTagSelected(item.tag));
    chip.addEventListener("click", () => toggleOcTag(item.tag));
    container.appendChild(chip);
  }
}

function renderOcSelected() {
  const container = $("oc-selected");
  container.replaceChildren();
  if (!state.ocSelectedTags.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Ningún tag seleccionado.";
    container.appendChild(empty);
    return;
  }
  for (const tag of state.ocSelectedTags) {
    const chip = document.createElement("span");
    chip.className = "oc-selected-chip";
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "quitar";
    remove.addEventListener("click", () => toggleOcTag(tag));
    chip.append(text, remove);
    container.appendChild(chip);
  }
}

async function refreshOcCatalog() {
  const params = new URLSearchParams();
  const group = $("oc-catalog-group").value;
  const query = $("oc-catalog-search").value.trim();
  if (group) {
    params.set("group", group);
  }
  if (query) {
    params.set("q", query);
  }
  if (!group && !query) {
    params.set("limit", "60");
  }
  const data = await api(`/api/tags?${params.toString()}`);
  state.ocCatalogItems = data.items || [];
  renderOcCatalogResults();
}

async function loadOcCatalog() {
  const data = await api("/api/tags/groups");
  const select = $("oc-catalog-group");
  select.replaceChildren();
  select.appendChild(option("", "Todos los grupos"));
  for (const group of data.groups || []) {
    select.appendChild(option(group, GROUP_LABELS[group] || group));
  }
  await refreshOcCatalog();
}

async function loadOcPreprompts() {
  const family = state.family || "anima";
  const data = await api(`/api/preprompts?family=${encodeURIComponent(family)}`);
  const custom = new Set(data.custom || []);
  const select = $("oc-form-preprompt");
  select.replaceChildren();
  for (const name of data.names || []) {
    select.appendChild(option(name, custom.has(name) ? `${name} (propio)` : name));
  }
  state.ocPrepromptDefault = data.default || "";
  select.value = data.default || select.value;
}

function setPrepromptStatus(text, isError = false) {
  const el = $("preprompt-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function customPrepromptRow(name) {
  const row = document.createElement("div");
  row.className = "oc-item";
  const header = document.createElement("div");
  header.className = "oc-item-header";
  const title = document.createElement("strong");
  title.textContent = `${name} (propio)`;
  header.appendChild(title);
  const actions = document.createElement("div");
  actions.className = "oc-item-actions";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Borrar";
  remove.addEventListener("click", () => {
    deleteCustomPreprompt(name).catch((error) =>
      setPrepromptStatus(error.message, true)
    );
  });
  actions.appendChild(remove);
  row.append(header, actions);
  return row;
}

async function refreshCustomPreprompts() {
  await loadPrepromptOptions();
  const container = $("preprompt-custom-list");
  container.replaceChildren();
  if (!state.customPreprompts.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin preprompts propios.";
    container.appendChild(empty);
    return;
  }
  for (const name of state.customPreprompts) {
    container.appendChild(customPrepromptRow(name));
  }
}

async function saveCustomPreprompt(event) {
  event.preventDefault();
  try {
    const data = await postJson("/api/preprompts/custom", {
      name: $("preprompt-form-name").value.trim(),
      positive: $("preprompt-form-positive").value,
      negative: $("preprompt-form-negative").value,
    });
    await refreshCustomPreprompts();
    setSelectValue($("preprompt"), data.name);
    await refreshNegative();
    $("preprompt-form").reset();
    setPrepromptStatus(`Preprompt «${data.name}» guardado (propio)`);
  } catch (error) {
    setPrepromptStatus(error.message, true);
  }
}

async function deleteCustomPreprompt(name) {
  if (!window.confirm(`¿Borrar el preprompt propio «${name}»?`)) {
    return;
  }
  await api(`/api/preprompts/custom/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  await refreshCustomPreprompts();
  await refreshNegative();
  setPrepromptStatus(`Preprompt «${name}» borrado`);
}

function openPrepromptModal() {
  $("preprompt-modal").classList.remove("hidden");
  setPrepromptStatus("Listo");
  refreshCustomPreprompts().catch((error) =>
    setPrepromptStatus(error.message, true)
  );
}

function closePrepromptModal() {
  $("preprompt-modal").classList.add("hidden");
}

function toggleOcTag(tag) {
  const folded = tag.toLowerCase();
  const index = state.ocSelectedTags.findIndex(
    (item) => item.toLowerCase() === folded
  );
  if (index >= 0) {
    state.ocSelectedTags.splice(index, 1);
  } else {
    state.ocSelectedTags.push(tag);
  }
  renderOcSelected();
  renderOcCatalogResults();
}

function characterById(charId) {
  return state.characters.find((item) => item.id === charId) || null;
}

function renderCharacters() {
  const container = $("oc-list");
  container.replaceChildren();
  if (!state.characters.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin OCs guardados.";
    container.appendChild(empty);
    return;
  }
  for (const character of state.characters) {
    container.appendChild(characterRow(character));
  }
}

function characterRow(character) {
  const row = document.createElement("div");
  row.className = "oc-item";
  row.classList.toggle("active", character.id === state.activeCharacterId);
  const header = document.createElement("div");
  header.className = "oc-item-header";
  const name = document.createElement("strong");
  name.textContent = character.name;
  header.appendChild(name);
  if (character.id === state.activeCharacterId) {
    const badge = document.createElement("span");
    badge.className = "oc-item-badge";
    badge.textContent = "activo";
    header.appendChild(badge);
  }
  const tags = document.createElement("span");
  tags.className = "oc-item-tags";
  tags.textContent = (character.tags || []).join(", ") || "sin tags";
  const actions = document.createElement("div");
  actions.className = "oc-item-actions";
  const handlers = [
    ["Usar", () => useCharacter(character)],
    ["Generar LoRA", () => openTrainModal(character)],
    ["Editar", () => editCharacter(character)],
    ["Duplicar", () => duplicateCharacter(character)],
    ["Eliminar", () => deleteCharacter(character)],
  ];
  for (const [label, handler] of handlers) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => {
      Promise.resolve(handler()).catch((error) =>
        setOcStatus(error.message, true)
      );
    });
    actions.appendChild(button);
  }
  row.append(header, tags, actions);
  return row;
}

async function loadCharacters() {
  state.characters = await api("/api/characters");
  if (
    state.activeCharacterId != null &&
    !state.characters.some((item) => item.id === state.activeCharacterId)
  ) {
    state.activeCharacterId = null;
  }
  renderCharacters();
}

function isOcEditing() {
  return state.ocEditingId != null;
}

function updateOcFormMode() {
  const editing = isOcEditing();
  const character = editing ? characterById(state.ocEditingId) : null;
  $("oc-form-title").textContent = editing
    ? `Editando: ${character ? character.name : "OC"}`
    : "Crear OC";
  $("btn-oc-save").textContent = editing ? "Guardar cambios" : "Guardar OC";
  $("btn-oc-cancel-edit").classList.toggle("hidden", !editing);
  $("oc-form").classList.toggle("editing", editing);
}

function resetOcForm() {
  state.ocEditingId = null;
  state.ocSelectedTags = [];
  $("oc-form-name").value = "";
  const preprompt = $("oc-form-preprompt");
  preprompt.value =
    state.ocPrepromptDefault ||
    (preprompt.options.length ? preprompt.options[0].value : "");
  $("oc-form-rating").value = "sfw";
  $("oc-form-notes").value = "";
  updateOcFormMode();
  renderOcSelected();
  renderOcCatalogResults();
}

function fillCharacterForm(character) {
  if (!character) {
    resetOcForm();
    return;
  }
  state.ocEditingId = character.id;
  state.ocSelectedTags = [...(character.tags || [])];
  $("oc-form-name").value = character.name;
  $("oc-form-preprompt").value = character.preprompt;
  $("oc-form-rating").value = character.rating;
  $("oc-form-notes").value = character.notes;
  updateOcFormMode();
  renderOcSelected();
  renderOcCatalogResults();
}

async function startNewOc() {
  resetOcForm();
  await loadCharacterRefs();
  setOcStatus("Modo crear: nuevo OC");
}

async function cancelOcEdit() {
  resetOcForm();
  await loadCharacterRefs();
  setOcStatus("Edición cancelada: modo crear");
}

async function useCharacter(character) {
  const addition = promptFromTags(character.tags || []);
  const current = $("prompt").value.trim();
  if (addition) {
    $("prompt").value = current
      ? mergeIntoPrompt(current, addition)
      : addition;
  }
  refreshPromptZones();
  $("preprompt").value = character.preprompt;
  $("rating").value = character.rating;
  state.activeCharacterId = character.id;
  renderCharacters();
  await loadCharacterRefs();
  if (!state.negativeTouched) {
    await refreshNegative();
  }
  const refs = state.characterRefs || [];
  if (refs.length) {
    await attachReferenceFromUrl(refs[0].url, refs[0].url.split("/").pop());
  }
  closeOcModal();
  setStatus(`OC «${character.name}» cargado`);
}

async function editCharacter(character) {
  fillCharacterForm(character);
  setOcStatus(`Editando: ${character.name}`);
}

async function duplicateCharacter(character) {
  fillCharacterForm(character);
  state.ocEditingId = null;
  $("oc-form-name").value = `${character.name} (copia)`;
  updateOcFormMode();
  setOcStatus("Ajusta el nombre y guarda la copia");
}

async function deleteCharacter(character) {
  if (!window.confirm(`¿Eliminar el OC «${character.name}» y sus referencias?`)) {
    return;
  }
  await api(`/api/characters/${character.id}`, { method: "DELETE" });
  if (state.activeCharacterId === character.id) {
    state.activeCharacterId = null;
  }
  if (state.ocEditingId === character.id) {
    resetOcForm();
  }
  await loadCharacters();
  await loadCharacterRefs();
  setOcStatus(`OC «${character.name}» eliminado`);
}

async function saveCharacter(event) {
  event.preventDefault();
  const name = $("oc-form-name").value.trim();
  if (!name) {
    setOcStatus("El nombre es obligatorio", true);
    return;
  }
  const payload = {
    name,
    tags: state.ocSelectedTags.slice(),
    preprompt: $("oc-form-preprompt").value,
    rating: $("oc-form-rating").value,
    notes: $("oc-form-notes").value,
  };
  try {
    let charId = state.ocEditingId;
    if (charId == null) {
      const created = await postJson("/api/characters", payload);
      charId = created.id;
      state.activeCharacterId = charId;
    } else {
      await api(`/api/characters/${charId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    await loadCharacters();
    resetOcForm();
    await loadCharacterRefs();
    setOcStatus(`OC «${name}» guardado`);
  } catch (error) {
    setOcStatus(error.message, true);
  }
}

async function loadCharacterRefs() {
  const container = $("oc-refs");
  const title = $("oc-refs-title");
  const button = $("btn-oc-sheet");
  container.replaceChildren();
  state.characterRefs = [];
  if (state.activeCharacterId == null) {
    title.textContent = "sin OC activo";
    button.disabled = true;
    return;
  }
  const character = characterById(state.activeCharacterId);
  const refs = await api(`/api/characters/${state.activeCharacterId}/refs`);
  state.characterRefs = refs;
  title.textContent = character ? `de ${character.name}` : "";
  button.disabled = refs.length < 2;
  if (!refs.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin referencias. Añádelas desde la galería.";
    container.appendChild(empty);
    return;
  }
  for (const ref of refs) {
    const figure = document.createElement("figure");
    figure.className = "oc-ref";
    const img = document.createElement("img");
    img.src = ref.url;
    img.alt = `Referencia ${ref.id}`;
    img.loading = "lazy";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Quitar";
    remove.addEventListener("click", () => {
      removeCharacterRef(ref).catch((error) =>
        setOcStatus(error.message, true)
      );
    });
    figure.append(img, remove);
    container.appendChild(figure);
  }
}

async function removeCharacterRef(ref) {
  await api(`/api/characters/${ref.character_id}/refs/${ref.id}`, {
    method: "DELETE",
  });
  await loadCharacterRefs();
  setOcStatus("Referencia quitada");
}

async function createCharacterSheet() {
  if (state.activeCharacterId == null) {
    return;
  }
  const button = $("btn-oc-sheet");
  button.disabled = true;
  setOcStatus("Creando hoja...");
  try {
    const data = await postJson(
      `/api/characters/${state.activeCharacterId}/sheet`,
      {}
    );
    await attachReferenceFromUrl(
      data.url,
      `sheet_${state.activeCharacterId}.png`
    );
    await loadCharacterRefs();
    closeOcModal();
    setStatus("Hoja de referencia adjuntada al panel");
  } catch (error) {
    setOcStatus(error.message, true);
    button.disabled = state.characterRefs.length < 2;
  }
}

function addOcTagsToPrompt() {
  if (!state.ocSelectedTags.length) {
    setOcStatus("Selecciona al menos un tag del catálogo", true);
    return;
  }
  const addition = promptFromTags(state.ocSelectedTags);
  const current = $("prompt").value.trim();
  $("prompt").value = current ? mergeIntoPrompt(current, addition) : addition;
  refreshPromptZones();
  closeOcModal();
  setStatus("Tags añadidos al prompt");
}

async function openOcSaveModal(item) {
  state.ocSaveGenId = item.id;
  setOcSaveStatus(`Imagen #${item.id}`);
  $("oc-save-name").value = "";
  await loadCharacters();
  const select = $("oc-save-select");
  select.replaceChildren();
  select.appendChild(option("", "— elegir OC —"));
  for (const character of state.characters) {
    select.appendChild(option(String(character.id), character.name));
  }
  if (state.activeCharacterId != null) {
    select.value = String(state.activeCharacterId);
  }
  $("oc-save-modal").classList.remove("hidden");
}

function closeOcSaveModal() {
  $("oc-save-modal").classList.add("hidden");
  state.ocSaveGenId = null;
}

async function confirmOcSave() {
  const genId = state.ocSaveGenId;
  if (genId == null) {
    return;
  }
  const button = $("btn-oc-save-confirm");
  button.disabled = true;
  try {
    let charId = $("oc-save-select").value
      ? Number($("oc-save-select").value)
      : null;
    const newName = $("oc-save-name").value.trim();
    if (newName) {
      const created = await postJson("/api/characters", {
        name: newName,
        tags: [],
      });
      charId = created.id;
    }
    if (charId == null) {
      setOcSaveStatus("Elige un OC o escribe un nombre nuevo", true);
      return;
    }
    await postJson(`/api/characters/${charId}/refs`, { gen_id: genId });
    await loadCharacters();
    if (state.activeCharacterId === charId) {
      await loadCharacterRefs();
    }
    closeOcSaveModal();
    setStatus("Referencia guardada en el OC");
  } catch (error) {
    setOcSaveStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function setTrainStatus(text, isError = false) {
  const el = $("oc-train-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function validTrainTrigger(trigger) {
  return TRAIN_TRIGGER_RE.test(trigger);
}

function readTrainEpochs() {
  const value = Number($("train-epochs").value);
  return Number.isInteger(value) ? value : NaN;
}

function updateTrainControls() {
  const count = state.trainSelected.size;
  $("train-counter").textContent =
    `${count} seleccionadas (mín. ${TRAIN_MIN}, máx. ${TRAIN_MAX})`;
  const trigger = $("train-trigger").value.trim();
  const triggerOk = validTrainTrigger(trigger);
  $("train-trigger-hint").classList.toggle("error", Boolean(trigger) && !triggerOk);
  const epochs = readTrainEpochs();
  const epochsOk = epochs >= 5 && epochs <= 30;
  $("btn-train-start").disabled =
    state.trainBusy ||
    count < TRAIN_MIN ||
    count > TRAIN_MAX ||
    !triggerOk ||
    !epochsOk;
}

function trainGalleryItem(item) {
  const figure = document.createElement("figure");
  figure.className = "train-item";
  figure.classList.toggle("selected", state.trainSelected.has(item.id));
  const label = document.createElement("label");
  label.className = "train-check";
  const check = document.createElement("input");
  check.type = "checkbox";
  check.checked = state.trainSelected.has(item.id);
  check.addEventListener("change", () => {
    if (check.checked) {
      state.trainSelected.add(item.id);
    } else {
      state.trainSelected.delete(item.id);
    }
    figure.classList.toggle("selected", check.checked);
    updateTrainControls();
  });
  const img = document.createElement("img");
  img.src = (item.urls && item.urls[0]) || "";
  img.alt = item.prompt || `Imagen #${item.id}`;
  img.loading = "lazy";
  label.append(check, img);
  const idTag = document.createElement("span");
  idTag.className = "train-item-id";
  idTag.textContent = `#${item.id}`;
  figure.append(label, idTag);
  return figure;
}

function renderTrainGallery() {
  const container = $("train-gallery");
  container.replaceChildren();
  if (!state.trainItems.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin imágenes listas en la galería.";
    container.appendChild(empty);
    return;
  }
  for (const item of state.trainItems) {
    container.appendChild(trainGalleryItem(item));
  }
}

async function loadTrainGalleryPage() {
  const data = await api(
    `/api/gallery?limit=${TRAIN_PAGE}&offset=${state.trainOffset}`
  );
  const raw = data.items || [];
  const seen = new Set(state.trainItems.map((item) => item.id));
  for (const item of raw) {
    if (item.kind === "image" && item.status === "done" && !seen.has(item.id)) {
      state.trainItems.push(item);
      seen.add(item.id);
    }
  }
  state.trainOffset += TRAIN_PAGE;
  $("btn-train-more").classList.toggle(
    "hidden",
    state.trainOffset >= (data.count || 0)
  );
  renderTrainGallery();
  updateTrainControls();
}

function openTrainModal(character) {
  state.trainCharacterId = character.id;
  state.trainItems = [];
  state.trainSelected = new Set();
  state.trainOffset = 0;
  state.trainJobId = null;
  $("oc-train-title").textContent = `Entrenar LoRA de ${character.name}`;
  $("train-rank").value = "16";
  $("train-epochs").value = "10";
  $("train-trigger").value = `oc_${character.id}`;
  $("train-gallery").replaceChildren();
  $("btn-train-more").classList.add("hidden");
  $("oc-train-modal").classList.remove("hidden");
  updateTrainControls();
  setTrainStatus("Cargando galería...");
  loadTrainGalleryPage()
    .then(() => setTrainStatus(`Elige entre ${TRAIN_MIN} y ${TRAIN_MAX} imágenes`))
    .catch((error) => setTrainStatus(error.message, true));
}

function closeTrainModal() {
  $("oc-train-modal").classList.add("hidden");
}

function setTrainProgress(progress) {
  const box = $("train-progress");
  const fill = $("train-progress-fill");
  const text = $("train-progress-text");
  const percent = progress && progress.percent != null ? Number(progress.percent) : null;
  if (percent == null || !Number.isFinite(percent)) {
    box.classList.add("hidden");
    fill.style.width = "0%";
    text.textContent = "paso -/-";
    return;
  }
  fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  const step = progress.step == null ? "-" : progress.step;
  const total = progress.total == null ? "-" : progress.total;
  text.textContent = `paso ${step}/${total}`;
  box.classList.remove("hidden");
}

function trainJobStatus(text, isError = false) {
  setTrainStatus(text === "Generando..." ? "Entrenando..." : text, isError);
}

async function startTrain() {
  if (state.trainBusy || state.trainCharacterId == null) {
    return;
  }
  const trigger = $("train-trigger").value.trim();
  const epochs = readTrainEpochs();
  const genIds = state.trainItems
    .filter((item) => state.trainSelected.has(item.id))
    .map((item) => item.id);
  if (genIds.length < TRAIN_MIN || genIds.length > TRAIN_MAX) {
    setTrainStatus(`Elige entre ${TRAIN_MIN} y ${TRAIN_MAX} imágenes`, true);
    return;
  }
  if (!validTrainTrigger(trigger)) {
    setTrainStatus("Trigger inválido: solo [a-z0-9_-]{2,32}", true);
    return;
  }
  if (!(epochs >= 5 && epochs <= 30)) {
    setTrainStatus("Epochs fuera de [5, 30]", true);
    return;
  }
  state.trainBusy = true;
  updateTrainControls();
  setTrainStatus("Encolando...");
  try {
    const data = await postJson(
      `/api/characters/${state.trainCharacterId}/train`,
      {
        gen_ids: genIds,
        rank: Number($("train-rank").value),
        epochs,
        trigger,
      }
    );
    state.trainJobId = data.job_id;
    const jobId = data.job_id;
    await pollJob(
      jobId,
      trainJobStatus,
      async () => {
        const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (job.status === "done") {
          const outputs = job.outputs || [];
          setTrainStatus(
            outputs.length ? `LoRA listo: ${outputs[0].name}` : "LoRA listo"
          );
          await loadLoras();
        }
      },
      setTrainProgress,
      false
    );
  } catch (error) {
    setTrainStatus(error.message, true);
  } finally {
    state.trainBusy = false;
    updateTrainControls();
  }
}

function openOcModal() {
  resetOcForm();
  setOcStatus("Modo crear: formulario limpio");
  $("oc-modal").classList.remove("hidden");
  loadCharacters()
    .then(loadCharacterRefs)
    .catch((error) => setOcStatus(error.message, true));
}

function closeOcModal() {
  $("oc-modal").classList.add("hidden");
}

function switchTab(tab) {
  const image = tab === "image";
  $("tab-image").classList.toggle("active", image);
  $("tab-video").classList.toggle("active", !image);
  $("panel-image").classList.toggle("active", image);
  $("panel-video").classList.toggle("active", !image);
}

function bind() {
  state.imagePager = makePager("gallery");
  state.videoPager = makePager("video-gallery");
  $("tab-image").addEventListener("click", () => switchTab("image"));
  $("tab-video").addEventListener("click", () => switchTab("video"));
  $("btn-enhance").addEventListener("click", enhancePrompt);
  $("btn-enhance-use").addEventListener("click", useEnhanceResult);
  $("btn-enhance-discard").addEventListener("click", discardEnhanceResult);
  $("btn-generate").addEventListener("click", generate);
  $("btn-cancel").addEventListener("click", cancelJob);
  $("btn-negative-restore").addEventListener("click", restoreNegative);
  $("btn-ref-clear").addEventListener("click", clearReference);
  $("btn-lightbox-close").addEventListener("click", closeLightbox);
  $("lightbox").addEventListener("click", (event) => {
    if (event.target === $("lightbox")) {
      closeLightbox();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeLightbox();
      closePrepromptModal();
      if (!$("oc-train-modal").classList.contains("hidden")) {
        closeTrainModal();
        return;
      }
      closeOcModal();
    }
  });
  $("gallery-prev").addEventListener("click", () => {
    state.imagePager.page -= 1;
    renderGalleries();
  });
  $("gallery-next").addEventListener("click", () => {
    state.imagePager.page += 1;
    renderGalleries();
  });
  $("video-gallery-prev").addEventListener("click", () => {
    state.videoPager.page -= 1;
    renderGalleries();
  });
  $("video-gallery-next").addEventListener("click", () => {
    state.videoPager.page += 1;
    renderGalleries();
  });
  $("btn-reload").addEventListener("click", () => {
    state.imagePager.page = 1;
    loadGallery();
  });
  $("btn-video-reload").addEventListener("click", () => {
    state.videoPager.page = 1;
    loadGallery();
  });
  $("btn-motion").addEventListener("click", generateMotion);
  $("btn-video-generate").addEventListener("click", generateVideo);
  $("video-engine").addEventListener("change", applyVideoEngine);
  $("size").addEventListener("change", applySizeSelection);
  $("preprompt").addEventListener("change", () => {
    refreshNegative().catch((error) => setStatus(error.message, true));
  });
  $("btn-preprompt-manage").addEventListener("click", openPrepromptModal);
  $("btn-preprompt-close").addEventListener("click", closePrepromptModal);
  $("preprompt-form").addEventListener("submit", saveCustomPreprompt);
  $("preprompt-modal").addEventListener("click", (event) => {
    if (event.target === $("preprompt-modal")) {
      closePrepromptModal();
    }
  });
  $("negative").addEventListener("input", () => {
    state.negativeTouched = true;
  });
  $("prompt").addEventListener("input", schedulePromptZones);
  for (const chip of document.querySelectorAll(".zone-chip")) {
    chip.addEventListener("click", () => {
      openZoneInsert(chip.dataset.zone).catch((error) =>
        setStatus(error.message, true)
      );
    });
  }
  $("zone-insert-form").addEventListener("submit", submitZoneInsert);
  $("zone-insert-cancel").addEventListener("click", closeZoneInsert);
  $("zone-popover-close").addEventListener("click", closeZoneInsert);
  $("zone-popover-search").addEventListener("input", renderZonePopoverGroups);
  $("zone-popover-insert").addEventListener("click", () => {
    insertZoneSelection().catch((error) => setStatus(error.message, true));
  });
  $("zone-popover-clear").addEventListener("click", clearZoneSelection);
  $("ref-image").addEventListener("change", updateReferencePreview);
  $("model").addEventListener("change", (event) => {
    applyModel(event.target.value).catch((error) => setStatus(error.message, true));
  });
  $("strength").addEventListener("input", (event) => {
    $("strength-value").textContent = Number(event.target.value).toFixed(2);
  });
  $("btn-oc").addEventListener("click", openOcModal);
  $("btn-oc-close").addEventListener("click", closeOcModal);
  $("btn-oc-add").addEventListener("click", addOcTagsToPrompt);
  $("oc-modal").addEventListener("click", (event) => {
    if (event.target === $("oc-modal")) {
      closeOcModal();
    }
  });
  $("oc-catalog-group").addEventListener("change", () => {
    refreshOcCatalog().catch((error) => setOcStatus(error.message, true));
  });
  $("oc-catalog-search").addEventListener("input", () => {
    if (ocSearchTimer) {
      clearTimeout(ocSearchTimer);
    }
    ocSearchTimer = setTimeout(() => {
      refreshOcCatalog().catch((error) => setOcStatus(error.message, true));
    }, 250);
  });
  $("oc-form").addEventListener("submit", saveCharacter);
  $("btn-oc-new").addEventListener("click", () => {
    startNewOc().catch((error) => setOcStatus(error.message, true));
  });
  $("btn-oc-cancel-edit").addEventListener("click", () => {
    cancelOcEdit().catch((error) => setOcStatus(error.message, true));
  });
  $("btn-oc-sheet").addEventListener("click", () => {
    createCharacterSheet().catch((error) => setOcStatus(error.message, true));
  });
  $("btn-oc-save-close").addEventListener("click", closeOcSaveModal);
  $("btn-oc-save-confirm").addEventListener("click", () => {
    confirmOcSave().catch((error) => setOcSaveStatus(error.message, true));
  });
  $("oc-save-modal").addEventListener("click", (event) => {
    if (event.target === $("oc-save-modal")) {
      closeOcSaveModal();
    }
  });
  $("btn-oc-train-close").addEventListener("click", closeTrainModal);
  $("oc-train-modal").addEventListener("click", (event) => {
    if (event.target === $("oc-train-modal")) {
      closeTrainModal();
    }
  });
  $("btn-train-more").addEventListener("click", () => {
    loadTrainGalleryPage().catch((error) => setTrainStatus(error.message, true));
  });
  $("btn-train-start").addEventListener("click", () => {
    startTrain().catch((error) => setTrainStatus(error.message, true));
  });
  $("train-rank").addEventListener("change", updateTrainControls);
  $("train-epochs").addEventListener("input", updateTrainControls);
  $("train-trigger").addEventListener("input", updateTrainControls);
}

async function init() {
  bind();
  applyVideoEngine();
  try {
    await loadParams();
    await loadFormats();
    await loadModels();
    await loadOcCatalog();
    await loadOcPreprompts();
    await loadCharacters();
    await refreshNegative();
    await loadGallery();
    await refreshPromptZones();
    setStatus("Listo");
  } catch (error) {
    setStatus(error.message, true);
  }
}

document.addEventListener("DOMContentLoaded", init);
