// WaifuStudio — Pestaña de Galería Principal
// Qué hace: visualización de creaciones, filtros por modelo, búsqueda por tags y borrado.
// Qué no hace: no genera nuevos medios ni entrena modelos LoRA.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import { state, GALLERY_PAGE_SIZE } from "../state.js";
import {
  $,
  on,
  setStatus,
  setVideoStatus,
  formatGalleryDate,
  isVideoUrl,
  downloadUrlFor,
} from "../dom.js";
import { api, postJson } from "../api.js";
import { openLightbox } from "../components/lightbox.js";
import { switchTab } from "../main.js";
import {
  setUpscaleStatus,
  clearUpscaleSelection,
  applyUpscaleKind,
  loadUpscaleGallery,
  selectUpscaleSource,
} from "./upscaler.js";
import {
  setEditorStatus,
  setEditorEditSource,
  updateEditorMode,
  updateEditorControls,
} from "./editor.js";
import { attachReferenceFromUrl } from "../components/prompt_popover.js";
import { attachVideoFrameFromUrl, attachFileInputFromUrl } from "./video.js";
import { reuseGeneration } from "./image.js";

let galleryModalItem = null;

function galleryKindLabel(kind) {
  if (kind === "image") {
    return "Imagen";
  }
  if (kind === "video") {
    return "Vídeo";
  }
  return kind || "Sin tipo";
}

function galleryStatusLabel(status) {
  if (status === "queued") {
    return "en cola";
  }
  if (status === "running") {
    return "generando";
  }
  if (status === "error") {
    return "error";
  }
  if (status === "cancelled") {
    return "cancelado";
  }
  return status || "sin estado";
}

function galleryItemUrl(item) {
  const urls = (item && item.urls) || [];
  return urls.length ? urls[0] : null;
}

function galleryPromptPreview(prompt, max = 90) {
  const text = String(prompt || "").trim();
  return text.length > max ? `${text.slice(0, max)}…` : text;
}


function renderGalleryTab() {
  const grid = $("gallery-grid");
  const empty = $("gallery-empty");
  const gallery = state.galleryTab;
  grid.replaceChildren();
  grid.scrollTop = 0;
  if (!gallery.items.length) {
    empty.textContent =
      gallery.kind === "video"
        ? "Sin vídeos."
        : gallery.kind === "image"
        ? "Sin imágenes."
        : "Sin generaciones.";
    empty.classList.remove("hidden");
    grid.classList.add("hidden");
  } else {
    empty.classList.add("hidden");
    grid.classList.remove("hidden");
  }
  for (const item of gallery.items) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "gallery-card";
    const title = item.prompt ? `#${item.id} ${item.prompt}` : `Generación #${item.id}`;
    card.title = title;
    card.setAttribute("aria-label", title);
    const media = document.createElement("span");
    media.className = "gallery-card-media";
    const url = galleryItemUrl(item);
    if (url && isVideoUrl(url)) {
      const video = document.createElement("video");
      video.src = url;
      video.muted = true;
      video.preload = "metadata";
      video.playsInline = true;
      media.appendChild(video);
    } else if (url) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = item.prompt || `Generación #${item.id}`;
      img.loading = "lazy";
      media.appendChild(img);
    } else {
      const missing = document.createElement("span");
      missing.className = "thumb-missing";
      missing.textContent = item.status === "error" ? "Error" : "Sin resultado";
      media.appendChild(missing);
    }
    const badge = document.createElement("span");
    badge.className = "gallery-badge";
    badge.textContent = galleryKindLabel(item.kind);
    media.appendChild(badge);
    card.appendChild(media);
    const preview = galleryPromptPreview(item.prompt);
    if (preview) {
      const text = document.createElement("span");
      text.className = "gallery-card-prompt";
      text.textContent = preview;
      card.appendChild(text);
    }
    if (item.status !== "done") {
      const status = document.createElement("span");
      status.className = "gallery-card-status";
      if (item.status === "error" || item.status === "cancelled") {
        status.classList.add("error");
      }
      status.textContent = galleryStatusLabel(item.status);
      card.appendChild(status);
    }
    card.addEventListener("click", () => openGalleryModal(item));
    grid.appendChild(card);
  }
  $("gallery-info").textContent = `página ${gallery.page} de ${gallery.total}`;
  $("gallery-prev").disabled = gallery.page <= 1;
  $("gallery-next").disabled = gallery.page >= gallery.total;
}

