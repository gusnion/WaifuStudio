// WaifuStudio — Gestor de Zonas de Prompt
// prompt_zones.js: estructura de tags por zonas, composición y edición de prompt.

import {
  state,
  ZONE_ORDER,
  GENERAL_SUBCATS,
  GENERAL_SUBCAT_LABELS,
  GENERAL_SUBCAT_FALLBACK,
  PROMPT_TAGS_MAX,
} from "../state.js";
import { $, on, setStatus, writeClipboard } from "../dom.js";
import { postJson } from "../api.js";
import { openZoneInsert, seedZonePopoverSelection } from "./prompt_popover.js";

function normalizeTags(tags) {
  const merged = [];
  const seen = new Set();
  for (const raw of tags) {
    const tag = String(raw || "").trim();
    if (!tag) {
      continue;
    }
    const folded = tag.toLowerCase();
    if (seen.has(folded)) {
      continue;
    }
    seen.add(folded);
    merged.push(tag);
  }
  return merged;
}

function promptFromTags(tags) {
  return normalizeTags(tags).join(", ");
}

function promptTagsFromText(text) {
  return String(text || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function generalBucket(subcat) {
  const key = GENERAL_SUBCATS.includes(subcat) ? subcat : GENERAL_SUBCAT_FALLBACK;
  if (!Array.isArray(state.promptZones.general[key])) {
    state.promptZones.general[key] = [];
  }
  return state.promptZones.general[key];
}

function allPromptTagKeys() {
  const seen = new Set();
  for (const zone of ZONE_ORDER) {
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        for (const tag of state.promptZones.general[subcat] || []) {
          seen.add(String(tag).toLowerCase());
        }
      }
      continue;
    }
    for (const tag of state.promptZones[zone] || []) {
      seen.add(String(tag).toLowerCase());
    }
  }
  return seen;
}

function zoneScopeTags(zone, subcat) {
  if (!zone || !ZONE_ORDER.includes(zone)) {
    return [];
  }
  if (zone === "general") {
    return generalBucket(subcat);
  }
  return state.promptZones[zone] || [];
}


function composePrompt() {
  const merged = [];
  const seen = new Set();
  const push = (tags) => {
    for (const raw of tags || []) {
      const tag = String(raw == null ? "" : raw).trim();
      if (!tag) {
        continue;
      }
      const folded = tag.toLowerCase();
      if (seen.has(folded)) {
        continue;
      }
      seen.add(folded);
      merged.push(tag);
    }
  };
  for (const zone of ZONE_ORDER) {
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        push(state.promptZones.general[subcat]);
      }
      continue;
    }
    push(state.promptZones[zone]);
  }
  return merged.join(", ");
}

function collectPromptZoneTags() {
  const tags = [];
  const seen = new Set();
  const push = (raw) => {
    if (tags.length >= PROMPT_TAGS_MAX) {
      return;
    }
    const tag = String(raw == null ? "" : raw).trim();
    if (!tag) {
      return;
    }
    const folded = tag.toLowerCase();
    if (seen.has(folded)) {
      return;
    }
    seen.add(folded);
    tags.push(tag);
  };
  for (const zone of ZONE_ORDER) {
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        for (const tag of state.promptZones.general[subcat] || []) {
          push(tag);
        }
      }
      continue;
    }
    for (const tag of state.promptZones[zone] || []) {
      push(tag);
    }
  }
  return tags;
}

function resetPromptZones() {
  state.promptZones.quality = [];
  state.promptZones.safety = [];
  state.promptZones.subject = [];
  state.promptZones.character = [];
  state.promptZones.general = {};
  for (const subcat of GENERAL_SUBCATS) {
    state.promptZones.general[subcat] = [];
  }
}

function pushTagsToZone(zone, tags, subcat, seen) {
  const added = [];
  let target = null;
  if (zone === "general") {
    target = generalBucket(subcat);
  } else if (ZONE_ORDER.includes(zone)) {
    target = state.promptZones[zone];
  }
  if (!target) {
    return added;
  }
  for (const raw of tags || []) {
    const tag = String(raw == null ? "" : raw).trim();
    if (!tag) {
      continue;
    }
    const folded = tag.toLowerCase();
    if (seen.has(folded)) {
      continue;
    }
    seen.add(folded);
    target.push(tag);
    added.push(tag);
  }
  return added;
}

