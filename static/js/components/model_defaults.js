import { state } from "../state.js";
import { applyModel } from "../tabs/image.js";
import { hideTooltip, showTooltip } from "./tooltip_help.js";

const FIELDS = ["seed", "steps", "cfg", "sampler_name", "scheduler", "width", "height"];

function fieldLabel(name) {
  return { seed: "Seed", steps: "Pasos", cfg: "CFG", sampler_name: "Sampler", scheduler: "Scheduler", width: "Ancho", height: "Alto" }[name] || name;
}

async function saveDefaults(modelId, values) {
  const response = await fetch(`/api/models/${encodeURIComponent(modelId)}/defaults`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "No se pudieron guardar los defaults");
  const model = state.models.find((item) => item.id === modelId);
  if (model) model.defaults = { ...(model.defaults || {}), ...payload.defaults };
  await applyModel(modelId);
}

function openDefaults(modelId) {
  const model = state.models.find((item) => item.id === modelId);
  if (!model) return;
  const defaults = model.defaults || {};
  const overlay = document.createElement("div");
  overlay.className = "modal model-defaults-modal";
  const box = document.createElement("div");
  box.className = "modal-box";
  const header = document.createElement("div");
  header.className = "modal-header";
  const title = document.createElement("h2");
  title.textContent = `Defaults · ${model.display_name || model.id}`;
  header.appendChild(title);
  const body = document.createElement("div");
  body.className = "model-defaults-body";
  const card = document.createElement("fieldset");
  card.className = "control-card";
  const legend = document.createElement("legend");
  legend.append("Valores por defecto");
  const help = document.createElement("button");
  help.type = "button";
  help.className = "btn-help";
  help.textContent = "?";
  help.dataset.help = "Valores iniciales que se aplican al elegir este modelo. Los campos vacíos no se guardan.";
  help.addEventListener("mouseenter", () => showTooltip(help, help.dataset.help));
  help.addEventListener("mouseleave", () => hideTooltip());
  help.addEventListener("focus", () => showTooltip(help, help.dataset.help));
  help.addEventListener("blur", () => hideTooltip());
  help.addEventListener("click", (event) => {
    event.preventDefault();
    showTooltip(help, help.dataset.help);
  });
  legend.appendChild(help);
  const form = document.createElement("div");
  form.className = "grid-2";
  card.append(legend, form);
  const inputs = {};
  for (const name of FIELDS) {
    const label = document.createElement("label");
    label.className = "field";
    const span = document.createElement("span");
    span.textContent = fieldLabel(name);
    const input = document.createElement("input");
    input.type = name === "cfg" ? "number" : name === "sampler_name" || name === "scheduler" ? "text" : "number";
    if (name === "cfg") input.step = "0.1";
    input.value = defaults[name] ?? "";
    inputs[name] = input;
    label.append(span, input);
    form.appendChild(label);
  }
  const status = document.createElement("p");
  status.className = "status";
  const actions = document.createElement("div");
  actions.className = "modal-footer";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "secondary";
  cancel.textContent = "Cancelar";
  cancel.addEventListener("click", () => overlay.remove());
  const save = document.createElement("button");
  save.type = "button";
  save.className = "primary";
  save.textContent = "Guardar defaults";
  save.addEventListener("click", async () => {
    const values = {};
    for (const [name, input] of Object.entries(inputs)) {
      if (input.value === "") continue;
      values[name] = input.type === "number" ? Number(input.value) : input.value;
    }
    save.disabled = true;
    try {
      await saveDefaults(modelId, values);
      overlay.remove();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
      save.disabled = false;
    }
  });
  actions.append(cancel, save);
  body.append(card, status);
  box.append(header, body, actions);
  overlay.appendChild(box);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) overlay.remove();
  });
  document.body.appendChild(overlay);
}

export function initModelDefaults() {
  const button = document.getElementById("btn-model-defaults");
  if (!button) return;
  button.addEventListener("click", () => {
    const modelId = document.getElementById("model")?.value;
    if (modelId) openDefaults(modelId);
  });
}
