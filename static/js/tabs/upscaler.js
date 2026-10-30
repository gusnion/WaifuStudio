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
  getThumbsCapacity,
} from "../dom.js";
import { api, postJson, pollJob, cancelJob, enqueueJobs } from "../api.js";
import { openLightbox } from "../components/lightbox.js";
import { t } from "../i18n.js";
import { imageViewUrl, reloadImageViewerFirstPage } from "./image_viewer.js";
import { reloadVideoViewerFirstPage, videoEngineLabel, videoViewUrl } from "./video.js";
import { switchTab } from "../navigation.js";


function setUpscaleProgress(progress) {
  setProgress(progress, "upscale");
  if (!progress) return;
  const stateText = progress.state || "running";
  const step = progress.step == null ? "-" : progress.step;
  const total = progress.total == null ? "-" : progress.total;
  const percent = progress.percent == null ? "" : ` · ${Number(progress.percent).toFixed(0)}%`;
  const node = progress.node ? ` · nodo ${progress.node}` : "";
  setUpscaleStatus(`Escalando ${step}/${total}${percent}${node} (${stateText})`);
}

function upscaleKind() {
  const kind = $("upscale-kind").value;
  return kind === "video" || kind === "fps" ? kind : "image";
}

function upscaleSourceKind() {
  return upscaleKind() === "image" ? "image" : "video";
}

function upscaleModelNote() {
  const selectedId = $("upscale-model").value;
  const model = state.upscalers.find((item) => item.id === selectedId);
  const missing = state.upscalers.filter((item) => item.available === false);
  const missingNote = missing.length
    ? ` · No disponibles (faltan en ComfyUI/models/upscale_models): ${missing.map((m) => m.file || m.id).join(", ")}`
    : "";
  if (!state.upscalers.length) {
    $("upscale-model-note").textContent = "Cargando modelos…";
    return;
  }
  if (!model) {
    $("upscale-model-note").textContent = missing.length
      ? `Sin modelos disponibles (faltan en ComfyUI/models/upscale_models: ${missing.map((m) => m.file || m.id).join(", ")})`
      : "Elige un modelo de escalado";
    return;
  }
  if (model.available === false) {
    $("upscale-model-note").textContent = `No disponible: falta ${model.file || model.id} en ComfyUI/models/upscale_models`;
    return;
  }
  $("upscale-model-note").textContent = `Escala ×${model.scale}${model.note ? ` · ${model.note}` : ""}${missingNote}`;
}

function validateSelectedUpscaleModel(modelId) {
  if (!modelId) {
    setUpscaleStatus("Elige un modelo de escalado", true);
    return null;
  }
  const entry = state.upscalers.find((item) => item.id === modelId);
  if (entry && entry.available === false) {
    setUpscaleStatus(
      `Modelo no disponible: falta ${entry.file || entry.id} en ComfyUI/models/upscale_models`,
      true
    );
    return null;
  }
  if (state.upscalers.length > 0 && !entry) {
    setUpscaleStatus(`Modelo de escalado no disponible: ${modelId}`, true);
    return null;
  }
  return modelId;
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
  const rifeSelect = $("upscale-rife-model");
  if (rifeSelect) {
    const previousRife = rifeSelect.value;
    rifeSelect.replaceChildren();
    rifeSelect.appendChild(option("", "Sin interpolación"));
    for (const ckpt of ckpts) {
      rifeSelect.appendChild(option(ckpt, ckpt));
    }
    setSelectValue(rifeSelect, previousRife);
  }
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
    const available = model.available !== false;
    const label = available
      ? `${model.label || model.id} (×${model.scale})`
      : `${model.label || model.id} (×${model.scale}) — No disponible (falta ${model.file || "archivo"})`;
    const opt = option(model.id, label);
    if (!available) {
      opt.disabled = true;
      opt.setAttribute("disabled", "disabled");
      opt.setAttribute(
        "title",
        `No disponible: falta ${model.file || model.id} en ComfyUI/models/upscale_models`
      );
    }
    select.appendChild(opt);
  }
  const previousAvailable = state.upscalers.find(
    (item) => item.id === previous && item.available !== false
  );
  const firstAvailable = state.upscalers.find((item) => item.available !== false);
  if (previousAvailable) {
    setSelectValue(select, previousAvailable.id);
    select.value = previousAvailable.id;
  } else if (firstAvailable) {
    setSelectValue(select, firstAvailable.id);
    select.value = firstAvailable.id;
  } else {
    select.value = "";
  }
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

function clearUpscaleLocalFile(revoke = true) {
  if (state.upscaleLocalFile) {
    if (revoke && state.upscaleLocalFile.url !== state.upscaleLastSourceUrl) {
      try {
        URL.revokeObjectURL(state.upscaleLocalFile.url);
      } catch (_err) {}
    }
    state.upscaleLocalFile = null;
  }
  const input = $("upscale-file");
  if (input) {
    input.value = "";
  }
  clearUpscaleLocalVideo(revoke);
}

