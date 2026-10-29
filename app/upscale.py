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
from pathlib import Path
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

from app.config import APP_ROOT
from app.engine import ComfyEngine, EngineError
from app.progress import ProgressTracker

logger = logging.getLogger(__name__)

UPSCALERS_PATH = APP_ROOT / "registry" / "upscalers-v1.json"
CATALOG_VERSION = 1
MIN_UPSCALE_SCALE = 1
MAX_UPSCALE_INPUT_SIDE = 2560
MAX_UPSCALE_OUTPUT_SIDE = 4096
MAX_VIDEO_UPSCALE_INPUT_SIDE = 1920
MAX_VIDEO_UPSCALE_OUTPUT_SIDE = 3840  # 2160p (4K UHD)
MAX_VIDEO_UPSCALE_FRAMES = 300  # Presupuesto maximo de fotogramas batch (12 GB VRAM)
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


def validate_video_upscale_dimensions(
    video_path: Path | str,
    *,
    scale: int = 2,
    model_file: str | None = None,
    ffprobe_bin: str | Path | None = None,
) -> dict[str, Any]:
    """Valida que la resolucion, fotogramas y memoria del video no excedan la VRAM (12 GB).

    Lanza EngineError (HTTP 400) si:
    - No se pueden leer las dimensiones o los fotogramas del video
    - El lado mayor supera MAX_VIDEO_UPSCALE_INPUT_SIDE (1920 px)
    - La resolucion esperada de salida supera MAX_VIDEO_UPSCALE_OUTPUT_SIDE (3840 px / 2160p)
    - El numero de fotogramas supera MAX_VIDEO_UPSCALE_FRAMES (300 fotogramas)
    - El presupuesto de memoria de entrada supera MAX_VIDEO_UPSCALE_INPUT_BYTES (4 GiB)
    - El presupuesto de memoria de salida supera MAX_VIDEO_UPSCALE_OUTPUT_BYTES (16 GiB)
    """
    path = Path(video_path)
    if not path.is_file():
        raise EngineError(f"Archivo de video no encontrado: {path}")

    meta = probe_video_metadata(path, ffprobe_bin=ffprobe_bin)
    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)

    # 1. meta = probe; si width<=0 o height<=0 => EngineError claro
    if width <= 0 or height <= 0:
        raise EngineError(f"No se pudieron leer las dimensiones del video: {path.name}")

    # 2. frames: si meta["frames"]<=0, calcular round(duration*fps); si sigue <=0 => EngineError
    frames = int(meta.get("frames") or 0)
    if frames <= 0:
        duration = float(meta.get("duration") or 0.0)
        fps = float(meta.get("fps") or 0.0)
        if duration > 0 and fps > 0:
            frames = round(duration * fps)
        if frames <= 0:
            raise EngineError(f"No se pudo determinar el numero de fotogramas del video: {path.name}")
        meta["frames"] = frames

    # 3. comprobar max side input/output (como ahora)
    if max(width, height) > MAX_VIDEO_UPSCALE_INPUT_SIDE:
        raise EngineError(
            f"El video de entrada es demasiado grande para escalar ({width}x{height} px; "
            f"maximo permitido de entrada: {MAX_VIDEO_UPSCALE_INPUT_SIDE} px en el lado mayor). "
            f"Para 12 GB de VRAM reduzca la resolucion a 1080p o inferior antes de escalar."
        )

    effective_scale = (
        2
        if model_file == "RealESRGAN_x2.pth"
        else (scale if isinstance(scale, int) and scale > 0 else 2)
    )

    out_side = max(width, height) * effective_scale
    if out_side > MAX_VIDEO_UPSCALE_OUTPUT_SIDE:
        raise EngineError(
            f"El escalado solicitado ({width}x{height} px x {effective_scale} = {width*effective_scale}x{height*effective_scale} px) "
            f"supera el limite de salida permitido para 12 GB VRAM ({MAX_VIDEO_UPSCALE_OUTPUT_SIDE} px / 2160p)."
        )

    # 4. comprobar frames > MAX_VIDEO_UPSCALE_FRAMES => EngineError
    if frames > MAX_VIDEO_UPSCALE_FRAMES:
        raise EngineError(
            f"El video tiene demasiados fotogramas ({frames} frames; "
            f"maximo permitido para escalado en batch: {MAX_VIDEO_UPSCALE_FRAMES} frames). "
            f"Reduzca la duracion del clip antes de escalar."
        )

    # 5. input_bytes y output_bytes
    input_bytes = frames * width * height * 3 * 4
    output_w = round(width * effective_scale)
    output_h = round(height * effective_scale)
    output_bytes = frames * output_w * output_h * 3 * 4

    # 6. si input_bytes > MAX_VIDEO_UPSCALE_INPUT_BYTES => EngineError con GB y límite
    if input_bytes > MAX_VIDEO_UPSCALE_INPUT_BYTES:
        raise EngineError(
            f"El presupuesto de memoria de entrada ({input_bytes / (1024**3):.2f} GB) supera "
            f"el maximo permitido ({MAX_VIDEO_UPSCALE_INPUT_BYTES / (1024**3):.1f} GB). "
            f"Reduzca la resolucion o los fotogramas."
        )

    # 7. si output_bytes > MAX_VIDEO_UPSCALE_OUTPUT_BYTES => EngineError con GB y límite
    if output_bytes > MAX_VIDEO_UPSCALE_OUTPUT_BYTES:
        raise EngineError(
            f"El presupuesto de memoria de salida ({output_bytes / (1024**3):.2f} GB) supera "
            f"el maximo permitido ({MAX_VIDEO_UPSCALE_OUTPUT_BYTES / (1024**3):.1f} GB). "
            f"Reduzca la escala, resolucion o fotogramas."
        )

    return meta


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
                "unet_name": "Anima-2.9B-preview-v1.safetensors",
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
    return params


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
        sharpen = parse_sharpen(job.get("sharpen"))
        job["sharpen"] = sharpen
        sharpen_method = parse_sharpen_method(job.get("sharpen_method"))
        job["sharpen_method"] = sharpen_method
        rife_model = job.get("rife_model")
        if rife_model:
            rife_model = fps_ckpt(rife_model)
        job["rife_model"] = rife_model
        job["params"] = _video_upscale_params(job)
        model_file = resolve_upscale_model_file(job.get("model_file"), config)
        if config and hasattr(config, "comfy_input_dir") and job.get("video_name"):
            input_video_path = Path(config.comfy_input_dir) / job.get("video_name")
            if input_video_path.is_file():
                validate_video_upscale_dimensions(
                    input_video_path,
                    scale=job.get("scale", 2),
                    model_file=model_file,
                )
        graph = build_video_upscale_graph(
            job.get("video_name"),
            model_file,
            prefix=job.get("prefix") or DEFAULT_PREFIX,
            filename_prefix=job.get("filename_prefix") or DEFAULT_FILENAME_PREFIX,
            sharpen=sharpen,
            sharpen_method=sharpen_method,
            rife_model=rife_model,
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
        if config and hasattr(config, "comfy_input_dir") and job.get("video_name"):
            input_video_path = Path(config.comfy_input_dir) / job.get("video_name")
            if input_video_path.is_file():
                validate_video_upscale_dimensions(
                    input_video_path,
                    scale=2,
                    model_file=None,
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
