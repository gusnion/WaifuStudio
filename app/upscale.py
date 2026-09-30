"""Upscaler de imagen y video e interpolacion de fotogramas (M10-2d U1/U2/U3):
catalogo y runners.

Catalogo local estricto ``registry/upscalers-v1.json`` (mismo estilo que
`app.video_presets`: solo stdlib, EngineError claro si falta o es invalido).
`build_upscale_graph` arma el grafo API minimo LoadImage -> UpscaleModelLoader
-> ImageUpscaleWithModel -> SaveImage validando los nombres; con ``passes=2``
encadena una segunda ampliacion (×2 × ×2 = ×4, la misma encima de si misma) y
`run_upscale` encola en el engine, espera, copia el PNG a
``data/gallery/<gen_id>/``, refleja el estado en el store (``kind="image"``) y
registra el tracker de progreso para que `GET /api/jobs/{id}` sirva `progress`.
Sin GPU y sin red.

U2 (M10-2d) anade el video con nodos core: `build_video_upscale_graph` arma
LoadVideo -> GetVideoComponents -> ImageUpscaleWithModel -> CreateVideo (fps y
audio enlazados del origen) -> SaveVideo en MP4, y `run_video_upscale` copia el
video escalado a la galeria (``kind="video"``, ``params.task="upscale_video"``).
`ImageUpscaleWithModel` ya hace tiling interno: aqui no se reimplementa.

U3 (M10-2d) anade FPS/VFI con el custom node ComfyUI-Frame-Interpolation:
`build_fps_graph` arma LoadVideo -> GetVideoComponents -> ComfyMathExpression
(fps × multiplier) + RIFE VFI -> CreateVideo -> SaveVideo, y `run_fps` copia el
video interpolado a la galeria (``kind="video"``, ``params.task="rife"``). La
seccion ``frame_interpolation`` del catalogo lista los ckpts RIFE presentes en
``ComfyUI/custom_nodes/ComfyUI-Frame-Interpolation/ckpts/rife/``.
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
DEFAULT_FPS_FILENAME_PREFIX = "interp"
SAVE_VIDEO_FORMAT = "mp4"
FRAME_INTERPOLATION_KEY = "frame_interpolation"
RIFE_CLASS = "RIFE VFI"
FPS_MULTIPLIERS = (2, 4)
UPSCALE_PASSES = (1, 2)

# Defaults exactos del nodo RIFE VFI (custom node ComfyUI-Frame-Interpolation);
# el ckpt y el multiplier los fija el job.
RIFE_DEFAULTS = {
    "clear_cache_after_n_frames": 10,
    "fast_mode": True,
    "ensemble": True,
    "scale_factor": 1.0,
    "dtype": "float32",
    "torch_compile": False,
    "batch_size": 1,
}

# El video tarda mucho mas que una imagen (decodificar, escalar y recodificar).
VIDEO_HISTORY_TIMEOUT_S = 3600.0
FPS_HISTORY_TIMEOUT_S = 3600.0

# Nodos del grafo API minimo de imagen (ids fijos).
LOAD_IMAGE_ID = "1"
MODEL_LOADER_ID = "2"
UPSCALE_ID = "3"
SAVE_IMAGE_ID = "4"
# Segunda ampliacion encadenada (solo con passes=2); SaveImage sigue en "4".
UPSCALE2_ID = "5"

# Nodos del grafo API minimo de video (ids fijos).
LOAD_VIDEO_ID = "1"
VIDEO_COMPONENTS_ID = "2"
VIDEO_MODEL_LOADER_ID = "3"
VIDEO_UPSCALE_ID = "4"
CREATE_VIDEO_ID = "5"
SAVE_VIDEO_ID = "6"

# Nodos del grafo API minimo de interpolacion de fotogramas (ids fijos).
FPS_MATH_ID = "3"
FPS_INTERP_ID = "4"
FPS_CREATE_VIDEO_ID = "5"
FPS_SAVE_VIDEO_ID = "6"


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


def _parse_ckpt(value: Any) -> str:
    """Ckpt RIFE: archivo ``.pth`` simple (sin rutas ni ``..``)."""
    ckpt = _require_plain_name(value, "frame_interpolation: ckpt")
    if Path(ckpt).suffix.lower() != ".pth":
        raise EngineError(f"frame_interpolation: ckpt invalido: {value!r}")
    return ckpt


def _parse_multiplier(value: Any) -> int:
    """Multiplicador de interpolacion del catalogo: entero >= 2."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        raise EngineError(f"frame_interpolation: multiplier invalido: {value!r}")
    return value


