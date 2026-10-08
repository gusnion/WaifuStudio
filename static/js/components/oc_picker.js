// WaifuStudio — Selector y Modal de OC (Original Character)
// oc_picker.js: creación, edición, catálogo de rasgos y persistencia de OCs.

import { state, GROUP_LABELS, OC_TRAIT_GROUPS } from "../state.js";
import { $, on, setStatus, setSelectValue, readFileBase64, option, showUiBanner } from "../dom.js";
import { api, postJson, putJson } from "../api.js";
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
import { attachReferenceFromUrl, fetchCharacterProfile } from "./prompt_popover.js";
import { openTrainModal } from "./oc_train.js";
import { selectLora } from "./loras.js";
import { refreshNegative } from "../tabs/image.js";

let ocSearchTimer = null;

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

async function useRefAsReference(ref) {
  if (isSheetRef(ref)) {
    const proceed = window.confirm(
      "Esta ref es una hoja (catálogo para IPAdapter M10): como referencia I2I puede copiar el mosaico. ¿Adjuntarla igualmente?"
    );
    if (!proceed) {
      return false;
    }
  }
  await attachReferenceFromUrl(ref.url, refFilename(ref));
  closeOcModal();
  setStatus(
    `Referencia adjuntada (fuerza ${Number($("strength").value).toFixed(2)})`
  );
  return true;
}

function isOcTagSelected(tag) {
  const folded = tag.toLowerCase();
  return state.ocSelectedTags.some((item) => item.toLowerCase() === folded);
}

function renderOcCatalogResults() {
  const container = $("oc-catalog-results");
  container.replaceChildren();
  if (!state.ocCatalogItems.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin resultados.";
    container.appendChild(empty);
    return;
  }
  for (const item of state.ocCatalogItems) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "oc-chip";
    chip.textContent =
      item.label && item.label !== item.tag
        ? `${item.label} · ${item.tag}`
        : item.tag;
    chip.title = item.tag;
    chip.classList.toggle("selected", isOcTagSelected(item.tag));
    chip.addEventListener("click", () => toggleOcTag(item.tag));
    container.appendChild(chip);
  }
}

