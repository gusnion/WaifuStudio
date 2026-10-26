"""Rutas HTTP del gestor de addons."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.addons import import_addon, import_catalog, list_addons, set_addon_enabled
from app.engine import EngineError

router = APIRouter()


@router.get("/api/addons")
async def api_addons(request: Request) -> dict:
    return {"items": list_addons(request.app.state.config.data_dir)}


@router.post("/api/addons/import")
async def api_addon_import(request: Request) -> Any:
    raw = await request.body()
    try:
        addon = import_addon(request.app.state.config.data_dir, raw)
    except EngineError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"ok": True, "addon": addon}


@router.post("/api/addons/catalog")
async def api_addon_catalog(request: Request) -> Any:
    try:
        payload = await request.json()
        return import_catalog(request.app.state.config.data_dir, payload)
    except EngineError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@router.post("/api/addons/{addon_id}/enable")
async def api_addon_enable(request: Request, addon_id: str) -> Any:
    try:
        return set_addon_enabled(request.app.state.config.data_dir, addon_id, True)
    except EngineError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})


@router.post("/api/addons/{addon_id}/disable")
async def api_addon_disable(request: Request, addon_id: str) -> Any:
    try:
        return set_addon_enabled(request.app.state.config.data_dir, addon_id, False)
    except EngineError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})


@router.post("/api/addons/{addon_id}/rollback")
async def api_addon_rollback(request: Request, addon_id: str) -> Any:
    try:
        return set_addon_enabled(request.app.state.config.data_dir, addon_id, False)
    except EngineError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})


@router.get("/api/addons/{addon_id}")
async def api_addon(request: Request, addon_id: str) -> Any:
    items = list_addons(request.app.state.config.data_dir)
    found = next((item for item in items if item.get("id") == addon_id), None)
    if found is None:
        return JSONResponse(status_code=404, content={"error": "addon no instalado"})
    return found
