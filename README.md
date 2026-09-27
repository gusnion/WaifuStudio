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
| F5 | Migración de assets a `E:\IA\WAIFU` y archivo del legacy (retirado en 2026-09-26) |

## Layout

```
E:\IA\WAIFU
├─ app/
│  ├─ __init__.py
│  ├─ characters.py   # OCs con referencias, rasgos/extras y perfil en data/waifu.db (M9-B1/B3)
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
├─ install/           # instalador en máquina limpia: install.ps1, manifiestos y README_INSTALL.md (F3b/M10-6b)
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
`GET /api/gallery?limit&offset&kind` (cap de 24 por página; `kind` opcional
`image|video` filtra el feed **y** el `count` que lo acompaña, 400 con otro valor),
`GET /api/refs/{name:path}` (sirve una referencia de `comfy_root/input/` con
confinamiento estricto —`resolve()` + `is_relative_to`— y solo extensiones
png/jpg/jpeg/webp: 403 si la ruta escapa o la extensión no vale, 404 si falta;
la UI lo usa para re-adjuntar la ref guardada en `params.ref_image`) y
`GET /media/{gen_id}/{name}` (PNG confinado a `data_dir/gallery/<gen_id>/`, 404/403).

El runner `run_generation(job, config, store, registry, engine_factory)` carga
`workflows\anima_base.json`, aplica `patch_model`/`patch_params` (e `to_img2img` con
`ref_image`+`strength`), encola en la `JobQueue` (`submit`→`wait`→`outputs`) y copia los PNG a
`data_dir/gallery/<gen_id>/` actualizando el store; un fallo queda en store y job sin matar al
worker. La UI (`templates/index.html` + `static/app.css` + `static/app.js`, sin CDN) trae la
pestaña **Imagen**: editor por zonas como único editor del positivo, con input rápido
(tags directos) por zona/subcategoría y «Generar prompt» global desde el cuadro de
lenguaje natural, y select de fuerza (Fiel/Balanceado/Creativo,
default Balanceado) con estados del botón; preprompt/modelo; sampler y scheduler como `<select>`
poblados desde `/api/params`; tamaño como `<select>` con los 11 presets + `Manual` (Ancho/Alto
solo en manual); negativo pre-cargado desde `/api/negative` (se refresca al cambiar preprompt
si el usuario no lo ha editado) con botón «Restaurar»; imagen de referencia con miniatura y
botón «Quitar»; Generar con polling y galería de 6 por página (‹ Anterior / página X de Y /
Siguiente ›), lightbox al clic (X y tecla ESC) y «Reusar» por tarjeta, que aplica toda la
configuración guardada de esa generación: modelo, preprompt, rating, negativo,
seed/steps/cfg/sampler/scheduler, tamaño (selecciona el preset si `width`/`height` coinciden,
si no `Manual` con esos valores), LoRAs con sus pesos y la referencia (`params.ref_image` +
`strength`, descargada como blob de `/api/refs/` y adjuntada al input); lo que falte queda en
blanco sin romper. La pestaña **Video**
(F4, ver abajo) es independiente, y el panel modal **OC Maker** (8 grupos + «Añadir al prompt»).

Desde **M9-B-fix4**, un middleware de `create_app` añade `Cache-Control: no-store` a `/` y
`/static/...` (no a `/api`, `/media` ni `/api/refs`), para que el navegador no mezcle un
`index.html` cacheado con un `app.js` nuevo. Además, `app.js` blinda el arranque: `bind()`
comprueba los elementos imprescindibles y, si falta alguno, muestra el banner
«UI desactualizada: recarga con Ctrl+F5» sin lanzar; `init()` carga cada sección con un helper
`settle` que acumula fallos y termina con `Fallaron: <secciones>` (y `console.error` por cada
uno) en vez de morir en silencio dejando los desplegables vacíos.

### Requisitos y arranque

Las 3 dependencias están instaladas en el venv del propio repo y fijadas en `requirements.txt`
(fastapi 0.141.1, uvicorn 0.53.0, jinja2 3.1.6). Para una **máquina limpia**, la instalación
reproducible (engine, runtime, modelos y LoRAs de usuario) está en `install\README_INSTALL.md`
(F3b):

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
(delete borra refs y su carpeta), `add_ref(id, src_path, *, refs_root, name)` copia una imagen
real (png/jpg/jpeg/webp) a `<refs_root>\<id>\<uuid>.<ext>` o al `name` simple indicado (misma
extensión, sin rutas; si el origen ya está en esa ruta se registra sin recopiar), `refs(id)`
lista las filas, `first_non_sheet_ref(id)` devuelve la primera ref que no es hoja (o `None`) y
`remove_ref(id, ref_id)` borra archivo y fila. `is_sheet(relpath)` detecta las hojas por el
prefijo `sheet_` del nombre del archivo. `prompt_from_tags(tags)` une con ", " dedup
case-insensitive en orden estable. Las refs viven en `data\characters\<id>\`.

Rutas nuevas en `app\server.py`: `GET /api/tags/groups` → `{groups}`;
`GET /api/tags?group=&q=&limit=` → `{items}` (por grupo, búsqueda o ambos; sin filtro, primeros
200); `GET/POST /api/characters` y `GET/PUT/DELETE /api/characters/{id}` (400 en validación, 404
si no existe); `POST /api/characters/{id}/refs` `{gen_id}` copia el primer output de
`data\gallery\<gen_id>\` (404 sin generación/archivo), `GET /api/characters/{id}/refs` añade
`url` e `is_sheet` a cada ref y `DELETE /api/characters/{id}/refs/{ref_id}`;
`GET /media/characters/{char_id}/{name}`
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
  prompt, fija preprompt/rating y adjunta la **primera ref que no sea hoja**
  como imagen de referencia del panel si existe; si solo hay hojas no adjunta
  nada y lo indica), «Editar», «Duplicar» (copia sin id, el guardado crea un OC
  nuevo) y «Eliminar» (con confirmación). Formulario Guardar/Actualizar con
  nombre, preprompt, rating y notas; los tags del OC son los seleccionados en el
  catálogo (`POST`/`PUT /api/characters`).
- **Referencias**: miniaturas de `GET /api/characters/{id}/refs` (cada item trae
  `url` e `is_sheet`) servidas por `/media/characters/{id}/{name}`, «Quitar» por
  ref (`DELETE .../refs/{ref_id}`), **«Usar como referencia»** (adjunta esa
  imagen como I2I con el `strength` actual; si es una hoja pide confirmación
  avisando de que puede copiar el mosaico) y **«Crear hoja»** (habilitado con ≥2
  refs), que llama a `POST /api/characters/{id}/sheet` y refresca la lista
  **sin adjuntarla**: la hoja se registra con su nombre `sheet_<uuid>.png`, se
  muestra con badge «hoja», la nota «Para IPAdapter (M10); no recomendada como
  referencia I2I» y un enlace «Ver/Descargar».

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
genera `<refs_root>\<id>\sheet_<uuid>.png`, lo registra como ref con
`add_ref(..., name=...)` conservando el prefijo `sheet_` (400 si quedan <2 refs,
404 si el OC no existe) y devuelve `{"relpath", "url"}`; la hoja queda como
catálogo para IPAdapter (M10), no como referencia I2I automática: la UI ya no la
adjunta al panel, `is_sheet(relpath)` la identifica y «Usar» la salta.

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

La UI (sin CDN) usa el **editor por zonas como único editor** del positivo
(`#zone-editor`, sin textarea de prompt): cada zona muestra sus tags como chips
(con «×» para quitar) y, dentro de cada bloque, un **input rápido** + «Insertar»
(M10-2f) que añade el texto como tags (separados por comas, con trim y dedup
global, sin LLM). El **prompt final** (`#prompt-final`, `<textarea>` readonly
con «Copiar») se recompone con `composePrompt()` tras cada cambio; el botón `+`
de cada zona abre su popover de opciones —el de **«Personaje»** incluye «Mis
OCs»— anclado junto al botón que lo abre (M10-2f). Solo la cabecera de
`general` conserva el `+` de subcategoría; las subcategorías se insertan con su
input rápido.

