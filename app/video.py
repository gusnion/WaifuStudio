"""Grafos y runner de video (F4/M9-F1): Wan 2.2 I2V/FLF2V y MiniMax H3 FL2VA.

Sin GPU y sin red: las plantillas certificadas viven en `workflows/` (Wan
exportado del legacy con funciones puras; H3 copiado verbatim del certificado).
`prepare_*` parchea sobre copias profundas validando nodos/campos y
`run_video_generation` encola en el engine, copia los videos a la galería,
refleja el estado en el store (``kind="video"``) y registra el tracker de
progreso (M9-F1) para que `GET /api/jobs/{id}` sirva `progress`.

M9-F1 añade FLF2V (primer+último frame), la duración en segundos (frames 4n+1 a
16 fps, 1..15 s) y la tabla de VRAM para 12 GB (`frames_for_seconds`,
`vram_hint`).
"""

from __future__ import annotations

import copy
import math
import shutil
from pathlib import Path
from typing import Any, Callable

from app.config import APP_ROOT
from app.engine import ComfyEngine, EngineError, load_graph
from app.motion import MOTION_NEGATIVE
from app.params import is_valid_sampler, is_valid_scheduler
from app.progress import ProgressTracker
from app.video_presets import PRESET_MANUAL, resolve_video_preset

WAN_TEMPLATE_PATH = APP_ROOT / "workflows" / "wan22_i2v_432x768.api.json"
WAN_FLF_TEMPLATE_PATH = APP_ROOT / "workflows" / "wan22_flf2v_432x768.api.json"
H3_TEMPLATE_PATH = APP_ROOT / "workflows" / "h3_fl2va_vertical.api.json"

# El video puede tardar mucho mas que una imagen (H3 8 s en 4 pasos + decodificacion).
VIDEO_HISTORY_TIMEOUT_S = 3600.0
VIDEO_EXT = ("mp4", "webm")

# Wan: perfil del plan (vertical 432x768); horizontal simetrico 768x432.
ASPECTS = {"vertical": (432, 768), "horizontal": (768, 432)}

SAMPLER_CLASSES = ("KSampler", "KSamplerAdvanced")

# Perfil certificado de Wan (nodo 10/11 shift 8.0; samplers 12/13 euler/simple/20).
MODEL_SAMPLING_CLASS = "ModelSamplingSD3"
WAN_HIGH_SAMPLER_ID = "12"
WAN_LOW_SAMPLER_ID = "13"
WAN_DEFAULT_SAMPLER = "euler"
WAN_DEFAULT_SCHEDULER = "simple"
WAN_DEFAULT_STEPS = 20
WAN_DEFAULT_SHIFT = 8.0
MIN_VIDEO_STEPS = 1
MAX_VIDEO_STEPS = 200

# Duracion (M9-F1): Wan exige length 4n+1 y su CreateVideo va a 16 fps.
VIDEO_FPS = 16.0
MIN_VIDEO_SECONDS = 1.0
MAX_VIDEO_SECONDS = 15.0

# Tabla VRAM 12 GB (perfil certificado 432x768, 16 fps, 20 pasos, GGUF Q4_K_S).
VRAM_COMFORT_FRAMES = 81  # <= 5 s
VRAM_TIGHT_FRAMES = 121  # 5-7.5 s: entra pero mas lento
WAN_FLF_MODE = "flf2v"


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"{label} vacio")
    return value.strip()


def _require_seed(seed: Any) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        try:
            seed = int(seed)
        except (TypeError, ValueError) as exc:
            raise EngineError(f"seed invalida: {seed!r}") from exc
    return seed


def _node_inputs(graph: dict, node_id: str, class_type: str) -> dict:
    """Inputs del nodo `node_id`, exigiendo el `class_type` esperado."""
    node = graph.get(str(node_id))
    if not isinstance(node, dict):
        raise EngineError(f"grafo sin nodo {node_id!r}")
    if node.get("class_type") != class_type:
        raise EngineError(
            f"nodo {node_id!r} no es {class_type}: {node.get('class_type')!r}"
        )
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise EngineError(f"nodo {node_id!r} sin inputs dict")
    return inputs


