"""Ruta de generación de vídeo (/api/video/generate).

Qué hace: gestiona la validación y encolado de jobs de vídeo para Wan y VideoDeltaNet H3.
Qué no hace: no realiza generación de imágenes fijas ni edición por inpaint.
Dependencias: app.video, app.h3_presets, app.motion, app.routes.image y el registro de jobs.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

from fastapi import APIRouter, Body, Request

from app import video as video_module
from app.config import APP_ROOT
from app.engine import EngineError
from app.h3_presets import (
    h3_aspect,
    h3_default_size,
    h3_frames_for_seconds,
    h3_template_path,
    is_vdn_installed,
    require_h3_seconds,
    resolve_h3_profile,
    resolve_h3_variant,
    validate_h3_profile_variant,
    validate_h3_size,
)
from app.motion import MOTION_NEGATIVE
from app.routes.image import _decode_image_b64, _write_input_png
from app.routes.jobs import _JOBS
from app.video import (
    ASPECTS,
    WAN_FLF_TEMPLATE_PATH,
    WAN_TEMPLATE_PATH,
    frames_for_seconds,
    resolve_wan_profile,
    vram_hint,
)
from app.video_presets import PRESET_MANUAL


from app import h3_presets as _h3_presets


def _is_vdn_installed(comfy_root: Any) -> bool:
    server = sys.modules.get("app.server")
    server_fn = getattr(server, "is_vdn_installed", None) if server is not None else None
    if callable(server_fn) and server_fn is not _h3_presets.is_vdn_installed:
        return server_fn(comfy_root)
    video_mod = sys.modules.get("app.routes.video")
    video_fn = getattr(video_mod, "is_vdn_installed", None) if video_mod is not None else None
    if callable(video_fn) and video_fn is not _h3_presets.is_vdn_installed:
        return video_fn(comfy_root)
    return _h3_presets.is_vdn_installed(comfy_root)



router = APIRouter()


@router.post("/api/video/generate")
async def api_video_generate(request: Request, payload: dict = Body(...)) -> Any:
    """Encola un video (M9-F1/M10-2a/M10-2c): mode i2v|flf2v, segundos y negativo.

    `engine` sigue siendo `wan|h3`; si falta la clave, default `wan` (el
    `mode` de Wan elige plantilla I2V o FLF2V y `seconds` fija los frames
    4n+1). Para Wan, `preset` (id o `"manual"`; desconocido => 400) y los
    overrides `sampler_name`/`scheduler`/`steps`/`shift` se resuelven con
    precedencia overrides > preset > certificado; el tamano efectivo sale
    del preset segun `aspect` y `vram_hint` lo refleja. En `engine=h3` el
    preset Wan no aplica (400 si llega uno real) y `profile` (ausente ->
    `referencia`), `variant` (ausente -> `turbo4`; `turbo8` usa LoRA de 8
    pasos), `sage` (bool; inserta el patch de KJNodes), `seconds`
    (5/8/10/12/15), `width`/`height` (múltiplo de 32, área <= 768x1344)
    eligen plantilla y grid 5+17n. La respuesta añade `frames` y
    `vram_hint` (tabla Wan; null en H3).
    """
    cfg = request.app.state.config
    st = request.app.state.store
    queue = request.app.state.queue

    if "engine" in payload:
        engine_kind = payload.get("engine")
    else:
        engine_kind = "h3" if payload.get("mode") == "ref2va" or payload.get("profile") == "ref2va" else "wan"
    if engine_kind not in ("wan", "h3"):
        raise EngineError("engine invalido; usar wan|h3")
    mode = payload.get("mode") or ("ref2va" if payload.get("profile") == "ref2va" else "i2v")
    if mode not in ("i2v", "flf2v", "ref2va", "v2v"):
        raise EngineError("mode invalido; usar i2v|flf2v|ref2va|v2v")
    if mode in ("ref2va", "v2v") and engine_kind != "h3":
        raise EngineError(f"{mode} solo es compatible con motor h3")
    aspect = payload.get("aspect") or "vertical"
    if aspect not in ASPECTS:
        raise EngineError("aspect invalido; usar vertical|horizontal")
    profile = None
    h3_profile = None
    h3_variant = None
    sage = False
    if engine_kind == "wan":
        profile = resolve_wan_profile(
            preset=payload.get("preset"),
            aspect=aspect,
            sampler_name=payload.get("sampler_name"),
            scheduler=payload.get("scheduler"),
            steps=payload.get("steps"),
            shift=payload.get("shift"),
        )
        seconds = payload.get("seconds")
        if seconds is None:
            seconds = 5
        if isinstance(seconds, bool):
            raise EngineError("seconds invalido; usar un numero entre 1 y 15")
        try:
            seconds = float(seconds)
        except (TypeError, ValueError) as exc:
            raise EngineError(
                "seconds invalido; usar un numero entre 1 y 15"
            ) from exc
        frames = frames_for_seconds(seconds)
        width, height = profile["width"], profile["height"]
        hint = vram_hint(frames, width, height)
    else:
        raw_preset = payload.get("preset")
        if isinstance(raw_preset, str):
            raw_preset = raw_preset.strip()
        if raw_preset not in (None, "", PRESET_MANUAL):
            raise EngineError("preset de video solo aplica a engine wan")
        req_profile = payload.get("profile") or ("ref2va" if mode in ("ref2va", "v2v") else None)
        h3_profile = resolve_h3_profile(req_profile)
        raw_variant = payload.get("variant")
        if h3_profile["id"] in ("vdn", "ref2va") and (
            raw_variant is None
            or (isinstance(raw_variant, str) and not raw_variant.strip())
        ):
            raw_variant = "vdn8"
        h3_variant = resolve_h3_variant(raw_variant, profile=h3_profile["id"])
        validate_h3_profile_variant(h3_profile["id"], h3_variant["id"])
        if h3_profile["id"] == "vdn" and not _is_vdn_installed(cfg.comfy_root):
            raise EngineError(
                "los pesos de VDN deben instalarse previamente en ComfyUI/models/vdn"
            )
        sage = payload.get("sage")
        if sage is None:
            sage = False
        if not isinstance(sage, bool):
            raise EngineError("sage invalido; usar booleano")
        raw_seconds = payload.get("seconds")
        if raw_seconds is None:
            raw_seconds = h3_profile["seconds_recomendados"][0]
        seconds = float(require_h3_seconds(raw_seconds))
        if mode in ("ref2va", "v2v") and seconds > 15:
            raise EngineError(
                f"El modo {mode.upper()} esta optimizado para clips de identidad continua <= 15 s (recomendado: 8 s)"
            )
        if seconds > 15 and video_module.find_ffmpeg() is None:
            raise EngineError(
                "El encadenado continuo de videos >15 s requiere ffmpeg en el PATH o en tools/ffmpeg/ffmpeg.exe"
            )
        frames = h3_frames_for_seconds(seconds)
        width = payload.get("width")
        height = payload.get("height")
        if width is None and height is None:
            width, height = h3_default_size(aspect)
        elif width is None or height is None:
            raise EngineError("h3: width y height deben ir juntos")
        width, height = validate_h3_size(width, height)
        aspect = h3_aspect(width, height)
        hint = None
    ref_images_b64 = payload.get("ref_images_b64") or []
    ref_video_b64 = payload.get("ref_video_b64") or payload.get("video_b64")
    if mode == "v2v":
        if not ref_video_b64:
            raise EngineError("v2v requiere un video de referencia (ref_video_b64)")
        first_raw = _decode_image_b64(payload.get("image_b64"), "image") if payload.get("image_b64") else None
        last_raw = None
    elif mode == "ref2va":
        if not ref_images_b64 and not payload.get("image_b64") and not ref_video_b64:
            raise EngineError("ref2va requiere al menos una imagen o video de referencia")
        first_raw = _decode_image_b64(payload.get("image_b64"), "image") if payload.get("image_b64") else None
        last_raw = _decode_image_b64(payload.get("last_image_b64"), "last_image") if payload.get("last_image_b64") else None
    else:
        first_raw = _decode_image_b64(payload.get("image_b64"), "image")
        last_raw = None
        if mode == "flf2v":
            last_raw = _decode_image_b64(payload.get("last_image_b64"), "last_image")
    if engine_kind == "wan":
        motion_positive = payload.get("motion_positive")
        if not isinstance(motion_positive, str) or not motion_positive.strip():
            raise EngineError("motion_positive requerido para wan")
        motion_positive = motion_positive.strip()
        prompt = str(payload.get("prompt") or "")
        motion_negative = payload.get("motion_negative")
        if motion_negative is not None and not isinstance(motion_negative, str):
            raise EngineError("motion_negative invalido")
        motion_negative = (
            motion_negative.strip()
            if isinstance(motion_negative, str) and motion_negative.strip()
            else MOTION_NEGATIVE
        )
    else:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise EngineError("prompt requerido para h3")
        prompt = prompt.strip()
        motion_positive = str(payload.get("motion_positive") or "")
        motion_negative = str(payload.get("motion_negative") or "")
    seed = payload.get("seed")
    if seed is None:
        seed = 42
    if isinstance(seed, bool):
        raise EngineError("seed invalido")
    try:
        seed = int(seed)
    except (TypeError, ValueError) as exc:
        raise EngineError("seed invalido") from exc
    input_dir = cfg.comfy_input_dir
    ref_image_names: list[str] = []
    if ref_images_b64:
        ref_batch_id = uuid.uuid4().hex
        for i, raw_b64 in enumerate(ref_images_b64):
            ref_bytes = _decode_image_b64(raw_b64, f"ref_{i}")
            ref_name = _write_input_png(
                input_dir, ref_bytes, filename=f"ref_{ref_batch_id}_{i}.png"
            )
            ref_image_names.append(ref_name)
    ref_video_name = None
    if ref_video_b64:
        ref_vid_bytes = _decode_image_b64(ref_video_b64, "ref_video")
        ref_vid_id = uuid.uuid4().hex
        ref_video_name = f"ref_vid_{ref_vid_id}.mp4"
        (input_dir / ref_video_name).write_bytes(ref_vid_bytes)
    image_name = _write_input_png(input_dir, first_raw) if first_raw is not None else None
    last_image_name = (
        _write_input_png(input_dir, last_raw) if last_raw is not None else None
    )
    if mode in ("ref2va", "v2v"):
        if not image_name and ref_image_names:
            image_name = ref_image_names[0]
        if not last_image_name and len(ref_image_names) > 1:
            last_image_name = ref_image_names[1]
    if engine_kind == "h3":
        if mode == "v2v":
            template = h3_template_path(resolve_h3_profile("ref2va"))
        elif h3_profile["id"] == "personalizado" and payload.get("encoder") == "32b":
            template = APP_ROOT / "workflows" / "h3_fl2va_vertical.api.json"
        elif h3_profile["id"] == "personalizado" and h3_variant["id"] == "vdn8":
            template = APP_ROOT / "workflows" / "h3_vdn_8step.api.json"
        else:
            template = h3_template_path(h3_profile)
    elif mode == "flf2v":
        template = WAN_FLF_TEMPLATE_PATH
    else:
        template = WAN_TEMPLATE_PATH
    profile_fields = (
        {
            field: profile[field]
            for field in ("sampler_name", "scheduler", "steps", "shift")
        }
        if profile is not None
        else {}
    )
    stored_params = {
        "engine": engine_kind,
        "mode": mode,
        "aspect": aspect,
        "seconds": seconds,
        "frames": frames,
        "seed": seed,
        "image": image_name,
        "last_image": last_image_name,
        "ref_images": ref_image_names,
        "ref_video": ref_video_name,
        "preset": PRESET_MANUAL if profile is None else profile["preset"],
        **profile_fields,
    }
    if h3_profile is not None:
        stored_params["profile"] = h3_profile["id"]
        stored_params["variant"] = h3_variant["id"]
        stored_params["sage"] = sage
        stored_params["width"] = width
        stored_params["height"] = height
        for opt_key in (
            "encoder",
            "lora_strength",
            "denoise",
            "sampler_name",
            "scheduler",
            "tile_size",
            "include_audio",
        ):
            if opt_key in payload:
                stored_params[opt_key] = payload[opt_key]
    gen_id = st.add(
        engine_kind,
        motion_positive if engine_kind == "wan" else prompt,
        motion_negative,
        stored_params,
        kind="video",
    )
    job = {
        "kind": "video",
        "gen_id": gen_id,
        "engine": engine_kind,
        "mode": mode,
        "template": str(template),
        "image_name": image_name,
        "last_image_name": last_image_name,
        "ref_image_names": ref_image_names,
        "ref_video_name": ref_video_name,
        "motion_positive": motion_positive,
        "motion_negative": motion_negative,
        "prompt": prompt,
        "aspect": aspect,
        "seconds": seconds,
        "frames": frames,
        "seed": seed,
        "preset": stored_params["preset"],
        **profile_fields,
    }
    if h3_profile is not None:
        job["profile"] = h3_profile["id"]
        job["variant"] = h3_variant["id"]
        job["sage"] = sage
        job["width"] = width
        job["height"] = height
        for opt_key in (
            "encoder",
            "lora_strength",
            "denoise",
            "sampler_name",
            "scheduler",
            "tile_size",
            "include_audio",
        ):
            if opt_key in payload:
                job[opt_key] = payload[opt_key]
    _JOBS[gen_id] = {
        "prompt_id": None,
        "tracker": None,
        "status": "queued",
        "engine": None,
        "kind": "video",
    }
    job_id = queue.submit(job)
    request.app.state.jobs[job_id] = job
    return {"job_id": job_id, "frames": frames, "vram_hint": hint}
