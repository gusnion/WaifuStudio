"""Tests CPU de la webapp FastAPI (F3b). Sin red, GPU ni LLM real."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import EngineConfig
from app.engine import ComfyEngine
from app.jobs import JobQueue
from app.registry import DEFAULT_PATH, ModelRegistry
from app.server import create_app, run_generation
from app.store import Store

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"waifu-fake-png"
MODEL_ID = "anima-2.9b-preview"


def make_config(root: Path) -> EngineConfig:
    return EngineConfig(
        comfy_root=root / "comfy",
        comfy_url="http://127.0.0.1:1",
        data_dir=root / "data",
    )


class FakeTransport:
    """Transporte HTTP falso del engine: submit y history success con PNG fake."""

    def __init__(self, config, *, output_name="fake.png", write_output=True):
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
                (self.config.comfy_output_dir / self.output_name).write_bytes(PNG_BYTES)
            return 200, json.dumps(
                {
                    "p1": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "9": {
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


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = make_config(self.root)
        self.store = Store(self.config.data_dir / "waifu.db")
        self.store.init()
        self.registry = ModelRegistry.load(DEFAULT_PATH)

    def make_client(self, **kwargs) -> TestClient:
        kwargs.setdefault("config", self.config)
        kwargs.setdefault("store", self.store)
        kwargs.setdefault("registry", self.registry)
        kwargs.setdefault("start_worker", False)
        client = TestClient(create_app(**kwargs))
        self.addCleanup(client.close)
        return client

    def fake_factory(self, transport):
        return lambda: ComfyEngine(
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

    def add_gallery_png(self, gen_id: int, name: str = "ok.png") -> Path:
        directory = self.config.data_dir / "gallery" / str(gen_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(PNG_BYTES)
        return path


class ReadRoutesTests(ServerTestCase):
    def test_models(self):
        response = self.make_client().get("/api/models")
        self.assertEqual(response.status_code, 200)
        models = response.json()
        self.assertGreaterEqual(len(models), 1)
        self.assertEqual(models[0]["id"], MODEL_ID)
        self.assertEqual(
            set(models[0]),
            {"id", "display_name", "family", "preprompt", "unet_name", "defaults"},
        )
        self.assertEqual(models[0]["family"], "anima")
        self.assertIsInstance(models[0]["defaults"], dict)

    def test_preprompts(self):
        response = self.make_client().get("/api/preprompts", params={"family": "anima"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["family"], "anima")
        self.assertIn("glossy", data["names"])
        self.assertEqual(data["default"], "glossy")

    def test_preprompts_familia_desconocida_400(self):
        response = self.make_client().get("/api/preprompts", params={"family": "nope"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_traits(self):
        response = self.make_client().get("/api/traits")
        self.assertEqual(response.status_code, 200)
        groups = response.json()
        self.assertEqual(len(groups), 8)
        self.assertIn("hair", groups)
        self.assertTrue(all(isinstance(traits, list) for traits in groups.values()))

    def test_gallery_vacia(self):
        response = self.make_client().get("/api/gallery")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [], "count": 0})

    def test_gallery_con_item_y_urls(self):
        gen_id = self.store.add(MODEL_ID, "1girl, smile")
        self.store.update(gen_id, status="done", outputs=["ok.png"])
        data = self.make_client().get("/api/gallery").json()
        self.assertEqual(data["count"], 1)
        item = data["items"][0]
        self.assertEqual(item["id"], gen_id)
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["urls"], [f"/media/{gen_id}/ok.png"])


class PromptBuildTests(ServerTestCase):
    def test_ok(self):
        response = self.make_client().post(
            "/api/prompt/build", json={"trait_ids": ["smile", "long_hair"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"prompt": "long hair, smile"})

    def test_vacio(self):
        response = self.make_client().post("/api/prompt/build", json={"trait_ids": []})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"prompt": ""})

    def test_trait_desconocido_400(self):
        response = self.make_client().post(
            "/api/prompt/build", json={"trait_ids": ["no_existe"]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_sin_trait_ids_400(self):
        response = self.make_client().post("/api/prompt/build", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class EnhanceRouteTests(ServerTestCase):
    @staticmethod
    def fake_llm(system, user):
        return "1girl, smile"

    @staticmethod
    def nsfw_llm(system, user):
        return "1girl, nsfw, uncensored, smile"

    def test_con_llm(self):
        client = self.make_client(llm=self.fake_llm)
        response = client.post(
            "/api/enhance", json={"text": "1girl", "preprompt": "glossy"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("1girl, smile", data["positive"])
        self.assertTrue(data["positive"].endswith("sfw"))
        self.assertIn("masterpiece", data["positive"])
        self.assertIn("worst quality", data["negative"])

    def test_sin_llm_503(self):
        response = self.make_client().post("/api/enhance", json={"text": "1girl"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "LLM no disponible"})

    def test_texto_vacio_400(self):
        client = self.make_client(llm=self.fake_llm)
        response = client.post("/api/enhance", json={"text": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_rating_por_defecto_sfw_elimina_nsfw(self):
        client = self.make_client(llm=self.nsfw_llm)
        response = client.post("/api/enhance", json={"text": "1girl", "preprompt": "ninguno"})
        self.assertEqual(response.status_code, 200)
        tags = [tag.strip().lower() for tag in response.json()["positive"].split(",")]
        self.assertIn("sfw", tags)
        self.assertNotIn("nsfw", tags)
        self.assertNotIn("uncensored", tags)

    def test_rating_invalido_400(self):
        for rating in ("explicit", "", 5):
            with self.subTest(rating=rating):
                response = self.make_client(llm=self.fake_llm).post(
                    "/api/enhance", json={"text": "1girl", "rating": rating}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())


class GenerateValidationTests(ServerTestCase):
    def payload(self, **overrides) -> dict:
        data = {
            "model_id": MODEL_ID,
            "prompt": "1girl, smile",
            "preprompt": "ninguno",
            "params": {"seed": 1},
        }
        data.update(overrides)
        return data

    def test_modelo_inexistente_400(self):
        response = self.make_client().post(
            "/api/generate", json=self.payload(model_id="no-existe")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_prompt_vacio_400(self):
        for prompt in ("", "   "):
            with self.subTest(prompt=prompt):
                response = self.make_client().post(
                    "/api/generate", json=self.payload(prompt=prompt)
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_rating_invalido_400(self):
        response = self.make_client().post(
            "/api/generate", json=self.payload(rating="explicit")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_strength_invalido_400(self):
        for strength in (0, 1.5, "abc"):
            with self.subTest(strength=strength):
                response = self.make_client().post(
                    "/api/generate", json=self.payload(strength=strength)
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_base64_invalido_400(self):
        response = self.make_client().post(
            "/api/generate", json=self.payload(ref_image_b64="%%%no-base64%%%")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_encola_y_escribe_referencia(self):
        client = self.make_client()
        raw = base64.b64encode(PNG_BYTES).decode("ascii")
        response = client.post(
            "/api/generate", json=self.payload(ref_image_b64=raw, strength=0.5)
        )
        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        self.assertRegex(job_id, r"^[0-9a-f]{32}$")
        inputs = list((self.config.comfy_root / "input").glob("*.png"))
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0].read_bytes(), PNG_BYTES)
        self.assertEqual(self.store.count(), 1)
        row = self.store.list()[0]
        self.assertEqual(row["params"]["strength"], 0.5)
        self.assertEqual(row["params"]["ref_image"], inputs[0].name)
        self.assertEqual(row["params"]["rating"], "sfw")
        status = client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(status["status"], "queued")
        self.assertEqual(status["outputs"], [])
        self.assertIsNone(status["error"])

    def test_job_desconocido_404(self):
        response = self.make_client().get("/api/jobs/no-existe")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())


class RunGenerationTests(ServerTestCase):
    def make_job(self, **overrides) -> dict:
        gen_id = self.store.add(MODEL_ID, "1girl, smile", "", {"seed": 7})
        job = {
            "gen_id": gen_id,
            "model_id": MODEL_ID,
            "prompt": "1girl, smile",
            "negative": "",
            "preprompt": "ninguno",
            "params": {"seed": 7, "steps": 5, "width": 320, "height": 576},
            "ref_image": None,
            "strength": None,
        }
        job.update(overrides)
        return job

    def test_end_to_end_copia_a_galeria(self):
        transport = FakeTransport(self.config)
        job = self.make_job()
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["outputs"], ["fake.png"])
        self.assertIsNone(row["error"])
        copied = self.config.data_dir / "gallery" / str(job["gen_id"]) / "fake.png"
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), PNG_BYTES)
        self.assertEqual(job["outputs"], ["fake.png"])
        self.assertIsNone(job["error"])
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["7"]["inputs"]["seed"], 7)
        self.assertEqual(graph["7"]["inputs"]["steps"], 5)
        self.assertEqual(graph["4"]["inputs"]["text"], "1girl, smile")
        self.assertEqual(graph["5"]["inputs"]["text"], "")

    def test_img2img_usa_referencia_y_fuerza(self):
        transport = FakeTransport(self.config)
        job = self.make_job(ref_image="ref-abc.png", strength=0.5)
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        self.assertEqual(self.store.get(job["gen_id"])["status"], "done")
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["img_ref"]["inputs"]["image"], "ref-abc.png")
        self.assertEqual(graph["7"]["inputs"]["denoise"], 0.5)
        self.assertNotIn("6", graph)

    def test_preprompt_glossy_se_aplica(self):
        transport = FakeTransport(self.config)
        job = self.make_job(preprompt="glossy")
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        graph = transport.submits[0]["prompt"]
        self.assertTrue(graph["4"]["inputs"]["text"].startswith("masterpiece, best quality"))
        self.assertIn("worst quality", graph["5"]["inputs"]["text"])

    def test_error_no_propaga_y_marca_store(self):
        transport = FakeTransport(self.config, write_output=False)
        job = self.make_job()
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertTrue(row["error"])
        self.assertEqual(job["outputs"], [])
        self.assertTrue(job["error"])

    def test_modelo_desconocido_marca_error(self):
        transport = FakeTransport(self.config)
        job = self.make_job(model_id="no-existe")
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("no registrado", row["error"])


class QueueIntegrationTests(ServerTestCase):
    def test_flujo_http_completo_con_worker(self):
        transport = FakeTransport(self.config)
        factory = self.fake_factory(transport)

        def run_job(job):
            run_generation(
                job,
                config=self.config,
                store=self.store,
                registry=self.registry,
                engine_factory=factory,
            )

        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            queue=JobQueue(run_job),
            start_worker=True,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/generate",
                json={
                    "model_id": MODEL_ID,
                    "prompt": "1girl",
                    "preprompt": "ninguno",
                    "params": {"seed": 3},
                },
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 5)
            status = client.get(f"/api/jobs/{job_id}").json()
            self.assertEqual(status["status"], "done")
            self.assertEqual(len(status["outputs"]), 1)
            self.assertEqual(status["outputs"][0]["name"], "fake.png")
            media = client.get(status["outputs"][0]["url"])
            self.assertEqual(media.status_code, 200)
            self.assertEqual(media.content, PNG_BYTES)
            gallery = client.get("/api/gallery").json()
            self.assertEqual(gallery["count"], 1)
            self.assertEqual(gallery["items"][0]["urls"], [status["outputs"][0]["url"]])


class MediaTests(ServerTestCase):
    def test_sirve_png_y_404(self):
        gen_id = self.store.add(MODEL_ID, "1girl")
        self.add_gallery_png(gen_id)
        client = self.make_client()
        response = client.get(f"/media/{gen_id}/ok.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, PNG_BYTES)
        missing = client.get(f"/media/{gen_id}/nope.png")
        self.assertEqual(missing.status_code, 404)
        self.assertIn("error", missing.json())

    def test_traversal_403(self):
        gen_id = self.store.add(MODEL_ID, "1girl")
        (self.config.data_dir / "secret.png").write_bytes(PNG_BYTES)
        response = self.make_client().get(f"/media/{gen_id}/..%2F..%2Fsecret.png")
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())


class IndexTests(ServerTestCase):
    def test_index_200_con_waifu(self):
        response = self.make_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("WAIFU", response.text)
        self.assertIn("/static/app.js", response.text)
        self.assertIn("OC Maker", response.text)
        self.assertIn("Video", response.text)


if __name__ == "__main__":
    unittest.main()
