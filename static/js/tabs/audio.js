// WaifuStudio — Pestaña de Audio (Modo B con MMAudio)
// Qué hace: selección de clips de vídeo, herencia de duración/fps, configuración de prompts MMAudio,
//           reemplazar/mezclar pista, encolado en FIFO y previsualización de MP4 con audio y WAV master 48 kHz.
// Qué no hace: no sintetiza voz (Irodori deshabilitado hasta C-17), no re-renderiza el vídeo original.
// Dependencias: static/js/dom.js, static/js/api.js, static/js/state.js.

import { $, on } from "../dom.js";
import { api, postJson, pollJob, cancelJob } from "../api.js";
import { state } from "../state.js";

let selectedClip = null;
let activeAudioJobId = null;
let irodoriStatusCache = null;

export function updateIrodoriUI(statusData) {
  irodoriStatusCache = statusData;
  const checkbox = $("audio-engine-irodori");
  if (!checkbox) return;

  const label = checkbox.closest("label") || checkbox.parentElement;
  const badge = label ? label.querySelector(".badge") : null;
  const hint = label?.nextElementSibling?.classList?.contains("field-hint")
    ? label.nextElementSibling
    : null;

  const isInstalled = Boolean(statusData?.irodori_installed);
  const status = statusData?.irodori_status || (isInstalled ? "installed" : "absent");
  const reason = statusData?.irodori_reason || (isInstalled ? "Irodori microservicio listo en localhost:8291" : "Irodori no disponible");

  if (isInstalled) {
    checkbox.disabled = false;
    checkbox.style.cursor = "pointer";
    if (label) {
      label.style.opacity = "1";
      label.style.cursor = "pointer";
      label.title = reason;
    }
    if (badge) {
      badge.textContent = "Instalado";
      badge.style.background = "#28a745";
      badge.style.color = "#fff";
    }
    if (hint) {
      hint.textContent = reason;
      hint.style.color = "var(--text-muted, #8e90a6)";
    }
  } else {
    checkbox.disabled = true;
    checkbox.checked = false;
    checkbox.style.cursor = "not-allowed";
    if (label) {
      label.style.opacity = "0.6";
      label.style.cursor = "not-allowed";
      label.title = reason;
    }
    if (badge) {
      badge.textContent = status === "offline" ? "Servicio Offline" : "Deshabilitado";
      badge.style.background = status === "offline" ? "#d97706" : "#444";
      badge.style.color = "#bbb";
    }
    if (hint) {
      hint.textContent = reason;
      hint.style.color = status === "offline" ? "#e06c75" : "var(--text-muted, #8e90a6)";
    }
  }
}

export async function refreshAudioStatus() {
  try {
    const data = await api("/api/audio/status");
    updateIrodoriUI(data);
    return data;
  } catch (err) {
    console.error("[audio] Error al consultar /api/audio/status:", err);
    updateIrodoriUI({
      irodori_installed: false,
      irodori_status: "absent",
      irodori_reason: `No se pudo consultar estado de Irodori (${err.message})`,
    });
    return null;
  }
}

