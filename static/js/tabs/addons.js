let addonsLoaded = false;

function setAddonsStatus(message, error = false) {
  const el = document.getElementById("addons-status");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", Boolean(error));
}

function addonButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

async function loadAddons() {
  const box = document.getElementById("addons-list");
  if (!box) return;
  box.replaceChildren();
  try {
    const response = await fetch("/api/addons", { cache: "no-store" });
    const data = await response.json();
    const items = data.items || [];
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "field-hint";
      empty.textContent = "No hay addons instalados.";
      box.appendChild(empty);
      return;
    }
    for (const item of items) {
      const card = document.createElement("article");
      card.className = "addon-card";
      const title = document.createElement("h3");
      title.textContent = `${item.name || item.id} v${item.version || "?"}`;
      const meta = document.createElement("p");
      meta.className = "field-hint";
      meta.textContent = `${item.id} · ${item.enabled ? "activo" : "desactivado"}${item.reason ? ` · ${item.reason}` : ""}`;
      const actions = document.createElement("div");
      actions.className = "addon-actions";
      if (item.valid) {
        actions.appendChild(
          addonButton(item.enabled ? "Desactivar" : "Activar", async () => {
            const endpoint = item.enabled ? "disable" : "enable";
            const res = await fetch(`/api/addons/${encodeURIComponent(item.id)}/${endpoint}`, { method: "POST" });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) {
              setAddonsStatus(payload.error || "No se pudo cambiar el addon", true);
              return;
            }
            setAddonsStatus(`${item.id}: ${endpoint === "enable" ? "activo" : "desactivado"}`);
            await loadAddons();
          })
        );
      }
      card.append(title, meta, actions);
      box.appendChild(card);
    }
  } catch (error) {
    setAddonsStatus(error.message, true);
  }
}

async function importAddon() {
  const input = document.getElementById("addon-file");
  const file = input?.files?.[0];
  if (!file) {
    setAddonsStatus("Selecciona un .zip", true);
    return;
  }
  const form = file;
  setAddonsStatus("Importando…");
  try {
    const response = await fetch("/api/addons/import", {
      method: "POST",
      headers: { "Content-Type": "application/zip" },
      body: form,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      setAddonsStatus(payload.error || "Import fallido", true);
      return;
    }
    input.value = "";
    setAddonsStatus(`Instalado desactivado: ${payload.addon?.id || ""}`);
    await loadAddons();
  } catch (error) {
    setAddonsStatus(error.message, true);
  }
}

export function initAddons() {
  const input = document.getElementById("addon-file");
  const button = document.getElementById("btn-addon-import");
  if (!input || !button) return;
  input.addEventListener("change", () => {
    button.disabled = !input.files?.length;
  });
  button.addEventListener("click", importAddon);
  if (!addonsLoaded) {
    addonsLoaded = true;
    loadAddons();
  }
}

export { loadAddons };
