"""Tests CPU de OCs con referencias (M9-B1) y rasgos/extras (M9-B3).

Sin red ni GPU.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from app import loras
from app.characters import (
    CharacterStore,
    is_sheet,
    prompt_from_extras,
    prompt_from_tags,
    split_character_tags,
)
from app.engine import EngineError

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"waifu-ref"

LEGACY_SCHEMA = """
CREATE TABLE characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    tags TEXT NOT NULL DEFAULT '[]',
    preprompt TEXT NOT NULL DEFAULT 'glossy',
    rating TEXT NOT NULL DEFAULT 'sfw',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""


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
            [
                "id",
                "name",
                "tags",
                "extras",
                "preprompt",
                "rating",
                "notes",
                "created_at",
            ],
        )
        self.assertEqual(ref_columns, ["id", "character_id", "relpath", "created_at"])

    def test_init_idempotente(self):
        self.store.init()
        self.assertEqual(self.store.list(), [])


class ExtrasMigrationTests(unittest.TestCase):
    def test_init_migra_extras_en_bd_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "nested" / "waifu.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(str(db_path))) as conn, conn:
                conn.execute(LEGACY_SCHEMA)
                conn.execute(
                    "INSERT INTO characters (name, tags, created_at) "
                    "VALUES (?, ?, ?)",
                    ("Vieja", json.dumps(["long hair"]), "2026-01-01"),
                )
            store = CharacterStore(db_path, refs_root=root / "refs")
            store.init()
            store.init()
            with closing(sqlite3.connect(str(db_path))) as conn:
                columns = [
                    row[1] for row in conn.execute("PRAGMA table_info(characters)")
                ]
            self.assertIn("extras", columns)
            row = store.get(1)
            self.assertEqual(row["tags"], ["long hair"])
            self.assertEqual(row["extras"], [])

    def test_get_separa_extras_legacy_de_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "waifu.db"
            with closing(sqlite3.connect(str(db_path))) as conn, conn:
                conn.execute(LEGACY_SCHEMA)
                conn.execute(
                    "INSERT INTO characters (name, tags, created_at) "
                    "VALUES (?, ?, ?)",
                    (
                        "Vieja",
                        json.dumps(["long hair", "school uniform", "smile"]),
                        "2026-01-01",
                    ),
                )
            store = CharacterStore(db_path, refs_root=root / "refs")
            store.init()
            row = store.get(1)
            self.assertEqual(row["tags"], ["long hair"])
            self.assertEqual(row["extras"], ["school uniform", "smile"])
            self.assertEqual(store.list()[0]["extras"], ["school uniform", "smile"])
            self.assertTrue(store.update(1, tags=row["tags"]))
            self.assertEqual(store.get(1)["extras"], ["school uniform", "smile"])


