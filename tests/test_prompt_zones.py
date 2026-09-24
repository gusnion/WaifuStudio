"""Tests CPU de las zonas del prompt (M9-C). Sin red ni GPU."""

from __future__ import annotations

import unittest

from app.engine import EngineError
from app.prompt_zones import (
    CAMERA_TAGS,
    CATALOG_GROUP_SUBCAT,
    GENERAL_SUBCATS,
    GENERAL_SUBCAT_LABELS,
    QUALITY_OPTIONS,
    QUALITY_TAGS,
    SAFETY_OPTIONS,
    SAFETY_TAGS,
    SUBJECT_OPTIONS,
    SUBJECT_TAGS,
    ZONE_LABELS,
    ZONE_ORDER,
    canonical_order,
    classify_tag,
    compose_zones,
    general_subcat,
    insert_tag,
    prompt_options,
    split_zones,
    zones_payload,
)


class ConstantsTests(unittest.TestCase):
    def test_zone_order_y_labels(self):
        self.assertEqual(
            ZONE_ORDER, ("quality", "safety", "subject", "character", "general")
        )
        self.assertEqual(
            ZONE_LABELS,
            {
                "quality": "Calidad/meta",
                "safety": "Safety",
                "subject": "Sujeto",
                "character": "Personaje",
                "general": "General",
            },
        )
        self.assertEqual(set(ZONE_LABELS), set(ZONE_ORDER))
        self.assertTrue(QUALITY_TAGS)
        self.assertTrue(SAFETY_TAGS)
        self.assertTrue(SUBJECT_TAGS)


class GeneralSubcatTests(unittest.TestCase):
    def test_orden_y_labels(self):
        self.assertEqual(
            GENERAL_SUBCATS,
            (
                "rasgos",
                "ropa",
                "accesorios",
                "accion",
                "expresion",
                "camara",
                "fondo",
                "otros",
            ),
        )
        self.assertEqual(
            GENERAL_SUBCAT_LABELS,
            {
                "rasgos": "Rasgos",
                "ropa": "Ropa",
                "accesorios": "Accesorios",
                "accion": "Acción/Pose",
                "expresion": "Expresión",
                "camara": "Cámara",
                "fondo": "Fondo/Escena",
                "otros": "Otros",
            },
        )
        self.assertEqual(set(GENERAL_SUBCAT_LABELS), set(GENERAL_SUBCATS))

    def test_grupos_del_catalogo(self):
        cases = {
            "long hair": "rasgos",
            "blue eyes": "rasgos",
            "freckles": "rasgos",
            "large breasts": "rasgos",
            "school uniform": "ropa",
            "hair ornament": "accesorios",
            "walking": "accion",
            "smile": "expresion",
            "blue sky": "fondo",
        }
        for tag, expected in cases.items():
            with self.subTest(tag=tag):
                self.assertEqual(general_subcat(tag), expected)
        self.assertEqual(
            CATALOG_GROUP_SUBCAT,
            {
                "hair": "rasgos",
                "eyes": "rasgos",
                "face": "rasgos",
                "body": "rasgos",
                "outfit": "ropa",
                "accessories": "accesorios",
                "action": "accion",
                "expression": "expresion",
                "setting": "fondo",
            },
        )

    def test_camara_manda_sobre_el_catalogo(self):
        self.assertGreaterEqual(len(CAMERA_TAGS), 20)
        self.assertEqual(len(set(CAMERA_TAGS)), len(CAMERA_TAGS))
        for tag in CAMERA_TAGS:
            with self.subTest(tag=tag):
                self.assertEqual(general_subcat(tag), "camara")
        self.assertEqual(general_subcat("(close-up:1.2)"), "camara")
        self.assertEqual(general_subcat("  DUTCH   ANGLE  "), "camara")
        self.assertEqual(general_subcat("full body"), "camara")

    def test_desconocido_o_vacio_otros(self):
        for tag in ("inventado xyz", "hatsune miku", "meta tag raro", ""):
            with self.subTest(tag=tag):
                self.assertEqual(general_subcat(tag), "otros")

    def test_tag_no_str(self):
        for tag in (None, 3, ["long hair"]):
            with self.subTest(tag=tag):
                with self.assertRaises(EngineError):
                    general_subcat(tag)


