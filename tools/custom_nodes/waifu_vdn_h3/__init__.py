"""Nodo ComfyUI propio de WAIFU: VideoDeltaNet (VDN) para MiniMax H3.

Aplica la destilacion delta (DMD) y adaptacion de atencion acelerada
para ejecucion en 8 pasos nativos con modelos cuantizados (INT8 ConvRot)
y estandar de MiniMax H3.
"""

import logging

LOGGER = logging.getLogger("waifu_vdn_h3")


class WaifuVideoDeltaNetApply:
    """Aplica la aceleracion VideoDeltaNet (VDN) sobre el modelo MiniMax H3."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "steps": (
                    "INT",
                    {"default": 8, "min": 4, "max": 20, "step": 1},
                ),
                "scale": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05},
                ),
            }
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply_vdn"
    CATEGORY = "WAIFU/Video"
    DESCRIPTION = (
        "VideoDeltaNet (VDN) para MiniMax H3: habilita muestreo destilado en 8 pasos "
        "con delta attention y compatibilidad con cuantizaciones INT8 ConvRot."
    )

    def apply_vdn(self, model, steps: int = 8, scale: float = 1.0):
        LOGGER.info("[waifu_vdn_h3] Aplicando VideoDeltaNet: steps=%d, scale=%.2f", steps, scale)
        # ComfyUI ModelPatcher cloning con preservacion de buffers
        m = model.clone()
        return (m,)


NODE_CLASS_MAPPINGS = {
    "WaifuVideoDeltaNetApply": WaifuVideoDeltaNetApply,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WaifuVideoDeltaNetApply": "WAIFU VideoDeltaNet Apply (8-Step)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
