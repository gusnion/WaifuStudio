// WaifuStudio — Pestaña de Upscaler e Interpolación
// Qué hace: escalado de imagen con UltraSharp/DAT e interpolación de vídeo con RIFE.
// Qué no hace: no genera fotogramas base ni gestiona checkpoints de difusión.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import { state, UPSCALE_GALLERY_PAGE_SIZE } from "../state.js";
import {
  $,
  on,
  setStatus,
  option,
  setSelectValue,
  formatGalleryDate,
  isVideoUrl,
  toggleThumbs,
  readFileBase64,
  setProgress,
  setUpscaleStatus,
} from "../dom.js";
import { api, postJson, pollJob, cancelJob } from "../api.js";
import { openLightbox } from "../components/lightbox.js";
import { imageViewUrl, reloadImageViewerFirstPage } from "./image_viewer.js";
import { reloadVideoViewerFirstPage, videoEngineLabel, videoViewUrl } from "./video.js";
import { switchTab } from "../main.js";


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
  $("upscale-sharpen-field").classList.toggle("hidden", isVideo);
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
    const sharpen = Number($("upscale-sharpen").value);
    if (![0, 1, 2].includes(sharpen)) {
      setUpscaleStatus("Mejora de detalle inválida", true);
      return;
    }
    payload.model = model;
    payload.passes = passes;
    payload.sharpen = sharpen;
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


function initUpscalerTab() {
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
  on("btn-toggle-upscale-thumbs", "click", () =>
    toggleThumbs("upscaler-gallery", "btn-toggle-upscale-thumbs")
  );
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
}

export {
  setUpscaleStatus,
  setUpscaleProgress,
  upscaleKind,
  upscaleSourceKind,
  upscaleModelNote,
  upscaleCkptNote,
  loadUpscaleInterpolation,
  loadUpscaleModels,
  upscaleItemName,
  selectedUpscaleSource,
  clearUpscaleLocalFile,
  clearUpscaleSelection,
  selectUpscaleSource,
  renderUpscaleGallery,
  loadUpscaleGallery,
  useUpscaleLocalFile,
  updateUpscaleSourceView,
  applyUpscaleKind,
  finishUpscale,
  finishVideoUpscale,
  generateUpscale,
  initUpscalerTab,
};
