"""Tests CPU del catalogo de perfiles H3 FL2VA (M10-2c-1). Sin red ni GPU.

Verifican ``registry/h3_presets-v1.json`` y su exposicion en ``app.h3_presets``
(carga estricta, resolucion por id, plantilla por perfil, snap 5+17n de los
segundos y validacion de resoluciones vertical/horizontal). M10-2c-3 añade las
variantes (LoRA + pasos, default ``turbo4``).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app import h3_presets as h3_presets_module
from app.config import APP_ROOT
from app.engine import EngineError, load_graph
from app.h3_presets import (
    DEFAULT_PROFILE,
    DEFAULT_VARIANT,
    H3_FPS,
    H3_MAX_FRAMES,
    H3_MAX_PIXELS,
    H3_MIN_FRAMES,
    H3_SECONDS,
    PROFILE_COMPATIBLE_VARIANTS,
    PROFILES_PATH,
    get_h3_presets,
    get_h3_profile,
    get_h3_variant,
    h3_aspect,
    h3_catalog,
    h3_default_size,
    h3_frames_for_seconds,
    h3_resolutions,
    h3_seconds,
    h3_template_path,
    is_vdn_installed,
    list_h3_profiles,
    list_h3_variants,
    load_h3_presets,
    require_h3_frames,
    require_h3_seconds,
    resolve_h3_profile,
    resolve_h3_variant,
    split_chained_seconds,
    validate_h3_profile_variant,
    validate_h3_size,
)

EXPECTED_IDS = ("referencia", "calidad", "ligero", "vdn", "ref2va")
EXPECTED_FRAMES = {5: 124, 8: 192, 10: 243, 12: 294, 15: 362}
EXPECTED_VARIANTS = (
    {
        "id": "turbo4",
        "label": "turbo",
        "lora": "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
        "steps": 4,
    },
    {
        "id": "turbo8",
        "label": "mejor calidad, ~2×",
        "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        "steps": 8,
    },
    {
        "id": "vdn8",
        "label": "VDN 8-Pasos (Ultra Rápido)",
        "lora": None,
        "steps": 8,
    },
)
VARIANT_LORAS_DIR = APP_ROOT / "ComfyUI" / "models" / "loras"

EXPECTED_ASSETS = {
    "referencia": {
        "template": "h3_fl2va_vertical.api.json",
        "dit": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "vae_video": "minimax_h3_video_vae_fp16.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "encoder": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "projection": None,
        "seconds_recomendados": [8],
    },
    "calidad": {
        "template": "h3_fl2va_calidad.api.json",
        "dit": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "vae_video": "minimax_h3_video_vae_fp16.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "encoder": "qwen3vl_4b_fp8_scaled.safetensors",
        "projection": "mmh3-4b-ClipProj-v3.1.safetensors",
        "seconds_recomendados": [8, 10, 12],
    },
    "ligero": {
        "template": "h3_fl2va_ligero.api.json",
        "dit": "minimax_h3_fl2va_pruned-w4a8_convrot_pruned.safetensors",
        "vae_video": "minimax_h3_video_vae_int8_convrot.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "encoder": "qwen3vl_4b_fp8_scaled.safetensors",
        "projection": "mmh3-4b-ClipProj-v3.1.safetensors",
        "seconds_recomendados": [8, 10, 12, 15],
    },
    "vdn": {
        "template": "h3_vdn_8step.api.json",
        "dit": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "vae_video": "minimax_h3_video_vae_fp16.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "encoder": "qwen3vl_4b_fp8_scaled.safetensors",
        "projection": "mmh3-4b-ClipProj-v3.1.safetensors",
        "lora": None,
        "seconds_recomendados": [5, 8, 10, 12],
    },
    "ref2va": {
        "template": "h3_ref2va.api.json",
        "dit": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        "vae_video": "minimax_h3_video_vae_fp16.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "encoder": "qwen3vl_4b_fp8_scaled.safetensors",
        "projection": "mmh3-4b-ClipProj-v3.1.safetensors",
        "lora": None,
        "seconds_recomendados": [8],
    },
}

LORA = "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"
VERTICAL_TEMPLATE_PATH = APP_ROOT / "workflows" / "h3_fl2va_vertical.api.json"


def _valid_profile() -> dict:
    return {
        "id": "prueba",
        "label": "Prueba",
        "note": "nota",
        "template": "h3_fl2va_vertical.api.json",
        "dit": "diffusion_models/dit.safetensors",
        "vae_video": "minimax_h3_video_vae_fp16.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "encoder": None,
        "projection": None,
        "lora": None,
        "seconds_recomendados": [8],
    }


def _valid_catalog(entries=None, variants=None) -> dict:
    return {
        "schema_version": "h3_presets/v1",
        "seconds": [5, 8, 10, 12, 15, 20, 24, 25, 30],
        "variants": [dict(variant) for variant in EXPECTED_VARIANTS]
        if variants is None
        else variants,
        "resoluciones": {
            "vertical": [{"width": 576, "height": 1024}],
            "horizontal": [{"width": 1024, "height": 576}],
        },
        "perfiles": [_valid_profile()] if entries is None else entries,
    }


class RegistryFileTests(unittest.TestCase):
    def test_path_derivado_de_app_root(self):
        self.assertEqual(PROFILES_PATH, APP_ROOT / "registry" / "h3_presets-v1.json")
        self.assertTrue(PROFILES_PATH.is_file())

    def test_json_del_catalogo(self):
        data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "h3_presets/v1")
        self.assertEqual([entry["id"] for entry in data["perfiles"]], list(EXPECTED_IDS))
        self.assertEqual(data["seconds"], list(H3_SECONDS))
        self.assertEqual(data["variants"], list(EXPECTED_VARIANTS))

    def test_variantes_y_loras_en_disco(self):
        self.assertEqual(h3_catalog()["variants"], list(EXPECTED_VARIANTS))
        for variant in list_h3_variants():
            with self.subTest(variant=variant["id"]):
                self.assertTrue(variant["label"])
                self.assertTrue(variant["steps"] >= 1)
                if variant.get("lora") is not None:
                    self.assertTrue(
                        (VARIANT_LORAS_DIR / variant["lora"]).is_file(),
                        f"falta en disco: {variant['lora']}",
                    )

    def test_segundos_y_resoluciones(self):
        self.assertEqual(h3_seconds(), [5, 8, 10, 12, 15, 20, 24, 25, 30])
        resolutions = h3_resolutions()
        self.assertEqual(
            [(r["width"], r["height"]) for r in resolutions["vertical"]],
            [(576, 1024), (768, 1344)],
        )
        self.assertEqual(
            [(r["width"], r["height"]) for r in resolutions["horizontal"]],
            [(1024, 576), (1344, 768)],
        )
        for aspect in ("vertical", "horizontal"):
            for size in resolutions[aspect]:
                with self.subTest(aspect=aspect, size=size):
                    self.assertEqual(size["width"] % 32, 0)
                    self.assertEqual(size["height"] % 32, 0)
                    self.assertLessEqual(size["width"] * size["height"], H3_MAX_PIXELS)

    def test_perfiles_y_assets_certificados(self):
        catalog = {profile["id"]: profile for profile in list_h3_profiles()}
        self.assertEqual(list(catalog), list(EXPECTED_IDS))
        for profile_id, expected in EXPECTED_ASSETS.items():
            with self.subTest(profile_id=profile_id):
                profile = catalog[profile_id]
                for field, value in expected.items():
                    self.assertEqual(profile[field], value)
                self.assertEqual(profile["lora"], expected.get("lora", LORA))
                self.assertTrue(profile["label"])
                self.assertTrue(profile["note"])
                for field in ("dit", "vae_video", "vae_audio"):
                    self.assertTrue(profile[field])

    def test_plantillas_existen_y_comparten_ids(self):
        reference = load_graph(VERTICAL_TEMPLATE_PATH)
        for profile in list_h3_profiles():
            with self.subTest(profile=profile["id"]):
                path = h3_template_path(profile)
                self.assertEqual(path.parent, APP_ROOT / "workflows")
                self.assertTrue(path.is_file())
                graph = load_graph(path)
                expected_nodes = set(reference)
                if profile["lora"] is None:
                    expected_nodes = expected_nodes - {"134"}
                self.assertTrue(expected_nodes <= set(graph))
                expected_extra = set()
                if profile["projection"]:
                    expected_extra.add("135")
                if profile["id"] == "vdn":
                    expected_extra.add("136")
                if profile["id"] == "ref2va":
                    expected_extra.update({"142", "143"})
                self.assertEqual(set(graph) - expected_nodes, expected_extra)
                expected_class = (
                    "MiniMaxH3ReferenceToVideo"
                    if profile["id"] == "ref2va"
                    else "MiniMaxH3ImageToVideo"
                )
                self.assertEqual(graph["131"]["class_type"], expected_class)
                self.assertEqual(graph["131"]["inputs"]["width"], 576)
                self.assertEqual(graph["131"]["inputs"]["height"], 1024)
                self.assertEqual(graph["131"]["inputs"]["length"], 192)
                self.assertEqual(graph["127"]["inputs"]["unet_name"], profile["dit"])
                self.assertEqual(
                    graph["119"]["inputs"]["vae_name"], profile["vae_video"]
                )
                self.assertEqual(
                    graph["120"]["inputs"]["vae_name"], profile["vae_audio"]
                )
                if profile["lora"] is not None:
                    self.assertEqual(graph["134"]["inputs"]["lora_name"], profile["lora"])
                else:
                    self.assertNotIn("134", graph)

    def test_clip_proyectado_alimenta_minimax(self):
        catalog = {profile["id"]: profile for profile in list_h3_profiles()}
        for profile_id in ("calidad", "ligero", "vdn", "ref2va"):
            with self.subTest(profile_id=profile_id):
                profile = catalog[profile_id]
                graph = load_graph(h3_template_path(profile))
                self.assertEqual(graph["128"]["class_type"], "CLIPLoader")
                self.assertEqual(
                    graph["128"]["inputs"]["clip_name"], profile["encoder"]
                )
                self.assertEqual(graph["128"]["inputs"]["type"], "krea2")
                self.assertEqual(graph["135"]["class_type"], "ClipProjApply")
                self.assertEqual(graph["135"]["inputs"]["clip"], ["128", 0])
                self.assertEqual(
                    graph["135"]["inputs"]["projection"], profile["projection"]
                )
                self.assertEqual(graph["131"]["inputs"]["clip"], ["135", 0])
        reference = catalog["referencia"]
        graph = load_graph(h3_template_path(reference))
        self.assertNotIn("135", graph)
        self.assertEqual(graph["128"]["inputs"]["type"], "minimax")
        self.assertEqual(graph["128"]["inputs"]["clip_name"], reference["encoder"])
        self.assertEqual(graph["131"]["inputs"]["clip"], ["128", 0])


class ListAndResolveTests(unittest.TestCase):
    def test_list_en_orden_y_copia(self):
        listed = list_h3_profiles()
        self.assertEqual([item["id"] for item in listed], list(EXPECTED_IDS))
        listed[0]["seconds_recomendados"].append(5)
        self.assertEqual(list_h3_profiles()[0]["seconds_recomendados"], [8])

    def test_catalog_copia(self):
        catalog = h3_catalog()
        self.assertEqual([item["id"] for item in catalog["profiles"]], list(EXPECTED_IDS))
        self.assertEqual(catalog["seconds"], list(H3_SECONDS))
        catalog["profiles"][0]["label"] = "x"
        self.assertEqual(list_h3_profiles()[0]["label"], "Referencia")

    def test_resolve_ausente_o_vacio_es_referencia(self):
        for value in (None, "", "  "):
            with self.subTest(value=value):
                self.assertEqual(resolve_h3_profile(value)["id"], DEFAULT_PROFILE)

    def test_resolve_conocido(self):
        self.assertEqual(resolve_h3_profile("calidad")["id"], "calidad")
        self.assertEqual(resolve_h3_profile(" ligero ")["id"], "ligero")

    def test_resolve_desconocido_o_no_str(self):
        for value in ("nope", "REFERENCIA", 5, ["calidad"], True):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    resolve_h3_profile(value)

    def test_get_h3_profile_estricto(self):
        self.assertEqual(get_h3_profile("calidad")["projection"], EXPECTED_ASSETS["calidad"]["projection"])
        self.assertEqual(get_h3_profile(" ligero ")["id"], "ligero")
        for value in ("nope", None, 5):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    get_h3_profile(value)

    def test_default_size_por_aspecto(self):
        self.assertEqual(h3_default_size("vertical"), (576, 1024))
        self.assertEqual(h3_default_size("horizontal"), (1024, 576))
        with self.assertRaises(EngineError):
            h3_default_size("cuadrado")


class VariantTests(unittest.TestCase):
    def test_default_es_turbo4(self):
        self.assertEqual(DEFAULT_VARIANT, "turbo4")
        for value in (None, "", "  "):
            with self.subTest(value=value):
                self.assertEqual(resolve_h3_variant(value)["id"], "turbo4")

    def test_resolve_conocida(self):
        self.assertEqual(resolve_h3_variant("turbo8")["steps"], 8)
        self.assertEqual(
            resolve_h3_variant(" turbo4 ")["lora"], EXPECTED_VARIANTS[0]["lora"]
        )

    def test_resolve_desconocida_o_no_str(self):
        for value in ("nope", "TURBO8", 5, ["turbo8"], True):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    resolve_h3_variant(value)

    def test_get_estricto(self):
        self.assertEqual(get_h3_variant("turbo8")["label"], "mejor calidad, ~2×")
        for value in ("nope", None, 5):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    get_h3_variant(value)

    def test_list_y_catalog_son_copias(self):
        listed = list_h3_variants()
        listed[0]["steps"] = 99
        self.assertEqual(list_h3_variants()[0]["steps"], 4)
        catalog = h3_catalog()
        catalog["variants"][1]["lora"] = "x.safetensors"
        self.assertEqual(list_h3_variants()[1]["lora"], EXPECTED_VARIANTS[1]["lora"])


class FramesTests(unittest.TestCase):
    def test_snap_5_mas_17n(self):
        self.assertEqual(H3_FPS, 24)
        for seconds, frames in EXPECTED_FRAMES.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(h3_frames_for_seconds(seconds), frames)
                self.assertEqual(h3_frames_for_seconds(float(seconds)), frames)
                self.assertEqual(frames % 17, 5)
                self.assertTrue(H3_MIN_FRAMES <= frames <= H3_MAX_FRAMES)

    def test_invalidos(self):
        for value in (0, 4, 4.9, 16, -1, "abc", None, True, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    h3_frames_for_seconds(value)

    def test_require_h3_frames(self):
        for frames in (124, 192, 243, 294, 362):
            with self.subTest(frames=frames):
                self.assertEqual(require_h3_frames(frames), frames)
        for value in (5, 81, 120, 123, 363, 400, True, "192", 192.0, None):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    require_h3_frames(value)

    def test_require_h3_seconds(self):
        for value in (5, 8, 10, 12, 15, 20, 24, 25, 30, 8.0):
            with self.subTest(value=value):
                self.assertEqual(require_h3_seconds(value), int(value))
        for value in (0, 6, 7, 15.5, 16, 21, 29, 31, "8", True, None, float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    require_h3_seconds(value)

    def test_split_chained_seconds(self):
        self.assertEqual(split_chained_seconds(5), [5])
        self.assertEqual(split_chained_seconds(8), [8])
        self.assertEqual(split_chained_seconds(10), [10])
        self.assertEqual(split_chained_seconds(12), [12])
        self.assertEqual(split_chained_seconds(15), [15])
        self.assertEqual(split_chained_seconds(20), [10, 10])
        self.assertEqual(split_chained_seconds(24), [12, 12])
        self.assertEqual(split_chained_seconds(25), [10, 15])
        self.assertEqual(split_chained_seconds(30), [15, 15])



class SizeTests(unittest.TestCase):
    def test_validos(self):
        self.assertEqual(h3_aspect(576, 1024), "vertical")
        self.assertEqual(h3_aspect(1024, 576), "horizontal")
        self.assertEqual(validate_h3_size(576, 1024), (576, 1024))
        self.assertEqual(validate_h3_size(768, 1344), (768, 1344))
        self.assertEqual(validate_h3_size(1344, 768, "horizontal"), (1344, 768))
        self.assertEqual(validate_h3_size(768, 1344, "vertical"), (768, 1344))

    def test_area_excedida(self):
        self.assertEqual(H3_MAX_PIXELS, 768 * 1344)
        for width, height in ((2048, 576), (1344, 1024), (1024, 1344)):
            with self.subTest(width=width, height=height):
                self.assertGreater(width * height, H3_MAX_PIXELS)
                with self.assertRaises(EngineError):
                    validate_h3_size(width, height)

    def test_multiplo_32_y_tipos(self):
        for width, height in ((600, 1024), (576, 1000), (576, 1024.0), (True, 1024), ("576", 1024)):
            with self.subTest(width=width, height=height):
                with self.assertRaises(EngineError):
                    validate_h3_size(width, height)

    def test_cuadrada_y_aspecto_incorrecto(self):
        with self.assertRaises(EngineError):
            validate_h3_size(1024, 1024)
        with self.assertRaises(EngineError):
            validate_h3_size(576, 1024, "horizontal")
        with self.assertRaises(EngineError):
            validate_h3_size(1024, 576, "vertical")
        with self.assertRaises(EngineError):
            validate_h3_size(576, 1024, "cuadrado")


class LoadH3PresetsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "h3.json"

    def write(self, payload) -> Path:
        if isinstance(payload, str):
            self.path.write_text(payload, encoding="utf-8")
        else:
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.path

    def test_valido(self):
        loaded = load_h3_presets(self.write(_valid_catalog()))
        self.assertEqual(list(loaded["profiles"]), ["prueba"])
        self.assertEqual(loaded["seconds"], list(H3_SECONDS))
        self.assertEqual(
            [variant["id"] for variant in loaded["variants"].values()],
            ["turbo4", "turbo8", "vdn8"],
        )

    def test_variante_con_lora_null(self):
        loaded = load_h3_presets(
            self.write(
                _valid_catalog(
                    variants=[{"id": "turbo4", "label": "x", "lora": None, "steps": 4}]
                )
            )
        )
        self.assertIsNone(loaded["variants"]["turbo4"]["lora"])

    def test_ilegible_o_json_invalido(self):
        with self.assertRaises(EngineError):
            load_h3_presets(Path(self._tmp.name) / "no-existe.json")
        with self.assertRaises(EngineError):
            load_h3_presets(self.write("{no json"))

    def test_forma_del_catalogo(self):
        for payload in ([], {"perfiles": {}}, {"perfiles": []}, "no-json"):
            with self.subTest(payload=payload):
                with self.assertRaises(EngineError):
                    load_h3_presets(self.write(payload))

    def test_seconds_invalidos(self):
        cases = (
            None,
            [],
            [5, 6],
            [5, 5],
            [8, 5],
            [5, 8.0],
            [True],
        )
        for value in cases:
            with self.subTest(value=value):
                payload = _valid_catalog()
                payload["seconds"] = value
                with self.assertRaises(EngineError):
                    load_h3_presets(self.write(payload))

    def test_variants_invalidas(self):
        payload = _valid_catalog()
        del payload["variants"]
        with self.assertRaises(EngineError):
            load_h3_presets(self.write(payload))
        cases = (
            None,
            [],
            {},
            "turbo4",
            ["x"],
            [{"label": "x", "lora": "a.safetensors", "steps": 4}],
            [{"id": "turbo4", "label": "", "lora": "a.safetensors", "steps": 4}],
            [{"id": "turbo4", "label": "x", "lora": "", "steps": 4}],
            [{"id": "turbo4", "label": "x", "lora": 123, "steps": 4}],
            [{"id": "turbo4", "label": "x", "lora": "a.safetensors", "steps": 0}],
            [{"id": "turbo4", "label": "x", "lora": "a.safetensors", "steps": 201}],
            [{"id": "turbo4", "label": "x", "lora": "a.safetensors", "steps": True}],
            [{"id": "turbo4", "label": "x", "lora": "a.safetensors", "steps": 4.0}],
            [{"id": "turbo4", "label": "x", "lora": "a.safetensors", "steps": "4"}],
            [
                {"id": "turbo4", "label": "x", "lora": "a.safetensors", "steps": 4},
                {"id": "turbo4", "label": "y", "lora": "b.safetensors", "steps": 8},
            ],
            [{"id": "turbo8", "label": "x", "lora": "a.safetensors", "steps": 8}],
        )
        for value in cases:
            with self.subTest(value=value):
                payload = _valid_catalog()
                payload["variants"] = value
                with self.assertRaises(EngineError):
                    load_h3_presets(self.write(payload))

    def test_resoluciones_invalidas(self):
        cases = (
            None,
            {},
            {"vertical": [], "horizontal": [{"width": 1024, "height": 576}]},
            {
                "vertical": [{"width": 600, "height": 1024}],
                "horizontal": [{"width": 1024, "height": 576}],
            },
            {
                "vertical": [{"width": 2048, "height": 1024}],
                "horizontal": [{"width": 1024, "height": 2048}],
            },
            {
                "vertical": [{"width": 1024, "height": 576}],
                "horizontal": [{"width": 1024, "height": 576}],
            },
            {
                "vertical": [{"width": 576, "height": 1024}],
                "horizontal": [{"width": 576, "height": 1024}],
            },
        )
        for value in cases:
            with self.subTest(value=value):
                payload = _valid_catalog()
                payload["resoluciones"] = value
                with self.assertRaises(EngineError):
                    load_h3_presets(self.write(payload))

    def test_entrada_no_dict_y_campos_requeridos(self):
        with self.assertRaises(EngineError):
            load_h3_presets(self.write(_valid_catalog(["x"])))
        for field in (
            "id",
            "label",
            "note",
            "template",
            "dit",
            "vae_video",
            "vae_audio",
            "seconds_recomendados",
        ):
            with self.subTest(field=field):
                entry = _valid_profile()
                del entry[field]
                with self.assertRaises(EngineError):
                    load_h3_presets(self.write(_valid_catalog([entry])))

    def test_id_duplicado(self):
        with self.assertRaises(EngineError):
            load_h3_presets(self.write(_valid_catalog([_valid_profile(), _valid_profile()])))

    def test_template_invalido(self):
        for template in ("", "otra.txt", "sub/plantilla.json", "../plantilla.json", 5, None):
            with self.subTest(template=template):
                entry = _valid_profile()
                entry["template"] = template
                with self.assertRaises(EngineError):
                    load_h3_presets(self.write(_valid_catalog([entry])))

    def test_projection_sin_encoder(self):
        entry = _valid_profile()
        entry["projection"] = "mmh3-4b-ClipProj-v3.1.safetensors"
        entry["encoder"] = None
        with self.assertRaises(EngineError):
            load_h3_presets(self.write(_valid_catalog([entry])))

    def test_seconds_recomendados_invalidos(self):
        for value in (None, [], [6], [8, 8], [10, 8], ["8"], [True]):
            with self.subTest(value=value):
                entry = _valid_profile()
                entry["seconds_recomendados"] = value
                with self.assertRaises(EngineError):
                    load_h3_presets(self.write(_valid_catalog([entry])))

    def test_catalogo_cacheado(self):
        self.assertIs(h3_presets_module._catalog(), h3_presets_module._catalog())


class H3ProfileVariantCompatibilityTests(unittest.TestCase):
    def test_compatible_variants_mapping(self):
        self.assertEqual(PROFILE_COMPATIBLE_VARIANTS["vdn"], {"vdn8"})
        self.assertEqual(
            PROFILE_COMPATIBLE_VARIANTS["ref2va"], {"vdn8", "turbo4", "turbo8"}
        )
        self.assertEqual(
            PROFILE_COMPATIBLE_VARIANTS["referencia"], {"turbo4", "turbo8"}
        )
        self.assertEqual(
            PROFILE_COMPATIBLE_VARIANTS["calidad"], {"turbo4", "turbo8"}
        )
        self.assertEqual(
            PROFILE_COMPATIBLE_VARIANTS["ligero"], {"turbo4", "turbo8"}
        )

    def test_validate_h3_profile_variant_success(self):
        valid = [
            ("vdn", "vdn8"),
            ("ref2va", "vdn8"),
            ("ref2va", "turbo4"),
            ("ref2va", "turbo8"),
            ("referencia", "turbo4"),
            ("referencia", "turbo8"),
            ("calidad", "turbo4"),
            ("calidad", "turbo8"),
            ("ligero", "turbo4"),
            ("ligero", "turbo8"),
        ]
        for p, v in valid:
            with self.subTest(profile=p, variant=v):
                validate_h3_profile_variant(p, v)

    def test_validate_h3_profile_variant_rejects_incompatible(self):
        invalid = [
            ("vdn", "turbo4"),
            ("vdn", "turbo8"),
            ("referencia", "vdn8"),
            ("calidad", "vdn8"),
            ("ligero", "vdn8"),
            ("desconocido", "turbo4"),
            ("calidad", "desconocida"),
        ]
        for p, v in invalid:
            with self.subTest(profile=p, variant=v):
                with self.assertRaises(EngineError):
                    validate_h3_profile_variant(p, v)

    def test_resolve_h3_variant_default_for_vdn(self):
        res = resolve_h3_variant(None, profile="vdn")
        self.assertEqual(res["id"], "vdn8")
        res_empty = resolve_h3_variant("", profile="vdn")
        self.assertEqual(res_empty["id"], "vdn8")
        res_other = resolve_h3_variant(None, profile="calidad")
        self.assertEqual(res_other["id"], DEFAULT_VARIANT)

    def test_is_vdn_installed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            # Sin carpeta vdn
            self.assertFalse(is_vdn_installed(tmp_root))
            # Con carpeta vdn vacía
            vdn_models = tmp_root / "models" / "vdn"
            vdn_models.mkdir(parents=True)
            self.assertFalse(is_vdn_installed(tmp_root))
            sub = vdn_models / "model_checkpoint"
            sub.mkdir()
            self.assertFalse(is_vdn_installed(tmp_root))
            # Con subcarpeta linear_branch
            (sub / "linear_branch").mkdir()
            self.assertTrue(is_vdn_installed(tmp_root))

    def test_get_h3_presets_availability_flag(self):
        presets = get_h3_presets()
        for p in presets:
            self.assertIn("available", p)
            self.assertIsInstance(p["available"], bool)
            if p["id"] == "vdn" and not p["available"]:
                self.assertIn("missing_reason", p)


if __name__ == "__main__":
    unittest.main()
