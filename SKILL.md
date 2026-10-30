# SKILL — API HTTP de WAIFU STUDIO 2.x

## 1. Base y autenticación

Base local: `http://127.0.0.1:8765`. No hay API keys ni autenticación.
Todas las peticiones son JSON salvo la subida de addons, que es un ZIP binario.
La app y el motor deben estar arrancados (`start.bat`).

## 2. Estado del sistema

- `GET /api/first-run` → `{ready, items, missing}`.
- `GET /api/jobs/{job_id}` → estado del trabajo.
- `GET /api/models?scan=1` → catálogo de checkpoints.
- `GET /api/params`, `GET /api/formats` → catálogos de parámetros/tamaños.

## 3. Generar una imagen

`POST /api/generate`

```json
{
  "model_id": "animagine-xl-4-opt",
  "prompt": "1girl, smile, blue dress",
  "negative": "",
  "preprompt": "ninguno",
  "params": {"seed": 42, "steps": 28, "cfg": 5.0, "sampler_name": "euler_ancestral"}
}
```

Respuesta: `{"job_id":"<32 hex>"}`. La generación es asíncrona.

## 4. Seguir un job

`GET /api/jobs/{job_id}` devuelve:

```json
{"status":"running","progress":{"step":3,"total":28,"percent":10.7},"outputs":[],"error":null}
```

Estados: `queued`, `running`, `done`, `error`, `cancelled`.
`POST /api/jobs/{job_id}/cancel` solicita cancelación.

## 5. Descargar resultados

- `GET /media/{gen_id}/{name}` → bytes para previsualización.
- `GET /api/download/{gen_id}/{name}` → descarga con Content-Disposition.
- `GET /api/gallery?limit=20&offset=0` → historial.
- `DELETE /api/gallery/{id}` → borra una generación.

## 6. Vídeo Wan

`POST /api/video/generate`

```json
{
  "engine": "wan",
  "image_b64": "<base64>",
  "motion_positive": "She turns her head slowly",
  "aspect": "vertical",
  "preset": "rapido",
  "seconds": 5,
  "seed": 42
}
```

`preset=rapido` (4 pasos, CFG 1, LoRA 1) o `calidad` (30 pasos, CFG 4, LoRA 0).
`GET /api/video/presets` lista tamaños y perfiles. El motor AIO usa el text encoder NSFW fp8 y el LoRA `NSFW-22-H-e8` a 0.8 de forma fija. El MP4 sale **sin audio** (mudo); el audio se genera aparte en la pestaña AUDIO (MMAudio/Irodori) y se mezcla con Estudio.

## 7. Editor Qwen-Image 2.1

- `GET /api/editor/status`.
- `POST /api/editor/license` con `{"accepted":true}` si `license_accepted=false`.
- `POST /api/editor/generate`:

```json
{
  "image_b64": "<base64>",
  "prompt": "change the jacket to red",
  "mode": "edit",
  "seed": 42,
  "ref_images_b64": []
}
```

`mode` acepta `generate` o `edit`. Sin licencia aceptada devuelve `403`.
El resultado es un job normal.

## 8. Upscaler y RIFE

- `GET /api/upscale/models`.
- `POST /api/upscale` con `kind=image|video|interpolate`.

```json
{"kind":"image","image_b64":"<base64>","model":"realesrgan-x4plus","passes":[{"model":"realesrgan-x4plus","scale":4}]}
```

Para vídeo usa `source_gen` o `file`; para interpolación usa `rife_model` y
`multiplier`.

## 9. Addons

- `GET /api/addons`.
- `POST /api/addons/import` — cuerpo ZIP, `Content-Type: application/zip`.
- `POST /api/addons/{id}/enable|disable|rollback`.

El ZIP debe traer `addon.json` en la raíz con `id`, `name`, `version`,
`requires_core` y `slots`. Los slots activos son exclusivos.

## 10. Errores

Los errores de validación devuelven `400` con `{"error":"..."}`.
Conflicto de addon o licencia: `409`/`403`. Recurso inexistente: `404`.
Un fallo del motor llega como job `error` con el detalle en `error`.