function setAudioStatus(text, isError = false) {
  const el = $("audio-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = isError ? "var(--accent, #e06c75)" : "var(--text-muted, #8e90a6)";
}

function setAudioProgress(percent = 0, text = "") {
  const wrap = $("audio-progress");
  const fill = $("audio-progress-fill");
  const txt = $("audio-progress-text");
  if (!wrap || !fill || !txt) return;

  const valid = typeof percent === "number" && percent >= 0;
  wrap.style.display = valid ? "block" : "none";
  fill.style.width = valid ? `${Math.min(100, Math.max(0, percent))}%` : "0%";
  txt.textContent = text || (valid ? `${Math.round(percent)}%` : "");
}

export async function loadAudioClips() {
  const grid = $("audio-gallery-grid");
  if (!grid) return;

  try {
    const clips = await api("/api/audio/clips");
    if (!clips || !clips.length) {
      grid.innerHTML = '<p class="field-hint" style="grid-column: 1/-1;">No hay clips de vídeo recientes en la galería. Genera un vídeo Wan primero.</p>';
      return;
    }

    grid.innerHTML = "";
    clips.forEach((clip) => {
      const card = document.createElement("div");
      card.className = "gallery-item";
      card.style.cursor = "pointer";
      card.style.border = "1px solid var(--border-color, #333)";
      card.style.borderRadius = "4px";
      card.style.padding = "4px";
      card.style.background = "rgba(255,255,255,0.02)";
      card.style.transition = "transform 0.15s, border-color 0.15s";

      card.innerHTML = `
        <div style="font-weight:600; font-size:0.75rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${clip.name}</div>
        <div style="font-size:0.7rem; color:var(--text-muted, #888); margin-top:2px;">Gen #${clip.gen_id}</div>
      `;

      card.addEventListener("mouseenter", () => {
        card.style.borderColor = "var(--primary, #5c7cfa)";
      });
      card.addEventListener("mouseleave", () => {
        if (selectedClip?.gen_id !== clip.gen_id) {
          card.style.borderColor = "var(--border-color, #333)";
        }
      });
      card.addEventListener("click", () => {
        selectClip({ gen_id: clip.gen_id, name: clip.name, path: clip.path });
      });

      grid.appendChild(card);
    });
  } catch (err) {
    console.error("[audio] Error al cargar clips de galería:", err);
    if (grid) {
      grid.innerHTML = `<p class="field-hint" style="color:var(--accent,#e06c75);">Error al cargar galería: ${err.message}</p>`;
    }
  }
}

export async function selectClip(clipSource) {
  setAudioStatus("Inspeccionando metadatos del clip...");
  try {
    const meta = await postJson("/api/audio/probe", clipSource);
    selectedClip = {
      ...clipSource,
      duration: meta.duration,
      fps: meta.fps,
      width: meta.width,
      height: meta.height,
      has_audio: meta.has_audio,
      path: meta.path,
      name: meta.name || clipSource.name || "clip.mp4",
    };

    $("audio-clip-name").textContent = selectedClip.name;
    $("audio-clip-duration").textContent = `${Number(selectedClip.duration).toFixed(2)}`;
    $("audio-clip-fps").textContent = `${selectedClip.fps} fps`;
    $("audio-clip-audio-status").textContent = selectedClip.has_audio ? "Con audio" : "Mudo";
    $("audio-selected-path").value = selectedClip.path || "";
    $("audio-selected-gen-id").value = selectedClip.gen_id || "";

    const btnGen = $("btn-audio-generate");
    if (btnGen) {
      btnGen.disabled = false;
      btnGen.textContent = `🎵 Generar Audio (${Number(selectedClip.duration).toFixed(1)} s)`;
    }

    setAudioStatus(`Clip listo: ${selectedClip.name} (${Number(selectedClip.duration).toFixed(2)} s heredados)`, false);
  } catch (err) {
    console.error("[audio] Error al inspeccionar clip:", err);
    setAudioStatus(`Error al cargar clip: ${err.message}`, true);
  }
}

async function handleGenerateAudio() {
  if (!selectedClip || !selectedClip.path) {
    setAudioStatus("Selecciona primero un clip de vídeo de la galería.", true);
    return;
  }

  const prompt = $("audio-prompt")?.value?.trim() || "";
  const negative = $("audio-negative")?.value?.trim() || "";
  const steps = parseInt($("audio-steps")?.value, 10) || 25;
  const cfg = parseFloat($("audio-cfg")?.value) || 4.5;
  const seedInput = parseInt($("audio-seed")?.value, 10);
  const seed = isNaN(seedInput) || seedInput < 0 ? Math.floor(Math.random() * 2147483647) : seedInput;

  const actionRadios = document.getElementsByName("audio-track-action");
  let action = "replace";
  for (const r of actionRadios) {
    if (r.checked) {
      action = r.value;
      break;
    }
  }

  const irodoriCheckbox = $("audio-engine-irodori");
  const voiceEnabled = Boolean(irodoriCheckbox?.checked && !irodoriCheckbox?.disabled);

  const payload = {
    video_path: selectedClip.path,
    source_gen_id: selectedClip.gen_id || null,
    duration: selectedClip.duration,
    fps: selectedClip.fps,
    prompt,
    negative,
    steps,
    cfg,
    seed,
    action,
    voice_enabled: voiceEnabled,
  };

  const btnGen = $("btn-audio-generate");
  const btnCancel = $("btn-audio-cancel");
  if (btnGen) btnGen.disabled = true;
  if (btnCancel) btnCancel.style.display = "block";

  setAudioStatus("Enviando trabajo a la cola FIFO...");
  setAudioProgress(0, "En cola");

  try {
    const res = await postJson("/api/audio/generate", payload);
    activeAudioJobId = res.job_id;

    await pollJob(
      res.job_id,
      (text, isErr) => setAudioStatus(text, isErr),
      async (jobData) => {
        if (btnGen) btnGen.disabled = false;
        if (btnCancel) btnCancel.style.display = "none";
        setAudioProgress(100, "Completado");

        if (jobData.status === "done" && jobData.outputs && jobData.outputs.length) {
          setAudioStatus("¡Audio generado con éxito! MP4 nuevo y WAV 48 kHz listos.", false);
          renderAudioResult(jobData);
        } else if (jobData.status === "cancelled") {
          setAudioStatus("Generación cancelada.", false);
        } else {
          setAudioStatus(jobData.error || "Fallo en la generación de audio.", true);
        }
      },
      (percent, text) => setAudioProgress(percent, text),
      true,
      "btn-audio-cancel"
    );
  } catch (err) {
    console.error("[audio] Error al iniciar trabajo:", err);
    setAudioStatus(`Error: ${err.message}`, true);
    if (btnGen) btnGen.disabled = false;
    if (btnCancel) btnCancel.style.display = "none";
    setAudioProgress(-1);
  }
}

function renderAudioResult(jobData) {
  const resultCard = $("audio-result-card");
  const emptyCard = $("audio-empty-card");
  const videoEl = $("audio-preview-video");
  const wavEl = $("audio-preview-wav");
  const downloadMp4Btn = $("btn-audio-download-mp4");
  const downloadWavBtn = $("btn-audio-download-wav");

  if (!resultCard) return;

  const gid = jobData.gen_id;
  const outputs = jobData.outputs || [];

  let mp4Url = "";
  let wavUrl = "";

  outputs.forEach((item) => {
    const name = item.name || "";
    if (name.endsWith(".mp4")) {
      mp4Url = item.url || `/media/${gid}/${name}`;
    } else if (name.endsWith(".wav")) {
      wavUrl = `/api/audio/media/${gid}/${name}`;
    }
  });

  if (videoEl && mp4Url) {
    videoEl.src = mp4Url;
    videoEl.load();
  }
  if (wavEl && wavUrl) {
    wavEl.src = wavUrl;
    wavEl.load();
  }

  if (downloadMp4Btn && mp4Url) {
    downloadMp4Btn.href = mp4Url;
    downloadMp4Btn.setAttribute("download", `waifu_audio_${gid}.mp4`);
  }
  if (downloadWavBtn && wavUrl) {
    downloadWavBtn.href = wavUrl;
    downloadWavBtn.setAttribute("download", `waifu_audio_${gid}_48k.wav`);
  }

  resultCard.style.display = "block";
  if (emptyCard) emptyCard.style.display = "none";

  resultCard.scrollIntoView({ behavior: "smooth" });
}

export function initAudioTab() {
  on("btn-audio-generate", "click", handleGenerateAudio);

  on("btn-audio-cancel", "click", async () => {
    if (activeAudioJobId) {
      await cancelJob(activeAudioJobId, "btn-audio-cancel");
      setAudioStatus("Cancelando trabajo...", false);
    }
  });

  on("btn-audio-refresh-gallery", "click", () => {
    loadAudioClips();
  });

  on("btn-audio-pick-gallery", "click", () => {
    $("audio-gallery-grid")?.scrollIntoView({ behavior: "smooth" });
  });

  on("btn-audio-latest-video", async () => {
    try {
      const clips = await api("/api/audio/clips");
      if (clips && clips.length > 0) {
        selectClip(clips[0]);
      } else {
        setAudioStatus("No hay vídeos disponibles en la galería.", true);
      }
    } catch (err) {
      setAudioStatus(`Error: ${err.message}`, true);
    }
  });

  on("btn-audio-random-seed", "click", () => {
    const seedEl = $("audio-seed");
    if (seedEl) seedEl.value = Math.floor(Math.random() * 2147483647);
  });

  on("btn-audio-mode-a", "click", () => {
    $("btn-audio-mode-a")?.classList.add("active");
    $("btn-audio-mode-b")?.classList.remove("active");
    $("audio-mode-hint").textContent = "Modo A: duración libre sin vídeo de referencia. MMAudio genera audio ambiental puro.";
    $("audio-mode-a-notice").style.display = "inline-flex";
    $("audio-clip-selector-card").style.opacity = "0.4";
  });

  on("btn-audio-mode-b", "click", () => {
    $("btn-audio-mode-b")?.classList.add("active");
    $("btn-audio-mode-a")?.classList.remove("active");
    $("audio-mode-hint").textContent = "Modo B: hereda duración y sincroniza audio condicionado a los fotogramas del clip sin regenerar vídeo.";
    $("audio-mode-a-notice").style.display = "none";
    $("audio-clip-selector-card").style.opacity = "1";
  });

  on("btn-audio-send-timeline", "click", () => {
    setAudioStatus("Pista preparada para el Timeline.", false);
    const tabTimeline = $("tab-timeline");
    if (tabTimeline) tabTimeline.click();
  });

  loadAudioClips();
  refreshAudioStatus();
}
