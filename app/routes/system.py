"""Rutas del sistema y UI web (GET /).

Qué hace: sirve la plantilla principal HTML de la interfaz (templates/index.html).
Qué no hace: no procesa generación de medios ni lógica de catálogos (la salud del sistema opera vía CLI python -m app.health).
Dependencias: Jinja2Templates, app.config.APP_ROOT.
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
