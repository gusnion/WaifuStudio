"""Tests CPU del store de generaciones (M8-21). Sin red ni GPU."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.engine import EngineError
from app.store import Store


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "nested" / "waifu.db"
        self.store = Store(self.db_path)
        self.store.init()


class InitTests(StoreTestCase):
    def test_init_crea_directorio_padre_y_tabla(self):
        self.assertTrue(self.db_path.parent.is_dir())
        self.assertTrue(self.db_path.is_file())
        with closing(sqlite3.connect(str(self.db_path))) as connection:
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(generations)")
            ]
        self.assertEqual(
            columns,
            [
                "id",
                "created_at",
                "model_id",
                "prompt",
                "negative",
                "params",
                "status",
                "outputs",
                "error",
                "kind",
            ],
        )


class AddGetTests(StoreTestCase):
    def test_add_devuelve_id_incremental_y_defaults(self):
        first = self.store.add("anima-2.9b-preview", "1girl, smile")
        second = self.store.add("anima-2.9b-preview", "1girl, run")
        self.assertEqual((first, second), (1, 2))
        row = self.store.get(first)
        self.assertEqual(row["id"], first)
        self.assertEqual(row["model_id"], "anima-2.9b-preview")
        self.assertEqual(row["prompt"], "1girl, smile")
        self.assertEqual(row["negative"], "")
        self.assertEqual(row["params"], {})
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["outputs"], [])
        self.assertIsNone(row["error"])
        self.assertTrue(row["created_at"])

    def test_add_serializa_params_y_outputs(self):
        gen_id = self.store.add(
            "m",
            "p",
            negative="worst quality",
            params={"steps": 20, "cfg": 4.0},
            status="running",
        )
        self.store.update(gen_id, outputs=[{"path": "a.png", "bytes": 10}])
        row = self.store.get(gen_id)
        self.assertEqual(row["params"], {"steps": 20, "cfg": 4.0})
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["outputs"], [{"path": "a.png", "bytes": 10}])

    def test_kind_default_image_y_roundtrip(self):
        image_id = self.store.add("m", "p")
        video_id = self.store.add("m", "p", kind="video")
        self.assertEqual(self.store.get(image_id)["kind"], "image")
        self.assertEqual(self.store.get(video_id)["kind"], "video")
        self.assertEqual(
            [row["kind"] for row in self.store.list()], ["image", "video"]
        )
        self.assertTrue(self.store.update(video_id, kind="image"))
        self.assertEqual(self.store.get(video_id)["kind"], "image")

    def test_get_inexistente_devuelve_none(self):
        self.assertIsNone(self.store.get(999))

    def test_persistencia_al_reabrir(self):
        gen_id = self.store.add("m", "p", params={"seed": 42})
        reopened = Store(self.db_path)
        reopened.init()
        self.assertEqual(reopened.count(), 1)
        self.assertEqual(reopened.get(gen_id)["params"], {"seed": 42})

    def test_params_no_serializables_lanzan_engine_error(self):
        with self.assertRaises(EngineError):
            self.store.add("m", "p", params={1, 2})


class ListCountTests(StoreTestCase):
    def test_list_orden_y_paginacion(self):
        for index in range(5):
            self.store.add("m", f"prompt {index}")
        ids = [row["id"] for row in self.store.list()]
        self.assertEqual(ids, [1, 2, 3, 4, 5])
        self.assertEqual([row["id"] for row in self.store.list(limit=2)], [1, 2])
        self.assertEqual(
            [row["id"] for row in self.store.list(limit=2, offset=2)], [3, 4]
        )
        self.assertEqual(self.store.list(limit=10, offset=10), [])

    def test_count(self):
        self.assertEqual(self.store.count(), 0)
        self.store.add("m", "p")
        self.store.add("m", "p")
        self.assertEqual(self.store.count(), 2)


class UpdateTests(StoreTestCase):
    def test_update_parcial_y_roundtrip(self):
        gen_id = self.store.add("m", "p")
        self.assertTrue(self.store.update(gen_id, status="done"))
        self.assertTrue(
            self.store.update(gen_id, outputs=[{"path": "a.png"}], error=None)
        )
        self.assertTrue(self.store.update(gen_id, error="fallo x"))
        row = self.store.get(gen_id)
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["outputs"], [{"path": "a.png"}])
        self.assertEqual(row["error"], "fallo x")

    def test_update_sin_campos_solo_comprueba_existencia(self):
        gen_id = self.store.add("m", "p")
        self.assertTrue(self.store.update(gen_id))
        self.assertFalse(self.store.update(999))

    def test_update_inexistente_devuelve_false(self):
        self.assertFalse(self.store.update(999, status="done"))


class MalformedJsonTests(StoreTestCase):
    def _corrupt_params(self, gen_id: int) -> None:
        with closing(sqlite3.connect(str(self.db_path))) as connection, connection:
            connection.execute(
                "UPDATE generations SET params = '{' WHERE id = ?", (gen_id,)
            )

    def test_get_con_json_malformado_lanza_engine_error(self):
        gen_id = self.store.add("m", "p")
        self._corrupt_params(gen_id)
        with self.assertRaises(EngineError):
            self.store.get(gen_id)

    def test_list_con_json_malformado_lanza_engine_error(self):
        gen_id = self.store.add("m", "p")
        self._corrupt_params(gen_id)
        with self.assertRaises(EngineError):
            self.store.list()


if __name__ == "__main__":
    unittest.main()
