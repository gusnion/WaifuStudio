// WaifuStudio — Pestaña Estudio / Timeline (M20 T-03b)
// Qué hace: NLE secuencial, preview continua, audio multi-pista y generación IA integrada.
// Dependencias: static/js/api.js y static/js/dom.js.

import { api, postJson, enqueueJobs, cancelJob } from "../api.js";
import { $, on } from "../dom.js";

const state = {
  projects: [],
  current: { id: null, name: "Mi Secuencia", data: { clips: [], audio_tracks: [], width: 1280, height: 720, fps: 24 } },
  selectedIndex: 0,
  isPlayingAll: false,
  playIndex: 0,
  aiGenerating: false,
};
let previewAudioEls = [];
let audioStartTimers = [];
let imageSequenceTimer = null;

function setTimelineStatus(msg, err = false) {
  const el = $("timeline-status");
  if (el) { el.textContent = msg; el.style.color = err ? "#ff5252" : "#aaa"; }
}

function setAiStatus(msg, err = false) {
  const el = $("timeline-ai-status");
  if (el) { el.textContent = msg; el.style.color = err ? "#ff5252" : "var(--accent, #ff4081)"; }
}

function calcTotalDuration() {  const clips = state.current.data.clips || [];
  const total = clips.reduce((acc, c) => acc + (Number(c.duration) || 3.0), 0);
  const durEl = $("timeline-total-duration");
  if (durEl) durEl.textContent = `Duración total: ${total.toFixed(1)}s (${clips.length} clips)`;
  const cntEl = $("timeline-track-count");
  if (cntEl) cntEl.textContent = `${clips.length} clips`;
}

function resolveMediaUrl(item) {
  if (!item) return "";
  if (item.url) return item.url;
  const out = (item.outputs || [])[0];
  const name = typeof out === "string" ? out : out && out.name;
  return name && item.id ? `/media/${item.id}/${name}` : "";
}

/**
 * El primer clip manda el perfil del proyecto. Los clips siguientes se
 * normalizan a ese lienzo; no al reves.
 */
export function applyFirstClipProfile(projectData, item) {
  if (!projectData || !item) return false;
  const p = item.params || {};
  let width = Number(p.width);
  let height = Number(p.height);
  if ((!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) &&
      (p.aspect === "vertical" || p.aspect === "horizontal")) {
    width = p.aspect === "vertical" ? 432 : 768;
    height = p.aspect === "vertical" ? 768 : 432;
  }
  if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
    return false;
  }
  projectData.width = Math.round(width);
  projectData.height = Math.round(height);
  const fps = Number(p.fps);
  if (Number.isFinite(fps) && fps > 0) projectData.fps = Math.round(fps);
  return true;
}

export function clipDurationForItem(item, metadataDuration = null) {
  const isVideo = item && item.kind === "video";
  if (!isVideo) {
    const pDur = Number(item?.params?.duration);
    if (Number.isFinite(pDur) && pDur > 0) return pDur;
    return 3.0;
  }
  const pSec = Number(item?.params?.seconds);
  if (Number.isFinite(pSec) && pSec > 0) return pSec;
  const pDur = Number(item?.params?.duration);
  if (Number.isFinite(pDur) && pDur > 0) return pDur;
  const metaDur = Number(metadataDuration);
  if (Number.isFinite(metaDur) && metaDur > 0) {
    return Math.round(metaDur * 10) / 10;
  }
  return 5.0;
}

function updatePreviewMedia(clip) {
  const video = $("timeline-preview-video");
  let img = $("timeline-preview-image");
  if (!img && video && video.parentNode) {
    img = document.createElement("img");
    img.id = "timeline-preview-image";
    img.style.display = "none";
    img.alt = "Preview clip";
    video.parentNode.insertBefore(img, video.nextSibling);
  }
  if (!clip) {
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.style.display = "none";
    }
    if (img) {
      img.removeAttribute("src");
      img.style.display = "none";
    }
    return;
  }
  if (clip.kind === "image") {
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.style.display = "none";
    }
    if (img) {
      img.setAttribute("src", clip.url);
      img.style.display = "block";
    }
  } else {
    if (img) {
      img.removeAttribute("src");
      img.style.display = "none";
    }
    if (video) {
      video.style.display = "block";
      video.src = clip.url;
      video.muted = Boolean(clip.mute);
      video.currentTime = 0;
    }
  }
}

