"""Tests CPU del gestor de addons (PL-18/19)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.addons import (
    addon_model_entries,
    import_addon,
    import_catalog,
    list_addons,
    list_video_engines,
    set_addon_enabled,
)
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

    def test_c51_06_addon_model_entries_estados_y_movable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"
            models_dir = Path(tmp_dir) / "comfy_models"
            models_dir.mkdir(parents=True, exist_ok=True)
            addon_dir = data_dir / "addons" / "models-pack"
            archive_dir = addon_dir / "models" / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)

            # Archivo activo en comfy models
            (models_dir / "model_active.safetensors").write_bytes(b"active")
            # Archivo archivado en data/addons/<id>/models/archive
            (archive_dir / "model_archived.safetensors").write_bytes(b"archived")

            manifest = {
                "id": "models-pack",
                "name": "Models Pack",
                "version": "1.0.0",
                "requires_core": "2.x",
                "slots": ["image"],
                "models": [
                    {"id": "m-active", "file": "model_active.safetensors"},
                    {"id": "m-archived", "file": "model_archived.safetensors"},
                    {"id": "m-uninstalled", "file": "model_missing.safetensors"},
                ],
            }

            # Prueba directa con addon_model_entries
            entries = addon_model_entries(addon_dir, manifest, models_dir)
            by_id = {e["id"]: e for e in entries}

            self.assertEqual(by_id["m-active"]["state"], "activo")
            self.assertEqual(by_id["m-active"]["path"], str(models_dir / "model_active.safetensors"))
            self.assertEqual(by_id["m-active"]["owner_addon"], "models-pack")
            self.assertTrue(by_id["m-active"]["movable"])

            self.assertEqual(by_id["m-archived"]["state"], "archivado")
            self.assertEqual(by_id["m-archived"]["path"], str(archive_dir / "model_archived.safetensors"))
            self.assertEqual(by_id["m-archived"]["owner_addon"], "models-pack")
            self.assertTrue(by_id["m-archived"]["movable"])

            self.assertEqual(by_id["m-uninstalled"]["state"], "no instalado")
            self.assertEqual(by_id["m-uninstalled"]["path"], "")
            self.assertEqual(by_id["m-uninstalled"]["owner_addon"], "models-pack")
            self.assertTrue(by_id["m-uninstalled"]["movable"])

            # movable es False si owner_addon esta vacio
            entries_no_owner = addon_model_entries(
                addon_dir=Path(""),
                manifest={"id": "", "models": [{"id": "m1", "file": "model_active.safetensors"}]},
                models_dir=models_dir,
            )
            self.assertFalse(entries_no_owner[0]["movable"])
            self.assertEqual(entries_no_owner[0]["owner_addon"], "")

            # Verificacion a traves de import_addon y list_addons con comfy_models_dir
            manifest_imported = dict(manifest, id="models-pack-imported")
            import_addon(data_dir, make_zip(manifest_imported))
            imported_archive = data_dir / "addons" / "models-pack-imported" / "models" / "archive"
            imported_archive.mkdir(parents=True, exist_ok=True)
            (imported_archive / "model_archived.safetensors").write_bytes(b"archived")

            listed = list_addons(data_dir, comfy_models_dir=models_dir)
            addon_info = next(item for item in listed if item["id"] == "models-pack-imported")
            list_by_id = {m["id"]: m for m in addon_info["models"]}

            self.assertEqual(list_by_id["m-active"]["state"], "activo")
            self.assertTrue(list_by_id["m-active"]["movable"])
            self.assertEqual(list_by_id["m-archived"]["state"], "archivado")
            self.assertTrue(list_by_id["m-archived"]["movable"])
            self.assertEqual(list_by_id["m-uninstalled"]["state"], "no instalado")
            self.assertTrue(list_by_id["m-uninstalled"]["movable"])

    def test_c51_07_requires_capabilities_declarada_y_no_declarada(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"

            # 1. Capacidad declarada (presente en registry/capabilities.json, ej: engine.video.wan)
            manifest_ok = dict(
                MANIFEST,
                id="cap-ok-pack",
                name="Cap OK Pack",
                requires_capabilities=["engine.video.wan"],
            )
            import_addon(data_dir, make_zip(manifest_ok))

            # 2. Capacidad no declarada (no existe en registry/capabilities.json)
            manifest_missing = dict(
                MANIFEST,
                id="cap-missing-pack",
                name="Cap Missing Pack",
                requires_capabilities=["capacidad.inexistente.fantasma"],
            )
            import_addon(data_dir, make_zip(manifest_missing))

            addons = {a["id"]: a for a in list_addons(data_dir)}

            self.assertTrue(addons["cap-ok-pack"]["valid"])
            self.assertEqual(addons["cap-ok-pack"]["reason"], "")
            self.assertEqual(addons["cap-ok-pack"]["requires_capabilities"], ["engine.video.wan"])

            self.assertFalse(addons["cap-missing-pack"]["valid"])
            self.assertEqual(addons["cap-missing-pack"]["reason"], "capacidad no declarada")
            self.assertEqual(
                addons["cap-missing-pack"]["requires_capabilities"],
                ["capacidad.inexistente.fantasma"],
            )

    def test_c51_07_list_video_engines_addon_enabled_echo_y_wan_base(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"

            manifest_echo = dict(
                MANIFEST,
                id="video-echo-pack",
                name="Video Echo Pack",
                slots=["video"],
                video_engines={
                    "echo": {
                        "label": "Echo Video Engine",
                        "workflow": "workflows/echo_video.json",
                    }
                },
            )
            import_addon(data_dir, make_zip(manifest_echo))

            # Antes de habilitar: solo motores base
            engines_before = list_video_engines(data_dir)
            self.assertIn("wan", engines_before)
            self.assertNotIn("echo", engines_before)

            # Tras habilitar el addon: aparece echo y la base wan sigue
            set_addon_enabled(data_dir, "video-echo-pack", True)
            engines_after = list_video_engines(data_dir)

            self.assertIn("wan", engines_after)
            self.assertIn("echo", engines_after)
            self.assertEqual(engines_after["echo"]["label"], "Echo Video Engine")
            self.assertEqual(engines_after["echo"]["workflow"], "workflows/echo_video.json")



if __name__ == "__main__":
    unittest.main()
