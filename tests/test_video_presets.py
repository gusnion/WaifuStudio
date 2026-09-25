"""Tests CPU del catalogo de presets de video Wan (M10-2a). Sin red ni GPU.

Verifican ``registry/video_presets-v1.json`` y su exposicion en
``app.video_presets`` (carga estricta, resolucion manual/desconocido y copias).
"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from app import video_presets as video_presets_module
from app.config import APP_ROOT
from app.engine import EngineError
from app.video_presets import (
    MAX_PRESET_STEPS,
    MIN_PRESET_STEPS,
    PRESETS_PATH,
    PRESET_MANUAL,
    get_video_preset,
    list_video_presets,
    load_video_presets,
    resolve_video_preset,
    video_presets,
)

EXPECTED_IDS = ("rapido", "calidad")

EXPECTED = {
    "rapido": {
        "label": "Rápido",
        "vertical": {"width": 432, "height": 768},
        "horizontal": {"width": 768, "height": 432},
        "sampler": "euler",
        "scheduler": "simple",
        "steps": 20,
        "shift": 8.0,
    },
    "calidad": {
        "label": "Calidad",
        "vertical": {"width": 512, "height": 896},
        "horizontal": {"width": 896, "height": 512},
        "sampler": "er_sde",
        "scheduler": "simple",
        "steps": 30,
        "shift": 5.0,
    },
}


def _valid_entry() -> dict:
    return {
        "id": "manual-test",
        "label": "Test",
        "note": "nota",
        "vertical": {"width": 432, "height": 768},
        "horizontal": {"width": 768, "height": 432},
        "sampler": "euler",
        "scheduler": "simple",
        "steps": 20,
        "shift": 8.0,
    }


class RegistryFileTests(unittest.TestCase):
    def test_path_derivado_de_app_root(self):
        self.assertEqual(PRESETS_PATH, APP_ROOT / "registry" / "video_presets-v1.json")
        self.assertTrue(PRESETS_PATH.is_file())

    def test_json_del_catalogo(self):
        data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "video_presets/v1")
        self.assertEqual([entry["id"] for entry in data["presets"]], list(EXPECTED_IDS))

    def test_perfiles_certificados_y_provisionales(self):
        catalog = video_presets()
        for preset_id, expected in EXPECTED.items():
            with self.subTest(preset_id=preset_id):
                preset = catalog[preset_id]
                self.assertEqual(preset["label"], expected["label"])
                self.assertIn("provisional hasta el A/B de M10-2a", preset["note"])
                self.assertEqual(preset["vertical"], expected["vertical"])
                self.assertEqual(preset["horizontal"], expected["horizontal"])
                self.assertEqual(preset["sampler"], expected["sampler"])
                self.assertEqual(preset["scheduler"], expected["scheduler"])
                self.assertEqual(preset["steps"], expected["steps"])
                self.assertEqual(preset["shift"], expected["shift"])
                for aspect in ("vertical", "horizontal"):
                    for name in ("width", "height"):
                        self.assertEqual(preset[aspect][name] % 16, 0)


class ListAndResolveTests(unittest.TestCase):
    def test_list_en_orden_y_copia(self):
        listed = list_video_presets()
        self.assertEqual([item["id"] for item in listed], list(EXPECTED_IDS))
        listed[0]["vertical"]["width"] = 1
        self.assertEqual(video_presets()["rapido"]["vertical"]["width"], 432)

    def test_resolve_manual_o_ausente(self):
        for value in (None, "", "  ", PRESET_MANUAL, " manual "):
            with self.subTest(value=value):
                self.assertIsNone(resolve_video_preset(value))

    def test_resolve_conocido(self):
        preset = resolve_video_preset("calidad")
        self.assertIsNotNone(preset)
        self.assertEqual(preset["sampler"], "er_sde")
        self.assertEqual(preset["steps"], 30)

    def test_resolve_desconocido_o_no_str(self):
        for value in ("nope", "RAPIDO", 5, ["rapido"], True):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    resolve_video_preset(value)

    def test_get_video_preset_estricto(self):
        self.assertEqual(get_video_preset("rapido")["steps"], 20)
        self.assertEqual(get_video_preset(" calidad ")["sampler"], "er_sde")
        for value in ("nope", "manual", None, 5):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    get_video_preset(value)

    def test_alias_perezoso_estilo_formats(self):
        self.assertEqual(video_presets_module.VIDEO_PRESETS["calidad"]["steps"], 30)
        self.assertEqual(video_presets_module.PRESETS["rapido"]["steps"], 20)
        with self.assertRaises(AttributeError):
            video_presets_module.OTRO  # noqa: B018


class LoadVideoPresetsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "presets.json"

    def write(self, payload) -> Path:
        if isinstance(payload, str):
            self.path.write_text(payload, encoding="utf-8")
        else:
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.path

    def catalog(self, entries) -> dict:
        return {"schema_version": "video_presets/v1", "presets": entries}

    def test_valido(self):
        loaded = load_video_presets(self.write(self.catalog([_valid_entry()])))
        self.assertEqual(list(loaded), ["manual-test"])

    def test_ilegible_o_json_invalido(self):
        with self.assertRaises(EngineError):
            load_video_presets(Path(self._tmp.name) / "no-existe.json")
        with self.assertRaises(EngineError):
            load_video_presets(self.write("{no json"))

    def test_forma_del_catalogo(self):
        for payload in ([], {"presets": {}}, {"presets": []}, "no-json"):
            with self.subTest(payload=payload):
                with self.assertRaises(EngineError):
                    load_video_presets(self.write(payload))

    def test_entrada_no_dict_y_campos_requeridos(self):
        with self.assertRaises(EngineError):
            load_video_presets(self.write(self.catalog(["x"])))
        for field in ("id", "label", "note", "sampler", "scheduler", "steps", "shift"):
            with self.subTest(field=field):
                entry = _valid_entry()
                del entry[field]
                with self.assertRaises(EngineError):
                    load_video_presets(self.write(self.catalog([entry])))

    def test_id_manual_reservado_y_duplicado(self):
        entry = _valid_entry()
        entry["id"] = PRESET_MANUAL
        with self.assertRaises(EngineError):
            load_video_presets(self.write(self.catalog([entry])))
        with self.assertRaises(EngineError):
            load_video_presets(
                self.write(self.catalog([_valid_entry(), _valid_entry()]))
            )

    def test_sampler_scheduler_invalidos(self):
        for field, value in (("sampler", "nope"), ("scheduler", "nope")):
            with self.subTest(field=field):
                entry = _valid_entry()
                entry[field] = value
                with self.assertRaises(EngineError):
                    load_video_presets(self.write(self.catalog([entry])))

    def test_steps_invalidos(self):
        for value in (True, 0, MAX_PRESET_STEPS + 1, 20.5, "20"):
            with self.subTest(value=value):
                entry = _valid_entry()
                entry["steps"] = value
                with self.assertRaises(EngineError):
                    load_video_presets(self.write(self.catalog([entry])))

    def test_shift_invalidos(self):
        for value in (True, 0, -1, "8", float("nan"), float("inf")):
            with self.subTest(value=value):
                entry = _valid_entry()
                entry["shift"] = value
                with self.assertRaises(EngineError):
                    load_video_presets(self.write(self.catalog([entry])))

    def test_tamanos_invalidos(self):
        cases = (
            ("vertical", None),
            ("vertical", {"width": 431, "height": 768}),
            ("vertical", {"width": 432}),
            ("horizontal", {"width": 768, "height": 432.0}),
            ("horizontal", {"width": True, "height": 432}),
        )
        for aspect, value in cases:
            with self.subTest(aspect=aspect, value=value):
                entry = _valid_entry()
                entry[aspect] = value
                with self.assertRaises(EngineError):
                    load_video_presets(self.write(self.catalog([entry])))

    def test_limits_expuestos(self):
        self.assertEqual((MIN_PRESET_STEPS, MAX_PRESET_STEPS), (1, 200))
        self.assertTrue(math.isfinite(_valid_entry()["shift"]))


if __name__ == "__main__":
    unittest.main()
