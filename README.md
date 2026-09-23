# WAIFU

Clon personal local estilo *betterwaifu*, solo-GPU (RTX 3060), con **ComfyUI como engine**.
Sin nube obligatoria: el engine corre en loopback y la app consume su API local.

## Fases

| Fase | Alcance |
|------|---------|
| F0 | Fundación: repo, config del engine e interfaz engine (M8-01..03) + 1 imagen end-to-end |
| F1 | Registro de modelos (Anima-first) y preprompts por familia |
| F2 | Manual de prompting + «Mejorar prompt» (LLM+RAG) + store de generaciones |
| F3 | Webapp · pestaña Imagen (MVP): prompt, preprompt/modelo/params, I2I, galería, OC traits |
| F4 | Webapp · pestaña Video (independiente): Wan y H3 |
| F5 | Migración de assets a `E:\IA\WAIFU` y archivo del legacy |

## Layout

```
E:\IA\WAIFU
├─ app/
│  ├─ __init__.py
│  ├─ config.py       # configuración central congelada
│  ├─ engine.py       # cliente API del engine ComfyUI (M8-03)
│  ├─ enhancer.py     # «Mejorar prompt»: LLM local + RAG + preprompts (M8-20)
│  ├─ formats.py      # catálogo de formatos de imagen registry/formatos-v1.json (M9-A1)
│  ├─ gate_f1.py      # runner Gate F1: 1 imagen por modelo del registro (M8-11b)
│  ├─ graphs.py       # grafos API-format: perfil/params e img2img (F3a)
│  ├─ jobs.py         # cola 1-GPU en serie con worker daemon (F3a)
│  ├─ motion.py       # motion de video con LLM local inyectable (F4)
│  ├─ oc_traits.py    # catálogo de traits OC Maker con tags danbooru (F3a)
│  ├─ params.py       # enums reales de sampler/scheduler de ComfyUI (M9-A1)
│  ├─ preprompts.py   # catálogo de preprompts por familia (M8-12)
│  ├─ registry.py     # registro de modelos (M8-10; CLI: python -m app.registry)
│  ├─ server.py       # webapp FastAPI: API JSON, runners y UI (F3b/F4)
│  ├─ store.py        # store sqlite3 de generaciones con kind image|video (M8-21/F4)
│  ├─ video.py        # grafos y runner de video Wan/H3 (F4)
│  └─ health.py       # smoke CLI (python -m app.health)
├─ docs/
│  └─ prompting_anima.md  # manual local de prompting Anima (F2)
├─ registry/
│  ├─ formatos-v1.json  # catálogo legacy de formatos imagen/video, copia verbatim (M9-A1)
│  └─ models.json     # registro versionado de modelos locales (M8-10)
├─ static/            # app.css y app.js de la UI (F3b/F4)
├─ templates/
│  └─ index.html      # UI de una página: pestañas Imagen/Video + OC Maker (F3b/F4)
├─ tests/             # tests CPU, sin red ni GPU
│  ├─ __init__.py
│  ├─ test_engine.py
│  ├─ test_enhancer.py
│  ├─ test_formats.py
│  ├─ test_gate_f1.py
│  ├─ test_graphs.py
│  ├─ test_jobs.py
│  ├─ test_motion.py
│  ├─ test_oc_traits.py
│  ├─ test_params.py
│  ├─ test_preprompts.py
│  ├─ test_registry.py
│  ├─ test_server.py
│  ├─ test_server_video.py
│  ├─ test_store.py
│  └─ test_video.py
├─ workflows/         # plantillas API-format certificadas (imagen y video)
│  ├─ anima_base.json
│  ├─ wan22_i2v_432x768.api.json    # Wan 2.2 I2V exportado del legacy (F4)
│  └─ h3_fl2va_vertical.api.json    # MiniMax H3 FL2VA verbatim del certificado (F4)
├─ scripts/           # launchers del stack (F5)
│  ├─ environment.ps1               # envs y dirs de cache/tmp del repo
│  ├─ start_engine.ps1              # arranca el engine ComfyUI en 8288 (idempotente)
│  └─ stop_engine.ps1               # para el engine (exige /queue vacía)
├─ ComfyUI/           # engine movido en F5 (ignorado por git)
├─ python/            # CPython base del venv (ignorado por git)
├─ .venv/             # venv del repo (ignorado por git)
├─ cache/             # caches uv/huggingface/torch/pip (ignorado por git)
├─ data/           # estado local (ignorado por git)
├─ outputs/        # resultados propios (ignorado por git, aún no creado)
├─ .gitignore
├─ requirements.txt  # fastapi/uvicorn/jinja2 fijados (F3b)
└─ README.md
```

