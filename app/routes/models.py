"""Rutas de catálogo de modelos y LoRAs (/api/models, /api/loras).

Qué hace: gestiona la consulta de modelos disponibles, altas, edición y catálogo de LoRAs.
Qué no hace: no realiza inferencia ni carga pesos directamente en memoria GPU.
Dependencias: app.registry.ModelRegistry y app.loras.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import replace
from pathlib import Path
import re
import shutil
import struct
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
from app.registry import (
    DEFAULT_SUBFAMILY,
    KNOWN_SUBFAMILIES,
    PROMPT_PROFILES,
    PROMPT_PROFILE_INFO,
    ModelEntry,
    ModelProfile,
    ModelRegistry,
    infer_prompt_profile,
    infer_subfamily,
    prompt_profile_info,
)
from app.params import SAMPLER_NAMES, SCHEDULER_NAMES
from app.preprompts import default_preprompt_for_profile

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
_MAX_HEADER_READ_BYTES = 32 * 1024 * 1024
_GENERIC_BOORU_TAGS = frozenset({
    "1girl", "1boy", "solo", "anime screencap", "anime coloring", "portrait",
    "long hair", "short hair", "blonde hair", "brown hair", "black hair",
    "pink hair", "blue hair", "blue eyes", "red eyes", "brown eyes",
    "looking at viewer", "smile", "blush", "blushing", "open mouth",
    "simple background", "white background", "upper body", "cowboy shot",
    "full body", "breasts", "large breasts", "medium breasts", "small breasts",
    "shirt", "white shirt", "skirt", "dress", "black dress", "school uniform",
    "cosplay", "frills", "indoor", "outdoor", "day", "night", "highres",
    "absurdres", "long eyelashes", "messy hair", "bangs", "closed eyes",
})


def classify_safetensors_file(path: Path) -> tuple[str, bytes]:
    """Clasifica un .safetensors leyendo solo su cabecera JSON (<1ms, sin RAM/GPU).

    Devuelve ``(kind, raw_header)`` donde ``kind`` es uno de:
    ``"lora"``, ``"checkpoint"``, ``"anima_unet"``, ``"video_model"``,
    ``"unknown"`` o ``"invalid"``.
    """
    try:
        with path.open("rb") as handle:
            raw8 = handle.read(8)
            if len(raw8) < 8:
                return "invalid", b""
            (hlen,) = struct.unpack("<Q", raw8)
            if hlen == 0 or hlen > _MAX_HEADER_READ_BYTES:
                return "invalid", b""
            body = handle.read(hlen)
            if len(body) < hlen:
                return "invalid", b""
            raw_header = raw8 + body
    except OSError:
        return "invalid", b""

    header = safetensors_header(raw_header)
    if header is None:
        return "invalid", b""
    keys = [k for k in header.keys() if k != "__metadata__"]
    if not keys:
        return "unknown", raw_header

    lora_markers = (
        ".lora_down", ".lora_up", ".lora_A.", ".lora_B.",
        "lora_unet", "lora_te", "hada_w", "lokr_w",
    )
    if any(
        any(m in k for m in lora_markers) or k.endswith(".alpha")
        for k in keys
    ):
        return "lora", raw_header

    if any(
        k.startswith(("audio_patch_proj.", "adaln_t_table", "patch_embedding.", "time_projection."))
        for k in keys
    ):
        return "video_model", raw_header

    has_diff = any(k.startswith("model.diffusion_model.") for k in keys)
    has_ckpt_aux = any(
        k.startswith(("first_stage_model.", "conditioner.", "cond_stage_model."))
        for k in keys
    )
    if has_diff and has_ckpt_aux:
        return "checkpoint", raw_header

    if any(
        k.startswith(("net.blocks.", "model.diffusion_model.blocks.", "diffusion_model.blocks."))
        for k in keys
    ):
        return "anima_unet", raw_header

    return "unknown", raw_header


def _clean_fallback_trigger(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    stripped = re.sub(
        r"(?:\s+[-_|]?\s*(?:style|lora|sdxl|xl|illustrious|illu|noobai|anima|v\d+(?:\.\d+)?))+$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return stripped or cleaned


def _smart_infer_trigger(raw_header: bytes, fallback_trigger: str, stem: str = "") -> str:
    """Extrae el trigger de personaje/estilo ignorando tags genericos de booru."""
    clean_fb = _clean_fallback_trigger(fallback_trigger)
    header = safetensors_header(raw_header)
    if not isinstance(header, dict):
        return clean_fb
    meta = header.get("__metadata__")
    if not isinstance(meta, dict):
        return clean_fb
    raw_freq = meta.get("ss_tag_frequency")
    if not isinstance(raw_freq, str) or not raw_freq.strip():
        return clean_fb
    try:
        data = json.loads(raw_freq)
    except ValueError:
        return clean_fb
    if not isinstance(data, dict):
        return clean_fb
    counts: dict[str, int] = {}
    for ds in data.values():
        if not isinstance(ds, dict):
            continue
        for tag, cnt in ds.items():
            if not isinstance(tag, str):
                continue
            try:
                val = int(str(cnt).strip())
            except ValueError:
                continue
            norm = " ".join(tag.split())
            if not norm:
                continue
            if norm.lower().replace("_", " ") in _GENERIC_BOORU_TAGS:
                continue
            counts[norm] = counts.get(norm, 0) + val
    if counts:
        stem_tokens = [
            tok for tok in re.split(r"[^a-z0-9]+", stem.lower()) if len(tok) >= 4
        ]
        if stem_tokens:
            stem_matches = {
                tag: cnt
                for tag, cnt in counts.items()
                if cnt >= 10 and any(tok in tag.lower() for tok in stem_tokens)
            }
            if stem_matches:
                return max(stem_matches.items(), key=lambda kv: kv[1])[0]
        best_tag, best_cnt = max(counts.items(), key=lambda kv: kv[1])
        if best_cnt >= 10:
            return best_tag
    return clean_fb


def scan_disk_models(cfg: Any, registry: ModelRegistry | None = None) -> list[dict]:
    """Escanea modelos en ComfyUI/models (reubicando si estan en loras) y los registra."""
    if cfg is None or not getattr(cfg, "comfy_root", None):
        return []
    models_root = Path(cfg.comfy_root) / "models"
    if not models_root.is_dir():
        return []

    loras_dir = models_root / "loras"
    diff_dir = models_root / "diffusion_models"
    ckpt_dir = models_root / "checkpoints"

    # Paso 1: Reubicar modelos completos puestos por error en loras/ o carpetas cruzadas
    for scan_dir in (loras_dir, diff_dir, ckpt_dir):
        if not scan_dir.is_dir():
            continue
        for path in sorted(scan_dir.rglob("*.safetensors")):
            kind, _ = classify_safetensors_file(path)
            if kind == "checkpoint" and scan_dir != ckpt_dir:
                rel = path.relative_to(scan_dir)
                dest = ckpt_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    try:
                        shutil.move(str(path), str(dest))
                    except OSError:
                        pass
            elif kind == "anima_unet" and scan_dir != diff_dir:
                rel = path.relative_to(scan_dir)
                dest = diff_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    try:
                        shutil.move(str(path), str(dest))
                    except OSError:
                        pass

    if registry is None:
        return []

    known_unets = {
        entry.profile.unet_name.replace("/", "\\").lower()
        for entry in registry.models
    }
    known_ids = {entry.id for entry in registry.models}
    added: list[ModelEntry] = []

    candidates: list[tuple[Path, Path, str, bytes]] = []
    if diff_dir.is_dir():
        for p in sorted(diff_dir.rglob("*.safetensors")):
            kind, raw_hdr = classify_safetensors_file(p)
            if kind == "anima_unet":
                candidates.append((p, diff_dir, "anima_unet", raw_hdr))
    if ckpt_dir.is_dir():
        for p in sorted(ckpt_dir.rglob("*.safetensors")):
            kind, raw_hdr = classify_safetensors_file(p)
            if kind in ("checkpoint", "anima_unet"):
                candidates.append((p, ckpt_dir, "checkpoint", raw_hdr))

    for path, base_dir, kind, raw_hdr in candidates:
        rel_name = str(path.relative_to(base_dir)).replace("\\", "/")
        if rel_name.replace("/", "\\").lower() in known_unets:
            continue
        base_id = _lora_slug(path.stem)
        model_id = base_id
        suffix = 2
        while model_id in known_ids:
            model_id = f"{base_id}-{suffix}"
            suffix += 1
        meta = {}
        tensor_names: list[str] = []
        if raw_hdr:
            hdr = safetensors_header(raw_hdr)
            if isinstance(hdr, dict):
                if isinstance(hdr.get("__metadata__"), dict):
                    meta = hdr["__metadata__"]
                tensor_names = [k for k in hdr if k != "__metadata__"]
        subfamily = infer_subfamily(meta, tensor_names, rel_name)

        if kind == "checkpoint":
            model_family = "sdxl"
            profile = ModelProfile(
                unet_name=rel_name,
                clip_name="__checkpoint__",
                clip_type="checkpoint",
                vae_name="__checkpoint__",
            )
            defaults = {
                "steps": 28,
                "cfg": 3.5,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "width": 1024,
                "height": 1024,
            }
            source = "auto-detectado (ComfyUI/models/checkpoints)"
            notes = "Checkpoint completo (UNet + CLIP + VAE) auto-detectado en disco"
        else:
            model_family = "anima"
            profile = ModelProfile(
                unet_name=rel_name,
                clip_name="qwen_3_06b_base.safetensors",
                clip_type="stable_diffusion",
                vae_name="qwen_image_vae.safetensors",
            )
            defaults = {
                "steps": 30,
                "cfg": 6.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "width": 1024,
                "height": 1024,
            }
            source = "auto-detectado (ComfyUI/models/diffusion_models)"
            notes = "Modelo Anima auto-detectado en disco"

        prompt_profile = infer_prompt_profile(
            model_id=model_id,
            family=model_family,
            display_name=path.stem,
            unet_name=rel_name,
            subfamily=subfamily,
        )
        # Preprompt por perfil/modelo (W2): Animagine -> animagine, natural -> ninguno,
        # tags genericos -> sdxl_default, Anima -> glossy (no forzar sdxl_tags a todos).
        _pp_family, preprompt_name = default_preprompt_for_profile(
            prompt_profile, model_family
        )
        entry = ModelEntry(
            id=model_id,
            family=model_family,
            display_name=path.stem,
            profile=profile,
            source=source,
            license="no verificada (archivo local del usuario)",
            preprompt=preprompt_name,
            defaults=defaults,
            notes=notes,
            prompt_profile=prompt_profile,
            subfamily=subfamily,
        )
        registry.add(entry)
        known_ids.add(model_id)
        known_unets.add(rel_name.replace("/", "\\").lower())
        added.append(entry)

    # Auto-corregir familia de modelos checkpoint existentes si estaban marcados como anima
    for existing_model in list(registry.models):
        if existing_model.profile.clip_type == "checkpoint" and existing_model.family != "sdxl":
            try:
                fixed_model = ModelEntry(
                    id=existing_model.id,
                    family="sdxl",
                    display_name=existing_model.display_name,
                    profile=existing_model.profile,
                    source=existing_model.source,
                    license=existing_model.license,
                    preprompt=existing_model.preprompt,
                    defaults=dict(existing_model.defaults),
                    notes=existing_model.notes,
                    prompt_profile=existing_model.prompt_profile,
                    subfamily=getattr(existing_model, "subfamily", DEFAULT_SUBFAMILY),
                )
                registry._replace(fixed_model)
            except Exception:
                pass

    if added and getattr(cfg, "data_dir", None):
        user_models_path = Path(cfg.data_dir) / "registry" / "models.json"
        try:
            user_reg = ModelRegistry.load_or_empty(user_models_path)
            for item in added:
                user_reg._replace(item)
            user_reg.save(user_models_path)
        except Exception:
            pass

    return [
        {
            "id": e.id,
            "display_name": e.display_name,
            "family": e.family,
            "subfamily": e.subfamily,
            "unet_name": e.profile.unet_name,
        }
        for e in added
    ]


def infer_lora_family(raw_header: bytes, rel_path: Path) -> str:
    """Detecta la arquitectura base compatible de un LoRA (anima, sdxl, wan, h3)."""
    header = safetensors_header(raw_header)
    keys = [k for k in header.keys() if k != "__metadata__"] if header else []
    meta = header.get("__metadata__", {}) if isinstance(header, dict) else {}
    arch = str(meta.get("modelspec.architecture") or "").lower()
    base = str(meta.get("ss_base_model_version") or "").lower()
    sd_name = str(meta.get("ss_sd_model_name") or "").lower()
    combined_meta = f"{arch} {base} {sd_name}".lower()

    if any(m in combined_meta for m in ("wan", "lightx2v")) or any("wan" in k.lower() for k in keys):
        return "wan"
    if any(m in combined_meta for m in ("h3", "minimax")) or rel_path.name.lower().startswith("minimax_h3"):
        return "h3"
    if "anima" in combined_meta:
        return "anima"
    if any(k.startswith(("diffusion_model.blocks.", "lora_te_layers_", "net.blocks.")) for k in keys):
        return "anima"
    if any(m in combined_meta for m in ("sdxl", "illustrious", "pony")):
        return "sdxl"
    if any(k.startswith(("lora_te1_", "lora_te2_")) for k in keys):
        return "sdxl"
    if any(
        "input_blocks" in k
        or "output_blocks" in k
        or any(b in k for b in ("lora_unet_down_blocks", "lora_unet_up_blocks", "down_blocks.", "up_blocks."))
        for k in keys
    ):
        return "sdxl"
    parts = rel_path.parts
    if len(parts) > 1:
        sub = _lora_slug(parts[0])
        if sub in ("wan", "lightx2v"):
            return "wan"
        if sub in ("h3", "minimax_h3"):
            return "h3"
        if sub in ("sdxl", "illustrious", "pony"):
            return "sdxl"
        if sub == "anima":
            return "anima"
    return "anima"


def scan_disk_loras(comfy_root: Any) -> list[dict]:
    """Escanea ComfyUI/models/loras, infiere arquitectura y registra novedades o auto-corrige familias."""
    if not comfy_root:
        return []
    loras_dir = Path(comfy_root) / "models" / "loras"
    if not loras_dir.is_dir():
        return []

    existing = list_loras()
    file_to_entry = {
        item["file"].replace("/", "\\").lower(): item for item in existing
    }
    known_files = set(file_to_entry.keys())
    known_ids = {item["id"] for item in existing}
    added: list[dict] = []

    for path in sorted(loras_dir.rglob("*.safetensors")):
        rel_path = path.relative_to(loras_dir)
        rel_str = str(rel_path).replace("/", "\\")
        kind, raw_header = classify_safetensors_file(path)
        if kind != "lora":
            continue
        family = infer_lora_family(raw_header, rel_path)
        key = rel_str.lower()
        if key in known_files:
            existing_item = file_to_entry[key]
            if existing_item.get("family") != family:
                try:
                    update_lora(existing_item["id"], {"family": family})
                    existing_item["family"] = family
                except Exception:
                    pass
            continue

        inferred = inspect_safetensors(raw_header)
        stem = path.stem
        title = inferred["title"].strip()
        if title and title.lower() != stem.lower() and len(title) <= 40:
            display_name = f"{stem} ({title})"
        else:
            display_name = stem

        trigger = _smart_infer_trigger(raw_header, inferred["trigger"], stem=stem)
        base_id = _lora_slug(stem)
        lora_id = base_id
        suffix = 2
        while lora_id in known_ids:
            lora_id = f"{base_id}-{suffix}"
            suffix += 1

        meta = {}
        if raw_header:
            hdr = safetensors_header(raw_header)
            if isinstance(hdr, dict) and isinstance(hdr.get("__metadata__"), dict):
                meta = hdr["__metadata__"]
        lora_subfamily = infer_subfamily(meta)
        if lora_subfamily == DEFAULT_SUBFAMILY:
            parts_str = str(rel_path).lower()
            if "illustrious" in parts_str:
                lora_subfamily = "illustrious"
            elif "pony" in parts_str:
                lora_subfamily = "pony"
            elif "noobai" in parts_str:
                lora_subfamily = "noobai"
            elif "anima" in parts_str:
                lora_subfamily = "anima"
            else:
                lora_subfamily = ""

        entry = {
            "id": lora_id,
            "family": family,
            "subfamily": lora_subfamily,
            "file": rel_str,
            "display_name": display_name,
            "trigger": trigger,
            "default_weight": 1.0,
            "source": "auto-detectado (ComfyUI\\models\\loras)",
            "license": "no verificada (archivo del usuario)",
            "notes": _lora_upload_notes(inferred),
        }
        try:
            saved = _call_add_lora(entry)
            known_files.add(rel_str.lower())
            known_ids.add(lora_id)
            added.append(saved)
        except Exception:
            continue

    return added


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

DEFAULTS_KEYS = ("seed", "steps", "cfg", "sampler_name", "scheduler", "width", "height")


def _validate_defaults(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise EngineError("defaults invalido; usar objeto")
    clean: dict = {}
    for key, value in payload.items():
        if key not in DEFAULTS_KEYS:
            raise EngineError(f"default desconocido: {key}")
        if key in ("seed", "steps", "width", "height"):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EngineError(f"{key} invalido")
        elif key == "cfg":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise EngineError("cfg invalido")
            value = float(value)
        elif key == "sampler_name" and value not in SAMPLER_NAMES:
            raise EngineError(f"sampler_name invalido: {value!r}")
        elif key == "scheduler" and value not in SCHEDULER_NAMES:
            raise EngineError(f"scheduler invalido: {value!r}")
        clean[key] = value
    return clean


@router.get("/api/models/{model_id}/defaults")
async def api_model_defaults(request: Request, model_id: str) -> Any:
    try:
        entry = request.app.state.registry.get(model_id)
    except EngineError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    return {"model_id": entry.id, "defaults": dict(entry.defaults)}


@router.put("/api/models/{model_id}/defaults")
async def api_model_defaults_update(
    request: Request, model_id: str, payload: dict = Body(...)
) -> Any:
    try:
        entry = request.app.state.registry.get(model_id)
        defaults = dict(entry.defaults)
        defaults.update(_validate_defaults(payload))
        entry = replace(entry, defaults=defaults)
        request.app.state.registry._replace(entry)
        path = Path(request.app.state.config.data_dir) / "registry" / "models.json"
        request.app.state.registry.save(path)
    except EngineError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"model_id": entry.id, "defaults": dict(entry.defaults)}


@router.put("/api/models/{model_id}")
async def api_model_update(
    request: Request, model_id: str, payload: dict = Body(...)
) -> Any:
    """Edita campos de un modelo registrado (subfamily, display_name, notes, preprompt, prompt_profile)."""
    try:
        entry = request.app.state.registry.get(model_id)
    except EngineError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    updates: dict[str, Any] = {}
    if "subfamily" in payload:
        subfamily = str(payload["subfamily"]).strip()
        if subfamily not in KNOWN_SUBFAMILIES:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"subfamily invalida: {subfamily!r} (esperada una de {KNOWN_SUBFAMILIES})"
                },
            )
        updates["subfamily"] = subfamily
    if "display_name" in payload and str(payload["display_name"]).strip():
        updates["display_name"] = str(payload["display_name"]).strip()
    if "notes" in payload and isinstance(payload["notes"], str):
        updates["notes"] = payload["notes"]
    if "preprompt" in payload and isinstance(payload["preprompt"], str):
        updates["preprompt"] = payload["preprompt"]
    if "prompt_profile" in payload:
        prof = str(payload["prompt_profile"]).strip()
        if prof in PROMPT_PROFILES:
            updates["prompt_profile"] = prof
        else:
            return JSONResponse(
                status_code=400,
                content={"error": f"prompt_profile invalido: {prof!r}"},
            )

    if updates:
        entry = replace(entry, **updates)
        request.app.state.registry._replace(entry)
        cfg = getattr(request.app.state, "config", None)
        if cfg and getattr(cfg, "data_dir", None):
            path = Path(cfg.data_dir) / "registry" / "models.json"
            request.app.state.registry.save(path)

    return {
        "id": entry.id,
        "display_name": entry.display_name,
        "family": entry.family,
        "subfamily": entry.subfamily,
        "preprompt": entry.preprompt,
        "prompt_profile": entry.prompt_profile,
        "prompt_profile_info": prompt_profile_info(entry.prompt_profile),
        "unet_name": entry.profile.unet_name,
        "defaults": dict(entry.defaults),
    }


@router.get("/api/prompt/profiles")
async def api_prompt_profiles() -> dict:
    """Guia de prompt por perfil (fuente unica: registry.PROMPT_PROFILE_INFO)."""
    profiles = sorted(
        (prompt_profile_info(name) for name in PROMPT_PROFILE_INFO),
        key=lambda info: info["order"],
    )
    return {"profiles": profiles}


@router.get("/api/models")
async def api_models(request: Request, scan: bool = False) -> list[dict]:
    reg = request.app.state.registry
    if scan:
        cfg = getattr(request.app.state, "config", None)
        scan_disk_models(cfg, reg)
    return [
        {
            "id": entry.id,
            "display_name": entry.display_name,
            "family": entry.family,
            "subfamily": getattr(entry, "subfamily", DEFAULT_SUBFAMILY),
            "preprompt": entry.preprompt,
            "prompt_profile": entry.prompt_profile,
            "prompt_profile_info": prompt_profile_info(entry.prompt_profile),
            "unet_name": entry.profile.unet_name,
            "defaults": dict(entry.defaults),
        }
        for entry in reg.models
    ]


@router.get("/api/loras")
async def api_loras(
    request: Request,
    family: str | None = None,
    subfamily: str | None = None,
    all: bool = False,
    scan: bool = False,
) -> dict:
    if scan:
        cfg = getattr(request.app.state, "config", None)
        reg = getattr(request.app.state, "registry", None)
        scan_disk_models(cfg, reg)
        if cfg is not None:
            scan_disk_loras(cfg.comfy_root)
    qp = request.query_params
    ver_todas = (
        all
        or qp.get("all") in ("1", "true", "True")
        or qp.get("ver_todas") in ("1", "true", "True")
        or qp.get("show_all") in ("1", "true", "True")
    )
    items = list_loras(family=family, subfamily=subfamily, all=ver_todas)
    for item in items:
        if "subfamily" not in item:
            item["subfamily"] = ""
    return {"items": items, "families": lora_families()}


@router.post("/api/loras/scan")
async def api_loras_scan(request: Request) -> dict:
    """Escanea las carpetas de modelos y LoRAs en disco y registra novedades."""
    cfg = getattr(request.app.state, "config", None)
    reg = getattr(request.app.state, "registry", None)
    added_models = scan_disk_models(cfg, reg)
    added_loras = scan_disk_loras(cfg.comfy_root) if cfg is not None else []
    return {
        "added_loras": added_loras,
        "added_models": added_models,
        **_lora_catalog(),
    }


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
    lora_subfamily = payload.get("subfamily")
    if not isinstance(lora_subfamily, str) or not lora_subfamily.strip():
        lora_subfamily = infer_subfamily(filename)
        if lora_subfamily == DEFAULT_SUBFAMILY:
            lora_subfamily = ""
    else:
        lora_subfamily = lora_subfamily.strip()
    entry = {
        "id": lora_id,
        "family": family,
        "subfamily": lora_subfamily,
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
