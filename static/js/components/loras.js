// WaifuStudio — Selector y Biblioteca de LoRAs
// Qué hace: modal de selección de LoRAs, ajuste de pesos y CRUD de biblioteca.
// Qué no hace: no aplica pesos al sampling ni ejecuta el pipeline de inferencia.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import { state } from "../state.js";
import { $, on, setStatus, readFileBase64 } from "../dom.js";
import { api, postJson, putJson } from "../api.js";

async function loadLoras() {
  const family = state.family || "anima";
  const data = await api(`/api/loras?family=${encodeURIComponent(family)}`);
  state.loras = data.items || [];
  state.loraSelection = new Map();
  renderLoras();
}

function loraById(loraId) {
  return state.loras.find((lora) => lora.id === loraId) || null;
}

function clampLoraWeight(value) {
  const weight = Number(value);
  if (!Number.isFinite(weight)) {
    return null;
  }
  return Math.max(0, Math.min(2, weight));
}

function emptyLoraMessage(text) {
  const empty = document.createElement("p");
  empty.className = "empty";
  empty.textContent = text;
  return empty;
}

function renderLoraChips() {
  const container = $("loras-list");
  if (!container) {
    return;
  }
  container.replaceChildren();
  if (!state.loras.length) {
    container.appendChild(
      emptyLoraMessage(
        "No hay LoRAs de imagen registradas. Añádelas con «Gestionar " +
          "biblioteca» (o en registry/loras.json) con familia anima"
      )
    );
    return;
  }
  if (!state.loraSelection.size) {
    container.appendChild(emptyLoraMessage("Ningún LoRA seleccionado."));
    return;
  }
  for (const lora of state.loras) {
    if (!state.loraSelection.has(lora.id)) {
      continue;
    }
    const weight = Number(state.loraSelection.get(lora.id));
    const chip = document.createElement("span");
    chip.className = "lora-chip";
    const name = document.createElement("span");
    name.className = "lora-chip-name";
    name.textContent = lora.display_name || lora.id;
    name.title = `${lora.id} @ ${weight.toFixed(2)}`;
    const value = document.createElement("span");
    value.className = "lora-chip-weight";
    value.textContent = `@ ${weight.toFixed(2)}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "lora-chip-remove";
    remove.textContent = "×";
    remove.title = "Quitar";
    remove.addEventListener("click", () => setLoraSelected(lora.id, false));
    chip.append(name, value, remove);
    container.appendChild(chip);
  }
}

function updateLoraCounters() {
  const total = state.loraSelection.size;
  const button = $("btn-lora-modal");
  if (button) {
    button.textContent = `Elegir LoRAs (${total})`;
  }
  const summary = $("loras-count");
  if (summary) {
    summary.textContent = String(total);
  }
  const modalCount = $("lora-selected-count");
  if (modalCount) {
    modalCount.textContent = `${total} seleccionado${total === 1 ? "" : "s"}`;
  }
}

function syncLoraControls(loraId) {
  const controls = state.loraControls[loraId];
  const lora = loraById(loraId);
  if (!controls || !lora) {
    return;
  }
  const selected = state.loraSelection.has(loraId);
  const stored = selected ? Number(state.loraSelection.get(loraId)) : NaN;
  const weight = Number.isFinite(stored) ? stored : Number(lora.default_weight);
  controls.check.checked = selected;
  controls.weight.value = String(weight);
  controls.value.textContent = weight.toFixed(2);
}

function setLoraSelected(loraId, selected, weight) {
  const lora = loraById(loraId);
  if (!lora) {
    return false;
  }
  if (selected) {
    const wanted = clampLoraWeight(weight);
    state.loraSelection.set(
      loraId,
      wanted == null ? Number(lora.default_weight) : wanted
    );
  } else {
    state.loraSelection.delete(loraId);
  }
  syncLoraControls(loraId);
  renderLoraChips();
  updateLoraCounters();
  return true;
}

function selectLora(loraId, weight) {
  return setLoraSelected(loraId, true, weight);
}

function renderLoraModalList() {
  const container = $("lora-options");
  if (!container) {
    return;
  }
  const search = $("lora-search");
  const query = (search ? search.value : "").trim().toLowerCase();
  container.replaceChildren();
  state.loraControls = {};
  if (!state.loras.length) {
    container.appendChild(
      emptyLoraMessage(
        "No hay LoRAs de imagen registradas. Añádelas con «Gestionar " +
          "biblioteca» (o en registry/loras.json) con familia anima"
      )
    );
    return;
  }
  const items = state.loras.filter((lora) => {
    if (!query) {
      return true;
    }
    const haystack = [lora.id, lora.display_name || "", lora.trigger || ""]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
  if (!items.length) {
    container.appendChild(emptyLoraMessage("Sin resultados."));
    return;
  }
  for (const lora of items) {
    const row = document.createElement("div");
    row.className = "lora-option";
    const label = document.createElement("label");
    label.className = "lora-check";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.loraId = lora.id;
    const name = document.createElement("span");
    name.textContent = lora.display_name || lora.id;
    name.title = lora.trigger ? `${lora.id} · trigger: ${lora.trigger}` : lora.id;
    label.append(check, name);
    const weightBox = document.createElement("div");
    weightBox.className = "lora-weight";
    const weight = document.createElement("input");
    weight.type = "range";
    weight.min = "0";
    weight.max = "2";
    weight.step = "0.05";
    weight.dataset.loraWeight = lora.id;
    const stored = state.loraSelection.has(lora.id)
      ? Number(state.loraSelection.get(lora.id))
      : Number(lora.default_weight);
    weight.value = String(Number.isFinite(stored) ? stored : lora.default_weight);
    const value = document.createElement("output");
    value.className = "lora-weight-value";
    value.textContent = Number(weight.value).toFixed(2);
    check.checked = state.loraSelection.has(lora.id);
    check.addEventListener("change", () => {
      setLoraSelected(lora.id, check.checked, weight.value);
    });
    weight.addEventListener("input", () => {
      value.textContent = Number(weight.value).toFixed(2);
      if (state.loraSelection.has(lora.id)) {
        state.loraSelection.set(lora.id, Number(weight.value));
        renderLoraChips();
        updateLoraCounters();
      }
    });
    weightBox.append(weight, value);
    row.append(label, weightBox);
    container.appendChild(row);
    state.loraControls[lora.id] = { check, weight, value };
  }
}

function renderLoras() {
  renderLoraChips();
  updateLoraCounters();
  renderLoraModalList();
}

function openLoraModal() {
  const modal = $("lora-modal");
  if (!modal) {
    console.error("lora: falta #lora-modal (¿UI desactualizada?)");
    return;
  }
  const search = $("lora-search");
  if (search) {
    search.value = "";
  }
  renderLoraModalList();
  updateLoraCounters();
  modal.classList.remove("hidden");
}

function closeLoraModal() {
  const modal = $("lora-modal");
  if (modal) {
    modal.classList.add("hidden");
  }
}

function clearLoraSelection() {
  state.loraSelection = new Map();
  renderLoraModalList();
  renderLoraChips();
  updateLoraCounters();
}

function readLorasPayload() {
  const selection = [];
  for (const lora of state.loras) {
    if (!state.loraSelection.has(lora.id)) {
      continue;
    }
    const weight = Number(state.loraSelection.get(lora.id));
    selection.push({
      id: lora.id,
      weight: Number.isFinite(weight) ? weight : lora.default_weight,
    });
  }
  return selection;
}

function applyLorasSelection(loras) {
  const known = new Set(state.loras.map((lora) => lora.id));
  state.loraSelection = new Map();
  for (const item of loras || []) {
    if (!item || typeof item.id !== "string" || !known.has(item.id)) {
      continue;
    }
    const lora = loraById(item.id);
    const wanted = clampLoraWeight(item.weight);
    state.loraSelection.set(
      item.id,
      wanted == null ? Number(lora.default_weight) : wanted
    );
  }
  for (const lora of state.loras) {
    syncLoraControls(lora.id);
  }
  renderLoraChips();
  updateLoraCounters();
}

function setLoraLibraryStatus(text, isError = false) {
  const el = $("lora-library-status");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function loraLibraryEntry(loraId) {
  return state.loraLibrary.find((lora) => lora.id === loraId) || null;
}

function loraLibraryRow(lora) {
  const row = document.createElement("div");
  row.className = "oc-item";
  const header = document.createElement("div");
  header.className = "oc-item-header";
  const title = document.createElement("strong");
  title.textContent = lora.display_name || lora.id;
  const badge = document.createElement("span");
  badge.className = "oc-item-badge";
  badge.textContent = lora.family;
  header.append(title, badge);
  const meta = document.createElement("div");
  meta.className = "oc-item-tags";
  const bits = [`@ ${Number(lora.default_weight).toFixed(2)}`, `id: ${lora.id}`];
  if (lora.trigger) {
    bits.push(`trigger: ${lora.trigger}`);
  }
  if (lora.notes) {
    bits.push(lora.notes);
  }
  meta.textContent = bits.join(" · ");
  const file = document.createElement("div");
  file.className = "oc-item-tags";
  file.textContent = lora.file;
  const actions = document.createElement("div");
  actions.className = "oc-item-actions";
  const edit = document.createElement("button");
  edit.type = "button";
  edit.textContent = "Editar";
  edit.addEventListener("click", () => editLoraEntry(lora.id));
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Borrar";
  remove.addEventListener("click", () => {
    deleteLoraEntry(lora.id).catch((error) =>
      setLoraLibraryStatus(error.message, true)
    );
  });
  const removeFile = document.createElement("button");
  removeFile.type = "button";
  removeFile.className = "danger btn-lora-delete-file";
  removeFile.textContent = "Borrar + archivo";
  removeFile.addEventListener("click", () => {
    deleteLoraEntry(lora.id, { withFile: true }).catch((error) =>
      setLoraLibraryStatus(error.message, true)
    );
  });
  actions.append(edit, remove, removeFile);
  row.append(header, meta, file, actions);
  return row;
}

function renderLoraLibrary() {
  const container = $("lora-library-list");
  if (!container) {
    return;
  }
  container.replaceChildren();
  if (!state.loraLibrary.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin LoRAs registradas.";
    container.appendChild(empty);
    return;
  }
  for (const lora of state.loraLibrary) {
    container.appendChild(loraLibraryRow(lora));
  }
}

async function loadLoraLibrary() {
  const data = await api("/api/loras");
  state.loraLibrary = data.items || [];
  renderLoraLibrary();
  return data;
}

function resetLoraForm() {
  state.loraEditId = null;
  const form = $("lora-library-form");
  if (form) {
    form.reset();
  }
  const title = $("lora-library-form-title");
  if (title) {
    title.textContent = "Añadir LoRA";
  }
  const idInput = $("lora-form-id");
  if (idInput) {
    idInput.disabled = false;
  }
  const cancel = $("btn-lora-form-cancel");
  if (cancel) {
    cancel.classList.add("hidden");
  }
}

function editLoraEntry(loraId) {
  const lora = loraLibraryEntry(loraId);
  if (!lora) {
    return;
  }
  state.loraEditId = lora.id;
  $("lora-form-id").value = lora.id;
  $("lora-form-id").disabled = true;
  $("lora-form-family").value = lora.family;
  $("lora-form-file").value = lora.file;
  $("lora-form-display").value = lora.display_name;
  $("lora-form-trigger").value = lora.trigger || "";
  $("lora-form-weight").value = String(lora.default_weight);
  $("lora-form-source").value = lora.source;
  $("lora-form-license").value = lora.license;
  $("lora-form-notes").value = lora.notes || "";
  $("lora-library-form-title").textContent = `Editar «${lora.id}»`;
  $("btn-lora-form-cancel").classList.remove("hidden");
  setLoraLibraryStatus(`Editando ${lora.id} (id inmutable)`);
}

function readLoraForm() {
  const rawWeight = $("lora-form-weight").value;
  return {
    id: state.loraEditId || $("lora-form-id").value.trim(),
    family: $("lora-form-family").value.trim(),
    file: $("lora-form-file").value.trim(),
    display_name: $("lora-form-display").value.trim(),
    trigger: $("lora-form-trigger").value.trim(),
    default_weight: rawWeight === "" ? 1 : Number(rawWeight),
    source: $("lora-form-source").value.trim(),
    license: $("lora-form-license").value.trim(),
    notes: $("lora-form-notes").value,
  };
}

async function saveLoraEntry(event) {
  event.preventDefault();
  const payload = readLoraForm();
  if (
    !payload.id ||
    !payload.family ||
    !payload.file ||
    !payload.display_name ||
    !payload.source ||
    !payload.license
  ) {
    setLoraLibraryStatus(
      "Id, familia, archivo, nombre visible, fuente y licencia son obligatorios.",
      true
    );
    return;
  }
  try {
    if (state.loraEditId) {
      const data = await putJson(
        `/api/loras/${encodeURIComponent(state.loraEditId)}`,
        payload
      );
      setLoraLibraryStatus(`LoRA «${data.item.id}» actualizada`);
    } else {
      const data = await postJson("/api/loras", payload);
      setLoraLibraryStatus(`LoRA «${data.item.id}» añadida`);
    }
    resetLoraForm();
    await loadLoraLibrary();
    await loadLoras();
  } catch (error) {
    setLoraLibraryStatus(error.message, true);
  }
}

async function deleteLoraEntry(loraId, options = {}) {
  const withFile = Boolean(options.withFile);
  const lora = loraLibraryEntry(loraId);
  const label = lora ? lora.display_name || lora.id : loraId;
  const question = withFile
    ? `¿Borrar «${label}» del registro y ELIMINAR su archivo .safetensors? Esta acción no se puede deshacer.`
    : `¿Quitar «${label}» del registro? El archivo .safetensors NO se borra.`;
  if (!window.confirm(question)) {
    return;
  }
  const query = withFile ? "?file=1" : "";
  const data = await api(
    `/api/loras/${encodeURIComponent(loraId)}${query}`,
    { method: "DELETE" }
  );
  if (state.loraEditId === loraId) {
    resetLoraForm();
  }
  await loadLoraLibrary();
  await loadLoras();
  if (!withFile) {
    setLoraLibraryStatus(`LoRA «${loraId}» quitada del registro (archivo intacto)`);
    return;
  }
  setLoraLibraryStatus(
    data.file_removed
      ? `LoRA «${loraId}» y su archivo eliminados`
      : `LoRA «${loraId}» quitada del registro (el archivo ya no existía)`
  );
}

async function uploadLoraFile() {
  const input = $("lora-upload");
  const file = input && input.files ? input.files[0] : null;
  if (!file) {
    setLoraLibraryStatus("Elige un archivo .safetensors para cargar", true);
    return;
  }
  setLoraLibraryStatus("Subiendo y registrando…");
  try {
    const payload = {
      filename: file.name,
      family: $("lora-form-family").value.trim() || "anima",
      file_b64: await readFileBase64(file),
    };
    const displayName = $("lora-form-display").value.trim();
    if (displayName) {
      payload.display_name = displayName;
    }
    const trigger = $("lora-form-trigger").value.trim();
    if (trigger) {
      payload.trigger = trigger;
    }
    const data = await postJson("/api/loras/upload", payload);
    if (input) {
      input.value = "";
    }
    await loadLoraLibrary();
    await loadLoras();
    const inferred = data.trigger_inferido
      ? ` · trigger: ${data.trigger_inferido}`
      : "";
    setLoraLibraryStatus(`Registrado ✓ («${data.item.id}»${inferred})`);
  } catch (error) {
    setLoraLibraryStatus(error.message, true);
  }
}

function openLoraLibrary() {
  closeLoraModal();
  resetLoraForm();
  $("lora-library-modal").classList.remove("hidden");
  setLoraLibraryStatus("Listo");
  loadLoraLibrary().catch((error) => setLoraLibraryStatus(error.message, true));
}

function closeLoraLibrary() {
  const modal = $("lora-library-modal");
  if (modal) {
    modal.classList.add("hidden");
  }
}


function initLoras() {
  on("btn-lora-modal", "click", openLoraModal);
  on("btn-lora-close", "click", closeLoraModal);
  on("btn-lora-done", "click", closeLoraModal);
  on("btn-lora-clear", "click", clearLoraSelection);
  on("lora-search", "input", renderLoraModalList);
  on("lora-modal", "click", (event) => {
    if (event.target === $("lora-modal")) {
      closeLoraModal();
    }
  });
  on("btn-lora-manage", "click", openLoraLibrary);
  on("btn-lora-manage-modal", "click", openLoraLibrary);
  on("btn-lora-library-close", "click", closeLoraLibrary);
  on("btn-lora-form-cancel", "click", resetLoraForm);
  on("btn-lora-upload", "click", () => {
    $("lora-upload").click();
  });
  on("lora-upload", "change", () => {
    uploadLoraFile().catch((error) => setLoraLibraryStatus(error.message, true));
  });
  on("lora-library-form", "submit", saveLoraEntry);
  on("lora-library-modal", "click", (event) => {
    if (event.target === $("lora-library-modal")) {
      closeLoraLibrary();
    }
  });
}

export {
  loadLoras,
  loraById,
  clampLoraWeight,
  emptyLoraMessage,
  renderLoraChips,
  updateLoraCounters,
  syncLoraControls,
  setLoraSelected,
  selectLora,
  renderLoraModalList,
  renderLoras,
  openLoraModal,
  closeLoraModal,
  clearLoraSelection,
  readLorasPayload,
  applyLorasSelection,
  setLoraLibraryStatus,
  loraLibraryEntry,
  loraLibraryRow,
  renderLoraLibrary,
  loadLoraLibrary,
  resetLoraForm,
  editLoraEntry,
  readLoraForm,
  saveLoraEntry,
  deleteLoraEntry,
  uploadLoraFile,
  openLoraLibrary,
  closeLoraLibrary,
  initLoras,
};