async function loadGalleryTab(page = 1) {
  const gallery = state.galleryTab;
  const wanted = Math.max(1, Math.trunc(Number(page)) || 1);
  const offset = (wanted - 1) * GALLERY_PAGE_SIZE;
  const kind = gallery.kind ? `&kind=${encodeURIComponent(gallery.kind)}` : "";
  const qParam = gallery.q ? `&q=${encodeURIComponent(gallery.q)}` : "";
  const data = await api(
    `/api/gallery?limit=${GALLERY_PAGE_SIZE}&offset=${offset}${kind}${qParam}`
  );
  const items = data.items || [];
  const count = Number(data.count);
  const total = Number.isFinite(count) && count > 0 ? count : items.length;
  gallery.total = Math.max(1, Math.ceil(total / GALLERY_PAGE_SIZE));
  if (wanted > gallery.total && gallery.total > 0) {
    return await loadGalleryTab(gallery.total);
  }
  gallery.page = wanted;
  gallery.items = items;
  renderGalleryTab();
}

function openGalleryModal(item) {
  const modal = $("gallery-modal");
  const media = $("gallery-modal-media");
  if (!modal || !item) {
    return;
  }
  closeGalleryModal();
  galleryModalItem = item;
  const url = galleryItemUrl(item);
  if (url && isVideoUrl(url)) {
    const video = document.createElement("video");
    video.src = url;
    video.controls = true;
    video.autoplay = true;
    video.playsInline = true;
    media.appendChild(video);
  } else if (url) {
    const img = document.createElement("img");
    img.src = url;
    img.alt = item.prompt || `Generación #${item.id}`;
    media.appendChild(img);
  } else {
    const missing = document.createElement("p");
    missing.className = "empty";
    missing.textContent =
      item.status === "error" ? "Sin resultado (error)" : "Sin resultado";
    media.appendChild(missing);
  }
  $("gallery-modal-info").textContent = `#${item.id} · ${galleryKindLabel(
    item.kind
  )} · ${formatGalleryDate(item.created_at)}`;
  const prompt = $("gallery-modal-prompt");
  prompt.textContent = item.prompt || "Sin prompt.";
  prompt.classList.toggle("hidden", !item.prompt);
  $("btn-gallery-download").disabled = !downloadUrlFor(url);
  const isImage = item.kind === "image";
  const isVideo = item.kind === "video";
  const hasUrl = Boolean(url);
  $("btn-gallery-use-ref").disabled = !(isImage && hasUrl);
  $("btn-gallery-animate").disabled = !(isImage && hasUrl);
  $("btn-gallery-edit").disabled = !(isImage && hasUrl);
  $("btn-gallery-upscale").disabled = !((isImage || isVideo) && hasUrl);
  modal.classList.remove("hidden");
}

function closeGalleryModal() {
  const modal = $("gallery-modal");
  if (!modal) {
    return;
  }
  const media = $("gallery-modal-media");
  if (media) {
    for (const video of media.querySelectorAll("video")) {
      video.pause();
    }
    media.replaceChildren();
  }
  galleryModalItem = null;
  modal.classList.add("hidden");
}

async function deleteGalleryItem() {
  if (!galleryModalItem) return;
  const id = galleryModalItem.id;
  if (!confirm(`¿Eliminar la generación #${id} y sus archivos del disco?`)) return;
  try {
    await api(`/api/gallery/${id}`, { method: "DELETE" });
    closeGalleryModal();
    setStatus(`Generación #${id} eliminada.`);
    await loadGalleryTab(state.galleryTab.page);
  } catch (err) {
    setStatus(`Error al borrar: ${err.message}`, true);
  }
}

async function cleanFailedGenerations() {
  if (!confirm("¿Eliminar todas las generaciones fallidas de la base de datos?")) return;
  try {
    const res = await api("/api/gallery/clean_failed", { method: "POST" });
    setStatus(`Limpieza completada: ${res.cleaned} generaciones eliminadas.`);
    await loadGalleryTab(1);
  } catch (err) {
    setStatus(`Error en limpieza: ${err.message}`, true);
  }
}


