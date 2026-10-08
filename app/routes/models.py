"""Rutas de modelos base y catálogo de LoRAs (/api/models, /api/loras).

Gestiona la consulta de modelos disponibles, altas, edición, subida y borrado de LoRAs.
Depende de app.registry.ModelRegistry y app.loras.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
import re
import sys
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.engine import EngineError
from app.loras import (
    add_entry as add_lora,
    delete_entry as delete_lora,
    families as lora_families,
    get as get_lora,
    inspect_safetensors,
    list_loras,
    safetensors_header,
    update_entry as update_lora,
)


from app import loras as _loras_module


def _call_add_lora(entry: dict) -> dict:
    server = sys.modules.get("app.server")
    server_fn = getattr(server, "add_lora", None) if server is not None else None
    if callable(server_fn) and server_fn is not _loras_module.add_entry:
        return server_fn(entry)
    models_mod = sys.modules.get("app.routes.models")
    models_fn = getattr(models_mod, "add_lora", None) if models_mod is not None else None
    if callable(models_fn) and models_fn is not _loras_module.add_entry:
        return models_fn(entry)
    return _loras_module.add_entry(entry)



LORA_UPLOAD_MAX_BYTES = int(2.5 * 1024 * 1024 * 1024)
_LORA_FAMILY_RE = re.compile(r"[a-z0-9._-]+")
_LORA_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def lora_file_path(comfy_root: Any, relative: object) -> Path:
    """Resuelve ``file`` de una LoRA dentro de ``models/loras`` (M10-5b).

    ``relative`` debe ser texto no vacio y quedarse dentro de la raiz (nada de
    absolutos ni ``..``); el fichero debe existir. EngineError (400) en caso
    contrario. No escanea el directorio: solo confina y comprueba existencia.
    """
    if not isinstance(relative, str) or not relative.strip():
        raise EngineError(f"file de lora requerido (recibido {relative!r})")
    if Path(relative).is_absolute():
        raise EngineError(
            f"file de lora debe ser relativo a models/loras: {relative!r}"
        )
    root = (Path(comfy_root) / "models" / "loras").resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise EngineError(f"ruta de lora fuera de models/loras: {relative!r}")
    if not candidate.is_file():
        raise EngineError(f"archivo de lora no encontrado: {relative!r}")
    return candidate


def _lora_slug(text: str) -> str:
    """Slug de id para un stem: minusculas, resto a ``-`` y recortado."""
    return _LORA_SLUG_RE.sub("-", text.lower()).strip("-") or "lora"


def _require_lora_filename(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"filename requerido (recibido {value!r})")
    if "/" in value or "\\" in value or "\x00" in value:
        raise EngineError(f"filename debe ser un nombre sin rutas: {value!r}")
    if (
        value in (".", "..")
        or not value.lower().endswith(".safetensors")
        or value.lower() == ".safetensors"
    ):
        raise EngineError(f"filename debe terminar en .safetensors: {value!r}")
    return value


def _require_lora_family(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(f"family requerida (recibido {value!r})")
    if _LORA_FAMILY_RE.fullmatch(value) is None or value in (".", ".."):
        raise EngineError(f"family invalida: {value!r} (solo [a-z0-9._-]+)")
    return value


def _decode_lora_b64(value: object) -> bytes:
    """Decodifica ``file_b64`` (data URI opcional) con limite de tamaño."""
    if not isinstance(value, str) or not value.strip():
        raise EngineError("file_b64 requerido (base64 del .safetensors)")
    text = "".join(value.split())
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    if len(text) > (LORA_UPLOAD_MAX_BYTES * 4) // 3 + 16:
        raise EngineError(
            f"archivo demasiado grande (max {LORA_UPLOAD_MAX_BYTES} bytes)"
        )
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EngineError(f"file_b64 no es base64 valido: {exc}") from exc
    if not raw:
        raise EngineError("file_b64 decodifica vacio")
    if len(raw) > LORA_UPLOAD_MAX_BYTES:
        raise EngineError(
            f"archivo demasiado grande: {len(raw)} bytes "
            f"(max {LORA_UPLOAD_MAX_BYTES})"
        )
    return raw


def _lora_upload_target(comfy_root: Any, family: str, filename: str) -> Path:
    root = (Path(comfy_root) / "models" / "loras").resolve()
    target = (root / family / filename).resolve()
    if not target.is_relative_to(root):
        raise EngineError(f"destino de lora fuera de models/loras: {family}/{filename}")
    return target


def _lora_upload_notes(inferred: dict) -> str:
    parts: list[str] = []
    dim = inferred["dim"]
    alpha = inferred["alpha"]
    if dim is not None and alpha is not None:
        parts.append(f"dim {dim} / alpha {alpha}")
    elif dim is not None:
        parts.append(f"dim {dim}")
    elif alpha is not None:
        parts.append(f"alpha {alpha}")
    if inferred["base"]:
        parts.append(f"base {inferred['base']}")
    parts.append("trigger inferido del safetensors (editable)")
    return "; ".join(parts)


def _lora_catalog() -> dict:
    return {"items": list_loras(), "families": lora_families()}


router = APIRouter()


@router.get("/api/models")
async def api_models(request: Request) -> list[dict]:
    reg = request.app.state.registry
    return [
        {
            "id": entry.id,
            "display_name": entry.display_name,
            "family": entry.family,
            "preprompt": entry.preprompt,
            "unet_name": entry.profile.unet_name,
            "defaults": dict(entry.defaults),
        }
        for entry in reg.models
    ]


@router.get("/api/loras")
async def api_loras(family: str | None = None) -> dict:
    return {"items": list_loras(family), "families": lora_families()}


@router.post("/api/loras")
async def api_loras_add(request: Request, payload: dict = Body(...)) -> Any:
    """Crea una entrada: id unico, fichero existente y confinado (M10-5b)."""
    cfg = request.app.state.config
    lora_id = payload.get("id")
    if any(item["id"] == lora_id for item in list_loras()):
        return JSONResponse(
            status_code=409, content={"error": f"id duplicado: {lora_id!r}"}
        )
    lora_file_path(cfg.comfy_root, payload.get("file"))
    item = _call_add_lora(payload)
    return {"item": item, **_lora_catalog()}


@router.post("/api/loras/upload")
async def api_loras_upload(request: Request, payload: dict = Body(...)) -> Any:
    """Copia un .safetensors a models/loras y lo registra (M10-5c)."""
    cfg = request.app.state.config
    filename = _require_lora_filename(payload.get("filename"))
    family = _require_lora_family(payload.get("family"))
    raw = _decode_lora_b64(payload.get("file_b64"))
    if safetensors_header(raw) is None:
        raise EngineError("cabecera safetensors invalida")
    target = _lora_upload_target(cfg.comfy_root, family, filename)
    relative = f"{family}/{filename}"
    if target.exists():
        return JSONResponse(
            status_code=409,
            content={"error": f"ya existe ese archivo en loras/{relative}"},
        )
    inferred = inspect_safetensors(raw)
    title = inferred["title"].strip()
    display_name = payload.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = title or filename[: -len(".safetensors")]
    else:
        display_name = display_name.strip()
    trigger = payload.get("trigger")
    if not isinstance(trigger, str) or not trigger.strip():
        trigger = inferred["trigger"]
    else:
        trigger = trigger.strip()
    stem = filename[: -len(".safetensors")]
    existing = {item["id"] for item in list_loras()}
    lora_id = _lora_slug(stem)
    if lora_id in existing:
        suffix = 2
        while f"{lora_id}-{suffix}" in existing:
            suffix += 1
        lora_id = f"{lora_id}-{suffix}"
    entry = {
        "id": lora_id,
        "family": family,
        "file": f"{family}\\{filename}",
        "display_name": display_name,
        "trigger": trigger,
        "default_weight": 1.0,
        "source": "subido desde la app",
        "license": "no verificada (archivo del usuario)",
        "notes": _lora_upload_notes(inferred),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    except OSError as exc:
        raise EngineError(
            f"no se pudo copiar el archivo a models/loras: {exc}"
        ) from exc
    try:
        item = _call_add_lora(entry)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {
        "item": item,
        "file": entry["file"],
        "trigger_inferido": inferred["trigger"],
    }


@router.put("/api/loras/{lora_id}")
async def api_loras_update(
    request: Request, lora_id: str, payload: dict = Body(...)
) -> Any:
    """Edita una entrada existente; el id es inmutable (M10-5b)."""
    cfg = request.app.state.config
    try:
        get_lora(lora_id)
    except EngineError:
        return JSONResponse(
            status_code=404, content={"error": f"lora no registrado: {lora_id!r}"}
        )
    if "id" in payload and payload["id"] != lora_id:
        return JSONResponse(
            status_code=400, content={"error": f"id inmutable: {lora_id!r}"}
        )
    if "file" in payload:
        lora_file_path(cfg.comfy_root, payload.get("file"))
    item = update_lora(lora_id, payload)
    return {"item": item, **_lora_catalog()}


@router.delete("/api/loras/{lora_id}")
async def api_loras_delete(
    request: Request, lora_id: str, file: bool = False
) -> Any:
    """Quita la entrada; con ``file=1`` borra ademas el .safetensors (M10-5c)."""
    cfg = request.app.state.config
    try:
        entry = get_lora(lora_id)
    except EngineError:
        return JSONResponse(
            status_code=404, content={"error": f"lora no registrado: {lora_id!r}"}
        )
    file_removed = False
    if file:
        root = (Path(cfg.comfy_root) / "models" / "loras").resolve()
        target = (root / entry["file"]).resolve()
        if not target.is_relative_to(root):
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"ruta de lora fuera de models/loras: {entry['file']!r}"
                },
            )
        if target.is_file():
            try:
                target.unlink()
            except OSError as exc:
                raise EngineError(
                    f"no se pudo borrar el archivo de lora: {exc}"
                ) from exc
            file_removed = True
    item = delete_lora(lora_id)
    return {
        "deleted": item["id"],
        "file_removed": file_removed,
        **_lora_catalog(),
    }
