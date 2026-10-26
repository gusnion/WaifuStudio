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
`GET /api/video/presets` lista tamaños y perfiles. El MP4 incluye AAC.

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