class CanonicalOrderTests(unittest.TestCase):
    def test_ejemplo_gate(self):
        self.assertEqual(
            canonical_order(
                "blue sky, long hair, nsfw, 1girl, masterpiece, school uniform"
            ),
            "masterpiece, nsfw, 1girl, long hair, school uniform, blue sky",
        )

    def test_por_zonas_completo(self):
        self.assertEqual(
            canonical_order("smile, 1girl, nsfw, hatsune miku, masterpiece"),
            "masterpiece, nsfw, 1girl, smile, hatsune miku",
        )

    def test_general_por_subcategorias_y_orden_estable(self):
        self.assertEqual(
            canonical_order(
                "blue sky, standing, long hair, school uniform, hair ornament, "
                "smile, blue eyes"
            ),
            "long hair, blue eyes, school uniform, hair ornament, standing, "
            "smile, blue sky",
        )

    def test_dedup_global_ci(self):
        self.assertEqual(
            canonical_order("smile, 1girl, Smile, masterpiece, MASTERPIECE"),
            "masterpiece, 1girl, smile",
        )
        self.assertEqual(
            canonical_order("Smile, 1girl, smile, MASTERPIECE, masterpiece"),
            "MASTERPIECE, 1girl, Smile",
        )

    def test_pesos_intactos(self):
        self.assertEqual(
            canonical_order("(blue sky:1.3), (long hair:1.2), (masterpiece:1.1)"),
            "(masterpiece:1.1), (long hair:1.2), (blue sky:1.3)",
        )

    def test_cadena_limpia_y_vacia(self):
        self.assertEqual(canonical_order(""), "")
        self.assertEqual(canonical_order("  , , ,  "), "")
        self.assertEqual(canonical_order("  master   piece  "), "master piece")

    def test_idempotente(self):
        text = "masterpiece, nsfw, 1girl, long hair, school uniform, blue sky"
        self.assertEqual(canonical_order(text), text)
        self.assertEqual(canonical_order(canonical_order(text)), text)

    def test_prompt_no_str(self):
        for prompt in (None, 3, ["1girl"]):
            with self.subTest(prompt=prompt):
                with self.assertRaises(EngineError):
                    canonical_order(prompt)


