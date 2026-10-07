"""Catalogo local de perfiles H3 FL2VA (M10-2c-1): ``registry/h3_presets-v1.json``.

Espejo de `app.video_presets`: solo stdlib, sin red ni dependencias. Carga
perezosa y estricta (EngineError claro si el JSON falta, no tiene la forma
esperada o un perfil/variante es invalido). Cada perfil trae id/label/note,
plantilla, modelo DiT, VAEs de video/audio, encoder con proyeccion ClipProj (o
null) y LoRA. El catalogo fija las variantes (M10-2c-3: LoRA + pasos, default
``turbo4``), los segundos permitidos (5/8/10/12/15) y las resoluciones
vertical/horizontal. H3 exige ``length = 5+17n`` a 24 fps y medidas multiplo de
32 con area <= 768x1344.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from app.config import APP_ROOT
from app.engine import EngineError

PROFILES_PATH = APP_ROOT / "registry" / "h3_presets-v1.json"
DEFAULT_PROFILE = "referencia"
DEFAULT_VARIANT = "turbo4"
H3_ASPECTS: tuple[str, ...] = ("vertical", "horizontal")
H3_SECONDS: tuple[int, ...] = (5, 8, 10, 12, 15, 20, 24, 25, 30)
H3_VARIANT_STEPS_MAX = 200
H3_FPS = 24
H3_FRAME_BASE = 5
H3_FRAME_STEP = 17
H3_MIN_FRAMES = 124
H3_MAX_FRAMES = 362
H3_SIZE_STEP = 32
H3_MAX_PIXELS = 768 * 1344

PROFILE_COMPATIBLE_VARIANTS: dict[str, set[str]] = {
    "vdn": {"vdn8"},
    "ref2va": {"vdn8"},
    "referencia": {"turbo4", "turbo8"},
    "calidad": {"turbo4", "turbo8"},
    "ligero": {"turbo4", "turbo8"},
}


def validate_h3_profile_variant(profile_id: str, variant_id: str) -> None:
    """Valida compatibilidad estricta perfil <-> variante."""
    if not isinstance(profile_id, str) or not isinstance(variant_id, str):
        raise EngineError(
            f"perfil o variante invalido: profile_id={profile_id!r}, variant_id={variant_id!r}"
        )
    p_id = profile_id.strip()
    v_id = variant_id.strip()
    allowed = PROFILE_COMPATIBLE_VARIANTS.get(p_id)
    if allowed is None:
        raise EngineError(f"perfil H3 desconocido: {profile_id!r}")
    if v_id not in allowed:
        raise EngineError(
            f"la variante {v_id!r} no es compatible con el perfil {p_id!r}; "
            f"variantes permitidas: {sorted(allowed)}"
        )


def is_vdn_installed(comfy_root: Path | str | None = None) -> bool:
    """Comprueba si existe el directorio models/vdn y contiene al menos una carpeta con linear_branch."""
    if comfy_root is None:
        vdn_dir = APP_ROOT / "ComfyUI" / "models" / "vdn"
    else:
        root = Path(comfy_root)
        if root.name == "vdn":
            vdn_dir = root
        elif (root / "models" / "vdn").exists():
            vdn_dir = root / "models" / "vdn"
        elif (root / "vdn").exists():
            vdn_dir = root / "vdn"
        else:
            vdn_dir = root / "models" / "vdn"
    if not vdn_dir.is_dir():
        return False
    try:
        for child in vdn_dir.iterdir():
            if child.is_dir() and (child / "linear_branch").is_dir():
                return True
        if (vdn_dir / "linear_branch").is_dir():
            return True
    except OSError:
        return False
    return False


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"{label} invalido: {value!r}")
    return value.strip()


def _parse_seconds_catalog(value: Any) -> list[int]:
    if not isinstance(value, list) or not value:
        raise EngineError(f"catalogo H3: seconds invalido: {value!r}")
    seconds: list[int] = []
    for item in value:
        if (
            isinstance(item, bool)
            or not isinstance(item, int)
            or item not in H3_SECONDS
        ):
            raise EngineError(
                f"catalogo H3: seconds invalido {item!r}; usar {list(H3_SECONDS)}"
            )
        if item in seconds:
            raise EngineError(f"catalogo H3: seconds duplicado: {item!r}")
        seconds.append(item)
    if seconds != sorted(seconds):
        raise EngineError(f"catalogo H3: seconds debe ir en orden: {value!r}")
    return seconds


def _parse_resolution(value: Any, aspect: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise EngineError(
            f"catalogo H3: resolucion {aspect!r} invalida: {value!r}"
        )
    sizes: dict[str, int] = {}
    for name in ("width", "height"):
        size = value.get(name)
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < H3_SIZE_STEP
            or size % H3_SIZE_STEP != 0
        ):
            raise EngineError(
                f"catalogo H3: {name} {aspect!r} invalido "
                f"(min {H3_SIZE_STEP}, paso {H3_SIZE_STEP}): {size!r}"
            )
        sizes[name] = size
    if sizes["width"] * sizes["height"] > H3_MAX_PIXELS:
        raise EngineError(
            f"catalogo H3: resolucion {aspect!r} excede {H3_MAX_PIXELS} px: {value!r}"
        )
    if aspect == "vertical" and sizes["height"] <= sizes["width"]:
        raise EngineError(
            f"catalogo H3: resolucion vertical invalida: {value!r}"
        )
    if aspect == "horizontal" and sizes["width"] <= sizes["height"]:
        raise EngineError(
            f"catalogo H3: resolucion horizontal invalida: {value!r}"
        )
    return sizes


def _parse_resolutions(value: Any) -> dict[str, list[dict[str, int]]]:
    if not isinstance(value, dict):
        raise EngineError(f"catalogo H3: resoluciones invalidas: {value!r}")
    resolutions: dict[str, list[dict[str, int]]] = {}
    for aspect in H3_ASPECTS:
        entries = value.get(aspect)
        if not isinstance(entries, list) or not entries:
            raise EngineError(f"catalogo H3: faltan resoluciones {aspect!r}")
        resolutions[aspect] = [
            _parse_resolution(entry, aspect) for entry in entries
        ]
    return resolutions


def _parse_variant(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise EngineError(f"variante H3 #{index} invalida: se esperaba objeto")
    variant_id = entry.get("id")
    if not isinstance(variant_id, str) or not variant_id.strip():
        raise EngineError(f"variante H3 #{index} sin id valido: {variant_id!r}")
    variant_id = variant_id.strip()
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        raise EngineError(f"variante H3 {variant_id!r}: label invalido: {label!r}")
    lora_raw = entry.get("lora")
    lora = None if lora_raw is None else _require_text(lora_raw, f"variante H3 {variant_id!r}: lora")
    steps = entry.get("steps")
    if (
        isinstance(steps, bool)
        or not isinstance(steps, int)
        or not 1 <= steps <= H3_VARIANT_STEPS_MAX
    ):
        raise EngineError(
            f"variante H3 {variant_id!r}: steps invalido {steps!r}; "
            f"usar entero 1..{H3_VARIANT_STEPS_MAX}"
        )
    return {
        "id": variant_id,
        "label": label.strip(),
        "lora": lora,
        "steps": steps,
    }


def _parse_variants(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise EngineError(f"catalogo H3: variants invalidas: {value!r}")
    variants: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(value):
        variant = _parse_variant(entry, index)
        if variant["id"] in variants:
            raise EngineError(
                f"catalogo H3: variante duplicada: {variant['id']!r}"
            )
        variants[variant["id"]] = variant
    if DEFAULT_VARIANT not in variants:
        raise EngineError(
            f"catalogo H3: falta la variante por defecto {DEFAULT_VARIANT!r}"
        )
    return variants


def _parse_profile(
    entry: Any, index: int, allowed_seconds: list[int]
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise EngineError(f"perfil H3 #{index} invalido: se esperaba objeto")
    profile_id = entry.get("id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise EngineError(f"perfil H3 #{index} sin id valido: {profile_id!r}")
    profile_id = profile_id.strip()
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        raise EngineError(f"perfil H3 {profile_id!r}: label invalido: {label!r}")
    note = entry.get("note")
    if not isinstance(note, str):
        raise EngineError(f"perfil H3 {profile_id!r}: note invalido: {note!r}")
    template = entry.get("template")
    if (
        not isinstance(template, str)
        or not template.strip()
        or not template.strip().endswith(".json")
        or Path(template.strip()).name != template.strip()
    ):
        raise EngineError(
            f"perfil H3 {profile_id!r}: template invalido (archivo .json): {template!r}"
        )
    assets = {
        field: _require_text(entry.get(field), f"perfil H3 {profile_id!r}: {field}")
        for field in ("dit", "vae_video", "vae_audio")
    }
    encoder = entry.get("encoder")
    if encoder is not None:
        encoder = _require_text(encoder, f"perfil H3 {profile_id!r}: encoder")
    projection = entry.get("projection")
    if projection is not None:
        projection = _require_text(
            projection, f"perfil H3 {profile_id!r}: projection"
        )
        if encoder is None:
            raise EngineError(
                f"perfil H3 {profile_id!r}: projection sin encoder"
            )
    lora = entry.get("lora")
    if lora is not None:
        lora = _require_text(lora, f"perfil H3 {profile_id!r}: lora")
    recommended = entry.get("seconds_recomendados")
    if not isinstance(recommended, list) or not recommended:
        raise EngineError(
            f"perfil H3 {profile_id!r}: seconds_recomendados invalidos: {recommended!r}"
        )
    recom: list[int] = []
    for item in recommended:
        if (
            isinstance(item, bool)
            or not isinstance(item, int)
            or item not in allowed_seconds
        ):
            raise EngineError(
                f"perfil H3 {profile_id!r}: seconds_recomendados invalido {item!r}; "
                f"usar {allowed_seconds}"
            )
        if item in recom:
            raise EngineError(
                f"perfil H3 {profile_id!r}: seconds_recomendados duplicado: {item!r}"
            )
        recom.append(item)
    if recom != sorted(recom):
        raise EngineError(
            f"perfil H3 {profile_id!r}: seconds_recomendados debe ir en orden: "
            f"{recommended!r}"
        )
    return {
        "id": profile_id,
        "label": label.strip(),
        "note": note,
        "template": template.strip(),
        **assets,
        "encoder": encoder,
        "projection": projection,
        "lora": lora,
        "seconds_recomendados": recom,
    }


def _parse_catalog(data: Any, path: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("perfiles"), list):
        raise EngineError(f"catalogo de perfiles H3 invalido: {path}")
    seconds = _parse_seconds_catalog(data.get("seconds"))
    resolutions = _parse_resolutions(data.get("resoluciones"))
    variants = _parse_variants(data.get("variants"))
    profiles: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(data["perfiles"]):
        profile = _parse_profile(entry, index, seconds)
        if profile["id"] in profiles:
            raise EngineError(
                f"perfil H3 duplicado en {path}: {profile['id']!r}"
            )
        profiles[profile["id"]] = profile
    if not profiles:
        raise EngineError(f"catalogo de perfiles H3 sin perfiles: {path}")
    return {
        "seconds": seconds,
        "resolutions": resolutions,
        "variants": variants,
        "profiles": profiles,
    }


def load_h3_presets(path: str | Path = PROFILES_PATH) -> dict[str, Any]:
    """Lee y valida el catalogo; EngineError claro si falta o es invalido."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"catalogo de perfiles H3 ilegible: {path}") from exc
    return _parse_catalog(data, path)


