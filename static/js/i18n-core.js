// WaifuStudio — nucleo de internacionalizacion.
// Que hace: resuelve textos visibles por idioma sin tocar IDs, valores ni datos.
// Que no hace: no manipula el DOM ni conoce la app.

import { TEXT } from "./i18n-data.js";

const HAS_ENGLISH = Object.keys(TEXT.en || {}).length > 0;
export const DEFAULT_LANG = "es";
export const LOCALES = ["en", "es", "ja", "zh", "ru"];
export const LOCALE_LABELS = {
  en: "English",
  es: "Espanol",
  ja: "Japanese",
  zh: "Chinese",
  ru: "Russian",
};

const PATTERNS = {
  en: [
    [/^L([0-3]) \(Sutil\)$/, "L$1 (Subtle)"],
    [/^L([0-3]) \(Moderada\)$/, "L$1 (Moderate)"],
    [/^L([0-3]) \(Expansiva\)$/, "L$1 (Expansive)"],
    [/^L([0-3]) \(Extrema\)$/, "L$1 (Extreme)"],
    [/^Pasos: (\d+) \(VDN 8-Pasos \(Ultra Rápido\)\)$/, "Steps: $1 (VDN 8-Step (Ultra Fast))"],
    [/^Encolar \((\d+)\)$/, "Queue ($1)"],
    [/^Cargado #(\d+) · (.+)$/, "Loaded #$1 · $2"],
    [/^Cargado #(\d+)$/, "Loaded #$1"],
    [/^Modelo: (.+)$/, "Model: $1"],
    [/^Fuerza (\d+(?:\.\d+)?)$/, "Strength $1"],
    [/^Fuerza LoRA Turbo (\d+(?:\.\d+)?)$/, "Turbo LoRA strength $1"],
    [/^Denoise (\d+(?:\.\d+)?)$/, "Denoise $1"],
    [/^LoRAs \((\d+)\)$/, "LoRAs ($1)"],
    [/^Prompt generado ✓ · (.+)$/, "Prompt generated ✓ · $1"],
    [/^Resultado de (.+); abrelo en su pestana$/, "Result from $1; open it in its tab"],
    [/^Resultado de (.+); ábrelo en su pestaña$/, "Result from $1; open it in its tab"],
    [/^Error al iniciar: (.+)$/, "Startup error: $1"],
    [/^Fallaron: (.+)$/, "Failed: $1"],
    [/^paso -\/-$/, "step -/-"],
    [/^paso ([^/]+)\/([^ ]+) · nodo (.+)$/, "step $1/$2 · node $3"],
    [/^paso ([^/]+)\/([^ ]+)$/, "step $1/$2"],
    [/^Generación #(\d+)$/, "Generation #$1"],
    [/^página (\d+) de (\d+)$/, "page $1 of $2"],
    [/^(\d+) clips$/, "$1 clips"],
    [/^(\d+) seleccionadas$/, "$1 selected"],
    [/^(\d+) seleccionados$/, "$1 selected"],
    [/^Referencias: (\d+)\/(\d+)$/, "References: $1/$2"],
    [/^Duración total: (.+)$/, "Total duration: $1"],
    [/^En cola \((\d+) tareas\)\.\.\.$/, "Queued ($1 tasks)..."],
    [/^Pasos: (\d+) \((.+)\)$/, "Steps: $1 ($2)"],
    [/^Cargar generación #(\d+)$/, "Load generation #$1"],
    [/^#(\d+) cargada como referencia$/, "#$1 loaded as reference"],
    [/^#(\d+) como primer fotograma$/, "#$1 as first frame"],
    [/^#(\d+) seleccionada como origen$/, "#$1 selected as source"],
    [/^Error: (.+)$/, "Error: $1"],
    [/^Video V2V previo: (.+)$/, "Previous V2V video: $1"],
    [/^(\d+) tags personalizadas$/, "$1 custom tags"],
    [/^Resolución nativa: (.+)$/, "Native resolution: $1"],
    [/^Pasos: (\d+) \(VDN 8-Pasos \(Ultra Rápido\)\)$/, "Steps: $1 (VDN 8-Step (Ultra Fast))"],
    [/^Pasos: (\d+) \(mejor calidad, ~2×\)$/, "Steps: $1 (better quality, ~2×)"],
    [/^Pasos: (\d+) \(turbo\)$/, "Steps: $1 (turbo)"],
  ],
  ja: [
    [/^L([0-3]) \(Sutil\)$/, "L$1 (軽微)"],
    [/^L([0-3]) \(Moderada\)$/, "L$1 (中程度)"],
    [/^L([0-3]) \(Expansiva\)$/, "L$1 (大幅)"],
    [/^L([0-3]) \(Extrema\)$/, "L$1 (極端)"],
    [/^Pasos: (\d+) \(VDN 8-Pasos \(Ultra Rápido\)\)$/, "ステップ: $1 (VDN 8ステップ (超高速))"],
    [/^Encolar \((\d+)\)$/, "キュー ($1)"],
    [/^Cargado #(\d+) · (.+)$/, "読み込み済み #$1 · $2"],
    [/^Cargado #(\d+)$/, "読み込み済み #$1"],
    [/^Modelo: (.+)$/, "モデル: $1"],
    [/^Fuerza (\d+(?:\.\d+)?)$/, "強度 $1"],
    [/^Fuerza LoRA Turbo (\d+(?:\.\d+)?)$/, "Turbo LoRA 強度 $1"],
    [/^Denoise (\d+(?:\.\d+)?)$/, "Denoise $1"],
    [/^LoRAs \((\d+)\)$/, "LoRAs ($1)"],
    [/^Prompt generado ✓ · (.+)$/, "プロンプト生成 ✓ · $1"],
    [/^Resultado de (.+); (?:ábrelo en su pestaña|abrelo en su pestana)$/, "$1 の結果。タブで開いてください"],
    [/^Error al iniciar: (.+)$/, "起動エラー: $1"],
    [/^Fallaron: (.+)$/, "失敗: $1"],
    [/^paso -\/-$/, "ステップ -/-"],
    [/^paso ([^/]+)\/([^ ]+) · nodo (.+)$/, "ステップ $1/$2 · ノード $3"],
    [/^paso ([^/]+)\/([^ ]+)$/, "ステップ $1/$2"],
    [/^Generación #(\d+)$/, "生成 #$1"],
    [/^página (\d+) de (\d+)$/, "$2 ページ中 $1"],
    [/^(\d+) clips$/, "$1 クリップ"],
    [/^(\d+) seleccionadas$/, "$1 件選択"],
    [/^(\d+) seleccionados$/, "$1 件選択"],
    [/^Referencias: (\d+)\/(\d+)$/, "参照: $1/$2"],
    [/^Duración total: (.+)$/, "合計時間: $1"],
    [/^En cola \((\d+) tareas\)\.\.\.$/, "キューに追加 ($1 件)..."],
    [/^Pasos: (\d+) \((.+)\)$/, "ステップ: $1 ($2)"],
    [/^Cargar generación #(\d+)$/, "生成 #$1 を読み込む"],
    [/^#(\d+) cargada como referencia$/, "#$1 を参照として読み込み"],
    [/^#(\d+) como primer fotograma$/, "#$1 を最初のフレームに"],
    [/^#(\d+) seleccionada como origen$/, "#$1 をソースに選択"],
    [/^Error: (.+)$/, "エラー: $1"],
    [/^Video V2V previo: (.+)$/, "以前の V2V 動画: $1"],
    [/^(\d+) tags personalizadas$/, "カスタムタグ $1 件"],
    [/^Resolución nativa: (.+)$/, "ネイティブ解像度: $1"],
    [/^Pasos: (\d+) \(VDN 8-Pasos \(Ultra Rápido\)\)$/, "ステップ: $1 (VDN 8ステップ (超高速))"],
    [/^Pasos: (\d+) \(mejor calidad, ~2×\)$/, "ステップ: $1 (高画質、約2倍)"],
    [/^Pasos: (\d+) \(turbo\)$/, "ステップ: $1 (turbo)"],
  ],
  zh: [
    [/^L([0-3]) \(Sutil\)$/, "L$1 (细微)"],
    [/^L([0-3]) \(Moderada\)$/, "L$1 (中等)"],
    [/^L([0-3]) \(Expansiva\)$/, "L$1 (大幅)"],
    [/^L([0-3]) \(Extrema\)$/, "L$1 (极端)"],
    [/^Pasos: (\d+) \(VDN 8-Pasos \(Ultra Rápido\)\)$/, "步数：$1（VDN 8 步（超快））"],
    [/^Encolar \((\d+)\)$/, "排队 ($1)"],
    [/^Cargado #(\d+) · (.+)$/, "已加载 #$1 · $2"],
    [/^Cargado #(\d+)$/, "已加载 #$1"],
    [/^Modelo: (.+)$/, "模型：$1"],
    [/^Fuerza (\d+(?:\.\d+)?)$/, "强度 $1"],
    [/^Fuerza LoRA Turbo (\d+(?:\.\d+)?)$/, "Turbo LoRA 强度 $1"],
    [/^Denoise (\d+(?:\.\d+)?)$/, "Denoise $1"],
    [/^LoRAs \((\d+)\)$/, "LoRAs ($1)"],
    [/^Prompt generado ✓ · (.+)$/, "提示词已生成 ✓ · $1"],
    [/^Resultado de (.+); (?:ábrelo en su pestaña|abrelo en su pestana)$/, "$1 的结果，请在对应标签页打开"],
    [/^Error al iniciar: (.+)$/, "启动错误：$1"],
    [/^Fallaron: (.+)$/, "失败：$1"],
    [/^paso -\/-$/, "步骤 -/-"],
    [/^paso ([^/]+)\/([^ ]+) · nodo (.+)$/, "步骤 $1/$2 · 节点 $3"],
    [/^paso ([^/]+)\/([^ ]+)$/, "步骤 $1/$2"],
    [/^Generación #(\d+)$/, "生成 #$1"],
    [/^página (\d+) de (\d+)$/, "第 $1 页，共 $2 页"],
    [/^(\d+) clips$/, "$1 个片段"],
    [/^(\d+) seleccionadas$/, "已选择 $1 项"],
    [/^(\d+) seleccionados$/, "已选择 $1 项"],
    [/^Referencias: (\d+)\/(\d+)$/, "参考图：$1/$2"],
    [/^Duración total: (.+)$/, "总时长：$1"],
    [/^En cola \((\d+) tareas\)\.\.\.$/, "排队中（$1 个任务）..."],
    [/^Pasos: (\d+) \((.+)\)$/, "步数：$1（$2）"],
    [/^Cargar generación #(\d+)$/, "加载生成 #$1"],
    [/^#(\d+) cargada como referencia$/, "#$1 已加载为参考"],
    [/^#(\d+) como primer fotograma$/, "#$1 作为首帧"],
    [/^#(\d+) seleccionada como origen$/, "#$1 已选为源"],
    [/^Error: (.+)$/, "错误：$1"],
    [/^Video V2V previo: (.+)$/, "之前的 V2V 视频：$1"],
    [/^(\d+) tags personalizadas$/, "$1 个自定义标签"],
    [/^Resolución nativa: (.+)$/, "原生分辨率：$1"],
    [/^Pasos: (\d+) \(VDN 8-Pasos \(Ultra Rápido\)\)$/, "步数：$1（VDN 8 步（超快））"],
    [/^Pasos: (\d+) \(mejor calidad, ~2×\)$/, "步数：$1（更高质量，约 2×）"],
    [/^Pasos: (\d+) \(turbo\)$/, "步数：$1（turbo）"],
  ],
  ru: [
    [/^L([0-3]) \(Sutil\)$/, "L$1 (минимально)"],
    [/^L([0-3]) \(Moderada\)$/, "L$1 (умеренно)"],
    [/^L([0-3]) \(Expansiva\)$/, "L$1 (выраженно)"],
    [/^L([0-3]) \(Extrema\)$/, "L$1 (радикально)"],
    [/^Pasos: (\d+) \(VDN 8-Pasos \(Ultra Rápido\)\)$/, "Шаги: $1 (VDN 8 шагов (сверхбыстро))"],
    [/^Encolar \((\d+)\)$/, "В очередь ($1)"],
    [/^Cargado #(\d+) · (.+)$/, "Загружено #$1 · $2"],
    [/^Cargado #(\d+)$/, "Загружено #$1"],
    [/^Modelo: (.+)$/, "Модель: $1"],
    [/^Fuerza (\d+(?:\.\d+)?)$/, "Сила $1"],
    [/^Fuerza LoRA Turbo (\d+(?:\.\d+)?)$/, "Сила Turbo LoRA $1"],
    [/^Denoise (\d+(?:\.\d+)?)$/, "Denoise $1"],
    [/^LoRAs \((\d+)\)$/, "LoRAs ($1)"],
    [/^Prompt generado ✓ · (.+)$/, "Промпт создан ✓ · $1"],
    [/^Resultado de (.+); (?:ábrelo en su pestaña|abrelo en su pestana)$/, "Результат $1; откройте его во вкладке"],
    [/^Error al iniciar: (.+)$/, "Ошибка запуска: $1"],
    [/^Fallaron: (.+)$/, "Не удалось: $1"],
    [/^paso -\/-$/, "шаг -/-"],
    [/^paso ([^/]+)\/([^ ]+) · nodo (.+)$/, "шаг $1/$2 · узел $3"],
    [/^paso ([^/]+)\/([^ ]+)$/, "шаг $1/$2"],
    [/^Generación #(\d+)$/, "Генерация #$1"],
    [/^página (\d+) de (\d+)$/, "страница $1 из $2"],
    [/^(\d+) clips$/, "$1 клипов"],
    [/^(\d+) seleccionadas$/, "Выбрано: $1"],
    [/^(\d+) seleccionados$/, "Выбрано: $1"],
    [/^Referencias: (\d+)\/(\d+)$/, "Ссылки: $1/$2"],
    [/^Duración total: (.+)$/, "Общая длительность: $1"],
    [/^En cola \((\d+) tareas\)\.\.\.$/, "В очереди ($1 задач)..."],
    [/^Pasos: (\d+) \((.+)\)$/, "Шаги: $1 ($2)"],
    [/^Cargar generación #(\d+)$/, "Загрузить генерацию #$1"],
    [/^#(\d+) cargada como referencia$/, "#$1 загружена как референс"],
    [/^#(\d+) como primer fotograma$/, "#$1 как первый кадр"],
    [/^#(\d+) seleccionada como origen$/, "#$1 выбрана как источник"],
    [/^Error: (.+)$/, "Ошибка: $1"],
    [/^Video V2V previo: (.+)$/, "Предыдущее V2V-видео: $1"],
    [/^(\d+) tags personalizadas$/, "Пользовательские теги: $1"],
    [/^Resolución nativa: (.+)$/, "Нативное разрешение: $1"],
    [/^Pasos: (\d+) \(VDN 8-Pasos \(Ultra Rápido\)\)$/, "Шаги: $1 (VDN 8 шагов (сверхбыстро))"],
    [/^Pasos: (\d+) \(mejor calidad, ~2×\)$/, "Шаги: $1 (лучшее качество, ~2×)"],
    [/^Pasos: (\d+) \(turbo\)$/, "Шаги: $1 (turbo)"],
  ],
};

const ATTRIBUTE_PATTERNS = {
  en: [
    [/^Añadir tag a (.+)$/, "Add tag to $1"],
    [/^Añadir a (.+)$/, "Add to $1"],
    [/^Reusar generación #(\d+)$/, "Reuse generation #$1"],
    [/^Cargar generación #(\d+)$/, "Load generation #$1"],
    [/^Usar generación #(\d+) como referencia$/, "Use generation #$1 as reference"],
    [/^Usar generación #(\d+) \((.+)\)$/, "Use generation #$1 ($2)"],
    [/^Usar generación #(\d+)$/, "Use generation #$1"],
    [/^Eliminar (.+)$/, "Delete $1"],
    [/^Descargar (.+)$/, "Download $1"],
    [/^Seleccionar (.+)$/, "Select $1"],
  ],
  ja: [
    [/^Añadir tag a (.+)$/, "$1 にタグを追加"],
    [/^Añadir a (.+)$/, "$1 に追加"],
    [/^Reusar generación #(\d+)$/, "生成 #$1 を再利用"],
    [/^Cargar generación #(\d+)$/, "生成 #$1 を読み込む"],
    [/^Usar generación #(\d+) como referencia$/, "生成 #$1 を参照として使用"],
    [/^Usar generación #(\d+) \((.+)\)$/, "生成 #$1 を使用 ($2)"],
    [/^Usar generación #(\d+)$/, "生成 #$1 を使用"],
    [/^Eliminar (.+)$/, "$1 を削除"],
    [/^Descargar (.+)$/, "$1 をダウンロード"],
    [/^Seleccionar (.+)$/, "$1 を選択"],
  ],
  zh: [
    [/^Añadir tag a (.+)$/, "添加标签到 $1"],
    [/^Añadir a (.+)$/, "添加到 $1"],
    [/^Reusar generación #(\d+)$/, "重用生成 #$1"],
    [/^Cargar generación #(\d+)$/, "加载生成 #$1"],
    [/^Usar generación #(\d+) como referencia$/, "使用生成 #$1 作为参考"],
    [/^Usar generación #(\d+) \((.+)\)$/, "使用生成 #$1（$2）"],
    [/^Usar generación #(\d+)$/, "使用生成 #$1"],
    [/^Eliminar (.+)$/, "删除 $1"],
    [/^Descargar (.+)$/, "下载 $1"],
    [/^Seleccionar (.+)$/, "选择 $1"],
  ],
  ru: [
    [/^Añadir tag a (.+)$/, "Добавить тег в $1"],
    [/^Añadir a (.+)$/, "Добавить в $1"],
    [/^Reusar generación #(\d+)$/, "Использовать генерацию #$1"],
    [/^Cargar generación #(\d+)$/, "Загрузить генерацию #$1"],
    [/^Usar generación #(\d+) como referencia$/, "Использовать генерацию #$1 как референс"],
    [/^Usar generación #(\d+) \((.+)\)$/, "Использовать генерацию #$1 ($2)"],
    [/^Usar generación #(\d+)$/, "Использовать генерацию #$1"],
    [/^Eliminar (.+)$/, "Удалить $1"],
    [/^Descargar (.+)$/, "Скачать $1"],
    [/^Seleccionar (.+)$/, "Выбрать $1"],
  ],
};

let currentLang = DEFAULT_LANG;

function normalizeLang(value) {
  const lang = String(value || "").trim().toLowerCase();
  return LOCALES.includes(lang) ? lang : DEFAULT_LANG;
}

function lookup(text, lang) {
  const key = String(text || "").replace(/\s+/g, " ").trim();
  if (!key) return null;
  const dictionaries = [TEXT[lang], TEXT.en, TEXT.es].filter(Boolean);
  for (const dictionary of dictionaries) {
    if (Object.prototype.hasOwnProperty.call(dictionary, key)) {
      const value = dictionary[key];
      if (typeof value === "string" && value.trim()) return value;
    }
  }
  return null;
}

export function getCurrentLang() {
  return currentLang;
}

export function setCurrentLang(lang) {
  currentLang = normalizeLang(lang);
  return currentLang;
}

export function isSupportedLang(lang) {
  return LOCALES.includes(String(lang || "").trim().toLowerCase());
}

export function translateText(text, lang = currentLang) {
  if (text == null || text === "") return text;
  const target = normalizeLang(lang);
  if (target === "es") return String(text);

  const exact = lookup(text, target);
  if (exact != null) return exact;

  const source = String(text).replace(/\s+/g, " ").trim();
  for (const [pattern, replacement] of PATTERNS[target] || []) {
    if (pattern.test(source)) return source.replace(pattern, replacement);
  }
  return String(text);
}

export function translateAttribute(value, lang = currentLang) {
  if (value == null || value === "") return value;
  const target = normalizeLang(lang);
  if (target === "es") return value;
  const exact = translateText(value, target);
  if (exact !== value) return exact;
  for (const [pattern, template] of ATTRIBUTE_PATTERNS[target] || []) {
    const match = String(value).match(pattern);
    if (!match) continue;
    let result = template;
    for (let index = 1; index < match.length; index += 1) {
      const argument = match[index] == null ? "" : translateText(match[index], target);
      result = result.replace(`$${index}`, argument);
    }
    return result;
  }
  return value;
}
