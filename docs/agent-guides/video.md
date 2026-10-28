# Vídeo Wan AIO

- Motor único: `wan2.2-i2v-rapid-aio-v10-nsfw-Q4_K_M.gguf`, un `KSampler`, I2V.
- El clip debe salir mudo; compruébalo con `ffprobe -select_streams a`.
- Presets: Fast, Standard, Quality y Manual. En Manual se envían sampler, scheduler, pasos y shift.
- El aviso de licencia comunitaria debe estar visible en la pestaña.
- No se ofrece el modelo dual high/low.
- La generación se encola en `POST /api/video/generate` y se consulta en `/api/jobs/{id}`.
