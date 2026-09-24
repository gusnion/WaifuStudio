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
│  ├─ characters.py   # OCs guardables con referencias en data/waifu.db (M9-B1)
│  ├─ config.py       # configuración central congelada
│  ├─ engine.py       # cliente API del engine ComfyUI (M8-03)
│  ├─ enhancer.py     # «Mejorar prompt»: LLM local + RAG + preprompts (M8-20)
│  ├─ formats.py      # catálogo de formatos de imagen registry/formatos-v1.json (M9-A1)
│  ├─ gate_f1.py      # runner Gate F1: 1 imagen por modelo del registro (M8-11b)
│  ├─ graphs.py       # grafos API-format: perfil/params e img2img (F3a)
│  ├─ jobs.py         # cola 1-GPU en serie con worker daemon (F3a)
│  ├─ loras.py        # biblioteca de LoRAs locales: registro y validación (M9-D1)
│  ├─ motion.py       # motion de video con LLM local inyectable (F4)
│  ├─ oc_traits.py    # catálogo de traits OC Maker con tags danbooru (F3a)
│  ├─ params.py       # enums reales de sampler/scheduler de ComfyUI (M9-A1)
│  ├─ preprompts.py   # catálogo de preprompts por familia (M8-12)
│  ├─ progress.py     # tracker WS de progreso del engine (M9-A2)
│  ├─ prompt_zones.py # zonas del prompt en orden Anima (M9-C)
│  ├─ registry.py     # registro de modelos (M8-10; CLI: python -m app.registry)
│  ├─ server.py       # webapp FastAPI: API JSON, runners y UI (F3b/F4)
│  ├─ sheet.py        # hoja de referencia de OCs (collage PNG con Pillow, M9-B2)
│  ├─ store.py        # store sqlite3 de generaciones con kind image|video (M8-21/F4)
│  ├─ tags.py         # catálogo starter de tags Danbooru (M9-B1)
│  ├─ video.py        # grafos y runner de video Wan/H3 (F4)
│  └─ health.py       # smoke CLI (python -m app.health)
├─ docs/
│  └─ prompting_anima.md  # manual local de prompting Anima (F2)
├─ registry/
│  ├─ formatos-v1.json  # catálogo legacy de formatos imagen/video, copia verbatim (M9-A1)
│  ├─ loras.json      # registro versionado de LoRAs locales (M9-D1)
│  ├─ models.json     # registro versionado de modelos locales (M8-10)
│  └─ tags_danbooru.json  # catálogo starter de tags Danbooru (M9-B1)
├─ static/            # app.css y app.js de la UI (F3b/F4)
├─ templates/
│  └─ index.html      # UI de una página: pestañas Imagen/Video + OC Maker (F3b/F4)
├─ tests/             # tests CPU, sin red ni GPU
│  ├─ __init__.py
│  ├─ test_characters.py
│  ├─ test_engine.py
│  ├─ test_enhancer.py
│  ├─ test_formats.py
│  ├─ test_gate_f1.py
│  ├─ test_graphs.py
│  ├─ test_jobs.py
│  ├─ test_loras.py
│  ├─ test_motion.py
│  ├─ test_oc_traits.py
│  ├─ test_params.py
│  ├─ test_preprompts.py
│  ├─ test_prompt_zones.py
│  ├─ test_registry.py
│  ├─ test_server.py
│  ├─ test_server_video.py
│  ├─ test_sheet.py
│  ├─ test_store.py
│  ├─ test_tags.py
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
.\INICIAR_WAIFU.bat        # scripts\start_app.ps1 (primer plano)
.\DETENER_WAIFU.bat        # scripts\stop_app.ps1

# o directo con el venv del repo
& 'E:\IA\WAIFU\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& 'E:\IA\WAIFU\.venv\Scripts\python.exe' -m app.server
```

Por defecto escucha en `127.0.0.1:8765` (default de `app.server`); el puerto se cambia con
`WAIFU_APP_PORT`, que `start_app.ps1` y `stop_app.ps1` respetan.
`INICIAR_WAIFU.bat` llama a `scripts\start_app.ps1`: si el 8765 ya lo escucha la app de WAIFU
(python del venv y `app.server` en su línea de comandos), imprime
`La app ya esta corriendo: http://127.0.0.1:8765` y sale con código 0 sin arrancar una segunda
instancia; si el puerto lo ocupa otra aplicación, falla sin arrancar nada.
`DETENER_WAIFU.bat` llama a `scripts\stop_app.ps1`: valida el dueño del puerto antes de matar,
por lo que nunca detiene una aplicación ajena (throw); si no hay listener informa
`La app ya esta detenida.` y sale con código 0.
La generación real requiere ComfyUI arriba (`WAIFU_COMFY_URL`) y GPU libre; los tests corren
offline con un transporte falso y `start_worker=False` (sin GPU ni LLM reales).

