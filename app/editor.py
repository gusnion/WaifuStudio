"""Editor Qwen-Image 2.1 UC (M10-3): grafo API y runner.

Carga `workflows/qwen_image_2.1_editor.api.json` — adaptacion del template
oficial `image_qwen_image_2_1_image_edit` (Comfy-Org/workflow_templates) al par
UC: UnetLoaderGGUF + CLIPLoader ``type="qwen_image"`` + VAELoader 2.1 +
``TextEncodeQwenImage21`` (prompt/negativo/VAE de referencia + autogrow
``images.image_1..image_10``) + EmptyLatentImage + QwenImage21Cache + KSampler
certificado (seed, 25 pasos, cfg 1, euler/simple) + VAEDecode + SaveImage
``waifu/editor``.

`build_editor_graph` parchea prompt/negativo/seed/tamano (512-2048, multiplo de
16) y hasta 10 referencias, anadiendo un LoadImage ``ref_N`` por imagen y su
enlace ``images.image_N``; las referencias ya estan escritas en
``ComfyUI/input`` (el server las guarda al encolar). El runner
`run_editor_generation` sigue el patron de imagen: un grafo por job, tracker de
progreso, copia de los PNG a ``data/gallery/<gen_id>/`` y estado en el store;
los errores se guardan en el job y en el store, nunca se propagan al worker.
Solo stdlib; sin red, sin GPU.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, Callable

from app.config import APP_ROOT
from app.engine import ComfyEngine, EngineError, load_graph
from app.progress import ProgressTracker

EDITOR_TEMPLATE_PATH = APP_ROOT / "workflows" / "qwen_image_2.1_editor.api.json"
EDITOR_REF_LIMIT = 10
EDITOR_SIZE_MIN = 512
EDITOR_SIZE_MAX = 2048
EDITOR_SIZE_STEP = 16
EDITOR_DEFAULT_SIZE = 1024
EDITOR_SEED_MAX = 2**64 - 1
REFERENCE_RESOLUTION_MAX = 4096
REFERENCE_RESOLUTION_STEP = 32

ENCODE_CLASS = "TextEncodeQwenImage21"
LATENT_CLASS = "EmptyLatentImage"
KSAMPLER_CLASS = "KSampler"
LOAD_IMAGE_CLASS = "LoadImage"
REF_ID_PREFIX = "ref_"
REF_IMAGE_KEY_PREFIX = "images.image_"


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"{label} vacio")
    return value.strip()


def _require_negative(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise EngineError(f"negativo invalido: {value!r}")
    return value.strip()


def _require_seed(value: Any) -> int:
    if isinstance(value, bool):
        raise EngineError(f"seed invalida: {value!r}")
    try:
        seed = int(value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"seed invalida: {value!r}") from exc
    if not 0 <= seed <= EDITOR_SEED_MAX:
        raise EngineError(f"seed fuera de 0..{EDITOR_SEED_MAX}: {value!r}")
    return seed


def _require_size_value(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise EngineError(f"{name} invalido: {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"{name} invalido: {value!r}") from exc
    if not EDITOR_SIZE_MIN <= number <= EDITOR_SIZE_MAX or number % EDITOR_SIZE_STEP:
        raise EngineError(
            f"{name} fuera de [{EDITOR_SIZE_MIN}, {EDITOR_SIZE_MAX}] "
            f"o no multiplo de {EDITOR_SIZE_STEP}: {value!r}"
        )
    return number


def _require_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise EngineError(f"ref_images invalido: {value!r}; usar lista")
    if len(value) > EDITOR_REF_LIMIT:
        raise EngineError(f"maximo {EDITOR_REF_LIMIT} imagenes de referencia")
    refs: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise EngineError(f"ref_images[{index}] invalido: {item!r}")
        refs.append(item.strip())
    return refs


def _reference_resolution(width: int, height: int) -> int:
    """Presupuesto del encoder (`resolution`, paso 32) a partir del tamano."""
    budget = max(width, height)
    steps = (budget + REFERENCE_RESOLUTION_STEP - 1) // REFERENCE_RESOLUTION_STEP
    return min(steps * REFERENCE_RESOLUTION_STEP, REFERENCE_RESOLUTION_MAX)


def inherit_size_from_image(raw: bytes) -> tuple[int, int]:
    """Tamano «Original» del editor: el de la primera referencia, encajado.

    Escala el aspecto para caer en [512, 2048] y redondea cada lado al paso 16
    del editor; EngineError si la imagen es ilegible o sin tamano. Pensado para
    la edicion encadenada: la referencia es el resultado anterior y el tamano
    se mantiene entre pasos.
    """
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(raw)) as handle:
            width, height = handle.size
    except Exception as exc:
        raise EngineError(f"original: referencia ilegible ({exc})") from exc
    if width <= 0 or height <= 0:
        raise EngineError("original: referencia sin tamano")
    scale = 1.0
    small, big = (width, height) if width <= height else (height, width)
    if small < EDITOR_SIZE_MIN:
        scale = EDITOR_SIZE_MIN / small
    if big * scale > EDITOR_SIZE_MAX:
        scale = EDITOR_SIZE_MAX / big

    def _snap(value: float) -> int:
        snapped = round(value / EDITOR_SIZE_STEP) * EDITOR_SIZE_STEP
        return max(EDITOR_SIZE_MIN, min(EDITOR_SIZE_MAX, snapped))

    return _snap(width * scale), _snap(height * scale)


def _find_node(graph: dict, class_type: str) -> tuple[str, dict]:
    for node_id, node in graph.items():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                raise EngineError(f"nodo {node_id!r} sin inputs dict")
            return node_id, inputs
    raise EngineError(f"grafo sin nodo {class_type}")


def _require_field(inputs: dict, field: str, node_id: str) -> None:
    if field not in inputs:
        raise EngineError(f"nodo {node_id!r} sin campo {field!r}")


def prepare_editor_graph(
    graph: dict,
    *,
    prompt: Any,
    negative: Any = "",
    seed: Any = 42,
    width: Any = EDITOR_DEFAULT_SIZE,
    height: Any = EDITOR_DEFAULT_SIZE,
    ref_images: Any = (),
) -> dict:
    """Copia de ``graph`` con prompt/negativo/seed/tamano/refs aplicados.

    El encoder ``TextEncodeQwenImage21`` recibe prompt, ``negative_prompt`` y el
    ``resolution`` (presupuesto de las referencias, multiplo de 32); el
    EmptyLatentImage fija el tamano de salida. Cada referencia anade un
    LoadImage ``ref_N`` y su enlace ``images.image_N`` (hasta 10). Los refs
    existentes se reemplazan. EngineError con cualquier valor fuera de rango o
    nodo ausente; el grafo de entrada nunca se muta.
    """
    prompt = _require_text(prompt, "prompt")
    negative = _require_negative(negative)
    seed = _require_seed(seed)
    width = _require_size_value(width, "width")
    height = _require_size_value(height, "height")
    refs = _require_refs(ref_images)

    prepared = copy.deepcopy(graph)
    encode_id, encode = _find_node(prepared, ENCODE_CLASS)
    for field in ("prompt", "negative_prompt", "resolution"):
        _require_field(encode, field, encode_id)
    encode["prompt"] = prompt
    encode["negative_prompt"] = negative
    encode["resolution"] = _reference_resolution(width, height)
    for key in [key for key in encode if key.startswith(REF_IMAGE_KEY_PREFIX)]:
        del encode[key]
    for node_id, node in list(prepared.items()):
        if (
            str(node_id).startswith(REF_ID_PREFIX)
            and str(node_id)[len(REF_ID_PREFIX) :].isdigit()
            and isinstance(node, dict)
            and node.get("class_type") == LOAD_IMAGE_CLASS
        ):
            del prepared[node_id]

    latent_id, latent = _find_node(prepared, LATENT_CLASS)
    for field in ("width", "height"):
        _require_field(latent, field, latent_id)
    latent["width"] = width
    latent["height"] = height

    sampler_id, sampler = _find_node(prepared, KSAMPLER_CLASS)
    _require_field(sampler, "seed", sampler_id)
    sampler["seed"] = seed

    for index, image in enumerate(refs, start=1):
        node_id = f"{REF_ID_PREFIX}{index}"
        if node_id in prepared:
            raise EngineError(f"id de referencia ocupado en el grafo: {node_id!r}")
        prepared[node_id] = {
            "class_type": LOAD_IMAGE_CLASS,
            "inputs": {"image": image},
        }
        encode[f"{REF_IMAGE_KEY_PREFIX}{index}"] = [node_id, 0]
    return prepared


def build_editor_graph(
    *,
    prompt: Any,
    negative: Any = "",
    seed: Any = 42,
    width: Any = EDITOR_DEFAULT_SIZE,
    height: Any = EDITOR_DEFAULT_SIZE,
    ref_images: Any = (),
    template_path: str | Path = EDITOR_TEMPLATE_PATH,
) -> dict:
    """Carga el template del editor y devuelve el grafo listo para encolar."""
    graph = load_graph(template_path)
    return prepare_editor_graph(
        graph,
        prompt=prompt,
        negative=negative,
        seed=seed,
        width=width,
        height=height,
        ref_images=ref_images,
    )


def _progress_ws_url(config: Any) -> str:
    """WS del engine desde `comfy_url` (misma semantica que `app.server`)."""
    base = str(config.comfy_url).rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return f"{base}/ws"


def run_editor_generation(
    job: dict,
    *,
    config: Any,
    store: Any,
    engine_factory: Callable[[], Any] | None = None,
    ws_factory: Any = None,
    record: dict | None = None,
) -> None:
    """Ejecuta un job del editor: grafo -> engine -> galeria -> store.

    `record` es el registro de `_JOBS[gen_id]` del server: si se pasa, se le
    registran engine, `prompt_id`, tracker y estado (queued -> running ->
    done/error/cancelled) como en imagen. La generacion se guarda con
    ``kind="image"`` y ``params.task="editor"`` (visible en la galeria de
    Imagen); el PNG se copia a ``data/gallery/<gen_id>/``. No propaga errores:
    el fallo se guarda en el store y en ``job["error"]``.
    """
    gen_id = job["gen_id"]
    if record is not None and record.get("status") == "cancelled":
        job["outputs"] = []
        job["error"] = None
        return
    tracker = None
    try:
        graph = build_editor_graph(
            prompt=job.get("prompt"),
            negative=job.get("negative") or "",
            seed=job.get("seed", 42),
            width=job.get("width", EDITOR_DEFAULT_SIZE),
            height=job.get("height", EDITOR_DEFAULT_SIZE),
            ref_images=job.get("ref_images") or (),
            template_path=job.get("template") or EDITOR_TEMPLATE_PATH,
        )
        engine = engine_factory() if engine_factory is not None else ComfyEngine(config)
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
    "EDITOR_DEFAULT_SIZE",
    "EDITOR_REF_LIMIT",
    "EDITOR_SEED_MAX",
    "EDITOR_SIZE_MAX",
    "EDITOR_SIZE_MIN",
    "EDITOR_SIZE_STEP",
    "EDITOR_TEMPLATE_PATH",
    "build_editor_graph",
    "prepare_editor_graph",
    "run_editor_generation",
]