## Configuración

Claves de `app/config.py` (dataclass inmutable `EngineConfig`) y sus overrides por entorno.
Los valores vacíos se ignoran y se usa el default.

| Clave | Variable de entorno | Default |
|-------|---------------------|---------|
| `comfy_root` | `WAIFU_COMFY_ROOT` | `E:\IA\WAIFU\ComfyUI` |
| `comfy_url` | `WAIFU_COMFY_URL` | `http://127.0.0.1:8288` |
| `data_dir` | `WAIFU_DATA_DIR` | `E:\IA\WAIFU\data` |

Derivadas de `comfy_root`: `comfy_output_dir` (`output/`), `comfy_workflows_dir` (`user/default/workflows/`),
`comfy_models_dir` (`models/`), `comfy_custom_nodes_dir` (`custom_nodes/`).

Sin secretos ni lectura de `.env`: solo `os.environ`.

## Engine (M8-03)

`app/engine.py` es el cliente HTTP de la API de ComfyUI (solo stdlib, transporte inyectable):

```python
from app.config import load_config
from app.engine import ComfyEngine, load_graph

engine = ComfyEngine(load_config())
graph = load_graph(r"workflows\base.json")
prompt_id = engine.submit(graph)
entry = engine.wait(prompt_id)
paths = engine.outputs(entry, expected_ext=("png",))
```

Los tests corren offline con un transporte falso: no envían jobs al engine ni tocan la GPU.

## Modelos y preprompts (F1)

`app/registry.py` (M8-10) carga y guarda el registro versionado `registry/models.json`
(`{"version": 1, "models": [...]}`). Cada `ModelEntry` declara familia, `profile` (unet/clip/clip_type/vae),
origen, licencia y preprompt; los ids son slugs `[a-z0-9._-]+` y no pueden repetirse.
CLI: `python -m app.registry` imprime una línea por modelo: `id | family | unet | preprompt`.

`app/preprompts.py` (M8-12) mantiene `FAMILY_PREPROMPTS` (familia → nombre → `{positive, negative}`) con
los textos certificados de la familia `anima`; `DEFAULT_FAMILY = "anima"` y `DEFAULT_PREPROMPT = "glossy"`.
F1 solo registra y cataloga: aplicar el preprompt al prompt es de F2.

## Prompting y store (F2)

`docs/prompting_anima.md` (M8-20) es el manual local de prompting Anima: orden canónico de tags,
calidad `score_`, safety, artistas `@`, negativos, anti-censura y los preprompts certificados.
Sale solo de las fuentes legacy certificadas, sin lore ni parámetros inventados.

`app/enhancer.py` (M8-20) implementa «Mejorar prompt» offline: `SYS_PROMPT` y `BASE_NEGATIVE`
(copias exactas del legacy), `RAG_ENTRIES`/`retrieve` por solape de keywords, `apply_preprompt`
(prefijo positivo + texto; negativo = `BASE_NEGATIVE` + negativo del preprompt, dedup
case-insensitive) y `enhance(user_text, ..., llm=...)` con el
LLM inyectado como `llm(system, user) -> str`. `enhance` normaliza la salida del LLM (`_` → espacio
salvo `score_<N>`) y fuerza el rating pedido antes del preprompt: `nsfw` garantiza `nsfw` y
`uncensored` y elimina `sfw`; `sfw` garantiza `sfw` y elimina `nsfw`/`uncensored`; sin rating no se
toca. `load_local_llm()` carga el GGUF local en CPU (`n_gpu_layers=0`, `n_ctx=2048`) y devuelve un
callable de chat (`create_chat_completion`, `max_tokens=192`, `temperature=0.7`) que exige
contenido de texto no vacío; no se ejecuta en tests.

