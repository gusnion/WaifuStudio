// WaifuStudio  ESelector y Modal de OCs (Original Characters)
// Qué hace: creación, edición, catálogo de rasgos y persistencia de personajes.
// Qué no hace: no ejecuta entrenamientos ni renderiza hojas de contacto (sheets).
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import { state, GROUP_LABELS, OC_TRAIT_GROUPS } from "../state.js";
import { $, on, setStatus, setSelectValue, readFileBase64, option, showUiBanner } from "../dom.js";
import { api, postJson, putJson, pollJob } from "../api.js";
import {
  addTagsToZone,
  renderZoneEditor,
  normalizeTags,
  composePrompt,
  pushTagsToZone,
  promptFromTags,
  promptTagsFromText,
  mergeZonesText,
} from "./prompt_zones.js";
import { fetchCharacterProfile } from "./prompt_popover.js";
import { openLightbox } from "./lightbox.js";
import { openTrainModal } from "./oc_train.js";
import { runMultiviewGeneration, renderSheet } from "./editor_multiview.js";
import { selectLora } from "./loras.js";
import { clearReference, refreshNegative } from "../tabs/image.js";
import { openPoseLibrary, initPoseLibrary, getSelectedPose } from "./pose_library.js";
import { t } from "../i18n.js";

let ocSearchTimer = null;
let ocConfirmResolver = null;
let ocCreating = false;
let ocSaveTagsTimer = null;

function showOcConfirmModal({
  title = "Confirmar",
  message = "¿Estás seguro de realizar esta acción?",
  confirmText = "Confirmar",
  cancelText = "Cancelar",
  isDanger = false,
} = {}) {
  return new Promise((resolve) => {
    ocConfirmResolver = resolve;
    const modal = $("oc-confirm-modal");
    if (!modal) {
      resolve(false);
      return;
    }
    const titleEl = $("oc-confirm-title");
    if (titleEl) {
      titleEl.textContent = title;
    }
    const msgEl = $("oc-confirm-message");
    if (msgEl) {
      msgEl.textContent = message;
    }
    const btnAccept = $("btn-oc-confirm-accept");
    if (btnAccept) {
      btnAccept.textContent = confirmText;
      btnAccept.classList.toggle("danger", Boolean(isDanger));
      btnAccept.classList.toggle("primary", !isDanger);
    }
    const btnCancel = $("btn-oc-confirm-cancel");
    if (btnCancel) {
      btnCancel.textContent = cancelText;
    }
    modal.classList.remove("hidden");
  });
}

function closeOcConfirmModal(result = false) {
  const modal = $("oc-confirm-modal");
  if (modal) {
    modal.classList.add("hidden");
  }
  if (ocConfirmResolver) {
    const resolve = ocConfirmResolver;
    ocConfirmResolver = null;
    resolve(Boolean(result));
  }
}

function handleConfirmAccept() {
  closeOcConfirmModal(true);
}

function handleConfirmCancel() {
  closeOcConfirmModal(false);
}