async function openCustomTagsModal() {
  const modal = $("custom-tags-modal");
  if (!modal) return;
  $("custom-tags-status").textContent = "Cargando...";
  modal.classList.remove("hidden");
  await refreshCustomTagsList();
}

function closeCustomTagsModal() {
  const modal = $("custom-tags-modal");
  if (!modal) return;
  modal.classList.add("hidden");
}

async function refreshCustomTagsList() {
  const container = $("custom-tags-list");
  if (!container) return;
  try {
    const data = await api("/api/tags/custom");
    const tags = Array.isArray(data) ? data : (data.tags || []);
    container.replaceChildren();
    if (!tags.length) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "No hay tags personalizadas en data/registry/tags_danbooru.json.";
      container.appendChild(p);
    } else {
      for (const t of tags) {
        const item = document.createElement("div");
        item.className = "custom-tag-item";
        const info = document.createElement("div");
        info.className = "custom-tag-item-info";
        const nameSpan = document.createElement("strong");
        nameSpan.textContent = t.name;
        const catSpan = document.createElement("span");
        catSpan.className = "custom-tag-item-cat";
        catSpan.textContent = t.category || "general";
        const countSpan = document.createElement("span");
        countSpan.className = "custom-tag-item-count";
        countSpan.textContent = `(${t.count || 0} posts)`;
        info.appendChild(nameSpan);
        info.appendChild(catSpan);
        info.appendChild(countSpan);

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "custom-tag-item-del";
        delBtn.textContent = "Eliminar";
        delBtn.title = `Eliminar ${t.name}`;
        delBtn.addEventListener("click", async () => {
          if (!confirm(`¿Eliminar tag personalizada "${t.name}"?`)) return;
          try {
            await api(`/api/tags/custom/${encodeURIComponent(t.name)}`, { method: "DELETE" });
            $("custom-tags-status").textContent = `Tag "${t.name}" eliminada`;
            await refreshCustomTagsList();
          } catch (err) {
            $("custom-tags-status").textContent = `Error: ${err.message}`;
          }
        });

        item.appendChild(info);
        item.appendChild(delBtn);
        container.appendChild(item);
      }
    }
    $("custom-tags-status").textContent = `${tags.length} tags personalizadas`;
  } catch (err) {
    $("custom-tags-status").textContent = `Error: ${err.message}`;
  }
}

async function submitCustomTag(event) {
  event.preventDefault();
  const nameInput = $("custom-tag-name");
  const catInput = $("custom-tag-category");
  const countInput = $("custom-tag-count");
  const name = nameInput.value.trim();
  if (!name) return;
  const category = catInput.value;
  const count = parseInt(countInput.value, 10) || 100;
  try {
    await api("/api/tags/custom", {
      method: "POST",
      body: { name, category, count },
    });
    nameInput.value = "";
    $("custom-tags-status").textContent = `Tag "${name}" guardada`;
    await refreshCustomTagsList();
  } catch (err) {
    $("custom-tags-status").textContent = `Error: ${err.message}`;
  }
}

function downloadGalleryItem() {
  const downloadUrl = downloadUrlFor(galleryItemUrl(galleryModalItem));
  if (!downloadUrl) {
    return;
  }
  window.location.href = downloadUrl;
}

async function useGalleryItemAsReference(item) {
  closeGalleryModal();
  switchTab("image");
  await reuseGeneration(item);
  const name =
    ((item.outputs || [])[0]) || "galeria-" + item.id + ".png";
  await attachReferenceFromUrl(galleryItemUrl(item), name);
  setStatus(`#${item.id} cargada como referencia`);
}

async function animateGalleryItem(item) {
  closeGalleryModal();
  switchTab("video");
  const name =
    ((item.outputs || [])[0]) || "galeria-" + item.id + ".png";
  await attachFileInputFromUrl("video-image", galleryItemUrl(item), name);
  setVideoStatus(`#${item.id} como primer fotograma`);
}

