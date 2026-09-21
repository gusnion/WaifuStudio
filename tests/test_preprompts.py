"""Tests CPU del catalogo de preprompts (M8-12). Sin red ni GPU."""

from __future__ import annotations

import unittest

from app.engine import EngineError
from app.preprompts import (
    DEFAULT_FAMILY,
    DEFAULT_PREPROMPT,
    FAMILY_PREPROMPTS,
    get_preprompt,
    list_families,
    list_preprompts,
)

GOLDEN = {
    "anima_default": {
        "positive": "masterpiece, best quality, score_8",
        "negative": "worst quality, low quality, score_1, score_2, score_3, artist name",
    },
    "glossy": {
        "positive": "masterpiece, best quality, absurdres, highres, score_7, score_8, score_9",
        "negative": (
            "worst quality, low quality, score_1, score_2, score_3, blurry, "
            "jpeg artifacts, sepia, bad anatomy, bad hands, mutated hands, "
            "fused fingers, extra fingers, watermark, signature, logo"
        ),
    },
    "not_glossy": {
        "positive": "newest, good quality, score_6, score_5, highres",
        "negative": "low quality, score_1, score_2",
    },
    "ninguno": {"positive": "", "negative": ""},
}


class GoldenTests(unittest.TestCase):
    def test_catalogo_anima_coincide_con_golden(self):
        self.assertEqual(FAMILY_PREPROMPTS["anima"], GOLDEN)

    def test_get_preprompt_devuelve_textos_exactos(self):
        for name, expected in GOLDEN.items():
            with self.subTest(name=name):
                self.assertEqual(get_preprompt("anima", name), expected)

    def test_defaults_apuntan_a_anima_glossy(self):
        self.assertEqual(DEFAULT_FAMILY, "anima")
        self.assertEqual(DEFAULT_PREPROMPT, "glossy")
        self.assertIn(DEFAULT_PREPROMPT, GOLDEN)


class ApiTests(unittest.TestCase):
    def test_list_families(self):
        self.assertEqual(list_families(), ["anima"])

    def test_list_preprompts_ordenado(self):
        self.assertEqual(list_preprompts("anima"), sorted(GOLDEN))

    def test_get_preprompt_devuelve_copia(self):
        first = get_preprompt("anima", "glossy")
        first["positive"] = "mutado"
        self.assertEqual(
            get_preprompt("anima", "glossy")["positive"], GOLDEN["glossy"]["positive"]
        )

    def test_familia_desconocida_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            get_preprompt("no-existe", "glossy")
        with self.assertRaises(EngineError):
            list_preprompts("no-existe")

    def test_nombre_desconocido_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            get_preprompt("anima", "no-existe")


if __name__ == "__main__":
    unittest.main()
