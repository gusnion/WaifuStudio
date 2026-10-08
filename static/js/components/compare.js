// WaifuStudio — Comparador Interactivo Antes/Después
// Qué hace: visor dividido con handle de arrastre, zoom 8x y pan para imagen y editor.
// Qué no hace: no inicia trabajos de generación ni gestiona peticiones de API.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/tabs/image_viewer.js.

import { state, COMPARE_MAX_SCALE, COMPARE_DRAG_CLICK_MS, COMPARE_DRAG_THRESHOLD } from "../state.js";
import { $, on, setEditorStatus } from "../dom.js";
import { selectedImageView, imageViewUrl, updateImagePreview } from "../tabs/image_viewer.js";
import { updateEditorPreview } from "../tabs/editor.js";

let imageCompareActive = false;
let imageCompareSlot1 = "";
let imageCompareSlot2 = "";
let imageCompareView = { scale: 1, x: 0, y: 0, ratio: 0.5 };
let imageComparePan = null;
let imageCompareHandleDrag = false;

let editorCompareActive = false;
let editorCompareSelecting = false;
let editorCompareSlot1 = "";
let editorCompareSlot2 = "";
let editorCompareView = { scale: 1, x: 0, y: 0, ratio: 0.5, beforeUrl: "", afterUrl: "" };
let editorComparePan = null;
let editorCompareHandleDrag = false;

const IMAGE_COMPARE_MAX_SCALE = 8;
const IMAGE_COMPARE_DRAG_THRESHOLD = 4;
const EDITOR_COMPARE_MAX_SCALE = 8;
const EDITOR_COMPARE_DRAG_THRESHOLD = 4;

function editorCurrentPreviewUrl() {
  return state.editorResultUrl || (state.editorRefs.length ? state.editorRefs[0].url : "") || ($("editor-preview-img") ? $("editor-preview-img").getAttribute("src") : "");
}

function editorCompareUrls() {
  return {
    before: editorCompareSlot1 || (state.editorRefs.length ? state.editorRefs[0].url : ""),
    after: editorCompareSlot2 || state.editorResultUrl || "",
  };
}

function applyImageCompare() {
  const stage = $("image-compare-stage");
  const compare = $("image-compare");
  if (!stage || !compare) {
    return;
  }
  stage.style.transform = `translate(${imageCompareView.x}px, ${imageCompareView.y}px) scale(${imageCompareView.scale})`;
  const after = $("image-compare-after");
  if (after) {
    after.style.clipPath = `inset(0 0 0 ${imageCompareView.ratio * 100}%)`;
  }
  compare.classList.toggle("zoomed", imageCompareView.scale > 1);
  const rect = stage.getBoundingClientRect();
  const wrap = compare.getBoundingClientRect();
  const handle = $("image-compare-handle");
  if (handle) {
    handle.style.left = `${rect.left - wrap.left + imageCompareView.ratio * rect.width}px`;
  }
  const percent = Math.round(imageCompareView.ratio * 100);
  if (handle) {
    handle.setAttribute("aria-valuenow", String(percent));
  }
  const label = $("image-compare-ratio");
  if (label) {
    label.textContent = `${percent}%`;
  }
}

function resetImageCompareView() {
  imageCompareView.scale = 1;
  imageCompareView.x = 0;
  imageCompareView.y = 0;
  imageCompareView.ratio = 0.5;
  imageComparePan = null;
  const compare = $("image-compare");
  if (compare) {
    compare.classList.remove("dragging");
  }
  applyImageCompare();
}

function setImageCompareEnabled(on) {
  const button = $("btn-image-compare");
  if (on) {
    const item = selectedImageView();
    const url = imageViewUrl(item);
    if (!url) return;
    imageCompareActive = true;
    imageCompareSlot1 = url;
    imageCompareSlot2 = "";
    if (button) {
      button.textContent = "Cerrar comparación";
      button.setAttribute("aria-pressed", "true");
      button.disabled = false;
    }
    const info = $("image-preview-info");
    if (info) {
      info.textContent = "Selecciona una imagen de la minigalería para comparar";
    }
  } else {
    imageCompareActive = false;
    imageCompareSlot1 = "";
    imageCompareSlot2 = "";
    imageCompareHandleDrag = false;
    imageComparePan = null;
    const compare = $("image-compare");
    if (compare) {
      compare.classList.add("hidden");
    }
    const img = $("image-preview-img");
    if (img) {
      img.classList.remove("hidden");
    }
    if (button) {
      button.textContent = "Comparar";
      button.setAttribute("aria-pressed", "false");
    }
    updateImagePreview();
  }
}

