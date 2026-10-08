// WaifuStudio — Modal de Entrenamiento LoRA para OCs
// Qué hace: selección de imágenes de entrenamiento, parámetros y llamada a /train.
// Qué no hace: no almacena personajes ni genera prompts de inferencia.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import { state, TRAIN_PAGE, TRAIN_MIN, TRAIN_MAX, TRAIN_TRIGGER_RE } from "../state.js";
import { $, on } from "../dom.js";
import { api, postJson, pollJob } from "../api.js";
import { characterById } from "./oc_picker.js";
import { loadLoras } from "./loras.js";

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
  refreshTrainVisionState();
  setTrainStatus("Cargando galería...");
  loadTrainGalleryPage()
    .then(() => setTrainStatus(`Elige entre ${TRAIN_MIN} y ${TRAIN_MAX} imágenes`))
    .catch((error) => setTrainStatus(error.message, true));
}

function closeTrainModal() {
  $("oc-train-modal").classList.add("hidden");
}

function refreshTrainVisionState() {
  const check = $("train-auto-tags");
  const threshold = $("train-tag-threshold");
  const note = $("train-wd14-note");
  api("/api/vision/status")
    .then((data) => {
      const missing = Boolean(data && data.wd14 && data.wd14.installed === false);
      check.disabled = missing;
      threshold.disabled = missing;
      note.classList.toggle("hidden", !missing);
      if (missing) {
        check.checked = false;
      }
    })
    .catch((error) => {
      console.error("No se pudo consultar el estado de WD14", error);
    });
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
  const label = progress.node === "tags" ? "etiquetando" : "paso";
  text.textContent = `${label} ${step}/${total}`;
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
  const autoTags = $("train-auto-tags").checked && !$("train-auto-tags").disabled;
  const tagThreshold = Number($("train-tag-threshold").value);
  if (!(tagThreshold >= 0.05 && tagThreshold <= 0.95)) {
    setTrainStatus("Umbral WD14 fuera de [0.05, 0.95]", true);
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
        auto_tags: autoTags,
        tag_threshold: tagThreshold,
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


function initOcTrain() {
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
}

export {
  setTrainStatus,
  validTrainTrigger,
  readTrainEpochs,
  updateTrainControls,
  trainGalleryItem,
  renderTrainGallery,
  loadTrainGalleryPage,
  openTrainModal,
  closeTrainModal,
  refreshTrainVisionState,
  setTrainProgress,
  trainJobStatus,
  startTrain,
  initOcTrain,
};
