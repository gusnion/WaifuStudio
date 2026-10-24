"""Rutas y ejecución de generación de imágenes (/api/generate).

Qué hace: gestiona la validación de peticiones de generación y el runner de KSampler.
Qué no hace: no maneja generación de vídeo Wan/H3 ni tareas del editor inpainting.
Dependencias: app.engine, app.graphs, app.enhancer y el registro de modelos.
"""

from __future__ import annotations

import base64
import binascii
import re
import shutil
import uuid
from typing import Any, Callable

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.config import APP_ROOT, EngineConfig
from app.engine import EngineError, load_graph
from app.enhancer import apply_preprompt
from app.formats import get_size
from app.graphs import (
    DEFAULT_STRENGTH,
    apply_loras,
    patch_model,
    patch_params,
    to_img2img,
)
from app.loras import get as get_lora, validate_selection
from app.params import is_valid_sampler, is_valid_scheduler
from app.preprompts import DEFAULT_FAMILY, DEFAULT_PREPROMPT, get_preprompt
from app.progress import ProgressTracker
from app.registry import ModelRegistry
from app.routes.jobs import _JOBS, _progress_ws_url
from app.store import Store

DEFAULT_GRAPH_PATH = APP_ROOT / "workflows" / "anima_base.json"
PARAM_KEYS = ("seed", "steps", "cfg", "sampler_name", "scheduler", "width", "height")


def _merge_tags(parts: list[str]) -> str:
    """Une fragmentos con ', ' deduplicando case-insensitive (primera aparición)."""
    seen: set[str] = set()
    merged: list[str] = []
    for part in parts:
        for tag in str(part or "").split(","):
            tag = tag.strip()
            if not tag:
                continue
            folded = tag.lower()
            if folded not in seen:
                seen.add(folded)
                merged.append(tag)
    return ", ".join(merged)


def _inject_lora_triggers(prompt: str, validated_loras: list[dict]) -> str:
    """Inyecta los triggers de los LoRAs activos si no estan ya en el prompt."""
    if not validated_loras:
        return prompt
    prompt_tags = {tag.strip().lower() for tag in prompt.split(",") if tag.strip()}
    prompt_tags_spaces = {tag.replace("_", " ") for tag in prompt_tags}
    lower_prompt = prompt.lower()

    triggers: list[str] = []
    for item in validated_loras:
        lora_id = item.get("id")
        if not isinstance(lora_id, str) or not lora_id.strip():
            continue
        try:
            lora_entry = get_lora(lora_id.strip())
        except EngineError:
            continue
        trigger = str(lora_entry.get("trigger") or "").strip()
        if not trigger:
            continue

        trig_lower = trigger.lower()
        trig_spaced = trig_lower.replace("_", " ")

        # 1. Comparar contra etiquetas separadas por comas
        if trig_lower in prompt_tags or trig_spaced in prompt_tags_spaces:
            continue

        # 2. Comprobar mediante regex de limite de palabra (\b)
        pattern = r"\b" + re.escape(trig_lower) + r"\b"
        pattern_spaced = r"\b" + re.escape(trig_spaced) + r"\b"
        if re.search(pattern, lower_prompt) or re.search(pattern_spaced, lower_prompt.replace("_", " ")):
            continue

        triggers.append(trigger)
    if not triggers:
        return prompt
    return _merge_tags([*triggers, prompt])


def _set_text_nodes(graph: dict, positive: str, negative: str) -> dict:
    """Escribe positive/negative en los CLIPTextEncode enlazados al KSampler."""
    ksamplers = [
        node
        for node in graph.values()
        if isinstance(node, dict) and node.get("class_type") == "KSampler"
    ]
    if not ksamplers:
        raise EngineError("grafo sin KSampler: no se puede fijar el prompt")
    for ksampler in ksamplers:
        inputs = ksampler.get("inputs")
        if not isinstance(inputs, dict):
            raise EngineError("KSampler sin inputs dict: no se puede fijar el prompt")
        for key, text in (("positive", positive), ("negative", negative)):
            link = inputs.get(key)
            if not isinstance(link, (list, tuple)) or not link:
                raise EngineError(f"KSampler sin enlace {key!r}: no se puede fijar el prompt")
            target = graph.get(str(link[0]))
            if not isinstance(target, dict) or target.get("class_type") != "CLIPTextEncode":
                raise EngineError(
                    f"enlace {key!r} del KSampler no apunta a CLIPTextEncode"
                )
            target_inputs = target.get("inputs")
            if not isinstance(target_inputs, dict):
                raise EngineError("CLIPTextEncode sin inputs dict: no se puede fijar el prompt")
            target_inputs["text"] = text
    return graph


