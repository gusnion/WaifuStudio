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
import io
import json
import logging
import math
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

from app.config import APP_ROOT
from app.engine import ComfyEngine, EngineError, JobCancelledError
from app.progress import ProgressTracker
from app.video import concat_videos, find_ffmpeg

logger = logging.getLogger(__name__)

# Presupuestos de pixeles por VRAM para evitar que una difusion Highres
# desborde una GPU pequena. Son orientativos: el bloqueo duro deja margen 1.25x.
_HIRES_MP_PER_GB = 0.25
_FAST_MP_PER_GB = 1.25


def detect_gpu_vram_gb() -> float:
    """VRAM total de la GPU mas grande detectada por nvidia-smi; 12 GB si falla."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        values = []
        for line in (result.stdout or "").splitlines():
            try:
                values.append(float(line.strip()))
            except ValueError:
                continue
        if values:
            return round(max(values) / 1024.0, 1)
    except (OSError, subprocess.SubprocessError):
        pass
    return 12.0


def evaluate_upscale_risk(
    width: int,
    height: int,
    *,
    scale: int,
    passes: int,
    mode: str,
    vram_gb: float | None = None,
    output_scale: int | None = None,
) -> dict[str, Any]:
    """Calcula salida y riesgo de una ampliacion antes de encolarla.

    ``scale`` es la escala nativa que ejecuta el modelo; ``output_scale`` es la
    escala final solicitada. Un modelo x4 con salida x2 sigue calculando x4 y
    luego reduce, por eso el riesgo se mide sobre el calculo real.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    scale = max(1, int(scale))
    passes = 1 if int(passes) <= 1 else 2
    mode = str(mode or "fast")
    target_scale = max(1, int(output_scale or scale))
    vram = float(vram_gb if vram_gb is not None else detect_gpu_vram_gb())
    compute_factor = scale ** passes
    output_factor = target_scale ** passes
    compute_w, compute_h = width * compute_factor, height * compute_factor
    out_w, out_h = width * output_factor, height * output_factor
    megapixels = round((out_w * out_h) / 1_000_000, 2)
    compute_megapixels = round((compute_w * compute_h) / 1_000_000, 2)
    per_gb = _HIRES_MP_PER_GB if mode in ("hires", "qwen_remaster") else _FAST_MP_PER_GB
    budget = round(max(1.5, vram * per_gb), 2)
    hard_limit = round(min(40.0, budget * 1.25), 2)
    if mode in ("hires", "qwen_remaster"):
        budget = min(budget, 10.0)
        hard_limit = min(hard_limit, 12.5)
    work_megapixels = max(megapixels, compute_megapixels)
    reasons: list[str] = []
    if mode in ("hires", "qwen_remaster") and work_megapixels > budget:
        reasons.append("highres_over_budget")
    if work_megapixels > hard_limit:
        reasons.append("output_over_hard_limit")
    risk = "blocked" if work_megapixels > hard_limit else ("warn" if reasons else "ok")
    recommended_scale = 2 if target_scale > 2 else target_scale
    recommended_mode = "fast" if mode != "fast" else mode
    return {
        "source": {"width": width, "height": height},
        "output": {"width": out_w, "height": out_h, "megapixels": megapixels},
        "compute": {
            "width": compute_w,
            "height": compute_h,
            "megapixels": compute_megapixels,
            "native_scale": scale,
        },
        "vram_gb": vram,
        "mode": mode,
        "budget_mp": budget,
        "hard_limit_mp": hard_limit,
        "risk": risk,
        "reasons": reasons,
        "recommended": {
            "scale": recommended_scale,
            "passes": 1,
            "upscale_mode": recommended_mode,
        },
    }

UPSCALERS_PATH = APP_ROOT / "registry" / "upscalers-v1.json"
CATALOG_VERSION = 1
MIN_UPSCALE_SCALE = 1
MAX_UPSCALE_INPUT_SIDE = 2560
MAX_UPSCALE_OUTPUT_SIDE = 4096
MAX_VIDEO_UPSCALE_INPUT_SIDE = 1920
MAX_VIDEO_UPSCALE_OUTPUT_SIDE = 3840  # 2160p (4K UHD)
MAX_VIDEO_UPSCALE_FRAMES = 300  # Presupuesto maximo de fotogramas por tramo (12 GB VRAM)
MAX_VIDEO_UPSCALE_FPS = 120.0
MAX_VIDEO_UPSCALE_DURATION_S = 600.0
MAX_VIDEO_UPSCALE_TOTAL_OUTPUT_BYTES = 45 * 1024**3
VIDEO_UPSCALE_CHUNK_FRAMES_1080 = 150
VIDEO_UPSCALE_CHUNK_FRAMES_DEFAULT = 300
MAX_VIDEO_UPSCALE_INPUT_BYTES = 4 * 1024**3
MAX_VIDEO_UPSCALE_OUTPUT_BYTES = 16 * 1024**3
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
UPSCALE_SHARPEN = (0, 1, 2)
SHARPEN_CLASS = "ImageSharpen"
SHARPEN_KJ_CLASS = "ImageSharpenKJ"
SHARPEN_ID = "6"
SHARPEN_PRESETS = {
    1: {"sharpen_radius": 1, "sigma": 0.8, "alpha": 0.6},
    2: {"sharpen_radius": 2, "sigma": 1.0, "alpha": 1.2},
}
VALID_SHARPEN_METHODS = frozenset({"legacy", "rcas", "adaptive_usm"})
VALID_UPSCALE_MODES = frozenset({"fast", "hires", "qwen_remaster"})
DENOISE_MIN = 0.10
DENOISE_MAX = 0.50
DEFAULT_DENOISE = 0.25

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