function clearUpscaleLocalVideo(revoke = true) {
  if (state.upscaleLocalVideo) {
    if (revoke && state.upscaleLocalVideo.url !== state.upscaleLastSourceUrl) {
      try {
        URL.revokeObjectURL(state.upscaleLocalVideo.url);
      } catch (_err) {}
    }
    state.upscaleLocalVideo = null;
  }
  const input = $("upscale-video-file");
  if (input) input.value = "";
  const note = $("upscale-video-file-note");
  if (note) note.textContent = "";
  const hint = $("upscale-chunk-hint");
  if (hint) hint.hidden = true;
}

async function useUpscaleLocalVideoFile(file) {
  if (!file) return;
  const isVideoMime = String(file.type || "").startsWith("video/");
  if (!isVideoMime && !/\.(mp4|webm)$/i.test(file.name)) {
    throw new Error("El archivo local debe ser un vídeo MP4 o WebM");
  }
  if (file.size > 512 * 1024 * 1024) {
    throw new Error("El vídeo local supera 512 MB; recórtalo antes de subirlo");
  }
  const b64 = await readFileBase64(file);
  clearUpscaleLocalFile(true);
  const url = URL.createObjectURL(file);
  state.upscaleLocalVideo = {
    name: file.name,
    b64,
    url,
    duration: 0,
    width: 0,
    height: 0,
  };
  state.upscaleSourceId = null;
  state.upscaleCompareSlot2 = null;
  if (upscaleCompareActive) setUpscaleCompareActive(false);
  const probe = document.createElement("video");
  probe.preload = "metadata";
  probe.src = url;
  probe.addEventListener("loadedmetadata", () => {
    if (!state.upscaleLocalVideo || state.upscaleLocalVideo.url !== url) return;
    state.upscaleLocalVideo.duration = Number(probe.duration) || 0;
    state.upscaleLocalVideo.width = Number(probe.videoWidth) || 0;
    state.upscaleLocalVideo.height = Number(probe.videoHeight) || 0;
    updateUpscaleChunkHint();
  });
  updateUpscaleSourceView();
  updateUpscaleChunkHint();
  setUpscaleStatus(`Vídeo local: ${file.name}`);
}

function updateUpscaleChunkHint() {
  const hint = $("upscale-chunk-hint");
  if (!hint) return;
  const kind = upscaleKind();
  const local = kind === "image" ? null : state.upscaleLocalVideo;
  if (!local || !local.duration) {
    hint.hidden = true;
    hint.textContent = "";
    return;
  }
  const fps = 24;
  const frames = Math.max(1, Math.round(local.duration * fps));
  const height = local.height || 0;
  const chunk = height >= 1080 ? 150 : 300;
  const rife = kind === "video" && $("upscale-rife-model")?.value;
  const perChunk = Math.max(1, Math.floor(chunk / (rife ? 2 : 1)));
  const chunks = Math.max(1, Math.ceil(frames / perChunk));
  const scale = 2;
  const outW = (local.width || 0) * scale;
  const outH = (local.height || 0) * scale;
  const estGb = outW && outH
    ? (frames * outW * outH * 3 * 4 * (rife ? 2 : 1)) / (1024 ** 3)
    : 0;
  hint.hidden = false;
  hint.textContent = `Duración ${local.duration.toFixed(1)} s · ${frames} frames aprox. · ${chunks} tramo${chunks > 1 ? "s" : ""}${estGb ? ` · salida estimada ~${estGb.toFixed(1)} GB` : ""}. El servidor calcula el corte exacto antes de encolar.`;
}


function resolveItemImageUrl(item) {
  if (!item) return null;
  const viewUrl = imageViewUrl(item);
  if (viewUrl) return viewUrl;
  const urls = (item && item.urls) || [];
  if (urls.length && !isVideoUrl(urls[0])) return urls[0];
  const outs = (item && item.outputs) || [];
  if (outs.length && outs[0] && !isVideoUrl(outs[0])) {
    return `/media/${item.id}/${outs[0]}`;
  }
  return null;
}

function hasItemUpscalePair(item) {
  if (!item) return false;
  if (item.params && item.params.source_gen != null) return true;
  if ((state.upscaleSources || []).some((s) => s.params && s.params.source_gen === item.id)) return true;
  if (((state.upscaleGallery && state.upscaleGallery.items) || []).some((s) => s.params && s.params.source_gen === item.id)) return true;
  if (
    state.upscaleLastResultUrl &&
    state.upscaleLastSourceUrl &&
    (item.id === state.upscaleLastResultId || item.id === state.upscaleLastSourceId)
  ) {
    return true;
  }
  return false;
}

let upscaleCompareActive = false;
let upscaleCompareRatio = 0.5;
let upscaleCompareDragging = false;
const upscaleCompareView = { scale: 1, x: 0, y: 0, panning: false, startX: 0, startY: 0 };

function isUpscaleCompareActive() {
  return upscaleCompareActive;
}

