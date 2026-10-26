"""Gestor local de addons: importar, validar, activar y desactivar."""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from app.engine import EngineError
from app import __version__

ADDONS_DIRNAME = "addons"
MANIFEST_NAME = "addon.json"
STATE_NAME = "state.json"
MAX_ZIP_BYTES = 64 * 1024 * 1024
ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")
SLOTS = ("image", "editor", "video", "upscaler", "timeline", "gallery")


def addons_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / ADDONS_DIRNAME


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"addon.json ilegible: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError("addon.json debe ser un objeto")
    addon_id = data.get("id")
    if not isinstance(addon_id, str) or ID_RE.fullmatch(addon_id) is None:
        raise EngineError("id de addon invalido")
    for field in ("name", "version", "requires_core"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EngineError(f"campo obligatorio del addon: {field}")
    slots = data.get("slots", [])
    if not isinstance(slots, list) or any(slot not in SLOTS for slot in slots):
        raise EngineError(f"slots invalidos; permitidos: {', '.join(SLOTS)}")
    if len(set(slots)) != len(slots):
        raise EngineError("slots duplicados")
    return data


def _compatible(requires: str, core: str = __version__) -> bool:
    """Soporta `2.x`, `>=2.0`, `>=2.0,<3.0` y `*`."""
    spec = requires.strip()
    if spec in ("*", "", core):
        return True
    if spec.endswith(".x"):
        return core.split(".", 1)[0] == spec[:-2]
    match = re.fullmatch(r">=\s*([0-9.]+)(?:,<\s*([0-9.]+))?", spec)
    if not match:
        return False
    lower = tuple(int(part) for part in match.group(1).split("."))
    current = tuple(int(part) for part in core.split("."))
    if current < lower:
        return False
    if match.group(2):
        upper = tuple(int(part) for part in match.group(2).split("."))
        if current >= upper:
            return False
    return True


def _state_path(path: Path) -> Path:
    return path / STATE_NAME


def _read_state(path: Path) -> dict[str, Any]:
    state_path = _state_path(path)
    if not state_path.is_file():
        return {"enabled": False}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"enabled": False}
    return {"enabled": bool(data.get("enabled", False))}


def _write_state(path: Path, enabled: bool) -> None:
    _state_path(path).write_text(
        json.dumps({"enabled": bool(enabled)}, indent=2) + "\n", encoding="utf-8"
    )


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise EngineError(f"ruta insegura en el ZIP: {info.filename!r}")
        destination = (target / name).resolve()
        if target.resolve() not in destination.parents and destination != target.resolve():
            raise EngineError(f"ruta fuera del addon: {info.filename!r}")
        if info.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


def list_addons(data_dir: str | Path) -> list[dict[str, Any]]:
    root = addons_root(data_dir)
    if not root.is_dir():
        return []
    result = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        try:
            manifest = _read_manifest(path / MANIFEST_NAME)
        except EngineError as exc:
            result.append(
                {
                    "id": path.name,
                    "enabled": False,
                    "valid": False,
                    "reason": str(exc),
                }
            )
            continue
        state = _read_state(path)
        compatible = _compatible(manifest["requires_core"])
        result.append(
            {
                "id": manifest["id"],
                "name": manifest["name"],
                "version": manifest["version"],
                "requires_core": manifest["requires_core"],
                "slots": manifest.get("slots", []),
                "description": str(manifest.get("description", "")),
                "enabled": state["enabled"],
                "valid": compatible,
                "reason": "" if compatible else "requires_core incompatible",
            }
        )
    return result