def _decode_image_b64(value: Any, label: str) -> bytes:
    """Decodifica un data URI/base64 (validate=True); EngineError si es invalido."""
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"{label}: imagen requerida")
    data = value.strip()
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EngineError(f"{label}: base64 invalido") from exc
    if not raw:
        raise EngineError(f"{label}: imagen vacia")
    return raw


def _write_input_png(input_dir: Any, raw: bytes, filename: str | None = None) -> str:
    """Escribe la imagen en comfy_root/input con nombre uuid (o filename) y devuelve el nombre."""
    input_dir.mkdir(parents=True, exist_ok=True)
    name = filename if filename is not None else f"{uuid.uuid4().hex}.png"
    (input_dir / name).write_bytes(raw)
    return name


def _fit_reference(raw: bytes, width: int, height: int) -> bytes:
    """Ajusta la referencia al tamano pedido (cover + recorte centrado, PNG).

    Con referencia el grafo pasa a img2img y el latente hereda el tamano de la
    imagen de entrada; sin este ajuste el selector de tamano quedaba ignorado.
    Mantiene el aspect ratio escalando y recortando (sin deformar).
    """
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(raw)) as handle:
            image = handle.convert("RGB")
    except Exception as exc:
        raise EngineError("referencia invalida; usar PNG/JPG/WebP") from exc
    if image.size == (width, height):
        return raw
    scale = max(width / image.size[0], height / image.size[1])
    resized = image.resize(
        (
            max(1, round(image.size[0] * scale)),
            max(1, round(image.size[1] * scale)),
        ),
        Image.LANCZOS,
    )
    left = (resized.size[0] - width) // 2
    top = (resized.size[1] - height) // 2
    cropped = resized.crop((left, top, left + width, top + height))
    buffer = BytesIO()
    cropped.save(buffer, format="PNG")
    return buffer.getvalue()


