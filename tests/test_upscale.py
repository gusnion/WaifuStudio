"""Tests CPU del upscaler de imagen y video (M10-2d U1/U2). Sin red, GPU ni engine real.

Verifican el catalogo ``registry/upscalers-v1.json`` (carga estricta, listado y
resolucion), `build_upscale_graph` (grafo minimo y validacion de nombres),
`build_video_upscale_graph` (nodos core, refs de fps/audio y prefijos),
`run_upscale` y `run_video_upscale` con engine/ws falsos (galeria, store,
tracker y validacion de fps).
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
    DEFAULT_PREFIX,
    IMAGE_EXT,
    LOAD_VIDEO_ID,
    MIN_UPSCALE_SCALE,
    SAVE_VIDEO_FORMAT,
    SAVE_VIDEO_ID,
    UPSCALERS_PATH,
    VIDEO_COMPONENTS_ID,
    VIDEO_EXT,
    VIDEO_MODEL_LOADER_ID,
    VIDEO_UPSCALE_ID,
    build_upscale_graph,
    build_video_upscale_graph,
    get_upscaler,
    list_upscalers,
    load_upscalers,
    run_upscale,
    run_video_upscale,
    upscalers,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"waifu-fake-png"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"waifu-fake-mp4"
EXPECTED_ID = "real-esrgan-x2"


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



if __name__ == "__main__":
    unittest.main()