function selectClip(index) {
  const clips = state.current.data.clips;
  if (index < 0 || index >= clips.length) return;
  state.selectedIndex = index;
  renderTracks();
  const clip = clips[index];
  updatePreviewMedia(clip);
}

function isLocalDiskPath(p) {
  return /^[a-zA-Z]:[\\/]/.test(p) || p.startsWith("\\\\") || (p.includes("\\") && !p.startsWith("/"));
}

export function getPlayableAudioUrl(track) {
  if (!track || typeof track !== "object") return "";
  const rawUrl = typeof track.url === "string" ? track.url.trim() : "";
  if (rawUrl && !isLocalDiskPath(rawUrl)) {
    return rawUrl;
  }
  const rawSource = typeof track.source_path === "string" ? track.source_path.trim() : "";
  if (rawSource && !isLocalDiskPath(rawSource)) {
    return rawSource;
  }
  return "";
}

export function audioSchedule(tracks) {
  if (!Array.isArray(tracks)) return [];
  const schedule = [];
  for (const track of tracks) {
    if (!track || typeof track !== "object") continue;
    if (Boolean(track.mute || track.muted)) continue;
    const url = getPlayableAudioUrl(track);
    if (!url) continue;

    let volume = (track.volume !== null && track.volume !== undefined && track.volume !== "") ? Number(track.volume) : 1.0;
    if (!Number.isFinite(volume)) volume = 1.0;
    volume = Math.max(0, Math.min(volume, 1.0));

    const startTime = Math.max(0, Number(track.start_time) || 0);

    schedule.push({
      url,
      volume,
      startTime,
      immediate: startTime === 0,
      track,
    });
  }
  return schedule;
}

export function stopAudioPlayback() {
  for (const timer of audioStartTimers) {
    clearTimeout(timer);
  }
  audioStartTimers = [];
  for (const audio of previewAudioEls) {
    try {
      audio.pause();
      audio.currentTime = 0;
    } catch (_) {}
  }
  previewAudioEls = [];
}

function stopSequencePlayback() {
  state.isPlayingAll = false;
  if (imageSequenceTimer) {
    clearTimeout(imageSequenceTimer);
    imageSequenceTimer = null;
  }
  const btn = $("btn-timeline-play-all");
  if (btn) btn.textContent = "▶ Reproducir Secuencia";
  stopAudioPlayback();
}

function playNextInSequence() {
  const clips = state.current.data.clips;
  if (!state.isPlayingAll || state.playIndex >= clips.length) { stopSequencePlayback(); return; }
  if (imageSequenceTimer) {
    clearTimeout(imageSequenceTimer);
    imageSequenceTimer = null;
  }
  const clip = clips[state.playIndex];
  state.selectedIndex = state.playIndex;
  renderTracks();
  updatePreviewMedia(clip);
  if (clip.kind === "image") {
    const durMs = Math.max(0.5, Number(clip.duration) || 3.0) * 1000;
    imageSequenceTimer = setTimeout(() => {
      imageSequenceTimer = null;
      if (state.isPlayingAll) { state.playIndex++; playNextInSequence(); }
    }, durMs);
  } else {
    const video = $("timeline-preview-video");
    if (video) {
      video.play().catch(() => {});
    }
  }
}

