"""Upscaler de imagen y video (M10-2d U1/U2): catalogo y runners.

Catalogo local estricto ``registry/upscalers-v1.json`` (mismo estilo que
`app.video_presets`: solo stdlib, EngineError claro si falta o es invalido).
`build_upscale_graph` arma el grafo API minimo LoadImage -> UpscaleModelLoader
-> ImageUpscaleWithModel -> SaveImage validando los nombres, y `run_upscale`
encola en el engine, espera, copia el PNG a ``data/gallery/<gen_id>/``, refleja
el estado en el store (``kind="image"``) y registra el tracker de progreso para
que `GET /api/jobs/{id}` sirva `progress`. Sin GPU y sin red.

U2 (M10-2d) anade el video con nodos core: `build_video_upscale_graph` arma
LoadVideo -> GetVideoComponents -> ImageUpscaleWithModel -> CreateVideo (fps y
audio enlazados del origen) -> SaveVideo en MP4, y `run_video_upscale` copia el
video escalado a la galeria (``kind="video"``, ``params.task="upscale_video"``).
`ImageUpscaleWithModel` ya hace tiling interno: aqui no se reimplementa.
"""

from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path
from typing import Any, Callable

from app.config import APP_ROOT
from app.engine import ComfyEngine, EngineError
from app.progress import ProgressTracker

UPSCALERS_PATH = APP_ROOT / "registry" / "upscalers-v1.json"
CATALOG_VERSION = 1
MIN_UPSCALE_SCALE = 1
IMAGE_EXT = ("png",)
VIDEO_EXT = ("mp4", "webm")
DEFAULT_PREFIX = "waifu/upscale"
DEFAULT_FILENAME_PREFIX = "upscaled"
SAVE_VIDEO_FORMAT = "mp4"

# El video tarda mucho mas que una imagen (decodificar, escalar y recodificar).
VIDEO_HISTORY_TIMEOUT_S = 3600.0

# Nodos del grafo API minimo de imagen (ids fijos).
LOAD_IMAGE_ID = "1"
MODEL_LOADER_ID = "2"
UPSCALE_ID = "3"
SAVE_IMAGE_ID = "4"

# Nodos del grafo API minimo de video (ids fijos).
LOAD_VIDEO_ID = "1"
VIDEO_COMPONENTS_ID = "2"
VIDEO_MODEL_LOADER_ID = "3"
VIDEO_UPSCALE_ID = "4"
CREATE_VIDEO_ID = "5"
SAVE_VIDEO_ID = "6"


def _parse_file(value: Any, upscaler_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"upscaler {upscaler_id!r}: file invalido: {value!r}")
    file = value.strip()
    if (
        Path(file).is_absolute()
        or "/" in file
        or "\\" in file
        or file in (".", "..")
    ):
        raise EngineError(f"upscaler {upscaler_id!r}: file invalido: {value!r}")
    return file


def _parse_scale(value: Any, upscaler_id: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < MIN_UPSCALE_SCALE
    ):
        raise EngineError(
            f"upscaler {upscaler_id!r}: scale invalido "
            f"(entero >= {MIN_UPSCALE_SCALE}): {value!r}"
        )
    return value


