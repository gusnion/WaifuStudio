// WaifuStudio — Punto de Entrada y Orquestación Principal
// Qué hace: arranque initApp, atajos globales, REQUIRED_IDS y registro de pestañas.
// Qué no hace: no implementa lógica de generación ni manejo interno de pestañas.
// Dependencias: static/js/state.js, static/js/dom.js, tabs/* y components/*.

import { state, PANEL_SECTIONS } from "./state.js";
import { $, on, setStatus, setVideoStatus, setEditorStatus, setUpscaleStatus, showUiBanner, initSeedRandom, toggleSeedRandom, panelSectionKey, readStoredSection, storeSection, initPanelSections } from "./dom.js";
import { initCompare, setImageCompareEnabled, setEditorCompareEnabled, imageCompareActive, editorCompareActive, editorCompareSelecting } from "./components/compare.js";
import { initLightbox, closeLightbox } from "./components/lightbox.js";
import { initPromptZones, renderZoneEditor } from "./components/prompt_zones.js";
import { initPromptPopover, closeZoneInsert } from "./components/prompt_popover.js";
import { initOcPicker, openOcModal, closeOcModal, loadCharacters, loadOcCatalog, loadOcPreprompts } from "./components/oc_picker.js";
import { initOcTrain, closeTrainModal } from "./components/oc_train.js";
import { initLoras, closeLoraLibrary, closeLoraModal } from "./components/loras.js";
import { initVision, closeVisionModal } from "./components/vision.js";
import { initPreprompts, closePrepromptModal } from "./components/preprompts.js";
import { initImageTab, loadParams, loadFormats, loadModels, refreshNegative, applyStartupDefaults, refreshLlmStatus } from "./tabs/image.js";
import { initImageViewer, loadImageViewer } from "./tabs/image_viewer.js";
import { initVideoTab, applyVideoEngine, loadVideoViewer } from "./tabs/video.js";
import { initVideoH3, loadH3Profiles } from "./tabs/video_h3.js";
import { initEditorTab, updateEditorControls, updateEditorMode, loadEditorStatus, loadEditorGallery } from "./tabs/editor.js";
import { initUpscalerTab, applyUpscaleKind, loadUpscaleGallery, loadUpscaleModels } from "./tabs/upscaler.js";
import { initGalleryTab, loadGalleryTab, closeGalleryModal, closeCustomTagsModal } from "./tabs/gallery.js";

function switchTab(tab) {
  const image = tab === "image";
  const video = tab === "video";
  const editor = tab === "editor";
  const upscaler = tab === "upscaler";
  const gallery = tab === "gallery";
  $("tab-image").classList.toggle("active", image);
  $("tab-video").classList.toggle("active", video);
  $("tab-editor").classList.toggle("active", editor);
  $("tab-upscaler").classList.toggle("active", upscaler);
  $("tab-gallery").classList.toggle("active", gallery);
  $("panel-image").classList.toggle("active", image);
  $("panel-video").classList.toggle("active", video);
  $("panel-editor").classList.toggle("active", editor);
  $("panel-upscaler").classList.toggle("active", upscaler);
  $("panel-gallery").classList.toggle("active", gallery);
  if (upscaler) {
    applyUpscaleKind();
    loadUpscaleGallery(1).catch((error) => setUpscaleStatus(error.message, true));
  }
  if (gallery && !state.galleryTab.items.length) {
    loadGalleryTab(1).catch((error) => setStatus(error.message, true));
  }
}

