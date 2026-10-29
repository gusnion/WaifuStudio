// WaifuStudio — Modal y Asistente de Visión (Qwen2.5-VL / WD14)
// Qué hace: descripción de imágenes de referencia, extracción de tags y análisis visual.
// Qué no hace: no arranca el servidor LLM ni genera imágenes en ComfyUI.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import { state } from "../state.js";
import { $, on, setStatus, readFileBase64, writeClipboard } from "../dom.js";
import { api, postJson } from "../api.js";
import { addTagsToZone, renderZoneEditor } from "./prompt_zones.js";
import { selectedImageView } from "../tabs/image_viewer.js";
import { refreshLlmStatus } from "../tabs/image.js";

const VISION_TIMEOUT_TAGS_MS = 30000;
const VISION_TIMEOUT_UNIFIED_MS = 180000;

let visionRequestSeq = 0;
let visionInsertTimer = null;
let visionAbortController = null;
let visionTimeoutTimer = null;
let visionResult = { tags: [], caption: "" };
let visionLastPayload = null;

function abortVisionRequest() {
  if (visionTimeoutTimer) {
    clearTimeout(visionTimeoutTimer);
    visionTimeoutTimer = null;
  }
  if (visionAbortController) {
    visionAbortController.abort();
    visionAbortController = null;
  }
}

// Badge #vision-mode: WD14 rapido ("WD14 rápido") o "LLM caption+tags"
function setVisionMode(mode = "tags") {
  const el = $("vision-mode");
  if (!el) {
    return;
  }
  const isUnified = mode === "unified";
  el.textContent = isUnified ? "LLM caption+tags" : "WD14 rápido";
  el.dataset.mode = isUnified ? "unified" : "tags";
  el.classList.toggle("is-llm", isUnified);
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
  setVisionMode("tags");
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

function renderVisionResult(data, elapsedMs) {
  const raw = data && typeof data === "object" ? data : {};
  const tags = Array.isArray(raw.tags)
    ? raw.tags.map((tag) => String(tag == null ? "" : tag).trim()).filter(Boolean)
    : [];
  const caption = typeof raw.caption === "string" ? raw.caption.trim() : "";
  visionResult = { tags, caption };
  if (raw.mode === "unified" || raw.mode === "tags") {
    setVisionMode(raw.mode);
  }
  const model = raw.model && typeof raw.model === "object" ? raw.model : {};
  const names = [model.wd14, model.vl].filter(
    (name) => typeof name === "string" && name
  );
  const modelNote = names.length ? ` · ${names.join(" + ")}` : "";
  const dropped = Array.isArray(raw.dropped) ? raw.dropped.filter(Boolean) : [];
  const droppedNote = dropped.length
    ? ` · ${dropped.length} tag(s) fuera del catálogo`
    : "";
  const modeNote = raw.mode === "tags" ? " · WD14 (rápido)" : "";
  const timeNote = Number.isFinite(elapsedMs)
    ? ` · ${(elapsedMs / 1000).toFixed(1)} s`
    : "";
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
    setVisionStatus(`Sin resultados${modelNote}${modeNote}${droppedNote}${timeNote}`);
    return;
  }
  if (empty) {
    empty.classList.add("hidden");
  }
  setVisionStatus(`Listo${modelNote}${modeNote}${droppedNote}${timeNote}`);
}

async function openVisionModal(source, mode = "tags") {
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
  const effectiveMode = mode === "unified" ? "unified" : "tags";
  const previousResult =
    effectiveMode === "unified" &&
    (visionResult.tags.length > 0 || Boolean(visionResult.caption))
      ? { tags: [...visionResult.tags], caption: visionResult.caption }
      : null;

  abortVisionRequest();
  visionLastPayload = payload;
  if (!previousResult) {
    resetVisionModal();
  } else {
    const empty = $("vision-empty");
    if (empty) {
      empty.textContent = "Analizando…";
      empty.classList.remove("hidden", "error");
    }
  }
  setVisionMode(effectiveMode);
  modal.classList.remove("hidden");
  setVisionStatus("Analizando…");

  const seq = ++visionRequestSeq;
  const timeoutMs =
    effectiveMode === "unified" ? VISION_TIMEOUT_UNIFIED_MS : VISION_TIMEOUT_TAGS_MS;
  const controller = new AbortController();
  visionAbortController = controller;
  visionTimeoutTimer = setTimeout(() => {
    controller.abort();
  }, timeoutMs);
  const startedAt = performance.now();

  try {
    const data = await api("/api/vision/image_to_prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...payload,
        mode: effectiveMode,
      }),
      signal: controller.signal,
      timeoutMs,
    });
    const elapsedMs = performance.now() - startedAt;
    if (seq !== visionRequestSeq) {
      return;
    }
    setVisionMode(effectiveMode);
    renderVisionResult(data, elapsedMs);
  } catch (error) {
    if (seq !== visionRequestSeq) {
      return;
    }
    if (previousResult) {
      renderVisionResult({
        tags: previousResult.tags,
        caption: previousResult.caption,
        mode: "tags",
      });
      setVisionMode("tags");
    }
    showVisionError(error.message);
  } finally {
    if (visionTimeoutTimer) {
      clearTimeout(visionTimeoutTimer);
      visionTimeoutTimer = null;
    }
    if (visionAbortController === controller) {
      visionAbortController = null;
    }
    refreshLlmStatus();
  }
}

async function runVisionLlm() {
  const mode = "unified";
  return openVisionModal(visionLastPayload, mode);
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
    await openVisionModal({ image_b64: b64 }, "tags");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function closeVisionModal() {
  visionRequestSeq += 1;
  abortVisionRequest();
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

function initVision() {
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
  on("btn-vision-tags-only", "click", () => {
    if (!visionLastPayload) {
      return;
    }
    openVisionModal(visionLastPayload, "tags").catch((error) =>
      setVisionStatus(error.message, true)
    );
  });
  on("btn-vision-llm", "click", () => {
    runVisionLlm().catch((error) => setVisionStatus(error.message, true));
  });
  on("btn-describe-ref", "click", describeRefFromDisk);
  on("describe-file", "change", () => {
    describeSelectedRefFile().catch((error) => setStatus(error.message, true));
  });
  on("btn-describe-image", "click", () => {
    openVisionModal(null, "tags").catch((error) => setStatus(error.message, true));
  });
}

export {
  visionGenId,
  setVisionStatus,
  setVisionMode,
  resetVisionModal,
  showVisionError,
  renderVisionResult,
  openVisionModal,
  runVisionLlm,
  describeRefFromDisk,
  describeSelectedRefFile,
  closeVisionModal,
  visionGeneralTarget,
  insertVisionIntoPrompt,
  insertVisionFromModal,
  copyVisionText,
  initVision,
};