function togglePlayAll() {
  const clips = state.current.data.clips;
  if (!clips.length) return;
  if (state.isPlayingAll) {
    stopSequencePlayback();
    const video = $("timeline-preview-video");
    if (video) video.pause();
    return;
  }
  state.isPlayingAll = true;
  state.playIndex = 0;
  const btn = $("btn-timeline-play-all");
  if (btn) btn.textContent = "⏸️ Pausar";

  stopAudioPlayback();
  const scheduledTracks = audioSchedule(state.current.data.audio_tracks || []);
  for (const item of scheduledTracks) {
    try {
      const audio = new Audio(item.url);
      try {
        audio.volume = item.volume;
      } catch (_) {}
      previewAudioEls.push(audio);
      if (item.immediate) {
        try {
          const p = audio.play();
          if (p && typeof p.catch === "function") p.catch(() => {});
        } catch (_) {}
      } else {
        const timer = setTimeout(() => {
          if (!state.isPlayingAll) return;
          try {
            const p = audio.play();
            if (p && typeof p.catch === "function") p.catch(() => {});
          } catch (_) {}
        }, item.startTime * 1000);
        audioStartTimers.push(timer);
      }
    } catch (_) {
      // Ignorar fallo de audio individual sin romper los demas
    }
  }

  playNextInSequence();
}

function renderTracks() {
  const container = $("timeline-track-video");
  if (!container) return;
  container.replaceChildren();
  const clips = state.current.data.clips || [];
  if (!clips.length && !state.aiGenerating) {
    container.innerHTML = `<div id="timeline-empty-hint" style="color:#777; font-size:12px; margin:auto;">Añade clips desde la Biblioteca o genera con IA para empezar.</div>`;
    calcTotalDuration(); renderAudioTrack(); return;
  }
  clips.forEach((clip, idx) => {
    const card = document.createElement("div");
    card.className = `timeline-clip-card${idx === state.selectedIndex ? " active" : ""}`;
    card.dataset.idx = String(idx);
    const mediaHtml = clip.kind === "video" ? `<video src="${clip.url}" preload="metadata"></video>` : `<img src="${clip.url}">`;
    card.innerHTML = `
      <div class="timeline-clip-thumb-wrap" data-action="select">${mediaHtml}<span class="timeline-clip-badge">#${idx + 1} ${clip.kind === "video" ? "🎬" : "🖼️"}</span></div>
      <div class="timeline-clip-meta"><span>Dur:</span><input type="number" min="0.5" max="60" step="0.5" value="${clip.duration || (clip.kind === "video" ? 5.0 : 3.0)}" class="clip-dur"><button type="button" class="timeline-btn-mini" data-action="mute">${clip.mute ? "🔇" : "🔊"}</button></div>
      <select class="timeline-btn-mini clip-fx" style="width:100%;"><option value="none"${clip.effect === "none" && clip.transition_in !== "fade" ? " selected" : ""}>FX: Ninguno</option><option value="fade"${clip.transition_in === "fade" ? " selected" : ""}>Transición Fade</option><option value="zoom_in"${clip.effect === "zoom_in" ? " selected" : ""}>Zoom In</option><option value="zoom_out"${clip.effect === "zoom_out" ? " selected" : ""}>Zoom Out</option></select>
      <div class="timeline-clip-actions"><button type="button" class="timeline-btn-mini" data-action="i2v" title="Continuar con I2V">⏭️ I2V</button><button type="button" class="timeline-btn-mini" data-action="left"${idx === 0 ? " disabled" : ""}>◀</button><button type="button" class="timeline-btn-mini" data-action="right"${idx === clips.length - 1 ? " disabled" : ""}>▶</button><button type="button" class="timeline-btn-mini" data-action="del" title="Eliminar">✕</button></div>`;
    container.appendChild(card);
    if (clip.kind === "video" && !clip._hasExplicitDuration) {
      const cardVideo = card.querySelector("video");
      if (cardVideo) {
        const updateFromCard = () => {
          if (!clip._hasExplicitDuration && Number.isFinite(cardVideo.duration) && cardVideo.duration > 0) {
            const d = clipDurationForItem(clip, cardVideo.duration);
            clip.duration = d;
            clip._hasExplicitDuration = true;
            const durInput = card.querySelector(".clip-dur");
            if (durInput) durInput.value = d;
            calcTotalDuration();
          }
        };
        if (Number.isFinite(cardVideo.duration) && cardVideo.duration > 0) {
          updateFromCard();
        } else {
          cardVideo.addEventListener("loadedmetadata", updateFromCard, { once: true });
        }
      }
    }
  });
  if (state.aiGenerating) {
    const ph = document.createElement("div");
    ph.className = "timeline-clip-placeholder";
    ph.innerHTML = `<span class="queue-spinner" style="width:20px;height:20px;border-width:2px;"></span><span>Generando con IA...</span>`;
    container.appendChild(ph);
  }
  calcTotalDuration(); renderAudioTrack();
}