const REQUIRED_IDS = [
  "job-status", "video-status", "tab-image", "tab-video", "tab-editor", "tab-upscaler",
  "btn-enhance", "llm-status", "prompt-general", "btn-generate", "btn-cancel", "btn-seed-random",
  "btn-negative-restore", "btn-ref-clear", "btn-lightbox-close", "lightbox", "btn-new-generation", "btn-describe-image",
  "btn-describe-ref", "describe-file", "btn-download-image", "btn-save-to-oc", "image-preview", "image-preview-img",
  "image-preview-empty", "image-preview-info", "btn-image-compare", "image-compare", "image-compare-stage", "image-compare-before",
  "image-compare-after", "image-compare-handle", "image-compare-ratio", "btn-toggle-image-thumbs", "image-prev-page", "image-next-page",
  "image-page-info", "image-thumbs", "video-gallery-prev", "video-gallery-next", "btn-reload", "btn-video-reload",
  "btn-video-generate", "btn-video-cancel", "video-engine", "video-mode", "video-h3-profile", "video-h3-profile-note",
  "video-h3-seconds", "video-h3-seconds-info", "video-h3-aspect", "video-h3-size", "video-h3-size-info", "video-h3-variant",
  "video-h3-sage", "video-h3-guide", "btn-h3-insert-template", "btn-h3-copy-guide", "h3-guide-status", "video-input-hint",
  "video-h3-prompt-actions", "btn-h3-prompt", "video-h3-prompt-strength", "h3-prompt-status", "video-v2v-input", "enhance-hint",
  "video-preview", "video-preview-empty", "video-preview-info", "video-prev-page", "video-next-page", "video-page-info",
  "video-thumbs", "btn-toggle-video-thumbs", "btn-new-video", "editor-prompt", "editor-refs", "editor-refs-field",
  "editor-refs-hint", "editor-size", "editor-manual-size", "editor-negative", "editor-steps", "editor-cfg",
  "editor-cfg-note", "editor-result", "editor-preview", "editor-preview-img", "editor-preview-empty", "btn-editor-compare",
  "btn-toggle-editor-thumbs", "editor-compare", "editor-compare-stage", "editor-compare-before", "editor-compare-after", "editor-compare-handle",
  "editor-compare-ratio", "btn-editor-generate", "btn-editor-open-gallery", "btn-editor-edit-result", "btn-editor-download", "editor-gallery-thumbs",
  "editor-gallery-prev", "editor-gallery-next", "editor-gallery-info", "panel-upscaler", "upscale-kind", "upscale-source-field",
  "upscale-source-label", "upscale-source-info", "upscale-file-field", "upscale-file", "upscale-passes-field", "upscale-passes",
  "upscale-sharpen-field", "upscale-sharpen", "upscale-gallery-thumbs", "upscale-gallery-prev", "upscale-gallery-next", "upscale-gallery-info",
  "upscale-model-field", "upscale-model", "upscale-model-note", "upscale-ckpt-field", "upscale-ckpt", "upscale-ckpt-note",
  "upscale-multiplier-field", "upscale-multiplier", "btn-upscale", "btn-upscale-cancel", "upscale-status", "upscale-progress",
  "upscale-progress-fill", "upscale-progress-text", "upscale-preview", "upscale-preview-img", "upscale-preview-video", "upscale-preview-empty",
  "btn-toggle-upscale-thumbs", "tab-gallery", "panel-gallery", "gallery-filter", "gallery-tag-search", "btn-gallery-clean-failed",
  "btn-manage-custom-tags", "btn-gallery-refresh", "gallery-grid", "gallery-empty", "gallery-prev", "gallery-info",
  "gallery-next", "gallery-modal", "gallery-modal-media", "gallery-modal-info", "gallery-modal-prompt", "btn-gallery-use-ref",
  "btn-gallery-animate", "btn-gallery-edit", "btn-gallery-upscale", "btn-gallery-delete", "btn-gallery-download", "btn-gallery-close",
  "size", "preprompt", "btn-preprompt-manage", "btn-preprompt-close", "preprompt-form", "preprompt-modal",
  "negative", "zone-editor", "prompt-final", "btn-copy-prompt", "zone-insert-form", "zone-insert-cancel",
  "zone-popover-close", "zone-popover-search", "zone-popover-insert", "zone-popover-clear", "zone-ocs-extras", "zone-ocs-traits",
  "ref-image", "model", "strength", "strength-value", "btn-oc", "btn-oc-close",
  "btn-oc-add", "oc-modal", "oc-catalog-group", "oc-catalog-search", "oc-form", "btn-oc-new",
  "btn-oc-cancel-edit", "btn-oc-sheet", "btn-oc-extras-move", "btn-oc-save-close", "btn-oc-save-confirm", "oc-save-modal",
  "btn-oc-train-close", "oc-train-modal", "btn-train-more", "btn-train-start", "train-rank", "train-epochs",
  "train-trigger", "train-auto-tags", "train-tag-threshold", "btn-lora-modal", "lora-modal", "btn-lora-close",
  "btn-lora-done", "btn-lora-clear", "lora-search", "btn-lora-manage", "btn-lora-manage-modal", "lora-library-modal",
  "btn-lora-library-close", "lora-library-status", "lora-library-list", "lora-library-form", "lora-library-form-title", "lora-form-id",
  "lora-form-family", "lora-form-file", "lora-form-display", "lora-form-trigger", "lora-form-weight", "lora-form-source",
  "lora-form-license", "lora-form-notes", "btn-lora-form-cancel", "btn-lora-upload", "lora-upload", "vision-modal",
  "btn-vision-close", "vision-status", "vision-empty", "vision-caption-block", "vision-caption", "btn-vision-copy-caption",
  "vision-tags-block", "vision-tags", "btn-vision-copy-tags", "btn-vision-insert-caption", "btn-vision-insert-tags", "vision-advanced",
  "btn-vision-tags-only", "custom-tags-modal", "custom-tags-status", "btn-custom-tags-close", "custom-tags-form", "custom-tag-name",
  "custom-tag-category", "custom-tag-count", "btn-custom-tag-add", "custom-tags-list",
];

