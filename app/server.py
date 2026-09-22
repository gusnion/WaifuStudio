"""Webapp local FastAPI (F3b): API JSON, runner de generación y UI.

`create_app` inyecta todo (config, store, registry, engine_factory, llm, queue y
`start_worker`) para que los tests corran offline con un transporte falso: la
GPU y el LLM reales no se tocan. `run_generation` parchea el grafo base con el
modelo/params, copia los PNG a `data_dir/gallery/<gen_id>/` y refleja el estado
en el store; un fallo queda registrado en store y job sin propagarse al worker.
"""

from __future__ import annotations

import base64
import binascii
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import APP_ROOT, EngineConfig, load_config
from app.engine import ComfyEngine, EngineError, load_graph
from app.enhancer import apply_preprompt
from app.enhancer import enhance as enhance_prompt
from app.graphs import DEFAULT_STRENGTH, patch_model, patch_params, to_img2img
from app.jobs import JobQueue
from app.motion import MOTION_NEGATIVE, write_motion
from app.oc_traits import build_prompt, list_traits
from app.preprompts import DEFAULT_FAMILY, DEFAULT_PREPROMPT, get_preprompt, list_preprompts
from app.registry import DEFAULT_PATH as REGISTRY_PATH
from app.registry import ModelRegistry
from app.store import Store
from app.video import (
    ASPECTS,
    H3_TEMPLATE_PATH,
    VIDEO_HISTORY_TIMEOUT_S,
    WAN_TEMPLATE_PATH,
    run_video_generation,
)

