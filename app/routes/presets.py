"""Rutas de presets y metadatos de generación (/api/params, /api/formats, /api/video/*).

Qué hace: expone parámetros de muestreo, formatos de imagen, presets de video y perfiles H3.
Qué no hace: no ejecuta generación ni almacena configuraciones de usuario.
Dependencias: app.params, app.formats, app.video_presets y app.h3_presets.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.formats import DEFAULT_FORMAT, list_image_formats
from app.h3_presets import h3_catalog
from app.params import (
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    SAMPLER_NAMES,
    SCHEDULER_NAMES,
)
from app.video_presets import list_video_presets

router = APIRouter()


@router.get("/api/params")
async def api_params() -> dict:
    return {
        "samplers": list(SAMPLER_NAMES),
        "schedulers": list(SCHEDULER_NAMES),
        "default_sampler": DEFAULT_SAMPLER,
        "default_scheduler": DEFAULT_SCHEDULER,
    }


@router.get("/api/formats")
async def api_formats() -> dict:
    return {"formats": list_image_formats(), "default": DEFAULT_FORMAT}


@router.get("/api/video/presets")
async def api_video_presets() -> dict:
    """Presets de video Wan (M10-2a): id/label/note + tamano y perfil."""
    items = []
    for preset in list_video_presets():
        item = dict(preset)
        item["profile"] = {
            "sampler": preset["sampler"],
            "scheduler": preset["scheduler"],
            "steps": preset["steps"],
            "shift": preset["shift"],
        }
        items.append(item)
    return {"items": items, "presets": items}


@router.get("/api/video/h3_profiles")
async def api_video_h3_profiles(request: Request) -> dict:
    """Perfiles H3 (M10-2c-1): catalogo + variantes, segundos y resoluciones."""
    cfg = request.app.state.config
    catalog = h3_catalog(cfg.comfy_root)
    items = catalog["profiles"]
    return {
        "items": items,
        "profiles": items,
        "variants": catalog["variants"],
        "seconds": catalog["seconds"],
        "resolutions": catalog["resolutions"],
    }
