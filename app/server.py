"""Webapp local FastAPI (F3b): API JSON, runner de generación y UI.

Punto de entrada HTTP y orquestador de dependencias. Las rutas están
modularizadas en `app.routes.*` (M17).
"""

from __future__ import annotations

import atexit
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import trainer
from app.characters import CharacterStore
from app.config import APP_ROOT, EngineConfig, load_config
from app.editor import EDITOR_DEFAULT_CFG, EDITOR_DEFAULT_STEPS, run_editor_generation
from app.engine import ComfyEngine, EngineError
from app.enhancer import load_server_llm
from app.h3_presets import is_vdn_installed
from app.jobs import JobQueue
from app.registry import DEFAULT_PATH as REGISTRY_PATH, ModelRegistry
from app.store import Store
from app.upscale import run_fps, run_upscale, run_video_upscale
from app.video import VIDEO_HISTORY_TIMEOUT_S, run_video_generation
from app.vision import VisionService

# Re-exports y routers modulares (M17)
from app.routes.jobs import _JOBS, PROGRESS_KEYS, _empty_progress, _progress_ws_url, router as jobs_router
from app.routes.system import TEMPLATES_DIR, templates, router as system_router
from app.routes.models import (
    LORA_UPLOAD_MAX_BYTES, _decode_lora_b64, _lora_catalog, _lora_slug, _lora_upload_notes,
    _lora_upload_target, _require_lora_family, _require_lora_filename, add_lora, lora_file_path,
    router as models_router,
)
from app.routes.tags import TAGS_UNFILTERED_LIMIT, _clamp_tags_limit, router as tags_router
from app.routes.characters import router as characters_router, run_training_job
from app.routes.presets import router as presets_router
from app.routes.gallery import CHARACTER_MEDIA_TYPES, MEDIA_TYPES, MEDIA_URL, router as gallery_router
from app.routes.image import (
    DEFAULT_GRAPH_PATH, PARAM_KEYS, _decode_image_b64, _fit_reference, _merge_tags,
    _set_text_nodes, _write_input_png, run_generation, router as image_router,
)
from app.routes.editor import (
    EDITOR_MODEL, EDITOR_MODEL_FILES, EDITOR_NOTE, EDITOR_REF_LIMIT, EDITOR_SIZE_MAX,
    EDITOR_SIZE_MIN, EDITOR_SIZE_STEP, editor_installed, router as editor_router,
)
from app.routes.upscale import router as upscale_router
from app.routes.video import router as video_router
from app.routes.prompt import _ensure_vision_server, _get_manager, _manager, _manager_llm, router as prompt_router

APP_HOST = "127.0.0.1"
APP_PORT = 8765
STATIC_DIR = APP_ROOT / "static"
CHARACTER_REFS_DIRNAME = "characters"
_atexit_registered = False


