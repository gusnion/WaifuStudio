"""Manipuladores de grafos API-format para imagen (F3a).

Todas las funciones trabajan sobre una COPIA PROFUNDA: el grafo de entrada nunca
se muta. Los loaders y el sampler se localizan por ``class_type``, no por id fijo.
Solo stdlib; sin red, sin GPU y sin dependencias nuevas.
"""

from __future__ import annotations

import copy
from typing import Any

from app.engine import EngineError

KSAMPLER_CLASS = "KSampler"
LATENT_CLASS = "EmptyLatentImage"
IMG_REF_ID = "img_ref"
IMG_ENC_ID = "img_enc"
DEFAULT_STRENGTH = 0.6

_KSAMPLER_WIDGETS = ("seed", "steps", "cfg", "sampler_name", "scheduler")
_LATENT_WIDGETS = ("width", "height")
_CASTS = {
    "seed": int,
    "steps": int,
    "width": int,
    "height": int,
    "cfg": float,
    "sampler_name": str,
    "scheduler": str,
}


def _nodes_of(graph: dict, class_type: str) -> list[tuple[str, dict]]:
    return [
        (node_id, node)
        for node_id, node in graph.items()
        if isinstance(node, dict) and node.get("class_type") == class_type
    ]


def _inputs_of(node: dict, class_type: str, node_id: str) -> dict:
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise EngineError(f"nodo {class_type} ({node_id}) sin inputs dict: {node!r}")
    return inputs


def _profile_field(profile: object, name: str) -> str:
    value = getattr(profile, name, None)
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"profile.{name} invalido: {value!r}")
    return value


def _patch_loader(graph: dict, class_type: str, fields: dict[str, str]) -> None:
    nodes = _nodes_of(graph, class_type)
    if not nodes:
        raise EngineError(
            f"grafo sin nodo {class_type}: no se puede aplicar el perfil del modelo"
        )
    for node_id, node in nodes:
        _inputs_of(node, class_type, node_id).update(fields)


def _patch_clip_loader(graph: dict, clip_name: str, clip_type: str) -> None:
    nodes = _nodes_of(graph, "CLIPLoader")
    if not nodes:
        raise EngineError(
            "grafo sin nodo CLIPLoader: no se puede aplicar el perfil del modelo"
        )
    for node_id, node in nodes:
        inputs = _inputs_of(node, "CLIPLoader", node_id)
        inputs["clip_name"] = clip_name
        if "type" not in inputs and "clip_type" in inputs:
            inputs["clip_type"] = clip_type
        else:
            inputs["type"] = clip_type


def _apply_seed(graph: dict, seed: object) -> None:
    try:
        value = int(seed)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"seed invalida: {seed!r}") from exc
    applied = 0
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict) and "seed" in inputs:
            inputs["seed"] = value
            applied += 1
    if not applied:
        raise EngineError("grafo sin nodo con widget 'seed': no se puede fijar la seed")


def _coerce(name: str, value: object) -> Any:
    try:
        return _CASTS[name](value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"parametro {name} invalido: {value!r}") from exc


def _set_widget(graph: dict, class_type: str, widget: str, value: Any) -> None:
    nodes = _nodes_of(graph, class_type)
    if not nodes:
        raise EngineError(f"grafo sin nodo {class_type}: no se puede aplicar {widget!r}")
    applied = 0
    for node_id, node in nodes:
        inputs = _inputs_of(node, class_type, node_id)
        if widget in inputs:
            inputs[widget] = value
            applied += 1
    if not applied:
        raise EngineError(
            f"nodo {class_type} sin widget {widget!r}: no se puede aplicar el parametro"
        )


def _strength(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"strength invalida: {value!r}") from exc
    if not 0.0 < result <= 1.0:
        raise EngineError(f"strength fuera de (0, 1]: {value!r}")
    return result