APP_HOST = "127.0.0.1"
APP_PORT = 8765
DEFAULT_GRAPH_PATH = APP_ROOT / "workflows" / "anima_base.json"
TEMPLATES_DIR = APP_ROOT / "templates"
STATIC_DIR = APP_ROOT / "static"
MEDIA_URL = "/media/{gen_id}/{name}"
PARAM_KEYS = ("seed", "steps", "cfg", "sampler_name", "scheduler", "width", "height")
MEDIA_TYPES = {
    ".png": "image/png",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


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


def _write_input_png(input_dir: Any, raw: bytes) -> str:
    """Escribe la imagen en comfy_root/input con nombre uuid y devuelve el nombre."""
    input_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.png"
    (input_dir / name).write_bytes(raw)
    return name


def run_generation(
    job: dict,
    *,
    config: EngineConfig,
    store: Store,
    registry: ModelRegistry,
    engine_factory: Callable[[], Any],
) -> None:
    """Ejecuta un job de imagen: grafo -> engine -> galería -> store.

    No propaga errores: el fallo se guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    try:
        entry = registry.get(job["model_id"])
        params = dict(job.get("params") or {})
        graph = load_graph(DEFAULT_GRAPH_PATH)
        graph = patch_model(graph, entry, seed=params.get("seed"))
        applied = {key: params[key] for key in PARAM_KEYS if params.get(key) is not None}
        graph = patch_params(graph, **applied)
        preprompt = job.get("preprompt") or entry.preprompt or DEFAULT_PREPROMPT
        positive, preprompt_negative = apply_preprompt(
            job["prompt"], family=entry.family, name=preprompt
        )
        graph = _set_text_nodes(
            graph, positive, _merge_tags([preprompt_negative, job.get("negative") or ""])
        )
        if job.get("ref_image"):
            graph = to_img2img(
                graph, job["ref_image"], job.get("strength", DEFAULT_STRENGTH)
            )
        engine = engine_factory()
        prompt_id = engine.submit(graph)
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
    except Exception as exc:
        job["outputs"] = []
        job["error"] = str(exc)
        try:
            store.update(gen_id, status="error", error=str(exc))
        except EngineError:
            pass


def create_app(
    config: EngineConfig | None = None,
    store: Store | None = None,
    registry: ModelRegistry | None = None,
    engine_factory: Callable[[], Any] | None = None,
    llm: Callable[[str, str], str] | None = None,
    *,
    queue: JobQueue | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """Construye la app con todas sus dependencias inyectables.

    Defaults: `load_config()`, `Store(config.data_dir/'waifu.db')` con `init()`,
    `ModelRegistry.load(registry/models.json)` y `ComfyEngine(config)`. El
    lifespan arranca/para la cola salvo `start_worker=False` (tests).
    """
    cfg = config if config is not None else load_config()
    st = store if store is not None else Store(cfg.data_dir / "waifu.db")
    if store is None:
        st.init()
    reg = registry if registry is not None else ModelRegistry.load(REGISTRY_PATH)
    factory = engine_factory if engine_factory is not None else (lambda: ComfyEngine(cfg))
    video_factory = (
        engine_factory
        if engine_factory is not None
        else (lambda: ComfyEngine(cfg, history_timeout_s=VIDEO_HISTORY_TIMEOUT_S))
    )

    def _dispatch(job: dict) -> None:
        if job.get("kind") == "video":
            run_video_generation(
                job, config=cfg, store=st, engine_factory=video_factory
            )
        else:
            run_generation(
                job, config=cfg, store=st, registry=reg, engine_factory=factory
            )

    if queue is None:
        queue = JobQueue(_dispatch)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_worker:
            queue.start()
        try:
            yield
        finally:
            if start_worker:
                queue.stop()

    app = FastAPI(title="WAIFU", lifespan=lifespan)
    app.state.config = cfg
    app.state.store = st
    app.state.registry = reg
    app.state.engine_factory = factory
    app.state.llm = llm
    app.state.queue = queue
    app.state.jobs = {}

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(EngineError)
    async def _engine_error(_request: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.get("/api/models")
    async def api_models() -> list[dict]:
        return [
            {
                "id": entry.id,
                "display_name": entry.display_name,
                "family": entry.family,
                "preprompt": entry.preprompt,
                "unet_name": entry.profile.unet_name,
                "defaults": dict(entry.defaults),
            }
            for entry in reg.models
        ]

    @app.get("/api/preprompts")
    async def api_preprompts(family: str = DEFAULT_FAMILY) -> dict:
        return {
            "family": family,
            "names": list_preprompts(family),
            "default": DEFAULT_PREPROMPT,
        }

    @app.get("/api/traits")
    async def api_traits() -> dict:
        return list_traits()

    @app.post("/api/prompt/build")
    async def api_prompt_build(payload: dict = Body(...)) -> dict:
        return {"prompt": build_prompt(payload.get("trait_ids"))}

    @app.post("/api/enhance")
    async def api_enhance(payload: dict = Body(...)) -> Any:
        if llm is None:
            return JSONResponse(status_code=503, content={"error": "LLM no disponible"})
        result = enhance_prompt(
            str(payload.get("text") or ""),
            family=str(payload.get("family") or DEFAULT_FAMILY),
            preprompt=str(payload.get("preprompt") or DEFAULT_PREPROMPT),
            rating=payload.get("rating"),
            llm=llm,
        )
        return {"positive": result["positive"], "negative": result["negative"]}

    @app.post("/api/motion")
    async def api_motion(payload: dict = Body(...)) -> Any:
        if llm is None:
            return JSONResponse(status_code=503, content={"error": "LLM no disponible"})
        return write_motion(
            payload.get("text"),
            rating=str(payload.get("rating") or "nsfw"),
            llm=llm,
        )

    @app.post("/api/generate")
    async def api_generate(payload: dict = Body(...)) -> Any:
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
        get_preprompt(entry.family, preprompt)
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return JSONResponse(status_code=400, content={"error": "params invalido"})
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
            input_dir = cfg.comfy_root / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            ref_image = f"{uuid.uuid4().hex}.png"
            (input_dir / ref_image).write_bytes(raw)
        if ref_image is not None and strength is None:
            strength = DEFAULT_STRENGTH
        stored_params = dict(params)
        stored_params["preprompt"] = preprompt
        if ref_image is not None:
            stored_params["strength"] = strength
            stored_params["ref_image"] = ref_image
        gen_id = st.add(entry.id, prompt.strip(), negative, stored_params)
        job = {
            "gen_id": gen_id,
            "model_id": entry.id,
            "prompt": prompt.strip(),
            "negative": negative,
            "preprompt": preprompt,
            "params": params,
            "ref_image": ref_image,
            "strength": strength,
        }
        job_id = queue.submit(job)
        app.state.jobs[job_id] = job
        return {"job_id": job_id}

    @app.post("/api/video/generate")
    async def api_video_generate(payload: dict = Body(...)) -> Any:
        engine_kind = payload.get("engine")
        if engine_kind not in ("wan", "h3"):
            raise EngineError("engine invalido; usar wan|h3")
        aspect = payload.get("aspect") or "vertical"
        if aspect not in ASPECTS:
            raise EngineError("aspect invalido; usar vertical|horizontal")
        first_raw = _decode_image_b64(payload.get("image_b64"), "image")
        last_raw = None
        if engine_kind == "h3":
            last_raw = _decode_image_b64(payload.get("last_image_b64"), "last_image")
        if engine_kind == "wan":
            motion_positive = payload.get("motion_positive")
            if not isinstance(motion_positive, str) or not motion_positive.strip():
                raise EngineError("motion_positive requerido para wan")
            motion_positive = motion_positive.strip()
            prompt = str(payload.get("prompt") or "")
            motion_negative = payload.get("motion_negative")
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
        input_dir = cfg.comfy_root / "input"
        image_name = _write_input_png(input_dir, first_raw)
        last_image_name = (
            _write_input_png(input_dir, last_raw) if last_raw is not None else None
        )
        template = WAN_TEMPLATE_PATH if engine_kind == "wan" else H3_TEMPLATE_PATH
        gen_id = st.add(
            engine_kind,
            motion_positive if engine_kind == "wan" else prompt,
            motion_negative,
            {
                "engine": engine_kind,
                "aspect": aspect,
                "seed": seed,
                "image": image_name,
                "last_image": last_image_name,
            },
            kind="video",
        )
        job = {
            "kind": "video",
            "gen_id": gen_id,
            "engine": engine_kind,
            "template": str(template),
            "image_name": image_name,
            "last_image_name": last_image_name,
            "motion_positive": motion_positive,
            "motion_negative": motion_negative,
            "prompt": prompt,
            "aspect": aspect,
            "seed": seed,
        }
        job_id = queue.submit(job)
        app.state.jobs[job_id] = job
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    async def api_job(job_id: str) -> Any:
        try:
            status = queue.status(job_id)
        except EngineError:
            return JSONResponse(status_code=404, content={"error": "job desconocido"})
        job = app.state.jobs.get(job_id) or {}
        if status == "done" and job.get("error"):
            status = "error"
        gen_id = job.get("gen_id")
        outputs = [
            {"name": name, "url": MEDIA_URL.format(gen_id=gen_id, name=name)}
            for name in (job.get("outputs") or [])
        ]
        return {"status": status, "outputs": outputs, "error": job.get("error")}

    @app.get("/api/gallery")
    async def api_gallery(limit: int = 50, offset: int = 0) -> dict:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        items = []
        for row in st.list(limit=limit, offset=offset):
            item = dict(row)
            item["urls"] = [
                MEDIA_URL.format(gen_id=row["id"], name=name)
                for name in (row.get("outputs") or [])
            ]
            items.append(item)
        return {"items": items, "count": st.count()}

    @app.get("/media/{gen_id}/{name:path}")
    async def api_media(gen_id: int, name: str) -> Any:
        gen_root = (cfg.data_dir / "gallery" / str(gen_id)).resolve()
        candidate = (gen_root / name).resolve()
        if not candidate.is_relative_to(gen_root):
            return JSONResponse(
                status_code=403, content={"error": "ruta fuera de la galeria"}
            )
        media_type = MEDIA_TYPES.get(candidate.suffix.lower())
        if media_type is None or not candidate.is_file():
            return JSONResponse(status_code=404, content={"error": "no encontrado"})
        return FileResponse(candidate, media_type=media_type)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Any:
        return templates.TemplateResponse(request, "index.html", {"title": "WAIFU"})

    return app


def main() -> int:
    """`python -m app.server`: uvicorn en 127.0.0.1 y puerto de WAIFU_APP_PORT."""
    import uvicorn

    port_text = os.environ.get("WAIFU_APP_PORT", "").strip()
    port = int(port_text) if port_text else APP_PORT
    uvicorn.run(create_app(), host=APP_HOST, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "APP_HOST",
    "APP_PORT",
    "DEFAULT_GRAPH_PATH",
    "create_app",
    "main",
    "run_generation",
]
