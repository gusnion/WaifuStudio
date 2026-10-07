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

import atexit
import base64
import binascii
import os
import re
import shutil
import threading
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
    run_editor_generation,
)
from app.editor_models import editor_model
from app.engine import ComfyEngine, EngineError, load_graph
from app.enhancer import DEFAULT_STRENGTH_PRESET, STRENGTH_PRESETS
from app.enhancer import apply_preprompt
from app.enhancer import enhance as enhance_prompt
from app.enhancer import load_server_llm
from app.formats import DEFAULT_FORMAT, get_size, list_image_formats
from app.graphs import (
    DEFAULT_STRENGTH,
    apply_loras,
    patch_model,
    patch_params,
    to_img2img,
)
from app.h3_presets import (
    h3_aspect,
    h3_catalog,
    h3_default_size,
    h3_frames_for_seconds,
    h3_template_path,
    require_h3_seconds,
    resolve_h3_profile,
    resolve_h3_variant,
    validate_h3_size,
)
from app.jobs import JobQueue
from app.loras import add_entry as add_lora
from app.loras import delete_entry as delete_lora
from app.loras import families as lora_families
from app.loras import get as get_lora
from app.loras import inspect_safetensors
from app.loras import list_loras
from app.loras import safetensors_header
from app.loras import update_entry as update_lora
from app.loras import validate_selection
from app.llm_server import LlamaServerManager
from app.h3_prompt import write_h3_prompt
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
    ZONE_ORDER,
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
from app.tags import (
    add_custom_tag,
    by_group,
    delete_custom_tag,
    list_custom_tags,
    list_groups,
    load_catalog,
    search,
)
from app.upscale import (
    fps_ckpt,
    fps_multiplier,
    frame_interpolation,
    get_upscaler,
    list_upscalers,
    parse_fps,
    parse_passes,
    parse_sharpen,
    run_fps,
    run_upscale,
    run_video_upscale,
)
from app.video import (
    ASPECTS,
    VIDEO_HISTORY_TIMEOUT_S,
    WAN_FLF_TEMPLATE_PATH,
    WAN_TEMPLATE_PATH,
    frames_for_seconds,
    resolve_wan_profile,
    run_video_generation,
    vram_hint,
)
from app.video_presets import PRESET_MANUAL, list_video_presets
from app.vision import WD14_THRESHOLD, VisionService, VisionUnavailable

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
# Catalogo del Editor (M10-6b): nombres reales del par UC en
# registry/editor_models-v1.json; el VAE del editor (qwen_image_2.1_vae_bf16)
# no es el de Anima (qwen_image_vae) y no lo pisa.
_EDITOR = editor_model()
EDITOR_MODEL = _EDITOR.id
EDITOR_MODEL_FILES = _EDITOR.files
EDITOR_NOTE = _EDITOR.note
EDITOR_REF_LIMIT = 10
EDITOR_SIZE_MIN = 512
EDITOR_SIZE_MAX = 2048
EDITOR_SIZE_STEP = 16
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


def lora_file_path(comfy_root: Any, relative: object) -> Path:
    """Resuelve ``file`` de una LoRA dentro de ``models/loras`` (M10-5b).

    ``relative`` debe ser texto no vacio y quedarse dentro de la raiz (nada de
    absolutos ni ``..``); el fichero debe existir. EngineError (400) en caso
    contrario. No escanea el directorio: solo confina y comprueba existencia.
    """
    if not isinstance(relative, str) or not relative.strip():
        raise EngineError(f"file de lora requerido (recibido {relative!r})")
    if Path(relative).is_absolute():
        raise EngineError(
            f"file de lora debe ser relativo a models/loras: {relative!r}"
        )
    root = (Path(comfy_root) / "models" / "loras").resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise EngineError(f"ruta de lora fuera de models/loras: {relative!r}")
    if not candidate.is_file():
        raise EngineError(f"archivo de lora no encontrado: {relative!r}")
    return candidate


LORA_UPLOAD_MAX_BYTES = int(2.5 * 1024 * 1024 * 1024)
_LORA_FAMILY_RE = re.compile(r"[a-z0-9._-]+")
_LORA_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _lora_slug(text: str) -> str:
    """Slug de id para un stem: minusculas, resto a ``-`` y recortado."""
    return _LORA_SLUG_RE.sub("-", text.lower()).strip("-") or "lora"


