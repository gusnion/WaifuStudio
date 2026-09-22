"""Tests CPU de grafos y runner de video (F4). Sin red, GPU ni engine real."""

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.config import EngineConfig
from app.engine import ComfyEngine, EngineError, load_graph
from app.motion import MOTION_NEGATIVE
from app.store import Store
from app.video import (
    H3_TEMPLATE_PATH,
    WAN_TEMPLATE_PATH,
    build_video_graph,
    prepare_h3_graph,
    prepare_wan_graph,
    run_video_generation,
)

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"waifu-fake-mp4"

_OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    negative TEXT DEFAULT '',
    params TEXT DEFAULT '{}',
    status TEXT NOT NULL,
    outputs TEXT DEFAULT '[]',
    error TEXT
)
"""


class PrepareWanTests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph(WAN_TEMPLATE_PATH)
        self.snapshot = copy.deepcopy(self.graph)

    def test_plantilla_certificada(self):
        self.assertEqual(len(self.graph), 15)
        self.assertEqual(self.graph["5"]["inputs"]["text"], "1girl, walking, cinematic motion")
        self.assertEqual(self.graph["6"]["inputs"]["text"], MOTION_NEGATIVE)
        self.assertEqual(self.graph["7"]["inputs"]["image"], "ref.png")
        self.assertEqual(self.graph["9"]["class_type"], "WanImageToVideo")
        self.assertEqual(self.graph["9"]["inputs"]["width"], 432)
        self.assertEqual(self.graph["9"]["inputs"]["height"], 768)
        self.assertEqual(self.graph["9"]["inputs"]["length"], 81)
        self.assertEqual(self.graph["15"]["inputs"]["fps"], 16.0)
        self.assertEqual(self.graph["16"]["inputs"]["filename_prefix"], "waifu/video")
        self.assertEqual(self.graph["12"]["inputs"]["noise_seed"], 42)

    def test_parcheo_exacto(self):
        patched = prepare_wan_graph(
            self.graph,
            image_name="frame-0001.png",
            motion_positive="She walks slowly toward the camera.",
            motion_negative="no motion",
            width=432,
            height=768,
            seed=7,
        )
        self.assertEqual(
            patched["5"]["inputs"]["text"], "She walks slowly toward the camera."
        )
        self.assertEqual(patched["6"]["inputs"]["text"], "no motion")
        self.assertEqual(patched["7"]["inputs"]["image"], "frame-0001.png")
        self.assertEqual(patched["9"]["inputs"]["width"], 432)
        self.assertEqual(patched["9"]["inputs"]["height"], 768)
        self.assertEqual(patched["12"]["inputs"]["noise_seed"], 7)
        self.assertEqual(patched["13"]["inputs"]["noise_seed"], 7)

    def test_tamano_horizontal(self):
        patched = prepare_wan_graph(
            self.graph,
            image_name="frame.png",
            motion_positive="She walks.",
            motion_negative="no motion",
            width=768,
            height=432,
            seed=1,
        )
        self.assertEqual(patched["9"]["inputs"]["width"], 768)
        self.assertEqual(patched["9"]["inputs"]["height"], 432)

    def test_no_muta_el_original(self):
        prepare_wan_graph(
            self.graph,
            image_name="otro.png",
            motion_positive="She runs.",
            motion_negative="blur",
            seed=99,
        )
        self.assertEqual(self.graph, self.snapshot)

    def test_nodo_ausente_lanza_engine_error(self):
        for node_id in ("5", "6", "7", "9"):
            with self.subTest(node_id=node_id):
                broken = copy.deepcopy(self.graph)
                del broken[node_id]
                with self.assertRaises(EngineError):
                    prepare_wan_graph(
                        broken, image_name="f.png", motion_positive="m", motion_negative="n", seed=1
                    )

    def test_clase_incorrecta_lanza_engine_error(self):
        broken = copy.deepcopy(self.graph)
        broken["7"]["class_type"] = "CLIPTextEncode"
        with self.assertRaises(EngineError):
            prepare_wan_graph(
                broken, image_name="f.png", motion_positive="m", motion_negative="n", seed=1
            )

    def test_campo_ausente_lanza_engine_error(self):
        for node_id, field in (("5", "text"), ("7", "image"), ("9", "width")):
            with self.subTest(node_id=node_id, field=field):
                broken = copy.deepcopy(self.graph)
                del broken[node_id]["inputs"][field]
                with self.assertRaises(EngineError):
                    prepare_wan_graph(
                        broken, image_name="f.png", motion_positive="m", motion_negative="n", seed=1
                    )

    def test_sin_samplers_lanza_engine_error(self):
        broken = copy.deepcopy(self.graph)
        del broken["12"]
        del broken["13"]
        with self.assertRaises(EngineError):
            prepare_wan_graph(
                broken, image_name="f.png", motion_positive="m", motion_negative="n", seed=1
            )

    def test_entradas_invalidas_lanzan_engine_error(self):
        cases = (
            {"image_name": "  "},
            {"motion_positive": ""},
            {"motion_negative": None},
            {"width": 431},
            {"height": "alto"},
            {"seed": "abc"},
        )
        base = {
            "image_name": "f.png",
            "motion_positive": "m",
            "motion_negative": "n",
            "width": 432,
            "height": 768,
            "seed": 1,
        }
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    prepare_wan_graph(self.graph, **(base | override))


class PrepareH3Tests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph(H3_TEMPLATE_PATH)
        self.snapshot = copy.deepcopy(self.graph)

    def test_plantilla_certificada(self):
        self.assertEqual(len(self.graph), 17)
        self.assertEqual(self.graph["140"]["inputs"]["image"], "frames/FIRST_FRAME.png")
        self.assertEqual(self.graph["141"]["inputs"]["image"], "frames/LAST_FRAME.png")
        self.assertEqual(self.graph["131"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(self.graph["131"]["inputs"]["width"], 576)
        self.assertEqual(self.graph["131"]["inputs"]["height"], 1024)
        self.assertEqual(self.graph["131"]["inputs"]["length"], 192)
        self.assertEqual(self.graph["129"]["inputs"]["noise_seed"], 57003060)
        self.assertEqual(self.graph["92"]["inputs"]["filename_prefix"], "video/H3_FL2VA_VERTICAL")

    def test_parcheo_exacto(self):
        patched = prepare_h3_graph(
            self.graph,
            first_image_name="first.png",
            last_image_name="last.png",
            prompt="integrated_multimodal_description: test",
            seed=9,
        )
        self.assertEqual(patched["140"]["inputs"]["image"], "first.png")
        self.assertEqual(patched["141"]["inputs"]["image"], "last.png")
        self.assertEqual(
            patched["131"]["inputs"]["prompt"], "integrated_multimodal_description: test"
        )
        self.assertEqual(patched["129"]["inputs"]["noise_seed"], 9)

    def test_no_muta_el_original(self):
        prepare_h3_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            prompt="p",
            seed=3,
        )
        self.assertEqual(self.graph, self.snapshot)

    def test_nodo_campo_o_clase_mal_lanza_engine_error(self):
        for node_id in ("140", "141", "131", "129"):
            with self.subTest(node_id=node_id):
                broken = copy.deepcopy(self.graph)
                del broken[node_id]
                with self.assertRaises(EngineError):
                    prepare_h3_graph(
                        broken,
                        first_image_name="a.png",
                        last_image_name="b.png",
                        prompt="p",
                        seed=1,
                    )
        broken = copy.deepcopy(self.graph)
        del broken["131"]["inputs"]["prompt"]
        with self.assertRaises(EngineError):
            prepare_h3_graph(
                broken, first_image_name="a.png", last_image_name="b.png", prompt="p", seed=1
            )
        broken = copy.deepcopy(self.graph)
        broken["129"]["class_type"] = "KSampler"
        with self.assertRaises(EngineError):
            prepare_h3_graph(
                broken, first_image_name="a.png", last_image_name="b.png", prompt="p", seed=1
            )

    def test_entradas_invalidas_lanzan_engine_error(self):
        base = {
            "first_image_name": "a.png",
            "last_image_name": "b.png",
            "prompt": "p",
            "seed": 1,
        }
        for override in ({"first_image_name": ""}, {"last_image_name": None}, {"prompt": " "}):
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    prepare_h3_graph(self.graph, **(base | override))


class BuildVideoGraphTests(unittest.TestCase):
    def test_engine_invalido(self):
        with self.assertRaises(EngineError):
            build_video_graph({"engine": "nope", "template": str(WAN_TEMPLATE_PATH)})

    def test_template_ausente(self):
        with self.assertRaises(EngineError):
            build_video_graph({"engine": "wan", "template": ""})

    def test_aspect_invalido(self):
        with self.assertRaises(EngineError):
            build_video_graph(
                {
                    "engine": "wan",
                    "template": str(WAN_TEMPLATE_PATH),
                    "image_name": "f.png",
                    "motion_positive": "m",
                    "motion_negative": "n",
                    "aspect": "cuadrado",
                    "seed": 1,
                }
            )


class VideoTestCase(unittest.TestCase):
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


class FakeVideoTransport:
    """Transporte falso: submit y history success con un mp4 escrito en disco."""

    def __init__(self, config, *, output_name="clip.mp4", write_output=True):
        self.config = config
        self.output_name = output_name
        self.write_output = write_output
        self.submits = []

    def __call__(self, method, path, body=None, headers=None, timeout=None):
        if method == "POST" and path == "/prompt":
            self.submits.append(json.loads(body.decode("utf-8")))
            return 200, b'{"prompt_id": "p1"}'
        if method == "GET" and path == "/history/p1":
            if self.write_output:
                self.config.comfy_output_dir.mkdir(parents=True, exist_ok=True)
                (self.config.comfy_output_dir / self.output_name).write_bytes(MP4_BYTES)
            return 200, json.dumps(
                {
                    "p1": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "92": {
                                "videos": [
                                    {
                                        "filename": self.output_name,
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                }
            ).encode("utf-8")
        raise AssertionError(f"transporte inesperado: {method} {path}")


class RunVideoTests(VideoTestCase):
    def make_job(self, **overrides) -> dict:
        gen_id = self.store.add("wan", "motion", "", {"seed": 7}, kind="video")
        job = {
            "kind": "video",
            "gen_id": gen_id,
            "engine": "wan",
            "template": str(WAN_TEMPLATE_PATH),
            "image_name": "frame.png",
            "last_image_name": None,
            "motion_positive": "She walks slowly.",
            "motion_negative": "no motion",
            "prompt": "",
            "aspect": "vertical",
            "seed": 7,
        }
        job.update(overrides)
        return job

    def factory(self, transport):
        return lambda: ComfyEngine(
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

    def test_wan_end_to_end_copia_a_galeria(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job()
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["outputs"], ["clip.mp4"])
        self.assertIsNone(row["error"])
        copied = self.config.data_dir / "gallery" / str(job["gen_id"]) / "clip.mp4"
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), MP4_BYTES)
        self.assertEqual(job["outputs"], ["clip.mp4"])
        self.assertIsNone(job["error"])
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["5"]["inputs"]["text"], "She walks slowly.")
        self.assertEqual(graph["6"]["inputs"]["text"], "no motion")
        self.assertEqual(graph["7"]["inputs"]["image"], "frame.png")
        self.assertEqual(graph["12"]["inputs"]["noise_seed"], 7)
        self.assertEqual(graph["9"]["inputs"]["width"], 432)
        self.assertEqual(graph["9"]["inputs"]["height"], 768)

    def test_horizontal_patch(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job(aspect="horizontal")
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["9"]["inputs"]["width"], 768)
        self.assertEqual(graph["9"]["inputs"]["height"], 432)

    def test_h3_end_to_end(self):
        transport = FakeVideoTransport(self.config, output_name="h3.webm")
        gen_id = self.store.add("h3", "prompt h3", "", {}, kind="video")
        job = {
            "kind": "video",
            "gen_id": gen_id,
            "engine": "h3",
            "template": str(H3_TEMPLATE_PATH),
            "image_name": "first.png",
            "last_image_name": "last.png",
            "motion_positive": "",
            "motion_negative": "",
            "prompt": "integrated_multimodal_description: test",
            "aspect": "vertical",
            "seed": 11,
        }
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(gen_id)
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["outputs"], ["h3.webm"])
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["140"]["inputs"]["image"], "first.png")
        self.assertEqual(graph["141"]["inputs"]["image"], "last.png")
        self.assertEqual(
            graph["131"]["inputs"]["prompt"], "integrated_multimodal_description: test"
        )
        self.assertEqual(graph["129"]["inputs"]["noise_seed"], 11)

    def test_negativo_por_defecto_si_falta(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job(motion_negative=None)
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["6"]["inputs"]["text"], MOTION_NEGATIVE)

    def test_sin_video_marca_error_sin_propagar(self):
        transport = FakeVideoTransport(self.config, write_output=False)
        job = self.make_job()
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["kind"], "video")
        self.assertTrue(row["error"])
        self.assertEqual(job["outputs"], [])
        self.assertTrue(job["error"])

    def test_engine_desconocido_marca_error(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job(engine="nope")
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("engine invalido", row["error"])
        self.assertEqual(transport.submits, [])


class StoreKindMigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "waifu.db"

    def _old_db_with_row(self) -> None:
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute(_OLD_SCHEMA)
            conn.execute(
                "INSERT INTO generations (created_at, model_id, prompt, status) "
                "VALUES ('2026-01-01T00:00:00+00:00', 'm', 'p', 'done')"
            )

    def test_init_migra_db_existente_sin_kind(self):
        self._old_db_with_row()
        store = Store(self.db_path)
        store.init()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            columns = [
                row[1] for row in conn.execute("PRAGMA table_info(generations)")
            ]
        self.assertIn("kind", columns)
        self.assertEqual(store.get(1)["kind"], "image")
        video_id = store.add("wan", "motion", kind="video")
        self.assertEqual(store.get(video_id)["kind"], "video")
        self.assertEqual(
            [row["kind"] for row in store.list()], ["image", "video"]
        )

    def test_init_idempotente(self):
        store = Store(self.db_path)
        store.init()
        store.init()
        self.assertEqual(store.count(), 0)


if __name__ == "__main__":
    unittest.main()