def list_upscalers_with_availability(config: Any = None) -> list[dict[str, Any]]:
    """Catalogo con ``available`` segun exista el archivo en disco.

    La UI usa ``available`` para deshabilitar modelos fantasma; los runners
    antiguos conservan el fallback interno de ``resolve_upscale_model_file``.
    """
    items = list_upscalers()
    if not config or not hasattr(config, "comfy_root"):
        return items
    models_dir = Path(config.comfy_root) / "models" / "upscale_models"
    for item in items:
        filename = item.get("file")
        available = bool(filename and (models_dir / filename).is_file())
        item["available"] = available
        if not available:
            item["unavailable_reason"] = (
                f"Falta {filename} en ComfyUI/models/upscale_models"
            )
    return items



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


def parse_sharpen(value: Any) -> int:
    """Mejora de detalle de imagen (0|1|2); ``None`` usa 0; EngineError si no."""
    if value is None:
        return 0
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in UPSCALE_SHARPEN
    ):
        raise EngineError(f"sharpen invalido (usar 0|1|2): {value!r}")
    return value


def parse_sharpen_method(value: Any) -> str:
    """Metodo de enfoque: legacy (ImageSharpen), rcas o adaptive_usm (ImageSharpenKJ)."""
    if value is None:
        return "legacy"
    if not isinstance(value, str) or value.strip() not in VALID_SHARPEN_METHODS:
        allowed = "|".join(sorted(VALID_SHARPEN_METHODS))
        raise EngineError(
            f"sharpen_method invalido (usar {allowed}): {value!r}"
        )
    return value.strip()


def parse_upscale_mode(value: Any) -> str:
    """Modo de escalado: fast (GAN puro), hires (Anima difusion), qwen_remaster (Qwen 2.1)."""
    if value is None:
        return "fast"
    if not isinstance(value, str) or value.strip() not in VALID_UPSCALE_MODES:
        allowed = "|".join(sorted(VALID_UPSCALE_MODES))
        raise EngineError(
            f"upscale_mode invalido (usar {allowed}): {value!r}"
        )
    return value.strip()


def parse_denoise(value: Any) -> float:
    """Denoise para modos generativos de escalado (0.10 a 0.50)."""
    if value is None:
        return DEFAULT_DENOISE
    if isinstance(value, bool):
        raise EngineError(f"denoise invalido: {value!r}")
    try:
        val = float(value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"denoise invalido: {value!r}") from exc
    if not DENOISE_MIN <= val <= DENOISE_MAX:
        raise EngineError(
            f"denoise fuera de [{DENOISE_MIN}, {DENOISE_MAX}]: {value!r}"
        )
    return val


def resolve_upscale_model_file(model_file: str, config: Any = None) -> str:
    """Fallback transparente a RealESRGAN_x2.pth si el modelo no existe en disco."""
    if not config or not hasattr(config, "comfy_root"):
        return model_file
    models_dir = Path(config.comfy_root) / "models" / "upscale_models"
    if not models_dir.is_dir():
        return model_file
    target = models_dir / model_file
    if target.is_file():
        return model_file
    fallback = models_dir / "RealESRGAN_x2.pth"
    if fallback.is_file():
        return "RealESRGAN_x2.pth"
    return model_file


def clamp_or_validate_upscale_dimensions(
    image_path_or_bytes: Path | bytes,
    scale: int,
    passes: int,
    model_file: str | None = None,
) -> int:
    """Valida dimensiones de entrada y ajusta passes si el resultado excedería MAX_UPSCALE_OUTPUT_SIDE."""
    try:
        if isinstance(image_path_or_bytes, (bytes, bytearray)):
            img = Image.open(io.BytesIO(image_path_or_bytes))
        else:
            path = Path(image_path_or_bytes)
            if not path.is_file():
                return passes
            img = Image.open(path)
        with img:
            width, height = img.size
    except Image.DecompressionBombError:
        raise EngineError("imagen demasiado grande para escalar")
    except (UnidentifiedImageError, OSError, ValueError):
        return passes

    if max(width, height) > MAX_UPSCALE_INPUT_SIDE:
        raise EngineError(
            f"La imagen ya es de alta resolucion ({width}x{height} px, "
            f"max permitido de entrada {MAX_UPSCALE_INPUT_SIDE} px); no requiere mas reescalado."
        )

    effective_scale = (
        2
        if model_file == "RealESRGAN_x2.pth"
        else (scale if isinstance(scale, int) and scale > 0 else 2)
    )
    if passes == 2 and max(width, height) * (effective_scale ** 2) > MAX_UPSCALE_OUTPUT_SIDE:
        return 1
    return passes