function bind() {
  const missing = REQUIRED_IDS.filter((id) => !$(id));
  if (missing.length) {
    showUiBanner("UI desactualizada: recarga con Ctrl+F5");
    setStatus("UI desactualizada: recarga con Ctrl+F5", true);
    console.error("bind: faltan elementos de la UI", missing);
  }
  on("tab-image", "click", () => switchTab("image"));
  on("tab-video", "click", () => switchTab("video"));
  on("tab-editor", "click", () => { switchTab("editor"); updateEditorMode(); });
  on("tab-upscaler", "click", () => switchTab("upscaler"));
  on("tab-gallery", "click", () => switchTab("gallery"));
  on("btn-seed-random", "click", () => toggleSeedRandom());
  on("btn-video-seed-random", "click", () => toggleSeedRandom(setVideoStatus));
  on("btn-editor-seed-random", "click", () => toggleSeedRandom(setEditorStatus));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeLightbox(); closeGalleryModal(); closeCustomTagsModal();
      if (imageCompareActive) setImageCompareEnabled(false);
      if (editorCompareActive || editorCompareSelecting) setEditorCompareEnabled(false);
      closeVisionModal(); closePrepromptModal(); closeLoraLibrary(); closeLoraModal();
      const trainModal = $("oc-train-modal");
      if (trainModal && !trainModal.classList.contains("hidden")) { closeTrainModal(); return; }
      closeOcModal();
    }
  });
  initCompare(); initLightbox(); initPromptZones(); initPromptPopover();
  initOcPicker(); initOcTrain(); initLoras(); initVision(); initPreprompts();
  initImageViewer(); initImageTab(); initVideoTab(); initVideoH3();
  initEditorTab(); initUpscalerTab(); initGalleryTab();
  return missing.length === 0;
}

async function init() {
  const failures = [];
  const settle = async (label, fn) => {
    try {
      return await fn();
    } catch (error) {
      failures.push(label);
      console.error(`init: fallo en ${label}`, error);
      return undefined;
    }
  };
  try {
    const bound = await settle("bind", bind);
    if (bound === false) {
      failures.push("bind");
    }
    await settle("secciones", initPanelSections);
    await settle("seed aleatoria", initSeedRandom);
    await settle("perfiles H3", loadH3Profiles);
    await settle("video", applyVideoEngine);
    await settle("editor", () => {
      updateEditorControls();
      updateEditorMode();
    });
    await settle("parámetros", loadParams);
    await settle("formatos", loadFormats);
    await settle("modelos", loadModels);
    await settle("catálogo OC", loadOcCatalog);
    await settle("preprompts OC", loadOcPreprompts);
    await settle("OCs", loadCharacters);
    await settle("negativo", refreshNegative);
    await settle("defaults de arranque", applyStartupDefaults);
    await settle("visor de video", () => loadVideoViewer());
    await settle("visor de imagen", () => loadImageViewer());
    await settle("galería del editor", () => loadEditorGallery(1));
    await settle("upscaler", () => loadUpscaleGallery(1));
    await settle("modelos de upscaler", loadUpscaleModels);
    await settle("zonas", renderZoneEditor);
    await settle("estado del editor", loadEditorStatus);
    await settle("estado del LLM", refreshLlmStatus);
    setInterval(refreshLlmStatus, 15000);
  } catch (error) {
    console.error("init", error);
    setStatus(`Error al iniciar: ${error.message}`, true);
    return;
  }
  if (failures.length) {
    setStatus(`Fallaron: ${failures.join(", ")}`, true);
  } else {
    setStatus("Listo");
  }
}

document.addEventListener("DOMContentLoaded", init);

export {
  switchTab,
  panelSectionKey,
  readStoredSection,
  storeSection,
  initPanelSections,
  REQUIRED_IDS,
  bind,
  init,
};