function handleTrackClick(e) {
  const card = e.target.closest(".timeline-clip-card");
  if (!card) return;
  const idx = Number(card.dataset.idx);
  const clips = state.current.data.clips;
  const action = e.target.dataset.action || (e.target.closest("[data-action]") && e.target.closest("[data-action]").dataset.action);
  if (action === "select") selectClip(idx);
  else if (action === "mute") {
    clips[idx].mute = !clips[idx].mute; e.target.textContent = clips[idx].mute ? "🔇" : "🔊";
    if (idx === state.selectedIndex) { const pv = $("timeline-preview-video"); if (pv) pv.muted = clips[idx].mute; }
  } else if (action === "i2v") triggerAiAction("continue_i2v", idx);
  else if (action === "left" && idx > 0) { [clips[idx - 1], clips[idx]] = [clips[idx], clips[idx - 1]]; selectClip(idx - 1); }
  else if (action === "right" && idx < clips.length - 1) { [clips[idx + 1], clips[idx]] = [clips[idx], clips[idx + 1]]; selectClip(idx + 1); }
  else if (action === "del") {
    clips.splice(idx, 1);
    state.selectedIndex = Math.max(0, Math.min(idx, clips.length - 1));
    renderTracks();
    calcTotalDuration();
    if (clips.length) { selectClip(state.selectedIndex); } else { updatePreviewMedia(null); }
  }
}

function handleTrackChange(e) {
  const card = e.target.closest(".timeline-clip-card");
  if (!card) return;
  const clip = state.current.data.clips[Number(card.dataset.idx)];
  if (!clip) return;
  if (e.target.classList.contains("clip-dur")) {
    clip.duration = Math.max(0.5, Number(e.target.value) || 3.0);
    clip._hasExplicitDuration = true;
    calcTotalDuration();
  }
  else if (e.target.classList.contains("clip-fx")) {
    const val = e.target.value;
    clip.transition_in = val === "fade" ? "fade" : "none"; clip.transition_out = val === "fade" ? "fade" : "none"; clip.effect = val === "fade" ? "none" : val;
  }
}

