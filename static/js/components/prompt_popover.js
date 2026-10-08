// WaifuStudio — Popover de Inserción de Tags y Catálogo
// Qué hace: búsqueda en catálogo de tags, sugerencias por grupo y selección rápida.
// Qué no hace: no modifica directamente los campos de texto ni genera imágenes.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import {
  state,
  GROUP_LABELS,
  ZONE_ORDER,
  GENERAL_SUBCATS,
  GENERAL_SUBCAT_LABELS,
  GENERAL_SUBCAT_FALLBACK,
} from "../state.js";
import { $, on, setStatus } from "../dom.js";
import { api } from "../api.js";
import {
  allPromptTagKeys,
  addTagsToZone,
  renderZoneEditor,
  normalizeTags,
  promptTagsFromText,
  zoneScopeTags,
  composePrompt,
  mergeZonesText,
  pushTagsToZone,
  removeTagsFromZoneScope,
  removeTagsFromZones,
} from "./prompt_zones.js";
import { loadCharacters } from "./oc_picker.js";
import { setLoraSelected } from "./loras.js";
import { updateReferencePreview } from "../tabs/image.js";

let zoneInsertTarget = null;
let zonePopoverOptions = null;
let zonePopoverSubcat = null;
let zonePopoverOriginSubcat = null;
let zonePopoverSelected = new Map();
let zonePopoverSeq = 0;
let zonePopoverAnchor = null;
let zoneCatalogSearchSeq = 0;
let zoneOcApplied = [];
let zoneOcCharacter = null;

function seedZonePopoverSelection(zone, subcat) {
  zonePopoverSelected = new Map();
  for (const raw of zoneScopeTags(zone, subcat)) {
    const tag = String(raw == null ? "" : raw);
    const folded = tag.toLowerCase();
    if (folded) {
      zonePopoverSelected.set(folded, tag);
    }
  }
}

function selectLora(loraId, weight) {
  return setLoraSelected(loraId, true, weight);
}

async function fetchCharacterProfile(character, mode) {
  const query = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return api(`/api/characters/${character.id}/profile${query}`);
}

function zoneSubcatLocked(subcat) {
  return subcat === "rasgos" && Boolean(state.activeCharacterId);
}

function zonePopoverGroup() {
  if (!zonePopoverOptions) {
    return null;
  }
  if (zoneInsertTarget === "general") {
    return (
      zonePopoverOptions.find((group) => group.id === zonePopoverSubcat) || null
    );
  }
  return zonePopoverOptions[0] || null;
}

function defaultGeneralSubcat() {
  const ids = zonePopoverOptions.map((group) => group.id);
  if (!state.activeCharacterId && ids.includes("rasgos")) {
    return "rasgos";
  }
  const other = ids.find((id) => id !== "rasgos");
  return other || ids[0] || null;
}

function renderZonePopoverTabs() {
  const container = $("zone-popover-tabs");
  container.replaceChildren();
  if (zoneInsertTarget !== "general") {
    return;
  }
  for (const group of zonePopoverOptions || []) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "zone-tab";
    tab.textContent = group.label;
    const locked = zoneSubcatLocked(group.id);
    tab.classList.toggle("active", group.id === zonePopoverSubcat);
    tab.classList.toggle("locked", locked);
    tab.disabled = locked;
    tab.title = locked ? "Fijado por el OC" : group.label;
    if (!locked) {
      tab.addEventListener("click", () => {
        zonePopoverSubcat = group.id;
        renderZonePopoverTabs();
        renderZonePopoverGroups();
      });
    }
    container.appendChild(tab);
  }
}

function makeZoneOptionRow(item) {
  const row = document.createElement("label");
  row.className = "zone-option";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = zonePopoverSelected.has(item.tag.toLowerCase());
  box.addEventListener("change", () => {
    const folded = item.tag.toLowerCase();
    if (box.checked) {
      zonePopoverSelected.set(folded, item.tag);
    } else {
      zonePopoverSelected.delete(folded);
    }
    renderZonePopoverSelected();
  });
  const text = document.createElement("span");
  text.className = "zone-option-text";
  text.textContent = item.tag;
  const label = document.createElement("span");
  label.className = "zone-option-label";
  label.textContent = item.label || item.tag;
  row.append(box, text, label);
  return row;
}

