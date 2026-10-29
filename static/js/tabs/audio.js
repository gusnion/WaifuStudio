// WaifuStudio — Pestaña de Audio (Modo B con MMAudio, Modo A con voz Irodori)
// Qué hace: selección de clips de vídeo, herencia de duración/fps, configuración de prompts MMAudio,
//           reemplazar/mezclar pista, encolado en FIFO y previsualización de MP4 con audio y WAV master 48 kHz.
//           Modo A (C-18): texto con paleta de emojis, caption/seed, referencia de voz opcional (ref_wav o
//           ref_embed) y reproducción/descarga del WAV de Irodori vía POST /api/audio/voice.
// Qué no hace: no calcula Speaker Inversion (solo reenvía un ref_embed existente), no re-renderiza el vídeo original.
// Dependencias: static/js/dom.js, static/js/api.js, static/js/state.js.

import { $, on } from "../dom.js";
import { api, postJson, pollJob, cancelJob } from "../api.js";
import { state } from "../state.js";

let selectedClip = null;
let activeAudioJobId = null;
let irodoriStatusCache = null;
let lastVoiceGenId = null;
let lastAmbientGenId = null;
let lastVideoGenId = null;
let lastVoiceResult = null;
let lastAmbientResult = null;
let lastMixResult = null;
let activeAudioResult = "ambient";
let mixBusy = false;

