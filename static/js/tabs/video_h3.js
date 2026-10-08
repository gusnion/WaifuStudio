// WaifuStudio — Asistente de Prompt y Perfiles H3
// video_h3.js: plantillas H3, guía oficial MiniMax, cálculo de segundos/resolución y profiles.

import {
  state,
  H3_FPS,
  H3_FRAME_BASE,
  H3_FRAME_STEP,
  H3_PROMPT_TEMPLATE,
  H3_GUIDE_TEXT,
  H3_TEMPLATE_PORTRAIT,
  H3_TEMPLATE_WALK,
  H3_TEMPLATE_ACTION,
} from "../state.js";
import {
  $,
  on,
  setVideoStatus,
  writeClipboard,
  option,
  setSelectValue,
  readFileBase64,
} from "../dom.js";
import { api, postJson } from "../api.js";
import { applyVideoEngine } from "./video.js";

let h3PromptResetTimer = null;
let h3PromptStatusTimer = null;

async function improveH3Prompt() {
  if (state.pendingH3Prompt) {
    return;
  }
  const area = $("video-prompt");
  const text = area.value.trim();
  if (!text) {
    setH3PromptStatus("Escribe el prompt H3 para mejorarlo", true);
    area.focus();
    return;
  }
  const button = $("btn-h3-prompt");
  state.pendingH3Prompt = true;
  button.disabled = true;
  button.textContent = "Mejorando…";
  setH3PromptStatus("Generando…");
  if (h3PromptStatusTimer) {
    clearTimeout(h3PromptStatusTimer);
    h3PromptStatusTimer = null;
  }
  try {
    const ratingEl = $("video-rating");
    const mode = $("video-mode") ? $("video-mode").value : "i2v";
    const strengthEl = $("video-h3-prompt-strength");
    const strength = (strengthEl && strengthEl.value) || "balanceado";
    let image_b64 = null;
    let images_b64 = null;
    if (mode === "ref2va" && state.videoRefs && state.videoRefs.length > 0) {
      images_b64 = state.videoRefs.map((ref) => {
        const raw = ref.b64 || "";
        return raw.includes(",") ? raw.split(",", 2)[1] : raw;
      });
    } else {
      const videoImageInput = $("video-image");
      const file = videoImageInput && videoImageInput.files && videoImageInput.files[0];
      if (file) {
        const rawB64 = await readFileBase64(file);
        image_b64 = (typeof rawB64 === "string" && rawB64.includes(","))
          ? rawB64.split(",", 2)[1]
          : rawB64;
      }
    }
    const reqBody = {
      text,
      rating: (ratingEl && ratingEl.value) || "nsfw",
      strength,
    };
    if (images_b64) {
      reqBody.images_b64 = images_b64;
    } else if (image_b64) {
      reqBody.image_b64 = image_b64;
    }
    const data = await postJson("/api/video/h3_prompt", reqBody);
    area.value = data.h3_prompt || "";
    button.textContent = "Listo ✓";
    setH3PromptStatus("Generado ✓");
    if (h3PromptStatusTimer) {
      clearTimeout(h3PromptStatusTimer);
    }
    h3PromptStatusTimer = setTimeout(() => {
      if (!state.pendingH3Prompt) {
        setH3PromptStatus("");
      }
    }, 2000);
  } catch (error) {
    button.textContent = "Error";
    setH3PromptStatus(error.message, true);
  } finally {
    state.pendingH3Prompt = false;
    button.disabled = false;
    if (h3PromptResetTimer) {
      clearTimeout(h3PromptResetTimer);
    }
    h3PromptResetTimer = setTimeout(() => {
      if (!state.pendingH3Prompt) {
        button.textContent = "Mejorar prompt (H3)";
      }
    }, 1600);
  }
}


function selectedH3Profile() {
  return (
    state.videoH3Profiles.find(
      (profile) => profile.id === $("video-h3-profile").value
    ) || null
  );
}

function h3FramesForSeconds(seconds) {
  const needed = Math.ceil(seconds * H3_FPS);
  if (needed <= H3_FRAME_BASE) {
    return H3_FRAME_BASE;
  }
  return (
    H3_FRAME_BASE +
    H3_FRAME_STEP * Math.ceil((needed - H3_FRAME_BASE) / H3_FRAME_STEP)
  );
}

function defaultH3Seconds() {
  const profile = state.videoH3Profiles.find((item) => item.id === "estandar" || item.id === "calidad");
  const recommended = (profile && profile.seconds_recomendados) || [];
  return recommended.length ? recommended[0] : state.videoH3Seconds[0] || 8;
}