_CATALOG: dict[str, Any] | None = None


def _catalog() -> dict[str, Any]:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = load_h3_presets(PROFILES_PATH)
    return _CATALOG


def h3_catalog(comfy_root: Path | str | None = None) -> dict[str, Any]:
    """Copia serializable del catalogo completo (segundos, resoluciones, variantes y perfiles)."""
    catalog = _catalog()
    vdn_ok = is_vdn_installed(comfy_root)
    profiles = []
    for p in catalog["profiles"].values():
        item = copy.deepcopy(p)
        if item.get("id") == "vdn":
            item["available"] = vdn_ok
            if not vdn_ok:
                item["missing_reason"] = "Pesos VDN no encontrados en ComfyUI/models/vdn"
        else:
            item["available"] = True
        profiles.append(item)
    return {
        "seconds": list(catalog["seconds"]),
        "resolutions": copy.deepcopy(catalog["resolutions"]),
        "variants": [copy.deepcopy(v) for v in catalog["variants"].values()],
        "profiles": profiles,
    }


def get_h3_presets(comfy_root: Path | str | None = None) -> list[dict[str, Any]]:
    """Devuelve la lista de perfiles anotada con su disponibilidad."""
    return h3_catalog(comfy_root)["profiles"]


def list_h3_profiles() -> list[dict[str, Any]]:
    """Copia serializable de los perfiles, en orden del catalogo."""
    return [copy.deepcopy(profile) for profile in _catalog()["profiles"].values()]


