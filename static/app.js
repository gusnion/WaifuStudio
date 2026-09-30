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

const ZONE_ORDER = ["quality", "safety", "subject", "character", "general"];

const GENERAL_SUBCATS = [
  "rasgos",
  "ropa",
  "accesorios",
  "accion",
  "poses",
  "poses_sexuales",
  "poses_sexys",
  "expresion",
  "expresiones_nsfw",
  "camara",
  "fondo",
];

const GENERAL_SUBCAT_LABELS = {
  rasgos: "Rasgos",
  ropa: "Ropa",
  accesorios: "Accesorios",
  accion: "Acción/Pose",
  poses: "Poses",
  poses_sexuales: "Poses sexuales",
  poses_sexys: "Poses sexys",
  expresion: "Expresión",
  expresiones_nsfw: "Expresiones NSFW",
  camara: "Cámara",
  fondo: "Fondo/Escena",
};

const GENERAL_SUBCAT_FALLBACK = "fondo";

const PAGE_SIZE = 6;
const IMAGE_PAGE_SIZE = 5;
const VIDEO_PAGE_SIZE = 5;
const VIDEO_FPS = 16;
const H3_FPS = 24;
const H3_FRAME_BASE = 5;
const H3_FRAME_STEP = 17;

const H3_PROMPT_TEMPLATE = [
  "integrated_multimodal_description:",
  "overall_soundscape:",
  "non_diegetic_music: None",
].join("\n");

const H3_GUIDE_TEXT = [
  "Guía de prompt H3 (MiniMax):",
  "",
  H3_PROMPT_TEMPLATE,
  "",
  "Una toma continua por generación, sin cortes.",
  "integrated_multimodal_description: sujeto, vestuario, entorno, luz, cámara y movimiento restringido.",
  "overall_soundscape: ambiente y efectos; diálogo solo si aplica con <d>[Idioma] texto</d>.",
  "Declara un speaker id estable antes de las voces (p. ej. speaker_1).",
  "Un diálogo no debe llenar más de ~2/3 de su plano.",
  "non_diegetic_music: música o None.",
  "También aplica a FL2VA (primer y último frame).",
].join("\n");

const EDITOR_REF_LIMIT = 10;
const EDITOR_GALLERY_PAGE_SIZE = 5;
const UPSCALE_GALLERY_PAGE_SIZE = 5;
const EDITOR_SIZE_MIN = 512;
const EDITOR_SIZE_MAX = 2048;
const EDITOR_SIZE_STEP = 16;
const PROMPT_TAGS_MAX = 120;

const STARTUP_DEFAULTS = {
  model: "one-obsession-anima-v40",
  steps: 30,
  cfg: 6,
  sampler: "euler",
  scheduler: "normal",
  width: 1024,
  height: 1024,
  preprompt: "anima_default",
  rating: "nsfw",
  negative:
    "worst quality, low quality, jpeg artifacts, child, teen, loli, young-looking, " +
    "blurry, mosaic censoring, bar censor, score_1, score_2, score_3, artist name",
  video_engine: "h3",
};

const SEED_RANDOM_KEY = "waifu.seed.random";
const SEED_RANDOM_MAX = 2147483647;

const OC_TRAIT_GROUPS = ["hair", "eyes", "face", "body"];

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
  promptZones: {
    quality: [],
    safety: [],
    subject: [],
    character: [],
    general: {
      rasgos: [],
      ropa: [],
      accesorios: [],
      accion: [],
      poses: [],
      poses_sexuales: [],
      poses_sexys: [],
      expresion: [],
      expresiones_nsfw: [],
      camara: [],
      fondo: [],
    },
  },
  pendingEnhance: false,
  pendingMotion: false,
  pendingH3Prompt: false,
  videoNegativeTouched: false,
  videoVramHint: "",
  videoPresets: [],
  videoH3Profiles: [],
  videoH3Variants: [],
  videoH3Seconds: [],
  videoH3Resolutions: {},
  editorInstalled: false,
  editorRefs: [],
  editorBusy: false,
  editorResultUrl: null,
  editorGallery: {
    page: 1,
    total: 1,
    items: [],
  },
  upscalers: [],
  frameInterpolation: null,
  upscaleSources: [],
  upscaleSourceId: null,
  upscaleLocalFile: null,
  upscaleGallery: {
    page: 1,
    total: 1,
    items: [],
  },
  imageViewer: {
    page: 1,
    total: 1,
    items: [],
    selectedId: null,
  },
  videoViewer: {
    page: 1,
    total: 1,
    items: [],
    selectedId: null,
  },
  activeJobId: null,
  busy: false,
  seedRandom: false,
  characters: [],
  activeCharacterId: null,
  ocSelectedTags: [],
  ocExtras: [],
  ocCatalogItems: [],
  ocEditingId: null,
  ocPrepromptDefault: "",
  characterRefs: [],
  ocSaveGenId: null,
  loras: [],
  loraControls: {},
  loraSelection: new Map(),
  loraLibrary: [],
  loraEditId: null,
  customPreprompts: [],
  trainCharacterId: null,
  trainItems: [],
  trainSelected: new Set(),
  trainOffset: 0,
  trainBusy: false,
  trainJobId: null,
};

let enhanceResetTimer = null;
let motionResetTimer = null;
let h3PromptResetTimer = null;
let h3PromptStatusTimer = null;
let refObjectUrl = null;
let ocSearchTimer = null;
let zoneInsertTarget = null;
let zonePopoverOptions = null;
let zonePopoverSubcat = null;
let zonePopoverOriginSubcat = null;
let zonePopoverSelected = new Map();
let zonePopoverSeq = 0;
let zonePopoverAnchor = null;
let zoneOcApplied = [];
let zoneOcCharacter = null;
let visionRequestSeq = 0;
let visionInsertTimer = null;
let visionResult = { tags: [], caption: "" };

const $ = (id) => document.getElementById(id);

function on(id, event, handler) {
  const el = $(id);
  if (!el) {
    console.error(`bind: falta #${id} (¿UI desactualizada? recarga con Ctrl+F5)`);
    return false;
  }
  el.addEventListener(event, handler);
  return true;
}

function showUiBanner(message) {
  let banner = $("ui-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "ui-banner";
    banner.style.cssText =
      "position:fixed;top:0;left:0;right:0;z-index:1000;padding:10px 14px;" +
      "background:#7a1f1f;color:#fff;font-weight:600;text-align:center";
    document.body.appendChild(banner);
  }
  banner.textContent = message;
}