def import_addon(data_dir: str | Path, raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_ZIP_BYTES:
        raise EngineError("ZIP vacio o demasiado grande")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise EngineError("el archivo no es un ZIP valido") from exc
    with archive:
        names = {info.filename.replace("\\", "/") for info in archive.infolist()}
        if MANIFEST_NAME not in names:
            raise EngineError("el ZIP no contiene addon.json en la raiz")
        with archive.open(MANIFEST_NAME) as handle:
            try:
                manifest_data = json.loads(handle.read().decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise EngineError("addon.json invalido") from exc
        if not isinstance(manifest_data, dict):
            raise EngineError("addon.json debe ser un objeto")
        addon_id = manifest_data.get("id")
        if not isinstance(addon_id, str) or ID_RE.fullmatch(addon_id) is None:
            raise EngineError("id de addon invalido")
        destination = addons_root(data_dir) / addon_id
        if destination.exists():
            raise EngineError(f"el addon ya existe: {addon_id}")
        with tempfile.TemporaryDirectory(dir=addons_root(data_dir) if addons_root(data_dir).is_dir() else None) as tmp:
            staging = Path(tmp)
            _safe_extract(archive, staging)
            _read_manifest(staging / MANIFEST_NAME)
            addons_root(data_dir).mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging), str(destination))
        _write_state(destination, False)
        manifest = _read_manifest(destination / MANIFEST_NAME)
    return {
        "id": manifest["id"],
        "name": manifest["name"],
        "version": manifest["version"],
        "enabled": False,
        "valid": _compatible(manifest["requires_core"]),
    }


def import_catalog(data_dir: str | Path, payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EngineError("catalogo invalido; usar objeto JSON")
    if payload.get("schema") not in ("waifu.addons-catalog/v1", None):
        raise EngineError("schema de catalogo no soportado")
    requires = payload.get("requires_core")
    if not isinstance(requires, str) or not _compatible(requires):
        raise EngineError(f"catalogo incompatible con core {__version__}")
    entries = payload.get("addons")
    if not isinstance(entries, list):
        raise EngineError("addons debe ser una lista")
    accepted = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise EngineError("entrada de catalogo invalida")
        addon_id = entry.get("id")
        if not isinstance(addon_id, str) or ID_RE.fullmatch(addon_id) is None:
            raise EngineError("id de addon invalido en catalogo")
        slots = entry.get("slots", [])
        if not isinstance(slots, list) or any(slot not in SLOTS for slot in slots):
            raise EngineError(f"slots invalidos en {addon_id}")
        url = entry.get("url")
        if url is not None and (not isinstance(url, str) or not url.startswith(("https://", "http://"))):
            raise EngineError(f"url invalida en {addon_id}")
        accepted.append(
            {
                "id": addon_id,
                "name": str(entry.get("name") or addon_id),
                "version": str(entry.get("version") or "0"),
                "requires_core": str(entry.get("requires_core") or requires),
                "slots": slots,
                "url": url or "",
            }
        )
    root = addons_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "catalog.json").write_text(
        json.dumps({"schema": "waifu.addons-catalog/v1", "requires_core": requires, "addons": accepted}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return {"accepted": accepted, "count": len(accepted)}


def set_addon_enabled(data_dir: str | Path, addon_id: str, enabled: bool) -> dict[str, Any]:
    path = addons_root(data_dir) / addon_id
    if not path.is_dir():
        raise EngineError(f"addon no instalado: {addon_id}")
    manifest = _read_manifest(path / MANIFEST_NAME)
    if enabled and not _compatible(manifest["requires_core"]):
        raise EngineError("requires_core incompatible con esta version")
    if enabled:
        own_slots = set(manifest.get("slots", []))
        for other in list_addons(data_dir):
            if other["id"] == addon_id or not other.get("enabled"):
                continue
            shared = own_slots & set(other.get("slots", []))
            if shared:
                raise EngineError(
                    f"slot ocupado por {other['id']}: {', '.join(sorted(shared))}"
                )
    _write_state(path, enabled)
    return {"id": addon_id, "enabled": bool(enabled)}


__all__ = [
    "ADDONS_DIRNAME",
    "addons_root",
    "import_addon",
    "list_addons",
    "set_addon_enabled",
]
