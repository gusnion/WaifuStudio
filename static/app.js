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
};

const state = {
  models: [],
  negative: "",
  videoNegative: "",
  busy: false,
};

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
  if (defaults.sampler_name) {
    $("sampler").value = defaults.sampler_name;
  }
  if (defaults.scheduler) {
    $("scheduler").value = defaults.scheduler;
  }
  if (defaults.width != null) {
    $("width").value = defaults.width;
  }
  if (defaults.height != null) {
    $("height").value = defaults.height;
  }
}

function readParams() {
  const toNumber = (id, fallback) => {
    const value = Number($(id).value);
    return Number.isFinite(value) ? value : fallback;
  };
  return {
    seed: Math.trunc(toNumber("seed", 42)),
    steps: Math.trunc(toNumber("steps", 20)),
    cfg: toNumber("cfg", 4),
    sampler_name: $("sampler").value.trim() || "euler",
    scheduler: $("scheduler").value.trim() || "sgm_uniform",
    width: Math.trunc(toNumber("width", 320)),
    height: Math.trunc(toNumber("height", 576)),
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

async function enhancePrompt() {
  const text = $("prompt").value.trim();
  if (!text) {
    setStatus("Escribe un prompt para mejorarlo", true);
    return;
  }
  setStatus("Mejorando prompt...");
  try {
    const data = await postJson("/api/enhance", {
      text,
      preprompt: $("preprompt").value,
    });
    $("prompt").value = data.positive;
    state.negative = data.negative || "";
    setStatus("Prompt mejorado");
  } catch (error) {
    setStatus(error.message, true);
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
  const payload = {
    model_id: $("model").value,
    prompt,
    negative: state.negative,
    preprompt: $("preprompt").value,
    params: readParams(),
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

async function pollJob(jobId, statusFn = setStatus, onDone = loadGallery) {
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (job.status === "queued" || job.status === "running") {
      statusFn(job.status === "running" ? "Generando..." : "En cola...");
      continue;
    }
    if (job.status === "error") {
      statusFn(`Error: ${job.error || "desconocido"}`, true);
      return;
    }
    statusFn("Listo");
    await onDone();
    return;
  }
}

function isVideoUrl(url) {
  return /\.(mp4|webm)$/i.test(String(url || ""));
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
  card.appendChild(caption);
  return card;
}

function renderGallery(container, items, emptyText) {
  container.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }
  for (const item of items) {
    container.appendChild(galleryCard(item));
  }
}

async function loadGallery() {
  try {
    const data = await api("/api/gallery?limit=50");
    const items = data.items.slice().reverse();
    renderGallery(
      $("gallery"),
      items.filter((item) => item.kind !== "video"),
      "Sin generaciones todavía."
    );
    renderGallery(
      $("video-gallery"),
      items.filter((item) => item.kind === "video"),
      "Sin videos todavía."
    );
  } catch (error) {
    setStatus(error.message, true);
  }
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
    await pollJob(data.job_id, setVideoStatus, loadGallery);
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

async function loadTraits() {
  const groups = await api("/api/traits");
  const container = $("oc-groups");
  container.replaceChildren();
  for (const [group, traits] of Object.entries(groups)) {
    const fieldset = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = GROUP_LABELS[group] || group;
    fieldset.appendChild(legend);
    const list = document.createElement("div");
    list.className = "trait-list";
    for (const trait of traits) {
      const label = document.createElement("label");
      label.className = "trait";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = trait.id;
      const text = document.createElement("span");
      text.textContent = trait.label;
      label.append(checkbox, text);
      list.appendChild(label);
    }
    fieldset.appendChild(list);
    container.appendChild(fieldset);
  }
}

async function addTraitsToPrompt() {
  const ids = Array.from($("oc-groups").querySelectorAll("input:checked")).map(
    (el) => el.value
  );
  if (!ids.length) {
    setStatus("Selecciona al menos un trait", true);
    return;
  }
  try {
    const data = await postJson("/api/prompt/build", { trait_ids: ids });
    const current = $("prompt").value.trim();
    $("prompt").value = current ? `${current}, ${data.prompt}` : data.prompt;
    closeOcModal();
    setStatus("Traits añadidos al prompt");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function openOcModal() {
  $("oc-modal").classList.remove("hidden");
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
  $("tab-image").addEventListener("click", () => switchTab("image"));
  $("tab-video").addEventListener("click", () => switchTab("video"));
  $("btn-enhance").addEventListener("click", enhancePrompt);
  $("btn-generate").addEventListener("click", generate);
  $("btn-reload").addEventListener("click", loadGallery);
  $("btn-motion").addEventListener("click", generateMotion);
  $("btn-video-generate").addEventListener("click", generateVideo);
  $("btn-video-reload").addEventListener("click", loadGallery);
  $("video-engine").addEventListener("change", applyVideoEngine);
  $("model").addEventListener("change", (event) => {
    applyModel(event.target.value).catch((error) => setStatus(error.message, true));
  });
  $("strength").addEventListener("input", (event) => {
    $("strength-value").textContent = Number(event.target.value).toFixed(2);
  });
  $("btn-oc").addEventListener("click", openOcModal);
  $("btn-oc-close").addEventListener("click", closeOcModal);
  $("btn-oc-add").addEventListener("click", addTraitsToPrompt);
  $("oc-modal").addEventListener("click", (event) => {
    if (event.target === $("oc-modal")) {
      closeOcModal();
    }
  });
}

async function init() {
  bind();
  applyVideoEngine();
  try {
    await loadModels();
    await loadTraits();
    await loadGallery();
    setStatus("Listo");
  } catch (error) {
    setStatus(error.message, true);
  }
}

document.addEventListener("DOMContentLoaded", init);
