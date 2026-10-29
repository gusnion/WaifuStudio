"""Rutas HTTP para el catalogo e indice de poses."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.engine import EngineError
from app.poses import download_pose_index, load_pose_index, load_pose_tags, pose_status

router = APIRouter()


@router.get("/api/poses/status")
async def api_poses_status(request: Request) -> dict[str, Any]:
    data_dir = request.app.state.config.data_dir
    return pose_status(data_dir)


@router.post("/api/poses/download")
async def api_poses_download(request: Request) -> Any:
    data_dir = request.app.state.config.data_dir
    try:
        target = download_pose_index(data_dir)
    except EngineError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"ok": True, "path": str(target)}


@router.get("/api/poses")
async def api_poses_list(request: Request) -> dict[str, Any]:
    data_dir = request.app.state.config.data_dir
    items = load_pose_index(data_dir)
    return {
        "items": items,
        "count": len(items),
    }


@router.get("/api/poses/tags")
async def api_poses_tags() -> dict[str, Any]:
    return load_pose_tags()