def list_h3_variants() -> list[dict[str, Any]]:
    """Copia serializable de las variantes (turbo4, turbo8), en orden del catalogo."""
    return [copy.deepcopy(variant) for variant in _catalog()["variants"].values()]


def h3_seconds() -> list[int]:
    """Segundos permitidos del catalogo (5/8/10/12/15)."""
    return list(_catalog()["seconds"])


def h3_resolutions() -> dict[str, list[dict[str, int]]]:
    """Resoluciones por aspecto del catalogo (vertical y espejo horizontal)."""
    return copy.deepcopy(_catalog()["resolutions"])


def get_h3_profile(profile_id: object) -> dict[str, Any]:
    """Perfil por id estricto; EngineError si no existe."""
    entry = (
        _catalog()["profiles"].get(profile_id.strip())
        if isinstance(profile_id, str)
        else None
    )
    if entry is None:
        raise EngineError(f"perfil H3 desconocido: {profile_id!r}")
    return entry


def resolve_h3_profile(profile: object = None) -> dict[str, Any]:
    """Perfil por id; ausente/``""`` = ``referencia`` (reproduce jobs viejos).

    EngineError si ``profile`` no es texto o si el id no existe en el catalogo.
    """
    if profile is None:
        return get_h3_profile(DEFAULT_PROFILE)
    if not isinstance(profile, str):
        raise EngineError(f"perfil H3 desconocido: {profile!r}")
    value = profile.strip()
    if not value:
        return get_h3_profile(DEFAULT_PROFILE)
    return get_h3_profile(value)