def _require_lora_filename(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"filename requerido (recibido {value!r})")
    if "/" in value or "\\" in value or "\x00" in value:
        raise EngineError(f"filename debe ser un nombre sin rutas: {value!r}")
    if (
        value in (".", "..")
        or not value.lower().endswith(".safetensors")
        or value.lower() == ".safetensors"
    ):
        raise EngineError(f"filename debe terminar en .safetensors: {value!r}")
    return value


def _require_lora_family(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"family requerida (recibido {value!r})")
    if _LORA_FAMILY_RE.fullmatch(value) is None or value in (".", ".."):
        raise EngineError(f"family invalida: {value!r} (solo [a-z0-9._-]+)")
    return value


def _decode_lora_b64(value: object) -> bytes:
    """Decodifica ``file_b64`` (data URI opcional) con limite de tamaño."""
    if not isinstance(value, str) or not value.strip():
        raise EngineError("file_b64 requerido (base64 del .safetensors)")
    text = "".join(value.split())
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    if len(text) > (LORA_UPLOAD_MAX_BYTES * 4) // 3 + 16:
        raise EngineError(
            f"archivo demasiado grande (max {LORA_UPLOAD_MAX_BYTES} bytes)"
        )
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EngineError(f"file_b64 no es base64 valido: {exc}") from exc
    if not raw:
        raise EngineError("file_b64 decodifica vacio")
    if len(raw) > LORA_UPLOAD_MAX_BYTES:
        raise EngineError(
            f"archivo demasiado grande: {len(raw)} bytes "
            f"(max {LORA_UPLOAD_MAX_BYTES})"
        )
    return raw


def _lora_upload_target(comfy_root: Any, family: str, filename: str) -> Path:
    root = (Path(comfy_root) / "models" / "loras").resolve()
    target = (root / family / filename).resolve()
    if not target.is_relative_to(root):
        raise EngineError(f"destino de lora fuera de models/loras: {family}/{filename}")
    return target


def _lora_upload_notes(inferred: dict) -> str:
    parts: list[str] = []
    dim = inferred["dim"]
    alpha = inferred["alpha"]
    if dim is not None and alpha is not None:
        parts.append(f"dim {dim} / alpha {alpha}")
    elif dim is not None:
        parts.append(f"dim {dim}")
    elif alpha is not None:
        parts.append(f"alpha {alpha}")
    if inferred["base"]:
        parts.append(f"base {inferred['base']}")
    parts.append("trigger inferido del safetensors (editable)")
    return "; ".join(parts)


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
            model_id=job.get("model_id"),
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


_manager_lock = threading.Lock()
_manager_instance: LlamaServerManager | None = None
_atexit_registered = False


def _manager() -> LlamaServerManager:
    """Manager unico del `llama-server` gestionado (creado con `APP_ROOT`)."""
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = LlamaServerManager(APP_ROOT)
        return _manager_instance


