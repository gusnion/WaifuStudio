"""Catalogo de preprompts de calidad por familia (M8-12) y propios (M9-D2).

Textos certificados copiados EXACTOS del planner legacy certificado:
``E:\\IA\\VIDEO\\local_prompt_planner\\local_planner.py`` (QUALITY_PREPROMPTS).
Aqui solo se catalogan; aplicarlos al prompt es responsabilidad de F2.

Los preprompts propios viven en ``<data_dir>/preprompts.json`` con la forma
``{"custom": {"<slug>": {"positive": "...", "negative": "..."}}}``; se escriben
de forma atomica (tmp + replace) creando el data_dir si falta, y nunca
sobrescriben los cuatro certificados.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from app.config import load_config
from app.engine import EngineError

FAMILY_PREPROMPTS: dict[str, dict[str, dict[str, str]]] = {
    "anima": {
        "anima_default": {
            "positive": "masterpiece, best quality, score_8",
            "negative": (
                "worst quality, low quality, score_1, score_2, score_3, artist name"
            ),
        },
        "glossy": {
            "positive": (
                "masterpiece, best quality, absurdres, highres, score_7, score_8, "
                "score_9"
            ),
            "negative": (
                "worst quality, low quality, score_1, score_2, score_3, blurry, "
                "jpeg artifacts, sepia, bad anatomy, bad hands, mutated hands, "
                "fused fingers, extra fingers, watermark, signature, logo"
            ),
        },
        "not_glossy": {
            "positive": "newest, good quality, score_6, score_5, highres",
            "negative": "low quality, score_1, score_2",
        },
        "ninguno": {"positive": "", "negative": ""},
    },
}

DEFAULT_FAMILY = "anima"
DEFAULT_PREPROMPT = "glossy"

CUSTOM_STORE_FILENAME = "preprompts.json"
CUSTOM_STORE_KEY = "custom"
CUSTOM_NAME_RE = re.compile(r"[a-z0-9_-]{2,32}")

_CERTIFIED_NAMES = frozenset(
    name for family in FAMILY_PREPROMPTS.values() for name in family
)


def _store_path() -> Path:
    """Ruta del almacen de propios derivada de ``config.load_config().data_dir``."""
    return load_config().data_dir / CUSTOM_STORE_FILENAME


def _entry(name: object, value: object) -> dict[str, str] | None:
    """Normaliza una entrada del almacen; None si el nombre o el contenido no son validos."""
    if not isinstance(name, str) or CUSTOM_NAME_RE.fullmatch(name) is None:
        return None
    if not isinstance(value, dict):
        return None
    positive = value.get("positive")
    if not isinstance(positive, str) or not positive.strip():
        return None
    negative = value.get("negative", "")
    if not isinstance(negative, str):
        negative = ""
    return {"positive": positive.strip(), "negative": negative.strip()}


def _load_custom(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Preprompts propios persistidos; ``{}`` si el fichero no existe.

    EngineError si el JSON es ilegible o no tiene la forma esperada. Las
    entradas invalidas se ignoran para no romper los certificados.
    """
    target = Path(path) if path is not None else _store_path()
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(
            f"preprompts propios ilegibles {target}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise EngineError(
            f"preprompts propios invalidos: se esperaba objeto JSON, "
            f"recibido {type(data).__name__}"
        )
    custom = data.get(CUSTOM_STORE_KEY, {})
    if not isinstance(custom, dict):
        raise EngineError("preprompts propios invalidos: 'custom' debe ser un objeto")
    loaded: dict[str, dict[str, str]] = {}
    for name, value in custom.items():
        entry = _entry(name, value)
        if entry is not None:
            loaded[name] = entry
    return loaded


def _write_custom(
    custom: dict[str, dict[str, str]], path: str | Path | None = None
) -> None:
    """Escritura atomica (tmp + replace) creando el directorio padre si falta."""
    target = Path(path) if path is not None else _store_path()
    payload = {CUSTOM_STORE_KEY: custom}
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, target)
    except OSError as exc:
        raise EngineError(f"no se pudo guardar {target}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)


def list_custom() -> dict[str, dict[str, str]]:
    """Copia de los preprompts propios ``{slug: {"positive", "negative"}}``."""
    return {name: dict(entry) for name, entry in _load_custom().items()}


def save_custom(name: str, positive: str, negative: str = "") -> str:
    """Guarda un preprompt propio y devuelve el slug.

    El nombre debe ser un slug ``[a-z0-9_-]{2,32}``, no puede coincidir con un
    certificado ni repetir uno propio (no se sobrescribe), y el positivo no
    puede estar vacio; EngineError si algo falla.
    """
    if not isinstance(name, str) or CUSTOM_NAME_RE.fullmatch(name.strip()) is None:
        raise EngineError(
            f"nombre de preprompt propio invalido: {name!r} (slug [a-z0-9_-]{{2,32}})"
        )
    slug = name.strip()
    if slug in _CERTIFIED_NAMES:
        raise EngineError(
            f"no se puede sobrescribir el preprompt certificado {slug!r}"
        )
    if not isinstance(positive, str) or not positive.strip():
        raise EngineError("preprompt propio: positivo requerido")
    if not isinstance(negative, str):
        raise EngineError(f"preprompt propio: negativo invalido: {negative!r}")
    custom = _load_custom()
    if slug in custom:
        raise EngineError(f"preprompt propio duplicado: {slug!r}")
    custom[slug] = {"positive": positive.strip(), "negative": negative.strip()}
    _write_custom(custom)
    return slug


def delete_custom(name: str) -> bool:
    """Borra un preprompt propio; False si no existe."""
    if not isinstance(name, str):
        return False
    slug = name.strip()
    custom = _load_custom()
    if slug not in custom:
        return False
    del custom[slug]
    _write_custom(custom)
    return True


def list_families() -> list[str]:
    """Nombres de familia registrados, ordenados."""
    return sorted(FAMILY_PREPROMPTS)


def list_preprompts(family: str) -> list[str]:
    """Nombres de preprompt de una familia: certificados y propios (sin duplicar).

    Los propios van al final, ordenados. EngineError si la familia no existe;
    un almacen de propios corrupto no rompe los certificados.
    """
    if not isinstance(family, str) or family not in FAMILY_PREPROMPTS:
        raise EngineError(f"familia de preprompts desconocida: {family!r}")
    names = sorted(FAMILY_PREPROMPTS[family])
    seen = set(names)
    try:
        custom = sorted(_load_custom())
    except EngineError:
        custom = []
    for name in custom:
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def get_preprompt(family: str, name: str) -> dict[str, str]:
    """Copia de {"positive": str, "negative": str}; el certificado gana al propio."""
    if not isinstance(family, str) or family not in FAMILY_PREPROMPTS:
        raise EngineError(f"familia de preprompts desconocida: {family!r}")
    preprompts = FAMILY_PREPROMPTS[family]
    if not isinstance(name, str):
        raise EngineError(f"preprompt desconocido {name!r} en familia {family!r}")
    if name in preprompts:
        return dict(preprompts[name])
    custom = _load_custom()
    if name in custom:
        return dict(custom[name])
    raise EngineError(f"preprompt desconocido {name!r} en familia {family!r}")


__all__ = [
    "CUSTOM_NAME_RE",
    "CUSTOM_STORE_FILENAME",
    "DEFAULT_FAMILY",
    "DEFAULT_PREPROMPT",
    "FAMILY_PREPROMPTS",
    "delete_custom",
    "get_preprompt",
    "list_custom",
    "list_families",
    "list_preprompts",
    "save_custom",
]
