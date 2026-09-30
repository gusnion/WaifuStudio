"""Nodo ComfyUI propio de WAIFU: aplica un LoRA Anima base (28 bloques) al
modelo expandido Anima-2.9B-preview (40 bloques) remapeando los indices de
bloque con la tabla canonica de `expand_manifest.json`.

Uso: sustituye al LoraLoaderModelOnly para LoRAs entrenados sobre Anima-Base
cuando el modelo cargado es el expandido; el mapeo puro vive en `mapping.py`
(stdlib, testeable offline) y aqui solo se carga el safetensors, se remapea y
se aplica con las APIs publicas de ComfyUI (`comfy.sd.load_lora_for_models`).
No se toca nada del core.
"""

import logging

import comfy.sd
import comfy.utils
import folder_paths

from .mapping import (
    ANIMA_BASE_BLOCKS,
    ANIMA_EXPANDED_BLOCKS,
    LAYOUT_BASE28,
    remap_state_dict,
)

LOGGER = logging.getLogger("waifu_anima_patch")


class WaifuAnimaPatch28to40:
    """Aplica un LoRA de 28 bloques sobre el modelo expandido de 40."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "lora_name": (folder_paths.get_filename_list("loras"),),
                "strength_model": (
                    "FLOAT",
                    {"default": 1.0, "min": -20.0, "max": 20.0, "step": 0.01},
                ),
            }
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "patch"
    CATEGORY = "WAIFU"
    DESCRIPTION = (
        f"LoRA Anima base ({ANIMA_BASE_BLOCKS} bloques) sobre el modelo expandido "
        f"({ANIMA_EXPANDED_BLOCKS} bloques): remapea los indices DiT a las "
        "posiciones originales; los bloques insertados no reciben LoRA. "
        "Los LoRAs ya nativos del modelo expandido se aplican sin cambios."
    )

    def patch(self, model, lora_name, strength_model):
        lora_path = folder_paths.get_full_path_or_raise("loras", lora_name)
        lora_sd = comfy.utils.load_torch_file(lora_path, safe_load=True)
        remapped_sd, report = remap_state_dict(lora_sd)
        LOGGER.info("[waifu_anima_patch] %s -> %s", lora_name, report["message"])
        if report["layout"] == LAYOUT_BASE28 and report["remapped"] == 0:
            LOGGER.warning(
                "[waifu_anima_patch] %s detectado como base28 sin claves que "
                "cambien; se aplica tal cual.",
                lora_name,
            )
        patched, _ = comfy.sd.load_lora_for_models(
            model, None, remapped_sd, strength_model, 0
        )
        return (patched,)


NODE_CLASS_MAPPINGS = {"WaifuAnimaPatch28to40": WaifuAnimaPatch28to40}
NODE_DISPLAY_NAME_MAPPINGS = {
    "WaifuAnimaPatch28to40": "WAIFU Anima Patch 28->40"
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
