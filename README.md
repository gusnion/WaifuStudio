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
│  ├─ gate_f1.py      # runner Gate F1: 1 imagen por modelo del registro (M8-11b)
│  ├─ preprompts.py   # catálogo de preprompts por familia (M8-12)
│  ├─ registry.py     # registro de modelos (M8-10; CLI: python -m app.registry)
│  └─ health.py       # smoke CLI (python -m app.health)
├─ registry/
│  └─ models.json     # registro versionado de modelos locales (M8-10)
├─ tests/             # tests CPU, sin red ni GPU
│  ├─ __init__.py
│  ├─ test_engine.py
│  ├─ test_gate_f1.py
│  ├─ test_preprompts.py
│  └─ test_registry.py
├─ data/           # estado local (ignorado por git, aún no creado)
├─ outputs/        # resultados propios (ignorado por git, aún no creado)
├─ .gitignore
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