def _require_field(inputs: dict, field: str, node_id: str) -> None:
    if field not in inputs:
        raise EngineError(f"nodo {node_id!r} sin campo {field!r}")


def _find_node(graph: dict, class_type: str) -> tuple[str, dict]:
    for node_id, node in graph.items():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                raise EngineError(f"nodo {node_id!r} sin inputs dict")
            return node_id, inputs
    raise EngineError(f"grafo sin nodo {class_type}")


def _set_sampler_seed(graph: dict, seed: int) -> None:
    samplers = 0
    for node_id, node in graph.items():
        if not isinstance(node, dict) or node.get("class_type") not in SAMPLER_CLASSES:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise EngineError(f"nodo {node_id!r} sin inputs dict")
        if "seed" in inputs:
            inputs["seed"] = seed
        elif "noise_seed" in inputs:
            inputs["noise_seed"] = seed
        else:
            raise EngineError(f"nodo {node_id!r} sin campo de seed")
        samplers += 1
    if not samplers:
        raise EngineError("grafo sin KSampler: no se puede fijar la seed")


def _require_frames(frames: Any) -> int:
    """Valida length 4n+1 (n>=1: 5, 9, ..., 81, ...) y lo devuelve."""
    if isinstance(frames, bool) or not isinstance(frames, int):
        raise EngineError(f"video: frames invalido {frames!r}; usar entero 4n+1")
    if frames < 5 or frames % 4 != 1:
        raise EngineError(
            f"video: length invalida {frames}; Wan exige 4n+1 con n>=1 (5, 9, ..., 81)"
        )
    return frames


def _patch_length(inputs: dict, node_id: str, frames: int) -> None:
    """Fija `length` del nodo video (I2V/FLF) validando 4n+1."""
    _require_field(inputs, "length", node_id)
    inputs["length"] = _require_frames(frames)


def _require_sampler_name(value: Any, label: str) -> str:
    if not is_valid_sampler(value):
        raise EngineError(f"{label}: sampler_name invalido: {value!r}")
    return value


def _require_scheduler(value: Any, label: str) -> str:
    if not is_valid_scheduler(value):
        raise EngineError(f"{label}: scheduler invalido: {value!r}")
    return value


def _require_steps(value: Any, label: str) -> int:
    """Entero (no bool) 1..200; los float integrales se normalizan a int."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineError(
            f"{label}: steps invalido {value!r}; usar entero {MIN_VIDEO_STEPS}..{MAX_VIDEO_STEPS}"
        )
    steps = value
    if isinstance(steps, float):
        if not math.isfinite(steps) or not steps.is_integer():
            raise EngineError(
                f"{label}: steps invalido {value!r}; usar entero "
                f"{MIN_VIDEO_STEPS}..{MAX_VIDEO_STEPS}"
            )
        steps = int(steps)
    if not MIN_VIDEO_STEPS <= steps <= MAX_VIDEO_STEPS:
        raise EngineError(
            f"{label}: steps fuera de {MIN_VIDEO_STEPS}..{MAX_VIDEO_STEPS}: {value!r}"
        )
    return int(steps)


def _require_shift(value: Any, label: str) -> float:
    """Numero finito > 0 (rechaza bool, NaN e infinitos)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineError(f"{label}: shift invalido {value!r}; usar numero > 0")
    shift = float(value)
    if not math.isfinite(shift) or shift <= 0:
        raise EngineError(f"{label}: shift invalido {value!r}; usar numero > 0")
    return shift