class PromptOptionsTests(unittest.TestCase):
    ZONES = ("quality", "safety", "subject", "general", "character")

    def test_forma_y_zonas_validas(self):
        for zone in self.ZONES:
            with self.subTest(zone=zone):
                data = prompt_options(zone)
                self.assertEqual(set(data), {"zone", "subgroups"})
                self.assertEqual(data["zone"], zone)
                self.assertIsInstance(data["subgroups"], list)
                for subgroup in data["subgroups"]:
                    self.assertEqual(set(subgroup), {"id", "label", "tags"})
                    self.assertTrue(subgroup["label"])
                    for item in subgroup["tags"]:
                        self.assertEqual(set(item), {"tag", "label"})
                        self.assertTrue(item["tag"])
                        self.assertTrue(item["label"])

    def test_zone_invalida_engine_error(self):
        for zone in (None, "", "nope", 5, ["quality"]):
            with self.subTest(zone=zone):
                with self.assertRaises(EngineError):
                    prompt_options(zone)

    def test_calidad_safety_sujeto_desde_listas_curadas(self):
        for zone, options, curated in (
            ("quality", QUALITY_OPTIONS, QUALITY_TAGS),
            ("safety", SAFETY_OPTIONS, SAFETY_TAGS),
            ("subject", SUBJECT_OPTIONS, SUBJECT_TAGS),
        ):
            with self.subTest(zone=zone):
                data = prompt_options(zone)
                self.assertEqual([sub["id"] for sub in data["subgroups"]], [zone])
                tags = {item["tag"] for item in data["subgroups"][0]["tags"]}
                self.assertEqual(tags, set(curated))
                self.assertGreater(len(data["subgroups"][0]["tags"]), 0)

    def test_general_subgrupos_orden_y_sin_duplicar(self):
        data = prompt_options("general")
        ids = [sub["id"] for sub in data["subgroups"]]
        self.assertEqual(ids, [sub for sub in GENERAL_SUBCATS if sub in set(ids)])
        self.assertIn("camara", ids)
        self.assertIn("rasgos", ids)
        self.assertIn("otros", ids)
        by_id = {sub["id"]: sub for sub in data["subgroups"]}
        camera_tags = [item["tag"] for item in by_id["camara"]["tags"]]
        self.assertEqual(camera_tags, list(CAMERA_TAGS))
        flat = [
            item["tag"].lower()
            for sub in data["subgroups"]
            for item in sub["tags"]
        ]
        self.assertEqual(len(flat), len(set(flat)))
        for subcat in ("rasgos", "accion", "expresion", "fondo", "otros"):
            for item in by_id[subcat]["tags"]:
                self.assertNotIn(item["tag"], CAMERA_TAGS)
        rasgos = {item["tag"]: item["label"] for item in by_id["rasgos"]["tags"]}
        self.assertIn("long hair", rasgos)
        self.assertEqual(rasgos["long hair"], "Cabello largo")

    def test_character_vacio(self):
        self.assertEqual(
            prompt_options("character"), {"zone": "character", "subgroups": []}
        )


class ClassifyTagTests(unittest.TestCase):
    def test_calidad(self):
        for tag in (
            "masterpiece",
            "best quality",
            "absurdres",
            "highres",
            "very aesthetic",
            "newest",
            "amazing quality",
            "high quality",
            "low quality",
            "worst quality",
            "jpeg artifacts",
            "sepia",
            "watermark",
            "signature",
            "logo",
        ):
            with self.subTest(tag=tag):
                self.assertEqual(classify_tag(tag), "quality")

    def test_score_1_a_9(self):
        for index in range(1, 10):
            with self.subTest(index=index):
                self.assertEqual(classify_tag(f"score_{index}"), "quality")

    def test_safety(self):
        for tag in (
            "sfw",
            "nsfw",
            "uncensored",
            "explicit",
            "sensitive",
            "safe",
            "rating_safe",
            "rating_explicit",
        ):
            with self.subTest(tag=tag):
                self.assertEqual(classify_tag(tag), "safety")

    def test_sujeto(self):
        for tag in (
            "1girl",
            "1boy",
            "2girls",
            "1other",
            "solo",
            "multiple girls",
            "multiple boys",
            "hetero",
            "yuri",
            "yaoi",
        ):
            with self.subTest(tag=tag):
                self.assertEqual(classify_tag(tag), "subject")

    def test_catalogo_general(self):
        for tag in ("long hair", "smile", "blue sky", "school uniform"):
            with self.subTest(tag=tag):
                self.assertEqual(classify_tag(tag), "general")

    def test_desconocido_general(self):
        for tag in ("my character", "hatsune miku", "inventado xyz"):
            with self.subTest(tag=tag):
                self.assertEqual(classify_tag(tag), "general")

    def test_nunca_devuelve_character(self):
        for tag in ("my character", "hatsune miku", "long hair", "1girl", "nsfw"):
            with self.subTest(tag=tag):
                self.assertNotEqual(classify_tag(tag), "character")

    def test_normaliza_espacios_y_mayusculas(self):
        self.assertEqual(classify_tag("  MASTERPIECE  "), "quality")
        self.assertEqual(classify_tag("Best   Quality"), "quality")
        self.assertEqual(classify_tag("LONG HAIR"), "general")

    def test_pesos(self):
        self.assertEqual(classify_tag("(masterpiece:1.2)"), "quality")
        self.assertEqual(classify_tag("(Best Quality:1.3)"), "quality")
        self.assertEqual(classify_tag("(nsfw:1.5)"), "safety")
        self.assertEqual(classify_tag("(1girl:1.1)"), "subject")
        self.assertEqual(classify_tag("(long hair:1.2)"), "general")
        self.assertEqual(classify_tag("masterpiece:1.2"), "quality")

    def test_tag_invalido_o_vacio(self):
        for tag in (None, 3, "", "   "):
            with self.subTest(tag=tag):
                with self.assertRaises(EngineError):
                    classify_tag(tag)