function fillH3Sizes() {
  const select = $("video-h3-size");
  if (!select) return;
  const aspect = ($("video-h3-aspect") && $("video-h3-aspect").value) || "vertical";
  const previous = select.value;
  select.replaceChildren();
  const list = (state.videoH3Resolutions && state.videoH3Resolutions[aspect]) || [];
  for (const size of list) {
    const idUpper = (size.id || "").toUpperCase();
    const label = size.label ? `${idUpper} · ${size.label}` : `${idUpper} · ${size.width}×${size.height}`;
    select.appendChild(
      option(`${size.width}x${size.height}`, label)
    );
  }
  if (previous && Array.from(select.options).some((o) => o.value === previous)) {
    select.value = previous;
  } else {
    const hdOpt = Array.from(select.options).find((o) => o.textContent.startsWith("HD"));
    if (hdOpt) {
      select.value = hdOpt.value;
    }
  }
  updateH3Notes();
}

function selectedH3Size() {
  const el = $("video-h3-size");
  if (!el || !el.value) return null;
  const parts = el.value.split("x");
  const width = Number(parts[0]);
  const height = Number(parts[1]);
  return Number.isFinite(width) && Number.isFinite(height)
    ? { width, height }
    : null;
}

function updateH3Notes() {
  const profile = selectedH3Profile();
  const note = $("video-h3-profile-note");
  if (note) {
    if (!profile) {
      note.textContent = "Cargando perfiles…";
    } else {
      let desc = profile.note || "";
      if (profile.vram_hint) {
        desc += ` · ${profile.vram_hint}`;
      }
      note.textContent = desc;
    }
  }

  const customPanel = $("video-custom-settings-panel");
  if (customPanel) {
    const isCustom = profile && profile.id === "personalizado";
    customPanel.classList.toggle("hidden", !isCustom);
  }

  const seconds = Number($("video-h3-seconds") ? $("video-h3-seconds").value : 8);
  const secondsInfo = $("video-h3-seconds-info");
  if (secondsInfo) {
    secondsInfo.textContent = Number.isFinite(seconds)
      ? `≈ ${seconds} s → ${h3FramesForSeconds(seconds)} frames (${H3_FPS} fps)`
      : "";
  }

  const size = selectedH3Size();
  const sizeInfo = $("video-h3-size-info");
  const vramWarning = $("video-h3-vram-warning");
  if (size) {
    const aspect = ($("video-h3-aspect") && $("video-h3-aspect").value) || "vertical";
    const list = (state.videoH3Resolutions && state.videoH3Resolutions[aspect]) || [];
    const found = list.find((item) => item.width === size.width && item.height === size.height);
    const vramHint = (found && found.vram_hint) || "12GB VRAM";
    if (sizeInfo) {
      sizeInfo.textContent = `Resolución nativa: ${size.width}×${size.height} · ${vramHint}`;
    }
    const isHighRes = found && ["fhd", "qhd", "2k"].includes(found.id);
    if (vramWarning) {
      if (isHighRes) {
        vramWarning.textContent = "⚠️ En GPUs de 12GB (como RTX 3060), esta resolución puede requerir >16GB VRAM y generar error Out Of Memory (OOM). Si ocurre, usa HD o reduce la duración.";
        vramWarning.classList.remove("hidden");
      } else {
        vramWarning.textContent = "";
        vramWarning.classList.add("hidden");
      }
    }
  } else if (sizeInfo) {
    sizeInfo.textContent = "";
  }
}

const PROFILE_COMPATIBLE_VARIANTS = {
  rapido: ["turbo4", "turbo8"],
  estandar: ["turbo4", "turbo8"],
  calidad: ["turbo4", "turbo8"],
  ultra: ["vdn8"],
  personalizado: ["turbo4", "turbo8", "vdn8"],
  ref2va: ["vdn8"],
  vdn: ["vdn8"],
  referencia: ["turbo4", "turbo8"],
  ligero: ["turbo4", "turbo8"],
};

function updateH3Variants() {
  const profileEl = $("video-h3-profile");
  const profile = profileEl ? profileEl.value : "estandar";
  const allowed = PROFILE_COMPATIBLE_VARIANTS[profile] || ["turbo4", "turbo8"];
  const variantSelect = $("video-h3-variant");
  if (!variantSelect) return;
  const currentVal = variantSelect.value;
  variantSelect.replaceChildren();
  for (const variant of state.videoH3Variants || []) {
    if (allowed.includes(variant.id)) {
      variantSelect.appendChild(
        option(variant.id, `Pasos: ${variant.steps} (${variant.label})`)
      );
    }
  }
  if (allowed.includes(currentVal)) {
    variantSelect.value = currentVal;
  } else if (profile === "ultra" || profile === "vdn" || profile === "ref2va") {
    variantSelect.value = "vdn8";
  } else if (allowed.length > 0) {
    variantSelect.value = allowed[0];
  }
}

