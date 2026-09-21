"""Registro versionado de modelos locales (M8-10).

Formato JSON: ``{"version": 1, "models": [ModelEntry, ...]}`` en
``E:\\IA\\WAIFU\\registry\\models.json``. CPU, sin red ni GPU.
CLI: ``python -m app.registry`` imprime ``id | family | unet | preprompt``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from app.engine import EngineError

REGISTRY_VERSION = 1
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "registry" / "models.json"

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

    def to_dict(self) -> dict:
        return {
            "version": REGISTRY_VERSION,
            "models": [asdict(entry) for entry in self._models],
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
        """Carga el JSON UTF-8 de path; EngineError si es ilegible o invalido."""
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EngineError(
                f"registro ilegible {path}: {type(exc).__name__}: {exc}"
            ) from exc
        return cls.from_dict(payload)

    def save(self, path: str | Path) -> Path:
        """Escribe el registro como JSON UTF-8 con indent de 2."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"
        target.write_text(text, encoding="utf-8")
        return target


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
    "REGISTRY_VERSION",
    "ModelEntry",
    "ModelProfile",
    "ModelRegistry",
    "main",
]