## Opciones por zona y orden canónico (M9-C2, sin «otros» desde M10-2f)

`app\prompt_zones.py` añade la capa de opciones y el orden canónico:

- `GENERAL_SUBCATS` y `GENERAL_SUBCAT_LABELS`: subcategorías de `general` en
  orden —`rasgos`, `ropa`, `accesorios`, `accion`, `poses`, `poses_sexuales`,
  `poses_sexys`, `expresion`, `expresiones_nsfw`, `camara`, `fondo`— con labels
  ES (`Rasgos`, `Ropa`, `Accesorios`, `Acción/Pose`, `Poses`, `Poses sexuales`,
  `Poses sexys`, `Expresión`, `Expresiones NSFW`, `Cámara`, `Fondo/Escena`).
  No hay `otros`; lo desconocido cae en `GENERAL_FALLBACK_SUBCAT` (`fondo`).
- `general_subcat(tag)`: `CAMERA_TAGS` (~21 encuadres/ángulos: `close-up`,
  `portrait`, `full body`, `from above`, `dutch angle`, `looking at viewer`,
  `depth of field`...) manda siempre; después mandan las listas curadas de
  M10-2f (`POSES_TAGS`, `POSES_SEXUALES_TAGS`, `POSES_SEXYS_TAGS`,
  `EXPRESIONES_NSFW_TAGS`, con precedencia tipo `CAMERA_TAGS`); si no, el grupo
  del catálogo (`hair/eyes/face/body`→`rasgos`, `outfit`→`ropa`,
  `accessories`→`accesorios`, `action`→`accion`, `expression`→`expresion`,
  `setting`→`fondo`) y los 3 tags de fondo del grupo `meta`
  (`blurry/detailed/simple background`→`fondo`, `CATALOG_TAG_SUBCAT`);
  desconocido/vacío→`GENERAL_FALLBACK_SUBCAT`.
- `canonical_order(text)`: reordena por zonas (`quality`, `safety`, `subject`,
  `character`, `general`) y dentro de general por `GENERAL_SUBCATS`; dedup
  global case-insensitive preservando la primera aparición, pesos `(tag:1.2)`
  intactos y cadenas vacías ignoradas.
- `zones_payload(prompt)`: la zona `general` añade `subcats: [{id, label,
  tags}]` (solo subcategorías con tags).
- `prompt_options(zone)`: `{zone, subgroups: [{id, label, tags: [{tag,
  label}]}]}`; quality/safety/subject desde las listas curadas de C1, general
  desde `CAMERA_TAGS` + listas curadas de M10-2f + catálogo por subcategoría
  (sin duplicar; los tags del catálogo que clasifican a otra zona no se
  publican en general) y `character` vacío (los OCs llegan en M9-B3);
  `EngineError` (400) con zona inválida.

`GET /api/prompt/options?zone=` publica esas opciones. `enhance` aplica
`canonical_order` al positivo compuesto (preprompt incluido) sin tocar el
negativo ni el `raw`. La UI abre un **popover** por botón `+` con buscador,
checkboxes con etiquetas visibles, input manual + «Añadir» e «Insertar», tabs
por subcategoría en general y la subcategoría Rasgos bloqueada con la nota
«Fijado por el OC» cuando hay un OC activo. El popover se ancla junto al botón
que lo abre (`position: fixed` + `getBoundingClientRect` con clamp de viewport,
M10-2f). El `+` de la cabecera de `general` (las subcategorías ya no tienen `+`,
M10-2f) no inserta en un subcat fijo: «Insertar» manda los tags a
`POST /api/prompt/zones` y cada uno cae donde lo clasifique el backend
(`general_subcat` + zonas); los tags desconocidos van al fallback.

