"""Catalogo local de formatos (tamano) de imagen: ``registry/formatos-v1.json``.

Procedencia legacy: copia VERBATIM del contrato ``formatos/v1`` (el origen
vivía en el repo legacy, retirado el 2026-09-26; la copia canónica es
``registry/formatos-v1.json``). El JSON lista 11 formatos de
imagen + 2 de video (``video_vertical``/``video_horizontal`` se repiten con
``tipo`` distinto); aqui solo se exponen los de ``tipo == "imagen"``, en el
orden real del catalogo. Sin red y sin dependencias: solo stdlib.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import APP_ROOT
from app.engine import EngineError

FORMATS_PATH = APP_ROOT / "registry" / "formatos-v1.json"


def _load_catalog() -> dict[str, Any]:
    """Lee el catalogo JSON; EngineError si falta o no tiene la forma esperada."""
    try:
        data = json.loads(FORMATS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"catalogo de formatos ilegible: {FORMATS_PATH}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("formatos"), list):
        raise EngineError(f"catalogo de formatos invalido: {FORMATS_PATH}")
    return data


def _image_formats(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{id: {id, label, width, height}}`` solo de ``tipo == "imagen"``."""
    formats: dict[str, dict[str, Any]] = {}
    for entry in catalog["formatos"]:
        if not isinstance(entry, dict) or entry.get("tipo") != "imagen":
            continue
        try:
            format_id = str(entry["id"])
            label = str(entry["label_es"])
            width = int(entry["width"])
            height = int(entry["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EngineError(
                f"formato de imagen invalido en {FORMATS_PATH}: {entry!r}"
            ) from exc
        formats[format_id] = {
            "id": format_id,
            "label": label,
            "width": width,
            "height": height,
        }
    if not formats:
        raise EngineError(f"catalogo de formatos sin formatos de imagen: {FORMATS_PATH}")
    return formats


_CATALOG = _load_catalog()
IMAGE_FORMATS: dict[str, dict[str, Any]] = _image_formats(_CATALOG)

_DEFAULT_DECLARADO = _CATALOG.get("default")
DEFAULT_FORMAT = (
    _DEFAULT_DECLARADO
    if isinstance(_DEFAULT_DECLARADO, str) and _DEFAULT_DECLARADO in IMAGE_FORMATS
    else "retrato_plan"
)


def list_image_formats() -> list[dict[str, Any]]:
    """Copia serializable de los formatos de imagen, en orden del catalogo."""
    return [dict(item) for item in IMAGE_FORMATS.values()]


def get_size(format_id: object) -> tuple[int, int]:
    """``(width, height)`` del formato de imagen; EngineError si no existe."""
    if not isinstance(format_id, str) or format_id not in IMAGE_FORMATS:
        raise EngineError(f"formato de imagen desconocido: {format_id!r}")
    item = IMAGE_FORMATS[format_id]
    return int(item["width"]), int(item["height"])


__all__ = [
    "DEFAULT_FORMAT",
    "FORMATS_PATH",
    "IMAGE_FORMATS",
    "get_size",
    "list_image_formats",
]
