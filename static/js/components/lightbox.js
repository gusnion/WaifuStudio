// WaifuStudio — Visor Lightbox Fullscreen con Zoom y Pan
// lightbox.js: visor modal con drag, wheel zoom hasta 8x y reset.

import { LIGHTBOX_MAX_SCALE, LIGHTBOX_DRAG_CLICK_MS, LIGHTBOX_DRAG_THRESHOLD } from "../state.js";
import { $, on } from "../dom.js";

let lightboxView = { scale: 1, x: 0, y: 0 };
let lightboxDrag = null;
let lightboxDragMoved = false;
let lightboxDragMovedAt = 0;

function applyLightboxTransform() {
  const image = $("lightbox-img");
  if (!image) {
    return;
  }
  image.style.transform = `translate(${lightboxView.x}px, ${lightboxView.y}px) scale(${lightboxView.scale})`;
  const lightbox = $("lightbox");
  if (lightbox) {
    lightbox.classList.toggle("zoomed", lightboxView.scale > 1);
  }
}

function endLightboxPan() {
  if (lightboxDrag && lightboxDragMoved) {
    lightboxDragMovedAt = Date.now();
  }
  lightboxDrag = null;
  lightboxDragMoved = false;
  const lightbox = $("lightbox");
  if (lightbox) {
    lightbox.classList.remove("dragging");
  }
}

function resetLightboxView() {
  lightboxView = { scale: 1, x: 0, y: 0 };
  lightboxDragMovedAt = 0;
  endLightboxPan();
  applyLightboxTransform();
}

function startLightboxPan(event) {
  if (event.button !== 0 || lightboxView.scale <= 1) {
    return;
  }
  event.preventDefault();
  lightboxDrag = {
    startX: event.clientX,
    startY: event.clientY,
    x: lightboxView.x,
    y: lightboxView.y,
  };
  lightboxDragMoved = false;
  $("lightbox").classList.add("dragging");
}

function moveLightboxPan(event) {
  if (!lightboxDrag) {
    return;
  }
  const dx = event.clientX - lightboxDrag.startX;
  const dy = event.clientY - lightboxDrag.startY;
  if (Math.abs(dx) + Math.abs(dy) > LIGHTBOX_DRAG_THRESHOLD) {
    lightboxDragMoved = true;
  }
  lightboxView.x = lightboxDrag.x + dx;
  lightboxView.y = lightboxDrag.y + dy;
  applyLightboxTransform();
}

function zoomLightbox(event) {
  const image = $("lightbox-img");
  if (!image || !image.getAttribute("src")) {
    return;
  }
  event.preventDefault();
  const current = lightboxView.scale;
  const factor = Math.exp(-event.deltaY * 0.0015);
  const next = Math.min(LIGHTBOX_MAX_SCALE, Math.max(1, current * factor));
  if (next === current) {
    return;
  }
  const rect = image.getBoundingClientRect();
  const pointX = (event.clientX - rect.left) / current;
  const pointY = (event.clientY - rect.top) / current;
  const layoutLeft = rect.left - lightboxView.x;
  const layoutTop = rect.top - lightboxView.y;
  if (next <= 1) {
    resetLightboxView();
    return;
  }
  lightboxView.scale = next;
  lightboxView.x = event.clientX - pointX * next - layoutLeft;
  lightboxView.y = event.clientY - pointY * next - layoutTop;
  applyLightboxTransform();
}

function initLightboxInteractions() {
  const image = $("lightbox-img");
  if (!image) {
    return;
  }
  image.addEventListener("wheel", zoomLightbox, { passive: false });
  image.addEventListener("mousedown", startLightboxPan);
  image.addEventListener("dblclick", () => resetLightboxView());
  document.addEventListener("mousemove", moveLightboxPan);
  document.addEventListener("mouseup", endLightboxPan);
}

function openLightbox(url, alt) {
  const image = $("lightbox-img");
  image.src = url;
  image.alt = alt || "";
  $("lightbox").classList.remove("hidden");
  resetLightboxView();
}

function closeLightbox() {
  $("lightbox").classList.add("hidden");
  $("lightbox-img").removeAttribute("src");
  resetLightboxView();
}


function initLightbox() {
  initLightboxInteractions();
  on("btn-lightbox-close", "click", closeLightbox);
  on("lightbox", "click", (event) => {
    if (
      event.target === $("lightbox") &&
      Date.now() - lightboxDragMovedAt > LIGHTBOX_DRAG_CLICK_MS
    ) {
      closeLightbox();
    }
  });
}

export {
  openLightbox,
  closeLightbox,
  zoomLightbox,
  resetLightboxView,
  startLightboxPan,
  moveLightboxPan,
  endLightboxPan,
  initLightboxInteractions,
  initLightbox,
};
