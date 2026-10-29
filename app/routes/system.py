"""Rutas del sistema y UI web (GET /).

Qué hace: sirve la plantilla principal HTML de la interfaz (templates/index.html).
Qué no hace: no procesa generación de medios ni lógica de catálogos (la salud del sistema opera vía CLI python -m app.health).
Dependencias: Jinja2Templates, app.config.APP_ROOT.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import APP_ROOT
from app.first_run import first_run_report

TEMPLATES_DIR = APP_ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/api/skill")
async def get_skill() -> FileResponse:
    skill_file = APP_ROOT / "SKILL.md"
    if not skill_file.is_file():
        raise HTTPException(status_code=404, detail="SKILL.md no encontrado")
    return FileResponse(
        path=skill_file,
        media_type="text/markdown",
        filename="SKILL.md",
    )


@router.get("/api/first-run")
async def first_run(request: Request) -> dict:
    return first_run_report(request.app.state.config)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Any:
    return templates.TemplateResponse(request, "index.html", {"title": "WAIFU"})
