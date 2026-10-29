"""Ruta de generación de vídeo (/api/video/generate).

Qué hace: gestiona la validación y encolado de jobs de vídeo para Wan y VideoDeltaNet H3.
Qué no hace: no realiza generación de imágenes fijas ni edición por inpaint.
Dependencias: app.video, app.h3_presets, app.motion, app.routes.image y el registro de jobs.
"""

from __future__ import annotations

import json
from pathlib import Path
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
    WAN_AIO_TEMPLATE_PATH,
    WAN_FLF_TEMPLATE_PATH,
    WAN_MODEL_DUAL,
    WAN_MODEL_NSFW_AIO,
    WAN_MODELS,
    WAN_TEMPLATE_PATH,
    frames_for_seconds,
    resolve_wan_profile,
    vram_hint,
)
from app.video_presets import PRESET_MANUAL


from app import h3_presets as _h3_presets

VIDEO_ENGINES_PATH = APP_ROOT / "registry" / "video_engines.json"
_VIDEO_ENGINES_CACHE: dict[str, Any] | None = None


def get_video_engines() -> dict[str, Any]:
    global _VIDEO_ENGINES_CACHE
    if _VIDEO_ENGINES_CACHE is not None:
        return _VIDEO_ENGINES_CACHE
    if not VIDEO_ENGINES_PATH.exists():
        raise EngineError(f"registro no encontrado: {VIDEO_ENGINES_PATH}")
    try:
        data = json.loads(VIDEO_ENGINES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EngineError(f"registro ilegible: {VIDEO_ENGINES_PATH}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("engines"), dict):
        raise EngineError(f"registro invalido: {VIDEO_ENGINES_PATH}")
    _VIDEO_ENGINES_CACHE = data["engines"]
    return _VIDEO_ENGINES_CACHE


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



def _resolve_gen_image_bytes(
    st: Any, cfg: Any, raw_gen_id: Any, label: str
) -> tuple[int, bytes]:
    if isinstance(raw_gen_id, bool) or not isinstance(raw_gen_id, (int, str)):
        raise EngineError(f"{label}: id invalido")
    try:
        gid = int(raw_gen_id)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"{label}: id invalido") from exc
    if gid <= 0:
        raise EngineError(f"{label}: id invalido")
    row = st.get(gid)
    if row is None:
        raise EngineError(f"{label}: generacion desconocida")
    file_name = ""
    for output in row.get("outputs") or []:
        candidate = output.get("name") if isinstance(output, dict) else output
        if isinstance(candidate, str) and candidate.strip():
            file_name = candidate.strip()
            break
    gallery_root = (cfg.data_dir / "gallery" / str(gid)).resolve()
    if not file_name and gallery_root.is_dir():
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            matches = sorted(gallery_root.glob(f"*{ext}"))
            if matches:
                file_name = matches[0].name
                break
    if not file_name:
        raise EngineError(f"{label}: la generacion no tiene salidas")
    source = (gallery_root / file_name).resolve()
    if not source.is_relative_to(gallery_root) or not source.is_file():
        raise EngineError(f"{label}: archivo no encontrado")
    raw = source.read_bytes()
    if not raw:
        raise EngineError(f"{label}: imagen vacia")
    return gid, raw


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
        engine_kind = (
            "h3"
            if payload.get("mode") in ("ref2va", "v2v")
            or payload.get("profile") == "ref2va"
            else "wan"
        )
    engines = get_video_engines()
    if not isinstance(engine_kind, str) or engine_kind not in engines:
        raise EngineError(f"motor desconocido: {engine_kind!r}")
    wan_model = payload.get("wan_model") or WAN_MODEL_DUAL
    if not isinstance(wan_model, str) or wan_model not in WAN_MODELS:
        raise EngineError("wan_model invalido; usar dual|nsfw_aio")
    if engine_kind == "h3" and wan_model != WAN_MODEL_DUAL:
        raise EngineError("wan_model solo aplica a engine wan")
    mode = payload.get("mode") or ("ref2va" if payload.get("profile") == "ref2va" else "i2v")
    if mode not in ("i2v", "flf2v", "ref2va", "v2v"):
        raise EngineError("mode invalido; usar i2v|flf2v|ref2va|v2v")
    if mode in ("ref2va", "v2v") and engine_kind != "h3":
        raise EngineError(f"{mode} solo es compatible con motor h3")
    if wan_model == WAN_MODEL_NSFW_AIO and mode not in ("i2v", "flf2v"):
        raise EngineError("wan AIO v10 solo admite i2v|flf2v en esta integracion")
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
            width=payload.get("width"),
            height=payload.get("height"),
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
        if mode in ("ref2va", "v2v"):
            effective_profile = "ref2va"
            effective_variant = "vdn8"
        else:
            effective_profile = payload.get("profile")
            effective_variant = payload.get("variant")
        h3_profile = resolve_h3_profile(effective_profile)
        if h3_profile["id"] in ("vdn", "ref2va") and (
            effective_variant is None
            or (isinstance(effective_variant, str) and not effective_variant.strip())
        ):
            effective_variant = "vdn8"
        h3_variant = resolve_h3_variant(effective_variant, profile=h3_profile["id"])
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
    end_gen_id = None
    if mode == "v2v":
        if not ref_video_b64:
            raise EngineError("v2v requiere un video de referencia (ref_video_b64)")
        first_raw = _decode_image_b64(payload.get("image_b64"), "image") if payload.get("image_b64") else None
        last_raw = None
    elif mode == "ref2va":
        if not ref_images_b64 and not payload.get("image_b64") and not ref_video_b64:
            raise EngineError("ref2va requiere al menos una imagen o video de referencia")
        first_raw = _decode_image_b64(payload.get("image_b64"), "image") if payload.get("image_b64") else None
        if payload.get("end_image_b64"):
            last_raw = _decode_image_b64(payload.get("end_image_b64"), "end_image")
        elif payload.get("last_image_b64"):
            last_raw = _decode_image_b64(payload.get("last_image_b64"), "last_image")
        elif payload.get("end_gen_id") is not None:
            end_gen_id, last_raw = _resolve_gen_image_bytes(
                st, cfg, payload.get("end_gen_id"), "end_gen_id"
            )
        else:
            last_raw = None
    else:
        if payload.get("image_b64") is not None or payload.get("gen_id") is None:
            first_raw = _decode_image_b64(payload.get("image_b64"), "image")
        else:
            _, first_raw = _resolve_gen_image_bytes(
                st, cfg, payload.get("gen_id"), "gen_id"
            )
        last_raw = None
        if mode == "flf2v":
            if "end_image_b64" in payload and payload.get("end_image_b64") is not None:
                last_raw = _decode_image_b64(payload.get("end_image_b64"), "end_image")
            elif "last_image_b64" in payload and payload.get("last_image_b64") is not None:
                last_raw = _decode_image_b64(payload.get("last_image_b64"), "last_image")
            elif payload.get("end_gen_id") is not None:
                end_gen_id, last_raw = _resolve_gen_image_bytes(
                    st, cfg, payload.get("end_gen_id"), "end_gen_id"
                )
            else:
                last_raw = _decode_image_b64(None, "last_image")
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
        input_dir.mkdir(parents=True, exist_ok=True)
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
        if mode in ("ref2va", "v2v"):
            template = h3_template_path(resolve_h3_profile("ref2va"))
        elif h3_profile["id"] == "personalizado" and payload.get("encoder") == "32b":
            template = APP_ROOT / "workflows" / "h3_fl2va_vertical.api.json"
        elif h3_profile["id"] == "personalizado" and h3_variant["id"] == "vdn8":
            template = APP_ROOT / "workflows" / "h3_vdn_8step.api.json"
        else:
            template = h3_template_path(h3_profile)
    elif mode == "flf2v":
        template = WAN_FLF_TEMPLATE_PATH
    elif wan_model == WAN_MODEL_NSFW_AIO:
        template = WAN_AIO_TEMPLATE_PATH
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
    if end_gen_id is not None:
        stored_params["end_gen_id"] = end_gen_id
    if engine_kind == "wan":
        stored_params["width"] = width
        stored_params["height"] = height
        stored_params["wan_model"] = wan_model
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
    if end_gen_id is not None:
        job["end_gen_id"] = end_gen_id
    if engine_kind == "wan":
        job["width"] = width
        job["height"] = height
        job["wan_model"] = wan_model
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
