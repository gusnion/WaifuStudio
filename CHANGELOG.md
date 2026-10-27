# Changelog

## 2.1.0 — 2026-10-26

### Motor y modelos

- ComfyUI 0.42.5 como base.
- Wan 2.2 I2V/FLF2V con high/low Q4_K_S, umt5 Q5_K_M, VAE Wan 2.1 y LightX2V.
- Perfiles Fast (4 pasos/CFG 1) y Quality (30 pasos/CFG 4, LoRA 0).
- Audio MMAudio en los MP4 de Wan.
- Set oficial: Animagine XL 4.0 Opt, RealVisXL V5 y Juggernaut XL Ragnarok.
- FFmpeg/FFprobe con URL, tamaño y SHA256 fijados.

### Producto

- Editor Qwen-Image 2.1 con licencia persistida y multivista 4/6/8.
- Defaults por modelo editables desde la UI.
- Addons: ZIP, slots exclusivos, rollback y catálogo externo con `requires_core`.
- Timeline: el primer clip fija ancho, alto y FPS.
- Tokens de diseño, tema claro/oscuro AA y sistema visual en pestañas canónicas.
- Chequeo de primera ejecución con reintentos y detección de la GPU de mayor VRAM.
- Catálogo web JSON descargable.
- Guías de agente y SKILL de API.

### Correcciones

- El motor selecciona la GPU de mayor VRAM mediante `CUDA_VISIBLE_DEVICES`.
- El aviso de primera ejecución reintenta antes de mostrar un falso positivo.
- La multivista usa una sola referencia por vista y pausa entre jobs para no saturar 12 GB.

### Verificación

- Suite offline: 1.643 tests OK, 1 skipped.
- Tests JS de Timeline, cola, audio, upscaler, reúso de vídeo y multivista.
