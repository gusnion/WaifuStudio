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
    rows, total = st.page(limit=limit, offset=offset, order="desc", kind=kind, q=q)
    items = []
    for row in rows:
        item = dict(row)
        item["urls"] = [
            MEDIA_URL.format(gen_id=row["id"], name=name)
            for name in (row.get("outputs") or [])
        ]
        items.append(item)
    return {"items": items, "count": total}


@router.get("/api/gallery/{id}")
async def api_gallery_item(id: int, request: Request) -> Any:
    """Devuelve una generacion concreta con `params` y `urls`.

    Lo usa el Timeline para hidratar clips antiguos guardados sin `params`
    (proyectos creados antes de la herencia de configuracion).
    """
    st = request.app.state.store
    row = st.get(id)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "no encontrado"})
    item = dict(row)
    item["urls"] = [
        MEDIA_URL.format(gen_id=row["id"], name=name)
        for name in (row.get("outputs") or [])
    ]
    return item


def _hydrate_gallery_item(row: dict) -> dict:
    item = dict(row)
    item["urls"] = [
        MEDIA_URL.format(gen_id=row["id"], name=name)
        for name in (row.get("outputs") or [])
    ]
    return item


def _positive_int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


@router.get("/api/gallery/{id}/lineage")
async def api_gallery_lineage(id: int, request: Request) -> Any:
    """Devuelve el nodo, cadena de ancestros hasta la raiz, hijos directos y `root_id`."""
    st = request.app.state.store
    row = st.get(id)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "no encontrado"})

    node = _hydrate_gallery_item(row)
    node_params = node.get("params") if isinstance(node.get("params"), dict) else {}

    ancestors: list[dict] = []
    visited: set[int] = {id}
    curr_params = node_params
    while True:
        parent_id = _positive_int_or_none(curr_params.get("parent_gen_id"))
        if parent_id is None or parent_id in visited:
            break
        visited.add(parent_id)
        parent_row = st.get(parent_id)
        if parent_row is None:
            break
        parent_item = _hydrate_gallery_item(parent_row)
        ancestors.append(parent_item)
        curr_params = (
            parent_item.get("params")
            if isinstance(parent_item.get("params"), dict)
            else {}
        )

    top = ancestors[-1] if ancestors else node
    top_params = top.get("params") if isinstance(top.get("params"), dict) else {}
    root_id = (
        _positive_int_or_none(top_params.get("root_gen_id"))
        or _positive_int_or_none(node_params.get("root_gen_id"))
        or _positive_int_or_none(top_params.get("parent_gen_id"))
        or int(top["id"])
    )

    total = st.count() if hasattr(st, "count") else 0
    all_rows = st.list(limit=max(total, 1000), offset=0, order="asc")
    children: list[dict] = []
    for candidate in all_rows:
        cand_id = int(candidate.get("id", 0))
        if cand_id == id:
            continue
        cand_params = (
            candidate.get("params")
            if isinstance(candidate.get("params"), dict)
            else {}
        )
        if _positive_int_or_none(cand_params.get("parent_gen_id")) == id:
            children.append(_hydrate_gallery_item(candidate))

    return {
        "node": node,
        "ancestors": ancestors,
        "children": children,
        "root_id": root_id,
    }


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
    char_root = (refs_root / str(char_id)).resolve()
    candidate = (char_root / name).resolve()
    if not candidate.is_relative_to(char_root):
        return JSONResponse(
            status_code=403, content={"error": "ruta fuera de las referencias"}
        )
    media_type = CHARACTER_MEDIA_TYPES.get(candidate.suffix.lower())
    if media_type is None or not candidate.is_file():
        return JSONResponse(status_code=404, content={"error": "no encontrado"})
    return FileResponse(candidate, media_type=media_type)


@router.get("/api/refs/{name:path}")
async def api_ref(name: str, request: Request) -> Any:
    """Sirve una referencia guardada de `comfy_root/input` (imagenes o video V2V).

    Confinamiento estricto al directorio input: 403 si la ruta escapa o la
    extension no es png/jpg/jpeg/webp/mp4/webm, 404 si el archivo no existe.
    La UI lo usa para re-adjuntar `params.ref_image` y `params.ref_video`.
    """
    cfg = request.app.state.config
    input_root = (cfg.comfy_root / "input").resolve()
    candidate = (input_root / name).resolve()
    if not candidate.is_relative_to(input_root):
        return JSONResponse(
            status_code=403, content={"error": "ruta fuera de comfy input"}
        )
    media_type = CHARACTER_MEDIA_TYPES.get(candidate.suffix.lower()) or MEDIA_TYPES.get(
        candidate.suffix.lower()
    )
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
