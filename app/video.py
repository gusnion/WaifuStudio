"""Grafos y runner de video (F4): Wan 2.2 I2V y MiniMax H3 FL2VA.

Sin GPU y sin red: las plantillas certificadas viven en `workflows/` (Wan
exportado del legacy con funciones puras; H3 copiado verbatim del certificado).
`prepare_*` parchea sobre copias profundas validando nodos/campos y
`run_video_generation` encola en el engine, copia los videos a la galería y
refleja el estado en el store (``kind="video"``).
"""

from __future__ import annotations

import copy
import shutil
from typing import Any, Callable

from app.config import APP_ROOT
from app.engine import ComfyEngine, EngineError, load_graph
from app.motion import MOTION_NEGATIVE

WAN_TEMPLATE_PATH = APP_ROOT / "workflows" / "wan22_i2v_432x768.api.json"
H3_TEMPLATE_PATH = APP_ROOT / "workflows" / "h3_fl2va_vertical.api.json"

# El video puede tardar mucho mas que una imagen (H3 8 s en 4 pasos + decodificacion).
VIDEO_HISTORY_TIMEOUT_S = 3600.0
VIDEO_EXT = ("mp4", "webm")

# Wan: perfil del plan (vertical 432x768); horizontal simetrico 768x432.
ASPECTS = {"vertical": (432, 768), "horizontal": (768, 432)}

SAMPLER_CLASSES = ("KSampler", "KSamplerAdvanced")


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


def prepare_wan_graph(
    graph: dict,
    *,
    image_name: str,
    motion_positive: str,
    motion_negative: str,
    width: int = 432,
    height: int = 768,
    seed: int,
) -> dict:
    """Copia el grafo Wan I2V y fija textos, imagen, tamaño y seed.

    Nodos del perfil certificado: CLIPTextEncode ``5`` (positivo) y ``6``
    (negativo), LoadImage ``7`` (primer frame), ``WanImageToVideo`` (width/
    height) y la seed en todos los samplers (``noise_seed``/``seed``).
    """
    image_name = _require_text(image_name, "wan: image_name")
    motion_positive = _require_text(motion_positive, "wan: motion_positive")
    motion_negative = _require_text(motion_negative, "wan: motion_negative")
    seed = _require_seed(seed)
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
    _set_sampler_seed(prepared, seed)
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
    """Carga la plantilla del job y aplica la preparación del motor."""
    template = job.get("template")
    if not isinstance(template, str) or not template.strip():
        raise EngineError("video: template requerido")
    graph = load_graph(template)
    engine_kind = job.get("engine")
    seed = _require_seed(job.get("seed", 42))
    if engine_kind == "wan":
        aspect = job.get("aspect") or "vertical"
        sizes = ASPECTS.get(aspect)
        if sizes is None:
            raise EngineError(f"video: aspect invalido {aspect!r}; usar vertical|horizontal")
        width, height = sizes
        return prepare_wan_graph(
            graph,
            image_name=job.get("image_name"),
            motion_positive=job.get("motion_positive"),
            motion_negative=job.get("motion_negative") or MOTION_NEGATIVE,
            width=width,
            height=height,
            seed=seed,
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
) -> None:
    """Ejecuta un job de video: grafo -> engine -> galería -> store.

    No propaga errores: el fallo se guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    try:
        graph = build_video_graph(job)
        engine = (
            engine_factory()
            if engine_factory is not None
            else ComfyEngine(config, history_timeout_s=VIDEO_HISTORY_TIMEOUT_S)
        )
        prompt_id = engine.submit(graph)
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
    except Exception as exc:
        job["outputs"] = []
        job["error"] = str(exc)
        try:
            store.update(gen_id, status="error", error=str(exc))
        except EngineError:
            pass


__all__ = [
    "ASPECTS",
    "H3_TEMPLATE_PATH",
    "SAMPLER_CLASSES",
    "VIDEO_EXT",
    "VIDEO_HISTORY_TIMEOUT_S",
    "WAN_TEMPLATE_PATH",
    "build_video_graph",
    "prepare_h3_graph",
    "prepare_wan_graph",
    "run_video_generation",
]
