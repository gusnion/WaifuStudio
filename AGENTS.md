# AGENTS.md — Guía de Instalación, Diagnóstico y Desarrollo para Agentes IA (WaifuStudio v2.1.0)

Este archivo es la autoridad técnica embebida del repositorio **WaifuStudio** (versión compactada del plano de control `.agents`). Tiene dos propósitos:
1. **Asistir al usuario final** en la instalación, configuración y resolución de problemas en máquinas Windows con GPUs NVIDIA RTX 3000 / 4000 / 5000 (8 GB+ VRAM).
2. **Permitir a cualquier agente IA retomar el desarrollo** sin lecturas ciegas ni pérdida de contexto (Protocolo *Zero-Blind-Read*).

Trabaja siempre en español, de forma concisa y directa, sin emojis, verificando los hechos en el código antes de afirmarlos.

---

## 1. Qué es WaifuStudio y Arquitectura de Ejecución

Webapp local autónoma (**FastAPI + Jinja2 + Vanilla ES Modules / CSS modular**, cero bundlers ni telemetría) que utiliza **ComfyUI v0.42.5** como engine desacoplado:
- **App Web**: `http://127.0.0.1:8765` (`WAIFU_APP_PORT`). Lanzador ligero en ventana dedicada (~100 MB RAM): `start.bat` (`scripts/open_window.ps1`).
- **Engine ComfyUI**: `http://127.0.0.1:8288` (`WAIFU_COMFY_URL`), cola estrictamente monohilo FIFO (`app/jobs.py`) dimensionada para **1 GPU desde 8–12 GB VRAM (RTX 3060+)**.
- **LLM / Visión en CPU (`:8290`)**: `Qwen3.5-9B NSFW Captioning v5` (`Q4_K_M` + `mmproj-Q8_0`) servido por `tools/llama.cpp/llama-server.exe` con `-ngl 0` (100% CPU, 0 VRAM). La app lo arranca y detiene automáticamente mediante `app/llm_server.py`.
- **7 Pestañas**:
  1. **Imagen**: checkpoints **Animagine XL 4.0 Opt, RealVisXL V5 y Juggernaut XL Ragnarok** (SDXL) con `LoraLoader` dual, auto-detección de arquitectura de LoRAs por tensores (`infer_lora_family`) e inyección automática de *triggers*.
  2. **Vídeo**: **Wan 2.2 I2V/FLF2V** con perfiles Fast (4 pasos) y Quality (30 pasos), LightX2V y audio MMAudio.
  3. **Editor**: **Qwen-Image 2.1 Uncensored** (GGUF `Q4_K_M`, hasta 10 referencias, inpaint/edición con modo «Original 1ª ref» y `CFG=1`).
  4. **Upscaler**: **RealESRGAN x2/x4** (imagen/vídeo) + **RIFE** (interpolación FPS) con visor comparador interactivo antes/después.
  5. **Estudio/Timeline**: secuenciador de clips e imágenes con export MP4, biblioteca de medios e IA Wan.
  6. **Galería**: Persistencia en SQLite (`data/waifu.db`, modo WAL) y copias seguras (`shutil.copy2`) en `data/gallery/<id>/`.
  7. **OC Maker**: ficha de personaje, referencias, hoja de vistas y entrenamiento LoRA; ahora es pestaña, no modal.
  - **Guía** y **Addons** viven en la barra superior derecha, no en la navegación principal.

---

## 2. Guía para Asistir en la Instalación (`install.bat` / `install/install.ps1`)

El instalador está diseñado en **Modo Hermético 100% Portable** para no colisionar con instalaciones previas de Python (3.10, 3.11, 3.12, 3.13), Conda, Automatic1111 o Forge en la PC del usuario:

