"""Tests CPU del editor Qwen-Image 2.1 UC (M10-3).

Sin red, GPU ni engine real: plantilla API, `app.editor.prepare_editor_graph` /
`build_editor_graph` (parcheo y validaciones) y `run_editor_generation` con
transporte/engine falsos, mas un flujo HTTP completo con `JobQueue` inyectada
(misma tecnica que `tests/test_server_video.py`).
"""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import server as server_module
from app.config import EngineConfig
from app.editor import (
    EDITOR_CFG_MAX,
    EDITOR_CFG_MIN,
    EDITOR_DEFAULT_CFG,
    EDITOR_DEFAULT_SIZE,
    EDITOR_DEFAULT_STEPS,
    EDITOR_PRESERVE_DENOISE,
    EDITOR_REF_LIMIT,
    EDITOR_SIZE_MAX,
    EDITOR_SIZE_MIN,
    EDITOR_STEPS_MAX,
    EDITOR_STEPS_MIN,
    EDITOR_TEMPLATE_PATH,
    PRESERVE_ENCODE_ID,
    build_editor_graph,
    prepare_editor_graph,
    run_editor_generation,
)
from app.engine import ComfyEngine, EngineError, load_graph
from app.jobs import JobQueue
from app.registry import ModelRegistry
from app.server import create_app
from app.store import Store

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"waifu-editor-png"


def accept_editor_license(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "editor-license.json").write_text(
        '{"accepted": true, "version": "qwen-image-2.1-research", '
        '"accepted_at": "2026-10-26T00:00:00+00:00"}\n',
        encoding="utf-8",
    )

EDITOR_MODEL = "qwen-image-2.1"
VAE_ID = "3"
ENCODE_ID = "4"
LATENT_ID = "5"
SAMPLER_ID = "7"
DECODE_ID = "8"
SAVE_ID = "9"
CACHE_ID = "6"


def make_config(root: Path) -> EngineConfig:
    return EngineConfig(
        comfy_root=root / "comfy",
        comfy_url="http://127.0.0.1:1",
        data_dir=root / "data",
    )


