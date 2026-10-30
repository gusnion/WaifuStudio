// WaifuStudio — Selector y Biblioteca de LoRAs
// Qué hace: modal de selección de LoRAs, ajuste de pesos y CRUD de biblioteca.
// Qué no hace: no aplica pesos al sampling ni ejecuta el pipeline de inferencia.
// Dependencias: static/js/state.js, static/js/dom.js y static/js/api.js.

import { state } from "../state.js";
import { $, on, setStatus, setEditorStatus, readFileBase64 } from "../dom.js";
import { api, postJson, putJson } from "../api.js";

function getLoraCompatibility(lora) {
  const modelSub = String(state.subfamily || "").trim().toLowerCase();
  const loraSub = String(lora.subfamily || "").trim().toLowerCase();
  const modelHasSub = Boolean(modelSub && modelSub !== "sin_clasificar");
  const loraHasSub = Boolean(loraSub && loraSub !== "sin_clasificar");

  if (modelHasSub && loraHasSub) {
    if (modelSub === loraSub) {
      return { isMatch: true, isMismatch: false, isUnverified: false, warning: null };
    }
    return {
      isMatch: false,
      isMismatch: true,
      isUnverified: false,
      warning: `Incompatible (${loraSub} vs ${modelSub})`,
    };
  }
  return {
    isMatch: true,
    isMismatch: false,
    isUnverified: true,
    warning: "Compatibilidad no verificada",
  };
}

function ensureToggleElements() {
  // 1. En #section-loras .lora-actions (Pestaña Imagen)
  const actions = document.querySelector("#section-loras .lora-actions");
  if (actions && !$("lora-toggle-all-container")) {
    const wrap = document.createElement("label");
    wrap.id = "lora-toggle-all-container";
    wrap.className = "lora-toggle-label";
    wrap.style.display = "inline-flex";
    wrap.style.alignItems = "center";
    wrap.style.gap = "6px";
    wrap.style.fontSize = "0.85rem";
    wrap.style.cursor = "pointer";
    wrap.style.marginLeft = "auto";
    wrap.title = "Desactiva el filtro por subrama y muestra todas las LoRAs";

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.id = "lora-toggle-all";
    chk.checked = Boolean(state.lorasShowAll);
    chk.addEventListener("change", (e) => onToggleAllChanged(e.target.checked));

    const txt = document.createElement("span");
    txt.textContent = "Ver todas";

    wrap.append(chk, txt);
    actions.appendChild(wrap);
  }

  // 2. En #lora-modal .lora-body (Modal Elegir LoRAs)
  const searchInput = $("lora-search");
  if (searchInput && !$("lora-modal-toggle-all-container")) {
    const wrap = document.createElement("label");
    wrap.id = "lora-modal-toggle-all-container";
    wrap.className = "lora-toggle-label";
    wrap.style.display = "inline-flex";
    wrap.style.alignItems = "center";
    wrap.style.gap = "6px";
    wrap.style.fontSize = "0.85rem";
    wrap.style.cursor = "pointer";
    wrap.style.margin = "6px 0 10px 0";
    wrap.title = "Desactiva el filtro por subrama y muestra todas las LoRAs";

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.id = "lora-modal-toggle-all";
    chk.checked = Boolean(state.lorasShowAll);
    chk.addEventListener("change", (e) => onToggleAllChanged(e.target.checked));

    const txt = document.createElement("span");
    txt.textContent = "Ver todas";

    wrap.append(chk, txt);
    searchInput.parentNode.insertBefore(wrap, searchInput.nextSibling);
  }

  const c1 = $("lora-toggle-all");
  if (c1) c1.checked = Boolean(state.lorasShowAll);
  const c2 = $("lora-modal-toggle-all");
  if (c2) c2.checked = Boolean(state.lorasShowAll);
}

async function onToggleAllChanged(checked) {
  state.lorasShowAll = Boolean(checked);
  ensureToggleElements();
  await loadLoras({ preserveSelection: true });
}