def _patch_samplers(
    graph: dict,
    *,
    sampler_name: str | None,
    scheduler: str | None,
    steps: int | None,
) -> None:
    """Aplica sampler/scheduler/steps a TODOS los nodos sampler del grafo."""
    if sampler_name is None and scheduler is None and steps is None:
        return
    applied = 0
    for node_id, node in graph.items():
        if not isinstance(node, dict) or node.get("class_type") not in SAMPLER_CLASSES:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise EngineError(f"nodo {node_id!r} sin inputs dict")
        for field, value in (
            ("sampler_name", sampler_name),
            ("scheduler", scheduler),
            ("steps", steps),
        ):
            if value is None:
                continue
            _require_field(inputs, field, node_id)
            inputs[field] = value
        applied += 1
    if not applied:
        raise EngineError("grafo sin KSampler: no se pueden aplicar los overrides")


def _patch_wan_split(graph: dict, steps: int) -> None:
    """Reparte high/low para `steps`: 12 end_at_step=steps//2, 13 start_at_step=steps//2.

    El sampler alto conserva ``end_at_step=10000``/``add_noise`` del certificado;
    con N=20 el reparto es 10/10, identico a la plantilla.
    """
    mid = steps // 2
    high = _node_inputs(graph, WAN_HIGH_SAMPLER_ID, "KSamplerAdvanced")
    _require_field(high, "end_at_step", WAN_HIGH_SAMPLER_ID)
    high["end_at_step"] = mid
    low = _node_inputs(graph, WAN_LOW_SAMPLER_ID, "KSamplerAdvanced")
    _require_field(low, "start_at_step", WAN_LOW_SAMPLER_ID)
    low["start_at_step"] = mid


def _patch_shift(graph: dict, shift: float) -> None:
    """Aplica `shift` a TODOS los nodos ModelSamplingSD3 del grafo."""
    applied = 0
    for node_id, node in graph.items():
        if not isinstance(node, dict) or node.get("class_type") != MODEL_SAMPLING_CLASS:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise EngineError(f"nodo {node_id!r} sin inputs dict")
        _require_field(inputs, "shift", node_id)
        inputs["shift"] = shift
        applied += 1
    if not applied:
        raise EngineError(
            f"grafo sin {MODEL_SAMPLING_CLASS}: no se puede aplicar shift"
        )


def _progress_ws_url(config: Any) -> str:
    """WS del engine desde `comfy_url` (misma semantica que `app.server`).

    Se duplica aqui (8 lineas) para no importar `app.server` desde el modulo de
    video (ciclo server -> video).
    """
    base = str(config.comfy_url).rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return f"{base}/ws"