function setOcStatus(text, isError = false) {
  const el = $("oc-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function setOcSaveStatus(text, isError = false) {
  const el = $("oc-save-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}


function refFilename(ref) {
  const source = String((ref && (ref.url || ref.relpath)) || "");
  return source.split("/").pop() || "reference.png";
}

function isSheetRef(ref) {
  if (ref && ref.is_sheet === true) {
    return true;
  }
  return refFilename(ref).startsWith("sheet_");
}

const OC_CATEGORY_ICONS = {
  hair: "💇",
  eyes: "👁️",
  face: "✨",
  body: "👤",
  other: "🏷️",
};

const OC_CATEGORY_TITLES = {
  hair: "Pelo",
  eyes: "Ojos",
  face: "Cara",
  body: "Cuerpo",
  other: "Otros rasgos",
};

const KNOWN_TRAIT_GROUPS = {
  "long hair": "hair", "short hair": "hair", "twintails": "hair", "ponytail": "hair",
  "side ponytail": "hair", "bob cut": "hair", "braid": "hair", "hime cut": "hair",
  "drill hair": "hair", "ahoge": "hair",
  "heterochromia": "eyes", "red eyes": "eyes", "blue eyes": "eyes", "green eyes": "eyes",
  "purple eyes": "eyes", "yellow eyes": "eyes", "closed eyes": "eyes", "tsurime": "eyes", "tareme": "eyes",
  "freckles": "face", "mole under eye": "face", "blush": "face", "pointy ears": "face",
  "fang": "face", "sharp teeth": "face", "pale skin": "face", "dark skin": "face",
  "large breasts": "body", "medium breasts": "body", "small breasts": "body",
  "wide hips": "body", "thick thighs": "body", "muscular": "body", "chubby": "body",
  "abs": "body", "flat chest": "body",
};

const tagCategoryCache = new Map();

function getOcTagGroup(tag) {
  const folded = String(tag || "").toLowerCase().trim();
  if (tagCategoryCache.has(folded)) {
    return tagCategoryCache.get(folded);
  }
  if (KNOWN_TRAIT_GROUPS[folded]) {
    return KNOWN_TRAIT_GROUPS[folded];
  }
  if (folded.includes("hair") || folded.includes("bangs") || folded.includes("ponytail") || folded.includes("braid")) {
    return "hair";
  }
  if (folded.includes("eye") || folded.includes("pupil")) {
    return "eyes";
  }
  if (folded.includes("skin") || folded.includes("ear") || folded.includes("fang") || folded.includes("face") || folded.includes("freckle") || folded.includes("mole")) {
    return "face";
  }
  if (folded.includes("breast") || folded.includes("body") || folded.includes("thigh") || folded.includes("hip") || folded.includes("waist") || folded.includes("chest")) {
    return "body";
  }
  return "other";
}

function isOcTagSelected(tag) {
  const folded = tag.toLowerCase();
  return state.ocSelectedTags.some((item) => item.toLowerCase() === folded);
}

function renderOcCatalogResults() {
  const container = $("oc-catalog-results");
  if (!container) return;
  container.replaceChildren();
  if (!state.ocCatalogItems || !state.ocCatalogItems.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin resultados.";
    container.appendChild(empty);
    return;
  }

  const groupFilter = $("oc-catalog-group") ? $("oc-catalog-group").value : "";
  const activeGroups = groupFilter ? [groupFilter] : OC_TRAIT_GROUPS;

  const grouped = new Map();
  for (const g of activeGroups) {
    grouped.set(g, []);
  }

  for (const item of state.ocCatalogItems) {
    const g = item.group || groupFilter || getOcTagGroup(item.tag) || "hair";
    if (grouped.has(g)) {
      grouped.get(g).push(item);
    } else {
      grouped.set(g, [item]);
    }
  }

  let renderedAny = false;

  for (const [groupKey, items] of grouped.entries()) {
    if (!items.length) continue;
    renderedAny = true;

    const card = document.createElement("div");
    card.className = "oc-category-card";
    card.dataset.category = groupKey;

    const header = document.createElement("div");
    header.className = "oc-category-header";

    const titleBox = document.createElement("div");
    titleBox.className = "oc-category-title-box";

    const icon = document.createElement("span");
    icon.className = "oc-category-icon";
    icon.textContent = OC_CATEGORY_ICONS[groupKey] || "🏷️";

    const title = document.createElement("h4");
    title.className = "oc-category-title";
    title.textContent = GROUP_LABELS[groupKey] || OC_CATEGORY_TITLES[groupKey] || groupKey;

    titleBox.append(icon, title);

    const countSelected = items.filter((it) => isOcTagSelected(it.tag)).length;
    const badge = document.createElement("span");
    badge.className = "oc-category-badge";
    if (countSelected > 0) {
      badge.classList.add("has-selected");
      badge.textContent = `${countSelected} sel. / ${items.length}`;
    } else {
      badge.textContent = `${items.length}`;
    }

    header.append(titleBox, badge);
    card.appendChild(header);

    const grid = document.createElement("div");
    grid.className = "oc-trait-grid";

    for (const item of items) {
      const isSelected = isOcTagSelected(item.tag);
      const traitCard = document.createElement("button");
      traitCard.type = "button";
      traitCard.className = "oc-trait-card oc-chip" + (isSelected ? " selected" : "");
      traitCard.title = item.tag;

      const check = document.createElement("span");
      check.className = "oc-trait-check";
      check.textContent = isSelected ? "✓" : "+";

      const info = document.createElement("div");
      info.className = "oc-trait-info";

      const label = document.createElement("span");
      label.className = "oc-trait-label";
      label.textContent = item.label || item.tag;
      info.appendChild(label);

      if (item.label && item.label.toLowerCase() !== item.tag.toLowerCase()) {
        const subtag = document.createElement("span");
        subtag.className = "oc-trait-subtag";
        subtag.textContent = item.tag;
        info.appendChild(subtag);
      }

      traitCard.append(check, info);
      traitCard.addEventListener("click", () => toggleOcTag(item.tag));
      grid.appendChild(traitCard);
    }

    card.appendChild(grid);
    container.appendChild(card);
  }

  if (!renderedAny) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin resultados para el filtro actual.";
    container.appendChild(empty);
  }
}

function renderOcSelected() {
  const container = $("oc-selected");
  if (!container) return;
  container.replaceChildren();
  if (!state.ocSelectedTags || !state.ocSelectedTags.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Ningún tag seleccionado.";
    container.appendChild(empty);
    return;
  }

  const grouped = new Map();
  for (const g of [...OC_TRAIT_GROUPS, "other"]) {
    grouped.set(g, []);
  }

  for (const tag of state.ocSelectedTags) {
    const g = getOcTagGroup(tag);
    if (grouped.has(g)) {
      grouped.get(g).push(tag);
    } else {
      grouped.get("other").push(tag);
    }
  }

  for (const [groupKey, tags] of grouped.entries()) {
    if (!tags.length) continue;

    const groupCard = document.createElement("div");
    groupCard.className = "oc-selected-group";
    groupCard.dataset.category = groupKey;

    const groupTitle = document.createElement("div");
    groupTitle.className = "oc-selected-group-title";

    const icon = document.createElement("span");
    icon.textContent = OC_CATEGORY_ICONS[groupKey] || "🏷️";

    const label = document.createElement("span");
    label.textContent = `${GROUP_LABELS[groupKey] || OC_CATEGORY_TITLES[groupKey] || "Otros"} (${tags.length})`;

    groupTitle.append(icon, label);
    groupCard.appendChild(groupTitle);

    const row = document.createElement("div");
    row.className = "oc-selected-cards-row";

    for (const tag of tags) {
      const card = document.createElement("div");
      card.className = "oc-selected-card oc-selected-chip";

      const text = document.createElement("span");
      text.className = "oc-selected-card-tag";
      text.textContent = tag;

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "oc-selected-card-remove";
      remove.textContent = "✕";
      remove.title = `Quitar ${tag}`;
      remove.setAttribute("aria-label", `Quitar ${tag}`);
      remove.addEventListener("click", () => toggleOcTag(tag));

      card.append(text, remove);
      row.appendChild(card);
    }

    groupCard.appendChild(row);
    container.appendChild(groupCard);
  }
}

function renderOcExtras() {
  const box = $("oc-extras-box");
  const container = $("oc-extras");
  container.replaceChildren();
  box.classList.toggle("hidden", !state.ocExtras.length);
  for (const tag of state.ocExtras) {
    const chip = document.createElement("span");
    chip.className = "oc-selected-chip";
    const text = document.createElement("span");
    text.textContent = tag;
    chip.appendChild(text);
    container.appendChild(chip);
  }
}

async function moveOcExtrasToGeneral() {
  const extras = state.ocExtras.slice();
  if (!extras.length) {
    return;
  }
  const added = await mergeZonesText(extras.join(", "));
  let removed = false;
  if (state.ocEditingId != null) {
    const confirmed = await showOcConfirmModal({
      title: "Mover extras a General",
      message: `Extras insertados en General${
        added.length ? "" : " (ya estaban en el prompt)"
      }. ¿Quitarlos también del OC?`,
      confirmText: "Confirmar",
      cancelText: "Cancelar",
    });
    if (confirmed) {
      await api(`/api/characters/${state.ocEditingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ extras: [] }),
      });
      state.ocExtras = [];
      renderOcExtras();
      await loadCharacters();
      removed = true;
    }
  }
  setOcStatus(
    removed
      ? "Extras movidos a General y quitados del OC"
      : "Extras insertados en General (siguen en el OC)"
  );
}

async function refreshOcCatalog() {
  const group = $("oc-catalog-group").value;
  const query = $("oc-catalog-search").value.trim();
  let items = [];
  if (group) {
    const params = new URLSearchParams();
    params.set("group", group);
    if (query) {
      params.set("q", query);
    }
    const data = await api(`/api/tags?${params.toString()}`);
    items = (data.items || []).map((item) => ({
      ...item,
      group: item.group || group,
    }));
  } else {
    const results = await Promise.all(
      OC_TRAIT_GROUPS.map(async (name) => {
        const data = await api(`/api/tags?group=${encodeURIComponent(name)}`);
        return (data.items || []).map((item) => ({
          ...item,
          group: item.group || name,
        }));
      })
    );
    items = results.flat();
    if (query) {
      const needle = query.toLowerCase();
      items = items.filter(
        (item) =>
          item.tag.toLowerCase().includes(needle) ||
          String(item.label || "").toLowerCase().includes(needle)
      );
    }
  }
  for (const item of items) {
    if (item && item.tag && item.group) {
      tagCategoryCache.set(item.tag.toLowerCase(), item.group);
    }
  }
  state.ocCatalogItems = items;
  renderOcCatalogResults();
}

async function loadOcCatalog() {
  const data = await api("/api/tags/groups");
  const select = $("oc-catalog-group");
  select.replaceChildren();
  select.appendChild(option("", "Todos los rasgos"));
  for (const group of data.groups || []) {
    if (!OC_TRAIT_GROUPS.includes(group)) {
      continue;
    }
    select.appendChild(option(group, GROUP_LABELS[group] || group));
  }
  await refreshOcCatalog();
}

async function loadOcPreprompts() {
  const family = state.family === "sdxl" ? "anima" : (state.family || "anima");
  const data = await api(`/api/preprompts?family=${encodeURIComponent(family)}`);
  const custom = new Set(data.custom || []);
  const select = $("oc-form-preprompt");
  if (!select) return;
  select.replaceChildren();
  for (const name of data.names || []) {
    select.appendChild(option(name, custom.has(name) ? `${name} (propio)` : name));
  }
  state.ocPrepromptDefault = data.default || "";
  select.value = data.default || select.value;
}


function renderOcCreateSelected() {
  const container = $("oc-create-selected");
  if (!container) return;
  container.replaceChildren();
  if (!state.ocSelectedTags?.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Ningún rasgo seleccionado.";
    container.appendChild(empty);
    return;
  }
  for (const tag of state.ocSelectedTags) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "oc-chip selected";
    chip.textContent = `${tag} ×`;
    chip.title = "Quitar";
    chip.addEventListener("click", () => toggleOcTag(tag));
    container.appendChild(chip);
  }
}

function renderOcCreateTraits() {
  const container = $("oc-create-traits");
  const select = $("oc-create-group");
  if (!container) return;
  const group = select?.value || "hair";
  const items = (state.ocCatalogItems || []).filter(
    (item) => (item.group || getOcTagGroup(item.tag)) === group
  );
  container.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin rasgos en este grupo.";
    container.appendChild(empty);
    return;
  }
  for (const item of items) {
    const selected = isOcTagSelected(item.tag);
    const button = document.createElement("button");
    button.type = "button";
    button.className = `oc-trait-card oc-chip${selected ? " selected" : ""}`;
    button.title = item.tag;
    const check = document.createElement("span");
    check.className = "oc-trait-check";
    check.textContent = selected ? "✓" : "+";
    const info = document.createElement("span");
    info.className = "oc-trait-info";
    const label = document.createElement("span");
    label.className = "oc-trait-label";
    label.textContent = item.label || item.tag;
    info.appendChild(label);
    if (item.label && item.label.toLowerCase() !== item.tag.toLowerCase()) {
      const sub = document.createElement("span");
      sub.className = "oc-trait-subtag";
      sub.textContent = item.tag;
      info.appendChild(sub);
    }
    button.append(check, info);
    button.addEventListener("click", () => toggleOcTag(item.tag));
    container.appendChild(button);
  }
}

function renderOcCreateModal() {
  renderOcCreateTraits();
  renderOcCreateSelected();
}

function openOcCreateModal() {
  const modal = $("oc-create-modal");
  if (!modal) return;
  ocCreating = true;
  state.ocSelectedTags = [];
  state.ocExtras = [];
  const name = $("oc-create-name");
  if (name) name.value = "";
  const select = $("oc-create-group");
  if (select && !select.options.length) {
    for (const group of OC_TRAIT_GROUPS) {
      select.appendChild(option(group, GROUP_LABELS[group] || group));
    }
  }
  renderOcCreateModal();
  modal.classList.remove("hidden");
  name?.focus();
}

function closeOcCreateModal(restore = true) {
  ocCreating = false;
  $("oc-create-modal")?.classList.add("hidden");
  if (restore) {
    const character = characterById(state.activeCharacterId);
    state.ocSelectedTags = [...(character?.tags || [])];
    state.ocExtras = [...(character?.extras || [])];
    renderOcSelected();
    renderOcCatalogResults();
  }
}

function openOcGenerateModal() {
  openOcCreateModal();
  const groups = [...OC_TRAIT_GROUPS];
  const picked = [];
  for (const group of groups) {
    const items = (state.ocCatalogItems || []).filter(
      (item) => (item.group || getOcTagGroup(item.tag)) === group
    );
    if (!items.length) continue;
    picked.push(items[Math.floor(Math.random() * items.length)].tag);
  }
  state.ocSelectedTags = [...new Set(picked)];
  renderOcCreateModal();
  const status = $("oc-create-status");
  if (status) {
    status.textContent = state.ocSelectedTags.length
      ? "Etiquetas aleatorias generadas. Escribe el nombre y guarda."
      : "No hay rasgos cargados para generar un OC.";
  }
}

async function saveOcFromModal() {
  const name = ($("oc-create-name")?.value || "").trim();
  const status = $("oc-create-status");
  if (!name) {
    if (status) status.textContent = "El nombre es obligatorio.";
    return;
  }
  const save = $("btn-oc-create-save");
  if (save) save.disabled = true;
  try {
    const created = await postJson("/api/characters", {
      name,
      tags: [...state.ocSelectedTags],
      preprompt: "ninguno",
      rating: "nsfw",
      notes: "",
    });
    state.activeCharacterId = created.id;
    ocCreating = false;
    closeOcCreateModal(false);
    await loadCharacters();
    renderOcSelected();
    renderOcCatalogResults();
    await loadCharacterRefs();
    setOcStatus(`OC «${name}» creado`);
  } catch (error) {
    if (status) status.textContent = error.message;
  } finally {
    if (save) save.disabled = false;
  }
}

function scheduleSaveActiveOcTags() {
  clearTimeout(ocSaveTagsTimer);
  ocSaveTagsTimer = setTimeout(async () => {
    const character = characterById(state.activeCharacterId);
    if (!character || ocCreating) return;
    try {
      await putJson(`/api/characters/${character.id}`, {
        name: character.name,
        tags: [...state.ocSelectedTags],
        preprompt: "ninguno",
        rating: character.rating || "nsfw",
        notes: character.notes || "",
      });
      character.tags = [...state.ocSelectedTags];
      setOcStatus("Rasgos del OC guardados");
    } catch (error) {
      setOcStatus(error.message, true);
    }
  }, 450);
}

function toggleOcTag(tag) {
  const folded = tag.toLowerCase();
  const index = state.ocSelectedTags.findIndex(
    (item) => item.toLowerCase() === folded
  );
  if (index >= 0) {
    state.ocSelectedTags.splice(index, 1);
  } else {
    state.ocSelectedTags.push(tag);
  }
  if (ocCreating) {
    renderOcCreateModal();
    return;
  }
  renderOcSelected();
  renderOcCatalogResults();
  scheduleSaveActiveOcTags();
}

function characterById(charId) {
  return state.characters.find((item) => item.id === charId) || null;
}

function updateOcActiveHeader() {
  const character = characterById(state.activeCharacterId);
  const name = $("oc-active-name");
  const meta = $("oc-active-meta");
  const edit = $("btn-oc-edit-active");
  const add = $("btn-oc-add");
  const train = $("btn-oc-train");
  const addRef = $("btn-oc-add-ref");
  const addRefGallery = $("btn-oc-add-ref-gallery");
  const useImage = $("btn-oc-use-image");
  const multiview = $("btn-oc-multiview");
  const multiviewCount = $("oc-multiview-count");
  const hasActive = Boolean(character);
  if (name) name.textContent = hasActive ? character.name : "Sin OC activo";
  if (meta) {
    meta.textContent = hasActive
      ? `${(character.tags || []).length} rasgos · ${(character.extras || []).length} extras · ${(state.characterRefs || []).length} referencias`
      : "Crea o selecciona un OC para ver su ficha.";
  }
  for (const button of [edit, add, train, addRef, addRefGallery, useImage, multiview, multiviewCount]) {
    if (button) button.disabled = !hasActive;
  }
}

function renderCharacters() {
  const container = $("oc-list");
  container.replaceChildren();
  if (!state.characters.length) {
    const empty = document.createElement("div");
    empty.className = "oc-empty";
    const text = document.createElement("p");
    text.className = "empty";
    text.textContent = "Sin OCs guardados. Crea el primero con el formulario de abajo.";
    const create = document.createElement("button");
    create.type = "button";
    create.className = "primary";
    create.textContent = t("Crear OC");
    create.addEventListener("click", () => {
      startNewOc().catch((error) => setOcStatus(error.message, true));
    });
    empty.append(text, create);
    container.appendChild(empty);
    updateOcActiveHeader();
    return;
  }
  for (const character of state.characters) {
    container.appendChild(characterRow(character));
  }
  updateOcActiveHeader();
}

function characterRow(character) {
  const row = document.createElement("div");
  row.className = "oc-item";
  row.dataset.id = String(character.id);
  row.classList.toggle("active", character.id === state.activeCharacterId);
  const header = document.createElement("div");
  header.className = "oc-item-header";
  const name = document.createElement("strong");
  name.className = "oc-item-name";
  name.textContent = character.name;
  header.appendChild(name);
  if (character.id === state.activeCharacterId) {
    const badge = document.createElement("span");
    badge.className = "oc-item-badge";
    badge.textContent = "activo";
    header.appendChild(badge);
  }
  const extrasCount = (character.extras || []).length;
  const tags = document.createElement("span");
  tags.className = "oc-item-tags";
  tags.textContent = `${(character.tags || []).join(", ") || "sin rasgos"}${
    extrasCount ? ` · +${extrasCount} extras` : ""
  }`;

  // Entrada de renombrado directo en la tarjeta
  const renameBox = document.createElement("form");
  renameBox.className = "oc-item-rename hidden";
  const renameInput = document.createElement("input");
  renameInput.type = "text";
  renameInput.className = "oc-rename-input";
  renameInput.value = character.name;
  renameInput.placeholder = "Nuevo nombre";
  const renameSaveBtn = document.createElement("button");
  renameSaveBtn.type = "submit";
  renameSaveBtn.className = "oc-rename-save primary";
  renameSaveBtn.textContent = "Guardar";
  const renameCancelBtn = document.createElement("button");
  renameCancelBtn.type = "button";
  renameCancelBtn.className = "oc-rename-cancel";
  renameCancelBtn.textContent = "Cancelar";
  renameBox.append(renameInput, renameSaveBtn, renameCancelBtn);

  renameBox.addEventListener("submit", (e) => {
    e.preventDefault();
    renameCharacter(character, renameInput.value)
      .then(() => {
        renameBox.classList.add("hidden");
      })
      .catch((error) => setOcStatus(error.message, true));
  });

  renameCancelBtn.addEventListener("click", (e) => {
    e.preventDefault();
    renameInput.value = character.name;
    renameBox.classList.add("hidden");
  });

  const actions = document.createElement("div");
  actions.className = "oc-item-actions";
  const useButton = document.createElement("button");
  useButton.type = "button";
  useButton.className = "primary";
  useButton.textContent = t("Usar");
  useButton.addEventListener("click", () => {
    Promise.resolve(useCharacter(character)).catch((error) => setOcStatus(error.message, true));
  });
  const moreButton = document.createElement("button");
  moreButton.type = "button";
  moreButton.textContent = t("Más");
  moreButton.setAttribute("aria-haspopup", "menu");
  moreButton.setAttribute("aria-expanded", "false");
  const menu = document.createElement("div");
  menu.className = "oc-item-menu hidden";
  menu.setAttribute("role", "menu");
  moreButton.addEventListener("click", () => {
    const opening = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !opening);
    moreButton.setAttribute("aria-expanded", opening ? "true" : "false");
  });

  const menuItems = [
    ["8 vistas", () => generateCharacterMultiview(character)],
    ["Editar", () => editCharacter(character)],
    ["Duplicar", () => duplicateCharacter(character)],
    [
      "Renombrar",
      () => {
        renameBox.classList.remove("hidden");
        renameInput.value = character.name;
        renameInput.focus();
        renameInput.select();
      },
    ],
    ["Eliminar", () => deleteCharacter(character)],
  ];
  for (const [label, handler] of menuItems) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitem");
    button.textContent = t(label);
    if (label === "8 vistas") {
      button.className = "oc-btn-multiview";
      button.setAttribute("data-action", "multiview-8");
      button.title = "Genera 8 vistas coherentes con Qwen usando la primera referencia";
    }
    button.addEventListener("click", () => {
      menu.classList.add("hidden");
      moreButton.setAttribute("aria-expanded", "false");
      Promise.resolve(handler()).catch((error) => setOcStatus(error.message, true));
    });
    menu.appendChild(button);
  }
  actions.append(useButton, moreButton, menu);
  row.append(header, tags, renameBox, actions);
  row.addEventListener("click", (event) => {
    if (event.target.closest("button, input, select, textarea, a, label")) return;
    selectCharacter(character).catch((error) => setOcStatus(error.message, true));
  });
  return row;
}

async function loadCharacters() {
  state.characters = await api("/api/characters");
  if (
    state.activeCharacterId != null &&
    !state.characters.some((item) => item.id === state.activeCharacterId)
  ) {
    state.activeCharacterId = null;
  }
  renderCharacters();
}

function isOcEditing() {
  return state.ocEditingId != null;
}

function updateOcFormMode() {
  const editing = isOcEditing();
  const character = editing ? characterById(state.ocEditingId) : null;
  $("oc-form-title").textContent = editing
    ? `Editando: ${character ? character.name : "OC"}`
    : "Crear OC";
  $("btn-oc-save").textContent = editing ? "Guardar cambios" : "Guardar OC";
  $("btn-oc-cancel-edit").classList.toggle("hidden", !editing);
  $("oc-form").classList.toggle("editing", editing);
  const summary = $("oc-form-summary");
  if (summary) summary.textContent = editing ? `Editar: ${character ? character.name : "OC"}` : "Nuevo OC / Editar";
}

function resetOcForm() {
  state.ocEditingId = null;
  state.ocSelectedTags = [];
  state.ocExtras = [];
  $("oc-form-name").value = "";
  const ratingField = $("oc-form-rating");
  if (ratingField) ratingField.value = "nsfw";
  $("oc-form-notes").value = "";
  updateOcFormMode();
  renderOcSelected();
  renderOcExtras();
  renderOcCatalogResults();
}

function fillCharacterForm(character) {
  const details = $("oc-form-details");
  if (details && character) details.open = true;
  if (!character) {
    resetOcForm();
    return;
  }
  state.ocEditingId = character.id;
  state.ocSelectedTags = [...(character.tags || [])];
  state.ocExtras = [...(character.extras || [])];
  $("oc-form-name").value = character.name;
  const ratingFieldEdit = $("oc-form-rating");
  if (ratingFieldEdit) ratingFieldEdit.value = character.rating;
  $("oc-form-notes").value = character.notes;
  updateOcFormMode();
  renderOcSelected();
  renderOcExtras();
  renderOcCatalogResults();
}

async function startNewOc() {
  const details = $("oc-form-details");
  if (details) details.open = true;
  resetOcForm();
  await loadCharacterRefs();
  setOcStatus("Modo crear: nuevo OC");
}

async function cancelOcEdit() {
  resetOcForm();
  await loadCharacterRefs();
  setOcStatus("Edición cancelada: modo crear");
}

async function selectCharacter(character) {
  if (!character) return;
  state.activeCharacterId = character.id;
  state.ocSelectedTags = [...(character.tags || [])];
  state.ocExtras = [...(character.extras || [])];
  renderOcSelected();
  renderOcCatalogResults();
  renderCharacters();
  await loadCharacterRefs();
  setOcStatus(`OC «${character.name}» seleccionado; pulsa «Usar» para cargarlo en Imagen.`);
}

function ocUsesTagZones() {
  const info = state.prompt_profile_info;
  if (info && typeof info.zones_visible === "boolean") return info.zones_visible;
  return ["anima", "animagine", "sdxl_tags"].includes(String(state.prompt_profile || ""));
}

async function applyOcTagsToImagePrompt(text, extras = []) {
  const tags = promptTagsFromText(text);
  if (ocUsesTagZones()) {
    if (tags.length) addTagsToZone("character", tags);
    if (extras.length) await mergeZonesText(extras.join(", "));
    return;
  }
  const field = $("prompt-general");
  if (!field) return;
  const current = String(field.value || "").trim();
  const existing = new Set(
    current.split(",").map((tag) => tag.trim().toLowerCase()).filter(Boolean)
  );
  const missing = [...tags, ...extras]
    .map((tag) => String(tag || "").trim())
    .filter((tag) => tag && !existing.has(tag.toLowerCase()));
  if (!missing.length) return;
  field.value = current ? `${current}, ${missing.join(", ")}` : missing.join(", ");
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

async function useCharacter(character) {
  const profile = await fetchCharacterProfile(character, "auto");
  await applyOcTagsToImagePrompt(profile.text, profile.extras || []);
  let loraNote = "";
  if (profile.lora) {
    const selected = selectLora(profile.lora.id, profile.lora.default_weight);
    loraNote = selected
      ? ` · LoRA ${profile.lora.id} @ ${profile.lora.default_weight}`
      : ` · LoRA ${profile.lora.id} fuera del panel (familia activa)`;
  }
  const extrasNote = (profile.extras || []).length
    ? ` · extras: ${profile.extras.join(", ")}`
    : "";
  $("rating").value = character.rating;
  state.activeCharacterId = character.id;
  renderCharacters();
  await loadCharacterRefs();
  if (!state.negativeTouched) {
    await refreshNegative();
  }
  clearReference();
  $("tab-image")?.click();
  setStatus(
    `OC «${character.name}» cargado como rasgos/LoRA (${profile.mode})${loraNote}${extrasNote}; sin imagen de referencia`
  );
}

async function editCharacter(character) {
  const details = $("oc-form-details");
  if (details) details.open = true;
  fillCharacterForm(character);
  setOcStatus(`Editando: ${character.name}`);
}

async function duplicateCharacter(character) {
  fillCharacterForm(character);
  state.ocEditingId = null;
  $("oc-form-name").value = `${character.name} (copia)`;
  updateOcFormMode();
  setOcStatus("Ajusta el nombre y guarda la copia");
}

async function renameCharacter(character, newName) {
  const charId =
    typeof character === "object" && character !== null
      ? character.id
      : character;
  const targetChar =
    typeof character === "object" && character !== null
      ? character
      : characterById(charId);
  const name = String(newName || "").trim();
  if (!name) {
    setOcStatus("El nombre es obligatorio", true);
    return;
  }
  if (targetChar && targetChar.name === name) {
    setOcStatus(`El OC ya se llama «${name}»`);
    return;
  }
  await putJson(`/api/characters/${charId}`, { name });
  if (targetChar) {
    targetChar.name = name;
  }
  if (state.ocEditingId === charId) {
    const formName = $("oc-form-name");
    if (formName) {
      formName.value = name;
    }
    updateOcFormMode();
  }
  await loadCharacters();
  if (state.activeCharacterId === charId) {
    await loadCharacterRefs();
  }
  setOcStatus(`OC renombrado a «${name}»`);
}

const handleRename = renameCharacter;

async function deleteCharacter(character) {
  const confirmed = await showOcConfirmModal({
    title: "Eliminar personaje",
    message: `¿Eliminar el OC «${character.name}» y sus referencias?`,
    confirmText: "Confirmar",
    cancelText: "Cancelar",
    isDanger: true,
  });
  if (!confirmed) {
    return;
  }
  await api(`/api/characters/${character.id}`, { method: "DELETE" });
  if (state.activeCharacterId === character.id) {
    state.activeCharacterId = null;
  }
  if (state.ocEditingId === character.id) {
    resetOcForm();
  }
  await loadCharacters();
  await loadCharacterRefs();
  setOcStatus(`OC «${character.name}» eliminado`);
}

const confirmDelete = deleteCharacter;
const confirmDeleteCharacter = deleteCharacter;

async function saveCharacter(event) {
  event.preventDefault();
  const name = $("oc-form-name").value.trim();
  if (!name) {
    setOcStatus("El nombre es obligatorio", true);
    return;
  }
  const payload = {
    name,
    tags: state.ocSelectedTags.slice(),
    preprompt: "ninguno",
    rating: $("oc-form-rating")?.value || "nsfw",
    notes: $("oc-form-notes").value,
  };
  try {
    let charId = state.ocEditingId;
    if (charId == null) {
      const created = await postJson("/api/characters", payload);
      charId = created.id;
      state.activeCharacterId = charId;
    } else {
      await api(`/api/characters/${charId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    await loadCharacters();
    resetOcForm();
    await loadCharacterRefs();
    setOcStatus(`OC «${name}» guardado`);
  } catch (error) {
    setOcStatus(error.message, true);
  }
}

function ocGalleryImageUrl(item) {
  return (item?.urls && item.urls[0]) || (item?.outputs && item.outputs[0]
    ? `/media/${item.id}/${item.outputs[0]}`
    : "");
}

async function openOcRefGallery() {
  if (state.activeCharacterId == null) {
    setOcStatus("Selecciona un OC antes de añadir referencias", true);
    return;
  }
  $("oc-ref-gallery-modal")?.classList.remove("hidden");
  await loadOcRefGallery();
}

async function loadOcRefGallery() {
  const grid = $("oc-ref-gallery-grid");
  const status = $("oc-ref-gallery-status");
  if (!grid) return;
  grid.replaceChildren();
  if (status) status.textContent = "Cargando…";
  try {
    const data = await api("/api/gallery?kind=image&limit=24&offset=0");
    const items = (data.items || []).filter((item) => item.status === "done");
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No hay imágenes en la galería.";
      grid.appendChild(empty);
      if (status) status.textContent = "Vacío";
      return;
    }
    for (const item of items) {
      const url = ocGalleryImageUrl(item);
      if (!url) continue;
      const card = document.createElement("button");
      card.type = "button";
      card.className = "oc-ref-gallery-card";
      card.title = item.prompt || `Generación #${item.id}`;
      const img = document.createElement("img");
      img.src = url;
      img.alt = card.title;
      img.loading = "lazy";
      card.appendChild(img);
      card.addEventListener("click", () => {
        addOcRefFromGallery(item.id).catch((error) => setOcStatus(error.message, true));
      });
      grid.appendChild(card);
    }
    if (status) status.textContent = `${items.length} imágenes`;
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

async function addOcRefFromGallery(genId) {
  const charId = state.activeCharacterId;
  if (charId == null) return;
  $("oc-ref-gallery-modal")?.classList.add("hidden");
  await postJson(`/api/characters/${charId}/refs`, { gen_id: genId });
  await loadCharacterRefs();
  setOcStatus(`Referencia de la galería añadida a #${charId}`);
}

async function uploadOcRef(file) {
  const charId = state.activeCharacterId;
  if (charId == null) {
    setOcStatus("Selecciona un OC antes de añadir referencias", true);
    return;
  }
  if (!file) return;
  const b64 = await readFileBase64(file);
  await postJson(`/api/characters/${charId}/refs/upload`, {
    filename: file.name,
    file_b64: b64,
  });
  await loadCharacterRefs();
  setOcStatus(`Referencia añadida a #${charId}`);
}

async function loadCharacterRefs() {
  const container = $("oc-refs");
  const title = $("oc-refs-title");
  const button = $("btn-oc-sheet");
  container.replaceChildren();
  state.characterRefs = [];
  if (state.activeCharacterId == null) {
    title.textContent = "sin OC activo";
    if (button) button.disabled = true;
    updateOcActiveHeader();
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Selecciona un OC de la lista o crea uno nuevo para ver sus referencias.";
    container.appendChild(empty);
    return;
  }
  const character = characterById(state.activeCharacterId);
  const refs = await api(`/api/characters/${state.activeCharacterId}/refs`);
  state.characterRefs = refs;
  title.textContent = character ? `de ${character.name}` : "";
  if (button) button.disabled = refs.length < 2;
  updateOcActiveHeader();
  if (!refs.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin referencias. Usa «Añadir referencia» o la Galería.";
    container.appendChild(empty);
    return;
  }
  for (const ref of refs) {
    const figure = document.createElement("figure");
    figure.className = "oc-ref";
    if (isSheetRef(ref)) {
      figure.classList.add("is-sheet");
    }
    const img = document.createElement("img");
    img.src = ref.url;
    img.alt = `Referencia ${ref.id}`;
    img.loading = "lazy";
    img.style.cursor = "pointer";
    img.addEventListener("click", () => {
      openLightbox(ref.url, img.alt);
    });
    figure.appendChild(img);
    if (isSheetRef(ref)) {
      const badge = document.createElement("span");
      badge.className = "oc-ref-badge";
      badge.textContent = "hoja";
      const note = document.createElement("p");
      note.className = "oc-ref-note";
      note.textContent = "Para IPAdapter (M10); no recomendada como referencia I2I";
      figure.append(badge, note);
    }
    const link = document.createElement("a");
    link.className = "oc-ref-link";
    link.href = ref.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "Ver/Descargar";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Quitar";
    remove.addEventListener("click", () => {
      removeCharacterRef(ref).catch((error) =>
        setOcStatus(error.message, true)
      );
    });
    figure.append(link, remove);
    container.appendChild(figure);
  }
}

async function removeCharacterRef(ref) {
  await api(`/api/characters/${ref.character_id}/refs/${ref.id}`, {
    method: "DELETE",
  });
  await loadCharacterRefs();
  setOcStatus("Referencia quitada");
}

async function createCharacterSheet() {
  if (state.activeCharacterId == null) {
    return;
  }
  const button = $("btn-oc-sheet");
  button.disabled = true;
  setOcStatus("Creando hoja...");
  try {
    await postJson(`/api/characters/${state.activeCharacterId}/sheet`, {});
    await loadCharacterRefs();
    setOcStatus(
      "Hoja creada: catálogo para IPAdapter (M10); no se adjunta como referencia I2I"
    );
  } catch (error) {
    setOcStatus(error.message, true);
    button.disabled = state.characterRefs.length < 2;
  }
}

async function openOcMultiviewPicker() {
  const character = characterById(state.activeCharacterId);
  if (!character) {
    setOcStatus("Selecciona un OC antes de generar multivistas", true);
    return;
  }
  await loadCharacterRefs();
  const refs = (state.characterRefs || []).filter((ref) => !isSheetRef(ref));
  if (!refs.length) {
    setOcStatus("El OC no tiene referencias para usar como base", true);
    return;
  }
  const modal = $("oc-multiview-modal");
  const grid = $("oc-multiview-grid");
  if (!modal || !grid) return;
  grid.replaceChildren();
  for (const ref of refs) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "oc-ref-gallery-card";
    card.title = "Usar esta referencia como base";
    const img = document.createElement("img");
    img.src = ref.url;
    img.alt = "Referencia base";
    img.loading = "lazy";
    card.appendChild(img);
    card.addEventListener("click", () => {
      modal.classList.add("hidden");
      const count = Number($("oc-multiview-count")?.value || 4);
      generateCharacterMultiview(character, { ref, count })
        .catch((error) => setOcStatus(error.message, true));
    });
    grid.appendChild(card);
  }
  modal.classList.remove("hidden");
}

export async function generateCharacterMultiview(character, options = {}) {
  if (!character || !character.id) return;
  state.activeCharacterId = character.id;
  renderCharacters();
  await loadCharacterRefs();

  const refs = state.characterRefs || [];
  const attachable = refs.filter((ref) => !isSheetRef(ref));
  if (!attachable.length) {
    setOcStatus(
      `El OC «${character.name}» no tiene referencias válidas. Añade al menos una imagen de referencia antes de generar la multivista.`,
      true
    );
    return;
  }
  const firstRef = options.ref || attachable[0];

  if (!state.editorLicenseAccepted) {
    try {
      const editorStatus = await api("/api/editor/status");
      state.editorLicenseAccepted = Boolean(editorStatus && editorStatus.license && editorStatus.license.accepted);
    } catch {
      // Ignorar fallo puntual de red
    }
  }
  if (!state.editorLicenseAccepted) {
    setOcStatus("Acepta la licencia de Qwen-Image 2.1 en la pestaña Editor antes de generar multivista", true);
    return;
  }

  setOcStatus(`Cargando referencia de «${character.name}»…`);
  const res = await fetch(firstRef.url);
  if (!res.ok) {
    throw new Error(`Error al leer la referencia del OC (HTTP ${res.status})`);
  }
  const blob = await res.blob();
  const refB64 = await readFileBase64(blob);

  const charTags = (character.tags || []).join(", ");
  const prompt = charTags
    ? `${charTags}, character turnaround, full body, neutral background`
    : "character turnaround, full body, neutral background";

  const count = [4, 6, 8].includes(Number(options.count)) ? Number(options.count) : 8;
  setOcStatus(`Iniciando generación de ${count} vistas para «${character.name}»…`);

  const entries = await runMultiviewGeneration({
    refs: [refB64],
    prompt,
    count,
    seed: 42,
    steps: 25,
    cfg: 1.0,
    onProgress: (msg) => setOcStatus(`Multivista «${character.name}»: ${msg}`),
    onViewGenerated: async (entry) => {
      if (entry && entry.gen_id) {
        try {
          await postJson(`/api/characters/${character.id}/refs`, { gen_id: entry.gen_id });
          await loadCharacterRefs();
        } catch (err) {
          console.error(`[oc_picker] Error guardando referencia de multivista para OC ${character.id}:`, err);
        }
      }
    },
  });

  const ocResults = $("oc-multiview-results");
  if (ocResults) {
    renderSheet(entries, ocResults);
  }

  await loadCharacterRefs();
  setOcStatus(`${count} vistas generadas y guardadas como referencias para «${character.name}»`);
  return entries;
}

function buildPosePrompt(character, pose) {
  const charTags = ((character && character.tags) || []).join(", ");
  const tags = Array.isArray(pose?.tags) ? pose.tags : [];
  const poseText = tags.length ? tags.join(", ") : (pose?.nombre_ja || "pose");
  const base = `${poseText}, same character, same outfit, full body, neutral background`;
  return charTags ? `${charTags}, ${base}` : base;
}

// C-29: llamada rápida de pose desde OC Maker, sin abrir el Editor.
// Usa la pose elegida en la librería y la primera referencia no-hoja del OC activo.
async function generateCharacterPose() {
  const character = characterById(state.activeCharacterId);
  if (!character) {
    setOcStatus("Selecciona un OC para generar la pose", true);
    return null;
  }
  const pose = getSelectedPose();
  if (!pose) {
    setOcStatus("Elige una pose en «Poses» antes de generar", true);
    return null;
  }
  await loadCharacterRefs();
  const attachable = (state.characterRefs || []).filter((ref) => !isSheetRef(ref));
  if (!attachable.length) {
    setOcStatus(
      `El OC «${character.name}» no tiene referencias válidas. Añade una imagen de referencia antes de generar la pose.`,
      true
    );
    return null;
  }
  if (!state.editorLicenseAccepted) {
    try {
      const editorStatus = await api("/api/editor/status");
      state.editorLicenseAccepted = Boolean(editorStatus && editorStatus.license && editorStatus.license.accepted);
    } catch {
      // Ignorar fallo puntual de red
    }
  }
  if (!state.editorLicenseAccepted) {
    setOcStatus("Acepta la licencia de Qwen-Image 2.1 en la pestaña Editor antes de generar la pose", true);
    return null;
  }

  const button = $("btn-oc-pose-generate");
  if (button) button.disabled = true;
  try {
    setOcStatus(`Cargando referencia de «${character.name}»…`);
    const res = await fetch(attachable[0].url);
    if (!res.ok) {
      throw new Error(`Error al leer la referencia del OC (HTTP ${res.status})`);
    }
    const refB64 = await readFileBase64(await res.blob());
    const job = await postJson("/api/editor/generate", {
      prompt: buildPosePrompt(character, pose),
      mode: "generate",
      negative: "",
      steps: 25,
      cfg: 1,
      size: { original: true },
      seed: Math.floor(Math.random() * 2147483647),
      preserve_structure: false,
      ref_images_b64: [refB64],
    });
    setOcStatus(`Generando pose «${pose.clase_es} · ${pose.angulo_es}» para «${character.name}»…`);
    const done = await new Promise((resolve, reject) => {
      pollJob(
        job.job_id,
        (message, isError) => setOcStatus(`Pose «${character.name}»: ${message}`, Boolean(isError)),
        resolve,
        () => {},
        false
      ).catch(reject);
    });
    if (!done || done.status !== "done" || !done.gen_id) {
      throw new Error((done && done.error) || "La pose no devolvió imagen");
    }
    await postJson(`/api/characters/${character.id}/refs`, { gen_id: done.gen_id });
    await loadCharacterRefs();
    setOcStatus(`Pose generada y guardada como nueva referencia de «${character.name}»`);
    return done;
  } finally {
    if (button) button.disabled = false;
  }
}

function addOcTagsToPrompt() {
  if (!state.ocSelectedTags.length) {
    setOcStatus("Selecciona al menos un tag del catálogo", true);
    return;
  }
  const text = promptFromTags(state.ocSelectedTags);
  applyOcTagsToImagePrompt(text)
    .then(() => setOcStatus("Rasgos añadidos al prompt, sin cambiar de pestaña"))
    .catch((error) => setOcStatus(error.message, true));
}

async function openOcSaveModal(item) {
  state.ocSaveGenId = item.id;
  setOcSaveStatus(`Imagen #${item.id}`);
  $("oc-save-name").value = "";
  await loadCharacters();
  const select = $("oc-save-select");
  select.replaceChildren();
  select.appendChild(option("", "Elegir OC"));
  for (const character of state.characters) {
    select.appendChild(option(String(character.id), character.name));
  }
  if (state.activeCharacterId != null) {
    select.value = String(state.activeCharacterId);
  }
  $("oc-save-modal").classList.remove("hidden");
}

function closeOcSaveModal() {
  $("oc-save-modal").classList.add("hidden");
  state.ocSaveGenId = null;
}

async function confirmOcSave() {
  const genId = state.ocSaveGenId;
  if (genId == null) {
    return;
  }
  const button = $("btn-oc-save-confirm");
  button.disabled = true;
  try {
    let charId = $("oc-save-select").value
      ? Number($("oc-save-select").value)
      : null;
    const newName = $("oc-save-name").value.trim();
    if (newName) {
      const created = await postJson("/api/characters", {
        name: newName,
        tags: [],
      });
      charId = created.id;
    }
    if (charId == null) {
      setOcSaveStatus("Elige un OC o escribe un nombre nuevo", true);
      return;
    }
    await postJson(`/api/characters/${charId}/refs`, { gen_id: genId });
    await loadCharacters();
    if (state.activeCharacterId === charId) {
      await loadCharacterRefs();
    }
    closeOcSaveModal();
    setStatus("Referencia guardada en el OC");
  } catch (error) {
    setOcSaveStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}


function openOcModal() {
  // La pestaña ya está montada: al entrar se refrescan OCs, rasgos y referencias.
  Promise.all([
    loadCharacters(),
    loadOcCatalog(),
    loadOcPreprompts(),
    loadCharacterRefs(),
  ]).catch((error) => setOcStatus(error.message, true));
}

function closeOcModal() {
  // OC Maker es una pestaña real: no hay modal que cerrar.
}


function initOcPicker() {
  on("btn-oc-create", "click", openOcCreateModal);
  on("btn-oc-generate", "click", openOcGenerateModal);
  on("btn-oc-create-close", "click", () => closeOcCreateModal(true));
  on("btn-oc-create-cancel", "click", () => closeOcCreateModal(true));
  on("btn-oc-create-save", "click", () => saveOcFromModal().catch((error) => setOcStatus(error.message, true)));
  on("oc-create-group", "change", renderOcCreateTraits);
  on("btn-oc-multiview", "click", () => {
    openOcMultiviewPicker().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-multiview-close", "click", () => $("oc-multiview-modal")?.classList.add("hidden"));
  on("oc-multiview-modal", "click", (event) => {
    if (event.target === $("oc-multiview-modal")) $("oc-multiview-modal")?.classList.add("hidden");
  });
  on("btn-oc-use-image", "click", () => {
    const character = characterById(state.activeCharacterId);
    if (character) useCharacter(character).catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-add", "click", addOcTagsToPrompt);
  on("btn-oc-edit-active", "click", () => {
    const character = characterById(state.activeCharacterId);
    if (character) editCharacter(character).catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-train", "click", () => {
    const character = characterById(state.activeCharacterId) || state.characters[0];
    if (!character) {
      setOcStatus("Crea o selecciona un OC antes de entrenar una LoRA.", true);
      return;
    }
    openTrainModal(character);
  });
  on("btn-oc-add-ref", "click", () => $("oc-ref-upload").click());
  on("btn-oc-add-ref-gallery", "click", () => {
    openOcRefGallery().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-ref-gallery-close", "click", () => $("oc-ref-gallery-modal")?.classList.add("hidden"));
  on("oc-ref-gallery-modal", "click", (event) => {
    if (event.target === $("oc-ref-gallery-modal")) $("oc-ref-gallery-modal")?.classList.add("hidden");
  });
  on("oc-ref-upload", "change", () => {
    const file = $("oc-ref-upload").files[0];
    uploadOcRef(file)
      .catch((error) => setOcStatus(error.message, true))
      .finally(() => {
        $("oc-ref-upload").value = "";
      });
  });
  on("oc-catalog-group", "change", () => {
    refreshOcCatalog().catch((error) => setOcStatus(error.message, true));
  });
  on("oc-catalog-search", "input", () => {
    if (ocSearchTimer) {
      clearTimeout(ocSearchTimer);
    }
    ocSearchTimer = setTimeout(() => {
      refreshOcCatalog().catch((error) => setOcStatus(error.message, true));
    }, 250);
  });
  on("oc-form", "submit", saveCharacter);
  on("btn-oc-new", "click", () => {
    startNewOc().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-cancel-edit", "click", () => {
    cancelOcEdit().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-extras-move", "click", () => {
    moveOcExtrasToGeneral().catch((error) => setOcStatus(error.message, true));
  });
  on("btn-oc-save-close", "click", closeOcSaveModal);
  on("btn-oc-save-confirm", "click", () => {
    confirmOcSave().catch((error) => setOcSaveStatus(error.message, true));
  });
  on("oc-save-modal", "click", (event) => {
    if (event.target === $("oc-save-modal")) {
      closeOcSaveModal();
    }
  });
  on("btn-oc-confirm-accept", "click", handleConfirmAccept);
  on("btn-oc-confirm-cancel", "click", handleConfirmCancel);
  on("btn-oc-confirm-close", "click", handleConfirmCancel);
  on("oc-confirm-modal", "click", (event) => {
    if (event.target === $("oc-confirm-modal")) {
      handleConfirmCancel();
    }
  });
}

export {
  setOcStatus,
  setOcSaveStatus,
  refFilename,
  isSheetRef,
  isOcTagSelected,
  getOcTagGroup,
  renderOcCatalogResults,
  renderOcSelected,
  renderOcExtras,
  moveOcExtrasToGeneral,
  showOcConfirmModal,
  closeOcConfirmModal,
  handleConfirmAccept,
  handleConfirmCancel,
  refreshOcCatalog,
  loadOcCatalog,
  loadOcPreprompts,
  toggleOcTag,
  characterById,
  renderCharacters,
  characterRow,
  loadCharacters,
  loadCharacterRefs,
  isOcEditing,
  updateOcFormMode,
  resetOcForm,
  fillCharacterForm,
  startNewOc,
  cancelOcEdit,
  useCharacter,
  editCharacter,
  duplicateCharacter,
  renameCharacter,
  handleRename,
  deleteCharacter,
  confirmDelete,
  confirmDeleteCharacter,
  saveCharacter,
  removeCharacterRef,
  createCharacterSheet,
  buildPosePrompt,
  generateCharacterPose,
  addOcTagsToPrompt,
  openOcSaveModal,
  closeOcSaveModal,
  confirmOcSave,
  openOcModal,
  closeOcModal,
  initOcPicker,
};
