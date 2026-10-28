# C-21 / C-22 — Evidencia de Estudio (2026-10-27)

Proyecto: `tl_c21_demo` — 2 clips + 1 audio, recorte y fundido.

## Datos del proyecto

- Clip 1: `/media/1242/video_00008_.mp4`, `trim_in=0.5`, `duration=2.5`, fade in/out.
- Clip 2: `/media/1243/video_audio_1243.mp4`, `trim_in=0.0`, `duration=2.5`, fade in.
- Audio: `/media/audio/e9b71d68_audio_1243.wav`, inicio 0, duración 4.5, volumen 0.8.

## Export

`POST /api/timeline/export` con `{"project_id":"tl_c21_demo"}`:

```json
{"ok": true, "generation_id": 1244, "output_name": "timeline_1244.mp4", "output_url": "/media/1244/timeline_1244.mp4"}
```

`ffprobe` del resultado:

- H.264, 432×768.
- AAC, 44.1 kHz, 2 canales.
- Duración 5.023220 s.
- Archivo `data/gallery/1244/timeline_1244.mp4`.

## C-22

`BUG-TIMELINE-11` corregido en `2816b8b`; `node tests/test_timeline_logic.mjs` ejecutó 8/8, incluido “el primer clip define ancho, alto y fps del proyecto”. No hay controles muertos detectados en el flujo probado.
