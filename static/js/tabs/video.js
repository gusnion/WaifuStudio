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
  getThumbsCapacity,
} from "../dom.js";
import { api, postJson, pollJob, cancelJob, enqueueJobs } from "../api.js";
import { t } from "../i18n.js";
import {
  defaultH3Seconds,
  selectedH3Profile,
  selectedH3Size,
  fillH3Sizes,
  updateH3Notes,
  updateH3Variants,
  updateVideoDurationInfo,
  updateH3SecondsAvailability,
} from "./video_h3.js";

let v2vPreviewObjectUrl = null;

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
    } else if (item.status === "queued" || item.status === "running") {
      const pending = document.createElement("span");
      pending.className = `thumb-pending is-${item.status}`;
      const spinner = document.createElement("span");
      spinner.className = "queue-spinner";
      const label = document.createElement("span");
      label.textContent = item.status === "running" ? "Generando" : "En cola";
      pending.appendChild(spinner);
      pending.appendChild(label);
      button.appendChild(pending);
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
  const pageSize = getThumbsCapacity("video-thumbs");
  viewer.pageSize = pageSize;
  viewer.page = Math.max(1, viewer.page);
  const offset = (viewer.page - 1) * pageSize;
  try {
    const data = await api(
      `/api/gallery?kind=video&limit=${pageSize}&offset=${offset}`
    );
    const raw = data.items || [];
    const count = Number(data.count);
    const total = Number.isFinite(count) && count > 0 ? count : raw.length;
    viewer.total = Math.max(1, Math.ceil(total / pageSize));
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

function videoReuseParams(params = {}) {
  const p = params || {};
  let mode = "i2v";
  if (p.mode === "ref2va") mode = "ref2va";
  else if (p.mode === "v2v") mode = "v2v";
  else if (p.mode === "flf2v") mode = "flf2v";

  const profile =
    mode === "ref2va" || mode === "v2v"
      ? "ref2va"
      : typeof p.profile === "string" && p.profile
      ? p.profile
      : "referencia";

  const variant =
    mode === "ref2va" || mode === "v2v"
      ? "vdn8"
      : typeof p.variant === "string" && p.variant
      ? p.variant
      : "turbo4";

  const sage = p.sage === true;

  const seconds = Number.isFinite(Number(p.seconds)) ? Number(p.seconds) : null;
  const width = Number.isFinite(Number(p.width)) ? Number(p.width) : null;
  const height = Number.isFinite(Number(p.height)) ? Number(p.height) : null;
  const seed = p.seed != null ? p.seed : null;
  const prompt = String(p.prompt || p.motion_positive || "");

  // Personalizado
  const encoder = p.encoder != null ? String(p.encoder) : "4b";
  const lora_strength =
    p.lora_strength != null && Number.isFinite(Number(p.lora_strength))
      ? Number(p.lora_strength)
      : 1.0;
  const denoise =
    p.denoise != null && Number.isFinite(Number(p.denoise))
      ? Number(p.denoise)
      : 1.0;
  const sampler_name =
    p.sampler_name != null ? String(p.sampler_name) : "res_multistep";
  const scheduler =
    p.scheduler != null ? String(p.scheduler) : "simple";
  const tile_size =
    p.tile_size != null && Number.isFinite(Number(p.tile_size))
      ? Number(p.tile_size)
      : 256;
  const include_audio =
    p.include_audio !== undefined ? Boolean(p.include_audio) : true;

  const ref_images = Array.isArray(p.ref_images)
    ? p.ref_images
    : p.ref_images
    ? [p.ref_images]
    : [];
  const ref_video = typeof p.ref_video === "string" ? p.ref_video.trim() : "";

  return {
    mode,
    profile,
    variant,
    sage,
    seconds,
    width,
    height,
    seed,
    prompt,
    encoder,
    lora_strength,
    denoise,
    sampler_name,
    scheduler,
    tile_size,
    include_audio,
    ref_images,
    ref_video,
  };
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

  // BUG-VIDEO-03: Restaura params.ref_images en state.videoRefs y refresca UI
  clearVideoRefs();
  const refImages = Array.isArray(saved.ref_images)
    ? saved.ref_images
    : (saved.ref_images ? [saved.ref_images] : []);
  for (const refName of refImages) {
    const clean = typeof refName === "string" ? refName.trim() : "";
    if (!clean) continue;
    try {
      const url = clean.startsWith("data:") || clean.startsWith("blob:")
        ? clean
        : `/api/refs/${encodeURIComponent(clean)}`;
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const file = new File([blob], clean, { type: blob.type || "image/png" });
      const b64 = await readFileBase64(file);
      state.videoRefs.push({
        name: clean,
        originalPath: clean,
        b64,
        url: URL.createObjectURL(file),
      });
    } catch (err) {
      warnings.push(`ref ${clean} no disponible (${err.message})`);
    }
  }
  updateVideoRefs();

  // BUG-VIDEO-03: Restaura params.ref_video en input/flujo V2V
  const refVid = typeof saved.ref_video === "string" ? saved.ref_video.trim() : "";
  if (refVid) {
    try {
      await attachFileInputFromUrl(
        "video-v2v-input",
        `/api/refs/${encodeURIComponent(refVid)}`,
        refVid
      );
      const v2vInput = $("video-v2v-input");
      const file = v2vInput && v2vInput.files && v2vInput.files[0];
      const wrap = $("video-v2v-preview-wrap");
      const preview = $("video-v2v-preview");
      if (file && preview && wrap) {
        if (v2vPreviewObjectUrl) URL.revokeObjectURL(v2vPreviewObjectUrl);
        v2vPreviewObjectUrl = URL.createObjectURL(file);
        preview.src = v2vPreviewObjectUrl;
        wrap.classList.remove("hidden");
      }
    } catch (_err) {
      const v2vInput = $("video-v2v-input");
      if (v2vInput) v2vInput.title = `Video V2V previo: ${refVid}`;
      saved._ref_video_status = `video previo: ${refVid}`;
    }
  }

  if (warnings.length) {
    throw new Error(warnings.join("; "));
  }
}

async function reuseVideoGeneration(item) {
  const params = item.params || {};
  const reused = videoReuseParams(params);

  $("video-engine").value = "wan";
  $("video-mode").value = reused.mode;

  setSelectValue($("video-h3-profile"), reused.profile);
  updateH3Variants();
  setSelectValue($("video-h3-variant"), reused.variant);

  $("video-h3-sage").checked = reused.sage;
  if (reused.seconds != null && state.videoH3Seconds.includes(reused.seconds)) {
    $("video-h3-seconds").value = String(reused.seconds);
  }
  if (reused.width != null && reused.height != null) {
    setSelectValue($("video-h3-size"), `${reused.width}x${reused.height}`);
  }

  // BUG-VIDEO-05: Restaura Personalizado y badges/controles
  const encEl = $("video-h3-encoder");
  if (encEl) setSelectValue(encEl, reused.encoder);
  const warn = $("video-h3-encoder-warning");
  if (warn) warn.classList.toggle("hidden", reused.encoder !== "32b");

  const loraSlider = $("video-h3-lora-strength");
  if (loraSlider) loraSlider.value = String(reused.lora_strength);
  const loraBadge = $("video-h3-lora-strength-val");
  if (loraBadge) loraBadge.textContent = reused.lora_strength.toFixed(2);

  const denoiseSlider = $("video-h3-denoise");
  if (denoiseSlider) denoiseSlider.value = String(reused.denoise);
  const denoiseBadge = $("video-h3-denoise-val");
  if (denoiseBadge) denoiseBadge.textContent = reused.denoise.toFixed(2);

  const samplerEl = $("video-h3-sampler");
  if (samplerEl) setSelectValue(samplerEl, reused.sampler_name);

  const schedEl = $("video-h3-scheduler");
  if (schedEl) setSelectValue(schedEl, reused.scheduler);

  const tileEl = $("video-h3-tile-size");
  if (tileEl) setSelectValue(tileEl, String(reused.tile_size));

  const audioEl = $("video-h3-audio");
  if (audioEl) audioEl.checked = reused.include_audio;

  updateH3Notes();
  if (reused.seed != null) {
    $("video-seed").value = reused.seed;
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
  } else if (params._ref_video_status) {
    setVideoStatus(`Cargado #${item.id} (${params._ref_video_status})`);
  } else {
    setVideoStatus(`Cargado #${item.id}`);
  }
}

function startNewVideo() {
  if ($("video-engine")) $("video-engine").value = "wan";
  if ($("video-mode")) $("video-mode").value = "i2v";
  $("video-seed").value = $("video-seed").defaultValue || "42";
  $("video-prompt").value = "";
  $("video-image").value = "";
  if ($("video-last-image")) $("video-last-image").value = "";
  const v2vInput = $("video-v2v-input");
  if (v2vInput) {
    v2vInput.value = "";
    v2vInput.removeAttribute("title");
  }
  if (v2vPreviewObjectUrl) {
    URL.revokeObjectURL(v2vPreviewObjectUrl);
    v2vPreviewObjectUrl = null;
  }
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

  // Reset controles personalizado
  const encEl = $("video-h3-encoder");
  if (encEl) setSelectValue(encEl, "4b");
  const warn = $("video-h3-encoder-warning");
  if (warn) warn.classList.add("hidden");
  const loraSlider = $("video-h3-lora-strength");
  if (loraSlider) loraSlider.value = "1.0";
  const loraBadge = $("video-h3-lora-strength-val");
  if (loraBadge) loraBadge.textContent = "1.00";
  const denoiseSlider = $("video-h3-denoise");
  if (denoiseSlider) denoiseSlider.value = "1.0";
  const denoiseBadge = $("video-h3-denoise-val");
  if (denoiseBadge) denoiseBadge.textContent = "1.00";
  const samplerEl = $("video-h3-sampler");
  if (samplerEl) setSelectValue(samplerEl, "res_multistep");
  const schedEl = $("video-h3-scheduler");
  if (schedEl) setSelectValue(schedEl, "simple");
  const tileEl = $("video-h3-tile-size");
  if (tileEl) setSelectValue(tileEl, "256");
  const audioEl = $("video-h3-audio");
  if (audioEl) audioEl.checked = true;

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
  if (removed) {
    if (removed.url) {
      URL.revokeObjectURL(removed.url);
    }
    if (removed.name && state.localFilesOriginalPaths) {
      state.localFilesOriginalPaths.delete(removed.name);
    }
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
    const originalPath = file.path || file.webkitRelativePath || file.name;
    if (state.localFilesOriginalPaths) {
      state.localFilesOriginalPaths.set(file.name, originalPath);
    }
    const b64 = await readFileBase64(file);
    state.videoRefs.push({
      name: file.name,
      originalPath,
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
      if (ref) {
        if (ref.url) {
          URL.revokeObjectURL(ref.url);
        }
        if (ref.name && state.localFilesOriginalPaths) {
          state.localFilesOriginalPaths.delete(ref.name);
        }
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

async function generateWanVideo() {
  const mode = $("video-mode")?.value || "i2v";
  if (mode !== "i2v" && mode !== "flf2v") {
    setVideoStatus("Wan solo admite I2V y FLF2V", true);
    return;
  }
  const first = $("video-image")?.files?.[0];
  if (!first) {
    setVideoStatus("Sube la imagen inicial (first frame)", true);
    return;
  }
  const prompt = $("video-prompt")?.value.trim() || "";
  if (!prompt) {
    setVideoStatus("Wan requiere un prompt de movimiento", true);
    return;
  }
  const payload = {
    engine: "wan",
    mode,
    image_b64: await readFileBase64(first),
    motion_positive: prompt,
    motion_negative: "",
    aspect: $("video-h3-aspect")?.value || "vertical",
    preset: $("video-wan-preset")?.value || "rapido",
    seconds: Number($("video-h3-seconds")?.value || 5),
    seed: readVideoSeed(),
  };
  if (mode === "flf2v") {
    const last = $("video-last-image")?.files?.[0];
    if (!last) {
      setVideoStatus("FLF2V requiere la imagen final", true);
      return;
    }
    payload.last_image_b64 = await readFileBase64(last);
  }
  const btn = $("btn-video-generate");
  if (btn) btn.disabled = true;
  setVideoStatus("Encolando vídeo Wan…");
  try {
    const data = await postJson("/api/video/generate", payload);
    reloadVideoViewerFirstPage().catch(() => {});
    await enqueueJobs(data.job_id, {
      statusFn: setVideoJobStatus,
      onDone: reloadVideoViewerFirstPage,
      progressFn: setVideoProgress,
      manageCancel: true,
      cancelButtonId: "btn-video-cancel",
    });
  } catch (error) {
    setVideoStatus(error.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function generateVideo() {
  if (($("video-engine")?.value || "wan") === "wan") {
    await generateWanVideo();
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
    if (mode === "ref2va" || mode === "v2v") {
      payload.profile = "ref2va";
      payload.variant = "vdn8";
    } else {
      payload.profile = $("video-h3-profile").value;
      payload.variant = $("video-h3-variant").value;
    }
    payload.sage = $("video-h3-sage").checked;
    if (payload.profile === "personalizado") {
      const encEl = $("video-h3-encoder");
      if (encEl) payload.encoder = encEl.value;
      const loraStrEl = $("video-h3-lora-strength");
      if (loraStrEl) payload.lora_strength = Number(loraStrEl.value);
      const denoiseEl = $("video-h3-denoise");
      if (denoiseEl) payload.denoise = Number(denoiseEl.value);
      const samplerEl = $("video-h3-sampler");
      if (samplerEl) payload.sampler_name = samplerEl.value;
      const schedEl = $("video-h3-scheduler");
      if (schedEl) payload.scheduler = schedEl.value;
      const tileEl = $("video-h3-tile-size");
      if (tileEl) payload.tile_size = Number(tileEl.value);
      const audioEl = $("video-h3-audio");
      if (audioEl) payload.include_audio = audioEl.checked;
    }
    const secondsEl = $("video-h3-seconds") || $("video-seconds");
    payload.seconds = Number(secondsEl ? secondsEl.value : 8);
    payload.width = size.width;
    payload.height = size.height;
  } catch (error) {
    setVideoStatus(error.message, true);
    return;
  }
  const btn = $("btn-video-generate");
  if (btn) btn.disabled = true;
  setVideoStatus("Encolando...");
  try {
    const data = await postJson("/api/video/generate", payload);
    reloadVideoViewerFirstPage().catch(() => {});
    await enqueueJobs(data.job_id, {
      statusFn: setVideoJobStatus,
      onDone: reloadVideoViewerFirstPage,
      progressFn: setVideoProgress,
      manageCancel: true,
      cancelButtonId: "btn-video-cancel",
    });
  } catch (error) {
    setVideoStatus(error.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = state.activeJobsCount > 0 ? `${t("queue_prefix")} (${state.activeJobsCount})` : t("generate");
    }
  }
}


function applyVideoEngine() {
  const isWan = $("video-engine") ? $("video-engine").value === "wan" : false;
  let mode = $("video-mode") ? $("video-mode").value : "i2v";
  const modeSelect = $("video-mode");
  if (modeSelect && isWan) {
    for (const value of ["ref2va", "v2v"]) {
      const opt = modeSelect.querySelector(`option[value="${value}"]`);
      if (opt) opt.hidden = true;
    }
    if (mode === "ref2va" || mode === "v2v") {
      modeSelect.value = "i2v";
      mode = "i2v";
    }
  }
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
  const h3Only = [
    "video-h3-prompt-actions",
    "video-h3-profile-field",
    "video-h3-size-field",
    "video-h3-res-badge-wrap",
    "video-h3-encoder-field",
    "video-h3-variant-field",
    "video-h3-encoder-warning",
    "video-h3-sage-field",
    "video-custom-settings-panel",
  ];
  for (const id of h3Only) {
    const el = $(id);
    if (el) el.style.display = isWan ? "none" : "";
  }
  const wanPreset = $("video-wan-preset-field");
  if (wanPreset) wanPreset.style.display = isWan ? "" : "none";

  if (mode === "ref2va" || mode === "v2v") {
    setSelectValue($("video-h3-profile"), "ref2va");
  } else if ($("video-h3-profile") && $("video-h3-profile").value === "ref2va") {
    setSelectValue($("video-h3-profile"), "estandar");
  }
  updateH3Variants();
  updateH3SecondsAvailability();
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
  window.addEventListener("waifu:queue-updated", () => {
    const btn = $("btn-video-generate");
    if (btn) {
      btn.textContent = state.activeJobsCount > 0 ? `${t("queue_prefix")} (${state.activeJobsCount})` : t("generate");
    }
  });
  on("video-engine", "change", applyVideoEngine);
  on("video-mode", "change", applyVideoEngine);
  on("video-v2v-input", "change", (event) => {
    const file = event.target.files && event.target.files[0];
    const wrap = $("video-v2v-preview-wrap");
    const preview = $("video-v2v-preview");
    if (v2vPreviewObjectUrl) {
      URL.revokeObjectURL(v2vPreviewObjectUrl);
      v2vPreviewObjectUrl = null;
    }
    if (file && preview && wrap) {
      v2vPreviewObjectUrl = URL.createObjectURL(file);
      preview.src = v2vPreviewObjectUrl;
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
  on("video-image", "change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file && state.localFilesOriginalPaths) {
      const originalPath = file.path || file.webkitRelativePath || file.name;
      state.localFilesOriginalPaths.set(file.name, originalPath);
    }
  });
  on("video-last-image", "change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file && state.localFilesOriginalPaths) {
      const originalPath = file.path || file.webkitRelativePath || file.name;
      state.localFilesOriginalPaths.set(file.name, originalPath);
    }
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
  videoReuseParams,
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
