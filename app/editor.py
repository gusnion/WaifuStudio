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
EDITOR_STEPS_MIN = 10
EDITOR_STEPS_MAX = 50
EDITOR_DEFAULT_STEPS = 25
EDITOR_CFG_MIN = 1.0
EDITOR_CFG_MAX = 10.0
EDITOR_DEFAULT_CFG = 1.0
REFERENCE_RESOLUTION_MAX = 4096
REFERENCE_RESOLUTION_STEP = 32

ENCODE_CLASS = "TextEncodeQwenImage21"
LATENT_CLASS = "EmptyLatentImage"
KSAMPLER_CLASS = "KSampler"
LOAD_IMAGE_CLASS = "LoadImage"
LORA_LOADER_CLASS = "LoraLoaderModelOnly"
REF_ID_PREFIX = "ref_"
REF_IMAGE_KEY_PREFIX = "images.image_"
VAE_LOADER_CLASS = "VAELoader"
VAE_ENCODE_CLASS = "VAEEncode"
PRESERVE_ENCODE_ID = "preserve_encode"
EDITOR_PRESERVE_DENOISE = 0.65

VALID_SAMPLERS = frozenset({"euler", "er_sde", "dpmpp_2m"})
VALID_SCHEDULERS = frozenset({"simple", "beta", "normal", "karras"})

_POSE_ALIASES: dict[str, str] = {
    "l0_sfw": "l0_editorial",
    "l1_suggestive": "l1_open",
}

QWEN_POSE_PRESETS: dict[str, dict[str, str]] = {
    "l0_editorial": {
        "id": "l0_editorial",
        "label": "L0 Editorial / SFW",
        "level": "L0",
        "template": (
            "Maintain the exact character, face, hair, and 2D anime art style from the reference image. "
            "Adjust posture to a natural dynamic standing or seated anime pose, balanced full-body composition, "
            "clean 2D linework, soft cel-shaded lighting, high quality anime illustration."
        ),
    },
    "l1_open": {
        "id": "l1_open",
        "label": "L1 Open / Glamour",
        "level": "L1",
        "template": (
            "Maintain the exact character, face, hair, and 2D anime art style from the reference image. "
            "Adjust posture to an alluring, playful, suggestive anime pose with a curved back arch and "
            "expressive glance toward the viewer, medium-full shot keeping the face clearly visible, "
            "warm anime lighting, clean cel-shaded illustration."
        ),
    },
    "l2_bold_nsfw": {
        "id": "l2_bold_nsfw",
        "label": "L2 Bold NSFW (Low Angle)",
        "level": "L2",
        "template": (
            "Maintain the exact character, face, hair, and 2D anime art style from the reference image. "
            "Repose the character into the requested bold, explicit uncensored NSFW posture while keeping "
            "a full or medium-full framing where the character's head, face, and expression remain in frame. "
            "Clean 2D anime linework, smooth anime shading, vibrant uncensored 2D illustration."
        ),
    },
    "l3_extreme": {
        "id": "l3_extreme",
        "label": "L3 Extreme Close-Up NSFW",
        "level": "L3",
        "template": (
            "Maintain the exact character, face, hair, and 2D anime art style from the reference image. "
            "Repose the character into the requested intense, explicit uncensored NSFW pose with dynamic angle "
            "and clear visibility of both the character's face/expression and full body action. "
            "Crisp 2D anime lineart, cel-shaded lighting, uncensored anime masterwork."
        ),
    },
}


def format_qwen_7block_prompt(user_prompt: str, pose_preset: str | None = None) -> str:
    """Combina el prompt del usuario con la plantilla de 7 bloques del preset de pose."""
    clean_user = user_prompt.strip() if isinstance(user_prompt, str) else ""
    if pose_preset and pose_preset in _POSE_ALIASES:
        pose_preset = _POSE_ALIASES[pose_preset]
    if not pose_preset or pose_preset not in QWEN_POSE_PRESETS:
        return clean_user
    template = QWEN_POSE_PRESETS[pose_preset]["template"]
    if not clean_user:
        return template
    if template.lower() in clean_user.lower():
        return clean_user
    return f"{clean_user}, {template}"