function addTagsToZone(zone, tags, subcat) {
  const added = pushTagsToZone(zone, tags, subcat, allPromptTagKeys());
  renderZoneEditor();
  return added;
}

function removeTagsFromZones(tags) {
  const folded = new Set(
    (tags || [])
      .map((tag) => String(tag == null ? "" : tag).trim().toLowerCase())
      .filter(Boolean)
  );
  if (!folded.size) {
    return;
  }
  for (const zone of ZONE_ORDER) {
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        state.promptZones.general[subcat] = (
          state.promptZones.general[subcat] || []
        ).filter((tag) => !folded.has(String(tag).toLowerCase()));
      }
      continue;
    }
    state.promptZones[zone] = (state.promptZones[zone] || []).filter(
      (tag) => !folded.has(String(tag).toLowerCase())
    );
  }
  renderZoneEditor();
}

function removeTagsFromZoneScope(zone, tags, subcat) {
  const folded = new Set(
    (tags || [])
      .map((tag) => String(tag == null ? "" : tag).trim().toLowerCase())
      .filter(Boolean)
  );
  if (!folded.size) {
    return;
  }
  if (zone === "general") {
    const key = GENERAL_SUBCATS.includes(subcat) ? subcat : GENERAL_SUBCAT_FALLBACK;
    state.promptZones.general[key] = (
      state.promptZones.general[key] || []
    ).filter((tag) => !folded.has(String(tag).toLowerCase()));
    return;
  }
  if (!ZONE_ORDER.includes(zone)) {
    return;
  }
  state.promptZones[zone] = (state.promptZones[zone] || []).filter(
    (tag) => !folded.has(String(tag).toLowerCase())
  );
}

function applyZonesPayload(zonesPayload, { replace = false } = {}) {
  if (replace) {
    resetPromptZones();
  }
  const seen = allPromptTagKeys();
  const added = [];
  for (const item of zonesPayload || []) {
    const zone = item && item.id;
    if (!ZONE_ORDER.includes(zone)) {
      continue;
    }
    if (zone === "general") {
      const subcats =
        Array.isArray(item.subcats) && item.subcats.length
          ? item.subcats
          : [{ id: GENERAL_SUBCAT_FALLBACK, tags: item.tags || [] }];
      for (const block of subcats) {
        added.push(
          ...pushTagsToZone("general", block.tags || [], block.id, seen)
        );
      }
      continue;
    }
    added.push(...pushTagsToZone(zone, item.tags || [], null, seen));
  }
  renderZoneEditor();
  return added;
}

async function mergeZonesText(text) {
  const data = await postJson("/api/prompt/zones", { text });
  return applyZonesPayload(data.zones || []);
}

function countZoneTags(zone) {
  if (zone === "general") {
    return GENERAL_SUBCATS.reduce(
      (total, subcat) => total + (state.promptZones.general[subcat] || []).length,
      0
    );
  }
  return (state.promptZones[zone] || []).length;
}

function updateGenerateState() {
  const button = $("btn-generate");
  if (!button) {
    return;
  }
  button.disabled = state.busy || !composePrompt();
}

function removeTagFromZone(zone, tag, subcat) {
  const folded = String(tag).toLowerCase();
  if (zone === "general") {
    const key = GENERAL_SUBCATS.includes(subcat) ? subcat : GENERAL_SUBCAT_FALLBACK;
    state.promptZones.general[key] = (
      state.promptZones.general[key] || []
    ).filter((item) => String(item).toLowerCase() !== folded);
  } else if (ZONE_ORDER.includes(zone)) {
    state.promptZones[zone] = (state.promptZones[zone] || []).filter(
      (item) => String(item).toLowerCase() !== folded
    );
  }
  renderZoneEditor();
}

function zoneTagsRow(zone, tags, subcat) {
  const row = document.createElement("div");
  row.className = "zone-editor-chips";
  for (const tag of tags || []) {
    const chip = document.createElement("span");
    chip.className = `zone-selected-chip zone-tag zone-${zone}`;
    const text = document.createElement("span");
    text.className = "zone-chip-text";
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "zone-selected-remove";
    remove.textContent = "×";
    remove.title = "Quitar";
    remove.addEventListener("click", () => removeTagFromZone(zone, tag, subcat));
    chip.append(text, remove);
    row.appendChild(chip);
  }
  return row;
}