def probe_video_metadata(
    video_path: Path | str,
    *,
    ffprobe_bin: str | Path | None = None,
) -> dict[str, Any]:
    """Obtiene metadatos basicos de un archivo de video (ancho, alto, frames, duracion, fps).

    Prioridad de deteccion:
    1. ffprobe CLI (via subprocess) si esta instalado o especificado.
    2. cv2 (OpenCV) si esta disponible en el entorno.
    3. av (PyAV) si esta disponible en el entorno.
    """
    path = Path(video_path)
    if not path.is_file():
        logger.warning("No se pudo sondear metadatos de video: archivo no encontrado (%s)", path)
        return {"width": 0, "height": 0, "frames": 0, "duration": 0.0, "fps": 0.0}

    failures: list[str] = []

    # 1. ffprobe CLI
    exe = str(ffprobe_bin) if ffprobe_bin else (
        os.environ.get("FFPROBE_PATH")
        or shutil.which("ffprobe")
        or (str(APP_ROOT / "tools" / "ffmpeg" / "ffprobe.exe") if (APP_ROOT / "tools" / "ffmpeg" / "ffprobe.exe").is_file() else None)
    )
    if exe:
        try:
            cmd = [
                exe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,nb_frames,duration,r_frame_rate",
                "-of", "json",
                str(path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                streams = data.get("streams") or []
                if streams:
                    s = streams[0]
                    w = int(s.get("width") or 0)
                    h = int(s.get("height") or 0)
                    nb_frames = int(s.get("nb_frames") or 0)
                    dur = float(s.get("duration") or 0.0)
                    fps_val = 0.0
                    r_fps = s.get("r_frame_rate")
                    if r_fps and "/" in str(r_fps):
                        num, den = str(r_fps).split("/", 1)
                        fps_val = float(num) / float(den) if float(den) else 0.0
                    elif r_fps:
                        fps_val = float(r_fps)
                    if nb_frames == 0 and dur > 0 and fps_val > 0:
                        nb_frames = int(dur * fps_val)
                    if w > 0 and h > 0:
                        return {
                            "width": w,
                            "height": h,
                            "frames": nb_frames,
                            "duration": dur,
                            "fps": fps_val,
                        }
                    failures.append(f"ffprobe retorno dimensiones no validas ({w}x{h})")
                else:
                    failures.append("ffprobe no encontro streams de video")
            else:
                err_detail = proc.stderr.strip() if proc.stderr else f"codigo {proc.returncode}"
                failures.append(f"ffprobe fallo: {err_detail}")
        except Exception as exc:
            failures.append(f"ffprobe fallo: {exc}")
    else:
        failures.append("ffprobe no esta instalado o especificado")

    # 2. cv2 fallback
    try:
        import cv2
        cap = cv2.VideoCapture(str(path))
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps_val = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.release()
            if w > 0 and h > 0:
                dur = (frames / fps_val) if fps_val > 0 and frames > 0 else 0.0
                return {
                    "width": w,
                    "height": h,
                    "frames": frames,
                    "duration": dur,
                    "fps": fps_val,
                }
            failures.append(f"cv2 retorno dimensiones no validas ({w}x{h})")
        else:
            failures.append("cv2 no pudo abrir el archivo")
    except Exception as exc:
        failures.append(f"cv2 fallo o no disponible: {exc}")

    # 3. av fallback
    try:
        import av
        with av.open(str(path)) as container:
            for stream in container.streams.video:
                w = int(stream.width or 0)
                h = int(stream.height or 0)
                frames = int(stream.frames or 0)
                dur = float(stream.duration * stream.time_base) if stream.duration and stream.time_base else 0.0
                fps_val = float(stream.average_rate) if stream.average_rate else 0.0
                if w > 0 and h > 0:
                    return {
                        "width": w,
                        "height": h,
                        "frames": frames,
                        "duration": dur,
                        "fps": fps_val,
                    }
            failures.append("av no encontro streams de video validos")
    except Exception as exc:
        failures.append(f"av fallo o no disponible: {exc}")

    logger.warning("No se pudieron sondear metadatos de video para %s: %s", path, "; ".join(failures))
    return {"width": 0, "height": 0, "frames": 0, "duration": 0.0, "fps": 0.0}


def _effective_video_scale(scale: int, model_file: str | None) -> int:
    """Escala real: x2 fija para RealESRGAN_x2, si no la solicitada valida."""
    if model_file == "RealESRGAN_x2.pth":
        return 2
    return scale if isinstance(scale, int) and scale > 0 else 2


def plan_video_chunks(
    meta: dict[str, Any],
    *,
    scale: int = 2,
    model_file: str | None = None,
    rife_multiplier: int = 1,
) -> dict[str, Any]:
    """Planifica un video por tramos sin el limite fijo de 300 frames totales.

    Mantiene el presupuesto por tramo (entrada <= 4 GiB, salida <= 16 GiB y
    150/300 frames segun resolucion) y anade topes globales de duracion y
    espacio. ``rife_multiplier`` multiplica los frames de salida por tramo.
    """
    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    if width <= 0 or height <= 0:
        raise EngineError("No se pudieron leer las dimensiones del video")

    frames = int(meta.get("frames") or 0)
    fps = float(meta.get("fps") or 0.0)
    duration = float(meta.get("duration") or 0.0)
    if frames <= 0:
        if duration > 0 and fps > 0:
            frames = round(duration * fps)
        if frames <= 0:
            raise EngineError("No se pudo determinar el numero de fotogramas del video")
    if not math.isfinite(fps) or fps <= 0:
        raise EngineError("No se pudo determinar el fps del video")
    if fps > MAX_VIDEO_UPSCALE_FPS:
        raise EngineError(
            f"El video tiene {fps:g} fps; el maximo permitido es {MAX_VIDEO_UPSCALE_FPS:g} fps."
        )
    if duration <= 0:
        duration = frames / fps
    if duration > MAX_VIDEO_UPSCALE_DURATION_S:
        raise EngineError(
            f"El video dura {duration:.1f} s; el maximo por job es "
            f"{MAX_VIDEO_UPSCALE_DURATION_S:.0f} s. Divida el clip antes de escalar."
        )

    if isinstance(rife_multiplier, bool) or not isinstance(rife_multiplier, int):
        raise EngineError("rife_multiplier invalido")
    if rife_multiplier < 1 or rife_multiplier > 4:
        raise EngineError("rife_multiplier fuera de rango (1-4)")

    effective_scale = _effective_video_scale(scale, model_file)
    out_w = round(width * effective_scale)
    out_h = round(height * effective_scale)
    if max(width, height) > MAX_VIDEO_UPSCALE_INPUT_SIDE:
        raise EngineError(
            f"El video de entrada es demasiado grande para escalar ({width}x{height} px; "
            f"maximo permitido de entrada: {MAX_VIDEO_UPSCALE_INPUT_SIDE} px en el lado mayor). "
            f"Para 12 GB de VRAM reduzca la resolucion a 1080p o inferior antes de escalar."
        )
    if max(out_w, out_h) > MAX_VIDEO_UPSCALE_OUTPUT_SIDE:
        raise EngineError(
            f"El escalado solicitado ({width}x{height} px x {effective_scale} = {out_w}x{out_h} px) "
            f"supera el limite de salida permitido para 12 GB VRAM "
            f"({MAX_VIDEO_UPSCALE_OUTPUT_SIDE} px / 2160p)."
        )

    chunk_frames = (
        VIDEO_UPSCALE_CHUNK_FRAMES_1080
        if height >= 1080
        else VIDEO_UPSCALE_CHUNK_FRAMES_DEFAULT
    )
    input_per_frame = width * height * 3 * 4
    output_per_frame = out_w * out_h * 3 * 4 * rife_multiplier
    max_by_input = MAX_VIDEO_UPSCALE_INPUT_BYTES // max(1, input_per_frame)
    max_by_output = MAX_VIDEO_UPSCALE_OUTPUT_BYTES // max(1, output_per_frame)
    chunk_frames = min(chunk_frames, max_by_input, max_by_output)
    if chunk_frames < 1:
        raise EngineError(
            "Un solo fotograma supera el presupuesto de VRAM para este video; "
            "reduzca la resolucion o la escala."
        )

    total_output_bytes = frames * output_per_frame
    if total_output_bytes > MAX_VIDEO_UPSCALE_TOTAL_OUTPUT_BYTES:
        raise EngineError(
            f"La salida estimada ({total_output_bytes / (1024**3):.2f} GB) supera el tope "
            f"de espacio por job ({MAX_VIDEO_UPSCALE_TOTAL_OUTPUT_BYTES / (1024**3):.0f} GB). "
            f"Divida el clip o reduzca la escala."
        )

    chunks = max(1, math.ceil(frames / chunk_frames))
    return {
        "width": width,
        "height": height,
        "frames": frames,
        "duration": duration,
        "fps": fps,
        "scale": effective_scale,
        "output_width": out_w,
        "output_height": out_h,
        "chunk_frames": chunk_frames,
        "chunks": chunks,
        "needs_chunks": chunks > 1,
        "estimated_output_bytes": total_output_bytes,
        "estimated_output_gb": round(total_output_bytes / (1024**3), 2),
    }


def validate_video_upscale_dimensions(
    video_path: Path | str,
    *,
    scale: int = 2,
    model_file: str | None = None,
    rife_multiplier: int = 1,
    ffprobe_bin: str | Path | None = None,
) -> dict[str, Any]:
    """Valida el video y devuelve el plan de tramos (sin limite fijo de 300).

    Lanza EngineError (HTTP 400) si no puede leer dimensiones/frames/fps, si
    el lado de entrada/salida excede el limite, si fps > 120, si la duracion
    supera 600 s o si la salida total estimada supera 48 GiB. Cada tramo
    respeta el presupuesto de VRAM (4 GiB entrada / 16 GiB salida).
    """
    path = Path(video_path)
    if not path.is_file():
        raise EngineError(f"Archivo de video no encontrado: {path}")

    meta = probe_video_metadata(path, ffprobe_bin=ffprobe_bin)
    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    if width <= 0 or height <= 0:
        raise EngineError(f"No se pudieron leer las dimensiones del video: {path.name}")

    plan = plan_video_chunks(
        meta,
        scale=scale,
        model_file=model_file,
        rife_multiplier=rife_multiplier,
    )
    return {**meta, **plan}



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
    sharpen: int = 0,
    sharpen_method: str = "legacy",
    upscale_mode: str = "fast",
    denoise: float = DEFAULT_DENOISE,
    prefix: str = DEFAULT_PREFIX,
    filename_prefix: str = DEFAULT_FILENAME_PREFIX,
) -> dict:
    """Grafo API de escalado de una imagen (Fast GAN, Hires Difusion o Qwen Remaster).

    Nodos base: LoadImage (``image_name``), UpscaleModelLoader (``model_file``),
    ImageUpscaleWithModel y SaveImage. Con ``passes=2`` encadena una segunda
    ampliacion. Con ``sharpen`` 1|2 aplica ImageSharpen (legacy) o ImageSharpenKJ
    (rcas/adaptive_usm).
    Con ``upscale_mode="hires"`` anade difusion con modelo Anima y denoise.
    Con ``upscale_mode="qwen_remaster"`` anade refinamiento semantico con Qwen 2.1.
    """
    image_name = _require_plain_name(image_name, "upscale: image_name")
    model_file = _require_plain_name(model_file, "upscale: model_file")
    passes = parse_passes(passes)
    sharpen = parse_sharpen(sharpen)
    sharpen_method = parse_sharpen_method(sharpen_method)
    upscale_mode = parse_upscale_mode(upscale_mode)
    denoise = parse_denoise(denoise)
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
    last_id = [UPSCALE_ID, 0]
    if passes == 2:
        graph[UPSCALE2_ID] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {
                "upscale_model": [MODEL_LOADER_ID, 0],
                "image": [UPSCALE_ID, 0],
            },
        }
        last_id = [UPSCALE2_ID, 0]
        graph[SAVE_IMAGE_ID]["inputs"]["images"] = last_id

    if sharpen != 0:
        if sharpen_method == "rcas":
            strength = 0.45 if sharpen == 1 else 0.75
            graph[SHARPEN_ID] = {
                "class_type": SHARPEN_KJ_CLASS,
                "inputs": {
                    "image": last_id,
                    "method": "rcas",
                    "method.strength": strength,
                },
            }
        elif sharpen_method == "adaptive_usm":
            strength = 0.45 if sharpen == 1 else 0.75
            graph[SHARPEN_ID] = {
                "class_type": SHARPEN_KJ_CLASS,
                "inputs": {
                    "image": last_id,
                    "method": "adaptive_usm",
                    "method.strength": strength,
                    "method.radius": 1.0,
                    "method.threshold": 0.05,
                },
            }
        else:
            graph[SHARPEN_ID] = {
                "class_type": SHARPEN_CLASS,
                "inputs": {"image": last_id, **SHARPEN_PRESETS[sharpen]},
            }
        last_id = [SHARPEN_ID, 0]
        graph[SAVE_IMAGE_ID]["inputs"]["images"] = last_id

    if upscale_mode == "hires":
        graph["10"] = {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "qwen_image_vae.safetensors"},
        }
        graph["11"] = {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "anima_aestheticV11.safetensors",
                "weight_dtype": "default",
            },
        }
        graph["12"] = {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen_3_06b_base.safetensors",
                "type": "stable_diffusion",
            },
        }
        graph["13"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["12", 0],
                "text": "masterpiece, best quality, ultra-detailed, sharp clean linework, intricate details",
            },
        }
        graph["14"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["12", 0],
                "text": "blurry, lowres, artifacts, halo, noise",
            },
        }
        graph["15"] = {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": last_id,
                "vae": ["10", 0],
            },
        }
        graph["16"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": ["11", 0],
                "positive": ["13", 0],
                "negative": ["14", 0],
                "latent_image": ["15", 0],
                "seed": 42,
                "steps": 14,
                "cfg": 4.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": denoise,
            },
        }
        graph["17"] = {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["16", 0],
                "vae": ["10", 0],
            },
        }
        graph[SAVE_IMAGE_ID]["inputs"]["images"] = ["17", 0]
    elif upscale_mode == "qwen_remaster":
        graph["10"] = {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": "qwen-image-2.1-UC-Q4_K_M.gguf"},
        }
        graph["11"] = {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen3vl_8b_int8_convrot.safetensors",
                "type": "qwen_image",
                "device": "default",
            },
        }
        graph["12"] = {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"},
        }
        graph["13"] = {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "clip": ["11", 0],
                "prompt": "Enhance to ultra-high resolution, sharp clean linework, intricate micro-details, pristine quality, 8k masterpiece",
                "negative_prompt": "blurry, lowres, artifacts, halo, noise",
                "vae": ["12", 0],
                "resolution": 2048,
                "images.image_1": last_id,
            },
        }
        graph["14"] = {
            "class_type": "QwenImage21Cache",
            "inputs": {
                "model": ["10", 0],
                "device": "auto",
                "dtype": "default",
            },
        }
        graph["15"] = {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": last_id,
                "vae": ["12", 0],
            },
        }
        graph["16"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": ["14", 0],
                "positive": ["13", 0],
                "negative": ["13", 1],
                "latent_image": ["15", 0],
                "seed": 42,
                "steps": 16,
                "cfg": 2.5,
                "sampler_name": "er_sde",
                "scheduler": "beta",
                "denoise": denoise,
            },
        }
        graph["17"] = {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["16", 0],
                "vae": ["12", 0],
            },
        }
        graph[SAVE_IMAGE_ID]["inputs"]["images"] = ["17", 0]

    return graph


