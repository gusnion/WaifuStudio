import { state } from "../state.js";
import { $ } from "../dom.js";
import { postJson, pollJob } from "../api.js";

function setEditorStatus(message, error = false) {
  const element = $("editor-status");
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("error", Boolean(error));
}

const VIEWS = {
  4: ["front", "left", "back", "right"],
  6: ["front", "front-left", "left", "back", "right", "front-right"],
  8: ["front", "front-left", "left", "back-left", "back", "back-right", "right", "front-right"],
};

export function multiviewPrompts(basePrompt, count = 8) {
  const views = VIEWS[count] || VIEWS[8];
  const base = (basePrompt || "character turnaround, full body, neutral background").trim();
  return views.map((view) => `${base}, ${view} view, same character, same outfit, consistent proportions`);
}

function resultUrl(job) {
  const out = (job.outputs || [])[0];
  if (!out) return "";
  if (typeof out === "string") return job.gen_id ? `/media/${job.gen_id}/${out}` : "";
  if (out.url) return out.url;
  return out.name && job.gen_id ? `/media/${job.gen_id}/${out.name}` : "";
}

function renderSheet(entries) {
  const box = $("editor-multiview-results");
  if (!box) return;
  box.replaceChildren();
  for (const entry of entries) {
    const figure = document.createElement("figure");
    const img = document.createElement("img");
    img.src = entry.url;
    img.alt = entry.view;
    const caption = document.createElement("figcaption");
    caption.textContent = `${entry.view} · seed ${entry.seed}`;
    figure.append(img, caption);
    box.appendChild(figure);
  }
  const manifest = document.createElement("a");
  manifest.href = URL.createObjectURL(
    new Blob([JSON.stringify(entries, null, 2)], { type: "application/json" })
  );
  manifest.download = "multiview-manifest.json";
  manifest.textContent = "Descargar manifiesto JSON";
  manifest.className = "btn-link";
  box.appendChild(manifest);
  box.classList.remove("hidden");
}

export function initEditorMultiview() {
  const button = $("btn-editor-multiview");
  if (!button) return;
  button.addEventListener("click", async () => {
    if (!state.editorLicenseAccepted) {
      setEditorStatus("Acepta la licencia de Qwen-Image 2.1 antes de generar vistas", true);
      return;
    }
    if (!state.editorRefs.length) {
      setEditorStatus("Añade al menos una referencia para la multivista", true);
      return;
    }
    const count = Number($("editor-multiview-views")?.value || 8);
    const prompts = multiviewPrompts($("editor-prompt")?.value || "", count);
    const seed = Number($("editor-seed")?.value || 42);
    const steps = Number($("editor-steps")?.value || 25);
    const cfg = Number($("editor-cfg")?.value || 1.0);
    button.disabled = true;
    setEditorStatus(`Generando ${prompts.length} vistas con seed ${seed}…`);
    const entries = [];
    try {
      for (const [index, prompt] of prompts.entries()) {
        const payload = {
          prompt,
          mode: "generate",
          negative: $("editor-negative")?.value || "",
          steps,
          cfg,
          size: { original: true },
          seed,
          preserve_structure: false,
          ref_images_b64: state.editorRefs.map((ref) => ref.b64),
        };
        const job = await postJson("/api/editor/generate", payload);
        await new Promise((resolve, reject) => {
          pollJob(
            job.job_id,
            (message) => setEditorStatus(`Vista ${index + 1}/${prompts.length}: ${message}`),
            (done) => {
              const url = resultUrl(done);
              if (!url) {
                reject(new Error(done.error || "La vista no devolvió imagen"));
                return;
              }
              entries.push({ view: VIEWS[count][index], seed, job_id: job.job_id, url });
              resolve();
            },
            () => {},
            false
          ).catch(reject);
        });
      }
      renderSheet(entries);
      setEditorStatus(`Hoja de contacto lista (${entries.length} vistas)`);
    } catch (error) {
      setEditorStatus(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}