function applyUpscaleCompareTransform() {
  const before = $("upscale-compare-before");
  const after = $("upscale-compare-after");
  const transform = `translate(${upscaleCompareView.x}px, ${upscaleCompareView.y}px) scale(${upscaleCompareView.scale})`;
  if (before) {
    before.style.transform = transform;
    before.style.transformOrigin = "center center";
  }
  if (after) {
    after.style.transform = transform;
    after.style.transformOrigin = "center center";
  }
}

function resetUpscaleCompareZoom() {
  upscaleCompareView.scale = 1;
  upscaleCompareView.x = 0;
  upscaleCompareView.y = 0;
  upscaleCompareView.panning = false;
  applyUpscaleCompareTransform();
}

function applyUpscaleCompare() {
  const compare = $("upscale-compare");
  const after = $("upscale-compare-after");
  const handle = $("upscale-compare-handle");
  const label = $("upscale-compare-ratio");
  if (!compare || !after || !handle) return;
  const percent = Math.round(upscaleCompareRatio * 100);
  after.style.clipPath = `inset(0 0 0 ${percent}%)`;
  handle.style.left = `${percent}%`;
  handle.setAttribute("aria-valuenow", String(percent));
  if (label) label.textContent = `${percent}%`;
  applyUpscaleCompareTransform();
}

function setUpscaleCompareImages(beforeUrl, afterUrl) {
  resetUpscaleCompareZoom();
  state.upscaleCompareBeforeUrl = beforeUrl || null;
  state.upscaleCompareAfterUrl = afterUrl || null;
  const beforeImg = $("upscale-compare-before");
  const afterImg = $("upscale-compare-after");
  if (beforeImg) {
    if (beforeUrl) {
      beforeImg.src = beforeUrl;
    } else {
      beforeImg.removeAttribute("src");
    }
  }
  if (afterImg) {
    if (afterUrl) {
      afterImg.src = afterUrl;
    } else {
      afterImg.removeAttribute("src");
    }
  }
  applyUpscaleCompare();
}

function getUpscaleCompareUrls() {
  if (upscaleSourceKind() === "video") {
    return { canCompare: false, before: null, after: null };
  }

  const local = state.upscaleLocalFile;
  const item = local ? null : selectedUpscaleSource();
  const currentUrl = local ? local.url : resolveItemImageUrl(item);

  if (!currentUrl) {
    return { canCompare: false, before: null, after: null };
  }

  // Caso 0: Comparación interactiva con Slot 2 asignado
  if (state.upscaleCompareSlot2 && state.upscaleCompareSlot2 !== currentUrl) {
    return {
      canCompare: true,
      before: currentUrl,
      after: state.upscaleCompareSlot2,
      label: "Comparación interactiva",
    };
  }

  // Caso 1: Ítem seleccionado de galería con referencia de origen (generación escalada previa)
  if (item && item.params && item.params.source_gen != null) {
    const sourceGen = item.params.source_gen;
    const sourceFile = item.params.source_file;
    let sourceUrl = null;
    if (sourceFile) {
      sourceUrl = `/media/${sourceGen}/${sourceFile}`;
    } else {
      const srcItem =
        (state.upscaleSources || []).find((s) => s.id === sourceGen) ||
        (state.upscaleGallery.items || []).find((s) => s.id === sourceGen);
      sourceUrl = srcItem ? resolveItemImageUrl(srcItem) : null;
    }
    const resultUrl = resolveItemImageUrl(item);
    if (sourceUrl && resultUrl && sourceUrl !== resultUrl) {
      return {
        canCompare: true,
        before: currentUrl,
        after: sourceUrl,
        label: `Escalada (#${item.id}) vs Original (#${sourceGen})`,
      };
    }
  }

  // Caso 1b: Ítem seleccionado es la imagen original que fue escalada previamente (tiene hijo escalado)
  if (item && item.id != null) {
    const childItem =
      (state.upscaleSources || []).find((s) => s.params && s.params.source_gen === item.id) ||
      (state.upscaleGallery.items || []).find((s) => s.params && s.params.source_gen === item.id);
    if (childItem) {
      const sourceUrl = currentUrl;
      const childUrl = resolveItemImageUrl(childItem);
      if (sourceUrl && childUrl && sourceUrl !== childUrl) {
        return {
          canCompare: true,
          before: sourceUrl,
          after: childUrl,
          label: `Original (#${item.id}) vs Escalada (#${childItem.id})`,
        };
      }
    }
  }

  // Caso 2: Trabajo de upscale completado en la sesión actual asociado al ítem o URL activa
  if (
    state.upscaleLastSourceUrl &&
    state.upscaleLastResultUrl &&
    state.upscaleLastSourceUrl !== state.upscaleLastResultUrl
  ) {
    const isMatchingResult =
      (item && (item.id === state.upscaleLastResultId || item.id === state.upscaleLastSourceId)) ||
      (local && local.url === state.upscaleLastSourceUrl) ||
      currentUrl === state.upscaleLastResultUrl ||
      currentUrl === state.upscaleLastSourceUrl;
    if (isMatchingResult) {
      const isResultActive = currentUrl === state.upscaleLastResultUrl;
      return {
        canCompare: true,
        before: currentUrl,
        after: isResultActive ? state.upscaleLastSourceUrl : state.upscaleLastResultUrl,
        label: isResultActive ? "Resultado escalado vs Origen" : "Origen vs Resultado escalado",
      };
    }
  }

  // Caso 3: Contraste con otra imagen disponible en la galería o fuentes
  const otherItem =
    (state.upscaleGallery.items || []).find(
      (it) =>
        it &&
        (item ? it.id !== item.id : true) &&
        resolveItemImageUrl(it) &&
        resolveItemImageUrl(it) !== currentUrl
    ) ||
    (state.upscaleSources || []).find(
      (it) =>
        it &&
        (item ? it.id !== item.id : true) &&
        resolveItemImageUrl(it) &&
        resolveItemImageUrl(it) !== currentUrl
    );

  if (otherItem) {
    const otherUrl = resolveItemImageUrl(otherItem);
    return {
      canCompare: true,
      before: currentUrl,
      after: otherUrl,
      label: `#${item ? item.id : "local"} vs #${otherItem.id}`,
    };
  }

  // Caso 4: Solo hay una imagen en el visor (habilita modo comparación a la espera de otra o como Slot 1)
  return {
    canCompare: true,
    before: currentUrl,
    after: currentUrl,
    label: "Selecciona otra miniatura para contrastar",
    solo: true,
  };
}

