# Guías para agentes — WAIFU STUDIO 2.x

Estas ocho guías son operativas: cada una termina en una acción verificable.
La app escucha en `http://127.0.0.1:8765`; el motor en `http://127.0.0.1:8288`.
No hay autenticación: no expongas estos puertos fuera de la máquina.

## 1. Instalar un checkpoint o modelo Wan

1. Comprueba el estado: `GET /api/models?scan=1`.
2. Copia el archivo en la carpeta correcta:
   - SDXL: `ComfyUI/models/checkpoints/*.safetensors`.
   - Wan DiT: `ComfyUI/models/diffusion_models/*.gguf`.
   - Text encoder Wan: `ComfyUI/models/text_encoders/umt5-xxl-encoder-Q5_K_M.gguf`.
   - VAE Wan: `ComfyUI/models/vae/wan_2.1_vae.safetensors`.
3. Verifica el SHA256 contra `install/manifest/manifest.wan.json` antes de usar.
4. Vuelve a llamar `GET /api/models?scan=1` y confirma que el `id` aparece.
5. Si el modelo no aparece, revisa que la extensión sea la esperada y que el
   archivo no esté en uso por otra descarga.

Criterio de éxito: `GET /api/models` devuelve el modelo con su `family` correcta.

## 2. Generar una imagen

```bash
curl -s http://127.0.0.1:8765/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"animagine-xl-4-opt","prompt":"1girl, smile, blue dress","preprompt":"ninguno","params":{"seed":42,"steps":28,"cfg":5.0}}'
```

La respuesta es `{"job_id":"..."}`. Consulta el job hasta que `status` sea
`done` o `error`:

```bash
curl -s http://127.0.0.1:8765/api/jobs/<job_id>
```

La salida trae `outputs[].url`; descárgala con
`GET /api/download/{gen_id}/{name}`. Si `status=error`, lee `error` y no
reintentes con los mismos parámetros sin corregir la causa.

## 3. Generar vídeo Wan con audio

```bash
curl -s http://127.0.0.1:8765/api/video/generate \
  -H 'Content-Type: application/json' \
  -d '{"engine":"wan","image_b64":"<base64>","motion_positive":"She turns her head slowly","aspect":"vertical","preset":"rapido","seconds":5,"seed":42}'
```

- `preset=rapido`: 4 pasos, CFG 1, LoRA LightX2V activa.
- `preset=calidad`: 30 pasos, CFG 4, LoRA en 0.
- `seconds=5` produce 81 frames a 16 fps.
- La salida incluye pista AAC generada por MMAudio.

El mismo `GET /api/jobs/{job_id}` sirve para vídeo. No lances dos jobs de vídeo
en paralelo: la cola es FIFO y la GPU es única.

## 4. Editar una imagen

1. `GET /api/editor/status` y confirma `installed=true` y la licencia aceptada.
2. Si la licencia no está aceptada: `POST /api/editor/license` con
   `{"accepted":true}`.
3. `POST /api/editor/generate` con `image_b64`, `prompt`, `mode` (`generate` o
   `edit`), `seed` y, si aplica, `ref_images_b64` y `size`.
4. Sigue el job con `GET /api/jobs/{job_id}`.

Si recibes `403`, falta la aceptación de licencia. Si recibes `400`, revisa
`size`, `steps` o el número de referencias.

## 5. Upscaler e interpolación

```bash
curl -s http://127.0.0.1:8765/api/upscale/models
curl -s http://127.0.0.1:8765/api/upscale \
  -H 'Content-Type: application/json' \
  -d '{"kind":"image","image_b64":"<base64>","model":"realesrgan-x4plus","passes":[{"model":"realesrgan-x4plus","scale":4}]}'
```

`kind` acepta `image`, `video` e `interpolate`. Para un vídeo usa `source_gen`
o `file`; para interpolación usa `rife_model` y `multiplier`. El resultado se
consulta con el job de siempre.

## 6. Galería y descarga

- `GET /api/gallery?limit=20&offset=0` lista generaciones.
- `GET /media/{gen_id}/{name}` sirve el archivo para el navegador.
- `GET /api/download/{gen_id}/{name}` fuerza descarga.
- `DELETE /api/gallery/{id}` borra la generación y sus copias.

Nunca borres `data/gallery` a mano: la base SQLite y las copias deben quedar
sincronizadas.

## 7. Addons

1. Prepara un ZIP con `addon.json` en la raíz:
   ```json
   {"id":"mi-pack","name":"Mi Pack","version":"1.0.0","requires_core":"2.x","slots":["image"]}
   ```
2. `POST /api/addons/import` con el ZIP como cuerpo binario y
   `Content-Type: application/zip`.
3. `GET /api/addons` confirma `enabled=false`.
4. `POST /api/addons/{id}/enable`; si el slot está ocupado, devuelve `409`.
5. `POST /api/addons/{id}/disable` o `/rollback` lo desactiva.

El ZIP no puede contener rutas absolutas ni `..`. Un addon incompatible con
`requires_core` se instala pero no se puede activar.

## 8. Diagnóstico

- `GET /api/first-run`: motor, modelos, FFmpeg y VRAM; `ready=false` lista lo
  que falta.
- `GET /api/models?scan=1`: catálogo real de checkpoints.
- `python -m app.health`: rutas, base de datos y servicios.
- `python -m unittest discover -s tests`: suite offline; debe terminar `OK`.
- Si el motor no responde, revisa `http://127.0.0.1:8288/system_stats` y el
  log del lanzador antes de tocar la app.

Regla de oro: un fallo de modelo o de VRAM se corrige en el modelo/engine, no
inventando endpoints nuevos en la UI.