def _parse_frame_interpolation(section: Any) -> dict[str, Any]:
    if not isinstance(section, dict):
        raise EngineError("frame_interpolation invalido: se esperaba objeto")
    label = section.get("label")
    if not isinstance(label, str) or not label.strip():
        raise EngineError(f"frame_interpolation: label invalido: {label!r}")
    note = section.get("note")
    if not isinstance(note, str):
        raise EngineError(f"frame_interpolation: note invalido: {note!r}")
    raw_ckpts = section.get("ckpts")
    if not isinstance(raw_ckpts, list) or not raw_ckpts:
        raise EngineError(f"frame_interpolation: ckpts invalido: {raw_ckpts!r}")
    ckpts: list[str] = []
    for raw in raw_ckpts:
        ckpt = _parse_ckpt(raw)
        if ckpt in ckpts:
            raise EngineError(f"frame_interpolation: ckpt duplicado: {ckpt!r}")
        ckpts.append(ckpt)
    default = section.get("default")
    if default not in ckpts:
        raise EngineError(f"frame_interpolation: default invalido: {default!r}")
    raw_multipliers = section.get("multipliers")
    if not isinstance(raw_multipliers, list) or not raw_multipliers:
        raise EngineError(
            f"frame_interpolation: multipliers invalido: {raw_multipliers!r}"
        )
    multipliers: list[int] = []
    for raw in raw_multipliers:
        multiplier = _parse_multiplier(raw)
        if multiplier in multipliers:
            raise EngineError(
                f"frame_interpolation: multiplier duplicado: {multiplier!r}"
            )
        multipliers.append(multiplier)
    return {
        "label": label.strip(),
        "ckpts": ckpts,
        "default": default,
        "multipliers": multipliers,
        "note": note,
    }


def load_frame_interpolation(path: str | Path = UPSCALERS_PATH) -> dict[str, Any]:
    """Lee y valida la seccion ``frame_interpolation``; EngineError si falta o es invalida."""
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
    if FRAME_INTERPOLATION_KEY not in data:
        raise EngineError(f"catalogo de upscalers sin {FRAME_INTERPOLATION_KEY}: {path}")
    return _parse_frame_interpolation(data[FRAME_INTERPOLATION_KEY])


_FRAME_INTERPOLATION: dict[str, Any] | None = None


def frame_interpolation() -> dict[str, Any]:
    """Seccion cargada una vez (perezoso); copia profunda por llamada."""
    global _FRAME_INTERPOLATION
    if _FRAME_INTERPOLATION is None:
        _FRAME_INTERPOLATION = load_frame_interpolation(UPSCALERS_PATH)
    return copy.deepcopy(_FRAME_INTERPOLATION)


def fps_ckpt(value: object) -> str:
    """Ckpt RIFE del catalogo (default si ``value`` es None); EngineError si no existe."""
    entry = frame_interpolation()
    name = entry["default"] if value is None else value
    if isinstance(name, str):
        name = name.strip()
    if name not in entry["ckpts"]:
        raise EngineError(f"ckpt de interpolacion desconocido: {value!r}")
    return name


def fps_multiplier(value: object) -> int:
    """Multiplicador FPS permitido (2|4); EngineError si no lo es."""
    allowed = "|".join(str(multiplier) for multiplier in FPS_MULTIPLIERS)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in FPS_MULTIPLIERS
    ):
        raise EngineError(
            f"multiplier de interpolacion invalido (usar {allowed}): {value!r}"
        )
    return value


