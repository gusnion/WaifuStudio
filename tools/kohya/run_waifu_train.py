"""Lanzador del entrenador kohya para WAIFU (sd-scripts + networks.lora_anima).

El orquestador de la app (`app/trainer.py`) ejecuta
``WAIFU_TRAINER_CMD + [config_path]``; este script recibe esa config TOML de la
app (`write_config`: source_image_dir, output_dir, output_name, rank, epochs,
lr, resolution, batch_size, gradient_checkpointing, optimizer), la traduce a:

- un dataset TOML al estilo sd-scripts (``[[datasets.subsets]]`` con
  ``image_dir`` = ``<source_image_dir>/img`` y ``caption_extension=".txt"``);
- la linea de argumentos de ``anima_train_network.py`` con
  ``--network_module networks.lora_anima`` y los pesos base/encoder/VAE;

y lanza el entrenamiento con el python de su propio venv (``sys.executable``),
con cwd en el checkout de sd-scripts. Todo el mapeo es stdlib puro y testeable
offline; ``--dry-run`` imprime el comando sin ejecutarlo.

Variables opcionales: ``WAIFU_TRAIN_BASE``, ``WAIFU_TRAIN_QWEN3``,
``WAIFU_TRAIN_VAE`` (rutas de pesos; si faltan se derivan de
``WAIFU_COMFY_ROOT`` o de ``<repo>/ComfyUI``), ``WAIFU_TRAIN_RESOLUTION`` no se
usa (manda la config de la app).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

KOHYA_DIR = Path(__file__).resolve().parent
REPO_ROOT = KOHYA_DIR.parents[1]
SD_SCRIPTS_DIR = KOHYA_DIR / "sd-scripts"
TRAIN_SCRIPT = "anima_train_network.py"
NETWORK_MODULE = "networks.lora_anima"
SAVE_MODEL_AS = "safetensors"
MIXED_PRECISION = "bf16"

DEFAULT_BASE = Path("models") / "diffusion_models" / "anima_aestheticV11.safetensors"
DEFAULT_QWEN3 = Path("models") / "text_encoders" / "qwen_3_06b_base.safetensors"
DEFAULT_VAE = Path("models") / "vae" / "qwen_image_vae.safetensors"

CONFIG_KEYS = (
    "source_image_dir",
    "output_dir",
    "output_name",
    "rank",
    "epochs",
    "lr",
    "resolution",
    "batch_size",
    "gradient_checkpointing",
    "optimizer",
)


def _parse_value(raw: str) -> Any:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1]
    if len(text) >= 2 and text[0] == text[-1] == '"':
        body = text[1:-1]
        return body.replace("\\\\", "\\").replace('\\"', '"')
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_app_config(text: str) -> dict[str, Any]:
    """Config TOML de la app -> dict; ignora comentarios y claves desconocidas."""
    config: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        key = key.strip()
        if key not in CONFIG_KEYS:
            continue
        config[key] = _parse_value(raw)
    missing = [
        key
        for key in ("source_image_dir", "output_dir", "output_name", "rank", "epochs", "lr")
        if key not in config
    ]
    if missing:
        raise ValueError(f"config de la app incompleta: faltan {missing}")
    return config


def _toml_str(value: Any) -> str:
    """String TOML literal (comillas simples, o dobles si el valor las lleva)."""
    text = str(value)
    if "'" in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"'{text}'"


def build_dataset_toml(config: Mapping[str, Any]) -> str:
    """Dataset TOML para sd-scripts a partir de la config de la app."""
    dataset_dir = Path(str(config["source_image_dir"]))
    image_dir = dataset_dir / "img"
    resolution = int(config.get("resolution", 512))
    batch_size = int(config.get("batch_size", 1))
    lines = [
        "[general]",
        "enable_bucket = true",
        "bucket_no_upscale = false",
        "",
        "[[datasets]]",
        f"batch_size = {batch_size}",
        "",
        "[[datasets.subsets]]",
        f"image_dir = {_toml_str(image_dir)}",
        "caption_extension = '.txt'",
        "num_repeats = 1",
        f"resolution = {resolution}",
        "",
    ]
    return "\n".join(lines)


def resolve_weights(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Rutas de base/encoder/VAE con overrides por entorno (sin tocar nada)."""
    source = env if env is not None else os.environ
    comfy_root = Path(source.get("WAIFU_COMFY_ROOT") or (REPO_ROOT / "ComfyUI"))
    overrides = {
        "base_model": source.get("WAIFU_TRAIN_BASE"),
        "qwen3": source.get("WAIFU_TRAIN_QWEN3"),
        "vae": source.get("WAIFU_TRAIN_VAE"),
    }
    defaults = {
        "base_model": comfy_root / DEFAULT_BASE,
        "qwen3": comfy_root / DEFAULT_QWEN3,
        "vae": comfy_root / DEFAULT_VAE,
    }
    return {
        key: str(overrides[key]) if overrides[key] else str(defaults[key])
        for key in defaults
    }