function updateUpscaleCompare() {
  const btnCompare = $("btn-upscale-compare");
  if (!btnCompare) return;

  if (upscaleSourceKind() === "video") {
    if (upscaleCompareActive) {
      setUpscaleCompareActive(false);
    }
    btnCompare.disabled = true;
    btnCompare.textContent = "Comparar";
    btnCompare.setAttribute("aria-pressed", "false");
    return;
  }

  const isVideo = upscaleSourceKind() === "video";
  const local = !isVideo ? state.upscaleLocalFile : null;
  const item = local ? null : selectedUpscaleSource();
  const currentUrl = local ? local.url : resolveItemImageUrl(item);
  const hasImage = Boolean(currentUrl);

  if (upscaleCompareActive) {
    btnCompare.disabled = false;
    btnCompare.textContent = "Cerrar comparación";
    btnCompare.setAttribute("aria-pressed", "true");
    if (!state.upscaleCompareSlot2) {
      const urls = getUpscaleCompareUrls();
      if (urls.before && urls.after) {
        setUpscaleCompareImages(urls.before, urls.after);
      }
    }
  } else {
    btnCompare.disabled = !hasImage;
    btnCompare.textContent = "Comparar";
    btnCompare.setAttribute("aria-pressed", "false");
  }
}

function updateUpscaleActions() {
  updateUpscaleCompare();
}

function setUpscaleCompareActive(active) {
  upscaleCompareActive = Boolean(active);
  state.upscaleCompareActive = upscaleCompareActive;
  const compare = $("upscale-compare");
  const img = $("upscale-preview-img");
  const btnCompare = $("btn-upscale-compare");

  if (upscaleCompareActive) {
    const urls = getUpscaleCompareUrls();
    if (!urls.canCompare || !urls.before) {
      upscaleCompareActive = false;
      state.upscaleCompareActive = false;
      return;
    }
    setUpscaleCompareImages(urls.before, urls.after || urls.before);
    if (compare) compare.classList.remove("hidden");
    if (img) img.classList.add("hidden");
    $("upscale-preview").classList.add("has-image");
    if (btnCompare) {
      btnCompare.textContent = "Cerrar comparación";
      btnCompare.setAttribute("aria-pressed", "true");
      btnCompare.disabled = false;
    }
    if (urls.solo) {
      setUpscaleStatus("Selecciona otra miniatura de la galería o carga un archivo para comparar");
    } else if (urls.label) {
      setUpscaleStatus(`Comparando: ${urls.label}`);
    }
    applyUpscaleCompare();
  } else {
    resetUpscaleCompareZoom();
    if (compare) compare.classList.add("hidden");
    state.upscaleCompareSlot2 = null;
    updateUpscaleSourceView();
    if (btnCompare) {
      btnCompare.textContent = "Comparar";
      btnCompare.setAttribute("aria-pressed", "false");
    }
    updateUpscaleActions();
  }
}

function clearUpscaleSelection() {
  clearUpscaleLocalFile(true);
  state.upscaleSources = [];
  state.upscaleSourceId = null;
  state.upscaleGallery.page = 1;
  state.upscaleGallery.items = [];
  state.upscaleCompareSlot2 = null;
  state.upscaleLastSourceUrl = null;
  state.upscaleLastSourceId = null;
  state.upscaleLastResultUrl = null;
  state.upscaleLastResultId = null;
  if (upscaleCompareActive) {
    setUpscaleCompareActive(false);
  }
  updateUpscaleActions();
}