## Tags y OCs (M9-B1)

`registry\tags_danbooru.json` es el catálogo **starter** curado de tags Danbooru (349 en 10
grupos: hair, eyes, face, body, outfit, expression, accessories, setting, action y meta), sin
red ni descargas; cada entrada es `{tag, label, group}` con tags canónicos (nada inventado) y
`meta` incluye `score_7/8/9`, `masterpiece`, `best quality`, `sfw`, `nsfw` y `uncensored`.
`app\tags.py` lo carga desde `APP_ROOT` y expone `GROUPS`, `list_groups()`, `by_group(group)`
(`EngineError` si no existe), `search(q, limit)` (substring case-insensitive en tag/label, orden
estable, limit acotado a 1..200), `get(tag)` y `all_tags()`; el dataset completo (3-8k) llega en
M10 con las descargas.

`app\characters.py` guarda OCs en la MISMA sqlite (`data\waifu.db`) con migración idempotente:
`characters` (name único, `tags` JSON, `preprompt` de la familia anima, `rating` sfw|nsfw y
`notes`) y `character_refs` (FK con `ON DELETE CASCADE`). `CharacterStore(db_path)` crea el
directorio padre en `init()`; `add`/`get`/`list`/`update`/`delete` validan con `EngineError`
(delete borra refs y su carpeta), `add_ref(id, src_path, *, refs_root)` copia una imagen real
(png/jpg/jpeg/webp) a `<refs_root>\<id>\<uuid>.<ext>`, `refs(id)` lista las filas y
`remove_ref(id, ref_id)` borra archivo y fila. `prompt_from_tags(tags)` une con ", " dedup
case-insensitive en orden estable. Las refs viven en `data\characters\<id>\`.

Rutas nuevas en `app\server.py`: `GET /api/tags/groups` → `{groups}`;
`GET /api/tags?group=&q=&limit=` → `{items}` (por grupo, búsqueda o ambos; sin filtro, primeros
200); `GET/POST /api/characters` y `GET/PUT/DELETE /api/characters/{id}` (400 en validación, 404
si no existe); `POST /api/characters/{id}/refs` `{gen_id}` copia el primer output de
`data\gallery\<gen_id>\` (404 sin generación/archivo), `GET /api/characters/{id}/refs` añade
`url` y `DELETE /api/characters/{id}/refs/{ref_id}`; `GET /media/characters/{char_id}/{name}`
sirve la referencia con confinamiento estricto (`resolve()` + `is_relative_to(refs_root)`: 403
si escapa, 404 si falta). Todo inyectable vía `create_app(..., character_store=...)` y testeable
offline.

## OC Maker (M9-B2)

La UI (sin CDN) rediseña el panel modal **OC Maker** en tres columnas:

- **Catálogo**: select de grupos (`/api/tags/groups`) + buscador en vivo
  (`/api/tags?group&q&limit`), resultados como chips con selección múltiple y la
  lista visible de tags elegidos, cada uno con «quitar». «Añadir al prompt» sigue
  funcionando: compone el prompt desde los tags seleccionados (dedup
  case-insensitive) y cierra el panel.
- **Mis OCs**: lista de `GET /api/characters` con «Usar» (vuelca los tags en el
  prompt, fija preprompt/rating y adjunta la primera ref como imagen de
  referencia del panel de generación si existe), «Editar», «Duplicar» (copia sin
  id, el guardado crea un OC nuevo) y «Eliminar» (con confirmación). Formulario
  Guardar/Actualizar con nombre, preprompt, rating y notas; los tags del OC son
  los seleccionados en el catálogo (`POST`/`PUT /api/characters`).
- **Referencias**: miniaturas de `GET /api/characters/{id}/refs` servidas por
  `/media/characters/{id}/{name}`, «Quitar» por ref
  (`DELETE .../refs/{ref_id}`) y **«Crear hoja»** (habilitado con ≥2 refs), que
  llama a `POST /api/characters/{id}/sheet`, adjunta el PNG resultante como
  imagen de referencia del panel y refresca la lista.

Además, cada tarjeta de imagen de la galería tiene **«Guardar en OC»**: abre un
selector con los OCs existentes o un nombre para crear uno nuevo y hace
`POST /api/characters/{id}/refs` con el `gen_id` (refresca las refs si ese OC
está abierto).

`app\sheet.py` (CPU pura, Pillow) expone
`make_sheet(image_paths, out_path, *, cell=512, cols=2, bg=(24,24,28))`: exige
≥2 imágenes existentes (`EngineError`), ajusta cada una con `ImageOps.fit` a la
celda interior y compone la rejilla de `cols` columnas con 8 px de fondo `bg`
separando las vistas (celdas de retrato 2:3), creando el directorio padre y
guardando un PNG RGB en `out_path`; con los defaults, 3-4 refs dan 512×768.
`POST /api/characters/{id}/sheet` (`{"ref_ids": [..]?}`, todas si se omite)
genera `<refs_root>\<id>\sheet_<uuid>.png`, lo registra como ref con el
`add_ref` de siempre (400 si quedan <2 refs, 404 si el OC no existe) y devuelve
`{"relpath", "url"}`; el PNG temporal se borra tras registrarlo, así el
directorio del OC solo contiene archivos registrados.

## Zonas del prompt (M9-C)

`app\prompt_zones.py` (CPU, sin red) parte el prompt en las cinco zonas del orden
Anima —`quality`, `safety`, `subject`, `character`, `general`— y lo recompone:

- `ZONE_ORDER` y `ZONE_LABELS` (`Calidad/meta`, `Safety`, `Sujeto`, `Personaje`,
  `General`); `QUALITY_TAGS` (`masterpiece`, `best quality`, `absurdres`,
  `highres`, `very aesthetic`, `newest`, `score_1..score_9`, `jpeg artifacts`,
  `sepia`, `watermark`...), `SAFETY_TAGS` (`sfw`, `nsfw`, `uncensored`, `explicit`,
  `sensitive`, `safe`, `rating_*`) y `SUBJECT_TAGS` (`1girl`, `1boy`, `2girls`,
  `1other`, `solo`, `multiple girls`, `hetero`, `yuri`, `yaoi`...).
- `classify_tag(tag)`: normaliza espacios/mayúsculas y resuelve el peso
  (`(tag:1.2)` → `tag`); el resto (tags del catálogo de `app.tags` o
  desconocidos) cae siempre en `general`: nunca se adivina `character`.
- `split_zones(prompt)`: separa por comas, limpia, deduplica case-insensitive por
  zona y devuelve siempre las 5 claves; `compose_zones(zones)`: une en
  `ZONE_ORDER`, solo zonas con tags y dedup global; `insert_tag(prompt, tag,
  zone=None)`: clasifica si no hay zona, inserta en la posición de su zona y no
  duplica (si ya está, devuelve el prompt intacto); `zones_payload(prompt)`:
  `[{id, label, tags}]` para la API/UI.

Rutas nuevas en `app\server.py`: `POST /api/prompt/zones` `{text}` →
`{zones, composed}`, `POST /api/prompt/compose` `{zones}` → `{text}` y
`POST /api/prompt/insert` `{text, tag, zone?}` → `{text}` (400 con forma
inválida, tag vacío o zona desconocida).

La UI (sin CDN) añade debajo del prompt una **previsualización coloreada** por
zona con leyenda, actualizada al escribir (debounce 300 ms vía
`/api/prompt/zones`), y una fila de **chips por zona** que abren un input y
añaden el tag con `/api/prompt/insert` (el textarea sigue siendo la fuente de
verdad); el chip destacado **«+ Personaje»** inserta en la zona `character`
(el caso del nombre del OC).

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
(503 sin LLM), `POST /api/video/generate` `{engine?, mode?, seconds?, image_b64, last_image_b64?,
motion_positive?, motion_negative?, prompt?, aspect, seed?}` → `{job_id, frames, vram_hint}`
(M9-F1; 400 si el engine/mode/seconds/aspect son inválidos, si wan no trae motion positivo, si
h3 no trae prompt/último frame o si el base64 es inválido), `/media` sirve también mp4/webm por
extensión y `GET /api/gallery` incluye `kind` y `urls`.

La UI de la pestaña Video (sin CDN) trae select de motor, imagen fuente y (solo H3) último frame,
textarea de movimiento + rating + «Generar motion», motion positivo (Wan) / prompt (H3), aspecto
(solo Wan), seed, estado del job con polling y galería de video con `<video controls>`.

**Requisito GPU/ComfyUI**: la generación real necesita el engine arriba (`WAIFU_COMFY_URL`), GPU
libre y los modelos/custom nodes de cada motor instalados en `E:\IA\WAIFU\ComfyUI` (UnetLoaderGGUF
para Wan, nodos MiniMax H3 + turbo LoRA para H3). Los tests corren offline con transporte y LLM
falsos: no tocan GPU ni red.

## LoRAs (M9-D1)

`app\loras.py` (CPU, sin red) carga y valida la biblioteca versionada
`registry\loras.json` (`{"version": 1, "loras": [...]}`). Cada entrada declara
`id`, `family`, `file` (relativo a `ComfyUI\models\loras`), `display_name`,
`trigger`, `default_weight` (0..2), `source`, `license` y `notes`; el `_comment`
del registro recuerda que **los LoRAs de Anima llegan en M10 (descargas
diferidas)** y solo se registran ficheros presentes en disco:

| id | familia | archivo |
|----|---------|---------|
| `lightx2v-wan-high` | `wan` | `lightx2v\wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors` |
| `lightx2v-wan-low` | `wan` | `lightx2v\wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors` |
| `reika-kurashiki` | `animagine` | `Reika Kurashiki_1.safetensors` (legacy, no se usa en Anima) |
| `minimax-h3-fl2v-turbo-4step` | `h3` | `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` (turbo de la plantilla H3) |

API del módulo: `list_loras(family=None)` (orden del JSON), `get(id)`,
`families()` y `validate_selection([{"id", "weight"?}])`, que normaliza a
`[{"id", "file", "weight"}]` (weight float 0..2, default el del registro);
`EngineError` si el id no existe o el peso es inválido.

`app\graphs.py:apply_loras(graph, loras)` devuelve una copia profunda con la
cadena `lora_1..lora_N` (`LoraLoaderModelOnly`: `lora_name=file`,
`strength_model=weight`) enganchada al `UNETLoader` (o `UnetLoaderGGUF`): el
primer nodo toma su `model`, el resto encadena al anterior y todo input `model`
que apuntara al loader pasa a apuntar al último LoRA. Lista vacía devuelve la
copia sin cambios; `EngineError` si falta el loader, colisiona un id `lora_N` o
un item no trae `file`/peso válido.

Rutas: `GET /api/loras?family=` → `{"items": [...], "families": [...]}` y
`POST /api/generate` acepta `loras: [{"id", "weight"?}]` (400 si es inválido),
los aplica tras `patch_model` y guarda los `params` del store con `loras`
normalizados. Los LoRAs de vídeo (wan/h3) se conectarán a los runners de vídeo
en **M9-F**; hasta entonces la biblioteca queda como registro y validación.

## LoRAs en la UI (M9-D2)

El panel **Imagen** trae una sección **LoRAs de imagen** poblada desde
`GET /api/loras?family=<familia del modelo>`: por cada LoRA, checkbox + slider
de peso (0..2, paso 0.05, default el `default_weight` del registro). Si la
familia no tiene entradas, muestra «Aún no hay LoRAs de imagen (llegan con las
descargas M10)». `POST /api/generate` recibe `loras: [{"id", "weight"}]` con
los marcados, y el resumen de cada tarjeta de la galería lista los LoRAs usados
(`lora <id> @ <peso>`); «Reusar» vuelve a marcarlos y ajustar sus pesos desde
`params.loras` del store.

## Preprompts propios (M9-D2)

`app\preprompts.py` añade preprompts del usuario sobre `data_dir\preprompts.json`
(`{"custom": {"<slug>": {"positive", "negative"}}}`), con escritura atómica
(tmp + `os.replace`) y creación del `data_dir` si falta. `save_custom(name,
positive, negative="")` exige slug `[a-z0-9_-]{2,32}` y positivo no vacío, y
rechaza los cuatro certificados (`anima_default`, `glossy`, `not_glossy`,
`ninguno`) y los duplicados exactos; `delete_custom(name)` devuelve `False` si
no existe y `list_custom()` es una copia del mapa. `get_preprompt(family,
name)` resuelve primero el certificado y luego el propio, y
`list_preprompts(family)` añade los propios al final sin duplicar (un almacén
corrupto no rompe los certificados).

Rutas: `GET /api/preprompts?family=` devuelve además `custom` (lista de
nombres; `names`/`default` intactos), `POST /api/preprompts/custom`
`{name, positive, negative?}` → `{"name"}` (400 si es inválido) y
`DELETE /api/preprompts/custom/{name}` → `{"deleted": true}` (404 si no
existe). `POST /api/generate` valida `preprompt` contra certificados y propios
(400 si no existe o no es texto). En la UI, junto al selector de preprompt hay
un botón **Gestionar** que abre un mini-modal con la lista de propios (con
**Borrar**) y un formulario (nombre/positivo/negativo); al guardar o borrar se
refresca el select y los propios se muestran como `<nombre> (propio)`.

## Entrenador de LoRA (M9-E1)

`app\trainer.py` (CPU, sin GPU, red ni dependencias) orquesta el entrenamiento
de un LoRA de OC desde la galería; el entrenador real (fork kohya de Anima) se
instala en **M10**:

1. `prepare_dataset(char, gen_ids, store=..., gallery_root=..., out_dir=...,
   trigger=...)`: valida el OC, 10..50 `gen_ids` únicos, que cada generación sea
   `kind="image"` y `status="done"` y que su archivo exista en
   `data_dir\gallery\<gen_id>\`; copia a `data_dir\trainer\<char_id>\img\NN.png`
   (NN=01..) con `NN.txt` = `trigger, <prompt_from_tags(tags)>` deduplicado, y
   escribe `manifest.json`. Devuelve `{"dataset_dir", "images", "captions",
   "trigger"}` (`EngineError` si algo falla).
2. `write_config(dataset_dir, out_dir, rank=16, epochs=10, lr=1e-4)`:
   `data_dir\trainer\train_config.toml` con `source_image_dir`, `output_dir`,
   `output_name`, `rank`, `epochs`, `lr`, `resolution=512`, `batch_size=1`,
   `gradient_checkpointing=true` y `optimizer="AdamW8bit"`. El aviso del fichero
   recuerda **revisar claves contra el fork kohya de Anima al instalar (M10)**.
3. `run_training(config_path, cmd=None, env=None, log_path=None,
   timeout_s=4*3600)`: sin `cmd` usa `WAIFU_TRAINER_CMD` (lista separada por
   espacios; si falta → `EngineError("entrenador no instalado (M10)")`); lanza
   `cmd + [config_path]` con `subprocess.Popen`, vuelca stdout+stderr al log en
   streaming (append) y devuelve el exit code; al agotar el timeout mata el
   proceso y lanza `EngineError`.
4. `register_lora(char, lora_path, comfy_loras_dir=..., trigger=...,
   display_name=None)`: exige un `.safetensors` existente, lo copia a
   `ComfyUI\models\loras\waifu\<char_id>.safetensors` y crea la entrada
   `oc-<char_id>` (familia `anima`, `default_weight=0.8`, source
   `entrenado local (M9-E)`, license `local`, notes con fecha) con
   `loras.add_entry`, que guarda `registry\loras.json` de forma atómica
   (tmp + replace) conservando el orden.
5. `train_character(...)` encadena prepare → config → run → register y devuelve
   el dict de resultado (dataset, config, log, lora, exit code y entry).

Ruta: `POST /api/characters/{id}/train` `{gen_ids, rank?, epochs?, trigger?}`
valida (404 OC desconocido; 400 `gen_ids` fuera de 10..50, no enteros o
`rank`/`epochs`/`trigger` inválidos), registra la generación `kind="train"` y
encola el job; `GET /api/jobs/{id}` responde con `progress` nulo mientras corre
y `outputs=[ruta lora]` al terminar (o `error`). Cancelar un train devuelve
**409** (`cancelar train: pendiente (M9-F)`), igual que los jobs de vídeo.

## Progreso y cancelación (M9-A2b)

`run_generation` crea un `ProgressTracker` (WS del engine derivado de
`comfy_url`, ver `app\progress.py`) antes del submit, lo arranca y lo para en el
`finally`; el registro `_JOBS[gen_id]` (engine, `prompt_id`, tracker y estado)
vive en memoria del proceso y se pierde al reiniciar la app.

- `GET /api/jobs/{id}` añade `progress`: `{step, total, percent, node, state}`
  con nulls si el job no tiene tracker.
- `POST /api/jobs/{id}/cancel`: 404 si el job no existe, 409 si ya está
  `done|error|cancelled` (o si es un train); en `queued` llama a
  `ComfyEngine.delete_queued(prompt_id)` y en `running` a
  `ComfyEngine.interrupt()`, marca el store como `cancelled` y
  devuelve `{"status": "cancelled"}`. Un job cancelado antes de arrancar no se
  ejecuta. Imagen y **vídeo** comparten esta semántica desde M9-F1; el train
  sigue devolviendo 409 (`cancelar train: pendiente (M9-F)`).
- UI (sin CDN): barra de progreso con `paso X/Y` + nodo, polling cada 1 s
  mientras el job está activo (`queued|running`) y botón **Cancelar** junto a
  «Generar» visible solo con job activo; al terminar (`done|error|cancelled`)
  para el polling, recarga la galería y limpia la barra.

## Vídeo FLF2V, duración y cancelar (M9-F1)

`app\video.py` amplía el backend de vídeo sin tocar lo existente:

- **Plantilla FLF2V**: `workflows\wan22_flf2v_432x768.api.json` (16 nodos) se exportó del legacy
  con la función pura `build_wan_graph` en modo `FLF2V` (81 frames, 16 fps, seed 42, prefijo
  `waifu/video_flf`, `ref_first.png`/`ref_last.png`, 432×768 y `MOTION_NEGATIVE` de
  `app.motion`). `prepare_wan_flf_graph(graph, *, first_image_name, last_image_name,
  motion_positive, motion_negative, width=432, height=768, seed, frames=None)` parchea sobre copia
  profunda los dos `LoadImage` **por orden de inserción** del grafo (el export inserta el primero
  antes que el último y `WanFirstLastFrameToVideo` los enlaza como `start_image`/`end_image`; se
  exigen exactamente dos), los `CLIPTextEncode` `5`/`6`, width/height del nodo FLF, la seed de los
  samplers y, si se pasa, `length` (4n+1).
- **Duración**: `frames_for_seconds(seconds, fps=16)` devuelve el menor length 4n+1 >=
  `ceil(seconds*fps)` (`needed + ((4 - (needed-1) % 4) % 4)`); 1..15 s y `EngineError` fuera.
  Valores reales con fps 16: 1→17, 5→81, 8→129, 15→241. `prepare_wan_graph` acepta `frames` y
  parchea `length` del nodo I2V.
- **VRAM 12 GB**: `vram_hint(frames, width, height)` documenta la tabla del perfil 432×768 (16 fps,
  20 pasos, GGUF Q4_K_S): <=81 frames «cabe en 12 GB (perfil certificado)», 82..121 «ajustado, más
  lento» (sin certificar) y >121 «riesgo de OOM en 12 GB; no certificado».
- **API**: `POST /api/video/generate` acepta `mode` (`i2v`|`flf2v`, default `i2v`), `seconds` (1-15,
  default 5), `motion_negative` opcional (vacío o ausente usa `MOTION_NEGATIVE`) y
  `last_image_b64` (obligatorio en `flf2v`); `engine` sigue siendo `wan`|`h3` y si falta la clave el
  default es `wan` (400 si mode/seconds/engine/aspect son inválidos, si falta el motion positivo de
  wan o las imágenes). Responde `{job_id, frames, vram_hint}`; en `flf2v` usa la plantilla FLF con
  dos frames y `h3` no admite `mode=flf2v`.
- **Progreso/cancelar**: el job de vídeo registra `_JOBS[gen_id]` con `kind="video"`, `engine` y
  `ProgressTracker` (start antes del submit, stop en el `finally`, `ws_factory` inyectable) igual
  que imagen, así que `GET /api/jobs/{id}` sirve `progress` también para vídeo y
  `POST /api/jobs/{id}/cancel` deja de devolver 409: `queued` → `delete_queued`, `running` →
  `interrupt` (solo el train sigue en 409).

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
