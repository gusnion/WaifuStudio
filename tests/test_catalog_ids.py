"""Consistencia de ids entre el manifiesto de instalacion y el catalogo (PL-01)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "install" / "manifest" / "manifest.models.json"
RECOMMENDED_PATH = ROOT / "registry" / "recommended-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CatalogIdsTests(unittest.TestCase):
    def test_no_queda_el_id_legacy_anima_29b(self):
        for path in (MANIFEST_PATH, RECOMMENDED_PATH):
            with self.subTest(path=path.name):
                self.assertNotIn("anima-29b-preview", path.read_text(encoding="utf-8"))

    def test_manifiesto_y_catalogo_coinciden_por_filename(self):
        manifest = _load(MANIFEST_PATH)
        recommended = _load(RECOMMENDED_PATH)
        manifest_ids = {
            entry["filename"]: entry["id"]
            for entry in manifest["models"]
            if isinstance(entry, dict) and "filename" in entry and "id" in entry
        }
        recommended_ids = {
            entry["profile"]["unet_name"]: entry["id"]
            for entry in recommended["models"]
            if isinstance(entry, dict) and "profile" in entry and "id" in entry
        }
        shared = set(manifest_ids) & set(recommended_ids)
        self.assertTrue(shared)
        for filename in sorted(shared):
            with self.subTest(filename=filename):
                self.assertEqual(manifest_ids[filename], recommended_ids[filename])

    def test_anima_29b_tiene_un_unico_id_canonico(self):
        recommended = _load(RECOMMENDED_PATH)
        matches = [
            entry["id"]
            for entry in recommended["models"]
            if entry.get("profile", {}).get("unet_name")
            == "Anima-2.9B-preview-v1.safetensors"
        ]
        self.assertEqual(matches, ["anima-2.9b-preview"])


if __name__ == "__main__":
    unittest.main()