## Mejora con zona objetivo (M9-C3a)

`POST /api/prompt/enhance_zones` `{text, zone?, strength?, rating?}`: mejora el
prompt y lo devuelve ya repartido para el editor por zonas.

- Valida `text` no vacío, `zone` (si viene) de
  `quality|safety|subject|character|general`, `strength` de
  `fiel|balanceado|creativo` (default `balanceado`) y `rating` `sfw|nsfw`
  (ausente → `sfw`): 400 con `{"error"}`; sin LLM → 503
  `{"error":"LLM no disponible"}` (mismo mensaje que `/api/enhance`).
- `enhancer.enhance` acepta `zone_hint` (opcional): añade al mensaje de usuario
  la línea interna `Zona objetivo: <zone>. Coloca sólo etiquetas de esa zona; si
  algo no pertenece, omítelo.` sin alterar rating, normalización, orden canónico
  ni preprompt; `None` o vacío dejan el comportamiento previo intacto.
- Respuesta: `{raw, positive, negative, composed, zones}`; `zones` es
  `zones_payload(positive)` (con `subcats` en general) y `composed` el
  `compose_zones` canónico del positivo.

## Input rápido e inserción por subcategoría (M10-2f)

Cada bloque del editor por zonas (`renderZoneEditor()`) añade un **input
rápido** (`form.zone-quick` con `input.zone-quick-input` + botón «Insertar»),
en cada zona y en cada subcategoría de `general` (las 11 se pintan siempre,
aunque estén vacías). Sustituye a los huecos de texto natural + «Mejorar» por
zona de M9-C3b-2, retirados con su `state.zoneDrafts` y sus llamadas a
`enhance_zones`:

- «Insertar» toma el texto, lo separa por comas, limpia y añade cada tag a su
  zona/subcategoría con dedup global (`addTagsToZone`), sin LLM; si ya estaba
  avisa «Sin cambios en …: ya estaba».
- El botón global «Generar prompt» (`#btn-enhance`, M10-2e) sigue usando
  `POST /api/prompt/enhance_zones` sin `zone` desde el cuadro «Prompt general»
  y fusiona las zonas con `applyZonesPayload(data.zones)`.
- El `+` de la cabecera de `general` abre el popover y «Insertar» clasifica los
  tags seleccionados con `mergeZonesText` (`POST /api/prompt/zones`), de modo
  que cada uno cae donde `general_subcat`/`classify_tag` lo resuelva.

## OCs en Personaje y rasgos/extras (M9-B3)

`app\characters.py` separa los rasgos del personaje de los extras de escena con el
catálogo real de `app.prompt_zones`:

- **Migración idempotente**: `characters` añade `extras TEXT NOT NULL DEFAULT '[]'`
  (`ALTER TABLE` en `init()` si falta, como el `kind` del store); las BD antiguas
  quedan con `extras` vacío y `get`/`list` devuelven siempre `tags` (rasgos) y
  `extras`.
- `split_character_tags(tags)`: `traits` = subcategoría `rasgos` (grupos
  hair/eyes/face/body); `extras` = ropa/accesorios/acción/poses/expresión/cámara/
  fondo (incluidos los desconocidos, que caen en el fallback) y también
  calidad/safety/sujeto (no definen al personaje). Dedup case-insensitive en
  orden estable.
- `add`/`update` normalizan: `tags` guarda solo rasgos y los extras se separan a
  `extras` (aceptan además `extras` explícito); `update(tags=...)` preserva los
  extras guardados y suma los nuevos, `update(extras=...)` los reemplaza. Nada se
  pierde. `prompt_from_extras(extras)` usa el mismo dedup/orden que
  `prompt_from_tags`.
- `CharacterStore.profile(char_id, mode="auto")`: busca el LoRA `oc-<id>` en
  `app.loras` y devuelve `{"text", "mode", "extras", "lora"}`; `auto` usa el
  trigger si hay LoRA y no está vacío, si no los rasgos; `traits` compone los
  rasgos (con LoRA o sin él) y `trigger` sin LoRA lanza `EngineError`.

`GET /api/characters/{id}/profile?mode=auto|trigger|traits` publica ese payload
(404 si el OC no existe, 400 con `mode` inválido); el CRUD devuelve `extras` en
las filas y acepta `extras` en `POST`/`PUT`.

La UI mantiene el **OC Maker** pero el catálogo del formulario se limita a los
grupos de rasgos (pelo/ojos/cara/cuerpo) con la nota «Solo rasgos del personaje;
ropa/entorno se eligen en Composición (General)»; los extras guardados (legacy)
se listan aparte con «Mover a General», que los inserta en el prompt actual
(zona general vía `/api/prompt/insert`) y, solo si el usuario confirma, los quita
del OC. El botón «Usar» y el picker **«+ Personaje»** componen vía `profile`: el
popover de la zona Personaje muestra **«Mis OCs»**, inserta el `text` en
`character`, autoselecciona el LoRA `oc-<id>` con su `default_weight` en el panel
LoRAs (avisando si no está en la familia activa), ofrece el checkbox «aplicar
extras del OC a General» (default ON, por subcategoría) y, cuando hay LoRA, el
toggle «usar rasgos en vez del trigger» (repite con `mode=traits`); «Usar» hace
lo mismo desde el modal sin romper las referencias (sigue adjuntando la primera
ref que no sea hoja).

## Video (F4)

