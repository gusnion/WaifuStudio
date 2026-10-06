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
INICIAR_LLM.bat      -> scripts\start_llm.ps1     -> servidor LLM EXTERNO opcional (la app arranca el suyo sola; usar solo en modo externo con WAIFU_LLM_URL)
DETENER_ENGINE.bat   -> scripts\stop_engine.ps1   (rechaza parar si hay jobs en la cola)
DETENER_LLM.bat      -> scripts\stop_llm.ps1      (solo modo externo; procesos de tools\llama.cpp)
DETENER_WAIFU.bat    -> scripts\stop_app.ps1
VERIFICAR_WAIFU.bat  -> .venv\Scripts\python.exe -m app.health   (--require-llm exige el LLM listo)
```

Comandos directos equivalentes (desde la raíz del repo):

```powershell
& .\.venv\Scripts\python.exe -m app.server                 # app (uvicorn)
& .\.venv\Scripts\python.exe -m app.health                 # rutas + ping al engine y estado del LLM
& .\.venv\Scripts\python.exe -m app.health --require-engine
& .\.venv\Scripts\python.exe -m unittest discover -s tests # 1449 tests offline (CPU, mocks)
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
  img2img) siempre sobre copias; incluye inyección de `WaifuAnimaPatch28to40` para modelos Anima expandidos (`ANIMA_EXPANDED_MODELS`).
- `jobs.py`: cola 1-GPU en serie (un hilo daemon); el engine no admite concurrencia.
- `llm_server.py`: servidor LLM gestionado (M12). `LlamaServerManager` arranca/para
  `llama-server` como proceso hijo en CPU (`-ngl 0`) con el GGUF + mmproj del manifiesto;
  `probe`/`status` (ready/loading/foreign/offline) con spawn y probe inyectables en tests.
- `store.py`: sqlite `data/waifu.db`, tabla `generations` (estados y `kind` image/video/train).
- `registry.py`: registro versionado de modelos; carga `registry/models.json` y fusiona la capa
  de usuario `data/registry/models.json` (gana la de usuario por `id`).
- `loras.py`: biblioteca de LoRAs; la capa de usuario es `data/registry/loras.json` y las
  escrituras van ahí. Pesos válidos: `[0, 2]`.
- `enhancer.py`: «Mejorar prompt» (LLM + RAG + preprompts), validación estricta de tags
  (alias→canónico, inventados a `dropped`), vocabulario restringido y el adaptador
  `load_server_llm`/`server_llm_state`; `load_local_llm` (llama-cpp CPU) queda legado/solo gates.
- `vision.py`: WD14 (onnxruntime, CPU) y **descripción unificada en 1 llamada** al servidor
  OpenAI-compatible gestionado (`load_server_describer`); `VisionService` con cargas perezosas
  y `tagger_for(threshold)` para el auto-caption.
- `prompt_zones.py`: zonas del prompt, orden Anima, subcategorías y opciones.
- `tags.py`: catálogo Danbooru v3 de `registry/tags_danbooru.json`: capa curada (3249 con rank) +
  catálogo completo (91.357 con `posts`/`aliases`), soporte de override en `data/registry/tags_danbooru.json`, búsqueda FTS5 (`retrieve`) y validación
  (`is_valid`/`resolve`/`validate_list`).
- `preprompts.py`: preprompts certificados por familia y preprompts propios
  (`data/preprompts.json`).
- `formats.py`: presets de tamaño de `registry/formatos-v1.json`.
- `h3_presets.py`: perfiles H3 (Referencia/Calidad/Ligero/VDN), variantes turbo4/turbo8/vdn8, segundos y
  resoluciones de `registry/h3_presets-v1.json`.
