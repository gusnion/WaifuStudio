"""Catálogo estático verificable (PL-34)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "catalog" / "catalog.json"


class CatalogTests(unittest.TestCase):
    def test_schema_y_modelos(self):
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "waifu.catalog/v1")
        ids = {item["id"] for item in data["models"]}
        for expected in (
            "animagine-xl-4-opt",
            "realvisxl-v50",
            "juggernaut-xl-ragnarok",
            "wan2.2-i2v-a14b-highnoise-q4-k-s",
        ):
            self.assertIn(expected, ids)
        self.assertTrue(all(len(item.get("sha256", "")) == 64 for item in data["models"] if "sha256" in item))

    def test_pagina_descarga(self):
        html = (ROOT / "docs" / "catalog" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="catalog.json"', html)
        self.assertIn("catalog.json", html)


if __name__ == "__main__":
    unittest.main()
