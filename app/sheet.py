"""Hoja de referencia de un OC (M9-B2): collage PNG de 2+ vistas con Pillow.

`make_sheet` compone una rejilla de `cols` columnas con celdas de retrato 2:3
(el formato natural de las vistas de un OC): cada columna mide `cell // cols`
de ancho, cada celda `1.5x` ese ancho, y las imagenes se ajustan con
`ImageOps.fit` al area interior dejando 8 px de fondo `bg` entre ellas (y 4 px
de margen exterior). Con los defaults, 3-4 refs dan una hoja de 512x768.
CPU pura, sin red ni dependencias extra.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from app.engine import EngineError

SHEET_GAP = 8


def make_sheet(
    image_paths: list[Path],
    out_path: Path,
    *,
    cell: int = 512,
    cols: int = 2,
    bg: tuple[int, int, int] = (24, 24, 28),
) -> Path:
    """Compone las imagenes en un PNG RGB en `out_path` y lo devuelve.

    Exige al menos 2 imagenes existentes (`EngineError` si no). Cada imagen se
    redimensiona con `ImageOps.fit` a la celda interior (sin deformar, recorte
    centrado) y se guarda con el fondo `bg` a la vista como separacion.
    """
    if not isinstance(image_paths, (list, tuple)):
        raise EngineError(f"hoja de referencia: se esperaba lista de rutas: {image_paths!r}")
    paths = [Path(path) for path in image_paths]
    if len(paths) < 2:
        raise EngineError(
            f"hoja de referencia: se necesitan >=2 imagenes, hay {len(paths)}"
        )
    for path in paths:
        if not path.is_file():
            raise EngineError(f"hoja de referencia: imagen no encontrada: {path}")
    if isinstance(cols, bool) or not isinstance(cols, int) or cols < 1:
        raise EngineError(f"hoja de referencia: cols invalido: {cols!r}")
    if isinstance(cell, bool) or not isinstance(cell, int) or cell < 16:
        raise EngineError(f"hoja de referencia: cell invalido: {cell!r}")

    gap = SHEET_GAP
    cell_w = max(1, cell // cols)
    cell_h = max(1, cell_w * 3 // 2)
    inner = (max(1, cell_w - gap), max(1, cell_h - gap))
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), tuple(bg))
    offset = gap // 2
    for index, path in enumerate(paths):
        try:
            with Image.open(path) as raw:
                tile = ImageOps.fit(raw.convert("RGB"), inner)
        except (OSError, ValueError) as exc:
            raise EngineError(f"hoja de referencia: imagen ilegible {path}: {exc}") from exc
        x = (index % cols) * cell_w + offset
        y = (index // cols) * cell_h + offset
        sheet.paste(tile, (x, y))

    out = Path(out_path)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out, format="PNG")
    except OSError as exc:
        raise EngineError(f"hoja de referencia: no se pudo guardar {out}: {exc}") from exc
    return out


__all__ = ["SHEET_GAP", "make_sheet"]
