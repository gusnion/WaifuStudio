"""Tests CPU del catalogo de formatos de imagen (M9-A1). Sin red ni GPU.

Verifican la copia verbatim ``registry/formatos-v1.json`` (contrato legacy
``formatos/v1``) y su exposicion en ``app.formats``.
"""

from __future__ import annotations

import json
import unittest

from app.config import APP_ROOT
from app.engine import EngineError
from app.formats import (
    DEFAULT_FORMAT,
    FORMATS_PATH,
    IMAGE_FORMATS,
    get_size,
    list_image_formats,
)

EXPECTED_IDS = (
    "video_vertical",
    "retrato_sm",
    "retrato_plan",
    "retrato_hd",
    "retrato_xl",
    "video_vertical_hd",
    "video_vertical_xl",
    "video_horizontal",
    "paisaje_sm",
    "paisaje_plan",
    "paisaje_hd",
    "paisaje_xl",
    "video_horizontal_hd",
    "video_horizontal_xl",
    "cuadro_hd",
)

EXPECTED_SIZES = {
    "video_vertical": (432, 768),
    "retrato_sm": (512, 896),
    "retrato_plan": (768, 1344),
    "retrato_hd": (832, 1216),
    "retrato_xl": (1024, 1536),
    "video_vertical_hd": (576, 1024),
    "video_vertical_xl": (1008, 1792),
    "video_horizontal": (768, 432),
    "paisaje_sm": (896, 512),
    "paisaje_plan": (1344, 768),
    "paisaje_hd": (1216, 832),
    "paisaje_xl": (1536, 1024),
    "video_horizontal_hd": (1024, 576),
    "video_horizontal_xl": (1792, 1008),
    "cuadro_hd": (1024, 1024),
}


class RegistryFileTests(unittest.TestCase):
    def test_path_derivado_de_app_root(self):
        self.assertEqual(FORMATS_PATH, APP_ROOT / "registry" / "formatos-v1.json")
        self.assertTrue(FORMATS_PATH.is_file())

    def test_json_verbatim_del_contrato(self):
        data = json.loads(FORMATS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "formatos/v1")
        self.assertEqual(len(data["formatos"]), 17)
        imagen = [entry for entry in data["formatos"] if entry["tipo"] == "imagen"]
        video = [entry for entry in data["formatos"] if entry["tipo"] == "video"]
        self.assertEqual(len(imagen), 15)
        self.assertEqual(len(video), 2)
        self.assertEqual(
            [entry["id"] for entry in imagen], list(EXPECTED_IDS)
        )


class ImageFormatsTests(unittest.TestCase):
    def test_once_formatos_en_orden(self):
        self.assertEqual(tuple(IMAGE_FORMATS), EXPECTED_IDS)
        self.assertEqual(len(IMAGE_FORMATS), 15)

    def test_cada_formato_tiene_id_label_width_height(self):
        for format_id, item in IMAGE_FORMATS.items():
            with self.subTest(format_id=format_id):
                self.assertEqual(
                    set(item), {"id", "label", "width", "height"}
                )
                self.assertEqual(item["id"], format_id)
                self.assertIsInstance(item["label"], str)
                self.assertTrue(item["label"].strip())
                self.assertEqual(
                    (item["width"], item["height"]), EXPECTED_SIZES[format_id]
                )
                self.assertEqual(item["width"] % 8, 0)
                self.assertEqual(item["height"] % 8, 0)

    def test_list_image_formats_copia_en_orden(self):
        listed = list_image_formats()
        self.assertIsInstance(listed, list)
        self.assertEqual([item["id"] for item in listed], list(EXPECTED_IDS))
        self.assertEqual(listed[0]["label"], "VIDEO 9:16")
        listed[0]["width"] = 1
        self.assertEqual(IMAGE_FORMATS["video_vertical"]["width"], 432)

    def test_default_es_retrato_plan(self):
        self.assertEqual(DEFAULT_FORMAT, "retrato_plan")
        self.assertIn(DEFAULT_FORMAT, IMAGE_FORMATS)


class GetSizeTests(unittest.TestCase):
    def test_todos_los_formatos(self):
        for format_id, expected in EXPECTED_SIZES.items():
            with self.subTest(format_id=format_id):
                self.assertEqual(get_size(format_id), expected)

    def test_desconocido_o_no_str_lanza_engine_error(self):
        for value in ("no-existe", "", None, 5, ["cuadro_hd"]):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    get_size(value)


if __name__ == "__main__":
    unittest.main()
