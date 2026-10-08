"""Rutas de personajes / OC Maker (/api/characters).

Qué hace: gestiona creación, edición, perfiles, referencias, sheets y entrenamiento de OCs.
Qué no hace: no ejecuta directamente el entrenamiento de LoRA ni tareas de inferencia.
Dependencias: app.characters.CharacterStore, app.sheet y app.trainer.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app import trainer
from app.characters import is_sheet
from app.config import EngineConfig
from app.engine import EngineError
from app.preprompts import DEFAULT_PREPROMPT
from app.routes.jobs import _JOBS
from app.sheet import make_sheet
from app.store import Store
from app.vision import WD14_THRESHOLD, VisionService


def run_training_job(
    job: dict, *, config: EngineConfig, store: Store, vision: VisionService | None = None
) -> None:
    """Ejecuta un job de entrenamiento: trainer -> lora -> registry -> store.

    Si ``auto_tags`` (default True) y hay ``vision`` con WD14 instalado, el
    dataset se auto-captiona con ``vision.tagger_for(tag_threshold)``; el
    progreso del tagging queda en ``job["progress"]`` (node="tags"). No
    propaga errores: el fallo se guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    try:
        tagger = None
        if job.get("auto_tags", True) and vision is not None and vision.wd14_installed():
            tagger = vision.tagger_for(job.get("tag_threshold"))

        def progress(step: int, total: int) -> None:
            job["progress"] = {
                "step": step,
                "total": total,
                "percent": (100.0 * step / total if total else 0.0),
                "node": "tags",
                "state": "running",
            }

        result = trainer.train_character(
            job["char"],
            job["gen_ids"],
            store=store,
            config=config,
            trigger=job.get("trigger"),
            rank=job.get("rank", 16),
            epochs=job.get("epochs", 10),
            tagger=tagger,
            tag_threshold=job.get("tag_threshold"),
            progress=progress,
        )
        outputs = [result["lora_path"]]
        store.update(gen_id, status="done", outputs=outputs, kind="train")
        job["outputs"] = outputs
        job["result"] = result
        job["error"] = None
    except Exception as exc:
        job["outputs"] = []
        job["error"] = str(exc)
        try:
            store.update(gen_id, status="error", error=str(exc), kind="train")
        except EngineError:
            pass


router = APIRouter()


@router.get("/api/characters")
async def api_characters(request: Request) -> list[dict]:
    chars = request.app.state.characters
    return chars.list()


@router.post("/api/characters")
async def api_character_add(request: Request, payload: dict = Body(...)) -> Any:
    chars = request.app.state.characters
    char_id = chars.add(
        payload.get("name"),
        payload.get("tags") if payload.get("tags") is not None else [],
        preprompt=payload.get("preprompt") or DEFAULT_PREPROMPT,
        rating=payload.get("rating") or "sfw",
        notes=payload.get("notes") or "",
        extras=payload.get("extras"),
    )
    return {"id": char_id}


@router.get("/api/characters/{char_id}")
async def api_character_get(char_id: int, request: Request) -> Any:
    chars = request.app.state.characters
    row = chars.get(char_id)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    return row


@router.get("/api/characters/{char_id}/profile")
async def api_character_profile(char_id: int, request: Request, mode: str = "auto") -> Any:
    """Perfil del OC (M9-B3): trigger/rasgos, extras y LoRA oc-<id>."""
    chars = request.app.state.characters
    if chars.get(char_id) is None:
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    return chars.profile(char_id, mode)


@router.put("/api/characters/{char_id}")
async def api_character_update(
    char_id: int, request: Request, payload: dict = Body(...)
) -> Any:
    chars = request.app.state.characters
    if chars.get(char_id) is None:
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    fields = {
        key: payload[key]
        for key in ("name", "tags", "extras", "preprompt", "rating", "notes")
        if key in payload
    }
    chars.update(char_id, **fields)
    return chars.get(char_id)


@router.delete("/api/characters/{char_id}")
async def api_character_delete(char_id: int, request: Request) -> Any:
    chars = request.app.state.characters
    if not chars.delete(char_id):
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    return {"deleted": True}


@router.post("/api/characters/{char_id}/refs")
async def api_character_ref_add(
    char_id: int, request: Request, payload: dict = Body(...)
) -> Any:
    chars = request.app.state.characters
    st = request.app.state.store
    cfg = request.app.state.config
    if chars.get(char_id) is None:
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    gen_id = payload.get("gen_id")
    if isinstance(gen_id, bool) or not isinstance(gen_id, int):
        raise EngineError("gen_id requerido")
    row = st.get(gen_id)
    if row is None:
        return JSONResponse(
            status_code=404, content={"error": "generacion desconocida"}
        )
    outputs = row.get("outputs") or []
    first = outputs[0] if outputs else None
    name = first.get("name") if isinstance(first, dict) else first
    if not isinstance(name, str) or not name.strip():
        return JSONResponse(
            status_code=404, content={"error": "la generacion no tiene salidas"}
        )
    src = cfg.data_dir / "gallery" / str(gen_id) / name
    if not src.is_file():
        return JSONResponse(
            status_code=404, content={"error": "archivo de la generacion no encontrado"}
        )
    return {"relpath": chars.add_ref(char_id, src)}


