"""Tests CPU del gestor de addons (PL-18/19)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.addons import import_addon, import_catalog, list_addons, set_addon_enabled
from app.engine import EngineError


def make_zip(manifest: dict, files: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("addon.json", json.dumps(manifest))
        for name, content in (files or {"assets/readme.txt": "ok"}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


MANIFEST = {
    "id": "demo-pack",
    "name": "Demo Pack",
    "version": "1.0.0",
    "requires_core": "2.x",
    "slots": ["image"],
    "description": "demo",
}


class AddonManagerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name) / "data"

    def test_importa_desactivado_y_activa(self):
        imported = import_addon(self.data, make_zip(MANIFEST))
        self.assertEqual(imported["id"], "demo-pack")
        self.assertFalse(imported["enabled"])
        self.assertEqual(list_addons(self.data)[0]["enabled"], False)
        set_addon_enabled(self.data, "demo-pack", True)
        self.assertEqual(list_addons(self.data)[0]["enabled"], True)
        set_addon_enabled(self.data, "demo-pack", False)
        self.assertEqual(list_addons(self.data)[0]["enabled"], False)

    def test_rechaza_zip_sin_manifiesto(self):
        with self.assertRaises(EngineError):
            import_addon(self.data, b"no-zip")

    def test_rechaza_ruta_insegura(self):
        raw = make_zip(MANIFEST, {"../evil.txt": "x"})
        with self.assertRaises(EngineError):
            import_addon(self.data, raw)

    def test_rechaza_requires_core_incompatible(self):
        bad = dict(MANIFEST, id="futuro", requires_core=">=3.0")
        imported = import_addon(self.data, make_zip(bad))
        self.assertFalse(imported["valid"])
        with self.assertRaises(EngineError):
            set_addon_enabled(self.data, "futuro", True)

    def test_ids_duplicados(self):
        import_addon(self.data, make_zip(MANIFEST))
        with self.assertRaises(EngineError):
            import_addon(self.data, make_zip(MANIFEST))

    def test_slots_exclusivos(self):
        import_addon(self.data, make_zip(MANIFEST))
        second = dict(MANIFEST, id="demo-pack-2", name="Demo 2")
        import_addon(self.data, make_zip(second))
        set_addon_enabled(self.data, "demo-pack", True)
        with self.assertRaises(EngineError):
            set_addon_enabled(self.data, "demo-pack-2", True)
        set_addon_enabled(self.data, "demo-pack", False)
        set_addon_enabled(self.data, "demo-pack-2", True)
        self.assertTrue(next(item for item in list_addons(self.data) if item["id"] == "demo-pack-2")["enabled"])

    def test_catalogo_compatible(self):
        payload = {
            "schema": "waifu.addons-catalog/v1",
            "requires_core": "2.x",
            "addons": [{"id": "catalog-pack", "name": "Catalog", "version": "1.0", "slots": ["image"]}],
        }
        result = import_catalog(self.data, payload)
        self.assertEqual(result["count"], 1)
        self.assertTrue((self.data / "addons" / "catalog.json").is_file())

    def test_catalogo_incompatible(self):
        with self.assertRaises(EngineError):
            import_catalog(
                self.data,
                {"schema": "waifu.addons-catalog/v1", "requires_core": ">=3.0", "addons": []},
            )


if __name__ == "__main__":
    unittest.main()