def _validate_dimension(name: str, value: Any) -> tuple[int | None, str | None]:
    """Valida que una dimension este en [64, 4096] y sea multiplo de 8."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, f"{name} invalido"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{name} invalido"
    if not number.is_integer():
        return None, f"{name} fuera de [64, 4096] o no multiplo de 8"
    number = int(number)
    if not 64 <= number <= 4096 or number % 8:
        return None, f"{name} fuera de [64, 4096] o no multiplo de 8"
    return number, None


def run_generation(
    job: dict,
    *,
    config: EngineConfig,
    store: Store,
    registry: ModelRegistry,
    engine_factory: Callable[[], Any],
    ws_factory: Any = None,
) -> None:
    """Ejecuta un job de imagen: grafo -> engine -> galería -> store.

    Registra en `_JOBS` (memoria del proceso, se pierde al reiniciar la app) el
    engine creado, el `prompt_id` y el tracker de progreso, y no propaga
    errores: el fallo se guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    record = _JOBS.setdefault(
        gen_id,
        {"prompt_id": None, "tracker": None, "status": "queued", "engine": None},
    )
    if record.get("status") == "cancelled":
        job["outputs"] = []
        job["error"] = None
        return
    tracker = None
    try:
        entry = registry.get(job["model_id"])
        params = dict(job.get("params") or {})
        graph = load_graph(DEFAULT_GRAPH_PATH)
        graph = patch_model(graph, entry, seed=params.get("seed"))
        raw_loras = job.get("loras")
        validated_loras = validate_selection([] if raw_loras is None else raw_loras)
        graph = apply_loras(
            graph,
            validated_loras,
            model_id=job.get("model_id"),
        )
        applied = {key: params[key] for key in PARAM_KEYS if params.get(key) is not None}
        graph = patch_params(graph, **applied)
        preprompt = job.get("preprompt") or entry.preprompt or DEFAULT_PREPROMPT
        prompt_text = _inject_lora_triggers(job["prompt"], validated_loras)
        preprompt_family = entry.family or DEFAULT_FAMILY
        positive, negative = apply_preprompt(
            prompt_text, family=preprompt_family, name=preprompt
        )
        graph = _set_text_nodes(
            graph, positive, _merge_tags([job.get("negative") or "", negative])
        )
        if job.get("ref_image"):
            graph = to_img2img(
                graph, job["ref_image"], job.get("strength", DEFAULT_STRENGTH)
            )
        engine = engine_factory()
        record["engine"] = engine
        tracker = ProgressTracker(
            _progress_ws_url(config),
            engine.client_id,
            "",
            ws_factory=ws_factory,
        )
        record["tracker"] = tracker
        record["status"] = "running"
        tracker.start()
        prompt_id = engine.submit(graph)
        record["prompt_id"] = prompt_id
        tracker.prompt_id = prompt_id
        history = engine.wait(prompt_id)
        paths = engine.outputs(history, expected_ext=("png",))
        if not paths:
            raise EngineError(f"el engine no devolvio ningun PNG para {prompt_id}")
        gallery_dir = config.data_dir / "gallery" / str(gen_id)
        gallery_dir.mkdir(parents=True, exist_ok=True)
        names: list[str] = []
        for path in paths:
            target = gallery_dir / path.name
            shutil.copy2(path, target)
            names.append(target.name)
        store.update(gen_id, status="done", outputs=names)
        job["outputs"] = names
        job["error"] = None
        record["status"] = "done"
    except Exception as exc:
        job["outputs"] = []
        job["error"] = str(exc)
        if record.get("status") == "cancelled":
            job["error"] = None
            try:
                store.update(gen_id, status="cancelled")
            except EngineError:
                pass
        else:
            record["status"] = "error"
            try:
                store.update(gen_id, status="error", error=str(exc))
            except EngineError:
                pass
    finally:
        if tracker is not None:
            tracker.stop()


router = APIRouter()