export function updateIrodoriUI(statusData) {
  irodoriStatusCache = statusData;
  const badge = $("audio-engine-irodori-badge");
  const hint = $("audio-engine-irodori-hint");
  if (!badge && !hint) return;

  const isInstalled = Boolean(statusData?.irodori_installed);
  const status = statusData?.irodori_status || (isInstalled ? "installed" : "absent");
  const reason = statusData?.irodori_reason || (isInstalled ? "Irodori microservicio listo en localhost:8291" : "Irodori no disponible");

  if (badge) {
    badge.textContent = isInstalled
      ? "Instalado"
      : status === "offline"
      ? "Servicio offline"
      : "No instalado";
    badge.style.background = isInstalled ? "#28a745" : status === "offline" ? "#d97706" : "#444";
    badge.style.color = isInstalled || status === "offline" ? "#fff" : "#bbb";
  }
  if (hint) {
    hint.textContent = isInstalled
      ? `${reason} La voz se genera en Modo A.`
      : reason;
    hint.style.color = status === "offline" ? "#e06c75" : "var(--text-muted, #8e90a6)";
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

function audioResultAvailability() {
  return {
    ambient: Boolean(lastAmbientResult),
    voice: Boolean(lastVoiceResult),
    mix: Boolean(lastMixResult),
  };
}

function updateAudioResultTabs() {
  const available = audioResultAvailability();
  document.querySelectorAll("[data-audio-result]").forEach((btn) => {
    const key = btn.dataset.audioResult;
    const ok = Boolean(available[key]);
    btn.disabled = !ok;
    btn.classList.toggle("active", ok && key === activeAudioResult);
    btn.setAttribute("aria-selected", ok && key === activeAudioResult ? "true" : "false");
  });
}

function showAudioResult(key) {
  const available = audioResultAvailability();
  if (!available[key]) return;
  if (key === "voice") setAudioMode("a");
  else if (key === "ambient") setAudioMode("b");
  const cards = {
    ambient: $("audio-result-card"),
    voice: $("audio-voice-result-card"),
    mix: $("audio-mix-result-card"),
  };
  for (const [name, card] of Object.entries(cards)) {
    if (card) card.style.display = name === key ? "block" : "none";
  }
  const ambientEmpty = $("audio-empty-card");
  if (ambientEmpty) ambientEmpty.style.display = "none";
  const voiceEmpty = $("audio-voice-empty-card");
  if (voiceEmpty) voiceEmpty.style.display = "none";
  activeAudioResult = key;
  updateAudioResultTabs();
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
        <video class="audio-clip-thumb" src="${clip.url || ""}" preload="metadata" muted playsinline></video>
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

    const preview = $("audio-clip-preview");
    const previewUrl = clipSource.url
      || (selectedClip.gen_id ? `/media/${selectedClip.gen_id}/${encodeURIComponent(selectedClip.name)}` : "");
    if (preview) {
      if (previewUrl) {
        preview.src = previewUrl;
        preview.hidden = false;
        preview.load();
      } else {
        preview.removeAttribute("src");
        preview.hidden = true;
      }
    }
    const durationBadge = $("audio-clip-duration-badge");
    if (durationBadge) {
      durationBadge.hidden = false;
      durationBadge.classList.remove("hidden");
    }
    updateMixAvailability();

    if (selectedClip.gen_id) {
      lastVideoGenId = selectedClip.gen_id;
      const vidInput = $("audio-mix-video-id");
      if (vidInput && !vidInput.value) vidInput.placeholder = `Vídeo (#${lastVideoGenId})`;
    }

    const btnGen = $("btn-audio-generate");
    if (btnGen) {
      btnGen.disabled = false;
      btnGen.textContent = `🎵 Generar ambiente (${Number(selectedClip.duration).toFixed(1)} s)`;
    }

    setAudioStatus(`Clip listo: ${selectedClip.name} (${Number(selectedClip.duration).toFixed(2)} s)`, false);
  } catch (err) {
    console.error("[audio] Error al inspeccionar clip:", err);
    const preview = $("audio-clip-preview");
    if (preview) {
      preview.removeAttribute("src");
      preview.hidden = true;
    }
    const durationBadge = $("audio-clip-duration-badge");
    if (durationBadge) durationBadge.classList.add("hidden");
    setAudioStatus(`Error al cargar clip: ${err.message}`, true);
  }
}

function updateMixAvailability() {
  const mute = Boolean(selectedClip && selectedClip.has_audio === false);
  const mixRadio = document.querySelector('input[name="audio-track-action"][value="mix"]');
  const replaceRadio = document.querySelector('input[name="audio-track-action"][value="replace"]');
  if (mixRadio) {
    mixRadio.disabled = mute;
    mixRadio.title = mute ? "El clip es mudo: no hay pista que mezclar." : "";
    if (mute && mixRadio.checked && replaceRadio) replaceRadio.checked = true;
  }
  const label = $("audio-track-mix-label");
  if (label) label.classList.toggle("disabled", mute);
  const hint = $("audio-mix-mute-hint");
  if (hint) hint.hidden = !mute;
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
  if (selectedClip.has_audio === false && action === "mix") action = "replace";

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
    voice_enabled: false,
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
  if (gid) {
    lastAmbientGenId = gid;
    const ambInput = $("audio-mix-ambient-id");
    if (ambInput && !ambInput.value) ambInput.placeholder = `Último amb. (#${lastAmbientGenId})`;
  }
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

  lastAmbientResult = jobData;
  showAudioResult("ambient");
}

const VOICE_MAX_REF_BYTES = 25 * 1024 * 1024;
const VOICE_REQUEST_TIMEOUT_MS = 330000;
let voiceBusy = false;

export function insertEmojiAtCursor(textarea, emoji) {
  if (!textarea || !emoji) return;
  const value = textarea.value || "";
  const start = typeof textarea.selectionStart === "number" ? textarea.selectionStart : value.length;
  const end = typeof textarea.selectionEnd === "number" ? textarea.selectionEnd : start;
  textarea.value = value.slice(0, start) + emoji + value.slice(end);
  const caret = start + emoji.length;
  if (typeof textarea.setSelectionRange === "function") textarea.setSelectionRange(caret, caret);
  if (typeof textarea.focus === "function") textarea.focus();
}

function setVoiceStatus(text, isError = false) {
  const el = $("audio-voice-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = isError ? "var(--accent, #e06c75)" : "var(--text-muted, #8e90a6)";
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("No se pudo leer el archivo de referencia"));
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}

export function setVoiceProgress(percent = 0, text = "") {
  const wrap = $("audio-voice-progress");
  const fill = $("audio-voice-progress-fill");
  const txt = $("audio-voice-progress-text");
  if (!wrap || !fill) return;

  const valid = typeof percent === "number" && percent >= 0;
  wrap.style.display = valid ? "block" : "none";
  fill.style.width = valid ? `${Math.min(100, Math.max(0, percent))}%` : "0%";
  if (txt) {
    txt.style.display = valid ? "block" : "none";
    txt.textContent = text || (valid ? `${Math.round(percent)}%` : "");
  }
}

export function splitVoiceTextJS(text, maxChars = 220, targetChunks = null, targetDuration = null) {
  const clean = (text || "").trim();
  if (!clean) return [];
  if (!targetChunks && targetDuration && targetDuration > 0) {
    targetChunks = Math.max(1, Math.round(targetDuration / 20));
  }
  if (targetChunks === 1) return [clean];

  const sentences = clean.split(/(?<=[.!?。！？\n])\s+/).map((s) => s.trim()).filter(Boolean);
  const baseList = sentences.length ? sentences : [clean];

  if (targetChunks && targetChunks > 1) {
    if (baseList.length === targetChunks) return baseList;
    if (baseList.length > targetChunks) {
      const chunks = [];
      for (let i = 0; i < targetChunks; i++) {
        const start = Math.floor((i * baseList.length) / targetChunks);
        const end = Math.floor(((i + 1) * baseList.length) / targetChunks);
        const block = baseList.slice(start, end).join(" ").trim();
        if (block) chunks.push(block);
      }
      return chunks;
    }
    const words = clean.split(/\s+/).filter(Boolean);
    if (words.length >= targetChunks) {
      const chunks = [];
      for (let i = 0; i < targetChunks; i++) {
        const start = Math.floor((i * words.length) / targetChunks);
        const end = Math.floor(((i + 1) * words.length) / targetChunks);
        const block = words.slice(start, end).join(" ").trim();
        if (block) chunks.push(block);
      }
      return chunks;
    }
    const totalChars = clean.length;
    if (totalChars >= targetChunks) {
      const chunks = [];
      for (let i = 0; i < targetChunks; i++) {
        const start = Math.floor((i * totalChars) / targetChunks);
        const end = Math.floor(((i + 1) * totalChars) / targetChunks);
        const block = clean.slice(start, end).trim();
        if (block) chunks.push(block);
      }
      if (chunks.length === targetChunks) return chunks;
    }
    return baseList;
  }

  const chunks = [];
  let current = [];
  let currentLen = 0;
  for (const s of baseList) {
    if (s.length > maxChars) {
      if (current.length) {
        chunks.push(current.join(" "));
        current = [];
        currentLen = 0;
      }
      const words = s.split(/\s+/).filter(Boolean);
      let wAcc = [];
      let wLen = 0;
      for (const w of words) {
        if (wAcc.length && (wLen + w.length + 1 > maxChars)) {
          chunks.push(wAcc.join(" "));
          wAcc = [w];
          wLen = w.length;
        } else {
          wAcc.push(w);
          wLen += w.length + 1;
        }
      }
      if (wAcc.length) chunks.push(wAcc.join(" "));
      continue;
    }
    const added = s.length + (current.length ? 1 : 0);
    if (current.length && currentLen + added > maxChars) {
      chunks.push(current.join(" "));
      current = [s];
      currentLen = s.length;
    } else {
      current.push(s);
      currentLen += added;
    }
  }
  if (current.length) chunks.push(current.join(" "));
  return chunks;
}

export function updateVoiceLongPreview() {
  const longCheck = $("audio-voice-long");
  const controls = $("audio-voice-long-controls");
  const info = $("audio-voice-chunks-info");
  if (!longCheck) return;
  const isLong = Boolean(longCheck.checked);
  if (controls) controls.style.display = isLong ? "block" : "none";
  if (!isLong || !info) return;

  const text = $("audio-voice-text")?.value?.trim() || "";
  const tramosInput = parseInt($("audio-voice-tramos")?.value, 10);
  const manualTramos = !isNaN(tramosInput) && tramosInput > 0 ? tramosInput : null;
  const chunks = splitVoiceTextJS(text, 220, manualTramos);
  const count = chunks.length || 1;
  const estSeconds = Math.round(count * 20);
  if (manualTramos) {
    info.textContent = `${count} tramos manuales (~${estSeconds} s, crossfade 0,3 s)`;
  } else {
    info.textContent = `Previsto: ${count} tramo${count > 1 ? "s" : ""} (~${estSeconds} s, crossfade 0,3 s)`;
  }
}

function renderVoiceResult(res) {
  const card = $("audio-voice-result-card");
  const empty = $("audio-voice-empty-card");
  const player = $("audio-voice-preview");
  const download = $("btn-audio-voice-download");
  const meta = $("audio-voice-result-meta");
  if (!card || !res?.url) return;

  const gid = res?.gen_id;
  if (gid) {
    lastVoiceGenId = gid;
    const voiceInput = $("audio-mix-voice-id");
    if (voiceInput && !voiceInput.value) voiceInput.placeholder = `Última voz (#${lastVoiceGenId})`;
  }

  if (player) {
    player.src = res.url;
    player.load();
  }
  if (download) {
    download.href = res.url;
    download.setAttribute("download", `waifu_voice_${res.gen_id}.wav`);
  }
  if (meta) {
    const secs = typeof res.duration === "number" ? `${res.duration.toFixed(1)} s · ` : "";
    const tramosStr = res.chunks && res.chunks > 1 ? ` · ${res.chunks} tramos (crossfade 0,3 s)` : "";
    meta.textContent = `${secs}seed ${res.seed}${res.has_ref ? " · con referencia" : ""}${tramosStr}`;
  }
  lastVoiceResult = res;
  showAudioResult("voice");
}

async function handleGenerateVoice() {
  if (voiceBusy) return;
  const text = $("audio-voice-text")?.value?.trim() || "";
  if (!text) {
    setVoiceStatus("Escribe el texto (puedes usar la paleta de emojis).", true);
    return;
  }

  const caption = $("audio-voice-caption")?.value?.trim() || "";
  const seedInput = parseInt($("audio-voice-seed")?.value, 10);
  const payload = { text, caption, seed: isNaN(seedInput) || seedInput < 0 ? -1 : seedInput };

  const isLong = Boolean($("audio-voice-long")?.checked);
  const tramosInput = parseInt($("audio-voice-tramos")?.value, 10);
  if (isLong) {
    payload.long = true;
    payload.crossfade = 0.3;
    if (!isNaN(tramosInput) && tramosInput > 0) {
      payload.tramos = tramosInput;
    }
  }

  const file = $("audio-voice-ref-file")?.files?.[0] || null;
  const refEmbed = $("audio-voice-ref-embed")?.value?.trim() || "";
  if (file && refEmbed) {
    setVoiceStatus("Usa una sola referencia: archivo de audio o ref_embed.", true);
    return;
  }

  const manualTramos = !isNaN(tramosInput) && tramosInput > 0 ? tramosInput : null;
  const expectedChunks = isLong ? (splitVoiceTextJS(text, 220, manualTramos).length || 1) : 1;

  const btn = $("btn-audio-voice-generate");
  voiceBusy = true;
  if (btn) btn.disabled = true;

  if (isLong) {
    setVoiceProgress(20, `Sintetizando voz en ${expectedChunks} tramos (sin progreso simulado)...`);
    setVoiceStatus(`Sintetizando voz en ${expectedChunks} tramos con crossfade de 0,3 s. Puede tardar varios minutos.`);
  } else {
    setVoiceProgress(20, "Sintetizando voz con Irodori...");
    setVoiceStatus("Sintetizando voz con Irodori. Puede tardar varios minutos.");
  }

  try {
    if (file) {
      if (file.size > VOICE_MAX_REF_BYTES) throw new Error("La referencia supera 25 MB");
      payload.ref_wav_data = await fileToBase64(file);
      payload.ref_wav_name = file.name;
    } else if (refEmbed) {
      payload.ref_embed = refEmbed;
    }

    const res = await api("/api/audio/voice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      timeoutMs: VOICE_REQUEST_TIMEOUT_MS,
    });

    if (isLong) {
      setVoiceProgress(100, `Completado: ${res.chunks || expectedChunks} tramos concatenados`);
      setVoiceStatus(`Voz continua generada (${res.chunks || expectedChunks} tramos con crossfade de 0,3 s, Gen #${res.gen_id}).`, false);
    } else {
      setVoiceProgress(100, "Voz completada");
      setVoiceStatus(`Voz generada y guardada en la galería (Gen #${res.gen_id}).`, false);
    }

    renderVoiceResult(res);
  } catch (err) {
    console.error("[audio] Error al sintetizar voz:", err);
    setVoiceProgress(-1);
    setVoiceStatus(`Error: ${err.message}`, true);
  } finally {
    voiceBusy = false;
    if (btn) btn.disabled = false;
    setTimeout(() => {
      if (!voiceBusy) setVoiceProgress(-1);
    }, 3500);
  }
}

function setAudioMode(mode) {
  const isA = mode === "a";
  $("btn-audio-mode-a")?.classList.toggle("active", isA);
  $("btn-audio-mode-b")?.classList.toggle("active", !isA);
  const toggle = (id, hidden) => {
    const el = $(id);
    if (el) el.hidden = hidden;
  };
  toggle("audio-mode-a-sidebar", !isA);
  toggle("audio-mode-a-viewport", !isA);
  toggle("audio-mode-b-sidebar", isA);
  toggle("audio-mode-b-viewport", isA);
  const hint = $("audio-mode-hint");
  if (hint) {
    hint.textContent = isA
      ? "Modo A: voz con Irodori TTS. Escribe el texto, ajusta la voz y genera un WAV en la galería."
      : "Modo B: ambiente desde un clip de vídeo. Elige clip, ajusta el ambiente y genera sin regenerar vídeo.";
  }
  const notice = $("audio-mode-a-notice");
  if (notice) notice.style.display = isA ? "inline-flex" : "none";
  const voiceEmpty = $("audio-voice-empty-card");
  if (voiceEmpty) voiceEmpty.style.display = isA && !lastVoiceResult ? "" : "none";
  const ambientEmpty = $("audio-empty-card");
  if (ambientEmpty) ambientEmpty.style.display = !isA && !lastAmbientResult ? "" : "none";
  updateAudioResultTabs();
}

function setMixStatus(text, isError = false) {
  const el = $("audio-mix-status");
  if (!el) return;
  el.textContent = text;
  el.style.color = isError ? "var(--error-color, #e74c3c)" : "var(--accent-color, #27ae60)";
}

export async function updateLatestMixDefaults() {
  try {
    const data = await api("/api/audio/mix/latest");
    if (data?.latest_voice_gen_id && !lastVoiceGenId) {
      lastVoiceGenId = data.latest_voice_gen_id;
      const vi = $("audio-mix-voice-id");
      if (vi && !vi.value) vi.placeholder = `Última voz (#${lastVoiceGenId})`;
    }
    if (data?.latest_ambient_gen_id && !lastAmbientGenId) {
      lastAmbientGenId = data.latest_ambient_gen_id;
      const ai = $("audio-mix-ambient-id");
      if (ai && !ai.value) ai.placeholder = `Último amb. (#${lastAmbientGenId})`;
    }
  } catch (_) {}
}

export function renderMixResult(res) {
  const card = $("audio-mix-result-card");
  if (!card) return;

  const mixedAudio = $("audio-mix-preview-mixed");
  const voiceAudio = $("audio-mix-preview-voice");
  const ambientAudio = $("audio-mix-preview-ambient");
  const videoEl = $("audio-mix-preview-video");
  const videoWrap = $("audio-mix-video-container");

  const btnMixed = $("btn-audio-download-mixed");
  const btnVoice = $("btn-audio-download-voice-stem");
  const btnAmbient = $("btn-audio-download-ambient-stem");
  const btnMp4 = $("btn-audio-download-mixed-mp4");

  if (mixedAudio && res.mixed_wav) {
    mixedAudio.src = res.mixed_wav;
    mixedAudio.load();
  }
  if (voiceAudio && res.voice_stem) {
    voiceAudio.src = res.voice_stem;
    voiceAudio.load();
  }
  if (ambientAudio && res.ambient_stem) {
    ambientAudio.src = res.ambient_stem;
    ambientAudio.load();
  }

  if (btnMixed && res.mixed_wav) {
    btnMixed.href = res.mixed_wav;
    btnMixed.setAttribute("download", `mixed_${res.gen_id}.wav`);
  }
  if (btnVoice && res.voice_stem) {
    btnVoice.href = res.voice_stem;
    btnVoice.setAttribute("download", `voice_${res.gen_id}.wav`);
  }
  if (btnAmbient && res.ambient_stem) {
    btnAmbient.href = res.ambient_stem;
    btnAmbient.setAttribute("download", `ambient_${res.gen_id}.wav`);
  }

  if (res.has_video && res.mixed_mp4) {
    if (videoWrap) videoWrap.style.display = "block";
    if (videoEl) {
      videoEl.src = res.mixed_mp4;
      videoEl.load();
    }
    if (btnMp4) {
      btnMp4.style.display = "inline-flex";
      btnMp4.href = res.mixed_mp4;
      btnMp4.setAttribute("download", `mixed_${res.gen_id}.mp4`);
    }
  } else {
    if (videoWrap) videoWrap.style.display = "none";
    if (btnMp4) btnMp4.style.display = "none";
  }

  lastMixResult = res;
  showAudioResult("mix");
}

export async function handleMixLayers() {
  if (mixBusy) return;
  const btn = $("btn-audio-mix-layers");
  const voiceInput = $("audio-mix-voice-id")?.value?.trim();
  const ambientInput = $("audio-mix-ambient-id")?.value?.trim();
  const videoInput = $("audio-mix-video-id")?.value?.trim();

  const voiceId = voiceInput ? parseInt(voiceInput, 10) : lastVoiceGenId;
  const ambientId = ambientInput ? parseInt(ambientInput, 10) : lastAmbientGenId;
  const videoId = videoInput ? parseInt(videoInput, 10) : (lastVideoGenId || selectedClip?.gen_id || null);

  mixBusy = true;
  if (btn) btn.disabled = true;
  setMixStatus("Mezclando capas a 48 kHz (voz + ambiente)...");

  try {
    const payload = {
      voice_gen_id: voiceId,
      ambient_gen_id: ambientId,
      video_gen_id: videoId,
    };
    const res = await postJson("/api/audio/mix", payload);
    setMixStatus(`Mezcla completada (Gen #${res.gen_id}). Stems y master listos.`, false);
    renderMixResult(res);
  } catch (err) {
    console.error("[audio] Error al mezclar capas:", err);
    setMixStatus(`Error: ${err.message}`, true);
  } finally {
    mixBusy = false;
    if (btn) btn.disabled = false;
  }
}

async function sendAmbientToTimeline() {
  const res = lastAmbientResult;
  const wav = res && Array.isArray(res.outputs)
    ? res.outputs.find((item) => String(item.name || "").toLowerCase().endsWith(".wav"))
    : null;
  if (!res || !wav) {
    setAudioStatus("Genera primero un ambiente para enviarlo al Timeline.", true);
    return;
  }
  const url = wav.url || `/api/audio/media/${res.gen_id}/${encodeURIComponent(wav.name)}`;
  setAudioStatus("Enviando audio al Timeline...");
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`No se pudo descargar el WAV (${response.status})`);
    const blob = await response.blob();
    const audioB64 = await fileToBase64(new File([blob], wav.name, { type: blob.type || "audio/wav" }));
    const uploaded = await postJson("/api/timeline/upload_audio", { filename: wav.name, audio_b64: audioB64 });
    if (!uploaded || !uploaded.audio_url) throw new Error("La subida no devolvió URL");
    window.dispatchEvent(new CustomEvent("waifu:timeline-audio-add", {
      detail: {
        name: wav.name,
        track: {
          source_path: uploaded.audio_path || uploaded.audio_url,
          url: uploaded.audio_url,
          start_time: 0,
          volume: 1.0,
        },
      },
    }));
    setAudioStatus(`Audio enviado al Timeline: ${wav.name}`, false);
    const tabTimeline = $("tab-timeline");
    if (tabTimeline) tabTimeline.click();
  } catch (err) {
    setAudioStatus(`No se pudo enviar al Timeline: ${err.message}`, true);
  }
}