const EDITOR_ONLY_LORA_FAMILIES = new Set([
  "qwen",
  "qwen-image",
  "qwen_image",
  "editor",
]);
const VIDEO_ONLY_LORA_FAMILIES = new Set(["wan", "lightx2v", "h3", "minimax"]);

function isEditorOnlyLora(lora) {
  if (!lora || typeof lora !== "object") return false;
  const fam = String(lora.family || "").trim().toLowerCase();
  if (EDITOR_ONLY_LORA_FAMILIES.has(fam)) return true;
  const file = String(lora.file || "").trim().toLowerCase();
  return /^(qwen|qwen-image|qwen_image|editor)[\\/]/i.test(file);
}

async function loadLoras(options = {}) {
  const family = state.family || "anima";
  const subfamily = state.subfamily || "";
  const showAll = Boolean(state.lorasShowAll);
  const previousSelection =
    options && options.preserveSelection && state.loraSelection instanceof Map
      ? new Map(state.loraSelection)
      : null;
  const query = new URLSearchParams({
    family,
    scan: "1",
  });
  if (subfamily) {
    query.set("subfamily", subfamily);
  }
  if (showAll) {
    query.set("all", "1");
  }
  const data = await api(
    `/api/loras?${query.toString()}`
  );
  const rawItems = data.items || [];
  state.loras = showAll
    ? rawItems
    : rawItems.filter(
        (item) =>
          !isEditorOnlyLora(item) &&
          !VIDEO_ONLY_LORA_FAMILIES.has(String(item?.family || "").toLowerCase())
      );
  if (previousSelection) {
    const validIds = new Set(state.loras.map((l) => l.id));
    const nextSelection = new Map();
    for (const [id, weight] of previousSelection.entries()) {
      if (validIds.has(id)) {
        nextSelection.set(id, weight);
      }
    }
    state.loraSelection = nextSelection;
  } else {
    state.loraSelection = new Map();
  }
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
  ensureToggleElements();
  const container = $("loras-list");
  if (!container) {
    return;
  }
  container.replaceChildren();
  if (!state.loras.length) {
    const fam = state.family || "anima";
    const famLabel = fam === "anima" ? "Anima" : fam.toUpperCase();
    container.appendChild(
      emptyLoraMessage(
        `No hay LoRAs de imagen registradas compatibles con ${famLabel}. Usa «Cargar LoRA», añádelas en models/loras o con «Gestionar biblioteca».`
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

    const compat = getLoraCompatibility(lora);
    let title = `${lora.id} @ ${weight.toFixed(2)}`;
    if (compat.isMismatch) {
      title += ` · ${compat.warning}`;
    } else if (compat.isUnverified) {
      title += " · Compatibilidad no verificada";
    }
    name.title = title;

    const value = document.createElement("span");
    value.className = "lora-chip-weight";
    value.textContent = `@ ${weight.toFixed(2)}`;

    chip.appendChild(name);
    if (compat.isMismatch) {
      const warn = document.createElement("span");
      warn.className = "lora-chip-warn";
      warn.style.color = "var(--color-danger, #e74c3c)";
      warn.style.marginLeft = "4px";
      warn.title = compat.warning;
      warn.textContent = "⚠️";
      chip.appendChild(warn);
    } else if (compat.isUnverified) {
      const warn = document.createElement("span");
      warn.className = "lora-chip-warn";
      warn.style.color = "var(--color-warning, #e67e22)";
      warn.style.marginLeft = "4px";
      warn.title = "Compatibilidad no verificada";
      warn.textContent = "⚠️";
      chip.appendChild(warn);
    }
    chip.appendChild(value);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "lora-chip-remove";
    remove.textContent = "×";
    remove.title = "Quitar";
    remove.addEventListener("click", () => setLoraSelected(lora.id, false));
    chip.appendChild(remove);

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
  ensureToggleElements();
  const container = $("lora-options");
  if (!container) {
    return;
  }
  const search = $("lora-search");
  const query = (search ? search.value : "").trim().toLowerCase();
  container.replaceChildren();
  state.loraControls = {};
  if (!state.loras.length) {
    const fam = state.family || "anima";
    const famLabel = fam === "anima" ? "Anima" : fam.toUpperCase();
    container.appendChild(
      emptyLoraMessage(
        `No hay LoRAs registradas compatibles con ${famLabel}. Activa «Ver todas» o añádelas con «Cargar LoRA» / «Gestionar biblioteca».`
      )
    );
    return;
  }
  const items = state.loras.filter((lora) => {
    if (!query) {
      return true;
    }
    const haystack = [lora.id, lora.display_name || "", lora.trigger || "", lora.subfamily || ""]
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
    if (lora.image) {
      const thumb = document.createElement("img");
      thumb.className = "lora-thumb";
      thumb.src = lora.image;
      thumb.alt = lora.display_name || lora.id;
      thumb.loading = "lazy";
      thumb.addEventListener("error", () => thumb.classList.add("broken"));
      row.appendChild(thumb);
    } else {
      const thumb = document.createElement("div");
      thumb.className = "lora-thumb lora-thumb-placeholder";
      thumb.textContent = "Sin miniatura";
      row.appendChild(thumb);
    }
    const label = document.createElement("label");
    label.className = "lora-check";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.loraId = lora.id;
    const name = document.createElement("span");
    name.textContent = lora.display_name || lora.id;

    const compat = getLoraCompatibility(lora);
    let title = lora.trigger ? `${lora.id} · trigger: ${lora.trigger}` : lora.id;
    if (compat.isMismatch) {
      title += ` · ${compat.warning}`;
    } else if (compat.isUnverified) {
      title += " · Compatibilidad no verificada";
    }
    name.title = title;

    if (lora.subfamily && lora.subfamily !== "sin_clasificar") {
      const badge = document.createElement("span");
      badge.className = "oc-item-badge";
      badge.style.fontSize = "0.75rem";
      badge.style.marginLeft = "6px";
      badge.textContent = lora.subfamily;
      name.appendChild(document.createTextNode(" "));
      name.appendChild(badge);
    }

    if (compat.isMismatch) {
      const warnBadge = document.createElement("span");
      warnBadge.className = "lora-warn-badge error";
      warnBadge.style.fontSize = "0.75rem";
      warnBadge.style.color = "var(--color-danger, #e74c3c)";
      warnBadge.style.marginLeft = "6px";
      warnBadge.textContent = "(incompatible)";
      warnBadge.title = compat.warning;
      name.appendChild(document.createTextNode(" "));
      name.appendChild(warnBadge);
    } else if (compat.isUnverified) {
      const warnBadge = document.createElement("span");
      warnBadge.className = "lora-warn-badge";
      warnBadge.style.fontSize = "0.75rem";
      warnBadge.style.color = "var(--color-warning, #e67e22)";
      warnBadge.style.marginLeft = "6px";
      warnBadge.textContent = "(compatibilidad no verificada)";
      warnBadge.title = "Falta subrama en el modelo o en la LoRA: compatibilidad no verificada";
      name.appendChild(document.createTextNode(" "));
      name.appendChild(warnBadge);
    }

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
    const info = document.createElement("button");
    info.type = "button";
    info.className = "secondary lora-info-btn";
    info.textContent = "Ficha";
    info.title = "Ver imagen, descripción y triggers";
    info.addEventListener("click", () => {
      openLoraCard(lora.id).catch((error) => setStatus(error.message, true));
    });
    row.append(label, weightBox, info);
    container.appendChild(row);
    state.loraControls[lora.id] = { check, weight, value };
  }
}

function renderLoras() {
  ensureToggleElements();
  const badge = $("lora-modal-family-badge");
  if (badge) {
    const fam = state.family || "anima";
    badge.textContent = fam === "anima" ? "Anima" : fam.toUpperCase();
  }
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
  const badge = $("lora-modal-family-badge");
  if (badge) {
    const fam = state.family || "anima";
    badge.textContent = fam === "anima" ? "Anima" : fam.toUpperCase();
  }
  renderLoraModalList();
  updateLoraCounters();
  modal.classList.remove("hidden");
  loadLoras({ preserveSelection: true })
    .then(() => {
      window.dispatchEvent(new CustomEvent("waifu:models-refresh"));
    })
    .catch((error) => {
      console.warn("lora scan:", error);
    });
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
  const data = await api("/api/loras?scan=1");
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
  $("lora-form-description").value = lora.description || "";
  $("lora-form-image").value = lora.image || "";
  $("lora-form-url").value = lora.url || "";
  $("lora-form-triggers").value = (Array.isArray(lora.triggers) ? lora.triggers : []).join(", ");
  $("lora-form-recommended").value = String(lora.recommended_weight ?? lora.default_weight ?? 1);
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
    description: $("lora-form-description").value.trim(),
    image: $("lora-form-image").value.trim(),
    url: $("lora-form-url").value.trim(),
    triggers: $("lora-form-triggers").value.split(",").map((t) => t.trim()).filter(Boolean),
    recommended_weight: Number($("lora-form-recommended").value),
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
    await loadLoras({ preserveSelection: true });
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
  await loadLoras({ preserveSelection: true });
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

function parseSafetensorsHeaderFromBase64(fileB64) {
  const clean = String(fileB64 || "").replace(/\s+/g, "");
  const b64 =
    clean.startsWith("data:") && clean.includes(",")
      ? clean.split(",", 2)[1]
      : clean;
  if (!b64 || b64.length < 12) {
    return null;
  }
  try {
    const prefix8 = atob(b64.slice(0, 12));
    if (prefix8.length < 8) {
      return null;
    }
    const lo =
      (prefix8.charCodeAt(0) |
        (prefix8.charCodeAt(1) << 8) |
        (prefix8.charCodeAt(2) << 16) |
        (prefix8.charCodeAt(3) << 24)) >>>
      0;
    const hi =
      (prefix8.charCodeAt(4) |
        (prefix8.charCodeAt(5) << 8) |
        (prefix8.charCodeAt(6) << 16) |
        (prefix8.charCodeAt(7) << 24)) >>>
      0;
    const hlen = hi * 0x100000000 + lo;
    if (!Number.isFinite(hlen) || hlen <= 0 || hlen > 32 * 1024 * 1024) {
      return null;
    }
    const totalBytes = 8 + hlen;
    const neededChars = Math.ceil(totalBytes / 3) * 4;
    if (b64.length < neededChars) {
      return null;
    }
    const rawSlice = atob(b64.slice(0, neededChars));
    if (rawSlice.length < totalBytes) {
      return null;
    }
    const bytes = new Uint8Array(hlen);
    for (let i = 0; i < hlen; i += 1) {
      bytes[i] = rawSlice.charCodeAt(8 + i);
    }
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return parsed;
  } catch (_error) {
    return null;
  }
}

function checkLoraRootCompatibility(header, filename, scope = "image", targetFamily = "") {
  const name = String(filename || "").trim();
  if (!name.toLowerCase().endsWith(".safetensors") || name.toLowerCase() === ".safetensors") {
    return {
      compatible: false,
      family: "",
      reason: "Archivo incompatible de raíz: debe ser un archivo .safetensors.",
    };
  }
  if (!header || typeof header !== "object") {
    return {
      compatible: false,
      family: "",
      reason: "Archivo incompatible de raíz: cabecera .safetensors inválida.",
    };
  }
  const keys = Object.keys(header).filter((k) => k !== "__metadata__");
  const meta =
    header.__metadata__ && typeof header.__metadata__ === "object"
      ? header.__metadata__
      : {};
  const loraMarkers = [
    ".lora_down",
    ".lora_up",
    ".lora_A.",
    ".lora_B.",
    "lora_unet",
    "lora_te",
    "hada_w",
    "lokr_w",
  ];
  const hasLoraKeys = keys.some(
    (k) => loraMarkers.some((m) => k.includes(m)) || k.endsWith(".alpha")
  );
  if (keys.length > 0 && !hasLoraKeys) {
    const isVideoModel = keys.some(
      (k) =>
        k.startsWith("audio_patch_proj.") ||
        k.startsWith("adaln_t_table") ||
        k.startsWith("patch_embedding.") ||
        k.startsWith("time_projection.")
    );
    const isCheckpoint =
      keys.some((k) => k.startsWith("model.diffusion_model.")) &&
      keys.some(
        (k) =>
          k.startsWith("first_stage_model.") ||
          k.startsWith("conditioner.") ||
          k.startsWith("cond_stage_model.")
      );
    const isFullUnet = keys.some(
      (k) =>
        k.startsWith("net.blocks.") ||
        k.startsWith("model.diffusion_model.blocks.") ||
        k.startsWith("diffusion_model.blocks.")
    );
    if (isVideoModel || isCheckpoint || isFullUnet) {
      return {
        compatible: false,
        family: "",
        reason:
          "Archivo incompatible de raíz: el .safetensors es un modelo base o checkpoint, no un LoRA.",
      };
    }
  }

  const arch = String(meta["modelspec.architecture"] || "").toLowerCase();
  const base = String(meta["ss_base_model_version"] || "").toLowerCase();
  const sdName = String(meta["ss_sd_model_name"] || "").toLowerCase();
  const combinedMeta = `${arch} ${base} ${sdName}`.toLowerCase();
  const lowerName = name.toLowerCase();
  const lowerKeys = keys.map((k) => k.toLowerCase());

  let detectedFamily = "";
  if (
    combinedMeta.includes("wan") ||
    combinedMeta.includes("lightx2v") ||
    lowerKeys.some((k) => k.includes("wan"))
  ) {
    detectedFamily = "wan";
  } else if (
    combinedMeta.includes("h3") ||
    combinedMeta.includes("minimax") ||
    lowerName.startsWith("minimax_h3")
  ) {
    detectedFamily = "h3";
  } else if (
    combinedMeta.includes("qwen") ||
    lowerName.includes("qwen") ||
    lowerKeys.some((k) => k.includes("qwen"))
  ) {
    detectedFamily = "qwen";
  } else if (
    combinedMeta.includes("anima") ||
    keys.some(
      (k) =>
        k.startsWith("diffusion_model.blocks.") ||
        k.startsWith("lora_te_layers_") ||
        k.startsWith("net.blocks.")
    )
  ) {
    detectedFamily = "anima";
  } else if (
    combinedMeta.includes("sdxl") ||
    combinedMeta.includes("illustrious") ||
    combinedMeta.includes("pony") ||
    combinedMeta.includes("noobai") ||
    keys.some((k) => k.startsWith("lora_te1_") || k.startsWith("lora_te2_")) ||
    keys.some(
      (k) =>
        k.includes("input_blocks") ||
        k.includes("output_blocks") ||
        k.includes("lora_unet_down_blocks") ||
        k.includes("lora_unet_up_blocks") ||
        k.includes("down_blocks.") ||
        k.includes("up_blocks.")
    )
  ) {
    detectedFamily = "sdxl";
  } else if (
    combinedMeta.includes("sd_v1") ||
    combinedMeta.includes("sd15") ||
    combinedMeta.includes("sd 1.5") ||
    combinedMeta.includes("v1-5") ||
    combinedMeta.includes("flux")
  ) {
    detectedFamily = "unsupported";
  }

  if (detectedFamily === "wan" || detectedFamily === "h3") {
    return {
      compatible: false,
      family: detectedFamily,
      reason: `LoRA incompatible de raíz: pertenece a vídeo (${detectedFamily.toUpperCase()}).`,
    };
  }
  if (detectedFamily === "unsupported") {
    return {
      compatible: false,
      family: detectedFamily,
      reason: "LoRA incompatible de raíz: arquitectura base no soportada.",
    };
  }

  const normalizedScope = String(scope || "image").toLowerCase();
  const wantedFamily = String(
    targetFamily || (normalizedScope === "editor" ? "qwen" : state.family || "anima")
  )
    .trim()
    .toLowerCase();

  if (normalizedScope === "editor") {
    if (detectedFamily && detectedFamily !== "qwen") {
      return {
        compatible: false,
        family: detectedFamily,
        reason: `LoRA incompatible de raíz con Editor (Qwen): detectada familia ${detectedFamily.toUpperCase()}.`,
      };
    }
    return { compatible: true, family: "qwen", reason: null };
  }

  if (normalizedScope === "image") {
    if (detectedFamily === "qwen") {
      return {
        compatible: false,
        family: detectedFamily,
        reason: "LoRA incompatible de raíz con Imagen: el archivo es exclusivo del Editor (Qwen).",
      };
    }
    if (detectedFamily && wantedFamily && detectedFamily !== wantedFamily) {
      return {
        compatible: false,
        family: detectedFamily,
        reason: `LoRA incompatible de raíz con el modelo activo (${detectedFamily.toUpperCase()} vs ${wantedFamily.toUpperCase()}).`,
      };
    }
    return {
      compatible: true,
      family: detectedFamily || wantedFamily || "anima",
      reason: null,
    };
  }

  return {
    compatible: true,
    family: detectedFamily || wantedFamily || "anima",
    reason: null,
  };
}

async function uploadLocalLora(file, options = {}) {
  const scope = options.scope || "image";
  const onStatus =
    typeof options.onStatus === "function"
      ? options.onStatus
      : scope === "editor"
      ? setEditorStatus
      : scope === "library"
      ? setLoraLibraryStatus
      : setStatus;
  const input = options.input || null;

  if (!file) {
    onStatus("Elige un archivo .safetensors para cargar", true);
    return null;
  }

  onStatus("Subiendo y registrando…");
  try {
    const fileB64 = await readFileBase64(file);
    const header = parseSafetensorsHeaderFromBase64(fileB64);
    const targetFamily =
      options.family ||
      (scope === "editor" ? "qwen" : state.family || "anima");
    const rootCompat = checkLoraRootCompatibility(
      header,
      file.name,
      scope,
      targetFamily
    );
    if (!rootCompat.compatible) {
      throw new Error(rootCompat.reason || "LoRA incompatible de raíz");
    }

    const payload = {
      filename: file.name,
      family: rootCompat.family || targetFamily,
      file_b64: fileB64,
    };
    const displayName = options.displayName
      ? String(options.displayName).trim()
      : "";
    if (displayName) {
      payload.display_name = displayName;
    }
    const trigger = options.trigger ? String(options.trigger).trim() : "";
    if (trigger) {
      payload.trigger = trigger;
    }

    const data = await postJson("/api/loras/upload", payload);
    if (input) {
      input.value = "";
    }
    await loadLoraLibrary();
    await loadLoras({ preserveSelection: true });
    if (typeof options.onUploaded === "function") {
      await options.onUploaded(data);
    }
    const inferred = data.trigger_inferido
      ? ` · trigger: ${data.trigger_inferido}`
      : "";
    const statusText = `Registrado ✓ («${data.item.id}»${inferred})`;
    setLoraLibraryStatus(statusText);
    const compat = data && data.item ? getLoraCompatibility(data.item) : null;
    if (scope !== "editor" && compat && compat.isMismatch && compat.warning) {
      onStatus(`${statusText} · ${compat.warning}`, true);
    } else {
      onStatus(statusText);
    }
    window.dispatchEvent(new CustomEvent("waifu:lora-uploaded", { detail: data }));
    return data;
  } catch (error) {
    if (input) {
      input.value = "";
    }
    const rawMsg = String(error?.message || error || "Error al cargar LoRA");
    const msg = /cabecera safetensors invalida/i.test(rawMsg)
      ? `Archivo incompatible de raíz: ${rawMsg}`
      : rawMsg;
    setLoraLibraryStatus(msg, true);
    onStatus(msg, true);
    throw error;
  }
}

function triggerLoraUpload(defaultFamily = null) {
  const familyStr = typeof defaultFamily === "string" ? defaultFamily : "";
  if (familyStr === "qwen") {
    const editorInput = $("editor-lora-import-file");
    if (editorInput) {
      editorInput.click();
      return;
    }
  } else {
    const imageInput = $("lora-import-file");
    if (imageInput) {
      imageInput.click();
      return;
    }
  }
  openLoraLibrary();
  if (familyStr) {
    const familyInput = $("lora-form-family");
    if (familyInput) {
      familyInput.value = familyStr;
    }
  }
  const input = $("lora-upload");
  if (input) {
    input.click();
  }
}

async function uploadLoraFile() {
  const input = $("lora-upload");
  const file = input && input.files ? input.files[0] : null;
  if (!file) {
    setLoraLibraryStatus("Elige un archivo .safetensors para cargar", true);
    return;
  }
  const family = $("lora-form-family")?.value.trim() || "anima";
  const displayName = $("lora-form-display")?.value.trim() || "";
  const trigger = $("lora-form-trigger")?.value.trim() || "";
  try {
    await uploadLocalLora(file, {
      scope: "library",
      family,
      displayName,
      trigger,
      input,
      onStatus: setLoraLibraryStatus,
    });
  } catch (_error) {
    // Error ya reportado por uploadLocalLora
  }
}

function openLoraLibrary() {
  closeLoraModal();
  resetLoraForm();
  $("lora-library-modal").classList.remove("hidden");
  setLoraLibraryStatus("Escaneando carpeta…");
  loadLoraLibrary()
    .then(async () => {
      await loadLoras({ preserveSelection: true });
      window.dispatchEvent(new CustomEvent("waifu:models-refresh"));
      setLoraLibraryStatus("Listo (sincronizado)");
    })
    .catch((error) => setLoraLibraryStatus(error.message, true));
}

function closeLoraLibrary() {
  const modal = $("lora-library-modal");
  if (modal) {
    modal.classList.add("hidden");
  }
}


function enrichModal(title) {
  const modal = $("enrich-modal");
  const titleEl = $("enrich-title");
  const body = $("enrich-body");
  if (!modal || !body) return null;
  if (titleEl) titleEl.textContent = title;
  body.replaceChildren();
  modal.classList.remove("hidden");
  modal.classList.add("enrich-stack");
  return body;
}

function closeEnrichModal() {
  const modal = $("enrich-modal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("enrich-stack");
  }
}

function enrichRow(label, value) {
  const row = document.createElement("p");
  row.className = "enrich-row";
  const strong = document.createElement("strong");
  strong.textContent = `${label}: `;
  row.append(strong, document.createTextNode(value || "—"));
  return row;
}

function openEnrichImage(body, url) {
  if (!url) return;
  const img = document.createElement("img");
  img.className = "enrich-image";
  img.src = url;
  img.alt = "Imagen de la ficha";
  img.loading = "lazy";
  img.addEventListener("error", () => img.remove());
  body.appendChild(img);
}

function insertTrigger(trigger) {
  const value = String(trigger || "").trim();
  if (!value) return;
  const prompt = $("prompt-general");
  const editorPrompt = $("editor-prompt");
  const target = prompt || editorPrompt;
  if (!target) return;
  if (String(target.value || "").includes(value)) {
    setStatus(`El trigger «${value}» ya está en el prompt`);
    return;
  }
  const prev = String(target.value || "").trim();
  target.value = prev ? `${prev}, ${value}` : value;
  target.dispatchEvent(new Event("input", { bubbles: true }));
  setStatus(`Trigger añadido: ${value}`);
}

async function openLoraCard(loraId) {
  const lora = state.loras.find((item) => item.id === loraId);
  if (!lora) return;
  const body = enrichModal(lora.display_name || lora.id);
  if (!body) return;
  openEnrichImage(body, lora.image);
  body.appendChild(enrichRow("ID", lora.id));
  body.appendChild(enrichRow("Familia", lora.family));
  body.appendChild(enrichRow("Subfamilia", lora.subfamily || "sin clasificar"));
  body.appendChild(enrichRow("Descripción", lora.description || "Sin descripción enriquecida"));
  const triggers = Array.isArray(lora.triggers) ? lora.triggers : (lora.trigger ? [lora.trigger] : []);
  body.appendChild(enrichRow("Triggers", triggers.length ? triggers.join(", ") : "sin trigger"));
  body.appendChild(enrichRow("Peso recomendado", String(lora.recommended_weight ?? lora.default_weight ?? "—")));
  body.appendChild(enrichRow("Compatibilidad", getLoraCompatibility(lora).warning || "Compatible / no verificada"));
  if (lora.url) {
    const link = document.createElement("a");
    link.href = lora.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "Fuente del autor";
    body.appendChild(link);
  }
  if (triggers.length) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary";
    button.textContent = "Insertar trigger";
    button.addEventListener("click", () => {
      insertTrigger(triggers[0]);
      closeEnrichModal();
    });
    body.appendChild(button);
  }
}

async function openModelCard(modelId) {
  let models = state.models || [];
  if (!models.length) {
    const data = await api("/api/models");
    models = data.items || data.models || [];
  }
  const model = models.find((item) => item.id === modelId);
  if (!model) return;
  const body = enrichModal(model.display_name || model.id);
  if (!body) return;
  openEnrichImage(body, model.image);
  body.appendChild(enrichRow("ID", model.id));
  body.appendChild(enrichRow("Familia / subfamilia", `${model.family || "—"} / ${model.subfamily || "sin clasificar"}`));
  body.appendChild(enrichRow("Base", model.profile?.unet_name || model.profile?.base_model || "—"));
  body.appendChild(enrichRow("Perfil de prompt", model.prompt_profile || "—"));
  body.appendChild(enrichRow("Preprompt", model.preprompt || "—"));
  body.appendChild(enrichRow("Licencia", model.license || "—"));
  const defaults = model.defaults || {};
  body.appendChild(enrichRow("Resolución", defaults.width && defaults.height ? `${defaults.width}x${defaults.height}` : "—"));
  body.appendChild(enrichRow("Sampler / CFG / pasos", `${defaults.sampler_name || "—"} / ${defaults.cfg ?? "—"} / ${defaults.steps ?? "—"}`));
  body.appendChild(enrichRow("Triggers", (model.triggers || []).join(", ") || "—"));
  if (model.url) {
    const link = document.createElement("a");
    link.href = model.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "Fuente del autor";
    body.appendChild(link);
  }
  if (!model.image && !model.url && !(model.triggers || []).length) {
    const note = document.createElement("p");
    note.className = "field-hint";
    note.textContent = "Ficha sin enriquecer. Pide a tu agente que lea la ficha del autor y complete imagen, URL y triggers.";
    body.appendChild(note);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = "Copiar id para el agente";
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(model.id);
        setStatus(`ID copiado: ${model.id}`);
      } catch (_error) {
        setStatus(`ID: ${model.id}`);
      }
    });
    body.appendChild(button);
  }
}

function initLoras() {
  ensureToggleElements();
  on("btn-enrich-close", "click", closeEnrichModal);
  on("enrich-modal", "click", (event) => {
    if (event.target === $("enrich-modal")) closeEnrichModal();
  });
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
  window.addEventListener("waifu:lora-uploaded", (event) => {
    const item = event && event.detail && event.detail.item;
    openLoraLibrary();
    if (item && item.id) {
      setTimeout(() => editLoraEntry(item.id), 900);
    }
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
  parseSafetensorsHeaderFromBase64,
  checkLoraRootCompatibility,
  uploadLocalLora,
  triggerLoraUpload,
  uploadLoraFile,
  openLoraLibrary,
  closeLoraLibrary,
  openLoraCard,
  openModelCard,
  initLoras,
};