build_image_upscale_graph = build_upscale_graph


def build_video_upscale_graph(
    video_name: str,
    model_file: str,
    *,
    prefix: str = DEFAULT_PREFIX,
    filename_prefix: str = DEFAULT_FILENAME_PREFIX,
    sharpen: int = 0,
    sharpen_method: str = "legacy",
    rife_model: str | None = None,
) -> dict:
    """Grafo API de escalado de un video con nodos core, sharpen y RIFE opcional."""
    video_name = _require_plain_name(video_name, "upscale: video_name")
    model_file = _require_plain_name(model_file, "upscale: model_file")
    prefix = _require_prefix(prefix, "upscale: prefix", allow_empty=True)
    filename_prefix = _require_prefix(filename_prefix, "upscale: filename_prefix")
    sharpen = parse_sharpen(sharpen)
    sharpen_method = parse_sharpen_method(sharpen_method)
    save_prefix = f"{prefix}/{filename_prefix}" if prefix else filename_prefix

    graph = {
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

    last_images = [VIDEO_UPSCALE_ID, 0]
    if sharpen != 0:
        if sharpen_method == "rcas":
            strength = 0.45 if sharpen == 1 else 0.75
            graph["7"] = {
                "class_type": SHARPEN_KJ_CLASS,
                "inputs": {
                    "image": last_images,
                    "method": "rcas",
                    "method.strength": strength,
                },
            }
        elif sharpen_method == "adaptive_usm":
            strength = 0.45 if sharpen == 1 else 0.75
            graph["7"] = {
                "class_type": SHARPEN_KJ_CLASS,
                "inputs": {
                    "image": last_images,
                    "method": "adaptive_usm",
                    "method.strength": strength,
                    "method.radius": 1.0,
                    "method.threshold": 0.05,
                },
            }
        else:
            graph["7"] = {
                "class_type": SHARPEN_CLASS,
                "inputs": {"image": last_images, **SHARPEN_PRESETS[sharpen]},
            }
        last_images = ["7", 0]

    fps_source = [VIDEO_COMPONENTS_ID, 2]
    if rife_model:
        rife_ckpt = fps_ckpt(rife_model)
        graph["8"] = {
            "class_type": "ComfyMathExpression",
            "inputs": {
                "expression": "a * 2",
                "values.a": [VIDEO_COMPONENTS_ID, 2],
            },
        }
        graph["9"] = {
            "class_type": RIFE_CLASS,
            "inputs": {
                "ckpt_name": rife_ckpt,
                "frames": last_images,
                "multiplier": 2,
                **RIFE_DEFAULTS,
            },
        }
        last_images = ["9", 0]
        fps_source = ["8", 0]

    graph[CREATE_VIDEO_ID]["inputs"]["images"] = last_images
    graph[CREATE_VIDEO_ID]["inputs"]["fps"] = fps_source
    return graph


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
    params = {
        "task": "upscale",
        "source_gen": job.get("source_gen"),
        "source_file": job.get("source_file"),
        "model": job.get("model"),
        "scale": job.get("scale"),
        "passes": job.get("passes"),
        "sharpen": job.get("sharpen"),
    }
    if job.get("sharpen_method") and job.get("sharpen_method") != "legacy":
        params["sharpen_method"] = job.get("sharpen_method")
    if job.get("upscale_mode") and job.get("upscale_mode") != "fast":
        params["upscale_mode"] = job.get("upscale_mode")
    if job.get("denoise") is not None and job.get("upscale_mode") and job.get("upscale_mode") != "fast":
        params["denoise"] = job.get("denoise")
    return params


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
    passes, sharpen}`` (``passes`` normalizado a 1|2 y ``sharpen`` a 0|1|2).
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
        passes = parse_passes(job.get("passes"))
        job["passes"] = passes
        sharpen = parse_sharpen(job.get("sharpen"))
        job["sharpen"] = sharpen
        sharpen_method = parse_sharpen_method(job.get("sharpen_method"))
        job["sharpen_method"] = sharpen_method
        upscale_mode = parse_upscale_mode(job.get("upscale_mode"))
        job["upscale_mode"] = upscale_mode
        denoise = parse_denoise(job.get("denoise"))
        job["denoise"] = denoise
        model_file = resolve_upscale_model_file(job.get("model_file"), config)
        scale = job.get("scale") or 2
        if hasattr(config, "comfy_root") and job.get("image_name"):
            input_img = Path(config.comfy_root) / "input" / str(job["image_name"])
            if input_img.is_file():
                passes = clamp_or_validate_upscale_dimensions(
                    input_img,
                    scale=scale,
                    passes=passes,
                    model_file=model_file,
                )
        job["passes"] = passes
        job["params"] = _upscale_params(job)
        graph = build_upscale_graph(
            job.get("image_name"),
            model_file,
            passes=passes,
            sharpen=sharpen,
            sharpen_method=sharpen_method,
            upscale_mode=upscale_mode,
            denoise=denoise,
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
        native_scale = int(job.get("scale") or 0)
        output_scale = int(job.get("output_scale") or native_scale or 0)
        if native_scale > 0 and output_scale > 0 and output_scale != native_scale:
            ratio = output_scale / native_scale
            for name in names:
                target = gallery_dir / name
                try:
                    with Image.open(target) as img:
                        size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
                        resized = img.resize(size, Image.Resampling.LANCZOS)
                        resized.save(target)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("no se pudo ajustar escala de salida %s: %s", target, exc)
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
    params = {
        "task": "upscale_video",
        "source_gen": job.get("source_gen"),
        "source_file": job.get("source_file"),
        "model": job.get("model"),
        "scale": job.get("scale"),
        "fps": job.get("fps"),
    }
    if job.get("sharpen") is not None and job.get("sharpen") != 0:
        params["sharpen"] = job.get("sharpen")
    if job.get("sharpen_method") and job.get("sharpen_method") != "legacy":
        params["sharpen_method"] = job.get("sharpen_method")
    if job.get("rife_model"):
        params["rife_model"] = job.get("rife_model")
    if job.get("chunks") is not None:
        params["chunks"] = job.get("chunks")
        params["chunk_frames"] = job.get("chunk_frames")
    return params


def _run_ffmpeg(cmd: list[str], *, timeout: int = 600, label: str = "ffmpeg") -> None:
    """Ejecuta ffmpeg y convierte cualquier fallo en EngineError con stderr."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - se reporta como EngineError
        raise EngineError(f"error de {label}: {exc}") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise EngineError(f"error de {label}: {stderr[-800:]}")


def _video_has_audio(path: Path, ffmpeg_bin: str) -> bool:
    """Comprueba si el video tiene pista de audio sin fallar si ffmpeg devuelve 1."""
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return False
    return "Audio:" in (proc.stderr or "")


def _split_video_chunks(
    source: Path,
    out_dir: Path,
    *,
    frames: int,
    fps: float,
    chunk_frames: int,
    ffmpeg_bin: str,
) -> list[Path]:
    """Corta el video en tramos silenciosos de ``chunk_frames`` fotogramas."""
    if frames <= 0 or chunk_frames <= 0:
        raise EngineError("tramos invalidos: frames/chunk_frames vacios")
    if not math.isfinite(fps) or fps <= 0:
        raise EngineError("No se pudo determinar el fps para dividir el video")
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[Path] = []
    for index, start in enumerate(range(0, frames, chunk_frames)):
        count = min(chunk_frames, frames - start)
        target = out_dir / f"chunk_{index:03d}.mp4"
        _run_ffmpeg(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                str(source),
                "-ss",
                f"{start / fps:.6f}",
                "-frames:v",
                str(count),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-avoid_negative_ts",
                "make_zero",
                str(target),
            ],
            label="ffmpeg al dividir el video en tramos",
        )
        if not target.is_file() or target.stat().st_size == 0:
            raise EngineError(f"ffmpeg no genero el tramo {target.name}")
        chunks.append(target)
    return chunks


def _mux_original_audio(
    video_path: Path,
    original_path: Path,
    output_path: Path,
    *,
    ffmpeg_bin: str,
) -> None:
    """Remuxea el audio original sobre el video concatenado, sin reencodear video."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not _video_has_audio(original_path, ffmpeg_bin):
        shutil.copy2(video_path, output_path)
        return
    _run_ffmpeg(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(original_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ],
        label="ffmpeg al remuxear el audio original",
    )


def _submit_video_graph(
    *,
    engine: Any,
    tracker: Any,
    record: dict | None,
    job: dict,
    video_name: str,
    model_file: str,
    sharpen: int,
    sharpen_method: str,
    rife_model: str | None,
) -> list[Path]:
    graph = build_video_upscale_graph(
        video_name,
        model_file,
        prefix=job.get("prefix") or DEFAULT_PREFIX,
        filename_prefix=job.get("filename_prefix") or DEFAULT_FILENAME_PREFIX,
        sharpen=sharpen,
        sharpen_method=sharpen_method,
        rife_model=rife_model,
    )
    prompt_id = engine.submit(graph)
    if record is not None:
        record["prompt_id"] = prompt_id
    tracker.prompt_id = prompt_id
    history = engine.wait(prompt_id)
    paths = engine.outputs(history, expected_ext=VIDEO_EXT)
    if not paths:
        raise EngineError(f"el engine no devolvio ningun video para {prompt_id}")
    return paths


def run_video_upscale(
    job: dict,
    *,
    config: Any,
    store: Any,
    engine_factory: Callable[[], Any] = None,
    record: dict | None = None,
    ws_factory: Any = None,
) -> None:
    """Ejecuta un job de escalado de video, por tramos si hace falta.

    Mantiene el contrato de estado queued -> running -> done/error/cancelled.
    Si el video supera el presupuesto de un tramo, lo divide con ffmpeg,
    escala cada tramo en el mismo job (``job["progress"]["state"]`` indica
    "tramo i/N"), concatena y remuxea el audio original. Los temporales se
    eliminan siempre en el ``finally``.
    """
    gen_id = job["gen_id"]
    if record is not None and record.get("status") == "cancelled":
        job["params"] = _video_upscale_params(job)
        job["outputs"] = []
        job["error"] = None
        return
    tracker = None
    temp_dir: Path | None = None
    try:
        job["fps"] = parse_fps(job.get("fps"))
        sharpen = parse_sharpen(job.get("sharpen"))
        job["sharpen"] = sharpen
        sharpen_method = parse_sharpen_method(job.get("sharpen_method"))
        job["sharpen_method"] = sharpen_method
        rife_model = job.get("rife_model")
        if rife_model:
            rife_model = fps_ckpt(rife_model)
        job["rife_model"] = rife_model
        model_file = resolve_upscale_model_file(job.get("model_file"), config)
        plan: dict[str, Any] | None = None
        input_video_path: Path | None = None
        if config and hasattr(config, "comfy_input_dir") and job.get("video_name"):
            input_video_path = Path(config.comfy_input_dir) / job.get("video_name")
            if input_video_path.is_file():
                plan = validate_video_upscale_dimensions(
                    input_video_path,
                    scale=job.get("scale", 2),
                    model_file=model_file,
                    rife_multiplier=2 if rife_model else 1,
                )
                job["chunks"] = plan["chunks"]
                job["chunk_frames"] = plan["chunk_frames"]
                job["chunks_total"] = plan["chunks"]
        job["params"] = _video_upscale_params(job)
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

        gallery_dir = config.data_dir / "gallery" / str(gen_id)
        gallery_dir.mkdir(parents=True, exist_ok=True)
        names: list[str] = []

        chunks = int((plan or {}).get("chunks") or 1)
        if chunks > 1 and input_video_path is not None and plan is not None:
            ffmpeg_bin = find_ffmpeg()
            if not ffmpeg_bin:
                raise EngineError(
                    "ffmpeg no encontrado: el escalado por tramos necesita ffmpeg en "
                    "tools/ffmpeg/ffmpeg.exe o en el PATH"
                )
            temp_dir = Path(config.data_dir) / "tmp" / f"upscale_{gen_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            chunk_paths = _split_video_chunks(
                input_video_path,
                temp_dir,
                frames=int(plan["frames"]),
                fps=float(plan["fps"]),
                chunk_frames=int(plan["chunk_frames"]),
                ffmpeg_bin=ffmpeg_bin,
            )
            chunk_outputs: list[Path] = []
            for index, chunk_path in enumerate(chunk_paths):
                if (record is not None and record.get("status") == "cancelled") or getattr(
                    tracker, "is_cancelled", False
                ):
                    if record is not None:
                        record["status"] = "cancelled"
                    raise JobCancelledError("cancelado entre tramos")
                total = len(chunk_paths)
                job["chunk_index"] = index + 1
                job["chunks_total"] = total
                job["progress"] = {
                    "step": index + 1,
                    "total": total,
                    "percent": round((index / total) * 100, 1),
                    "state": f"tramo {index + 1}/{total}",
                    "node": "upscale_video",
                }
                input_name = f"{uuid.uuid4().hex}.mp4"
                input_chunk = Path(config.comfy_input_dir) / input_name
                shutil.copy2(chunk_path, input_chunk)
                try:
                    paths = _submit_video_graph(
                        engine=engine,
                        tracker=tracker,
                        record=record,
                        job=job,
                        video_name=input_name,
                        model_file=model_file,
                        sharpen=sharpen,
                        sharpen_method=sharpen_method,
                        rife_model=rife_model,
                    )
                finally:
                    input_chunk.unlink(missing_ok=True)
                chunk_out = temp_dir / f"out_{index:03d}.mp4"
                shutil.copy2(paths[0], chunk_out)
                chunk_outputs.append(chunk_out)

            concat_path = temp_dir / "concat.mp4"
            concat_videos(chunk_outputs, concat_path, ffmpeg_exe=ffmpeg_bin)
            final_path = temp_dir / "final.mp4"
            _mux_original_audio(
                concat_path,
                input_video_path,
                final_path,
                ffmpeg_bin=ffmpeg_bin,
            )
            target = gallery_dir / f"upscaled_{gen_id}.mp4"
            shutil.copy2(final_path, target)
            names = [target.name]
            job["progress"] = {
                "step": int((plan or {}).get("chunks") or 1),
                "total": int((plan or {}).get("chunks") or 1),
                "percent": 100.0,
                "state": "completado",
                "node": "upscale_video",
            }
        else:
            paths = _submit_video_graph(
                engine=engine,
                tracker=tracker,
                record=record,
                job=job,
                video_name=job.get("video_name"),
                model_file=model_file,
                sharpen=sharpen,
                sharpen_method=sharpen_method,
                rife_model=rife_model,
            )
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
        cancelled = (
            (record is not None and record.get("status") == "cancelled")
            or isinstance(exc, JobCancelledError)
            or (tracker is not None and getattr(tracker, "is_cancelled", False))
        )
        if cancelled:
            job["error"] = None
            if record is not None:
                record["status"] = "cancelled"
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
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)



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
        if config and hasattr(config, "comfy_input_dir") and job.get("video_name"):
            input_video_path = Path(config.comfy_input_dir) / job.get("video_name")
            if input_video_path.is_file():
                validate_video_upscale_dimensions(
                    input_video_path,
                    scale=2,
                    model_file=None,
                    rife_multiplier=multiplier,
                )
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