function renderZonePopoverGroups() {
  const container = $("zone-popover-groups");
  const note = $("zone-popover-note");
  container.replaceChildren();
  const rawQuery = $("zone-popover-search").value.trim();
  const lockedNote =
    zoneInsertTarget === "general" && Boolean(state.activeCharacterId);
  note.classList.toggle("hidden", !lockedNote);
  if (lockedNote) {
    note.textContent =
      "Rasgos fijados por el OC activo (Fijado por el OC): no se editan aquí.";
  }
  const group = zonePopoverGroup();
  if (!group) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent =
      zoneInsertTarget === "character"
        ? "Elige un OC en «Mis OCs» o añade el tag a mano."
        : "Sin opciones.";
    container.appendChild(empty);
    if (rawQuery.length >= 2) {
      renderZoneCatalogSearch(rawQuery, container, new Set());
    }
    return;
  }
  const query = rawQuery.toLowerCase();
  const tags = (group.tags || []).filter(
    (item) =>
      !query ||
      item.tag.toLowerCase().includes(query) ||
      String(item.label || "").toLowerCase().includes(query)
  );
  if (!tags.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin resultados.";
    container.appendChild(empty);
    if (rawQuery.length >= 2) {
      renderZoneCatalogSearch(rawQuery, container, new Set());
    }
    return;
  }
  const shownTags = new Set();
  for (const item of tags) {
    container.appendChild(makeZoneOptionRow(item));
    shownTags.add(item.tag.toLowerCase());
  }
  if (rawQuery.length >= 2) {
    renderZoneCatalogSearch(rawQuery, container, shownTags);
  }
}

async function renderZoneCatalogSearch(rawQuery, container, shownTags) {
  const seq = ++zoneCatalogSearchSeq;
  let items = [];
  try {
    const data = await api(
      `/api/tags?q=${encodeURIComponent(rawQuery)}&limit=60`
    );
    items = (data && data.items) || [];
  } catch (_error) {
    return;
  }
  if (
    seq !== zoneCatalogSearchSeq ||
    $("zone-popover").classList.contains("hidden") ||
    $("zone-popover-search").value.trim() !== rawQuery
  ) {
    return;
  }
  const results = items.filter(
    (item) => !shownTags.has(String(item.tag || "").toLowerCase())
  );
  if (!results.length) {
    return;
  }
  const title = document.createElement("p");
  title.className = "zone-catalog-title";
  title.textContent = `Catálogo completo (${results.length})`;
  container.appendChild(title);
  for (const item of results) {
    container.appendChild(makeZoneOptionRow(item));
  }
}

function renderZonePopoverSelected() {
  const container = $("zone-popover-selected");
  container.replaceChildren();
  if (!zonePopoverSelected.size) {
    const empty = document.createElement("span");
    empty.className = "empty";
    empty.textContent = "Sin selección.";
    container.appendChild(empty);
    return;
  }
  const count = document.createElement("span");
  count.className = "zone-popover-count";
  count.textContent = `${zonePopoverSelected.size} seleccionada${
    zonePopoverSelected.size === 1 ? "" : "s"
  }`;
  container.appendChild(count);
  for (const tag of zonePopoverSelected.values()) {
    const chip = document.createElement("span");
    chip.className = "zone-selected-chip";
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "zone-selected-remove";
    remove.textContent = "×";
    remove.title = "Quitar";
    remove.addEventListener("click", () => {
      zonePopoverSelected.delete(String(tag).toLowerCase());
      renderZonePopoverSelected();
      renderZonePopoverGroups();
    });
    chip.append(text, remove);
    container.appendChild(chip);
  }
}

function setZoneOcStatus(text, isError = false) {
  const el = $("zone-ocs-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function renderZoneOcList() {
  const container = $("zone-ocs-list");
  container.replaceChildren();
  if (!state.characters.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin OCs guardados.";
    container.appendChild(empty);
    return;
  }
  for (const character of state.characters) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "zone-oc";
    button.textContent = character.name;
    button.title = (character.tags || []).join(", ") || "sin rasgos";
    button.addEventListener("click", () => {
      applyOcFromPicker(character).catch((error) =>
        setZoneOcStatus(error.message, true)
      );
    });
    container.appendChild(button);
  }
}

