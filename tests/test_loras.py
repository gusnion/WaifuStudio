"""Tests CPU de la biblioteca de LoRAs (M9-D1) contra el registro real."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.engine import EngineError
from app.loras import DEFAULT_PATH, add_entry, families, get, list_loras
from app.loras import load_registry, save_registry, validate_selection

ROOT = Path(__file__).resolve().parents[1]
LORAS_DIR = ROOT / "ComfyUI" / "models" / "loras"
REAL_IDS = [
    "lightx2v-wan-high",
    "lightx2v-wan-low",
    "reika-kurashiki",
    "minimax-h3-fl2v-turbo-4step",
]
REIKA_FILE = "Reika Kurashiki\\Reika Kurashiki_1.safetensors"


def entry(**overrides) -> dict:
    data = {
        "id": "lora-test",
        "family": "test",
        "file": "test.safetensors",
        "display_name": "Lora de test",
        "trigger": "",
        "default_weight": 1.0,
        "source": "local (test)",
        "license": "test",
        "notes": "",
    }
    data.update(overrides)
    return data


class RealRegistryTests(unittest.TestCase):
    def test_default_path_apunta_al_registro_del_repo(self):
        self.assertEqual(DEFAULT_PATH, ROOT / "registry" / "loras.json")
        self.assertTrue(DEFAULT_PATH.is_file())

    def test_cuatro_entradas_en_orden_del_json(self):
        self.assertEqual([item["id"] for item in list_loras()], REAL_IDS)

    def test_familias_en_orden_de_aparicion(self):
        self.assertEqual(families(), ["wan", "animagine", "h3"])

    def test_campos_de_cada_entrada(self):
        expected = {
            "id",
            "family",
            "file",
            "display_name",
            "trigger",
            "default_weight",
            "source",
            "license",
            "notes",
        }
        for item in list_loras():
            with self.subTest(lora=item["id"]):
                self.assertEqual(set(item), expected)
                self.assertEqual(item["default_weight"], 1.0)
                self.assertIsInstance(item["trigger"], str)
                self.assertIsInstance(item["notes"], str)

    def test_ficheros_registrados_existen_en_disco(self):
        for item in list_loras():
            with self.subTest(lora=item["id"]):
                self.assertTrue(
                    (LORAS_DIR / item["file"]).is_file(),
                    f"falta en disco: {item['file']}",
                )

    def test_lightx2v_wan_high_y_low(self):
        high, low = list_loras("wan")
        self.assertEqual(high["family"], "wan")
        self.assertEqual(low["family"], "wan")
        self.assertIn("high_noise", high["file"])
        self.assertIn("low_noise", low["file"])
        self.assertTrue(high["file"].startswith("lightx2v\\"))
        self.assertEqual(high["license"], "Apache-2.0")
        self.assertEqual(low["license"], "Apache-2.0")
        self.assertIn("4 pasos", high["notes"])
        self.assertIn("4 pasos", low["notes"])

    def test_reika_legacy_no_se_usa_en_anima(self):
        reika = get("reika-kurashiki")
        self.assertEqual(reika["family"], "animagine")
        self.assertEqual(reika["file"], REIKA_FILE)
        self.assertIn("legacy", reika["notes"])
        self.assertIn("Anima", reika["notes"])

    def test_minimax_h3_de_la_plantilla(self):
        entry_data = get("minimax-h3-fl2v-turbo-4step")
        self.assertEqual(entry_data["family"], "h3")
        self.assertEqual(
            entry_data["file"],
            "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
        )

    def test_comment_m10(self):
        payload = load_registry()
        self.assertEqual(payload["version"], 1)
        self.assertIn("M10", payload["_comment"])
        self.assertIn("LoRAs de Anima", payload["_comment"])

    def test_filtro_por_familia(self):
        self.assertEqual(
            [item["id"] for item in list_loras(family="wan")],
            ["lightx2v-wan-high", "lightx2v-wan-low"],
        )
        self.assertEqual(
            [item["id"] for item in list_loras("animagine")], ["reika-kurashiki"]
        )
        self.assertEqual(
            [item["id"] for item in list_loras("h3")],
            ["minimax-h3-fl2v-turbo-4step"],
        )
        self.assertEqual(list_loras("no-existe"), [])

    def test_get_devuelve_copia_e_inexistente_lanza(self):
        first = get("reika-kurashiki")
        first["file"] = "mutado.safetensors"
        self.assertEqual(get("reika-kurashiki")["file"], REIKA_FILE)
        with self.assertRaises(EngineError):
            get("no-existe")

    def test_list_loras_devuelve_copias(self):
        items = list_loras()
        items[0]["file"] = "mutado.safetensors"
        self.assertNotEqual(list_loras()[0]["file"], "mutado.safetensors")


class ValidateSelectionTests(unittest.TestCase):
    def test_normaliza_con_file_y_peso_del_registro(self):
        normalized = validate_selection([{"id": "reika-kurashiki"}])
        self.assertEqual(
            normalized,
            [{"id": "reika-kurashiki", "file": REIKA_FILE, "weight": 1.0}],
        )

    def test_peso_explicito_y_texto_numerico(self):
        normalized = validate_selection(
            [
                {"id": "lightx2v-wan-high", "weight": 0.8},
                {"id": "reika-kurashiki", "weight": "1.5"},
            ]
        )
        self.assertEqual(normalized[0]["weight"], 0.8)
        self.assertEqual(normalized[1]["weight"], 1.5)

    def test_pesos_en_los_limites(self):
        normalized = validate_selection(
            [
                {"id": "reika-kurashiki", "weight": 0},
                {"id": "reika-kurashiki", "weight": 2},
            ]
        )
        self.assertEqual([item["weight"] for item in normalized], [0.0, 2.0])

    def test_claves_extra_se_ignoran_y_orden_se_conserva(self):
        normalized = validate_selection(
            [
                {"id": "lightx2v-wan-low", "weight": 0.5, "extra": True},
                {"id": "lightx2v-wan-high"},
            ]
        )
        self.assertEqual(
            [item["id"] for item in normalized],
            ["lightx2v-wan-low", "lightx2v-wan-high"],
        )
        self.assertEqual(set(normalized[0]), {"id", "file", "weight"})

    def test_lista_vacia(self):
        self.assertEqual(validate_selection([]), [])

    def test_seleccion_no_lista_lanza(self):
        for selection in (None, {}, "x", 5):
            with self.subTest(selection=selection):
                with self.assertRaises(EngineError):
                    validate_selection(selection)

    def test_item_invalido_lanza(self):
        for selection in ([None], ["reika-kurashiki"], [{"weight": 1.0}]):
            with self.subTest(selection=selection):
                with self.assertRaises(EngineError):
                    validate_selection(selection)

    def test_id_desconocido_o_vacio_lanza(self):
        for lora_id in ("no-existe", "", "   ", 5, None):
            with self.subTest(lora_id=lora_id):
                with self.assertRaises(EngineError):
                    validate_selection([{"id": lora_id}])

    def test_peso_invalido_lanza(self):
        for weight in (True, -0.1, 2.01, "abc", [0.5], float("nan"), float("inf")):
            with self.subTest(weight=weight):
                with self.assertRaises(EngineError):
                    validate_selection([{"id": "reika-kurashiki", "weight": weight}])


class TempRegistryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "loras.json"

    def write(self, payload) -> Path:
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.path

    def test_path_alternativo(self):
        self.write({"version": 1, "loras": [entry(family="otra")]})
        self.assertEqual([item["id"] for item in list_loras(path=self.path)], ["lora-test"])
        self.assertEqual(list_loras("otra", path=self.path)[0]["id"], "lora-test")
        self.assertEqual(families(path=self.path), ["otra"])
        self.assertEqual(
            validate_selection([{"id": "lora-test"}], path=self.path)[0]["weight"],
            1.0,
        )

    def test_version_incorrecta(self):
        self.write({"version": 2, "loras": [entry()]})
        with self.assertRaises(EngineError):
            load_registry(self.path)

    def test_sin_lista_loras(self):
        self.write({"version": 1})
        with self.assertRaises(EngineError):
            load_registry(self.path)

    def test_fichero_ilegible_o_json_invalido(self):
        with self.assertRaises(EngineError):
            load_registry(self.path)
        self.path.write_text("{no-json", encoding="utf-8")
        with self.assertRaises(EngineError):
            load_registry(self.path)
        self.path.write_text("[]", encoding="utf-8")
        with self.assertRaises(EngineError):
            load_registry(self.path)

    def test_id_duplicado(self):
        self.write({"version": 1, "loras": [entry(), entry()]})
        with self.assertRaises(EngineError):
            load_registry(self.path)

    def test_campo_obligatorio_ausente(self):
        for key in ("id", "family", "file", "display_name", "source", "license"):
            with self.subTest(key=key):
                data = entry()
                del data[key]
                self.write({"version": 1, "loras": [data]})
                with self.assertRaises(EngineError):
                    load_registry(self.path)

    def test_entrada_no_dict(self):
        self.write({"version": 1, "loras": ["x"]})
        with self.assertRaises(EngineError):
            load_registry(self.path)

    def test_id_fuera_del_slug(self):
        self.write({"version": 1, "loras": [entry(id="Con Mayusculas")]})
        with self.assertRaises(EngineError):
            load_registry(self.path)

    def test_default_weight_invalido(self):
        for weight in (True, 2.5, "abc"):
            with self.subTest(weight=weight):
                self.write({"version": 1, "loras": [entry(default_weight=weight)]})
                with self.assertRaises(EngineError):
                    load_registry(self.path)

    def test_default_weight_por_defecto_es_uno(self):
        data = entry()
        del data["default_weight"]
        self.write({"version": 1, "loras": [data]})
        self.assertEqual(load_registry(self.path)["loras"][0]["default_weight"], 1.0)

    def test_trigger_y_notes_deben_ser_str(self):
        for key in ("trigger", "notes"):
            with self.subTest(key=key):
                self.write({"version": 1, "loras": [entry(**{key: 5})]})
                with self.assertRaises(EngineError):
                    load_registry(self.path)

    def test_comment_se_conserva(self):
        self.write({"version": 1, "_comment": "nota", "loras": [entry()]})
        self.assertEqual(load_registry(self.path)["_comment"], "nota")


class AddEntryTests(unittest.TestCase):
    """Alta de entradas con registro temporal (M9-E1)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "loras.json"
        self.write({"version": 1, "_comment": "nota", "loras": [entry(family="base")]})

    def write(self, payload) -> None:
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def test_add_entry_al_final_y_persiste(self):
        added = add_entry(entry(id="nueva", family="anima"), path=self.path)
        self.assertEqual(added["id"], "nueva")
        self.assertEqual(added["family"], "anima")
        self.assertEqual(
            [item["id"] for item in list_loras(path=self.path)],
            ["lora-test", "nueva"],
        )
        self.assertEqual(load_registry(self.path)["_comment"], "nota")

    def test_add_entry_devuelve_copia(self):
        added = add_entry(entry(id="nueva"), path=self.path)
        added["file"] = "mutado.safetensors"
        self.assertEqual(
            list_loras(path=self.path)[-1]["file"], "test.safetensors"
        )

    def test_add_entry_duplicado_lanza_y_no_toca_el_fichero(self):
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(EngineError) as ctx:
            add_entry(entry(), path=self.path)
        self.assertIn("duplicado", str(ctx.exception))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_add_entry_invalida_lanza_y_no_toca_el_fichero(self):
        for data in (
            {},
            entry(id="Con Mayusculas"),
            entry(file=""),
            entry(default_weight=3),
            entry(trigger=5),
        ):
            with self.subTest(data=data):
                with self.assertRaises(EngineError):
                    add_entry(data, path=self.path)
        self.assertEqual(
            [item["id"] for item in list_loras(path=self.path)], ["lora-test"]
        )

    def test_add_entry_sin_registro_lanza(self):
        missing = Path(self._tmp.name) / "no-existe.json"
        with self.assertRaises(EngineError):
            add_entry(entry(), path=missing)

    def test_save_registry_conserva_orden_y_comment(self):
        target = Path(self._tmp.name) / "guardado.json"
        payload = {
            "version": 1,
            "_comment": "otro",
            "loras": [entry(id="b"), entry(id="a", family="otra")],
        }
        self.assertEqual(save_registry(payload, path=target), target)
        saved = load_registry(target)
        self.assertEqual([item["id"] for item in saved["loras"]], ["b", "a"])
        self.assertEqual(saved["_comment"], "otro")

    def test_save_registry_invalido_lanza(self):
        for payload in (
            None,
            [],
            {"version": 2, "loras": []},
            {"version": 1},
            {"version": 1, "loras": "x"},
            {"version": 1, "loras": [entry(), entry()]},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(EngineError):
                    save_registry(payload, path=Path(self._tmp.name) / "x.json")

    def test_save_registry_no_deja_tmp(self):
        target = Path(self._tmp.name) / "sub" / "loras.json"
        save_registry({"version": 1, "loras": [entry()]}, path=target)
        self.assertEqual(list(target.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
