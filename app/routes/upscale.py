"""Rutas de escalado e interpolación de vídeo (/api/upscale/models, /api/upscale).

Qué hace: gestiona modelos de escalado, interpolación RIFE y encolado de jobs de upscale.
Qué no hace: no genera fotogramas base ni gestiona checkpoints de difusión.
Dependencias: app.upscale, app.routes.image y el registro de jobs.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.engine import EngineError
from app.routes.image import _decode_image_b64, _write_input_png
from app.routes.jobs import _JOBS
from app.upscale import (
    fps_ckpt,
    fps_multiplier,
    frame_interpolation,
    get_upscaler,
    list_upscalers,
    parse_fps,
    parse_passes,
    parse_sharpen,
)

router = APIRouter()


@router.get("/api/upscale/models")
async def api_upscale_models() -> dict:
    """Catalogo de upscalers (M10-2d U1/U2/U3): id/label/file/scale/note,
    kinds y la seccion ``frame_interpolation`` (ckpts RIFE + multipliers)."""
    items = list_upscalers()
    return {
        "items": items,
        "models": items,
        "kinds": ["image", "video", "fps"],
        "frame_interpolation": frame_interpolation(),
    }


@router.post("/api/upscale")
async def api_upscale(request: Request, payload: dict = Body(...)) -> Any:
    """Encola el escalado de una generacion de imagen (U1), de video (U2)
    o la interpolacion de fotogramas de un video (U3).

    Body: ``{source_gen, model, file?, kind?, passes?, sharpen?}`` con
    ``kind`` ``"image"`` (default) o ``"video"``. Para ``kind="image"`` se
    admite ``image_b64`` (data URI/base64 de un archivo local; exclusivo
    con ``source_gen``), ``passes`` 1|2 (default 1: ×2; 2: ×4 con dos
    ampliaciones encadenadas) y ``sharpen`` 0|1|2 (default 0: sin mejora
    de detalle; 1 suave y 2 fuerte con el nodo core ``ImageSharpen`` tras
    la ultima ampliacion). Para ``kind="fps"`` el body es
    ``{source_gen, ckpt?, multiplier, file?, fps_in?}``: valida que el
    origen sea un video, que ``ckpt`` este en la seccion
    ``frame_interpolation`` del catalogo y que ``multiplier`` sea 2|4.
    Copia el origen (o la imagen subida) a ``ComfyUI/input`` y encola un
    job ``kind="upscale"`` que produce una generacion nueva: imagen
    (``kind="image"``, ``params.task="upscale"``), video con audio del
    origen (``kind="video"``, ``params.task="upscale_video"``) o video
    interpolado (``kind="video"``, ``params.task="rife"``).
    """
    cfg = request.app.state.config
    st = request.app.state.store
    queue = request.app.state.queue

    source_kind = payload.get("kind")
    if source_kind is None:
        source_kind = "image"
    if source_kind == "image":
        label = "imagen"
        extensions = (".png", ".jpg", ".jpeg", ".webp")
    elif source_kind in ("video", "fps"):
        label = "video"
        extensions = (".mp4", ".webm")
    else:
        raise EngineError("kind invalido; usar image|video|fps")
    image_b64 = payload.get("image_b64")
    if image_b64 is not None and source_kind != "image":
        raise EngineError("image_b64 solo aplica a kind=image")
    raw_passes = payload.get("passes")
    if source_kind == "image":
        passes = parse_passes(raw_passes)
    elif raw_passes is not None and not (
        isinstance(raw_passes, int)
        and not isinstance(raw_passes, bool)
        and raw_passes == 1
    ):
        raise EngineError("passes solo aplica a imagen")
    raw_sharpen = payload.get("sharpen")
    if source_kind == "image":
        sharpen = parse_sharpen(raw_sharpen)
    elif raw_sharpen is not None and not (
        isinstance(raw_sharpen, int)
        and not isinstance(raw_sharpen, bool)
        and raw_sharpen == 0
    ):
        raise EngineError("sharpen solo aplica a imagen")
    if source_kind == "image" and image_b64 is not None:
        if payload.get("source_gen") is not None:
            raise EngineError(
                "source_gen y image_b64 son mutuamente excluyentes"
            )
        entry = get_upscaler(payload.get("model"))
        media_name = _write_input_png(
            cfg.comfy_root / "input", _decode_image_b64(image_b64, "image_b64")
        )
        params = {
            "task": "upscale",
            "source_gen": None,
            "source_file": None,
            "model": entry["id"],
            "scale": entry["scale"],
            "passes": passes,
            "sharpen": sharpen,
        }
        gen_id = st.add(
            "upscale", "upscale archivo local", "", params, kind="image"
        )
        job = {
            "kind": "upscale",
            "gen_id": gen_id,
            "source_gen": None,
            "source_file": None,
            "image_name": media_name,
            "model": entry["id"],
            "model_file": entry["file"],
            "scale": entry["scale"],
            "passes": passes,
            "sharpen": sharpen,
            "params": dict(params),
        }
        _JOBS[gen_id] = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
            "kind": "upscale",
        }
        job_id = queue.submit(job)
        request.app.state.jobs[job_id] = job
        return {"job_id": job_id}
    source_gen = payload.get("source_gen")
    if isinstance(source_gen, bool) or not isinstance(source_gen, int):
        if source_kind == "image":
            raise EngineError("source_gen o image_b64 requerido para imagen")
        raise EngineError("source_gen requerido (entero)")
    row = st.get(source_gen)
    if row is None:
        return JSONResponse(
            status_code=404, content={"error": "generacion origen desconocida"}
        )
    source_expected = "video" if source_kind == "fps" else source_kind
    if row.get("kind") != source_expected:
        raise EngineError(
            f"origen invalido; se requiere una generacion de {label}"
        )
    raw_file = payload.get("file")
    if raw_file is not None and (
        not isinstance(raw_file, str) or not raw_file.strip()
    ):
        raise EngineError("file invalido; usar un nombre de archivo")
    if isinstance(raw_file, str):
        file_name = raw_file.strip()
    else:
        file_name = ""
        for output in row.get("outputs") or []:
            candidate = output.get("name") if isinstance(output, dict) else output
            if isinstance(candidate, str) and candidate.strip():
                file_name = candidate.strip()
                break
        if not file_name:
            return JSONResponse(
                status_code=404,
                content={"error": "la generacion origen no tiene salidas"},
            )
    gallery_root = (cfg.data_dir / "gallery" / str(source_gen)).resolve()
    source = (gallery_root / file_name).resolve()
    if not source.is_relative_to(gallery_root):
        return JSONResponse(
            status_code=403, content={"error": "ruta fuera de la galeria"}
        )
    if source.suffix.lower() not in extensions or not source.is_file():
        return JSONResponse(
            status_code=404, content={"error": "archivo de origen no encontrado"}
        )
    entry = None
    ckpt = None
    multiplier = None
    fps_in = None
    fps_out = None
    if source_kind == "fps":
        ckpt = fps_ckpt(payload.get("ckpt"))
        multiplier = fps_multiplier(payload.get("multiplier"))
        fps_in = parse_fps(payload.get("fps_in"), "fps_in")
        fps_out = None if fps_in is None else fps_in * multiplier
    else:
        entry = get_upscaler(payload.get("model"))
    input_dir = cfg.comfy_input_dir
    input_dir.mkdir(parents=True, exist_ok=True)
    media_name = f"{uuid.uuid4().hex}{source.suffix.lower()}"
    (input_dir / media_name).write_bytes(source.read_bytes())
    if source_kind == "fps":
        params = {
            "task": "rife",
            "source_gen": source_gen,
            "source_file": file_name,
            "ckpt": ckpt,
            "multiplier": multiplier,
            "fps_in": fps_in,
            "fps_out": fps_out,
        }
        gen_id = st.add(
            "upscale",
            f"fps #{source_gen}/{file_name}",
            "",
            params,
            kind="video",
        )
        job = {
            "kind": "upscale",
            "task": "rife",
            "gen_id": gen_id,
            "source_gen": source_gen,
            "source_file": file_name,
            "video_name": media_name,
            "ckpt": ckpt,
            "ckpt_name": ckpt,
            "multiplier": multiplier,
            "fps_in": fps_in,
            "fps_out": fps_out,
            "params": dict(params),
        }
    elif source_kind == "video":
        params = {
            "task": "upscale_video",
            "source_gen": source_gen,
            "source_file": file_name,
            "model": entry["id"],
            "scale": entry["scale"],
            "fps": None,
        }
        gen_id = st.add(
            "upscale",
            f"upscale #{source_gen}/{file_name}",
            "",
            params,
            kind="video",
        )
        job = {
            "kind": "upscale",
            "task": "upscale_video",
            "gen_id": gen_id,
            "source_gen": source_gen,
            "source_file": file_name,
            "video_name": media_name,
            "model": entry["id"],
            "model_file": entry["file"],
            "scale": entry["scale"],
            "fps": None,
            "params": dict(params),
        }
    else:
        params = {
            "task": "upscale",
            "source_gen": source_gen,
            "source_file": file_name,
            "model": entry["id"],
            "scale": entry["scale"],
            "passes": passes,
            "sharpen": sharpen,
        }
        gen_id = st.add(
            "upscale",
            f"upscale #{source_gen}/{file_name}",
            "",
            params,
            kind="image",
        )
        job = {
            "kind": "upscale",
            "gen_id": gen_id,
            "source_gen": source_gen,
            "source_file": file_name,
            "image_name": media_name,
            "model": entry["id"],
            "model_file": entry["file"],
            "scale": entry["scale"],
            "passes": passes,
            "sharpen": sharpen,
            "params": dict(params),
        }
    _JOBS[gen_id] = {
        "prompt_id": None,
        "tracker": None,
        "status": "queued",
        "engine": None,
        "kind": "upscale",
    }
    job_id = queue.submit(job)
    request.app.state.jobs[job_id] = job
    return {"job_id": job_id}