def _parse_upscaler(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise EngineError(f"upscaler #{index} invalido: se esperaba objeto")
    upscaler_id = entry.get("id")
    if not isinstance(upscaler_id, str) or not upscaler_id.strip():
        raise EngineError(f"upscaler #{index} sin id valido: {upscaler_id!r}")
    upscaler_id = upscaler_id.strip()
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        raise EngineError(f"upscaler {upscaler_id!r}: label invalido: {label!r}")
    note = entry.get("note")
    if not isinstance(note, str):
        raise EngineError(f"upscaler {upscaler_id!r}: note invalido: {note!r}")
    return {
        "id": upscaler_id,
        "label": label.strip(),
        "file": _parse_file(entry.get("file"), upscaler_id),
        "scale": _parse_scale(entry.get("scale"), upscaler_id),
        "note": note,
    }


def load_upscalers(path: str | Path = UPSCALERS_PATH) -> dict[str, dict[str, Any]]:
    """Lee y valida el catalogo; EngineError claro si falta o es invalido."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"catalogo de upscalers ilegible: {path}") from exc
    if not isinstance(data, dict):
        raise EngineError(f"catalogo de upscalers invalido: {path}")
    version = data.get("version")
    if isinstance(version, bool) or version != CATALOG_VERSION:
        raise EngineError(
            f"catalogo de upscalers con version invalida: {version!r} (esperada {CATALOG_VERSION})"
        )
    entries = data.get("upscalers")
    if not isinstance(entries, list):
        raise EngineError(f"catalogo de upscalers invalido: {path}")
    upscalers: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        upscaler = _parse_upscaler(entry, index)
        if upscaler["id"] in upscalers:
            raise EngineError(
                f"upscaler duplicado en {path}: {upscaler['id']!r}"
            )
        upscalers[upscaler["id"]] = upscaler
    if not upscalers:
        raise EngineError(f"catalogo de upscalers sin upscalers: {path}")
    return upscalers


_UPSCALERS: dict[str, dict[str, Any]] | None = None


def upscalers() -> dict[str, dict[str, Any]]:
    """Catalogo cargado una vez (perezoso); copia profunda por llamada."""
    global _UPSCALERS
    if _UPSCALERS is None:
        _UPSCALERS = load_upscalers(UPSCALERS_PATH)
    return copy.deepcopy(_UPSCALERS)


def list_upscalers() -> list[dict[str, Any]]:
    """Copia serializable de los upscalers, en orden del catalogo."""
    return [copy.deepcopy(upscaler) for upscaler in upscalers().values()]


def get_upscaler(upscaler_id: object) -> dict[str, Any]:
    """Upscaler por id estricto; EngineError si no existe o no es texto."""
    entry = (
        upscalers().get(upscaler_id.strip())
        if isinstance(upscaler_id, str)
        else None
    )
    if entry is None:
        raise EngineError(f"upscaler desconocido: {upscaler_id!r}")
    return entry


def _require_plain_name(value: Any, label: str) -> str:
    """Nombre de archivo simple (sin rutas ni ``..``): image/model del grafo."""
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"{label} vacio")
    name = value.strip()
    if (
        Path(name).is_absolute()
        or "/" in name
        or "\\" in name
        or name in (".", "..")
    ):
        raise EngineError(f"{label} invalido: {value!r}")
    return name


def _require_prefix(value: Any, label: str, *, allow_empty: bool = False) -> str:
    """Prefijo de salida: segmentos no vacios, sin ``\\\\``, ``..`` ni empezar por ``/``."""
    if not isinstance(value, str):
        raise EngineError(f"{label} invalido: {value!r}")
    prefix = value.strip()
    if not prefix:
        if allow_empty:
            return ""
        raise EngineError(f"{label} vacio")
    if prefix.startswith("/") or "\\" in prefix:
        raise EngineError(f"{label} invalido: {value!r}")
    if any(part in ("", ".", "..") for part in prefix.split("/")):
        raise EngineError(f"{label} invalido: {value!r}")
    return prefix


def build_upscale_graph(
    image_name: str,
    model_file: str,
    *,
    prefix: str = DEFAULT_PREFIX,
    filename_prefix: str = DEFAULT_FILENAME_PREFIX,
) -> dict:
    """Grafo API minimo de escalado de una imagen.

    Nodos: LoadImage (``image_name``), UpscaleModelLoader (``model_file``),
    ImageUpscaleWithModel y SaveImage. El prefijo de guardado final es
    ``prefix/filename_prefix`` (o solo ``filename_prefix`` si ``prefix`` va
    vacio). EngineError si un nombre no es un archivo simple o un prefijo
    escapa del arbol de output.
    """
    image_name = _require_plain_name(image_name, "upscale: image_name")
    model_file = _require_plain_name(model_file, "upscale: model_file")
    prefix = _require_prefix(prefix, "upscale: prefix", allow_empty=True)
    filename_prefix = _require_prefix(filename_prefix, "upscale: filename_prefix")
    save_prefix = f"{prefix}/{filename_prefix}" if prefix else filename_prefix
    return {
        LOAD_IMAGE_ID: {
            "class_type": "LoadImage",
            "inputs": {"image": image_name, "upload": "image"},
        },
        MODEL_LOADER_ID: {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": model_file},
        },
        UPSCALE_ID: {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {
                "upscale_model": [MODEL_LOADER_ID, 0],
                "image": [LOAD_IMAGE_ID, 0],
            },
        },
        SAVE_IMAGE_ID: {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": save_prefix, "images": [UPSCALE_ID, 0]},
        },
    }


def build_video_upscale_graph(
    video_name: str,
    model_file: str,
    *,
    prefix: str = DEFAULT_PREFIX,
    filename_prefix: str = DEFAULT_FILENAME_PREFIX,
) -> dict:
    """Grafo API minimo de escalado de un video con nodos core.

    Nodos: LoadVideo (``video_name``), GetVideoComponents (imagenes/audio/fps
    del origen), UpscaleModelLoader (``model_file``), ImageUpscaleWithModel
    (tiling interno del core), CreateVideo (``fps`` y ``audio`` enlazados del
    origen) y SaveVideo en MP4. El prefijo de guardado final es
    ``prefix/filename_prefix`` (o solo ``filename_prefix`` si ``prefix`` va
    vacio). EngineError si un nombre no es un archivo simple o un prefijo
    escapa del arbol de output.
    """
    video_name = _require_plain_name(video_name, "upscale: video_name")
    model_file = _require_plain_name(model_file, "upscale: model_file")
    prefix = _require_prefix(prefix, "upscale: prefix", allow_empty=True)
    filename_prefix = _require_prefix(filename_prefix, "upscale: filename_prefix")
    save_prefix = f"{prefix}/{filename_prefix}" if prefix else filename_prefix
    return {
        LOAD_VIDEO_ID: {
            "class_type": "LoadVideo",
            "inputs": {"file": video_name},
        },
        VIDEO_COMPONENTS_ID: {
            "class_type": "GetVideoComponents",
            "inputs": {"video": [LOAD_VIDEO_ID, 0]},
        },
        VIDEO_MODEL_LOADER_ID: {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": model_file},
        },
        VIDEO_UPSCALE_ID: {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {
                "upscale_model": [VIDEO_MODEL_LOADER_ID, 0],
                "image": [VIDEO_COMPONENTS_ID, 0],
            },
        },
        CREATE_VIDEO_ID: {
            "class_type": "CreateVideo",
            "inputs": {
                "images": [VIDEO_UPSCALE_ID, 0],
                "fps": [VIDEO_COMPONENTS_ID, 2],
                "audio": [VIDEO_COMPONENTS_ID, 1],
            },
        },
        SAVE_VIDEO_ID: {
            "class_type": "SaveVideo",
            "inputs": {
                "video": [CREATE_VIDEO_ID, 0],
                "filename_prefix": save_prefix,
                "format": SAVE_VIDEO_FORMAT,
            },
        },
    }


def _progress_ws_url(config: Any) -> str:
    """WS del engine desde `comfy_url` (misma semantica que `app.server`)."""
    base = str(config.comfy_url).rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return f"{base}/ws"


def _upscale_params(job: dict) -> dict:
    return {
        "task": "upscale",
        "source_gen": job.get("source_gen"),
        "source_file": job.get("source_file"),
        "model": job.get("model"),
        "scale": job.get("scale"),
    }


def run_upscale(
    job: dict,
    *,
    config: Any,
    store: Any,
    engine_factory: Callable[[], Any] = None,
    record: dict | None = None,
    ws_factory: Any = None,
) -> None:
    """Ejecuta un job de escalado: grafo -> engine -> galeria -> store.

    `record` es el registro de `_JOBS[gen_id]` del server: si se pasa, se le
    registran engine, `prompt_id`, tracker y estado (queued -> running ->
    done/error/cancelled) como en imagen/video; el `ProgressTracker` se crea
    antes del submit (con `ws_factory` inyectable) y se para en el `finally`.
    Deja en ``job["params"]`` ``{task, source_gen, source_file, model, scale}``.
    No propaga errores: el fallo se guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    job["params"] = _upscale_params(job)
    if record is not None and record.get("status") == "cancelled":
        job["outputs"] = []
        job["error"] = None
        return
    tracker = None
    try:
        graph = build_upscale_graph(
            job.get("image_name"),
            job.get("model_file"),
            prefix=job.get("prefix") or DEFAULT_PREFIX,
            filename_prefix=job.get("filename_prefix") or DEFAULT_FILENAME_PREFIX,
        )
        engine = (
            engine_factory()
            if engine_factory is not None
            else ComfyEngine(config)
        )
        if record is not None:
            record["engine"] = engine
        tracker = ProgressTracker(
            _progress_ws_url(config),
            engine.client_id,
            "",
            ws_factory=ws_factory,
        )
        if record is not None:
            record["tracker"] = tracker
            record["status"] = "running"
        tracker.start()
        prompt_id = engine.submit(graph)
        if record is not None:
            record["prompt_id"] = prompt_id
        tracker.prompt_id = prompt_id
        history = engine.wait(prompt_id)
        paths = engine.outputs(history, expected_ext=IMAGE_EXT)
        if not paths:
            raise EngineError(f"el engine no devolvio ningun PNG para {prompt_id}")
        gallery_dir = config.data_dir / "gallery" / str(gen_id)
        gallery_dir.mkdir(parents=True, exist_ok=True)
        names: list[str] = []
        for path in paths:
            target = gallery_dir / path.name
            shutil.copy2(path, target)
            names.append(target.name)
        store.update(gen_id, status="done", outputs=names, kind="image")
        job["outputs"] = names
        job["error"] = None
        if record is not None:
            record["status"] = "done"
    except Exception as exc:
        job["outputs"] = []
        job["error"] = str(exc)
        if record is not None and record.get("status") == "cancelled":
            job["error"] = None
            try:
                store.update(gen_id, status="cancelled")
            except EngineError:
                pass
        else:
            if record is not None:
                record["status"] = "error"
            try:
                store.update(gen_id, status="error", error=str(exc))
            except EngineError:
                pass
    finally:
        if tracker is not None:
            tracker.stop()


def _require_fps(value: Any) -> float | None:
    """fps de metadata del job: ``None`` o numero finito > 0."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineError(f"upscale: fps invalido: {value!r}")
    fps = float(value)
    if not math.isfinite(fps) or fps <= 0:
        raise EngineError(f"upscale: fps invalido: {value!r}")
    return fps


def _video_upscale_params(job: dict) -> dict:
    return {
        "task": "upscale_video",
        "source_gen": job.get("source_gen"),
        "source_file": job.get("source_file"),
        "model": job.get("model"),
        "scale": job.get("scale"),
        "fps": job.get("fps"),
    }


def run_video_upscale(
    job: dict,
    *,
    config: Any,
    store: Any,
    engine_factory: Callable[[], Any] = None,
    record: dict | None = None,
    ws_factory: Any = None,
) -> None:
    """Ejecuta un job de escalado de video: grafo -> engine -> galeria -> store.

    Mismo contrato que `run_upscale` (estado queued -> running -> done/error/
    cancelled en `record`, tracker parado en el `finally`, sin propagar
    errores), pero el resultado va a la galeria como ``kind="video"`` y
    ``job["params"]`` queda como ``{task: "upscale_video", source_gen,
    source_file, model, scale, fps}``. ``job["fps"]`` es metadata opcional
    (``None`` o numero > 0): el grafo toma fps y audio reales del origen via
    `GetVideoComponents`.
    """
    gen_id = job["gen_id"]
    if record is not None and record.get("status") == "cancelled":
        job["params"] = _video_upscale_params(job)
        job["outputs"] = []
        job["error"] = None
        return
    tracker = None
    try:
        job["fps"] = _require_fps(job.get("fps"))
        job["params"] = _video_upscale_params(job)
        graph = build_video_upscale_graph(
            job.get("video_name"),
            job.get("model_file"),
            prefix=job.get("prefix") or DEFAULT_PREFIX,
            filename_prefix=job.get("filename_prefix") or DEFAULT_FILENAME_PREFIX,
        )
        engine = (
            engine_factory()
            if engine_factory is not None
            else ComfyEngine(config, history_timeout_s=VIDEO_HISTORY_TIMEOUT_S)
        )
        if record is not None:
            record["engine"] = engine
        tracker = ProgressTracker(
            _progress_ws_url(config),
            engine.client_id,
            "",
            ws_factory=ws_factory,
        )
        if record is not None:
            record["tracker"] = tracker
            record["status"] = "running"
        tracker.start()
        prompt_id = engine.submit(graph)
        if record is not None:
            record["prompt_id"] = prompt_id
        tracker.prompt_id = prompt_id
        history = engine.wait(prompt_id)
        paths = engine.outputs(history, expected_ext=VIDEO_EXT)
        if not paths:
            raise EngineError(f"el engine no devolvio ningun video para {prompt_id}")
        gallery_dir = config.data_dir / "gallery" / str(gen_id)
        gallery_dir.mkdir(parents=True, exist_ok=True)
        names: list[str] = []
        for path in paths:
            target = gallery_dir / path.name
            shutil.copy2(path, target)
            names.append(target.name)
        store.update(gen_id, status="done", outputs=names, kind="video")
        job["outputs"] = names
        job["error"] = None
        if record is not None:
            record["status"] = "done"
    except Exception as exc:
        job["outputs"] = []
        job["error"] = str(exc)
        if record is not None and record.get("status") == "cancelled":
            job["error"] = None
            try:
                store.update(gen_id, status="cancelled")
            except EngineError:
                pass
        else:
            if record is not None:
                record["status"] = "error"
            try:
                store.update(gen_id, status="error", error=str(exc))
            except EngineError:
                pass
    finally:
        if tracker is not None:
            tracker.stop()


def __getattr__(name: str) -> Any:
    """Alias perezoso del catalogo, al estilo de ``video_presets.PRESETS``."""
    if name == "UPSCALERS":
        return upscalers()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CATALOG_VERSION",
    "CREATE_VIDEO_ID",
    "DEFAULT_FILENAME_PREFIX",
    "DEFAULT_PREFIX",
    "IMAGE_EXT",
    "LOAD_IMAGE_ID",
    "LOAD_VIDEO_ID",
    "MIN_UPSCALE_SCALE",
    "MODEL_LOADER_ID",
    "SAVE_IMAGE_ID",
    "SAVE_VIDEO_FORMAT",
    "SAVE_VIDEO_ID",
    "UPSCALERS_PATH",
    "UPSCALE_ID",
    "VIDEO_COMPONENTS_ID",
    "VIDEO_EXT",
    "VIDEO_HISTORY_TIMEOUT_S",
    "VIDEO_MODEL_LOADER_ID",
    "VIDEO_UPSCALE_ID",
    "build_upscale_graph",
    "build_video_upscale_graph",
    "get_upscaler",
    "list_upscalers",
    "load_upscalers",
    "run_upscale",
    "run_video_upscale",
    "upscalers",
]