## 11. Límites y buenas prácticas

- Una sola GPU y cola FIFO: no paralelices vídeo.
- `image_b64` debe ser base64 válido, sin prefijo `data:`.
- Los modelos se resuelven por `id` del catálogo, no por ruta.
- Verifica hashes de modelos contra `install/manifest/*.json`.
- No expongas los puertos 8765/8288 a la red.

## 12. Manual probado de imagen (operativa completa)

---
name: waifu-imagen
description: Genera imágenes con WAIFU STUDIO por HTTP local (T2I e img2img). Úsala cuando necesites assets de imagen generados en esta máquina sin abrir la interfaz.
---

## Skill: generar imágenes con WAIFU STUDIO (solo imagen)

Guía operativa para un agente. Todo se hace por **HTTP local**; no se abre ninguna ventana ni navegador.
La app escucha en `http://127.0.0.1:8765` y el motor ComfyUI en `http://127.0.0.1:8288`.

Rutas base de la instalación: `E:\IA\WAIFU` (app) y `E:\IA\WAIFU\.venv\Scripts\python.exe` (intérprete).

---

### 1. Antes de generar: comprobar que está vivo

```powershell
## ¿motor arriba? (ComfyUI)
try { (Invoke-WebRequest 'http://127.0.0.1:8288/system_stats' -TimeoutSec 3).StatusCode } catch { 'MOTOR CAIDO' }

## ¿app arriba?
try { (Invoke-WebRequest 'http://127.0.0.1:8765/api/models' -TimeoutSec 3).StatusCode } catch { 'APP CAIDA' }
```

Si falta alguno, levántalo. **Los dos van en segundo plano**: `start_engine.ps1` se queda en primer plano esperando, así que lánzalo con `Start-Process`.

```powershell
cd E:\IA\WAIFU

## motor en background (:8288)
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","E:\IA\WAIFU\scripts\start_engine.ps1" -WindowStyle Minimized

## app headless (:8765)
Start-Process -FilePath "E:\IA\WAIFU\.venv\Scripts\python.exe" -ArgumentList "-m","app.server" -WindowStyle Hidden

## esperar a que el motor responda (puede tardar 1-2 min la primera vez)
$t=0; while ($t -lt 120) { try { (Invoke-WebRequest 'http://127.0.0.1:8288/system_stats' -TimeoutSec 3).StatusCode; break } catch { Start-Sleep 3; $t+=3 } }
```

`python -m app.server` arranca la app **headless** (uvicorn). `start.bat` abre además navegador: no lo uses.

**Regla:** si el motor no responde, cualquier generación fallará. Espera a `/system_stats` antes de encolar.

#### 1.b Los servicios tienen que sobrevivir a tu llamada

Si lanzas esto desde un agente, **los procesos hijos pueden morir cuando termina tu comando**. `Start-Process` devuelve el control, y a los pocos segundos el motor y la app desaparecen sin dejar mensaje.

Antes de seguir, comprueba que **siguen escuchando** (espera ~10 s y repite):

```powershell
foreach ($p in 8765,8288) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if ($c) { "OK $p (pid $($c.OwningProcess))" } else { "CAIDO $p" }
}
```

Si se caen, mantenlos en un **job en segundo plano** que sobreviva a la llamada (o ejecuta la generación dentro del mismo job). Y **redirige la salida a un log**: si el motor muere, sin log no hay diagnóstico.

```powershell
Start-Process -FilePath "E:\IA\WAIFU\.venv\Scripts\python.exe" -WindowStyle Hidden `
  -WorkingDirectory "E:\IA\WAIFU\ComfyUI" `
  -RedirectStandardOutput "E:\IA\run\engine.out.log" -RedirectStandardError "E:\IA\run\engine.err.log" `
  -ArgumentList "-s","main.py","--listen","127.0.0.1","--port","8288", ...