function setImageCompareSlot2(url) {
  if (!url || !imageCompareSlot1) return;
  imageCompareSlot2 = url;
  imageCompareActive = true;
  const before = $("image-compare-before");
  const after = $("image-compare-after");
  if (before) before.src = imageCompareSlot1;
  if (after) after.src = imageCompareSlot2;
  resetImageCompareView();
  const compare = $("image-compare");
  if (compare) compare.classList.remove("hidden");
  const img = $("image-preview-img");
  if (img) img.classList.add("hidden");
  const info = $("image-preview-info");
  if (info) {
    info.textContent = "Comparando: Slot 1 (fijo) vs Slot 2 (clic en otra miniatura para cambiar Slot 2)";
  }
  const button = $("btn-image-compare");
  if (button) {
    button.textContent = "Cerrar comparación";
    button.setAttribute("aria-pressed", "true");
    button.disabled = false;
  }
}

function initImageCompareInteractions() {
  const stage = $("image-compare-stage");
  const handle = $("image-compare-handle");
  if (!stage || !handle) return;

  stage.addEventListener("wheel", (event) => {
    if (!imageCompareActive || !imageCompareSlot2) return;
    event.preventDefault();
    const current = imageCompareView.scale;
    const factor = Math.exp(-event.deltaY * 0.0015);
    const next = Math.min(IMAGE_COMPARE_MAX_SCALE, Math.max(1, current * factor));
    if (next === current) return;
    const rect = stage.getBoundingClientRect();
    const pointX = (event.clientX - rect.left) / current;
    const pointY = (event.clientY - rect.top) / current;
    const layoutLeft = rect.left - imageCompareView.x;
    const layoutTop = rect.top - imageCompareView.y;
    if (next <= 1) {
      resetImageCompareView();
      return;
    }
    imageCompareView.scale = next;
    imageCompareView.x = event.clientX - pointX * next - layoutLeft;
    imageCompareView.y = event.clientY - pointY * next - layoutTop;
    applyImageCompare();
  }, { passive: false });

  stage.addEventListener("mousedown", (event) => {
    if (event.button !== 0 || imageCompareView.scale <= 1) return;
    event.preventDefault();
    imageComparePan = {
      startX: event.clientX,
      startY: event.clientY,
      x: imageCompareView.x,
      y: imageCompareView.y,
      moved: false,
    };
  });

  stage.addEventListener("dblclick", () => resetImageCompareView());

  document.addEventListener("mousemove", (event) => {
    if (!imageComparePan) return;
    const dx = event.clientX - imageComparePan.startX;
    const dy = event.clientY - imageComparePan.startY;
    if (!imageComparePan.moved) {
      if (Math.abs(dx) + Math.abs(dy) <= IMAGE_COMPARE_DRAG_THRESHOLD) return;
      imageComparePan.moved = true;
      const compare = $("image-compare");
      if (compare) compare.classList.add("dragging");
    }
    imageCompareView.x = imageComparePan.x + dx;
    imageCompareView.y = imageComparePan.y + dy;
    applyImageCompare();
  });

  document.addEventListener("mouseup", () => {
    imageComparePan = null;
    const compare = $("image-compare");
    if (compare) compare.classList.remove("dragging");
  });

  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    imageCompareHandleDrag = true;
    if (handle.setPointerCapture) handle.setPointerCapture(event.pointerId);
  });

  handle.addEventListener("pointermove", (event) => {
    if (!imageCompareHandleDrag) return;
    const stageEl = $("image-compare-stage");
    if (!stageEl) return;
    event.preventDefault();
    const rect = stageEl.getBoundingClientRect();
    if (!rect.width) return;
    const ratio = (event.clientX - rect.left) / rect.width;
    imageCompareView.ratio = Math.min(1, Math.max(0, ratio));
    applyImageCompare();
  });

  const endDrag = () => { imageCompareHandleDrag = false; };
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);

  handle.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const delta = event.key === "ArrowLeft" ? -0.02 : 0.02;
      imageCompareView.ratio = Math.min(1, Math.max(0, imageCompareView.ratio + delta));
      applyImageCompare();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      imageCompareView.ratio = event.key === "Home" ? 0 : 1;
      applyImageCompare();
    }
  });

  window.addEventListener("resize", () => {
    if (imageCompareActive && imageCompareSlot2) {
      applyImageCompare();
    }
  });
}


function resetEditorCompareView() {
  editorCompareView.scale = 1;
  editorCompareView.x = 0;
  editorCompareView.y = 0;
  editorCompareView.ratio = 0.5;
  endEditorComparePan();
  applyEditorCompare();
}