class FakeEditorTransport:
    """Transporte HTTP falso del engine: submit y history success con PNG."""

    def __init__(self, config, *, output_name="editor_00001_.png", write_output=True):
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
                (self.config.comfy_output_dir / self.output_name).write_bytes(
                    PNG_BYTES
                )
            return 200, json.dumps(
                {
                    "p1": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            SAVE_ID: {
                                "images": [
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


class EditorTemplateTests(unittest.TestCase):
    def template(self) -> dict:
        return load_graph(EDITOR_TEMPLATE_PATH)

    def test_carga_los_loaders_del_par_uc(self):
        graph = self.template()
        self.assertEqual(graph["1"]["class_type"], "UnetLoaderGGUF")
        self.assertEqual(
            graph["1"]["inputs"]["unet_name"], "qwen-image-2.1-UC-Q4_K_M.gguf"
        )
        self.assertEqual(graph["2"]["class_type"], "CLIPLoader")
        self.assertEqual(
            graph["2"]["inputs"]["clip_name"], "qwen3vl_8b_int8_convrot.safetensors"
        )
        self.assertEqual(graph["2"]["inputs"]["type"], "qwen_image")
        self.assertEqual(graph["3"]["class_type"], "VAELoader")
        self.assertEqual(
            graph["3"]["inputs"]["vae_name"], "qwen_image_2.1_vae_bf16.safetensors"
        )

    def test_cadena_encoder_sampler_decode_save(self):
        graph = self.template()
        encode = graph[ENCODE_ID]
        self.assertEqual(encode["class_type"], "TextEncodeQwenImage21")
        self.assertEqual(encode["inputs"]["clip"], ["2", 0])
        self.assertEqual(encode["inputs"]["vae"], ["3", 0])
        self.assertIn("prompt", encode["inputs"])
        self.assertIn("negative_prompt", encode["inputs"])
        self.assertEqual(graph[CACHE_ID]["class_type"], "QwenImage21Cache")
        self.assertEqual(graph[CACHE_ID]["inputs"]["model"], ["1", 0])
        sampler = graph[SAMPLER_ID]
        self.assertEqual(sampler["class_type"], "KSampler")
        self.assertEqual(sampler["inputs"]["model"], [CACHE_ID, 0])
        self.assertEqual(sampler["inputs"]["positive"], [ENCODE_ID, 0])
        self.assertEqual(sampler["inputs"]["negative"], [ENCODE_ID, 1])
        self.assertEqual(sampler["inputs"]["latent_image"], [LATENT_ID, 0])
        self.assertEqual(sampler["inputs"]["sampler_name"], "euler")
        self.assertEqual(sampler["inputs"]["scheduler"], "simple")
        self.assertEqual(sampler["inputs"]["steps"], 25)
        self.assertEqual(sampler["inputs"]["cfg"], 1.0)
        self.assertEqual(graph[LATENT_ID]["class_type"], "EmptyLatentImage")
        self.assertEqual(graph[DECODE_ID]["class_type"], "VAEDecode")
        self.assertEqual(graph[DECODE_ID]["inputs"]["samples"], [SAMPLER_ID, 0])
        self.assertEqual(graph[DECODE_ID]["inputs"]["vae"], ["3", 0])
        save = graph[SAVE_ID]
        self.assertEqual(save["class_type"], "SaveImage")
        self.assertEqual(save["inputs"]["images"], [DECODE_ID, 0])
        self.assertEqual(save["inputs"]["filename_prefix"], "waifu/editor")

    def test_sin_referencias_ni_loadimage_por_defecto(self):
        graph = self.template()
        self.assertNotIn("LoadImage", {node["class_type"] for node in graph.values()})
        self.assertFalse(
            any(
                key.startswith("images.")
                for node in graph.values()
                for key in node["inputs"]
            )
        )


class PrepareEditorGraphTests(unittest.TestCase):
    def template(self) -> dict:
        return load_graph(EDITOR_TEMPLATE_PATH)

    def test_parcheo_exacto_de_prompt_negativo_seed_y_tamano(self):
        graph = self.template()
        result = prepare_editor_graph(
            graph,
            prompt=" 1girl, smile ",
            negative=" low quality ",
            seed=7,
            width=768,
            height=512,
        )
        encode = result[ENCODE_ID]["inputs"]
        self.assertEqual(encode["prompt"], "1girl, smile")
        self.assertEqual(encode["negative_prompt"], "low quality")
        self.assertEqual(encode["resolution"], 0)
        self.assertEqual(result[LATENT_ID]["inputs"]["width"], 768)
        self.assertEqual(result[LATENT_ID]["inputs"]["height"], 512)
        self.assertEqual(result[SAMPLER_ID]["inputs"]["seed"], 7)
        self.assertEqual(graph[ENCODE_ID]["inputs"]["prompt"], "")
        self.assertEqual(graph[LATENT_ID]["inputs"]["width"], EDITOR_DEFAULT_SIZE)

    def test_resolucion_cero_y_latent_del_encoder_con_refs(self):
        result = prepare_editor_graph(
            self.template(),
            prompt="1girl",
            width=768,
            height=512,
            ref_images=["input.png"],
        )
        self.assertEqual(result[ENCODE_ID]["inputs"]["resolution"], 0)
        self.assertEqual(
            result[SAMPLER_ID]["inputs"]["latent_image"], [ENCODE_ID, 2]
        )

    def test_refs_uno_a_diez_anaden_loadimage_y_enlace(self):
        for count in (1, 5, EDITOR_REF_LIMIT):
            with self.subTest(count=count):
                refs = [f"ref-{index}.png" for index in range(count)]
                result = prepare_editor_graph(
                    self.template(), prompt="1girl", ref_images=refs
                )
                for index, name in enumerate(refs, start=1):
                    node = result[f"ref_{index}"]
                    self.assertEqual(node["class_type"], "LoadImage")
                    self.assertEqual(node["inputs"]["image"], name)
                    self.assertEqual(
                        result[ENCODE_ID]["inputs"][f"images.image_{index}"],
                        [f"ref_{index}", 0],
                    )
                self.assertNotIn(f"ref_{count + 1}", result)
                self.assertNotIn(
                    f"images.image_{count + 1}", result[ENCODE_ID]["inputs"]
                )

    def test_reparchear_reemplaza_refs_previas(self):
        once = prepare_editor_graph(
            self.template(), prompt="1girl", ref_images=["a.png", "b.png"]
        )
        twice = prepare_editor_graph(
            once, prompt="1girl", ref_images=["c.png"]
        )
        self.assertIn("ref_1", twice)
        self.assertNotIn("ref_2", twice)
        self.assertEqual(len(twice[ENCODE_ID]["inputs"]), 6)
        self.assertEqual(
            twice[ENCODE_ID]["inputs"]["images.image_1"], ["ref_1", 0]
        )

    def test_tupla_de_refs_tambien_vale(self):
        result = prepare_editor_graph(
            self.template(), prompt="1girl", ref_images=("a.png",)
        )
        self.assertIn("ref_1", result)

    def test_prompt_vacio_o_no_str(self):
        for prompt in ("", "   ", None, 7):
            with self.subTest(prompt=prompt):
                with self.assertRaises(EngineError):
                    prepare_editor_graph(self.template(), prompt=prompt)

    def test_negativo_no_str(self):
        for negative in (7, True, ["x"]):
            with self.subTest(negative=negative):
                with self.assertRaises(EngineError):
                    prepare_editor_graph(
                        self.template(), prompt="1girl", negative=negative
                    )

    def test_seed_invalida(self):
        for seed in (True, "x", None, -1, 2**64):
            with self.subTest(seed=seed):
                with self.assertRaises(EngineError):
                    prepare_editor_graph(self.template(), prompt="1girl", seed=seed)

    def test_seed_maxima_valida(self):
        result = prepare_editor_graph(
            self.template(), prompt="1girl", seed=2**64 - 1
        )
        self.assertEqual(result[SAMPLER_ID]["inputs"]["seed"], 2**64 - 1)

    def test_defaults_de_steps_y_cfg(self):
        result = prepare_editor_graph(self.template(), prompt="1girl")
        self.assertEqual(result[SAMPLER_ID]["inputs"]["steps"], EDITOR_DEFAULT_STEPS)
        self.assertEqual(result[SAMPLER_ID]["inputs"]["cfg"], EDITOR_DEFAULT_CFG)

    def test_parcheo_exacto_de_steps_y_cfg(self):
        graph = self.template()
        result = prepare_editor_graph(graph, prompt="1girl", steps=30, cfg=2.5)
        self.assertEqual(result[SAMPLER_ID]["inputs"]["steps"], 30)
        self.assertEqual(result[SAMPLER_ID]["inputs"]["cfg"], 2.5)
        self.assertEqual(graph[SAMPLER_ID]["inputs"]["steps"], 25)
        self.assertEqual(graph[SAMPLER_ID]["inputs"]["cfg"], 1.0)

    def test_steps_y_cfg_en_los_limites(self):
        for steps in (EDITOR_STEPS_MIN, EDITOR_STEPS_MAX):
            with self.subTest(steps=steps):
                result = prepare_editor_graph(
                    self.template(), prompt="1girl", steps=steps
                )
                self.assertEqual(result[SAMPLER_ID]["inputs"]["steps"], steps)
        for cfg in (EDITOR_CFG_MIN, EDITOR_CFG_MAX):
            with self.subTest(cfg=cfg):
                result = prepare_editor_graph(
                    self.template(), prompt="1girl", cfg=cfg
                )
                self.assertEqual(result[SAMPLER_ID]["inputs"]["cfg"], cfg)

    def test_steps_invalidos(self):
        for steps in (9, 51, 25.5, "25.5", True, "x", None):
            with self.subTest(steps=steps):
                with self.assertRaises(EngineError):
                    prepare_editor_graph(
                        self.template(), prompt="1girl", steps=steps
                    )

    def test_cfg_invalida(self):
        for cfg in (0.9, 10.1, True, "x", None):
            with self.subTest(cfg=cfg):
                with self.assertRaises(EngineError):
                    prepare_editor_graph(self.template(), prompt="1girl", cfg=cfg)

    def test_tamano_fuera_de_rango_o_no_multiplo_16(self):
        for width, height in (
            (EDITOR_SIZE_MIN - 1, 1024),
            (1024, EDITOR_SIZE_MAX + 1),
            (1000, 1024),
            (1024, 1023),
            (True, 1024),
            ("x", 1024),
        ):
            with self.subTest(width=width, height=height):
                with self.assertRaises(EngineError):
                    prepare_editor_graph(
                        self.template(), prompt="1girl", width=width, height=height
                    )

    def test_refs_invalidas_o_de_mas(self):
        for refs in (
            "no-lista",
            [""],
            [7],
            [None],
            [f"r{i}.png" for i in range(EDITOR_REF_LIMIT + 1)],
        ):
            with self.subTest(refs=str(refs)[:60]):
                with self.assertRaises(EngineError):
                    prepare_editor_graph(
                        self.template(), prompt="1girl", ref_images=refs
                    )

    def test_nodos_ausentes_lanzan_engine_error(self):
        graph = self.template()
        del graph[ENCODE_ID]
        with self.assertRaises(EngineError):
            prepare_editor_graph(graph, prompt="1girl")
        graph = self.template()
        del graph[LATENT_ID]
        with self.assertRaises(EngineError):
            prepare_editor_graph(graph, prompt="1girl")
        graph = self.template()
        del graph[SAMPLER_ID]["inputs"]["seed"]
        with self.assertRaises(EngineError):
            prepare_editor_graph(graph, prompt="1girl")

    def test_id_de_referencia_ocupado_por_otro_nodo(self):
        graph = self.template()
        graph["ref_1"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0]}}
        with self.assertRaises(EngineError):
            prepare_editor_graph(graph, prompt="1girl", ref_images=["a.png"])

    def test_build_editor_graph_carga_la_plantilla(self):
        result = build_editor_graph(
            prompt="1girl", seed=3, width=512, height=2048
        )
        self.assertEqual(result[ENCODE_ID]["inputs"]["prompt"], "1girl")
        self.assertEqual(result[SAMPLER_ID]["inputs"]["seed"], 3)
        self.assertEqual(result[LATENT_ID]["inputs"]["height"], 2048)

    def test_build_editor_graph_pasa_steps_y_cfg(self):
        result = build_editor_graph(prompt="1girl", steps=40, cfg=3.0)
        self.assertEqual(result[SAMPLER_ID]["inputs"]["steps"], 40)
        self.assertEqual(result[SAMPLER_ID]["inputs"]["cfg"], 3.0)


class RunEditorGenerationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = make_config(self.root)
        self.store = Store(self.config.data_dir / "waifu.db")
        self.store.init()

    def make_job(self, **overrides) -> dict:
        params = {
            "task": "editor",
            "mode": "edit",
            "width": 768,
            "height": 512,
            "seed": 7,
            "ref_images": ["ref-a.png"],
        }
        gen_id = self.store.add(
            EDITOR_MODEL, "1girl", "", dict(params), kind="image"
        )
        job = {
            "kind": "editor",
            "gen_id": gen_id,
            "prompt": "1girl",
            "negative": "",
            "seed": 7,
            "width": 768,
            "height": 512,
            "ref_images": ["ref-a.png"],
            "params": dict(params),
        }
        job.update(overrides)
        return job

    def factory(self, transport):
        return lambda: ComfyEngine(
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

    def test_end_to_end_copia_a_galeria(self):
        transport = FakeEditorTransport(self.config)
        job = self.make_job()
        record = {"prompt_id": None, "tracker": None, "status": "queued", "engine": None}
        run_editor_generation(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "image")
        self.assertEqual(row["params"]["task"], "editor")
        self.assertEqual(row["outputs"], ["editor_00001_.png"])
        self.assertIsNone(row["error"])
        copied = (
            self.config.data_dir
            / "gallery"
            / str(job["gen_id"])
            / "editor_00001_.png"
        )
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), PNG_BYTES)
        self.assertEqual(job["outputs"], ["editor_00001_.png"])
        self.assertIsNone(job["error"])
        self.assertEqual(record["prompt_id"], "p1")
        self.assertEqual(record["status"], "done")
        self.assertIsNotNone(record["engine"])
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph[ENCODE_ID]["inputs"]["prompt"], "1girl")
        self.assertEqual(graph[SAMPLER_ID]["inputs"]["seed"], 7)
        self.assertEqual(graph[LATENT_ID]["inputs"]["width"], 768)
        self.assertEqual(graph[LATENT_ID]["inputs"]["height"], 512)
        self.assertEqual(graph["ref_1"]["inputs"]["image"], "ref-a.png")
        self.assertEqual(
            graph[ENCODE_ID]["inputs"]["images.image_1"], ["ref_1", 0]
        )

    def test_envia_steps_y_cfg_del_job(self):
        transport = FakeEditorTransport(self.config)
        job = self.make_job(steps=30, cfg=2.5)
        record = {"prompt_id": None, "tracker": None, "status": "queued", "engine": None}
        run_editor_generation(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
        )
        self.assertEqual(self.store.get(job["gen_id"])["status"], "done")
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph[SAMPLER_ID]["inputs"]["steps"], 30)
        self.assertEqual(graph[SAMPLER_ID]["inputs"]["cfg"], 2.5)

    def test_error_no_propaga_y_marca_store(self):
        transport = FakeEditorTransport(self.config, write_output=False)
        job = self.make_job()
        record = {"prompt_id": None, "tracker": None, "status": "queued", "engine": None}
        run_editor_generation(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIsNotNone(row["error"])
        self.assertEqual(job["outputs"], [])
        self.assertIsNotNone(job["error"])
        self.assertEqual(record["status"], "error")

    def test_grafo_invalido_marca_error(self):
        job = self.make_job(prompt="", seed=-3)
        run_editor_generation(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(FakeEditorTransport(self.config)),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("prompt", row["error"])

    def test_cancelado_antes_de_arrancar_no_hace_nada(self):
        job = self.make_job()
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "cancelled",
            "engine": None,
        }
        run_editor_generation(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(FakeEditorTransport(self.config)),
            record=record,
        )
        self.assertEqual(job["outputs"], [])
        self.assertIsNone(job["error"])
        self.assertEqual(self.store.get(job["gen_id"])["status"], "queued")


class EditorQueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = make_config(self.root)
        self.store = Store(self.config.data_dir / "waifu.db")
        self.store.init()
        accept_editor_license(self.config.data_dir)
        self.registry = ModelRegistry.load(
            Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "models.json"
        )
        server_module._JOBS.clear()
        self.addCleanup(server_module._JOBS.clear)

    def install_model(self) -> None:
        for relative in server_module.EDITOR_MODEL_FILES:
            path = self.config.comfy_root / "models" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-model")

    def test_flujo_http_completo_con_worker(self):
        self.install_model()
        transport = FakeEditorTransport(self.config)
        factory = lambda: ComfyEngine(  # noqa: E731
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

        def run_job(job):
            run_editor_generation(
                job, config=self.config, store=self.store, engine_factory=factory
            )

        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=factory,
            queue=JobQueue(run_job),
            start_worker=True,
        )
        ref = base64.b64encode(PNG_BYTES).decode("ascii")
        with TestClient(app) as client:
            response = client.post(
                "/api/editor/generate",
                json={
                    "prompt": "1girl, smile",
                    "mode": "edit",
                    "negative": "low quality",
                    "ref_images_b64": [ref, ref],
                    "size": {"width": 768, "height": 512},
                    "seed": 9,
                },
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 5)
            status = client.get(f"/api/jobs/{job_id}").json()
            self.assertEqual(status["status"], "done")
            self.assertEqual(status["outputs"][0]["name"], "editor_00001_.png")
            media = client.get(status["outputs"][0]["url"])
            self.assertEqual(media.status_code, 200)
            self.assertEqual(media.headers["content-type"], "image/png")
            self.assertEqual(media.content, PNG_BYTES)
            gallery = client.get("/api/gallery").json()
            self.assertEqual(gallery["count"], 1)
            item = gallery["items"][0]
            self.assertEqual(item["kind"], "image")
            self.assertEqual(item["params"]["task"], "editor")
            self.assertEqual(item["params"]["width"], 768)
            self.assertEqual(item["params"]["height"], 512)
            self.assertEqual(item["params"]["seed"], 9)
            self.assertEqual(len(item["params"]["ref_images"]), 2)
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph[ENCODE_ID]["inputs"]["prompt"], "1girl, smile")
        self.assertEqual(graph[ENCODE_ID]["inputs"]["negative_prompt"], "low quality")
        self.assertEqual(graph[SAMPLER_ID]["inputs"]["seed"], 9)
        self.assertEqual(graph[LATENT_ID]["inputs"]["width"], 768)
        self.assertEqual(graph[LATENT_ID]["inputs"]["height"], 512)
        names = [graph["ref_1"]["inputs"]["image"], graph["ref_2"]["inputs"]["image"]]
        for name in names:
            self.assertTrue((self.config.comfy_root / "input" / name).is_file())
        self.assertEqual(names[0], item["params"]["ref_images"][0])

    def test_flujo_sin_refs_usa_el_tamano_por_defecto(self):
        self.install_model()
        transport = FakeEditorTransport(self.config)
        factory = lambda: ComfyEngine(  # noqa: E731
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

        def run_job(job):
            run_editor_generation(
                job, config=self.config, store=self.store, engine_factory=factory
            )

        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=factory,
            queue=JobQueue(run_job),
            start_worker=True,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/editor/generate", json={"prompt": "1girl"}
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 5)
            self.assertEqual(
                client.get(f"/api/jobs/{job_id}").json()["status"], "done"
            )
        params = self.store.get(1)["params"]
        self.assertEqual(params["mode"], "generate")
        self.assertEqual(params["width"], EDITOR_DEFAULT_SIZE)
        self.assertEqual(params["height"], EDITOR_DEFAULT_SIZE)
        self.assertEqual(params["ref_images"], [])


