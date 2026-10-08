"""Rutas de tags, rasgos OC y preprompts (/api/preprompts, /api/traits, /api/tags).

Qué hace: gestiona el catálogo de tags danbooru/e621, tags custom, rasgos OC y preprompts.
Qué no hace: no compone el prompt final de generación ni ejecuta inferencia.
Dependencias: app.tags, app.oc_traits y app.preprompts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.engine import EngineError
from app.oc_traits import list_traits
from app.preprompts import (
    DEFAULT_FAMILY,
    DEFAULT_PREPROMPT,
    delete_custom,
    list_custom,
    list_preprompts,
    save_custom,
)
from app.tags import (
    add_custom_tag,
    by_group,
    delete_custom_tag,
    list_custom_tags,
    list_groups,
    search,
)

TAGS_UNFILTERED_LIMIT = 200


def _clamp_tags_limit(limit: int) -> int:
    """Clamp del limit de `/api/tags` a 1..200."""
    return max(1, min(int(limit), TAGS_UNFILTERED_LIMIT))


router = APIRouter()


@router.get("/api/preprompts")
async def api_preprompts(family: str = DEFAULT_FAMILY) -> dict:
    names = list_preprompts(family)
    try:
        custom = sorted(list_custom())
    except EngineError:
        custom = []
    return {
        "family": family,
        "names": names,
        "custom": custom,
        "default": DEFAULT_PREPROMPT,
    }


@router.post("/api/preprompts/custom")
async def api_preprompt_custom_add(payload: dict = Body(...)) -> dict:
    negative = payload.get("negative")
    name = save_custom(
        payload.get("name"),
        payload.get("positive"),
        "" if negative is None else negative,
    )
    return {"name": name}


@router.delete("/api/preprompts/custom/{name}")
async def api_preprompt_custom_delete(name: str) -> Any:
    if not delete_custom(name):
        return JSONResponse(
            status_code=404, content={"error": "preprompt propio desconocido"}
        )
    return {"deleted": True}


@router.get("/api/traits")
async def api_traits() -> dict:
    return list_traits()


@router.get("/api/tags/groups")
async def api_tags_groups() -> dict:
    return {"groups": list_groups()}


@router.get("/api/tags")
async def api_tags(
    group: str | None = None,
    q: str | None = None,
    limit: int = TAGS_UNFILTERED_LIMIT,
) -> dict:
    limit = _clamp_tags_limit(limit)
    if group:
        items = by_group(group)
        if q:
            needle = q.strip().lower()
            items = [
                item
                for item in items
                if needle in item["tag"].lower() or needle in item["label"].lower()
            ]
    else:
        items = search(q if q is not None else "", limit=limit)
    return {"items": items[:limit]}


@router.get("/api/tags/custom")
async def api_tags_custom_list() -> list[dict]:
    return list_custom_tags()


@router.post("/api/tags/custom")
async def api_tags_custom_add(payload: dict = Body(...)) -> Any:
    name = payload.get("name") if isinstance(payload, dict) else None
    if not isinstance(name, str) or not name.strip():
        return JSONResponse(
            status_code=400, content={"error": "nombre de tag requerido y no vacio"}
        )
    category = payload.get("category") or "general"
    count = payload.get("count", 100)
    try:
        created = add_custom_tag(name=name, category=category, count=count)
    except EngineError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"ok": True, "tag": created}


@router.delete("/api/tags/custom/{name}")
async def api_tags_custom_delete(name: str) -> Any:
    if not name or not name.strip():
        return JSONResponse(
            status_code=400, content={"error": "nombre de tag requerido"}
        )
    deleted = delete_custom_tag(name)
    if not deleted:
        return JSONResponse(
            status_code=404, content={"error": "tag personalizada no encontrada"}
        )
    return {"ok": True, "name": name}