export function initAudioTab() {
  on("btn-audio-generate", "click", handleGenerateAudio);
  on("btn-audio-voice-generate", "click", handleGenerateVoice);
  on("btn-audio-mix-layers", "click", handleMixLayers);
  on("btn-audio-send-timeline", "click", sendAmbientToTimeline);

  document.querySelectorAll("[data-audio-result]").forEach((btn) => {
    btn.addEventListener("click", () => showAudioResult(btn.dataset.audioResult));
  });
  updateAudioResultTabs();
  updateMixAvailability();

  const palette = $("audio-voice-palette");
  if (palette) {
    palette.addEventListener("click", (event) => {
      const btn = event.target?.closest?.(".audio-emoji-btn");
      if (btn) insertEmojiAtCursor($("audio-voice-text"), btn.dataset.emoji || "");
    });
  }

  on("btn-audio-voice-random-seed", "click", () => {
    const seedEl = $("audio-voice-seed");
    if (seedEl) seedEl.value = Math.floor(Math.random() * 2147483647);
  });

  on("audio-voice-long", "change", updateVoiceLongPreview);
  on("audio-voice-text", "input", updateVoiceLongPreview);
  on("audio-voice-tramos", "input", updateVoiceLongPreview);
  updateVoiceLongPreview();

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

  on("btn-audio-mode-a", "click", () => setAudioMode("a"));

  on("btn-audio-mode-b", "click", () => setAudioMode("b"));

  loadAudioClips();
  refreshAudioStatus();
  updateLatestMixDefaults();
  setAudioMode("b");
}