class InheritSizeTests(unittest.TestCase):
    @staticmethod
    def _png(width: int, height: int) -> bytes:
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (width, height), (9, 9, 9)).save(buffer, format="PNG")
        return buffer.getvalue()

    def test_tamano_valido_se_conserva(self):
        from app.editor import inherit_size_from_image

        self.assertEqual(inherit_size_from_image(self._png(640, 960)), (640, 960))

    def test_pequeno_se_escala_al_minimo(self):
        from app.editor import inherit_size_from_image

        self.assertEqual(inherit_size_from_image(self._png(400, 600)), (512, 768))

    def test_grande_se_encaja_al_maximo(self):
        from app.editor import inherit_size_from_image

        self.assertEqual(inherit_size_from_image(self._png(4096, 3072)), (2048, 1536))

    def test_ilegible_lanza_engine_error(self):
        from app.editor import inherit_size_from_image

        with self.assertRaises(EngineError):
            inherit_size_from_image(b"no-es-una-imagen")


class QwenPoseAndPresetTests(unittest.TestCase):
    def test_presets_existentes_y_completos(self):
        from app.editor import QWEN_POSE_PRESETS

        self.assertEqual(len(QWEN_POSE_PRESETS), 4)
        for key in ("l0_editorial", "l1_open", "l2_bold_nsfw", "l3_extreme"):
            self.assertIn(key, QWEN_POSE_PRESETS)
            preset = QWEN_POSE_PRESETS[key]
            self.assertEqual(preset["id"], key)
            self.assertTrue(preset["label"])
            self.assertTrue(preset["level"])
            self.assertTrue(len(preset["template"]) > 20)

    def test_format_qwen_7block_prompt(self):
        from app.editor import QWEN_POSE_PRESETS, format_qwen_7block_prompt

        self.assertEqual(format_qwen_7block_prompt("cat", None), "cat")
        self.assertEqual(format_qwen_7block_prompt("cat", "inexistente"), "cat")
        formatted = format_qwen_7block_prompt("cat", "l0_editorial")
        self.assertTrue(formatted.startswith("cat, "))
        self.assertIn("standing or seated anime pose", formatted)

        # Empty prompt returns template
        self.assertEqual(
            format_qwen_7block_prompt("", "l0_editorial"),
            QWEN_POSE_PRESETS["l0_editorial"]["template"],
        )

        # Template already in prompt is not duplicated
        tpl = QWEN_POSE_PRESETS["l0_editorial"]["template"]
        self.assertEqual(
            format_qwen_7block_prompt(f"1girl, {tpl}", "l0_editorial"),
            f"1girl, {tpl}",
        )


class EditorGraphFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.template = load_graph(EDITOR_TEMPLATE_PATH)

    def test_validaciones_sampler_y_scheduler(self):
        with self.assertRaises(EngineError):
            prepare_editor_graph(
                self.template, prompt="test", sampler_name="invalid_sampler"
            )
        with self.assertRaises(EngineError):
            prepare_editor_graph(
                self.template, prompt="test", scheduler="invalid_scheduler"
            )

    def test_sampler_y_scheduler_configurados(self):
        graph = prepare_editor_graph(
            self.template,
            prompt="test",
            sampler_name="er_sde",
            scheduler="beta",
        )
        sampler = graph[SAMPLER_ID]["inputs"]
        self.assertEqual(sampler["sampler_name"], "er_sde")
        self.assertEqual(sampler["scheduler"], "beta")

    def test_preserve_structure_con_refs(self):
        graph = prepare_editor_graph(
            self.template,
            prompt="test",
            ref_images=["input.png"],
            preserve_structure=True,
        )
        sampler = graph[SAMPLER_ID]["inputs"]
        self.assertIn(PRESERVE_ENCODE_ID, graph)
        self.assertEqual(graph[PRESERVE_ENCODE_ID]["class_type"], "VAEEncode")
        self.assertEqual(
            graph[PRESERVE_ENCODE_ID]["inputs"],
            {"pixels": ["ref_1", 0], "vae": [VAE_ID, 0]},
        )
        self.assertEqual(sampler["latent_image"], [PRESERVE_ENCODE_ID, 0])
        self.assertNotEqual(sampler["latent_image"], [ENCODE_ID, 2])
        self.assertNotEqual(sampler["latent_image"], [LATENT_ID, 0])
        self.assertEqual(sampler["denoise"], EDITOR_PRESERVE_DENOISE)
        self.assertLess(sampler["denoise"], 1.0)

    def test_preserve_structure_false_usa_latent_del_encoder_y_denoise_1(self):
        graph = prepare_editor_graph(
            self.template,
            prompt="test",
            ref_images=["input.png"],
            preserve_structure=False,
        )
        sampler = graph[SAMPLER_ID]["inputs"]
        self.assertNotIn(PRESERVE_ENCODE_ID, graph)
        self.assertEqual(sampler["latent_image"], [ENCODE_ID, 2])
        self.assertEqual(sampler["denoise"], 1.0)

    def test_preserve_structure_sin_refs_conserva_empty_latent(self):
        graph = prepare_editor_graph(
            self.template,
            prompt="test",
            ref_images=[],
            preserve_structure=True,
        )
        sampler = graph[SAMPLER_ID]["inputs"]
        self.assertNotIn(PRESERVE_ENCODE_ID, graph)
        self.assertEqual(sampler["latent_image"], [LATENT_ID, 0])
        self.assertEqual(sampler["denoise"], 1.0)

    def test_preserve_structure_multiples_refs_usa_primera_ref(self):
        graph = prepare_editor_graph(
            self.template,
            prompt="test",
            ref_images=["char_a.png", "char_b.png", "char_c.png"],
            preserve_structure=True,
        )
        encode_inputs = graph[ENCODE_ID]["inputs"]
        self.assertEqual(encode_inputs["images.image_1"], ["ref_1", 0])
        self.assertEqual(encode_inputs["images.image_2"], ["ref_2", 0])
        self.assertEqual(encode_inputs["images.image_3"], ["ref_3", 0])
        self.assertIn(PRESERVE_ENCODE_ID, graph)
        self.assertEqual(
            graph[PRESERVE_ENCODE_ID]["inputs"],
            {"pixels": ["ref_1", 0], "vae": [VAE_ID, 0]},
        )
        sampler = graph[SAMPLER_ID]["inputs"]
        self.assertEqual(sampler["latent_image"], [PRESERVE_ENCODE_ID, 0])
        self.assertEqual(sampler["denoise"], 0.65)

    def test_preserve_structure_sin_vaeloader_lanza_engine_error(self):
        graph = load_graph(EDITOR_TEMPLATE_PATH)
        del graph[VAE_ID]
        with self.assertRaises(EngineError):
            prepare_editor_graph(
                graph,
                prompt="test",
                ref_images=["input.png"],
                preserve_structure=True,
            )

    def test_build_editor_graph_preserve_structure(self):
        result = build_editor_graph(
            prompt="test",
            ref_images=["input.png"],
            preserve_structure=True,
        )
        self.assertIn(PRESERVE_ENCODE_ID, result)
        self.assertEqual(
            result[SAMPLER_ID]["inputs"]["latent_image"],
            [PRESERVE_ENCODE_ID, 0],
        )
        self.assertEqual(result[SAMPLER_ID]["inputs"]["denoise"], 0.65)

    def test_loras_encadenados(self):
        loras = [
            {"file": "lora_a.safetensors", "weight": 0.8},
            {"file": "lora_b.safetensors", "weight": 0.5},
        ]
        graph = prepare_editor_graph(
            self.template,
            prompt="test",
            loras=loras,
        )
        self.assertIn("lora_1", graph)
        self.assertIn("lora_2", graph)
        self.assertEqual(graph["lora_1"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(graph["lora_1"]["inputs"]["model"], ["1", 0])
        self.assertEqual(graph["lora_1"]["inputs"]["lora_name"], "lora_a.safetensors")
        self.assertEqual(graph["lora_1"]["inputs"]["strength_model"], 0.8)

        self.assertEqual(graph["lora_2"]["inputs"]["model"], ["lora_1", 0])
        self.assertEqual(graph["lora_2"]["inputs"]["lora_name"], "lora_b.safetensors")
        self.assertEqual(graph["lora_2"]["inputs"]["strength_model"], 0.5)

        # Cache node must consume lora_2
        self.assertEqual(graph[CACHE_ID]["inputs"]["model"], ["lora_2", 0])

    def test_loras_invalidos_lanzan_engine_error(self):
        with self.assertRaises(EngineError):
            prepare_editor_graph(self.template, prompt="test", loras="no-lista")
        with self.assertRaises(EngineError):
            prepare_editor_graph(
                self.template, prompt="test", loras=[{"sin_archivo": True}]
            )


class EditorRouteFeaturesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = make_config(self.root)
        self.store = Store(self.config.data_dir / "waifu.db")
        self.store.init()
        accept_editor_license(self.config.data_dir)
        self.registry = ModelRegistry.load(
            Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "models.json"
        )
        server_module._JOBS.clear()
        self.addCleanup(server_module._JOBS.clear)

    def install_model(self) -> None:
        for relative in server_module.EDITOR_MODEL_FILES:
            path = self.config.comfy_root / "models" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-model")

    def test_api_editor_pose_presets(self):
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            queue=JobQueue(lambda j: None),
        )
        with TestClient(app) as client:
            res = client.get("/api/editor/pose_presets")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("presets", data)
            self.assertEqual(len(data["presets"]), 4)

    def test_api_editor_generate_con_nuevos_campos(self):
        self.install_model()
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            queue=JobQueue(lambda j: None),
        )
        with TestClient(app) as client:
            res = client.post(
                "/api/editor/generate",
                json={
                    "prompt": "waifu portrait",
                    "pose_preset": "l2_bold_nsfw",
                    "sampler_name": "er_sde",
                    "scheduler": "beta",
                    "preserve_structure": True,
                    "loras": [{"file": "test.safetensors", "weight": 0.7}],
                },
            )
            self.assertEqual(res.status_code, 200)
            job_id = res.json()["job_id"]
            job = app.state.jobs[job_id]
            self.assertEqual(job["sampler_name"], "er_sde")
            self.assertEqual(job["scheduler"], "beta")
            self.assertTrue(job["preserve_structure"])
            self.assertEqual(job["pose_preset"], "l2_bold_nsfw")
            self.assertEqual(len(job["loras"]), 1)

    def test_api_editor_generate_preset_valido_con_prompt_vacio(self):
        self.install_model()
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            queue=JobQueue(lambda j: None),
        )
        with TestClient(app) as client:
            res = client.post(
                "/api/editor/generate",
                json={
                    "prompt": "",
                    "pose_preset": "l1_open",
                },
            )
            self.assertEqual(res.status_code, 200)
            job_id = res.json()["job_id"]
            job = app.state.jobs[job_id]
            self.assertTrue("suggestive anime pose" in job["prompt"].lower())

    def test_api_editor_generate_validaciones_error(self):
        self.install_model()
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            queue=JobQueue(lambda j: None),
        )
        with TestClient(app) as client:
            res = client.post(
                "/api/editor/generate",
                json={"prompt": "test", "sampler_name": "invalido"},
            )
            self.assertEqual(res.status_code, 400)

            res = client.post(
                "/api/editor/generate",
                json={"prompt": "test", "scheduler": "invalido"},
            )
            self.assertEqual(res.status_code, 400)

            res = client.post(
                "/api/editor/generate",
                json={"prompt": "test", "pose_preset": "invalido"},
            )
            self.assertEqual(res.status_code, 400)

            res = client.post(
                "/api/editor/generate",
                json={"prompt": "test", "loras": "no-lista"},
            )
            self.assertEqual(res.status_code, 400)


    def test_api_editor_generate_parent_y_root_gen_id(self):
        self.install_model()
        root_id = self.store.add("anima-2.9b-preview", "root prompt", "", {"task": "txt2img"})
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            queue=JobQueue(lambda j: None),
        )
        with TestClient(app) as client:
            res_no_parent = client.post(
                "/api/editor/generate",
                json={"prompt": "standalone edit"},
            )
            self.assertEqual(res_no_parent.status_code, 200)
            standalone_job = app.state.jobs[res_no_parent.json()["job_id"]]
            standalone_row = self.store.get(standalone_job["gen_id"])
            self.assertNotIn("parent_gen_id", standalone_row["params"])
            self.assertNotIn("root_gen_id", standalone_row["params"])

            res_child = client.post(
                "/api/editor/generate",
                json={"prompt": "first edit", "parent_gen_id": root_id},
            )
            self.assertEqual(res_child.status_code, 200)
            child_job = app.state.jobs[res_child.json()["job_id"]]
            child_id = child_job["gen_id"]
            child_row = self.store.get(child_id)
            self.assertEqual(child_row["params"]["parent_gen_id"], root_id)
            self.assertEqual(child_row["params"]["root_gen_id"], root_id)

            res_grandchild = client.post(
                "/api/editor/generate",
                json={"prompt": "second edit", "parent_gen_id": child_id},
            )
            self.assertEqual(res_grandchild.status_code, 200)
            grandchild_job = app.state.jobs[res_grandchild.json()["job_id"]]
            grandchild_row = self.store.get(grandchild_job["gen_id"])
            self.assertEqual(grandchild_row["params"]["parent_gen_id"], child_id)
            self.assertEqual(grandchild_row["params"]["root_gen_id"], root_id)

            for invalid_parent in (0, -3, "abc", True, 2.5):
                res_bad = client.post(
                    "/api/editor/generate",
                    json={"prompt": "bad parent", "parent_gen_id": invalid_parent},
                )
                self.assertEqual(res_bad.status_code, 400)
                self.assertIn("parent_gen_id", res_bad.json().get("error", ""))


if __name__ == "__main__":
    unittest.main()
