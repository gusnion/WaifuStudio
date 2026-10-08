"""Rutas de jobs y estado de ejecución (/api/jobs).

Qué hace: gestiona la consulta de progreso/estado y la cancelación de jobs activos.
Qué no hace: no crea nuevos trabajos ni orquesta flujos de inferencia.
Dependencias: app.jobs.JobQueue, app.store.Store y el registro en memoria _JOBS.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import EngineConfig
from app.engine import EngineError

PROGRESS_KEYS = ("step", "total", "percent", "node", "state")
MEDIA_URL = "/media/{gen_id}/{name}"

_JOBS: dict[int, dict] = {}


def _progress_ws_url(config: EngineConfig) -> str:
    """Deriva la URL WS del engine desde `comfy_url` (http->ws, +/ws)."""
    base = str(config.comfy_url).rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return f"{base}/ws"


def _empty_progress() -> dict:
    """Payload de progreso sin tracker: todas las claves a null."""
    return {key: None for key in PROGRESS_KEYS}


router = APIRouter()


@router.get("/api/jobs/{job_id}")
async def api_job(job_id: str, request: Request) -> Any:
    queue = request.app.state.queue
    try:
        status = queue.status(job_id)
    except EngineError:
        return JSONResponse(status_code=404, content={"error": "job desconocido"})
    job = request.app.state.jobs.get(job_id) or {}
    if status == "done" and job.get("error"):
        status = "error"
    record = _JOBS.get(job.get("gen_id"))
    if record is not None and record.get("status") == "cancelled":
        status = "cancelled"
    tracker = record.get("tracker") if record else None
    if tracker is not None:
        snapshot = tracker.snapshot()
        progress = {
            "step": snapshot.get("step"),
            "total": snapshot.get("total"),
            "percent": tracker.percent(),
            "node": snapshot.get("node"),
            "state": snapshot.get("state"),
        }
    elif isinstance(job.get("progress"), dict):
        snapshot = job["progress"]
        progress = {key: snapshot.get(key) for key in PROGRESS_KEYS}
    else:
        progress = _empty_progress()
    gen_id = job.get("gen_id")
    outputs = [
        {"name": name, "url": MEDIA_URL.format(gen_id=gen_id, name=name)}
        for name in (job.get("outputs") or [])
    ]
    return {
        "status": status,
        "outputs": outputs,
        "error": job.get("error"),
        "progress": progress,
        "params": job.get("params") or {},
        "prompt": job.get("prompt"),
        "negative": job.get("negative"),
    }


@router.post("/api/jobs/{job_id}/cancel")
async def api_job_cancel(job_id: str, request: Request) -> Any:
    """Cancela un job (imagen o video); los registros de `_JOBS` viven en memoria.

    Misma semántica que imagen (M9-F1): `queued` borra del engine con
    `delete_queued`, `running` interrumpe; el train sigue devolviendo 409.
    """
    queue = request.app.state.queue
    try:
        queue_status = queue.status(job_id)
    except EngineError:
        return JSONResponse(status_code=404, content={"error": "job desconocido"})
    job = request.app.state.jobs.get(job_id) or {}
    gen_id = job.get("gen_id")
    record = _JOBS.get(gen_id)
    row = request.app.state.store.get(gen_id) if gen_id is not None else None
    kinds = (
        job.get("kind"),
        record.get("kind") if record else None,
        row.get("kind") if row else None,
    )
    if "train" in kinds:
        return JSONResponse(
            status_code=409,
            content={"error": "cancelar train: pendiente (M9-F)"},
        )
    status = queue_status
    if record is not None and record.get("status") in ("done", "error", "cancelled"):
        status = record["status"]
    if status not in ("queued", "running"):
        return JSONResponse(status_code=409, content={"error": "job no cancelable"})
    engine = record.get("engine") if record else None
    prompt_id = record.get("prompt_id") if record else None
    if status == "queued":
        if engine is not None:
            engine.delete_queued(prompt_id)
    elif engine is not None:
        engine.interrupt()
    if record is not None:
        record["status"] = "cancelled"
        tracker = record.get("tracker")
        if tracker is not None:
            tracker.is_cancelled = True
    if gen_id is not None:
        request.app.state.store.update(gen_id, status="cancelled")
    return {"status": "cancelled"}