function zoneAddButton(zone, subcat, label) {
  const add = document.createElement("button");
  add.type = "button";
  add.className = "zone-add";
  add.textContent = "＋";
  add.title = `Añadir a ${label}`;
  add.addEventListener("click", () => {
    openZoneInsert(zone, subcat, add).catch((error) =>
      setStatus(error.message, true)
    );
  });
  return add;
}

function zoneQuickRow(zone, subcat, label) {
  const row = document.createElement("form");
  row.className = "zone-quick";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "zone-quick-input";
  input.placeholder = "Tag(s) separados por comas…";
  input.setAttribute("aria-label", `Añadir tag a ${label}`);
  const insert = document.createElement("button");
  insert.type = "submit";
  insert.className = "zone-quick-add";
  insert.textContent = "Insertar";
  insert.title = `Añadir a ${label}`;
  row.append(input, insert);
  row.addEventListener("submit", (event) => {
    event.preventDefault();
    const tags = promptTagsFromText(input.value);
    if (!tags.length) {
      return;
    }
    const added = addTagsToZone(zone, tags, subcat);
    setStatus(
      added.length
        ? `${added.length} tag(s) añadido(s) a ${label}`
        : `Sin cambios en ${label}: ya estaba`
    );
  });
  return row;
}

function renderZoneEditor() {
  const container = $("zone-editor");
  if (!container) {
    return;
  }
  container.replaceChildren();
  for (const zone of ZONE_ORDER) {
    const label = ZONE_LABELS[zone] || zone;
    const block = document.createElement("section");
    block.className = `zone-block zone-block-${zone}`;
    const head = document.createElement("div");
    head.className = "zone-block-head";
    const title = document.createElement("strong");
    title.className = "zone-block-title";
    title.textContent = label;
    const count = document.createElement("span");
    count.className = "zone-block-count";
    count.textContent = String(countZoneTags(zone));
    head.append(title, count, zoneAddButton(zone, null, label));
    block.appendChild(head);
    if (zone === "general") {
      for (const subcat of GENERAL_SUBCATS) {
        const tags = state.promptZones.general[subcat] || [];
        const subLabel = GENERAL_SUBCAT_LABELS[subcat] || subcat;
        const subBlock = document.createElement("div");
        subBlock.className = "zone-subblock";
        const subHead = document.createElement("div");
        subHead.className = "zone-subblock-head";
        const subTitle = document.createElement("span");
        subTitle.textContent = subLabel;
        subHead.append(subTitle);
        subBlock.append(subHead);
        if (tags.length) {
          subBlock.appendChild(zoneTagsRow("general", tags, subcat));
        }
        subBlock.appendChild(zoneQuickRow("general", subcat, subLabel));
        block.appendChild(subBlock);
      }
    } else {
      block.appendChild(zoneTagsRow(zone, state.promptZones[zone] || [], null));
      block.appendChild(zoneQuickRow(zone, null, label));
    }
    container.appendChild(block);
  }
  const finalArea = $("prompt-final");
  if (finalArea) {
    finalArea.value = composePrompt();
  }
  updateGenerateState();
}

async function copyFinalPrompt() {
  const text = composePrompt();
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = $("prompt-final");
      area.focus();
      area.select();
      document.execCommand("copy");
    }
    setStatus("Prompt copiado");
  } catch (error) {
    setStatus(error.message, true);
  }
}


function initPromptZones() {
  on("btn-copy-prompt", "click", copyFinalPrompt);
}

export {
  normalizeTags,
  promptFromTags,
  promptTagsFromText,
  generalBucket,
  allPromptTagKeys,
  zoneScopeTags,
  seedZonePopoverSelection,
  composePrompt,
  collectPromptZoneTags,
  resetPromptZones,
  pushTagsToZone,
  addTagsToZone,
  removeTagsFromZones,
  removeTagsFromZoneScope,
  applyZonesPayload,
  mergeZonesText,
  countZoneTags,
  updateGenerateState,
  removeTagFromZone,
  zoneTagsRow,
  zoneAddButton,
  zoneQuickRow,
  renderZoneEditor,
  copyFinalPrompt,
  initPromptZones,
};
