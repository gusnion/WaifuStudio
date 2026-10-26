"""Tests de defaults por modelo (PL-22)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.registry import ModelRegistry
from app.routes.models import _validate_defaults
from app.server import create_app
from app.store import Store


class ValidateDefaultsTests(unittest.TestCase):
    def test_acepta_claves_validas(self):
        self.assertEqual(_validate_defaults({"steps": 8, "cfg": 4}), {"steps": 8, "cfg": 4.0})

    def test_rechaza_clave_desconocida(self):
        with self.assertRaises(Exception):
            _validate_defaults({"nope": 1})

    def test_rechaza_tipos(self):
        for payload in ({"steps": 0}, {"steps": True}, {"cfg": "x"}, {"seed": 1.5}):
            with self.subTest(payload=payload):
                with self.assertRaises(Exception):
                    _validate_defaults(payload)


class DefaultsRouteTests(unittest.TestCase):
    def test_get_y_put_persisten_en_registro_de_usuario(self):
        from tests.test_server import REGISTRY_FIXTURE, make_config

        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            cfg.data_dir.mkdir(parents=True)
            registry = ModelRegistry.load(REGISTRY_FIXTURE)
            store = Store(cfg.data_dir / "waifu.db")
            store.init()
            app = create_app(
                config=cfg, store=store, registry=registry, start_worker=False
            )
            with TestClient(app) as client:
                model_id = registry.models[0].id
                original = client.get(f"/api/models/{model_id}/defaults")
                self.assertEqual(original.status_code, 200)
                response = client.put(
                    f"/api/models/{model_id}/defaults",
                    json={"steps": 12, "cfg": 3.5},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["defaults"]["steps"], 12)
                saved = (cfg.data_dir / "registry" / "models.json").read_text(
                    encoding="utf-8"
                )
                self.assertIn('"steps": 12', saved)


if __name__ == "__main__":
    unittest.main()