function onH3ProfileChange() {
  const profile = $("video-h3-profile") ? $("video-h3-profile").value : "";
  if (profile === "ref2va" && $("video-mode") && $("video-mode").value !== "ref2va") {
    setSelectValue($("video-mode"), "ref2va");
    applyVideoEngine();
  } else if (profile !== "ref2va" && $("video-mode") && $("video-mode").value === "ref2va") {
    setSelectValue($("video-mode"), "i2v");
    applyVideoEngine();
  }
  updateH3Variants();
  updateH3Notes();
}

async function loadH3Profiles() {
  const data = await api("/api/video/h3_profiles");
  state.videoH3Profiles = data.items || data.profiles || [];
  state.videoH3Variants = data.variants || [];
  state.videoH3Seconds = data.seconds || [];
  state.videoH3Resolutions = data.resolutions || {};
  const profileSelect = $("video-h3-profile");
  profileSelect.replaceChildren();
  for (const profile of state.videoH3Profiles) {
    let label = profile.label || profile.id;
    if (profile.available === false) {
      label = profile.id === "ultra" || profile.id === "vdn"
        ? "Ultra (8-Pasos VDN · Requiere Pesos)"
        : `${label} (No disponible)`;
    }
    const opt = option(profile.id, label);
    if (profile.available === false) {
      opt.title = profile.missing_reason || "Requiere pesos no instalados";
    }
    profileSelect.appendChild(opt);
  }
  setSelectValue(profileSelect, "estandar");
  updateH3Variants();
  const secondsSelect = $("video-h3-seconds");
  secondsSelect.replaceChildren();
  for (const seconds of state.videoH3Seconds) {
    secondsSelect.appendChild(option(String(seconds), `${seconds} s`));
  }
  fillH3Sizes();
  setSelectValue($("video-h3-variant"), "turbo8");
  setSelectValue(secondsSelect, String(defaultH3Seconds()));
  updateH3Notes();
}


function setH3GuideStatus(text, isError = false) {
  const el = $("h3-guide-status");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setH3PromptStatus(text, isError = false) {
  const el = $("h3-prompt-status");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function insertH3Template() {
  const area = $("video-prompt");
  if (!area) {
    return;
  }
  const current = area.value.replace(/\s+$/, "");
  area.value = current ? `${current}\n\n${H3_PROMPT_TEMPLATE}` : H3_PROMPT_TEMPLATE;
  area.focus();
  setH3GuideStatus("Plantilla insertada");
}

async function copyH3Guide() {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(H3_GUIDE_TEXT);
    } else {
      const area = document.createElement("textarea");
      area.value = H3_GUIDE_TEXT;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setH3GuideStatus("Guía copiada");
  } catch (error) {
    setH3GuideStatus(error.message, true);
  }
}


function initVideoH3() {
  on("btn-h3-prompt", "click", improveH3Prompt);
  on("video-h3-profile", "change", onH3ProfileChange);
  on("video-h3-seconds", "change", updateH3Notes);
  on("video-h3-aspect", "change", fillH3Sizes);
  on("video-h3-size", "change", updateH3Notes);
  on("btn-h3-insert-template", "click", insertH3Template);
  on("btn-h3-template-portrait", "click", () => {
    const area = $("video-prompt");
    if (area) {
      area.value = H3_TEMPLATE_PORTRAIT;
      area.focus();
      setH3GuideStatus("Plantilla 'Retrato Anime' insertada");
    }
  });
  on("btn-h3-template-walk", "click", () => {
    const area = $("video-prompt");
    if (area) {
      area.value = H3_TEMPLATE_WALK;
      area.focus();
      setH3GuideStatus("Plantilla 'Caminata Costa' insertada");
    }
  });
  on("btn-h3-template-action", "click", () => {
    const area = $("video-prompt");
    if (area) {
      area.value = H3_TEMPLATE_ACTION;
      area.focus();
      setH3GuideStatus("Plantilla 'Escena Dinámica' insertada");
    }
  });
  on("btn-h3-copy-guide", "click", copyH3Guide);
}

function updateVideoDurationInfo() {
  updateH3Notes();
}

export {
  improveH3Prompt,
  selectedH3Profile,
  h3FramesForSeconds,
  defaultH3Seconds,
  fillH3Sizes,
  selectedH3Size,
  updateH3Notes,
  updateH3Variants,
  updateVideoDurationInfo,
  onH3ProfileChange,
  loadH3Profiles,
  setH3GuideStatus,
  setH3PromptStatus,
  insertH3Template,
  copyH3Guide,
  initVideoH3,
};
