// WaifuStudio — Visor y Mini-Galería de Imagen
// Qué hace: visor principal de imágenes generadas, tira de miniaturas y paginación.
// Qué no hace: no gestiona la lógica de sampling ni realiza peticiones de generación.
// Dependencias: static/js/state.js y static/js/dom.js.

import { state, IMAGE_PAGE_SIZE } from "../state.js";
import { $, on, setStatus, formatGalleryDate, isVideoUrl, downloadUrlFor, toggleThumbs, getThumbsCapacity } from "../dom.js";
import { api } from "../api.js";
import { openLightbox } from "../components/lightbox.js";
import { setImageCompareSlot2, applyImageCompare, imageCompareActive, setImageCompareEnabled } from "../components/compare.js";
import { reuseGeneration } from "./image.js";

function selectedImageView() {
  return (
    state.imageViewer.items.find(
      (item) => item.id === state.imageViewer.selectedId
    ) || null
  );
}

function imageViewUrl(item) {
  const urls = (item && item.urls) || [];
  return urls.length && !isVideoUrl(urls[0]) ? urls[0] : null;
}


function updateImagePreview() {
  const item = selectedImageView();
  const url = imageViewUrl(item);
  const img = $("image-preview-img");
  const empty = $("image-preview-empty");
  if (url) {
    img.src = url;
    img.alt = item.prompt ? `#${item.id} ${item.prompt}` : `Generación #${item.id}`;
    img.classList.remove("hidden");
    empty.classList.add("hidden");
  } else {
    img.removeAttribute("src");
    img.alt = "";
    img.classList.add("hidden");
    empty.classList.remove("hidden");
    if (!item) {
      empty.textContent = "Sin generaciones";
    } else {
      empty.textContent = item.status === "error" ? "Sin resultado (error)" : "Sin resultado";
    }
  }
  $("image-preview").classList.toggle("has-image", Boolean(url));
  $("btn-save-to-oc").disabled = !item;
  const describeButton = $("btn-describe-image");
  if (describeButton) {
    describeButton.disabled = !(item && item.kind === "image" && url);
  }
  const downloadButton = $("btn-download-image");
  if (downloadButton) {
    downloadButton.disabled = !(item && item.kind === "image" && url);
  }
  const compareButton = $("btn-image-compare");
  if (compareButton) {
    if (imageCompareActive) {
      compareButton.disabled = false;
      compareButton.textContent = "Cerrar comparación";
      compareButton.setAttribute("aria-pressed", "true");
    } else {
      compareButton.disabled = !(item && item.kind === "image" && url);
      compareButton.textContent = "Comparar";
      compareButton.setAttribute("aria-pressed", "false");
    }
  }
  const info = $("image-preview-info");
  if (!imageCompareActive) {
    info.textContent = item
      ? `#${item.id} · ${item.model_id} · ${formatGalleryDate(item.created_at)}`
      : "Sin generaciones";
  }
}



function downloadSelectedImage() {
  const item = selectedImageView();
  const downloadUrl = downloadUrlFor(imageViewUrl(item));
  if (!downloadUrl) {
    setStatus("No hay imagen seleccionada para descargar", true);
    return;
  }
  window.location.href = downloadUrl;
}

function renderImageThumbs() {
  const container = $("image-thumbs");
  container.replaceChildren();
  const items = state.imageViewer.items;
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin generaciones.";
    container.appendChild(empty);
    return;
  }
  for (const item of items) {
    const selected = item.id === state.imageViewer.selectedId;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "image-thumb";
    button.classList.toggle("selected", selected);
    if (selected) {
      button.setAttribute("aria-current", "true");
    }
    button.title = `Reusar generación #${item.id}`;
    button.setAttribute("aria-label", `Reusar generación #${item.id}`);
    const url = imageViewUrl(item);
    if (url) {
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
    button.addEventListener("click", () => {
      if (imageCompareActive) {
        if (url) {
          setImageCompareSlot2(url);
        }
        return;
      }
      selectImageGeneration(item).catch((error) => setStatus(error.message, true));
    });
    container.appendChild(button);
  }
}

function renderImageViewer() {
  const viewer = state.imageViewer;
  updateImagePreview();
  renderImageThumbs();
  $("image-page-info").textContent = `página ${viewer.page} de ${viewer.total}`;
  $("image-prev-page").disabled = viewer.page <= 1;
  $("image-next-page").disabled = viewer.page >= viewer.total;
}

async function loadImageViewer({ selectNewest = false } = {}) {
  const viewer = state.imageViewer;
  const pageSize = getThumbsCapacity("image-thumbs");
  viewer.pageSize = pageSize;
  viewer.page = Math.max(1, viewer.page);
  const offset = (viewer.page - 1) * pageSize;
  try {
    const data = await api(
      `/api/gallery?kind=image&limit=${pageSize}&offset=${offset}`
    );
    const raw = data.items || [];
    const count = Number(data.count);
    const total = Number.isFinite(count) && count > 0 ? count : raw.length;
    viewer.total = Math.max(1, Math.ceil(total / pageSize));
    if (viewer.page > viewer.total) {
      viewer.page = viewer.total;
      return await loadImageViewer({ selectNewest });
    }
    viewer.items = raw;
    const onPage = viewer.items.some((item) => item.id === viewer.selectedId);
    if (selectNewest && viewer.items.length) {
      viewer.selectedId = viewer.items[0].id;
    } else if (!onPage) {
      viewer.selectedId = viewer.items.length ? viewer.items[0].id : null;
    }
    renderImageViewer();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function selectImageGeneration(item) {
  state.imageViewer.selectedId = item.id;
  renderImageViewer();
  await reuseGeneration(item);
}

async function reloadImageViewerFirstPage() {
  state.imageViewer.page = 1;
  await loadImageViewer({ selectNewest: true });
}


function initImageViewer() {
  on("image-preview", "click", () => {
    const item = selectedImageView();
    const url = imageViewUrl(item);
    if (url) {
      openLightbox(url, `Generación #${item.id}`);
    }
  });
  on("image-prev-page", "click", () => {
    state.imageViewer.page -= 1;
    loadImageViewer();
  });
  on("image-next-page", "click", () => {
    state.imageViewer.page += 1;
    loadImageViewer();
  });
  on("btn-reload", "click", () => {
    state.imageViewer.page = 1;
    loadImageViewer();
  });
  on("btn-download-image", "click", downloadSelectedImage);
  on("btn-image-compare", "click", () =>
    setImageCompareEnabled(!imageCompareActive)
  );
  on("btn-toggle-image-thumbs", "click", () =>
    toggleThumbs("image-thumbs", "btn-toggle-image-thumbs")
  );
}

export {
  selectedImageView,
  imageViewUrl,
  updateImagePreview,
  downloadSelectedImage,
  renderImageThumbs,
  renderImageViewer,
  loadImageViewer,
  selectImageGeneration,
  reloadImageViewerFirstPage,
  initImageViewer,
};