@router.get("/api/characters/{char_id}/refs")
async def api_character_refs(char_id: int, request: Request) -> Any:
    chars = request.app.state.characters
    if chars.get(char_id) is None:
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    items = []
    for ref in chars.refs(char_id):
        item = dict(ref)
        item["url"] = f"/media/characters/{char_id}/{Path(ref['relpath']).name}"
        item["is_sheet"] = is_sheet(ref["relpath"])
        items.append(item)
    return items


@router.post("/api/characters/{char_id}/sheet")
async def api_character_sheet(
    char_id: int, request: Request, payload: dict | None = Body(default=None)
) -> Any:
    chars = request.app.state.characters
    if chars.get(char_id) is None:
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    refs = chars.refs(char_id)
    ref_ids = payload.get("ref_ids") if isinstance(payload, dict) else None
    if ref_ids is not None:
        if not isinstance(ref_ids, list) or any(
            isinstance(ref_id, bool) or not isinstance(ref_id, int)
            for ref_id in ref_ids
        ):
            raise EngineError("ref_ids invalido; usar lista de enteros")
        wanted = set(ref_ids)
        refs = [ref for ref in refs if ref["id"] in wanted]
    if len(refs) < 2:
        return JSONResponse(
            status_code=400,
            content={"error": "se necesitan al menos 2 referencias para la hoja"},
        )
    refs_root = Path(chars.refs_root)
    sheet_path = refs_root / str(char_id) / f"sheet_{uuid.uuid4().hex}.png"
    try:
        make_sheet([refs_root / ref["relpath"] for ref in refs], sheet_path)
    except Exception:
        sheet_path.unlink(missing_ok=True)
        raise
    relpath = chars.add_ref(char_id, sheet_path, name=sheet_path.name)
    return {
        "relpath": relpath,
        "url": f"/media/characters/{char_id}/{Path(relpath).name}",
    }


@router.delete("/api/characters/{char_id}/refs/{ref_id}")
async def api_character_ref_delete(char_id: int, ref_id: int, request: Request) -> Any:
    chars = request.app.state.characters
    if chars.get(char_id) is None:
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    if not chars.remove_ref(char_id, ref_id):
        return JSONResponse(
            status_code=404, content={"error": "referencia desconocida"}
        )
    return {"deleted": True}


@router.post("/api/characters/{char_id}/train")
async def api_character_train(
    char_id: int, request: Request, payload: dict = Body(...)
) -> Any:
    """Valida y encola un job `kind="train"` para el OC (M9-E1)."""
    chars = request.app.state.characters
    st = request.app.state.store
    queue = request.app.state.queue
    row = chars.get(char_id)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "OC desconocido"})
    gen_ids = payload.get("gen_ids")
    if not isinstance(gen_ids, list):
        raise EngineError("gen_ids requerido (lista de enteros)")
    if any(
        isinstance(gen_id, bool) or not isinstance(gen_id, int)
        for gen_id in gen_ids
    ):
        raise EngineError("gen_ids invalido; usar lista de enteros")
    if not trainer.MIN_IMAGES <= len(gen_ids) <= trainer.MAX_IMAGES:
        raise EngineError(
            f"se necesitan entre {trainer.MIN_IMAGES} y {trainer.MAX_IMAGES} "
            f"imagenes para entrenar: {len(gen_ids)}"
        )
    rank = payload.get("rank", 16)
    if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
        raise EngineError(f"rank invalido: {rank!r}")
    epochs = payload.get("epochs", 10)
    if isinstance(epochs, bool) or not isinstance(epochs, int) or epochs <= 0:
        raise EngineError(f"epochs invalido: {epochs!r}")
    trigger = payload.get("trigger")
    if trigger is not None:
        if not isinstance(trigger, str) or not trigger.strip():
            raise EngineError(f"trigger invalido: {trigger!r}")
        trigger = trigger.strip()
    auto_tags = payload.get("auto_tags", True)
    if not isinstance(auto_tags, bool):
        raise EngineError(f"auto_tags invalido: {auto_tags!r}")
    tag_threshold = trainer._require_threshold(
        payload.get("tag_threshold", WD14_THRESHOLD)
    )
    gen_id = st.add(
        f"oc-{char_id}",
        trigger or row["name"],
        "",
        {
            "character_id": char_id,
            "gen_ids": list(gen_ids),
            "rank": rank,
            "epochs": epochs,
            "trigger": trigger,
            "auto_tags": auto_tags,
            "tag_threshold": tag_threshold,
        },
        kind="train",
    )
    job = {
        "kind": "train",
        "gen_id": gen_id,
        "char": row,
        "character_id": char_id,
        "gen_ids": list(gen_ids),
        "rank": rank,
        "epochs": epochs,
        "trigger": trigger,
        "auto_tags": auto_tags,
        "tag_threshold": tag_threshold,
    }
    _JOBS[gen_id] = {
        "prompt_id": None,
        "tracker": None,
        "status": "queued",
        "engine": None,
        "kind": "train",
    }
    job_id = queue.submit(job)
    request.app.state.jobs[job_id] = job
    return {"job_id": job_id}