```

Y al terminar, limpia: pueden quedar **procesos python huérfanos** aunque los puertos estén libres. Búscalos y mátalos por id (§11).

**Si la instalación es de solo lectura** (típico en agentes con sandbox, o si `start_engine.ps1` muere con `No usable temporary directory`), salta a **§11**: hay que redirigir datos, salida y `TMP`.

---

### 2. Descubrir qué hay (no inventes valores)

| Llamada | Devuelve |
|---|---|
| `GET /api/models` | modelos instalados; necesitas el campo **`id`** de cada uno |
| `GET /api/params` | samplers y schedulers válidos, y defaults |
| `GET /api/formats` | formatos de tamaño con nombre |
| `GET /api/preprompts` | presets de prompt por familia |
| `GET /api/loras` | LoRAs con `file` y `weight` |
| `GET /api/gallery` | generaciones previas, con `outputs` |

Ejemplo:

```powershell
$models = Invoke-RestMethod 'http://127.0.0.1:8765/api/models'
$models | Select-Object id, family, display_name | Format-Table
```

Usa **`id` del registro**, nunca el nombre del archivo ni el nombre visible.

---

### 3. Generar (texto → imagen)

`POST /api/generate` con JSON. Campos:

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `model_id` | string | **sí** | `id` de `/api/models` |
| `prompt` | string | **sí** | no vacío |
| `negative` | string | no | prompt negativo |
| `preprompt` | string | no | nombre de `/api/preprompts`; si se omite, el del modelo |
| `rating` | `"sfw"` \| `"nsfw"` | no | por defecto `sfw` |
| `size` | string | no | formato con nombre (tabla §6) |
| `width`, `height` | int | no | alternativa a `size`; múltiplos razonables |
| `params` | objeto | no | ver §4 |
| `loras` | array | no | `[{ "file": "...", "weight": 0.8 }]` |
| `batch_size` | int | no | **1..4**; cada imagen extra sube la seed +1 |
| `ref_image_b64` | string base64 | no | activa img2img (§7) |
| `strength` | float (0,1] | no | solo con `ref_image_b64`; por defecto el de la app |

```powershell
$body = @{
  model_id = 'anima-2.9b-preview'
  prompt   = '1girl, solo, school uniform, classroom, window light, looking at viewer, masterpiece, best quality'
  negative = 'lowres, bad anatomy, bad hands, extra digits, watermark, signature'
  size     = 'retrato_hd'
  params   = @{ steps = 30; cfg = 6.0; seed = 12345; sampler_name = 'euler'; scheduler = 'normal' }
  rating   = 'sfw'
  batch_size = 1
} | ConvertTo-Json -Depth 6

