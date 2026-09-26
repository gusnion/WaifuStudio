"""Catalogo starter de tags Danbooru (M9-B1).

Carga ``registry/tags_danbooru.json`` (path desde APP_ROOT) y expone la consulta
por grupo y la busqueda por substring: starter; el dataset completo (3-8k) llega
en M10 con las descargas. Solo stdlib: sin red, GPU ni dependencias.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.config import APP_ROOT
from app.engine import EngineError

CATALOG_PATH = APP_ROOT / "registry" / "tags_danbooru.json"
MAX_SEARCH_LIMIT = 200
DEFAULT_SEARCH_LIMIT = 50
BULK_GROUPS = ("general_top", "character", "series", "artist")


def _load_catalog(path: Path = CATALOG_PATH) -> tuple[list[str], list[dict]]:
    """Lee y valida el JSON; EngineError con el detalle si esta corrupto."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"catalogo de tags ilegible en {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError(f"catalogo de tags invalido en {path}: se esperaba un objeto")
    groups = data.get("groups")
    tags = data.get("tags")
    if not isinstance(groups, list) or not all(
        isinstance(group, str) and group for group in groups
    ):
        raise EngineError(f"catalogo de tags sin 'groups' validos en {path}")
    if len(set(groups)) != len(groups):
        raise EngineError(f"catalogo de tags con grupos duplicados en {path}")
    if not isinstance(tags, list):
        raise EngineError(f"catalogo de tags sin 'tags' validos en {path}")
    seen: set[str] = set()
    entries: list[dict] = []
    for item in tags:
        if not isinstance(item, dict):
            raise EngineError(f"entrada de tag invalida en {path}: {item!r}")
        tag = item.get("tag")
        label = item.get("label")
        group = item.get("group")
        if not isinstance(tag, str) or not tag.strip():
            raise EngineError(f"tag invalido en {path}: {tag!r}")
        if not isinstance(label, str) or not label.strip():
            raise EngineError(f"label invalido para {tag!r} en {path}")
        if group not in groups:
            raise EngineError(f"grupo invalido para {tag!r} en {path}: {group!r}")
        folded = tag.strip().lower()
        if folded in seen:
            raise EngineError(f"tag duplicado en {path}: {tag!r}")
        seen.add(folded)
        rank = item.get("rank", 0)
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
            raise EngineError(f"rank invalido para {tag!r} en {path}: {rank!r}")
        entries.append(
            {"tag": tag.strip(), "label": label.strip(), "group": group, "rank": rank}
        )
    order = {group: index for index, group in enumerate(groups)}
    entries.sort(key=lambda entry: order[entry["group"]])
    return list(groups), entries


GROUPS, _ENTRIES = _load_catalog()
_BY_GROUP: dict[str, list[dict]] = {group: [] for group in GROUPS}
for _entry in _ENTRIES:
    _BY_GROUP[_entry["group"]].append(_entry)
_INDEX: dict[str, dict] = {entry["tag"].lower(): entry for entry in _ENTRIES}


def list_groups() -> list[str]:
    """Nombres de grupo en orden canonico."""
    return list(GROUPS)


def by_group(group: str) -> list[dict]:
    """Entradas de un grupo como copias; EngineError si el grupo no existe."""
    if group not in _BY_GROUP:
        raise EngineError(f"grupo de tags desconocido: {group!r}")
    return copy.deepcopy(_BY_GROUP[group])


def search(q: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict]:
    """Substring case-insensitive en tag/label, orden estable y limit 1..200."""
    if not isinstance(q, str):
        raise EngineError(f"consulta de tags invalida: {q!r}")
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"limit de tags invalido: {limit!r}") from exc
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    needle = q.strip().lower()
    matches = [
        entry
        for entry in _ENTRIES
        if needle in entry["tag"].lower() or needle in entry["label"].lower()
    ]
    return copy.deepcopy(matches[:limit])


def get(tag: str) -> dict | None:
    """Entrada por tag canonico (case-insensitive), o None si no existe."""
    if not isinstance(tag, str):
        return None
    entry = _INDEX.get(tag.strip().lower())
    return copy.deepcopy(entry) if entry is not None else None


def all_tags() -> list[dict]:
    """Todas las entradas (copias) en orden de grupo canonico."""
    return copy.deepcopy(_ENTRIES)


__all__ = [
    "BULK_GROUPS",
    "CATALOG_PATH",
    "GROUPS",
    "MAX_SEARCH_LIMIT",
    "all_tags",
    "by_group",
    "get",
    "list_groups",
    "search",
]