La pestaña **Video** es independiente de la de imagen y tiene dos motores, cada uno con su
plantilla API-format certificada en `workflows\`:

| Motor | Plantilla | Perfil |
|-------|-----------|--------|
| **Wan 2.2 I2V** | `workflows\wan22_i2v_432x768.api.json` | I2V (`WanImageToVideo`): 81 frames (4n+1), 16 fps, 20 pasos, CFG 4.0, euler/`simple`, shift 8, GGUF High+Low (`Wan2.2-I2V-A14B-*-Q4_K_S`), CLIP `umt5_xxl_fp8_e4m3fn_scaled` type `wan`, VAE `wan_2.1_vae`; vertical 432×768 (default) u horizontal 768×432 |
| **MiniMax H3 FL2VA** | `workflows\h3_fl2va_vertical.api.json` | FL2VA (`MiniMaxH3ImageToVideo`) con first/last frame: 576×1024, 192 frames (~8 s a 24 fps), 4 pasos, turbo LoRA, `res_multistep`/`simple`, VAE de video + VAE de audio |

La plantilla Wan se exportó del legacy con la función pura `build_wan_graph`
(archivada en `data\gates\m10\evidencia-legacy\nw04_wan_graph.py`, fuera de git) con seed 42,
prefijo `waifu/video` y textos placeholder neutros; la de H3 es copia verbatim del certificado.
`app\video.py` las parchea sobre copias profundas: `prepare_wan_graph` fija CLIPTextEncode `5`/`6`,
LoadImage `7`, width/height de
`WanImageToVideo` y la seed de los samplers; `prepare_h3_graph` fija LoadImage `140`/`141`,
`MiniMaxH3ImageToVideo` `131` y `RandomNoise` `129`; ambos lanzan `EngineError` si faltan nodos o
campos.

`app\motion.py` escribe el motion positivo con el LLM local: `SYS_PROMPT_MOTION` y
`MOTION_NEGATIVE` son copias EXACTAS del legacy (archivado en
`data\gates\m10\evidencia-legacy\motion.py`), `write_motion`
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
`id`, `family`, `file` (relativo a `ComfyUI\models\loras`, admite subcarpetas), `display_name`,
`trigger`, `default_weight` (0..2), `source`, `license` y `notes`; el `_comment`
del registro recuerda que **el resto de LoRAs de Anima llegan en M10 (descargas
diferidas)** y solo se registran ficheros presentes en disco:

| id | familia | archivo |
|----|---------|---------|
| `lightx2v-wan-high` | `wan` | `lightx2v\wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors` |
| `lightx2v-wan-low` | `wan` | `lightx2v\wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors` |
| `minimax-h3-fl2v-turbo-4step` | `h3` | `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` (turbo de la plantilla H3) |
| `miku-nakano-anima` | `anima` | `anima\Miku_Nakano_Anima_v0.7.safetensors` (Anima base 28 bloques: nativo con `anima-official-aesthetic-v11`; en los 2.9B, patch 28→40 de M10 y peso 0.5-0.7) |
| `kurashiki-reika-saimin-anima` | `anima` | `anima\Kurashiki Reika Saimin Seishidou.safetensors` (Anima nativo; trigger `kur4sh1k1r31k4`) |
| `shuuko-komi-s1s2-anima` | `anima` | `anima\shuuko-komi-s1s2.safetensors` (Anima nativo; trigger `shuuko komi`) |

Uso para Miku: modelo `anima-official-aesthetic-v11`, LoRA `miku-nakano-anima`,
peso 1.0 y trigger `M1kuNakan0_anima` + tags de apariencia.

Uso para Reika Saimin: modelo Anima (p.ej. `one-obsession-anima-v40`), LoRA
`kurashiki-reika-saimin-anima`, peso 1.0 (ajustable 0.6-1.0) y trigger
`kur4sh1k1r31k4`.

Uso para Shuuko Komi S1S2: modelo Anima, LoRA `shuuko-komi-s1s2-anima`,
peso 1.0 y trigger `shuuko komi`. Los LoRAs se registran en el JSON o desde la
UI («Gestionar biblioteca», M10-5b); la app no escanea la carpeta.

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

El panel **Imagen** trae una sección **LoRAs** plegable poblada desde
`GET /api/loras?family=<familia del modelo>`: en el panel se ve «Elegir LoRAs (N)» con chips
compactos de los seleccionados (nombre + peso, «×» para quitar) y el modal `#lora-modal`
(M9-B-fix6, ver abajo) concentra la elección con checkbox + slider de peso (0..2, paso 0.05,
default el `default_weight` del registro). Si la
familia no tiene entradas, muestra «No hay LoRAs de imagen registradas. Añádelas en
`registry\loras.json` con familia `anima` (o espera las descargas de M10)». Para registrar una a
mano: deja el `.safetensors` bajo `ComfyUI\models\loras` (con su subcarpeta si la tiene) y añade
la entrada a `registry\loras.json` con `family: "anima"` y `file` relativo a esa carpeta: `file`
admite subcarpetas (en JSON, `Carpeta\\archivo.safetensors`) y el valor debe coincidir con la
ruta relativa real en disco.
`POST /api/generate` recibe `loras: [{"id", "weight"}]` con
los marcados, y el resumen de cada tarjeta de la galería lista los LoRAs usados
(`lora <id> @ <peso>`); «Reusar» vuelve a marcarlos y ajustar sus pesos desde
`params.loras` del store (además de modelo, preprompt, rating, negativo,
seed/steps/cfg/sampler/scheduler, tamaño y referencia guardada; ver «Webapp (F3)»).

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

## Pestaña Editor (M9-G)

Esqueleto de la tercera pestaña **Editor (Qwen-Image 2.1)** con guarda de «modelo no instalado»;
no ejecuta nada todavía (sin GPU, red ni dependencias nuevas).