$r = Invoke-RestMethod 'http://127.0.0.1:8765/api/generate' -Method Post -ContentType 'application/json' -Body $body
$r.job_id
```

> **Los `model_id` cambian según lo que haya instalado.** Los de esta máquina a día de hoy son `anima-2.9b-preview`, `anima-official-aesthetic-v11`, `one-obsession-anima-v40`, `anima_basev10` (familia anima) y `vidrohah-v1.2` (familia sdxl). **Confírmalos siempre con `GET /api/models`** antes de generar: un id inexistente devuelve error.

Respuesta: `{"job_id": "..."}`. Con `batch_size > 1` devuelve además `job_ids`, `gen_ids` y `batch_size`.

---

### 4. Parámetros (`params`)

| Clave | Tipo | Rango típico | Default |
|---|---|---|---|
| `steps` | int | 20–35 | 30 (defaults del modelo) |
| `cfg` | float | 4–7 (Anima ~6) | 6.0 |
| `seed` | int | cualquiera | aleatoria |
| `sampler_name` | string | ver lista | `euler` (default del engine) |
| `scheduler` | string | ver lista | `sgm_uniform` (default del engine; los perfiles de modelo suelen usar `normal`) |
| `width`, `height` | int | — | del `size` o del modelo |

Samplers útiles: `euler`, `euler_ancestral`, `dpmpp_2m`, `dpmpp_2m_sde`, `dpmpp_3m_sde`, `res_multistep`, `er_sde`, `uni_pc`.
Schedulers útiles: `normal`, `karras`, `simple`, `sgm_uniform`, `beta`, `exponential`.
La lista completa y válida es la de `GET /api/params`; un valor fuera de ella devuelve error 400.

**Preprompts (importante):** si no mandas `preprompt`, se aplica el del modelo y, si no tiene, el **`glossy`**, que inyecta estilo anime (`masterpiece, absurdres, score_7/8/9`…). Eso arruina una textura o un material. Para assets que no son ilustración usa:

```powershell
preprompt = 'ninguno'    # preset vacío de verdad (positivo y negativo en blanco)
```

Lista real de presets: `GET /api/preprompts`. En esta máquina hay `anima_default`, `glossy`, `not_glossy`, `ninguno` y un preset **personalizado llamado `vacio`** que inyecta `mastepiece` (con typo) — no lo uses como "vacío"; el vacío es `ninguno`.

**Determinismo:** misma `seed` + mismos params + mismo modelo ⇒ misma imagen. Fija `seed` cuando quieras reproducir.

---

### 5. Seguir el trabajo y recoger el archivo

```powershell
do {
  Start-Sleep -Seconds 2
  $s = Invoke-RestMethod "http://127.0.0.1:8765/api/jobs/$($r.job_id)"
  $s.status
} while ($s.status -in @('queued','running'))
```

Estados: `queued` → `running` → `done`, o `error` / `cancelled`.
Durante `running` hay `progress` con `step`, `total`, `percent`.

Cuando el estado es `done`, **la propia respuesta del job ya trae los archivos**: `outputs` es una lista de `{name, url}`.

```powershell
$s.outputs                 # @( @{ name='00001.png'; url='/media/12/00001.png' } )
$s.outputs[0].name         # '00001.png'
$s.outputs[0].url          # '/media/12/00001.png'

## en disco (preferible para copiar a tu proyecto)
"E:\IA\WAIFU\data\gallery\$($s.gen_id)\$($s.outputs[0].name)"