function selectUpscaleSource(id) {
  const targetId = id == null ? null : Number(id);
  const clickedItem = (state.upscaleSources || []).find((s) => s.id === targetId);

  clearUpscaleLocalFile(true);

  if (upscaleCompareActive && clickedItem) {
    const prevSourceId = state.upscaleSourceId;
    const prevBeforeUrl = state.upscaleCompareBeforeUrl;

    const prevItem = (state.upscaleSources || []).find((s) => s.id === prevSourceId);
    const prevUrl = prevBeforeUrl || (prevItem ? resolveItemImageUrl(prevItem) : null);
    const clickedUrl = resolveItemImageUrl(clickedItem);
    if (prevUrl && clickedUrl && prevUrl !== clickedUrl) {
      state.upscaleSourceId = prevSourceId != null ? prevSourceId : targetId;
      state.upscaleCompareSlot2 = clickedUrl;
      setUpscaleCompareImages(prevUrl, clickedUrl);
      setUpscaleStatus(`Comparando #${prevSourceId || "origen"} vs #${clickedItem.id}`);
      renderUpscaleGallery();
      return;
    }
  }

  state.upscaleSourceId = targetId;
  state.upscaleCompareSlot2 = null;
  renderUpscaleGallery();
  updateUpscaleSourceView();
}

function selectUpscaleGalleryItem(itemOrId) {
  const id = typeof itemOrId === "object" && itemOrId !== null ? itemOrId.id : itemOrId;
  return selectUpscaleSource(id);
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
  const pageSize = getThumbsCapacity("upscale-gallery-thumbs");
  gallery.pageSize = pageSize;
  const wanted = Math.max(1, Math.trunc(Number(page)) || 1);
  const offset = (wanted - 1) * pageSize;
  const data = await api(
    `/api/gallery?kind=${kind}&limit=${pageSize}&offset=${offset}`
  );
  const items = data.items || [];
  const count = Number(data.count);
  const total = Number.isFinite(count) && count > 0 ? count : items.length;
  gallery.total = Math.max(1, Math.ceil(total / pageSize));
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
  updateUpscaleActions();
}

async function useUpscaleLocalFile(file) {
  if (!file) {
    return;
  }
  const originalPath = file.path || file.webkitRelativePath || file.name;
  if (state.localFilesOriginalPaths) {
    state.localFilesOriginalPaths.set(file.name, originalPath);
  }
  const b64 = await readFileBase64(file);
  clearUpscaleLocalFile(true);
  state.upscaleLocalFile = {
    name: file.name,
    originalPath,
    b64,
    url: URL.createObjectURL(file),
  };
  state.upscaleSourceId = null;
  state.upscaleCompareSlot2 = null;
  if (upscaleCompareActive) {
    setUpscaleCompareActive(false);
  }
  renderUpscaleGallery();
  updateUpscaleSourceView();
  setUpscaleStatus(`Archivo local: ${file.name}`);
}

function updateUpscaleSourceView() {
  const isVideo = upscaleSourceKind() === "video";
  const local = isVideo ? state.upscaleLocalVideo : state.upscaleLocalFile;
  const item = local ? null : selectedUpscaleSource();
  const url = local ? local.url : isVideo ? videoViewUrl(item) : resolveItemImageUrl(item);
  const img = $("upscale-preview-img");
  const video = $("upscale-preview-video");
  const empty = $("upscale-preview-empty");
  const compare = $("upscale-compare");

  if (upscaleCompareActive && !isVideo) {
    if (compare) compare.classList.remove("hidden");
    img.removeAttribute("src");
    img.alt = "";
    img.classList.add("hidden");
    video.pause();
    video.removeAttribute("src");
    video.classList.add("hidden");
    empty.classList.add("hidden");
  } else {
    if (compare) compare.classList.add("hidden");
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
  }
  $("upscale-preview").classList.toggle("has-image", (Boolean(url) || upscaleCompareActive) && !isVideo);
  $("upscale-preview").title = isVideo
    ? "Origen de vídeo"
    : upscaleCompareActive
    ? "Comparación antes/después"
    : "Ampliar imagen";
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

  updateUpscaleActions();
}

function upscaleActionLabel() {
  return upscaleKind() === "fps" ? "Interpolar" : "Escalar";
}

