"""Tests CPU de la biblioteca de LoRAs (M9-D1) contra el registro real."""

from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import loras as loras_module
from app.engine import EngineError
from app.loras import DEFAULT_PATH, add_entry, delete_entry, families, get
from app.loras import inspect_safetensors, list_loras, load_registry
from app.loras import safetensors_header, save_registry, update_entry
from app.loras import validate_selection

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "loras.json"
LORAS_DIR = ROOT / "ComfyUI" / "models" / "loras"
TEST_ASSETS_ENV = "WAIFU_TEST_ASSETS"
REAL_IDS = [
    "lightx2v-wan-high",
    "lightx2v-wan-low",
    "minimax-h3-fl2v-turbo-4step",
    "miku-nakano-anima",
    "kurashiki-reika-saimin-anima",
    "shuuko-komi-s1s2-anima",
    "mina-ashido-1-anima",
    "mina-ashido-2-anima",
]
WAN_HIGH_ID = "lightx2v-wan-high"
WAN_HIGH_FILE = (
    "lightx2v\\wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors"
)
MIKU_ID = "miku-nakano-anima"
MIKU_FILE = "anima\\Miku_Nakano_Anima_v0.7.safetensors"
SAIMIN_ID = "kurashiki-reika-saimin-anima"
SAIMIN_FILE = "anima\\Kurashiki Reika Saimin Seishidou.safetensors"
SAIMIN_SIZE = 277207608
SHUUKO_ID = "shuuko-komi-s1s2-anima"
SHUUKO_FILE = "anima\\shuuko-komi-s1s2.safetensors"
SHUUKO_SIZE = 91866600


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
    def setUp(self):
        patcher = mock.patch.object(loras_module, "DEFAULT_PATH", FIXTURE)
        patcher.start()
        self.addCleanup(patcher.stop)
        user = mock.patch.object(
            loras_module,
            "user_registry_path",
            lambda: ROOT / "tests" / "fixtures" / "sin-capa-usuario.json",
        )
        user.start()
        self.addCleanup(user.stop)

    def require_disk(self, name: str) -> Path:
        """Ruta del LoRA en disco; skip si falta y el clon no trae assets (F3b).

        En el clon limpio del instalador las LoRAs de usuario no se descargan
        (no redistribuibles): con ``WAIFU_TEST_ASSETS=1`` la exigencia de disco
        se mantiene; sin la variable, el test se salta solo si el archivo falta.
        """
        path = LORAS_DIR / name
        if not path.is_file() and os.environ.get(TEST_ASSETS_ENV) != "1":
            self.skipTest(
                "LoRA no instalada en el clon (aporta el archivo o define "
                f"{TEST_ASSETS_ENV}=1): {name}"
            )
        return path

    def test_fixture_es_el_registro_efectivo_de_estos_tests(self):
        self.assertEqual(loras_module.DEFAULT_PATH, FIXTURE)
        self.assertTrue(FIXTURE.is_file())

    def test_registro_del_repo_publico_esta_vacio(self):
        payload = json.loads(
            (ROOT / "registry" / "loras.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["loras"], [])

    def test_seis_entradas_en_orden_del_json(self):
        self.assertEqual([item["id"] for item in list_loras()], REAL_IDS)

    def test_familias_en_orden_de_aparicion(self):
        self.assertEqual(families(), ["wan", "h3", "anima"])

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
        if os.environ.get(TEST_ASSETS_ENV) != "1":
            missing = [
                item["file"]
                for item in list_loras()
                if not (LORAS_DIR / item["file"]).is_file()
            ]
            if missing:
                self.skipTest(
                    "LoRAs de usuario no instaladas en el clon (define "
                    f"{TEST_ASSETS_ENV}=1): {', '.join(missing)}"
                )
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

    def test_reika_legacy_retirada_del_registro(self):
        with self.assertRaises(EngineError):
            get("reika-kurashiki")
        self.assertEqual(list_loras("animagine"), [])
        self.assertNotIn("reika-kurashiki", [item["id"] for item in list_loras()])

    def test_minimax_h3_de_la_plantilla(self):
        entry_data = get("minimax-h3-fl2v-turbo-4step")
        self.assertEqual(entry_data["family"], "h3")
        self.assertEqual(
            entry_data["file"],
            "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
        )

    def test_miku_nakano_anima_registrada_y_en_disco(self):
        miku = get(MIKU_ID)
        self.assertEqual(miku["family"], "anima")
        self.assertEqual(miku["file"], MIKU_FILE)
        self.assertEqual(miku["display_name"], "Miku Nakano (Anima v0.7)")
        self.assertEqual(miku["trigger"], "M1kuNakan0_anima")
        self.assertEqual(miku["default_weight"], 1.0)
        self.assertIn("1158201", miku["source"])
        self.assertIn("v3020851", miku["source"])
        self.assertIn("Anima", miku["notes"])
        self.assertIn("28", miku["notes"])
        self.assertIn("2.9B", miku["notes"])
        self.assertIn("M10", miku["notes"])
        path = self.require_disk(miku["file"])
        self.assertTrue(path.is_file(), f"falta en disco: {path}")
        self.assertEqual(path.stat().st_size, 132299512)
        self.assertEqual(
            validate_selection([{"id": MIKU_ID}]),
            [{"id": MIKU_ID, "file": MIKU_FILE, "weight": 1.0}],
        )
        normalized = validate_selection([{"id": MIKU_ID, "weight": 0.6}])
        self.assertEqual(normalized[0]["weight"], 0.6)

    def test_kurashiki_reika_saimin_anima_registrada_y_en_disco(self):
        saimin = get(SAIMIN_ID)
        self.assertEqual(saimin["family"], "anima")
        self.assertEqual(saimin["file"], SAIMIN_FILE)
        self.assertEqual(
            saimin["display_name"], "Kurashiki Reika Saimin Seishidou (Anima)"
        )
        self.assertEqual(saimin["trigger"], "kur4sh1k1r31k4")
        self.assertEqual(saimin["default_weight"], 1.0)
        self.assertIn("2026-09-25", saimin["source"])
        self.assertIn("training_6602895-20260804081407000", saimin["source"])
        self.assertIn("no verificada", saimin["license"])
        self.assertIn("dim 64", saimin["notes"])
        self.assertIn("alpha 32", saimin["notes"])
        self.assertIn("2500", saimin["notes"])
        self.assertIn("Anima-Base-v1.0", saimin["notes"])
        self.assertIn("modelspec.title", saimin["notes"])
        self.assertIn("Gestionar biblioteca", saimin["notes"])
        path = self.require_disk(saimin["file"])
        self.assertTrue(path.is_file(), f"falta en disco: {path}")
        self.assertEqual(path.stat().st_size, SAIMIN_SIZE)
        self.assertEqual(
            validate_selection([{"id": SAIMIN_ID}]),
            [{"id": SAIMIN_ID, "file": SAIMIN_FILE, "weight": 1.0}],
        )
        normalized = validate_selection([{"id": SAIMIN_ID, "weight": 0.6}])
        self.assertEqual(normalized[0]["weight"], 0.6)

    def test_shuuko_komi_s1s2_anima_registrada_y_en_disco(self):
        shuuko = get(SHUUKO_ID)
        self.assertEqual(shuuko["family"], "anima")
        self.assertEqual(shuuko["file"], SHUUKO_FILE)
        self.assertEqual(shuuko["display_name"], "Shuuko Komi S1S2 (Anima)")
        self.assertEqual(shuuko["trigger"], "shuuko komi")
        self.assertEqual(shuuko["default_weight"], 1.0)
        self.assertIn("2026-09-25", shuuko["source"])
        self.assertIn("nochekaiser", shuuko["source"])
        self.assertIn(
            "shuuko-komi-s1s2-anima-lora-nochekaiser", shuuko["source"]
        )
        self.assertIn("no verificada", shuuko["license"])
        self.assertIn("dim 32", shuuko["notes"])
        self.assertIn("alpha 32", shuuko["notes"])
        self.assertIn("408", shuuko["notes"])
        self.assertIn("1000", shuuko["notes"])
        self.assertIn("anima_baseV10", shuuko["notes"])
        self.assertIn("shuuko komi", shuuko["notes"])
        self.assertIn("komi shouko", shuuko["notes"])
        path = self.require_disk(shuuko["file"])
        self.assertTrue(path.is_file(), f"falta en disco: {path}")
        self.assertEqual(path.stat().st_size, SHUUKO_SIZE)
        self.assertEqual(
            validate_selection([{"id": SHUUKO_ID}]),
            [{"id": SHUUKO_ID, "file": SHUUKO_FILE, "weight": 1.0}],
        )
        normalized = validate_selection([{"id": SHUUKO_ID, "weight": 0.6}])
        self.assertEqual(normalized[0]["weight"], 0.6)

    def test_filtro_anima_miku_saimin_shuuko_y_mina(self):
        self.assertEqual(
            [item["id"] for item in list_loras("anima")],
            [
                MIKU_ID,
                SAIMIN_ID,
                SHUUKO_ID,
                "mina-ashido-1-anima",
                "mina-ashido-2-anima",
            ],
        )

    def test_comment_del_registro(self):
        payload = load_registry()
        self.assertEqual(payload["version"], 1)
        self.assertIn("Registro local de LoRAs", payload["_comment"])
        self.assertIn("Gestionar biblioteca", payload["_comment"])

    def test_filtro_por_familia(self):
        self.assertEqual(
            [item["id"] for item in list_loras(family="wan")],
            ["lightx2v-wan-high", "lightx2v-wan-low"],
        )
        self.assertEqual(list_loras("animagine"), [])
        self.assertEqual(
            [item["id"] for item in list_loras("h3")],
            ["minimax-h3-fl2v-turbo-4step"],
        )
        anima = list_loras("anima")
        self.assertEqual(
            [item["id"] for item in anima],
            [
                MIKU_ID,
                SAIMIN_ID,
                SHUUKO_ID,
                "mina-ashido-1-anima",
                "mina-ashido-2-anima",
            ],
        )
        self.assertEqual([item["default_weight"] for item in anima], [1.0] * 5)
        self.assertEqual(list_loras("no-existe"), [])

    def test_get_devuelve_copia_e_inexistente_lanza(self):
        first = get(WAN_HIGH_ID)
        first["file"] = "mutado.safetensors"
        self.assertEqual(get(WAN_HIGH_ID)["file"], WAN_HIGH_FILE)
        with self.assertRaises(EngineError):
            get("no-existe")

    def test_list_loras_devuelve_copias(self):
        items = list_loras()
        items[0]["file"] = "mutado.safetensors"
        self.assertNotEqual(list_loras()[0]["file"], "mutado.safetensors")


class ValidateSelectionTests(unittest.TestCase):
    def test_normaliza_con_file_y_peso_del_registro(self):
        normalized = validate_selection([{"id": MIKU_ID}])
        self.assertEqual(
            normalized,
            [{"id": MIKU_ID, "file": MIKU_FILE, "weight": 1.0}],
        )

    def test_peso_explicito_y_texto_numerico(self):
        normalized = validate_selection(
            [
                {"id": WAN_HIGH_ID, "weight": 0.8},
                {"id": MIKU_ID, "weight": "1.5"},
            ]
        )
        self.assertEqual(normalized[0]["weight"], 0.8)
        self.assertEqual(normalized[1]["weight"], 1.5)

    def test_pesos_en_los_limites(self):
        normalized = validate_selection(
            [
                {"id": MIKU_ID, "weight": 0},
                {"id": MIKU_ID, "weight": 2},
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
        for selection in ([None], [MIKU_ID], [{"weight": 1.0}]):
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
                    validate_selection([{"id": MIKU_ID, "weight": weight}])


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


class UpdateDeleteEntryTests(unittest.TestCase):
    """Edicion y borrado de entradas con registro temporal (M10-5b)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "loras.json"
        self.write(
            {
                "version": 1,
                "_comment": "nota",
                "loras": [entry(), entry(id="otra", family="anima")],
            }
        )

    def write(self, payload) -> None:
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_update_campos_persiste_y_devuelve_copia(self):
        updated = update_entry(
            "lora-test",
            {"family": "anima", "default_weight": 0.6, "trigger": "t1"},
            path=self.path,
        )
        self.assertEqual(updated["family"], "anima")
        self.assertEqual(updated["default_weight"], 0.6)
        updated["display_name"] = "mutado"
        saved = get("lora-test", path=self.path)
        self.assertEqual(saved["display_name"], "Lora de test")
        self.assertEqual(saved["file"], "test.safetensors")
        self.assertEqual(saved["trigger"], "t1")

    def test_update_parcial_conserva_el_resto(self):
        update_entry("lora-test", {"trigger": "t1"}, path=self.path)
        saved = get("lora-test", path=self.path)
        self.assertEqual(saved["trigger"], "t1")
        self.assertEqual(saved["source"], "local (test)")
        self.assertEqual(saved["license"], "test")

    def test_update_claves_extra_se_ignoran(self):
        update_entry("lora-test", {"trigger": "t", "inventado": 5}, path=self.path)
        self.assertEqual(
            set(get("lora-test", path=self.path)),
            {
                "id",
                "family",
                "file",
                "display_name",
                "trigger",
                "default_weight",
                "source",
                "license",
                "notes",
            },
        )

    def test_update_id_inmutable(self):
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(EngineError) as ctx:
            update_entry("lora-test", {"id": "otro"}, path=self.path)
        self.assertIn("inmutable", str(ctx.exception))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_update_mismo_id_permitido(self):
        updated = update_entry(
            "lora-test", {"id": "lora-test", "trigger": "t"}, path=self.path
        )
        self.assertEqual(updated["id"], "lora-test")

    def test_update_inexistente_lanza(self):
        with self.assertRaises(EngineError):
            update_entry("no-existe", {"trigger": "t"}, path=self.path)

    def test_update_invalido_lanza_y_no_toca_el_fichero(self):
        before = self.path.read_text(encoding="utf-8")
        for changes in (
            {"file": ""},
            {"default_weight": 3},
            {"trigger": 5},
            None,
            [],
            "x",
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(EngineError):
                    update_entry("lora-test", changes, path=self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_update_conserva_orden_y_comment(self):
        update_entry("lora-test", {"family": "z"}, path=self.path)
        payload = self.read()
        self.assertEqual(
            [item["id"] for item in payload["loras"]], ["lora-test", "otra"]
        )
        self.assertEqual(payload["_comment"], "nota")

    def test_delete_quita_solo_la_entrada(self):
        removed = delete_entry("lora-test", path=self.path)
        self.assertEqual(removed["id"], "lora-test")
        removed["file"] = "mutado.safetensors"
        self.assertEqual([item["id"] for item in list_loras(path=self.path)], ["otra"])
        self.assertEqual(self.read()["_comment"], "nota")

    def test_delete_inexistente_lanza_y_no_toca_el_fichero(self):
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(EngineError):
            delete_entry("no-existe", path=self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_delete_no_deja_tmp(self):
        delete_entry("lora-test", path=self.path)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])


def safetensors_blob(metadata=None, tensors=None) -> bytes:
    header: dict = dict(tensors or {})
    if metadata is not None:
        header["__metadata__"] = metadata
    encoded = json.dumps(header).encode("utf-8")
    encoded += b" " * ((8 - len(encoded) % 8) % 8)
    return struct.pack("<Q", len(encoded)) + encoded + b"\x00" * 64


class InspectSafetensorsTests(unittest.TestCase):
    def test_metadata_completa(self):
        raw = safetensors_blob(
            {
                "ss_network_dim": "32",
                "ss_network_alpha": "16",
                "ss_sd_model_name": "anima_baseV10",
                "modelspec.title": "Miku Nakano (Anima v0.7)",
                "ss_tag_frequency": json.dumps(
                    {"dataset": {" miku   nakano ": 42, "otro": 5}}
                ),
            }
        )
        self.assertEqual(
            inspect_safetensors(raw),
            {
                "title": "Miku Nakano (Anima v0.7)",
                "trigger": "miku nakano",
                "dim": 32,
                "alpha": 16,
                "base": "anima_baseV10",
            },
        )

    def test_trigger_titulo_cuando_frecuencia_baja(self):
        raw = safetensors_blob(
            {
                "modelspec.title": "Mi Lora",
                "ss_tag_frequency": json.dumps({"ds": {"casi": 9}}),
            }
        )
        self.assertEqual(inspect_safetensors(raw)["trigger"], "Mi Lora")

    def test_trigger_titulo_cuando_empate(self):
        raw = safetensors_blob(
            {
                "modelspec.title": "Empatada",
                "ss_tag_frequency": json.dumps({"ds": {"uno": 20, "dos": 20}}),
            }
        )
        self.assertEqual(inspect_safetensors(raw)["trigger"], "Empatada")

    def test_trigger_sin_frecuencia_y_titulo_largo(self):
        raw = safetensors_blob({"modelspec.title": "x" * 49})
        self.assertEqual(inspect_safetensors(raw)["trigger"], "")

    def test_trigger_sin_titulo(self):
        raw = safetensors_blob({})
        self.assertEqual(inspect_safetensors(raw)["trigger"], "")

    def test_base_model_version_como_fallback(self):
        raw = safetensors_blob({"ss_base_model_version": "sdxl_base_v1-0"})
        self.assertEqual(inspect_safetensors(raw)["base"], "sdxl_base_v1-0")

    def test_dim_alpha_invalidos_son_none(self):
        raw = safetensors_blob(
            {
                "ss_network_dim": "no-numero",
                "ss_network_alpha": True,
            }
        )
        result = inspect_safetensors(raw)
        self.assertIsNone(result["dim"])
        self.assertIsNone(result["alpha"])

    def test_sin_metadata_devuelve_vacios(self):
        raw = safetensors_blob(None, {"lora_a.weight": {"dtype": "F16"}})
        self.assertEqual(
            inspect_safetensors(raw),
            {"title": "", "trigger": "", "dim": None, "alpha": None, "base": ""},
        )

    def test_datos_invalidos_no_lanzan(self):
        for raw in (b"", b"\x00", b"garbage-safetensors", b"\xff" * 32):
            with self.subTest(raw=raw):
                self.assertEqual(
                    inspect_safetensors(raw),
                    {
                        "title": "",
                        "trigger": "",
                        "dim": None,
                        "alpha": None,
                        "base": "",
                    },
                )

    def test_cabecera_no_dict_o_truncada(self):
        self.assertIsNone(safetensors_header(struct.pack("<Q", 2) + b"[]"))
        self.assertIsNone(safetensors_header(struct.pack("<Q", 500) + b"{}"))
        self.assertEqual(
            safetensors_header(safetensors_blob({"modelspec.title": "t"})),
            {"__metadata__": {"modelspec.title": "t"}},
        )
        self.assertEqual(safetensors_header(b"corto"), None)


if __name__ == "__main__":
    unittest.main()
