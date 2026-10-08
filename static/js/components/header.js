// WaifuStudio — Header Global: Recarga Universal y Selector de Idioma (M18-01, M18-02)
// Qué hace: controla #btn-universal-reload y #btn-language-selector en el topbar.
// Qué no hace: no maneja navegación principal de pestañas.

import { $, on } from "../dom.js";
import { loadEditorGallery, loadEditorStatus } from "../tabs/editor.js";
import { loadUpscaleGallery, applyUpscaleKind } from "../tabs/upscaler.js";

const STORAGE_LANG_KEY = "waifu_lang";

export function getActiveTab() {
  const tabs = ["image", "video", "editor", "upscaler", "gallery", "test"];
  for (const t of tabs) {
    const el = $(`panel-${t}`);
    if (el && el.classList.contains("active")) {
      return t;
    }
  }
  return "image";
}

export function triggerActiveTabReload() {
  const activeTab = getActiveTab();
  const reloadBtn = $("btn-universal-reload");
  if (reloadBtn) {
    reloadBtn.classList.add("spin");
    setTimeout(() => reloadBtn.classList.remove("spin"), 600);
  }

  switch (activeTab) {
    case "image": {
      const localBtn = $("btn-reload");
      if (localBtn) localBtn.click();
      break;
    }
    case "video": {
      const localBtn = $("btn-video-reload");
      if (localBtn) localBtn.click();
      break;
    }
    case "editor": {
      try {
        loadEditorStatus();
        loadEditorGallery(1);
      } catch (err) {
        console.warn("Editor reload error:", err);
      }
      break;
    }
    case "upscaler": {
      try {
        applyUpscaleKind();
        loadUpscaleGallery(1);
      } catch (err) {
        console.warn("Upscaler reload error:", err);
      }
      break;
    }
    case "gallery": {
      const galleryRefresh = $("btn-gallery-refresh");
      if (galleryRefresh) galleryRefresh.click();
      break;
    }
    case "test": {
      const event = new CustomEvent("waifu:test-reload");
      window.dispatchEvent(event);
      break;
    }
    default:
      break;
  }
}

export function initLanguageSelector() {
  const langBtn = $("btn-language-selector");
  const dropdown = $("language-dropdown");
  const label = $("lang-current-label");
  if (!langBtn || !dropdown) return;

  const currentLang = localStorage.getItem(STORAGE_LANG_KEY) || "es";
  if (label) label.textContent = currentLang.toUpperCase();

  const options = dropdown.querySelectorAll(".lang-option");
  options.forEach((opt) => {
    opt.classList.toggle("active", opt.dataset.lang === currentLang);
    opt.addEventListener("click", (e) => {
      e.stopPropagation();
      const lang = opt.dataset.lang || "es";
      localStorage.setItem(STORAGE_LANG_KEY, lang);
      if (label) label.textContent = lang.toUpperCase();
      options.forEach((o) => o.classList.toggle("active", o === opt));
      dropdown.classList.add("hidden");
    });
  });

  langBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown.classList.toggle("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!dropdown.contains(e.target) && !langBtn.contains(e.target)) {
      dropdown.classList.add("hidden");
    }
  });
}

export function initHeader() {
  const reloadBtn = $("btn-universal-reload");
  if (reloadBtn) {
    reloadBtn.addEventListener("click", () => triggerActiveTabReload());
  }
  initLanguageSelector();
}
