"""Catalogo local de presets de video Wan (M10-2a): ``registry/video_presets-v1.json``.

Espejo de `app.formats`: solo stdlib, sin red ni dependencias. Carga perezosa y
estricta (EngineError claro si el JSON falta, no tiene la forma esperada o un
preset es invalido). Cada preset trae id/label/note, tamano por aspecto
(``vertical``/``horizontal``) y perfil de muestreo (``sampler``/``scheduler``/
``steps``/``shift``). ``preset`` ausente, vacio o ``"manual"`` = sin preset.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from app.config import APP_ROOT
from app.engine import EngineError
from app.params import is_valid_sampler, is_valid_scheduler

PRESETS_PATH = APP_ROOT / "registry" / "video_presets-v1.json"
PRESET_MANUAL = "manual"
VIDEO_ASPECTS: tuple[str, ...] = ("vertical", "horizontal")
MIN_PRESET_STEPS = 1
MAX_PRESET_STEPS = 200
MIN_PRESET_SIZE = 16
PRESET_SIZE_STEP = 16


def _parse_size(entry: dict, aspect: str, preset_id: str) -> dict[str, int]:
    value = entry.get(aspect)
    if not isinstance(value, dict):
        raise EngineError(
            f"preset de video {preset_id!r}: falta el tamano {aspect!r}"
        )
    sizes: dict[str, int] = {}
    for name in ("width", "height"):
        size = value.get(name)
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < MIN_PRESET_SIZE
            or size % PRESET_SIZE_STEP != 0
        ):
            raise EngineError(
                f"preset de video {preset_id!r}: {name} {aspect} invalido "
                f"(min {MIN_PRESET_SIZE}, paso {PRESET_SIZE_STEP}): {size!r}"
            )
        sizes[name] = size
    return sizes


def _parse_steps(value: Any, preset_id: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_PRESET_STEPS <= value <= MAX_PRESET_STEPS
    ):
        raise EngineError(
            f"preset de video {preset_id!r}: steps invalido "
            f"(entero {MIN_PRESET_STEPS}..{MAX_PRESET_STEPS}): {value!r}"
        )
    return value


def _parse_shift(value: Any, preset_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineError(
            f"preset de video {preset_id!r}: shift invalido (numero > 0): {value!r}"
        )
    shift = float(value)
    if not math.isfinite(shift) or shift <= 0:
        raise EngineError(
            f"preset de video {preset_id!r}: shift invalido (numero > 0): {value!r}"
        )
    return shift


def _parse_preset(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise EngineError(f"preset de video #{index} invalido: se esperaba objeto")
    preset_id = entry.get("id")
    if not isinstance(preset_id, str) or not preset_id.strip():
        raise EngineError(f"preset de video #{index} sin id valido: {preset_id!r}")
    preset_id = preset_id.strip()
    if preset_id == PRESET_MANUAL:
        raise EngineError(f"preset de video: el id {PRESET_MANUAL!r} esta reservado")
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        raise EngineError(f"preset de video {preset_id!r}: label invalido: {label!r}")
    note = entry.get("note")
    if not isinstance(note, str):
        raise EngineError(f"preset de video {preset_id!r}: note invalido: {note!r}")
    sampler = entry.get("sampler")
    if not is_valid_sampler(sampler):
        raise EngineError(
            f"preset de video {preset_id!r}: sampler invalido: {sampler!r}"
        )
    scheduler = entry.get("scheduler")
    if not is_valid_scheduler(scheduler):
        raise EngineError(
            f"preset de video {preset_id!r}: scheduler invalido: {scheduler!r}"
        )
    sizes = {aspect: _parse_size(entry, aspect, preset_id) for aspect in VIDEO_ASPECTS}
    return {
        "id": preset_id,
        "label": label.strip(),
        "note": note,
        "sampler": sampler,
        "scheduler": scheduler,
        "steps": _parse_steps(entry.get("steps"), preset_id),
        "shift": _parse_shift(entry.get("shift"), preset_id),
        **sizes,
    }


def load_video_presets(path: str | Path = PRESETS_PATH) -> dict[str, dict[str, Any]]:
    """Lee y valida el catalogo; EngineError claro si falta o es invalido."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(
            f"catalogo de presets de video ilegible: {path}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("presets"), list):
        raise EngineError(f"catalogo de presets de video invalido: {path}")
    presets: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(data["presets"]):
        preset = _parse_preset(entry, index)
        if preset["id"] in presets:
            raise EngineError(
                f"preset de video duplicado en {path}: {preset['id']!r}"
            )
        presets[preset["id"]] = preset
    if not presets:
        raise EngineError(f"catalogo de presets de video sin presets: {path}")
    return presets


_PRESETS: dict[str, dict[str, Any]] | None = None


def video_presets() -> dict[str, dict[str, Any]]:
    """Catalogo cargado una vez (perezoso); copia profunda por llamada."""
    global _PRESETS
    if _PRESETS is None:
        _PRESETS = load_video_presets(PRESETS_PATH)
    return copy.deepcopy(_PRESETS)


def list_video_presets() -> list[dict[str, Any]]:
    """Copia serializable de los presets, en orden del catalogo."""
    return [copy.deepcopy(preset) for preset in video_presets().values()]


def get_video_preset(preset_id: object) -> dict[str, Any]:
    """Preset por id estricto (nunca ``manual``); EngineError si no existe."""
    entry = (
        video_presets().get(preset_id.strip())
        if isinstance(preset_id, str)
        else None
    )
    if entry is None:
        raise EngineError(f"preset de video desconocido: {preset_id!r}")
    return entry


def resolve_video_preset(preset: object) -> dict[str, Any] | None:
    """Preset por id; ausente/``""``/``"manual"`` = sin preset.

    EngineError si ``preset`` no es texto o si el id no existe en el catalogo.
    """
    if preset is None:
        return None
    if not isinstance(preset, str):
        raise EngineError(f"preset de video desconocido: {preset!r}")
    value = preset.strip()
    if not value or value == PRESET_MANUAL:
        return None
    entry = video_presets().get(value)
    if entry is None:
        raise EngineError(f"preset de video desconocido: {value!r}")
    return entry


def __getattr__(name: str) -> Any:
    """Alias perezoso del catalogo, al estilo de ``formats.IMAGE_FORMATS``."""
    if name in ("PRESETS", "VIDEO_PRESETS"):
        return video_presets()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MAX_PRESET_STEPS",
    "MIN_PRESET_SIZE",
    "MIN_PRESET_STEPS",
    "PRESETS_PATH",
    "PRESET_MANUAL",
    "PRESET_SIZE_STEP",
    "VIDEO_ASPECTS",
    "get_video_preset",
    "list_video_presets",
    "load_video_presets",
    "resolve_video_preset",
    "video_presets",
]
