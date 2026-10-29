"""Registro versionado de modelos locales (M8-10).

Formato JSON: ``{"version": 1, "models": [ModelEntry, ...]}`` en
``E:\\IA\\WAIFU\\registry\\models.json``. CPU, sin red ni GPU.
CLI: ``python -m app.registry`` imprime ``id | family | unet | preprompt``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from app.engine import EngineError

REGISTRY_VERSION = 1
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "registry" / "models.json"

PROMPT_PROFILES = ("anima", "sdxl_tags", "sdxl_natural", "qwen_edit", "animagine")
DEFAULT_PROMPT_PROFILE = "sdxl_tags"

# Fuente unica de verdad de la guia de prompt por perfil (UI + API).
# Campos: label, placeholder, help (hint bajo "Generar prompt"), legend_help
# (tooltip del bloque 1), zones_help (tooltip del bloque de zonas, solo tags),
# prose_guide (guia de prosa, solo natural/edicion), quality_tags,
# artist_prefix, order, zones_visible, prompt_kind ("tags" | "natural").
PROMPT_PROFILE_INFO: dict[str, dict] = {
    "anima": {
        "label": "Anima (tags Danbooru)",
        "placeholder": "Tags Danbooru con @artista (ej.: 1girl, solo, looking at viewer, @artist)",
        "help": (
            "Escribe la escena en lenguaje natural: se convierte en tags Danbooru por zona, "
            "con score_N y @artista. Tus tags ya insertadas se respetan (no se repiten)."
        ),
        "legend_help": (
            "Describe la escena: sujeto, estilo, entorno o acción. "
            "Se descompone en tags Danbooru por zonas."
        ),
        "zones_help": "Organiza los tags Danbooru por cuadrantes y capas de personajes u OCs.",
        "prose_guide": "",
        "quality_tags": ["masterpiece", "best quality", "score_8"],
        "artist_prefix": "@",
        "order": 10,
        "zones_visible": True,
        "prompt_kind": "tags",
    },
    "animagine": {
        "label": "Animagine (tags SDXL anime)",
        "placeholder": "Tags anime separados por comas, sin scores numéricos ni prefijo de artista (ej.: 1girl, solo, smile, masterpiece, high score)",
        "help": (
            "Escribe la escena en lenguaje natural: se convierte en tags por zona al estilo "
            "Animagine (masterpiece, high score, great score). Sin scores numéricos ni prefijo de artista."
        ),
        "legend_help": (
            "Describe la escena: sujeto, estilo, entorno o acción. "
            "Se descompone en tags anime por zonas."
        ),
        "zones_help": "Organiza los tags anime por cuadrantes y capas de personajes u OCs.",
        "prose_guide": "",
        "quality_tags": ["masterpiece", "high score", "great score", "absurdres"],
        "artist_prefix": "",
        "order": 20,
        "zones_visible": True,
        "prompt_kind": "tags",
    },
    "sdxl_tags": {
        "label": "SDXL / Illustrious (tags)",
        "placeholder": "Tags descriptivos sin score_N ni @ (ej.: 1girl, solo, portrait, soft lighting, highres)",
        "help": (
            "Escribe la escena en lenguaje natural: se convierte en tags descriptivos por zona. "
            "Tus tags ya insertadas se respetan (no se repiten)."
        ),
        "legend_help": (
            "Describe la escena: sujeto, estilo, entorno o acción. "
            "Se descompone en tags por zonas."
        ),
        "zones_help": "Organiza los tags por cuadrantes y capas de personajes u OCs.",
        "prose_guide": "",
        "quality_tags": ["masterpiece", "best quality", "highres"],
        "artist_prefix": "",
        "order": 30,
        "zones_visible": True,
        "prompt_kind": "tags",
    },
    "sdxl_natural": {
        "label": "SDXL realista (lenguaje natural)",
        "placeholder": "Frase en lenguaje natural (ej.: A serene portrait of a young woman in a sunlit garden)",
        "help": (
            "Escribe la escena como prosa: sujeto, luz, cámara y ambiente en frases completas. "
            "El asistente la reescribe como una descripción fluida."
        ),
        "legend_help": "Describe la escena en frases completas: sujeto, entorno, luz, cámara y ambiente.",
        "zones_help": "",
        "prose_guide": (
            "Guía de prosa: 1-3 frases en inglés con sujeto + acción + entorno + luz + cámara "
            "(ej.: A candid photo of a woman reading in a café, soft window light, 85mm, shallow depth of field)."
        ),
        "quality_tags": [],
        "artist_prefix": "",
        "order": 40,
        "zones_visible": False,
        "prompt_kind": "natural",
    },
    "qwen_edit": {
        "label": "Qwen Edit (instrucción)",
        "placeholder": "Instrucción de edición o generación (ej.: Change expression to a gentle smile, sunset background)",
        "help": (
            "Escribe una instrucción clara y directa sobre qué cambiar o generar. "
            "El asistente la mantiene como una orden en prosa."
        ),
        "legend_help": "Describe en una frase qué quieres generar o cambiar en la imagen.",
        "zones_help": "",
        "prose_guide": (
            "Guía de prosa: una instrucción por frase, verbo + objeto + detalle "
            "(ej.: Replace the background with a snowy forest at dusk)."
        ),
        "quality_tags": [],
        "artist_prefix": "",
        "order": 50,
        "zones_visible": False,
        "prompt_kind": "natural",
    },
}


def prompt_profile_info(profile: str = "") -> dict:
    """Devuelve una copia de la guia de prompt del perfil (default: sdxl_tags)."""
    key = profile if profile in PROMPT_PROFILE_INFO else DEFAULT_PROMPT_PROFILE
    info = PROMPT_PROFILE_INFO[key]
    return {"profile": key, **info, "quality_tags": list(info["quality_tags"])}

KNOWN_SUBFAMILIES = (
    "anima",
    "illustrious",
    "pony",
    "noobai",
    "sdxl_base",
    "wan",
    "h3",
    "sin_clasificar",
)
DEFAULT_SUBFAMILY = "sin_clasificar"


_ANIMA_RE = re.compile(r"(?<![a-z])anima(?![a-z])")
_SDXL_TENSOR_PREFIX = "model.diffusion_model.input_blocks."
_ANIMA_TENSOR_PREFIXES = ("model.diffusion_model.blocks.", "net.blocks.", "diffusion_model.blocks.")
_VIDEO_TENSOR_PREFIXES = (
    "patch_embedding.",
    "time_projection.",
    "audio_patch_proj.",
    "model.diffusion_model.patch_embedding.",
    "model.diffusion_model.time_projection.",
)


def _infer_from_tensor_names(tensor_names) -> str:
    """Subfamilia base por layout de tensores (evidencia fuerte). ``""`` si no hay layout claro."""
    if tensor_names is None:
        return ""
    try:
        names = [str(n) for n in tensor_names if n != "__metadata__"]
    except TypeError:
        return ""
    if not names:
        return ""
    has_cond = any(n.startswith("conditioner.embedders.") for n in names)
    has_vae = any(n.startswith("first_stage_model.") for n in names)
    has_input = any(n.startswith(_SDXL_TENSOR_PREFIX) for n in names)
    if has_cond and has_vae and has_input:
        return "sdxl_base"
    if any(n.startswith(_VIDEO_TENSOR_PREFIXES) for n in names):
        return ""
    if any(n.startswith(_ANIMA_TENSOR_PREFIXES) for n in names):
        return "anima"
    return ""


def _infer_from_filename(filename: str, *, sdxl_layout: bool = False) -> str:
    """Pista debil por nombre de archivo. Animagine se evalua antes que Anima."""
    name = str(filename or "").lower()
    if not name:
        return ""
    if "animagine" in name:
        return "sdxl_base"
    if "illustrious" in name or re.search(r"(?<![a-z])illu(?![a-z])", name):
        return "illustrious"
    if "pony" in name:
        return "pony"
    if "noobai" in name or "noob-ai" in name:
        return "noobai"
    if sdxl_layout:
        return ""
    if _ANIMA_RE.search(name):
        return "anima"
    if "sdxl" in name or "sd_xl" in name:
        return "sdxl_base"
    return ""


def infer_subfamily(
    metadata_or_base: dict | str | None = None,
    tensor_names=None,
    filename: str = "",
    *,
    modelspec_architecture: str = "",
    ss_base_model_version: str = "",
) -> str:
    """Infiere la subfamilia base de un modelo/LoRA safetensors.

    Orden de evidencia: 1) metadata (ss_base_model_version / modelspec.architecture),
    2) layout de tensores (``tensor_names``: SDXL = conditioner.embedders + first_stage_model
    + input_blocks; Anima = ``*.blocks.*``), 3) nombre de archivo solo como pista.
    Sin evidencia devuelve ``sin_clasificar``; nunca inventa.

    Valores conocidos:
    - anima, illustrious, pony, noobai, sdxl_base, wan, h3, sin_clasificar.
    """
    from_meta = _infer_from_metadata(
        metadata_or_base,
        modelspec_architecture=modelspec_architecture,
        ss_base_model_version=ss_base_model_version,
    )
    if from_meta != DEFAULT_SUBFAMILY:
        return from_meta
    layout = _infer_from_tensor_names(tensor_names)
    if layout:
        if layout == "sdxl_base":
            return _infer_from_filename(filename, sdxl_layout=True) or "sdxl_base"
        return layout
    return _infer_from_filename(filename) or DEFAULT_SUBFAMILY


def _infer_from_metadata(
    metadata_or_base: dict | str | None = None,
    *,
    modelspec_architecture: str = "",
    ss_base_model_version: str = "",
) -> str:
    """Subfamilia segun texto de metadata (ss_base_model_version y modelspec.architecture)."""
    if isinstance(metadata_or_base, dict):
        meta_ci = {str(k).lower(): v for k, v in metadata_or_base.items()}
        base_ver = str(
            meta_ci.get("ss_base_model_version")
            or metadata_or_base.get("ss_base_model_version")
            or ss_base_model_version
            or ""
        )
        arch = str(
            meta_ci.get("modelspec.architecture")
            or metadata_or_base.get("modelspec.architecture")
            or modelspec_architecture
            or ""
        )
    elif isinstance(metadata_or_base, str):
        base_ver = metadata_or_base
        arch = str(modelspec_architecture or "")
    else:
        base_ver = str(ss_base_model_version or "")
        arch = str(modelspec_architecture or "")

    combined = f"{arch} {base_ver}".strip().lower()
    if not combined:
        return DEFAULT_SUBFAMILY

    # 1. Illustrious
    if "illustrious" in combined or "illu" in combined.split() or "illu_v" in combined or "illu-v" in combined:
        return "illustrious"

    # 2. Pony
    if "pony" in combined:
        return "pony"

    # 3. NoobAI
    if "noobai" in combined or "noob-ai" in combined or "noob" in combined.split():
        return "noobai"

    # 4. Animagine (SDXL; antes de Anima por colision de prefijo) y Anima
    if "animagine" in combined:
        return "sdxl_base"
    if _ANIMA_RE.search(combined):
        return "anima"

    # 5. Wan
    if "wan" in combined or "lightx2v" in combined:
        return "wan"

    # 6. H3
    if "h3" in combined.split() or "minimax" in combined:
        return "h3"

    # 7. SDXL base
    if "sdxl" in combined or "stable-diffusion-xl" in combined or "sd_xl" in combined:
        return "sdxl_base"

    return DEFAULT_SUBFAMILY


def infer_prompt_profile(
    model_id: str | dict | ModelEntry = "",
    family: str = "",
    display_name: str = "",
    unet_name: str = "",
    subfamily: str = "",
) -> str:
    """Infiere el prompt_profile para compatibilidad retroactiva con modelos conocidos.

    Reglas:
    - animagine -> "animagine" (perfil propio: tags SDXL sin score_N/@ de Anima;
      evaluado antes de anima por colision de prefijo)
    - realvis / juggernaut -> "sdxl_natural"
    - subfamilia illustrious / pony / noobai -> "sdxl_tags"
    - anima (familia, subfamilia, o nombre/id si la familia no es sdxl) -> "anima"
    - resto -> "sdxl_tags" (default retrocompatible)
    """
    if isinstance(model_id, dict):
        data = model_id
        mid = str(data.get("id") or "")
        fam = str(data.get("family") or "")
        disp = str(data.get("display_name") or "")
        prof = data.get("profile") or {}
        unet = str(prof.get("unet_name") or "") if isinstance(prof, dict) else ""
    elif isinstance(model_id, ModelEntry):
        mid = model_id.id
        fam = model_id.family
        disp = model_id.display_name
        unet = getattr(model_id.profile, "unet_name", "")
    else:
        mid = str(model_id or "")
        fam = str(family or "")
        disp = str(display_name or "")
        unet = str(unet_name or "")

    mid_l = mid.lower()
    fam_l = fam.lower()
    disp_l = disp.lower()
    unet_l = unet.lower()
    combined = f"{mid_l} {disp_l} {unet_l}"

    # 1. Animagine (SDXL anime por tags propios, sin scores/artistas de Anima)
    if "animagine" in combined:
        return "animagine"

    # 2. RealVisXL / Juggernaut (modelos SDXL de lenguaje natural)
    if "realvis" in combined or "juggernaut" in combined:
        return "sdxl_natural"

    # 3. Subfamilia SDXL basada en tags (evidencia de metadata/tensores/nombre)
    if str(subfamily or "").lower() in ("illustrious", "pony", "noobai"):
        return "sdxl_tags"

    # 4. Anima: familia/subfamilia anima, o nombre solo si la familia no es SDXL
    if (
        fam_l == "anima"
        or str(subfamily or "").lower() == "anima"
        or (fam_l != "sdxl" and "anima" in combined)
    ):
        return "anima"

    # 5. Resto (default retrocompatible)
    return DEFAULT_PROMPT_PROFILE


def user_registry_path() -> Path:
    """Capa de usuario del registro: `data/registry/models.json`.

    Se deriva de la raiz de `DEFAULT_PATH` (asi los tests que lo parchean a un
    temporal quedan aislados); `WAIFU_DATA_DIR` la mueve si esta definida.
    """
    root = DEFAULT_PATH.parents[1] if len(DEFAULT_PATH.parents) > 1 else DEFAULT_PATH.parent
    base = Path(os.environ.get("WAIFU_DATA_DIR") or root / "data")
    return base / "registry" / DEFAULT_PATH.name

_ID_RE = re.compile(r"[a-z0-9._-]+")
_REQUIRED_FIELDS = ("id", "family", "display_name", "profile", "source", "license")
_REQUIRED_TEXT_FIELDS = ("id", "family", "display_name", "source", "license")
_PROFILE_FIELDS = ("unet_name", "clip_name", "clip_type", "vae_name")


@dataclass(frozen=True)
class ModelProfile:
    """Perfil de carga del engine: unet + clip + vae."""

    unet_name: str
    clip_name: str
    clip_type: str
    vae_name: str


@dataclass(frozen=True)
class ModelEntry:
    """Modelo registrado: perfil, procedencia y defaults de generacion."""

    id: str
    family: str
    display_name: str
    profile: ModelProfile
    source: str
    license: str
    preprompt: str = "glossy"
    defaults: dict = field(default_factory=dict)
    notes: str = ""
    prompt_profile: str = ""
    subfamily: str = DEFAULT_SUBFAMILY
    owner_addon: str | None = None

    def __post_init__(self) -> None:
        if not self.prompt_profile:
            inferred = infer_prompt_profile(
                model_id=self.id,
                family=self.family,
                display_name=self.display_name,
                unet_name=getattr(self.profile, "unet_name", "") if hasattr(self, "profile") else "",
            )
            object.__setattr__(self, "prompt_profile", inferred)
        if not self.subfamily:
            object.__setattr__(self, "subfamily", DEFAULT_SUBFAMILY)
        elif not isinstance(self.subfamily, str) or self.subfamily not in KNOWN_SUBFAMILIES:
            raise EngineError(
                f"subfamily invalida: {self.subfamily!r} (esperada una de {KNOWN_SUBFAMILIES})"
            )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"campo obligatorio no vacio: {label} (recibido {value!r})")
    return value


def _validate_profile(profile: object) -> ModelProfile:
    if not isinstance(profile, ModelProfile):
        raise EngineError(
            f"profile invalido: se esperaba ModelProfile, recibido {type(profile).__name__}"
        )
    values = {
        name: _require_text(getattr(profile, name), f"profile.{name}")
        for name in _PROFILE_FIELDS
    }
    return ModelProfile(**values)


def _validate_entry(entry: object) -> ModelEntry:
    if not isinstance(entry, ModelEntry):
        raise EngineError(
            f"entrada invalida: se esperaba ModelEntry, recibido {type(entry).__name__}"
        )
    _require_text(entry.id, "id")
    if _ID_RE.fullmatch(entry.id) is None:
        raise EngineError(f"id fuera del slug [a-z0-9._-]+: {entry.id!r}")
    for attribute in _REQUIRED_TEXT_FIELDS[1:]:
        _require_text(getattr(entry, attribute), attribute)
    if not isinstance(entry.preprompt, str):
        raise EngineError(f"preprompt debe ser str: {entry.preprompt!r}")
    if not isinstance(entry.defaults, dict):
        raise EngineError(f"defaults debe ser dict: {entry.defaults!r}")
    if not isinstance(entry.notes, str):
        raise EngineError(f"notes debe ser str: {entry.notes!r}")
    if (
        not isinstance(entry.prompt_profile, str)
        or entry.prompt_profile not in PROMPT_PROFILES
    ):
        raise EngineError(
            f"prompt_profile invalido: {entry.prompt_profile!r} (esperado uno de {PROMPT_PROFILES})"
        )
    if (
        not isinstance(entry.subfamily, str)
        or entry.subfamily not in KNOWN_SUBFAMILIES
    ):
        raise EngineError(
            f"subfamily invalida: {entry.subfamily!r} (esperada una de {KNOWN_SUBFAMILIES})"
        )
    if entry.owner_addon is not None and not isinstance(entry.owner_addon, str):
        raise EngineError(
            f"owner_addon debe ser str o None: {entry.owner_addon!r}"
        )
    return replace(entry, profile=_validate_profile(entry.profile))


def _entry_from_dict(data: object) -> ModelEntry:
    if not isinstance(data, dict):
        raise EngineError(
            f"entrada de modelo invalida: se esperaba objeto JSON, recibido {type(data).__name__}"
        )
    missing = [key for key in _REQUIRED_FIELDS if key not in data]
    if missing:
        raise EngineError(f"entrada de modelo sin campos: {', '.join(missing)}")
    profile_data = data["profile"]
    if not isinstance(profile_data, dict):
        raise EngineError(
            f"profile debe ser dict: recibido {type(profile_data).__name__}"
        )
    missing_profile = [name for name in _PROFILE_FIELDS if name not in profile_data]
    if missing_profile:
        raise EngineError(f"profile sin campos: {', '.join(missing_profile)}")
    raw_profile = data.get("prompt_profile")
    if raw_profile is not None and str(raw_profile).strip():
        prompt_profile = str(raw_profile).strip()
    else:
        prompt_profile = infer_prompt_profile(
            model_id=data.get("id", ""),
            family=data.get("family", ""),
            display_name=data.get("display_name", ""),
            unet_name=profile_data.get("unet_name", "") if isinstance(profile_data, dict) else "",
        )
    raw_subfamily = data.get("subfamily")
    if raw_subfamily is not None and str(raw_subfamily).strip():
        subfamily = str(raw_subfamily).strip()
    else:
        subfamily = DEFAULT_SUBFAMILY
    owner_addon = data.get("owner_addon")
    entry = ModelEntry(
        id=data["id"],
        family=data["family"],
        display_name=data["display_name"],
        profile=ModelProfile(
            **{name: profile_data[name] for name in _PROFILE_FIELDS}
        ),
        source=data["source"],
        license=data["license"],
        preprompt=data.get("preprompt", "glossy"),
        defaults=data.get("defaults", {}),
        notes=data.get("notes", ""),
        prompt_profile=prompt_profile,
        subfamily=subfamily,
        owner_addon=owner_addon,
    )
    return _validate_entry(entry)


class ModelRegistry:
    """Coleccion en memoria de ModelEntry, cargable y guardable como JSON."""

    def __init__(self) -> None:
        self._models: list[ModelEntry] = []

    @property
    def models(self) -> list[ModelEntry]:
        return list(self._models)

    def __len__(self) -> int:
        return len(self._models)

    def get(self, model_id: str) -> ModelEntry:
        """Entrada con ese id; EngineError si no existe."""
        for entry in self._models:
            if entry.id == model_id:
                return entry
        raise EngineError(f"modelo no registrado: {model_id!r}")

    def by_family(self, family: str) -> list[ModelEntry]:
        """Entradas de una familia, en orden de registro."""
        return [entry for entry in self._models if entry.family == family]

    def add(self, entry: ModelEntry) -> ModelEntry:
        """Valida y anade; EngineError si el id ya existe o la entrada es invalida."""
        validated = _validate_entry(entry)
        if any(existing.id == validated.id for existing in self._models):
            raise EngineError(f"id duplicado en el registro: {validated.id!r}")
        self._models.append(validated)
        return validated

    def _replace(self, entry: ModelEntry) -> None:
        """Valida `entry` y sustituye la entrada con su id (o la anade)."""
        validated = _validate_entry(entry)
        for index, existing in enumerate(self._models):
            if existing.id == validated.id:
                self._models[index] = validated
                return
        self._models.append(validated)

    def update(self, model_id: str, **updates) -> ModelEntry:
        """Actualiza campos de un modelo existente y lo valida."""
        entry = self.get(model_id)
        updated = replace(entry, **updates)
        self._replace(updated)
        return updated

    def to_dict(self) -> dict:
        models = []
        for entry in self._models:
            d = asdict(entry)
            if entry.owner_addon is None:
                d.pop("owner_addon", None)
            models.append(d)
        return {
            "version": REGISTRY_VERSION,
            "models": models,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "ModelRegistry":
        if not isinstance(payload, dict):
            raise EngineError(
                f"registro invalido: se esperaba objeto JSON, recibido {type(payload).__name__}"
            )
        version = payload.get("version")
        if version != REGISTRY_VERSION:
            raise EngineError(
                f"version de registro no soportada: {version!r} (esperada {REGISTRY_VERSION})"
            )
        models = payload.get("models")
        if not isinstance(models, list):
            raise EngineError("registro invalido: falta la lista 'models'")
        registry = cls()
        for data in models:
            registry.add(_entry_from_dict(data))
        return registry

    @classmethod
    def load(cls, path: str | Path) -> "ModelRegistry":
        """Carga el JSON UTF-8 de path; EngineError si es ilegible o invalido.

        Con `DEFAULT_PATH` (registro del repo, vacio a proposito) se fusiona la
        capa de usuario `data/registry/models.json` si existe: misma id -> gana
        la de usuario. Con rutas explicitas (fixtures/tests) no hay overlay.
        """
        target = Path(path)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EngineError(
                f"registro ilegible {path}: {type(exc).__name__}: {exc}"
            ) from exc
        registry = cls.from_dict(payload)
        overlay = user_registry_path()
        if (
            target.resolve() == DEFAULT_PATH.resolve()
            and overlay.is_file()
            and overlay.resolve() != target.resolve()
        ):
            registry = _merge(registry, cls.load(overlay))
        return registry

    @classmethod
    def load_or_empty(cls, path: str | Path) -> "ModelRegistry":
        """Como `load`, pero un fichero ausente devuelve un registro vacio."""
        if not Path(path).is_file():
            return cls()
        return cls.load(path)

    def save(self, path: str | Path) -> Path:
        """Escribe el registro como JSON UTF-8 con indent de 2."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"
        target.write_text(text, encoding="utf-8")
        return target


def _merge(base: "ModelRegistry", extra: "ModelRegistry") -> "ModelRegistry":
    """Fusiona dos registros: las entradas de `extra` ganan por id."""
    merged = ModelRegistry()
    for entry in base.models:
        merged.add(entry)
    for entry in extra.models:
        merged._replace(entry)
    return merged


def main() -> int:
    """CLI: una linea por modelo (id | family | unet | preprompt)."""
    registry = ModelRegistry.load(DEFAULT_PATH)
    for entry in registry.models:
        print(
            f"{entry.id} | {entry.family} | {entry.profile.unet_name} | {entry.preprompt}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_PATH",
    "DEFAULT_PROMPT_PROFILE",
    "DEFAULT_SUBFAMILY",
    "KNOWN_SUBFAMILIES",
    "PROMPT_PROFILES",
    "PROMPT_PROFILE_INFO",
    "REGISTRY_VERSION",
    "ModelEntry",
    "ModelProfile",
    "ModelRegistry",
    "infer_prompt_profile",
    "infer_subfamily",
    "load_or_empty",
    "main",
    "prompt_profile_info",
    "user_registry_path",
]
