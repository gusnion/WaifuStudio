"""Chequeo de primera ejecución: qué falta para generar la primera imagen."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.config import APP_ROOT, EngineConfig
from app.video import find_ffmpeg

ENGINE_TIMEOUT = 8.0


def _check(label: str, ok: bool, detail: str, required: bool = True) -> dict[str, Any]:
    return {"label": label, "ok": bool(ok), "detail": detail, "required": required}


def _engine_check(cfg: EngineConfig) -> dict[str, Any]:
    endpoint = cfg.comfy_url.rstrip("/") + "/system_stats"
    try:
        with urllib.request.urlopen(endpoint, timeout=ENGINE_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        version = str((data.get("system") or {}).get("comfyui_version") or "?")
        return _check("Motor ComfyUI", True, f"responde; versión {version}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return _check("Motor ComfyUI", False, f"no responde en {cfg.comfy_url}: {exc}")


def _models_check(cfg: EngineConfig) -> dict[str, Any]:
    root = Path(cfg.comfy_root) / "models"
    expected = (
        "checkpoints/animagine-xl-4.0-opt.safetensors",
        "checkpoints/realvisxlV50_v50Bakedvae_full_fp16.safetensors",
        "checkpoints/juggernautXL_ragnarok.safetensors",
    )
    missing = [name for name in expected if not (root / name).is_file()]
    if missing:
        return _check(
            "Modelos de imagen",
            False,
            "faltan: " + ", ".join(missing),
        )
    return _check("Modelos de imagen", True, "los 3 checkpoints del set están presentes")


def _ffmpeg_check() -> dict[str, Any]:
    path = find_ffmpeg()
    if path:
        return _check("FFmpeg", True, str(path))
    return _check(
        "FFmpeg",
        False,
        "no encontrado; Timeline/export no disponible (install.bat --SkipFfmpeg)",
        required=False,
    )


def _vram_check() -> dict[str, Any]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return _check("VRAM", False, "nvidia-smi no disponible", required=False)
    try:
        result = subprocess.run(
            [exe, "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        gpus = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue
            try:
                gpus.append((int(parts[-1]), parts[-2], int(parts[0])))
            except ValueError:
                continue
        if not gpus:
            raise ValueError("nvidia-smi no devolvio GPUs")
        mib, name, _index = max(gpus)
        return _check("VRAM", mib >= 8192, f"{name}: {mib} MiB detectados")
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
        return _check("VRAM", False, f"no se pudo leer: {exc}", required=False)


def first_run_report(cfg: EngineConfig) -> dict[str, Any]:
    items = [
        _engine_check(cfg),
        _models_check(cfg),
        _ffmpeg_check(),
        _vram_check(),
    ]
    missing = [item for item in items if item["required"] and not item["ok"]]
    return {
        "ready": not missing,
        "items": items,
        "missing": [item["label"] for item in missing],
        "app_root": str(APP_ROOT),
    }


__all__ = ["first_run_report"]