def get_h3_variant(variant_id: object) -> dict[str, Any]:
    """Variante por id estricto; EngineError si no existe."""
    entry = (
        _catalog()["variants"].get(variant_id.strip())
        if isinstance(variant_id, str)
        else None
    )
    if entry is None:
        raise EngineError(f"variante H3 desconocida: {variant_id!r}")
    return entry


def resolve_h3_variant(
    variant: object = None, profile: object = None
) -> dict[str, Any]:
    """Variante por id; ausente/``""`` = ``turbo4`` (o ``vdn8`` si el perfil es vdn).

    EngineError si ``variant`` no es texto o si el id no existe en el catalogo.
    """
    is_vdn_like = False
    if isinstance(profile, str) and profile.strip() in ("vdn", "ref2va"):
        is_vdn_like = True
    elif isinstance(profile, dict) and profile.get("id") in ("vdn", "ref2va"):
        is_vdn_like = True
    default_v = "vdn8" if is_vdn_like else DEFAULT_VARIANT
    if variant is None:
        return get_h3_variant(default_v)
    if not isinstance(variant, str):
        raise EngineError(f"variante H3 desconocida: {variant!r}")
    value = variant.strip()
    if not value:
        return get_h3_variant(default_v)
    return get_h3_variant(value)


def h3_template_path(profile: dict[str, Any]) -> Path:
    """Ruta absoluta de la plantilla del perfil (``workflows/<template>``)."""
    template = profile.get("template")
    if not isinstance(template, str) or not template.strip():
        raise EngineError(f"perfil H3 sin template: {profile.get('id')!r}")
    return APP_ROOT / "workflows" / template.strip()


def require_h3_seconds(seconds: Any) -> int:
    """Segundos permitidos del catalogo (5/8/10/12/15); float integral vale."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise EngineError(f"h3: seconds invalido {seconds!r}; usar {h3_seconds()}")
    value = float(seconds)
    if not math.isfinite(value):
        raise EngineError(f"h3: seconds invalido {seconds!r}; usar {h3_seconds()}")
    for allowed in h3_seconds():
        if value == allowed:
            return allowed
    raise EngineError(f"h3: seconds invalido {seconds!r}; usar {h3_seconds()}")


def h3_frames_for_seconds(seconds: Any) -> int:
    """Menor length 5+17n >= ``seconds`` a 24 fps (5 s → 124, 8 s → 192).

    10 s → 243, 12 s → 294 y 15 s → 362 (grid entrenado 124-362). EngineError
    si ``seconds`` no es un numero valido del catalogo.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise EngineError(f"h3: seconds invalido {seconds!r}; usar {h3_seconds()}")
    value = float(seconds)
    if not math.isfinite(value) or not H3_SECONDS[0] <= value <= H3_SECONDS[-1]:
        raise EngineError(f"h3: seconds fuera de rango (5-{H3_SECONDS[-1]}): {seconds!r}")
    if int(value) != value or int(value) not in H3_SECONDS:
        raise EngineError(f"h3: seconds invalido {seconds!r}; usar {h3_seconds()}")
    needed = math.ceil(value * H3_FPS)
    if needed <= H3_FRAME_BASE:
        return H3_FRAME_BASE
    steps = math.ceil((needed - H3_FRAME_BASE) / H3_FRAME_STEP)
    return H3_FRAME_BASE + H3_FRAME_STEP * steps