function applyUpscaleKind() {
  const kind = upscaleKind();
  const isFps = kind === "fps";
  const isVideo = kind !== "image";
  if (isVideo && upscaleCompareActive) {
    setUpscaleCompareActive(false);
  }
  $("upscale-model-field").classList.toggle("hidden", isFps);
  $("upscale-ckpt-field").classList.toggle("hidden", !isFps);
  $("upscale-multiplier-field").classList.toggle("hidden", !isFps);
  $("upscale-file-field").classList.toggle("hidden", isVideo);
  $("upscale-video-file-field").classList.toggle("hidden", !isVideo);
  $("upscale-chunks-field")?.classList.toggle("hidden", !isVideo);
  if (isVideo) updateUpscaleChunkHint();
  else {
    const hint = $("upscale-chunk-hint");
    if (hint) hint.hidden = true;
  }
  $("upscale-passes-field").classList.toggle("hidden", isVideo || isFps);
  $("upscale-mode-field").classList.toggle("hidden", isVideo || isFps);
  const isDiffMode = !isVideo && !isFps && $("upscale-mode") && $("upscale-mode").value !== "fast";
  $("upscale-denoise-field").classList.toggle("hidden", !isDiffMode || $("upscale-mode")?.value !== "hires");
  $("upscale-diffusion-model-field")?.classList.toggle("hidden", !isDiffMode || $("upscale-mode")?.value !== "hires");
  $("upscale-sharpen-method-field").classList.toggle("hidden", isFps);
  const sharpenOn = $("upscale-sharpen-method") && $("upscale-sharpen-method").value !== "none";
  $("upscale-sharpen-field").classList.toggle("hidden", isFps || !sharpenOn);
  $("upscale-rife-model-field").classList.toggle("hidden", kind !== "video");
  $("btn-upscale").textContent = upscaleActionLabel();  updateUpscaleSourceView();
  updateUpscaleActions();
}

async function finishUpscale(job) {
  await reloadImageViewerFirstPage();
  const sourceBeforeUrl = state.upscaleLocalFile ? state.upscaleLocalFile.url : (state.upscaleLastSourceUrl || null);
  const sourceBeforeId = state.upscaleLastSourceId || state.upscaleSourceId;
  const localFile = state.upscaleLocalFile;
  if (state.upscaleLocalFile) {
    state.upscaleLocalFile = null;
    const input = $("upscale-file");
    if (input) input.value = "";
  }
  await loadUpscaleGallery(1);
  const resultItem = (state.upscaleGallery.items || []).find((it) => it.id === state.imageViewer.selectedId) || (state.upscaleGallery.items || [])[0];
  if (resultItem) {
    state.upscaleSourceId = resultItem.id;
  }
  const resultUrl = resultItem ? resolveItemImageUrl(resultItem) : (job && job.outputs && job.outputs[0] && job.outputs[0].url);
  if (resultUrl && resultItem) {
    state.upscaleLastResultUrl = resultUrl;
    state.upscaleLastResultId = resultItem.id;
    if (sourceBeforeUrl) {
      if (
        state.upscaleLastSourceUrl &&
        state.upscaleLastSourceUrl !== sourceBeforeUrl &&
        state.upscaleLastSourceUrl.startsWith("blob:")
      ) {
        try {
          URL.revokeObjectURL(state.upscaleLastSourceUrl);
        } catch (_err) {}
      }
      state.upscaleLastSourceUrl = sourceBeforeUrl;
      state.upscaleLastSourceId = sourceBeforeId;
    }
  } else if (localFile && localFile.url && localFile.url !== state.upscaleLastSourceUrl) {
    try {
      URL.revokeObjectURL(localFile.url);
    } catch (_err) {}
  }
  updateUpscaleSourceView();
  updateUpscaleActions();
  if (upscaleCompareActive) {
    const urls = getUpscaleCompareUrls();
    if (urls.canCompare && urls.before && urls.after && !urls.solo) {
      setUpscaleCompareImages(urls.before, urls.after);
    }
  }
}

async function finishVideoUpscale() {
  clearUpscaleLocalVideo(true);
  await reloadVideoViewerFirstPage();
  state.upscaleSourceId = state.videoViewer.selectedId;
  await loadUpscaleGallery(1);
  switchTab("video");
}

