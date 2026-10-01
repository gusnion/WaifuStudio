"""Tests CPU del catalogo Danbooru v3 (M11-1): curado + catalogo compacto + FTS5. Sin red ni GPU."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.engine import EngineError
from app.tags import (
    CATALOG_PATH,
    GROUPS,
    MAX_SEARCH_LIMIT,
    _load_catalog,
    all_tags,
    by_group,
    catalog_count,
    get,
    is_valid,
    list_groups,
    resolve,
    retrieve,
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
    "general_top",
    "character",
    "series",
    "artist",
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
CATALOG_CATEGORIES = ("general", "artist", "series", "character", "meta")


class CatalogFileTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.tags = self.data["tags"]
        self.catalog = self.data["catalog"]

    def test_json_valido_y_rango_de_tamano(self):
        self.assertEqual(
            set(self.data),
            {"schema_version", "descripcion", "source", "groups", "tags", "catalog"},
        )
        self.assertEqual(self.data["groups"], EXPECTED_GROUPS)
        self.assertEqual(self.data["schema_version"], "tags-danbooru/v3")
        self.assertEqual(len(self.tags), 3249)
        self.assertEqual(len(self.catalog), 91357)
        self.assertEqual(self.data["source"]["threshold"], 50)
        self.assertTrue(self.data["source"]["sha256"])

    def test_entradas_completas_unicas_y_minusculas(self):
        seen: set[str] = set()
        for item in self.tags:
            with self.subTest(tag=item.get("tag")):
                self.assertEqual(set(item), {"tag", "label", "group", "rank"})
                self.assertTrue(item["tag"].strip())
                self.assertEqual(item["tag"], item["tag"].lower())
                self.assertTrue(item["label"].strip())
                self.assertIn(item["group"], EXPECTED_GROUPS)
                self.assertIsInstance(item["rank"], int)
                self.assertGreaterEqual(item["rank"], 0)
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

    def test_catalogo_shape_y_nombres_unicos(self):
        seen: set[str] = set()
        for item in self.catalog:
            name = item.get("name")
            self.assertEqual(
                set(item), {"name", "category", "posts", "aliases"}, name
            )
            self.assertIsInstance(name, str, name)
            self.assertTrue(name.strip(), name)
            self.assertIn(item["category"], CATALOG_CATEGORIES, name)
            self.assertIsInstance(item["posts"], int, name)
            self.assertNotIsInstance(item["posts"], bool, name)
            self.assertGreater(item["posts"], 0, name)
            self.assertIsInstance(item["aliases"], list, name)
            for alias in item["aliases"]:
                self.assertIsInstance(alias, str, name)
                self.assertTrue(alias, name)
            self.assertNotIn(name, seen, name)
            seen.add(name)

    def test_catalogo_spot(self):
        by_name = {item["name"]: item for item in self.catalog}
        long_hair = by_name["long hair"]
        self.assertEqual(long_hair["category"], "general")
        self.assertEqual(long_hair["posts"], 4350743)
        self.assertEqual(long_hair["aliases"], ["longhair"])
        one_girl = by_name["1girl"]
        self.assertEqual(one_girl["category"], "general")
        self.assertEqual(one_girl["posts"], 6008644)
        self.assertEqual(one_girl["aliases"], ["1girls", "sole female"])

    def test_catalogo_posts_minimos_y_orden_descendente(self):
        posts = [item["posts"] for item in self.catalog]
        self.assertGreaterEqual(min(posts), 50)
        self.assertEqual(posts[:1000], sorted(posts[:1000], reverse=True))


class CatalogCountTests(unittest.TestCase):
    def test_cuenta_del_catalogo(self):
        self.assertEqual(catalog_count(), 91357)


class CatalogValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _write(self, payload: dict, name: str = "tags.json") -> Path:
        path = Path(self.tmpdir.name) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_sin_catalog_carga_lista_vacia(self):
        path = self._write({"groups": ["meta"], "tags": []})
        groups, tags, catalog = _load_catalog(path)
        self.assertEqual(groups, ["meta"])
        self.assertEqual(tags, [])
        self.assertEqual(catalog, [])

    def test_catalog_no_lista_engine_error(self):
        path = self._write({"groups": ["meta"], "tags": [], "catalog": "nope"})
        with self.assertRaises(EngineError) as ctx:
            _load_catalog(path)
        self.assertIn("catalog", str(ctx.exception))

    def test_entrada_de_catalogo_invalida_engine_error(self):
        cases = [
            {"name": "", "category": "general", "posts": 50, "aliases": []},
            {"name": "x", "category": "nope", "posts": 50, "aliases": []},
            {"name": "x", "category": "general", "posts": 0, "aliases": []},
            {"name": "x", "category": "general", "posts": True, "aliases": []},
            {"name": "x", "category": "general", "posts": 50, "aliases": [""]},
            {"name": "x", "category": "general", "posts": 50, "aliases": [3]},
            {"name": "x", "category": "general", "posts": 50},
            {
                "name": "x",
                "category": "general",
                "posts": 50,
                "aliases": [],
                "extra": 1,
            },
        ]
        for item in cases:
            with self.subTest(item=item):
                path = self._write(
                    {"groups": ["meta"], "tags": [], "catalog": [item]}, "bad.json"
                )
                with self.assertRaises(EngineError) as ctx:
                    _load_catalog(path)
                self.assertIn("bad.json", str(ctx.exception))


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

    def test_grupos_bulk_ordenados_por_rank(self):
        for group in ("general_top", "character", "series", "artist"):
            with self.subTest(group=group):
                ranks = [item["rank"] for item in by_group(group)]
                self.assertTrue(ranks)
                self.assertEqual(ranks, sorted(ranks, reverse=True))
                self.assertGreater(ranks[0], 0)

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

    def test_alias_del_catalogo(self):
        items = search("longhair")
        self.assertIn("long hair", [item["tag"] for item in items])

    def test_entrada_solo_de_catalogo(self):
        items = search("ink on face")
        self.assertIn("ink on face", [item["tag"] for item in items])
        entry = next(item for item in items if item["tag"] == "ink on face")
        self.assertEqual(
            entry,
            {
                "tag": "ink on face",
                "label": "ink on face",
                "group": "general",
                "rank": 167,
            },
        )

    def test_absurdly_long_hair_del_catalogo(self):
        tags = [item["tag"] for item in search("absurdly long hair")]
        self.assertIn("absurdly long hair", tags)

    def test_limite_con_catalogo(self):
        self.assertEqual(len(search("ink on face", limit=1)), 1)
        self.assertLessEqual(len(search("hair", limit=5)), 5)

    def test_estabilidad_con_catalogo(self):
        self.assertEqual(search("ink on face"), search("ink on face"))
        self.assertEqual(search("long hair", limit=10), search("long hair", limit=10))

    def test_resultados_son_copias(self):
        items = search("long hair", limit=5)
        items[0]["tag"] = "inventado"
        self.assertEqual(search("long hair", limit=5)[0]["tag"], "long hair")


class GetTests(unittest.TestCase):
    def test_get_canonico_y_case_insensitive(self):
        entry = get("long hair")
        self.assertEqual(
            entry,
            {
                "tag": "long hair",
                "label": "Cabello largo",
                "group": "hair",
                "rank": 0,
            },
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


class ValidationTests(unittest.TestCase):
    def test_curado(self):
        self.assertTrue(is_valid("long hair"))
        self.assertTrue(is_valid("LONG HAIR"))
        self.assertTrue(is_valid("1girl"))
        self.assertEqual(resolve("long hair"), "long hair")
        self.assertEqual(resolve("1girl"), "1girl")

    def test_catalogo(self):
        self.assertTrue(is_valid("ink on face"))
        self.assertEqual(resolve("ink on face"), "ink on face")

    def test_alias(self):
        self.assertTrue(is_valid("longhair"))
        self.assertEqual(resolve("longhair"), "long hair")
        self.assertEqual(resolve("LongHair"), "long hair")
        self.assertEqual(resolve("nekomimi"), "cat ears")

    def test_score(self):
        self.assertTrue(is_valid("score_9"))
        self.assertEqual(resolve("score_9"), "score_9")
        self.assertEqual(resolve("SCORE_9"), "score_9")
        self.assertFalse(is_valid("score_12"))
        self.assertIsNone(resolve("score_12"))

    def test_desconocido(self):
        self.assertFalse(is_valid("inventado"))
        self.assertIsNone(resolve("inventado"))

    def test_no_str(self):
        for value in (None, 3, ["long hair"], ""):
            with self.subTest(value=value):
                self.assertFalse(is_valid(value))
                self.assertIsNone(resolve(value))

    def test_fold_guion_bajo(self):
        self.assertTrue(is_valid("LONG_HAIR"))
        self.assertEqual(resolve("LONG_HAIR"), "long hair")


class RetrieveTests(unittest.TestCase):
    def test_long_hair_en_resultados(self):
        self.assertIn("long hair", retrieve("long hair"))

    def test_alias_en_resultados(self):
        self.assertIn("long hair", retrieve("longhair"))

    def test_dedup_y_limite(self):
        names = retrieve("hair", k=5)
        self.assertTrue(names)
        self.assertLessEqual(len(names), 5)
        self.assertEqual(len(names), len({name.lower() for name in names}))

    def test_k_clamp(self):
        self.assertEqual(retrieve("long hair", k=0), [])
        self.assertEqual(retrieve("long hair", k=-3), [])
        self.assertLessEqual(len(retrieve("hair", k=999)), 120)

    def test_query_sin_tokens(self):
        self.assertEqual(retrieve(""), [])
        self.assertEqual(retrieve("   "), [])
        self.assertEqual(retrieve("a"), [])
        self.assertEqual(retrieve(None), [])

    def test_zonas_hatsune_miku(self):
        self.assertIn("hatsune miku", retrieve("hatsune miku"))
        character = retrieve("hatsune miku", zone="character")
        self.assertIn("hatsune miku", character)
        general = retrieve("hatsune miku", zone="general")
        self.assertNotIn("hatsune miku", general)

    def test_resultados_canonicos(self):
        for name in retrieve("long hair", k=10):
            with self.subTest(name=name):
                self.assertTrue(is_valid(name))
                self.assertEqual(resolve(name), name)

    def test_estable(self):
        self.assertEqual(retrieve("long hair", k=10), retrieve("long hair", k=10))

    def test_stopwords_solas_devuelven_vacio(self):
        self.assertEqual(retrieve("con de la por"), [])

    def test_stopwords_no_meten_ruido(self):
        names = retrieve("chica pelirroja con uniforme escolar")
        for noise in ("condom", "controller", "contrapposto"):
            self.assertNotIn(noise, names)

    def test_stopwords_no_rompen_consulta_util(self):
        self.assertIn("long hair", retrieve("a girl with long hair"))


if __name__ == "__main__":
    unittest.main()