def split_chained_seconds(seconds: int | float) -> list[int]:
    """Divide segundos (> 15) en bloques secuenciales <= 15 s para encadenado continuo."""
    s = int(seconds)
    if s <= 15:
        return [s]
    if s == 20:
        return [10, 10]
    if s == 24:
        return [12, 12]
    if s == 25:
        return [10, 15]
    if s == 30:
        return [15, 15]
    blocks: list[int] = []
    rem = s
    while rem > 15:
        cand = 15
        while cand >= 5 and rem - cand < 5:
            cand -= 1
        blocks.append(cand)
        rem -= cand
    if rem > 0:
        blocks.append(rem)
    return blocks



def require_h3_frames(frames: Any) -> int:
    """Valida length 5+17n dentro del rango entrenado (124..362)."""
    if isinstance(frames, bool) or not isinstance(frames, int):
        raise EngineError(f"h3: frames invalido {frames!r}; usar entero 5+17n")
    if (
        frames < H3_MIN_FRAMES
        or frames > H3_MAX_FRAMES
        or (frames - H3_FRAME_BASE) % H3_FRAME_STEP != 0
    ):
        raise EngineError(
            f"h3: frames invalido {frames}; usar 5+17n entre "
            f"{H3_MIN_FRAMES} y {H3_MAX_FRAMES}"
        )
    return frames


def _require_size(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EngineError(
            f"h3: {name} invalido {value!r}; usar entero multiplo de {H3_SIZE_STEP}"
        )
    if value < H3_SIZE_STEP or value % H3_SIZE_STEP != 0:
        raise EngineError(
            f"h3: {name} invalido {value!r}; usar multiplo de {H3_SIZE_STEP}"
        )
    return value


def h3_aspect(width: Any, height: Any) -> str:
    """Aspecto implicito de la resolucion (vertical si alto > ancho)."""
    width = _require_size(width, "width")
    height = _require_size(height, "height")
    if width == height:
        raise EngineError(f"h3: resolucion cuadrada no soportada: {width}x{height}")
    return "vertical" if height > width else "horizontal"


def validate_h3_size(
    width: Any, height: Any, aspect: object = None
) -> tuple[int, int]:
    """Valida medidas: multiplo de 32, area <= 768x1344 y aspecto opcional."""
    width = _require_size(width, "width")
    height = _require_size(height, "height")
    if width * height > H3_MAX_PIXELS:
        raise EngineError(
            f"h3: area {width}x{height} excede {H3_MAX_PIXELS} px (768x1344)"
        )
    real = h3_aspect(width, height)
    if aspect is not None:
        if aspect not in H3_ASPECTS:
            raise EngineError(
                f"h3: aspect invalido {aspect!r}; usar vertical|horizontal"
            )
        if aspect != real:
            raise EngineError(f"h3: {width}x{height} no es {aspect}")
    return width, height


def h3_default_size(aspect: object = "vertical") -> tuple[int, int]:
    """Primera resolucion del catalogo para el aspecto dado."""
    if aspect not in H3_ASPECTS:
        raise EngineError(
            f"h3: aspect invalido {aspect!r}; usar vertical|horizontal"
        )
    size = h3_resolutions()[aspect][0]
    return size["width"], size["height"]


__all__ = [
    "DEFAULT_PROFILE",
    "DEFAULT_VARIANT",
    "H3_ASPECTS",
    "H3_FPS",
    "H3_FRAME_BASE",
    "H3_FRAME_STEP",
    "H3_MAX_FRAMES",
    "H3_MAX_PIXELS",
    "H3_MIN_FRAMES",
    "H3_SECONDS",
    "H3_SIZE_STEP",
    "H3_VARIANT_STEPS_MAX",
    "PROFILE_COMPATIBLE_VARIANTS",
    "PROFILES_PATH",
    "get_h3_presets",
    "get_h3_profile",
    "get_h3_variant",
    "h3_aspect",
    "h3_catalog",
    "h3_default_size",
    "h3_frames_for_seconds",
    "h3_resolutions",
    "h3_seconds",
    "h3_template_path",
    "is_vdn_installed",
    "list_h3_profiles",
    "list_h3_variants",
    "load_h3_presets",
    "require_h3_frames",
    "require_h3_seconds",
    "resolve_h3_profile",
    "resolve_h3_variant",
    "split_chained_seconds",
    "validate_h3_profile_variant",
    "validate_h3_size",
]