1. **Aislamiento de Python y Variables (`scripts/environment.ps1` e `install/install.ps1`)**:
   - Limpia en memoria `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`, `CONDA_PREFIX` y fuerza `UV_PYTHON_PREFERENCE=only-managed`.
   - Instala `uv` local en `tools\uv\` y CPython `3.12.12` portable en `python\cpython-3.12.12-windows-x86_64-none\`.
   - Verifica `.venv\pyvenv.cfg`: si existe un `.venv` previo apuntando a un Python del sistema del usuario, lo elimina y recrea herméticamente.
2. **Orden de Dependencias GPU**:
   - Clona `ComfyUI` (`v0.42.5`), instala los *custom nodes* (`ComfyUI-GGUF` fork *leejet*, `ComfyUI-KJNodes`, `ComfyUI-Frame-Interpolation`, `ComfyUI-ClipProj`, `ComfyUI-VDN-H3-Plus`, `ComfyUI-VideoHelperSuite`, `ComfyUI-MMAudio` y el nodo local `tools/custom_nodes/waifu_anima_patch`) junto con sus `requirements.txt` / `requirements-no-cupy.txt`, y **al final** fuerza `torch==2.11.0+cu130`, `torchvision==0.26.0+cu130`, `torchaudio==2.11.0+cu130`, `triton_windows==3.8.0.post28` y `SageAttention` (este último en bloque `try/catch` no bloqueante para compatibilidad con RTX 5000 Blackwell).
3. **Banderas útiles de `install\install.ps1` (o pasadas a `install.bat`)**:
   - `install.bat` (interactivo: instala engine + LLM + pregunta si descargar ~100 GB de modelos recomendados + VDN-H3).
   - `install.bat -SkipModels` (instala solo Engine + App + LLM ~15 GB; requiere >= 25 GB libres; ideal para usuarios que usarán sus propios checkpoints SDXL/Anima).
   - `install.bat -SkipModels -SkipLlm` (solo Engine + App ~8 GB).
   - `install.bat -IncludeOptional` (incluye modelos opcionales como Ref2VA DiT y WD14).
   - `install.bat -IncludeTrainer` (instala `tools/kohya` con `sd-scripts` v0.12.0 en su propio venv para entrenar LoRAs).
   - `install.bat -SkipFfmpeg` (no descarga FFmpeg/FFprobe; Timeline/export/fade quedan deshabilitados).
4. **Diagnóstico Rápido de Problemas de Instalación**:
   - **`torch.cuda.is_available() == False` o error de driver CUDA**: El stack usa `cu130` (CUDA 13.0). El usuario debe actualizar su **Driver NVIDIA Game Ready / Studio a versión >= 570.xx**. Verificar con `nvidia-smi`.
   - **Faltan modelos Wan**: verifica `install/manifest/manifest.wan.json` y ejecuta `& .\.venv\Scripts\python.exe scripts\fast_download_wan.py`.
   - **Falta el LLM o `llama-server.exe`**: Ejecutar `& .\.venv\Scripts\python.exe scripts\download_llm.py`.
   - **Modelos o LoRAs añadidos a mano no aparecen**: Colocarlos en `ComfyUI/models/checkpoints/`, `diffusion_models/` o `loras/` y pulsar el botón de recarga universal en la barra superior de la web (o invocar `GET /api/models?scan=1` / `POST /api/loras/scan`).

---

## 3. Reglas de Desarrollo para Agentes IA (Protocolo *Zero-Blind-Read*)

1. **PRODUCT_FIRST y Protección de Datos**: Priorizar soluciones simples y estables. **Prohibido** borrar o sobrescribir `data/` (galería, base de datos SQLite, personajes, `data/registry/`), `ComfyUI/models/` o configuraciones del usuario.
2. **Prohibido leer archivos >300 líneas completos**: Consulta primero las tablas de las secciones 4, 5 y 6 de este documento, localiza el símbolo con `grep` / `Select-String` y lee únicamente el rango necesario (`offset`, `limit=80`).
3. **Verificación obligatoria antes de cerrar cambios**:
   ```powershell
   & .\.venv\Scripts\python.exe -m unittest discover -s tests   # 1.649 tests offline en CPU (~60 s)
   node tests/test_upscale_compare_logic.mjs                    # 10 tests de lógica JS del comparador
   & .\.venv\Scripts\python.exe -m app.health                   # Diagnóstico de rutas y servicios
   ```

---

## 4. Mapa Completo de Salto Rápido (Frontend ↔ Router ↔ Backend Core)

| Dominio / Función | Frontend (`static/js/`) | Router (`app/routes/`) | Lógica Core (`app/`) |
|---|---|---|---|
| **Arranque SPA y estado global** | `main.js`, `state.js`, `dom.js` | `system.py` (`GET /`) | `server.py`, `config.py` |
| **Header (Recarga + Idioma)** | `components/header.js` | Cliente (`localStorage`) | Evento `waifu:language-changed` |
| **Jobs, Polling y Cancelación** | `api.js` (`pollJob`, `cancelJob`) | `jobs.py` (`/api/jobs/*`) | `jobs.py::JobQueue`, `progress.py`, `store.py` |
| **Imagen (Anima / SDXL)** | `tabs/image.js`, `tabs/image_viewer.js` | `image.py` (`POST /api/generate`) | `graphs.py`, `engine.py`, `params.py`, `formats.py` |
| **Modelos y Auto-scan** | `tabs/image.js` | `models.py` (`GET /api/models`) | `registry.py`, `models.py::scan_disk_models` |
| **LoRAs y Filtrado por Tensores** | `components/loras.js` | `models.py` (`/api/loras*`) | `loras.py`, `models.py::scan_disk_loras`, `infer_lora_family` |
| **Zonas de Prompt y Popover** | `components/prompt_zones.js`, `prompt_popover.js` | `prompt.py` (`/api/prompt/*`), `tags.py` | `prompt_zones.py`, `tags.py` (SQLite FTS5 91k tags) |
| **Mejorador LLM y Visión** | `tabs/image.js`, `components/vision.js` | `prompt.py` (`/api/enhance*`, `/api/vision/*`) | `enhancer.py`, `vision.py`, `llm_server.py`, `preprompts.py` |
| **OC Maker y Entrenador Kohya** | `components/oc_picker.js`, `oc_train.js` | `characters.py` (`/api/characters*`) | `characters.py`, `oc_traits.py`, `sheet.py`, `trainer.py` |
| **Vídeo Wan 2.2 (I2V/FLF2V)** | `tabs/video.js` | `video.py`, `presets.py` | `video.py`, `video_presets.py` |
| **Editor Qwen-Image 2.1 UC** | `tabs/editor.js` | `editor.py` (`/api/editor/*`) | `editor.py`, `editor_models.py` |
| **Upscaler (RealESRGAN + RIFE)** | `tabs/upscaler.js` | `upscale.py` (`/api/upscale*`) | `upscale.py` |
| **Galería y Medios** | `tabs/gallery.js`, `components/lightbox.js` | `gallery.py` (`/api/gallery*`, `/media/*`) | `store.py::Store` |
| **Componentes UI Canónicos** | `components/universal_viewer.js`, `resolution_kit.js`, `tooltip_help.js`, `compare.js` | Cliente | Zoom 8x, split compare, selector dual SD..2K, popovers `(?)` |

---

## 5. Mapa de Endpoints HTTP (`app/routes/*.py`)

- **`system.py`**: `GET /` (L24)
- **`image.py`**: `POST /api/generate` (L273)
- **`models.py`**: `GET /api/models` (L574), `GET /api/loras` (L593), `POST /api/loras/scan` (L606), `POST /api/loras` (L620), `POST /api/loras/upload` (L634), `PUT /api/loras/{lora_id}` (L700), `DELETE /api/loras/{lora_id}` (L722)
- **`jobs.py`**: `GET /api/jobs/{job_id}` (L42), `POST /api/jobs/{job_id}/cancel` (L86)
- **`prompt.py`**: `GET /api/negative` (L123), `POST /api/prompt/build` (L131), `POST /api/prompt/zones` (L136), `GET /api/prompt/options` (L145), `POST /api/prompt/compose` (L150), `POST /api/prompt/insert` (L158), `POST /api/enhance` (L169), `POST /api/prompt/enhance_zones` (L204), `POST /api/motion` (L276), `POST /api/video/h3_prompt` (L288), `GET /api/vision/status` (L316), `GET /api/llm/status` (L327), `POST /api/vision/image_to_prompt` (L333)
- **`tags.py`**: `GET /api/preprompts` (L45), `POST /api/preprompts/custom` (L60), `DELETE /api/preprompts/custom/{name}` (L71), `GET /api/traits` (L80), `GET /api/tags/groups` (L85), `GET /api/tags` (L90), `GET /api/tags/custom` (L111), `POST /api/tags/custom` (L116), `DELETE /api/tags/custom/{name}` (L132)
- **`characters.py`**: `GET /api/characters` (L82), `POST /api/characters` (L88), `GET /api/characters/{char_id}` (L102), `GET /api/characters/{char_id}/profile` (L111), `PUT /api/characters/{char_id}` (L120), `DELETE /api/characters/{char_id}` (L136), `POST /api/characters/{char_id}/refs` (L144), `GET /api/characters/{char_id}/refs` (L176), `POST /api/characters/{char_id}/sheet` (L190), `DELETE /api/characters/{char_id}/refs/{ref_id}` (L226), `POST /api/characters/{char_id}/train` (L238)
- **`video.py` & `presets.py`**: `POST /api/video/generate` (`video.py`:L64), `GET /api/params` (`presets.py`:L27), `GET /api/formats` (L37), `GET /api/video/presets` (L42), `GET /api/video/h3_profiles` (L58)
- **`editor.py`**: `GET /api/editor/status` (L83), `POST /api/editor/generate` (L101)
- **`upscale.py`**: `GET /api/upscale/models` (L33), `POST /api/upscale` (L46)
- **`gallery.py`**: `GET /api/gallery` (L33), `DELETE /api/gallery/{id}` (L66), `POST /api/gallery/clean_failed` (L102), `GET /media/characters/{char_id}/{name:path}` (L109), `GET /api/refs/{name:path}` (L124), `GET /media/{gen_id}/{name:path}` (L149), `GET /api/download/{gen_id}/{name:path}` (L164)

---

## 6. Rangos de Líneas de `templates/index.html` y Cascada CSS

- **Secciones en `templates/index.html` (1.753 líneas; no leer entero)**:
  - `L1–L63`: Header global, `nav.tabs`, acciones de Guía/Addons.
  - `L64–L339`: `#panel-image` | `L340–L688`: `#panel-video` | `L689–L884`: `#panel-editor` | `L885–L1033`: `#panel-upscaler` | `L1034–L1035`: `#panel-oc` | `L1036–L1149`: `#panel-timeline` | `L1150–L1201`: `#panel-gallery` | `L1202–L1366`: `#panel-guide` | `L1367–L1382`: `#panel-addons`.
  - `L1383–L1745`: modales OC/LoRA/Visión/Galería y `#lightbox` (L1746–L1753).
- **Orden de Cascada CSS (`static/css/`)**:
  `1. base.css` → `2. components.css` → `3. tabs/image.css` → `4. tabs/video.css` → `5. tabs/editor.css` → `6. tabs/upscaler.css` → `7. tabs/gallery.css` → `8. design-v2.css` → `9. light-theme.css`.
