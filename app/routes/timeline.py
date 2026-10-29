"""Rutas para el Estudio / Timeline (/api/timeline/* y /media/audio/*).

Qué hace: gestiona proyectos de timeline (CRUD en Store), extracción de fotogramas
clave para I2V/FLF2V, subida y servicio de pistas de audio, y exportación a vídeo MP4.
Qué no hace: no interactúa directamente con ComfyUI ni despacha workflows de difusión.
Dependencias: app.store.Store, app.timeline, app.engine.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.engine import EngineError
from app.timeline import export_timeline_project, extract_clip_frame, resolve_gallery_path

AUDIO_EXTENSIONS = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}

MEDIA_EXTENSIONS = {
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"),
    ".mp4": ("video", "video/mp4"),
    ".webm": ("video", "video/webm"),
}

router = APIRouter()


@router.post("/api/timeline/upload_media")
async def api_timeline_upload_media(request: Request) -> Any:
    """Importa una imagen o vídeo externo a data/gallery/timeline."""
    cfg = request.app.state.config
    payload = await request.json()
    filename = str(payload.get("filename") or "media")
    raw_b64 = payload.get("media_b64") or payload.get("data")
    if not isinstance(raw_b64, str) or not raw_b64:
        raise EngineError("media_b64 requerido")
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(raw_b64)
    except Exception as exc:
        raise EngineError(f"base64 invalido: {exc}") from exc
    ext = Path(filename).suffix.lower()
    entry = MEDIA_EXTENSIONS.get(ext)
    if entry is None:
        raise EngineError(f"extension no permitida: {ext}")
    target_dir = (cfg.data_dir / "gallery" / "timeline").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:10]}_{Path(filename).name}"
    target = (target_dir / safe_name).resolve()
    if not target.is_relative_to(target_dir):
        raise EngineError("nombre de archivo invalido")
    target.write_bytes(raw)
    return {
        "ok": True,
        "filename": safe_name,
        "kind": entry[0],
        "url": f"/media/timeline/{safe_name}",
    }


@router.get("/media/timeline/{name:path}")
async def api_media_timeline(name: str, request: Request) -> Any:
    cfg = request.app.state.config
    root = (cfg.data_dir / "gallery" / "timeline").resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        return JSONResponse(status_code=403, content={"error": "ruta fuera de timeline"})
    entry = MEDIA_EXTENSIONS.get(target.suffix.lower())
    if entry is None or not target.is_file():
        return JSONResponse(status_code=404, content={"error": "no encontrado"})
    return FileResponse(target, media_type=entry[1])


@router.get("/api/timeline/projects")
async def api_list_timeline_projects(request: Request) -> Any:
    """Lista los proyectos de timeline guardados en Store."""
    try:
        limit = int(request.query_params.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    st = request.app.state.store
    items = st.list_timeline_projects(limit=limit)
    return {"items": items}


@router.post("/api/timeline/projects")
async def api_save_timeline_project(request: Request) -> Any:
    """Crea o actualiza un proyecto de timeline."""
    payload = await request.json()
    project_id = payload.get("id")
    name = str(payload.get("name") or "Proyecto sin título").strip()
    data = payload.get("data")
    if not isinstance(data, dict):
        data = {}
    st = request.app.state.store
    saved = st.save_timeline_project(project_id, name, data)
    return saved


@router.get("/api/timeline/projects/{project_id}")
async def api_get_timeline_project(project_id: str, request: Request) -> Any:
    """Devuelve un proyecto de timeline por su ID."""
    st = request.app.state.store
    proj = st.get_timeline_project(project_id)
    if proj is None:
        return JSONResponse(status_code=404, content={"error": "proyecto no encontrado"})
    return proj


@router.delete("/api/timeline/projects/{project_id}")
async def api_delete_timeline_project(project_id: str, request: Request) -> Any:
    """Elimina un proyecto de timeline."""
    st = request.app.state.store
    ok = st.delete_timeline_project(project_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "proyecto no encontrado"})
    return {"ok": True, "id": project_id}


@router.post("/api/timeline/extract_frame")
async def api_timeline_extract_frame(request: Request) -> Any:
    """Extrae primer o último frame de un vídeo y lo ubica en ComfyUI/input para I2V."""
    payload = await request.json()
    cfg = request.app.state.config
    st = request.app.state.store
    gen_id = payload.get("generation_id")
    source_path = payload.get("source_path")
    position = str(payload.get("position") or "last").strip().lower()
    if position not in ("first", "last"):
        raise EngineError("position debe ser 'first' o 'last'")

    video_path: Path | None = None
    base_id = ""
    gallery_root = (cfg.data_dir / "gallery").resolve()

    if source_path:
        cand = resolve_gallery_path(source_path, gallery_root)
        if cand is not None and cand.is_file():
            video_path = cand
            base_id = str(gen_id) if gen_id is not None else cand.stem

    if video_path is None and gen_id is not None:
        try:
            gen_int = int(gen_id)
        except (ValueError, TypeError):
            gen_int = None
        if gen_int is not None:
            row = st.get(gen_int)
            if row is not None:
                gdir = (gallery_root / str(gen_id)).resolve()
                for out in (row.get("outputs") or []):
                    name = out.get("name") if isinstance(out, dict) else out
                    if name:
                        cand = (gdir / name).resolve()
                        if (
                            cand.is_relative_to(gallery_root)
                            and cand.is_file()
                            and cand.suffix.lower() in (".mp4", ".webm", ".png", ".jpg", ".jpeg", ".webp")
                        ):
                            video_path = cand
                            break
                if not video_path and gdir.is_dir():
                    for cand in sorted(gdir.glob("*")):
                        if (
                            cand.is_file()
                            and cand.suffix.lower() in (".mp4", ".webm", ".png", ".jpg", ".jpeg", ".webp")
                        ):
                            video_path = cand
                            break
                base_id = str(gen_id)
            elif not source_path:
                return JSONResponse(status_code=404, content={"error": f"generacion {gen_id} no encontrada"})

    if not video_path or not video_path.is_file():
        return JSONResponse(status_code=404, content={"error": "no se encontro video de origen"})

    image_name = f"tl_frame_{base_id}_{position}.png"
    target_png = cfg.comfy_input_dir / image_name
    if video_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        shutil.copy2(video_path, target_png)
    else:
        extract_clip_frame(video_path, target_png, position=position)
    preview_url = f"/api/refs/{image_name}"
    image_bytes = target_png.read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    return {
        "ok": True,
        "image_name": image_name,
        "image_b64": image_b64,
        "preview_url": preview_url,
    }


@router.post("/api/timeline/upload_audio")
async def api_timeline_upload_audio(request: Request) -> Any:
    """Sube un archivo de audio (.mp3, .wav, .ogg, .m4a) a data/audio/."""
    cfg = request.app.state.config
    audio_dir = (cfg.data_dir / "audio").resolve()
    audio_dir.mkdir(parents=True, exist_ok=True)

    content_type = request.headers.get("content-type", "")
    filename = ""
    file_bytes = b""

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded = form.get("file")
        if not uploaded or not hasattr(uploaded, "read"):
            raise EngineError("no se subio ningun archivo de audio")
        filename = getattr(uploaded, "filename", "audio.mp3")
        file_bytes = await uploaded.read()
    else:
        payload = await request.json()
        filename = payload.get("filename") or "audio.mp3"
        b64 = payload.get("audio_b64") or payload.get("data")
        if not b64 or not isinstance(b64, str):
            raise EngineError("audio_b64 o multipart/form-data requerido")
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        try:
            file_bytes = base64.b64decode(b64)
        except Exception as exc:
            raise EngineError(f"base64 invalido: {exc}") from exc

    ext = Path(filename).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        raise EngineError(f"extension de audio no permitida: {ext}; usar .mp3, .wav, .ogg o .m4a")

    safe_name = f"{uuid.uuid4().hex[:8]}_{Path(filename).name}"
    dest = (audio_dir / safe_name).resolve()
    dest.write_bytes(file_bytes)
    audio_url = f"/media/audio/{safe_name}"

    return {
        "ok": True,
        "filename": safe_name,
        "audio_path": str(dest),
        "audio_url": audio_url,
    }


@router.get("/media/audio/{name:path}")
async def api_media_audio(name: str, request: Request) -> Any:
    """Sirve archivos de audio desde data/audio con validación estricta de rutas."""
    cfg = request.app.state.config
    audio_dir = (cfg.data_dir / "audio").resolve()
    target = (audio_dir / name).resolve()
    if not target.is_relative_to(audio_dir):
        return JSONResponse(status_code=403, content={"error": "ruta fuera de directorio de audio"})
    ext = target.suffix.lower()
    media_type = AUDIO_EXTENSIONS.get(ext)
    if media_type is None:
        return JSONResponse(status_code=403, content={"error": "tipo de audio no soportado"})
    if not target.is_file():
        return JSONResponse(status_code=404, content={"error": "archivo de audio no encontrado"})
    return FileResponse(target, media_type=media_type)


@router.post("/api/timeline/export")
async def api_timeline_export(request: Request) -> Any:
    """Exporta y renderiza el proyecto de timeline a un nuevo registro de vídeo."""
    payload = await request.json()
    cfg = request.app.state.config
    st = request.app.state.store

    project_data = payload.get("project_data")
    project_id = payload.get("project_id")
    name = str(payload.get("name") or "Exportación Timeline").strip()

    if not project_data and project_id:
        proj = st.get_timeline_project(project_id)
        if proj is None:
            return JSONResponse(status_code=404, content={"error": "proyecto no encontrado"})
        project_data = proj.get("data")
        name = proj.get("name") or name

    if not isinstance(project_data, dict):
        raise EngineError("project_data o project_id requerido")

    clips = project_data.get("clips") or []
    if not clips:
        raise EngineError("el proyecto no tiene clips para exportar")

    gen_id = st.add(
        model_id="timeline",
        prompt=name,
        negative="",
        params={"task": "timeline_export", "project_data": project_data},
        status="queued",
        kind="video",
    )

    gallery_dir = (cfg.data_dir / "gallery").resolve()
    out_dir = gallery_dir / str(gen_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"timeline_{gen_id}.mp4"
    out_mp4 = out_dir / out_name
    work_dir = (cfg.data_dir / "tmp" / f"tl_work_{gen_id}").resolve()

    try:
        await asyncio.to_thread(
            export_timeline_project,
            project_data,
            out_mp4,
            work_dir=work_dir,
            gallery_dir=gallery_dir,
        )
        resolved_mp4 = out_mp4.resolve()
        st.update(gen_id, status="done", outputs=[out_name], kind="video")
        return {
            "ok": True,
            "generation_id": gen_id,
            "output_name": out_name,
            "output_url": f"/media/{gen_id}/{out_name}",
            "output_path": str(resolved_mp4),
        }
    except Exception as exc:
        st.update(gen_id, status="error", error=str(exc))
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@router.post("/api/timeline/reveal")
async def api_timeline_reveal(request: Request) -> Any:
    """Abre en Windows Explorer la carpeta del archivo exportado dentro de data/gallery o data/exports."""
    cfg = request.app.state.config
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    raw_path = str(payload.get("path") or payload.get("output_path") or "").strip()
    if not raw_path:
        return JSONResponse(status_code=400, content={"error": "path requerido"})
    if "\x00" in raw_path:
        return JSONResponse(
            status_code=403,
            content={"error": "ruta fuera de data/gallery o data/exports"},
        )

    raw_p = Path(raw_path)
    if ".." in raw_p.parts:
        return JSONResponse(
            status_code=403,
            content={"error": "ruta fuera de data/gallery o data/exports"},
        )

    gallery_root = (cfg.data_dir / "gallery").resolve()
    exports_root = (cfg.data_dir / "exports").resolve()

    try:
        if raw_p.is_absolute():
            target = raw_p.resolve()
        else:
            cand_data = (cfg.data_dir / raw_p).resolve()
            cand_root = (cfg.data_dir.parent / raw_p).resolve()
            if cand_data.is_relative_to(gallery_root) or cand_data.is_relative_to(exports_root):
                target = cand_data
            else:
                target = cand_root
    except Exception:
        return JSONResponse(status_code=400, content={"error": "ruta invalida"})

    if not (target.is_relative_to(gallery_root) or target.is_relative_to(exports_root)):
        return JSONResponse(
            status_code=403,
            content={"error": "ruta fuera de data/gallery o data/exports"},
        )

    if not target.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "archivo o carpeta exportado no encontrado"},
        )

    if os.name != "nt":
        return JSONResponse(
            status_code=400,
            content={"error": "Abrir carpeta en Explorer solo esta disponible en Windows"},
        )

    try:
        if target.is_dir():
            subprocess.Popen(["explorer.exe", str(target)])
            folder_path = str(target)
        else:
            subprocess.Popen(["explorer.exe", f"/select,{target}"])
            folder_path = str(target.parent)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"No se pudo abrir Explorer: {exc}"},
        )

    return {
        "ok": True,
        "path": str(target),
        "folder": folder_path,
    }
