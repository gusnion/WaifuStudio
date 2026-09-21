"""Configuración central del engine (contrato congelado M8-01)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_COMFY_ROOT = Path(r"E:\IA\VIDEO\ComfyUI")
DEFAULT_COMFY_URL = "http://127.0.0.1:8288"


@dataclass(frozen=True)
class EngineConfig:
    """Rutas y endpoint del engine local."""

    comfy_root: Path
    comfy_url: str
    data_dir: Path

    @property
    def comfy_output_dir(self) -> Path:
        return self.comfy_root / "output"

    @property
    def comfy_workflows_dir(self) -> Path:
        return self.comfy_root / "user" / "default" / "workflows"

    @property
    def comfy_models_dir(self) -> Path:
        return self.comfy_root / "models"

    @property
    def comfy_custom_nodes_dir(self) -> Path:
        return self.comfy_root / "custom_nodes"


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def load_config() -> EngineConfig:
    """Construye la config desde defaults más overrides de entorno."""
    return EngineConfig(
        comfy_root=_env_path("WAIFU_COMFY_ROOT", DEFAULT_COMFY_ROOT),
        comfy_url=_env_str("WAIFU_COMFY_URL", DEFAULT_COMFY_URL),
        data_dir=_env_path("WAIFU_DATA_DIR", APP_ROOT / "data"),
    )


def describe(cfg: EngineConfig) -> list[str]:
    """Líneas legibles 'clave: valor' para el smoke."""
    return [
        f"app_root: {APP_ROOT}",
        f"comfy_root: {cfg.comfy_root}",
        f"comfy_url: {cfg.comfy_url}",
        f"comfy_output_dir: {cfg.comfy_output_dir}",
        f"comfy_workflows_dir: {cfg.comfy_workflows_dir}",
        f"comfy_models_dir: {cfg.comfy_models_dir}",
        f"comfy_custom_nodes_dir: {cfg.comfy_custom_nodes_dir}",
        f"data_dir: {cfg.data_dir}",
    ]