def create_app(
    config: EngineConfig | None = None,
    store: Store | None = None,
    registry: ModelRegistry | None = None,
    engine_factory: Callable[[], Any] | None = None,
    llm: Callable[[str, str], str] | None = None,
    *,
    queue: JobQueue | None = None,
    start_worker: bool = True,
    character_store: CharacterStore | None = None,
    vision: VisionService | None = None,
) -> FastAPI:
    """Construye la app con todas sus dependencias inyectables."""
    cfg = config if config is not None else load_config()
    st = store if store is not None else Store(cfg.data_dir / "waifu.db")
    if store is None:
        st.init()
    chars = character_store if character_store is not None else CharacterStore(
        cfg.data_dir / "waifu.db", refs_root=cfg.data_dir / CHARACTER_REFS_DIRNAME
    )
    if character_store is None:
        chars.init()
    reg = registry if registry is not None else ModelRegistry.load(REGISTRY_PATH)
    factory = engine_factory if engine_factory is not None else (lambda: ComfyEngine(cfg))
    video_factory = (
        engine_factory if engine_factory is not None
        else (lambda: ComfyEngine(cfg, history_timeout_s=VIDEO_HISTORY_TIMEOUT_S))
    )

    def _dispatch(job: dict) -> None:
        kind = job.get("kind")
        if kind == "train":
            run_training_job(job, config=cfg, store=st, vision=vision_service)
        elif kind == "video":
            rec = _JOBS.setdefault(job["gen_id"], {"prompt_id": None, "tracker": None, "status": "queued", "engine": None, "kind": "video"})
            run_video_generation(job, config=cfg, store=st, engine_factory=video_factory, record=rec)
        elif kind == "editor":
            rec = _JOBS.setdefault(job["gen_id"], {"prompt_id": None, "tracker": None, "status": "queued", "engine": None, "kind": "editor"})
            run_editor_generation(job, config=cfg, store=st, engine_factory=factory, record=rec)
        elif kind == "upscale":
            rec = _JOBS.setdefault(job["gen_id"], {"prompt_id": None, "tracker": None, "status": "queued", "engine": None, "kind": "upscale"})
            task = job.get("task")
            if task == "upscale_video":
                run_video_upscale(job, config=cfg, store=st, engine_factory=video_factory, record=rec)
            elif task == "rife":
                run_fps(job, config=cfg, store=st, engine_factory=video_factory, record=rec)
            else:
                run_upscale(job, config=cfg, store=st, engine_factory=factory, record=rec)
        else:
            run_generation(job, config=cfg, store=st, registry=reg, engine_factory=factory)

    manager = _get_manager()
    default_server_url = manager.external_url() or manager.base_url
    vision_service = vision if vision is not None else VisionService(cfg.comfy_root, server_url=default_server_url)

    if queue is None:
        queue = JobQueue(_dispatch)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        global _atexit_registered
        if start_worker:
            st.fail_stale()
            queue.start()
            try:
                inp_dir = cfg.comfy_input_dir
                if inp_dir.exists():
                    for f in inp_dir.glob("*.png"):
                        if len(f.stem) == 32 or f.name.startswith("ref_"):
                            f.unlink(missing_ok=True)
            except Exception:
                pass
            if not _atexit_registered:
                _atexit_registered = True
                atexit.register(_get_manager().stop)
        try:
            yield
        finally:
            if start_worker:
                queue.stop()
                _get_manager().stop()

    app = FastAPI(title="WAIFU", lifespan=lifespan)
    app.state.config = cfg
    app.state.store = st
    app.state.registry = reg
    app.state.engine_factory = factory
    app.state.llm = llm
    app.state.queue = queue
    app.state.jobs = {}
    app.state.characters = chars
    app.state.vision = vision_service

    @app.middleware("http")
    async def _ui_no_store(request: Request, call_next):
        """`Cache-Control: no-store` para `/` y `/static/...` (nunca `/api`/`/media`)."""
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Registro de sub-routers modulares
    app.include_router(jobs_router)
    app.include_router(system_router)
    app.include_router(models_router)
    app.include_router(tags_router)
    app.include_router(characters_router)
    app.include_router(presets_router)
    app.include_router(gallery_router)
    app.include_router(upscale_router)
    app.include_router(prompt_router)
    app.include_router(image_router)
    app.include_router(video_router)
    app.include_router(editor_router)

    @app.exception_handler(EngineError)
    async def _engine_error(_request: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    return app


def main() -> int:
    """`python -m app.server`: uvicorn en 127.0.0.1 y puerto de WAIFU_APP_PORT."""
    import uvicorn

    mod = sys.modules.get("app.server")
    app_factory = getattr(mod, "create_app", create_app) if mod else create_app
    llm_factory = getattr(mod, "_manager_llm", _manager_llm) if mod else _manager_llm

    port_text = os.environ.get("WAIFU_APP_PORT", "").strip()
    port = int(port_text) if port_text else APP_PORT
    uvicorn.run(app_factory(llm=llm_factory()), host=APP_HOST, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "APP_HOST", "APP_PORT", "DEFAULT_GRAPH_PATH", "EDITOR_DEFAULT_CFG", "EDITOR_DEFAULT_STEPS",
    "EDITOR_MODEL", "EDITOR_MODEL_FILES", "PARAM_KEYS", "_JOBS", "_manager", "_manager_llm",
    "add_lora", "create_app", "editor_installed", "is_vdn_installed", "load_server_llm", "main",
    "run_generation", "run_training_job", "trainer",
]