function renderAudioTrack() {
  const container = $("timeline-track-audio");
  if (!container) return;
  container.replaceChildren();
  const tracks = state.current.data.audio_tracks || [];
  if (!tracks.length) {
    container.innerHTML = `<div id="timeline-audio-empty-hint" style="color:#666; font-size:11px; margin:auto;">Sin pista de audio externa (opcional).</div>`;
    return;
  }
  tracks.forEach((t, i) => {
    const card = document.createElement("div");
    card.className = "timeline-audio-card";
    const name = (t.source_path || "").split(/[\\/]/).pop() || `Audio #${i + 1}`;
    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; font-weight:600;"><span class="timeline-audio-title"></span><button type="button" class="timeline-btn-mini" data-del-audio="${i}">✕</button></div>
      <div style="display:flex; justify-content:space-between; align-items:center;"><span>Inicio: <input type="number" min="0" step="0.5" value="${t.start_time || 0}" data-field="start" data-idx="${i}" style="width:42px;">s</span><span>Vol: <input type="number" min="0" max="2" step="0.1" value="${t.volume || 1.0}" data-field="vol" data-idx="${i}" style="width:38px;"></span></div>`;
    const titleSpan = card.querySelector(".timeline-audio-title");
    if (titleSpan) titleSpan.textContent = `🎵 ${name}`;
    container.appendChild(card);
  });
}

export async function refreshTimelineMedia() {
  const shelf = $("timeline-media-shelf");
  if (!shelf) return;
  shelf.replaceChildren();
  const filter = ($("timeline-media-filter") && $("timeline-media-filter").value) || "";
  try {
    // /api/gallery limita a un maximo de 24 items por pagina (CODE-JS-10)
    const data = await api(`/api/gallery?limit=24${filter ? `&kind=${filter}` : ""}`);
    for (const item of (data.items || [])) {
      const isVideo = item.kind === "video";
      const url = resolveMediaUrl(item);
      if (!url) continue;
      const div = document.createElement("div");
      div.className = "timeline-media-item";
      div.title = `#${item.id} · ${item.prompt || ""}`;
      div.innerHTML = `${isVideo ? `<video src="${url}" preload="metadata"></video>` : `<img src="${url}" loading="lazy">`}<button type="button" class="timeline-media-add-btn">+</button>`;
      const videoEl = isVideo ? div.querySelector("video") : null;
      div.querySelector(".timeline-media-add-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        const hasParam = isVideo && (
          (Number(item?.params?.seconds) > 0) ||
          (Number(item?.params?.duration) > 0)
        );
        const metaDuration = videoEl && Number.isFinite(videoEl.duration) && videoEl.duration > 0 ? videoEl.duration : null;
        const dur = clipDurationForItem(item, metaDuration);
        const clip = {
          generation_id: item.id,
          kind: isVideo ? "video" : "image",
          url,
          source_path: url,
          duration: dur,
          params: item.params || {},
          mute: false,
          effect: "none",
          transition_in: "none",
          transition_out: "none",
          _hasExplicitDuration: Boolean(hasParam || metaDuration),
        };
        state.current.data.clips.push(clip);
        if (state.current.data.clips.length === 1) {
          applyFirstClipProfile(state.current.data, item);
        }
        const newIdx = state.current.data.clips.length - 1;
        selectClip(newIdx);

        if (isVideo && !clip._hasExplicitDuration && videoEl) {
          videoEl.addEventListener("loadedmetadata", () => {
            if (!clip._hasExplicitDuration && Number.isFinite(videoEl.duration) && videoEl.duration > 0) {
              clip.duration = clipDurationForItem(item, videoEl.duration);
              clip._hasExplicitDuration = true;
              calcTotalDuration();
              const cardDur = document.querySelector(`.timeline-clip-card[data-idx="${newIdx}"] .clip-dur`);
              if (cardDur) cardDur.value = clip.duration;
            }
          }, { once: true });
        }
      });
      shelf.appendChild(div);
    }
  } catch (err) { setTimelineStatus(`Error en medios: ${err.message}`, true); }
}

async function loadTimelineProjects() {
  try {
    const res = await api("/api/timeline/projects");
    state.projects = res.items || [];
    const select = $("timeline-project-select");
    if (!select) return;
    const prev = select.value;
    select.replaceChildren();
    const defOpt = document.createElement("option");
    defOpt.value = ""; defOpt.textContent = "(Nuevo proyecto)";
    select.appendChild(defOpt);
    for (const p of state.projects) {
      const opt = document.createElement("option");
      opt.value = p.id; opt.textContent = `${p.name} (${(p.data.clips || []).length} clips)`;
      select.appendChild(opt);
    }
    if (prev && state.projects.some((p) => p.id === prev)) select.value = prev;
  } catch (err) { setTimelineStatus(err.message, true); }
}

async function saveCurrentProject() {
  const name = ($("timeline-project-name") && $("timeline-project-name").value.trim()) || "Mi Secuencia";
  setTimelineStatus("Guardando proyecto...");
  try {
    const saved = await postJson("/api/timeline/projects", { id: state.current.id, name, data: state.current.data });
    state.current.id = saved.id; state.current.name = saved.name;
    setTimelineStatus("¡Proyecto guardado!");
    await loadTimelineProjects();
    const select = $("timeline-project-select");
    if (select) select.value = saved.id;
  } catch (err) { setTimelineStatus(err.message, true); }
}

