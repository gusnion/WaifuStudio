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
  characterRefs: [],
  ocSaveGenId: null,
};

let enhanceResetTimer = null;
let refObjectUrl = null;
let ocSearchTimer = null;
let promptZonesTimer = null;
let promptZonesSeq = 0;
let zoneInsertTarget = null;

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

async function applyModel(modelId) {
  const model = state.models.find((item) => item.id === modelId);
  if (!model) {
    return;
  }
  state.family = model.family || "anima";
  const data = await api(`/api/preprompts?family=${encodeURIComponent(model.family)}`);
  const select = $("preprompt");
  select.replaceChildren();
  for (const name of data.names) {
    select.appendChild(option(name, name));
  }
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

function openZoneInsert(zone) {
  if (!ZONE_LABELS[zone]) {
    return;
  }
  zoneInsertTarget = zone;
  const input = $("zone-insert-input");
  input.value = "";
  input.placeholder =
    zone === "character"
      ? "Nombre del personaje..."
      : `Tag para ${ZONE_LABELS[zone]}...`;
  $("zone-insert-form").classList.remove("hidden");
  input.focus();
}

function closeZoneInsert() {
  zoneInsertTarget = null;
  $("zone-insert-form").classList.add("hidden");
  $("zone-insert-input").value = "";
}

async function submitZoneInsert(event) {
  event.preventDefault();
  const tag = $("zone-insert-input").value.trim();
  const zone = zoneInsertTarget;
  if (!tag || !zone) {
    return;
  }
  try {
    const data = await postJson("/api/prompt/insert", {
      text: $("prompt").value,
      tag,
      zone,
    });
    $("prompt").value = data.text || "";
    closeZoneInsert();
    await refreshPromptZones();
    setStatus("Tag añadido");
  } catch (error) {
    setStatus(error.message, true);
  }
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
  const select = $("oc-form-preprompt");
  select.replaceChildren();
  for (const name of data.names || []) {
    select.appendChild(option(name, name));
  }
  select.value = data.default || select.value;
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

function fillCharacterForm(character) {
  state.ocEditingId = character ? character.id : null;
  state.ocSelectedTags = character ? [...(character.tags || [])] : [];
  $("oc-form-title").textContent = character
    ? `Editar «${character.name}»`
    : "Guardar OC";
  $("oc-form-name").value = character ? character.name : "";
  if (character) {
    $("oc-form-preprompt").value = character.preprompt;
  }
  $("oc-form-rating").value = character ? character.rating : "sfw";
  $("oc-form-notes").value = character ? character.notes : "";
  renderOcSelected();
  renderOcCatalogResults();
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
  setOcStatus(`Editando «${character.name}»`);
}

async function duplicateCharacter(character) {
  fillCharacterForm(character);
  state.ocEditingId = null;
  $("oc-form-title").textContent = "Guardar OC (copia)";
  $("oc-form-name").value = `${character.name} (copia)`;
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
    fillCharacterForm(null);
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
    } else {
      await api(`/api/characters/${charId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    state.activeCharacterId = charId;
    await loadCharacters();
    fillCharacterForm(characterById(charId));
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

function openOcModal() {
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
  $("negative").addEventListener("input", () => {
    state.negativeTouched = true;
  });
  $("prompt").addEventListener("input", schedulePromptZones);
  for (const chip of document.querySelectorAll(".zone-chip")) {
    chip.addEventListener("click", () => openZoneInsert(chip.dataset.zone));
  }
  $("zone-insert-form").addEventListener("submit", submitZoneInsert);
  $("zone-insert-cancel").addEventListener("click", closeZoneInsert);
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
    fillCharacterForm(null);
    setOcStatus("Nuevo OC");
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