def _manager_llm() -> Callable[[str, Any], str]:
    """LLM perezoso contra el servidor gestionado (o externo si hay env).

    El primer uso llama a `_manager().ensure()`, que arranca `llama-server`
    si hace falta; el cliente HTTP acepta `temperature` por kwarg.
    """

    def llm(system: str, user: Any, temperature: float | None = None) -> str:
        client = load_server_llm(_manager().ensure())
        return client(system, user, temperature=temperature)

    return llm


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
            run_training_job(job, config=cfg, store=st, vision=vision_service)
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
        elif job.get("kind") == "editor":
            record = _JOBS.setdefault(
                job["gen_id"],
                {
                    "prompt_id": None,
                    "tracker": None,
                    "status": "queued",
                    "engine": None,
                    "kind": "editor",
                },
            )
            run_editor_generation(
                job,
                config=cfg,
                store=st,
                engine_factory=factory,
                record=record,
            )
        elif job.get("kind") == "upscale":
            record = _JOBS.setdefault(
                job["gen_id"],
                {
                    "prompt_id": None,
                    "tracker": None,
                    "status": "queued",
                    "engine": None,
                    "kind": "upscale",
                },
            )
            if job.get("task") == "upscale_video":
                run_video_upscale(
                    job,
                    config=cfg,
                    store=st,
                    engine_factory=video_factory,
                    record=record,
                )
            elif job.get("task") == "rife":
                run_fps(
                    job,
                    config=cfg,
                    store=st,
                    engine_factory=video_factory,
                    record=record,
                )
            else:
                run_upscale(
                    job,
                    config=cfg,
                    store=st,
                    engine_factory=factory,
                    record=record,
                )
        else:
            run_generation(
                job, config=cfg, store=st, registry=reg, engine_factory=factory
            )

    manager = _manager()
    default_server_url = manager.external_url() or manager.base_url
    vision_service = (
        vision
        if vision is not None
        else VisionService(cfg.comfy_root, server_url=default_server_url)
    )

    def _ensure_vision_server() -> None:
        """Arranca el `llama-server` antes de un caption que use servidor (M12-4).

        Inocuo en modo externo (`ensure()` devuelve la URL sin arrancar nada) y
        en vision local sin `server_url` (no se llama). Si falla, el EngineError
        del manager se propaga con su mensaje.
        """
        if getattr(vision_service, "server_url", None):
            _manager().ensure()

    if queue is None:
        queue = JobQueue(_dispatch)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        global _atexit_registered
        if start_worker:
            st.fail_stale()
            queue.start()
            if not _atexit_registered:
                _atexit_registered = True
                atexit.register(_manager().stop)
        try:
            yield
        finally:
            if start_worker:
                queue.stop()
                _manager().stop()

    app = FastAPI(title="WAIFU", lifespan=lifespan)
    app.state.config = cfg
    app.state.store = st
    app.state.registry = reg
    app.state.engine_factory = factory
    app.state.llm = llm
    app.state.queue = queue
    app.state.jobs = {}
    app.state.characters = chars

    @app.middleware("http")
    async def _ui_no_store(request: Request, call_next):
        """`Cache-Control: no-store` para `/` y `/static/...` (nunca `/api`/`/media`)."""
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

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

    def _lora_catalog() -> dict:
        return {"items": list_loras(), "families": lora_families()}

    @app.post("/api/loras")
    async def api_loras_add(payload: dict = Body(...)) -> Any:
        """Crea una entrada: id unico, fichero existente y confinado (M10-5b)."""
        lora_id = payload.get("id")
        if any(item["id"] == lora_id for item in list_loras()):
            return JSONResponse(
                status_code=409, content={"error": f"id duplicado: {lora_id!r}"}
            )
        lora_file_path(cfg.comfy_root, payload.get("file"))
        item = add_lora(payload)
        return {"item": item, **_lora_catalog()}

    @app.post("/api/loras/upload")
    async def api_loras_upload(payload: dict = Body(...)) -> Any:
        """Copia un .safetensors a models/loras y lo registra (M10-5c)."""
        filename = _require_lora_filename(payload.get("filename"))
        family = _require_lora_family(payload.get("family"))
        raw = _decode_lora_b64(payload.get("file_b64"))
        if safetensors_header(raw) is None:
            raise EngineError("cabecera safetensors invalida")
        target = _lora_upload_target(cfg.comfy_root, family, filename)
        relative = f"{family}/{filename}"
        if target.exists():
            return JSONResponse(
                status_code=409,
                content={"error": f"ya existe ese archivo en loras/{relative}"},
            )
        inferred = inspect_safetensors(raw)
        title = inferred["title"].strip()
        display_name = payload.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = title or filename[: -len(".safetensors")]
        else:
            display_name = display_name.strip()
        trigger = payload.get("trigger")
        if not isinstance(trigger, str) or not trigger.strip():
            trigger = inferred["trigger"]
        else:
            trigger = trigger.strip()
        stem = filename[: -len(".safetensors")]
        existing = {item["id"] for item in list_loras()}
        lora_id = _lora_slug(stem)
        if lora_id in existing:
            suffix = 2
            while f"{lora_id}-{suffix}" in existing:
                suffix += 1
            lora_id = f"{lora_id}-{suffix}"
        entry = {
            "id": lora_id,
            "family": family,
            "file": f"{family}\\{filename}",
            "display_name": display_name,
            "trigger": trigger,
            "default_weight": 1.0,
            "source": "subido desde la app",
            "license": "no verificada (archivo del usuario)",
            "notes": _lora_upload_notes(inferred),
        }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        except OSError as exc:
            raise EngineError(
                f"no se pudo copiar el archivo a models/loras: {exc}"
            ) from exc
        try:
            item = add_lora(entry)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {
            "item": item,
            "file": entry["file"],
            "trigger_inferido": inferred["trigger"],
        }

    @app.put("/api/loras/{lora_id}")
    async def api_loras_update(lora_id: str, payload: dict = Body(...)) -> Any:
        """Edita una entrada existente; el id es inmutable (M10-5b)."""
        try:
            get_lora(lora_id)
        except EngineError:
            return JSONResponse(
                status_code=404, content={"error": f"lora no registrado: {lora_id!r}"}
            )
        if "id" in payload and payload["id"] != lora_id:
            return JSONResponse(
                status_code=400, content={"error": f"id inmutable: {lora_id!r}"}
            )
        if "file" in payload:
            lora_file_path(cfg.comfy_root, payload.get("file"))
        item = update_lora(lora_id, payload)
        return {"item": item, **_lora_catalog()}

    @app.delete("/api/loras/{lora_id}")
    async def api_loras_delete(lora_id: str, file: bool = False) -> Any:
        """Quita la entrada; con ``file=1`` borra ademas el .safetensors (M10-5c)."""
        try:
            entry = get_lora(lora_id)
        except EngineError:
            return JSONResponse(
                status_code=404, content={"error": f"lora no registrado: {lora_id!r}"}
            )
        file_removed = False
        if file:
            root = (Path(cfg.comfy_root) / "models" / "loras").resolve()
            target = (root / entry["file"]).resolve()
            if not target.is_relative_to(root):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": f"ruta de lora fuera de models/loras: {entry['file']!r}"
                    },
                )
            if target.is_file():
                try:
                    target.unlink()
                except OSError as exc:
                    raise EngineError(
                        f"no se pudo borrar el archivo de lora: {exc}"
                    ) from exc
                file_removed = True
        item = delete_lora(lora_id)
        return {
            "deleted": item["id"],
            "file_removed": file_removed,
            **_lora_catalog(),
        }

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

    @app.get("/api/tags/custom")
    async def api_tags_custom_list() -> list[dict]:
        return list_custom_tags()

    @app.post("/api/tags/custom")
    async def api_tags_custom_add(payload: dict = Body(...)) -> Any:
        name = payload.get("name") if isinstance(payload, dict) else None
        if not isinstance(name, str) or not name.strip():
            return JSONResponse(
                status_code=400, content={"error": "nombre de tag requerido y no vacio"}
            )
        category = payload.get("category") or "general"
        count = payload.get("count", 100)
        try:
            created = add_custom_tag(name=name, category=category, count=count)
        except EngineError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        return {"ok": True, "tag": created}

    @app.delete("/api/tags/custom/{name}")
    async def api_tags_custom_delete(name: str) -> Any:
        if not name or not name.strip():
            return JSONResponse(
                status_code=400, content={"error": "nombre de tag requerido"}
            )
        deleted = delete_custom_tag(name)
        if not deleted:
            return JSONResponse(
                status_code=404, content={"error": "tag personalizada no encontrada"}
            )
        return {"ok": True, "name": name}

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
            extras=payload.get("extras"),
        )
        return {"id": char_id}

    @app.get("/api/characters/{char_id}")
    async def api_character_get(char_id: int) -> Any:
        row = chars.get(char_id)
        if row is None:
            return JSONResponse(status_code=404, content={"error": "OC desconocido"})
        return row

    @app.get("/api/characters/{char_id}/profile")
    async def api_character_profile(char_id: int, mode: str = "auto") -> Any:
        """Perfil del OC (M9-B3): trigger/rasgos, extras y LoRA oc-<id>."""
        if chars.get(char_id) is None:
            return JSONResponse(status_code=404, content={"error": "OC desconocido"})
        return chars.profile(char_id, mode)

    @app.put("/api/characters/{char_id}")
    async def api_character_update(char_id: int, payload: dict = Body(...)) -> Any:
        if chars.get(char_id) is None:
            return JSONResponse(status_code=404, content={"error": "OC desconocido"})
        fields = {
            key: payload[key]
            for key in ("name", "tags", "extras", "preprompt", "rating", "notes")
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

    @app.get("/api/video/presets")
    async def api_video_presets() -> dict:
        """Presets de video Wan (M10-2a): id/label/note + tamano y perfil."""
        items = []
        for preset in list_video_presets():
            item = dict(preset)
            item["profile"] = {
                "sampler": preset["sampler"],
                "scheduler": preset["scheduler"],
                "steps": preset["steps"],
                "shift": preset["shift"],
            }
            items.append(item)
        return {"items": items, "presets": items}

    @app.get("/api/video/h3_profiles")
    async def api_video_h3_profiles() -> dict:
        """Perfiles H3 (M10-2c-1): catalogo + variantes, segundos y resoluciones."""
        catalog = h3_catalog()
        items = catalog["profiles"]
        return {
            "items": items,
            "profiles": items,
            "variants": catalog["variants"],
            "seconds": catalog["seconds"],
            "resolutions": catalog["resolutions"],
        }

    @app.get("/api/upscale/models")
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

    @app.post("/api/upscale")
    async def api_upscale(payload: dict = Body(...)) -> Any:
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
            app.state.jobs[job_id] = job
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
        app.state.jobs[job_id] = job
        return {"job_id": job_id}

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
        return {
            "positive": result["positive"],
            "negative": result["negative"],
            "dropped": result["dropped"],
        }

    @app.post("/api/prompt/enhance_zones")
    async def api_prompt_enhance_zones(payload: dict = Body(...)) -> Any:
        """«Mejorar prompt» por zonas (M9-C3a): positivo clasificado para el editor.

        Valida `text` no vacío, `zone` (si viene) de `ZONE_ORDER`, `strength`
        de `STRENGTH_PRESETS` y `rating` `sfw|nsfw` (ausente -> `sfw`): 400 con
        `{"error"}`. Sin LLM -> 503 con el mismo mensaje que `/api/enhance`.
        `zone` viaja como `zone_hint` al enhancer y el positivo resultante se
        reparte con `split_zones`/`zones_payload`; la respuesta es
        `{raw, positive, negative, composed, zones}` con `composed` canónico y
        `zones` el payload del editor (con `subcats` en general).
        """
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

    @app.post("/api/motion")
    async def api_motion(payload: dict = Body(...)) -> Any:
        if llm is None:
            return JSONResponse(status_code=503, content={"error": "LLM no disponible"})
        return write_motion(
            payload.get("text"),
            rating=str(payload.get("rating") or "nsfw"),
            llm=llm,
        )

    @app.post("/api/video/h3_prompt")
    async def api_video_h3_prompt(payload: dict = Body(...)) -> Any:
        if llm is None:
            return JSONResponse(status_code=503, content={"error": "LLM no disponible"})
        image_b64 = payload.get("image_b64")
        if image_b64 is not None and not isinstance(image_b64, str):
            image_b64 = None
        images_b64 = payload.get("images_b64")
        if images_b64 is not None and not isinstance(images_b64, list):
            images_b64 = None
        return write_h3_prompt(
            payload.get("text"),
            rating=str(payload.get("rating") or "nsfw"),
            llm=llm,
            image_b64=image_b64,
            images_b64=images_b64,
        )

    @app.get("/api/vision/status")
    async def api_vision_status() -> dict:
        return vision_service.status()

    @app.get("/api/llm/status")
    async def api_llm_status() -> dict:
        """Estado del LLM: externo si `WAIFU_LLM_URL`; si no, gestionado (M12-3)."""
        return _manager().status()

    @app.post("/api/vision/image_to_prompt")
    async def api_vision_image_to_prompt(payload: dict = Body(...)) -> Any:
        """Tags WD14 y/o caption VL de una imagen (galeria por `gen_id` o base64).

        Con `mode` (`unified|tags|caption`) se ignora `use_tags/use_caption`:
        `tags`/`caption` usan `describe` con un solo componente y `unified`
        pide caption + tags en una llamada (`describe_unified`); la respuesta
        anade `mode`, `dropped` y `zones` (si hay tags) sobre las claves
        actuales. Sin `mode` el comportamiento es el de siempre.
        """
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
                _ensure_vision_server()
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
            _ensure_vision_server()
        try:
            return vision_service.describe(
                raw, use_tags=use_tags, use_caption=use_caption
            )
        except VisionUnavailable as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})

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
            if width is not None and height is not None:
                raw = _fit_reference(raw, width, height)
            input_dir = cfg.comfy_input_dir
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
        """Encola un video (M9-F1/M10-2a/M10-2c): mode i2v|flf2v, segundos y negativo.

        `engine` sigue siendo `wan|h3`; si falta la clave, default `wan` (el
        `mode` de Wan elige plantilla I2V o FLF2V y `seconds` fija los frames
        4n+1). Para Wan, `preset` (id o `"manual"`; desconocido ⇒ 400) y los
        overrides `sampler_name`/`scheduler`/`steps`/`shift` se resuelven con
        precedencia overrides > preset > certificado; el tamano efectivo sale
        del preset segun `aspect` y `vram_hint` lo refleja.         En `engine=h3` el
        preset Wan no aplica (400 si llega uno real) y `profile` (ausente →
        `referencia`), `variant` (ausente → `turbo4`; `turbo8` usa LoRA de 8
        pasos), `sage` (bool; inserta el patch de KJNodes), `seconds`
        (5/8/10/12/15), `width`/`height` (múltiplo de 32, área <= 768x1344)
        eligen plantilla y grid 5+17n. La respuesta añade `frames` y
        `vram_hint` (tabla Wan; null en H3).
        """
        if "engine" in payload:
            engine_kind = payload.get("engine")
        else:
            engine_kind = "h3" if payload.get("mode") == "ref2va" or payload.get("profile") == "ref2va" else "wan"
        if engine_kind not in ("wan", "h3"):
            raise EngineError("engine invalido; usar wan|h3")
        mode = payload.get("mode") or ("ref2va" if payload.get("profile") == "ref2va" else "i2v")
        if mode not in ("i2v", "flf2v", "ref2va"):
            raise EngineError("mode invalido; usar i2v|flf2v|ref2va")
        if mode == "ref2va" and engine_kind != "h3":
            raise EngineError("ref2va solo es compatible con motor h3")
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
            req_profile = payload.get("profile") or ("ref2va" if mode == "ref2va" else None)
            h3_profile = resolve_h3_profile(req_profile)
            h3_variant = resolve_h3_variant(payload.get("variant"))
            sage = payload.get("sage")
            if sage is None:
                sage = False
            if not isinstance(sage, bool):
                raise EngineError("sage invalido; usar booleano")
            raw_seconds = payload.get("seconds")
            if raw_seconds is None:
                raw_seconds = h3_profile["seconds_recomendados"][0]
            seconds = float(require_h3_seconds(raw_seconds))
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
        if mode == "ref2va":
            if not ref_images_b64 and not payload.get("image_b64"):
                raise EngineError("ref2va requiere al menos una imagen de referencia")
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
            for i, raw_b64 in enumerate(ref_images_b64):
                ref_bytes = _decode_image_b64(raw_b64, f"ref_{i}")
                ref_name = _write_input_png(input_dir, ref_bytes, filename=f"ref_{i}.png")
                ref_image_names.append(ref_name)
        image_name = _write_input_png(input_dir, first_raw) if first_raw is not None else None
        last_image_name = (
            _write_input_png(input_dir, last_raw) if last_raw is not None else None
        )
        if mode == "ref2va":
            if not image_name and ref_image_names:
                image_name = ref_image_names[0]
            if not last_image_name and len(ref_image_names) > 1:
                last_image_name = ref_image_names[1]
        if engine_kind == "h3":
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
            "preset": PRESET_MANUAL if profile is None else profile["preset"],
            **profile_fields,
        }
        if h3_profile is not None:
            stored_params["profile"] = h3_profile["id"]
            stored_params["variant"] = h3_variant["id"]
            stored_params["sage"] = sage
            stored_params["width"] = width
            stored_params["height"] = height
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

    @app.get("/api/editor/status")
    async def api_editor_status() -> dict:
        """Estado real del editor Qwen-Image 2.1 (M9-G/M10-3).

        `expected` son las rutas relativas a `ComfyUI/models` del par UC (GGUF
        + text encoder int8 ConvRot + VAE bf16) definidas en
        `registry/editor_models-v1.json`; `installed` exige que existan TODAS y
        es lo que habilita el encolado real de `/api/editor/generate`.
        """
        return {
            "installed": editor_installed(cfg.comfy_root),
            "model": EDITOR_MODEL,
            "expected": list(EDITOR_MODEL_FILES),
            "note": EDITOR_NOTE,
        }

    @app.post("/api/editor/generate")
    async def api_editor_generate(payload: dict = Body(...)) -> Any:
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
        if not editor_installed(cfg.comfy_root):
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
        elif isinstance(job.get("progress"), dict):
            snapshot = job["progress"]
            progress = {key: snapshot.get(key) for key in PROGRESS_KEYS}
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
            "params": job.get("params") or {},
            "prompt": job.get("prompt"),
            "negative": job.get("negative"),
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
        row = app.state.store.get(gen_id) if gen_id is not None else None
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
            app.state.store.update(gen_id, status="cancelled")
        return {"status": "cancelled"}

    @app.get("/api/gallery")
    async def api_gallery(
        limit: int = 24,
        offset: int = 0,
        kind: str | None = None,
        q: str | None = None,
    ) -> Any:
        """Feed paginado (mas nuevo primero); `kind` opcional filtra image|video.

        `count` refleja el filtro aplicado, no solo la ventana: el visor de
        video pide `kind=video&limit=5&offset=…` y calcula su pagina X de Y.
        `q` filtra por substring de texto/tags en prompt o negative.
        """
        kind = kind or None
        if kind not in (None, "image", "video"):
            return JSONResponse(
                status_code=400, content={"error": "kind invalido; usar image|video"}
            )
        limit = max(1, min(int(limit), 24))
        offset = max(0, int(offset))
        items = []
        for row in st.list(limit=limit, offset=offset, order="desc", kind=kind, q=q):
            item = dict(row)
            item["urls"] = [
                MEDIA_URL.format(gen_id=row["id"], name=name)
                for name in (row.get("outputs") or [])
            ]
            items.append(item)
        return {"items": items, "count": st.count(kind=kind, q=q)}

    @app.delete("/api/gallery/{id}")
    async def api_gallery_delete(id: int) -> Any:
        row = st.get(id)
        if row is None:
            return JSONResponse(status_code=404, content={"error": "no encontrado"})

        base_root = cfg.data_dir.resolve()
        candidate_dirs = [
            (cfg.data_dir / "gallery" / str(id)).resolve(),
            (cfg.data_dir / "generations" / str(id)).resolve(),
        ]
        for dir_path in candidate_dirs:
            if dir_path.is_dir() and dir_path.is_relative_to(base_root):
                for out_name in (row.get("outputs") or []):
                    fpath = (dir_path / out_name).resolve()
                    if fpath.is_relative_to(dir_path) and fpath.is_file():
                        try:
                            fpath.unlink(missing_ok=True)
                        except OSError:
                            pass
                try:
                    shutil.rmtree(dir_path, ignore_errors=True)
                except OSError:
                    pass

        st.delete(id)
        return {"ok": True, "id": id}

    @app.post("/api/gallery/clean_failed")
    async def api_gallery_clean_failed() -> Any:
        cleaned = st.delete_failed()
        return {"ok": True, "cleaned": cleaned}

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

    @app.get("/api/download/{gen_id}/{name:path}")
    async def api_download(gen_id: int, name: str) -> Any:
        """Descarga directa de un archivo de la galeria (Content-Disposition adjunto).

        Mismo confinamiento que `/media`; el navegador lo guarda en Descargas.
        """
        gen_root = (cfg.data_dir / "gallery" / str(gen_id)).resolve()
        candidate = (gen_root / name).resolve()
        if not candidate.is_relative_to(gen_root):
            return JSONResponse(
                status_code=403, content={"error": "ruta fuera de la galeria"}
            )
        if not candidate.is_file():
            return JSONResponse(status_code=404, content={"error": "no encontrado"})
        media_type = MEDIA_TYPES.get(candidate.suffix.lower()) or "application/octet-stream"
        return FileResponse(
            candidate, media_type=media_type, filename=candidate.name
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Any:
        return templates.TemplateResponse(request, "index.html", {"title": "WAIFU"})

    return app


def main() -> int:
    """`python -m app.server`: uvicorn en 127.0.0.1 y puerto de WAIFU_APP_PORT.

    El LLM es el servidor gestionado con arranque perezoso (M12-3): la app
    arranca `llama-server` en el primer uso y lo para al cerrar. Con
    `WAIFU_LLM_URL` definida se usa ese servidor externo.
    """
    import uvicorn

    port_text = os.environ.get("WAIFU_APP_PORT", "").strip()
    port = int(port_text) if port_text else APP_PORT
    uvicorn.run(
        create_app(llm=_manager_llm()), host=APP_HOST, port=port, log_level="info"
    )
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
