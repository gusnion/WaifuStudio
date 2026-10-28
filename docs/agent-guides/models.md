# Configurar un modelo de imagen

1. Copia el `.safetensors` en `ComfyUI/models/checkpoints/` o `diffusion_models/` según su arquitectura.
2. Pulsa recarga en la barra superior o llama `GET /api/models?scan=1`.
3. En `data/registry/models.json` revisa `family`, `subfamily` y `prompt_profile`.
4. Si falta subrama, usa `PUT /api/models/{id}` con `{"subfamily":"illustrious"}` o el valor correcto.
5. Comprueba que el selector muestra el badge y que el placeholder cambia según el perfil.
6. Genera una imagen de prueba antes de usar el modelo en producción.