function applyEditorCompare() {
  const stage = $("editor-compare-stage");
  const compare = $("editor-compare");
  if (!stage || !compare) {
    return;
  }
  stage.style.transform = `translate(${editorCompareView.x}px, ${editorCompareView.y}px) scale(${editorCompareView.scale})`;
  const after = $("editor-compare-after");
  if (after) {
    after.style.clipPath = `inset(0 0 0 ${editorCompareView.ratio * 100}%)`;
  }
  compare.classList.toggle("zoomed", editorCompareView.scale > 1);
  const rect = stage.getBoundingClientRect();
  const wrap = compare.getBoundingClientRect();
  const handle = $("editor-compare-handle");
  if (handle) {
    handle.style.left = `${rect.left - wrap.left + editorCompareView.ratio * rect.width}px`;
  }
  const percent = Math.round(editorCompareView.ratio * 100);
  if (handle) {
    handle.setAttribute("aria-valuenow", String(percent));
  }
  const label = $("editor-compare-ratio");
  if (label) {
    label.textContent = `${percent}%`;
  }
}

function setEditorCompareEnabled(on) {
  const button = $("btn-editor-compare");
  if (on) {
    const current = editorCurrentPreviewUrl();
    if (!current) {
      return;
    }
    const { before, after } = editorCompareUrls();
    if (before && after) {
      editorCompareSlot1 = before;
      setEditorCompareSlot2(after);
      return;
    }
    editorCompareSlot1 = current;
    editorCompareSelecting = true;
    editorCompareActive = false;
    if (button) {
      button.disabled = false;
      button.textContent = "Cerrar comparación";
      button.setAttribute("aria-pressed", "true");
    }
    setEditorStatus("Selecciona una imagen de la minigalería para comparar");
  } else {
    editorCompareActive = false;
    editorCompareSelecting = false;
    editorCompareSlot1 = "";
    editorCompareSlot2 = "";
    editorCompareHandleDrag = false;
    $("editor-compare").classList.add("hidden");
    resetEditorCompareView();
    if (button) {
      button.textContent = "Comparar";
      button.setAttribute("aria-pressed", "false");
    }
  }
  updateEditorPreview();
}

function setEditorCompareSlot2(url) {
  if (!url || !editorCompareSlot1) return;
  editorCompareSlot2 = url;
  editorCompareActive = true;
  editorCompareSelecting = false;
  $("editor-compare-before").src = editorCompareSlot1;
  $("editor-compare-after").src = editorCompareSlot2;
  editorCompareView.beforeUrl = editorCompareSlot1;
  editorCompareView.afterUrl = editorCompareSlot2;
  resetEditorCompareView();
  $("editor-compare").classList.remove("hidden");
  const button = $("btn-editor-compare");
  if (button) {
    button.textContent = "Cerrar comparación";
    button.setAttribute("aria-pressed", "true");
    button.disabled = false;
  }
  setEditorStatus("Comparando: Slot 1 fijo vs Slot 2 (clic en otra miniatura para cambiar Slot 2)");
  updateEditorPreview();
}

function updateEditorCompare() {
  const button = $("btn-editor-compare");
  const hasImage = Boolean(editorCurrentPreviewUrl());
  if (button) {
    if (editorCompareActive || editorCompareSelecting) {
      button.disabled = false;
      button.textContent = "Cerrar comparación";
      button.setAttribute("aria-pressed", "true");
    } else {
      button.disabled = !hasImage;
      button.textContent = "Comparar";
      button.setAttribute("aria-pressed", "false");
    }
  }
  if (!editorCompareActive) {
    return;
  }
  const { before, after } = editorCompareUrls();
  if (!before || !after) {
    setEditorCompareEnabled(false);
    return;
  }
  if (
    editorCompareView.beforeUrl !== before ||
    editorCompareView.afterUrl !== after
  ) {
    editorCompareView.beforeUrl = before;
    editorCompareView.afterUrl = after;
    $("editor-compare-before").src = before;
    $("editor-compare-after").src = after;
    resetEditorCompareView();
  }
  applyEditorCompare();
  const image = $("editor-preview-img");
  const empty = $("editor-preview-empty");
  const box = $("editor-preview");
  if (image) {
    image.classList.add("hidden");
  }
  if (empty) {
    empty.classList.add("hidden");
  }
  if (box) {
    box.classList.add("has-image");
  }
}

function endEditorComparePan() {
  editorComparePan = null;
  const compare = $("editor-compare");
  if (compare) {
    compare.classList.remove("dragging");
  }
}

function startEditorComparePan(event) {
  if (event.button !== 0 || editorCompareView.scale <= 1) {
    return;
  }
  event.preventDefault();
  editorComparePan = {
    startX: event.clientX,
    startY: event.clientY,
    x: editorCompareView.x,
    y: editorCompareView.y,
    moved: false,
  };
}