- `GET /api/editor/status` → `{"installed", "model", "expected", "note"}` con
  `model: "qwen-image-2.1"` y `note: "La descarga e integración llegan en M10"`. `installed` exige
  que existan **todos** los archivos esperados (rutas relativas a `ComfyUI/models`, no se inventa
  que existan). El catálogo vive en `registry/editor_models-v1.json` (M10-6b) y son los nombres
  reales del par UC (`abenzerps/Qwen-Image-2.1-Uncensored-GGUF`), cargados por `app/editor_models.py`:
  - `unet/qwen-image-2.1-UC-Q4_K_M.gguf`
  - `text_encoders/qwen3vl_8b_int8_convrot.safetensors`
  - `vae/qwen_image_2.1_vae_bf16.safetensors` (VAE del Editor; **no** es el de Anima
    `vae/qwen_image_vae.safetensors`, que no se pisa)
- `POST /api/editor/generate` `{prompt, mode ("generate"|"edit", default generate), ref_images_b64?,
  size? {width,height}, seed?}`: valida la forma (400) con prompt no vacío, `mode` válido, máximo
  **10** referencias base64 válidas, `size` en `[512, 2048]` múltiplos de 16 y `seed` entera. Si la
  validación pasa: **503** `{"error": "modelo no instalado (M10)"}` cuando falta el modelo y **501**
  `{"error": "integracion pendiente (M10)"}` cuando está instalado (placeholder honesto, sin job).
- UI (sin CDN, resto intacto): tercera pestaña con banner ámbar «Qwen-Image 2.1 no instalado — llega
  con las descargas M10» (verde si instalado), prompt, modo Generar/Editar, hasta 10 referencias con
  miniaturas y «Quitar», ancho/alto manuales (nota 2K máx: 512-2048, múltiplos de 16), seed y
  «Generar» habilitado solo con prompt; al pulsar, si no está instalado muestra el 503 del servidor.
- **M10** traerá la descarga/integración del par UC (GGUF Q4_K_M + text encoder int8 ConvRot + VAE
  bf16) y el job real (encolado, progreso y galería) sobre este contrato; el manifiesto y la
  verificación sha256 viven en `install/`.

## Arreglos UI (M9-B-fix6)

Cuatro arreglos sobre la UI de Imagen (solo `templates\index.html`, `static\app.css`, `static\app.js`):

- **OC Maker no abría**: `bind()` moría en `for (const id of ("zone-ocs-extras", "zone-ocs-traits"))`
  (expresión coma: iteraba los caracteres de `"zone-ocs-traits"`), así que `$("z")` era `null` y
  `.addEventListener` lanzaba TypeError antes de enlazar `#btn-oc`; el resto de listeners
  anteriores ya funcionaba. Ahora todo `bind()` usa el helper `on(id, evento, fn)`, que si falta
  el elemento hace `console.error` y sigue con el siguiente (sin lanzar); `REQUIRED_IDS` solo avisa
  con el banner «UI desactualizada: recarga con Ctrl+F5» y `bind()` ya no aborta. Además
  `openOcModal()` va en try/catch: si algo falla al abrir, lo registra en consola, lo refleja en el
  estado del modal y muestra el banner.
- **Un solo botón «Personaje»**: se elimina el botón duplicado `#btn-zone-character` («+ Personaje»)
  y queda el chip «Personaje» de la fila con la clase `zone-chip-accent`, que abre el mismo
  popover con «Mis OCs» + tags manuales.
- **Panel con secciones plegables**: `<details class="advanced panel-section" data-section="...">`
  para «Prompt por zonas» (abierta por defecto), «Opciones de generación», «Tamaño», «LoRAs (N)»,
  «Negativo (avanzado)» e «Imagen de referencia» (cerradas); quedan fijos arriba Modelo, Preprompt,
  Rating, prompt + «Mejorar prompt» y al final Generar. El estado abierto/cerrado por sección se
  persiste en `localStorage` (`waifu.ui.section.<sección>` = `1`/`0`) y se restaura al arrancar.
- **Selector de LoRAs en ventana**: el panel muestra «Elegir LoRAs (N)» + chips compactos de los
  seleccionados (nombre + peso `@ x.xx` con «×» para quitar) y el modal `#lora-modal` trae
  buscador, lista con checkbox + slider 0-2 (`default_weight`), contador de seleccionados,
  «Quitar todos» y «Listo». El payload de `/api/generate` no cambia (`loras: [{id, weight}]`) y
  «Reusar» restaura la selección desde `params.loras` reflejándola en chips y modal.

Verificado con `node --check static\app.js` y la suite CPU (718 tests OK, sin GPU/red).

## Reorden del panel de Imagen (M9-B-fix7)

Reorden del panel lateral de la pestaña Imagen según el flujo real de uso (solo `templates\index.html`,
`static\app.css`, `static\app.js` y este README; sin GPU, red, dependencias, endpoints ni cambios en
el payload de `/api/generate`):

1. **Modelo** (fijo): selector `#model` arriba del todo.
2. **Prompting** (fijo, no colapsable, envuelto en `.prompt-block`): `#zone-editor` (editor por
   zonas, único editor del positivo, con huecos naturales por zona) + «Mejorar prompt» global con
   fuerza (`#enhance-strength`), `#preprompt` + «Gestionar» y `#rating`; después, las secciones
   plegables «Prompt por zonas» (`#section-zones`, abierta por defecto, con chips/popovers) y
   «Prompt final (solo lectura)» (`#section-final-prompt`).
3. **Generar** (fijo): `#btn-generate` + `#btn-cancel`, `#job-status` y `#job-progress` justo después
   del prompting (ya no al final del panel).
4. **LoRAs (N)** (`#section-loras`, plegable, cerrada por defecto): «Elegir LoRAs (N)» + chips.
5. **Imagen de referencia** (`#section-ref`, plegable, cerrada por defecto).
6. **Opciones de generación** (`#section-params`, plegable, cerrada por defecto): seed, pasos, cfg,
   sampler y scheduler, más **Tamaño** (`#size` + `#manual-size` con ancho/alto) dentro de la misma
   sección; el **Negativo (avanzado)** queda como sub-sección plegable anidada (`#section-negative`)
   dentro de Opciones (en vez de sección propia al final) para mantenerlo a mano sin añadir otro
   bloque suelto a la columna.

