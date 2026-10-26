"""Aceptacion persistida de la licencia de Qwen-Image 2.1 (research)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LICENSE_VERSION = "qwen-image-2.1-research"
LICENSE_NAME = "Qwen-Image 2.1 (qwen-research)"
LICENSE_FILE = "editor-license.json"


def license_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / LICENSE_FILE


def license_info(data_dir: str | Path) -> dict[str, Any]:
    """Estado persistido; accepted solo si la version coincide."""
    path = license_path(data_dir)
    accepted = False
    accepted_at = ""
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            accepted = (
                data.get("accepted") is True
                and data.get("version") == LICENSE_VERSION
            )
            accepted_at = str(data.get("accepted_at") or "")
        except (OSError, ValueError, AttributeError):
            accepted = False
    return {
        "name": LICENSE_NAME,
        "version": LICENSE_VERSION,
        "accepted": accepted,
        "accepted_at": accepted_at,
        "required": True,
    }


def accept_license(data_dir: str | Path) -> dict[str, Any]:
    path = license_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    accepted_at = datetime.now(timezone.utc).isoformat()
    path.write_text(
        json.dumps(
            {
                "accepted": True,
                "version": LICENSE_VERSION,
                "accepted_at": accepted_at,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return license_info(data_dir)


__all__ = [
    "LICENSE_FILE",
    "LICENSE_NAME",
    "LICENSE_VERSION",
    "accept_license",
    "license_info",
    "license_path",
]