## o por HTTP
"http://127.0.0.1:8765$($s.outputs[0].url)"
```

Alternativa si perdiste la respuesta: `GET /api/gallery/{gen_id}` devuelve la generación con `outputs` (lista de nombres) y `urls`. Ojo: `GET /api/gallery` **sin** id devuelve un objeto `{ "items": [...], "count": N }`, no una lista.

`gen_id` viene en la misma respuesta del job. Si `status` es `error`, lee el campo `error`: casi siempre es motor caído, modelo inexistente o LoRA incompatible.

---

### 6. Formatos de tamaño con nombre (imagen)

| `size` | Tamaño | Uso |
|---|---|---|
| `cuadro_hd` | 1024×1024 | cuadrado, iconos, retratos de busto |
| `retrato_sm` | 512×896 | vertical rápido |
| `retrato_plan` | 768×1344 | vertical estándar |
| `retrato_hd` | 832×1216 | vertical detalle |
| `retrato_xl` | 1024×1536 | vertical grande (más lento) |
| `paisaje_sm` | 896×512 | horizontal rápido |
| `paisaje_plan` | 1344×768 | horizontal estándar |
| `paisaje_hd` | 1216×832 | horizontal detalle |
| `paisaje_xl` | 1536×1024 | horizontal grande |

También se aceptan `width`/`height` numéricos: **rango 64–4096 y múltiplos de 8** (si no, error 400). Útil para tamaños que no están en el catálogo, por ejemplo `512x512` para una textura. Los formatos `video_*` existen en el catálogo pero son para vídeo: no los uses aquí.

---

### 7. img2img (imagen → imagen)

Igual que §3 más:

- `ref_image_b64`: la imagen en **base64** (acepta prefijo `data:image/png;base64,`).
- `strength`: 0.2 = se parece mucho al original; 0.8 = mucha libertad. Por defecto lo fija la app.

```powershell
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes('E:\proyecto\ref.png'))
$body = @{
  model_id = 'anima-29b-preview'
  prompt   = '1girl, same character, red jacket, night street'
  size     = 'retrato_hd'
  params   = @{ steps = 30; cfg = 6.0; seed = 777 }
  ref_image_b64 = $b64
  strength = 0.55
} | ConvertTo-Json -Depth 6
```

Si pasas `width`/`height`, la referencia se ajusta a ese tamaño.

---

### 8. Errores frecuentes y qué significan

| Respuesta | Causa | Solución |
|---|---|---|
| `model_id requerido` | falta el campo | lee `/api/models` y usa su `id` |
| `prompt vacio` | prompt en blanco | escribe el prompt |
| `formato desconocido: X` | `size` inválido | usa la tabla §6 o `width`/`height` |
| `sampler invalido` / `scheduler invalido` | valor fuera de la lista del engine | consulta `/api/params` |
| `batch_size invalido; usar 1..4` | lote fuera de rango | 1 a 4 |
| `strength fuera de (0, 1]` | strength 0 o >1 | 0.2–0.8 |
| `404 job desconocido` | `job_id` mal copiado | guarda el `job_id` exacto |
| `status: error` | motor caído, modelo/LoRA incompatible, OOM | revisa `error`, verifica `/system_stats` |
| `Acceso denegado` al escribir, o `No usable temporary directory` | la instalación no es escribible para este usuario | usa el redirect de §11 |
| id inexistente / modelo no encontrado | `model_id` copiado de otro sitio | `GET /api/models` y usa su `id` exacto |

---

### 9. Reglas para un agente

1. **Una generación a la vez.** La cola es FIFO de un solo trabajador: si encolas 20, se hacen en serie y las de vídeo bloquean.
2. **Espera `done` antes de leer el archivo.** En `queued`/`running` todavía no existe.
3. **No inventes `model_id`, `size`, sampler ni scheduler**: descúbrelos con §2.
4. **Fija `seed`** si vas a repetir o comparar. Anota la seed usada.
5. **Guarda un manifiesto** por asset: `{file, prompt, negative, model_id, seed, steps, cfg, size, fecha}`. Sin eso no podrás reproducir ni mantener el estilo del juego.
6. **No borres nada de `data/`.** Copia el archivo a tu carpeta de proyecto.
7. **No expongas el puerto**: la app no tiene autenticación y debe quedarse en `127.0.0.1`.

---

### 10. Flujo mínimo para hacer N assets

```powershell
$specs = @(
  @{ name='hero';   seed=101; prompt='1girl, knight, plate armor, castle courtyard, full body' },
  @{ name='npc1';   seed=102; prompt='1girl, merchant, apron, market stall, upper body' },
  @{ name='bg1';    seed=103; prompt='fantasy village at sunset, no humans, painting, landscape'; size='paisaje_hd' }
)

foreach ($s in $specs) {
  $body = @{
    model_id = 'anima-2.9b-preview'
    prompt   = $s.prompt
    negative = 'lowres, bad anatomy, bad hands, watermark'
    size     = $(if ($s.size) { $s.size } else { 'retrato_hd' })
    params   = @{ steps=30; cfg=6.0; seed=$s.seed; sampler_name='euler'; scheduler='normal' }
  } | ConvertTo-Json -Depth 6

  $r = Invoke-RestMethod 'http://127.0.0.1:8765/api/generate' -Method Post -ContentType 'application/json' -Body $body
  do { Start-Sleep 2; $j = Invoke-RestMethod "http://127.0.0.1:8765/api/jobs/$($r.job_id)" } while ($j.status -in @('queued','running'))
  if ($j.status -ne 'done') { Write-Warning "fallo en $($s.name): $($j.error)"; continue }

  $out = "E:\IA\WAIFU\data\gallery\$($j.gen_id)\$($j.outputs[0].name)"
  Copy-Item $out "E:\proyecto\assets\$($s.name).png" -Force
  [pscustomobject]@{ name=$s.name; seed=$s.seed; model='anima-29b-preview'; file="$($s.name).png" } |
    Export-Csv 'E:\proyecto\assets\manifest.csv' -Append -NoTypeInformation
}
```

---

### 11. Si la instalación es de solo lectura (agentes con sandbox)

Síntoma típico: `start_engine.ps1` muere con

```
FileNotFoundError: [Errno 2] No usable temporary directory found in ['E:\\IA\\WAIFU\\tmp', ...]
```

o cualquier escritura bajo `E:\IA\WAIFU` da **Acceso denegado**. La app y el motor necesitan escribir en `tmp`, en la salida de ComfyUI y en `data`.

Solución **sin tocar código**: redirigir todo a una carpeta escribible (`E:\IA\run` en este ejemplo), y hacer que **app y motor apunten a la misma salida**.

```powershell
New-Item -ItemType Directory -Force -Path E:\IA\run\tmp,E:\IA\run\data,E:\IA\run\comfy\output,E:\IA\run\comfy\temp | Out-Null
Copy-Item E:\IA\WAIFU\data\registry\*.json E:\IA\run\data\ -Recurse -Force   # el registro de modelos

