"""Gestor de catálogo, descarga e índices de poses (C51-08)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any
import urllib.request

from app.engine import EngineError

CATALOG_PATH = Path(__file__).resolve().parents[1] / "registry" / "pose-catalog-v1.json"
TAGS_PATH = Path(__file__).resolve().parents[1] / "registry" / "pose-tags-v1.json"


class PoseError(EngineError, ValueError):
    """Error al cargar catálogo o descargar poses."""


def load_pose_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Lee el catálogo de poses desde registry/pose-catalog-v1.json."""
    target = Path(path) if path is not None else CATALOG_PATH
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PoseError(f"Catalogo de poses ilegible {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise PoseError(f"Catalogo de poses debe ser un objeto: {target}")
    return data


def _resolve_index_path(data_dir: str | Path) -> Path:
    p = Path(data_dir)
    if p.is_file():
        return p
    if p.name == "poses":
        return p / "poses-index.json"
    return p / "poses" / "poses-index.json"


def pose_status(data_dir: str | Path) -> dict[str, Any]:
    """Devuelve el estado de poses: installed, count, version, bytes, url."""
    catalog = load_pose_catalog()
    target = _resolve_index_path(data_dir)
    installed = target.is_file()

    count = int(catalog.get("count", 0))
    version = str(catalog.get("version", ""))
    bytes_count = int(catalog.get("bytes", 0))
    url = str(catalog.get("url", ""))

    if installed:
        try:
            items = load_pose_index(data_dir)
            if isinstance(items, list):
                count = len(items)
            bytes_count = target.stat().st_size
        except Exception:
            pass

    return {
        "installed": installed,
        "count": count,
        "version": version,
        "bytes": bytes_count,
        "url": url,
    }


def download_pose_index(
    data_dir: str | Path,
    *,
    catalog_path: str | Path | None = None,
    timeout: float = 60.0,
) -> Path:
    """Descarga el índice de poses con urllib, verifica sha256 y bytes, y escribe de forma atómica."""
    catalog = load_pose_catalog(catalog_path)
    url = catalog.get("url")
    if not url or not isinstance(url, str):
        raise PoseError("URL de catálogo no disponible")

    expected_bytes = catalog.get("bytes")
    expected_sha256 = catalog.get("sha256")

    target = _resolve_index_path(data_dir)
    poses_dir = target.parent

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "WaifuStudio/2.5.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
    except Exception as exc:
        raise PoseError(f"Error al descargar indice de poses desde {url}: {exc}") from exc

    if expected_bytes is not None and len(content) != int(expected_bytes):
        raise PoseError(
            f"Tamano no coincide: esperado {expected_bytes} bytes, recibido {len(content)} bytes"
        )

    digest = hashlib.sha256(content).hexdigest().lower()
    if expected_sha256 and digest != str(expected_sha256).lower():
        raise PoseError(
            f"SHA256 no coincide: esperado {expected_sha256}, calculado {digest}"
        )

    poses_dir.mkdir(parents=True, exist_ok=True)
    temp_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=poses_dir, delete=False, prefix="poses_", suffix=".tmp") as f:
            temp_file = Path(f.name)
            f.write(content)
        temp_file.replace(target)
    finally:
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass

    return target


def load_pose_index(data_dir: str | Path) -> list[dict[str, Any]]:
    """Devuelve la lista items completa del índice de poses."""
    target = _resolve_index_path(data_dir)
    if not target.is_file():
        return []

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PoseError(f"Indice de poses ilegible {target}: {exc}") from exc

    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
        return []
    if isinstance(data, list):
        return data
    return []


def load_pose_tags(path: str | Path | None = None) -> dict[str, Any]:
    """Lee registry/pose-tags-v1.json."""
    target = Path(path) if path is not None else TAGS_PATH
    if not target.is_file():
        return {"classes": {}, "angles": {}}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PoseError(f"Catalogo de tags de pose ilegible {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise PoseError(f"Catalogo de tags de pose debe ser un objeto: {target}")
    return data


def build_pose_tags(
    clase_es: str | None = None,
    angulo_es: str | None = None,
    *,
    tags_data: dict[str, Any] | None = None,
) -> list[str]:
    """Combina tags de clase y ángulo sin duplicar y devuelve la lista."""
    data = tags_data if tags_data is not None else load_pose_tags()
    classes = data.get("classes") if isinstance(data, dict) else {}
    angles = data.get("angles") if isinstance(data, dict) else {}

    class_tags: list[str] = []
    if clase_es and isinstance(classes, dict):
        class_tags = classes.get(clase_es) or classes.get(clase_es.strip()) or []

    angle_tags: list[str] = []
    if angulo_es and isinstance(angles, dict):
        angle_tags = angles.get(angulo_es) or angles.get(angulo_es.strip()) or []

    combined: list[str] = []
    seen: set[str] = set()

    for tag in list(class_tags) + list(angle_tags):
        if not tag or not isinstance(tag, str):
            continue
        cleaned = tag.strip()
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            combined.append(cleaned)

    return combined


__all__ = [
    "CATALOG_PATH",
    "PoseError",
    "TAGS_PATH",
    "build_pose_tags",
    "download_pose_index",
    "load_pose_catalog",
    "load_pose_index",
    "load_pose_tags",
    "pose_status",
]
