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

let visionRequestSeq = 0;
let visionInsertTimer = null;
let visionResult = { tags: [], caption: "" };
let visionLastPayload = null;

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

function renderVisionResult(data, elapsedMs) {
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

async function openVisionModal(source, mode = "unified") {
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
  visionLastPayload = payload;
  resetVisionModal();
  modal.classList.remove("hidden");
  setVisionStatus("Analizando…");
  const seq = ++visionRequestSeq;
  const startedAt = performance.now();
  try {
    const data = await postJson("/api/vision/image_to_prompt", {
      ...payload,
      mode,
    });
    const elapsedMs = performance.now() - startedAt;
    if (seq !== visionRequestSeq) {
      return;
    }
    renderVisionResult(data, elapsedMs);
  } catch (error) {
    if (seq !== visionRequestSeq) {
      return;
    }
    showVisionError(error.message);
  } finally {
    refreshLlmStatus();
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
  on("btn-describe-ref", "click", describeRefFromDisk);
  on("describe-file", "change", () => {
    describeSelectedRefFile().catch((error) => setStatus(error.message, true));
  });
  on("btn-describe-image", "click", () => {
    openVisionModal().catch((error) => setStatus(error.message, true));
  });
}

export {
  visionGenId,
  setVisionStatus,
  resetVisionModal,
  showVisionError,
  renderVisionResult,
  openVisionModal,
  describeRefFromDisk,
  describeSelectedRefFile,
  closeVisionModal,
  visionGeneralTarget,
  insertVisionIntoPrompt,
  insertVisionFromModal,
  copyVisionText,
  initVision,
};