async function editGalleryItemInEditor(item) {
  closeGalleryModal();
  switchTab("editor");
  $("editor-mode").value = "edit";
  await setEditorEditSource(galleryItemUrl(item), null);
  updateEditorMode({ sync: false });
  $("editor-prompt").focus();
}

async function upscaleGalleryItem(item) {
  closeGalleryModal();
  $("upscale-kind").value = item.kind === "video" ? "video" : "image";
  clearUpscaleSelection();
  switchTab("upscaler");
  applyUpscaleKind();
  await loadUpscaleGallery(1);
  if (!state.upscaleSources.some((entry) => entry.id === item.id)) {
    state.upscaleSources.push(item);
  }
  selectUpscaleSource(item.id);
  setUpscaleStatus(`#${item.id} seleccionada como origen`);
}


function initGalleryTab() {
  on("gallery-filter", "change", () => {
    state.galleryTab.kind = $("gallery-filter").value;
    loadGalleryTab(1).catch((error) => setStatus(error.message, true));
  });
  on("gallery-tag-search", "input", (e) => {
    state.galleryTab.q = e.target.value.trim();
    loadGalleryTab(1).catch((error) => setStatus(error.message, true));
  });
  on("btn-gallery-clean-failed", "click", () => {
    cleanFailedGenerations().catch((error) => setStatus(error.message, true));
  });
  on("btn-manage-custom-tags", "click", openCustomTagsModal);
  on("btn-custom-tags-close", "click", closeCustomTagsModal);
  on("custom-tags-form", "submit", submitCustomTag);
  on("custom-tags-modal", "click", (event) => {
    if (event.target === $("custom-tags-modal")) {
      closeCustomTagsModal();
    }
  });
  on("gallery-prev", "click", () => {
    loadGalleryTab(state.galleryTab.page - 1).catch((error) =>
      setStatus(error.message, true)
    );
  });
  on("gallery-next", "click", () => {
    loadGalleryTab(state.galleryTab.page + 1).catch((error) =>
      setStatus(error.message, true)
    );
  });
  on("btn-gallery-refresh", "click", () => {
    loadGalleryTab(state.galleryTab.page).catch((error) =>
      setStatus(error.message, true)
    );
  });
  on("btn-gallery-close", "click", closeGalleryModal);
  on("btn-gallery-delete", "click", deleteGalleryItem);
  on("btn-gallery-download", "click", downloadGalleryItem);
  on("btn-gallery-use-ref", "click", () => {
    if (!galleryModalItem) {
      return;
    }
    useGalleryItemAsReference(galleryModalItem).catch((error) =>
      setStatus(error.message, true)
    );
  });
  on("btn-gallery-animate", "click", () => {
    if (!galleryModalItem) {
      return;
    }
    animateGalleryItem(galleryModalItem).catch((error) =>
      setVideoStatus(error.message, true)
    );
  });
  on("btn-gallery-edit", "click", () => {
    if (!galleryModalItem) {
      return;
    }
    editGalleryItemInEditor(galleryModalItem).catch((error) =>
      setEditorStatus(error.message, true)
    );
  });
  on("btn-gallery-upscale", "click", () => {
    if (!galleryModalItem) {
      return;
    }
    upscaleGalleryItem(galleryModalItem).catch((error) =>
      setUpscaleStatus(error.message, true)
    );
  });
  on("gallery-modal", "click", (event) => {
    if (event.target === $("gallery-modal")) {
      closeGalleryModal();
    }
  });
  on("gallery-modal-media", "click", (event) => {
    const target = event.target;
    if (target && target.tagName === "IMG" && target.getAttribute("src")) {
      openLightbox(target.getAttribute("src"), target.alt || "Galería");
    }
  });
}

export {
  galleryKindLabel,
  galleryStatusLabel,
  galleryItemUrl,
  galleryPromptPreview,
  renderGalleryTab,
  loadGalleryTab,
  openGalleryModal,
  closeGalleryModal,
  deleteGalleryItem,
  cleanFailedGenerations,
  openCustomTagsModal,
  closeCustomTagsModal,
  refreshCustomTagsList,
  submitCustomTag,
  downloadGalleryItem,
  useGalleryItemAsReference,
  animateGalleryItem,
  editGalleryItemInEditor,
  upscaleGalleryItem,
  initGalleryTab,
};
