"""Tests CPU de la hoja de referencia de OCs (M9-B2). Sin red ni GPU."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.engine import EngineError
from app.sheet import SHEET_GAP, make_sheet

COLORS = ((200, 40, 40), (40, 200, 40), (40, 40, 200), (200, 200, 40))
BG = (24, 24, 28)


class SheetTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def make_image(
        self,
        name: str,
        *,
        size: tuple[int, int] = (300, 500),
        color: tuple[int, int, int] = (100, 120, 140),
        subdir: str = "src",
    ) -> Path:
        path = self.root / subdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, color).save(path)
        return path

    def make_images(self, count: int) -> list[Path]:
        return [
            self.make_image(f"{index}.png", color=COLORS[index % len(COLORS)])
            for index in range(count)
        ]


class MakeSheetTests(SheetTestCase):
    def test_grid_2x2_y_crea_el_padre(self):
        out = self.root / "nested" / "deeper" / "sheet.png"
        result = make_sheet(self.make_images(4), out)
        self.assertEqual(result, out)
        self.assertTrue(out.is_file())
        self.assertEqual(out.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        with Image.open(out) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (512, 768))
            self.assertEqual(image.getpixel((0, 0)), BG)
            self.assertEqual(image.getpixel((4, 4)), COLORS[0])
            self.assertEqual(image.getpixel((260, 4)), COLORS[1])
            self.assertEqual(image.getpixel((4, 388)), COLORS[2])
            self.assertEqual(image.getpixel((260, 388)), COLORS[3])

    def test_grid_2x1(self):
        out = self.root / "sheet.png"
        make_sheet(self.make_images(2), out)
        with Image.open(out) as image:
            self.assertEqual(image.size, (512, 384))
            self.assertEqual(image.getpixel((4, 4)), COLORS[0])
            self.assertEqual(image.getpixel((260, 4)), COLORS[1])

    def test_tres_imagenes_dos_filas(self):
        out = self.root / "sheet.png"
        make_sheet(self.make_images(3), out)
        with Image.open(out) as image:
            self.assertEqual(image.size, (512, 768))
            self.assertEqual(image.getpixel((4, 4)), COLORS[0])
            self.assertEqual(image.getpixel((260, 4)), COLORS[1])
            self.assertEqual(image.getpixel((4, 388)), COLORS[2])
            self.assertEqual(image.getpixel((260, 388)), BG)

    def test_cell_cols_y_bg_personalizados(self):
        out = self.root / "sheet.png"
        make_sheet(self.make_images(2), out, cell=256, cols=1, bg=(1, 2, 3))
        with Image.open(out) as image:
            self.assertEqual(image.size, (256, 768))
            self.assertEqual(image.getpixel((0, 0)), (1, 2, 3))

    def test_acepta_strings_y_redimensiona(self):
        paths = self.make_images(2)
        out = make_sheet([str(path) for path in paths], self.root / "sheet.png")
        self.assertTrue(out.is_file())

    def test_separacion_es_el_fondo(self):
        out = self.root / "sheet.png"
        make_sheet(self.make_images(2), out)
        with Image.open(out) as image:
            for x in range(252, 260):
                self.assertEqual(image.getpixel((x, 10)), BG)
            self.assertEqual(SHEET_GAP, 8)

    def test_menos_de_dos_imagenes(self):
        out = self.root / "sheet.png"
        with self.assertRaises(EngineError):
            make_sheet([], out)
        with self.assertRaises(EngineError):
            make_sheet(self.make_images(1), out)
        self.assertFalse(out.exists())

    def test_imagen_inexistente(self):
        out = self.root / "sheet.png"
        paths = self.make_images(2)
        with self.assertRaises(EngineError):
            make_sheet([paths[0], self.root / "nope.png"], out)
        self.assertFalse(out.exists())

    def test_imagen_ilegible(self):
        broken = self.root / "src" / "broken.png"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_bytes(b"no soy un png")
        with self.assertRaises(EngineError):
            make_sheet([broken, self.make_image("ok.png")], self.root / "sheet.png")

    def test_cols_y_cell_invalidos(self):
        paths = self.make_images(2)
        out = self.root / "sheet.png"
        with self.assertRaises(EngineError):
            make_sheet(paths, out, cols=0)
        with self.assertRaises(EngineError):
            make_sheet(paths, out, cell=0)
        with self.assertRaises(EngineError):
            make_sheet("no-lista", out)

    def test_no_toca_las_originales(self):
        paths = self.make_images(2)
        before = [path.read_bytes() for path in paths]
        make_sheet(paths, self.root / "sheet.png")
        self.assertEqual([path.read_bytes() for path in paths], before)


if __name__ == "__main__":
    unittest.main()
