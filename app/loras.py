"""Biblioteca de LoRAs locales (M9-D1).

Carga y valida ``registry/loras.json`` (``{"version": 1, "loras": [...]}``):
registro ordenado, familias, consulta por id y normalizacion de selecciones de
la API. CPU, sin red, GPU ni dependencias; la ruta cuelga de ``APP_ROOT``.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import uuid
from pathlib import Path

from app.config import APP_ROOT
from app.engine import EngineError

REGISTRY_VERSION = 1
DEFAULT_PATH = APP_ROOT / "registry" / "loras.json"

_ID_RE = re.compile(r"[a-z0-9._-]+")
_REQUIRED_TEXT_FIELDS = ("id", "family", "file", "display_name", "source", "license")
_WEIGHT_MIN = 0.0
_WEIGHT_MAX = 2.0


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"campo obligatorio no vacio: {label} (recibido {value!r})")
    return value


def _weight(value: object, label: str) -> float:
    """Convierte a float en [0, 2]; EngineError si es bool, no numerico o no finito."""
    if isinstance(value, bool):
        raise EngineError(f"{label} invalido: {value!r}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"{label} invalido: {value!r}") from exc
    if not math.isfinite(result) or not _WEIGHT_MIN <= result <= _WEIGHT_MAX:
        raise EngineError(
            f"{label} fuera de [{_WEIGHT_MIN:g}, {_WEIGHT_MAX:g}]: {value!r}"
        )
    return result


def _entry_from_dict(data: object) -> dict:
    if not isinstance(data, dict):
        raise EngineError(
            f"entrada de lora invalida: se esperaba objeto JSON, "
            f"recibido {type(data).__name__}"
        )
    missing = [key for key in _REQUIRED_TEXT_FIELDS if key not in data]
    if missing:
        raise EngineError(f"entrada de lora sin campos: {', '.join(missing)}")
    for key in _REQUIRED_TEXT_FIELDS:
        _require_text(data.get(key), key)
    if _ID_RE.fullmatch(data["id"]) is None:
        raise EngineError(f"id fuera del slug [a-z0-9._-]+: {data['id']!r}")
    trigger = data.get("trigger", "")
    if not isinstance(trigger, str):
        raise EngineError(f"trigger debe ser str: {trigger!r}")
    notes = data.get("notes", "")
    if not isinstance(notes, str):
        raise EngineError(f"notes debe ser str: {notes!r}")
    default_weight = data.get("default_weight", 1.0)
    return {
        "id": data["id"],
        "family": data["family"],
        "file": data["file"],
        "display_name": data["display_name"],
        "trigger": trigger,
        "default_weight": _weight(
            default_weight, f"default_weight de {data['id']!r}"
        ),
        "source": data["source"],
        "license": data["license"],
        "notes": notes,
    }


def _payload(path: str | Path | None) -> dict:
    target = Path(path) if path is not None else DEFAULT_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(
            f"registro de loras ilegible {target}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise EngineError(
            f"registro de loras invalido: se esperaba objeto JSON, "
            f"recibido {type(data).__name__}"
        )
    version = data.get("version")
    if version != REGISTRY_VERSION:
        raise EngineError(
            f"version de registro no soportada: {version!r} "
            f"(esperada {REGISTRY_VERSION})"
        )
    loras = data.get("loras")
    if not isinstance(loras, list):
        raise EngineError("registro de loras invalido: falta la lista 'loras'")
    return data


def _canonical(data: object) -> dict:
    """Normaliza un payload de registro validando forma, entradas y ids unicos."""
    if not isinstance(data, dict):
        raise EngineError(
            f"registro de loras invalido: se esperaba objeto JSON, "
            f"recibido {type(data).__name__}"
        )
    version = data.get("version")
    if version != REGISTRY_VERSION:
        raise EngineError(
            f"version de registro no soportada: {version!r} "
            f"(esperada {REGISTRY_VERSION})"
        )
    loras = data.get("loras")
    if not isinstance(loras, list):
        raise EngineError("registro de loras invalido: falta la lista 'loras'")
    entries: list[dict] = []
    seen: set[str] = set()
    for item in loras:
        entry = _entry_from_dict(item)
        if entry["id"] in seen:
            raise EngineError(f"id duplicado en el registro: {entry['id']!r}")
        seen.add(entry["id"])
        entries.append(entry)
    canonical: dict = {"version": REGISTRY_VERSION, "loras": entries}
    comment = data.get("_comment")
    if isinstance(comment, str) and comment.strip():
        canonical["_comment"] = comment
    return canonical


def load_registry(path: str | Path | None = None) -> dict:
    """Registro canonico ``{"version": 1, "loras": [...]}`` con ids unicos.

    Conserva ``_comment`` si el JSON lo trae. EngineError si el fichero es
    ilegible, la version no es 1, falta ``loras`` o una entrada es invalida.
    """
    return _canonical(_payload(path))


def save_registry(payload: dict, *, path: str | Path | None = None) -> Path:
    """Valida y escribe el registro de forma atomica (tmp + replace).

    Conserva el orden de ``loras`` y ``_comment``; EngineError si el payload no
    es un registro valido o la escritura falla.
    """
    canonical = _canonical(payload)
    target = Path(path) if path is not None else DEFAULT_PATH
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, target)
    except OSError as exc:
        raise EngineError(
            f"no se pudo guardar el registro de loras {target}: {exc}"
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return target


def add_entry(entry: dict, *, path: str | Path | None = None) -> dict:
    """Valida ``entry``, la añade al final del registro y guarda (atomico).

    EngineError si la entrada es invalida o su id ya existe. Devuelve una copia
    de la entrada canonica guardada.
    """
    candidate = _entry_from_dict(entry)
    registry = load_registry(path)
    if any(item["id"] == candidate["id"] for item in registry["loras"]):
        raise EngineError(f"id duplicado en el registro: {candidate['id']!r}")
    registry["loras"].append(candidate)
    save_registry(registry, path=path)
    return copy.deepcopy(candidate)


def update_entry(
    loras_id: str, changes: dict, *, path: str | Path | None = None
) -> dict:
    """Aplica ``changes`` a la entrada ``loras_id`` y guarda (atomico).

    Los campos ausentes conservan su valor y las claves desconocidas se ignoran;
    el id no puede cambiar. EngineError si la entrada no existe, ``changes`` no
    es un objeto JSON o el resultado no es valido. Devuelve una copia de la
    entrada canonica guardada.
    """
    if not isinstance(changes, dict):
        raise EngineError(
            f"cambios invalidos: se esperaba objeto JSON, "
            f"recibido {type(changes).__name__}"
        )
    registry = load_registry(path)
    for position, item in enumerate(registry["loras"]):
        if item["id"] != loras_id:
            continue
        if "id" in changes and changes["id"] != loras_id:
            raise EngineError(f"id inmutable: {loras_id!r}")
        data = {
            key: changes[key] if key in changes else value
            for key, value in item.items()
        }
        candidate = _entry_from_dict(data)
        registry["loras"][position] = candidate
        save_registry(registry, path=path)
        return copy.deepcopy(candidate)
    raise EngineError(f"lora no registrado: {loras_id!r}")


def delete_entry(loras_id: str, *, path: str | Path | None = None) -> dict:
    """Elimina la entrada ``loras_id`` del registro y guarda (atomico).

    Solo toca ``registry/loras.json``: el fichero del modelo no se borra.
    EngineError si no existe. Devuelve una copia de la entrada eliminada.
    """
    registry = load_registry(path)
    for position, item in enumerate(registry["loras"]):
        if item["id"] == loras_id:
            removed = registry["loras"].pop(position)
            save_registry(registry, path=path)
            return copy.deepcopy(removed)
    raise EngineError(f"lora no registrado: {loras_id!r}")


def _entries(path: str | Path | None = None) -> list[dict]:
    return load_registry(path)["loras"]


def list_loras(
    family: str | None = None, *, path: str | Path | None = None
) -> list[dict]:
    """Entradas (copias) en orden del registro, filtradas por familia exacta."""
    entries = _entries(path)
    if family is not None:
        entries = [entry for entry in entries if entry["family"] == family]
    return copy.deepcopy(entries)


def families(*, path: str | Path | None = None) -> list[str]:
    """Familias presentes, en orden de aparicion del registro."""
    result: list[str] = []
    for entry in _entries(path):
        if entry["family"] not in result:
            result.append(entry["family"])
    return result


def get(loras_id: str, *, path: str | Path | None = None) -> dict:
    """Entrada (copia) con ese id; EngineError si no existe."""
    for entry in _entries(path):
        if entry["id"] == loras_id:
            return copy.deepcopy(entry)
    raise EngineError(f"lora no registrado: {loras_id!r}")


def validate_selection(
    selection: object, *, path: str | Path | None = None
) -> list[dict]:
    """Normaliza ``[{"id", "weight"?}]`` a ``[{"id", "file", "weight"}]``.

    Valida id existente y weight float en [0, 2] (default el del registro).
    EngineError si la seleccion no es lista o algun item es invalido.
    """
    entries = _entries(path)
    if not isinstance(selection, list):
        raise EngineError(
            f"seleccion de loras invalida: se esperaba lista, "
            f"recibido {type(selection).__name__}"
        )
    index = {entry["id"]: entry for entry in entries}
    normalized: list[dict] = []
    for position, item in enumerate(selection):
        if not isinstance(item, dict):
            raise EngineError(
                f"lora #{position}: entrada invalida (se esperaba objeto JSON)"
            )
        lora_id = item.get("id")
        if not isinstance(lora_id, str) or not lora_id.strip():
            raise EngineError(f"lora #{position}: id requerido")
        entry = index.get(lora_id)
        if entry is None:
            raise EngineError(f"lora no registrado: {lora_id!r}")
        weight = item.get("weight")
        if weight is None:
            weight = entry["default_weight"]
        else:
            weight = _weight(weight, f"lora {lora_id!r}: weight")
        normalized.append(
            {"id": entry["id"], "file": entry["file"], "weight": weight}
        )
    return normalized


__all__ = [
    "DEFAULT_PATH",
    "REGISTRY_VERSION",
    "add_entry",
    "delete_entry",
    "families",
    "get",
    "list_loras",
    "load_registry",
    "save_registry",
    "update_entry",
    "validate_selection",
]