class AddGetTests(CharacterStoreTestCase):
    def test_add_devuelve_id_y_defaults(self):
        char_id = self.store.add("Aiko", ["long hair", "blue eyes"])
        self.assertEqual(char_id, 1)
        row = self.store.get(char_id)
        self.assertEqual(row["id"], char_id)
        self.assertEqual(row["name"], "Aiko")
        self.assertEqual(row["tags"], ["long hair", "blue eyes"])
        self.assertEqual(row["extras"], [])
        self.assertEqual(row["preprompt"], "glossy")
        self.assertEqual(row["rating"], "sfw")
        self.assertEqual(row["notes"], "")
        self.assertTrue(row["created_at"])
        self.assertEqual(self.store.list(), [row])

    def test_add_separa_extras_sin_perder_nada(self):
        char_id = self.store.add(
            "Aiko", ["long hair", "school uniform", "from above", "long hair"]
        )
        row = self.store.get(char_id)
        self.assertEqual(row["tags"], ["long hair"])
        self.assertEqual(row["extras"], ["school uniform", "from above"])

    def test_add_acepta_extras_explicito_y_dedup(self):
        char_id = self.store.add(
            "Aiko",
            ["long hair", "blue sky"],
            extras=["school uniform", "Blue Sky", "nsfw"],
        )
        row = self.store.get(char_id)
        self.assertEqual(row["tags"], ["long hair"])
        self.assertEqual(row["extras"], ["blue sky", "school uniform", "nsfw"])

    def test_add_extras_invalido(self):
        with self.assertRaises(EngineError):
            self.store.add("Aiko", ["long hair"], extras="school uniform")
        with self.assertRaises(EngineError):
            self.store.add("Aiko", ["long hair"], extras=["school uniform", 3])

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

    def test_update_tags_preserva_extras_y_suma_los_nuevos(self):
        char_id = self.store.add(
            "Aiko", ["long hair", "school uniform", "from above"]
        )
        self.assertTrue(self.store.update(char_id, tags=["twintails", "blue sky"]))
        row = self.store.get(char_id)
        self.assertEqual(row["tags"], ["twintails"])
        self.assertEqual(
            row["extras"], ["school uniform", "from above", "blue sky"]
        )
        self.assertTrue(self.store.update(char_id, tags=["long hair"]))
        row = self.store.get(char_id)
        self.assertEqual(row["tags"], ["long hair"])
        self.assertEqual(
            row["extras"], ["school uniform", "from above", "blue sky"]
        )

    def test_update_extras_reemplaza(self):
        char_id = self.store.add("Aiko", ["long hair", "school uniform"])
        self.assertTrue(self.store.update(char_id, extras=["nsfw"]))
        row = self.store.get(char_id)
        self.assertEqual(row["tags"], ["long hair"])
        self.assertEqual(row["extras"], ["nsfw"])
        self.assertTrue(self.store.update(char_id, extras=[]))
        self.assertEqual(self.store.get(char_id)["extras"], [])

    def test_update_tags_con_extras_reemplaza_base(self):
        char_id = self.store.add("Aiko", ["long hair", "school uniform"])
        self.assertTrue(
            self.store.update(char_id, tags=["twintails", "blue sky"], extras=["nsfw"])
        )
        row = self.store.get(char_id)
        self.assertEqual(row["tags"], ["twintails"])
        self.assertEqual(row["extras"], ["nsfw", "blue sky"])


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

    def test_add_ref_con_name_conserva_el_nombre(self):
        char_id = self.store.add("Aiko", [])
        relpath = self.store.add_ref(
            char_id, self.make_file("sheet_manual.png"), name="sheet_manual.png"
        )
        self.assertEqual(relpath, f"{char_id}/sheet_manual.png")
        target = self.refs_root / relpath
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), PNG_BYTES)
        self.assertTrue(is_sheet(relpath))

    def test_add_ref_in_place_no_recopia(self):
        char_id = self.store.add("Aiko", [])
        directory = self.refs_root / str(char_id)
        directory.mkdir(parents=True, exist_ok=True)
        sheet = directory / "sheet_inplace.png"
        sheet.write_bytes(PNG_BYTES)
        relpath = self.store.add_ref(char_id, sheet, name=sheet.name)
        self.assertEqual(relpath, f"{char_id}/sheet_inplace.png")
        self.assertEqual(sheet.read_bytes(), PNG_BYTES)
        self.assertEqual(len(self.store.refs(char_id)), 1)

    def test_add_ref_name_invalido(self):
        char_id = self.store.add("Aiko", [])
        src = self.make_file("a.png")
        for name in ("../escapa.png", "sub/dir.png", "otra.gif", "", "sin_extension"):
            with self.subTest(name=name):
                with self.assertRaises(EngineError):
                    self.store.add_ref(char_id, src, name=name)
        self.assertEqual(self.store.refs(char_id), [])

    def test_first_non_sheet_ref_salta_hojas(self):
        char_id = self.store.add("Aiko", [])
        normal = self.store.add_ref(char_id, self.make_file("a.png"))
        self.store.add_ref(
            char_id, self.make_file("b.png"), name="sheet_b.png"
        )
        ref = self.store.first_non_sheet_ref(char_id)
        self.assertIsNotNone(ref)
        self.assertEqual(ref["relpath"], normal)

    def test_first_non_sheet_ref_none_si_solo_hay_hojas(self):
        char_id = self.store.add("Aiko", [])
        self.assertIsNone(self.store.first_non_sheet_ref(char_id))
        self.store.add_ref(char_id, self.make_file("a.png"), name="sheet_a.png")
        self.assertIsNone(self.store.first_non_sheet_ref(char_id))

    def test_first_non_sheet_ref_oc_desconocido(self):
        with self.assertRaises(EngineError):
            self.store.first_non_sheet_ref(99)


class IsSheetTests(unittest.TestCase):
    def test_prefijo_sheet_en_el_nombre(self):
        self.assertTrue(is_sheet("3/sheet_abc.png"))
        self.assertTrue(is_sheet(Path("3/sheet_abc.webp")))
        self.assertTrue(is_sheet("sheet_suelta.png"))

    def test_otros_nombres_no_son_hoja(self):
        self.assertFalse(is_sheet("3/abc.png"))
        self.assertFalse(is_sheet("3/sheet.png"))
        self.assertFalse(is_sheet("3/Sheet_abc.png"))
        self.assertFalse(is_sheet("3/mi_sheet_abc.png"))
        self.assertFalse(is_sheet("sheet_x/img.png"))


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


class SplitCharacterTagsTests(unittest.TestCase):
    def test_catalogo_real_separa_rasgos_y_extras(self):
        split = split_character_tags(
            [
                "long hair",
                "blue eyes",
                "school uniform",
                "from above",
                "nsfw",
                "blue sky",
            ]
        )
        self.assertEqual(split["traits"], ["long hair", "blue eyes"])
        self.assertEqual(
            split["extras"],
            ["school uniform", "from above", "nsfw", "blue sky"],
        )

    def test_calidad_sujeto_y_desconocidos_van_a_extras(self):
        split = split_character_tags(
            ["masterpiece", "1girl", "tag raro", "twintails", "smile"]
        )
        self.assertEqual(split["traits"], ["twintails"])
        self.assertEqual(
            split["extras"], ["masterpiece", "1girl", "tag raro", "smile"]
        )

    def test_normaliza_dedup_y_vacios(self):
        split = split_character_tags([" long hair ", "LONG HAIR", "", "  "])
        self.assertEqual(split["traits"], ["long hair"])
        self.assertEqual(split["extras"], [])

    def test_entrada_invalida(self):
        with self.assertRaises(EngineError):
            split_character_tags("long hair")
        with self.assertRaises(EngineError):
            split_character_tags(["long hair", 3])