async function exportTimeline() {
  if (!state.current.data.clips.length) { setTimelineStatus("La pista está vacía; añade clips antes de exportar.", true); return; }
  const btn = $("btn-timeline-export");
  if (btn) btn.disabled = true;
  setTimelineStatus("Renderizando secuencia con FFmpeg...");
  try {
    const res = await postJson("/api/timeline/export", { project_data: state.current.data, name: state.current.name || "Exportación Timeline" });
    setTimelineStatus(`¡Vídeo exportado con éxito! (#${res.generation_id})`);
    const video = $("timeline-preview-video");
    const img = $("timeline-preview-image");
    if (img) img.style.display = "none";
    if (video && res.output_url) {
      video.style.display = "block";
      video.src = res.output_url;
      video.play().catch(() => {});
    }
  } catch (err) { setTimelineStatus(`Error en exportación: ${err.message}`, true); }
  finally { if (btn) btn.disabled = false; }
}

function inheritedVideoConfig(clip) {
  const p = (clip && clip.params) || {};
  const width = Number(p.width);
  const height = Number(p.height);
  const hasSize = Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0;
  const profileOk = typeof p.profile === "string" && !["ref2va", "v2v"].includes(p.profile);
  const aspect = p.aspect === "vertical" || p.aspect === "horizontal"
    ? p.aspect
    : hasSize
    ? (height > width ? "vertical" : "horizontal")
    : "";
  return {
    profile: profileOk ? p.profile : "",
    variant: profileOk && typeof p.variant === "string" ? p.variant : "",
    width: hasSize ? Math.round(width) : null,
    height: hasSize ? Math.round(height) : null,
    aspect,
    sage: typeof p.sage === "boolean" ? p.sage : null,
    include_audio: typeof p.include_audio === "boolean" ? p.include_audio : null,
  };
}

function applyInheritedVideoConfig(payload, inherited) {
  if (inherited.profile) payload.profile = inherited.profile;
  if (inherited.variant) payload.variant = inherited.variant;
  if (inherited.width && inherited.height) {
    payload.width = inherited.width;
    payload.height = inherited.height;
  } else if (inherited.aspect) {
    payload.aspect = inherited.aspect;
  }
  if (inherited.sage !== null) payload.sage = inherited.sage;
  if (inherited.include_audio !== null) payload.include_audio = inherited.include_audio;
}

async function hydrateClipParams(clips) {
  const list = Array.isArray(clips) ? clips : [clips];
  let changed = false;
  for (const clip of list) {
    if (!clip || clip.generation_id == null) continue;
    if (clip.params && Object.keys(clip.params).length) continue;
    try {
      const item = await api(`/api/gallery/${encodeURIComponent(clip.generation_id)}`);
      if (item && item.params && Object.keys(item.params).length) {
        clip.params = item.params;
        changed = true;
      }
    } catch (_) {
      // Sin metadatos: la validación de herencia decide si se puede generar.
    }
  }
  return changed;
}

function setTimelineAiBusy(busy) {
  const btn = $("btn-timeline-ai-generate");
  if (btn) btn.disabled = Boolean(busy);
}

