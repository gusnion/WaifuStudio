// WaifuStudio — Header Global: Recarga Universal, Selector de Idioma y Tema Claro/Oscuro (M18-01, M18-02, C-13)
// Qué hace: controla #btn-universal-reload, #btn-language-selector y #btn-theme-toggle en el topbar.
// Qué no hace: no maneja navegación principal de pestañas.

import { $, on } from "../dom.js";
import { loadEditorGallery, loadEditorStatus } from "../tabs/editor.js";
import { loadUpscaleGallery, applyUpscaleKind } from "../tabs/upscaler.js";
import { applyLanguage, getCurrentLang, isSupportedLang } from "../i18n.js";

const STORAGE_LANG_KEY = "waifu_lang";
export const THEME_KEY = "waifu.theme";
const THEME_LEGACY_KEY = "waifu_theme";

/**
 * Sincroniza icono y atributos ARIA/título de accesibilidad en #btn-theme-toggle.
 * @param {"light"|"dark"} theme
 */
export function syncThemeUI(theme) {
  const isLight = theme === "light";
  const btn = $("btn-theme-toggle");
  if (btn) {
    btn.setAttribute("aria-pressed", isLight ? "true" : "false");
    const label = isLight ? "Cambiar a tema oscuro" : "Cambiar a tema claro";
    btn.setAttribute("aria-label", label);
    btn.setAttribute("title", label);
  }

  const icon = $("theme-toggle-icon");
  if (icon) {
    icon.classList.toggle("is-light", isLight);
  }
}

/**
 * Aplica el tema activo, persistencia en localStorage y metadatos.
 * @param {"light"|"dark"} theme
 */
export function applyTheme(theme) {
  const value = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = value;

  try {
    localStorage.setItem(THEME_KEY, value);
  } catch (_) {}

  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", value === "light" ? "#f6f7fb" : "#14151a");
  }

  syncThemeUI(value);

  window.dispatchEvent(
    new CustomEvent("waifu:theme-changed", { detail: { theme: value } })
  );
}

/**
 * Inicializa el interruptor #btn-theme-toggle con persistencia, ARIA y sincronía.
 */
export function initThemeToggle() {
  const button = $("btn-theme-toggle");
  if (!button) return;

  // Restaurar estado inicial
  let saved = null;
  try {
    saved = localStorage.getItem(THEME_KEY) || localStorage.getItem(THEME_LEGACY_KEY);
  } catch (_) {}

  if (saved !== "light" && saved !== "dark") {
    saved = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  }
  applyTheme(saved);

  // Observador de cambios en dataset.theme para mantener ARIA e icono sincronizados
  if (!button.dataset.themeObserved) {
    button.dataset.themeObserved = "true";
    if (typeof MutationObserver !== "undefined") {
      const observer = new MutationObserver((mutations) => {
        for (const m of mutations) {
          if (m.type === "attributes" && m.attributeName === "data-theme") {
            const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
            syncThemeUI(current);
          }
        }
      });
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
  }

  // Prevenir handlers duplicados
  if (button.dataset.themeBound) return;
  button.dataset.themeBound = "true";

  button.addEventListener("click", () => {
    const prevTheme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    setTimeout(() => {
      const currentTheme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
      if (currentTheme === prevTheme) {
        // Ningún otro handler alternó el tema, lo alternamos aquí
        const next = prevTheme === "light" ? "dark" : "light";
        applyTheme(next);
      } else {
        // Otro listener (ej. theme.js) ya alternó data-theme, asegurar persistencia y UI
        syncThemeUI(currentTheme);
        try { localStorage.setItem(THEME_KEY, currentTheme); } catch (_) {}
      }
    }, 0);
  });
}

export function getActiveTab() {
  const tabs = ["image", "video", "editor", "timeline", "upscaler", "gallery", "guide", "test"];
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
  if (langBtn.dataset.langBound === "1") return;
  langBtn.dataset.langBound = "1";

  const currentLang = getCurrentLang();
  if (label) label.textContent = currentLang.toUpperCase();

  const options = dropdown.querySelectorAll(".lang-option");
  options.forEach((opt) => {
    opt.classList.toggle("active", opt.dataset.lang === currentLang);
    opt.addEventListener("click", (e) => {
      e.stopPropagation();
      const lang = isSupportedLang(opt.dataset.lang) ? opt.dataset.lang : getCurrentLang();
      localStorage.setItem(STORAGE_LANG_KEY, lang);
      if (label) label.textContent = lang.toUpperCase();
      options.forEach((o) => o.classList.toggle("active", o === opt));
      dropdown.classList.add("hidden");
      applyLanguage(lang);
      window.dispatchEvent(
        new CustomEvent("waifu:language-changed", { detail: { lang } })
      );
      window.dispatchEvent(
        new CustomEvent("waifu:languagechange", { detail: { lang } })
      );
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
  initThemeToggle();
  initLanguageSelector();
}
