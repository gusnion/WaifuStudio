"""Tests CPU del catalogo OC Maker (F3a). Sin red ni GPU."""

from __future__ import annotations

import json
import unittest

from app.engine import EngineError
from app.oc_traits import TRAIT_GROUPS, build_prompt, list_traits

EXPECTED_GROUPS = [
    "hair",
    "eyes",
    "face",
    "body",
    "outfit",
    "expression",
    "accessories",
    "setting",
]

KNOWN_TAGS = [
    "long hair",
    "twintails",
    "heterochromia",
    "school uniform",
    "smile",
    "thighhighs",
    "cityscape",
]


class TraitCatalogTests(unittest.TestCase):
    def test_ocho_grupos_en_orden_y_6_a_10_traits(self):
        self.assertEqual(list(TRAIT_GROUPS), EXPECTED_GROUPS)
        for group, traits in TRAIT_GROUPS.items():
            with self.subTest(group=group):
                self.assertGreaterEqual(len(traits), 6)
                self.assertLessEqual(len(traits), 10)

    def test_traits_bien_formados_y_ids_unicos(self):
        seen_ids = set()
        for traits in TRAIT_GROUPS.values():
            for trait in traits:
                with self.subTest(trait=trait["id"]):
                    self.assertEqual(set(trait), {"id", "label", "tags"})
                    self.assertRegex(trait["id"], r"^[a-z0-9_]+$")
                    self.assertNotIn(trait["id"], seen_ids)
                    seen_ids.add(trait["id"])
                    self.assertIsInstance(trait["label"], str)
                    self.assertTrue(trait["label"].strip())
                    self.assertIsInstance(trait["tags"], list)
                    self.assertTrue(trait["tags"])
                    for tag in trait["tags"]:
                        self.assertIsInstance(tag, str)
                        self.assertTrue(tag.strip())

    def test_tags_danbooru_conocidos(self):
        tags = {
            tag
            for traits in TRAIT_GROUPS.values()
            for trait in traits
            for tag in trait["tags"]
        }

        for tag in KNOWN_TAGS:
            with self.subTest(tag=tag):
                self.assertIn(tag, tags)


class BuildPromptTests(unittest.TestCase):
    def test_ordena_por_grupo_del_catalogo(self):
        prompt = build_prompt(["smile", "long_hair", "school_uniform"])

        self.assertEqual(prompt, "long hair, school uniform, smile")

    def test_dedup_preserva_el_primer_tag(self):
        prompt = build_prompt(["thighhighs", "zettai_ryouiki"])

        self.assertEqual(prompt, "thighhighs, zettai ryouiki")
        self.assertEqual(prompt.count("thighhighs"), 1)

    def test_vacio_devuelve_cadena_vacia(self):
        self.assertEqual(build_prompt([]), "")

    def test_seleccion_repetida_no_duplica(self):
        self.assertEqual(build_prompt(["smile", "smile"]), "smile")

    def test_id_invalido_lanza_engine_error(self):
        for selected in (["no_existe"], [123], "long_hair", [None]):
            with self.subTest(selected=selected):
                with self.assertRaises(EngineError):
                    build_prompt(selected)


class ListTraitsTests(unittest.TestCase):
    def test_serializable_y_copia_profunda(self):
        data = list_traits()

        self.assertEqual(data, TRAIT_GROUPS)
        self.assertIsNot(data, TRAIT_GROUPS)
        self.assertEqual(json.loads(json.dumps(data)), TRAIT_GROUPS)

        data["hair"][0]["tags"].append("tag-inventado")
        data["hair"].clear()

        self.assertTrue(TRAIT_GROUPS["hair"])
        self.assertNotIn("tag-inventado", TRAIT_GROUPS["hair"][0]["tags"])


if __name__ == "__main__":
    unittest.main()