`app/store.py` (M8-21) persiste generaciones en sqlite3 (`generations`: prompt, negative, params,
status, outputs y error; `params`/`outputs` como JSON) con `add`, `get`, `list`, `count` y `update`.

## Backend F3

`app/graphs.py` (F3a) manipula grafos API-format sobre copias profundas: `patch_model` aplica el
`profile` del modelo (UNETLoader/CLIPLoader/VAELoader por `class_type`) y la seed; `patch_params`
aplica solo los parámetros no-None (seed/steps/cfg/sampler/scheduler al KSampler; width/height al
EmptyLatentImage); `to_img2img` sustituye el EmptyLatentImage por `img_ref` (LoadImage) + `img_enc`
(VAEEncode) y rewirea `latent_image`/`denoise` del KSampler. `EngineError` ante grafos o valores
incompletos. `app/gate_f1.py` reutiliza `patch_model`.

`app/jobs.py` (F3a) ejecuta los jobs de la GPU en serie (un worker daemon, FIFO): `submit` (id
`uuid4().hex`), `status` (`queued|running|done|error`), `result` (excepción guardada o None),
`wait` (estado final, o el actual al agotar timeout) y `start`/`stop` idempotentes; la excepción de
un job pasa a `error` sin matar al worker.

`app/oc_traits.py` (F3a) cataloga 8 grupos de traits OC Maker (hair, eyes, face, body, outfit,
expression, accessories, setting) con tags danbooru estándar; `build_prompt` valida los ids, deduplica
tags y compone el prompt en orden de grupo, y `list_traits` devuelve una copia serializable para la API.

Los tests de F3a (`tests\test_graphs.py`, `tests\test_jobs.py`, `tests\test_oc_traits.py`) corren
offline: `test_graphs.py` usa el grafo real `workflows\anima_base.json`.

## Webapp (F3)

`app/server.py` (F3b) es la webapp local FastAPI. `create_app(config, store, registry,
engine_factory, llm, *, queue, start_worker)` inyecta todas las dependencias para los tests.
Rutas JSON: `GET /api/models`, `GET /api/preprompts?family=`, `GET /api/traits`,
`GET /api/params` (samplers/schedulers reales de ComfyUI y sus defaults),
`GET /api/formats` (11 presets de imagen + default), `GET /api/negative?preprompt&family`
(negativo compuesto base+preprompt), `POST /api/prompt/build`,
`POST /api/enhance` (acepta `strength` `fiel|balanceado|creativo`, default `balanceado`;
503 `{"error":"LLM no disponible"}` sin LLM),
`POST /api/generate` (valida modelo/prompt/base64/strength, `size` de preset **o**
`width`/`height` manuales en [64, 4096] múltiplos de 8, y sampler/scheduler contra los
enums; escribe la referencia en `comfy_root/input/`), `GET /api/jobs/{id}`,
`GET /api/gallery?limit&offset` (cap de 24 por página) y
`GET /media/{gen_id}/{name}` (PNG confinado a `data_dir/gallery/<gen_id>/`, 404/403).

El runner `run_generation(job, config, store, registry, engine_factory)` carga
`workflows\anima_base.json`, aplica `patch_model`/`patch_params` (e `to_img2img` con
`ref_image`+`strength`), encola en la `JobQueue` (`submit`→`wait`→`outputs`) y copia los PNG a
`data_dir/gallery/<gen_id>/` actualizando el store; un fallo queda en store y job sin matar al
worker. La UI (`templates/index.html` + `static/app.css` + `static/app.js`, sin CDN) trae la
pestaña **Imagen**: prompt con «Mejorar prompt» y select de fuerza (Fiel/Balanceado/Creativo,
default Balanceado) con estados del botón y panel de propuesta (positivo/negativo + «Usar»/
«Descartar») justo debajo del prompt; preprompt/modelo; sampler y scheduler como `<select>`
poblados desde `/api/params`; tamaño como `<select>` con los 11 presets + `Manual` (Ancho/Alto
solo en manual); negativo pre-cargado desde `/api/negative` (se refresca al cambiar preprompt
si el usuario no lo ha editado) con botón «Restaurar»; imagen de referencia con miniatura y
botón «Quitar»; Generar con polling y galería de 6 por página (‹ Anterior / página X de Y /
Siguiente ›), lightbox al clic (X y tecla ESC) y «Reusar» por tarjeta. La pestaña **Video**
(F4, ver abajo) es independiente, y el panel modal **OC Maker** (8 grupos + «Añadir al prompt»).

