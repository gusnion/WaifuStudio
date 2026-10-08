"""Rutas del sistema y UI web (/, /health, /api/system/*).

Qué hace: sirve la plantilla principal HTML de la interfaz, diagnóstico y healthcheck.
Qué no hace: no procesa generación de medios ni lógica de catálogos.
Dependencias: Jinja2Templates, app.config.EngineConfig y app.health.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import APP_ROOT

TEMPLATES_DIR = APP_ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Any:
    return templates.TemplateResponse(request, "index.html", {"title": "WAIFU"})
