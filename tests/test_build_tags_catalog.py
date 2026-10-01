"""Tests offline del generador del catalogo v3 (scripts/build_tags_catalog.py).

Sin red: `build` se prueba con un CSV fixture temporal. El modulo se carga por
ruta con importlib (mismo approach que tests/test_kohya_wrapper.py).
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


def _load_builder():
    source = Path(__file__).resolve().parents[1] / "scripts" / "build_tags_catalog.py"
    spec = importlib.util.spec_from_file_location("build_tags_catalog", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_builder()

CURATED = {
    "groups": ["hair", "expression"],
    "tags": [
        {"tag": "long hair", "label": "Cabello largo", "group": "hair", "rank": 0},
        {"tag": "smile", "label": "Sonrisa", "group": "expression", "rank": 0},
        {"tag": "Exact Tag", "label": "Etiqueta exacta", "group": "hair", "rank": 0},
        {
            "tag": "legacy bulk",
            "label": "legacy bulk",
            "group": "general_top",
            "rank": 123,
        },
    ],
}
CURATED_TAGS = [dict(entry) for entry in CURATED["tags"] if entry["rank"] == 0]

FIXTURE_ROWS = [
    ("solo", "0", "60", "female_solo,sole_female"),
    ("long_hair", "0", "50", "/lh,longhair"),
    ("blush", "0", "49", "blushing,blush"),
    ("rare", "0", "10", ""),
    ("exact_tag", "0", "99", "exact tag"),
    ("1girl", "4", "70", ":),1girls"),
    ("smile", "3", "100", ":},smile"),
    ("sakura_(series)", "3", "55", "sakura,sakura_(series)"),
    ("artist_person", "1", "90", "art_person,artist-person"),
    ("weird", "5", "80", "___,-/:,???"),
    ("multi", "0", "75", "Foo,foo,FOO"),
    ("a__b", "0", "51", ""),
    ("aaa", "0", "71", ""),
    ("zzz", "0", "71", ""),
    ("zero", "0", "0", "nada"),
    ("broken", "0"),
    ("badposts", "0", "NaN", "x"),
    ("mindful", "6", "999", "x"),
]

EXPECTED_NAMES_50 = [
    "smile",
    "exact tag",
    "artist person",
    "weird",
    "multi",
    "aaa",
    "zzz",
    "1girl",
    "solo",
    "sakura (series)",
    "a b",
    "long hair",
]

EXPECTED_CATEGORIES = {
    "smile": "series",
    "exact tag": "general",
    "artist person": "artist",
    "weird": "meta",
    "multi": "general",
    "aaa": "general",
    "zzz": "general",
    "1girl": "character",
    "solo": "general",
    "sakura (series)": "series",
    "a b": "general",
    "long hair": "general",
}

EXPECTED_ALIASES = {
    "solo": ["female solo", "sole female"],
    "long hair": ["longhair"],
    "1girl": ["1girls"],
    "smile": [],
    "sakura (series)": ["sakura"],
    "artist person": ["art person", "artist-person"],
    "weird": [],
    "multi": ["Foo"],
    "a b": [],
    "exact tag": [],
}


def _write_csv(path: Path, rows) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    return path


class BuilderTestCase(unittest.TestCase):
    def _build(self, rows=None, curated=None, threshold=None):
        rows = FIXTURE_ROWS if rows is None else rows
        curated = json.loads(json.dumps(CURATED)) if curated is None else curated
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        csv_path = _write_csv(Path(tmp.name) / "danbooru.csv", rows)
        if threshold is None:
            data = builder.build(csv_path, curated)
        else:
            data = builder.build(csv_path, curated, threshold=threshold)
        return data, csv_path


class SchemaV3Tests(BuilderTestCase):
    def test_esquema_y_orden_de_claves(self):
        data, _ = self._build()
        self.assertEqual(
            list(data.keys()),
            ["schema_version", "descripcion", "source", "groups", "tags", "catalog"],
        )
        self.assertEqual(data["schema_version"], "tags-danbooru/v3")
        self.assertEqual(data["descripcion"], builder.DESCRIPTION)

    def test_source_completo(self):
        data, csv_path = self._build()
        source = data["source"]
        self.assertEqual(
            list(source.keys()),
            [
                "url",
                "sha256",
                "downloaded_at",
                "threshold",
                "csv_rows",
                "catalog_count",
                "topn",
            ],
        )
        self.assertEqual(source["url"], builder.CSV_URL)
        self.assertEqual(
            source["sha256"],
            hashlib.sha256(csv_path.read_bytes()).hexdigest().upper(),
        )
        self.assertEqual(source["threshold"], 50)
        self.assertEqual(source["csv_rows"], len(FIXTURE_ROWS))
        self.assertEqual(source["catalog_count"], len(data["catalog"]))
        self.assertEqual(
            source["topn"],
            {"general_top": 1500, "character": 800, "series": 300, "artist": 300},
        )

    def test_groups_ampliados_y_tags_curadas_al_frente(self):
        data, _ = self._build()
        self.assertEqual(
            data["groups"],
            ["hair", "expression", "general_top", "character", "series", "artist"],
        )
        self.assertEqual(data["tags"][: len(CURATED_TAGS)], CURATED_TAGS)

    def test_groups_no_duplica_los_bulk_ya_presentes(self):
        curated = json.loads(json.dumps(CURATED))
        curated["groups"] = ["hair", "general_top", "general_top", "meta"]
        data, _ = self._build(curated=curated)
        self.assertEqual(
            data["groups"],
            ["hair", "general_top", "meta", "character", "series", "artist"],
        )

    def test_entradas_de_catalogo_bien_formadas(self):
        data, _ = self._build()
        for entry in data["catalog"]:
            with self.subTest(name=entry["name"]):
                self.assertEqual(
                    list(entry.keys()), ["name", "category", "posts", "aliases"]
                )
                self.assertIsInstance(entry["posts"], int)
                self.assertIsInstance(entry["aliases"], list)


class ThresholdTests(BuilderTestCase):
    def test_default_50_filtra_por_debajo(self):
        data, _ = self._build()
        names = [entry["name"] for entry in data["catalog"]]
        self.assertEqual(names, EXPECTED_NAMES_50)
        self.assertIn("long hair", names)
        self.assertNotIn("blush", names)
        self.assertNotIn("rare", names)
        self.assertNotIn("zero", names)

    def test_threshold_0_incluye_todo(self):
        data, _ = self._build(threshold=0)
        names = [entry["name"] for entry in data["catalog"]]
        self.assertIn("blush", names)
        self.assertIn("rare", names)
        self.assertIn("zero", names)
        self.assertNotIn("mindful", names)
        self.assertEqual(data["source"]["threshold"], 0)

    def test_threshold_49_incluye_el_valor_exacto(self):
        data, _ = self._build(threshold=49)
        names = [entry["name"] for entry in data["catalog"]]
        self.assertIn("blush", names)
        self.assertNotIn("rare", names)
        self.assertNotIn("zero", names)


class CatalogContentTests(BuilderTestCase):
    def test_mapeo_de_categorias(self):
        data, _ = self._build()
        mapped = {entry["name"]: entry["category"] for entry in data["catalog"]}
        self.assertEqual(mapped, EXPECTED_CATEGORIES)

    def test_orden_por_posts_desc_y_name(self):
        data, _ = self._build()
        keys = [(-entry["posts"], entry["name"]) for entry in data["catalog"]]
        self.assertEqual(keys, sorted(keys))

    def test_limpieza_de_aliases(self):
        data, _ = self._build()
        mapped = {entry["name"]: entry["aliases"] for entry in data["catalog"]}
        for name, expected in EXPECTED_ALIASES.items():
            with self.subTest(name=name):
                self.assertEqual(mapped[name], expected)

    def test_name_con_underscores_y_espacios_colapsados(self):
        data, _ = self._build()
        names = [entry["name"] for entry in data["catalog"]]
        self.assertIn("long hair", names)
        self.assertIn("a b", names)


class CuratedTests(BuilderTestCase):
    def test_curada_se_conserva_exacta(self):
        data, _ = self._build()
        self.assertEqual(data["tags"][: len(CURATED_TAGS)], CURATED_TAGS)

    def test_rank_mayor_que_cero_no_se_conserva(self):
        data, _ = self._build()
        self.assertNotIn("legacy bulk", [entry["tag"] for entry in data["tags"]])

    def test_bulk_salta_la_curada_case_insensitive(self):
        data, _ = self._build()
        folded = [entry["tag"].lower() for entry in data["tags"]]
        self.assertEqual(folded.count("long hair"), 1)
        self.assertEqual(folded.count("smile"), 1)
        self.assertEqual(folded.count("exact tag"), 1)
        self.assertEqual(len(folded), len(set(folded)))

    def test_bulk_regenerado_por_grupo(self):
        data, _ = self._build()
        bulk = data["tags"][len(CURATED_TAGS) :]
        self.assertEqual(
            [(entry["tag"], entry["group"]) for entry in bulk],
            [
                ("multi", "general_top"),
                ("aaa", "general_top"),
                ("zzz", "general_top"),
                ("solo", "general_top"),
                ("a  b", "general_top"),
                ("blush", "general_top"),
                ("rare", "general_top"),
                ("1girl", "character"),
                ("sakura (series)", "series"),
                ("artist person", "artist"),
            ],
        )
        for entry in bulk:
            with self.subTest(tag=entry["tag"]):
                self.assertEqual(entry["label"], entry["tag"])
                self.assertGreater(entry["rank"], 0)

    def test_no_muta_el_dict_curado(self):
        original = json.loads(json.dumps(CURATED))
        curated = json.loads(json.dumps(CURATED))
        first, _ = self._build(curated=curated)
        second, _ = self._build(curated=curated)
        self.assertEqual(curated, original)
        self.assertEqual(first["tags"][: len(CURATED_TAGS)], CURATED_TAGS)
        self.assertEqual(second["tags"][: len(CURATED_TAGS)], CURATED_TAGS)


class DeterminismTests(BuilderTestCase):
    def test_dos_builds_iguales_ignorando_downloaded_at(self):
        first, _ = self._build()
        second, _ = self._build()
        first["source"]["downloaded_at"] = ""
        second["source"]["downloaded_at"] = ""
        self.assertEqual(first, second)


class MainTests(BuilderTestCase):
    def test_cli_escribe_json_compacto_y_reporta(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        csv_path = _write_csv(root / "danbooru.csv", FIXTURE_ROWS)
        catalog_path = root / "tags_danbooru.json"
        catalog_path.write_text(
            json.dumps(CURATED, ensure_ascii=False), encoding="utf-8"
        )
        original = builder.CATALOG_PATH
        builder.CATALOG_PATH = catalog_path
        try:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = builder.main(["--csv", str(csv_path), "--threshold", "50"])
        finally:
            builder.CATALOG_PATH = original
        self.assertEqual(code, 0)
        raw = catalog_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertEqual(
            raw, json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        self.assertEqual(data["schema_version"], "tags-danbooru/v3")
        self.assertEqual(len(data["tags"]), 13)
        self.assertEqual(data["source"]["catalog_count"], 12)
        self.assertTrue(data["source"]["downloaded_at"])
        output = buffer.getvalue()
        self.assertIn("13 tags (3 curadas + 10 top-N)", output)
        self.assertIn("catalog (posts>=50): 12", output)
        self.assertIn(f"sha256 csv: {data['source']['sha256']}", output)
        self.assertIn("tamano json:", output)


if __name__ == "__main__":
    unittest.main()