def frames_for_seconds(seconds: float, fps: float = VIDEO_FPS) -> int:
    """Menor length 4n+1 >= `seconds` a `fps` (Wan solo acepta 4n+1).

    `needed = ceil(seconds*fps)`; el resultado es
    `needed + ((4 - (needed-1) % 4) % 4)`. Rango 1..15 s (EngineError fuera),
    `fps` positivo (default 16, el certificado de Wan). Con fps=16 los enteros
    del rango dan 17 (1 s), 81 (5 s), 129 (8 s) y 241 (15 s).
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise EngineError(
            f"video: seconds invalido {seconds!r}; usar un numero entre 1 y 15"
        )
    value = float(seconds)
    if not math.isfinite(value) or not MIN_VIDEO_SECONDS <= value <= MAX_VIDEO_SECONDS:
        raise EngineError(f"video: seconds fuera de rango (1-15): {seconds!r}")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)):
        raise EngineError(f"video: fps invalido {fps!r}")
    rate = float(fps)
    if not math.isfinite(rate) or rate <= 0:
        raise EngineError(f"video: fps invalido {fps!r}")
    needed = math.ceil(value * rate)
    return needed + ((4 - (needed - 1) % 4) % 4)


def vram_hint(frames: int, width: int, height: int) -> str:
    """Aviso de VRAM para 12 GB segun los tramos certificados de Wan.

    Tabla (perfil 432x768, 16 fps, 20 pasos, GGUF Q4_K_S high+low):

    | frames   | duracion | veredicto                                  |
    |----------|----------|--------------------------------------------|
    | <= 81    | <= 5 s   | "cabe en 12 GB (perfil certificado)"       |
    | 82..121  | 5-7.5 s  | "ajustado, más lento" (sin certificar)     |
    | > 121    | > 7.5 s  | "riesgo de OOM en 12 GB; no certificado"   |

    El tamano va solo informativo: la certificacion es a 432x768.
    """
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
        raise EngineError(f"video: frames invalido {frames!r}")
    for name, size in (("width", width), ("height", height)):
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise EngineError(f"video: {name} invalido {size!r}")
    label = f"{frames} frames a {width}x{height}"
    if frames <= VRAM_COMFORT_FRAMES:
        return f"{label}: cabe en 12 GB (perfil certificado)"
    if frames <= VRAM_TIGHT_FRAMES:
        return f"{label}: ajustado, más lento"
    return f"{label}: riesgo de OOM en 12 GB; no certificado"



def resolve_wan_profile(
    *,
    preset: object = None,
    aspect: object = "vertical",
    sampler_name: object = None,
    scheduler: object = None,
    steps: object = None,
    shift: object = None,
) -> dict[str, Any]:
    """Perfil efectivo de Wan: overrides explicitos > preset > certificado.

    Devuelve ``{"preset", "sampler_name", "scheduler", "steps", "shift",
    "width", "height"}``. ``preset`` ausente/``""``/``"manual"`` = sin preset
    (tamano de ``ASPECTS`` y perfil certificado euler/simple/20/8.0); con preset
    el tamano sale de su par vertical/horizontal segun ``aspect``. EngineError
    si el preset, el aspecto o un override no validan.
    """
    if aspect not in ASPECTS:
        raise EngineError(f"video: aspect invalido {aspect!r}; usar vertical|horizontal")
    entry = resolve_video_preset(preset)
    if entry is None:
        profile: dict[str, Any] = {
            "preset": PRESET_MANUAL,
            "sampler_name": WAN_DEFAULT_SAMPLER,
            "scheduler": WAN_DEFAULT_SCHEDULER,
            "steps": WAN_DEFAULT_STEPS,
            "shift": WAN_DEFAULT_SHIFT,
            "width": ASPECTS[aspect][0],
            "height": ASPECTS[aspect][1],
        }
    else:
        profile = {
            "preset": entry["id"],
            "sampler_name": entry["sampler"],
            "scheduler": entry["scheduler"],
            "steps": entry["steps"],
            "shift": entry["shift"],
            "width": entry[aspect]["width"],
            "height": entry[aspect]["height"],
        }
    if sampler_name is not None:
        profile["sampler_name"] = _require_sampler_name(sampler_name, "video")
    if scheduler is not None:
        profile["scheduler"] = _require_scheduler(scheduler, "video")
    if steps is not None:
        profile["steps"] = _require_steps(steps, "video")
    if shift is not None:
        profile["shift"] = _require_shift(shift, "video")
    return profile


def prepare_wan_graph(
    graph: dict,
    *,
    image_name: str,
    motion_positive: str,
    motion_negative: str,
    width: int = 432,
    height: int = 768,
    seed: int,
    frames: int | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    steps: int | None = None,
    shift: float | None = None,
) -> dict:
    """Copia el grafo Wan I2V y fija textos, imagen, tamaño y seed.

    Nodos del perfil certificado: CLIPTextEncode ``5`` (positivo) y ``6``
    (negativo), LoadImage ``7`` (primer frame), ``WanImageToVideo`` (width/
    height) y la seed en todos los samplers (``noise_seed``/``seed``).
    `frames` opcional parchea `length` del nodo I2V (debe ser 4n+1). Los
    overrides opcionales van a todos los samplers (``sampler_name``/
    ``scheduler``/``steps``, con reparto high/low ``steps//2``) y a ambos
    ``ModelSamplingSD3`` (``shift``).
    """
    image_name = _require_text(image_name, "wan: image_name")
    motion_positive = _require_text(motion_positive, "wan: motion_positive")
    motion_negative = _require_text(motion_negative, "wan: motion_negative")
    seed = _require_seed(seed)
    if sampler_name is not None:
        sampler_name = _require_sampler_name(sampler_name, "wan")
    if scheduler is not None:
        scheduler = _require_scheduler(scheduler, "wan")
    if steps is not None:
        steps = _require_steps(steps, "wan")
    if shift is not None:
        shift = _require_shift(shift, "wan")
    for name, size in (("width", width), ("height", height)):
        if isinstance(size, bool) or not isinstance(size, int):
            raise EngineError(f"wan: {name} invalido: {size!r}")
        if size < 16 or size % 16 != 0:
            raise EngineError(f"wan: {name} fuera de rango (min 16, paso 16): {size}")

    prepared = copy.deepcopy(graph)
    positive = _node_inputs(prepared, "5", "CLIPTextEncode")
    _require_field(positive, "text", "5")
    positive["text"] = motion_positive
    negative = _node_inputs(prepared, "6", "CLIPTextEncode")
    _require_field(negative, "text", "6")
    negative["text"] = motion_negative
    first = _node_inputs(prepared, "7", "LoadImage")
    _require_field(first, "image", "7")
    first["image"] = image_name
    to_video_id, to_video = _find_node(prepared, "WanImageToVideo")
    for field in ("width", "height"):
        _require_field(to_video, field, to_video_id)
    to_video["width"] = width
    to_video["height"] = height
    if frames is not None:
        _patch_length(to_video, to_video_id, frames)
    _set_sampler_seed(prepared, seed)
    _patch_samplers(
        prepared, sampler_name=sampler_name, scheduler=scheduler, steps=steps
    )
    if steps is not None:
        _patch_wan_split(prepared, steps)
    if shift is not None:
        _patch_shift(prepared, shift)
    return prepared


def prepare_wan_flf_graph(
    graph: dict,
    *,
    first_image_name: str,
    last_image_name: str,
    motion_positive: str,
    motion_negative: str,
    width: int = 432,
    height: int = 768,
    seed: int,
    frames: int | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    steps: int | None = None,
    shift: float | None = None,
) -> dict:
    """Copia el grafo Wan FLF2V y fija primer/último frame, textos, tamaño y seed.

    Los dos LoadImage se localizan POR ORDEN de inserción del grafo (los dict de
    Python conservan el orden): el export `build_wan_graph` inserta el primer
    frame (nodo ``7``) antes que el último (nodo ``8``), y
    ``WanFirstLastFrameToVideo`` los enlaza como ``start_image``/``end_image``.
    Se exige que haya exactamente dos LoadImage (EngineError si no). Los
    CLIPTextEncode son los del perfil certificado (``5`` positivo, ``6``
    negativo). `frames` opcional parchea `length` del nodo FLF (4n+1). Los
    overrides opcionales de muestreo son los mismos que en `prepare_wan_graph`.
    """
    first_image_name = _require_text(first_image_name, "wan-flf: first_image_name")
    last_image_name = _require_text(last_image_name, "wan-flf: last_image_name")
    motion_positive = _require_text(motion_positive, "wan-flf: motion_positive")
    motion_negative = _require_text(motion_negative, "wan-flf: motion_negative")
    seed = _require_seed(seed)
    if sampler_name is not None:
        sampler_name = _require_sampler_name(sampler_name, "wan-flf")
    if scheduler is not None:
        scheduler = _require_scheduler(scheduler, "wan-flf")
    if steps is not None:
        steps = _require_steps(steps, "wan-flf")
    if shift is not None:
        shift = _require_shift(shift, "wan-flf")
    for name, size in (("width", width), ("height", height)):
        if isinstance(size, bool) or not isinstance(size, int):
            raise EngineError(f"wan-flf: {name} invalido: {size!r}")
        if size < 16 or size % 16 != 0:
            raise EngineError(
                f"wan-flf: {name} fuera de rango (min 16, paso 16): {size}"
            )

    prepared = copy.deepcopy(graph)
    load_images: list[tuple[str, dict]] = []
    for node_id, node in prepared.items():
        if isinstance(node, dict) and node.get("class_type") == "LoadImage":
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                raise EngineError(f"nodo {node_id!r} sin inputs dict")
            load_images.append((node_id, inputs))
    if len(load_images) != 2:
        raise EngineError(
            f"wan-flf: se esperan 2 LoadImage (first/last), hay {len(load_images)}"
        )
    first_id, first = load_images[0]
    last_id, last = load_images[1]
    _require_field(first, "image", first_id)
    first["image"] = first_image_name
    _require_field(last, "image", last_id)
    last["image"] = last_image_name

    positive = _node_inputs(prepared, "5", "CLIPTextEncode")
    _require_field(positive, "text", "5")
    positive["text"] = motion_positive
    negative = _node_inputs(prepared, "6", "CLIPTextEncode")
    _require_field(negative, "text", "6")
    negative["text"] = motion_negative

    to_video_id, to_video = _find_node(prepared, "WanFirstLastFrameToVideo")
    for field in ("width", "height"):
        _require_field(to_video, field, to_video_id)
    to_video["width"] = width
    to_video["height"] = height
    if frames is not None:
        _patch_length(to_video, to_video_id, frames)
    _set_sampler_seed(prepared, seed)
    _patch_samplers(
        prepared, sampler_name=sampler_name, scheduler=scheduler, steps=steps
    )
    if steps is not None:
        _patch_wan_split(prepared, steps)
    if shift is not None:
        _patch_shift(prepared, shift)
    return prepared


def prepare_h3_graph(
    graph: dict,
    *,
    first_image_name: str,
    last_image_name: str,
    prompt: str,
    seed: int,
) -> dict:
    """Copia el grafo H3 FL2VA y fija primer/último frame, prompt y seed.

    Nodos del certificado: LoadImage ``140``/``141`` (first/last),
    ``MiniMaxH3ImageToVideo`` ``131`` (prompt) y ``RandomNoise`` ``129``.
    """
    first_image_name = _require_text(first_image_name, "h3: first_image_name")
    last_image_name = _require_text(last_image_name, "h3: last_image_name")
    prompt = _require_text(prompt, "h3: prompt")
    seed = _require_seed(seed)

    prepared = copy.deepcopy(graph)
    first = _node_inputs(prepared, "140", "LoadImage")
    _require_field(first, "image", "140")
    first["image"] = first_image_name
    last = _node_inputs(prepared, "141", "LoadImage")
    _require_field(last, "image", "141")
    last["image"] = last_image_name
    to_video = _node_inputs(prepared, "131", "MiniMaxH3ImageToVideo")
    _require_field(to_video, "prompt", "131")
    to_video["prompt"] = prompt
    noise = _node_inputs(prepared, "129", "RandomNoise")
    _require_field(noise, "noise_seed", "129")
    noise["noise_seed"] = seed
    return prepared


def build_video_graph(job: dict) -> dict:
    """Carga la plantilla del job y aplica la preparación del motor.

    Para `engine="wan"`, `mode` (`i2v`|`flf2v`) elige el `prepare_*`; si falta,
    se infiere del nombre de la plantilla (`wan22_flf2v_...` → flf2v). El job
    puede traer `frames` (4n+1) para parchear `length` y, para Wan, `preset`
    (id, ``"manual"`` o ausente) y overrides `sampler_name`/`scheduler`/`steps`/
    `shift` resueltos con `resolve_wan_profile` (overrides > preset >
    certificado). H3 ignora esos campos.
    """
    template = job.get("template")
    if not isinstance(template, str) or not template.strip():
        raise EngineError("video: template requerido")
    graph = load_graph(template)
    engine_kind = job.get("engine")
    seed = _require_seed(job.get("seed", 42))
    if engine_kind == "wan":
        profile = resolve_wan_profile(
            preset=job.get("preset"),
            aspect=job.get("aspect") or "vertical",
            sampler_name=job.get("sampler_name"),
            scheduler=job.get("scheduler"),
            steps=job.get("steps"),
            shift=job.get("shift"),
        )
        mode = job.get("mode")
        if mode is None:
            mode = (
                WAN_FLF_MODE
                if Path(template).name == WAN_FLF_TEMPLATE_PATH.name
                else "i2v"
            )
        if mode not in ("i2v", WAN_FLF_MODE):
            raise EngineError(f"video: mode invalido {mode!r}; usar i2v|flf2v")
        common = {
            "width": profile["width"],
            "height": profile["height"],
            "seed": seed,
            "frames": job.get("frames"),
            "sampler_name": profile["sampler_name"],
            "scheduler": profile["scheduler"],
            "steps": profile["steps"],
            "shift": profile["shift"],
        }
        if mode == WAN_FLF_MODE:
            return prepare_wan_flf_graph(
                graph,
                first_image_name=job.get("image_name"),
                last_image_name=job.get("last_image_name"),
                motion_positive=job.get("motion_positive"),
                motion_negative=job.get("motion_negative") or MOTION_NEGATIVE,
                **common,
            )
        return prepare_wan_graph(
            graph,
            image_name=job.get("image_name"),
            motion_positive=job.get("motion_positive"),
            motion_negative=job.get("motion_negative") or MOTION_NEGATIVE,
            **common,
        )
    if engine_kind == "h3":
        return prepare_h3_graph(
            graph,
            first_image_name=job.get("image_name"),
            last_image_name=job.get("last_image_name"),
            prompt=job.get("prompt"),
            seed=seed,
        )
    raise EngineError(f"video: engine invalido {engine_kind!r}; usar wan|h3")


def run_video_generation(
    job: dict,
    *,
    config: Any,
    store: Any,
    engine_factory: Callable[[], Any],
    ws_factory: Any = None,
    record: dict | None = None,
) -> None:
    """Ejecuta un job de video: grafo -> engine -> galería -> store.

    `record` es el registro de `_JOBS[gen_id]` del server (M9-F1): si se pasa,
    se le registran engine, `prompt_id`, tracker y estado (queued → running →
    done/error/cancelled) como en imagen; el `ProgressTracker` se crea antes del
    submit (con `ws_factory` inyectable) y se para en el `finally`. No propaga
    errores: el fallo se guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    if record is not None and record.get("status") == "cancelled":
        job["outputs"] = []
        job["error"] = None
        return
    tracker = None
    try:
        graph = build_video_graph(job)
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


__all__ = [
    "ASPECTS",
    "H3_TEMPLATE_PATH",
    "MAX_VIDEO_SECONDS",
    "MAX_VIDEO_STEPS",
    "MIN_VIDEO_SECONDS",
    "MIN_VIDEO_STEPS",
    "MODEL_SAMPLING_CLASS",
    "SAMPLER_CLASSES",
    "VIDEO_EXT",
    "VIDEO_FPS",
    "VIDEO_HISTORY_TIMEOUT_S",
    "VRAM_COMFORT_FRAMES",
    "VRAM_TIGHT_FRAMES",
    "WAN_DEFAULT_SAMPLER",
    "WAN_DEFAULT_SCHEDULER",
    "WAN_DEFAULT_SHIFT",
    "WAN_DEFAULT_STEPS",
    "WAN_FLF_TEMPLATE_PATH",
    "WAN_HIGH_SAMPLER_ID",
    "WAN_LOW_SAMPLER_ID",
    "WAN_TEMPLATE_PATH",
    "build_video_graph",
    "frames_for_seconds",
    "prepare_h3_graph",
    "prepare_wan_flf_graph",
    "prepare_wan_graph",
    "resolve_wan_profile",
    "run_video_generation",
    "vram_hint",
]
