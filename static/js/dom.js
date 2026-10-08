// WaifuStudio — Helpers de DOM, UI y Eventos
// dom.js: selectores, toasts, helpers de control y formato.

import { state, SEED_RANDOM_KEY, SEED_RANDOM_MAX, PANEL_SECTIONS } from "./state.js";

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
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setEditorStatus(text, isError = false) {
  const el = $("editor-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setUpscaleStatus(text, isError = false) {
  const el = $("upscale-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setProgress(progress, prefix = "job") {
  const box = $(`${prefix}-progress`);
  const fill = $(`${prefix}-progress-fill`);
  const text = $(`${prefix}-progress-text`);
  if (!box || !fill || !text) return;
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

function setEditorProgress(progress) {
  setProgress(progress, "editor");
}

function setUpscaleProgress(progress) {
  setProgress(progress, "upscale");
}

function refFilename(ref) {
  if (!ref || !ref.url) return "";
  const parts = ref.url.split("/");
  return parts[parts.length - 1] || "";
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
  for (const id of [
  "btn-seed-random",
  "btn-video-seed-random",
  "btn-editor-seed-random",
    "btn-video-seed-random",
    "btn-editor-seed-random",
  ]) {
    const button = $(id);
    if (!button) {
      continue;
    }
    button.classList.toggle("active", state.seedRandom);
    button.setAttribute("aria-pressed", state.seedRandom ? "true" : "false");
  }
}

function initSeedRandom() {
  state.seedRandom = readStoredSeedRandom();
  updateSeedRandomButton();
}

function toggleSeedRandom(statusFn = setStatus) {
  state.seedRandom = !state.seedRandom;
  storeSeedRandom(state.seedRandom);
  updateSeedRandomButton();
  if (typeof statusFn === "function") {
    statusFn(
      state.seedRandom ? "Seed aleatoria activada" : "Seed aleatoria desactivada"
    );
  }
}

function applyRandomSeed(inputId = "seed") {
  if (!state.seedRandom) {
    return;
  }
  const input = $(inputId);
  if (input) {
    input.value = randomSeed();
  }
}


function isVideoUrl(url) {
  return /\.(mp4|webm)$/i.test(String(url || ""));
}


function formatGalleryDate(value) {
  const text = String(value || "").replace("T", " ");
  return text ? text.slice(0, 16) : "sin fecha";
}


function downloadUrlFor(url) {
  const text = String(url || "");
  return text.startsWith("/media/") ? `/api/download/${text.slice("/media/".length)}` : null;
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


function toggleThumbs(containerId, buttonId) {
  const container = $(containerId);
  const btn = $(buttonId);
  if (!container) return;
  const isHidden = container.classList.toggle("hidden");
  if (btn) {
    btn.setAttribute("aria-pressed", isHidden ? "false" : "true");
    btn.textContent = isHidden ? "Mostrar miniaturas" : "Miniaturas";
  }
}


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

export {
  $,
  on,
  showUiBanner,
  setStatus,
  setVideoStatus,
  setEditorStatus,
  setUpscaleStatus,
  setProgress,
  setVideoProgress,
  setEditorProgress,
  setUpscaleProgress,
  refFilename,
  option,
  setSelectValue,
  readFileBase64,
  readStoredSeedRandom,
  storeSeedRandom,
  randomSeed,
  updateSeedRandomButton,
  initSeedRandom,
  toggleSeedRandom,
  applyRandomSeed,
  isVideoUrl,
  formatGalleryDate,
  downloadUrlFor,
  writeClipboard,
  toggleThumbs,
  panelSectionKey,
  readStoredSection,
  storeSection,
  initPanelSections,
};
