// WaifuStudio — Modal y Gestión de Preprompts Personalizados
// Qué hace: modal CRUD para crear, actualizar y borrar preprompts de usuario.
// Qué no hace: no compone el prompt final ni procesa tags del catálogo.
// Dependencias: static/js/dom.js y static/js/api.js.

import { state } from "../state.js";
import { $, on, setStatus, setSelectValue } from "../dom.js";
import { api, postJson } from "../api.js";
import { loadPrepromptOptions, refreshNegative } from "../tabs/image.js";

function setPrepromptStatus(text, isError = false) {
  const el = $("preprompt-status");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function customPrepromptRow(name) {
  const row = document.createElement("div");
  row.className = "oc-item";
  const header = document.createElement("div");
  header.className = "oc-item-header";
  const title = document.createElement("strong");
  title.textContent = `${name} (propio)`;
  header.appendChild(title);
  const actions = document.createElement("div");
  actions.className = "oc-item-actions";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Borrar";
  remove.addEventListener("click", () => {
    deleteCustomPreprompt(name).catch((error) =>
      setPrepromptStatus(error.message, true)
    );
  });
  actions.appendChild(remove);
  row.append(header, actions);
  return row;
}

async function refreshCustomPreprompts() {
  await loadPrepromptOptions();
  const container = $("preprompt-custom-list");
  container.replaceChildren();
  if (!state.customPreprompts.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Sin preprompts propios.";
    container.appendChild(empty);
    return;
  }
  for (const name of state.customPreprompts) {
    container.appendChild(customPrepromptRow(name));
  }
}

async function saveCustomPreprompt(event) {
  event.preventDefault();
  try {
    const data = await postJson("/api/preprompts/custom", {
      name: $("preprompt-form-name").value.trim(),
      positive: $("preprompt-form-positive").value,
      negative: $("preprompt-form-negative").value,
    });
    await refreshCustomPreprompts();
    setSelectValue($("preprompt"), data.name);
    await refreshNegative();
    $("preprompt-form").reset();
    setPrepromptStatus(`Preprompt «${data.name}» guardado (propio)`);
  } catch (error) {
    setPrepromptStatus(error.message, true);
  }
}

async function deleteCustomPreprompt(name) {
  if (!window.confirm(`¿Borrar el preprompt propio «${name}»?`)) {
    return;
  }
  await api(`/api/preprompts/custom/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  await refreshCustomPreprompts();
  await refreshNegative();
  setPrepromptStatus(`Preprompt «${name}» borrado`);
}

function openPrepromptModal() {
  $("preprompt-modal").classList.remove("hidden");
  setPrepromptStatus("Listo");
  refreshCustomPreprompts().catch((error) =>
    setPrepromptStatus(error.message, true)
  );
}

function closePrepromptModal() {
  $("preprompt-modal").classList.add("hidden");
}


function initPreprompts() {
  on("btn-preprompt-manage", "click", openPrepromptModal);
  on("btn-preprompt-close", "click", closePrepromptModal);
  on("preprompt-form", "submit", saveCustomPreprompt);
  on("preprompt-modal", "click", (event) => {
    if (event.target === $("preprompt-modal")) {
      closePrepromptModal();
    }
  });
}

export {
  setPrepromptStatus,
  customPrepromptRow,
  refreshCustomPreprompts,
  saveCustomPreprompt,
  deleteCustomPreprompt,
  openPrepromptModal,
  closePrepromptModal,
  initPreprompts,
};
