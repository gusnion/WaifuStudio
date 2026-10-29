# CHECKLIST BUGFIX 2.5.0 — cierre de paquetes

Fecha: 2026-10-29. Ámbito: `PLAN-BUGFIX-2.5.0`. No es 2.5.1.
Convención: `[x]` hecho con evidencia · `[!]` implementado con verificación pendiente.

## W13 — Audio a demanda en Estudio

- [x] **W13** Botón “Generar audio”, primer clip de vídeo como `source_gen`, job MMAudio, subida/adjunto del WAV y guardado del proyecto.
  - Evidencia: `templates/index.html` (`btn-timeline-gen-audio`, `btn-timeline-audio-cancel`, paso 3), `static/js/tabs/timeline.js` (`findAudioSourceClip`, `extractWavOutput`, `buildAudioTrackEntry`, `generateTimelineAudio`, `enqueueJobs`), `tests/test_timeline_audio.mjs` (tests 7–9), `tests/test_timeline.py` (`test_w13_timeline_audio_on_demand_ui_contract`), `tests/test_audio.py` (`test_api_audio_generate_accepts_source_gen_id`).
  - Paso 3: CTAs y duración contextuales; opciones >15 s retiradas; imagen usa el modelo/tamaño del proyecto.
  - Comandos: `node --check static/js/tabs/timeline.js`; `node tests/test_timeline_audio.mjs`; `python -m unittest tests.test_timeline tests.test_audio` → 80 OK; suite completa → 1853 OK, 1 skipped.
  - Commits: `517731c`, `60ac03e`.

## W16b — AUDIO en tres pasos

- [x] **W16b** Pestaña AUDIO en tres pasos, un motor por modo, picker con preview, Mezclar deshabilitado si el clip es mudo, resultado con pestañas/visor único y stems secundarios.
  - Evidencia: `templates/index.html` (`audio-step-1/2-a/2-b/3`, `audio-clip-preview`, `audio-result-tabs`, `audio-mix-card` como `<details>`), `static/js/tabs/audio.js` (`showAudioResult`, `updateMixAvailability`), `static/css/tabs/audio.css`; avisos japonés/SilentCipher junto a la voz.
  - Eliminados los checkboxes falsos `audio-engine-mmaudio` y `audio-engine-irodori`.
  - “Enviar a Timeline” real vía `/api/timeline/upload_audio` y evento `waifu:timeline-audio-add`; el Timeline guarda la pista.
  - Sin progreso simulado en voz: se retiró el `setInterval`; estado honesto de espera.
  - Comandos: `node --check static/js/tabs/audio.js`; `python -m unittest tests.test_audio tests.test_timeline` → 85 OK; suite completa → 1856 OK, 1 skipped.
  - Commit: `609296c`.

## W15 — Vídeo local y cola por tramos

- [!] **W15** Implementado el vídeo local y el pipeline por tramos; falta la validación end-to-end con GPU/ComfyUI real.
  - Evidencia de implementación: `app/upscale.py` (`plan_video_chunks`, `validate_video_upscale_dimensions`, `_split_video_chunks`, `_mux_original_audio`, `run_video_upscale`), `app/routes/upscale.py` (`video_b64`, `/api/upscale/plan`), `static/js/tabs/upscaler.js` (entrada local, `updateUpscaleChunkHint`, `video_b64`, progreso “tramo i/N”), `templates/index.html` (`upscale-video-file`, `upscale-chunk-hint`), `app/routes/jobs.py` (progreso de tramos).
  - Prueba real de media (sin GPU): vídeo sintético 1920x1080, 24 fps, 10 s, 240 frames → plan 150+90 (2 tramos); split real con `tools/ffmpeg/ffmpeg.exe`; concatenación → 240 frames, 10,0 s; remux de audio original → pista de audio presente.
  - Tests: `python -m unittest tests.test_video_upscale_guard tests.test_upscale` → 132 OK; suite completa → 1868 OK, 1 skipped.
  - Limitación declarada: no se ejecutó el grafo RealESRGAN/RIFE en ComfyUI con GPU real; esa comprobación queda para la validación interactiva.
  - Commit: `a312eff`.

## W17d — OC Maker como pestaña real

- [x] **W17d** Contenido de `#oc-modal` movido a `#panel-oc`; sin `#btn-oc`, `#btn-oc-close` ni reparentado; jerarquía “Usar” + menú; “Entrenar LoRA” en cabecera; i18n; Escape de diálogos; estados vacíos.
  - Evidencia: `templates/index.html` (`#panel-oc` con aside/visor, `btn-oc-train`, sin `oc-modal`/`btn-oc`/`btn-oc-close`), `static/js/components/oc_picker.js` (`characterRow` con `oc-item-menu`, `t("Usar")`, `t("Más")`, `t(label)`), `static/js/main.js` (Escape cierra `closeOcConfirmModal`/`closeOcSaveModal`; sin `closeOcModal`), `static/js/i18n-data.js` (Usar/Duplicar/8 vistas/Generar LoRA/Generar pose/Entrenar LoRA en en/ja/ru/zh), `static/css/components.css` (`#panel-oc.tab-canonical-layout.active`, menú, ≤1100 px), `static/css/base.css` (sin `.oc-inline`).
  - Comandos: `node --check` de `oc_picker.js`, `main.js`, `i18n-data.js`; `python -m unittest tests.test_server tests.test_oc_traits` → 395 OK; suite completa final → 1869 OK, 1 skipped.
  - Commit: `fa571b9`.

## Cierre

- Limpieza final: `static/js/components/editor_multiview.js` ya no muestra “Hoja de contacto”; estado “Multivista lista”. Commit `c250cbe`.
- Suite completa final: **1869 tests OK, 1 skipped** (2026-10-29).
- `node --check`: `timeline.js`, `audio.js`, `upscaler.js`, `oc_picker.js`, `main.js`, `i18n-data.js`, `editor_multiview.js` OK.
- No se creó tag ni release.