def build_train_args(
    config: Mapping[str, Any],
    *,
    dataset_config: str | Path,
    weights: Mapping[str, str],
) -> list[str]:
    """Argumentos de ``anima_train_network.py`` para la config de la app."""
    args = [
        "--pretrained_model_name_or_path",
        str(weights["base_model"]),
        "--qwen3",
        str(weights["qwen3"]),
        "--vae",
        str(weights["vae"]),
        "--dataset_config",
        str(dataset_config),
        "--output_dir",
        str(config["output_dir"]),
        "--output_name",
        str(config["output_name"]),
        "--save_model_as",
        SAVE_MODEL_AS,
        "--network_module",
        NETWORK_MODULE,
        "--network_dim",
        str(int(config["rank"])),
        "--network_alpha",
        str(int(config["rank"])),
        "--learning_rate",
        f"{float(config['lr']):g}",
        "--max_train_epochs",
        str(int(config["epochs"])),
        "--optimizer_type",
        str(config.get("optimizer", "AdamW8bit")),
        "--mixed_precision",
        MIXED_PRECISION,
        "--cache_latents",
        "--max_data_loader_n_workers",
        "0",
        "--seed",
        "0",
    ]
    if config.get("gradient_checkpointing"):
        args.append("--gradient_checkpointing")
    return args


def build_job(
    config_path: str | Path, *, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Plan completo (sin ejecutar): config, dataset TOML y argv del entrenador."""
    config_path = Path(config_path)
    config = parse_app_config(config_path.read_text(encoding="utf-8"))
    dataset_config = Path(str(config["output_dir"])) / "train_dataset.toml"
    weights = resolve_weights(env)
    dataset_toml = build_dataset_toml(config)
    argv = [
        sys.executable,
        str(SD_SCRIPTS_DIR / TRAIN_SCRIPT),
        *build_train_args(config, dataset_config=dataset_config, weights=weights),
    ]
    return {
        "config": config,
        "config_path": str(config_path),
        "dataset_config": str(dataset_config),
        "dataset_toml": dataset_toml,
        "argv": argv,
        "weights": weights,
    }


def run(
    config_path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    dry_run: bool = False,
) -> int:
    """Ejecuta el plan; devuelve el exit code (0 en dry-run)."""
    script = SD_SCRIPTS_DIR / TRAIN_SCRIPT
    if not script.is_file():
        raise FileNotFoundError(f"checkout de sd-scripts no encontrado: {script}")
    job = build_job(config_path, env=env)
    dataset_config = Path(job["dataset_config"])
    dataset_config.parent.mkdir(parents=True, exist_ok=True)
    dataset_config.write_text(job["dataset_toml"], encoding="utf-8")
    if dry_run:
        print(" ".join(f'"{part}"' if " " in part else part for part in job["argv"]))
        return 0
    completed = runner(job["argv"], cwd=str(SD_SCRIPTS_DIR), env=dict(os.environ))
    return int(getattr(completed, "returncode", completed))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in args
    args = [arg for arg in args if arg != "--dry-run"]
    if len(args) != 1:
        print(
            "uso: run_waifu_train.py <train_config.toml> [--dry-run]",
            file=sys.stderr,
        )
        return 2
    if not SD_SCRIPTS_DIR.is_dir():
        print(f"checkout de sd-scripts no encontrado: {SD_SCRIPTS_DIR}", file=sys.stderr)
        return 2
    return run(args[0], dry_run=dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
