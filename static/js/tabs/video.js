// WaifuStudio — Pestaña de Generación de Vídeo
// Qué hace: modos I2V, FLF2V, Ref2VA y V2V con VideoDeltaNet, perfiles y ejecución.
// Qué no hace: no realiza inpainting estático ni entrena checkpoints de vídeo.
// Dependencias: static/js/state.js, static/js/dom.js, static/js/api.js y tabs/video_h3.js.

import {
  state,
  VIDEO_PAGE_SIZE,
  VIDEO_FPS,
  H3_FPS,
  VIDEO_REF_LIMIT,
} from "../state.js";
import {
  $,
  on,
  setVideoStatus,
  setStatus,
  readFileBase64,
  isVideoUrl,
  formatGalleryDate,
  applyRandomSeed,
  toggleThumbs,
  setSelectValue,
  setVideoProgress,
} from "../dom.js";
import { api, postJson, pollJob, cancelJob } from "../api.js";
import {
  defaultH3Seconds,
  selectedH3Profile,
  selectedH3Size,
  fillH3Sizes,
  updateH3Notes,
  updateH3Variants,
  updateVideoDurationInfo,
} from "./video_h3.js";

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

async function attachFileInputFromUrl(inputId, url, name) {
  const input = $(inputId);
  const response = await fetch(url);
  if (!response.ok) {
    input.value = "";
    throw new Error(`imagen no disponible (HTTP ${response.status})`);
  }
  const blob = await response.blob();
  const file = new File([blob], name || "imagen.png", {
    type: blob.type || "image/png",
  });
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
}

async function attachVideoFrameFromUrl(inputId, name) {
  const clean = typeof name === "string" ? name.trim() : "";
  const input = $(inputId);
  if (!clean) {
    input.value = "";
    return;
  }
  try {
    await attachFileInputFromUrl(
      inputId,
      `/api/refs/${encodeURIComponent(clean)}`,
      clean
    );
  } catch (error) {
    input.value = "";
    throw new Error(`frame guardado no disponible (${error.message})`);
  }
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
  $("video-engine").value = "h3";
  $("video-mode").value =
    params.mode === "flf2v" ? "flf2v" : "i2v";
  const storedProfile =
    typeof params.profile === "string" && params.profile
      ? params.profile
      : "referencia";
  setSelectValue($("video-h3-profile"), storedProfile);
  updateH3Variants();
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
  if (params.seed != null) {
    $("video-seed").value = params.seed;
  }
  $("video-prompt").value = String(
    params.prompt || item.prompt || params.motion_positive || ""
  );
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
  if ($("video-engine")) $("video-engine").value = "h3";
  if ($("video-mode")) $("video-mode").value = "i2v";
  $("video-seed").value = $("video-seed").defaultValue || "42";
  $("video-prompt").value = "";
  $("video-image").value = "";
  if ($("video-last-image")) $("video-last-image").value = "";
  const v2vInput = $("video-v2v-input");
  if (v2vInput) v2vInput.value = "";
  const v2vWrap = $("video-v2v-preview-wrap");
  if (v2vWrap) v2vWrap.classList.add("hidden");
  const v2vPreview = $("video-v2v-preview");
  if (v2vPreview) v2vPreview.src = "";
  clearVideoRefs();
  setSelectValue($("video-h3-profile"), "estandar");
  if ($("video-h3-aspect")) setSelectValue($("video-h3-aspect"), "vertical");
  fillH3Sizes();
  updateH3Variants();
  setSelectValue($("video-h3-variant"), "turbo8");
  $("video-h3-sage").checked = false;
  setSelectValue($("video-h3-seconds"), String(defaultH3Seconds()));
  state.videoNegativeTouched = false;
  state.videoVramHint = "";
  applyVideoEngine();
  updateVideoDurationInfo();
  setVideoStatus("Nuevo: opciones por defecto");
}

function updateVideoRefs() {
  const list = $("video-refs-list");
  if (!list) {
    return;
  }
  list.textContent = "";
  (state.videoRefs || []).forEach((ref, index) => {
    const item = document.createElement("div");
    item.className = "editor-ref";
    const img = document.createElement("img");
    img.src = ref.url;
    img.alt = ref.name || `Ref ${index + 1}`;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "Quitar";
    removeBtn.addEventListener("click", () => removeVideoRef(index));
    item.append(img, removeBtn);
    list.appendChild(item);
  });
}