Compatibilidad: se conservan todos los ids; `#section-size` deja de ser `<details>` y pasa a ser el
bloque no plegable `#section-size.section-subblock` dentro de Opciones. El mecanismo de
`localStorage` (`waifu.ui.section.<sección>` = `1`/`0`) se mantiene para `zones`, `params`, `loras`,
`negative` y `ref` (claves sin cambios ni migración); la clave antigua `size` deja de usarse al
fusionarse Tamaño en Opciones. Por defecto: Prompt por zonas abierta; LoRAs, referencia, opciones y
negativo cerradas.

Verificado con `node --check static\app.js`, la suite CPU (718 tests OK, sin GPU/red) y conteo
DOM↔JS sin ids perdidos.

## Panel a 2 columnas y popover coherente (M9-B-fix8)

Reorganización del panel lateral de la pestaña Imagen y sincronización del popover de zonas con
las tags reales del prompt (solo `templates\index.html`, `static\app.css`, `static\app.js` y este
README; sin GPU, red, dependencias, endpoints ni cambios en el payload de `/api/generate`):

- **Layout 2 columnas**: `aside.controls` de Imagen pasa a grid
  (`grid-template-columns: minmax(240px, 300px) minmax(320px, 1fr)`, `align-items: start`) con
  dos columnas. **Columna 1** (izquierda, orden): «Generar» arriba del todo con Cancelar/estado/
  progreso justo debajo, Modelo, Preprompt (con «Gestionar»), Rating, LoRAs, Imagen de referencia
  y Opciones de generación (con Tamaño y Negativo dentro). **Columna 2** (derecha): barra compacta
  «Mejorar prompt» + Fuerza, `#zone-editor` con scroll propio (`max-height`/`overflow-y: auto`)
  para que la cabecera y la barra queden visibles, y al pie «Prompt final (solo lectura)»
  plegable.
- **Fallback responsive**: con `max-width: 900px` el panel vuelve a 1 columna apilada
  (`grid-template-columns: minmax(0, 1fr)`).
- **Popover coherente**: al abrir el popover de una zona (o de una subcat de General) se
  pre-marcan los checkboxes de las tags que ya están en `state.promptZones` de esa zona/subcat
  (comparación case-insensitive con `Map`) y el contador muestra «Sin selección.» / «N
  seleccionada(s)» junto a los chips. «Insertar» aplica altas y bajas: añade las marcadas que
  falten y quita las desmarcadas que estén en la zona, con dedup CI y `renderZoneEditor()`/
  `composePrompt()` al terminar. Si el popover se abrió desde una subcat, las bajas aplican a esa
  subcat (solo tags de ella) y las altas van a la subcat de origen. El buscador y «Limpiar
  selección» no tocan `state.promptZones` hasta pulsar Insertar; los OCs aplicados desde el
  popover de Personaje se reflejan en la selección.
- Compatibilidad: se conservan todos los ids y la persistencia de colapsables
  (`waifu.ui.section.zones|params|loras|negative|ref`).

Verificado con `node --check static\app.js`, la suite CPU (732 tests OK, sin GPU/red) y
`git status --short` limitado a los 4 archivos.

## Ajustes de UI: negativo, alturas y dado de seed (M9-D1)

Tres ajustes de UI (solo `templates\index.html`, `static\app.css`, `static\app.js` y este
README; sin GPU, red, dependencias, endpoints ni cambios en el payload de `/api/generate`):

- **Negativo sin etiqueta duplicada**: en `#section-negative` se elimina el `<label>` interno que
  repetía «Negativo»; quedan la cabecera plegable «Negativo (avanzado)», el `#negative` (textarea)
  y «Restaurar» (`#btn-negative-restore`).
- **Altura reactiva y menos scroll general**: `#zone-editor` mide su contenido con tope
  `max-height: min(60vh, 640px)` y `overflow-y: auto` (sin `min-height`/`height` fijos); ya no
  reserva un hueco vacío cuando hay pocas zonas. `.zones-panel` (`#section-zones`) y su
  `.section-body` dejan de crecer (`flex: 0 0 auto`), y `.controls-column-zones` pasa a
  `overflow-y: auto` con `min-height: 0`. `aside.controls.image-controls` mantiene
  `overflow: hidden` y cada columna (`.controls-column-primary` / `.controls-column-zones`)
  scrollea solo si desborda; `#panel-image.active` fija `grid-template-rows: minmax(0, 1fr)` y
  `.gallery-panel`/`.gallery` llevan `min-height: 0` para que la galería scrollee dentro de su
  panel y el padre no scrollee como un todo.
- **Dado de seed aleatoria**: botón toggle `#btn-seed-random` (glifo 🎲, `title="Seed aleatoria"`,
  `aria-pressed` y clase `.active` visible) junto a «Generar». Estado persistido en
  `localStorage` (`waifu.seed.random` = `1`/`0`, por defecto OFF). Con el dado ON, `generate()`
  escribe una seed aleatoria nueva en `#seed` antes de construir el payload (se envía esa seed y
  «Cargar»/el registro muestran la usada); con OFF se usa el valor de `#seed` como hasta ahora.
  Si `localStorage` está bloqueado, el toggle sigue funcionando sin persistir.

Verificado con `node --check static\app.js`, la suite CPU (732 tests OK, sin GPU/red) y
`git status --short` limitado a los 4 archivos.

## Visor de imagen en la galería (M9-D2a)

La pestaña Imagen pasa de grid de tarjetas a **visor** (solo `templates\index.html`,
`static\app.css`, `static\app.js` y este README; sin GPU, red, dependencias, endpoints ni
cambios en el payload de `/api/generate`; la pestaña Video queda intacta):

