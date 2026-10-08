// WaifuStudio — Cliente HTTP y Polling de Trabajos
// api.js: fetch centralizado, postJson, putJson, pollJob, cancelJob.

import { state } from "./state.js";
import { $, setStatus, setVideoStatus, setEditorStatus, setUpscaleStatus } from "./dom.js";

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data = null;
  try {
    data = await response.json();
  } catch (_error) {
    data = null;
  }
  if (!response.ok) {
    throw new Error(data && data.error ? data.error : `HTTP ${response.status}`);
  }
  return data;
}

function postJson(path, payload) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function putJson(path, payload) {
  return api(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}


function setCancelVisible(visible, buttonId = "btn-cancel") {
  $(buttonId).classList.toggle("hidden", !visible);
}

async function cancelJob(event) {
  const jobId = state.activeJobId;
  if (!jobId) {
    return;
  }
  const button = event && event.currentTarget ? event.currentTarget : $("btn-cancel");
  const statusFn =
    button.id === "btn-video-cancel"
      ? setVideoStatus
      : button.id === "btn-upscale-cancel"
      ? setUpscaleStatus
      : setStatus;
  button.disabled = true;
  try {
    await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
    statusFn("Cancelado");
  } catch (error) {
    statusFn(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function pollJob(
  jobId,
  statusFn = setStatus,
  onDone = reloadImageViewerFirstPage,
  progressFn = setProgress,
  manageCancel = true,
  cancelButtonId = "btn-cancel"
) {
  if (manageCancel) {
    state.activeJobId = jobId;
    setCancelVisible(true, cancelButtonId);
  }
  try {
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (job.status === "queued" || job.status === "running") {
        if (progressFn) {
          progressFn(job.progress);
        }
        statusFn(job.status === "running" ? "Generando..." : "En cola...");
        continue;
      }
      if (job.status === "error") {
        statusFn(`Error: ${job.error || "desconocido"}`, true);
        await onDone(job);
        return;
      }
      if (job.status === "cancelled") {
        statusFn("Cancelado");
        await onDone(job);
        return;
      }
      statusFn("Listo");
      await onDone(job);
      return;
    }
  } finally {
    if (manageCancel) {
      state.activeJobId = null;
      setCancelVisible(false, cancelButtonId);
    }
    if (progressFn) {
      progressFn(null);
    }
  }
}


export {
  api,
  postJson,
  putJson,
  setCancelVisible,
  cancelJob,
  pollJob,
};
