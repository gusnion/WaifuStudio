"""Rutas de manipulación de prompts, enriquecimiento con LLM y visión.

Qué hace: gestiona /api/negative, /api/prompt/*, enhance, motion, prompt H3, vision y LLM status.
Qué no hace: no genera imágenes ni vídeos finales en ComfyUI.
Dependencias: app.prompt, app.vision, app.llm y app.video.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Callable

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.config import APP_ROOT
from app.engine import EngineError
from app.enhancer import (
    DEFAULT_STRENGTH_PRESET,
    STRENGTH_PRESETS,
    apply_preprompt,
    enhance as enhance_prompt,
    load_server_llm,
)
from app.h3_prompt import write_h3_prompt
from app.llm_server import LlamaServerManager
from app.motion import write_motion
from app.oc_traits import build_prompt
from app.preprompts import DEFAULT_FAMILY, DEFAULT_PREPROMPT
from app.prompt_zones import (
    ZONE_ORDER,
    compose_zones,
    insert_tag,
    prompt_options,
    split_zones,
    zones_payload,
)
from app.routes.image import _decode_image_b64
from app.vision import VisionService, VisionUnavailable

_manager_lock = threading.Lock()
_manager_instance: LlamaServerManager | None = None


def _manager() -> LlamaServerManager:
    """Manager unico del `llama-server` gestionado (creado con `APP_ROOT`)."""
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = LlamaServerManager(APP_ROOT)
        return _manager_instance


_orig_manager = _manager
_orig_load_server_llm = load_server_llm


def _get_manager() -> LlamaServerManager:
    """Obtiene el manager, respetando patches sobre app.server._manager en tests."""
    server = sys.modules.get("app.server")
    server_fn = getattr(server, "_manager", None) if server is not None else None
    if server_fn is not None and server_fn is not _orig_manager and server_fn is not _get_manager:
        return server_fn() if callable(server_fn) else server_fn
    prompt_mod = sys.modules.get("app.routes.prompt")
    prompt_fn = getattr(prompt_mod, "_manager", None) if prompt_mod is not None else None
    if prompt_fn is not None and prompt_fn is not _orig_manager and prompt_fn is not _get_manager:
        return prompt_fn() if callable(prompt_fn) else prompt_fn
    return _orig_manager()


def _manager_llm() -> Callable[[str, Any], str]:
    """LLM perezoso contra el servidor gestionado (o externo si hay env).

    El primer uso llama a `_manager().ensure()`, que arranca `llama-server`
    si hace falta; el cliente HTTP acepta `temperature` por kwarg.
    """

    def llm(
        system: str,
        user: Any,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        mgr = _get_manager()
        server_url = mgr.ensure()
        server = sys.modules.get("app.server")
        server_loader = getattr(server, "load_server_llm", None) if server is not None else None
        if callable(server_loader) and server_loader is not _orig_load_server_llm:
            loader = server_loader
        else:
            prompt_mod = sys.modules.get("app.routes.prompt")
            prompt_loader = getattr(prompt_mod, "load_server_llm", None) if prompt_mod is not None else None
            if callable(prompt_loader) and prompt_loader is not _orig_load_server_llm:
                loader = prompt_loader
            else:
                loader = _orig_load_server_llm
        client = loader(server_url)
        if max_tokens is not None:
            try:
                return client(system, user, temperature=temperature, max_tokens=max_tokens)
            except TypeError:
                pass
        return client(system, user, temperature=temperature)

    return llm


def _ensure_vision_server(vision_service: Any = None) -> None:
    """Arranca el `llama-server` antes de un caption que use servidor (M12-4).

    Inocuo en modo externo (`ensure()` devuelve la URL sin arrancar nada) y
    en vision local sin `server_url` (no se llama). Si falla, el EngineError
    del manager se propaga con su mensaje.
    """
    if getattr(vision_service, "server_url", None):
        _get_manager().ensure()


router = APIRouter()


@router.get("/api/negative")
async def api_negative(
    preprompt: str = DEFAULT_PREPROMPT, family: str = DEFAULT_FAMILY
) -> dict:
    _positive, negative = apply_preprompt("", family=family, name=preprompt)
    return {"negative": negative}


@router.post("/api/prompt/build")
async def api_prompt_build(payload: dict = Body(...)) -> dict:
    return {"prompt": build_prompt(payload.get("trait_ids"))}


@router.post("/api/prompt/zones")
async def api_prompt_zones(payload: dict = Body(...)) -> Any:
    text = payload.get("text")
    if not isinstance(text, str):
        raise EngineError("text requerido")
    zones = split_zones(text)
    return {"zones": zones_payload(text), "composed": compose_zones(zones)}


@router.get("/api/prompt/options")
async def api_prompt_options(zone: str | None = None) -> Any:
    return prompt_options(zone)


@router.post("/api/prompt/compose")
async def api_prompt_compose(payload: dict = Body(...)) -> Any:
    zones = payload.get("zones")
    if not isinstance(zones, dict):
        raise EngineError("zones requerido (objeto por zona)")
    return {"text": compose_zones(zones)}


@router.post("/api/prompt/insert")
async def api_prompt_insert(payload: dict = Body(...)) -> Any:
    text = payload.get("text")
    if not isinstance(text, str):
        raise EngineError("text requerido")
    tag = payload.get("tag")
    if not isinstance(tag, str) or not tag.strip():
        raise EngineError("tag requerido")
    return {"text": insert_tag(text, tag, payload.get("zone"))}


@router.post("/api/enhance")
async def api_enhance(request: Request, payload: dict = Body(...)) -> Any:
    llm = request.app.state.llm
    rating = payload.get("rating")
    if rating is None:
        rating = "sfw"
    if rating not in ("sfw", "nsfw"):
        return JSONResponse(
            status_code=400, content={"error": "rating invalido; usar sfw|nsfw"}
        )
    strength = payload.get("strength")
    if strength is None:
        strength = DEFAULT_STRENGTH_PRESET
    if not isinstance(strength, str) or strength not in STRENGTH_PRESETS:
        return JSONResponse(
            status_code=400,
            content={"error": "strength invalido; usar fiel|balanceado|creativo"},
        )
    if llm is None:
        return JSONResponse(status_code=503, content={"error": "LLM no disponible"})
    result = enhance_prompt(
        str(payload.get("text") or ""),
        family=str(payload.get("family") or DEFAULT_FAMILY),
        preprompt=str(payload.get("preprompt") or DEFAULT_PREPROMPT),
        rating=rating,
        strength=strength,
        llm=llm,
    )
    return {
        "positive": result["positive"],
        "negative": result["negative"],
        "dropped": result["dropped"],
    }


@router.post("/api/prompt/enhance_zones")
async def api_prompt_enhance_zones(request: Request, payload: dict = Body(...)) -> Any:
    """«Mejorar prompt» por zonas (M9-C3a): positivo clasificado para el editor.

    Valida `text` no vacío, `zone` (si viene) de `ZONE_ORDER`, `strength`
    de `STRENGTH_PRESETS` y `rating` `sfw|nsfw` (ausente -> `sfw`): 400 con
    `{"error"}`. Sin LLM -> 503 con el mismo mensaje que `/api/enhance`.
    `zone` viaja como `zone_hint` al enhancer y el positivo resultante se
    reparte con `split_zones`/`zones_payload`; la respuesta es
    `{raw, positive, negative, composed, zones}` con `composed` canónico y
    `zones` el payload del editor (con `subcats` en general).
    """
    llm = request.app.state.llm
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse(status_code=400, content={"error": "text vacio"})
    zone = payload.get("zone")
    if zone is not None and (not isinstance(zone, str) or zone not in ZONE_ORDER):
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    "zone invalido; usar quality|safety|subject|character|general"
                )
            },
        )
    strength = payload.get("strength")
    if strength is None:
        strength = DEFAULT_STRENGTH_PRESET
    if not isinstance(strength, str) or strength not in STRENGTH_PRESETS:
        return JSONResponse(
            status_code=400,
            content={"error": "strength invalido; usar fiel|balanceado|creativo"},
        )
    rating = payload.get("rating")
    if rating is None:
        rating = "sfw"
    if rating not in ("sfw", "nsfw"):
        return JSONResponse(
            status_code=400, content={"error": "rating invalido; usar sfw|nsfw"}
        )
    tags = payload.get("tags")
    if tags is None:
        tags = []
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        return JSONResponse(
            status_code=400,
            content={"error": "tags invalido; usar lista de strings"},
        )
    if len(tags) > 120:
        return JSONResponse(status_code=400, content={"error": "tags: maximo 120"})
    if llm is None:
        return JSONResponse(status_code=503, content={"error": "LLM no disponible"})
    result = enhance_prompt(
        text,
        strength=strength,
        rating=rating,
        llm=llm,
        zone_hint=zone,
        context_tags=tags,
    )
    zones = split_zones(result["positive"])
    return {
        "raw": result["raw"],
        "positive": result["positive"],
        "negative": result["negative"],
        "composed": compose_zones(zones),
        "zones": zones_payload(result["positive"]),
        "dropped": result["dropped"],
    }


@router.post("/api/motion")
async def api_motion(request: Request, payload: dict = Body(...)) -> Any:
    llm = request.app.state.llm
    if llm is None:
        return JSONResponse(status_code=503, content={"error": "LLM no disponible"})
    return write_motion(
        payload.get("text"),
        rating=str(payload.get("rating") or "nsfw"),
        llm=llm,
    )


@router.post("/api/video/h3_prompt")
async def api_video_h3_prompt(request: Request, payload: dict = Body(...)) -> Any:
    llm = request.app.state.llm
    if llm is None:
        return JSONResponse(status_code=503, content={"error": "LLM no disponible"})
    image_b64 = payload.get("image_b64")
    if image_b64 is not None and not isinstance(image_b64, str):
        image_b64 = None
    images_b64 = payload.get("images_b64")
    if images_b64 is not None and not isinstance(images_b64, list):
        images_b64 = None
    raw_strength = payload.get("strength")
    strength = str(raw_strength or "balanceado").strip().lower()
    if strength not in ("fiel", "balanceado", "creativo"):
        return JSONResponse(
            status_code=400,
            content={"error": "strength invalido; usar fiel|balanceado|creativo"},
        )
    return write_h3_prompt(
        payload.get("text"),
        rating=str(payload.get("rating") or "nsfw"),
        llm=llm,
        image_b64=image_b64,
        images_b64=images_b64,
        strength=strength,
    )


@router.get("/api/vision/status")
async def api_vision_status(request: Request) -> dict:
    vision_service = getattr(request.app.state, "vision", None)
    if vision_service is None:
        cfg = request.app.state.config
        mgr = _get_manager()
        default_server_url = mgr.external_url() or mgr.base_url
        vision_service = VisionService(cfg.comfy_root, server_url=default_server_url)
    return vision_service.status()


@router.get("/api/llm/status")
async def api_llm_status() -> dict:
    """Estado del LLM: externo si `WAIFU_LLM_URL`; si no, gestionado (M12-3)."""
    return _get_manager().status()


@router.post("/api/vision/image_to_prompt")
async def api_vision_image_to_prompt(request: Request, payload: dict = Body(...)) -> Any:
    """Tags WD14 y/o caption VL de una imagen (galeria por `gen_id` o base64).

    Con `mode` (`unified|tags|caption`) se ignora `use_tags/use_caption`:
    `tags`/`caption` usan `describe` con un solo componente y `unified`
    pide caption + tags en una llamada (`describe_unified`); la respuesta
    anade `mode`, `dropped` y `zones` (si hay tags) sobre las claves
    actuales. Sin `mode` el comportamiento es el de siempre.
    """
    cfg = request.app.state.config
    st = request.app.state.store
    vision_service = getattr(request.app.state, "vision", None)
    if vision_service is None:
        mgr = _get_manager()
        default_server_url = mgr.external_url() or mgr.base_url
        vision_service = VisionService(cfg.comfy_root, server_url=default_server_url)

    gen_id = payload.get("gen_id")
    image_b64 = payload.get("image_b64")
    if (gen_id is None) == (image_b64 is None):
        return JSONResponse(
            status_code=400,
            content={"error": "usar gen_id o image_b64 (uno solo)"},
        )
    mode = payload.get("mode")
    if mode is None:
        use_tags = payload.get("use_tags", True)
        use_caption = payload.get("use_caption", True)
        if not isinstance(use_tags, bool) or not isinstance(use_caption, bool):
            return JSONResponse(
                status_code=400,
                content={"error": "use_tags/use_caption booleanos"},
            )
        if not use_tags and not use_caption:
            return JSONResponse(
                status_code=400, content={"error": "activa use_tags o use_caption"}
            )
    elif mode not in ("unified", "tags", "caption"):
        return JSONResponse(
            status_code=400,
            content={"error": "mode invalido; usar unified|tags|caption"},
        )
    if image_b64 is not None:
        raw = _decode_image_b64(image_b64, "vision")
    else:
        if isinstance(gen_id, bool) or not isinstance(gen_id, (int, str)):
            return JSONResponse(
                status_code=400, content={"error": "gen_id invalido"}
            )
        try:
            gid = int(gen_id)
        except (TypeError, ValueError):
            return JSONResponse(
                status_code=400, content={"error": "gen_id invalido"}
            )
        row = st.get(gid)
        if row is None:
            return JSONResponse(
                status_code=404, content={"error": "generacion desconocida"}
            )
        if row.get("kind") != "image":
            return JSONResponse(
                status_code=400,
                content={"error": "se requiere una generacion de imagen"},
            )
        file_name = ""
        for output in row.get("outputs") or []:
            candidate = output.get("name") if isinstance(output, dict) else output
            if isinstance(candidate, str) and candidate.strip():
                file_name = candidate.strip()
                break
        if not file_name:
            return JSONResponse(
                status_code=404, content={"error": "la generacion no tiene salidas"}
            )
        gallery_root = (cfg.data_dir / "gallery" / str(gid)).resolve()
        source = (gallery_root / file_name).resolve()
        if not source.is_relative_to(gallery_root):
            return JSONResponse(
                status_code=403, content={"error": "ruta fuera de la galeria"}
            )
        if (
            source.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")
            or not source.is_file()
        ):
            return JSONResponse(
                status_code=404, content={"error": "archivo de origen no encontrado"}
            )
        raw = source.read_bytes()
    if mode is not None:
        if mode != "tags":
            _ensure_vision_server(vision_service)
        try:
            if mode == "unified":
                result = vision_service.describe_unified(raw)
            elif mode == "tags":
                result = vision_service.describe(
                    raw, use_tags=True, use_caption=False
                )
            else:
                result = vision_service.describe(
                    raw, use_tags=False, use_caption=True
                )
        except VisionUnavailable as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})
        tags = result.get("tags") or []
        response: dict[str, Any] = {
            "tags": result.get("tags"),
            "caption": result.get("caption"),
            "model": result.get("model"),
            "mode": mode,
            "dropped": list(result.get("dropped") or []),
        }
        if mode in ("unified", "tags") and tags:
            response["zones"] = zones_payload(", ".join(tags))
        return response
    if use_caption:
        _ensure_vision_server(vision_service)
    try:
        return vision_service.describe(
            raw, use_tags=use_tags, use_caption=use_caption
        )
    except VisionUnavailable as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