$env:TMP="E:\IA\run\tmp"; $env:TEMP="E:\IA\run\tmp"

## motor con salida redirigida
Start-Process -FilePath "E:\IA\WAIFU\.venv\Scripts\python.exe" -WindowStyle Hidden `
  -WorkingDirectory "E:\IA\WAIFU\ComfyUI" `
  -ArgumentList "-s","main.py","--listen","127.0.0.1","--port","8288","--disable-api-nodes","--disable-auto-launch","--output-directory","E:\IA\run\comfy\output","--temp-directory","E:\IA\run\comfy\temp"

## app apuntando a los mismos datos y al mismo motor
$env:WAIFU_DATA_DIR="E:\IA\run\data"
$env:WAIFU_COMFY_ROOT="E:\IA\run\comfy"
Start-Process -FilePath "E:\IA\WAIFU\.venv\Scripts\python.exe" -WindowStyle Hidden `
  -WorkingDirectory "E:\IA\WAIFU" -ArgumentList "-m","app.server"
```

Variables de entorno que entiende la app (`app/config.py`): `WAIFU_DATA_DIR`, `WAIFU_COMFY_ROOT`, `WAIFU_COMFY_URL`, `WAIFU_APP_PORT`.

Con esto, **la galería real estará en `E:\IA\run\data\gallery\<gen_id>\`**, no en `WAIFU\data`.

#### Parar los servicios

`stop_app.ps1` / `stop_engine.ps1` usan `Get-NetTCPConnection`, que en algunos entornos restringidos no ve los listeners y responden "ya está detenida" en falso. Comprueba el puerto y, si sigue escuchando, mata el proceso por id:

```powershell
foreach ($p in 8765,8288) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if ($c) { Stop-Process -Id $c.OwningProcess -Force; "parado $p" }
}
## huérfanos: python de este proyecto que ya no escucha en ningún puerto
Get-Process python -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like 'E:\IA\WAIFU\.venv\*' } |
  ForEach-Object { Stop-Process -Id $_.Id -Force; "huérfano parado: $($_.Id)" }