- `h3_prompt.py`: «Mejorar prompt (H3)»; escribe los tres bloques con el LLM.
- `motion.py`: «Mejorar prompt (video)» para el motor Wan con el LLM.
- `video.py`: grafos y runner de vídeo (H3 con modos **I2V**, **FLF2V** y **Ref2VA**; perfiles Referencia, Calidad, Ligero y VDN 8-pasos).
- `video_chain.py`: utilidades OpenCV para encadenado continuo (>15 s): extracción de último fotograma (`extract_last_frame`), concatenación sin pérdida (`concat_videos`) y planificación de segmentos (`plan_chain_segments`).
- `video_presets.py`: presets Wan de `registry/video_presets-v1.json`.
- `editor.py`: grafo y runner del Editor Qwen-Image 2.1 UC (hasta 10 referencias); tamaño «Original» (`inherit_size_from_image`) hereda el de la primera referencia. En la UI, «Generar» admite referencias (archivo o clic en la galería) y «Editar» trabaja sobre la imagen seleccionada en el visor de Imagen (el backend exige ≥1 referencia en modo editar).
- `editor_models.py`: nombres reales del par UC (`registry/editor_models-v1.json`).
- `upscale.py`: upscaler de imagen (RealESRGAN ×2, y ×4 con doble pasada), de vídeo por
  fotogramas y RIFE (`registry/upscalers-v1.json`).
- `characters.py`: OCs en sqlite + referencias copiadas a `data/characters/<id>/`.
- `trainer.py`: entrenador de LoRA; prepara dataset/config (con **auto-caption WD14** opcional:
  `tagger` + umbral, `wd14_tags` en `manifest.json`) y lanza un comando externo
  (`WAIFU_TRAINER_CMD`). El entrenador real vive en `tools/kohya/` (checkout de
  `kohya-ss/sd-scripts` v0.12.0 con `networks.lora_anima`, venv propio y wrapper
  `run_waifu_train.py`); aquí solo se orquesta.
- `health.py`: smoke CLI (rutas críticas + ping al engine + estado del LLM con `--require-llm`).
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
  `manifest.nodes.json`, `manifest.llm.json` para el LLM), `README_INSTALL.md` y
  `manifest/licenses/` (aviso pendiente). Descargador del LLM: `scripts/download_llm.py`.
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
| `WAIFU_LLM_URL` | URL OpenAI-compatible externa; si se define, la app no arranca el servidor gestionado |
| `WAIFU_LLM_TIMEOUT` | Timeout en segundos del adaptador HTTP (default 120) |
| `WAIFU_LLM_PORT` | Puerto del servidor gestionado (default 8290) |
| `WAIFU_LLM_MODEL` | GGUF del servidor gestionado (default: el 9B del manifiesto) |
| `WAIFU_LLM_MMPROJ` | mmproj del servidor gestionado (default: el F16 del manifiesto) |
| `WAIFU_LLM_THREADS` | Hilos CPU del servidor gestionado (default: mitad de nucleos, acotado a 4-8) |
| `WAIFU_TRAINER_CMD` | Comando del entrenador externo de LoRA |

LLM (M12): modelo único **Qwen3.5-9B-abliterated (Q4_K_M) + mmproj-F16** (~6,1 GiB) en
`ComfyUI/models/llm/qwen35-9b-abliterated/`, servido por `llama-server` stock b11146
(`tools/llama.cpp/`, ver `install/manifest/manifest.llm.json`) en **CPU** (`-ngl 0`, ctx 8192):
0 VRAM, pensado para no pelear con ComfyUI. Ciclo de vida gestionado (`app/llm_server.py`): sin
`WAIFU_LLM_URL`, la app arranca el proceso hijo en el primer uso (`/api/enhance`, `/api/motion`,
visión) y lo para al cerrar; con `WAIFU_LLM_URL` definida queda el modo externo (ni arranca ni
mata nada). Estado: `GET /api/llm/status` (ready/loading/stopped/offline/unavailable/foreign) y
badge «LLM:» de la UI. El instalador baja GGUF+mmproj por defecto; `scripts/download_llm.py`
completa/reverifica el paquete (runtime incluido) y `scripts/smoke_llm_cpu.py` mide en CPU
(~5-7 t/s generación). Nota: el vocabulario restringido del enhancer aporta cuando la consulta
solapa con el catálogo (etiquetas en inglés); en consultas en español la garantía la da la
validación estricta (`dropped`).

