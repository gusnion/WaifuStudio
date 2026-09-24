"""Tests CPU del catalogo de preprompts (M8-12) y propios (M9-D2). Sin red ni GPU."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.engine import EngineError
from app.preprompts import (
    DEFAULT_FAMILY,
    DEFAULT_PREPROMPT,
    FAMILY_PREPROMPTS,
    delete_custom,
    get_preprompt,
    list_custom,
    list_families,
    list_preprompts,
    save_custom,
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


class CustomPrepromptTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        patcher = mock.patch.dict(
            os.environ, {"WAIFU_DATA_DIR": str(self.data_dir)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def store_path(self) -> Path:
        return self.data_dir / "preprompts.json"


class CustomCrudTests(CustomPrepromptTestCase):
    def test_save_list_get_delete_roundtrip(self):
        slug = save_custom("mi_estilo", "cinematic lighting", "blurry")
        self.assertEqual(slug, "mi_estilo")
        self.assertEqual(
            list_custom(),
            {"mi_estilo": {"positive": "cinematic lighting", "negative": "blurry"}},
        )
        self.assertTrue(self.store_path.is_file())
        self.assertEqual(
            json.loads(self.store_path.read_text(encoding="utf-8")),
            {
                "custom": {
                    "mi_estilo": {
                        "positive": "cinematic lighting",
                        "negative": "blurry",
                    }
                }
            },
        )
        self.assertEqual(
            get_preprompt("anima", "mi_estilo"),
            {"positive": "cinematic lighting", "negative": "blurry"},
        )
        self.assertEqual(list_preprompts("anima")[-1], "mi_estilo")
        self.assertTrue(delete_custom("mi_estilo"))
        self.assertFalse(delete_custom("mi_estilo"))
        self.assertEqual(list_custom(), {})
        self.assertNotIn("mi_estilo", list_preprompts("anima"))
        self.assertFalse(self.store_path.exists() and "mi_estilo" in self.store_path.read_text(encoding="utf-8"))

    def test_negative_por_defecto_vacio_y_recorte(self):
        save_custom("otro", "  calidad  ")
        self.assertEqual(
            get_preprompt("anima", "otro"), {"positive": "calidad", "negative": ""}
        )
        save_custom("con_neg", "  uno  ", "  dos  ")
        self.assertEqual(
            get_preprompt("anima", "con_neg"),
            {"positive": "uno", "negative": "dos"},
        )

    def test_crea_data_dir_si_falta(self):
        self.assertFalse(self.data_dir.exists())
        save_custom("nuevo", "x")
        self.assertTrue(self.data_dir.is_dir())
        self.assertTrue(self.store_path.is_file())

    def test_persistencia_en_temp_al_releer(self):
        save_custom("persistente", "uno", "dos")
        save_custom("segundo", "tres")
        self.assertEqual(sorted(list_custom()), ["persistente", "segundo"])
        self.assertEqual(get_preprompt("anima", "persistente")["positive"], "uno")
        self.assertEqual(get_preprompt("anima", "segundo")["negative"], "")

    def test_delete_desconocido_o_invalido_devuelve_false(self):
        self.assertFalse(delete_custom("no-existe"))
        self.assertFalse(delete_custom("MAL"))
        self.assertFalse(delete_custom(None))
        self.assertFalse(delete_custom(5))

    def test_no_deja_temporales(self):
        save_custom("limpio", "x")
        save_custom("limpio2", "y")
        self.assertEqual(
            [path.name for path in self.data_dir.iterdir()],
            ["preprompts.json"],
        )

    def test_list_preprompts_incluye_custom_al_final_sin_duplicar(self):
        save_custom("zeta", "x")
        save_custom("alfa", "y")
        self.assertEqual(
            list_preprompts("anima"), sorted(GOLDEN) + ["alfa", "zeta"]
        )


class CustomValidationTests(CustomPrepromptTestCase):
    def test_slug_invalido_lanza_engine_error(self):
        for name in (
            "",
            "a",
            "MAL",
            "con espacio",
            "a" * 33,
            "acentué",
            "mi.estilo",
            "mi/estilo",
            None,
            5,
            ["x"],
        ):
            with self.subTest(name=name):
                with self.assertRaises(EngineError):
                    save_custom(name, "x")
        self.assertEqual(list_custom(), {})

    def test_positivo_vacio_o_invalido_lanza_engine_error(self):
        for positive in ("", "   ", None, 5):
            with self.subTest(positive=positive):
                with self.assertRaises(EngineError):
                    save_custom("valido", positive)
        with self.assertRaises(EngineError):
            save_custom("valido", "ok", negative=5)
        self.assertEqual(list_custom(), {})

    def test_no_sobrescribe_los_cuatro_certificados(self):
        for name in ("anima_default", "glossy", "not_glossy", "ninguno"):
            with self.subTest(name=name):
                with self.assertRaises(EngineError):
                    save_custom(name, "hostil")
        self.assertEqual(list_custom(), {})
        for name, expected in GOLDEN.items():
            self.assertEqual(get_preprompt("anima", name), expected)

    def test_duplicado_exacto_lanza_engine_error(self):
        save_custom("repe", "uno")
        with self.assertRaises(EngineError):
            save_custom("repe", "dos")
        self.assertEqual(get_preprompt("anima", "repe")["positive"], "uno")

    def test_certificado_gana_a_custom_hostil(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            json.dumps(
                {"custom": {"glossy": {"positive": "HOSTIL", "negative": ""}}}
            ),
            encoding="utf-8",
        )
        self.assertEqual(get_preprompt("anima", "glossy"), GOLDEN["glossy"])
        self.assertEqual(list_preprompts("anima").count("glossy"), 1)
        self.assertEqual(list_preprompts("anima"), sorted(GOLDEN))

    def test_store_corrupto_no_rompe_certificados(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text("{no-json", encoding="utf-8")
        with self.assertRaises(EngineError):
            list_custom()
        with self.assertRaises(EngineError):
            save_custom("nuevo", "x")
        self.assertEqual(get_preprompt("anima", "glossy"), GOLDEN["glossy"])
        self.assertEqual(list_preprompts("anima"), sorted(GOLDEN))

    def test_familia_desconocida_sigue_lanzando_engine_error(self):
        save_custom("mi_estilo", "x")
        with self.assertRaises(EngineError):
            list_preprompts("no-existe")
        with self.assertRaises(EngineError):
            get_preprompt("no-existe", "mi_estilo")
        with self.assertRaises(EngineError):
            get_preprompt("anima", "no-existe")


if __name__ == "__main__":
    unittest.main()