- **Preview grande** `#image-preview` (con `#image-preview-img` y el placeholder
  `#image-preview-empty` «Sin generaciones»): al abrir muestra la generación **más reciente**;
  clic en la preview abre el lightbox existente.
- **Barra del visor** sobre las miniaturas: «Generar nuevo» `#btn-new-generation`, info de la
  seleccionada `#image-preview-info` (`#id · modelo · fecha`) y paginación
  `#image-prev-page` / `#image-page-info` / `#image-next-page` (`‹ página X de Y ›`).
- **Miniaturas** `#image-thumbs`: **5 por página** (`IMAGE_PAGE_SIZE = 5`) servidas por
  `/api/gallery?kind=image&limit=5&offset=…` con `count` (el filtro `kind` llega en
  M9-D2b-fix; antes se descartaban los vídeos en cliente); la seleccionada lleva la clase `selected`
  (borde/aro de acento) y `aria-current="true"`. Clic en una miniatura la muestra en grande y
  carga sus condiciones con el flujo «Reusar» (`reuseGeneration`: modelo, prompt repartido en
  zonas, preprompt, rating, seed/pasos/cfg/sampler/scheduler, tamaño, LoRAs y referencia) con
  estado «Cargado #id»; ya no hay botones «Reusar» en tarjetas de imagen.
- **Generar nuevo** `#btn-new-generation`: resetea zonas y huecos, prompt final, modelo y params
  (`applyModel` con el modelo por defecto), preprompt, rating a `sfw`, LoRAs, referencia y
  negativo restaurado. Con el dado de seed OFF vuelve a la seed por defecto
  (`#seed.defaultValue`, 42); con el dado ON conserva la seed aleatoria ya aplicada por
  `generate()`. El visor no se vacía; estado «Nuevo: opciones por defecto».
- **Guardar en OC** `#btn-save-to-oc` en la barra del visor: guarda la **imagen seleccionada**
  como referencia del OC (`openOcSaveModal` → `POST /api/characters/{id}/refs {gen_id}`); sin
  selección queda deshabilitado.
- **Al terminar una generación** (`pollJob` → `reloadImageViewerFirstPage`): el visor recarga la
  **página 1**, selecciona la nueva y la muestra en grande.
- La galería de **Video** conservó en M9-D2a sus tarjetas y su pager propio (`PAGE_SIZE = 6`,
  ids `video-gallery-*`); **M9-D2b** la sustituye por el visor de vídeo (ver abajo). El pager
  heredado de Imagen `#gallery-prev`/`#gallery-page`/`#gallery-next` se mantiene oculto (los ids
  siguen en el DOM por compatibilidad con el chequeo DOM↔JS).

Verificado con `node --check static\app.js`, la suite CPU (732 tests OK, sin GPU/red),
`git status --short` limitado a los 4 archivos y un arnés DOM (Node, fuera del repo) que
ejercita paginación, selección, «Cargado #id», resets y «done → página 1».

## Visor de video en la galería (M9-D2b)

La pestaña Video pasa de grid de tarjetas a **visor** (solo `templates\index.html`,
`static\app.css`, `static\app.js` y este README; sin GPU, red, dependencias ni
cambios en el payload de `/api/video/generate`):

**M9-D2b-fix** (paginación real): `GET /api/gallery` acepta `kind` opcional
(`image|video`; 400 con otro valor) y filtra el feed y su `count`
(`app\server.py` + `kind=None` retrocompatible en `store.list`/`store.count`);
con eso el visor de vídeo pagina en servidor (`kind=video&limit=5&offset=…`) y el
visor de imagen pasa a `kind=image` (antes descartaba vídeos en cliente).

- **Preview grande** `#video-preview` (`<video controls preload="metadata">`) con placeholder
  `#video-preview-empty` «Sin videos»: al abrir muestra el vídeo **más reciente**; los controls
  nativos reproducen/pausan/hacen seek.
- **Barra del visor** sobre las miniaturas: «Generar nuevo» `#btn-new-video`, info de la
  seleccionada `#video-preview-info` (`#id · engine/mode · fecha`, p. ej. `#8 · wan/flf2v ·
  2026-09-24 20:08`) y paginación `#video-prev-page` / `#video-page-info` / `#video-next-page`
  (`‹ página X de Y ›`).
- **Miniaturas** `#video-thumbs`: **5 por página** (`VIDEO_PAGE_SIZE = 5`) con paginación
  **server-side** (`/api/gallery?kind=video&limit=5&offset=…` + `count`, igual que el visor de
  imagen; M9-D2b-fix). Antes se pedía la ventana reciente `/api/gallery?limit=24`, se filtraba
  `kind === "video"` en cliente y se paginaba el array: los vídeos fuera de los 24 ítems más
  recientes (el feed mezcla imagen y vídeo) no aparecían. Cada miniatura es un `<video muted preload="metadata" playsinline>`
  que busca el primer frame (`currentTime = 0.01` en `loadedmetadata`); la seleccionada lleva la
  clase `selected` y `aria-current="true"`. Clic en una miniatura la muestra en grande y carga
  sus condiciones.
