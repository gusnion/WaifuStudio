"""Rutas de galería y entrega de archivos multimedia (/api/gallery, /media, /api/download, /api/refs).

Qué hace: gestiona la visualización, descarga, borrado y servicio de estáticos de galería y OCs.
Qué no hace: no genera nuevos medios ni modifica parámetros de generación.
Dependencias: app.store.Store, configuración de rutas y FileResponse.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

MEDIA_URL = "/media/{gen_id}/{name}"
MEDIA_TYPES = {
    ".png": "image/png",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
CHARACTER_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

router = APIRouter()


@router.get("/api/gallery")
async def api_gallery(
    request: Request,
    limit: int = 24,
    offset: int = 0,
    kind: str | None = None,
    q: str | None = None,
) -> Any:
    """Feed paginado (mas nuevo primero); `kind` opcional filtra image|video.

    `count` refleja el filtro aplicado, no solo la ventana: el visor de
    video pide `kind=video&limit=5&offset=…` y calcula su pagina X de Y.
    `q` filtra por substring de texto/tags en prompt o negative.
    """
    st = request.app.state.store
    kind = kind or None
    if kind not in (None, "image", "video"):
        return JSONResponse(
            status_code=400, content={"error": "kind invalido; usar image|video"}
        )
    limit = max(1, min(int(limit), 24))
    offset = max(0, int(offset))
    items = []
    for row in st.list(limit=limit, offset=offset, order="desc", kind=kind, q=q):
        item = dict(row)
        item["urls"] = [
            MEDIA_URL.format(gen_id=row["id"], name=name)
            for name in (row.get("outputs") or [])
        ]
        items.append(item)
    return {"items": items, "count": st.count(kind=kind, q=q)}


@router.delete("/api/gallery/{id}")
async def api_gallery_delete(id: int, request: Request) -> Any:
    st = request.app.state.store
    cfg = request.app.state.config
    row = st.get(id)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "no encontrado"})
    if row.get("status") in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar una generacion en cola o en ejecucion",
        )

    base_root = cfg.data_dir.resolve()
    candidate_dirs = [
        (cfg.data_dir / "gallery" / str(id)).resolve(),
        (cfg.data_dir / "generations" / str(id)).resolve(),
    ]
    for dir_path in candidate_dirs:
        if dir_path.is_dir() and dir_path.is_relative_to(base_root):
            for out_name in (row.get("outputs") or []):
                fpath = (dir_path / out_name).resolve()
                if fpath.is_relative_to(dir_path) and fpath.is_file():
                    try:
                        fpath.unlink(missing_ok=True)
                    except OSError:
                        pass
            try:
                shutil.rmtree(dir_path, ignore_errors=True)
            except OSError:
                pass

    st.delete(id)
    return {"ok": True, "id": id}


@router.post("/api/gallery/clean_failed")
async def api_gallery_clean_failed(request: Request) -> Any:
    st = request.app.state.store
    cleaned = st.delete_failed()
    return {"ok": True, "cleaned": cleaned}


@router.get("/media/characters/{char_id}/{name:path}")
async def api_character_media(char_id: int, name: str, request: Request) -> Any:
    chars = request.app.state.characters
    refs_root = Path(chars.refs_root).resolve()
    candidate = (refs_root / str(char_id) / name).resolve()
    if not candidate.is_relative_to(refs_root):
        return JSONResponse(
            status_code=403, content={"error": "ruta fuera de las referencias"}
        )
    media_type = CHARACTER_MEDIA_TYPES.get(candidate.suffix.lower())
    if media_type is None or not candidate.is_file():
        return JSONResponse(status_code=404, content={"error": "no encontrado"})
    return FileResponse(candidate, media_type=media_type)


@router.get("/api/refs/{name:path}")
async def api_ref(name: str, request: Request) -> Any:
    """Sirve una referencia guardada de `comfy_root/input` (solo imagenes).

    Confinamiento estricto al directorio input: 403 si la ruta escapa o la
    extension no es png/jpg/jpeg/webp, 404 si el archivo no existe. La UI lo
    usa para re-adjuntar la referencia guardada en `params.ref_image`.
    """
    cfg = request.app.state.config
    input_root = (cfg.comfy_root / "input").resolve()
    candidate = (input_root / name).resolve()
    if not candidate.is_relative_to(input_root):
        return JSONResponse(
            status_code=403, content={"error": "ruta fuera de comfy input"}
        )
    media_type = CHARACTER_MEDIA_TYPES.get(candidate.suffix.lower())
    if media_type is None:
        return JSONResponse(
            status_code=403, content={"error": "extension no permitida"}
        )
    if not candidate.is_file():
        return JSONResponse(status_code=404, content={"error": "no encontrado"})
    return FileResponse(candidate, media_type=media_type)


@router.get("/media/{gen_id}/{name:path}")
async def api_media(gen_id: int, name: str, request: Request) -> Any:
    cfg = request.app.state.config
    gen_root = (cfg.data_dir / "gallery" / str(gen_id)).resolve()
    candidate = (gen_root / name).resolve()
    if not candidate.is_relative_to(gen_root):
        return JSONResponse(
            status_code=403, content={"error": "ruta fuera de la galeria"}
        )
    media_type = MEDIA_TYPES.get(candidate.suffix.lower())
    if media_type is None or not candidate.is_file():
        return JSONResponse(status_code=404, content={"error": "no encontrado"})
    return FileResponse(candidate, media_type=media_type)


@router.get("/api/download/{gen_id}/{name:path}")
async def api_download(gen_id: int, name: str, request: Request) -> Any:
    """Descarga directa de un archivo de la galeria (Content-Disposition adjunto).

    Mismo confinamiento que `/media`; el navegador lo guarda en Descargas.
    """
    cfg = request.app.state.config
    gen_root = (cfg.data_dir / "gallery" / str(gen_id)).resolve()
    candidate = (gen_root / name).resolve()
    if not candidate.is_relative_to(gen_root):
        return JSONResponse(
            status_code=403, content={"error": "ruta fuera de la galeria"}
        )
    if not candidate.is_file():
        return JSONResponse(status_code=404, content={"error": "no encontrado"})
    media_type = MEDIA_TYPES.get(candidate.suffix.lower()) or "application/octet-stream"
    return FileResponse(
        candidate, media_type=media_type, filename=candidate.name
    )
