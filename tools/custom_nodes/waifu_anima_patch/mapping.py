"""Mapeo puro de LoRAs Anima base (28 bloques) al modelo expandido de 40 bloques.

Anima-Base tiene 28 bloques DiT. Anima-2.9B-preview-v1 (Gazingstars123) amplio el
DiT a 40 bloques al estilo LLaMA Pro: 12 bloques insertados como copia de un
vecino con las proyecciones de salida a cero (``expand_manifest.json`` ->
``insertion_positions``). Los bloques originales NO cambiaron de contenido, solo
de indice: un LoRA entrenado sobre Anima-Base debe remapear sus numeros de bloque
para aterrizar en los 28 bloques originales del modelo expandido; los 12
insertados no reciben LoRA.

Tabla canonica (old -> new), derivada de las posiciones de insercion:

    OLD_BLOCK_TO_EXPANDED = {
        0: 0, 1: 1, 2: 3, 3: 4, 4: 6, 5: 7, 6: 9, 7: 10,
        8: 12, 9: 13, 10: 15, 11: 16, 12: 18, 13: 19, 14: 20,
        15: 22, 16: 23, 17: 25, 18: 26, 19: 28, 20: 29, 21: 31,
        22: 32, 23: 34, 24: 35, 25: 37, 26: 38, 27: 39,
    }

Este modulo es stdlib puro (importable sin ComfyUI ni torch) para poder testear
el mapeo offline; el nodo de ``__init__.py`` lo usa antes de aplicar el LoRA.
Las claves del text encoder (``lora_te_*``), del LLM adapter y cualquier otra no
DiT se dejan intactas: el adapter y el encoder no cambiaron en la expansion.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

ANIMA_BASE_BLOCKS = 28
ANIMA_EXPANDED_BLOCKS = 40

# Posiciones (0-based) de los bloques INSERTADOS en el modelo expandido
# (Anima-2.9B-preview-v1, expand_manifest.json).
INSERTED_BLOCK_POSITIONS = (2, 5, 8, 11, 14, 17, 21, 24, 27, 30, 33, 36)

assert len(INSERTED_BLOCK_POSITIONS) == ANIMA_EXPANDED_BLOCKS - ANIMA_BASE_BLOCKS

_ORIGINAL_POSITIONS = tuple(
    index
    for index in range(ANIMA_EXPANDED_BLOCKS)
    if index not in INSERTED_BLOCK_POSITIONS
)

OLD_BLOCK_TO_EXPANDED: dict[int, int] = {
    old: new for old, new in enumerate(_ORIGINAL_POSITIONS)
}

_KOHYA_DIT_RE = re.compile(r"^lora_unet_blocks_(\d+)_(.+)$")
_PEFT_DIT_RE = re.compile(r"^diffusion_model\.blocks\.(\d+)\.(.+)$")

LAYOUT_BASE28 = "base28"
LAYOUT_EXPANDED = "expanded"
LAYOUT_NO_DIT = "sin-bloques-dit"


def _dit_match(key: str) -> tuple[str, int] | None:
    """Devuelve (formato, indice de bloque) si la clave es DiT; si no, ``None``.

    Formatos soportados: kohya (``lora_unet_blocks_<i>_...``) y PEFT
    (``diffusion_model.blocks.<i>....``). Las claves del LLM adapter
    (``..._llm_adapter_...`` / ``....llm_adapter.blocks.``) no casan por el
    ancla del prefijo y quedan fuera.
    """
    match = _KOHYA_DIT_RE.match(key)
    if match:
        return ("kohya", int(match.group(1)))
    match = _PEFT_DIT_RE.match(key)
    if match:
        return ("peft", int(match.group(1)))
    return None


def detect_layout(keys: Iterable[str]) -> tuple[str, set[int]]:
    """Detecta si un LoRA es base28 (remapeable) o expandido (no tocar).

    Regla: si alguna clave DiT usa un bloque >= 28, el LoRA ya es del modelo
    expandido (o nativo 2.9B) y no se remapea; si todas estan en 0..27 es base28.
    """
    indices: set[int] = set()
    for key in keys:
        found = _dit_match(key)
        if found is not None:
            indices.add(found[1])
    if not indices:
        return (LAYOUT_NO_DIT, indices)
    if max(indices) >= ANIMA_BASE_BLOCKS:
        return (LAYOUT_EXPANDED, indices)
    return (LAYOUT_BASE28, indices)


def build_key_map(keys: Iterable[str]) -> tuple[dict[str, str], dict[str, Any]]:
    """Mapa ``clave_original -> clave_remap`` (solo claves que cambian) + informe.

    El informe es un dict con ``layout`` (base28|expanded|sin-bloques-dit),
    ``dit_blocks`` (indices vistos), ``remapped`` (claves cambiadas) y ``message``.
    """
    keys = list(keys)
    layout, indices = detect_layout(keys)
    report: dict[str, Any] = {
        "layout": layout,
        "dit_blocks": sorted(indices),
        "remapped": 0,
        "message": "",
    }
    if layout == LAYOUT_NO_DIT:
        report["message"] = "LoRA sin claves DiT: no hay nada que remapear."
        return {}, report
    if layout == LAYOUT_EXPANDED:
        report["message"] = (
            "LoRA ya usa bloques >= 28 (nativo/expandido): sin remapeo."
        )
        return {}, report
    mapping: dict[str, str] = {}
    for key in keys:
        found = _dit_match(key)
        if found is None:
            continue
        kind, old = found
        new = OLD_BLOCK_TO_EXPANDED[old]
        if new == old:
            continue
        if kind == "kohya":
            new_key = _KOHYA_DIT_RE.sub(
                lambda m: f"lora_unet_blocks_{new}_{m.group(2)}", key
            )
        else:
            new_key = _PEFT_DIT_RE.sub(
                lambda m: f"diffusion_model.blocks.{new}.{m.group(2)}", key
            )
        mapping[key] = new_key
    report["remapped"] = len(mapping)
    report["message"] = (
        f"LoRA Anima base (28 bloques): remapeadas {len(mapping)} claves DiT "
        "a las posiciones originales del modelo de 40 bloques; los 12 bloques "
        "insertados no reciben LoRA."
    )
    return mapping, report


def remap_state_dict(
    state_dict: Mapping[str, Any], keys: Iterable[str] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Copia del state dict con las claves DiT remapeadas + informe.

    ``keys`` permite analizar el layout sobre un subconjunto de claves (p. ej.
    solo pesos, excluyendo metadata); por defecto usa las del propio dict.
    """
    source_keys = list(state_dict.keys()) if keys is None else list(keys)
    mapping, report = build_key_map(source_keys)
    if not mapping:
        return dict(state_dict), report
    remapped: dict[str, Any] = {}
    for key, value in state_dict.items():
        remapped[mapping.get(key, key)] = value
    return remapped, report


__all__ = [
    "ANIMA_BASE_BLOCKS",
    "ANIMA_EXPANDED_BLOCKS",
    "INSERTED_BLOCK_POSITIONS",
    "LAYOUT_BASE28",
    "LAYOUT_EXPANDED",
    "LAYOUT_NO_DIT",
    "OLD_BLOCK_TO_EXPANDED",
    "build_key_map",
    "detect_layout",
    "remap_state_dict",
]
