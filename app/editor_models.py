"""Catalogo del editor Qwen-Image 2.1 UC (M10-6b).

Catalogo local estricto ``registry/editor_models-v1.json`` (mismo estilo que
`app.upscale`: solo stdlib y `EngineError` claro si falta o es invalido). Fija
los nombres REALES del par UC que espera el Editor: GGUF de difusion, text
encoder int8 ConvRot y VAE bf16. El VAE del editor
(``vae/qwen_image_2.1_vae_bf16.safetensors``) es distinto del VAE de Anima
(``vae/qwen_image_vae.safetensors``) y no lo pisa. CPU, sin red ni GPU.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.config import APP_ROOT
from app.engine import EngineError

EDITOR_CATALOG_PATH = APP_ROOT / "registry" / "editor_models-v1.json"
CATALOG_VERSION = 1


@dataclass(frozen=True)
class EditorModel:
    """Modelo del editor: id, etiqueta, nota de guarda y archivos relativos."""

    id: str
    display_name: str
    note: str
    files: tuple[str, ...]


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"catalogo del editor: {label} invalido: {value!r}")
    return value.strip()


def _require_relative_file(value: object, index: int) -> str:
    """Ruta relativa POSIX simple (sin absolutos, ``..`` ni ``\\``)."""
    file = _require_text(value, f"files[{index}]")
    path = Path(file)
    if path.is_absolute() or "\\" in file:
        raise EngineError(f"catalogo del editor: files[{index}] invalido: {value!r}")
    if any(part in ("", ".", "..") for part in file.split("/")):
        raise EngineError(f"catalogo del editor: files[{index}] invalido: {value!r}")
    return file


def load_editor_model(path: str | Path = EDITOR_CATALOG_PATH) -> EditorModel:
    """Lee y valida el catalogo; EngineError claro si falta o es invalido."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"catalogo del editor ilegible: {path}") from exc
    if not isinstance(data, dict):
        raise EngineError(f"catalogo del editor invalido: {path}")
    version = data.get("version")
    if isinstance(version, bool) or version != CATALOG_VERSION:
        raise EngineError(
            f"catalogo del editor con version invalida: {version!r} "
            f"(esperada {CATALOG_VERSION})"
        )
    model_id = _require_text(data.get("id"), "id")
    display_name = _require_text(data.get("display_name"), "display_name")
    note = data.get("note")
    if not isinstance(note, str):
        raise EngineError(f"catalogo del editor: note invalido: {note!r}")
    raw_files = data.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise EngineError(f"catalogo del editor: files invalido: {raw_files!r}")
    files: list[str] = []
    for index, raw in enumerate(raw_files):
        file = _require_relative_file(raw, index)
        if file in files:
            raise EngineError(f"catalogo del editor: archivo duplicado: {file!r}")
        files.append(file)
    return EditorModel(
        id=model_id,
        display_name=display_name,
        note=note,
        files=tuple(files),
    )


_EDITOR_MODEL: EditorModel | None = None


def editor_model() -> EditorModel:
    """Catalogo cargado una vez (perezoso); mismo objeto inmutable por llamada."""
    global _EDITOR_MODEL
    if _EDITOR_MODEL is None:
        _EDITOR_MODEL = load_editor_model(EDITOR_CATALOG_PATH)
    return _EDITOR_MODEL


__all__ = [
    "CATALOG_VERSION",
    "EDITOR_CATALOG_PATH",
    "EditorModel",
    "editor_model",
    "load_editor_model",
]
