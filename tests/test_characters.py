"""Tests CPU de OCs con referencias (M9-B1). Sin red ni GPU."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.characters import CharacterStore, prompt_from_tags
from app.engine import EngineError

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"waifu-ref"


class CharacterStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "nested" / "waifu.db"
        self.refs_root = self.root / "refs"
        self.store = CharacterStore(self.db_path, refs_root=self.refs_root)
        self.store.init()

    def make_file(self, name: str, data: bytes = PNG_BYTES) -> Path:
        path = self.root / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


class InitTests(CharacterStoreTestCase):
    def test_init_crea_directorio_y_tablas(self):
        self.assertTrue(self.db_path.parent.is_dir())
        self.assertTrue(self.db_path.is_file())
        with closing(sqlite3.connect(str(self.db_path))) as connection:
            char_columns = [
                row[1] for row in connection.execute("PRAGMA table_info(characters)")
            ]
            ref_columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(character_refs)")
            ]
        self.assertEqual(
            char_columns,
            ["id", "name", "tags", "preprompt", "rating", "notes", "created_at"],
        )
        self.assertEqual(ref_columns, ["id", "character_id", "relpath", "created_at"])

    def test_init_idempotente(self):
        self.store.init()
        self.assertEqual(self.store.list(), [])


class AddGetTests(CharacterStoreTestCase):
    def test_add_devuelve_id_y_defaults(self):
        char_id = self.store.add("Aiko", ["long hair", "smile"])
        self.assertEqual(char_id, 1)
        row = self.store.get(char_id)
        self.assertEqual(row["id"], char_id)
        self.assertEqual(row["name"], "Aiko")
        self.assertEqual(row["tags"], ["long hair", "smile"])
        self.assertEqual(row["preprompt"], "glossy")
        self.assertEqual(row["rating"], "sfw")
        self.assertEqual(row["notes"], "")
        self.assertTrue(row["created_at"])
        self.assertEqual(self.store.list(), [row])

    def test_add_normaliza_name_y_tags(self):
        char_id = self.store.add("  Aiko  ", [" long hair ", "long hair", "", "  "])
        row = self.store.get(char_id)
        self.assertEqual(row["name"], "Aiko")
        self.assertEqual(row["tags"], ["long hair"])

    def test_add_acepta_preprompt_rating_y_notes(self):
        char_id = self.store.add(
            "Aiko",
            [],
            preprompt="anima_default",
            rating="nsfw",
            notes="rubia",
        )
        row = self.store.get(char_id)
        self.assertEqual(row["preprompt"], "anima_default")
        self.assertEqual(row["rating"], "nsfw")
        self.assertEqual(row["notes"], "rubia")

    def test_get_inexistente_none(self):
        self.assertIsNone(self.store.get(99))

    def test_persistencia_al_reabrir(self):
        self.store.add("Aiko", ["smile"])
        reopened = CharacterStore(self.db_path, refs_root=self.refs_root)
        reopened.init()
        self.assertEqual([row["name"] for row in reopened.list()], ["Aiko"])


class ValidationTests(CharacterStoreTestCase):
    def test_name_vacio_o_no_str(self):
        for name in ("", "   ", None, 3):
            with self.subTest(name=name), self.assertRaises(EngineError):
                self.store.add(name, [])

    def test_name_duplicado(self):
        self.store.add("Aiko", [])
        with self.assertRaises(EngineError):
            self.store.add("Aiko", [])
        self.assertEqual(len(self.store.list()), 1)

    def test_tags_no_lista_o_con_no_str(self):
        with self.assertRaises(EngineError):
            self.store.add("Aiko", "long hair")
        with self.assertRaises(EngineError):
            self.store.add("Aiko", ["smile", 3])

    def test_preprompt_desconocido(self):
        with self.assertRaises(EngineError):
            self.store.add("Aiko", [], preprompt="inventado")

    def test_rating_invalido(self):
        with self.assertRaises(EngineError):
            self.store.add("Aiko", [], rating="explicit")

    def test_notes_no_str(self):
        with self.assertRaises(EngineError):
            self.store.add("Aiko", [], notes=7)

    def test_update_valida_y_exige_unicidad(self):
        first = self.store.add("Aiko", [])
        second = self.store.add("Mika", [])
        with self.assertRaises(EngineError):
            self.store.update(second, name="Aiko")
        with self.assertRaises(EngineError):
            self.store.update(first, preprompt="inventado")
        with self.assertRaises(EngineError):
            self.store.update(first, rating="explicit")
        with self.assertRaises(EngineError):
            self.store.update(first, tags="smile")


class UpdateTests(CharacterStoreTestCase):
    def test_update_parcial(self):
        char_id = self.store.add("Aiko", ["long hair"])
        self.assertTrue(
            self.store.update(
                char_id,
                name="Mika",
                tags=["twintails"],
                preprompt="anima_default",
                rating="nsfw",
                notes="nueva",
            )
        )
        row = self.store.get(char_id)
        self.assertEqual(row["name"], "Mika")
        self.assertEqual(row["tags"], ["twintails"])
        self.assertEqual(row["preprompt"], "anima_default")
        self.assertEqual(row["rating"], "nsfw")
        self.assertEqual(row["notes"], "nueva")

    def test_update_sin_campos_solo_comprueba_existencia(self):
        char_id = self.store.add("Aiko", [])
        self.assertTrue(self.store.update(char_id))
        self.assertFalse(self.store.update(99))

    def test_update_inexistente_false(self):
        self.assertFalse(self.store.update(99, notes="x"))


class DeleteTests(CharacterStoreTestCase):
    def test_delete_borra_refs_y_carpeta(self):
        char_id = self.store.add("Aiko", [])
        self.store.add_ref(char_id, self.make_file("a.png"))
        directory = self.refs_root / str(char_id)
        self.assertTrue(directory.is_dir())
        self.assertTrue(self.store.delete(char_id))
        self.assertFalse(directory.exists())
        self.assertIsNone(self.store.get(char_id))
        self.assertFalse(self.store.delete(char_id))

    def test_delete_inexistente_false(self):
        self.assertFalse(self.store.delete(99))


class RefsTests(CharacterStoreTestCase):
    def test_add_ref_copia_y_relpath(self):
        char_id = self.store.add("Aiko", [])
        relpath = self.store.add_ref(char_id, self.make_file("a.PNG"))
        self.assertTrue(relpath.startswith(f"{char_id}/"))
        self.assertTrue(relpath.endswith(".png"))
        target = self.refs_root / relpath
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), PNG_BYTES)
        rows = self.store.refs(char_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["character_id"], char_id)
        self.assertEqual(rows[0]["relpath"], relpath)
        self.assertTrue(rows[0]["created_at"])

    def test_add_ref_extensiones_soportadas(self):
        char_id = self.store.add("Aiko", [])
        for index, extension in enumerate((".png", ".jpg", ".jpeg", ".webp")):
            with self.subTest(extension=extension):
                relpath = self.store.add_ref(
                    char_id, self.make_file(f"r{index}{extension}")
                )
                self.assertTrue(relpath.endswith(extension))
                self.assertTrue((self.refs_root / relpath).is_file())
        self.assertEqual(len(self.store.refs(char_id)), 4)

    def test_add_ref_src_inexistente_o_directorio(self):
        char_id = self.store.add("Aiko", [])
        with self.assertRaises(EngineError):
            self.store.add_ref(char_id, self.root / "nope.png")
        directory = self.root / "src"
        directory.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(EngineError):
            self.store.add_ref(char_id, directory)

    def test_add_ref_extension_no_soportada(self):
        char_id = self.store.add("Aiko", [])
        with self.assertRaises(EngineError):
            self.store.add_ref(char_id, self.make_file("a.gif"))

    def test_add_ref_oc_desconocido(self):
        with self.assertRaises(EngineError):
            self.store.add_ref(99, self.make_file("a.png"))

    def test_add_ref_respeta_refs_root_por_llamada(self):
        other = self.root / "otro"
        char_id = self.store.add("Aiko", [])
        relpath = self.store.add_ref(char_id, self.make_file("a.png"), refs_root=other)
        self.assertTrue((other / relpath).is_file())

    def test_remove_ref_borra_archivo_y_fila(self):
        char_id = self.store.add("Aiko", [])
        relpath = self.store.add_ref(char_id, self.make_file("a.png"))
        ref_id = self.store.refs(char_id)[0]["id"]
        target = self.refs_root / relpath
        self.assertTrue(self.store.remove_ref(char_id, ref_id))
        self.assertFalse(target.exists())
        self.assertEqual(self.store.refs(char_id), [])
        self.assertFalse(self.store.remove_ref(char_id, ref_id))

    def test_refs_oc_desconocido(self):
        with self.assertRaises(EngineError):
            self.store.refs(99)


class PromptFromTagsTests(unittest.TestCase):
    def test_dedup_y_orden_estable(self):
        self.assertEqual(
            prompt_from_tags(["long hair", "smile", "long hair"]),
            "long hair, smile",
        )

    def test_dedup_case_insensitive(self):
        self.assertEqual(
            prompt_from_tags(["Long Hair", "long hair", "LONG HAIR"]),
            "Long Hair",
        )

    def test_strip_y_vacios(self):
        self.assertEqual(prompt_from_tags(["  smile ", "", "   "]), "smile")
        self.assertEqual(prompt_from_tags([]), "")

    def test_entrada_invalida(self):
        with self.assertRaises(EngineError):
            prompt_from_tags("long hair")
        with self.assertRaises(EngineError):
            prompt_from_tags(["smile", 3])


if __name__ == "__main__":
    unittest.main()