function moveEditorComparePan(event) {
  if (!editorComparePan) {
    return;
  }
  const dx = event.clientX - editorComparePan.startX;
  const dy = event.clientY - editorComparePan.startY;
  if (!editorComparePan.moved) {
    if (Math.abs(dx) + Math.abs(dy) <= EDITOR_COMPARE_DRAG_THRESHOLD) {
      return;
    }
    editorComparePan.moved = true;
    $("editor-compare").classList.add("dragging");
  }
  editorCompareView.x = editorComparePan.x + dx;
  editorCompareView.y = editorComparePan.y + dy;
  applyEditorCompare();
}

function zoomEditorCompare(event) {
  if (!editorCompareActive) {
    return;
  }
  const stage = $("editor-compare-stage");
  if (!stage) {
    return;
  }
  event.preventDefault();
  const current = editorCompareView.scale;
  const factor = Math.exp(-event.deltaY * 0.0015);
  const next = Math.min(
    EDITOR_COMPARE_MAX_SCALE,
    Math.max(1, current * factor)
  );
  if (next === current) {
    return;
  }
  const rect = stage.getBoundingClientRect();
  const pointX = (event.clientX - rect.left) / current;
  const pointY = (event.clientY - rect.top) / current;
  const layoutLeft = rect.left - editorCompareView.x;
  const layoutTop = rect.top - editorCompareView.y;
  if (next <= 1) {
    resetEditorCompareView();
    return;
  }
  editorCompareView.scale = next;
  editorCompareView.x = event.clientX - pointX * next - layoutLeft;
  editorCompareView.y = event.clientY - pointY * next - layoutTop;
  applyEditorCompare();
}

function startEditorCompareHandleDrag(event) {
  if (event.button !== 0) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  editorCompareHandleDrag = true;
  const handle = $("editor-compare-handle");
  if (handle && handle.setPointerCapture) {
    handle.setPointerCapture(event.pointerId);
  }
}

function moveEditorCompareHandleDrag(event) {
  if (!editorCompareHandleDrag) {
    return;
  }
  const stage = $("editor-compare-stage");
  if (!stage) {
    return;
  }
  event.preventDefault();
  const rect = stage.getBoundingClientRect();
  if (!rect.width) {
    return;
  }
  const ratio = (event.clientX - rect.left) / rect.width;
  editorCompareView.ratio = Math.min(1, Math.max(0, ratio));
  applyEditorCompare();
}

function endEditorCompareHandleDrag() {
  editorCompareHandleDrag = false;
}

function onEditorCompareHandleKeydown(event) {
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -0.02 : 0.02;
    editorCompareView.ratio = Math.min(
      1,
      Math.max(0, editorCompareView.ratio + delta)
    );
    applyEditorCompare();
    return;
  }
  if (event.key === "Home" || event.key === "End") {
    event.preventDefault();
    editorCompareView.ratio = event.key === "Home" ? 0 : 1;
    applyEditorCompare();
  }
}

function initEditorCompareInteractions() {
  const stage = $("editor-compare-stage");
  const handle = $("editor-compare-handle");
  if (!stage || !handle) {
    return;
  }
  stage.addEventListener("wheel", zoomEditorCompare, { passive: false });
  stage.addEventListener("mousedown", startEditorComparePan);
  stage.addEventListener("dblclick", () => resetEditorCompareView());
  document.addEventListener("mousemove", moveEditorComparePan);
  document.addEventListener("mouseup", endEditorComparePan);
  handle.addEventListener("pointerdown", startEditorCompareHandleDrag);
  handle.addEventListener("pointermove", moveEditorCompareHandleDrag);
  handle.addEventListener("pointerup", endEditorCompareHandleDrag);
  handle.addEventListener("pointercancel", endEditorCompareHandleDrag);
  handle.addEventListener("keydown", onEditorCompareHandleKeydown);
  window.addEventListener("resize", () => {
    if (editorCompareActive) {
      applyEditorCompare();
    }
  });
}


function initCompare() {
  initImageCompareInteractions();
  initEditorCompareInteractions();
}

export {
  imageCompareActive,
  editorCompareActive,
  editorCompareSelecting,
  applyImageCompare,
  resetImageCompareView,
  setImageCompareEnabled,
  setImageCompareSlot2,
  initImageCompareInteractions,
  resetEditorCompareView,
  applyEditorCompare,
  setEditorCompareEnabled,
  setEditorCompareSlot2,
  updateEditorCompare,
  zoomEditorCompare,
  startEditorComparePan,
  moveEditorComparePan,
  endEditorComparePan,
  startEditorCompareHandleDrag,
  moveEditorCompareHandleDrag,
  endEditorCompareHandleDrag,
  onEditorCompareHandleKeydown,
  editorCurrentPreviewUrl,
  editorCompareUrls,
  initEditorCompareInteractions,
  initCompare,
};