async function generateUpscale() {
  const kind = upscaleKind();
  const localImage = kind === "image" ? state.upscaleLocalFile : null;
  const localVideo = kind === "image" ? null : state.upscaleLocalVideo;
  const source = (localImage || localVideo) ? null : selectedUpscaleSource();
  if (!localImage && !localVideo && !source) {
    setUpscaleStatus(
      kind !== "image"
        ? "No hay vídeo de origen; elige uno de la galería o carga un vídeo local"
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
    if (localVideo) {
      payload.video_b64 = localVideo.b64;
      payload.filename = localVideo.name;
    } else {
      payload.source_gen = source.id;
      const fpsIn = Number(source.params && source.params.fps);
      if (Number.isFinite(fpsIn) && fpsIn > 0) {
        payload.fps_in = fpsIn;
      }
    }
    payload.ckpt = ckpt;
    payload.multiplier = multiplier;
  } else if (kind === "video") {
    const model = $("upscale-model").value;
    if (!model) {
      setUpscaleStatus("Elige un modelo de escalado", true);
      return;
    }
    if (localVideo) {
      payload.video_b64 = localVideo.b64;
      payload.filename = localVideo.name;
    } else {
      payload.source_gen = source.id;
    }
    payload.model = model;
    const sharpen = Number($("upscale-sharpen").value);
    if ([0, 1, 2].includes(sharpen) && sharpen > 0) {
      payload.sharpen = sharpen;
    }
    const sharpenMethod = $("upscale-sharpen-method") ? $("upscale-sharpen-method").value : "legacy";
    if (sharpenMethod && sharpenMethod !== "legacy") {
      payload.sharpen_method = sharpenMethod;
    }
    const rifeModel = $("upscale-rife-model") ? $("upscale-rife-model").value : "";
    if (rifeModel) {
      payload.rife_model = rifeModel;
    }
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
    const sharpenMethod = $("upscale-sharpen-method") ? $("upscale-sharpen-method").value : "legacy";
    if (sharpenMethod && sharpenMethod !== "legacy") {
      payload.sharpen_method = sharpenMethod;
    }
    const upscaleMode = $("upscale-mode") ? $("upscale-mode").value : "fast";
    if (upscaleMode && upscaleMode !== "fast") {
      payload.upscale_mode = upscaleMode;
      const denoiseVal = Number($("upscale-denoise").value);
      if (Number.isFinite(denoiseVal)) {
        payload.denoise = denoiseVal;
      }
      const diffusion = $("upscale-diffusion-model")?.value;
      if (upscaleMode === "hires" && diffusion) {
        payload.diffusion_model = diffusion;
      }
    }
    if (localImage) {
      payload.image_b64 = localImage.b64;
    } else {
      payload.source_gen = source.id;
    }
    const sourceBeforeUrl = localImage ? localImage.url : resolveItemImageUrl(source);
    state.upscaleLastSourceUrl = sourceBeforeUrl;
    state.upscaleLastSourceId = source ? source.id : null;
    state.upscaleLastResultUrl = null;
    state.upscaleLastResultId = null;
  }
  const btn = $("btn-upscale");
  if (btn) btn.disabled = true;
  setUpscaleStatus("Encolando...");
  try {
    const data = await postJson("/api/upscale", payload);
    loadUpscaleGallery(1).catch(() => {});
    await enqueueJobs(data.job_id, {
      statusFn: setUpscaleStatus,
      onDone: kind === "image" ? finishUpscale : finishVideoUpscale,
      progressFn: setUpscaleProgress,
      manageCancel: true,
      cancelButtonId: "btn-upscale-cancel",
    });
  } catch (error) {
    setUpscaleStatus(error.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = state.activeJobsCount > 0 ? `${t("queue_prefix")} (${state.activeJobsCount})` : upscaleActionLabel();
    }
  }
}


async function loadDiffusionModels() {
  const select = $("upscale-diffusion-model");
  if (!select) return;
  try {
    const data = await api("/api/models");
    const items = Array.isArray(data) ? data : Array.isArray(data.items) ? data.items : [];
    const imageModels = items.filter((model) => ["anima", "sdxl"].includes(String(model.family || "").toLowerCase()));
    select.replaceChildren();
    for (const model of imageModels) {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = `${model.display_name || model.id} · ${model.subfamily || model.family || ""}`;
      select.appendChild(option);
    }
    if (!imageModels.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Sin modelos de imagen registrados";
      select.appendChild(option);
      select.disabled = true;
    }
  } catch (_error) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No se pudieron cargar los modelos";
    select.replaceChildren(option);
    select.disabled = true;
  }
}