class SplitZonesTests(unittest.TestCase):
    def test_siempre_las_cinco_claves(self):
        zones = split_zones("")
        self.assertEqual(list(zones), list(ZONE_ORDER))
        self.assertTrue(all(tags == [] for tags in zones.values()))

    def test_ejemplo_gate(self):
        zones = split_zones(
            "1girl, masterpiece, nsfw, long hair, my character, blue sky"
        )
        self.assertEqual(zones["quality"], ["masterpiece"])
        self.assertEqual(zones["safety"], ["nsfw"])
        self.assertEqual(zones["subject"], ["1girl"])
        self.assertEqual(zones["character"], [])
        self.assertEqual(
            zones["general"], ["long hair", "my character", "blue sky"]
        )

    def test_preserva_el_conjunto(self):
        prompt = "masterpiece, 1girl, long hair, smile, blue sky, @artist name"
        zones = split_zones(prompt)
        merged = [tag for tags in zones.values() for tag in tags]
        self.assertEqual(sorted(merged), sorted(tag.strip() for tag in prompt.split(",")))

    def test_dedup_ci_preserva_orden(self):
        zones = split_zones("smile, Smile, SMILE, long hair, Long Hair")
        self.assertEqual(zones["general"], ["smile", "long hair"])

    def test_limpia_espacios_e_ignora_vacios(self):
        zones = split_zones("  1girl ,,  long   hair , ,")
        self.assertEqual(zones["subject"], ["1girl"])
        self.assertEqual(zones["general"], ["long hair"])

    def test_pesos_conservan_el_texto(self):
        zones = split_zones("(masterpiece:1.2), (1girl:1.1)")
        self.assertEqual(zones["quality"], ["(masterpiece:1.2)"])
        self.assertEqual(zones["subject"], ["(1girl:1.1)"])

    def test_prompt_no_str(self):
        with self.assertRaises(EngineError):
            split_zones(None)
        with self.assertRaises(EngineError):
            split_zones(["1girl"])


class ComposeZonesTests(unittest.TestCase):
    def test_orden_canonico(self):
        text = compose_zones(
            {
                "general": ["blue sky"],
                "subject": ["1girl"],
                "quality": ["masterpiece"],
                "safety": ["nsfw"],
            }
        )
        self.assertEqual(text, "masterpiece, nsfw, 1girl, blue sky")

    def test_solo_zonas_con_tags(self):
        self.assertEqual(compose_zones({"quality": [], "general": ["smile"]}), "smile")
        self.assertEqual(compose_zones({}), "")

    def test_dedup_global_ci(self):
        text = compose_zones(
            {"subject": ["1girl"], "general": ["1Girl", "smile", "SMILE"]}
        )
        self.assertEqual(text, "1girl, smile")

    def test_limpia_espacios_e_ignora_vacios(self):
        self.assertEqual(
            compose_zones({"general": ["  smile ", "", "   ", "blue   sky"]}),
            "smile, blue sky",
        )

    def test_roundtrip_conserva_conjunto_y_orden(self):
        prompt = "smile, 1girl, masterpiece, nsfw, long hair"
        self.assertEqual(
            compose_zones(split_zones(prompt)),
            "masterpiece, nsfw, 1girl, smile, long hair",
        )

    def test_forma_invalida(self):
        for zones in (None, [], "x"):
            with self.subTest(zones=zones):
                with self.assertRaises(EngineError):
                    compose_zones(zones)
        with self.assertRaises(EngineError):
            compose_zones({"nope": ["x"]})
        with self.assertRaises(EngineError):
            compose_zones({"general": "smile"})
        with self.assertRaises(EngineError):
            compose_zones({"general": [3]})