def patch_model(graph: dict, entry: object, seed: int | None = None) -> dict:
    """Copia de ``graph`` con el perfil de ``entry`` (y ``seed`` si no es None).

    UNETLoader toma ``profile.unet_name``, CLIPLoader ``clip_name``+``clip_type``
    (widget ``type``, o ``clip_type`` si el grafo ya usa ese nombre) y VAELoader
    ``vae_name``. La seed se fija en todo nodo con widget ``seed``. EngineError si
    falta alguno de los tres loaders, si el perfil es invalido o si ``seed`` viene
    y no hay ningun nodo con widget ``seed``.
    """
    profile = getattr(entry, "profile", None)
    if profile is None:
        raise EngineError("entrada sin profile: no se puede parchear el modelo")
    patched = copy.deepcopy(graph)
    _patch_loader(
        patched, "UNETLoader", {"unet_name": _profile_field(profile, "unet_name")}
    )
    _patch_clip_loader(
        patched,
        _profile_field(profile, "clip_name"),
        _profile_field(profile, "clip_type"),
    )
    _patch_loader(patched, "VAELoader", {"vae_name": _profile_field(profile, "vae_name")})
    if seed is not None:
        _apply_seed(patched, seed)
    return patched


def patch_params(
    graph: dict,
    *,
    seed: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    """Copia de ``graph`` con SOLO los parametros no-None aplicados.

    ``seed``/``steps``/``cfg``/``sampler_name``/``scheduler`` van al KSampler;
    ``width``/``height`` al EmptyLatentImage. EngineError si un parametro pedido
    no encuentra su nodo/widget.
    """
    patched = copy.deepcopy(graph)
    ksampler = {
        "seed": seed,
        "steps": steps,
        "cfg": cfg,
        "sampler_name": sampler_name,
        "scheduler": scheduler,
    }
    latent = {"width": width, "height": height}
    for name in _KSAMPLER_WIDGETS:
        value = ksampler[name]
        if value is not None:
            _set_widget(patched, KSAMPLER_CLASS, name, _coerce(name, value))
    for name in _LATENT_WIDGETS:
        value = latent[name]
        if value is not None:
            _set_widget(patched, LATENT_CLASS, name, _coerce(name, value))
    return patched


def to_img2img(graph: dict, image_name: str, strength: float = DEFAULT_STRENGTH) -> dict:
    """Copia de ``graph`` lista para img2img con LoadImage + VAEEncode.

    Elimina los EmptyLatentImage, anade los nodos fijos ``img_ref`` (LoadImage con
    ``image=image_name``) e ``img_enc`` (VAEEncode con pixels de ``img_ref`` y el
    vae del primer VAELoader) y rewirea cada KSampler a
    ``latent_image=['img_enc', 0]`` con ``denoise=strength``. EngineError si
    ``strength`` no cae en (0, 1], si ``img_ref``/``img_enc`` ya existen o si falta
    KSampler, VAELoader o EmptyLatentImage.
    """
    value = _strength(strength)
    if not isinstance(image_name, str) or not image_name.strip():
        raise EngineError(f"imagen de referencia invalida: {image_name!r}")
    if IMG_REF_ID in graph or IMG_ENC_ID in graph:
        raise EngineError(
            f"el grafo ya usa los ids {IMG_REF_ID!r}/{IMG_ENC_ID!r}: "
            "no se puede convertir a img2img"
        )
    ksamplers = _nodes_of(graph, KSAMPLER_CLASS)
    if not ksamplers:
        raise EngineError("grafo sin KSampler: no se puede convertir a img2img")
    vaes = _nodes_of(graph, "VAELoader")
    if not vaes:
        raise EngineError("grafo sin VAELoader: no se puede convertir a img2img")
    latents = _nodes_of(graph, LATENT_CLASS)
    if not latents:
        raise EngineError("grafo sin EmptyLatentImage: no se puede convertir a img2img")
    patched = copy.deepcopy(graph)
    for node_id, _node in latents:
        del patched[node_id]
    patched[IMG_REF_ID] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    patched[IMG_ENC_ID] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": [IMG_REF_ID, 0], "vae": [vaes[0][0], 0]},
    }
    for node_id, _node in ksamplers:
        inputs = _inputs_of(patched[node_id], KSAMPLER_CLASS, node_id)
        inputs["latent_image"] = [IMG_ENC_ID, 0]
        inputs["denoise"] = value
    return patched


__all__ = [
    "DEFAULT_STRENGTH",
    "IMG_ENC_ID",
    "IMG_REF_ID",
    "patch_model",
    "patch_params",
    "to_img2img",
]
