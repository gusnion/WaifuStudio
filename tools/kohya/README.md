# tools/kohya — entrenador LoRA de Anima (sd-scripts) para WAIFU

Instalacion local (2026-09-30) del entrenador real del OC Maker:

- **Checkout**: `tools/kohya/sd-scripts` de `kohya-ss/sd-scripts` pineado al tag
  **`v0.12.0`** (`690ea7f`), que incluye `anima_train_network.py` y
  `networks/lora_anima.py` (soporte Anima, PR upstream #2260). Los safetensors
  Anima del usuario citan commits de un fork local de sd-scripts que no existe
  en los repos publicos consultados (`df5ecc0d`/`a449700b`); se usa el pin
  publicado mas cercano y queda anotado aqui como procedencia.
- **Venv propio**: `tools/kohya/venv` (Python 3.12.12 gestionado), con
  `torch==2.11.0+cu130`, `torchvision==0.26.0+cu130` y
  `requirements.txt` del repo (accelerate 1.15, transformers 5.17,
  bitsandbytes 0.50.2, ...). Instalado con `uv pip`.
- **Wrapper**: `run_waifu_train.py` traduce la config TOML de la app
  (`data/trainer/train_config.toml`, escrita por `app/trainer.py`) a un dataset
  TOML de sd-scripts y a la linea de argumentos de `anima_train_network.py`
  (`--network_module networks.lora_anima`), y lanza el entrenamiento con el
  python del venv. `--dry-run` imprime el comando sin ejecutar.

## Conexion con la app

`WAIFU_TRAINER_CMD` debe apuntar al python del venv + este wrapper; la app le
anexa la ruta de `train_config.toml`:

```powershell
[Environment]::SetEnvironmentVariable(
  'WAIFU_TRAINER_CMD',
  'E:\IA\WAIFU\tools\kohya\venv\Scripts\python.exe E:\IA\WAIFU\tools\kohya\run_waifu_train.py',
  'User'
)
```

Reinicia la app para que herede la variable. La app parte el comando por
espacios (sin quoting): la instalacion por defecto `E:\IA\WAIFU` no tiene
espacios; si mueves el repo a una ruta con espacios, sigue usando este comando
sin comillas solo si ninguna ruta las lleva (o define un launcher sin espacios).
Pesos por defecto (override con `WAIFU_TRAIN_BASE` / `WAIFU_TRAIN_QWEN3` /
`WAIFU_TRAIN_VAE`, o `WAIFU_COMFY_ROOT` para la raiz):

- base: `ComfyUI/models/diffusion_models/anima_aestheticV11.safetensors`
  (Anima 28 bloques; los LoRAs de OC siguen ese linaje, nativo en la app).
- encoder: `ComfyUI/models/text_encoders/qwen_3_06b_base.safetensors`.
- VAE: `ComfyUI/models/vae/qwen_image_vae.safetensors`.

Prueba sin GPU (valida el mapeo y el script):

```powershell
& E:\IA\WAIFU\tools\kohya\venv\Scripts\python.exe tools\kohya\run_waifu_train.py `
  E:\IA\WAIFU\data\trainer\<id>\train_config.toml --dry-run
```

El **entrenamiento real lo valida el usuario** en la app (GPU); la suite offline
cubre el mapeo (`tests/test_kohya_wrapper.py`) y el pipeline del server con
comandos falsos. Actualizar el checkout: `git -C tools\kohya\sd-scripts fetch`
+ checkout de un tag nuevo solo con decision explicita (reproducibilidad del
metadata `ss_sd_scripts_commit_hash`).
