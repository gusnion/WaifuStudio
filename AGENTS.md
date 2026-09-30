# AGENTS.md — guía para asistentes IA

Ámbito: este archivo describe la copia descargada de WAIFU que tienes delante (la webapp y su
engine local). No es el repo de desarrollo ni una autoridad de proyecto: es una guía práctica
para que una IA ayude al usuario a instalar, configurar, ampliar o depurar ESTA app. Trabaja en
español, sin emojis, y verifica los hechos en el código antes de afirmarlos.

## Qué es y cómo se ejecuta

WAIFU es una webapp local (FastAPI + plantillas Jinja2 + JS sin frameworks ni CDN) que genera
imágenes y vídeo anime usando ComfyUI como engine. Solo-GPU (probado en RTX 3060 12 GB), de uso
personal, sin filtros NSFW/SFW. Puertos por defecto:

- App: `http://127.0.0.1:8765` (host fijo `127.0.0.1`, puerto configurable con `WAIFU_APP_PORT`).
- Engine ComfyUI: `http://127.0.0.1:8288` (configurable en `scripts/start_engine.ps1` y con
  `WAIFU_COMFY_URL`).
- Datos del usuario: `data/` (sqlite, galería, personajes, registros de usuario).

Launchers (raíz del repo; PowerShell 5.1):

```
INICIAR_ENGINE.bat   -> scripts\start_engine.ps1  -> ComfyUI: python -s main.py --listen 127.0.0.1 --port 8288 --disable-api-nodes --disable-auto-launch
INICIAR_WAIFU.bat    -> scripts\start_app.ps1     -> .venv\Scripts\python.exe -m app.server
DETENER_ENGINE.bat   -> scripts\stop_engine.ps1   (rechaza parar si hay jobs en la cola)
DETENER_WAIFU.bat    -> scripts\stop_app.ps1
VERIFICAR_WAIFU.bat  -> .venv\Scripts\python.exe -m app.health
```

Comandos directos equivalentes (desde la raíz del repo):

```powershell
& .\.venv\Scripts\python.exe -m app.server                 # app (uvicorn)
& .\.venv\Scripts\python.exe -m app.health                 # rutas + ping al engine
& .\.venv\Scripts\python.exe -m app.health --require-engine
& .\.venv\Scripts\python.exe -m unittest discover -s tests # 1095 tests offline (CPU, mocks)
```

