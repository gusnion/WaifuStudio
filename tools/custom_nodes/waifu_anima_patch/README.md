# waifu_anima_patch (nodo ComfyUI propio)

Nodo `WAIFU Anima Patch 28->40`: aplica un LoRA entrenado sobre Anima-Base
(28 bloques DiT) al modelo expandido **Anima-2.9B-preview-v1** (40 bloques),
remapeando los indices de bloque con la tabla canonica de la expansion
(`expand_manifest.json` -> `insertion_positions` = 2, 5, 8, 11, 14, 17, 21, 24,
27, 30, 33, 36; los 12 bloques insertados son copias con salidas a cero y no
reciben LoRA). Los LoRAs nativos del modelo expandido (alguna clave con bloque
>= 28) se aplican sin remapear. Las claves del text encoder (`lora_te_*`) y del
LLM adapter se dejan intactas: no cambiaron en la expansion.

Fuente de verdad: `tools/custom_nodes/waifu_anima_patch/` en el repo de WAIFU;
en `ComfyUI/custom_nodes/waifu_anima_patch` hay un junction a esta carpeta
(no editar la copia desplegada). El mapeo puro (`mapping.py`, stdlib) esta
cubierto por `tests/test_anima_patch.py` en la suite offline de la app.

Para desplegar el junction en una copia nueva (PowerShell, sin admin):

```powershell
New-Item -ItemType Junction `
  -Path 'E:\IA\WAIFU\ComfyUI\custom_nodes\waifu_anima_patch' `
  -Target 'E:\IA\WAIFU\tools\custom_nodes\waifu_anima_patch'
```

Uso en ComfyUI: conecta el MODEL del checkpoint expandido y elige el LoRA;
sustituye al `LoraLoaderModelOnly` solo cuando el modelo es el de 40 bloques
(con el modelo de 28 bloques usa el loader normal). El nodo es model-only:
las claves del text encoder (`lora_te_*`) no se aplican (igual que
`LoraLoaderModelOnly`); las DiT y del LLM adapter se dejan tal cual.
Procedencia de la tabla de expansion: `expand_manifest.json` del modelo
Anima-2.9B-preview-v1 (huggingface.co/Gazingstars123/Anima-2.9B) y el articulo
lilting.ch "Renumbered keys bring Anima-Base LoRAs back on 40-layer
Anima-2.9B"; extension de referencia "Anima 2B LoRA -> 2.9B Loader".

Pendiente (backlog): cablear el nodo en el grafo de la app para el modelo
2.9B y desplegar el junction desde `install/install.ps1` en la distribucion
publica; hoy se usa en un workflow manual de ComfyUI.
