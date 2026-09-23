"""Tests CPU del catalogo starter de tags Danbooru (M9-B1). Sin red ni GPU."""

from __future__ import annotations

import json
import unittest

from app.engine import EngineError
from app.tags import (
    CATALOG_PATH,
    GROUPS,
    MAX_SEARCH_LIMIT,
    all_tags,
    by_group,
    get,
    list_groups,
    search,
)

EXPECTED_GROUPS = [
    "hair",
    "eyes",
    "face",
    "body",
    "outfit",
    "expression",
    "accessories",
    "setting",
    "action",
    "meta",
]
META_REQUIRED = (
    "score_7",
    "score_8",
    "score_9",
    "masterpiece",
    "best quality",
    "sfw",
    "nsfw",
    "uncensored",
)


class CatalogFileTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.tags = self.data["tags"]

    def test_json_valido_y_rango_de_tamano(self):
        self.assertEqual(set(self.data), {"schema_version", "descripcion", "groups", "tags"})
        self.assertEqual(self.data["groups"], EXPECTED_GROUPS)
        self.assertGreaterEqual(len(self.tags), 250)
        self.assertLessEqual(len(self.tags), 350)

    def test_entradas_completas_unicas_y_minusculas(self):
        seen: set[str] = set()
        for item in self.tags:
            with self.subTest(tag=item.get("tag")):
                self.assertEqual(set(item), {"tag", "label", "group"})
                self.assertTrue(item["tag"].strip())
                self.assertEqual(item["tag"], item["tag"].lower())
                self.assertTrue(item["label"].strip())
                self.assertIn(item["group"], EXPECTED_GROUPS)
                folded = item["tag"].lower()
                self.assertNotIn(folded, seen)
                seen.add(folded)

    def test_cada_grupo_tiene_entradas(self):
        counts = {group: 0 for group in EXPECTED_GROUPS}
        for item in self.tags:
            counts[item["group"]] += 1
        for group, count in counts.items():
            with self.subTest(group=group):
                self.assertGreater(count, 0)

    def test_meta_requeridos(self):
        meta = {item["tag"] for item in self.tags if item["group"] == "meta"}
        for tag in META_REQUIRED:
            with self.subTest(tag=tag):
                self.assertIn(tag, meta)


class GroupsTests(unittest.TestCase):
    def test_orden_canonico(self):
        self.assertEqual(GROUPS, EXPECTED_GROUPS)
        self.assertEqual(list_groups(), EXPECTED_GROUPS)

    def test_list_groups_devuelve_copia(self):
        groups = list_groups()
        groups.append("nope")
        self.assertEqual(list_groups(), EXPECTED_GROUPS)


class ByGroupTests(unittest.TestCase):
    def test_hair_no_vacio_y_del_grupo(self):
        items = by_group("hair")
        self.assertTrue(items)
        self.assertTrue(all(item["group"] == "hair" for item in items))
        self.assertIn("long hair", [item["tag"] for item in items])

    def test_grupo_desconocido_engine_error(self):
        with self.assertRaises(EngineError):
            by_group("nope")

    def test_copia_no_muta_el_catalogo(self):
        items = by_group("hair")
        items[0]["tag"] = "inventado"
        self.assertEqual(by_group("hair")[0]["tag"], "long hair")


class SearchTests(unittest.TestCase):
    def test_substring_case_insensitive_en_tag(self):
        tags = [item["tag"] for item in search("LONG HAIR")]
        self.assertIn("long hair", tags)
        self.assertIn("absurdly long hair", tags)

    def test_substring_en_label(self):
        items = search("cabello")
        self.assertTrue(items)
        self.assertIn("long hair", [item["tag"] for item in items])

    def test_limit_clamp_1_200(self):
        self.assertEqual(len(search("a", limit=0)), 1)
        self.assertEqual(len(search("a", limit=-5)), 1)
        self.assertEqual(len(search("a", limit=5)), 5)
        self.assertLessEqual(len(search("a", limit=999)), MAX_SEARCH_LIMIT)

    def test_orden_estable_y_de_catalogo(self):
        first = search("a", limit=20)
        self.assertEqual(first, search("a", limit=20))
        expected = [
            item
            for item in all_tags()
            if "a" in item["tag"].lower() or "a" in item["label"].lower()
        ]
        self.assertEqual(first, expected[:20])

    def test_vacio_devuelve_los_primeros(self):
        self.assertEqual(search("", limit=3), all_tags()[:3])
        self.assertEqual(search("", limit=1), all_tags()[:1])

    def test_consulta_no_str_engine_error(self):
        with self.assertRaises(EngineError):
            search(None)
        with self.assertRaises(EngineError):
            search(3)


class GetTests(unittest.TestCase):
    def test_get_canonico_y_case_insensitive(self):
        entry = get("long hair")
        self.assertEqual(
            entry, {"tag": "long hair", "label": "Cabello largo", "group": "hair"}
        )
        self.assertEqual(get("LONG HAIR"), entry)
        self.assertIsNone(get("no existe"))

    def test_get_copia(self):
        entry = get("long hair")
        entry["label"] = "inventado"
        self.assertEqual(get("long hair")["label"], "Cabello largo")


class AllTagsTests(unittest.TestCase):
    def test_total_y_orden_por_grupos(self):
        items = all_tags()
        self.assertEqual(
            len(items), sum(len(by_group(group)) for group in list_groups())
        )
        positions = [EXPECTED_GROUPS.index(item["group"]) for item in items]
        self.assertEqual(positions, sorted(positions))
        groups_seen = [group for index, group in enumerate(EXPECTED_GROUPS) if index in positions]
        self.assertEqual(groups_seen, EXPECTED_GROUPS)

    def test_copia_no_muta(self):
        items = all_tags()
        items[0]["tag"] = "inventado"
        self.assertEqual(all_tags()[0]["tag"], "long hair")


if __name__ == "__main__":
    unittest.main()
