"""Tests CPU de la webapp FastAPI (F3b). Sin red, GPU ni LLM real."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from app import server as server_module
from app.config import EngineConfig
from app.engine import ComfyEngine, EngineError
from app.enhancer import BASE_NEGATIVE, apply_preprompt
from app.formats import DEFAULT_FORMAT, list_image_formats
from app.jobs import JobQueue
from app.params import (
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    SAMPLER_NAMES,
    SCHEDULER_NAMES,
)
from app.registry import DEFAULT_PATH, ModelRegistry
from app.server import create_app, run_generation
from app.store import Store
from app.tags import list_groups

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

    def add_gallery_image(self, gen_id: int, name: str = "ok.png") -> Path:
        directory = self.config.data_dir / "gallery" / str(gen_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        Image.new("RGB", (64, 64), (120, 80, 40)).save(path, format="PNG")
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

    def test_gallery_mas_nueva_primero(self):
        ids = [self.store.add(MODEL_ID, f"1girl {index}") for index in range(3)]
        data = self.make_client().get("/api/gallery").json()
        self.assertEqual(data["count"], 3)
        self.assertEqual([item["id"] for item in data["items"]], list(reversed(ids)))


class LorasRouteTests(ServerTestCase):
    def test_loras_200_con_items_y_familias(self):
        response = self.make_client().get("/api/loras")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"items", "families"})
        self.assertEqual(data["families"], ["wan", "animagine", "h3"])
        self.assertEqual(
            [item["id"] for item in data["items"]],
            [
                "lightx2v-wan-high",
                "lightx2v-wan-low",
                "reika-kurashiki",
                "minimax-h3-fl2v-turbo-4step",
            ],
        )

    def test_loras_filtro_por_familia(self):
        response = self.make_client().get("/api/loras", params={"family": "wan"})
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(
            [item["id"] for item in items],
            ["lightx2v-wan-high", "lightx2v-wan-low"],
        )
        self.assertTrue(all(item["family"] == "wan" for item in items))

    def test_loras_familia_desconocida_vacia(self):
        data = self.make_client().get(
            "/api/loras", params={"family": "no-existe"}
        ).json()
        self.assertEqual(data["items"], [])
        self.assertIn("wan", data["families"])


class ParamsRouteTests(ServerTestCase):
    def test_params_enums_y_defaults(self):
        response = self.make_client().get("/api/params")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["samplers"], list(SAMPLER_NAMES))
        self.assertEqual(data["schedulers"], list(SCHEDULER_NAMES))
        self.assertEqual(data["default_sampler"], DEFAULT_SAMPLER)
        self.assertEqual(data["default_scheduler"], DEFAULT_SCHEDULER)
        self.assertEqual(len(data["samplers"]), 44)
        self.assertEqual(len(data["schedulers"]), 9)
        self.assertEqual(
            set(data), {"samplers", "schedulers", "default_sampler", "default_scheduler"}
        )


class FormatsRouteTests(ServerTestCase):
    def test_formats_11_y_default(self):
        response = self.make_client().get("/api/formats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["default"], DEFAULT_FORMAT)
        self.assertEqual(data["default"], "retrato_plan")
        self.assertEqual(len(data["formats"]), 11)
        self.assertEqual(data["formats"], list_image_formats())
        first = data["formats"][0]
        self.assertEqual(set(first), {"id", "label", "width", "height"})
        self.assertEqual(first["id"], "video_vertical")
        self.assertEqual((first["width"], first["height"]), (432, 768))


class NegativeRouteTests(ServerTestCase):
    def test_default_glossy(self):
        response = self.make_client().get("/api/negative")
        self.assertEqual(response.status_code, 200)
        negative = response.json()["negative"]
        self.assertEqual(negative, apply_preprompt("", "anima", "glossy")[1])
        self.assertTrue(negative.startswith(BASE_NEGATIVE))
        self.assertIn("bad anatomy", negative)

    def test_family_y_preprompt_explicitos(self):
        response = self.make_client().get(
            "/api/negative", params={"preprompt": "anima_default", "family": "anima"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["negative"],
            apply_preprompt("", "anima", "anima_default")[1],
        )

    def test_preprompt_o_familia_invalidos_400(self):
        for params in (
            {"preprompt": "no-existe"},
            {"family": "no-existe"},
        ):
            with self.subTest(params=params):
                response = self.make_client().get("/api/negative", params=params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())


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


class PromptZonesRoutesTests(ServerTestCase):
    def test_zones_200(self):
        response = self.make_client().post(
            "/api/prompt/zones",
            json={"text": "1girl, masterpiece, nsfw, long hair"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"zones", "composed"})
        zones = {item["id"]: item for item in data["zones"]}
        self.assertEqual(
            [item["id"] for item in data["zones"]],
            ["quality", "safety", "subject", "character", "general"],
        )
        self.assertEqual(zones["quality"]["tags"], ["masterpiece"])
        self.assertEqual(zones["safety"]["tags"], ["nsfw"])
        self.assertEqual(zones["subject"]["tags"], ["1girl"])
        self.assertEqual(zones["character"]["tags"], [])
        self.assertEqual(zones["general"]["tags"], ["long hair"])
        self.assertEqual(zones["quality"]["label"], "Calidad/meta")
        self.assertEqual(data["composed"], "masterpiece, nsfw, 1girl, long hair")

    def test_zones_texto_vacio(self):
        response = self.make_client().post("/api/prompt/zones", json={"text": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["composed"], "")
        self.assertEqual(len(response.json()["zones"]), 5)

    def test_zones_sin_text_400(self):
        client = self.make_client()
        for payload in ({}, {"text": 3}, {"text": None}):
            with self.subTest(payload=payload):
                response = client.post("/api/prompt/zones", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_compose_200(self):
        response = self.make_client().post(
            "/api/prompt/compose",
            json={"zones": {"general": ["blue sky"], "subject": ["1girl"]}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "1girl, blue sky"})

    def test_compose_forma_invalida_400(self):
        client = self.make_client()
        for payload in (
            {},
            {"zones": []},
            {"zones": "x"},
            {"zones": {"nope": ["1girl"]}},
            {"zones": {"general": "smile"}},
            {"zones": {"general": [3]}},
        ):
            with self.subTest(payload=payload):
                response = client.post("/api/prompt/compose", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_insert_200_con_y_sin_zona(self):
        client = self.make_client()
        with_zone = client.post(
            "/api/prompt/insert",
            json={"text": "1girl, smile", "tag": "hatsune miku", "zone": "character"},
        )
        self.assertEqual(with_zone.status_code, 200)
        self.assertEqual(with_zone.json(), {"text": "1girl, hatsune miku, smile"})
        auto = client.post(
            "/api/prompt/insert", json={"text": "1girl, smile", "tag": "masterpiece"}
        )
        self.assertEqual(auto.status_code, 200)
        self.assertEqual(auto.json(), {"text": "masterpiece, 1girl, smile"})

    def test_insert_400(self):
        client = self.make_client()
        for payload in (
            {"text": "1girl", "tag": ""},
            {"text": "1girl", "tag": "   "},
            {"text": "1girl"},
            {"tag": "smile"},
            {"text": 3, "tag": "smile"},
            {"text": "1girl", "tag": "smile", "zone": "nope"},
        ):
            with self.subTest(payload=payload):
                response = client.post("/api/prompt/insert", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())


class CapturingLLM:
    """LLM falso que acepta `temperature` por kwarg y captura las llamadas."""

    def __init__(self, output: str = "1girl, smile") -> None:
        self.output = output
        self.calls: list[dict] = []

    def __call__(self, system, user, temperature=None):
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.output


class RecordingQueue:
    """Cola inyectada que solo registra los jobs (no arranca worker)."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def submit(self, job: dict) -> str:
        self.jobs.append(job)
        return f"job-{len(self.jobs)}"


