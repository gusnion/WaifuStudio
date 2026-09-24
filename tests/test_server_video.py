"""Tests CPU de los endpoints de video (F4). Sin red, GPU ni LLM real."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import server as server_module
from app.config import EngineConfig
from app.engine import ComfyEngine, EngineError
from app.jobs import JobQueue
from app.motion import MOTION_NEGATIVE, SYS_PROMPT_MOTION
from app.registry import DEFAULT_PATH, ModelRegistry
from app.server import create_app
from app.store import Store
from app.video import (
    H3_TEMPLATE_PATH,
    WAN_FLF_TEMPLATE_PATH,
    WAN_TEMPLATE_PATH,
    run_video_generation,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"waifu-fake-png"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"waifu-fake-mp4"
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")


class FakeLLM:
    def __init__(self, output: str = "She walks slowly.") -> None:
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.output


class RecordingQueue:
    """Cola inyectada que solo registra los jobs (no arranca worker)."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def submit(self, job: dict) -> str:
        self.jobs.append(job)
        return f"job-{len(self.jobs)}"


class StatusQueue:
    """Cola inyectada con estados mutables (patron de test_server.py)."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.statuses: dict[str, str] = {}

    def submit(self, job: dict) -> str:
        self.jobs.append(job)
        job_id = f"job-{len(self.jobs)}"
        self.statuses[job_id] = "queued"
        return job_id

    def status(self, job_id: str) -> str:
        if job_id not in self.statuses:
            raise EngineError(f"job desconocido: {job_id!r}")
        return self.statuses[job_id]


class FakeCancelEngine:
    """Engine falso que registra delete_queued/interrupt sin red."""

    client_id = "cancel-cid"

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.interrupts = 0

    def delete_queued(self, prompt_id: str) -> bool:
        self.deleted.append(prompt_id)
        return True

    def interrupt(self) -> bool:
        self.interrupts += 1
        return True


class FakeVideoTransport:
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


class ServerVideoTestCase(unittest.TestCase):
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
        self.registry = ModelRegistry.load(DEFAULT_PATH)
        server_module._JOBS.clear()
        self.addCleanup(server_module._JOBS.clear)

    def make_client(self, **kwargs) -> TestClient:
        kwargs.setdefault("config", self.config)
        kwargs.setdefault("store", self.store)
        kwargs.setdefault("registry", self.registry)
        kwargs.setdefault("start_worker", False)
        client = TestClient(create_app(**kwargs))
        self.addCleanup(client.close)
        return client

    def input_files(self) -> list[Path]:
        input_dir = self.config.comfy_root / "input"
        return sorted(input_dir.glob("*.png")) if input_dir.is_dir() else []


class MotionRouteTests(ServerVideoTestCase):
    def test_sin_llm_503(self):
        response = self.make_client().post("/api/motion", json={"text": "la chica camina"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "LLM no disponible"})

    def test_ok_devuelve_positivo_y_negativo_fijo(self):
        llm = FakeLLM()
        client = self.make_client(llm=llm)
        response = client.post(
            "/api/motion", json={"text": "la chica camina", "rating": "nsfw"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"motion_positive": "She walks slowly.", "motion_negative": MOTION_NEGATIVE},
        )
        system, user = llm.calls[0]
        self.assertEqual(system, SYS_PROMPT_MOTION)
        self.assertIn("movimiento: la chica camina", user)

    def test_rating_por_defecto_nsfw(self):
        llm = FakeLLM()
        response = self.make_client(llm=llm).post("/api/motion", json={"text": "camina"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("rating: nsfw", llm.calls[0][1])

    def test_texto_vacio_400(self):
        client = self.make_client(llm=FakeLLM())
        for text in ("", "   "):
            with self.subTest(text=text):
                response = client.post("/api/motion", json={"text": text})
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_rating_invalido_400(self):
        response = self.make_client(llm=FakeLLM()).post(
            "/api/motion", json={"text": "camina", "rating": "explicit"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class VideoGenerateValidationTests(ServerVideoTestCase):
    def payload(self, **overrides) -> dict:
        data = {
            "engine": "wan",
            "image_b64": PNG_B64,
            "motion_positive": "She walks slowly.",
            "aspect": "vertical",
            "seed": 5,
        }
        data.update(overrides)
        return data

    def assert_400(self, payload: dict) -> None:
        response = self.make_client().post("/api/video/generate", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_engine_invalido_400(self):
        self.assert_400(self.payload(engine="nope"))
        self.assert_400(self.payload(engine=None))

    def test_wan_sin_motion_positive_400(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assert_400(self.payload(motion_positive=value))

    def test_aspect_invalido_400(self):
        self.assert_400(self.payload(aspect="cuadrado"))

    def test_image_b64_requerida_o_invalida_400(self):
        self.assert_400(self.payload(image_b64=None))
        self.assert_400(self.payload(image_b64="  "))
        self.assert_400(self.payload(image_b64="%%%no-base64%%%"))

    def test_h3_sin_prompt_400(self):
        self.assert_400(
            self.payload(
                engine="h3", last_image_b64=PNG_B64, prompt="", motion_positive=""
            )
        )

    def test_h3_sin_last_image_400(self):
        self.assert_400(
            self.payload(engine="h3", last_image_b64=None, prompt="p descripcion")
        )

    def test_h3_last_image_b64_invalida_400(self):
        self.assert_400(
            self.payload(engine="h3", last_image_b64="%%%mal%%%", prompt="p")
        )

    def test_seed_invalida_400(self):
        self.assert_400(self.payload(seed="abc"))
        self.assert_400(self.payload(seed=True))

    def test_validaciones_no_escriben_imagenes(self):
        client = self.make_client()
        client.post("/api/video/generate", json=self.payload(engine="nope"))
        client.post("/api/video/generate", json=self.payload(image_b64="%%%mal%%%"))
        client.post("/api/video/generate", json=self.payload(engine="h3", prompt=""))
        self.assertEqual(self.input_files(), [])
        self.assertEqual(self.store.count(), 0)

    def test_mode_invalido_400(self):
        for value in ("nope", 5):
            with self.subTest(value=value):
                self.assert_400(self.payload(mode=value))

    def test_flf2v_sin_last_image_400(self):
        self.assert_400(
            {
                "mode": "flf2v",
                "image_b64": PNG_B64,
                "motion_positive": "She walks slowly.",
            }
        )
        self.assert_400(self.payload(mode="flf2v", last_image_b64=None))
        self.assert_400(self.payload(mode="flf2v", last_image_b64="%%%mal%%%"))

    def test_mode_flf2v_con_h3_400(self):
        self.assert_400(
            self.payload(engine="h3", mode="flf2v", last_image_b64=PNG_B64, prompt="p")
        )

    def test_seconds_fuera_de_rango_o_invalidos_400(self):
        for value in (0, 0.5, 16, 20, -1, "abc", True):
            with self.subTest(value=value):
                self.assert_400(self.payload(seconds=value))

    def test_motion_negative_no_str_400(self):
        self.assert_400(self.payload(motion_negative=123))


class VideoGenerateEnqueueTests(ServerVideoTestCase):
    def test_wan_encola_job_y_registra_kind_video(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/video/generate",
            json={
                "engine": "wan",
                "image_b64": PNG_B64,
                "motion_positive": "She walks slowly.",
                "aspect": "horizontal",
                "seed": 13,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["job_id"], "job-1")
        self.assertEqual(data["frames"], 81)
        self.assertIn("cabe en 12 GB (perfil certificado)", data["vram_hint"])
        self.assertEqual(len(queue.jobs), 1)
        job = queue.jobs[0]
        self.assertEqual(job["kind"], "video")
        self.assertEqual(job["engine"], "wan")
        self.assertEqual(job["mode"], "i2v")
        self.assertEqual(job["template"], str(WAN_TEMPLATE_PATH))
        self.assertEqual(job["aspect"], "horizontal")
        self.assertEqual(job["seed"], 13)
        self.assertEqual(job["seconds"], 5.0)
        self.assertEqual(job["frames"], 81)
        self.assertEqual(job["motion_positive"], "She walks slowly.")
        self.assertEqual(job["motion_negative"], MOTION_NEGATIVE)
        self.assertIsNone(job["last_image_name"])
        files = self.input_files()
        self.assertEqual([path.name for path in files], [job["image_name"]])
        self.assertEqual(files[0].read_bytes(), PNG_BYTES)
        row = self.store.list()[0]
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["model_id"], "wan")
        self.assertEqual(row["prompt"], "She walks slowly.")
        self.assertEqual(row["params"]["engine"], "wan")
        self.assertEqual(row["params"]["mode"], "i2v")
        self.assertEqual(row["params"]["aspect"], "horizontal")
        self.assertEqual(row["params"]["seed"], 13)
        self.assertEqual(row["params"]["frames"], 81)
        self.assertEqual(row["params"]["seconds"], 5.0)

    def test_seconds_6_encola_frames_97_y_hint_ajustado(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/video/generate",
            json={
                "engine": "wan",
                "image_b64": PNG_B64,
                "motion_positive": "She walks slowly.",
                "seconds": 6,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["frames"], 97)
        self.assertIn("ajustado, más lento", data["vram_hint"])
        self.assertEqual(queue.jobs[0]["frames"], 97)

    def test_seconds_8_encola_frames_129_y_hint_oom(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/video/generate",
            json={
                "engine": "wan",
                "image_b64": PNG_B64,
                "motion_positive": "She walks slowly.",
                "seconds": 8,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["frames"], 129)
        self.assertIn("riesgo de OOM en 12 GB; no certificado", data["vram_hint"])
        self.assertEqual(queue.jobs[0]["frames"], 129)

    def test_flf2v_sin_engine_usa_plantilla_flf_y_dos_frames(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/video/generate",
            json={
                "mode": "flf2v",
                "image_b64": PNG_B64,
                "last_image_b64": PNG_B64,
                "motion_positive": "She walks slowly.",
                "seconds": 5,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["frames"], 81)
        self.assertIn("cabe en 12 GB (perfil certificado)", data["vram_hint"])
        job = queue.jobs[0]
        self.assertEqual(job["engine"], "wan")
        self.assertEqual(job["mode"], "flf2v")
        self.assertEqual(job["template"], str(WAN_FLF_TEMPLATE_PATH))
        self.assertEqual(job["frames"], 81)
        files = self.input_files()
        self.assertEqual(len(files), 2)
        self.assertEqual(
            {job["image_name"], job["last_image_name"]},
            {path.name for path in files},
        )
        row = self.store.list()[0]
        self.assertEqual(row["params"]["mode"], "flf2v")
        self.assertEqual(row["params"]["seconds"], 5.0)

    def test_negativo_editable_se_usa_y_se_guarda(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/video/generate",
            json={
                "image_b64": PNG_B64,
                "motion_positive": "She walks slowly.",
                "motion_negative": "custom negative",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(queue.jobs[0]["motion_negative"], "custom negative")
        self.assertEqual(self.store.list()[0]["negative"], "custom negative")

    def test_h3_encola_job_con_dos_frames(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/video/generate",
            json={
                "engine": "h3",
                "image_b64": PNG_B64,
                "last_image_b64": PNG_B64,
                "prompt": "integrated_multimodal_description: test",
                "seed": 2,
            },
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[0]
        self.assertEqual(job["engine"], "h3")
        self.assertEqual(job["template"], str(H3_TEMPLATE_PATH))
        self.assertEqual(job["prompt"], "integrated_multimodal_description: test")
        files = self.input_files()
        self.assertEqual(len(files), 2)
        self.assertEqual(
            {job["image_name"], job["last_image_name"]},
            {path.name for path in files},
        )
        self.assertNotEqual(job["image_name"], job["last_image_name"])
        row = self.store.list()[0]
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["model_id"], "h3")
        self.assertEqual(row["prompt"], "integrated_multimodal_description: test")


class VideoCancelTests(ServerVideoTestCase):
    def payload(self) -> dict:
        return {
            "engine": "wan",
            "image_b64": PNG_B64,
            "motion_positive": "She walks slowly.",
        }

    def test_cancel_video_queued_200_y_delete_queued(self):
        queue = StatusQueue()
        engine = FakeCancelEngine()
        client = self.make_client(queue=queue, engine_factory=lambda: engine)
        job_id = client.post("/api/video/generate", json=self.payload()).json()["job_id"]
        gen_id = queue.jobs[0]["gen_id"]
        record = server_module._JOBS[gen_id]
        self.assertEqual(record["kind"], "video")
        record["engine"] = engine
        record["prompt_id"] = "p1"
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "cancelled"})
        self.assertEqual(engine.deleted, ["p1"])
        self.assertEqual(engine.interrupts, 0)
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(self.store.get(gen_id)["status"], "cancelled")
        self.assertEqual(client.get(f"/api/jobs/{job_id}").json()["status"], "cancelled")

    def test_cancel_video_running_200_e_interrupt(self):
        queue = StatusQueue()
        engine = FakeCancelEngine()
        client = self.make_client(queue=queue, engine_factory=lambda: engine)
        job_id = client.post("/api/video/generate", json=self.payload()).json()["job_id"]
        gen_id = queue.jobs[0]["gen_id"]
        queue.statuses[job_id] = "running"
        record = server_module._JOBS[gen_id]
        record["engine"] = engine
        record["prompt_id"] = "p1"
        record["status"] = "running"
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(engine.deleted, [])
        self.assertEqual(engine.interrupts, 1)
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(self.store.get(gen_id)["status"], "cancelled")

    def test_cancel_video_terminado_409(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        job_id = client.post("/api/video/generate", json=self.payload()).json()["job_id"]
        queue.statuses[job_id] = "done"
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())

    def test_cancel_train_sigue_409(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        gen_id = self.store.add("oc-1", "aiko", "", {}, kind="train")
        job_id = "job-train"
        queue.statuses[job_id] = "running"
        client.app.state.jobs[job_id] = {"kind": "train", "gen_id": gen_id}
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 409)
        self.assertIn("train", response.json()["error"])
        self.assertEqual(self.store.get(gen_id)["status"], "queued")


class VideoQueueIntegrationTests(ServerVideoTestCase):
    def test_flujo_http_completo_con_worker(self):
        transport = FakeVideoTransport(self.config)
        factory = lambda: ComfyEngine(  # noqa: E731
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

        def run_job(job):
            run_video_generation(
                job, config=self.config, store=self.store, engine_factory=factory
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
                "/api/video/generate",
                json={
                    "engine": "wan",
                    "image_b64": PNG_B64,
                    "motion_positive": "She walks slowly.",
                    "seed": 3,
                },
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 5)
            status = client.get(f"/api/jobs/{job_id}").json()
            self.assertEqual(status["status"], "done")
            self.assertEqual(status["outputs"][0]["name"], "clip.mp4")
            media = client.get(status["outputs"][0]["url"])
            self.assertEqual(media.status_code, 200)
            self.assertEqual(media.headers["content-type"], "video/mp4")
            self.assertEqual(media.content, MP4_BYTES)
            gallery = client.get("/api/gallery").json()
            self.assertEqual(gallery["count"], 1)
            self.assertEqual(gallery["items"][0]["kind"], "video")
            self.assertEqual(gallery["items"][0]["urls"], [status["outputs"][0]["url"]])


class VideoMediaTests(ServerVideoTestCase):
    def add_gallery_file(self, gen_id: int, name: str) -> Path:
        directory = self.config.data_dir / "gallery" / str(gen_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(MP4_BYTES)
        return path

    def test_sirve_webm(self):
        gen_id = self.store.add("h3", "p", kind="video")
        self.add_gallery_file(gen_id, "clip.webm")
        response = self.make_client().get(f"/media/{gen_id}/clip.webm")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/webm")
        self.assertEqual(response.content, MP4_BYTES)

    def test_extension_no_soportada_404(self):
        gen_id = self.store.add("wan", "p", kind="video")
        self.add_gallery_file(gen_id, "clip.avi")
        response = self.make_client().get(f"/media/{gen_id}/clip.avi")
        self.assertEqual(response.status_code, 404)

    def test_traversal_video_403(self):
        gen_id = self.store.add("wan", "p", kind="video")
        (self.config.data_dir / "secret.mp4").write_bytes(MP4_BYTES)
        response = self.make_client().get(f"/media/{gen_id}/..%2F..%2Fsecret.mp4")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