### Requisitos y arranque

Las 3 dependencias están instaladas en el venv del propio repo y fijadas en `requirements.txt`
(fastapi 0.141.1, uvicorn 0.53.0, jinja2 3.1.6):

```powershell
# launchers en la raíz del repo
.\VERIFICAR_WAIFU.bat      # python -m app.health
.\INICIAR_WAIFU.bat        # python -m app.server

# o directo con el venv del repo
& 'E:\IA\WAIFU\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& 'E:\IA\WAIFU\.venv\Scripts\python.exe' -m app.server
```

Por defecto escucha en `127.0.0.1:8765`; el puerto se cambia con `WAIFU_APP_PORT`.
La generación real requiere ComfyUI arriba (`WAIFU_COMFY_URL`) y GPU libre; los tests corren
offline con un transporte falso y `start_worker=False` (sin GPU ni LLM reales).

## Video (F4)

La pestaña **Video** es independiente de la de imagen y tiene dos motores, cada uno con su
plantilla API-format certificada en `workflows\`:

| Motor | Plantilla | Perfil |
|-------|-----------|--------|
| **Wan 2.2 I2V** | `workflows\wan22_i2v_432x768.api.json` | I2V (`WanImageToVideo`): 81 frames (4n+1), 16 fps, 20 pasos, CFG 4.0, euler/`simple`, shift 8, GGUF High+Low (`Wan2.2-I2V-A14B-*-Q4_K_S`), CLIP `umt5_xxl_fp8_e4m3fn_scaled` type `wan`, VAE `wan_2.1_vae`; vertical 432×768 (default) u horizontal 768×432 |
| **MiniMax H3 FL2VA** | `workflows\h3_fl2va_vertical.api.json` | FL2VA (`MiniMaxH3ImageToVideo`) con first/last frame: 576×1024, 192 frames (~8 s a 24 fps), 4 pasos, turbo LoRA, `res_multistep`/`simple`, VAE de video + VAE de audio |

La plantilla Wan se exportó del legacy con la función pura `build_wan_graph`
(`E:\IA\VIDEO\scripts\nw04_wan_graph.py`, solo lectura) con seed 42, prefijo `waifu/video` y textos
placeholder neutros; la de H3 es copia verbatim del certificado. `app\video.py` las parchea sobre
copias profundas: `prepare_wan_graph` fija CLIPTextEncode `5`/`6`, LoadImage `7`, width/height de
`WanImageToVideo` y la seed de los samplers; `prepare_h3_graph` fija LoadImage `140`/`141`,
`MiniMaxH3ImageToVideo` `131` y `RandomNoise` `129`; ambos lanzan `EngineError` si faltan nodos o
campos.

`app\motion.py` escribe el motion positivo con el LLM local: `SYS_PROMPT_MOTION` y
`MOTION_NEGATIVE` son copias EXACTAS del legacy (`local_prompt_planner\motion.py`), `write_motion`
valida texto/rating y usa el `llm(system, user) -> str` inyectado (reutiliza
`load_local_llm` de `app.enhancer`; sin LLM lanza `EngineError("LLM no inyectado")`).

`run_video_generation(job, config, store, engine_factory)` carga la plantilla del job, aplica el
`prepare_*` según `engine` (`wan`|`h3`), usa `ComfyEngine(history_timeout_s=3600)` por defecto,
encola (`submit`→`wait`→`outputs` con extensiones mp4/webm) y copia el resultado a
`data_dir/gallery/<gen_id>/`; un fallo queda en store y job sin propagar. El store migra de forma
idempotente la columna `kind` (`ALTER TABLE`, default `image`) y las generaciones de video se
registran con `kind="video"`.

Rutas nuevas: `POST /api/motion` `{text, rating?}` → `{motion_positive, motion_negative}`
(503 sin LLM), `POST /api/video/generate` `{engine, image_b64, last_image_b64?, motion_positive?,
motion_negative?, prompt?, aspect, seed?}` → `{job_id}` (400 si el engine/aspect son inválidos, si
wan no trae motion positivo, si h3 no trae prompt/último frame o si el base64 es inválido),
`/media` sirve también mp4/webm por extensión y `GET /api/gallery` incluye `kind` y `urls`.

La UI de la pestaña Video (sin CDN) trae select de motor, imagen fuente y (solo H3) último frame,
textarea de movimiento + rating + «Generar motion», motion positivo (Wan) / prompt (H3), aspecto
(solo Wan), seed, estado del job con polling y galería de video con `<video controls>`.

**Requisito GPU/ComfyUI**: la generación real necesita el engine arriba (`WAIFU_COMFY_URL`), GPU
libre y los modelos/custom nodes de cada motor instalados en `E:\IA\WAIFU\ComfyUI` (UnetLoaderGGUF
para Wan, nodos MiniMax H3 + turbo LoRA para H3). Los tests corren offline con transporte y LLM
falsos: no tocan GPU ni red.

## Smoke

```
& 'E:\IA\WAIFU\.venv\Scripts\python.exe' -m app.health
& 'E:\IA\WAIFU\.venv\Scripts\python.exe' -m app.health --require-engine
```

Comprueba rutas críticas y hace `GET {comfy_url}/system_stats` (timeout 2s, nunca lanza jobs).
Exit 0 si las rutas críticas existen; exit 1 si falta alguna. Con `--require-engine`, exit 1
si el engine no responde. `data_dir` puede faltar sin romper el smoke.

## Nota legacy

Desde F5 el engine y los assets viven en `E:\IA\WAIFU` (ComfyUI, modelos, workflows, salidas,
`python\` y `.venv\`). `E:\IA\VIDEO` queda como repo legacy de solo lectura (herramientas y
fuentes) y ya no contiene `ComfyUI\`, `python\` ni `.venv\`.

## Gate F0

```
& 'E:\IA\WAIFU\.venv\Scripts\python.exe' -m app.gate_f0
```

**Requisito: GPU libre** (el operador confirma que ComfyUI no tiene trabajo en curso; el runner no
comprueba `/queue`, no espera ni pide confirmaciones).

Envía `workflows\anima_base.json` con `ComfyEngine.submit`, espera el history (`wait`) y verifica los
PNG con `outputs`. Imprime el `prompt_id`, la ruta absoluta y el tamaño de cada PNG; exit 0 con al
menos 1 PNG de peso > 0, exit 1 en cualquier fallo. Opciones: `--seed N` (default 42) y
`--graph RUTA` (default `E:\IA\WAIFU\workflows\anima_base.json`).

Perfil congelado del grafo (exportado de la ruta certificada nw03/nw07 con `build_master("imagen", seed=42)`):
`Anima-2.9B-preview-v1.safetensors` + CLIP `qwen_3_06b_base` + VAE `qwen_image_vae`; 320x576, batch 1;
20 pasos, cfg 4.0, euler/`sgm_uniform`, denoise 1.0, seed 42; 9 nodos: UNETLoader, CLIPLoader, VAELoader,
CLIPTextEncode x2, EmptyLatentImage, KSampler, VAEDecode, SaveImage.

## Gate F1

```
& 'E:\IA\WAIFU\.venv\Scripts\python.exe' -m app.gate_f1
```

**Requisito: GPU libre** (el operador confirma que ComfyUI no tiene trabajo en curso; igual que F0, el
runner no comprueba `/queue`, no espera ni pide confirmaciones).

Recorre el registro (o solo los `--model-id` indicados) y, por cada modelo, parchea los nodos
UNETLoader/CLIPLoader/VAELoader del grafo con su `profile` (localizados por `class_type`, no por id
fijo), fija la `--seed` en todo nodo con widget `seed` y ejecuta `submit` + `wait` + `outputs`.
Imprime una línea por PNG: `id | prompt_id | ruta | bytes`; exit 0 solo si todos los modelos generaron
al menos 1 PNG de peso > 0, exit 1 con el detalle de cada fallo. Opciones: `--model-id ID` (repetible;
default todos), `--seed N` (default 42) y `--graph RUTA` (default `E:\IA\WAIFU\workflows\anima_base.json`).