Los scripts comprueban que el proceso del puerto sea realmente de WAIFU (`.venv` o el Python
gestionado en `python\`) antes de arrancar o parar; no matan procesos ajenos.

## Mapa del código

`app/` (todo el backend; stdlib + dependencias de `requirements.txt`):

- `server.py`: webapp FastAPI. Rutas `/api/*` (modelos, LoRAs, preprompts, tags, personajes,
  formatos, vídeo, upscaler, editor, visión, enhance, generate, jobs, gallery), sirve la UI y el
  media, y contiene los runners de generación/entrenamiento. `_JOBS` es estado en memoria del
  proceso (se pierde al reiniciar).
- `config.py`: `EngineConfig` y lectura de entorno (`WAIFU_COMFY_ROOT`, `WAIFU_COMFY_URL`,
  `WAIFU_DATA_DIR`). `APP_ROOT` es la raíz del repo.
- `engine.py`: cliente HTTP mínimo de la API de ComfyUI (`/prompt`, `/history/<id>`, `/queue`,
  `/interrupt`, `/system_stats`), con transporte inyectable para tests. `load_graph` valida
  plantillas API-format.
- `graphs.py`: parcheo de grafos de imagen (loaders por `class_type`, sampler, parámetros,
  img2img) siempre sobre copias.
- `jobs.py`: cola 1-GPU en serie (un hilo daemon); el engine no admite concurrencia.
- `store.py`: sqlite `data/waifu.db`, tabla `generations` (estados y `kind` image/video/train).
- `registry.py`: registro versionado de modelos; carga `registry/models.json` y fusiona la capa
  de usuario `data/registry/models.json` (gana la de usuario por `id`).
- `loras.py`: biblioteca de LoRAs; la capa de usuario es `data/registry/loras.json` y las
  escrituras van ahí. Pesos válidos: `[0, 2]`.
- `enhancer.py`: «Mejorar prompt» (LLM local + RAG + preprompts) y `load_local_llm`.
- `vision.py`: WD14 (onnxruntime, CPU) y caption Qwen2.5-VL (llama-cpp); `VisionService` con
  cargas perezosas.
- `prompt_zones.py`: zonas del prompt, orden Anima, subcategorías y opciones.
- `tags.py`: catálogo Danbooru de `registry/tags_danbooru.json` (3249 etiquetas con rank).
- `preprompts.py`: preprompts certificados por familia y preprompts propios
  (`data/preprompts.json`).
- `formats.py`: presets de tamaño de `registry/formatos-v1.json`.
- `h3_presets.py`: perfiles H3 (Referencia/Calidad/Ligero), variantes turbo4/turbo8, segundos y
  resoluciones de `registry/h3_presets-v1.json`.
- `h3_prompt.py`: «Mejorar prompt (H3)»; escribe los tres bloques con el LLM.
- `motion.py`: «Mejorar prompt (video)» para el motor Wan con el LLM.
- `video.py`: grafos y runner de vídeo (H3 con modos **I2V** y **FLF2V**; Wan conservado en código como legado, sin selector en la UI).
- `video_presets.py`: presets Wan de `registry/video_presets-v1.json`.
- `editor.py`: grafo y runner del Editor Qwen-Image 2.1 UC (hasta 10 referencias); tamaño «Original» (`inherit_size_from_image`) hereda el de la primera referencia.
- `editor_models.py`: nombres reales del par UC (`registry/editor_models-v1.json`).
- `upscale.py`: upscaler de imagen (RealESRGAN ×2, y ×4 con doble pasada), de vídeo por
  fotogramas y RIFE (`registry/upscalers-v1.json`).
- `characters.py`: OCs en sqlite + referencias copiadas a `data/characters/<id>/`.
- `trainer.py`: entrenador de LoRA; prepara dataset/config y lanza un comando externo
  (`WAIFU_TRAINER_CMD`). La instalación del fork kohya está pendiente: aquí solo se orquesta.
- `health.py`: smoke CLI (rutas críticas + ping al engine).
- Otros: `params.py` (enums reales de sampler/scheduler), `progress.py` (progreso por WebSocket),
  `oc_traits.py` y `sheet.py` (OC Maker), `gate_f0/f1/f2.py` (gates GPU/CPU del proyecto).

Resto del repo:

- `workflows/`: plantillas API-format de ComfyUI (Anima base, 3 de H3, editor Qwen-Image 2.1,
  2 de Wan legado). Se envían al engine sin editar a mano.
- `registry/`: catálogos de solo lectura (`tags_danbooru.json`, `formatos-v1.json`,
  `h3_presets-v1.json`, `video_presets-v1.json`, `upscalers-v1.json`, `editor_models-v1.json`,
  `recommended-v1.json`) y `models.json`/`loras.json`, VACÍOS a propósito: el repo trae código,
  no tu contenido.
- `data/`: capa de usuario, la escriben la app y el instalador (`data/registry/`, `data/gallery/`,
  `data/characters/`, `data/trainer/`, `data/preprompts.json`, `data/waifu.db`). No vive en git.
- `static/` + `templates/`: UI de una página (pestañas Imagen, Vídeo, Editor, Upscaler, galerías y
  OC Maker).
- `install/`: `install.ps1`, manifiestos con pines (`manifest.models.json`,
  `manifest.nodes.json`), `README_INSTALL.md` y `manifest/licenses/` (aviso pendiente).
- `tests/`: suite unittest offline (sin GPU ni red). `docs/`: `prompting_anima.md`.

## Cómo funciona

Flujo de generación (imagen, vídeo, editor, upscaler; todos igual): la UI hace `POST` a la API
→ `server.py` valida y encola en `jobs.py` → el runner parchea la plantilla de `workflows/` con
modelo/params/LoRAs/referencias → `engine.py` hace `POST /prompt` y espera `/history` →
los resultados se copian a `data/gallery/<gen_id>/` → `store.py` refleja estado y salidas →
la UI consulta `GET /api/jobs/<gen_id>` (progreso por WebSocket vía `progress.py`).

Capa de registros: el repo publica registros vacíos y catálogos; los datos reales del usuario
están en `data/`. `registry.py` y `loras.py` leen ambas capas y las fusionan (el `id` de la capa
de usuario gana). Cualquier escritura (gestionar LoRAs, registrar modelos) va a `data/registry/`;
nunca reescribas los JSON del repo para "arreglar" la app.

Configuración por entorno (todas opcionales):

| Variable | Efecto |
|---|---|
| `WAIFU_COMFY_ROOT` | Ruta de ComfyUI (por defecto `ComfyUI\` en el repo) |
| `WAIFU_COMFY_URL` | URL del engine (por defecto `http://127.0.0.1:8288`) |
| `WAIFU_DATA_DIR` | Carpeta de datos (por defecto `data\` en el repo) |
| `WAIFU_APP_PORT` | Puerto de la app (por defecto 8765) |
| `WAIFU_LLM_MODEL` | GGUF del LLM local (si no, el Q4_K_M hermano del default) |
| `WAIFU_VL_MODEL`, `WAIFU_VL_MMPROJ`, `WAIFU_VL_GPU_LAYERS` | Modelo, mmproj y capas GPU del caption VL |
| `WAIFU_TRAINER_CMD` | Comando del entrenador externo de LoRA |

LLM local: `llama-cpp-python` en CPU (`n_gpu_layers=0`, `n_ctx=2048`), GGUF Qwen2.5-7B
abliterado en `ComfyUI/models/llm/Qwen25-7B-abliterated/`. El default del enhancer es Q3_K_M; el
servidor prefiere el Q4_K_M si existe (escribe mejor en inglés). La carga es perezosa: la paga la
primera llamada a `enhance`, `motion` o `h3_prompt`.

Visión: WD14 con onnxruntime en CPU sobre `ComfyUI/models/wd14` y caption Qwen2.5-VL con
llama-cpp usando el mmproj de `ComfyUI/models/llm/qwen25vl-7b-abliterated-gguf`. Consulta el
estado con `GET /api/vision/status`; si faltan pesos, la UI lo indica. Los pesos de visión están
en el manifiesto como **opcionales**: `INSTALAR.bat -IncludeOptional` los descarga (~6,4 GB);
también se pueden aportar a mano o ajustar con `WAIFU_VL_*`.

Engine: ComfyUI **v0.37.4** pinneado por commit, con nodos también pinneados en
`install/manifest/manifest.nodes.json` (ComfyUI-GGUF del fork **leejet**, KJNodes para el toggle
SageAttention, Frame-Interpolation para RIFE y ClipProj para H3). Dato crítico: el GGUF de
Qwen-Image 2.1 del Editor exige el fork leejet de ComfyUI-GGUF (línea `qwen_image21`); el fork
original no lo carga.

## Tareas frecuentes del asistente

1. **Instalar**: `INSTALAR.bat` en consola (equivale a `install\install.ps1`). Preflight:
   Windows 10/11 x64, GPU NVIDIA, ≥140 GB libres. Instala uv + CPython 3.12.12, `.venv`,
   ComfyUI v0.37.4 + nodos + torch cu130 + SageAttention, pregunta por los modelos recomendados
   (~106 GB) y verifica con SHA256. Es repetible. Banderas: `-SkipEngine`, `-SkipModels`,
   `-IncludeOptional`, `-SkipVerify`, `-NoUserEnv`, `-Yes`.
2. **Añadir modelos**: edita `data/registry/models.json` (o deja que `INSTALAR.bat` registre los
   recomendados presentes en disco). Esquema por entrada:

   ```json
   {
     "version": 1,
     "models": [
       {
         "id": "mi-modelo",
         "family": "anima",
         "display_name": "Mi modelo",
         "profile": {
           "unet_name": "mi_modelo.safetensors",
           "clip_name": "qwen_3_06b_base.safetensors",
           "clip_type": "stable_diffusion",
           "vae_name": "qwen_image_vae.safetensors"
         },
         "source": "origen del archivo",
         "license": "licencia del modelo",
         "preprompt": "glossy",
         "defaults": { "steps": 20, "cfg": 4.0 },
         "notes": ""
       }
     ]
   }
   ```

   Toma `registry/recommended-v1.json` como ejemplo real. Los nombres de `profile` deben existir
   bajo `ComfyUI/models/`; `id` solo admite `[a-z0-9._-]`. Reinicia la app para verlo.
3. **Añadir LoRAs**: desde la UI (Imagen → «Elegir LoRAs» → «Gestionar biblioteca») o editando
   `data/registry/loras.json`. Campos: `id`, `family`, `file` (relativo a
   `ComfyUI\models\loras`), `display_name`, `trigger`, `default_weight` (0-2), `source`,
   `license`, `notes`.
4. **Cambiar puertos**: app → `WAIFU_APP_PORT`; engine → edita el `--port` en
   `scripts\start_engine.ps1` y apunta `WAIFU_COMFY_URL` al nuevo puerto.
5. **Correr tests** antes de dar por bueno un cambio Python:
   `& .\.venv\Scripts\python.exe -m unittest discover -s tests`. Son 1095 tests offline.
6. **Ver logs**: la salida de la app y del engine es el stdout de sus consolas
   (`INICIAR_ENGINE.bat` / `INICIAR_WAIFU.bat`); ComfyUI escribe resultados en `ComfyUI\output`.
   El instalador deja marcadores en `.install-state\`.

## Convenciones

- Responde en español y no añadas emojis a los archivos.
- Cada cambio de código, con test unittest offline; no debilites ni borres tests existentes.
- No borres `data/` ni sobrescribas modelos del usuario: galería, OCs, LoRAs y registros son
  irrecuperables si se pierden.
- No toques `ComfyUI/` salvo petición explícita (es el engine y los pesos del usuario).
- Cambios pequeños y verificables; ejecuta la suite al terminar.
- No inventes URLs, IDs de modelos ni rutas: usa las del repo (`registry/`, `install/manifest/`).

## Diagnóstico de problemas frecuentes

- **El engine no responde**: arranca `INICIAR_ENGINE.bat` y espera a que cargue; comprueba con
  `.venv\Scripts\python.exe -m app.health --require-engine`. Si el puerto 8288 está ocupado por
  otra aplicación, los launchers se niegan a usarlo: libera el puerto o cambia el `--port`.
- **CUDA/torch roto**: los pines son torch 2.11.0+cu130 (backend cu130). Reinstala con
  `INSTALAR.bat` (es idempotente) o `uv pip install` de los pines de
  `install/manifest/manifest.nodes.json`. No mezcles versiones de torch a mano.
- **Un modelo no aparece en la UI**: revisa `data/registry/models.json` (esquema y que los
  archivos de `profile` existan bajo `ComfyUI/models/`); reinicia la app.
- **Una LoRA no aplica**: comprueba que está registrada en `data/registry/loras.json`, con el
  `trigger` correcto, peso en `[0, 2]` y `family` de la pestaña. Ojo con el desajuste de bloques:
  las LoRAs Anima de 28 bloques rinden mejor en el modelo de 28 que en el de 40.
- **Error `Unexpected architecture type ... qwen_image21` (Editor)**: ComfyUI-GGUF no es el fork
  leejet o está desactualizado. Reinicia `INSTALAR.bat` (fija el commit del manifiesto) o
  actualiza solo ese custom node al commit pineado.
- **VRAM insuficiente en vídeo**: usa el perfil Ligero, menos segundos (5-8) o una resolución
  menor; la cola es 1-GPU y serializa los jobs, así que cierra otras apps que usen la GPU y no
  lances dos generaciones a la vez.

## Dónde mirar más

- `install/README_INSTALL.md`: instalación, banderas y qué no se incluye.
- `install/manifest/manifest.models.json` y `manifest.nodes.json`: pines, tamaños, hashes y URLs.
- `registry/recommended-v1.json`: set recomendado y los 2 Anima de aporte manual.
- `THIRD_PARTY_NOTICES.md`: licencias de pesos y dependencias (Anima es no comercial).
- `docs/prompting_anima.md`: manual de prompting Anima del proyecto.
- `LICENSE`: el código es MIT.