def parse_passes(value: Any) -> int:
    """Pasadas de escalado de imagen (1|2); ``None`` usa 1; EngineError si no."""
    if value is None:
        return 1
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in UPSCALE_PASSES
    ):
        allowed = "|".join(str(item) for item in UPSCALE_PASSES)
        raise EngineError(f"passes invalido (usar {allowed}): {value!r}")
    return value


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
    passes: int = 1,
    prefix: str = DEFAULT_PREFIX,
    filename_prefix: str = DEFAULT_FILENAME_PREFIX,
) -> dict:
    """Grafo API minimo de escalado de una imagen.

    Nodos: LoadImage (``image_name``), UpscaleModelLoader (``model_file``),
    ImageUpscaleWithModel y SaveImage. Con ``passes=2`` la salida de la primera
    ampliacion entra en una segunda ``ImageUpscaleWithModel`` con el mismo
    modelo (×2 × ×2 = ×4) y SaveImage guarda esa cadena. El prefijo de guardado
    final es ``prefix/filename_prefix`` (o solo ``filename_prefix`` si
    ``prefix`` va vacio). EngineError si un nombre no es un archivo simple, un
    prefijo escapa del arbol de output o ``passes`` no es 1|2.
    """
    image_name = _require_plain_name(image_name, "upscale: image_name")
    model_file = _require_plain_name(model_file, "upscale: model_file")
    passes = parse_passes(passes)
    prefix = _require_prefix(prefix, "upscale: prefix", allow_empty=True)
    filename_prefix = _require_prefix(filename_prefix, "upscale: filename_prefix")
    save_prefix = f"{prefix}/{filename_prefix}" if prefix else filename_prefix
    graph = {
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
    if passes == 2:
        graph[UPSCALE2_ID] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {
                "upscale_model": [MODEL_LOADER_ID, 0],
                "image": [UPSCALE_ID, 0],
            },
        }
        graph[SAVE_IMAGE_ID]["inputs"]["images"] = [UPSCALE2_ID, 0]
    return graph


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


