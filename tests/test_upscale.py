"""Tests CPU del upscaler de imagen y video e interpolacion FPS (M10-2d U1/U2/U3).

Sin red, GPU ni engine real. Verifican el catalogo ``registry/upscalers-v1.json``
(carga estricta, listado, resolucion y seccion ``frame_interpolation``),
`build_upscale_graph` (grafo minimo y validacion de nombres),
`build_video_upscale_graph` (nodos core, refs de fps/audio y prefijos),
`build_fps_graph` (RIFE VFI, fps×multiplier, audio y prefijos), `run_upscale`,
`run_video_upscale` y `run_fps` con engine/ws falsos (galeria, store, tracker y
validacion de fps/multiplier).
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app import upscale as upscale_module
from app.config import APP_ROOT, EngineConfig
from app.engine import ComfyEngine, EngineError
from app.store import Store
from app.upscale import (
    CATALOG_VERSION,
    CREATE_VIDEO_ID,
    DEFAULT_FILENAME_PREFIX,
    DEFAULT_FPS_FILENAME_PREFIX,
    DEFAULT_PREFIX,
    FPS_CREATE_VIDEO_ID,
    FPS_HISTORY_TIMEOUT_S,
    FPS_INTERP_ID,
    FPS_MATH_ID,
    FPS_MULTIPLIERS,
    FPS_SAVE_VIDEO_ID,
    IMAGE_EXT,
    LOAD_VIDEO_ID,
    MIN_UPSCALE_SCALE,
    RIFE_CLASS,
    RIFE_DEFAULTS,
    SAVE_VIDEO_FORMAT,
    SAVE_VIDEO_ID,
    SHARPEN_CLASS,
    SHARPEN_ID,
    SHARPEN_PRESETS,
    UPSCALE2_ID,
    UPSCALERS_PATH,
    UPSCALE_PASSES,
    UPSCALE_SHARPEN,
    VIDEO_COMPONENTS_ID,
    VIDEO_EXT,
    VIDEO_MODEL_LOADER_ID,
    VIDEO_UPSCALE_ID,
    build_fps_graph,
    build_upscale_graph,
    build_video_upscale_graph,
    fps_ckpt,
    fps_multiplier,
    frame_interpolation,
    get_upscaler,
    list_upscalers,
    load_frame_interpolation,
    load_upscalers,
    parse_fps,
    parse_passes,
    parse_sharpen,
    run_fps,
    run_upscale,
    run_video_upscale,
    upscalers,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"waifu-fake-png"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"waifu-fake-mp4"
EXPECTED_ID = "real-esrgan-x2"
RIFE_CKPTS = ["rife417.pth", "rife426.pth", "rife47.pth", "rife49.pth"]
RIFE_DEFAULT = "rife49.pth"


def _entry(**overrides) -> dict:
    entry = {
        "id": "test-x2",
        "label": "Test x2",
        "file": "Test_x2.pth",
        "scale": 2,
        "note": "nota",
    }
    entry.update(overrides)
    return entry


class UpscalerCatalogTests(unittest.TestCase):
    def test_path_y_json_del_catalogo(self):
        self.assertEqual(UPSCALERS_PATH, APP_ROOT / "registry" / "upscalers-v1.json")
        self.assertTrue(UPSCALERS_PATH.is_file())
        data = json.loads(UPSCALERS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], CATALOG_VERSION)
        self.assertEqual([entry["id"] for entry in data["upscalers"]], [EXPECTED_ID])

    def test_entrada_real_esrgan_x2(self):
        entry = upscalers()[EXPECTED_ID]
        self.assertEqual(set(entry), {"id", "label", "file", "scale", "note"})
        self.assertEqual(entry["file"], "RealESRGAN_x2.pth")
        self.assertEqual(entry["scale"], 2)
        self.assertEqual(entry["note"], "×2")
        self.assertIn("real", entry["label"].lower())

    def test_list_en_orden_y_copia_profunda(self):
        listed = list_upscalers()
        self.assertEqual([item["id"] for item in listed], [EXPECTED_ID])
        listed[0]["scale"] = 99
        self.assertEqual(upscalers()[EXPECTED_ID]["scale"], 2)

    def test_get_estricto(self):
        self.assertEqual(get_upscaler(" real-esrgan-x2 ")["scale"], 2)
        for value in ("nope", None, 5, True):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    get_upscaler(value)

    def test_alias_perezoso_estilo_presets(self):
        self.assertEqual(upscale_module.UPSCALERS[EXPECTED_ID]["scale"], 2)
        with self.assertRaises(AttributeError):
            upscale_module.OTRO  # noqa: B018

    def test_limites_expuestos(self):
        self.assertEqual(MIN_UPSCALE_SCALE, 1)
        self.assertEqual(IMAGE_EXT, ("png",))
        self.assertEqual((DEFAULT_PREFIX, DEFAULT_FILENAME_PREFIX), ("waifu/upscale", "upscaled"))
        self.assertEqual(DEFAULT_FPS_FILENAME_PREFIX, "interp")
        self.assertEqual(FPS_MULTIPLIERS, (2, 4))
        self.assertEqual(FPS_HISTORY_TIMEOUT_S, 3600.0)


class FrameInterpolationCatalogTests(unittest.TestCase):
    def test_seccion_del_catalogo_real(self):
        data = json.loads(UPSCALERS_PATH.read_text(encoding="utf-8"))
        section = data["frame_interpolation"]
        self.assertEqual(section["ckpts"], RIFE_CKPTS)
        self.assertEqual(section["default"], RIFE_DEFAULT)
        self.assertEqual(section["multipliers"], [2, 4])
        self.assertTrue(section["label"])
        entry = frame_interpolation()
        self.assertEqual(
            set(entry), {"label", "ckpts", "default", "multipliers", "note"}
        )
        self.assertEqual(entry["default"], RIFE_DEFAULT)
        self.assertEqual(entry["multipliers"], [2, 4])

    def test_copia_profunda(self):
        entry = frame_interpolation()
        entry["ckpts"].append("otro.pth")
        entry["multipliers"][0] = 8
        fresh = frame_interpolation()
        self.assertEqual(fresh["ckpts"], RIFE_CKPTS)
        self.assertEqual(fresh["multipliers"], [2, 4])

    def test_fps_ckpt_estricto(self):
        self.assertEqual(fps_ckpt(None), RIFE_DEFAULT)
        self.assertEqual(fps_ckpt(" rife47.pth "), "rife47.pth")
        for value in ("nope.pth", "", "  ", 5, True, ["rife49.pth"]):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    fps_ckpt(value)

    def test_fps_multiplier_estricto(self):
        self.assertEqual(fps_multiplier(2), 2)
        self.assertEqual(fps_multiplier(4), 4)
        for value in (1, 3, 0, -2, True, "2", 2.0, None):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    fps_multiplier(value)

    def test_parse_fps(self):
        self.assertIsNone(parse_fps(None))
        self.assertEqual(parse_fps(24), 24.0)
        self.assertEqual(parse_fps(23.976), 23.976)
        for value in (0, -1, "24", True, float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    parse_fps(value)

    def test_parse_fps_etiqueta(self):
        with self.assertRaises(EngineError) as ctx:
            parse_fps("x", "fps_in")
        self.assertIn("fps_in", str(ctx.exception))


class LoadFrameInterpolationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "upscalers.json"

    def write(self, payload) -> Path:
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.path

    def section(self, **overrides) -> dict:
        section = {
            "label": "RIFE",
            "ckpts": list(RIFE_CKPTS),
            "default": RIFE_DEFAULT,
            "multipliers": [2, 4],
            "note": "nota",
        }
        section.update(overrides)
        return section

    def catalog(self, payload) -> dict:
        return {
            "version": CATALOG_VERSION,
            "upscalers": [_entry()],
            "frame_interpolation": payload,
        }

    def test_valido(self):
        loaded = load_frame_interpolation(self.write(self.catalog(self.section())))
        self.assertEqual(loaded["ckpts"], RIFE_CKPTS)
        self.assertEqual(loaded["default"], RIFE_DEFAULT)
        self.assertEqual(loaded["multipliers"], [2, 4])

    def test_ilegible_json_invalido_y_sin_seccion(self):
        with self.assertRaises(EngineError):
            load_frame_interpolation(Path(self._tmp.name) / "no-existe.json")
        with self.assertRaises(EngineError):
            load_frame_interpolation(self.write("{no json"))
        with self.assertRaises(EngineError):
            load_frame_interpolation(
                self.write({"version": CATALOG_VERSION, "upscalers": [_entry()]})
            )
        for payload in ("x", 5, [], None):
            with self.subTest(payload=payload):
                with self.assertRaises(EngineError):
                    load_frame_interpolation(self.write(self.catalog(payload)))

    def test_version_invalida(self):
        for version in (2, "1", True, None):
            payload = {
                "version": version,
                "upscalers": [_entry()],
                "frame_interpolation": self.section(),
            }
            with self.subTest(version=version):
                with self.assertRaises(EngineError):
                    load_frame_interpolation(self.write(payload))

    def test_label_note_ckpts_default_y_multipliers_invalidos(self):
        cases = (
            {"label": ""},
            {"label": "   "},
            {"label": 5},
            {"note": 5},
            {"ckpts": []},
            {"ckpts": "rife49.pth"},
            {"ckpts": [RIFE_DEFAULT, RIFE_DEFAULT]},
            {"ckpts": ["../rife49.pth"]},
            {"ckpts": ["rife49.pth", "model.bin"]},
            {"ckpts": ["rife49.pth", 5]},
            {"default": "otro.pth"},
            {"default": None},
            {"multipliers": []},
            {"multipliers": "2"},
            {"multipliers": [2, 2]},
            {"multipliers": [1]},
            {"multipliers": [2, True]},
            {"multipliers": ["2"]},
        )
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    load_frame_interpolation(
                        self.write(self.catalog(self.section(**override)))
                    )


class LoadUpscalersTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "upscalers.json"

    def write(self, payload) -> Path:
        if isinstance(payload, str):
            self.path.write_text(payload, encoding="utf-8")
        else:
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.path

    def catalog(self, entries) -> dict:
        return {"version": CATALOG_VERSION, "upscalers": entries}

    def test_valido(self):
        loaded = load_upscalers(self.write(self.catalog([_entry()])))
        self.assertEqual(list(loaded), ["test-x2"])
        self.assertEqual(loaded["test-x2"]["file"], "Test_x2.pth")

    def test_ilegible_o_json_invalido(self):
        with self.assertRaises(EngineError):
            load_upscalers(Path(self._tmp.name) / "no-existe.json")
        with self.assertRaises(EngineError):
            load_upscalers(self.write("{no json"))

    def test_version_y_forma_del_catalogo(self):
        cases = (
            [],
            {"upscalers": [_entry()]},
            {"version": 2, "upscalers": [_entry()]},
            {"version": "1", "upscalers": [_entry()]},
            {"version": True, "upscalers": [_entry()]},
            {"version": CATALOG_VERSION},
            {"version": CATALOG_VERSION, "upscalers": {}},
            {"version": CATALOG_VERSION, "upscalers": []},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(EngineError):
                    load_upscalers(self.write(payload))

    def test_entrada_no_dict_y_campos_requeridos(self):
        with self.assertRaises(EngineError):
            load_upscalers(self.write(self.catalog(["x"])))
        for field in ("id", "label", "file", "scale", "note"):
            entry = _entry()
            del entry[field]
            with self.subTest(field=field):
                with self.assertRaises(EngineError):
                    load_upscalers(self.write(self.catalog([entry])))

    def test_id_label_note_invalidos(self):
        cases = (
            {"id": ""},
            {"id": "   "},
            {"id": 5},
            {"label": ""},
            {"label": "   "},
            {"label": 5},
            {"note": 5},
            {"note": None},
        )
        for override in cases:
            entry = _entry(**override)
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    load_upscalers(self.write(self.catalog([entry])))

    def test_file_invalido(self):
        for value in ("", "   ", 5, "../x.pth", "dir/x.pth", "dir\\x.pth", "..", "."):
            entry = _entry(file=value)
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    load_upscalers(self.write(self.catalog([entry])))

    def test_scale_invalido(self):
        for value in (True, 0, -1, 2.5, "2", None):
            entry = _entry(scale=value)
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    load_upscalers(self.write(self.catalog([entry])))

    def test_id_duplicado(self):
        with self.assertRaises(EngineError):
            load_upscalers(self.write(self.catalog([_entry(), _entry()])))


class ParsePassesTests(unittest.TestCase):
    def test_limites(self):
        self.assertEqual(UPSCALE_PASSES, (1, 2))

    def test_validos(self):
        self.assertEqual(parse_passes(None), 1)
        self.assertEqual(parse_passes(1), 1)
        self.assertEqual(parse_passes(2), 2)

    def test_invalidos(self):
        for value in (0, 3, -1, True, False, "1", "2", 1.0, 2.0, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    parse_passes(value)


class ParseSharpenTests(unittest.TestCase):
    def test_presets_fijados(self):
        self.assertEqual(UPSCALE_SHARPEN, (0, 1, 2))
        self.assertEqual(
            SHARPEN_PRESETS,
            {
                1: {"sharpen_radius": 1, "sigma": 0.8, "alpha": 0.6},
                2: {"sharpen_radius": 2, "sigma": 1.0, "alpha": 1.2},
            },
        )
        self.assertEqual(SHARPEN_CLASS, "ImageSharpen")
        self.assertEqual(SHARPEN_ID, "6")

    def test_validos(self):
        self.assertEqual(parse_sharpen(None), 0)
        self.assertEqual(parse_sharpen(0), 0)
        self.assertEqual(parse_sharpen(1), 1)
        self.assertEqual(parse_sharpen(2), 2)

    def test_invalidos(self):
        for value in (3, -1, "x", True, False, "1", "2", 1.0, 2.0, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    parse_sharpen(value)


class BuildUpscaleGraphTests(unittest.TestCase):
    def test_grafo_minimo_por_defecto(self):
        graph = build_upscale_graph("src.png", "RealESRGAN_x2.pth")
        self.assertEqual(set(graph), {"1", "2", "3", "4"})
        self.assertEqual(
            graph["1"],
            {
                "class_type": "LoadImage",
                "inputs": {"image": "src.png", "upload": "image"},
            },
        )
        self.assertEqual(
            graph["2"],
            {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": "RealESRGAN_x2.pth"},
            },
        )
        self.assertEqual(graph["3"]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(graph["3"]["inputs"]["upscale_model"], ["2", 0])
        self.assertEqual(graph["3"]["inputs"]["image"], ["1", 0])
        self.assertEqual(graph["4"]["class_type"], "SaveImage")
        self.assertEqual(graph["4"]["inputs"]["images"], ["3", 0])
        self.assertEqual(
            graph["4"]["inputs"]["filename_prefix"],
            f"{DEFAULT_PREFIX}/{DEFAULT_FILENAME_PREFIX}",
        )

    def test_passes_uno_es_el_grafo_por_defecto(self):
        default = build_upscale_graph("a.png", "m.pth")
        explicit = build_upscale_graph("a.png", "m.pth", passes=1)
        self.assertEqual(explicit, default)
        self.assertEqual(set(explicit), {"1", "2", "3", "4"})

    def test_passes_dos_encadena_dos_ampliaciones(self):
        graph = build_upscale_graph("a.png", "m.pth", passes=2)
        self.assertEqual(set(graph), {"1", "2", "3", "4", UPSCALE2_ID})
        self.assertEqual(graph["3"]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(graph["3"]["inputs"]["image"], ["1", 0])
        self.assertEqual(graph[UPSCALE2_ID]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(graph[UPSCALE2_ID]["inputs"]["upscale_model"], ["2", 0])
        self.assertEqual(graph[UPSCALE2_ID]["inputs"]["image"], ["3", 0])
        self.assertEqual(graph["4"]["class_type"], "SaveImage")
        self.assertEqual(graph["4"]["inputs"]["images"], [UPSCALE2_ID, 0])
        self.assertEqual(
            graph["4"]["inputs"]["filename_prefix"],
            f"{DEFAULT_PREFIX}/{DEFAULT_FILENAME_PREFIX}",
        )

    def test_passes_invalidos(self):
        for value in (0, 3, -1, True, "2", 2.0, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_upscale_graph("a.png", "m.pth", passes=value)

    def test_sharpen_off_no_anade_nodo(self):
        graph = build_upscale_graph("a.png", "m.pth", sharpen=0)
        self.assertEqual(set(graph), {"1", "2", "3", "4"})
        self.assertEqual(graph["4"]["inputs"]["images"], ["3", 0])
        graph2 = build_upscale_graph("a.png", "m.pth", passes=2, sharpen=0)
        self.assertEqual(set(graph2), {"1", "2", "3", "4", UPSCALE2_ID})
        self.assertEqual(graph2["4"]["inputs"]["images"], [UPSCALE2_ID, 0])

    def test_sharpen_suave_encadena_tras_una_pasada(self):
        graph = build_upscale_graph("a.png", "m.pth", sharpen=1)
        self.assertEqual(set(graph), {"1", "2", "3", "4", SHARPEN_ID})
        self.assertEqual(
            graph[SHARPEN_ID],
            {
                "class_type": "ImageSharpen",
                "inputs": {
                    "image": ["3", 0],
                    "sharpen_radius": 1,
                    "sigma": 0.8,
                    "alpha": 0.6,
                },
            },
        )
        self.assertEqual(graph["4"]["class_type"], "SaveImage")
        self.assertEqual(graph["4"]["inputs"]["images"], [SHARPEN_ID, 0])

    def test_sharpen_fuerte_encadena_tras_dos_pasadas(self):
        graph = build_upscale_graph("a.png", "m.pth", passes=2, sharpen=2)
        self.assertEqual(graph[UPSCALE2_ID]["inputs"]["image"], ["3", 0])
        self.assertEqual(graph[SHARPEN_ID]["class_type"], "ImageSharpen")
        self.assertEqual(graph[SHARPEN_ID]["inputs"]["image"], [UPSCALE2_ID, 0])
        self.assertEqual(graph[SHARPEN_ID]["inputs"]["sharpen_radius"], 2)
        self.assertEqual(graph[SHARPEN_ID]["inputs"]["sigma"], 1.0)
        self.assertEqual(graph[SHARPEN_ID]["inputs"]["alpha"], 1.2)
        self.assertEqual(graph["4"]["inputs"]["images"], [SHARPEN_ID, 0])

    def test_sharpen_invalidos(self):
        for value in (3, -1, True, "1", 1.0, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_upscale_graph("a.png", "m.pth", sharpen=value)

    def test_prefijos_personalizados(self):
        graph = build_upscale_graph(
            "a.png", "m.pth", prefix="salida/x", filename_prefix="escalada"
        )
        self.assertEqual(graph["4"]["inputs"]["filename_prefix"], "salida/x/escalada")

    def test_prefix_vacio_usa_solo_filename_prefix(self):
        graph = build_upscale_graph(
            "a.png", "m.pth", prefix="", filename_prefix="escalada"
        )
        self.assertEqual(graph["4"]["inputs"]["filename_prefix"], "escalada")

    def test_nombres_simples_validos_y_recortados(self):
        graph = build_upscale_graph(" a.png ", " m.pth ")
        self.assertEqual(graph["1"]["inputs"]["image"], "a.png")
        self.assertEqual(graph["2"]["inputs"]["model_name"], "m.pth")

    def test_nombres_invalidos(self):
        bad = (None, "", "  ", 5, "../a.png", "dir/a.png", "dir\\a.png", "/abs.png", "..", ".")
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_upscale_graph(value, "m.pth")
                with self.assertRaises(EngineError):
                    build_upscale_graph("a.png", value)

    def test_prefijos_invalidos(self):
        bad = (None, 5, "a//b", "/abs", "a/../b", "a\\b", ".")
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_upscale_graph("a.png", "m.pth", prefix=value)
                with self.assertRaises(EngineError):
                    build_upscale_graph("a.png", "m.pth", filename_prefix=value)
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_upscale_graph("a.png", "m.pth", filename_prefix=value)

    def test_no_muta_nada_entre_llamadas(self):
        first = build_upscale_graph("a.png", "m.pth")
        second = build_upscale_graph("b.png", "n.pth")
        self.assertEqual(first["1"]["inputs"]["image"], "a.png")
        self.assertEqual(second["1"]["inputs"]["image"], "b.png")


class BuildVideoUpscaleGraphTests(unittest.TestCase):
    def test_grafo_minimo_por_defecto(self):
        graph = build_video_upscale_graph("clip.mp4", "RealESRGAN_x2.pth")
        self.assertEqual(set(graph), {"1", "2", "3", "4", "5", "6"})
        self.assertEqual(
            graph[LOAD_VIDEO_ID],
            {"class_type": "LoadVideo", "inputs": {"file": "clip.mp4"}},
        )
        self.assertEqual(
            graph[VIDEO_COMPONENTS_ID],
            {"class_type": "GetVideoComponents", "inputs": {"video": [LOAD_VIDEO_ID, 0]}},
        )
        self.assertEqual(
            graph[VIDEO_MODEL_LOADER_ID],
            {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": "RealESRGAN_x2.pth"},
            },
        )
        self.assertEqual(graph[VIDEO_UPSCALE_ID]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(
            graph[VIDEO_UPSCALE_ID]["inputs"]["upscale_model"],
            [VIDEO_MODEL_LOADER_ID, 0],
        )
        self.assertEqual(
            graph[VIDEO_UPSCALE_ID]["inputs"]["image"], [VIDEO_COMPONENTS_ID, 0]
        )
        self.assertEqual(graph[CREATE_VIDEO_ID]["class_type"], "CreateVideo")
        self.assertEqual(
            graph[CREATE_VIDEO_ID]["inputs"],
            {
                "images": [VIDEO_UPSCALE_ID, 0],
                "fps": [VIDEO_COMPONENTS_ID, 2],
                "audio": [VIDEO_COMPONENTS_ID, 1],
            },
        )
        self.assertEqual(graph[SAVE_VIDEO_ID]["class_type"], "SaveVideo")
        self.assertEqual(graph[SAVE_VIDEO_ID]["inputs"]["video"], [CREATE_VIDEO_ID, 0])
        self.assertEqual(
            graph[SAVE_VIDEO_ID]["inputs"]["filename_prefix"],
            f"{DEFAULT_PREFIX}/{DEFAULT_FILENAME_PREFIX}",
        )
        self.assertEqual(graph[SAVE_VIDEO_ID]["inputs"]["format"], SAVE_VIDEO_FORMAT)
        self.assertEqual(SAVE_VIDEO_FORMAT, "mp4")
        self.assertEqual(VIDEO_EXT, ("mp4", "webm"))

    def test_prefijos_personalizados(self):
        graph = build_video_upscale_graph(
            "a.mp4", "m.pth", prefix="salida/x", filename_prefix="escalada"
        )
        self.assertEqual(
            graph[SAVE_VIDEO_ID]["inputs"]["filename_prefix"], "salida/x/escalada"
        )

    def test_prefix_vacio_usa_solo_filename_prefix(self):
        graph = build_video_upscale_graph(
            "a.mp4", "m.pth", prefix="", filename_prefix="escalada"
        )
        self.assertEqual(graph[SAVE_VIDEO_ID]["inputs"]["filename_prefix"], "escalada")

    def test_nombres_simples_validos_y_recortados(self):
        graph = build_video_upscale_graph(" a.mp4 ", " m.pth ")
        self.assertEqual(graph[LOAD_VIDEO_ID]["inputs"]["file"], "a.mp4")
        self.assertEqual(graph[VIDEO_MODEL_LOADER_ID]["inputs"]["model_name"], "m.pth")

    def test_nombres_invalidos(self):
        bad = (None, "", "  ", 5, "../a.mp4", "dir/a.mp4", "dir\\a.mp4", "/abs.mp4", "..", ".")
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_video_upscale_graph(value, "m.pth")
                with self.assertRaises(EngineError):
                    build_video_upscale_graph("a.mp4", value)

    def test_prefijos_invalidos(self):
        bad = (None, 5, "a//b", "/abs", "a/../b", "a\\b", ".")
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_video_upscale_graph("a.mp4", "m.pth", prefix=value)
                with self.assertRaises(EngineError):
                    build_video_upscale_graph("a.mp4", "m.pth", filename_prefix=value)
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_video_upscale_graph(
                        "a.mp4", "m.pth", filename_prefix=value
                    )

    def test_no_muta_nada_entre_llamadas(self):
        first = build_video_upscale_graph("a.mp4", "m.pth")
        second = build_video_upscale_graph("b.mp4", "n.pth")
        self.assertEqual(first[LOAD_VIDEO_ID]["inputs"]["file"], "a.mp4")
        self.assertEqual(second[LOAD_VIDEO_ID]["inputs"]["file"], "b.mp4")


class BuildFpsGraphTests(unittest.TestCase):
    def test_grafo_minimo_por_defecto(self):
        graph = build_fps_graph("clip.mp4", RIFE_DEFAULT, 2)
        self.assertEqual(set(graph), {"1", "2", "3", "4", "5", "6"})
        self.assertEqual(
            graph[LOAD_VIDEO_ID],
            {"class_type": "LoadVideo", "inputs": {"file": "clip.mp4"}},
        )
        self.assertEqual(
            graph[VIDEO_COMPONENTS_ID],
            {
                "class_type": "GetVideoComponents",
                "inputs": {"video": [LOAD_VIDEO_ID, 0]},
            },
        )
        self.assertEqual(graph[FPS_MATH_ID]["class_type"], "ComfyMathExpression")
        self.assertEqual(
            graph[FPS_MATH_ID]["inputs"],
            {"expression": "a * 2", "values.a": [VIDEO_COMPONENTS_ID, 2]},
        )
        self.assertEqual(graph[FPS_INTERP_ID]["class_type"], RIFE_CLASS)
        self.assertEqual(
            graph[FPS_INTERP_ID]["inputs"],
            {
                "ckpt_name": RIFE_DEFAULT,
                "frames": [VIDEO_COMPONENTS_ID, 0],
                "multiplier": 2,
                **RIFE_DEFAULTS,
            },
        )
        self.assertEqual(
            graph[FPS_CREATE_VIDEO_ID]["inputs"],
            {
                "images": [FPS_INTERP_ID, 0],
                "fps": [FPS_MATH_ID, 0],
                "audio": [VIDEO_COMPONENTS_ID, 1],
            },
        )
        self.assertEqual(graph[FPS_SAVE_VIDEO_ID]["class_type"], "SaveVideo")
        self.assertEqual(graph[FPS_SAVE_VIDEO_ID]["inputs"]["video"], [FPS_CREATE_VIDEO_ID, 0])
        self.assertEqual(
            graph[FPS_SAVE_VIDEO_ID]["inputs"]["filename_prefix"],
            f"{DEFAULT_PREFIX}/{DEFAULT_FPS_FILENAME_PREFIX}",
        )
        self.assertEqual(graph[FPS_SAVE_VIDEO_ID]["inputs"]["format"], SAVE_VIDEO_FORMAT)

    def test_ids_defaults_y_multipliers(self):
        self.assertEqual(
            (FPS_MATH_ID, FPS_INTERP_ID, FPS_CREATE_VIDEO_ID, FPS_SAVE_VIDEO_ID),
            ("3", "4", "5", "6"),
        )
        self.assertEqual(FPS_MULTIPLIERS, (2, 4))
        self.assertEqual(RIFE_CLASS, "RIFE VFI")
        self.assertEqual(
            RIFE_DEFAULTS,
            {
                "clear_cache_after_n_frames": 10,
                "fast_mode": True,
                "ensemble": True,
                "scale_factor": 1.0,
                "dtype": "float32",
                "torch_compile": False,
                "batch_size": 1,
            },
        )
        for multiplier in FPS_MULTIPLIERS:
            with self.subTest(multiplier=multiplier):
                graph = build_fps_graph("a.mp4", "m.pth", multiplier)
                self.assertEqual(
                    graph[FPS_MATH_ID]["inputs"]["expression"], f"a * {multiplier}"
                )
                self.assertEqual(
                    graph[FPS_INTERP_ID]["inputs"]["multiplier"], multiplier
                )

    def test_prefijos_personalizados(self):
        graph = build_fps_graph(
            "a.mp4", "m.pth", 2, prefix="salida/x", filename_prefix="interpolado"
        )
        self.assertEqual(
            graph[FPS_SAVE_VIDEO_ID]["inputs"]["filename_prefix"],
            "salida/x/interpolado",
        )

    def test_prefix_vacio_usa_solo_filename_prefix(self):
        graph = build_fps_graph(
            "a.mp4", "m.pth", 2, prefix="", filename_prefix="interpolado"
        )
        self.assertEqual(
            graph[FPS_SAVE_VIDEO_ID]["inputs"]["filename_prefix"], "interpolado"
        )

    def test_nombres_simples_validos_y_recortados(self):
        graph = build_fps_graph(" a.mp4 ", " rife49.pth ", 2)
        self.assertEqual(graph[LOAD_VIDEO_ID]["inputs"]["file"], "a.mp4")
        self.assertEqual(graph[FPS_INTERP_ID]["inputs"]["ckpt_name"], "rife49.pth")

    def test_nombres_invalidos(self):
        bad = (None, "", "  ", 5, "../a.mp4", "dir/a.mp4", "dir\\a.mp4", "/abs.mp4", "..", ".")
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_fps_graph(value, "m.pth", 2)
                with self.assertRaises(EngineError):
                    build_fps_graph("a.mp4", value, 2)

    def test_multiplier_invalido(self):
        for value in (1, 3, 0, -2, 8, True, "2", 2.0, None):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_fps_graph("a.mp4", "m.pth", value)

    def test_prefijos_invalidos(self):
        bad = (None, 5, "a//b", "/abs", "a/../b", "a\\b", ".")
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_fps_graph("a.mp4", "m.pth", 2, prefix=value)
                with self.assertRaises(EngineError):
                    build_fps_graph("a.mp4", "m.pth", 2, filename_prefix=value)
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    build_fps_graph("a.mp4", "m.pth", 2, filename_prefix=value)

    def test_no_muta_nada_entre_llamadas(self):
        first = build_fps_graph("a.mp4", "m.pth", 2)
        second = build_fps_graph("b.mp4", "n.pth", 4)
        self.assertEqual(first[LOAD_VIDEO_ID]["inputs"]["file"], "a.mp4")
        self.assertEqual(second[LOAD_VIDEO_ID]["inputs"]["file"], "b.mp4")
        self.assertEqual(first[FPS_MATH_ID]["inputs"]["expression"], "a * 2")
        self.assertEqual(second[FPS_MATH_ID]["inputs"]["expression"], "a * 4")


class FakeUpscaleTransport:
    """Transporte falso: submit y history success con un PNG escrito en disco."""

    def __init__(
        self,
        config,
        *,
        output_name="upscaled_00001_.png",
        subfolder="waifu/upscale",
        write_output=True,
    ):
        self.config = config
        self.output_name = output_name
        self.subfolder = subfolder
        self.write_output = write_output
        self.submits = []

    def __call__(self, method, path, body=None, headers=None, timeout=None):
        if method == "POST" and path == "/prompt":
            self.submits.append(json.loads(body.decode("utf-8")))
            return 200, b'{"prompt_id": "p1"}'
        if method == "GET" and path == "/history/p1":
            if self.write_output:
                directory = self.config.comfy_output_dir / self.subfolder
                directory.mkdir(parents=True, exist_ok=True)
                (directory / self.output_name).write_bytes(PNG_BYTES)
            return 200, json.dumps(
                {
                    "p1": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "4": {
                                "images": [
                                    {
                                        "filename": self.output_name,
                                        "subfolder": self.subfolder,
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                }
            ).encode("utf-8")
        raise AssertionError(f"transporte inesperado: {method} {path}")


class FakeVideoUpscaleTransport:
    """Transporte falso: submit y history success con un MP4 escrito en disco."""

    def __init__(
        self,
        config,
        *,
        output_name="upscaled_00001_.mp4",
        subfolder="waifu/upscale",
        write_output=True,
    ):
        self.config = config
        self.output_name = output_name
        self.subfolder = subfolder
        self.write_output = write_output
        self.submits = []

    def __call__(self, method, path, body=None, headers=None, timeout=None):
        if method == "POST" and path == "/prompt":
            self.submits.append(json.loads(body.decode("utf-8")))
            return 200, b'{"prompt_id": "p1"}'
        if method == "GET" and path == "/history/p1":
            if self.write_output:
                directory = self.config.comfy_output_dir / self.subfolder
                directory.mkdir(parents=True, exist_ok=True)
                (directory / self.output_name).write_bytes(MP4_BYTES)
            return 200, json.dumps(
                {
                    "p1": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            SAVE_VIDEO_ID: {
                                "videos": [
                                    {
                                        "filename": self.output_name,
                                        "subfolder": self.subfolder,
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                }
            ).encode("utf-8")
        raise AssertionError(f"transporte inesperado: {method} {path}")


class BlockingWs:
    """WS falso que se queda abierto hasta que el tracker se cancela."""

    async def __aenter__(self):
        await asyncio.Event().wait()
        raise AssertionError("inalcanzable")

    async def __aexit__(self, exc_type, exc, tb):
        return False


def blocking_ws_factory(url: str) -> BlockingWs:
    return BlockingWs()


class UpscaleTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = EngineConfig(
            comfy_root=self.root / "comfy",
            comfy_url="http://127.0.0.1:1",
            data_dir=self.root / "data",
        )
        self.store = Store(self.config.data_dir / "waifu.db")
        self.store.init()


class RunUpscaleTests(UpscaleTestCase):
    def make_job(self, **overrides) -> dict:
        gen_id = self.store.add(
            "upscale", "upscale #1/ok.png", "", {"task": "upscale"}, kind="image"
        )
        job = {
            "kind": "upscale",
            "gen_id": gen_id,
            "source_gen": 1,
            "source_file": "ok.png",
            "image_name": "src.png",
            "model": "real-esrgan-x2",
            "model_file": "RealESRGAN_x2.pth",
            "scale": 2,
        }
        job.update(overrides)
        return job

    def factory(self, transport):
        return lambda: ComfyEngine(
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

    def test_end_to_end_copia_a_galeria(self):
        transport = FakeUpscaleTransport(self.config)
        job = self.make_job()
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "image")
        self.assertEqual(row["outputs"], ["upscaled_00001_.png"])
        self.assertIsNone(row["error"])
        copied = (
            self.config.data_dir
            / "gallery"
            / str(job["gen_id"])
            / "upscaled_00001_.png"
        )
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), PNG_BYTES)
        self.assertEqual(job["outputs"], ["upscaled_00001_.png"])
        self.assertIsNone(job["error"])
        self.assertEqual(
            job["params"],
            {
                "task": "upscale",
                "source_gen": 1,
                "source_file": "ok.png",
                "model": "real-esrgan-x2",
                "scale": 2,
                "passes": 1,
                "sharpen": 0,
            },
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["1"]["inputs"]["image"], "src.png")
        self.assertEqual(graph["2"]["inputs"]["model_name"], "RealESRGAN_x2.pth")
        self.assertEqual(graph["3"]["inputs"]["image"], ["1", 0])
        self.assertEqual(
            graph["4"]["inputs"]["filename_prefix"],
            f"{DEFAULT_PREFIX}/{DEFAULT_FILENAME_PREFIX}",
        )

    def test_sin_png_marca_error_sin_propagar(self):
        transport = FakeUpscaleTransport(self.config, write_output=False)
        job = self.make_job()
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["kind"], "image")
        self.assertTrue(row["error"])
        self.assertEqual(job["outputs"], [])
        self.assertTrue(job["error"])

    def test_grafo_invalido_marca_error_sin_submit(self):
        transport = FakeUpscaleTransport(self.config)
        job = self.make_job(model_file="../evil.pth")
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("model_file", row["error"])
        self.assertEqual(transport.submits, [])

    def test_registra_engine_prompt_id_y_tracker(self):
        transport = FakeUpscaleTransport(self.config)
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
            "kind": "upscale",
        }
        job = self.make_job()
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
            ws_factory=blocking_ws_factory,
        )
        self.assertIsNotNone(record["engine"])
        self.assertEqual(record["prompt_id"], "p1")
        self.assertEqual(record["status"], "done")
        tracker = record["tracker"]
        self.assertIsNotNone(tracker)
        self.assertFalse(tracker._thread is not None and tracker._thread.is_alive())

    def test_record_cancelado_antes_de_arrancar_no_ejecuta(self):
        transport = FakeUpscaleTransport(self.config)
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "cancelled",
            "engine": None,
            "kind": "upscale",
        }
        job = self.make_job()
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
        )
        self.assertEqual(transport.submits, [])
        self.assertEqual(job["outputs"], [])
        self.assertIsNone(job["error"])
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(self.store.get(job["gen_id"])["status"], "queued")
        self.assertEqual(job["params"]["task"], "upscale")

    def test_job_con_prefix_del_job(self):
        transport = FakeUpscaleTransport(self.config)
        job = self.make_job(prefix="otro/sitio", filename_prefix="grande")
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["4"]["inputs"]["filename_prefix"], "otro/sitio/grande")

    def test_passes_dos_envia_grafo_encadenado(self):
        transport = FakeUpscaleTransport(self.config)
        job = self.make_job(passes=2)
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(job["params"]["passes"], 2)
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph[UPSCALE2_ID]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(graph[UPSCALE2_ID]["inputs"]["upscale_model"], ["2", 0])
        self.assertEqual(graph[UPSCALE2_ID]["inputs"]["image"], ["3", 0])
        self.assertEqual(graph["4"]["inputs"]["images"], [UPSCALE2_ID, 0])

    def test_passes_invalido_marca_error_sin_submit(self):
        transport = FakeUpscaleTransport(self.config)
        job = self.make_job(passes=3)
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("passes", row["error"])
        self.assertEqual(transport.submits, [])
        self.assertEqual(job["outputs"], [])

    def test_sharpen_dos_envia_grafo_con_nodo_sharpen(self):
        transport = FakeUpscaleTransport(self.config)
        job = self.make_job(sharpen=2)
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(job["params"]["sharpen"], 2)
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph[SHARPEN_ID]["class_type"], "ImageSharpen")
        self.assertEqual(graph[SHARPEN_ID]["inputs"]["image"], ["3", 0])
        self.assertEqual(graph[SHARPEN_ID]["inputs"]["alpha"], 1.2)
        self.assertEqual(graph["4"]["inputs"]["images"], [SHARPEN_ID, 0])

    def test_sharpen_ausente_es_cero(self):
        transport = FakeUpscaleTransport(self.config)
        job = self.make_job()
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        self.assertEqual(job["sharpen"], 0)
        self.assertEqual(job["params"]["sharpen"], 0)
        graph = transport.submits[0]["prompt"]
        self.assertNotIn(SHARPEN_ID, graph)

    def test_sharpen_invalido_marca_error_sin_submit(self):
        transport = FakeUpscaleTransport(self.config)
        job = self.make_job(sharpen=3)
        run_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("sharpen", row["error"])
        self.assertEqual(transport.submits, [])


class RunVideoUpscaleTests(UpscaleTestCase):
    def make_job(self, **overrides) -> dict:
        gen_id = self.store.add(
            "upscale",
            "upscale #1/ok.mp4",
            "",
            {"task": "upscale_video"},
            kind="video",
        )
        job = {
            "kind": "upscale",
            "task": "upscale_video",
            "gen_id": gen_id,
            "source_gen": 1,
            "source_file": "ok.mp4",
            "video_name": "src.mp4",
            "model": "real-esrgan-x2",
            "model_file": "RealESRGAN_x2.pth",
            "scale": 2,
            "fps": None,
        }
        job.update(overrides)
        return job

    def factory(self, transport):
        return lambda: ComfyEngine(
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

    def test_end_to_end_copia_a_galeria(self):
        transport = FakeVideoUpscaleTransport(self.config)
        job = self.make_job(fps=24)
        run_video_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["outputs"], ["upscaled_00001_.mp4"])
        self.assertIsNone(row["error"])
        copied = (
            self.config.data_dir
            / "gallery"
            / str(job["gen_id"])
            / "upscaled_00001_.mp4"
        )
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), MP4_BYTES)
        self.assertEqual(job["outputs"], ["upscaled_00001_.mp4"])
        self.assertIsNone(job["error"])
        self.assertEqual(
            job["params"],
            {
                "task": "upscale_video",
                "source_gen": 1,
                "source_file": "ok.mp4",
                "model": "real-esrgan-x2",
                "scale": 2,
                "fps": 24.0,
            },
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph[LOAD_VIDEO_ID]["inputs"]["file"], "src.mp4")
        self.assertEqual(graph[VIDEO_COMPONENTS_ID]["inputs"]["video"], [LOAD_VIDEO_ID, 0])
        self.assertEqual(graph[VIDEO_UPSCALE_ID]["inputs"]["image"], [VIDEO_COMPONENTS_ID, 0])
        self.assertEqual(graph[CREATE_VIDEO_ID]["inputs"]["images"], [VIDEO_UPSCALE_ID, 0])
        self.assertEqual(graph[CREATE_VIDEO_ID]["inputs"]["fps"], [VIDEO_COMPONENTS_ID, 2])
        self.assertEqual(graph[CREATE_VIDEO_ID]["inputs"]["audio"], [VIDEO_COMPONENTS_ID, 1])
        self.assertEqual(graph[SAVE_VIDEO_ID]["inputs"]["video"], [CREATE_VIDEO_ID, 0])
        self.assertEqual(
            graph[SAVE_VIDEO_ID]["inputs"]["filename_prefix"],
            f"{DEFAULT_PREFIX}/{DEFAULT_FILENAME_PREFIX}",
        )

    def test_sin_video_marca_error_sin_propagar(self):
        transport = FakeVideoUpscaleTransport(self.config, write_output=False)
        job = self.make_job()
        run_video_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["kind"], "video")
        self.assertTrue(row["error"])
        self.assertEqual(job["outputs"], [])
        self.assertTrue(job["error"])

    def test_grafo_invalido_marca_error_sin_submit(self):
        transport = FakeVideoUpscaleTransport(self.config)
        job = self.make_job(model_file="../evil.pth")
        run_video_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("model_file", row["error"])
        self.assertEqual(transport.submits, [])

    def test_fps_invalido_marca_error_sin_submit(self):
        for fps in (-1, 0, "24", True):
            transport = FakeVideoUpscaleTransport(self.config)
            job = self.make_job(fps=fps)
            with self.subTest(fps=fps):
                run_video_upscale(
                    job,
                    config=self.config,
                    store=self.store,
                    engine_factory=self.factory(transport),
                )
                row = self.store.get(job["gen_id"])
                self.assertEqual(row["status"], "error")
                self.assertIn("fps", row["error"])
                self.assertEqual(transport.submits, [])

    def test_registra_engine_prompt_id_y_tracker(self):
        transport = FakeVideoUpscaleTransport(self.config)
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
            "kind": "upscale",
        }
        job = self.make_job()
        run_video_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
            ws_factory=blocking_ws_factory,
        )
        self.assertIsNotNone(record["engine"])
        self.assertEqual(record["prompt_id"], "p1")
        self.assertEqual(record["status"], "done")
        tracker = record["tracker"]
        self.assertIsNotNone(tracker)
        self.assertFalse(tracker._thread is not None and tracker._thread.is_alive())

    def test_record_cancelado_antes_de_arrancar_no_ejecuta(self):
        transport = FakeVideoUpscaleTransport(self.config)
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "cancelled",
            "engine": None,
            "kind": "upscale",
        }
        job = self.make_job()
        run_video_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
        )
        self.assertEqual(transport.submits, [])
        self.assertEqual(job["outputs"], [])
        self.assertIsNone(job["error"])
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(self.store.get(job["gen_id"])["status"], "queued")
        self.assertEqual(job["params"]["task"], "upscale_video")

    def test_job_con_prefix_del_job(self):
        transport = FakeVideoUpscaleTransport(self.config)
        job = self.make_job(prefix="otro/sitio", filename_prefix="grande")
        run_video_upscale(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(
            graph[SAVE_VIDEO_ID]["inputs"]["filename_prefix"], "otro/sitio/grande"
        )


class RunFpsTests(UpscaleTestCase):
    def make_job(self, **overrides) -> dict:
        gen_id = self.store.add(
            "upscale", "fps #1/ok.mp4", "", {"task": "rife"}, kind="video"
        )
        job = {
            "kind": "upscale",
            "task": "rife",
            "gen_id": gen_id,
            "source_gen": 1,
            "source_file": "ok.mp4",
            "video_name": "src.mp4",
            "ckpt": "rife49.pth",
            "ckpt_name": "rife49.pth",
            "multiplier": 2,
            "fps_in": None,
            "fps_out": None,
        }
        job.update(overrides)
        return job

    def factory(self, transport):
        return lambda: ComfyEngine(
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

    def test_end_to_end_copia_a_galeria(self):
        transport = FakeVideoUpscaleTransport(
            self.config, output_name="interp_00001_.mp4"
        )
        job = self.make_job(fps_in=24)
        run_fps(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["outputs"], ["interp_00001_.mp4"])
        self.assertIsNone(row["error"])
        copied = (
            self.config.data_dir
            / "gallery"
            / str(job["gen_id"])
            / "interp_00001_.mp4"
        )
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), MP4_BYTES)
        self.assertEqual(job["outputs"], ["interp_00001_.mp4"])
        self.assertIsNone(job["error"])
        self.assertEqual(
            job["params"],
            {
                "task": "rife",
                "source_gen": 1,
                "source_file": "ok.mp4",
                "ckpt": "rife49.pth",
                "multiplier": 2,
                "fps_in": 24.0,
                "fps_out": 48.0,
            },
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph[LOAD_VIDEO_ID]["inputs"]["file"], "src.mp4")
        self.assertEqual(
            graph[VIDEO_COMPONENTS_ID]["inputs"]["video"], [LOAD_VIDEO_ID, 0]
        )
        self.assertEqual(
            graph[FPS_MATH_ID]["inputs"],
            {"expression": "a * 2", "values.a": [VIDEO_COMPONENTS_ID, 2]},
        )
        self.assertEqual(graph[FPS_INTERP_ID]["class_type"], RIFE_CLASS)
        self.assertEqual(
            graph[FPS_INTERP_ID]["inputs"]["ckpt_name"], "rife49.pth"
        )
        self.assertEqual(
            graph[FPS_INTERP_ID]["inputs"]["frames"], [VIDEO_COMPONENTS_ID, 0]
        )
        self.assertEqual(graph[FPS_CREATE_VIDEO_ID]["inputs"]["images"], [FPS_INTERP_ID, 0])
        self.assertEqual(graph[FPS_CREATE_VIDEO_ID]["inputs"]["fps"], [FPS_MATH_ID, 0])
        self.assertEqual(
            graph[FPS_CREATE_VIDEO_ID]["inputs"]["audio"], [VIDEO_COMPONENTS_ID, 1]
        )
        self.assertEqual(
            graph[FPS_SAVE_VIDEO_ID]["inputs"]["video"], [FPS_CREATE_VIDEO_ID, 0]
        )
        self.assertEqual(
            graph[FPS_SAVE_VIDEO_ID]["inputs"]["filename_prefix"],
            f"{DEFAULT_PREFIX}/{DEFAULT_FPS_FILENAME_PREFIX}",
        )

    def test_multiplier_cuatro_y_fps_desconocido(self):
        transport = FakeVideoUpscaleTransport(self.config)
        job = self.make_job(multiplier=4)
        run_fps(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        self.assertEqual(job["fps_in"], None)
        self.assertEqual(job["fps_out"], None)
        self.assertEqual(job["params"]["multiplier"], 4)
        self.assertEqual(job["params"]["fps_out"], None)
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph[FPS_MATH_ID]["inputs"]["expression"], "a * 4")
        self.assertEqual(graph[FPS_INTERP_ID]["inputs"]["multiplier"], 4)

    def test_sin_video_marca_error_sin_propagar(self):
        transport = FakeVideoUpscaleTransport(self.config, write_output=False)
        job = self.make_job()
        run_fps(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["kind"], "video")
        self.assertTrue(row["error"])
        self.assertEqual(job["outputs"], [])
        self.assertTrue(job["error"])

    def test_grafo_invalido_marca_error_sin_submit(self):
        transport = FakeVideoUpscaleTransport(self.config)
        job = self.make_job(ckpt_name="../evil.pth")
        run_fps(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("ckpt_name", row["error"])
        self.assertEqual(transport.submits, [])

    def test_multiplier_invalido_marca_error_sin_submit(self):
        for multiplier in (1, 3, 8, "2", True, None):
            transport = FakeVideoUpscaleTransport(self.config)
            job = self.make_job(multiplier=multiplier)
            with self.subTest(multiplier=multiplier):
                run_fps(
                    job,
                    config=self.config,
                    store=self.store,
                    engine_factory=self.factory(transport),
                )
                row = self.store.get(job["gen_id"])
                self.assertEqual(row["status"], "error")
                self.assertIn("multiplier", row["error"])
                self.assertEqual(transport.submits, [])

    def test_fps_in_invalido_marca_error_sin_submit(self):
        for fps_in in (-1, 0, "24", True, float("inf")):
            transport = FakeVideoUpscaleTransport(self.config)
            job = self.make_job(fps_in=fps_in)
            with self.subTest(fps_in=fps_in):
                run_fps(
                    job,
                    config=self.config,
                    store=self.store,
                    engine_factory=self.factory(transport),
                )
                row = self.store.get(job["gen_id"])
                self.assertEqual(row["status"], "error")
                self.assertIn("fps_in", row["error"])
                self.assertEqual(transport.submits, [])

    def test_registra_engine_prompt_id_y_tracker(self):
        transport = FakeVideoUpscaleTransport(self.config)
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
            "kind": "upscale",
        }
        job = self.make_job()
        run_fps(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
            ws_factory=blocking_ws_factory,
        )
        self.assertIsNotNone(record["engine"])
        self.assertEqual(record["prompt_id"], "p1")
        self.assertEqual(record["status"], "done")
        tracker = record["tracker"]
        self.assertIsNotNone(tracker)
        self.assertFalse(tracker._thread is not None and tracker._thread.is_alive())

    def test_record_cancelado_antes_de_arrancar_no_ejecuta(self):
        transport = FakeVideoUpscaleTransport(self.config)
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "cancelled",
            "engine": None,
            "kind": "upscale",
        }
        job = self.make_job()
        run_fps(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
        )
        self.assertEqual(transport.submits, [])
        self.assertEqual(job["outputs"], [])
        self.assertIsNone(job["error"])
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(self.store.get(job["gen_id"])["status"], "queued")
        self.assertEqual(job["params"]["task"], "rife")

    def test_job_con_prefix_del_job(self):
        transport = FakeVideoUpscaleTransport(self.config)
        job = self.make_job(prefix="otro/sitio", filename_prefix="grande")
        run_fps(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(
            graph[FPS_SAVE_VIDEO_ID]["inputs"]["filename_prefix"], "otro/sitio/grande"
        )


if __name__ == "__main__":
    unittest.main()