async function applyOcFromPicker(character) {
  const mode = $("zone-ocs-traits").checked ? "traits" : "auto";
  const profile = await fetchCharacterProfile(character, mode);
  removeTagsFromZones(zoneOcApplied);
  if (zoneInsertTarget === "character") {
    for (const tag of zoneOcApplied) {
      zonePopoverSelected.delete(String(tag).toLowerCase());
    }
  }
  zoneOcApplied = addTagsToZone(
    "character",
    promptTagsFromText(profile.text)
  );
  if (zoneInsertTarget === "character") {
    for (const tag of zoneOcApplied) {
      zonePopoverSelected.set(String(tag).toLowerCase(), tag);
    }
    renderZonePopoverSelected();
    renderZonePopoverGroups();
  }
  zoneOcCharacter = character;
  const notes = [`modo ${profile.mode}`];
  if (profile.lora) {
    $("zone-ocs-traits-label").classList.remove("hidden");
    const selected = selectLora(profile.lora.id, profile.lora.default_weight);
    notes.push(
      selected
        ? `LoRA ${profile.lora.id} @ ${profile.lora.default_weight} seleccionado`
        : `LoRA ${profile.lora.id} fuera del panel (familia activa)`
    );
  } else {
    $("zone-ocs-traits-label").classList.add("hidden");
    $("zone-ocs-traits").checked = false;
  }
  if ($("zone-ocs-extras").checked && (profile.extras || []).length) {
    const extraAdded = await mergeZonesText(profile.extras.join(", "));
    zoneOcApplied = zoneOcApplied.concat(extraAdded);
    notes.push(`extras a General: ${profile.extras.join(", ")}`);
  }
  setZoneOcStatus(`OC «${character.name}» aplicado · ${notes.join(" · ")}`);
  setStatus(`OC «${character.name}» aplicado a la zona Personaje`);
}

function positionZonePopover() {
  const popover = $("zone-popover");
  if (
    !popover ||
    popover.classList.contains("hidden") ||
    !zonePopoverAnchor ||
    !zonePopoverAnchor.isConnected
  ) {
    return;
  }
  const rect = zonePopoverAnchor.getBoundingClientRect();
  const margin = 8;
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  let left = rect.left;
  let top = rect.bottom + 6;
  if (top + height > window.innerHeight - margin) {
    top = rect.top - height - 6;
  }
  left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
  top = Math.max(margin, Math.min(top, window.innerHeight - height - margin));
  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;
}

async function openZoneInsert(zone, subcat, anchor = null) {
  if (!ZONE_LABELS[zone]) {
    return;
  }
  zoneInsertTarget = zone;
  zonePopoverAnchor = anchor || null;
  zonePopoverOptions = null;
  zonePopoverSubcat = null;
  zonePopoverOriginSubcat = zone === "general" ? subcat || null : null;
  zonePopoverSelected = new Map();
  if (zone !== "general") {
    seedZonePopoverSelection(zone, null);
  }
  zoneOcApplied = [];
  zoneOcCharacter = null;
  const isCharacter = zone === "character";
  $("zone-popover-ocs").classList.toggle("hidden", !isCharacter);
  $("zone-ocs-extras").checked = true;
  $("zone-ocs-traits").checked = false;
  $("zone-ocs-traits-label").classList.add("hidden");
  setZoneOcStatus("");
  if (isCharacter) {
    renderZoneOcList();
    loadCharacters()
      .then(renderZoneOcList)
      .catch((error) => setZoneOcStatus(error.message, true));
  }
  $("zone-popover").classList.remove("hidden");
  $("zone-popover-title").textContent = ZONE_LABELS[zone];
  $("zone-popover-search").value = "";
  $("zone-popover-note").classList.add("hidden");
  $("zone-insert-input").value = "";
  $("zone-popover-tabs").replaceChildren();
  $("zone-popover-groups").replaceChildren();
  renderZonePopoverSelected();
  positionZonePopover();
  const seq = ++zonePopoverSeq;
  try {
    const data = await api(
      `/api/prompt/options?zone=${encodeURIComponent(zone)}`
    );
    if (seq !== zonePopoverSeq || zoneInsertTarget !== zone) {
      return;
    }
    zonePopoverOptions = data.subgroups || [];
    if (zone === "general") {
      const wanted = zoneSubcatLocked(subcat) ? null : subcat;
      zonePopoverSubcat = zonePopoverOptions.some(
        (group) => group.id === wanted
      )
        ? wanted
        : defaultGeneralSubcat();
      if (
        zonePopoverOriginSubcat &&
        (zoneSubcatLocked(zonePopoverOriginSubcat) ||
          !zonePopoverOptions.some(
            (group) => group.id === zonePopoverOriginSubcat
          ))
      ) {
        zonePopoverOriginSubcat = null;
      }
      seedZonePopoverSelection(zone, zonePopoverSubcat);
      renderZonePopoverSelected();
    }
    renderZonePopoverTabs();
    renderZonePopoverGroups();
    positionZonePopover();
  } catch (error) {
    if (seq === zonePopoverSeq) {
      setStatus(error.message, true);
    }
  }
}

function closeZoneInsert() {
  zoneInsertTarget = null;
  zonePopoverAnchor = null;
  zonePopoverOptions = null;
  zonePopoverSubcat = null;
  zonePopoverOriginSubcat = null;
  zonePopoverSelected = new Map();
  zoneOcApplied = [];
  zoneOcCharacter = null;
  zoneCatalogSearchSeq += 1;
  $("zone-popover").classList.add("hidden");
  $("zone-popover-search").value = "";
  $("zone-popover-tabs").replaceChildren();
  $("zone-popover-groups").replaceChildren();
  $("zone-popover-selected").replaceChildren();
  $("zone-popover-note").classList.add("hidden");
  $("zone-popover-ocs").classList.add("hidden");
  setZoneOcStatus("");
  $("zone-insert-input").value = "";
}