async function enqueueClipJob(jobId, kind, dur, insertIdx, msg) {
  await enqueueJobs(jobId, {
    statusFn: setAiStatus,
    cancelButtonId: "btn-timeline-ai-cancel",
    onDone: (job) => {
      state.aiGenerating = false;
      setTimelineAiBusy(false);
      const output = ((job && job.outputs) || [])[0];
      const outName = typeof output === "string" ? output : (output && output.name) || "";
      const outUrl = output && typeof output === "object" && output.url ? output.url : "";
      const derivedGenId = outUrl.match(/\/media\/(\d+)\//);
      const genId = job.gen_id != null ? job.gen_id : (derivedGenId ? Number(derivedGenId[1]) : null);
      if (job.status !== "done" || !outName || !outUrl || genId == null) {
        renderTracks();
        if (job.status === "cancelled") {
          setAiStatus("Generación cancelada");
        } else {
          setAiStatus(job.error || "La generación no devolvió un clip", true);
        }
        return;
      }
      const newUrl = outUrl;
      state.current.data.clips.splice(insertIdx, 0, {
        generation_id: genId, kind, url: newUrl, source_path: newUrl, duration: dur,
        params: job.params || {},
        mute: false, effect: "none",
        transition_in: "none", transition_out: "none", _hasExplicitDuration: true,
      });
      if (state.current.data.clips.length === 1) {
        applyFirstClipProfile(state.current.data, {
          kind,
          params: job.params || {},
        });
      }
      selectClip(insertIdx);
      setAiStatus(msg);
      saveCurrentProject();
    },
  });
}

async function triggerAiAction(actionType, targetClipIndex = null) {
  const clips = state.current.data.clips;
  const promptInput = $("timeline-ai-prompt");
  const prompt = promptInput ? promptInput.value.trim() : "";
  if (!prompt) {
    setAiStatus("Escribe un prompt antes de generar", true);
    return;
  }
  const seconds = Number(($("timeline-ai-seconds") && $("timeline-ai-seconds").value) || 5);
  setTimelineAiBusy(true);
  setAiStatus("Preparando generación IA...");
  try {
    if (actionType === "continue_i2v") {
      const refIdx = targetClipIndex !== null ? targetClipIndex : (state.selectedIndex ?? (clips.length - 1));
      const refClip = clips[refIdx];
      if (!refClip) throw new Error("No hay clip de referencia para continuar");
      await hydrateClipParams([refClip]);
      const inherited = inheritedVideoConfig(refClip);
      if (!inherited.aspect && !inherited.width) {
        throw new Error("El clip de referencia no tiene configuración guardada; vuelve a añadirlo desde la Biblioteca.");
      }
      state.aiGenerating = true;
      renderTracks();
      const frameRes = await postJson("/api/timeline/extract_frame", {
        generation_id: refClip.generation_id,
        source_path: refClip.source_path,
        position: "last",
      });
      setAiStatus("Encolando animación I2V...");
      const payload = {
        engine: "h3",
        mode: "i2v",
        image_b64: frameRes.image_b64,
        prompt,
        motion_positive: prompt,
        seconds,
        aspect: inherited.aspect || "horizontal",
      };
      applyInheritedVideoConfig(payload, inherited);
      if (!payload.image_b64 && frameRes.image_name) {
        payload.image_name = frameRes.image_name;
      }
      const res = await postJson("/api/video/generate", payload);
      await enqueueClipJob(res.job_id, "video", seconds, refIdx + 1, "¡Clip I2V insertado!");
    } else if (actionType === "bridge_flf2v") {
      if (clips.length < 2) throw new Error("Se requieren al menos 2 clips para puente FLF2V");
      const idxA = targetClipIndex !== null ? targetClipIndex : Math.max(0, clips.length - 2);
      const idxB = idxA + 1;
      await hydrateClipParams([clips[idxA], clips[idxB]]);
      const inherited = inheritedVideoConfig(clips[idxA]);
      if (!inherited.aspect && !inherited.width) {
        throw new Error("El clip de referencia no tiene configuración guardada; vuelve a añadirlo desde la Biblioteca.");
      }
      state.aiGenerating = true;
      renderTracks();
      setAiStatus("Extrayendo extremos para puente FLF2V...");
      const fA = await postJson("/api/timeline/extract_frame", { generation_id: clips[idxA].generation_id, source_path: clips[idxA].source_path, position: "last" });
      const fB = await postJson("/api/timeline/extract_frame", { generation_id: clips[idxB].generation_id, source_path: clips[idxB].source_path, position: "first" });
      const payload = {
        engine: "h3",
        mode: "flf2v",
        image_b64: fA.image_b64,
        last_image_b64: fB.image_b64,
        prompt,
        motion_positive: prompt,
        seconds,
        aspect: inherited.aspect || "horizontal",
      };
      applyInheritedVideoConfig(payload, inherited);
      if (!payload.image_b64 && fA.image_name) payload.image_name = fA.image_name;
      if (!payload.last_image_b64 && fB.image_name) payload.last_image_name = fB.image_name;
      const res = await postJson("/api/video/generate", payload);
      await enqueueClipJob(res.job_id, "video", seconds, idxB, "¡Clip puente FLF2V insertado!");
    } else if (actionType === "insert_image") {
      state.aiGenerating = true;
      renderTracks();
      setAiStatus("Generando imagen Anima...");
      const modelId = document.getElementById("model")?.value || "anima-official-aesthetic-v11";
      const res = await postJson("/api/generate", { model_id: modelId, prompt, negative: "", size: "paisaje_plan" });
      await enqueueClipJob(res.job_id, "image", 3.0, clips.length, "¡Imagen insertada!");
    }
  } catch (err) {
    state.aiGenerating = false;
    setTimelineAiBusy(false);
    renderTracks();
    setAiStatus(err.message, true);
  }
}

export function initTimelineTab() {
  const trackVideo = $("timeline-track-video");
  if (trackVideo) { trackVideo.addEventListener("click", handleTrackClick); trackVideo.addEventListener("change", handleTrackChange); }
  const trackAudio = $("timeline-track-audio");
  if (trackAudio) {
    trackAudio.addEventListener("click", (e) => {
      const delIdx = e.target.dataset.delAudio;
      if (delIdx != null) { state.current.data.audio_tracks.splice(Number(delIdx), 1); renderAudioTrack(); }
    });
    trackAudio.addEventListener("change", (e) => {
      const idx = Number(e.target.dataset.idx);
      const field = e.target.dataset.field;
      const t = state.current.data.audio_tracks[idx];
      if (t) {
        if (field === "start") t.start_time = Number(e.target.value) || 0;
        if (field === "vol") t.volume = Number(e.target.value) || 1.0;
      }
    });
  }

  on("btn-timeline-new", "click", () => {
    state.current = { id: null, name: "Mi Secuencia", data: { clips: [], audio_tracks: [], width: 1280, height: 720, fps: 24 } };
    const nameInput = $("timeline-project-name");
    if (nameInput) nameInput.value = "Mi Secuencia";
    const select = $("timeline-project-select");
    if (select) select.value = "";
    updatePreviewMedia(null);
    renderTracks(); setTimelineStatus("Nuevo proyecto iniciado");
  });

  on("btn-timeline-save", "click", saveCurrentProject);
  on("btn-timeline-export", "click", exportTimeline);
  on("btn-timeline-play-all", "click", togglePlayAll);
  on("btn-timeline-refresh-media", "click", refreshTimelineMedia);
  on("timeline-media-filter", "change", refreshTimelineMedia);

  on("timeline-project-select", "change", async (e) => {
    const id = e.target.value;
    if (!id) return;
    try {
      const proj = await api(`/api/timeline/projects/${id}`);
      const hydrated = await hydrateClipParams(proj.data ? proj.data.clips : []);
      state.current = proj;
      const nameInput = $("timeline-project-name");
      if (nameInput) nameInput.value = proj.name;
      renderTracks(); selectClip(0);
      setTimelineStatus(hydrated ? "Proyecto cargado (configuración de clips recuperada)" : `Proyecto '${proj.name}' cargado`);
    } catch (err) { setTimelineStatus(err.message, true); }
  });

  on("btn-timeline-ai-generate", "click", () => {
    triggerAiAction(($("timeline-ai-action") && $("timeline-ai-action").value) || "continue_i2v");
  });
  on("btn-timeline-ai-cancel", "click", (event) => cancelJob(event, setAiStatus));

  on("btn-timeline-add-audio", "click", () => {
    const input = $("timeline-audio-input");
    if (input) input.click();
  });

  on("timeline-audio-input", "change", async (e) => {
    const file = (e.target.files || [])[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setTimelineStatus("Subiendo pista de audio...");
    try {
      const res = await fetch("/api/timeline/upload_audio", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Fallo en subida");
      state.current.data.audio_tracks.push({ source_path: data.audio_path, url: data.audio_url, start_time: 0, volume: 1.0 });
      renderAudioTrack(); setTimelineStatus(`Pista añadida: ${file.name}`);
    } catch (err) { setTimelineStatus(err.message, true); }
  });

  const previewVideo = $("timeline-preview-video");
  if (previewVideo) {
    previewVideo.addEventListener("ended", () => { if (state.isPlayingAll) { state.playIndex++; playNextInSequence(); } });
  }

  loadTimelineProjects();
  refreshTimelineMedia();
  renderTracks();
}
