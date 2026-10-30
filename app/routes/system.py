"""Rutas del sistema y UI web (GET /).

Qué hace: sirve la plantilla principal HTML de la interfaz (templates/index.html).
Qué no hace: no procesa generación de medios ni lógica de catálogos (la salud del sistema opera vía CLI python -m app.health).
Dependencias: Jinja2Templates, app.config.APP_ROOT.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import APP_ROOT
from app.first_run import first_run_report

TEMPLATES_DIR = APP_ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


def _build_stamp() -> tuple[str, str]:
    """Hash corto del árbol servible y fecha del archivo más reciente."""
    digest = hashlib.sha1()
    latest = 0.0
    roots = (APP_ROOT / "app", APP_ROOT / "templates", APP_ROOT / "static")
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".html", ".js", ".css", ".json"}:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(f"{path.relative_to(APP_ROOT)}:{stat.st_mtime_ns}:{stat.st_size}".encode())
            latest = max(latest, stat.st_mtime)
    stamp = digest.hexdigest()[:10]
    when = datetime.fromtimestamp(latest, timezone.utc).isoformat(timespec="seconds") if latest else ""
    return stamp, when


BUILD_STAMP, BUILD_MTIME = _build_stamp()
STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "build": BUILD_STAMP,
        "build_mtime": BUILD_MTIME,
        "started_at": STARTED_AT,
        "pid": os.getpid(),
    }



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
    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "WAIFU", "build": BUILD_STAMP, "build_mtime": BUILD_MTIME},
    )