function initUpscalerTab() {
  on("upscale-kind", "change", () => {
    clearUpscaleSelection();
    applyUpscaleKind();
    loadUpscaleGallery(1).catch((error) => setUpscaleStatus(error.message, true));
  });
  window.addEventListener("waifu:queue-updated", () => {
    const btn = $("btn-upscale");
    if (btn) {
      btn.textContent = state.activeJobsCount > 0 ? `${t("queue_prefix")} (${state.activeJobsCount})` : upscaleActionLabel();
    }
  });
  on("upscale-file", "change", (event) => {
    const file = (event.target.files || [])[0];
    useUpscaleLocalFile(file).catch((error) => setUpscaleStatus(error.message, true));
  });
  on("upscale-video-file", "change", (event) => {
    const file = (event.target.files || [])[0];
    useUpscaleLocalVideoFile(file).catch((error) => setUpscaleStatus(error.message, true));
  });
  on("upscale-rife-model", "change", updateUpscaleChunkHint);
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
  on("upscale-mode", "change", () => {
    const isDiffMode = upscaleKind() === "image" && $("upscale-mode") && $("upscale-mode").value !== "fast";
    $("upscale-denoise-field").classList.toggle("hidden", !isDiffMode);
  });
  loadDiffusionModels();
  on("upscale-mode", "change", applyUpscaleKind);
  on("upscale-sharpen-method", "change", applyUpscaleKind);
  on("btn-upscale", "click", generateUpscale);
  on("btn-upscale-cancel", "click", cancelJob);
  on("upscale-preview", "click", () => {
    if (upscaleCompareActive) {
      return;
    }
    const item = selectedUpscaleSource();
    const url = resolveItemImageUrl(item);
    if (url) {
      openLightbox(url, `Generación #${item.id}`);
    }
  });

  on("btn-upscale-compare", "click", () => {
    setUpscaleCompareActive(!upscaleCompareActive);
  });

  const compareHandle = $("upscale-compare-handle");
  if (compareHandle) {
    compareHandle.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const delta = e.key === "ArrowLeft" ? -0.02 : 0.02;
        upscaleCompareRatio = Math.max(0.01, Math.min(0.99, upscaleCompareRatio + delta));
        applyUpscaleCompare();
      } else if (e.key === "Home" || e.key === "End") {
        e.preventDefault();
        upscaleCompareRatio = e.key === "Home" ? 0.01 : 0.99;
        applyUpscaleCompare();
      }
    });

    compareHandle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      e.preventDefault();
      e.stopPropagation();
      upscaleCompareDragging = true;
      if (compareHandle.setPointerCapture) {
        try {
          compareHandle.setPointerCapture(e.pointerId);
        } catch (_err) {}
      }
    });

    compareHandle.addEventListener("pointermove", (e) => {
      if (!upscaleCompareDragging) return;
      const stage = $("upscale-compare-stage");
      if (!stage) return;
      const rect = stage.getBoundingClientRect();
      if (rect.width <= 0) return;
      let ratio = (e.clientX - rect.left) / rect.width;
      upscaleCompareRatio = Math.max(0.01, Math.min(0.99, ratio));
      applyUpscaleCompare();
    });

    const endDrag = (e) => {
      if (upscaleCompareDragging) {
        upscaleCompareDragging = false;
        if (compareHandle.releasePointerCapture && e && e.pointerId) {
          try {
            compareHandle.releasePointerCapture(e.pointerId);
          } catch (_err) {}
        }
      }
    };
    compareHandle.addEventListener("pointerup", endDrag);
    compareHandle.addEventListener("pointercancel", endDrag);
  }

  const compareStage = $("upscale-compare-stage");
  if (compareStage) {
    compareStage.addEventListener("wheel", (e) => {
      e.preventDefault();
      const current = upscaleCompareView.scale;
      let next = Math.min(8, Math.max(1, current * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      if (next <= 1.02) {
        upscaleCompareView.scale = 1;
        upscaleCompareView.x = 0;
        upscaleCompareView.y = 0;
      } else {
        upscaleCompareView.scale = next;
      }
      applyUpscaleCompareTransform();
    }, { passive: false });

    compareStage.addEventListener("pointerdown", (e) => {
      if (e.target === compareHandle || (compareHandle && compareHandle.contains(e.target))) return;
      if (e.button !== 0 && e.pointerType === "mouse") return;
      if (upscaleCompareView.scale > 1) {
        e.preventDefault();
        upscaleCompareView.panning = true;
        upscaleCompareView.startX = e.clientX - upscaleCompareView.x;
        upscaleCompareView.startY = e.clientY - upscaleCompareView.y;
        if (compareStage.setPointerCapture) {
          try {
            compareStage.setPointerCapture(e.pointerId);
          } catch (_err) {}
        }
        return;
      }
      const rect = compareStage.getBoundingClientRect();
      if (rect.width <= 0) return;
      let ratio = (e.clientX - rect.left) / rect.width;
      upscaleCompareRatio = Math.max(0.01, Math.min(0.99, ratio));
      applyUpscaleCompare();
    });

    compareStage.addEventListener("pointermove", (e) => {
      if (!upscaleCompareView.panning) return;
      e.preventDefault();
      upscaleCompareView.x = e.clientX - upscaleCompareView.startX;
      upscaleCompareView.y = e.clientY - upscaleCompareView.startY;
      applyUpscaleCompareTransform();
    });

    const endPan = (e) => {
      if (upscaleCompareView.panning) {
        upscaleCompareView.panning = false;
        if (compareStage.releasePointerCapture && e && e.pointerId) {
          try {
            compareStage.releasePointerCapture(e.pointerId);
          } catch (_err) {}
        }
      }
    };
    compareStage.addEventListener("pointerup", endPan);
    compareStage.addEventListener("pointercancel", endPan);

    compareStage.addEventListener("dblclick", () => {
      resetUpscaleCompareZoom();
    });
  }

  const compareEl = $("upscale-compare");
  if (compareEl) {
    compareEl.addEventListener("click", (e) => {
      e.stopPropagation();
    });
  }

  window.addEventListener("resize", () => {
    if (upscaleCompareActive) {
      applyUpscaleCompare();
    }
  });

  updateUpscaleActions();
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
  selectUpscaleGalleryItem,
  renderUpscaleGallery,
  loadUpscaleGallery,
  useUpscaleLocalFile,
  updateUpscaleSourceView,
  updateUpscaleActions,
  updateUpscaleCompare,
  getUpscaleCompareUrls,
  resolveItemImageUrl,
  setUpscaleCompareActive,
  isUpscaleCompareActive,
  upscaleCompareActive,
  applyUpscaleKind,
  finishUpscale,
  finishVideoUpscale,
  generateUpscale,
  initUpscalerTab,
};