class InsertTagTests(unittest.TestCase):
    def test_con_zona_tras_sujeto(self):
        self.assertEqual(
            insert_tag("1girl, smile", "hatsune miku", "character"),
            "1girl, hatsune miku, smile",
        )

    def test_sin_zona_clasifica(self):
        self.assertEqual(
            insert_tag("1girl, smile", "masterpiece"), "masterpiece, 1girl, smile"
        )
        self.assertEqual(insert_tag("1girl, smile", "nsfw"), "nsfw, 1girl, smile")
        self.assertEqual(insert_tag("1girl, smile", "long hair"), "1girl, smile, long hair")

    def test_sin_duplicar(self):
        self.assertEqual(insert_tag("1girl, smile", "smile"), "1girl, smile")
        self.assertEqual(insert_tag("1girl, Smile", "smile"), "1girl, Smile")
        self.assertEqual(
            insert_tag("1girl, smile", "smile", "general"), "1girl, smile"
        )

    def test_prompt_vacio(self):
        self.assertEqual(insert_tag("", "1girl"), "1girl")
        self.assertEqual(insert_tag("   ", "1girl"), "1girl")

    def test_reordena_en_orden_anima(self):
        self.assertEqual(
            insert_tag("smile, 1girl", "best quality"), "best quality, 1girl, smile"
        )

    def test_errores(self):
        with self.assertRaises(EngineError):
            insert_tag("1girl", "")
        with self.assertRaises(EngineError):
            insert_tag("1girl", "   ")
        with self.assertRaises(EngineError):
            insert_tag("1girl", None)
        with self.assertRaises(EngineError):
            insert_tag("1girl", "smile", "nope")
        with self.assertRaises(EngineError):
            insert_tag(None, "smile")


class ZonesPayloadTests(unittest.TestCase):
    def test_estructura_y_orden(self):
        payload = zones_payload("1girl, masterpiece, nsfw")
        self.assertEqual([item["id"] for item in payload], list(ZONE_ORDER))
        self.assertEqual(
            [item["label"] for item in payload],
            [ZONE_LABELS[zone] for zone in ZONE_ORDER],
        )
        for item in payload:
            expected = (
                {"id", "label", "tags", "subcats"}
                if item["id"] == "general"
                else {"id", "label", "tags"}
            )
            self.assertEqual(set(item), expected)
            self.assertIsInstance(item["tags"], list)

    def test_subcats_solo_en_general(self):
        payload = {
            item["id"]: item
            for item in zones_payload(
                "long hair, school uniform, blue sky, smile"
            )
        }
        general = payload["general"]
        self.assertEqual(
            [sub["id"] for sub in general["subcats"]],
            ["rasgos", "ropa", "expresion", "fondo"],
        )
        self.assertEqual(
            general["subcats"][0],
            {"id": "rasgos", "label": "Rasgos", "tags": ["long hair"]},
        )
        self.assertEqual(
            general["subcats"][2],
            {"id": "expresion", "label": "Expresión", "tags": ["smile"]},
        )
        self.assertNotIn("subcats", payload["quality"])

    def test_tags_por_zona(self):
        payload = {
            item["id"]: item["tags"]
            for item in zones_payload("1girl, masterpiece, long hair")
        }
        self.assertEqual(payload["quality"], ["masterpiece"])
        self.assertEqual(payload["subject"], ["1girl"])
        self.assertEqual(payload["general"], ["long hair"])
        self.assertEqual(payload["safety"], [])
        self.assertEqual(payload["character"], [])

    def test_vacio(self):
        payload = zones_payload("")
        self.assertEqual(len(payload), 5)
        self.assertTrue(all(item["tags"] == [] for item in payload))


if __name__ == "__main__":
    unittest.main()
