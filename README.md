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
│  ├─ gate_f1.py      # runner Gate F1: 1 imagen por modelo del registro (M8-11b)
│  ├─ graphs.py       # grafos API-format: perfil/params e img2img (F3a)
│  ├─ jobs.py         # cola 1-GPU en serie con worker daemon (F3a)
│  ├─ oc_traits.py    # catálogo de traits OC Maker con tags danbooru (F3a)
│  ├─ preprompts.py   # catálogo de preprompts por familia (M8-12)
│  ├─ registry.py     # registro de modelos (M8-10; CLI: python -m app.registry)
│  ├─ server.py       # webapp FastAPI: API JSON, runner de generación y UI (F3b)
│  ├─ store.py        # store sqlite3 de generaciones (M8-21)
│  └─ health.py       # smoke CLI (python -m app.health)
├─ docs/
│  └─ prompting_anima.md  # manual local de prompting Anima (F2)
├─ registry/
│  └─ models.json     # registro versionado de modelos locales (M8-10)
├─ static/            # app.css y app.js de la UI (F3b)
├─ templates/
│  └─ index.html      # UI de una página: pestañas Imagen/Video + OC Maker (F3b)
├─ tests/             # tests CPU, sin red ni GPU
│  ├─ __init__.py
│  ├─ test_engine.py
│  ├─ test_enhancer.py
│  ├─ test_gate_f1.py
│  ├─ test_graphs.py
│  ├─ test_jobs.py
│  ├─ test_oc_traits.py
│  ├─ test_preprompts.py
│  ├─ test_registry.py
│  ├─ test_server.py
│  └─ test_store.py
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
| `comfy_root` | `WAIFU_COMFY_ROOT` | `E:\IA\VIDEO\ComfyUI` |
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

`app/enhancer.py` (M8-20) implementa «Mejorar prompt» offline: `SYS_PROMPT` (copia exacta del
legacy), `RAG_ENTRIES`/`retrieve` por solape de keywords, `apply_preprompt` (prefijo positivo +
texto, negativo del preprompt, dedup case-insensitive) y `enhance(user_text, ..., llm=...)` con el
LLM inyectado como `llm(system, user) -> str`. `load_local_llm()` carga el GGUF local en CPU
(`n_gpu_layers=0`, `n_ctx=2048`) y no se ejecuta en tests.

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
`POST /api/prompt/build`, `POST /api/enhance` (503 `{"error":"LLM no disponible"}` sin LLM),
`POST /api/generate` (valida modelo/prompt/base64/strength y escribe la referencia en
`comfy_root/input/`), `GET /api/jobs/{id}`, `GET /api/gallery?limit&offset` y
`GET /media/{gen_id}/{name}` (PNG confinado a `data_dir/gallery/<gen_id>/`, 404/403).

El runner `run_generation(job, config, store, registry, engine_factory)` carga
`workflows\anima_base.json`, aplica `patch_model`/`patch_params` (e `to_img2img` con
`ref_image`+`strength`), encola en la `JobQueue` (`submit`→`wait`→`outputs`) y copia los PNG a
`data_dir/gallery/<gen_id>/` actualizando el store; un fallo queda en store y job sin matar al
worker. La UI (`templates/index.html` + `static/app.css` + `static/app.js`, sin CDN) trae la
pestaña **Imagen** (prompt + «Mejorar prompt», preprompt/modelo, seed/steps/cfg/sampler/scheduler/
ancho/alto, imagen de referencia + fuerza, Generar con polling y galería) y la pestaña **Video**
como placeholder de F4, más el panel modal **OC Maker** (8 grupos + «Añadir al prompt»).

### Requisitos y arranque

Las 3 dependencias están instaladas en el venv legacy y fijadas en `requirements.txt`
(fastapi 0.141.1, uvicorn 0.53.0, jinja2 3.1.6):

```powershell
& 'E:\IA\VIDEO\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& 'E:\IA\VIDEO\.venv\Scripts\python.exe' -m app.server
```

Por defecto escucha en `127.0.0.1:8765`; el puerto se cambia con `WAIFU_APP_PORT`.
La generación real requiere ComfyUI arriba (`WAIFU_COMFY_URL`) y GPU libre; los tests corren
offline con un transporte falso y `start_worker=False` (sin GPU ni LLM reales).

## Smoke

```
& 'E:\IA\VIDEO\.venv\Scripts\python.exe' -m app.health
& 'E:\IA\VIDEO\.venv\Scripts\python.exe' -m app.health --require-engine
```

Comprueba rutas críticas y hace `GET {comfy_url}/system_stats` (timeout 2s, nunca lanza jobs).
Exit 0 si las rutas críticas existen; exit 1 si falta alguna. Con `--require-engine`, exit 1
si el engine no responde. `data_dir` puede faltar sin romper el smoke.

## Nota legacy

Hasta F5 el engine y los assets viven en `E:\IA\VIDEO` (ComfyUI, modelos, workflows, salidas).
Ese árbol es de solo lectura para este repo y se archiva al cerrar F5.

## Gate F0

```
& 'E:\IA\VIDEO\.venv\Scripts\python.exe' -m app.gate_f0
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
& 'E:\IA\VIDEO\.venv\Scripts\python.exe' -m app.gate_f1
```

**Requisito: GPU libre** (el operador confirma que ComfyUI no tiene trabajo en curso; igual que F0, el
runner no comprueba `/queue`, no espera ni pide confirmaciones).

Recorre el registro (o solo los `--model-id` indicados) y, por cada modelo, parchea los nodos
UNETLoader/CLIPLoader/VAELoader del grafo con su `profile` (localizados por `class_type`, no por id
fijo), fija la `--seed` en todo nodo con widget `seed` y ejecuta `submit` + `wait` + `outputs`.
Imprime una línea por PNG: `id | prompt_id | ruta | bytes`; exit 0 solo si todos los modelos generaron
al menos 1 PNG de peso > 0, exit 1 con el detalle de cada fallo. Opciones: `--model-id ID` (repetible;
default todos), `--seed N` (default 42) y `--graph RUTA` (default `E:\IA\WAIFU\workflows\anima_base.json`).