```

---

### 12. Límites conocidos (2026-10)

- **Sin ControlNet** todavía: la composición se controla con prompt, seed, LoRA e img2img.
- **Sin pixel-art exacto**: llegará con MOSS Image.
- **Cola monohilo**: no paralelices generaciones.
- **No hay autenticación**: cualquier proceso local puede llamar a la API.

#### 12.1 Texturas y materiales (importante)

Los modelos instalados (Anima, SDXL/Illustrious) están entrenados para **personajes e ilustración**, no para materiales. Resultado medido en un test real: **1 textura aceptable de 4 intentos**; las otras salieron lisas, con líneas de panel o lavadas.

- **No son seamless.** Repetir 2×2 muestra costuras. Si necesitas tile infinito, genera y luego corrige con espejo/offset en un editor, o parte de una textura real con `img2img` y `strength` bajo.
- **Nombra el material y su orientación en el prompt** (`flat front view of wood surface, visible vertical grain, matte flat lighting, no perspective`) y añade en negativo `perspective, shadows, vignette, furniture, objects`.
- **Usa `preprompt: "ninguno"`** o el estilo anime se impone.
- **Genera 3–4 variantes con seeds distintas** y elige; es más rápido que afinar un prompt perfecto.
- Documenta en el manifiesto si la textura es seamless o no (no lo asumas).

Esto es todo lo que un agente necesita para generar imágenes en esta máquina sin abrir la app.

## 13. Instalar un modelo y registrarlo (agente)

1. Copia el archivo a `ComfyUI/models/checkpoints/` (SDXL/Anima) o `diffusion_models/` (UNET).
2. `GET /api/models?scan=1`; localiza el `id` y revisa `family`, `subfamily` y `prompt_profile`.
3. Si la arquitectura es desconocida, no inventes familia: deja `sin_clasificar` y pide revisión.
4. Lee la ficha del autor (base, resolución, sampler/CFG/pasos, triggers y licencia).
5. Edita la entrada con `PUT /api/models/{id}` (`display_name`, `family`, `subfamily`, `prompt_profile`, `defaults`, `image`, `url`, `source`, `license`, `triggers`, `notes`). En la UI: «Ficha y defaults del modelo».
6. Añade el preprompt recomendado con `POST /api/preprompts/custom` (sin duplicar).
7. Descarga la imagen del autor a `data/registry/media/` y referencia su ruta en la entrada.
8. Comprueba en la UI: badge, placeholder, preprompt y defaults. Si no aparece, `?scan=1`.

## 14. Cómo redactar la entrada de una LoRA

- 2–4 líneas: qué hace, cuándo usarla y qué no hace.
- `triggers[]`: exactamente los del autor, sin traducir ni inventar.
- `recommended_weight`: el peso probado por el autor o el medido en la app.
- `description`, `source`, `url`, `image`, `triggers`, `recommended_weight`, `enriched_by`, `updated_at`.
- Alta/edición: `PUT /api/loras/{id}` o «Biblioteca / metadatos» en la UI.
- Si el autor no publica triggers, deja `triggers: []` y dilo; no inventes.

## 15. Cargar un preprompt recomendado

1. `GET /api/preprompts` para ver los existentes.
2. Compara texto y familia; no dupliques uno equivalente.
3. `POST /api/preprompts/custom` con `{"name":"...","family":"...","text":"..."}`.
4. Comprueba que aparece en el panel y anota la `url` de origen.

## 16. Descargar modelos de Civitai

1. `GET https://civitai.com/api/v1/models/{id}` con `Authorization: Bearer <token>` si el modelo lo requiere.
2. Elige la versión y el archivo; descarga con reanudación.
3. Verifica `sha256` contra el publicado.
4. Guarda en la carpeta por familia (`checkpoints`, `diffusion_models`, `loras`, `vae`, `text_encoders`).
5. Alta en `data/registry/models.json` con `family`, `subfamily`, `prompt_profile` y defaults.
6. Comprueba la licencia antes de usar comercialmente; si no consta, trátala como no comercial.

## 17. Integrar un modelo cuando falta el workflow

1. Inspecciona la arquitectura por tensores; no adivines.
2. Elige el motor compatible (`wan`, `h3` o el registrado en `registry/video_engines.json`).
3. Clona el workflow más cercano y cambia solo los cargadores (UNET/TE/VAE).
4. Registra el motor y sus límites; no toques una lista cerrada de la base.
5. Prueba un paso con seed fija y valida VRAM y salida antes de anunciarlo.

## 18. Audio y vídeo

- El vídeo Wan se genera **mudo**. El audio va por AUDIO: Modo B (MMAudio) o Modo A (Irodori).
- Para adjuntar audio a un vídeo, usa Estudio → “Generar audio” o AUDIO → “Enviar a Timeline”.
