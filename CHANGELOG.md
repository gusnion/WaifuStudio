# Changelog

## Unreleased — Linux deployment

- `[LINUX]` Native Linux install path: `install-linux.sh`, `start-linux.sh`, `stop-linux.sh`, `healthcheck.sh`, plus `README` steps and `docs/linux.md`.
- `[LINUX]` POSIX normalization for model/LoRA paths, extensionless `ffmpeg` discovery, `xdg-open` for exported folders, and a Linux llama.cpp runtime (`manifest.llm.linux.json`).
- `[CI]` `linux-smoke` workflow: shell syntax and Linux deployment checks.

## 2.5.1 — 2026-10-30

Primer y único tag de la línea 2.5. Cubre las funciones congeladas de 2.5 y las correcciones de 2.5.1.

- `[OC]` OC Maker rediseñado: modal Crear/Generar, catálogo completo y tags manuales, autosave, referencias local/galería paginada, multivistas 4/6/8, duplicar/renombrar/eliminar con confirmación.
- `[COMPAT]` Registro de capacidades y motores de vídeo; validación por registro y endpoint de lectura.
- `[REGISTRY]` Contrato de propiedad/estado de pesos por addon y ruta efectiva del directorio de modelos.
- `[MODEL]` Vídeo Wan AIO adopta el text encoder NSFW fp8 y el LoRA `NSFW-22-H-e8` a 0.8; comparación previa de 4 variantes sin adopción del resto.
- `[UI]` AUDIO en tres pasos; OC Maker como pestaña real; fichas flotantes de modelo, LoRA y prompts.
- `[FIX]` Correcciones de Estudio, audio a demanda, vídeo local por tramos y textos de referencia.
- `[DOCS]` `SKILL.md` descargable y ampliado; guía de conexión de agentes; README reescrito.
- `[SEC]` Guard de pre-push y checklist de limpieza.

## 2.5.0 — 2026-10-28 (funciones congeladas, sin tag)

- Cierre manual de 2.5: 42 ítems `[x]` + C-42 `[!]` autorizado por el usuario.
- Sin tag `v2.5.0` ni release remoto: el remoto rechazó la clave pública y `gh release view v2.5.0` dio `release not found`.
- Instalación limpia verificada en `G:\IA\WAIFU-25-clean`: app, ComfyUI 0.42.5, `app.health` OK y primera imagen gen 1.
- Suite final: 1.785 tests OK, 1 skipped.
- Evidencia y auditoría: `docs/2.5/CIERRE_2.5.md`.

## Unreleased — Video Wan 2.2 sin BETA

- Video queda sin badge BETA y sin controles visibles H3/VDN.
- Prompt enhancer Wan con enfoque (movimiento/cámara/acción/expresión) y fuerza.
- Guía Wan integrada con plantillas de retrato, caminata y acción.
- Preview de imagen inicial/final, prompt negativo, sampling manual y seed.
- Perfiles Fast/Standard/Quality y modo Manual con sampler, scheduler, pasos, shift y resolución propia.
- Envío directo de un vídeo generado a Timeline.
- Timeline migrado de H3 a Wan para Continuar I2V y Puente FLF2V.
- **Wan 2.2 NSFW AIO v10 Q4_K_M** opcional: grafo de un solo UNet y un `KSampler`; selector “Wan 2.2 NSFW AIO v10 · experimental”; solo I2V. Verificado con clip de 5 s a 432×768 en RTX 3060.
- MMAudio conserva su motor actual; se aplican los prompts de TW-12: positivo `soft breathing, quiet moans, wet sounds, fabric rustling` y negativo `speech, talking, dialogue, shouting, screaming, singing, crowd`.
- No se añadió pestaña de Audio ni modelos de sonido nuevos.
- Suite offline: 1.731 tests OK, 1 skipped.

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