@router.post("/api/generate")
async def api_generate(request: Request, payload: dict = Body(...)) -> Any:
    reg: ModelRegistry = request.app.state.registry
    cfg: EngineConfig = request.app.state.config
    st: Store = request.app.state.store
    queue = request.app.state.queue

    model_id = payload.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        return JSONResponse(status_code=400, content={"error": "model_id requerido"})
    entry = reg.get(model_id.strip())
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse(status_code=400, content={"error": "prompt vacio"})
    negative = payload.get("negative") or ""
    if not isinstance(negative, str):
        return JSONResponse(status_code=400, content={"error": "negative invalido"})
    preprompt = payload.get("preprompt") or entry.preprompt or DEFAULT_PREPROMPT
    if not isinstance(preprompt, str):
        return JSONResponse(status_code=400, content={"error": "preprompt invalido"})
    get_preprompt(entry.family, preprompt)
    rating = payload.get("rating")
    if rating is None:
        rating = "sfw"
    if rating not in ("sfw", "nsfw"):
        return JSONResponse(
            status_code=400, content={"error": "rating invalido; usar sfw|nsfw"}
        )
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return JSONResponse(status_code=400, content={"error": "params invalido"})
    params = dict(params)
    defaults = entry.defaults if isinstance(entry.defaults, dict) else {}
    has_reference = bool(payload.get("ref_image_b64"))
    for key in PARAM_KEYS:
        if has_reference and key in ("width", "height"):
            # img2img hereda el tamano de la referencia; no lo pisa el default.
            continue
        if params.get(key) is None and defaults.get(key) is not None:
            params[key] = defaults[key]
    raw_loras = payload.get("loras")
    loras = validate_selection([] if raw_loras is None else raw_loras)
    size = payload.get("size")
    width = payload.get("width")
    height = payload.get("height")
    if size not in (None, ""):
        if not isinstance(size, str):
            return JSONResponse(status_code=400, content={"error": "size invalido"})
        try:
            width, height = get_size(size.strip())
        except EngineError:
            return JSONResponse(
                status_code=400,
                content={"error": f"formato desconocido: {size!r}"},
            )
    else:
        for name, value in (("width", width), ("height", height)):
            val, err = _validate_dimension(name, value)
            if err:
                return JSONResponse(status_code=400, content={"error": err})
            if name == "width":
                width = val
            else:
                height = val
    for name in ("width", "height"):
        val, err = _validate_dimension(name, params.get(name))
        if err:
            return JSONResponse(status_code=400, content={"error": err})
        if val is not None:
            params[name] = val
    if width is not None:
        params = {**params, "width": width}
    elif "width" in params:
        width = params["width"]
    if height is not None:
        params = {**params, "height": height}
    elif "height" in params:
        height = params["height"]
    sampler_name = params.get("sampler_name")
    if sampler_name is not None and not is_valid_sampler(sampler_name):
        return JSONResponse(
            status_code=400,
            content={"error": f"sampler invalido: {sampler_name!r}"},
        )
    scheduler = params.get("scheduler")
    if scheduler is not None and not is_valid_scheduler(scheduler):
        return JSONResponse(
            status_code=400,
            content={"error": f"scheduler invalido: {scheduler!r}"},
        )
    strength = payload.get("strength")
    if strength is not None:
        try:
            strength = float(strength)
        except (TypeError, ValueError):
            return JSONResponse(status_code=400, content={"error": "strength invalido"})
        if not 0.0 < strength <= 1.0:
            return JSONResponse(
                status_code=400, content={"error": "strength fuera de (0, 1]"}
            )
    ref_image = None
    raw_b64 = payload.get("ref_image_b64")
    if raw_b64:
        if not isinstance(raw_b64, str):
            return JSONResponse(
                status_code=400, content={"error": "ref_image_b64 invalido"}
            )
        data = raw_b64.strip()
        if data.startswith("data:") and "," in data:
            data = data.split(",", 1)[1]
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return JSONResponse(
                status_code=400, content={"error": "base64 de referencia invalido"}
            )
        if not raw:
            return JSONResponse(
                status_code=400, content={"error": "imagen de referencia vacia"}
            )
        if width is not None and height is not None:
            raw = _fit_reference(raw, width, height)
        input_dir = cfg.comfy_input_dir
        input_dir.mkdir(parents=True, exist_ok=True)
        ref_image = f"{uuid.uuid4().hex}.png"
        (input_dir / ref_image).write_bytes(raw)
    if ref_image is not None and strength is None:
        strength = DEFAULT_STRENGTH
    raw_batch = payload.get("batch_size", 1)
    if raw_batch is None:
        raw_batch = 1
    if isinstance(raw_batch, bool) or not isinstance(raw_batch, int) or not (1 <= raw_batch <= 4):
        return JSONResponse(status_code=400, content={"error": "batch_size invalido; usar 1..4"})

    stored_params = dict(params)
    stored_params["preprompt"] = preprompt
    stored_params["rating"] = rating
    stored_params["loras"] = loras
    if ref_image is not None:
        stored_params["strength"] = strength
        stored_params["ref_image"] = ref_image

    job_ids: list[str] = []
    gen_ids: list[int] = []

    for idx in range(raw_batch):
        item_params = dict(params)
        item_stored = dict(stored_params)
        if idx > 0:
            if isinstance(item_params.get("seed"), int):
                item_params["seed"] = item_params["seed"] + idx
                item_stored["seed"] = item_params["seed"]
        gen_id = st.add(entry.id, prompt.strip(), negative, item_stored)
        job = {
            "gen_id": gen_id,
            "model_id": entry.id,
            "prompt": prompt.strip(),
            "negative": negative,
            "preprompt": preprompt,
            "params": item_params,
            "loras": loras,
            "ref_image": ref_image,
            "strength": strength,
        }
        _JOBS[gen_id] = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
        }
        job_id = queue.submit(job)
        request.app.state.jobs[job_id] = job
        job_ids.append(job_id)
        gen_ids.append(gen_id)

    if "batch_size" not in payload or raw_batch == 1:
        return {"job_id": job_ids[0]}
    return {
        "job_id": job_ids[0],
        "job_ids": job_ids,
        "gen_ids": gen_ids,
        "batch_size": raw_batch,
    }