function removeVideoRef(index) {
  if (!state.videoRefs) {
    return;
  }
  const removed = state.videoRefs.splice(index, 1)[0];
  if (removed && removed.url) {
    URL.revokeObjectURL(removed.url);
  }
  updateVideoRefs();
  setVideoStatus(`Referencias: ${state.videoRefs.length}/${VIDEO_REF_LIMIT}`);
}

async function addVideoRefs(fileList) {
  if (!state.videoRefs) {
    state.videoRefs = [];
  }
  const files = Array.from(fileList || []);
  if (!files.length) {
    return;
  }
  const room = Math.max(0, VIDEO_REF_LIMIT - state.videoRefs.length);
  if (files.length > room) {
    setVideoStatus(`Máximo ${VIDEO_REF_LIMIT} referencias de personaje`, true);
  }
  for (const file of files.slice(0, room)) {
    const b64 = await readFileBase64(file);
    state.videoRefs.push({
      name: file.name,
      b64,
      url: URL.createObjectURL(file),
    });
  }
  const inputEl = $("video-refs-input");
  if (inputEl) {
    inputEl.value = "";
  }
  updateVideoRefs();
  if (files.length <= room) {
    setVideoStatus(`Referencias: ${state.videoRefs.length}/${VIDEO_REF_LIMIT}`);
  }
}

function clearVideoRefs() {
  if (state.videoRefs) {
    for (const ref of state.videoRefs) {
      if (ref && ref.url) {
        URL.revokeObjectURL(ref.url);
      }
    }
    state.videoRefs = [];
  }
  const inputEl = $("video-refs-input");
  if (inputEl) {
    inputEl.value = "";
  }
  updateVideoRefs();
}


function readVideoSeed() {
  const value = Number($("video-seed").value);
  return Number.isFinite(value) ? Math.trunc(value) : 42;
}

function setVideoJobStatus(text, isError = false) {
  setVideoStatus(text, isError);
}

async function generateVideo() {
  if (state.busy) {
    return;
  }
  const engine = $("video-engine") ? $("video-engine").value : "h3";
  const mode = $("video-mode") ? $("video-mode").value : "i2v";
  if (mode === "ref2va") {
    if (!state.videoRefs || !state.videoRefs.length) {
      setVideoStatus("Ref2VA requiere al menos una imagen de referencia", true);
      return;
    }
  } else if (mode === "v2v") {
    const v2vInput = $("video-v2v-input");
    const v2vFile = v2vInput && v2vInput.files && v2vInput.files[0];
    if (!v2vFile) {
      setVideoStatus("V2V requiere un archivo de video de referencia (.mp4, .webm)", true);
      return;
    }
  } else {
    const file = $("video-image").files[0];
    if (!file) {
      setVideoStatus("Sube la imagen inicial (first frame)", true);
      return;
    }
  }
  applyRandomSeed("video-seed");
  const payload = {
    engine,
    seed: readVideoSeed(),
    mode,
  };
  try {
    if (mode === "ref2va") {
      payload.profile = "ref2va";
      payload.ref_images_b64 = state.videoRefs.map((r) => {
        const raw = r.b64 || "";
        return raw.includes(",") ? raw.split(",", 2)[1] : raw;
      });
    } else if (mode === "v2v") {
      const v2vInput = $("video-v2v-input");
      const v2vFile = v2vInput.files[0];
      payload.ref_video_b64 = await readFileBase64(v2vFile);
      const firstImg = $("video-image") && $("video-image").files && $("video-image").files[0];
      if (firstImg) {
        payload.image_b64 = await readFileBase64(firstImg);
      }
    } else {
      const file = $("video-image").files[0];
      payload.image_b64 = await readFileBase64(file);
      if (mode === "flf2v") {
        const last = $("video-last-image").files[0];
        if (!last) {
          setVideoStatus("FLF2V requiere la imagen final (last frame)", true);
          return;
        }
        payload.last_image_b64 = await readFileBase64(last);
      }
    }
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
    if (mode !== "ref2va") {
      payload.profile = $("video-h3-profile").value;
    }
    payload.variant = $("video-h3-variant").value;
    payload.sage = $("video-h3-sage").checked;
    const secondsEl = $("video-h3-seconds") || $("video-seconds");
    payload.seconds = Number(secondsEl ? secondsEl.value : 8);
    payload.width = size.width;
    payload.height = size.height;
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
    $("btn-video-generate").disabled = false;
  }
}