function setStatus(text, isError = false) {
  const el = $("job-status");
  if (!el) {
    if (isError) {
      showUiBanner(text);
    }
    return;
  }
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

function putJson(path, payload) {
  return api(path, {
    method: "PUT",
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
  fillEditorSizes();
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

async function loadLoras() {
  const family = state.family || "anima";
  const data = await api(`/api/loras?family=${encodeURIComponent(family)}`);
  state.loras = data.items || [];
  state.loraSelection = new Map();
  renderLoras();
}

function loraById(loraId) {
  return state.loras.find((lora) => lora.id === loraId) || null;
}

function clampLoraWeight(value) {
  const weight = Number(value);
  if (!Number.isFinite(weight)) {
    return null;
  }
  return Math.max(0, Math.min(2, weight));
}

function emptyLoraMessage(text) {
  const empty = document.createElement("p");
  empty.className = "empty";
  empty.textContent = text;
  return empty;
}

function renderLoraChips() {
  const container = $("loras-list");
  if (!container) {
    return;
  }
  container.replaceChildren();
  if (!state.loras.length) {
    container.appendChild(
      emptyLoraMessage(
        "No hay LoRAs de imagen registradas. Añádelas con «Gestionar " +
          "biblioteca» (o en registry/loras.json) con familia anima"
      )
    );
    return;
  }
  if (!state.loraSelection.size) {
    container.appendChild(emptyLoraMessage("Ningún LoRA seleccionado."));
    return;
  }
  for (const lora of state.loras) {
    if (!state.loraSelection.has(lora.id)) {
      continue;
    }
    const weight = Number(state.loraSelection.get(lora.id));
    const chip = document.createElement("span");
    chip.className = "lora-chip";
    const name = document.createElement("span");
    name.className = "lora-chip-name";
    name.textContent = lora.display_name || lora.id;
    name.title = `${lora.id} @ ${weight.toFixed(2)}`;
    const value = document.createElement("span");
    value.className = "lora-chip-weight";
    value.textContent = `@ ${weight.toFixed(2)}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "lora-chip-remove";
    remove.textContent = "×";
    remove.title = "Quitar";
    remove.addEventListener("click", () => setLoraSelected(lora.id, false));
    chip.append(name, value, remove);
    container.appendChild(chip);
  }
}

function updateLoraCounters() {
  const total = state.loraSelection.size;
  const button = $("btn-lora-modal");
  if (button) {
    button.textContent = `Elegir LoRAs (${total})`;
  }
  const summary = $("loras-count");
  if (summary) {
    summary.textContent = String(total);
  }
  const modalCount = $("lora-selected-count");
  if (modalCount) {
    modalCount.textContent = `${total} seleccionado${total === 1 ? "" : "s"}`;
  }
}

function syncLoraControls(loraId) {
  const controls = state.loraControls[loraId];
  const lora = loraById(loraId);
  if (!controls || !lora) {
    return;
  }
  const selected = state.loraSelection.has(loraId);
  const stored = selected ? Number(state.loraSelection.get(loraId)) : NaN;
  const weight = Number.isFinite(stored) ? stored : Number(lora.default_weight);
  controls.check.checked = selected;
  controls.weight.value = String(weight);
  controls.value.textContent = weight.toFixed(2);
}

function setLoraSelected(loraId, selected, weight) {
  const lora = loraById(loraId);
  if (!lora) {
    return false;
  }
  if (selected) {
    const wanted = clampLoraWeight(weight);
    state.loraSelection.set(
      loraId,
      wanted == null ? Number(lora.default_weight) : wanted
    );
  } else {
    state.loraSelection.delete(loraId);
  }
  syncLoraControls(loraId);
  renderLoraChips();
  updateLoraCounters();
  return true;
}

function renderLoraModalList() {
  const container = $("lora-options");
  if (!container) {
    return;
  }
  const search = $("lora-search");
  const query = (search ? search.value : "").trim().toLowerCase();
  container.replaceChildren();
  state.loraControls = {};
  if (!state.loras.length) {
    container.appendChild(
      emptyLoraMessage(
        "No hay LoRAs de imagen registradas. Añádelas con «Gestionar " +
          "biblioteca» (o en registry/loras.json) con familia anima"
      )
    );
    return;
  }
  const items = state.loras.filter((lora) => {
    if (!query) {
      return true;
    }
    const haystack = [lora.id, lora.display_name || "", lora.trigger || ""]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
  if (!items.length) {
    container.appendChild(emptyLoraMessage("Sin resultados."));
    return;
  }
  for (const lora of items) {
    const row = document.createElement("div");
    row.className = "lora-option";
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
    weight.dataset.loraWeight = lora.id;
    const stored = state.loraSelection.has(lora.id)
      ? Number(state.loraSelection.get(lora.id))
      : Number(lora.default_weight);
    weight.value = String(Number.isFinite(stored) ? stored : lora.default_weight);
    const value = document.createElement("output");
    value.className = "lora-weight-value";
    value.textContent = Number(weight.value).toFixed(2);
    check.checked = state.loraSelection.has(lora.id);
    check.addEventListener("change", () => {
      setLoraSelected(lora.id, check.checked, weight.value);
    });
    weight.addEventListener("input", () => {
      value.textContent = Number(weight.value).toFixed(2);
      if (state.loraSelection.has(lora.id)) {
        state.loraSelection.set(lora.id, Number(weight.value));
        renderLoraChips();
        updateLoraCounters();
      }
    });
    weightBox.append(weight, value);
    row.append(label, weightBox);
    container.appendChild(row);
    state.loraControls[lora.id] = { check, weight, value };
  }
}

function renderLoras() {
  renderLoraChips();
  updateLoraCounters();
  renderLoraModalList();
}

function openLoraModal() {
  const modal = $("lora-modal");
  if (!modal) {
    console.error("lora: falta #lora-modal (¿UI desactualizada?)");
    return;
  }
  const search = $("lora-search");
  if (search) {
    search.value = "";
  }
  renderLoraModalList();
  updateLoraCounters();
  modal.classList.remove("hidden");
}

function closeLoraModal() {
  const modal = $("lora-modal");
  if (modal) {
    modal.classList.add("hidden");
  }
}

function clearLoraSelection() {
  state.loraSelection = new Map();
  renderLoraModalList();
  renderLoraChips();
  updateLoraCounters();
}

function readLorasPayload() {
  const selection = [];
  for (const lora of state.loras) {
    if (!state.loraSelection.has(lora.id)) {
      continue;
    }
    const weight = Number(state.loraSelection.get(lora.id));
    selection.push({
      id: lora.id,
      weight: Number.isFinite(weight) ? weight : lora.default_weight,
    });
  }
  return selection;
}

function applyLorasSelection(loras) {
  const known = new Set(state.loras.map((lora) => lora.id));
  state.loraSelection = new Map();
  for (const item of loras || []) {
    if (!item || typeof item.id !== "string" || !known.has(item.id)) {
      continue;
    }
    const lora = loraById(item.id);
    const wanted = clampLoraWeight(item.weight);
    state.loraSelection.set(
      item.id,
      wanted == null ? Number(lora.default_weight) : wanted
    );
  }
  for (const lora of state.loras) {
    syncLoraControls(lora.id);
  }
  renderLoraChips();
  updateLoraCounters();
}

function setLoraLibraryStatus(text, isError = false) {
  const el = $("lora-library-status");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function loraLibraryEntry(loraId) {
  return state.loraLibrary.find((lora) => lora.id === loraId) || null;
}

function loraLibraryRow(lora) {
  const row = document.createElement("div");
  row.className = "oc-item";
  const header = document.createElement("div");
  header.className = "oc-item-header";
  const title = document.createElement("strong");
  title.textContent = lora.display_name || lora.id;
  const badge = document.createElement("span");
  badge.className = "oc-item-badge";
  badge.textContent = lora.family;
  header.append(title, badge);
  const meta = document.createElement("div");
  meta.className = "oc-item-tags";
  const bits = [`@ ${Number(lora.default_weight).toFixed(2)}`, `id: ${lora.id}`];
  if (lora.trigger) {
    bits.push(`trigger: ${lora.trigger}`);
  }
  if (lora.notes) {
    bits.push(lora.notes);
  }
  meta.textContent = bits.join(" · ");
  const file = document.createElement("div");
  file.className = "oc-item-tags";
  file.textContent = lora.file;
  const actions = document.createElement("div");
  actions.className = "oc-item-actions";
  const edit = document.createElement("button");
  edit.type = "button";
  edit.textContent = "Editar";
  edit.addEventListener("click", () => editLoraEntry(lora.id));
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Borrar";
  remove.addEventListener("click", () => {
    deleteLoraEntry(lora.id).catch((error) =>
      setLoraLibraryStatus(error.message, true)
    );
  });
  actions.append(edit, remove);
  row.append(header, meta, file, actions);
  return row;
}

function renderLoraLibrary() {
  const container = $("lora-library-list");
  if (!container) {
    return;
  }
  container.replaceChildren();
  if (!state.loraLibrary.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin LoRAs registradas.";
    container.appendChild(empty);
    return;
  }
  for (const lora of state.loraLibrary) {
    container.appendChild(loraLibraryRow(lora));
  }
}

async function loadLoraLibrary() {
  const data = await api("/api/loras");
  state.loraLibrary = data.items || [];
  renderLoraLibrary();
  return data;
}

function resetLoraForm() {
  state.loraEditId = null;
  const form = $("lora-library-form");
  if (form) {
    form.reset();
  }
  const title = $("lora-library-form-title");
  if (title) {
    title.textContent = "Añadir LoRA";
  }
  const idInput = $("lora-form-id");
  if (idInput) {
    idInput.disabled = false;
  }
  const cancel = $("btn-lora-form-cancel");
  if (cancel) {
    cancel.classList.add("hidden");
  }
}

function editLoraEntry(loraId) {
  const lora = loraLibraryEntry(loraId);
  if (!lora) {
    return;
  }
  state.loraEditId = lora.id;
  $("lora-form-id").value = lora.id;
  $("lora-form-id").disabled = true;
  $("lora-form-family").value = lora.family;
  $("lora-form-file").value = lora.file;
  $("lora-form-display").value = lora.display_name;
  $("lora-form-trigger").value = lora.trigger || "";
  $("lora-form-weight").value = String(lora.default_weight);
  $("lora-form-source").value = lora.source;
  $("lora-form-license").value = lora.license;
  $("lora-form-notes").value = lora.notes || "";
  $("lora-library-form-title").textContent = `Editar «${lora.id}»`;
  $("btn-lora-form-cancel").classList.remove("hidden");
  setLoraLibraryStatus(`Editando ${lora.id} (id inmutable)`);
}

function readLoraForm() {
  const rawWeight = $("lora-form-weight").value;
  return {
    id: state.loraEditId || $("lora-form-id").value.trim(),
    family: $("lora-form-family").value.trim(),
    file: $("lora-form-file").value.trim(),
    display_name: $("lora-form-display").value.trim(),
    trigger: $("lora-form-trigger").value.trim(),
    default_weight: rawWeight === "" ? 1 : Number(rawWeight),
    source: $("lora-form-source").value.trim(),
    license: $("lora-form-license").value.trim(),
    notes: $("lora-form-notes").value,
  };
}

async function saveLoraEntry(event) {
  event.preventDefault();
  const payload = readLoraForm();
  if (
    !payload.id ||
    !payload.family ||
    !payload.file ||
    !payload.display_name ||
    !payload.source ||
    !payload.license
  ) {
    setLoraLibraryStatus(
      "Id, familia, archivo, nombre visible, fuente y licencia son obligatorios.",
      true
    );
    return;
  }
  try {
    if (state.loraEditId) {
      const data = await putJson(
        `/api/loras/${encodeURIComponent(state.loraEditId)}`,
        payload
      );
      setLoraLibraryStatus(`LoRA «${data.item.id}» actualizada`);
    } else {
      const data = await postJson("/api/loras", payload);
      setLoraLibraryStatus(`LoRA «${data.item.id}» añadida`);
    }
    resetLoraForm();
    await loadLoraLibrary();
    await loadLoras();
  } catch (error) {
    setLoraLibraryStatus(error.message, true);
  }
}

async function deleteLoraEntry(loraId) {
  const lora = loraLibraryEntry(loraId);
  const label = lora ? lora.display_name || lora.id : loraId;
  if (
    !window.confirm(
      `¿Quitar «${label}» del registro? El archivo .safetensors NO se borra.`
    )
  ) {
    return;
  }
  await api(`/api/loras/${encodeURIComponent(loraId)}`, { method: "DELETE" });
  if (state.loraEditId === loraId) {
    resetLoraForm();
  }
  await loadLoraLibrary();
  await loadLoras();
  setLoraLibraryStatus(`LoRA «${loraId}» quitada del registro (archivo intacto)`);
}

function openLoraLibrary() {
  closeLoraModal();
  resetLoraForm();
  $("lora-library-modal").classList.remove("hidden");
  setLoraLibraryStatus("Listo");
  loadLoraLibrary().catch((error) => setLoraLibraryStatus(error.message, true));
}

function closeLoraLibrary() {
  const modal = $("lora-library-modal");
  if (modal) {
    modal.classList.add("hidden");
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
  try {
    const data = await postJson("/api/prompt/enhance_zones", {
      text,
      strength: $("enhance-strength").value,
      rating: $("rating").value,
      tags: collectPromptZoneTags(),
    });
    applyZonesPayload(data.zones || []);
    const negative = String(data.negative || "").trim();
    if (negative) {
      $("negative").value = negative;
      state.negativeTouched = false;
    }
    renderZoneEditor();
    button.textContent = "Generado ✓";
    setStatus("Prompt generado ✓");
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
  }
}

function readStoredSeedRandom() {
  try {
    return window.localStorage.getItem(SEED_RANDOM_KEY) === "1";
  } catch (_error) {
    return false;
  }
}

function storeSeedRandom(enabled) {
  try {
    window.localStorage.setItem(SEED_RANDOM_KEY, enabled ? "1" : "0");
  } catch (_error) {
    return;
  }
}

function randomSeed() {
  return Math.floor(Math.random() * SEED_RANDOM_MAX);
}

function updateSeedRandomButton() {
  const button = $("btn-seed-random");
  if (!button) {
    return;
  }
  button.classList.toggle("active", state.seedRandom);
  button.setAttribute("aria-pressed", state.seedRandom ? "true" : "false");
}

function initSeedRandom() {
  state.seedRandom = readStoredSeedRandom();
  updateSeedRandomButton();
}

function toggleSeedRandom() {
  state.seedRandom = !state.seedRandom;
  storeSeedRandom(state.seedRandom);
  updateSeedRandomButton();
  setStatus(state.seedRandom ? "Seed aleatoria activada" : "Seed aleatoria desactivada");
}

function applyRandomSeed() {
  if (!state.seedRandom) {
    return;
  }
  $("seed").value = randomSeed();
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

async function generate() {
  if (state.busy) {
    return;
  }
  const prompt = composePrompt();
  if (!prompt) {
    updateGenerateState();
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
  const file = $("ref-image").files[0];
  if (file) {
    payload.ref_image_b64 = await readFileBase64(file);
    payload.strength = Number($("strength").value);
  }
  state.busy = true;
  updateGenerateState();
  setStatus("Encolando...");
  try {
    const data = await postJson("/api/generate", payload);
    await pollJob(data.job_id, setStatus, reloadImageViewerFirstPage);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.busy = false;
    updateGenerateState();
  }
}

function setProgress(progress, prefix = "job") {
  const box = $(`${prefix}-progress`);
  const fill = $(`${prefix}-progress-fill`);
  const text = $(`${prefix}-progress-text`);
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

function setVideoProgress(progress) {
  setProgress(progress, "video");
}

function setCancelVisible(visible, buttonId = "btn-cancel") {
  $(buttonId).classList.toggle("hidden", !visible);
}

async function cancelJob(event) {
  const jobId = state.activeJobId;
  if (!jobId) {
    return;
  }
  const button = event && event.currentTarget ? event.currentTarget : $("btn-cancel");
  const statusFn =
    button.id === "btn-video-cancel"
      ? setVideoStatus
      : button.id === "btn-upscale-cancel"
      ? setUpscaleStatus
      : setStatus;
  button.disabled = true;
  try {
    await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
    statusFn("Cancelado");
  } catch (error) {
    statusFn(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function pollJob(
  jobId,
  statusFn = setStatus,
  onDone = reloadImageViewerFirstPage,
  progressFn = setProgress,
  manageCancel = true,
  cancelButtonId = "btn-cancel"
) {
  if (manageCancel) {
    state.activeJobId = jobId;
    setCancelVisible(true, cancelButtonId);
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
        await onDone(job);
        return;
      }
      if (job.status === "cancelled") {
        statusFn("Cancelado");
        await onDone(job);
        return;
      }
      statusFn("Listo");
      await onDone(job);
      return;
    }
  } finally {
    if (manageCancel) {
      state.activeJobId = null;
      setCancelVisible(false, cancelButtonId);
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
  const params = item.params || {};
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
  if (warning) {
    setStatus(`Cargado #${item.id} · ${warning}`, true);
  } else {
    setStatus(`Cargado #${item.id}`);
  }
}

function formatGalleryDate(value) {
  const text = String(value || "").replace("T", " ");
  return text ? text.slice(0, 16) : "sin fecha";
}

function selectedImageView() {
  return (
    state.imageViewer.items.find(
      (item) => item.id === state.imageViewer.selectedId
    ) || null
  );
}

function imageViewUrl(item) {
  const urls = (item && item.urls) || [];
  return urls.length && !isVideoUrl(urls[0]) ? urls[0] : null;
}

function downloadUrlFor(url) {
  const text = String(url || "");
  return text.startsWith("/media/") ? `/api/download/${text.slice("/media/".length)}` : null;
}

function updateImagePreview() {
  const item = selectedImageView();
  const url = imageViewUrl(item);
  const img = $("image-preview-img");
  const empty = $("image-preview-empty");
  if (url) {
    img.src = url;
    img.alt = item.prompt ? `#${item.id} ${item.prompt}` : `Generación #${item.id}`;
    img.classList.remove("hidden");
    empty.classList.add("hidden");
  } else {
    img.removeAttribute("src");
    img.alt = "";
    img.classList.add("hidden");
    empty.classList.remove("hidden");
    if (!item) {
      empty.textContent = "Sin generaciones";
    } else {
      empty.textContent = item.status === "error" ? "Sin resultado (error)" : "Sin resultado";
    }
  }
  $("image-preview").classList.toggle("has-image", Boolean(url));
  $("btn-save-to-oc").disabled = !item;
  const describeButton = $("btn-describe-image");
  if (describeButton) {
    describeButton.disabled = !(item && item.kind === "image" && url);
  }
  const downloadButton = $("btn-download-image");
  if (downloadButton) {
    downloadButton.disabled = !(item && item.kind === "image" && url);
  }
  const info = $("image-preview-info");
  info.textContent = item
    ? `#${item.id} · ${item.model_id} · ${formatGalleryDate(item.created_at)}`
    : "Sin generaciones";
}

function downloadSelectedImage() {
  const item = selectedImageView();
  const downloadUrl = downloadUrlFor(imageViewUrl(item));
  if (!downloadUrl) {
    setStatus("No hay imagen seleccionada para descargar", true);
    return;
  }
  window.location.href = downloadUrl;
}

function renderImageThumbs() {
  const container = $("image-thumbs");
  container.replaceChildren();
  const items = state.imageViewer.items;
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin generaciones.";
    container.appendChild(empty);
    return;
  }
  for (const item of items) {
    const selected = item.id === state.imageViewer.selectedId;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "image-thumb";
    button.classList.toggle("selected", selected);
    if (selected) {
      button.setAttribute("aria-current", "true");
    }
    button.title = `Reusar generación #${item.id}`;
    button.setAttribute("aria-label", `Reusar generación #${item.id}`);
    const url = imageViewUrl(item);
    if (url) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = item.prompt || `Generación #${item.id}`;
      img.loading = "lazy";
      button.appendChild(img);
    } else {
      const missing = document.createElement("span");
      missing.className = "thumb-missing";
      missing.textContent = item.status === "error" ? "Error" : "Sin resultado";
      button.appendChild(missing);
    }
    button.addEventListener("click", () => {
      selectImageGeneration(item).catch((error) => setStatus(error.message, true));
    });
    container.appendChild(button);
  }
}

function renderImageViewer() {
  const viewer = state.imageViewer;
  updateImagePreview();
  renderImageThumbs();
  $("image-page-info").textContent = `página ${viewer.page} de ${viewer.total}`;
  $("image-prev-page").disabled = viewer.page <= 1;
  $("image-next-page").disabled = viewer.page >= viewer.total;
}

async function loadImageViewer({ selectNewest = false } = {}) {
  const viewer = state.imageViewer;
  viewer.page = Math.max(1, viewer.page);
  const offset = (viewer.page - 1) * IMAGE_PAGE_SIZE;
  try {
    const data = await api(
      `/api/gallery?kind=image&limit=${IMAGE_PAGE_SIZE}&offset=${offset}`
    );
    const raw = data.items || [];
    const count = Number(data.count);
    const total = Number.isFinite(count) && count > 0 ? count : raw.length;
    viewer.total = Math.max(1, Math.ceil(total / IMAGE_PAGE_SIZE));
    if (viewer.page > viewer.total) {
      viewer.page = viewer.total;
      return await loadImageViewer({ selectNewest });
    }
    viewer.items = raw;
    const onPage = viewer.items.some((item) => item.id === viewer.selectedId);
    if (selectNewest && viewer.items.length) {
      viewer.selectedId = viewer.items[0].id;
    } else if (!onPage) {
      viewer.selectedId = viewer.items.length ? viewer.items[0].id : null;
    }
    renderImageViewer();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function selectImageGeneration(item) {
  state.imageViewer.selectedId = item.id;
  renderImageViewer();
  await reuseGeneration(item);
}

async function reloadImageViewerFirstPage() {
  state.imageViewer.page = 1;
  await loadImageViewer({ selectNewest: true });
}

function visionGenId(item) {
  if (!item) {
    return null;
  }
  const raw = item.gen_id != null ? item.gen_id : item.id;
  return raw == null ? null : String(raw);
}

function setVisionStatus(text, isError = false) {
  const el = $("vision-status");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function resetVisionModal() {
  visionResult = { tags: [], caption: "" };
  const empty = $("vision-empty");
  if (empty) {
    empty.textContent = "Analizando…";
    empty.classList.remove("hidden", "error");
  }
  for (const id of ["vision-caption-block", "vision-tags-block"]) {
    const block = $(id);
    if (block) {
      block.classList.add("hidden");
    }
  }
  for (const id of ["vision-caption", "vision-tags"]) {
    const text = $(id);
    if (text) {
      text.textContent = "";
    }
  }
  for (const id of [
    "btn-vision-copy-caption",
    "btn-vision-copy-tags",
    "btn-vision-insert-caption",
    "btn-vision-insert-tags",
  ]) {
    const button = $(id);
    if (button) {
      button.disabled = true;
    }
  }
  const insertCaption = $("btn-vision-insert-caption");
  if (insertCaption) {
    insertCaption.textContent = "Insertar caption";
  }
  const insertTags = $("btn-vision-insert-tags");
  if (insertTags) {
    insertTags.textContent = "Insertar tags";
  }
}

function showVisionError(message) {
  setVisionStatus("Error", true);
  const empty = $("vision-empty");
  if (empty) {
    empty.textContent = message || "No se pudo describir la imagen";
    empty.classList.remove("hidden");
    empty.classList.add("error");
  }
}

function renderVisionResult(data) {
  const raw = data && typeof data === "object" ? data : {};
  const tags = Array.isArray(raw.tags)
    ? raw.tags.map((tag) => String(tag == null ? "" : tag).trim()).filter(Boolean)
    : [];
  const caption = typeof raw.caption === "string" ? raw.caption.trim() : "";
  visionResult = { tags, caption };
  const model = raw.model && typeof raw.model === "object" ? raw.model : {};
  const names = [model.wd14, model.vl].filter(
    (name) => typeof name === "string" && name
  );
  const modelNote = names.length ? ` · ${names.join(" + ")}` : "";
  if (caption) {
    const captionEl = $("vision-caption");
    if (captionEl) {
      captionEl.textContent = caption;
    }
    const captionBlock = $("vision-caption-block");
    if (captionBlock) {
      captionBlock.classList.remove("hidden");
    }
    const copyCaption = $("btn-vision-copy-caption");
    if (copyCaption) {
      copyCaption.disabled = false;
    }
    const insertCaption = $("btn-vision-insert-caption");
    if (insertCaption) {
      insertCaption.disabled = false;
    }
  }
  if (tags.length) {
    const tagsEl = $("vision-tags");
    if (tagsEl) {
      tagsEl.textContent = tags.join(", ");
    }
    const tagsBlock = $("vision-tags-block");
    if (tagsBlock) {
      tagsBlock.classList.remove("hidden");
    }
    const copyTags = $("btn-vision-copy-tags");
    if (copyTags) {
      copyTags.disabled = false;
    }
    const insertTags = $("btn-vision-insert-tags");
    if (insertTags) {
      insertTags.disabled = false;
    }
  }
  const empty = $("vision-empty");
  if (!caption && !tags.length) {
    if (empty) {
      empty.textContent = "El modelo no devolvió tags ni caption.";
      empty.classList.remove("hidden");
    }
    setVisionStatus(`Sin resultados${modelNote}`);
    return;
  }
  if (empty) {
    empty.classList.add("hidden");
  }
  setVisionStatus(`Listo${modelNote}`);
}

async function openVisionModal(source) {
  let payload = source && typeof source === "object" ? source : null;
  if (!payload) {
    const item = selectedImageView();
    const genId = visionGenId(item);
    if (genId == null) {
      setStatus("Selecciona una imagen para describir", true);
      return;
    }
    payload = { gen_id: genId };
  }
  const modal = $("vision-modal");
  if (!modal) {
    return;
  }
  resetVisionModal();
  modal.classList.remove("hidden");
  setVisionStatus("Analizando…");
  const seq = ++visionRequestSeq;
  try {
    const data = await postJson("/api/vision/image_to_prompt", {
      ...payload,
      use_tags: true,
      use_caption: true,
    });
    if (seq !== visionRequestSeq) {
      return;
    }
    renderVisionResult(data);
  } catch (error) {
    if (seq !== visionRequestSeq) {
      return;
    }
    showVisionError(error.message);
  }
}

function describeRefFromDisk() {
  const input = $("describe-file");
  if (!input) {
    return;
  }
  input.value = "";
  input.click();
}

async function describeSelectedRefFile() {
  const input = $("describe-file");
  const file = input && input.files ? input.files[0] : null;
  if (!file) {
    return;
  }
  try {
    const b64 = await readFileBase64(file);
    await openVisionModal({ image_b64: b64 });
  } catch (error) {
    setStatus(error.message, true);
  }
}

function closeVisionModal() {
  visionRequestSeq += 1;
  if (visionInsertTimer) {
    clearTimeout(visionInsertTimer);
    visionInsertTimer = null;
  }
  const modal = $("vision-modal");
  if (modal) {
    modal.classList.add("hidden");
  }
}

function visionGeneralTarget() {
  const area = $("prompt-general");
  if (area) {
    return { el: area, label: "«Prompt general»", separator: "\n" };
  }
  const input = document.querySelector(
    "#zone-editor .zone-block-general .zone-quick-input"
  );
  if (input) {
    return { el: input, label: "la zona General", separator: ", " };
  }
  return null;
}

function insertVisionIntoPrompt(kind) {
  const isTags = kind === "tags";
  const text = isTags ? visionResult.tags.join(", ") : visionResult.caption;
  if (!text) {
    setVisionStatus(
      isTags ? "Sin tags que insertar" : "Sin caption que insertar",
      true
    );
    return false;
  }
  const target = visionGeneralTarget();
  if (!target) {
    setVisionStatus("No hay campo de prompt disponible", true);
    return false;
  }
  const current = String(target.el.value || "").replace(/\s+$/, "");
  target.el.value = current ? `${current}${target.separator}${text}` : text;
  target.el.focus();
  setStatus(
    `${isTags ? "Tags insertados" : "Caption insertado"} en ${target.label} ✓`
  );
  return true;
}

function insertVisionFromModal(kind) {
  if (!insertVisionIntoPrompt(kind)) {
    return;
  }
  const button = $(
    kind === "tags" ? "btn-vision-insert-tags" : "btn-vision-insert-caption"
  );
  if (button) {
    button.textContent = "Insertado ✓";
  }
  setVisionStatus(kind === "tags" ? "Tags insertados ✓" : "Caption insertado ✓");
  if (visionInsertTimer) {
    clearTimeout(visionInsertTimer);
  }
  visionInsertTimer = setTimeout(() => {
    visionInsertTimer = null;
    closeVisionModal();
  }, 500);
}

async function copyVisionText(kind) {
  const isTags = kind === "tags";
  const text = isTags ? visionResult.tags.join(", ") : visionResult.caption;
  if (!text) {
    setVisionStatus(isTags ? "Sin tags que copiar" : "Sin caption que copiar", true);
    return;
  }
  try {
    await writeClipboard(text);
    setVisionStatus(isTags ? "Tags copiados ✓" : "Caption copiado ✓");
  } catch (error) {
    setVisionStatus(error.message, true);
  }
}

async function writeClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

function selectedVideoView() {
  return (
    state.videoViewer.items.find(
      (item) => item.id === state.videoViewer.selectedId
    ) || null
  );
}

function videoViewUrl(item) {
  const urls = (item && item.urls) || [];
  return urls.length && isVideoUrl(urls[0]) ? urls[0] : null;
}

function videoEngineLabel(item) {
  const params = (item && item.params) || {};
  const engine = params.engine || (item && item.model_id) || "wan";
  const mode = params.mode === "flf2v" ? "flf2v" : "i2v";
  return `${engine}/${mode}`;
}

function updateVideoPreview() {
  const item = selectedVideoView();
  const url = videoViewUrl(item);
  const video = $("video-preview");
  const empty = $("video-preview-empty");
  if (url) {
    if (video.getAttribute("src") !== url) {
      video.pause();
      video.setAttribute("src", url);
      video.load();
    }
    video.classList.remove("hidden");
    empty.classList.add("hidden");
  } else {
    video.pause();
    video.removeAttribute("src");
    video.classList.add("hidden");
    empty.classList.remove("hidden");
    empty.textContent = item
      ? item.status === "error"
        ? "Sin resultado (error)"
        : "Sin resultado"
      : "Sin videos";
  }
  const info = $("video-preview-info");
  info.textContent = item
    ? `#${item.id} · ${videoEngineLabel(item)} · ${formatGalleryDate(item.created_at)}`
    : "Sin videos";
}

function renderVideoThumbs() {
  const container = $("video-thumbs");
  container.replaceChildren();
  const viewer = state.videoViewer;
  const items = viewer.items;
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin videos.";
    container.appendChild(empty);
    return;
  }
  for (const item of items) {
    const selected = item.id === viewer.selectedId;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "video-thumb";
    button.classList.toggle("selected", selected);
    if (selected) {
      button.setAttribute("aria-current", "true");
    }
    button.title = `Cargar generación #${item.id}`;
    button.setAttribute("aria-label", `Cargar generación #${item.id}`);
    const url = videoViewUrl(item);
    if (url) {
      const thumb = document.createElement("video");
      thumb.src = url;
      thumb.muted = true;
      thumb.preload = "metadata";
      thumb.playsInline = true;
      thumb.addEventListener(
        "loadedmetadata",
        () => {
          thumb.currentTime = 0.01;
        },
        { once: true }
      );
      button.appendChild(thumb);
    } else {
      const missing = document.createElement("span");
      missing.className = "thumb-missing";
      missing.textContent = item.status === "error" ? "Error" : "Sin resultado";
      button.appendChild(missing);
    }
    button.addEventListener("click", () => {
      selectVideoGeneration(item).catch((error) =>
        setVideoStatus(error.message, true)
      );
    });
    container.appendChild(button);
  }
}

function renderVideoViewer() {
  const viewer = state.videoViewer;
  updateVideoPreview();
  renderVideoThumbs();
  $("video-page-info").textContent = `página ${viewer.page} de ${viewer.total}`;
  $("video-prev-page").disabled = viewer.page <= 1;
  $("video-next-page").disabled = viewer.page >= viewer.total;
}

async function loadVideoViewer({ selectNewest = false } = {}) {
  const viewer = state.videoViewer;
  viewer.page = Math.max(1, viewer.page);
  const offset = (viewer.page - 1) * VIDEO_PAGE_SIZE;
  try {
    const data = await api(
      `/api/gallery?kind=video&limit=${VIDEO_PAGE_SIZE}&offset=${offset}`
    );
    const raw = data.items || [];
    const count = Number(data.count);
    const total = Number.isFinite(count) && count > 0 ? count : raw.length;
    viewer.total = Math.max(1, Math.ceil(total / VIDEO_PAGE_SIZE));
    if (viewer.page > viewer.total) {
      viewer.page = viewer.total;
      return await loadVideoViewer({ selectNewest });
    }
    viewer.items = raw;
    const onPage = viewer.items.some((item) => item.id === viewer.selectedId);
    if (selectNewest && viewer.items.length) {
      viewer.selectedId = viewer.items[0].id;
    } else if (!onPage) {
      viewer.selectedId = viewer.items.length ? viewer.items[0].id : null;
    }
    renderVideoViewer();
  } catch (error) {
    setVideoStatus(error.message, true);
  }
}

async function selectVideoGeneration(item) {
  state.videoViewer.selectedId = item.id;
  renderVideoViewer();
  await reuseVideoGeneration(item);
}

async function reloadVideoViewerFirstPage() {
  state.videoViewer.page = 1;
  await loadVideoViewer({ selectNewest: true });
}

async function attachVideoFrameFromUrl(inputId, name) {
  const clean = typeof name === "string" ? name.trim() : "";
  const input = $(inputId);
  if (!clean) {
    input.value = "";
    return;
  }
  const response = await fetch(`/api/refs/${encodeURIComponent(clean)}`);
  if (!response.ok) {
    input.value = "";
    throw new Error(`frame guardado no disponible (HTTP ${response.status})`);
  }
  const blob = await response.blob();
  const file = new File([blob], clean, {
    type: blob.type || "image/png",
  });
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
}

async function applyVideoSavedFrames(params) {
  const saved = params || {};
  const first = saved.image || saved.ref_image || "";
  const last = saved.last_image || "";
  const warnings = [];
  for (const [inputId, name] of [
    ["video-image", first],
    ["video-last-image", last],
  ]) {
    try {
      await attachVideoFrameFromUrl(inputId, name);
    } catch (error) {
      warnings.push(error.message);
    }
  }
  if (warnings.length) {
    throw new Error(warnings.join("; "));
  }
}

async function reuseVideoGeneration(item) {
  const params = item.params || {};
  const engine = (params.engine || item.model_id) === "h3" ? "h3" : "wan";
  $("video-engine").value = "h3";
  $("video-mode").value = params.mode === "flf2v" ? "flf2v" : "i2v";
  setSelectValue($("video-aspect"), params.aspect);
  const preset = typeof params.preset === "string" ? params.preset : "manual";
  const presetSelect = $("video-preset");
  presetSelect.value = preset;
  if (presetSelect.value !== preset) {
    presetSelect.value = "manual";
  }
  updateVideoPresetNote();
  const seconds = Number(params.seconds);
  if (Number.isFinite(seconds)) {
    $("video-seconds").value = String(Math.min(15, Math.max(1, seconds)));
  }
  updateVideoDurationInfo();
  if (engine === "h3") {
    const storedProfile =
      typeof params.profile === "string" && params.profile
        ? params.profile
        : "referencia";
    setSelectValue($("video-h3-profile"), storedProfile);
    const storedVariant =
      typeof params.variant === "string" && params.variant
        ? params.variant
        : "turbo4";
    setSelectValue($("video-h3-variant"), storedVariant);
    $("video-h3-sage").checked = params.sage === true;
    const h3Seconds = Number(params.seconds);
    if (state.videoH3Seconds.includes(h3Seconds)) {
      $("video-h3-seconds").value = String(h3Seconds);
    }
    const width = Number(params.width);
    const height = Number(params.height);
    if (Number.isFinite(width) && Number.isFinite(height)) {
      setSelectValue($("video-h3-size"), `${width}x${height}`);
    }
    updateH3Notes();
  }
  if (params.seed != null) {
    $("video-seed").value = params.seed;
  }
  $("video-motion").value =
    engine === "wan" ? String(params.motion_positive || item.prompt || "") : "";
  $("video-prompt").value =
    engine === "h3" ? String(params.prompt || item.prompt || "") : "";
  const storedNegative =
    typeof item.negative === "string" && item.negative
      ? item.negative
      : typeof params.motion_negative === "string"
        ? params.motion_negative
        : "";
  $("video-motion-negative").value = storedNegative;
  state.videoNegativeTouched = Boolean(storedNegative);
  applyVideoEngine();
  let warning = "";
  try {
    await applyVideoSavedFrames(params);
  } catch (error) {
    warning = error.message;
  }
  if (warning) {
    setVideoStatus(`Cargado #${item.id} · ${warning}`, true);
  } else {
    setVideoStatus(`Cargado #${item.id}`);
  }
}

function startNewVideo() {
  $("video-engine").value = STARTUP_DEFAULTS.video_engine;
  $("video-mode").value = "i2v";
  $("video-aspect").value = "vertical";
  $("video-preset").value = "manual";
  $("video-seconds").value = "5";
  $("video-seed").value = $("video-seed").defaultValue || "42";
  $("video-motion").value = "";
  $("video-prompt").value = "";
  $("video-motion-negative").value = "";
  $("video-image").value = "";
  $("video-last-image").value = "";
  setSelectValue($("video-h3-profile"), "calidad");
  setSelectValue($("video-h3-variant"), "turbo4");
  $("video-h3-sage").checked = false;
  setSelectValue($("video-h3-seconds"), String(defaultH3Seconds()));
  state.videoNegativeTouched = false;
  state.videoVramHint = "";
  applyVideoEngine();
  updateVideoDurationInfo();
  setVideoStatus("Nuevo: opciones por defecto");
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

async function improveMotion() {
  if (state.pendingMotion) {
    return;
  }
  const text = $("video-motion").value.trim();
  if (!text) {
    setVideoStatus("Escribe el movimiento para mejorarlo", true);
    return;
  }
  const button = $("btn-motion");
  state.pendingMotion = true;
  button.disabled = true;
  button.textContent = "Mejorando…";
  setVideoStatus("Mejorando prompt de video...");
  try {
    const data = await postJson("/api/motion", {
      text,
      rating: $("video-rating").value,
    });
    $("video-motion").value = data.motion_positive || "";
    if (!state.videoNegativeTouched && data.motion_negative) {
      $("video-motion-negative").value = data.motion_negative;
    }
    button.textContent = "Listo ✓";
    setVideoStatus("Prompt de video mejorado");
  } catch (error) {
    button.textContent = "Error";
    setVideoStatus(error.message, true);
  } finally {
    state.pendingMotion = false;
    button.disabled = false;
    if (motionResetTimer) {
      clearTimeout(motionResetTimer);
    }
    motionResetTimer = setTimeout(() => {
      if (!state.pendingMotion) {
        button.textContent = "Mejorar prompt (video)";
      }
    }, 1600);
  }
}

async function improveH3Prompt() {
  if (state.pendingH3Prompt) {
    return;
  }
  const area = $("video-prompt");
  const text = area.value.trim();
  if (!text) {
    setH3PromptStatus("Escribe el prompt H3 para mejorarlo", true);
    area.focus();
    return;
  }
  const button = $("btn-h3-prompt");
  state.pendingH3Prompt = true;
  button.disabled = true;
  button.textContent = "Generando…";
  setH3PromptStatus("Generando…");
  if (h3PromptStatusTimer) {
    clearTimeout(h3PromptStatusTimer);
    h3PromptStatusTimer = null;
  }
  try {
    const ratingEl = $("video-rating");
    const data = await postJson("/api/video/h3_prompt", {
      text,
      rating: (ratingEl && ratingEl.value) || "nsfw",
    });
    area.value = data.h3_prompt || "";
    button.textContent = "Listo ✓";
    setH3PromptStatus("Generado ✓");
    if (h3PromptStatusTimer) {
      clearTimeout(h3PromptStatusTimer);
    }
    h3PromptStatusTimer = setTimeout(() => {
      if (!state.pendingH3Prompt) {
        setH3PromptStatus("");
      }
    }, 2000);
  } catch (error) {
    button.textContent = "Error";
    setH3PromptStatus(error.message, true);
  } finally {
    state.pendingH3Prompt = false;
    button.disabled = false;
    if (h3PromptResetTimer) {
      clearTimeout(h3PromptResetTimer);
    }
    h3PromptResetTimer = setTimeout(() => {
      if (!state.pendingH3Prompt) {
        button.textContent = "Mejorar prompt (H3)";
      }
    }, 1600);
  }
}

function readVideoSeed() {
  const value = Number($("video-seed").value);
  return Number.isFinite(value) ? Math.trunc(value) : 42;
}

function readVideoSeconds() {
  const value = Number($("video-seconds").value);
  return Number.isFinite(value) ? value : 5;
}

function secondsToFrames(seconds) {
  const needed = Math.ceil(seconds * VIDEO_FPS);
  return needed + ((4 - ((needed - 1) % 4)) % 4);
}

function updateVideoDurationInfo() {
  const seconds = readVideoSeconds();
  const label = Number.isInteger(seconds) ? String(seconds) : seconds.toFixed(1);
  $("video-seconds-info").textContent =
    `≈ ${label} s → ${secondsToFrames(seconds)} frames (${VIDEO_FPS} fps)`;
}

function setVideoJobStatus(text, isError = false) {
  if (state.videoVramHint && !isError) {
    setVideoStatus(`${text} · ${state.videoVramHint}`);
    return;
  }
  setVideoStatus(text, isError);
}

async function generateVideo() {
  if (state.busy) {
    return;
  }
  const engine = $("video-engine").value;
  const file = $("video-image").files[0];
  if (!file) {
    setVideoStatus("Sube la imagen inicial (first frame)", true);
    return;
  }
  const payload = {
    engine,
    aspect: $("video-aspect").value,
    seed: readVideoSeed(),
  };
  state.videoVramHint = "";
  try {
    payload.image_b64 = await readFileBase64(file);
    const mode = $("video-mode").value;
    payload.mode = mode;
    if (mode === "flf2v") {
      const last = $("video-last-image").files[0];
      if (!last) {
        setVideoStatus("FLF2V requiere la imagen final (last frame)", true);
        return;
      }
      payload.last_image_b64 = await readFileBase64(last);
    }
    if (engine === "wan") {
      const positive = $("video-motion").value.trim();
      if (!positive) {
        setVideoStatus("Escribe el movimiento del video", true);
        return;
      }
      payload.seconds = readVideoSeconds();
      payload.motion_positive = positive;
      payload.preset = $("video-preset").value;
      const negative = $("video-motion-negative").value.trim();
      if (negative) {
        payload.motion_negative = negative;
      }
    } else {
      const prompt = $("video-prompt").value.trim();
      if (!prompt) {
        setVideoStatus("H3 requiere el prompt", true);
        return;
      }
      const size = selectedH3Size();
      if (!size) {
        setVideoStatus("Resolución H3 inválida", true);
        return;
      }
      payload.prompt = prompt;
      payload.profile = $("video-h3-profile").value;
      payload.variant = $("video-h3-variant").value;
      payload.sage = $("video-h3-sage").checked;
      payload.seconds = Number($("video-h3-seconds").value);
      payload.width = size.width;
      payload.height = size.height;
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
    if (engine === "wan" && data.vram_hint) {
      state.videoVramHint = data.vram_hint;
    }
    await pollJob(
      data.job_id,
      setVideoJobStatus,
      reloadVideoViewerFirstPage,
      setVideoProgress,
      true,
      "btn-video-cancel"
    );
  } catch (error) {
    setVideoStatus(error.message, true);
  } finally {
    state.busy = false;
    state.videoVramHint = "";
    $("btn-video-generate").disabled = false;
  }
}

const DEFAULT_VIDEO_SIZES = {
  vertical: { width: 432, height: 768 },
  horizontal: { width: 768, height: 432 },
};

async function loadVideoPresets() {
  const data = await api("/api/video/presets");
  state.videoPresets = data.items || [];
  const select = $("video-preset");
  const previous = select.value || "manual";
  select.replaceChildren(option("manual", "Manual"));
  for (const preset of state.videoPresets) {
    select.appendChild(option(preset.id, preset.label || preset.id));
  }
  setSelectValue(select, previous);
  updateVideoPresetNote();
}

function selectedVideoPreset() {
  return (
    state.videoPresets.find(
      (preset) => preset.id === $("video-preset").value
    ) || null
  );
}

function updateVideoAspectLabels() {
  const preset = selectedVideoPreset();
  for (const opt of $("video-aspect").options) {
    const size = (preset && preset[opt.value]) || DEFAULT_VIDEO_SIZES[opt.value];
    if (!size) {
      continue;
    }
    const label = opt.value === "vertical" ? "Vertical" : "Horizontal";
    opt.textContent = `${label} ${size.width}×${size.height}`;
  }
}

function updateVideoPresetNote() {
  const note = $("video-preset-note");
  if ($("video-engine").value !== "wan") {
    note.textContent = "no aplica a H3 (solo Wan)";
    updateVideoAspectLabels();
    return;
  }
  const preset = selectedVideoPreset();
  note.textContent = preset
    ? `Perfil: ${preset.sampler} · ${preset.scheduler} · ${preset.steps} pasos · ` +
      `shift ${preset.shift}${preset.note ? ` · ${preset.note}` : ""}`
    : "Sin preset: perfil certificado (euler · simple · 20 pasos · shift 8)";
  updateVideoAspectLabels();
}

function selectedH3Profile() {
  return (
    state.videoH3Profiles.find(
      (profile) => profile.id === $("video-h3-profile").value
    ) || null
  );
}

function h3FramesForSeconds(seconds) {
  const needed = Math.ceil(seconds * H3_FPS);
  if (needed <= H3_FRAME_BASE) {
    return H3_FRAME_BASE;
  }
  return (
    H3_FRAME_BASE +
    H3_FRAME_STEP * Math.ceil((needed - H3_FRAME_BASE) / H3_FRAME_STEP)
  );
}

function defaultH3Seconds() {
  const profile = state.videoH3Profiles.find((item) => item.id === "calidad");
  const recommended = (profile && profile.seconds_recomendados) || [];
  return recommended.length ? recommended[0] : state.videoH3Seconds[0] || 8;
}

function fillH3Sizes() {
  const select = $("video-h3-size");
  const previous = select.value;
  select.replaceChildren();
  for (const aspect of ["vertical", "horizontal"]) {
    for (const size of state.videoH3Resolutions[aspect] || []) {
      select.appendChild(
        option(
          `${size.width}x${size.height}`,
          `${size.width}×${size.height} ${aspect}`
        )
      );
    }
  }
  setSelectValue(select, previous);
}

function selectedH3Size() {
  const parts = $("video-h3-size").value.split("x");
  const width = Number(parts[0]);
  const height = Number(parts[1]);
  return Number.isFinite(width) && Number.isFinite(height)
    ? { width, height }
    : null;
}

function updateH3Notes() {
  const profile = selectedH3Profile();
  const note = $("video-h3-profile-note");
  if (!profile) {
    note.textContent = "Cargando perfiles…";
  } else {
    const encoder = profile.projection
      ? `ClipProj ${profile.projection}`
      : "encoder 32B sin proyección";
    const recommended = (profile.seconds_recomendados || []).join("/");
    note.textContent = `${profile.note} · ${encoder}` +
      (recommended ? ` · recomendado: ${recommended} s` : "");
  }
  const seconds = Number($("video-h3-seconds").value);
  $("video-h3-seconds-info").textContent = Number.isFinite(seconds)
    ? `≈ ${seconds} s → ${h3FramesForSeconds(seconds)} frames (${H3_FPS} fps)`
    : "";
  const size = selectedH3Size();
  $("video-h3-size-info").textContent = size
    ? `múltiplos de 32 · máx 768×1344 · grid 5+17n`
    : "";
}

async function loadH3Profiles() {
  const data = await api("/api/video/h3_profiles");
  state.videoH3Profiles = data.items || data.profiles || [];
  state.videoH3Variants = data.variants || [];
  state.videoH3Seconds = data.seconds || [];
  state.videoH3Resolutions = data.resolutions || {};
  const profileSelect = $("video-h3-profile");
  profileSelect.replaceChildren();
  for (const profile of state.videoH3Profiles) {
    profileSelect.appendChild(option(profile.id, profile.label || profile.id));
  }
  const variantSelect = $("video-h3-variant");
  variantSelect.replaceChildren();
  for (const variant of state.videoH3Variants) {
    variantSelect.appendChild(
      option(variant.id, `Pasos: ${variant.steps} (${variant.label})`)
    );
  }
  const secondsSelect = $("video-h3-seconds");
  secondsSelect.replaceChildren();
  for (const seconds of state.videoH3Seconds) {
    secondsSelect.appendChild(option(String(seconds), `${seconds} s`));
  }
  fillH3Sizes();
  setSelectValue(profileSelect, "calidad");
  setSelectValue(variantSelect, "turbo4");
  setSelectValue(secondsSelect, String(defaultH3Seconds()));
  updateH3Notes();
}

function applyVideoEngine() {
  const isWan = $("video-engine").value === "wan";
  const showLast = $("video-mode").value === "flf2v";
  $("video-mode-field").style.display = "";
  $("video-aspect-field").style.display = isWan ? "" : "none";
  $("video-preset-field").style.display = isWan ? "" : "none";
  $("video-preset").disabled = !isWan;
  $("video-seconds-field").style.display = isWan ? "" : "none";
  $("video-motion-field").style.display = isWan ? "" : "none";
  $("video-motion-actions").style.display = isWan ? "" : "none";
  $("video-negative-details").style.display = isWan ? "" : "none";
  $("video-prompt-field").style.display = isWan ? "none" : "";
  $("video-h3-prompt-actions").style.display = isWan ? "none" : "";
  $("video-h3-guide").style.display = isWan ? "none" : "";
  $("video-last-field").style.display = showLast ? "" : "none";
  for (const id of ["video-h3-profile-field", "video-h3-seconds-field", "video-h3-size-field", "video-h3-variant-field", "video-h3-sage-field"]) {
    $(id).style.display = isWan ? "none" : "";
  }
  for (const id of ["video-h3-profile", "video-h3-seconds", "video-h3-size", "video-h3-variant", "video-h3-sage"]) {
    $(id).disabled = isWan;
  }
  updateVideoPresetNote();
  updateH3Notes();
}

function setH3GuideStatus(text, isError = false) {
  const el = $("h3-guide-status");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setH3PromptStatus(text, isError = false) {
  const el = $("h3-prompt-status");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function insertH3Template() {
  const area = $("video-prompt");
  if (!area) {
    return;
  }
  const current = area.value.replace(/\s+$/, "");
  area.value = current ? `${current}\n\n${H3_PROMPT_TEMPLATE}` : H3_PROMPT_TEMPLATE;
  area.focus();
  setH3GuideStatus("Plantilla insertada");
}

async function copyH3Guide() {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(H3_GUIDE_TEXT);
    } else {
      const area = document.createElement("textarea");
      area.value = H3_GUIDE_TEXT;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setH3GuideStatus("Guía copiada");
  } catch (error) {
    setH3GuideStatus(error.message, true);
  }
}

function setEditorStatus(text, isError = false) {
  const el = $("editor-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
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
    const b64 = await readFileBase64(file);
    state.editorRefs.push({
      name: file.name,
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
  if ([...select.options].some((item) => item.value === previous)) {
    select.value = previous;
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
        addEditorRefFromUrl(url).catch((error) => setEditorStatus(error.message, true));
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
  const wanted = Math.max(1, Math.trunc(Number(page)) || 1);
  const offset = (wanted - 1) * EDITOR_GALLERY_PAGE_SIZE;
  try {
    const data = await api(
      `/api/gallery?kind=image&limit=${EDITOR_GALLERY_PAGE_SIZE}&offset=${offset}`
    );
    const items = data.items || [];
    const count = Number(data.count);
    const total = Number.isFinite(count) && count > 0 ? count : items.length;
    viewer.total = Math.max(1, Math.ceil(total / EDITOR_GALLERY_PAGE_SIZE));
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
  const image = $("editor-result-img");
  if (!output || !output.url || !box || !image) {
    return;
  }
  state.editorResultUrl = output.url;
  image.src = output.url;
  box.classList.remove("hidden");
}

async function openEditorResultInGallery() {
  switchTab("image");
  await reloadImageViewerFirstPage();
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
  $("editor-mode").value = "edit";
  setSelectValue($("editor-size"), "original");
  applyEditorSizeSelection();
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
  const seedValue = Number($("editor-seed").value);
  const payload = {
    prompt,
    mode: $("editor-mode").value,
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

function setUpscaleStatus(text, isError = false) {
  const el = $("upscale-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setUpscaleProgress(progress) {
  setProgress(progress, "upscale");
}

function upscaleKind() {
  const kind = $("upscale-kind").value;
  return kind === "video" || kind === "fps" ? kind : "image";
}

function upscaleSourceKind() {
  return upscaleKind() === "image" ? "image" : "video";
}

function upscaleModelNote() {
  const model = state.upscalers.find(
    (item) => item.id === $("upscale-model").value
  );
  $("upscale-model-note").textContent = model
    ? `Escala ×${model.scale}${model.note ? ` · ${model.note}` : ""}`
    : "Cargando modelos…";
}

function upscaleCkptNote() {
  const entry = state.frameInterpolation;
  const ckpt = $("upscale-ckpt").value;
  $("upscale-ckpt-note").textContent = entry
    ? `${ckpt || entry.default}${entry.note ? ` · ${entry.note}` : ""}`
    : "Cargando ckpts RIFE…";
}

function loadUpscaleInterpolation(entry) {
  state.frameInterpolation = entry || null;
  const select = $("upscale-ckpt");
  select.replaceChildren();
  const ckpts = (entry && entry.ckpts) || [];
  for (const ckpt of ckpts) {
    select.appendChild(option(ckpt, ckpt));
  }
  if (entry && entry.default) {
    setSelectValue(select, entry.default);
  }
  upscaleCkptNote();
  const multipliers = (entry && entry.multipliers) || [];
  if (multipliers.length) {
    const multiplierSelect = $("upscale-multiplier");
    const previous = multiplierSelect.value;
    multiplierSelect.replaceChildren();
    for (const value of multipliers) {
      multiplierSelect.appendChild(option(String(value), `×${value}`));
    }
    setSelectValue(multiplierSelect, previous);
  }
}

async function loadUpscaleModels() {
  const data = await api("/api/upscale/models");
  state.upscalers = data.items || data.models || [];
  const select = $("upscale-model");
  const previous = select.value;
  select.replaceChildren();
  for (const model of state.upscalers) {
    select.appendChild(
      option(model.id, `${model.label || model.id} (×${model.scale})`)
    );
  }
  setSelectValue(select, previous);
  upscaleModelNote();
  loadUpscaleInterpolation(data.frame_interpolation);
}

function upscaleItemName(item) {
  return ((item && item.outputs) || [])[0] || "";
}

function selectedUpscaleSource() {
  if (state.upscaleSourceId == null) {
    return null;
  }
  return (
    state.upscaleSources.find((item) => item.id === state.upscaleSourceId) || null
  );
}

function clearUpscaleLocalFile() {
  if (state.upscaleLocalFile) {
    URL.revokeObjectURL(state.upscaleLocalFile.url);
    state.upscaleLocalFile = null;
  }
  const input = $("upscale-file");
  if (input) {
    input.value = "";
  }
}

function clearUpscaleSelection() {
  clearUpscaleLocalFile();
  state.upscaleSources = [];
  state.upscaleSourceId = null;
  state.upscaleGallery.page = 1;
  state.upscaleGallery.items = [];
}

function selectUpscaleSource(id) {
  clearUpscaleLocalFile();
  state.upscaleSourceId = id == null ? null : Number(id);
  renderUpscaleGallery();
  updateUpscaleSourceView();
}

function renderUpscaleGallery() {
  const container = $("upscale-gallery-thumbs");
  if (!container) {
    return;
  }
  const gallery = state.upscaleGallery;
  const isVideo = upscaleSourceKind() === "video";
  container.replaceChildren();
  if (!gallery.items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = isVideo
      ? "Sin generaciones de vídeo."
      : "Sin generaciones de imagen.";
    container.appendChild(empty);
  }
  for (const item of gallery.items) {
    const selected = item.id === state.upscaleSourceId;
    const button = document.createElement("button");
    button.type = "button";
    button.className = isVideo ? "video-thumb" : "image-thumb";
    button.classList.toggle("selected", selected);
    if (selected) {
      button.setAttribute("aria-current", "true");
    }
    const name = upscaleItemName(item);
    button.title = `Usar generación #${item.id}${name ? ` (${name})` : ""}`;
    button.setAttribute("aria-label", button.title);
    const url = isVideo ? videoViewUrl(item) : imageViewUrl(item);
    if (url && isVideo) {
      const thumb = document.createElement("video");
      thumb.src = url;
      thumb.muted = true;
      thumb.preload = "metadata";
      thumb.playsInline = true;
      thumb.addEventListener(
        "loadedmetadata",
        () => {
          thumb.currentTime = 0.01;
        },
        { once: true }
      );
      button.appendChild(thumb);
    } else if (url) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = item.prompt || `Generación #${item.id}`;
      img.loading = "lazy";
      button.appendChild(img);
    } else {
      const missing = document.createElement("span");
      missing.className = "thumb-missing";
      missing.textContent = item.status === "error" ? "Error" : "Sin resultado";
      button.appendChild(missing);
    }
    button.addEventListener("click", () => selectUpscaleSource(item.id));
    container.appendChild(button);
  }
  $("upscale-gallery-info").textContent = `página ${gallery.page} de ${gallery.total}`;
  $("upscale-gallery-prev").disabled = gallery.page <= 1;
  $("upscale-gallery-next").disabled = gallery.page >= gallery.total;
}

async function loadUpscaleGallery(page = 1) {
  const kind = upscaleSourceKind();
  const gallery = state.upscaleGallery;
  const wanted = Math.max(1, Math.trunc(Number(page)) || 1);
  const offset = (wanted - 1) * UPSCALE_GALLERY_PAGE_SIZE;
  const data = await api(
    `/api/gallery?kind=${kind}&limit=${UPSCALE_GALLERY_PAGE_SIZE}&offset=${offset}`
  );
  const items = data.items || [];
  const count = Number(data.count);
  const total = Number.isFinite(count) && count > 0 ? count : items.length;
  gallery.total = Math.max(1, Math.ceil(total / UPSCALE_GALLERY_PAGE_SIZE));
  if (wanted > gallery.total) {
    return await loadUpscaleGallery(gallery.total);
  }
  gallery.page = wanted;
  gallery.items = items;
  const merged = new Map(state.upscaleSources.map((item) => [item.id, item]));
  for (const item of items) {
    merged.set(item.id, item);
  }
  state.upscaleSources = [...merged.values()].sort((a, b) => b.id - a.id);
  renderUpscaleGallery();
  updateUpscaleSourceView();
}

async function useUpscaleLocalFile(file) {
  if (!file) {
    return;
  }
  const b64 = await readFileBase64(file);
  if (state.upscaleLocalFile) {
    URL.revokeObjectURL(state.upscaleLocalFile.url);
  }
  state.upscaleLocalFile = {
    name: file.name,
    b64,
    url: URL.createObjectURL(file),
  };
  state.upscaleSourceId = null;
  renderUpscaleGallery();
  updateUpscaleSourceView();
  setUpscaleStatus(`Archivo local: ${file.name}`);
}

function updateUpscaleSourceView() {
  const isVideo = upscaleSourceKind() === "video";
  const local = !isVideo ? state.upscaleLocalFile : null;
  const item = local ? null : selectedUpscaleSource();
  const url = local ? local.url : isVideo ? videoViewUrl(item) : imageViewUrl(item);
  const img = $("upscale-preview-img");
  const video = $("upscale-preview-video");
  const empty = $("upscale-preview-empty");
  if (url && isVideo) {
    if (video.getAttribute("src") !== url) {
      video.pause();
      video.setAttribute("src", url);
      video.load();
    }
    video.classList.remove("hidden");
    img.removeAttribute("src");
    img.alt = "";
    img.classList.add("hidden");
    empty.classList.add("hidden");
  } else if (url) {
    img.src = url;
    img.alt = local
      ? local.name
      : item.prompt
      ? `#${item.id} ${item.prompt}`
      : `Generación #${item.id}`;
    img.classList.remove("hidden");
    video.pause();
    video.removeAttribute("src");
    video.classList.add("hidden");
    empty.classList.add("hidden");
  } else {
    img.removeAttribute("src");
    img.alt = "";
    img.classList.add("hidden");
    video.pause();
    video.removeAttribute("src");
    video.classList.add("hidden");
    empty.classList.remove("hidden");
    if (item) {
      empty.textContent =
        item.status === "error" ? "Origen sin resultado (error)" : "Origen sin resultado";
    } else {
      empty.textContent = isVideo
        ? "Sin generaciones de vídeo"
        : "Sin generaciones de imagen";
    }
  }
  $("upscale-preview").classList.toggle("has-image", Boolean(url) && !isVideo);
  $("upscale-preview").title = isVideo ? "Origen de vídeo" : "Ampliar imagen";
  const baseLabel = isVideo ? "Vídeo de origen" : "Imagen de origen";
  if (local) {
    $("upscale-source-label").textContent = `${baseLabel} — Archivo local: ${local.name}`;
  } else if (item) {
    const name = upscaleItemName(item);
    $("upscale-source-label").textContent = `${baseLabel} — #${item.id}${
      name ? ` ${name}` : ""
    }`;
  } else {
    $("upscale-source-label").textContent = baseLabel;
  }
  $("upscale-source-info").textContent = local
    ? `Archivo local · ${local.name}`
    : item
    ? isVideo
      ? `#${item.id} · ${upscaleItemName(item)} · ${videoEngineLabel(item)} · ${formatGalleryDate(item.created_at)}`
      : `#${item.id} · ${upscaleItemName(item)} · ${item.model_id} · ${formatGalleryDate(item.created_at)}`
    : isVideo
    ? "Elige una miniatura de la galería o genera un vídeo en la pestaña Vídeo"
    : "Elige una miniatura o un archivo local";
}

function applyUpscaleKind() {
  const kind = upscaleKind();
  const isFps = kind === "fps";
  const isVideo = kind !== "image";
  $("upscale-model-field").classList.toggle("hidden", isFps);
  $("upscale-ckpt-field").classList.toggle("hidden", !isFps);
  $("upscale-multiplier-field").classList.toggle("hidden", !isFps);
  $("upscale-file-field").classList.toggle("hidden", isVideo);
  $("upscale-passes-field").classList.toggle("hidden", isVideo);
  $("btn-upscale").textContent = isFps ? "Interpolar" : "Escalar";
  updateUpscaleSourceView();
}

async function finishUpscale() {
  await reloadImageViewerFirstPage();
  state.upscaleSourceId = state.imageViewer.selectedId;
  await loadUpscaleGallery(1);
}

async function finishVideoUpscale() {
  await reloadVideoViewerFirstPage();
  state.upscaleSourceId = state.videoViewer.selectedId;
  await loadUpscaleGallery(1);
  switchTab("video");
}

async function generateUpscale() {
  if (state.busy) {
    return;
  }
  const kind = upscaleKind();
  const local = kind === "image" ? state.upscaleLocalFile : null;
  const source = local ? null : selectedUpscaleSource();
  if (!local && !source) {
    setUpscaleStatus(
      kind !== "image"
        ? "No hay vídeo de origen; genera uno en Vídeo"
        : "No hay imagen de origen; elige una miniatura o un archivo local",
      true
    );
    return;
  }
  const payload = { kind };
  if (kind === "fps") {
    const ckpt = $("upscale-ckpt").value;
    if (!ckpt) {
      setUpscaleStatus("Elige un ckpt RIFE", true);
      return;
    }
    const multiplier = Number($("upscale-multiplier").value);
    if (multiplier !== 2 && multiplier !== 4) {
      setUpscaleStatus("Multiplicador inválido; usa ×2 o ×4", true);
      return;
    }
    payload.source_gen = source.id;
    payload.ckpt = ckpt;
    payload.multiplier = multiplier;
    const fpsIn = Number(source.params && source.params.fps);
    if (Number.isFinite(fpsIn) && fpsIn > 0) {
      payload.fps_in = fpsIn;
    }
  } else if (kind === "video") {
    const model = $("upscale-model").value;
    if (!model) {
      setUpscaleStatus("Elige un modelo de escalado", true);
      return;
    }
    payload.source_gen = source.id;
    payload.model = model;
  } else {
    const model = $("upscale-model").value;
    if (!model) {
      setUpscaleStatus("Elige un modelo de escalado", true);
      return;
    }
    const passes = Number($("upscale-passes").value);
    if (passes !== 1 && passes !== 2) {
      setUpscaleStatus("Escalado inválido; usa ×2 o ×4", true);
      return;
    }
    payload.model = model;
    payload.passes = passes;
    if (local) {
      payload.image_b64 = local.b64;
    } else {
      payload.source_gen = source.id;
    }
  }
  state.busy = true;
  $("btn-upscale").disabled = true;
  setUpscaleStatus("Encolando...");
  try {
    const data = await postJson("/api/upscale", payload);
    await pollJob(
      data.job_id,
      setUpscaleStatus,
      kind === "image" ? finishUpscale : finishVideoUpscale,
      setUpscaleProgress,
      true,
      "btn-upscale-cancel"
    );
  } catch (error) {
    setUpscaleStatus(error.message, true);
  } finally {
    state.busy = false;
    $("btn-upscale").disabled = false;
  }
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

function promptTagsFromText(text) {
  return String(text || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function generalBucket(subcat) {
  const key = GENERAL_SUBCATS.includes(subcat) ? subcat : GENERAL_SUBCAT_FALLBACK;
  if (!Array.isArray(state.promptZones.general[key])) {
    state.promptZones.general[key] = [];
  }
  return state.promptZones.general[key];
}

function allPromptTagKeys() {
  const seen = new Set();
  for (const zone of ZONE_ORDER) {
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        for (const tag of state.promptZones.general[subcat] || []) {
          seen.add(String(tag).toLowerCase());
        }
      }
      continue;
    }
    for (const tag of state.promptZones[zone] || []) {
      seen.add(String(tag).toLowerCase());
    }
  }
  return seen;
}

function zoneScopeTags(zone, subcat) {
  if (!zone || !ZONE_ORDER.includes(zone)) {
    return [];
  }
  if (zone === "general") {
    return generalBucket(subcat);
  }
  return state.promptZones[zone] || [];
}

function seedZonePopoverSelection(zone, subcat) {
  zonePopoverSelected = new Map();
  for (const raw of zoneScopeTags(zone, subcat)) {
    const tag = String(raw == null ? "" : raw);
    const folded = tag.toLowerCase();
    if (folded) {
      zonePopoverSelected.set(folded, tag);
    }
  }
}

function composePrompt() {
  const merged = [];
  const seen = new Set();
  const push = (tags) => {
    for (const raw of tags || []) {
      const tag = String(raw == null ? "" : raw).trim();
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
  };
  for (const zone of ZONE_ORDER) {
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        push(state.promptZones.general[subcat]);
      }
      continue;
    }
    push(state.promptZones[zone]);
  }
  return merged.join(", ");
}

function collectPromptZoneTags() {
  const tags = [];
  const seen = new Set();
  const push = (raw) => {
    if (tags.length >= PROMPT_TAGS_MAX) {
      return;
    }
    const tag = String(raw == null ? "" : raw).trim();
    if (!tag) {
      return;
    }
    const folded = tag.toLowerCase();
    if (seen.has(folded)) {
      return;
    }
    seen.add(folded);
    tags.push(tag);
  };
  for (const zone of ZONE_ORDER) {
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        for (const tag of state.promptZones.general[subcat] || []) {
          push(tag);
        }
      }
      continue;
    }
    for (const tag of state.promptZones[zone] || []) {
      push(tag);
    }
  }
  return tags;
}

function resetPromptZones() {
  state.promptZones.quality = [];
  state.promptZones.safety = [];
  state.promptZones.subject = [];
  state.promptZones.character = [];
  state.promptZones.general = {};
  for (const subcat of GENERAL_SUBCATS) {
    state.promptZones.general[subcat] = [];
  }
}

function pushTagsToZone(zone, tags, subcat, seen) {
  const added = [];
  let target = null;
  if (zone === "general") {
    target = generalBucket(subcat);
  } else if (ZONE_ORDER.includes(zone)) {
    target = state.promptZones[zone];
  }
  if (!target) {
    return added;
  }
  for (const raw of tags || []) {
    const tag = String(raw == null ? "" : raw).trim();
    if (!tag) {
      continue;
    }
    const folded = tag.toLowerCase();
    if (seen.has(folded)) {
      continue;
    }
    seen.add(folded);
    target.push(tag);
    added.push(tag);
  }
  return added;
}

function addTagsToZone(zone, tags, subcat) {
  const added = pushTagsToZone(zone, tags, subcat, allPromptTagKeys());
  renderZoneEditor();
  return added;
}

function removeTagsFromZones(tags) {
  const folded = new Set(
    (tags || [])
      .map((tag) => String(tag == null ? "" : tag).trim().toLowerCase())
      .filter(Boolean)
  );
  if (!folded.size) {
    return;
  }
  for (const zone of ZONE_ORDER) {
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        state.promptZones.general[subcat] = (
          state.promptZones.general[subcat] || []
        ).filter((tag) => !folded.has(String(tag).toLowerCase()));
      }
      continue;
    }
    state.promptZones[zone] = (state.promptZones[zone] || []).filter(
      (tag) => !folded.has(String(tag).toLowerCase())
    );
  }
  renderZoneEditor();
}

function removeTagsFromZoneScope(zone, tags, subcat) {
  const folded = new Set(
    (tags || [])
      .map((tag) => String(tag == null ? "" : tag).trim().toLowerCase())
      .filter(Boolean)
  );
  if (!folded.size) {
    return;
  }
  if (zone === "general") {
    const key = GENERAL_SUBCATS.includes(subcat) ? subcat : GENERAL_SUBCAT_FALLBACK;
    state.promptZones.general[key] = (
      state.promptZones.general[key] || []
    ).filter((tag) => !folded.has(String(tag).toLowerCase()));
    return;
  }
  if (!ZONE_ORDER.includes(zone)) {
    return;
  }
  state.promptZones[zone] = (state.promptZones[zone] || []).filter(
    (tag) => !folded.has(String(tag).toLowerCase())
  );
}

function applyZonesPayload(zonesPayload, { replace = false } = {}) {
  if (replace) {
    resetPromptZones();
  }
  const seen = allPromptTagKeys();
  const added = [];
  for (const item of zonesPayload || []) {
    const zone = item && item.id;
    if (!ZONE_ORDER.includes(zone)) {
      continue;
    }
    if (zone === "general") {
      const subcats =
        Array.isArray(item.subcats) && item.subcats.length
          ? item.subcats
          : [{ id: GENERAL_SUBCAT_FALLBACK, tags: item.tags || [] }];
      for (const block of subcats) {
        added.push(
          ...pushTagsToZone("general", block.tags || [], block.id, seen)
        );
      }
      continue;
    }
    added.push(...pushTagsToZone(zone, item.tags || [], null, seen));
  }
  renderZoneEditor();
  return added;
}

async function mergeZonesText(text) {
  const data = await postJson("/api/prompt/zones", { text });
  return applyZonesPayload(data.zones || []);
}

function countZoneTags(zone) {
  if (zone === "general") {
    return GENERAL_SUBCATS.reduce(
      (total, subcat) => total + (state.promptZones.general[subcat] || []).length,
      0
    );
  }
  return (state.promptZones[zone] || []).length;
}

function updateGenerateState() {
  const button = $("btn-generate");
  if (!button) {
    return;
  }
  button.disabled = state.busy || !composePrompt();
}

function removeTagFromZone(zone, tag, subcat) {
  const folded = String(tag).toLowerCase();
  if (zone === "general") {
    const key = GENERAL_SUBCATS.includes(subcat) ? subcat : GENERAL_SUBCAT_FALLBACK;
    state.promptZones.general[key] = (
      state.promptZones.general[key] || []
    ).filter((item) => String(item).toLowerCase() !== folded);
  } else if (ZONE_ORDER.includes(zone)) {
    state.promptZones[zone] = (state.promptZones[zone] || []).filter(
      (item) => String(item).toLowerCase() !== folded
    );
  }
  renderZoneEditor();
}

function zoneTagsRow(zone, tags, subcat) {
  const row = document.createElement("div");
  row.className = "zone-editor-chips";
  for (const tag of tags || []) {
    const chip = document.createElement("span");
    chip.className = `zone-selected-chip zone-tag zone-${zone}`;
    const text = document.createElement("span");
    text.className = "zone-chip-text";
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "zone-selected-remove";
    remove.textContent = "×";
    remove.title = "Quitar";
    remove.addEventListener("click", () => removeTagFromZone(zone, tag, subcat));
    chip.append(text, remove);
    row.appendChild(chip);
  }
  return row;
}

function zoneAddButton(zone, subcat, label) {
  const add = document.createElement("button");
  add.type = "button";
  add.className = "zone-add";
  add.textContent = "＋";
  add.title = `Añadir a ${label}`;
  add.addEventListener("click", () => {
    openZoneInsert(zone, subcat, add).catch((error) =>
      setStatus(error.message, true)
    );
  });
  return add;
}

function zoneQuickRow(zone, subcat, label) {
  const row = document.createElement("form");
  row.className = "zone-quick";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "zone-quick-input";
  input.placeholder = "Tag(s) separados por comas…";
  input.setAttribute("aria-label", `Añadir tag a ${label}`);
  const insert = document.createElement("button");
  insert.type = "submit";
  insert.className = "zone-quick-add";
  insert.textContent = "Insertar";
  insert.title = `Añadir a ${label}`;
  row.append(input, insert);
  row.addEventListener("submit", (event) => {
    event.preventDefault();
    const tags = promptTagsFromText(input.value);
    if (!tags.length) {
      return;
    }
    const added = addTagsToZone(zone, tags, subcat);
    setStatus(
      added.length
        ? `${added.length} tag(s) añadido(s) a ${label}`
        : `Sin cambios en ${label}: ya estaba`
    );
  });
  return row;
}

function renderZoneEditor() {
  const container = $("zone-editor");
  if (!container) {
    return;
  }
  container.replaceChildren();
  for (const zone of ZONE_ORDER) {
    const label = ZONE_LABELS[zone] || zone;
    const block = document.createElement("section");
    block.className = `zone-block zone-block-${zone}`;
    const head = document.createElement("div");
    head.className = "zone-block-head";
    const title = document.createElement("strong");
    title.className = "zone-block-title";
    title.textContent = label;
    const count = document.createElement("span");
    count.className = "zone-block-count";
    count.textContent = String(countZoneTags(zone));
    head.append(title, count, zoneAddButton(zone, null, label));
    block.appendChild(head);
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        const tags = state.promptZones.general[subcat] || [];
        const subLabel = GENERAL_SUBCAT_LABELS[subcat] || subcat;
        const subBlock = document.createElement("div");
        subBlock.className = "zone-subblock";
        const subHead = document.createElement("div");
        subHead.className = "zone-subblock-head";
        const subTitle = document.createElement("span");
        subTitle.textContent = subLabel;
        subHead.append(subTitle);
        subBlock.append(subHead);
        if (tags.length) {
          subBlock.appendChild(zoneTagsRow("general", tags, subcat));
        }
        subBlock.appendChild(zoneQuickRow("general", subcat, subLabel));
        block.appendChild(subBlock);
      }
    } else {
      block.appendChild(zoneTagsRow(zone, state.promptZones[zone] || [], null));
      block.appendChild(zoneQuickRow(zone, null, label));
    }
    container.appendChild(block);
  }
  const finalArea = $("prompt-final");
  if (finalArea) {
    finalArea.value = composePrompt();
  }
  updateGenerateState();
}

async function copyFinalPrompt() {
  const text = composePrompt();
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = $("prompt-final");
      area.focus();
      area.select();
      document.execCommand("copy");
    }
    setStatus("Prompt copiado");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function selectLora(loraId, weight) {
  return setLoraSelected(loraId, true, weight);
}

async function fetchCharacterProfile(character, mode) {
  const query = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return api(`/api/characters/${character.id}/profile${query}`);
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
        ? "Elige un OC en «Mis OCs» o añade el tag a mano."
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
    box.checked = zonePopoverSelected.has(item.tag.toLowerCase());
    box.addEventListener("change", () => {
      const folded = item.tag.toLowerCase();
      if (box.checked) {
        zonePopoverSelected.set(folded, item.tag);
      } else {
        zonePopoverSelected.delete(folded);
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
  const count = document.createElement("span");
  count.className = "zone-popover-count";
  count.textContent = `${zonePopoverSelected.size} seleccionada${
    zonePopoverSelected.size === 1 ? "" : "s"
  }`;
  container.appendChild(count);
  for (const tag of zonePopoverSelected.values()) {
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
      zonePopoverSelected.delete(String(tag).toLowerCase());
      renderZonePopoverSelected();
      renderZonePopoverGroups();
    });
    chip.append(text, remove);
    container.appendChild(chip);
  }
}

function setZoneOcStatus(text, isError = false) {
  const el = $("zone-ocs-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function renderZoneOcList() {
  const container = $("zone-ocs-list");
  container.replaceChildren();
  if (!state.characters.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin OCs guardados.";
    container.appendChild(empty);
    return;
  }
  for (const character of state.characters) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "zone-oc";
    button.textContent = character.name;
    button.title = (character.tags || []).join(", ") || "sin rasgos";
    button.addEventListener("click", () => {
      applyOcFromPicker(character).catch((error) =>
        setZoneOcStatus(error.message, true)
      );
    });
    container.appendChild(button);
  }
}

async function applyOcFromPicker(character) {
  const mode = $("zone-ocs-traits").checked ? "traits" : "auto";
  const profile = await fetchCharacterProfile(character, mode);
  removeTagsFromZones(zoneOcApplied);
  if (zoneInsertTarget === "character") {
    for (const tag of zoneOcApplied) {
      zonePopoverSelected.delete(String(tag).toLowerCase());
    }
  }
  zoneOcApplied = addTagsToZone(
    "character",
    promptTagsFromText(profile.text)
  );
  if (zoneInsertTarget === "character") {
    for (const tag of zoneOcApplied) {
      zonePopoverSelected.set(String(tag).toLowerCase(), tag);
    }
    renderZonePopoverSelected();
    renderZonePopoverGroups();
  }
  zoneOcCharacter = character;
  const notes = [`modo ${profile.mode}`];
  if (profile.lora) {
    $("zone-ocs-traits-label").classList.remove("hidden");
    const selected = selectLora(profile.lora.id, profile.lora.default_weight);
    notes.push(
      selected
        ? `LoRA ${profile.lora.id} @ ${profile.lora.default_weight} seleccionado`
        : `LoRA ${profile.lora.id} fuera del panel (familia activa)`
    );
  } else {
    $("zone-ocs-traits-label").classList.add("hidden");
    $("zone-ocs-traits").checked = false;
  }
  if ($("zone-ocs-extras").checked && (profile.extras || []).length) {
    const extraAdded = await mergeZonesText(profile.extras.join(", "));
    zoneOcApplied = zoneOcApplied.concat(extraAdded);
    notes.push(`extras a General: ${profile.extras.join(", ")}`);
  }
  setZoneOcStatus(`OC «${character.name}» aplicado · ${notes.join(" · ")}`);
  setStatus(`OC «${character.name}» aplicado a la zona Personaje`);
}

function positionZonePopover() {
  const popover = $("zone-popover");
  if (
    !popover ||
    popover.classList.contains("hidden") ||
    !zonePopoverAnchor ||
    !zonePopoverAnchor.isConnected
  ) {
    return;
  }
  const rect = zonePopoverAnchor.getBoundingClientRect();
  const margin = 8;
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  let left = rect.left;
  let top = rect.bottom + 6;
  if (top + height > window.innerHeight - margin) {
    top = rect.top - height - 6;
  }
  left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
  top = Math.max(margin, Math.min(top, window.innerHeight - height - margin));
  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;
}

async function openZoneInsert(zone, subcat, anchor = null) {
  if (!ZONE_LABELS[zone]) {
    return;
  }
  zoneInsertTarget = zone;
  zonePopoverAnchor = anchor || null;
  zonePopoverOptions = null;
  zonePopoverSubcat = null;
  zonePopoverOriginSubcat = zone === "general" ? subcat || null : null;
  zonePopoverSelected = new Map();
  if (zone !== "general") {
    seedZonePopoverSelection(zone, null);
  }
  zoneOcApplied = [];
  zoneOcCharacter = null;
  const isCharacter = zone === "character";
  $("zone-popover-ocs").classList.toggle("hidden", !isCharacter);
  $("zone-ocs-extras").checked = true;
  $("zone-ocs-traits").checked = false;
  $("zone-ocs-traits-label").classList.add("hidden");
  setZoneOcStatus("");
  if (isCharacter) {
    renderZoneOcList();
    loadCharacters()
      .then(renderZoneOcList)
      .catch((error) => setZoneOcStatus(error.message, true));
  }
  $("zone-popover").classList.remove("hidden");
  $("zone-popover-title").textContent = ZONE_LABELS[zone];
  $("zone-popover-search").value = "";
  $("zone-popover-note").classList.add("hidden");
  $("zone-insert-input").value = "";
  $("zone-popover-tabs").replaceChildren();
  $("zone-popover-groups").replaceChildren();
  renderZonePopoverSelected();
  positionZonePopover();
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
      const wanted = zoneSubcatLocked(subcat) ? null : subcat;
      zonePopoverSubcat = zonePopoverOptions.some(
        (group) => group.id === wanted
      )
        ? wanted
        : defaultGeneralSubcat();
      if (
        zonePopoverOriginSubcat &&
        (zoneSubcatLocked(zonePopoverOriginSubcat) ||
          !zonePopoverOptions.some(
            (group) => group.id === zonePopoverOriginSubcat
          ))
      ) {
        zonePopoverOriginSubcat = null;
      }
      seedZonePopoverSelection(zone, zonePopoverSubcat);
      renderZonePopoverSelected();
    }
    renderZonePopoverTabs();
    renderZonePopoverGroups();
    positionZonePopover();
  } catch (error) {
    if (seq === zonePopoverSeq) {
      setStatus(error.message, true);
    }
  }
}

function closeZoneInsert() {
  zoneInsertTarget = null;
  zonePopoverAnchor = null;
  zonePopoverOptions = null;
  zonePopoverSubcat = null;
  zonePopoverOriginSubcat = null;
  zonePopoverSelected = new Map();
  zoneOcApplied = [];
  zoneOcCharacter = null;
  $("zone-popover").classList.add("hidden");
  $("zone-popover-search").value = "";
  $("zone-popover-tabs").replaceChildren();
  $("zone-popover-groups").replaceChildren();
  $("zone-popover-selected").replaceChildren();
  $("zone-popover-note").classList.add("hidden");
  $("zone-popover-ocs").classList.add("hidden");
  setZoneOcStatus("");
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
      zonePopoverSelected.set(tag.toLowerCase(), tag);
    }
  }
  input.value = "";
  renderZonePopoverSelected();
  renderZonePopoverGroups();
}

function clearZoneSelection() {
  zonePopoverSelected = new Map();
  renderZonePopoverSelected();
  renderZonePopoverGroups();
}

async function insertZoneSelection() {
  const zone = zoneInsertTarget;
  if (!zone) {
    return;
  }
  const selected = Array.from(zonePopoverSelected.values());
  if (zone === "general" && !zonePopoverOriginSubcat) {
    if (!selected.length) {
      setStatus("Selecciona o añade algún tag antes de insertar", true);
      return;
    }
    const added = await mergeZonesText(selected.join(", "));
    closeZoneInsert();
    setStatus(
      added.length
        ? `Insertar: ${added.length} añadido(s)`
        : "Insertar: sin cambios (ya estaban)"
    );
    return;
  }
  const subcat =
    zone === "general"
      ? zonePopoverOriginSubcat || zonePopoverSubcat || GENERAL_SUBCAT_FALLBACK
      : null;
  const selectedFolded = new Set(selected.map((tag) => tag.toLowerCase()));
  const removals = zoneScopeTags(zone, subcat).filter(
    (tag) => !selectedFolded.has(String(tag).toLowerCase())
  );
  const known = allPromptTagKeys();
  const additions = selected.filter(
    (tag) => !known.has(String(tag).toLowerCase())
  );
  if (!additions.length && !removals.length) {
    setStatus("Selecciona o añade algún tag antes de insertar", true);
    return;
  }
  removeTagsFromZoneScope(zone, removals, subcat);
  const added = pushTagsToZone(zone, additions, subcat, allPromptTagKeys());
  renderZoneEditor();
  composePrompt();
  closeZoneInsert();
  const parts = [];
  if (added.length) {
    parts.push(`${added.length} añadido(s)`);
  }
  if (removals.length) {
    parts.push(`${removals.length} quitado(s)`);
  }
  setStatus(`Insertar: ${parts.join(" · ")}`);
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

function refFilename(ref) {
  const source = String((ref && (ref.url || ref.relpath)) || "");
  return source.split("/").pop() || "reference.png";
}

function isSheetRef(ref) {
  if (ref && ref.is_sheet === true) {
    return true;
  }
  return refFilename(ref).startsWith("sheet_");
}

async function useRefAsReference(ref) {
  if (isSheetRef(ref)) {
    const proceed = window.confirm(
      "Esta ref es una hoja (catálogo para IPAdapter M10): como referencia I2I puede copiar el mosaico. ¿Adjuntarla igualmente?"
    );
    if (!proceed) {
      return false;
    }
  }
  await attachReferenceFromUrl(ref.url, refFilename(ref));
  closeOcModal();
  setStatus(
    `Referencia adjuntada (fuerza ${Number($("strength").value).toFixed(2)})`
  );
  return true;
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

function renderOcExtras() {
  const box = $("oc-extras-box");
  const container = $("oc-extras");
  container.replaceChildren();
  box.classList.toggle("hidden", !state.ocExtras.length);
  for (const tag of state.ocExtras) {
    const chip = document.createElement("span");
    chip.className = "oc-selected-chip";
    const text = document.createElement("span");
    text.textContent = tag;
    chip.appendChild(text);
    container.appendChild(chip);
  }
}

async function moveOcExtrasToGeneral() {
  const extras = state.ocExtras.slice();
  if (!extras.length) {
    return;
  }
  const added = await mergeZonesText(extras.join(", "));
  let removed = false;
  if (
    state.ocEditingId != null &&
    window.confirm(
      `Extras insertados en General${
        added.length ? "" : " (ya estaban en el prompt)"
      }. ¿Quitarlos también del OC?`
    )
  ) {
    await api(`/api/characters/${state.ocEditingId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ extras: [] }),
    });
    state.ocExtras = [];
    renderOcExtras();
    await loadCharacters();
    removed = true;
  }
  setOcStatus(
    removed
      ? "Extras movidos a General y quitados del OC"
      : "Extras insertados en General (siguen en el OC)"
  );
}

async function refreshOcCatalog() {
  const group = $("oc-catalog-group").value;
  const query = $("oc-catalog-search").value.trim();
  let items = [];
  if (group) {
    const params = new URLSearchParams();
    params.set("group", group);
    if (query) {
      params.set("q", query);
    }
    const data = await api(`/api/tags?${params.toString()}`);
    items = data.items || [];
  } else {
    const results = await Promise.all(
      OC_TRAIT_GROUPS.map((name) =>
        api(`/api/tags?group=${encodeURIComponent(name)}`)
      )
    );
    items = results.flatMap((data) => data.items || []);
    if (query) {
      const needle = query.toLowerCase();
      items = items.filter(
        (item) =>
          item.tag.toLowerCase().includes(needle) ||
          String(item.label || "").toLowerCase().includes(needle)
      );
    }
  }
  state.ocCatalogItems = items;
  renderOcCatalogResults();
}

async function loadOcCatalog() {
  const data = await api("/api/tags/groups");
  const select = $("oc-catalog-group");
  select.replaceChildren();
  select.appendChild(option("", "Todos los rasgos"));
  for (const group of data.groups || []) {
    if (!OC_TRAIT_GROUPS.includes(group)) {
      continue;
    }
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
  const extrasCount = (character.extras || []).length;
  const tags = document.createElement("span");
  tags.className = "oc-item-tags";
  tags.textContent = `${(character.tags || []).join(", ") || "sin rasgos"}${
    extrasCount ? ` · +${extrasCount} extras` : ""
  }`;
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
  state.ocExtras = [];
  $("oc-form-name").value = "";
  const preprompt = $("oc-form-preprompt");
  preprompt.value =
    state.ocPrepromptDefault ||
    (preprompt.options.length ? preprompt.options[0].value : "");
  $("oc-form-rating").value = "sfw";
  $("oc-form-notes").value = "";
  updateOcFormMode();
  renderOcSelected();
  renderOcExtras();
  renderOcCatalogResults();
}

function fillCharacterForm(character) {
  if (!character) {
    resetOcForm();
    return;
  }
  state.ocEditingId = character.id;
  state.ocSelectedTags = [...(character.tags || [])];
  state.ocExtras = [...(character.extras || [])];
  $("oc-form-name").value = character.name;
  $("oc-form-preprompt").value = character.preprompt;
  $("oc-form-rating").value = character.rating;
  $("oc-form-notes").value = character.notes;
  updateOcFormMode();
  renderOcSelected();
  renderOcExtras();
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
  const profile = await fetchCharacterProfile(character, "auto");
  addTagsToZone("character", promptTagsFromText(profile.text));
  let loraNote = "";
  if (profile.lora) {
    const selected = selectLora(profile.lora.id, profile.lora.default_weight);
    loraNote = selected
      ? ` · LoRA ${profile.lora.id} @ ${profile.lora.default_weight}`
      : ` · LoRA ${profile.lora.id} fuera del panel (familia activa)`;
  }
  let extrasNote = "";
  if ((profile.extras || []).length) {
    await mergeZonesText(profile.extras.join(", "));
    extrasNote = ` · extras a General: ${profile.extras.join(", ")}`;
  }
  $("preprompt").value = character.preprompt;
  $("rating").value = character.rating;
  state.activeCharacterId = character.id;
  renderCharacters();
  await loadCharacterRefs();
  if (!state.negativeTouched) {
    await refreshNegative();
  }
  const refs = state.characterRefs || [];
  const attachable = refs.find((ref) => !isSheetRef(ref));
  let refNote = "";
  if (attachable) {
    await attachReferenceFromUrl(attachable.url, refFilename(attachable));
  } else if (refs.length) {
    refNote = " (solo hojas: sin referencia I2I)";
  }
  closeOcModal();
  setStatus(
    `OC «${character.name}» cargado (${profile.mode})${loraNote}${extrasNote}${refNote}`
  );
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
    if (isSheetRef(ref)) {
      figure.classList.add("is-sheet");
    }
    const img = document.createElement("img");
    img.src = ref.url;
    img.alt = `Referencia ${ref.id}`;
    img.loading = "lazy";
    figure.appendChild(img);
    if (isSheetRef(ref)) {
      const badge = document.createElement("span");
      badge.className = "oc-ref-badge";
      badge.textContent = "hoja";
      const note = document.createElement("p");
      note.className = "oc-ref-note";
      note.textContent = "Para IPAdapter (M10); no recomendada como referencia I2I";
      figure.append(badge, note);
    }
    const link = document.createElement("a");
    link.className = "oc-ref-link";
    link.href = ref.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "Ver/Descargar";
    const use = document.createElement("button");
    use.type = "button";
    use.textContent = "Usar como referencia";
    use.addEventListener("click", () => {
      useRefAsReference(ref).catch((error) => setOcStatus(error.message, true));
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Quitar";
    remove.addEventListener("click", () => {
      removeCharacterRef(ref).catch((error) =>
        setOcStatus(error.message, true)
      );
    });
    figure.append(link, use, remove);
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
    await postJson(`/api/characters/${state.activeCharacterId}/sheet`, {});
    await loadCharacterRefs();
    setOcStatus(
      "Hoja creada: catálogo para IPAdapter (M10); no se adjunta como referencia I2I"
    );
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
  const text = promptFromTags(state.ocSelectedTags);
  mergeZonesText(text)
    .then(() => {
      closeOcModal();
      setStatus("Tags añadidos al prompt");
    })
    .catch((error) => setOcStatus(error.message, true));
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
  try {
    resetOcForm();
    setOcStatus("Modo crear: formulario limpio");
    $("oc-modal").classList.remove("hidden");
  } catch (error) {
    console.error("openOcModal: no se pudo abrir el OC Maker", error);
    setOcStatus(`No se pudo abrir el OC Maker: ${error.message}`, true);
    showUiBanner("OC Maker no disponible: recarga con Ctrl+F5");
    return;
  }
  loadCharacters()
    .then(loadCharacterRefs)
    .catch((error) => setOcStatus(error.message, true));
}

function closeOcModal() {
  $("oc-modal").classList.add("hidden");
}

function switchTab(tab) {
  const image = tab === "image";
  const video = tab === "video";
  const editor = tab === "editor";
  const upscaler = tab === "upscaler";
  $("tab-image").classList.toggle("active", image);
  $("tab-video").classList.toggle("active", video);
  $("tab-editor").classList.toggle("active", editor);
  $("tab-upscaler").classList.toggle("active", upscaler);
  $("panel-image").classList.toggle("active", image);
  $("panel-video").classList.toggle("active", video);
  $("panel-editor").classList.toggle("active", editor);
  $("panel-upscaler").classList.toggle("active", upscaler);
  if (upscaler) {
    applyUpscaleKind();
    loadUpscaleGallery(1).catch((error) => setUpscaleStatus(error.message, true));
  }
}

const PANEL_SECTIONS = {
  zones: true,
  params: false,
  loras: false,
  negative: false,
  ref: false,
};

function panelSectionKey(name) {
  return `waifu.ui.section.${name}`;
}

function readStoredSection(name) {
  try {
    return window.localStorage.getItem(panelSectionKey(name));
  } catch (_error) {
    return null;
  }
}

function storeSection(name, open) {
  try {
    window.localStorage.setItem(panelSectionKey(name), open ? "1" : "0");
  } catch (_error) {
    /* localStorage bloqueado: la sección sigue funcionando sin persistir */
  }
}

function initPanelSections() {
  const sections = document.querySelectorAll("details.panel-section[data-section]");
  if (!sections.length) {
    console.error("initPanelSections: no hay secciones con data-section");
    return;
  }
  for (const details of sections) {
    const name = details.dataset.section;
    const stored = readStoredSection(name);
    const fallback = PANEL_SECTIONS[name] !== false;
    details.open = stored == null ? fallback : stored === "1";
    details.addEventListener("toggle", () => {
      storeSection(name, details.open);
    });
  }
}

const REQUIRED_IDS = [
  "job-status",
  "video-status",
  "tab-image",
  "tab-video",
  "tab-editor",
  "tab-upscaler",
  "btn-enhance",
  "prompt-general",
  "btn-generate",
  "btn-cancel",
  "btn-seed-random",
  "btn-negative-restore",
  "btn-ref-clear",
  "btn-lightbox-close",
  "lightbox",
  "btn-new-generation",
  "btn-describe-image",
  "btn-describe-ref",
  "describe-file",
  "btn-download-image",
  "btn-save-to-oc",
  "image-preview",
  "image-preview-img",
  "image-preview-empty",
  "image-preview-info",
  "image-prev-page",
  "image-next-page",
  "image-page-info",
  "image-thumbs",
  "gallery-prev",
  "gallery-next",
  "video-gallery-prev",
  "video-gallery-next",
  "btn-reload",
  "btn-video-reload",
  "btn-motion",
  "btn-video-generate",
  "btn-video-cancel",
  "video-engine",
  "video-mode",
  "video-preset",
  "video-preset-note",
  "video-seconds",
  "video-h3-profile",
  "video-h3-profile-note",
  "video-h3-seconds",
  "video-h3-seconds-info",
  "video-h3-size",
  "video-h3-size-info",
  "video-h3-variant",
  "video-h3-sage",
  "video-h3-guide",
  "btn-h3-insert-template",
  "btn-h3-copy-guide",
  "h3-guide-status",
  "video-motion-negative",
  "video-input-hint",
  "video-h3-prompt-actions",
  "btn-h3-prompt",
  "h3-prompt-status",
  "enhance-hint",
  "video-preview",
  "video-preview-empty",
  "video-preview-info",
  "video-prev-page",
  "video-next-page",
  "video-page-info",
  "video-thumbs",
  "btn-new-video",
  "editor-prompt",
  "editor-refs",
  "editor-size",
  "editor-manual-size",
  "editor-result",
  "editor-result-img",
  "btn-editor-generate",
  "btn-editor-open-gallery",
  "btn-editor-edit-result",
  "btn-editor-download",
  "editor-gallery-thumbs",
  "editor-gallery-prev",
  "editor-gallery-next",
  "editor-gallery-info",
  "panel-upscaler",
  "upscale-kind",
  "upscale-source-field",
  "upscale-source-label",
  "upscale-source-info",
  "upscale-file-field",
  "upscale-file",
  "upscale-passes-field",
  "upscale-passes",
  "upscale-gallery-thumbs",
  "upscale-gallery-prev",
  "upscale-gallery-next",
  "upscale-gallery-info",
  "upscale-model-field",
  "upscale-model",
  "upscale-model-note",
  "upscale-ckpt-field",
  "upscale-ckpt",
  "upscale-ckpt-note",
  "upscale-multiplier-field",
  "upscale-multiplier",
  "btn-upscale",
  "btn-upscale-cancel",
  "upscale-status",
  "upscale-progress",
  "upscale-progress-fill",
  "upscale-progress-text",
  "upscale-preview",
  "upscale-preview-img",
  "upscale-preview-video",
  "upscale-preview-empty",
  "size",
  "preprompt",
  "btn-preprompt-manage",
  "btn-preprompt-close",
  "preprompt-form",
  "preprompt-modal",
  "negative",
  "zone-editor",
  "prompt-final",
  "btn-copy-prompt",
  "zone-insert-form",
  "zone-insert-cancel",
  "zone-popover-close",
  "zone-popover-search",
  "zone-popover-insert",
  "zone-popover-clear",
  "zone-ocs-extras",
  "zone-ocs-traits",
  "ref-image",
  "model",
  "strength",
  "strength-value",
  "btn-oc",
  "btn-oc-close",
  "btn-oc-add",
  "oc-modal",
  "oc-catalog-group",
  "oc-catalog-search",
  "oc-form",
  "btn-oc-new",
  "btn-oc-cancel-edit",
  "btn-oc-sheet",
  "btn-oc-extras-move",
  "btn-oc-save-close",
  "btn-oc-save-confirm",
  "oc-save-modal",
  "btn-oc-train-close",
  "oc-train-modal",
  "btn-train-more",
  "btn-train-start",
  "train-rank",
  "train-epochs",
  "train-trigger",
  "btn-lora-modal",
  "lora-modal",
  "btn-lora-close",
  "btn-lora-done",
  "btn-lora-clear",
  "lora-search",
  "btn-lora-manage",
  "btn-lora-manage-modal",
  "lora-library-modal",
  "btn-lora-library-close",
  "lora-library-status",
  "lora-library-list",
  "lora-library-form",
  "lora-library-form-title",
  "lora-form-id",
  "lora-form-family",
  "lora-form-file",
  "lora-form-display",
  "lora-form-trigger",
  "lora-form-weight",
  "lora-form-source",
  "lora-form-license",
  "lora-form-notes",
  "btn-lora-form-cancel",
  "vision-modal",
  "btn-vision-close",
  "vision-status",
  "vision-empty",
  "vision-caption-block",
  "vision-caption",
  "btn-vision-copy-caption",
  "vision-tags-block",
  "vision-tags",
  "btn-vision-copy-tags",
  "btn-vision-insert-caption",
  "btn-vision-insert-tags",
];

function bind() {
  const missing = REQUIRED_IDS.filter((id) => !$(id));
  if (missing.length) {
    showUiBanner("UI desactualizada: recarga con Ctrl+F5");
    setStatus("UI desactualizada: recarga con Ctrl+F5", true);
    console.error("bind: faltan elementos de la UI", missing);
  }
  on("tab-image", "click", () => switchTab("image"));
  on("tab-video", "click", () => switchTab("video"));
  on("tab-editor", "click", () => switchTab("editor"));
  on("tab-upscaler", "click", () => switchTab("upscaler"));
  on("btn-enhance", "click", enhancePrompt);
  on("btn-generate", "click", generate);
  on("btn-cancel", "click", cancelJob);
  on("btn-seed-random", "click", toggleSeedRandom);
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
  on("btn-describe-ref", "click", describeRefFromDisk);
  on("describe-file", "change", () => {
    describeSelectedRefFile().catch((error) => setStatus(error.message, true));
  });
  on("btn-lightbox-close", "click", closeLightbox);
  on("btn-describe-image", "click", () => {
    openVisionModal().catch((error) => setStatus(error.message, true));
  });
  on("btn-download-image", "click", downloadSelectedImage);
  on("btn-vision-close", "click", closeVisionModal);
  on("vision-modal", "click", (event) => {
    if (event.target === $("vision-modal")) {
      closeVisionModal();
    }
  });
  on("btn-vision-copy-caption", "click", () => {
    copyVisionText("caption").catch((error) => setVisionStatus(error.message, true));
  });
  on("btn-vision-copy-tags", "click", () => {
    copyVisionText("tags").catch((error) => setVisionStatus(error.message, true));
  });
  on("btn-vision-insert-caption", "click", () => insertVisionFromModal("caption"));
  on("btn-vision-insert-tags", "click", () => insertVisionFromModal("tags"));
  on("image-preview", "click", () => {
    const item = selectedImageView();
    const url = imageViewUrl(item);
    if (url) {
      openLightbox(url, `Generación #${item.id}`);
    }
  });
  on("lightbox", "click", (event) => {
    if (event.target === $("lightbox")) {
      closeLightbox();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeLightbox();
      closeVisionModal();
      closePrepromptModal();
      closeLoraLibrary();
      closeLoraModal();
      const trainModal = $("oc-train-modal");
      if (trainModal && !trainModal.classList.contains("hidden")) {
        closeTrainModal();
        return;
      }
      closeOcModal();
    }
  });
  on("image-prev-page", "click", () => {
    state.imageViewer.page -= 1;
    loadImageViewer();
  });
  on("image-next-page", "click", () => {
    state.imageViewer.page += 1;
    loadImageViewer();
  });
  on("video-prev-page", "click", () => {
    state.videoViewer.page -= 1;
    loadVideoViewer();
  });
  on("video-next-page", "click", () => {
    state.videoViewer.page += 1;
    loadVideoViewer();
  });
  on("btn-new-video", "click", startNewVideo);
  on("btn-reload", "click", () => {
    state.imageViewer.page = 1;
    loadImageViewer();
  });
  on("btn-video-reload", "click", () => {
    state.videoViewer.page = 1;
    loadVideoViewer();
  });
  on("btn-motion", "click", improveMotion);
  on("btn-h3-prompt", "click", improveH3Prompt);
  on("btn-video-generate", "click", generateVideo);
  on("btn-video-cancel", "click", cancelJob);
  on("video-engine", "change", () => {
    applyVideoEngine();
    if ($("video-engine").value !== "wan") {
      setVideoStatus("H3: perfil ClipProj 4B · el preset Wan no aplica");
    }
  });
  on("video-mode", "change", applyVideoEngine);
  on("video-preset", "change", updateVideoPresetNote);
  on("video-seconds", "input", updateVideoDurationInfo);
  on("video-h3-profile", "change", updateH3Notes);
  on("video-h3-seconds", "change", updateH3Notes);
  on("video-h3-size", "change", updateH3Notes);
  on("btn-h3-insert-template", "click", insertH3Template);
  on("btn-h3-copy-guide", "click", copyH3Guide);
  on("video-motion-negative", "input", () => {
    state.videoNegativeTouched = true;
  });
  on("editor-prompt", "input", updateEditorControls);
  on("editor-refs", "change", (event) => {
    addEditorRefs(event.target.files).catch((error) =>
      setEditorStatus(error.message, true)
    );
  });
  on("btn-editor-generate", "click", generateEditor);
  on("editor-size", "change", applyEditorSizeSelection);
  on("btn-editor-open-gallery", "click", openEditorResultInGallery);
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
  on("upscale-kind", "change", () => {
    clearUpscaleSelection();
    applyUpscaleKind();
    loadUpscaleGallery(1).catch((error) => setUpscaleStatus(error.message, true));
  });
  on("upscale-file", "change", (event) => {
    const file = (event.target.files || [])[0];
    useUpscaleLocalFile(file).catch((error) => setUpscaleStatus(error.message, true));
  });
  on("upscale-gallery-prev", "click", () => {
    loadUpscaleGallery(state.upscaleGallery.page - 1).catch((error) =>
      setUpscaleStatus(error.message, true)
    );
  });
  on("upscale-gallery-next", "click", () => {
    loadUpscaleGallery(state.upscaleGallery.page + 1).catch((error) =>
      setUpscaleStatus(error.message, true)
    );
  });
  on("upscale-model", "change", upscaleModelNote);
  on("upscale-ckpt", "change", upscaleCkptNote);
  on("btn-upscale", "click", generateUpscale);
  on("btn-upscale-cancel", "click", cancelJob);
  on("upscale-preview", "click", () => {
    const item = selectedUpscaleSource();
    const url = imageViewUrl(item);
    if (url) {
      openLightbox(url, `Generación #${item.id}`);
    }
  });
  on("size", "change", applySizeSelection);
  on("preprompt", "change", () => {
    refreshNegative().catch((error) => setStatus(error.message, true));
  });
  on("btn-preprompt-manage", "click", openPrepromptModal);
  on("btn-preprompt-close", "click", closePrepromptModal);
  on("preprompt-form", "submit", saveCustomPreprompt);
  on("preprompt-modal", "click", (event) => {
    if (event.target === $("preprompt-modal")) {
      closePrepromptModal();
    }
  });
  on("negative", "input", () => {
    state.negativeTouched = true;
  });
  on("btn-copy-prompt", "click", copyFinalPrompt);
  document.addEventListener("scroll", positionZonePopover, true);
  window.addEventListener("resize", positionZonePopover);
  on("zone-insert-form", "submit", submitZoneInsert);
  on("zone-insert-cancel", "click", closeZoneInsert);
  on("zone-popover-close", "click", closeZoneInsert);
  on("zone-popover-search", "input", renderZonePopoverGroups);
  on("zone-popover-insert", "click", () => {
    insertZoneSelection().catch((error) => setStatus(error.message, true));
  });
  on("zone-popover-clear", "click", clearZoneSelection);
  for (const id of ["zone-ocs-extras", "zone-ocs-traits"]) {
    on(id, "change", () => {
      if (zoneOcCharacter) {
        applyOcFromPicker(zoneOcCharacter).catch((error) =>
          setZoneOcStatus(error.message, true)
        );
      }
    });
  }
  on("ref-image", "change", updateReferencePreview);
  on("model", "change", (event) => {
    applyModel(event.target.value).catch((error) => setStatus(error.message, true));
  });
  on("strength", "input", (event) => {
    $("strength-value").textContent = Number(event.target.value).toFixed(2);
  });
  on("btn-lora-modal", "click", openLoraModal);
  on("btn-lora-close", "click", closeLoraModal);
  on("btn-lora-done", "click", closeLoraModal);
  on("btn-lora-clear", "click", clearLoraSelection);
  on("lora-search", "input", renderLoraModalList);
  on("lora-modal", "click", (event) => {
    if (event.target === $("lora-modal")) {
      closeLoraModal();
    }
  });
  on("btn-lora-manage", "click", openLoraLibrary);
  on("btn-lora-manage-modal", "click", openLoraLibrary);
  on("btn-lora-library-close", "click", closeLoraLibrary);
  on("btn-lora-form-cancel", "click", resetLoraForm);
  on("lora-library-form", "submit", saveLoraEntry);
  on("lora-library-modal", "click", (event) => {
    if (event.target === $("lora-library-modal")) {
      closeLoraLibrary();
    }
  });
  on("btn-oc", "click", openOcModal);
  on("btn-oc-close", "click", closeOcModal);
  on("btn-oc-add", "click", addOcTagsToPrompt);
  on("oc-modal", "click", (event) => {
    if (event.target === $("oc-modal")) {
      closeOcModal();
    }
  });
  on("oc-catalog-group", "change", () => {
    refreshOcCatalog().catch((error) => setOcStatus(error.message, true));
  });
  on("oc-catalog-search", "input", () => {
    if (ocSearchTimer) {
      clearTimeout(ocSearchTimer);
    }
    ocSearchTimer = setTimeout(() => {
      refreshOcCatalog().catch((error) => setOcStatus(error.message, true));
    }, 250);
  });
  on("oc-form", "submit", saveCharacter);
  on("btn-oc-new", "click", () => {
    startNewOc().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-cancel-edit", "click", () => {
    cancelOcEdit().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-sheet", "click", () => {
    createCharacterSheet().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-extras-move", "click", () => {
    moveOcExtrasToGeneral().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-save-close", "click", closeOcSaveModal);
  on("btn-oc-save-confirm", "click", () => {
    confirmOcSave().catch((error) => setOcSaveStatus(error.message, true));
  });
  on("oc-save-modal", "click", (event) => {
    if (event.target === $("oc-save-modal")) {
      closeOcSaveModal();
    }
  });
  on("btn-oc-train-close", "click", closeTrainModal);
  on("oc-train-modal", "click", (event) => {
    if (event.target === $("oc-train-modal")) {
      closeTrainModal();
    }
  });
  on("btn-train-more", "click", () => {
    loadTrainGalleryPage().catch((error) => setTrainStatus(error.message, true));
  });
  on("btn-train-start", "click", () => {
    startTrain().catch((error) => setTrainStatus(error.message, true));
  });
  on("train-rank", "change", updateTrainControls);
  on("train-epochs", "input", updateTrainControls);
  on("train-trigger", "input", updateTrainControls);
  return missing.length === 0;
}

async function init() {
  const failures = [];
  const settle = async (label, fn) => {
    try {
      return await fn();
    } catch (error) {
      failures.push(label);
      console.error(`init: fallo en ${label}`, error);
      return undefined;
    }
  };
  try {
    const bound = await settle("bind", bind);
    if (bound === false) {
      failures.push("bind");
    }
    await settle("secciones", initPanelSections);
    await settle("seed aleatoria", initSeedRandom);
    await settle("presets de video", loadVideoPresets);
    await settle("perfiles H3", loadH3Profiles);
    await settle("video", () => {
      applyVideoEngine();
      updateVideoDurationInfo();
    });
    await settle("editor", updateEditorControls);
    await settle("parámetros", loadParams);
    await settle("formatos", loadFormats);
    await settle("modelos", loadModels);
    await settle("catálogo OC", loadOcCatalog);
    await settle("preprompts OC", loadOcPreprompts);
    await settle("OCs", loadCharacters);
    await settle("negativo", refreshNegative);
    await settle("defaults de arranque", applyStartupDefaults);
    await settle("visor de video", () => loadVideoViewer());
    await settle("visor de imagen", () => loadImageViewer());
    await settle("galería del editor", () => loadEditorGallery(1));
    await settle("upscaler", () => loadUpscaleGallery(1));
    await settle("modelos de upscaler", loadUpscaleModels);
    await settle("zonas", renderZoneEditor);
    await settle("estado del editor", loadEditorStatus);
  } catch (error) {
    console.error("init", error);
    setStatus(`Error al iniciar: ${error.message}`, true);
    return;
  }
  if (failures.length) {
    setStatus(`Fallaron: ${failures.join(", ")}`, true);
  } else {
    setStatus("Listo");
  }
}

document.addEventListener("DOMContentLoaded", init);
