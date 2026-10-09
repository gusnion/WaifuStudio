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

let upscaleCompareActive = false;
let upscaleCompareRatio = 0.5;
let upscaleCompareDragging = false;

function isUpscaleCompareActive() {
  return upscaleCompareActive;
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
}

function setUpscaleCompareImages(beforeUrl, afterUrl) {
  state.upscaleCompareBeforeUrl = beforeUrl || null;
  state.upscaleCompareAfterUrl = afterUrl || null;
  const beforeImg = $("upscale-compare-before");
  const afterImg = $("upscale-compare-after");
  if (beforeImg && beforeUrl) {
    beforeImg.src = beforeUrl;
  }
  if (afterImg && afterUrl) {
    afterImg.src = afterUrl;
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

  // Caso 1: Ítem seleccionado de galería con referencia de origen (generación escalada previa)
  if (item && item.params && item.params.source_gen != null) {
    const sourceGen = item.params.source_gen;
    const sourceFile = item.params.source_file;
    let sourceUrl = null;
    if (sourceFile) {
      sourceUrl = `/media/${sourceGen}/${sourceFile}`;
    } else {
      const srcItem = (state.upscaleSources || []).find((s) => s.id === sourceGen);
      sourceUrl = srcItem
        ? resolveItemImageUrl(srcItem)
        : `/media/${sourceGen}/${(item.outputs && item.outputs[0]) || ""}`;
    }
    const resultUrl = resolveItemImageUrl(item);
    if (sourceUrl && resultUrl && sourceUrl !== resultUrl) {
      return {
        canCompare: true,
        before: sourceUrl,
        after: resultUrl,
        label: `Original (#${sourceGen}) vs Escalada (#${item.id})`,
      };
    }
  }

  // Caso 2: Trabajo de upscale completado en la sesión actual asociado al ítem o URL activa
  if (
    state.upscaleLastSourceUrl &&
    state.upscaleLastResultUrl &&
    state.upscaleLastSourceUrl !== state.upscaleLastResultUrl
  ) {
    const isMatchingResult =
      (item && item.id === state.upscaleLastResultId) ||
      currentUrl === state.upscaleLastResultUrl ||
      currentUrl === state.upscaleLastSourceUrl;
    if (isMatchingResult) {
      return {
        canCompare: true,
        before: state.upscaleLastSourceUrl,
        after: state.upscaleLastResultUrl,
        label: "Origen vs Resultado escalado",
      };
    }
  }

  // Caso 3: Comparación interactiva con Slot 2 asignado
  if (state.upscaleCompareSlot2 && state.upscaleCompareSlot2 !== currentUrl) {
    return {
      canCompare: true,
      before: currentUrl,
      after: state.upscaleCompareSlot2,
      label: "Comparación interactiva",
    };
  }

  // Caso 4: Contraste con otra imagen disponible en la galería o fuentes
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

  // Caso 5: Solo hay una imagen en el visor (habilita modo comparación a la espera de otra o como Slot 1)
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
    const urls = getUpscaleCompareUrls();
    if (urls.before && urls.after) {
      setUpscaleCompareImages(urls.before, urls.after);
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
  state.upscaleLastResultUrl = null;
  state.upscaleLastResultId = null;
  if (upscaleCompareActive) {
    setUpscaleCompareActive(false);
  }
  updateUpscaleActions();
}

function selectUpscaleSource(id) {
  if (upscaleCompareActive) {
    const clickedItem = (state.upscaleSources || []).find((s) => s.id === Number(id));
    if (clickedItem) {
      if (clickedItem.params && clickedItem.params.source_gen != null) {
        state.upscaleSourceId = Number(id);
        state.upscaleCompareSlot2 = null;
        const sourceGen = clickedItem.params.source_gen;
        const sourceFile = clickedItem.params.source_file;
        let beforeUrl = null;
        if (sourceFile) {
          beforeUrl = `/media/${sourceGen}/${sourceFile}`;
        } else {
          const srcItem = (state.upscaleSources || []).find((s) => s.id === sourceGen);
          beforeUrl = srcItem ? resolveItemImageUrl(srcItem) : null;
        }
        const afterUrl = resolveItemImageUrl(clickedItem);
        if (beforeUrl && afterUrl && beforeUrl !== afterUrl) {
          setUpscaleCompareImages(beforeUrl, afterUrl);
          setUpscaleStatus(`Comparando original (#${sourceGen}) vs escalada (#${clickedItem.id})`);
          renderUpscaleGallery();
          return;
        }
      }

      const clickedUrl = resolveItemImageUrl(clickedItem);
      if (clickedUrl) {
        state.upscaleCompareSlot2 = clickedUrl;
        const currentUrls = getUpscaleCompareUrls();
        const beforeUrl = currentUrls.before || clickedUrl;
        setUpscaleCompareImages(beforeUrl, clickedUrl);
        setUpscaleStatus(`Comparando con generación #${clickedItem.id}`);
        renderUpscaleGallery();
        return;
      }
    }
  }
  clearUpscaleLocalFile(true);
  state.upscaleSourceId = id == null ? null : Number(id);
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
  const local = !isVideo ? state.upscaleLocalFile : null;
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
  $("upscale-passes-field").classList.toggle("hidden", isVideo);
  $("upscale-sharpen-field").classList.toggle("hidden", isVideo);
  $("btn-upscale").textContent = isFps ? "Interpolar" : "Escalar";
  updateUpscaleSourceView();
  updateUpscaleActions();
}

async function finishUpscale(job) {
  await reloadImageViewerFirstPage();
  state.upscaleSourceId = state.imageViewer.selectedId;
  const sourceBeforeUrl = state.upscaleLocalFile ? state.upscaleLocalFile.url : (state.upscaleLastSourceUrl || null);
  if (state.upscaleLocalFile) {
    state.upscaleLocalFile = null;
    const input = $("upscale-file");
    if (input) input.value = "";
  }
  await loadUpscaleGallery(1);
  const resultItem = (state.upscaleGallery.items || []).find((it) => it.id === state.upscaleSourceId) || (state.upscaleGallery.items || [])[0];
  const resultUrl = resultItem ? resolveItemImageUrl(resultItem) : (job && job.outputs && job.outputs[0] && job.outputs[0].url);
  if (resultUrl) {
    state.upscaleLastResultUrl = resultUrl;
    state.upscaleLastResultId = resultItem ? resultItem.id : state.upscaleSourceId;
    if (sourceBeforeUrl) {
      state.upscaleLastSourceUrl = sourceBeforeUrl;
    }
  }
  updateUpscaleSourceView();
  updateUpscaleActions();
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
    const sourceBeforeUrl = local ? local.url : resolveItemImageUrl(source);
    state.upscaleLastSourceUrl = sourceBeforeUrl;
    state.upscaleLastResultUrl = null;
    state.upscaleLastResultId = null;
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
    compareStage.addEventListener("pointerdown", (e) => {
      if (e.target === compareHandle || (compareHandle && compareHandle.contains(e.target))) return;
      if (e.button !== 0 && e.pointerType === "mouse") return;
      const rect = compareStage.getBoundingClientRect();
      if (rect.width <= 0) return;
      let ratio = (e.clientX - rect.left) / rect.width;
      upscaleCompareRatio = Math.max(0.01, Math.min(0.99, ratio));
      applyUpscaleCompare();
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