function applyVideoEngine() {
  const isWan = $("video-engine") ? $("video-engine").value === "wan" : false;
  const mode = $("video-mode") ? $("video-mode").value : "i2v";
  const showFirst = mode === "i2v" || mode === "flf2v" || mode === "v2v";
  const showLast = mode === "flf2v";
  const showRefs = mode === "ref2va";
  const showV2V = mode === "v2v";

  if ($("video-mode-field")) $("video-mode-field").style.display = "";
  if ($("video-image-field")) {
    $("video-image-field").style.display = showFirst ? "" : "none";
    const imgLabel = $("video-image-label");
    if (imgLabel) {
      imgLabel.textContent = mode === "v2v"
        ? "Imagen de inicio / estilo (opcional)"
        : "Imagen inicial (first frame)";
    }
  }
  const lastField = $("video-last-image-field");
  if (lastField) lastField.style.display = showLast ? "" : "none";
  const refsBox = $("video-refs-box");
  if (refsBox) {
    refsBox.classList.remove("hidden");
    refsBox.style.display = showRefs ? "" : "none";
  }
  const v2vBox = $("video-v2v-box");
  if (v2vBox) {
    v2vBox.classList.remove("hidden");
    v2vBox.style.display = showV2V ? "" : "none";
  }

  if ($("video-h3-guide")) $("video-h3-guide").style.display = isWan ? "none" : "";

  if (mode === "ref2va") {
    setSelectValue($("video-h3-profile"), "ref2va");
  } else if ($("video-h3-profile") && $("video-h3-profile").value === "ref2va") {
    setSelectValue($("video-h3-profile"), "estandar");
  }
  updateH3Variants();
  updateH3Notes();
}


function initVideoTab() {
  on("video-prev-page", "click", () => {
    state.videoViewer.page -= 1;
    loadVideoViewer();
  });
  on("video-next-page", "click", () => {
    state.videoViewer.page += 1;
    loadVideoViewer();
  });
  on("btn-new-video", "click", startNewVideo);
  on("btn-toggle-video-thumbs", "click", () =>
    toggleThumbs("video-thumbs", "btn-toggle-video-thumbs")
  );
  on("btn-video-reload", "click", () => {
    state.videoViewer.page = 1;
    loadVideoViewer();
  });
  on("btn-video-generate", "click", generateVideo);
  on("btn-video-cancel", "click", cancelJob);
  on("video-engine", "change", applyVideoEngine);
  on("video-mode", "change", applyVideoEngine);
  on("video-v2v-input", "change", (event) => {
    const file = event.target.files && event.target.files[0];
    const wrap = $("video-v2v-preview-wrap");
    const preview = $("video-v2v-preview");
    if (file && preview && wrap) {
      preview.src = URL.createObjectURL(file);
      wrap.classList.remove("hidden");
    } else if (preview && wrap) {
      preview.src = "";
      wrap.classList.add("hidden");
    }
  });
  on("btn-video-add-refs", "click", () => {
    const input = $("video-refs-input");
    if (input) input.click();
  });
  on("video-refs-input", "change", (event) => {
    addVideoRefs(event.target.files).catch((error) =>
      setVideoStatus(error.message, true)
    );
  });
  on("btn-video-clear-refs", "click", clearVideoRefs);
}

export {
  selectedVideoView,
  videoViewUrl,
  videoEngineLabel,
  updateVideoPreview,
  renderVideoThumbs,
  renderVideoViewer,
  loadVideoViewer,
  selectVideoGeneration,
  reloadVideoViewerFirstPage,
  attachFileInputFromUrl,
  attachVideoFrameFromUrl,
  applyVideoSavedFrames,
  reuseVideoGeneration,
  startNewVideo,
  updateVideoRefs,
  removeVideoRef,
  addVideoRefs,
  clearVideoRefs,
  readVideoSeed,
  setVideoJobStatus,
  setVideoProgress,
  generateVideo,
  applyVideoEngine,
  initVideoTab,
};