def build_fps_graph(
    video_name: str,
    ckpt_name: str,
    multiplier: int,
    *,
    prefix: str = DEFAULT_PREFIX,
    filename_prefix: str = DEFAULT_FPS_FILENAME_PREFIX,
) -> dict:
    """Grafo API minimo de interpolacion de fotogramas (FPS/VFI).

    Nodos: LoadVideo (``video_name``), GetVideoComponents (imagenes/audio/fps
    del origen), ComfyMathExpression (``fps`` × ``multiplier``), RIFE VFI
    (custom node ComfyUI-Frame-Interpolation, ``ckpt_name``, resto de inputs
    con los defaults del nodo), CreateVideo (fps interpolado y audio del
    origen) y SaveVideo en MP4. El prefijo de guardado final es
    ``prefix/filename_prefix`` (o solo ``filename_prefix`` si ``prefix`` va
    vacio). EngineError si un nombre no es un archivo simple, el multiplier no
    es 2|4 o un prefijo escapa del arbol de output.
    """
    video_name = _require_plain_name(video_name, "fps: video_name")
    ckpt_name = _require_plain_name(ckpt_name, "fps: ckpt_name")
    multiplier = fps_multiplier(multiplier)
    prefix = _require_prefix(prefix, "fps: prefix", allow_empty=True)
    filename_prefix = _require_prefix(filename_prefix, "fps: filename_prefix")
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
        FPS_MATH_ID: {
            "class_type": "ComfyMathExpression",
            "inputs": {
                "expression": f"a * {multiplier}",
                "values.a": [VIDEO_COMPONENTS_ID, 2],
            },
        },
        FPS_INTERP_ID: {
            "class_type": RIFE_CLASS,
            "inputs": {
                "ckpt_name": ckpt_name,
                "frames": [VIDEO_COMPONENTS_ID, 0],
                "multiplier": multiplier,
                **RIFE_DEFAULTS,
            },
        },
        FPS_CREATE_VIDEO_ID: {
            "class_type": "CreateVideo",
            "inputs": {
                "images": [FPS_INTERP_ID, 0],
                "fps": [FPS_MATH_ID, 0],
                "audio": [VIDEO_COMPONENTS_ID, 1],
            },
        },
        FPS_SAVE_VIDEO_ID: {
            "class_type": "SaveVideo",
            "inputs": {
                "video": [FPS_CREATE_VIDEO_ID, 0],
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
        "passes": job.get("passes"),
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
    Deja en ``job["params"]`` ``{task, source_gen, source_file, model, scale,
    passes}`` (``passes`` normalizado a 1|2). No propaga errores: el fallo se
    guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    job["params"] = _upscale_params(job)
    if record is not None and record.get("status") == "cancelled":
        job["outputs"] = []
        job["error"] = None
        return
    tracker = None
    try:
        passes = parse_passes(job.get("passes"))
        job["passes"] = passes
        job["params"] = _upscale_params(job)
        graph = build_upscale_graph(
            job.get("image_name"),
            job.get("model_file"),
            passes=passes,
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


def parse_fps(value: Any, label: str = "upscale: fps") -> float | None:
    """fps de metadata: ``None`` o numero finito > 0."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineError(f"{label} invalido: {value!r}")
    fps = float(value)
    if not math.isfinite(fps) or fps <= 0:
        raise EngineError(f"{label} invalido: {value!r}")
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
        job["fps"] = parse_fps(job.get("fps"))
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


def _fps_params(job: dict) -> dict:
    return {
        "task": "rife",
        "source_gen": job.get("source_gen"),
        "source_file": job.get("source_file"),
        "ckpt": job.get("ckpt"),
        "multiplier": job.get("multiplier"),
        "fps_in": job.get("fps_in"),
        "fps_out": job.get("fps_out"),
    }


def run_fps(
    job: dict,
    *,
    config: Any,
    store: Any,
    engine_factory: Callable[[], Any] = None,
    record: dict | None = None,
    ws_factory: Any = None,
) -> None:
    """Ejecuta un job de interpolacion de fotogramas: grafo -> engine -> galeria -> store.

    Mismo contrato que `run_video_upscale` (estado queued -> running -> done/
    error/cancelled en `record`, tracker parado en el `finally`, sin propagar
    errores), pero el grafo usa `build_fps_graph` y ``job["params"]`` queda
    como ``{task: "rife", source_gen, source_file, ckpt, multiplier, fps_in,
    fps_out}``. ``fps_in`` es metadata opcional (``None`` o numero > 0):
    ``fps_out`` se calcula como ``fps_in × multiplier`` y el grafo multiplica
    el fps real del origen con `ComfyMathExpression`.
    """
    gen_id = job["gen_id"]
    job["params"] = _fps_params(job)
    if record is not None and record.get("status") == "cancelled":
        job["outputs"] = []
        job["error"] = None
        return
    tracker = None
    try:
        multiplier = fps_multiplier(job.get("multiplier"))
        fps_in = parse_fps(job.get("fps_in"), "fps: fps_in")
        job["multiplier"] = multiplier
        job["fps_in"] = fps_in
        job["fps_out"] = None if fps_in is None else fps_in * multiplier
        job["params"] = _fps_params(job)
        graph = build_fps_graph(
            job.get("video_name"),
            job.get("ckpt_name"),
            multiplier,
            prefix=job.get("prefix") or DEFAULT_PREFIX,
            filename_prefix=job.get("filename_prefix") or DEFAULT_FPS_FILENAME_PREFIX,
        )
        engine = (
            engine_factory()
            if engine_factory is not None
            else ComfyEngine(config, history_timeout_s=FPS_HISTORY_TIMEOUT_S)
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
    "DEFAULT_FPS_FILENAME_PREFIX",
    "DEFAULT_PREFIX",
    "FPS_CREATE_VIDEO_ID",
    "FPS_HISTORY_TIMEOUT_S",
    "FPS_INTERP_ID",
    "FPS_MATH_ID",
    "FPS_MULTIPLIERS",
    "FPS_SAVE_VIDEO_ID",
    "FRAME_INTERPOLATION_KEY",
    "IMAGE_EXT",
    "LOAD_IMAGE_ID",
    "LOAD_VIDEO_ID",
    "MIN_UPSCALE_SCALE",
    "MODEL_LOADER_ID",
    "RIFE_CLASS",
    "RIFE_DEFAULTS",
    "SAVE_IMAGE_ID",
    "SAVE_VIDEO_FORMAT",
    "SAVE_VIDEO_ID",
    "UPSCALE2_ID",
    "UPSCALERS_PATH",
    "UPSCALE_ID",
    "UPSCALE_PASSES",
    "VIDEO_COMPONENTS_ID",
    "VIDEO_EXT",
    "VIDEO_HISTORY_TIMEOUT_S",
    "VIDEO_MODEL_LOADER_ID",
    "VIDEO_UPSCALE_ID",
    "build_fps_graph",
    "build_upscale_graph",
    "build_video_upscale_graph",
    "fps_ckpt",
    "fps_multiplier",
    "frame_interpolation",
    "get_upscaler",
    "list_upscalers",
    "load_frame_interpolation",
    "load_upscalers",
    "parse_fps",
    "parse_passes",
    "run_fps",
    "run_upscale",
    "run_video_upscale",
    "upscalers",
]