def _require_sampler(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "euler"
    if not isinstance(value, str) or value.strip() not in VALID_SAMPLERS:
        raise EngineError(f"sampler_name invalido: {value!r}")
    return value.strip()


def _require_scheduler(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "simple"
    if not isinstance(value, str) or value.strip() not in VALID_SCHEDULERS:
        raise EngineError(f"scheduler invalido: {value!r}")
    return value.strip()


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


def _require_steps(value: Any) -> int:
    if isinstance(value, bool):
        raise EngineError(f"steps invalido: {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise EngineError(f"steps invalido: {value!r}")
    try:
        steps = int(value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"steps invalido: {value!r}") from exc
    if not EDITOR_STEPS_MIN <= steps <= EDITOR_STEPS_MAX:
        raise EngineError(
            f"steps fuera de [{EDITOR_STEPS_MIN}, {EDITOR_STEPS_MAX}]: {value!r}"
        )
    return steps


def _require_cfg(value: Any) -> float:
    if isinstance(value, bool):
        raise EngineError(f"cfg invalido: {value!r}")
    try:
        cfg = float(value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"cfg invalido: {value!r}") from exc
    if not EDITOR_CFG_MIN <= cfg <= EDITOR_CFG_MAX:
        raise EngineError(
            f"cfg fuera de [{EDITOR_CFG_MIN}, {EDITOR_CFG_MAX}]: {value!r}"
        )
    return cfg


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


def _apply_editor_loras(graph: dict, loras: list[dict] | None) -> None:
    if not loras:
        return
    if not isinstance(loras, list):
        raise EngineError("loras debe ser una lista")
    unet_id, _ = _find_node(graph, "UnetLoaderGGUF")

    current_model: list[Any] = [unet_id, 0]
    for idx, item in enumerate(loras, start=1):
        if not isinstance(item, dict):
            raise EngineError(f"lora #{idx} invalido: se esperaba objeto dict")
        file = item.get("file") or item.get("lora_name")
        if not file and item.get("id"):
            try:
                from app.loras import get_lora

                entry = get_lora(str(item["id"]))
                if entry:
                    file = entry.get("file")
            except Exception:
                pass
        if not file or not isinstance(file, str) or not file.strip():
            raise EngineError(f"lora #{idx} sin archivo especificado ('file')")
        try:
            weight = float(item.get("weight", item.get("strength_model", 1.0)))
        except (TypeError, ValueError) as exc:
            raise EngineError(
                f"lora #{idx} peso invalido: {item.get('weight')!r}"
            ) from exc

        node_id = f"lora_{idx}"
        graph[node_id] = {
            "class_type": LORA_LOADER_CLASS,
            "inputs": {
                "model": current_model,
                "lora_name": file.strip(),
                "strength_model": weight,
            },
        }
        current_model = [node_id, 0]

    for n_id, node in graph.items():
        if str(n_id).startswith("lora_"):
            continue
        if isinstance(node, dict):
            inputs = node.get("inputs")
            if isinstance(inputs, dict):
                val = inputs.get("model")
                if (
                    isinstance(val, (list, tuple))
                    and len(val) >= 2
                    and str(val[0]) == str(unet_id)
                    and val[1] == 0
                ):
                    inputs["model"] = current_model


def prepare_editor_graph(
    graph: dict,
    *,
    prompt: Any,
    negative: Any = "",
    seed: Any = 42,
    steps: Any = EDITOR_DEFAULT_STEPS,
    cfg: Any = EDITOR_DEFAULT_CFG,
    width: Any = EDITOR_DEFAULT_SIZE,
    height: Any = EDITOR_DEFAULT_SIZE,
    ref_images: Any = (),
    sampler_name: Any = "euler",
    scheduler: Any = "simple",
    preserve_structure: bool = False,
    pose_preset: str | None = None,
    loras: list[dict] | None = None,
) -> dict:
    """Copia de ``graph`` con prompt/negativo/seed/steps/cfg/tamano/refs.

    El encoder ``TextEncodeQwenImage21`` recibe prompt, ``negative_prompt`` y el
    ``resolution`` (presupuesto de las referencias, multiplo de 32); el
    EmptyLatentImage fija el tamano de salida. El KSampler recibe ``steps``
    (10-50) y ``cfg`` (1.0-10.0) ademas de la seed, sampler_name y scheduler.
    Cada referencia anade un LoadImage ``ref_N`` y su enlace ``images.image_N``
    (hasta 10). Si preserve_structure=True y hay referencias, codifica la primera
    referencia mediante VAEEncode, conecta su salida a latent_image del KSampler y
    fija denoise=0.65; en caso contrario, usa EmptyLatentImage y denoise=1.0.
    Los LoRAs opcionales se encadenan mediante LoraLoaderModelOnly.
    """
    if pose_preset:
        prompt = format_qwen_7block_prompt(
            prompt if isinstance(prompt, str) else ("" if prompt is None else str(prompt)),
            pose_preset,
        )
    prompt = _require_text(prompt, "prompt")
    negative = _require_negative(negative)
    seed = _require_seed(seed)
    steps = _require_steps(steps)
    cfg = _require_cfg(cfg)
    width = _require_size_value(width, "width")
    height = _require_size_value(height, "height")
    refs = _require_refs(ref_images)
    sampler_name = _require_sampler(sampler_name)
    scheduler = _require_scheduler(scheduler)

    prepared = copy.deepcopy(graph)
    encode_id, encode = _find_node(prepared, ENCODE_CLASS)
    for field in ("prompt", "negative_prompt", "resolution"):
        _require_field(encode, field, encode_id)
    encode["prompt"] = prompt
    encode["negative_prompt"] = negative
    encode["resolution"] = 0
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
    if PRESERVE_ENCODE_ID in prepared:
        del prepared[PRESERVE_ENCODE_ID]

    latent_id, latent = _find_node(prepared, LATENT_CLASS)
    for field in ("width", "height"):
        _require_field(latent, field, latent_id)
    latent["width"] = width
    latent["height"] = height

    sampler_id, sampler = _find_node(prepared, KSAMPLER_CLASS)
    for field in ("seed", "steps", "cfg"):
        _require_field(sampler, field, sampler_id)
    sampler["seed"] = seed
    sampler["steps"] = steps
    sampler["cfg"] = cfg
    sampler["sampler_name"] = sampler_name
    sampler["scheduler"] = scheduler

    for index, image in enumerate(refs, start=1):
        node_id = f"{REF_ID_PREFIX}{index}"
        if node_id in prepared:
            raise EngineError(f"id de referencia ocupado en el grafo: {node_id!r}")
        prepared[node_id] = {
            "class_type": LOAD_IMAGE_CLASS,
            "inputs": {"image": image},
        }
        encode[f"{REF_IMAGE_KEY_PREFIX}{index}"] = [node_id, 0]

    if preserve_structure and refs:
        vae_id, _ = _find_node(prepared, VAE_LOADER_CLASS)
        ref1_id = f"{REF_ID_PREFIX}1"
        prepared[PRESERVE_ENCODE_ID] = {
            "class_type": VAE_ENCODE_CLASS,
            "inputs": {
                "pixels": [ref1_id, 0],
                "vae": [vae_id, 0],
            },
        }
        sampler["latent_image"] = [PRESERVE_ENCODE_ID, 0]
        sampler["denoise"] = EDITOR_PRESERVE_DENOISE
    else:
        if refs:
            sampler["latent_image"] = [encode_id, 2]
        else:
            sampler["latent_image"] = [latent_id, 0]
        sampler["denoise"] = 1.0

    _apply_editor_loras(prepared, loras)
    return prepared


def build_editor_graph(
    *,
    prompt: Any,
    negative: Any = "",
    seed: Any = 42,
    steps: Any = EDITOR_DEFAULT_STEPS,
    cfg: Any = EDITOR_DEFAULT_CFG,
    width: Any = EDITOR_DEFAULT_SIZE,
    height: Any = EDITOR_DEFAULT_SIZE,
    ref_images: Any = (),
    sampler_name: Any = "euler",
    scheduler: Any = "simple",
    preserve_structure: bool = False,
    pose_preset: str | None = None,
    loras: list[dict] | None = None,
    template_path: str | Path = EDITOR_TEMPLATE_PATH,
) -> dict:
    """Carga el template del editor y devuelve el grafo listo para encolar."""
    graph = load_graph(template_path)
    return prepare_editor_graph(
        graph,
        prompt=prompt,
        negative=negative,
        seed=seed,
        steps=steps,
        cfg=cfg,
        width=width,
        height=height,
        ref_images=ref_images,
        sampler_name=sampler_name,
        scheduler=scheduler,
        preserve_structure=preserve_structure,
        pose_preset=pose_preset,
        loras=loras,
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
            steps=job.get("steps", EDITOR_DEFAULT_STEPS),
            cfg=job.get("cfg", EDITOR_DEFAULT_CFG),
            width=job.get("width", EDITOR_DEFAULT_SIZE),
            height=job.get("height", EDITOR_DEFAULT_SIZE),
            ref_images=job.get("ref_images") or (),
            sampler_name=job.get("sampler_name", "euler"),
            scheduler=job.get("scheduler", "simple"),
            preserve_structure=bool(job.get("preserve_structure", False)),
            pose_preset=job.get("pose_preset"),
            loras=job.get("loras"),
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
    "EDITOR_CFG_MAX",
    "EDITOR_CFG_MIN",
    "EDITOR_DEFAULT_CFG",
    "EDITOR_DEFAULT_SIZE",
    "EDITOR_DEFAULT_STEPS",
    "EDITOR_PRESERVE_DENOISE",
    "EDITOR_REF_LIMIT",
    "EDITOR_SEED_MAX",
    "EDITOR_STEPS_MAX",
    "EDITOR_STEPS_MIN",
    "EDITOR_SIZE_MAX",
    "EDITOR_SIZE_MIN",
    "EDITOR_SIZE_STEP",
    "EDITOR_TEMPLATE_PATH",
    "PRESERVE_ENCODE_ID",
    "QWEN_POSE_PRESETS",
    "VALID_SAMPLERS",
    "VALID_SCHEDULERS",
    "build_editor_graph",
    "format_qwen_7block_prompt",
    "inherit_size_from_image",
    "prepare_editor_graph",
    "run_editor_generation",
]