class StatusQueue:
    """Cola inyectada con estados programables por job (sin worker)."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.statuses: dict[str, str] = {}

    def submit(self, job: dict) -> str:
        job_id = f"job-{len(self.jobs) + 1}"
        self.jobs.append(job)
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


class FakeRunEngine(FakeCancelEngine):
    """Engine mínimo para `run_generation`: submit/wait/outputs inmediatos."""

    def __init__(self, output_path: Path) -> None:
        super().__init__()
        self.client_id = "run-cid"
        self.output_path = output_path

    def submit(self, graph: dict) -> str:
        return "p1"

    def wait(self, prompt_id: str) -> dict:
        return {"status": {"status_str": "success"}, "outputs": {}}

    def outputs(self, entry: dict, *, expected_ext=("png",)) -> list[Path]:
        return [self.output_path]


class CancelThenFailEngine(FakeRunEngine):
    """Engine falso: marca el job como cancelado y falla en submit."""

    def __init__(self, output_path: Path, on_submit) -> None:
        super().__init__(output_path)
        self.on_submit = on_submit

    def submit(self, graph: dict) -> str:
        self.on_submit()
        raise EngineError("prompt interrumpido por cancelacion")


class FakeTracker:
    """Tracker falso con snapshot y percent fijos."""

    def __init__(self, snapshot: dict | None = None, percent: float | None = 50.0):
        self._snapshot = {"step": 3, "total": 6, "node": "9", "state": "running"}
        if snapshot:
            self._snapshot.update(snapshot)
        self._percent = percent

    def snapshot(self) -> dict:
        return dict(self._snapshot)

    def percent(self) -> float | None:
        return self._percent


class BlockingWs:
    """WS falso que se queda abierto hasta que el tracker se cancela."""

    async def __aenter__(self):
        await asyncio.Event().wait()
        raise AssertionError("inalcanzable")

    async def __aexit__(self, exc_type, exc, tb):
        return False


def blocking_ws_factory(url: str) -> BlockingWs:
    return BlockingWs()


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


class EnhanceStrengthRouteTests(ServerTestCase):
    def test_default_balanceado_temperature_0_7_sin_instruccion(self):
        llm = CapturingLLM()
        response = self.make_client(llm=llm).post(
            "/api/enhance", json={"text": "1girl, smile"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.calls[0]["temperature"], 0.7)
        self.assertNotIn("instruccion:", llm.calls[0]["user"])

    def test_fiel_pasa_instruccion_y_temperature_0_4(self):
        llm = CapturingLLM()
        response = self.make_client(llm=llm).post(
            "/api/enhance", json={"text": "1girl, smile", "strength": "fiel"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.calls[0]["temperature"], 0.4)
        self.assertIn("instruccion:", llm.calls[0]["user"])

    def test_creativo_temperature_1_0(self):
        llm = CapturingLLM()
        response = self.make_client(llm=llm).post(
            "/api/enhance", json={"text": "1girl, smile", "strength": "creativo"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.calls[0]["temperature"], 1.0)

    def test_strength_invalido_400_sin_llamar_al_llm(self):
        for strength in ("loco", "", 5, ["fiel"], {"fiel": True}):
            with self.subTest(strength=strength):
                llm = CapturingLLM()
                response = self.make_client(llm=llm).post(
                    "/api/enhance", json={"text": "1girl", "strength": strength}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
                self.assertEqual(llm.calls, [])


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


class GenerateSizeTests(ServerTestCase):
    def payload(self, **overrides) -> dict:
        data = {
            "model_id": MODEL_ID,
            "prompt": "1girl, smile",
            "preprompt": "ninguno",
            "params": {"seed": 1},
        }
        data.update(overrides)
        return data

    def test_size_preset_manda_sobre_manual(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/generate",
            json=self.payload(size="cuadro_hd", width=64, height=64),
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[0]
        self.assertEqual(job["params"]["width"], 1024)
        self.assertEqual(job["params"]["height"], 1024)
        row = self.store.list()[0]
        self.assertEqual(row["params"]["width"], 1024)
        self.assertEqual(row["params"]["height"], 1024)

    def test_manual_valido_se_mezcla_con_params(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/generate", json=self.payload(width=768, height=1344)
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[0]
        self.assertEqual(job["params"]["width"], 768)
        self.assertEqual(job["params"]["height"], 1344)
        self.assertEqual(job["params"]["seed"], 1)

    def test_size_desconocido_o_no_str_400(self):
        for size in ("no-existe", 5, ["cuadro_hd"], {"id": "cuadro_hd"}):
            with self.subTest(size=size):
                response = self.make_client().post(
                    "/api/generate", json=self.payload(size=size)
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_medidas_manuales_invalidas_400(self):
        for width, height in (
            (63, 768),
            (768, 4097),
            (100, 768),
            (768, 63),
            ("abc", 768),
            (768.5, 768),
            (0, 768),
        ):
            with self.subTest(width=width, height=height):
                response = self.make_client().post(
                    "/api/generate", json=self.payload(width=width, height=height)
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_medidas_manuales_en_los_limites_ok(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/generate", json=self.payload(width=64, height=4096)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(queue.jobs[0]["params"]["width"], 64)
        self.assertEqual(queue.jobs[0]["params"]["height"], 4096)


class GenerateEngineParamsValidationTests(ServerTestCase):
    def payload(self, params: dict) -> dict:
        return {
            "model_id": MODEL_ID,
            "prompt": "1girl",
            "preprompt": "ninguno",
            "params": params,
        }

    def test_sampler_invalido_400(self):
        for sampler in ("nope", "Euler", 5, True):
            with self.subTest(sampler=sampler):
                response = self.make_client().post(
                    "/api/generate", json=self.payload({"sampler_name": sampler})
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_scheduler_invalido_400(self):
        for scheduler in ("nope", "SGM_UNIFORM", 5, True):
            with self.subTest(scheduler=scheduler):
                response = self.make_client().post(
                    "/api/generate", json=self.payload({"scheduler": scheduler})
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_sampler_y_scheduler_validos_pasan(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/generate",
            json=self.payload(
                {
                    "seed": 1,
                    "sampler_name": "dpmpp_2m",
                    "scheduler": "karras",
                }
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(queue.jobs[0]["params"]["sampler_name"], "dpmpp_2m")
        self.assertEqual(queue.jobs[0]["params"]["scheduler"], "karras")

    def test_sin_sampler_ni_scheduler_pasa(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/generate", json=self.payload({"seed": 1})
        )
        self.assertEqual(response.status_code, 200)


class GenerateLorasTests(ServerTestCase):
    REIKA_FILE = "Reika Kurashiki_1.safetensors"

    def payload(self, **overrides) -> dict:
        data = {
            "model_id": MODEL_ID,
            "prompt": "1girl, smile",
            "preprompt": "ninguno",
            "params": {"seed": 1},
        }
        data.update(overrides)
        return data

    def test_generate_con_loras_normaliza_y_guarda(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/generate",
            json=self.payload(loras=[{"id": "reika-kurashiki", "weight": 0.8}]),
        )
        self.assertEqual(response.status_code, 200)
        expected = [
            {
                "id": "reika-kurashiki",
                "file": self.REIKA_FILE,
                "weight": 0.8,
            }
        ]
        self.assertEqual(queue.jobs[0]["loras"], expected)
        self.assertEqual(self.store.list()[0]["params"]["loras"], expected)

    def test_generate_sin_loras_guarda_lista_vacia(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/generate", json=self.payload()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(queue.jobs[0]["loras"], [])
        self.assertEqual(self.store.list()[0]["params"]["loras"], [])

    def test_generate_lora_sin_weight_usa_el_default(self):
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/generate", json=self.payload(loras=[{"id": "lightx2v-wan-high"}])
        )
        self.assertEqual(response.status_code, 200)
        item = queue.jobs[0]["loras"][0]
        self.assertEqual(item["weight"], 1.0)
        self.assertTrue(item["file"].endswith(".safetensors"))

    def test_generate_lora_invalida_400(self):
        for loras in (
            [{"id": "no-existe"}],
            [{"id": "reika-kurashiki", "weight": 3.0}],
            [{"id": "reika-kurashiki", "weight": True}],
            [{}],
            ["reika-kurashiki"],
            {"id": "reika-kurashiki"},
            "reika-kurashiki",
        ):
            with self.subTest(loras=loras):
                response = self.make_client().post(
                    "/api/generate", json=self.payload(loras=loras)
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(self.store.count(), 0)


class PrepromptsCustomRoutesTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(
            os.environ, {"WAIFU_DATA_DIR": str(self.config.data_dir)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def payload(self, **overrides) -> dict:
        data = {
            "model_id": MODEL_ID,
            "prompt": "1girl, smile",
            "preprompt": "ninguno",
            "params": {"seed": 1},
        }
        data.update(overrides)
        return data

    def test_post_get_delete_200(self):
        client = self.make_client()
        created = client.post(
            "/api/preprompts/custom",
            json={
                "name": "mi_estilo",
                "positive": "cinematic lighting",
                "negative": "blurry",
            },
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json(), {"name": "mi_estilo"})
        data = client.get("/api/preprompts", params={"family": "anima"}).json()
        self.assertEqual(data["family"], "anima")
        self.assertEqual(data["default"], "glossy")
        self.assertIn("glossy", data["names"])
        self.assertIn("mi_estilo", data["names"])
        self.assertEqual(data["custom"], ["mi_estilo"])
        negative = client.get(
            "/api/negative", params={"preprompt": "mi_estilo"}
        ).json()["negative"]
        self.assertTrue(negative.startswith(BASE_NEGATIVE))
        self.assertIn("blurry", negative)
        deleted = client.delete("/api/preprompts/custom/mi_estilo")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json(), {"deleted": True})
        after = client.get("/api/preprompts").json()
        self.assertEqual(after["custom"], [])
        self.assertNotIn("mi_estilo", after["names"])

    def test_delete_desconocido_404(self):
        response = self.make_client().delete("/api/preprompts/custom/no-existe")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_almacen_corrupto_devuelve_custom_vacio_y_certificados(self):
        (self.config.data_dir / "preprompts.json").write_text(
            "{no-json", encoding="utf-8"
        )
        response = self.make_client().get(
            "/api/preprompts", params={"family": "anima"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["custom"], [])
        self.assertEqual(data["default"], "glossy")
        self.assertIn("glossy", data["names"])
        self.assertIn("anima_default", data["names"])

    def test_post_duplicado_y_certificado_400(self):
        client = self.make_client()
        self.assertEqual(
            client.post(
                "/api/preprompts/custom",
                json={"name": "mi_estilo", "positive": "uno"},
            ).status_code,
            200,
        )
        duplicate = client.post(
            "/api/preprompts/custom",
            json={"name": "mi_estilo", "positive": "dos"},
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("error", duplicate.json())
        certified = client.post(
            "/api/preprompts/custom",
            json={"name": "glossy", "positive": "hostil"},
        )
        self.assertEqual(certified.status_code, 400)
        self.assertIn("error", certified.json())

    def test_post_validacion_400(self):
        client = self.make_client()
        for payload in (
            {},
            {"name": "mal nombre", "positive": "x"},
            {"name": "MAL", "positive": "x"},
            {"name": "ok", "positive": "  "},
            {"name": "ok"},
            {"name": "ok", "positive": 5},
            {"name": "ok", "positive": "x", "negative": 5},
        ):
            with self.subTest(payload=payload):
                response = client.post("/api/preprompts/custom", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(
            client.get("/api/preprompts").json()["custom"], []
        )

    def test_generate_con_preprompt_custom_ok(self):
        queue = RecordingQueue()
        client = self.make_client(queue=queue)
        client.post(
            "/api/preprompts/custom",
            json={"name": "mi_estilo", "positive": "cinematic lighting"},
        )
        response = client.post(
            "/api/generate", json=self.payload(preprompt="mi_estilo")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(queue.jobs[0]["preprompt"], "mi_estilo")
        self.assertEqual(self.store.list()[0]["params"]["preprompt"], "mi_estilo")

    def test_generate_con_preprompt_desconocido_400(self):
        response = self.make_client().post(
            "/api/generate", json=self.payload(preprompt="no-existe")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertEqual(self.store.count(), 0)

    def test_generate_con_preprompt_no_str_400(self):
        response = self.make_client().post(
            "/api/generate", json=self.payload(preprompt=["glossy"])
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertEqual(self.store.count(), 0)


class JobProgressTests(ServerTestCase):
    def payload(self) -> dict:
        return {
            "model_id": MODEL_ID,
            "prompt": "1girl, smile",
            "preprompt": "ninguno",
            "params": {"seed": 1},
        }

    def test_job_status_sin_tracker_devuelve_progress_nulo(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        job_id = client.post("/api/generate", json=self.payload()).json()["job_id"]
        status = client.get(f"/api/jobs/{job_id}").json()
        self.assertIn("progress", status)
        self.assertEqual(
            status["progress"],
            {"step": None, "total": None, "percent": None, "node": None, "state": None},
        )

    def test_job_status_con_tracker_publica_snapshot_y_percent(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        job_id = client.post("/api/generate", json=self.payload()).json()["job_id"]
        gen_id = queue.jobs[0]["gen_id"]
        server_module._JOBS[gen_id]["tracker"] = FakeTracker()
        server_module._JOBS[gen_id]["status"] = "running"
        queue.statuses[job_id] = "running"
        status = client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(status["status"], "running")
        self.assertEqual(
            status["progress"],
            {"step": 3, "total": 6, "percent": 50.0, "node": "9", "state": "running"},
        )


class CancelRouteTests(ServerTestCase):
    def payload(self) -> dict:
        return {
            "model_id": MODEL_ID,
            "prompt": "1girl, smile",
            "preprompt": "ninguno",
            "params": {"seed": 1},
        }

    def test_cancel_job_desconocido_404(self):
        client = self.make_client(queue=StatusQueue())
        response = client.post("/api/jobs/no-existe/cancel")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_cancel_job_terminado_409(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        job_id = client.post("/api/generate", json=self.payload()).json()["job_id"]
        queue.statuses[job_id] = "done"
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())
        self.assertEqual(self.store.list()[0]["status"], "queued")

    def test_cancel_queued_borra_del_engine_y_marca_store(self):
        queue = StatusQueue()
        engine = FakeCancelEngine()
        client = self.make_client(queue=queue, engine_factory=lambda: engine)
        job_id = client.post("/api/generate", json=self.payload()).json()["job_id"]
        gen_id = queue.jobs[0]["gen_id"]
        record = server_module._JOBS[gen_id]
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

    def test_cancel_video_queued_borra_del_engine_y_marca_store(self):
        queue = StatusQueue()
        engine = FakeCancelEngine()
        client = self.make_client(queue=queue, engine_factory=lambda: engine)
        gen_id = self.store.add("wan", "motion", "", kind="video")
        job_id = "job-1"
        queue.statuses[job_id] = "queued"
        client.app.state.jobs[job_id] = {"kind": "video", "gen_id": gen_id}
        server_module._JOBS[gen_id] = {
            "prompt_id": "p1",
            "tracker": None,
            "status": "queued",
            "engine": engine,
            "kind": "video",
        }
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "cancelled"})
        self.assertEqual(engine.deleted, ["p1"])
        self.assertEqual(engine.interrupts, 0)
        self.assertEqual(server_module._JOBS[gen_id]["status"], "cancelled")
        self.assertEqual(self.store.get(gen_id)["status"], "cancelled")

    def test_cancel_video_por_store_marca_cancelled(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        gen_id = self.store.add("wan", "motion", "", kind="video")
        job_id = "job-1"
        queue.statuses[job_id] = "running"
        client.app.state.jobs[job_id] = {"gen_id": gen_id}
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "cancelled"})
        self.assertEqual(self.store.get(gen_id)["status"], "cancelled")

    def test_cancel_running_interrumpe_el_engine(self):
        queue = StatusQueue()
        engine = FakeCancelEngine()
        client = self.make_client(queue=queue, engine_factory=lambda: engine)
        job_id = client.post("/api/generate", json=self.payload()).json()["job_id"]
        gen_id = queue.jobs[0]["gen_id"]
        queue.statuses[job_id] = "running"
        record = server_module._JOBS[gen_id]
        record["engine"] = engine
        record["prompt_id"] = "p1"
        record["status"] = "running"
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "cancelled"})
        self.assertEqual(engine.deleted, [])
        self.assertEqual(engine.interrupts, 1)
        self.assertEqual(self.store.get(gen_id)["status"], "cancelled")


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
        self.assertEqual(graph["5"]["inputs"]["text"], BASE_NEGATIVE)

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

    def test_negativo_compuesto_base_mas_preprompt_en_el_grafo(self):
        transport = FakeTransport(self.config)
        job = self.make_job(preprompt="glossy")
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        negative = transport.submits[0]["prompt"]["5"]["inputs"]["text"]
        self.assertIn("child", negative)
        self.assertIn("mosaic censoring", negative)
        self.assertIn("bar censor", negative)
        self.assertIn("bad anatomy", negative)
        tags = [tag.strip().lower() for tag in negative.split(",")]
        self.assertEqual(len(tags), len(set(tags)))

    def test_negativo_de_usuario_se_suma_al_compuesto_sin_duplicar(self):
        transport = FakeTransport(self.config)
        job = self.make_job(
            preprompt="glossy", negative="Child, user tag, LOW QUALITY"
        )
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        negative = transport.submits[0]["prompt"]["5"]["inputs"]["text"]
        tags = [tag.strip().lower() for tag in negative.split(",")]
        self.assertEqual(tags.count("child"), 1)
        self.assertEqual(tags.count("low quality"), 1)
        self.assertIn("user tag", tags)
        self.assertIn("mosaic censoring", tags)
        self.assertEqual(negative.split(",")[1].strip(), "user tag")

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

    def test_lora_en_el_grafo(self):
        transport = FakeTransport(self.config)
        job = self.make_job(
            loras=[{"id": "reika-kurashiki", "weight": 0.8}]
        )
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        self.assertEqual(self.store.get(job["gen_id"])["status"], "done")
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["lora_1"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(
            graph["lora_1"]["inputs"],
            {
                "model": ["1", 0],
                "lora_name": "Reika Kurashiki_1.safetensors",
                "strength_model": 0.8,
            },
        )
        self.assertEqual(graph["7"]["inputs"]["model"], ["lora_1", 0])

    def test_dos_loras_en_cadena_en_el_grafo(self):
        transport = FakeTransport(self.config)
        job = self.make_job(
            loras=[
                {"id": "lightx2v-wan-high", "weight": 0.5},
                {"id": "lightx2v-wan-low", "weight": 1.0},
            ]
        )
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["lora_1"]["inputs"]["model"], ["1", 0])
        self.assertEqual(graph["lora_2"]["inputs"]["model"], ["lora_1", 0])
        self.assertEqual(graph["7"]["inputs"]["model"], ["lora_2", 0])


class RunGenerationProgressTests(ServerTestCase):
    def make_job(self) -> dict:
        gen_id = self.store.add(MODEL_ID, "1girl, smile", "", {"seed": 7})
        return {
            "gen_id": gen_id,
            "model_id": MODEL_ID,
            "prompt": "1girl, smile",
            "negative": "",
            "preprompt": "ninguno",
            "params": {"seed": 7, "steps": 5, "width": 320, "height": 576},
            "ref_image": None,
            "strength": None,
        }

    def test_registra_engine_prompt_id_y_tracker(self):
        output = self.root / "fake.png"
        output.write_bytes(PNG_BYTES)
        engine = FakeRunEngine(output)
        job = self.make_job()
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=lambda: engine,
            ws_factory=blocking_ws_factory,
        )
        record = server_module._JOBS[job["gen_id"]]
        self.assertIs(record["engine"], engine)
        self.assertEqual(record["prompt_id"], "p1")
        self.assertEqual(record["status"], "done")
        tracker = record["tracker"]
        self.assertIsNotNone(tracker)
        self.assertFalse(tracker._thread is not None and tracker._thread.is_alive())
        self.assertEqual(self.store.get(job["gen_id"])["status"], "done")
        self.assertTrue(
            (self.config.data_dir / "gallery" / str(job["gen_id"]) / "fake.png").is_file()
        )

    def test_job_cancelado_antes_del_worker_no_ejecuta(self):
        output = self.root / "fake.png"
        output.write_bytes(PNG_BYTES)
        engine = FakeRunEngine(output)
        job = self.make_job()
        server_module._JOBS[job["gen_id"]] = {
            "prompt_id": None,
            "tracker": None,
            "status": "cancelled",
            "engine": None,
        }
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=lambda: engine,
            ws_factory=blocking_ws_factory,
        )
        self.assertEqual(server_module._JOBS[job["gen_id"]]["status"], "cancelled")
        self.assertEqual(engine.deleted, [])
        self.assertEqual(job["outputs"], [])
        self.assertFalse(
            (self.config.data_dir / "gallery" / str(job["gen_id"]) / "fake.png").is_file()
        )

    def test_fallo_tras_cancelar_conserva_cancelled(self):
        job = self.make_job()
        gen_id = job["gen_id"]
        engine = CancelThenFailEngine(
            self.root / "fake.png",
            lambda: server_module._JOBS[gen_id].update(status="cancelled"),
        )
        run_generation(
            job,
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=lambda: engine,
            ws_factory=blocking_ws_factory,
        )
        self.assertEqual(server_module._JOBS[gen_id]["status"], "cancelled")
        self.assertEqual(self.store.get(gen_id)["status"], "cancelled")
        self.assertIsNone(job["error"])
        self.assertEqual(job["outputs"], [])


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


class GalleryCapTests(ServerTestCase):
    def test_cap_24_manteniendo_offset(self):
        for index in range(30):
            self.store.add(MODEL_ID, f"1girl {index}")
        client = self.make_client()
        page1 = client.get("/api/gallery", params={"limit": 100}).json()
        self.assertEqual(page1["count"], 30)
        self.assertEqual(len(page1["items"]), 24)
        page2 = client.get("/api/gallery", params={"limit": 24, "offset": 24}).json()
        self.assertEqual(len(page2["items"]), 6)
        self.assertEqual(page2["count"], 30)
        self.assertTrue(
            set(item["id"] for item in page1["items"]).isdisjoint(
                item["id"] for item in page2["items"]
            )
        )

    def test_limit_minimo_1(self):
        self.store.add(MODEL_ID, "1girl")
        data = self.make_client().get("/api/gallery", params={"limit": 0}).json()
        self.assertEqual(len(data["items"]), 1)


class TagsRoutesTests(ServerTestCase):
    def test_groups(self):
        response = self.make_client().get("/api/tags/groups")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"groups": list_groups()})
        self.assertEqual(len(response.json()["groups"]), 10)

    def test_por_grupo_y_grupo_desconocido(self):
        client = self.make_client()
        response = client.get("/api/tags", params={"group": "hair"})
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertTrue(items)
        self.assertTrue(all(item["group"] == "hair" for item in items))
        bad = client.get("/api/tags", params={"group": "nope"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("error", bad.json())

    def test_busqueda_y_filtros_combinados(self):
        client = self.make_client()
        items = client.get("/api/tags", params={"q": "LONG HAIR"}).json()["items"]
        self.assertIn("long hair", [item["tag"] for item in items])
        combined = client.get(
            "/api/tags", params={"group": "hair", "q": "coleta"}
        ).json()["items"]
        self.assertTrue(combined)
        self.assertTrue(all(item["group"] == "hair" for item in combined))

    def test_sin_filtro_primeros_200_y_limit(self):
        client = self.make_client()
        data = client.get("/api/tags").json()
        self.assertEqual(len(data["items"]), 200)
        self.assertEqual(
            data["items"][0],
            {"tag": "long hair", "label": "Cabello largo", "group": "hair"},
        )
        limited = client.get("/api/tags", params={"limit": 0}).json()
        self.assertEqual(len(limited["items"]), 1)


class CharactersRoutesTests(ServerTestCase):
    def test_crud(self):
        client = self.make_client()
        created = client.post(
            "/api/characters", json={"name": "Aiko", "tags": ["long hair", "smile"]}
        )
        self.assertEqual(created.status_code, 200)
        char_id = created.json()["id"]
        listing = client.get("/api/characters")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)
        self.assertEqual(listing.json()[0]["name"], "Aiko")
        got = client.get(f"/api/characters/{char_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["tags"], ["long hair", "smile"])
        updated = client.put(
            f"/api/characters/{char_id}", json={"name": "Mika", "rating": "nsfw"}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Mika")
        self.assertEqual(updated.json()["rating"], "nsfw")
        deleted = client.delete(f"/api/characters/{char_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(client.get(f"/api/characters/{char_id}").status_code, 404)

    def test_validacion_400(self):
        client = self.make_client()
        for payload in (
            {"name": "", "tags": []},
            {"name": "Aiko", "tags": "long hair"},
            {"name": "Aiko", "tags": [], "preprompt": "inventado"},
            {"name": "Aiko", "tags": [], "rating": "explicit"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    client.post("/api/characters", json=payload).status_code, 400
                )
        client.post("/api/characters", json={"name": "Aiko", "tags": []})
        duplicate = client.post("/api/characters", json={"name": "Aiko", "tags": []})
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("error", duplicate.json())

    def test_404(self):
        client = self.make_client()
        self.assertEqual(client.get("/api/characters/99").status_code, 404)
        self.assertEqual(
            client.put("/api/characters/99", json={"notes": "x"}).status_code, 404
        )
        self.assertEqual(client.delete("/api/characters/99").status_code, 404)
        self.assertEqual(client.get("/api/characters/99/refs").status_code, 404)
        self.assertEqual(
            client.delete("/api/characters/99/refs/1").status_code, 404
        )


class CharacterRefsRoutesTests(ServerTestCase):
    def add_character(self, client) -> int:
        return client.post(
            "/api/characters", json={"name": "Aiko", "tags": []}
        ).json()["id"]

    def test_flujo_refs_y_media(self):
        client = self.make_client()
        char_id = self.add_character(client)
        gen_id = self.store.add(MODEL_ID, "1girl, smile")
        self.add_gallery_png(gen_id)
        self.store.update(gen_id, status="done", outputs=["ok.png"])
        response = client.post(
            f"/api/characters/{char_id}/refs", json={"gen_id": gen_id}
        )
        self.assertEqual(response.status_code, 200)
        relpath = response.json()["relpath"]
        target = self.config.data_dir / "characters" / relpath
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), PNG_BYTES)
        refs = client.get(f"/api/characters/{char_id}/refs")
        self.assertEqual(refs.status_code, 200)
        self.assertEqual(len(refs.json()), 1)
        ref = refs.json()[0]
        self.assertEqual(
            ref["url"], f"/media/characters/{char_id}/{Path(relpath).name}"
        )
        media = client.get(ref["url"])
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media.headers["content-type"], "image/png")
        self.assertEqual(media.content, PNG_BYTES)
        deleted = client.delete(f"/api/characters/{char_id}/refs/{ref['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(client.get(f"/api/characters/{char_id}/refs").json(), [])
        self.assertEqual(client.get(ref["url"]).status_code, 404)
        self.assertFalse(target.exists())

    def test_refs_404_y_400(self):
        client = self.make_client()
        char_id = self.add_character(client)
        self.assertEqual(
            client.post(
                f"/api/characters/{char_id}/refs", json={"gen_id": 999}
            ).status_code,
            404,
        )
        empty_gen = self.store.add(MODEL_ID, "1girl")
        self.assertEqual(
            client.post(
                f"/api/characters/{char_id}/refs", json={"gen_id": empty_gen}
            ).status_code,
            404,
        )
        no_file = self.store.add(MODEL_ID, "1girl")
        self.store.update(no_file, status="done", outputs=["ghost.png"])
        self.assertEqual(
            client.post(
                f"/api/characters/{char_id}/refs", json={"gen_id": no_file}
            ).status_code,
            404,
        )
        self.assertEqual(
            client.post(f"/api/characters/{char_id}/refs", json={}).status_code, 400
        )
        self.assertEqual(
            client.post("/api/characters/99/refs", json={"gen_id": 1}).status_code,
            404,
        )

    def test_delete_ref_desconocida_404(self):
        client = self.make_client()
        char_id = self.add_character(client)
        self.assertEqual(
            client.delete(f"/api/characters/{char_id}/refs/999").status_code, 404
        )

    def test_delete_oc_borra_carpeta_refs(self):
        client = self.make_client()
        char_id = self.add_character(client)
        gen_id = self.store.add(MODEL_ID, "1girl")
        self.add_gallery_png(gen_id)
        self.store.update(gen_id, status="done", outputs=["ok.png"])
        client.post(f"/api/characters/{char_id}/refs", json={"gen_id": gen_id})
        directory = self.config.data_dir / "characters" / str(char_id)
        self.assertTrue(directory.is_dir())
        self.assertEqual(client.delete(f"/api/characters/{char_id}").status_code, 200)
        self.assertFalse(directory.exists())


class CharacterSheetRoutesTests(ServerTestCase):
    def add_character(self, client, name: str = "Aiko") -> int:
        return client.post(
            "/api/characters", json={"name": name, "tags": []}
        ).json()["id"]

    def add_ref(self, client, char_id: int) -> str:
        gen_id = self.store.add(MODEL_ID, "1girl, smile")
        self.add_gallery_image(gen_id)
        self.store.update(gen_id, status="done", outputs=["ok.png"])
        return client.post(
            f"/api/characters/{char_id}/refs", json={"gen_id": gen_id}
        ).json()["relpath"]

    def test_404_oc_inexistente(self):
        client = self.make_client()
        self.assertEqual(
            client.post("/api/characters/99/sheet", json={}).status_code, 404
        )

    def test_400_con_menos_de_dos_refs(self):
        client = self.make_client()
        char_id = self.add_character(client)
        self.assertEqual(
            client.post(f"/api/characters/{char_id}/sheet", json={}).status_code,
            400,
        )
        self.add_ref(client, char_id)
        response = client.post(f"/api/characters/{char_id}/sheet", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_200_crea_y_registra_hoja(self):
        client = self.make_client()
        char_id = self.add_character(client)
        for _ in range(3):
            self.add_ref(client, char_id)
        before = client.get(f"/api/characters/{char_id}/refs").json()
        response = client.post(f"/api/characters/{char_id}/sheet", json={})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"relpath", "url"})
        target = self.config.data_dir / "characters" / data["relpath"]
        self.assertTrue(target.is_file())
        with Image.open(target) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (512, 768))
        self.assertEqual(
            data["url"],
            f"/media/characters/{char_id}/{Path(data['relpath']).name}",
        )
        media = client.get(data["url"])
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media.headers["content-type"], "image/png")
        refs = client.get(f"/api/characters/{char_id}/refs").json()
        self.assertEqual(len(refs), len(before) + 1)
        self.assertEqual(refs[-1]["relpath"], data["relpath"])
        self.assertEqual(refs[-1]["url"], data["url"])

    def test_sin_body_usa_todas_las_refs(self):
        client = self.make_client()
        char_id = self.add_character(client)
        self.add_ref(client, char_id)
        self.add_ref(client, char_id)
        response = client.post(f"/api/characters/{char_id}/sheet")
        self.assertEqual(response.status_code, 200)
        self.assertIn("relpath", response.json())

    def test_ref_ids_filtra_y_valida(self):
        client = self.make_client()
        char_id = self.add_character(client)
        self.add_ref(client, char_id)
        self.add_ref(client, char_id)
        refs = client.get(f"/api/characters/{char_id}/refs").json()
        one = client.post(
            f"/api/characters/{char_id}/sheet", json={"ref_ids": [refs[0]["id"]]}
        )
        self.assertEqual(one.status_code, 400)
        both = client.post(
            f"/api/characters/{char_id}/sheet",
            json={"ref_ids": [ref["id"] for ref in refs]},
        )
        self.assertEqual(both.status_code, 200)
        self.assertEqual(
            client.post(
                f"/api/characters/{char_id}/sheet", json={"ref_ids": "x"}
            ).status_code,
            400,
        )
        self.assertEqual(
            client.post(
                f"/api/characters/{char_id}/sheet", json={"ref_ids": [999, 998]}
            ).status_code,
            400,
        )

    def test_hoja_no_deja_huerfanos(self):
        client = self.make_client()
        char_id = self.add_character(client)
        for _ in range(3):
            self.add_ref(client, char_id)
        response = client.post(f"/api/characters/{char_id}/sheet", json={})
        self.assertEqual(response.status_code, 200)
        directory = self.config.data_dir / "characters" / str(char_id)
        on_disk = {path.name for path in directory.iterdir() if path.is_file()}
        refs = client.get(f"/api/characters/{char_id}/refs").json()
        registered = {Path(ref["relpath"]).name for ref in refs}
        self.assertEqual(on_disk, registered)
        self.assertEqual(len(on_disk), 4)


class CharacterTrainRoutesTests(ServerTestCase):
    def add_character(self, client, name: str = "Aiko") -> int:
        return client.post(
            "/api/characters", json={"name": name, "tags": ["long hair", "smile"]}
        ).json()["id"]

    def test_oc_inexistente_404(self):
        response = self.make_client().post(
            "/api/characters/999/train", json={"gen_ids": list(range(10))}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_gen_ids_invalidos_400(self):
        client = self.make_client()
        char_id = self.add_character(client)
        for gen_ids in (
            None,
            "x",
            10,
            list(range(9)),
            list(range(51)),
            [0, True, *range(2, 10)],
            [0, "1", *range(2, 10)],
        ):
            with self.subTest(gen_ids=gen_ids):
                response = client.post(
                    f"/api/characters/{char_id}/train", json={"gen_ids": gen_ids}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(self.store.count(), 0)

    def test_rank_epochs_trigger_invalidos_400(self):
        client = self.make_client()
        char_id = self.add_character(client)
        for payload in (
            {"gen_ids": list(range(10)), "rank": 0},
            {"gen_ids": list(range(10)), "rank": True},
            {"gen_ids": list(range(10)), "rank": "8"},
            {"gen_ids": list(range(10)), "epochs": -1},
            {"gen_ids": list(range(10)), "epochs": "x"},
            {"gen_ids": list(range(10)), "trigger": "  "},
            {"gen_ids": list(range(10)), "trigger": 5},
        ):
            with self.subTest(payload=payload):
                response = client.post(
                    f"/api/characters/{char_id}/train", json=payload
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(self.store.count(), 0)

    def test_encola_job_train_con_params(self):
        queue = RecordingQueue()
        client = self.make_client(queue=queue)
        char_id = self.add_character(client)
        gen_ids = list(range(10))
        response = client.post(
            f"/api/characters/{char_id}/train",
            json={"gen_ids": gen_ids, "rank": 8, "epochs": 2, "trigger": "aiko"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"job_id": "job-1"})
        job = queue.jobs[0]
        self.assertEqual(job["kind"], "train")
        self.assertEqual(job["character_id"], char_id)
        self.assertEqual(job["gen_ids"], gen_ids)
        self.assertEqual(job["rank"], 8)
        self.assertEqual(job["epochs"], 2)
        self.assertEqual(job["trigger"], "aiko")
        self.assertEqual(job["char"]["name"], "Aiko")
        row = self.store.list()[0]
        self.assertEqual(row["kind"], "train")
        self.assertEqual(row["model_id"], f"oc-{char_id}")
        self.assertEqual(row["prompt"], "aiko")
        self.assertEqual(row["params"]["gen_ids"], gen_ids)
        self.assertEqual(row["params"]["rank"], 8)
        record = server_module._JOBS[job["gen_id"]]
        self.assertEqual(record["kind"], "train")
        self.assertEqual(record["status"], "queued")

    def test_defaults_y_prompt_del_nombre(self):
        queue = RecordingQueue()
        client = self.make_client(queue=queue)
        char_id = self.add_character(client)
        response = client.post(
            f"/api/characters/{char_id}/train", json={"gen_ids": list(range(10))}
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[0]
        self.assertEqual(job["rank"], 16)
        self.assertEqual(job["epochs"], 10)
        self.assertIsNone(job["trigger"])
        self.assertEqual(self.store.list()[0]["prompt"], "Aiko")

    def test_job_status_train_progress_nulo_y_outputs(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        char_id = self.add_character(client)
        job_id = client.post(
            f"/api/characters/{char_id}/train", json={"gen_ids": list(range(10))}
        ).json()["job_id"]
        status = client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(status["status"], "queued")
        self.assertEqual(status["outputs"], [])
        self.assertIsNone(status["error"])
        self.assertEqual(
            status["progress"],
            {"step": None, "total": None, "percent": None, "node": None, "state": None},
        )

    def test_cancel_train_409(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        char_id = self.add_character(client)
        job_id = client.post(
            f"/api/characters/{char_id}/train", json={"gen_ids": list(range(10))}
        ).json()["job_id"]
        queue.statuses[job_id] = "running"
        response = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 409)
        self.assertIn("train", response.json()["error"])
        gen_id = queue.jobs[0]["gen_id"]
        self.assertEqual(self.store.get(gen_id)["status"], "queued")


class RunTrainingJobTests(ServerTestCase):
    def make_job(self, **overrides) -> dict:
        gen_id = self.store.add("oc-1", "aiko", "", {"character_id": 1}, kind="train")
        job = {
            "kind": "train",
            "gen_id": gen_id,
            "char": {"id": 1, "name": "Aiko", "tags": ["smile"]},
            "character_id": 1,
            "gen_ids": list(range(10)),
            "rank": 16,
            "epochs": 10,
            "trigger": "aiko",
        }
        job.update(overrides)
        return job

    def test_exito_marca_store_y_outputs(self):
        job = self.make_job()
        lora = self.root / "1.safetensors"
        lora.write_bytes(b"lora")
        with mock.patch.object(
            server_module.trainer,
            "train_character",
            return_value={"lora_path": str(lora), "entry": {"id": "oc-1"}},
        ) as fake:
            server_module.run_training_job(job, config=self.config, store=self.store)
        fake.assert_called_once()
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "train")
        self.assertEqual(row["outputs"], [str(lora)])
        self.assertEqual(job["outputs"], [str(lora)])
        self.assertIsNone(job["error"])

    def test_error_no_propaga_y_marca_store(self):
        job = self.make_job()
        with mock.patch.object(
            server_module.trainer,
            "train_character",
            side_effect=EngineError("entrenador no instalado (M10)"),
        ):
            server_module.run_training_job(job, config=self.config, store=self.store)
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("M10", row["error"])
        self.assertEqual(job["outputs"], [])
        self.assertIn("M10", job["error"])


class CharacterMediaTests(ServerTestCase):
    def test_404_y_confinamiento_403(self):
        client = self.make_client()
        missing = client.get("/media/characters/1/nope.png")
        self.assertEqual(missing.status_code, 404)
        self.assertIn("error", missing.json())
        (self.config.data_dir / "secret.png").write_bytes(PNG_BYTES)
        escape = client.get("/media/characters/1/..%2F..%2Fsecret.png")
        self.assertEqual(escape.status_code, 403)
        self.assertIn("error", escape.json())


class IndexTests(ServerTestCase):
    def test_index_200_con_waifu(self):
        response = self.make_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("WAIFU", response.text)
        self.assertIn("/static/app.js", response.text)
        self.assertIn("OC Maker", response.text)
        self.assertIn("Video", response.text)

    def test_index_incluye_controles_nuevos(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="size"',
            'id="manual-size"',
            'id="negative"',
            'id="btn-negative-restore"',
            'id="sampler"',
            'id="scheduler"',
            'id="enhance-strength"',
            'id="enhance-result"',
            'id="btn-enhance-use"',
            'id="btn-enhance-discard"',
            'id="ref-preview"',
            'id="btn-ref-clear"',
            'id="lightbox"',
            'id="gallery-prev"',
            'id="gallery-next"',
            'id="btn-cancel"',
            'id="job-progress"',
            'id="job-progress-fill"',
            'id="job-progress-text"',
            'id="prompt-zones"',
            'id="prompt-zones-preview"',
            'id="prompt-zones-legend"',
            'id="prompt-zones-chips"',
            'id="zone-insert-form"',
            'id="zone-insert-input"',
            'id="zone-insert-cancel"',
            'data-zone="character"',
            "+ Personaje",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_incluye_endpoints_y_features(self):
        text = self.make_client().get("/static/app.js").text
        for marker in (
            "/api/params",
            "/api/formats",
            "/api/negative",
            "const PAGE_SIZE = 6;",
            "Mejorando…",
            "Listo ✓",
            "Reusar",
            "openLightbox",
            "Escape",
            "/cancel",
            "setProgress",
            "setTimeout(resolve, 1000)",
            "/api/prompt/zones",
            "/api/prompt/insert",
            "refreshPromptZones",
            "openZoneInsert",
            "}, 300);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