class PromptFromExtrasTests(unittest.TestCase):
    def test_dedup_y_orden_estable(self):
        self.assertEqual(
            prompt_from_extras(["school uniform", "blue sky", "school uniform"]),
            "school uniform, blue sky",
        )

    def test_dedup_case_insensitive_y_vacios(self):
        self.assertEqual(
            prompt_from_extras(["Blue Sky", "blue sky", "", " nsfw "]),
            "Blue Sky, nsfw",
        )
        self.assertEqual(prompt_from_extras([]), "")

    def test_entrada_invalida(self):
        with self.assertRaises(EngineError):
            prompt_from_extras("school uniform")
        with self.assertRaises(EngineError):
            prompt_from_extras(["school uniform", 3])


class ProfileTests(CharacterStoreTestCase):
    def write_loras(self, entries: list[dict]) -> Path:
        path = self.root / "loras.json"
        path.write_text(
            json.dumps({"version": 1, "loras": entries}), encoding="utf-8"
        )
        return path

    def lora_entry(self, lora_id: str, trigger: str = "aiko") -> dict:
        return {
            "id": lora_id,
            "family": "anima",
            "file": f"{lora_id}.safetensors",
            "display_name": lora_id,
            "trigger": trigger,
            "default_weight": 0.8,
            "source": "test",
            "license": "test",
        }

    def test_auto_sin_lora_usa_rasgos_y_expone_extras(self):
        char_id = self.store.add(
            "Aiko", ["long hair", "blue eyes", "school uniform"]
        )
        path = self.write_loras([self.lora_entry("otro-lora")])
        with mock.patch.object(loras, "DEFAULT_PATH", path):
            payload = self.store.profile(char_id)
        self.assertEqual(payload["mode"], "traits")
        self.assertEqual(payload["text"], "long hair, blue eyes")
        self.assertEqual(payload["extras"], ["school uniform"])
        self.assertIsNone(payload["lora"])

    def test_auto_con_lora_usa_trigger(self):
        char_id = self.store.add("Aiko", ["long hair"])
        path = self.write_loras([self.lora_entry(f"oc-{char_id}")])
        with mock.patch.object(loras, "DEFAULT_PATH", path):
            payload = self.store.profile(char_id)
        self.assertEqual(payload["mode"], "trigger")
        self.assertEqual(payload["text"], "aiko")
        self.assertEqual(
            payload["lora"],
            {"id": f"oc-{char_id}", "default_weight": 0.8},
        )

    def test_auto_con_trigger_vacio_cae_a_rasgos(self):
        char_id = self.store.add("Aiko", ["long hair"])
        path = self.write_loras([self.lora_entry(f"oc-{char_id}", trigger="")])
        with mock.patch.object(loras, "DEFAULT_PATH", path):
            payload = self.store.profile(char_id)
        self.assertEqual(payload["mode"], "traits")
        self.assertEqual(payload["text"], "long hair")
        self.assertEqual(payload["lora"]["id"], f"oc-{char_id}")

    def test_trigger_explicito(self):
        char_id = self.store.add("Aiko", ["long hair"])
        path = self.write_loras([self.lora_entry(f"oc-{char_id}", "mika_oc")])
        with mock.patch.object(loras, "DEFAULT_PATH", path):
            payload = self.store.profile(char_id, "trigger")
        self.assertEqual(payload["mode"], "trigger")
        self.assertEqual(payload["text"], "mika_oc")

    def test_traits_explicito_con_lora(self):
        char_id = self.store.add("Aiko", ["long hair"])
        path = self.write_loras([self.lora_entry(f"oc-{char_id}")])
        with mock.patch.object(loras, "DEFAULT_PATH", path):
            payload = self.store.profile(char_id, "traits")
        self.assertEqual(payload["mode"], "traits")
        self.assertEqual(payload["text"], "long hair")
        self.assertEqual(payload["lora"]["id"], f"oc-{char_id}")

    def test_trigger_sin_lora_error(self):
        char_id = self.store.add("Aiko", ["long hair"])
        path = self.write_loras([self.lora_entry("otro-lora")])
        with mock.patch.object(loras, "DEFAULT_PATH", path):
            with self.assertRaises(EngineError):
                self.store.profile(char_id, "trigger")

    def test_mode_invalido_y_oc_inexistente(self):
        char_id = self.store.add("Aiko", [])
        with self.assertRaises(EngineError):
            self.store.profile(char_id, "nope")
        with self.assertRaises(EngineError):
            self.store.profile(99)


if __name__ == "__main__":
    unittest.main()