run_upscale_generation = run_upscale


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
    "MAX_UPSCALE_INPUT_SIDE",
    "MAX_UPSCALE_OUTPUT_SIDE",
    "MAX_VIDEO_UPSCALE_FRAMES",
    "MAX_VIDEO_UPSCALE_INPUT_BYTES",
    "MAX_VIDEO_UPSCALE_INPUT_SIDE",
    "MAX_VIDEO_UPSCALE_OUTPUT_BYTES",
    "MAX_VIDEO_UPSCALE_OUTPUT_SIDE",
    "MIN_UPSCALE_SCALE",
    "MODEL_LOADER_ID",
    "RIFE_CLASS",
    "RIFE_DEFAULTS",
    "SAVE_IMAGE_ID",
    "SAVE_VIDEO_FORMAT",
    "SAVE_VIDEO_ID",
    "SHARPEN_CLASS",
    "SHARPEN_ID",
    "SHARPEN_KJ_CLASS",
    "SHARPEN_PRESETS",
    "UPSCALE2_ID",
    "UPSCALERS_PATH",
    "UPSCALE_ID",
    "UPSCALE_PASSES",
    "UPSCALE_SHARPEN",
    "VALID_SHARPEN_METHODS",
    "VALID_UPSCALE_MODES",
    "VIDEO_COMPONENTS_ID",
    "VIDEO_EXT",
    "VIDEO_HISTORY_TIMEOUT_S",
    "VIDEO_MODEL_LOADER_ID",
    "VIDEO_UPSCALE_ID",
    "build_fps_graph",
    "build_image_upscale_graph",
    "build_upscale_graph",
    "build_video_upscale_graph",
    "clamp_or_validate_upscale_dimensions",
    "detect_gpu_vram_gb",
    "evaluate_upscale_risk",
    "fps_ckpt",
    "fps_multiplier",
    "frame_interpolation",
    "get_upscaler",
    "list_upscalers",
    "load_frame_interpolation",
    "load_upscalers",
    "parse_denoise",
    "parse_fps",
    "parse_passes",
    "parse_sharpen",
    "parse_sharpen_method",
    "parse_upscale_mode",
    "probe_video_metadata",
    "resolve_upscale_model_file",
    "run_fps",
    "run_upscale",
    "run_upscale_generation",
    "run_video_upscale",
    "upscalers",
    "validate_video_upscale_dimensions",
]