function submitZoneInsert(event) {
  event.preventDefault();
  const input = $("zone-insert-input");
  const raw = input.value.trim();
  if (!raw || !zoneInsertTarget) {
    return;
  }
  for (const part of raw.split(",")) {
    const tag = part.trim();
    if (tag) {
      zonePopoverSelected.set(tag.toLowerCase(), tag);
    }
  }
  input.value = "";
  renderZonePopoverSelected();
  renderZonePopoverGroups();
}

function clearZoneSelection() {
  zonePopoverSelected = new Map();
  renderZonePopoverSelected();
  renderZonePopoverGroups();
}

async function insertZoneSelection() {
  const zone = zoneInsertTarget;
  if (!zone) {
    return;
  }
  const selected = Array.from(zonePopoverSelected.values());
  if (zone === "general" && !zonePopoverOriginSubcat) {
    if (!selected.length) {
      setStatus("Selecciona o añade algún tag antes de insertar", true);
      return;
    }
    const added = await mergeZonesText(selected.join(", "));
    closeZoneInsert();
    setStatus(
      added.length
        ? `Insertar: ${added.length} añadido(s)`
        : "Insertar: sin cambios (ya estaban)"
    );
    return;
  }
  const subcat =
    zone === "general"
      ? zonePopoverOriginSubcat || zonePopoverSubcat || GENERAL_SUBCAT_FALLBACK
      : null;
  const selectedFolded = new Set(selected.map((tag) => tag.toLowerCase()));
  const removals = zoneScopeTags(zone, subcat).filter(
    (tag) => !selectedFolded.has(String(tag).toLowerCase())
  );
  const known = allPromptTagKeys();
  const additions = selected.filter(
    (tag) => !known.has(String(tag).toLowerCase())
  );
  if (!additions.length && !removals.length) {
    setStatus("Selecciona o añade algún tag antes de insertar", true);
    return;
  }
  removeTagsFromZoneScope(zone, removals, subcat);
  const added = pushTagsToZone(zone, additions, subcat, allPromptTagKeys());
  renderZoneEditor();
  composePrompt();
  closeZoneInsert();
  const parts = [];
  if (added.length) {
    parts.push(`${added.length} añadido(s)`);
  }
  if (removals.length) {
    parts.push(`${removals.length} quitado(s)`);
  }
  setStatus(`Insertar: ${parts.join(" · ")}`);
}

async function attachReferenceFromUrl(url, name) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`No se pudo cargar la referencia (HTTP ${response.status})`);
  }
  const blob = await response.blob();
  const file = new File([blob], name || "reference.png", {
    type: blob.type || "image/png",
  });
  const transfer = new DataTransfer();
  transfer.items.add(file);
  $("ref-image").files = transfer.files;
  updateReferencePreview();
}


function initPromptPopover() {
  document.addEventListener("scroll", positionZonePopover, true);
  window.addEventListener("resize", positionZonePopover);
  on("zone-insert-form", "submit", submitZoneInsert);
  on("zone-insert-cancel", "click", closeZoneInsert);
  on("zone-popover-close", "click", closeZoneInsert);
  on("zone-popover-search", "input", renderZonePopoverGroups);
  on("zone-popover-insert", "click", () => {
    insertZoneSelection().catch((error) => setStatus(error.message, true));
  });
  on("zone-popover-clear", "click", clearZoneSelection);
  for (const id of ["zone-ocs-extras", "zone-ocs-traits"]) {
    on(id, "change", () => {
      if (zoneOcCharacter) {
        applyOcFromPicker(zoneOcCharacter).catch((error) =>
          setZoneOcStatus(error.message, true)
        );
      }
    });
  }
}

export {
  seedZonePopoverSelection,
  selectLora,
  fetchCharacterProfile,
  zoneSubcatLocked,
  zonePopoverGroup,
  defaultGeneralSubcat,
  renderZonePopoverTabs,
  makeZoneOptionRow,
  renderZonePopoverGroups,
  renderZoneCatalogSearch,
  renderZonePopoverSelected,
  setZoneOcStatus,
  renderZoneOcList,
  applyOcFromPicker,
  positionZonePopover,
  openZoneInsert,
  closeZoneInsert,
  submitZoneInsert,
  clearZoneSelection,
  insertZoneSelection,
  attachReferenceFromUrl,
  initPromptPopover,
};
