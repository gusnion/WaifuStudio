"""Tests CPU del catalogo del editor Qwen-Image 2.1 UC (M10-6b).

Sin red, GPU ni engine: solo validacion del catalogo local
``registry/editor_models-v1.json`` y de su loader (`app.editor_models`).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.editor_models import (
    CATALOG_VERSION,
    EDITOR_CATALOG_PATH,
    editor_model,
    load_editor_model,
)
from app.engine import EngineError

UC_FILES = [
    "unet/qwen-image-2.1-UC-Q4_K_M.gguf",
    "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
    "vae/qwen_image_2.1_vae_bf16.safetensors",
]


def make_catalog(**overrides) -> dict:
    payload = {
        "version": CATALOG_VERSION,
        "id": "qwen-image-2.1",
        "display_name": "Qwen-Image 2.1 UC (Editor)",
        "note": "La descarga e integración llegan en M10",
        "files": list(UC_FILES),
    }
    payload.update(overrides)
    return payload


class EditorCatalogFileTests(unittest.TestCase):
    def test_catalogo_del_repo_usa_los_nombres_uc(self):
        self.assertTrue(EDITOR_CATALOG_PATH.is_file())
        model = load_editor_model()
        self.assertEqual(model.id, "qwen-image-2.1")
        self.assertEqual(model.display_name, "Qwen-Image 2.1 UC (Editor)")
        self.assertIn("M10", model.note)
        self.assertEqual(list(model.files), UC_FILES)
        self.assertNotIn("vae/qwen_image_vae.safetensors", model.files)

    def test_singleton_equivale_al_catalogo_del_repo(self):
        self.assertEqual(editor_model(), load_editor_model())


class EditorCatalogValidationTests(unittest.TestCase):
    def load_payload(self, payload: object):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalogo.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return load_editor_model(path)

    def test_version_invalida(self):
        for version in (2, "1", True, None):
            with self.subTest(version=version):
                with self.assertRaises(EngineError):
                    self.load_payload(make_catalog(version=version))

    def test_campos_de_texto_invalidos(self):
        for overrides in (
            {"id": ""},
            {"id": 7},
            {"display_name": "   "},
            {"note": None},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(EngineError):
                    self.load_payload(make_catalog(**overrides))

    def test_files_vacio_o_no_lista(self):
        for files in ([], "x", None, ["unet/a.gguf", 7]):
            with self.subTest(files=files):
                with self.assertRaises(EngineError):
                    self.load_payload(make_catalog(files=files))

    def test_archivo_fuera_de_models(self):
        for file in (
            "C:/modelos/a.gguf",
            "/unet/a.gguf",
            "../a.gguf",
            "unet/../../a.gguf",
            "unet\\a.gguf",
            "",
        ):
            with self.subTest(file=file):
                with self.assertRaises(EngineError):
                    self.load_payload(make_catalog(files=[file]))

    def test_archivo_duplicado(self):
        with self.assertRaises(EngineError):
            self.load_payload(make_catalog(files=[UC_FILES[0], UC_FILES[0]]))

    def test_fichero_inexistente(self):
        with self.assertRaises(EngineError):
            load_editor_model(Path(tempfile.gettempdir()) / "no-existe-waifu.json")

    def test_json_invalido(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalogo.json"
            path.write_text("{no-json", encoding="utf-8")
            with self.assertRaises(EngineError):
                load_editor_model(path)


if __name__ == "__main__":
    unittest.main()