- **Cargar condiciones de vídeo** (`reuseVideoGeneration`, estado «Cargado #id»): lee el `params`
  guardado por `/api/video/generate` (`engine`, `mode`, `aspect`, `seconds`/`frames`, `seed`,
  `image`, `last_image`) y el positivo/negativo de la fila (`item.prompt` guarda
  `motion_positive` en Wan o el prompt en H3; `item.negative` guarda `motion_negative`) y
  rellena: motor `#video-engine` (Wan/H3), modo `#video-mode` (i2v/flf2v), aspecto
  `#video-aspect`, duración `#video-seconds` con el texto de frames (`#video-seconds-info`,
  p. ej. «≈ 7.5 s → 121 frames (16 fps)»), seed `#video-seed`, movimiento `#video-motion` (o
  prompt H3 `#video-prompt`), negativo `#video-motion-negative` (vacío si la generación no
  guardó ninguno) y **re-adjunta** la imagen inicial/final desde
  `/api/refs/<image|last_image>` con el mismo patrón blob + `DataTransfer` que la referencia de
  imagen (`attachVideoFrameFromUrl`/`applyVideoSavedFrames`); si un frame ya no existe, ese input
  queda limpio y el estado lo avisa (`Cargado #id · frame guardado no disponible (HTTP 404)`).
  `applyVideoEngine()` refresca la visibilidad de campos según motor/modo.
- **Generar nuevo** `#btn-new-video` (`startNewVideo`): resetea a defaults — Wan/i2v, aspecto
  vertical, 5 s (81 frames), seed por defecto de `#video-seed` (42), movimiento/negativo/prompt
  H3 vacíos y referencias limpias — con estado «Nuevo: opciones por defecto»; el visor no se
  vacía.
- **Al terminar un vídeo** (`pollJob` → `reloadVideoViewerFirstPage`): el visor vuelve a la
  página 1, selecciona el nuevo y lo muestra en grande. Progreso y cancelar del job no cambian.
- **Ids heredados**: el pager antiguo de vídeo (`#video-gallery-prev`/`#video-gallery-page`/
  `#video-gallery-next`) queda **oculto** en el DOM (igual que el pager heredado de imagen) para
  no romper `REQUIRED_IDS`/el chequeo DOM↔JS; el grid `#video-gallery` se elimina junto con
  `galleryCard`/`renderGallery`/`renderVideoGallery`/`loadGallery`. La constante `PAGE_SIZE = 6`
  se conserva porque la suite la exige como marcador en `static\app.js`.

Verificado con `node --check static\app.js`, la suite CPU (737 tests OK, sin GPU/red),
`git status --short` limitado a los archivos del visor + `app\server.py`/`app\store.py`/`tests\`,
y un arnés DOM (Node, fuera del repo) que ejercita preview, toolbar, paginación (página 1 de 2),
5 miniaturas con selección, «Cargado #8» con motor/modo/aspecto/segundos/frames/seed/motion/
negativo y frames re-adjuntados, H3, frame ausente, «Generar nuevo» y «done → página 1 + nuevo en
grande». El fix se verificó además con `TestClient` sobre store temporal (3 imágenes + 4 vídeos):
`/api/gallery?kind=video&limit=5` devuelve solo vídeos en orden desc con `count=4`,
`/api/gallery?kind=nope` responde 400 y el visor pide `kind=video&limit=5&offset=…`.

## M10 (plataforma local: modelos, editor, visión)

- **Perfiles H3** (`registry/h3_presets-v1.json`): Referencia / Calidad (default) / Ligero con duración 5-15 s (grid `17k+5`, ≤0.98 MP) y variantes `turbo4`/`turbo8`; toggle **Sage Attention**; LoRA 8-step. Tarjeta Vídeo → motor H3.
- **Pestaña Upscaler** (M10-2d): imágenes ×2 (RealESRGAN x2), vídeo ×2 por frames con tiling y audio conservado, FPS con RIFE ×2/×4.
- **Editor Qwen-Image 2.1 UC** (M10-3): se activa con `registry/editor_models-v1.json` (GGUF Q4_K_M + Qwen3-VL-8B int8 ConvRot + VAE bf16); refs ≤10 y tamaño 512-2048 (múltiplo de 16); 503 si falta el modelo. El GGUF exige el fork **leejet/ComfyUI-GGUF** (arquitectura `qwen_image21`).
- **Imagen → prompt (M10-4b)**: botón **«Describir»** en el visor de imagen; `POST /api/vision/image_to_prompt` devuelve tags WD14 (onnxruntime, CPU) y caption Qwen2.5-VL (llama.cpp + mmproj; `WAIFU_VL_GPU_LAYERS`, default 0); `GET /api/vision/status` muestra el estado real de cada componente.
- **Prompt de vídeo H3** (M10-4e): botón «Mejorar prompt (H3)» (`POST /api/video/h3_prompt`) que reescribe los tres bloques (`integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`).
- **Generar prompt con tags** (M10-4d): `/api/prompt/enhance_zones` acepta `tags` (≤120) como «ya aplicadas» para no repetirlas; la UI las envía desde el editor por zonas.
- **Perfiles de tamaño de vídeo** (M10-4d): `VIDEO 9:16 HD` (576×1024), `VIDEO 16:9 HD` (1024×576) y **`VIDEO 9:16 XL` (1008×1792) / `VIDEO 16:9 XL` (1792×1008)** — mismo aspecto exacto que el vídeo y 1,81 MP (más que el mayor normal), pensados como imagen de entrada (más resolución → más detalle en cara/ojos).
- **Catálogo de tags completo** (M10-5): `registry/tags_danbooru.json` v2 con base curada (labels es) + top-N con `rank` de Danbooru; se regenera con `python scripts/build_tags_catalog.py`.
- **Referencia y tamaño**: con imagen de referencia el grafo pasa a img2img; la referencia se ajusta (**cover + recorte centrado**) al tamaño elegido antes de encolar, para que el selector de tamaño mande (antes heredaba las dimensiones de la referencia).
- **Huérfanos por reinicio**: al arrancar la app, `Store.fail_stale()` cierra las filas `queued/running` («interrumpido por un reinicio de la app»).

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
`python\` y `.venv\`). `E:\IA\VIDEO` se retiró por completo el 2026-09-26: la ruta ya no existe y
el repo no depende de ella. Las fuentes certificadas que salieron del legacy viven copiadas en
`app\` (`enhancer.py`, `motion.py`, `preprompts.py`, `formats.py`) y el material legacy (planner,
`build_wan_graph`, manifiestos de descarga) quedó archivado como evidencia local en
`data\gates\m10\evidencia-legacy\` (fuera de git). La instalación limpia se documenta en
`install\README_INSTALL.md`.

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
