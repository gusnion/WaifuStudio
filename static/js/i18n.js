// WaifuStudio — internacionalizacion de la interfaz.
// Traduce texto visible y atributos accesibles sin tocar IDs, valores ni datos.
// Dependencias: i18n-core.js.

import {
  DEFAULT_LANG,
  LOCALES,
  getCurrentLang as getCoreLang,
  isSupportedLang,
  setCurrentLang as setCoreLang,
  translateAttribute,
  translateText,
} from "./i18n-core.js";

const STORAGE_KEY = "waifu_lang";
const IGNORE_SELECTOR = [
  "[data-i18n-ignore]",
  ".no-i18n",
  "script",
  "style",
  "pre",
  "textarea",
  "[contenteditable='true']",
].join(",");

const ATTRIBUTE_NAMES = ["placeholder", "title", "aria-label", "alt", "data-help"];
const ATTRIBUTE_IGNORE_SELECTOR = [
  "[data-i18n-ignore]",
  ".no-i18n",
  "script",
  "style",
  "code",
  "pre",
].join(",");

const KEY_TRANSLATIONS = {
  en: {
    queue_prefix: "Queue",
    generate: "Generate",
    upscale_run: "Upscale",
  },
  es: {
    queue_prefix: "Encolar",
    generate: "Generar",
    upscale_run: "Escalar",
  },
  ja: {
    queue_prefix: "キュー",
    generate: "生成",
    upscale_run: "アップスケール",
  },
  zh: {
    queue_prefix: "排队",
    generate: "生成",
    upscale_run: "放大",
  },
  ru: {
    queue_prefix: "В очередь",
    generate: "Создать",
    upscale_run: "Увеличить",
  },
};

let observer = null;
let scheduled = false;

function storedLang() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return isSupportedLang(value) ? value.toLowerCase() : DEFAULT_LANG;
  } catch {
    return DEFAULT_LANG;
  }
}

function hasLetters(value) {
  return /[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\u3040-\u30ff\u3400-\u9fff\u0400-\u04ff]/.test(value);
}

function shouldTranslateText(node) {
  if (!node || node.nodeType !== Node.TEXT_NODE) return false;
  const value = node.nodeValue || "";
  if (!value.trim() || !hasLetters(value)) return false;
  const parent = node.parentElement;
  if (!parent) return false;
  if (parent.closest(IGNORE_SELECTOR)) return false;
  if (parent.closest("svg")) return false;
  return true;
}

function setTextNode(node, translated) {
  if (node.nodeValue === translated) return;
  node.nodeValue = translated;
}

function translateNode(node, lang) {
  if (!shouldTranslateText(node)) return;
  const raw = node.nodeValue || "";
  const source = node.__waifuI18nSource || raw;
  if (lang !== "es") node.__waifuI18nSource = source;
  if (lang === "es") {
    setTextNode(node, source);
    return;
  }
  const leading = source.match(/^\s*/)?.[0] || "";
  const trailing = source.match(/\s*$/)?.[0] || "";
  const translated = translateText(source, lang);
  setTextNode(node, leading + translated + trailing);
}

function translateAttributes(root, lang) {
  const elements = root.querySelectorAll(ATTRIBUTE_NAMES.map((name) => `[${name}]`).join(","));
  for (const element of elements) {
    if (element.closest(ATTRIBUTE_IGNORE_SELECTOR)) continue;
    const store = element.__waifuI18nAttrs || (element.__waifuI18nAttrs = {});
    for (const name of ATTRIBUTE_NAMES) {
      if (!element.hasAttribute(name)) continue;
      const current = element.getAttribute(name) || "";
      if (!current.trim()) continue;
      const source = store[name] || current;
      store[name] = source;
      const translated = lang === "es" ? source : translateAttribute(source, lang);
      if (translated !== current) element.setAttribute(name, translated);
    }
  }
}

function translateStatusElements(root, lang) {
  for (const element of root.querySelectorAll("[data-i18n-source]")) {
    if (element.closest(IGNORE_SELECTOR)) continue;
    const source = element.getAttribute("data-i18n-source") || "";
    if (!source) continue;
    const translated = lang === "es" ? source : translateText(source, lang);
    if (element.textContent !== translated) element.textContent = translated;
  }
}

function walkText(root, lang) {
  const walker = document.createTreeWalker(
    root,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        return shouldTranslateText(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    }
  );
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) translateNode(node, lang);
}

function translateRoot(root, lang) {
  walkText(root, lang);
  translateAttributes(root, lang);
  translateStatusElements(root, lang);
}

function scheduleObservedTranslation() {
  if (scheduled) return;
  scheduled = true;
  setTimeout(() => {
    scheduled = false;
    const lang = getCoreLang();
    if (lang === "es") return;
    translateRoot(document.body, lang);
  }, 0);
}

function startObserver() {
  if (observer || typeof MutationObserver === "undefined") return;
  observer = new MutationObserver((mutations) => {
    const lang = getCoreLang();
    if (lang === "es") return;
    let relevant = false;
    for (const mutation of mutations) {
      if (mutation.type === "childList" && (mutation.addedNodes.length || mutation.removedNodes.length)) {
        relevant = true;
      } else if (mutation.type === "characterData") {
        relevant = true;
      } else if (mutation.type === "attributes") {
        relevant = true;
      }
      if (relevant) break;
    }
    if (relevant) scheduleObservedTranslation();
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRIBUTE_NAMES,
  });
}

export function t(key, lang = getCoreLang()) {
  const target = isSupportedLang(lang) ? lang.toLowerCase() : DEFAULT_LANG;
  return KEY_TRANSLATIONS[target]?.[key] || KEY_TRANSLATIONS.en[key] || key;
}

export function getCurrentLang() {
  return getCoreLang();
}

export function applyLanguage(lang) {
  let target = isSupportedLang(lang) ? String(lang).toLowerCase() : DEFAULT_LANG;
  setCoreLang(target);
  try {
    localStorage.setItem(STORAGE_KEY, target);
  } catch {
    // Sin almacenamiento: la sesion sigue funcionando.
  }

  document.documentElement.lang = target;
  const label = document.getElementById("lang-current-label");
  if (label) label.textContent = target.toUpperCase();
  document.querySelectorAll(".lang-option").forEach((option) => {
    option.classList.toggle("active", (option.dataset.lang || "").toLowerCase() === target);
  });

  translateRoot(document.body, target);
  startObserver();

  window.dispatchEvent(new CustomEvent("waifu:languagechange", { detail: { lang: target } }));
  window.dispatchEvent(new CustomEvent("waifu:language-changed", { detail: { lang: target } }));
}

export function initI18n() {
  applyLanguage(storedLang());
}

export { LOCALES, isSupportedLang, translateAttribute, translateText };