Visión: WD14 con onnxruntime en CPU sobre `ComfyUI/models/wd14` (roles: «Solo tags (rápido)»,
grounding/validación y **auto-caption del dataset de entrenamiento**). «Describir» usa el modelo
único en 1 llamada (caption + tags validados + zonas): la ruta `/api/vision/image_to_prompt`
llama antes a `LlamaServerManager.ensure()` para arrancar el servidor si aún no está. El mmproj
F16 va **SIEMPRE aparte** (Qwen3.5): sin él no hay visión aunque el GGUF de texto cargue.
Consulta `GET /api/vision/status`; si faltan pesos, la UI lo indica. Los pesos WD14 están en el
manifiesto como **opcionales**: `INSTALAR.bat -IncludeOptional` los descarga; también se pueden
aportar a mano.

Engine: ComfyUI **v0.37.4** pinneado por commit, con nodos también pinneados en
`install/manifest/manifest.nodes.json` (ComfyUI-GGUF del fork **leejet**, KJNodes para el toggle
SageAttention, Frame-Interpolation para RIFE y ClipProj para H3). Dato crítico: el GGUF de
Qwen-Image 2.1 del Editor exige el fork leejet de ComfyUI-GGUF (línea `qwen_image21`); el fork
original no lo carga.

## Tareas frecuentes del asistente

1. **Instalar**: `INSTALAR.bat` en consola (equivale a `install\install.ps1`). Preflight:
   Windows 10/11 x64, GPU NVIDIA, ≥140 GB libres. Instala uv + CPython 3.12.12, `.venv`,
   ComfyUI v0.37.4 + nodos + torch cu130 + SageAttention, pregunta por los modelos recomendados
   (~106 GB + ~6,5 GB del LLM) y verifica con SHA256. Es repetible. Banderas: `-SkipEngine`, `-SkipModels`,
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
   `data/registry/loras.json`. La biblioteca permite **subir un `.safetensors` desde disco**
   («Cargar desde disco»): se copia a `ComfyUI/models/loras/<family>/` y se registra infiriendo
   trigger/dim/alpha/base del propio safetensors; además se puede **borrar la entrada con o sin
   el archivo** (`DELETE /api/loras/{id}?file=1`). Campos: `id`, `family`, `file` (relativo a
   `ComfyUI\models\loras`), `display_name`, `trigger`, `default_weight` (0-2), `source`,
   `license`, `notes`.
4. **Cambiar puertos**: app → `WAIFU_APP_PORT`; engine → edita el `--port` en
   `scripts\start_engine.ps1` y apunta `WAIFU_COMFY_URL` al nuevo puerto.
5. **Correr tests** antes de dar por bueno un cambio Python:
   `& .\.venv\Scripts\python.exe -m unittest discover -s tests`. Son 1440 tests offline.
6. **Ver logs**: la app y el engine escriben en sus consolas (`INICIAR_ENGINE.bat` /
   `INICIAR_WAIFU.bat`); el LLM gestionado escribe `data\llm-server.log`; ComfyUI escribe
   resultados en `ComfyUI\output`. El instalador deja marcadores en `.install-state\`.

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
- **El LLM no responde** («Generar prompt»/«Describir» fallan): mira el badge «LLM:» de la UI o
  `GET /api/llm/status`. `en espera`/`parado`/`cargando`: la app lo arranca al primer uso
  (unos segundos); si no levanta, revisa `data/llm-server.log`. `no instalado`: faltan pesos o
  runtime, ejecuta `scripts/download_llm.py`. `puerto ocupado`: libera 8290 o cambia
  `WAIFU_LLM_PORT`. `INICIAR_LLM.bat` es solo para el modo externo (define `WAIFU_LLM_URL`);
  el servidor es CPU (0 VRAM) y ya no compite con el engine.

## Dónde mirar más

- `install/README_INSTALL.md`: instalación, banderas y qué no se incluye.
- `install/manifest/manifest.models.json` y `manifest.nodes.json`: pines, tamaños, hashes y URLs.
- `install/manifest/manifest.llm.json`: pines del LLM único M12 (GGUF 9B + mmproj + runtime llama.cpp en CPU).
- `registry/recommended-v1.json`: set recomendado y los 2 Anima de aporte manual.
- `THIRD_PARTY_NOTICES.md`: licencias de pesos y dependencias (Anima es no comercial).
- `docs/prompting_anima.md`: manual de prompting Anima del proyecto.
- `LICENSE`: el código es MIT.
