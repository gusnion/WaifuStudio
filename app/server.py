"""Webapp local FastAPI (F3b): API JSON, runner de generación y UI.

`create_app` inyecta todo (config, store, registry, engine_factory, llm, queue y
`start_worker`) para que los tests corran offline con un transporte falso: la
GPU y el LLM reales no se tocan. `run_generation` parchea el grafo base con el
modelo/params, copia los PNG a `data_dir/gallery/<gen_id>/` y refleja el estado
en el store; un fallo queda registrado en store y job sin propagarse al worker.

`_JOBS` es el registro en memoria de progreso/cancelación por `gen_id` (engine,
`prompt_id`, `ProgressTracker` y estado): vive solo en el proceso, se pierde al
reiniciar la app y no se comparte entre workers.
"""

from __future__ import annotations

import base64
import binascii
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import trainer
from app.characters import CharacterStore, is_sheet
from app.config import APP_ROOT, EngineConfig, load_config
from app.engine import ComfyEngine, EngineError, load_graph
from app.enhancer import DEFAULT_LLM_RELATIVE, DEFAULT_STRENGTH_PRESET, STRENGTH_PRESETS
from app.enhancer import apply_preprompt
from app.enhancer import enhance as enhance_prompt
from app.enhancer import load_local_llm
from app.formats import DEFAULT_FORMAT, get_size, list_image_formats
from app.graphs import (
    DEFAULT_STRENGTH,
    apply_loras,
    patch_model,
    patch_params,
    to_img2img,
)
from app.jobs import JobQueue
from app.loras import families as lora_families
from app.loras import list_loras, validate_selection
from app.motion import MOTION_NEGATIVE, write_motion
from app.oc_traits import build_prompt, list_traits
from app.params import (
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    SAMPLER_NAMES,
    SCHEDULER_NAMES,
    is_valid_sampler,
    is_valid_scheduler,
)
from app.preprompts import (
    DEFAULT_FAMILY,
    DEFAULT_PREPROMPT,
    delete_custom,
    get_preprompt,
    list_custom,
    list_preprompts,
    save_custom,
)
from app.prompt_zones import (
    compose_zones,
    insert_tag,
    prompt_options,
    split_zones,
    zones_payload,
)
from app.progress import ProgressTracker
from app.registry import DEFAULT_PATH as REGISTRY_PATH
from app.registry import ModelRegistry
from app.sheet import make_sheet
from app.store import Store
from app.tags import by_group, list_groups, search
from app.video import (
    ASPECTS,
    H3_TEMPLATE_PATH,
    VIDEO_HISTORY_TIMEOUT_S,
    WAN_FLF_TEMPLATE_PATH,
    WAN_TEMPLATE_PATH,
    frames_for_seconds,
    run_video_generation,
    vram_hint,
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
CHARACTER_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
CHARACTER_REFS_DIRNAME = "characters"
TAGS_UNFILTERED_LIMIT = 200
_JOBS: dict[int, dict] = {}
PROGRESS_KEYS = ("step", "total", "percent", "node", "state")


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


def _clamp_tags_limit(limit: int) -> int:
    """Clamp del limit de `/api/tags` a 1..200."""
    return max(1, min(int(limit), TAGS_UNFILTERED_LIMIT))


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
        graph = apply_loras(
            graph,
            validate_selection([] if raw_loras is None else raw_loras),
        )
        applied = {key: params[key] for key in PARAM_KEYS if params.get(key) is not None}
        graph = patch_params(graph, **applied)
        preprompt = job.get("preprompt") or entry.preprompt or DEFAULT_PREPROMPT
        positive, negative = apply_preprompt(
            job["prompt"], family=entry.family, name=preprompt
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


def run_training_job(job: dict, *, config: EngineConfig, store: Store) -> None:
    """Ejecuta un job de entrenamiento: trainer -> lora -> registry -> store.

    No propaga errores: el fallo se guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    try:
        result = trainer.train_character(
            job["char"],
            job["gen_ids"],
            store=store,
            config=config,
            trigger=job.get("trigger"),
            rank=job.get("rank", 16),
            epochs=job.get("epochs", 10),
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
) -> FastAPI:
    """Construye la app con todas sus dependencias inyectables.

    Defaults: `load_config()`, `Store(config.data_dir/'waifu.db')` con `init()`,
    `ModelRegistry.load(registry/models.json)`, `ComfyEngine(config)` y
    `CharacterStore` sobre la misma sqlite con refs en
    `config.data_dir/characters`. El lifespan arranca/para la cola salvo
    `start_worker=False` (tests).
    """
    cfg = config if config is not None else load_config()
    st = store if store is not None else Store(cfg.data_dir / "waifu.db")
    if store is None:
        st.init()
    chars = (
        character_store
        if character_store is not None
        else CharacterStore(
            cfg.data_dir / "waifu.db",
            refs_root=cfg.data_dir / CHARACTER_REFS_DIRNAME,
        )
    )
    if character_store is None:
        chars.init()
    reg = registry if registry is not None else ModelRegistry.load(REGISTRY_PATH)
    factory = engine_factory if engine_factory is not None else (lambda: ComfyEngine(cfg))
    video_factory = (
        engine_factory
        if engine_factory is not None
        else (lambda: ComfyEngine(cfg, history_timeout_s=VIDEO_HISTORY_TIMEOUT_S))
    )

    def _dispatch(job: dict) -> None:
        if job.get("kind") == "train":
            run_training_job(job, config=cfg, store=st)
        elif job.get("kind") == "video":
            record = _JOBS.setdefault(
                job["gen_id"],
                {
                    "prompt_id": None,
                    "tracker": None,
                    "status": "queued",
                    "engine": None,
                    "kind": "video",
                },
            )
            run_video_generation(
                job,
                config=cfg,
                store=st,
                engine_factory=video_factory,
                record=record,
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
    app.state.characters = chars

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

    @app.get("/api/loras")
    async def api_loras(family: str | None = None) -> dict:
        return {"items": list_loras(family), "families": lora_families()}

    @app.get("/api/preprompts")
    async def api_preprompts(family: str = DEFAULT_FAMILY) -> dict:
        names = list_preprompts(family)
        try:
            custom = sorted(list_custom())
        except EngineError:
            custom = []
        return {
            "family": family,
            "names": names,
            "custom": custom,
            "default": DEFAULT_PREPROMPT,
        }

    @app.post("/api/preprompts/custom")
    async def api_preprompt_custom_add(payload: dict = Body(...)) -> dict:
        negative = payload.get("negative")
        name = save_custom(
            payload.get("name"),
            payload.get("positive"),
            "" if negative is None else negative,
        )
        return {"name": name}

    @app.delete("/api/preprompts/custom/{name}")
    async def api_preprompt_custom_delete(name: str) -> Any:
        if not delete_custom(name):
            return JSONResponse(
                status_code=404, content={"error": "preprompt propio desconocido"}
            )
        return {"deleted": True}

    @app.get("/api/traits")
    async def api_traits() -> dict:
        return list_traits()

    @app.get("/api/tags/groups")
    async def api_tags_groups() -> dict:
        return {"groups": list_groups()}

    @app.get("/api/tags")
    async def api_tags(
        group: str | None = None,
        q: str | None = None,
        limit: int = TAGS_UNFILTERED_LIMIT,
    ) -> dict:
        limit = _clamp_tags_limit(limit)
        if group:
            items = by_group(group)
            if q:
                needle = q.strip().lower()
                items = [
                    item
                    for item in items
                    if needle in item["tag"].lower() or needle in item["label"].lower()
                ]
        else:
            items = search(q if q is not None else "", limit=limit)
        return {"items": items[:limit]}

    @app.get("/api/characters")
    async def api_characters() -> list[dict]:
        return chars.list()

    @app.post("/api/characters")
    async def api_character_add(payload: dict = Body(...)) -> Any:
        char_id = chars.add(
            payload.get("name"),
            payload.get("tags") if payload.get("tags") is not None else [],
            preprompt=payload.get("preprompt") or DEFAULT_PREPROMPT,
            rating=payload.get("rating") or "sfw",
            notes=payload.get("notes") or "",
        )
        return {"id": char_id}

    @app.get("/api/characters/{char_id}")
    async def api_character_get(char_id: int) -> Any:
        row = chars.get(char_id)
        if row is None:
            return JSONResponse(status_code=404, content={"error": "OC desconocido"})
        return row

    @app.put("/api/characters/{char_id}")
    async def api_character_update(char_id: int, payload: dict = Body(...)) -> Any:
        if chars.get(char_id) is None:
            return JSONResponse(status_code=404, content={"error": "OC desconocido"})
        fields = {
            key: payload[key]
            for key in ("name", "tags", "preprompt", "rating", "notes")
            if key in payload
        }
        chars.update(char_id, **fields)
        return chars.get(char_id)

    @app.delete("/api/characters/{char_id}")
    async def api_character_delete(char_id: int) -> Any:
        if not chars.delete(char_id):
            return JSONResponse(status_code=404, content={"error": "OC desconocido"})
        return {"deleted": True}

    @app.post("/api/characters/{char_id}/refs")
    async def api_character_ref_add(char_id: int, payload: dict = Body(...)) -> Any:
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

    @app.get("/api/characters/{char_id}/refs")
    async def api_character_refs(char_id: int) -> Any:
        if chars.get(char_id) is None:
            return JSONResponse(status_code=404, content={"error": "OC desconocido"})
        items = []
        for ref in chars.refs(char_id):
            item = dict(ref)
            item["url"] = f"/media/characters/{char_id}/{Path(ref['relpath']).name}"
            item["is_sheet"] = is_sheet(ref["relpath"])
            items.append(item)
        return items

    @app.post("/api/characters/{char_id}/sheet")
    async def api_character_sheet(
        char_id: int, payload: dict | None = Body(default=None)
    ) -> Any:
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

    @app.delete("/api/characters/{char_id}/refs/{ref_id}")
    async def api_character_ref_delete(char_id: int, ref_id: int) -> Any:
        if chars.get(char_id) is None:
            return JSONResponse(status_code=404, content={"error": "OC desconocido"})
        if not chars.remove_ref(char_id, ref_id):
            return JSONResponse(
                status_code=404, content={"error": "referencia desconocida"}
            )
        return {"deleted": True}

    @app.post("/api/characters/{char_id}/train")
    async def api_character_train(char_id: int, payload: dict = Body(...)) -> Any:
        """Valida y encola un job `kind="train"` para el OC (M9-E1)."""
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
        }
        _JOBS[gen_id] = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
            "kind": "train",
        }
        job_id = queue.submit(job)
        app.state.jobs[job_id] = job
        return {"job_id": job_id}

    @app.get("/api/params")
    async def api_params() -> dict:
        return {
            "samplers": list(SAMPLER_NAMES),
            "schedulers": list(SCHEDULER_NAMES),
            "default_sampler": DEFAULT_SAMPLER,
            "default_scheduler": DEFAULT_SCHEDULER,
        }

    @app.get("/api/formats")
    async def api_formats() -> dict:
        return {"formats": list_image_formats(), "default": DEFAULT_FORMAT}

    @app.get("/api/negative")
    async def api_negative(
        preprompt: str = DEFAULT_PREPROMPT, family: str = DEFAULT_FAMILY
    ) -> dict:
        _positive, negative = apply_preprompt("", family=family, name=preprompt)
        return {"negative": negative}

    @app.post("/api/prompt/build")
    async def api_prompt_build(payload: dict = Body(...)) -> dict:
        return {"prompt": build_prompt(payload.get("trait_ids"))}

    @app.post("/api/prompt/zones")
    async def api_prompt_zones(payload: dict = Body(...)) -> Any:
        text = payload.get("text")
        if not isinstance(text, str):
            raise EngineError("text requerido")
        zones = split_zones(text)
        return {"zones": zones_payload(text), "composed": compose_zones(zones)}

    @app.get("/api/prompt/options")
    async def api_prompt_options(zone: str | None = None) -> Any:
        return prompt_options(zone)

    @app.post("/api/prompt/compose")
    async def api_prompt_compose(payload: dict = Body(...)) -> Any:
        zones = payload.get("zones")
        if not isinstance(zones, dict):
            raise EngineError("zones requerido (objeto por zona)")
        return {"text": compose_zones(zones)}

    @app.post("/api/prompt/insert")
    async def api_prompt_insert(payload: dict = Body(...)) -> Any:
        text = payload.get("text")
        if not isinstance(text, str):
            raise EngineError("text requerido")
        tag = payload.get("tag")
        if not isinstance(tag, str) or not tag.strip():
            raise EngineError("tag requerido")
        return {"text": insert_tag(text, tag, payload.get("zone"))}

    @app.post("/api/enhance")
    async def api_enhance(payload: dict = Body(...)) -> Any:
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
                if value is None:
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    return JSONResponse(
                        status_code=400, content={"error": f"{name} invalido"}
                    )
                if not number.is_integer():
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": f"{name} fuera de [64, 4096] o no multiplo de 8"
                        },
                    )
                number = int(number)
                if not 64 <= number <= 4096 or number % 8:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": f"{name} fuera de [64, 4096] o no multiplo de 8"
                        },
                    )
                if name == "width":
                    width = number
                else:
                    height = number
        if width is not None:
            params = {**params, "width": width}
        if height is not None:
            params = {**params, "height": height}
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
            input_dir = cfg.comfy_root / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            ref_image = f"{uuid.uuid4().hex}.png"
            (input_dir / ref_image).write_bytes(raw)
        if ref_image is not None and strength is None:
            strength = DEFAULT_STRENGTH
        stored_params = dict(params)
        stored_params["preprompt"] = preprompt
        stored_params["rating"] = rating
        stored_params["loras"] = loras
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
        app.state.jobs[job_id] = job
        return {"job_id": job_id}

    @app.post("/api/video/generate")
    async def api_video_generate(payload: dict = Body(...)) -> Any:
        """Encola un video (M9-F1): mode i2v|flf2v, segundos y negativo editable.

        `engine` sigue siendo `wan|h3`; si falta la clave, default `wan` (el
        `mode` de Wan elige plantilla I2V o FLF2V y `seconds` fija los frames
        4n+1). La respuesta añade `frames` y `vram_hint` (tabla de 12 GB).
        """
        if "engine" in payload:
            engine_kind = payload.get("engine")
        else:
            engine_kind = "wan"
        if engine_kind not in ("wan", "h3"):
            raise EngineError("engine invalido; usar wan|h3")
        mode = payload.get("mode") or "i2v"
        if mode not in ("i2v", "flf2v"):
            raise EngineError("mode invalido; usar i2v|flf2v")
        if engine_kind == "h3" and mode != "i2v":
            raise EngineError("mode flf2v solo aplica a engine wan")
        aspect = payload.get("aspect") or "vertical"
        if aspect not in ASPECTS:
            raise EngineError("aspect invalido; usar vertical|horizontal")
        seconds = payload.get("seconds")
        if seconds is None:
            seconds = 5
        if isinstance(seconds, bool):
            raise EngineError("seconds invalido; usar un numero entre 1 y 15")
        try:
            seconds = float(seconds)
        except (TypeError, ValueError) as exc:
            raise EngineError("seconds invalido; usar un numero entre 1 y 15") from exc
        frames = frames_for_seconds(seconds)
        width, height = ASPECTS[aspect]
        hint = vram_hint(frames, width, height)
        first_raw = _decode_image_b64(payload.get("image_b64"), "image")
        last_raw = None
        if engine_kind == "h3" or mode == "flf2v":
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
        input_dir = cfg.comfy_root / "input"
        image_name = _write_input_png(input_dir, first_raw)
        last_image_name = (
            _write_input_png(input_dir, last_raw) if last_raw is not None else None
        )
        if engine_kind == "h3":
            template = H3_TEMPLATE_PATH
        elif mode == "flf2v":
            template = WAN_FLF_TEMPLATE_PATH
        else:
            template = WAN_TEMPLATE_PATH
        gen_id = st.add(
            engine_kind,
            motion_positive if engine_kind == "wan" else prompt,
            motion_negative,
            {
                "engine": engine_kind,
                "mode": mode,
                "aspect": aspect,
                "seconds": seconds,
                "frames": frames,
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
            "mode": mode,
            "template": str(template),
            "image_name": image_name,
            "last_image_name": last_image_name,
            "motion_positive": motion_positive,
            "motion_negative": motion_negative,
            "prompt": prompt,
            "aspect": aspect,
            "seconds": seconds,
            "frames": frames,
            "seed": seed,
        }
        _JOBS[gen_id] = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
            "kind": "video",
        }
        job_id = queue.submit(job)
        app.state.jobs[job_id] = job
        return {"job_id": job_id, "frames": frames, "vram_hint": hint}

    @app.get("/api/jobs/{job_id}")
    async def api_job(job_id: str) -> Any:
        try:
            status = queue.status(job_id)
        except EngineError:
            return JSONResponse(status_code=404, content={"error": "job desconocido"})
        job = app.state.jobs.get(job_id) or {}
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
        }

    @app.post("/api/jobs/{job_id}/cancel")
    async def api_job_cancel(job_id: str) -> Any:
        """Cancela un job (imagen o video); los registros de `_JOBS` viven en memoria.

        Misma semántica que imagen (M9-F1): `queued` borra del engine con
        `delete_queued`, `running` interrumpe; el train sigue devolviendo 409.
        """
        try:
            queue_status = queue.status(job_id)
        except EngineError:
            return JSONResponse(status_code=404, content={"error": "job desconocido"})
        job = app.state.jobs.get(job_id) or {}
        gen_id = job.get("gen_id")
        record = _JOBS.get(gen_id)
        row = store.get(gen_id) if gen_id is not None else None
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
        if gen_id is not None:
            store.update(gen_id, status="cancelled")
        return {"status": "cancelled"}

    @app.get("/api/gallery")
    async def api_gallery(limit: int = 24, offset: int = 0) -> dict:
        limit = max(1, min(int(limit), 24))
        offset = max(0, int(offset))
        items = []
        for row in st.list(limit=limit, offset=offset, order="desc"):
            item = dict(row)
            item["urls"] = [
                MEDIA_URL.format(gen_id=row["id"], name=name)
                for name in (row.get("outputs") or [])
            ]
            items.append(item)
        return {"items": items, "count": st.count()}

    @app.get("/media/characters/{char_id}/{name:path}")
    async def api_character_media(char_id: int, name: str) -> Any:
        refs_root = Path(chars.refs_root).resolve()
        candidate = (refs_root / str(char_id) / name).resolve()
        if not candidate.is_relative_to(refs_root):
            return JSONResponse(
                status_code=403, content={"error": "ruta fuera de las referencias"}
            )
        media_type = CHARACTER_MEDIA_TYPES.get(candidate.suffix.lower())
        if media_type is None or not candidate.is_file():
            return JSONResponse(status_code=404, content={"error": "no encontrado"})
        return FileResponse(candidate, media_type=media_type)

    @app.get("/api/refs/{name:path}")
    async def api_ref(name: str) -> Any:
        """Sirve una referencia guardada de `comfy_root/input` (solo imagenes).

        Confinamiento estricto al directorio input: 403 si la ruta escapa o la
        extension no es png/jpg/jpeg/webp, 404 si el archivo no existe. La UI lo
        usa para re-adjuntar la referencia guardada en `params.ref_image`.
        """
        input_root = (cfg.comfy_root / "input").resolve()
        candidate = (input_root / name).resolve()
        if not candidate.is_relative_to(input_root):
            return JSONResponse(
                status_code=403, content={"error": "ruta fuera de comfy input"}
            )
        media_type = CHARACTER_MEDIA_TYPES.get(candidate.suffix.lower())
        if media_type is None:
            return JSONResponse(
                status_code=403, content={"error": "extension no permitida"}
            )
        if not candidate.is_file():
            return JSONResponse(status_code=404, content={"error": "no encontrado"})
        return FileResponse(candidate, media_type=media_type)

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


LIVE_LLM_ENV = "WAIFU_LLM_MODEL"


def _live_llm_path() -> str | None:
    """GGUF de la app en vivo: `WAIFU_LLM_MODEL`, si no el Q4_K_M hermano.

    El Q3_K_M por defecto del enhancer degenera con el prompt de motion (spam
    CJK tras la primera frase); el Q4_K_M del mismo directorio escribe ingles
    limpio. `None` deja el default de `load_local_llm` (Q3_K_M).
    """
    override = os.environ.get(LIVE_LLM_ENV, "").strip()
    if override:
        return override
    q3 = load_config().comfy_root / DEFAULT_LLM_RELATIVE
    q4 = q3.with_name(q3.name.replace(".Q3_K_M.gguf", ".Q4_K_M.gguf"))
    return str(q4) if q4 != q3 and q4.is_file() else None


def _lazy_llm() -> Callable[[str, str], str]:
    """LLM local perezoso: carga el GGUF en la primera llamada (CPU, sin GPU).

    El servidor arranca al instante y el coste de carga lo paga la primera
    peticion a `/api/enhance` o `/api/motion`.
    """
    loaded: list[Callable[..., str]] = []

    def llm(system: str, user: str, temperature: float | None = None) -> str:
        if not loaded:
            loaded.append(load_local_llm(_live_llm_path()))
        return loaded[0](system, user, temperature=temperature)

    return llm


def main() -> int:
    """`python -m app.server`: uvicorn en 127.0.0.1 y puerto de WAIFU_APP_PORT."""
    import uvicorn

    port_text = os.environ.get("WAIFU_APP_PORT", "").strip()
    port = int(port_text) if port_text else APP_PORT
    uvicorn.run(create_app(llm=_lazy_llm()), host=APP_HOST, port=port, log_level="info")
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
    "run_training_job",
]
