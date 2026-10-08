"""Rutas de edición y generación con Qwen-Image 2.1 (/api/editor/status, /api/editor/generate).

Gestiona verificación de modelos del editor y el encolado de jobs de edición / inpaint.
Depende de app.editor_models, app.editor, app.routes.image y el registro de jobs.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.editor import (
    EDITOR_CFG_MAX,
    EDITOR_CFG_MIN,
    EDITOR_DEFAULT_CFG,
    EDITOR_DEFAULT_SIZE,
    EDITOR_DEFAULT_STEPS,
    EDITOR_SEED_MAX,
    EDITOR_STEPS_MAX,
    EDITOR_STEPS_MIN,
    inherit_size_from_image,
)
from app.editor_models import editor_model
from app.engine import EngineError
from app.routes.image import _decode_image_b64, _write_input_png
from app.routes.jobs import _JOBS

_EDITOR = editor_model()
EDITOR_MODEL = _EDITOR.id
EDITOR_MODEL_FILES = _EDITOR.files
EDITOR_NOTE = _EDITOR.note
EDITOR_REF_LIMIT = 10
EDITOR_SIZE_MIN = 512
EDITOR_SIZE_MAX = 2048
EDITOR_SIZE_STEP = 16


def editor_installed(comfy_root: Any) -> bool:
    """True solo si existen TODOS los archivos esperados del editor (M9-G).

    `expected` son las rutas relativas a `ComfyUI/models` del catalogo UC
    (`registry/editor_models-v1.json`, M10-6b); no se comprueba tamaño ni hash
    y no se inventa que existan: con temp root el resultado es `False`. El GGUF
    de difusion se acepta en `unet/` (ruta del manifiesto) o en
    `diffusion_models/` (mismo alias que escanea UnetLoaderGGUF en ComfyUI):
    la descarga M10 solo dejo el archivo en el segundo.
    """
    models_root = Path(comfy_root) / "models"
    for relative in EDITOR_MODEL_FILES:
        if (models_root / relative).is_file():
            continue
        if relative.startswith("unet/"):
            alias = "diffusion_models/" + relative[len("unet/") :]
            if (models_root / alias).is_file():
                continue
        return False
    return True


_orig_editor_installed = editor_installed


def _is_editor_installed(comfy_root: Any) -> bool:
    server = sys.modules.get("app.server")
    server_fn = getattr(server, "editor_installed", None) if server is not None else None
    if callable(server_fn) and server_fn is not _orig_editor_installed:
        return server_fn(comfy_root)
    mod_editor = sys.modules.get("app.routes.editor")
    editor_fn = getattr(mod_editor, "editor_installed", None) if mod_editor is not None else None
    if callable(editor_fn) and editor_fn is not _orig_editor_installed:
        return editor_fn(comfy_root)
    return _orig_editor_installed(comfy_root)


router = APIRouter()


@router.get("/api/editor/status")
async def api_editor_status(request: Request) -> dict:
    """Estado real del editor Qwen-Image 2.1 (M9-G/M10-3).

    `expected` son las rutas relativas a `ComfyUI/models` del par UC (GGUF
    + text encoder int8 ConvRot + VAE bf16) definidas en
    `registry/editor_models-v1.json`; `installed` exige que existan TODAS y
    es lo que habilita el encolado real de `/api/editor/generate`.
    """
    cfg = request.app.state.config
    return {
        "installed": _is_editor_installed(cfg.comfy_root),
        "model": EDITOR_MODEL,
        "expected": list(EDITOR_MODEL_FILES),
        "note": EDITOR_NOTE,
    }


@router.post("/api/editor/generate")
async def api_editor_generate(request: Request, payload: dict = Body(...)) -> Any:
    """Valida y encola una generación del editor Qwen-Image 2.1 (M10-3).

    La forma se valida siempre (400): prompt, `mode` `generate|edit`,
    `negative` opcional (texto), máximo 10 refs base64 válidas, size en
    [512, 2048] múltiplos de 16, seed entera en 0..2^64-1, `steps` entero
    en [10, 50] y `cfg` en [1.0, 10.0]. Con el par UC
    instalado (los 3 archivos del catálogo) escribe las referencias en
    `ComfyUI/input` y encola un job `kind="editor"` que produce una
    generación nueva (`kind="image"`, `params.task="editor"`, visible en la
    galería de Imagen); 503 si falta algún archivo del modelo.
    """
    cfg = request.app.state.config
    st = request.app.state.store
    queue = request.app.state.queue

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse(status_code=400, content={"error": "prompt vacio"})
    mode = payload.get("mode") or "generate"
    if mode not in ("generate", "edit"):
        return JSONResponse(
            status_code=400, content={"error": "mode invalido; usar generate|edit"}
        )
    negative = payload.get("negative")
    if negative is None:
        negative = ""
    if not isinstance(negative, str):
        return JSONResponse(status_code=400, content={"error": "negative invalido"})
    refs = payload.get("ref_images_b64")
    raw_refs: list[bytes] = []
    if refs is not None:
        if not isinstance(refs, list):
            return JSONResponse(
                status_code=400,
                content={"error": "ref_images_b64 invalido; usar lista"},
            )
        if len(refs) > EDITOR_REF_LIMIT:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"maximo {EDITOR_REF_LIMIT} imagenes de referencia"
                },
            )
        for index, ref in enumerate(refs):
            raw_refs.append(_decode_image_b64(ref, f"ref_images_b64[{index}]"))
    if mode == "edit" and not raw_refs:
        return JSONResponse(
            status_code=400,
            content={"error": "modo editar requiere una imagen de referencia"},
        )
    width = None
    height = None
    original_size = False
    size = payload.get("size")
    if size not in (None, ""):
        if not isinstance(size, dict):
            return JSONResponse(status_code=400, content={"error": "size invalido"})
        if size.get("original") is True:
            original_size = True
        else:
            for name in ("width", "height"):
                value = size.get(name)
                if value is None or isinstance(value, bool):
                    return JSONResponse(
                        status_code=400, content={"error": f"size.{name} invalido"}
                    )
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    return JSONResponse(
                        status_code=400, content={"error": f"size.{name} invalido"}
                    )
                if (
                    not number.is_integer()
                    or not EDITOR_SIZE_MIN <= number <= EDITOR_SIZE_MAX
                    or number % EDITOR_SIZE_STEP
                ):
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": (
                                f"size fuera de [{EDITOR_SIZE_MIN}, {EDITOR_SIZE_MAX}]"
                                f" o no multiplo de {EDITOR_SIZE_STEP}"
                            )
                        },
                    )
                if name == "width":
                    width = int(number)
                else:
                    height = int(number)
    seed = payload.get("seed")
    if seed is None:
        seed = 42
    if isinstance(seed, bool):
        return JSONResponse(status_code=400, content={"error": "seed invalido"})
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "seed invalido"})
    if not 0 <= seed <= EDITOR_SEED_MAX:
        return JSONResponse(
            status_code=400,
            content={"error": f"seed fuera de 0..{EDITOR_SEED_MAX}"},
        )
    steps = payload.get("steps")
    if steps is None:
        steps = EDITOR_DEFAULT_STEPS
    if isinstance(steps, bool) or (
        isinstance(steps, float) and not steps.is_integer()
    ):
        return JSONResponse(status_code=400, content={"error": "steps invalido"})
    try:
        steps = int(steps)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "steps invalido"})
    if not EDITOR_STEPS_MIN <= steps <= EDITOR_STEPS_MAX:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"steps fuera de [{EDITOR_STEPS_MIN}, {EDITOR_STEPS_MAX}]"
            },
        )
    cfg_value = payload.get("cfg")
    if cfg_value is None:
        cfg_value = EDITOR_DEFAULT_CFG
    if isinstance(cfg_value, bool):
        return JSONResponse(status_code=400, content={"error": "cfg invalido"})
    try:
        cfg_value = float(cfg_value)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "cfg invalido"})
    if not EDITOR_CFG_MIN <= cfg_value <= EDITOR_CFG_MAX:
        return JSONResponse(
            status_code=400,
            content={"error": f"cfg fuera de [{EDITOR_CFG_MIN}, {EDITOR_CFG_MAX}]"},
        )
    if original_size:
        if not raw_refs:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "size original requiere al menos una referencia"
                },
            )
        try:
            width, height = inherit_size_from_image(raw_refs[0])
        except EngineError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
    if not _is_editor_installed(cfg.comfy_root):
        return JSONResponse(
            status_code=503, content={"error": "modelo no instalado (M10)"}
        )
    if width is None:
        width = EDITOR_DEFAULT_SIZE
    if height is None:
        height = EDITOR_DEFAULT_SIZE
    input_dir = cfg.comfy_input_dir
    ref_images = [_write_input_png(input_dir, raw) for raw in raw_refs]
    params = {
        "task": "editor",
        "mode": mode,
        "width": width,
        "height": height,
        "seed": seed,
        "steps": steps,
        "cfg": cfg_value,
        "ref_images": ref_images,
    }
    if original_size:
        params["original_size"] = True
    gen_id = st.add(
        EDITOR_MODEL, prompt.strip(), negative.strip(), params, kind="image"
    )
    job = {
        "kind": "editor",
        "gen_id": gen_id,
        "prompt": prompt.strip(),
        "negative": negative.strip(),
        "seed": seed,
        "steps": steps,
        "cfg": cfg_value,
        "width": width,
        "height": height,
        "ref_images": ref_images,
        "params": dict(params),
    }
    _JOBS[gen_id] = {
        "prompt_id": None,
        "tracker": None,
        "status": "queued",
        "engine": None,
        "kind": "editor",
    }
    job_id = queue.submit(job)
    request.app.state.jobs[job_id] = job
    return {"job_id": job_id}