function renderOcSelected() {
  const container = $("oc-selected");
  container.replaceChildren();
  if (!state.ocSelectedTags.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Ningún tag seleccionado.";
    container.appendChild(empty);
    return;
  }
  for (const tag of state.ocSelectedTags) {
    const chip = document.createElement("span");
    chip.className = "oc-selected-chip";
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "quitar";
    remove.addEventListener("click", () => toggleOcTag(tag));
    chip.append(text, remove);
    container.appendChild(chip);
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
  if (
    state.ocEditingId != null &&
    window.confirm(
      `Extras insertados en General${
        added.length ? "" : " (ya estaban en el prompt)"
      }. ¿Quitarlos también del OC?`
    )
  ) {
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
    items = data.items || [];
  } else {
    const results = await Promise.all(
      OC_TRAIT_GROUPS.map((name) =>
        api(`/api/tags?group=${encodeURIComponent(name)}`)
      )
    );
    items = results.flatMap((data) => data.items || []);
    if (query) {
      const needle = query.toLowerCase();
      items = items.filter(
        (item) =>
          item.tag.toLowerCase().includes(needle) ||
          String(item.label || "").toLowerCase().includes(needle)
      );
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
  const family = state.family || "anima";
  const data = await api(`/api/preprompts?family=${encodeURIComponent(family)}`);
  const custom = new Set(data.custom || []);
  const select = $("oc-form-preprompt");
  select.replaceChildren();
  for (const name of data.names || []) {
    select.appendChild(option(name, custom.has(name) ? `${name} (propio)` : name));
  }
  state.ocPrepromptDefault = data.default || "";
  select.value = data.default || select.value;
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
  renderOcSelected();
  renderOcCatalogResults();
}

function characterById(charId) {
  return state.characters.find((item) => item.id === charId) || null;
}

function renderCharacters() {
  const container = $("oc-list");
  container.replaceChildren();
  if (!state.characters.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin OCs guardados.";
    container.appendChild(empty);
    return;
  }
  for (const character of state.characters) {
    container.appendChild(characterRow(character));
  }
}

function characterRow(character) {
  const row = document.createElement("div");
  row.className = "oc-item";
  row.classList.toggle("active", character.id === state.activeCharacterId);
  const header = document.createElement("div");
  header.className = "oc-item-header";
  const name = document.createElement("strong");
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
  const actions = document.createElement("div");
  actions.className = "oc-item-actions";
  const handlers = [
    ["Usar", () => useCharacter(character)],
    ["Generar LoRA", () => openTrainModal(character)],
    ["Editar", () => editCharacter(character)],
    ["Duplicar", () => duplicateCharacter(character)],
    ["Eliminar", () => deleteCharacter(character)],
  ];
  for (const [label, handler] of handlers) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => {
      Promise.resolve(handler()).catch((error) =>
        setOcStatus(error.message, true)
      );
    });
    actions.appendChild(button);
  }
  row.append(header, tags, actions);
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
}

function resetOcForm() {
  state.ocEditingId = null;
  state.ocSelectedTags = [];
  state.ocExtras = [];
  $("oc-form-name").value = "";
  const preprompt = $("oc-form-preprompt");
  preprompt.value =
    state.ocPrepromptDefault ||
    (preprompt.options.length ? preprompt.options[0].value : "");
  $("oc-form-rating").value = "sfw";
  $("oc-form-notes").value = "";
  updateOcFormMode();
  renderOcSelected();
  renderOcExtras();
  renderOcCatalogResults();
}

function fillCharacterForm(character) {
  if (!character) {
    resetOcForm();
    return;
  }
  state.ocEditingId = character.id;
  state.ocSelectedTags = [...(character.tags || [])];
  state.ocExtras = [...(character.extras || [])];
  $("oc-form-name").value = character.name;
  $("oc-form-preprompt").value = character.preprompt;
  $("oc-form-rating").value = character.rating;
  $("oc-form-notes").value = character.notes;
  updateOcFormMode();
  renderOcSelected();
  renderOcExtras();
  renderOcCatalogResults();
}

async function startNewOc() {
  resetOcForm();
  await loadCharacterRefs();
  setOcStatus("Modo crear: nuevo OC");
}

async function cancelOcEdit() {
  resetOcForm();
  await loadCharacterRefs();
  setOcStatus("Edición cancelada: modo crear");
}

async function useCharacter(character) {
  const profile = await fetchCharacterProfile(character, "auto");
  addTagsToZone("character", promptTagsFromText(profile.text));
  let loraNote = "";
  if (profile.lora) {
    const selected = selectLora(profile.lora.id, profile.lora.default_weight);
    loraNote = selected
      ? ` · LoRA ${profile.lora.id} @ ${profile.lora.default_weight}`
      : ` · LoRA ${profile.lora.id} fuera del panel (familia activa)`;
  }
  let extrasNote = "";
  if ((profile.extras || []).length) {
    await mergeZonesText(profile.extras.join(", "));
    extrasNote = ` · extras a General: ${profile.extras.join(", ")}`;
  }
  $("preprompt").value = character.preprompt;
  $("rating").value = character.rating;
  state.activeCharacterId = character.id;
  renderCharacters();
  await loadCharacterRefs();
  if (!state.negativeTouched) {
    await refreshNegative();
  }
  const refs = state.characterRefs || [];
  const attachable = refs.find((ref) => !isSheetRef(ref));
  let refNote = "";
  if (attachable) {
    await attachReferenceFromUrl(attachable.url, refFilename(attachable));
  } else if (refs.length) {
    refNote = " (solo hojas: sin referencia I2I)";
  }
  closeOcModal();
  setStatus(
    `OC «${character.name}» cargado (${profile.mode})${loraNote}${extrasNote}${refNote}`
  );
}

async function editCharacter(character) {
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

async function deleteCharacter(character) {
  if (!window.confirm(`¿Eliminar el OC «${character.name}» y sus referencias?`)) {
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
    preprompt: $("oc-form-preprompt").value,
    rating: $("oc-form-rating").value,
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

async function loadCharacterRefs() {
  const container = $("oc-refs");
  const title = $("oc-refs-title");
  const button = $("btn-oc-sheet");
  container.replaceChildren();
  state.characterRefs = [];
  if (state.activeCharacterId == null) {
    title.textContent = "sin OC activo";
    button.disabled = true;
    return;
  }
  const character = characterById(state.activeCharacterId);
  const refs = await api(`/api/characters/${state.activeCharacterId}/refs`);
  state.characterRefs = refs;
  title.textContent = character ? `de ${character.name}` : "";
  button.disabled = refs.length < 2;
  if (!refs.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin referencias. Añádelas desde la galería.";
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
    const use = document.createElement("button");
    use.type = "button";
    use.textContent = "Usar como referencia";
    use.addEventListener("click", () => {
      useRefAsReference(ref).catch((error) => setOcStatus(error.message, true));
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Quitar";
    remove.addEventListener("click", () => {
      removeCharacterRef(ref).catch((error) =>
        setOcStatus(error.message, true)
      );
    });
    figure.append(link, use, remove);
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

function addOcTagsToPrompt() {
  if (!state.ocSelectedTags.length) {
    setOcStatus("Selecciona al menos un tag del catálogo", true);
    return;
  }
  const text = promptFromTags(state.ocSelectedTags);
  mergeZonesText(text)
    .then(() => {
      closeOcModal();
      setStatus("Tags añadidos al prompt");
    })
    .catch((error) => setOcStatus(error.message, true));
}

async function openOcSaveModal(item) {
  state.ocSaveGenId = item.id;
  setOcSaveStatus(`Imagen #${item.id}`);
  $("oc-save-name").value = "";
  await loadCharacters();
  const select = $("oc-save-select");
  select.replaceChildren();
  select.appendChild(option("", "— elegir OC —"));
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
  try {
    resetOcForm();
    setOcStatus("Modo crear: formulario limpio");
    $("oc-modal").classList.remove("hidden");
  } catch (error) {
    console.error("openOcModal: no se pudo abrir el OC Maker", error);
    setOcStatus(`No se pudo abrir el OC Maker: ${error.message}`, true);
    showUiBanner("OC Maker no disponible: recarga con Ctrl+F5");
    return;
  }
  loadCharacters()
    .then(loadCharacterRefs)
    .catch((error) => setOcStatus(error.message, true));
}

function closeOcModal() {
  $("oc-modal").classList.add("hidden");
}


function initOcPicker() {
  on("btn-oc", "click", openOcModal);
  on("btn-oc-close", "click", closeOcModal);
  on("btn-oc-add", "click", addOcTagsToPrompt);
  on("oc-modal", "click", (event) => {
    if (event.target === $("oc-modal")) {
      closeOcModal();
    }
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
  on("btn-oc-sheet", "click", () => {
    createCharacterSheet().catch((error) => setOcStatus(error.message, true));
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
}

export {
  setOcStatus,
  setOcSaveStatus,
  refFilename,
  isSheetRef,
  useRefAsReference,
  isOcTagSelected,
  renderOcCatalogResults,
  renderOcSelected,
  renderOcExtras,
  moveOcExtrasToGeneral,
  refreshOcCatalog,
  loadOcCatalog,
  loadOcPreprompts,
  toggleOcTag,
  characterById,
  renderCharacters,
  characterRow,
  loadCharacters,
  isOcEditing,
  updateOcFormMode,
  resetOcForm,
  fillCharacterForm,
  startNewOc,
  cancelOcEdit,
  useCharacter,
  editCharacter,
  duplicateCharacter,
  deleteCharacter,
  saveCharacter,
  loadCharacterRefs,
  removeCharacterRef,
  createCharacterSheet,
  addOcTagsToPrompt,
  openOcSaveModal,
  closeOcSaveModal,
  confirmOcSave,
  openOcModal,
  closeOcModal,
  initOcPicker,
};
