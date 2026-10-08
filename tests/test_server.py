"""Tests CPU de la webapp FastAPI (F3b). Sin red, GPU ni LLM real."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from app import loras as loras_module
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
from app.prompt_zones import CAMERA_TAGS, canonical_order
from app.registry import ModelRegistry
from app.server import create_app, run_generation
from app.store import Store
from app.tags import list_groups
from app.vision import WD14_THRESHOLD, VisionUnavailable

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"waifu-fake-png"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"waifu-fake-mp4"
MODEL_ID = "anima-2.9b-preview"
REGISTRY_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "models.json"


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


class FakeVideoTransport:
    """Transporte HTTP falso: submit y history success con MP4 fake."""

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
                (self.config.comfy_output_dir / self.output_name).write_bytes(
                    MP4_BYTES
                )
            return 200, json.dumps(
                {
                    "p1": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "6": {
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


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = make_config(self.root)
        self.store = Store(self.config.data_dir / "waifu.db")
        self.store.init()
        self.registry = ModelRegistry.load(REGISTRY_FIXTURE)
        server_module._JOBS.clear()
        self.addCleanup(server_module._JOBS.clear)

    def get_static_js(self) -> str:
        js_dir = Path(__file__).resolve().parent.parent / "static" / "js"
        parts = []
        for p in sorted(js_dir.rglob("*.js")):
            parts.append(p.read_text(encoding="utf-8"))
        return "\n".join(parts)

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
        self.assertEqual(data["families"], ["wan", "h3", "anima"])
        ids = [item["id"] for item in data["items"]]
        for seed_id in (
            "lightx2v-wan-high",
            "lightx2v-wan-low",
            "minimax-h3-fl2v-turbo-4step",
            "miku-nakano-anima",
            "kurashiki-reika-saimin-anima",
            "shuuko-komi-s1s2-anima",
            "mina-ashido-1-anima",
            "mina-ashido-2-anima",
        ):
            self.assertIn(seed_id, ids)

    def test_loras_filtro_por_familia(self):
        response = self.make_client().get("/api/loras", params={"family": "wan"})
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(
            [item["id"] for item in items],
            ["lightx2v-wan-high", "lightx2v-wan-low"],
        )
        self.assertTrue(all(item["family"] == "wan" for item in items))

    def test_loras_familia_anima_devuelve_miku_saimin_shuuko_y_mina(self):
        data = self.make_client().get(
            "/api/loras", params={"family": "anima"}
        ).json()
        self.assertGreaterEqual(len(data["items"]), 5)
        item = data["items"][0]
        self.assertEqual(item["id"], "miku-nakano-anima")
        self.assertEqual(item["family"], "anima")
        self.assertEqual(item["file"], "anima\\Miku_Nakano_Anima_v0.7.safetensors")
        self.assertEqual(item["trigger"], "M1kuNakan0_anima")
        self.assertEqual(item["default_weight"], 1.0)
        nueva = data["items"][1]
        self.assertEqual(nueva["id"], "kurashiki-reika-saimin-anima")
        self.assertEqual(nueva["family"], "anima")
        self.assertEqual(
            nueva["file"],
            "anima\\Kurashiki Reika Saimin Seishidou.safetensors",
        )
        self.assertEqual(nueva["trigger"], "kur4sh1k1r31k4")
        self.assertEqual(nueva["default_weight"], 1.0)
        shuuko = data["items"][2]
        self.assertEqual(shuuko["id"], "shuuko-komi-s1s2-anima")
        self.assertEqual(shuuko["family"], "anima")
        self.assertEqual(shuuko["file"], "anima\\shuuko-komi-s1s2.safetensors")
        self.assertEqual(shuuko["trigger"], "shuuko komi")
        self.assertEqual(shuuko["default_weight"], 1.0)
        mina1 = data["items"][3]
        self.assertEqual(mina1["id"], "mina-ashido-1-anima")
        self.assertEqual(mina1["family"], "anima")
        self.assertEqual(mina1["file"], "anima\\Mina Ashido 1.safetensors")
        self.assertEqual(mina1["trigger"], "aniashido")
        self.assertEqual(mina1["default_weight"], 1.0)
        mina2 = data["items"][4]
        self.assertEqual(mina2["id"], "mina-ashido-2-anima")
        self.assertEqual(mina2["family"], "anima")
        self.assertEqual(mina2["file"], "anima\\Mina Ashido 2.safetensors")
        self.assertEqual(mina2["trigger"], "")
        self.assertEqual(mina2["default_weight"], 1.0)
        self.assertIn("no verificada", shuuko["license"])
        self.assertIn("nochekaiser", shuuko["source"])
        self.assertIn("anima_baseV10", shuuko["notes"])
        self.assertIn("anima", data["families"])

    def test_loras_familia_desconocida_vacia(self):
        data = self.make_client().get(
            "/api/loras", params={"family": "no-existe"}
        ).json()
        self.assertEqual(data["items"], [])
        self.assertIn("wan", data["families"])


class LoraCrudRouteTests(ServerTestCase):
    """CRUD de biblioteca LoRAs (M10-5b): registro y models/loras temporales."""

    def setUp(self):
        super().setUp()
        self.loras_path = self.config.data_dir / "loras-test.json"
        self.loras_root = self.config.comfy_root / "models" / "loras"
        (self.loras_root / "anima").mkdir(parents=True, exist_ok=True)
        for stem in ("a", "b", "c"):
            (self.loras_root / "anima" / f"{stem}.safetensors").write_bytes(
                b"fake-lora"
            )
        self.write_registry([self.entry("lora-a", "a"), self.entry("lora-b", "b")])
        patcher = mock.patch.object(
            loras_module, "DEFAULT_PATH", self.loras_path
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        user = mock.patch.object(
            loras_module, "user_registry_path", lambda: self.loras_path
        )
        user.start()
        self.addCleanup(user.stop)

    def entry(self, lora_id: str, stem: str, **overrides) -> dict:
        data = {
            "id": lora_id,
            "family": "anima",
            "file": f"anima/{stem}.safetensors",
            "display_name": lora_id,
            "trigger": "",
            "default_weight": 1.0,
            "source": "test",
            "license": "test",
            "notes": "",
        }
        data.update(overrides)
        return data

    def write_registry(self, entries: list[dict]) -> None:
        self.loras_path.parent.mkdir(parents=True, exist_ok=True)
        self.loras_path.write_text(
            json.dumps({"version": 1, "loras": entries}), encoding="utf-8"
        )

    def registry_ids(self) -> list[str]:
        payload = json.loads(self.loras_path.read_text(encoding="utf-8"))
        return [item["id"] for item in payload["loras"]]

    def test_get_sigue_devolviendo_items_y_familias(self):
        data = self.make_client().get("/api/loras").json()
        self.assertEqual([item["id"] for item in data["items"]], ["lora-a", "lora-b"])
        self.assertEqual(data["families"], ["anima"])

    def test_post_crea_y_devuelve_catalogo(self):
        response = self.make_client().post(
            "/api/loras",
            json=self.entry("lora-c", "c", family="nueva", trigger="t1"),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["item"]["id"], "lora-c")
        self.assertEqual(data["item"]["trigger"], "t1")
        self.assertEqual(
            [item["id"] for item in data["items"]],
            ["lora-a", "lora-b", "lora-c"],
        )
        self.assertEqual(data["families"], ["anima", "nueva"])
        self.assertEqual(self.registry_ids(), ["lora-a", "lora-b", "lora-c"])

    def test_post_id_duplicado_409_y_registro_intacto(self):
        before = self.loras_path.read_text(encoding="utf-8")
        response = self.make_client().post("/api/loras", json=self.entry("lora-a", "c"))
        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())
        self.assertEqual(self.loras_path.read_text(encoding="utf-8"), before)

    def test_post_archivo_inexistente_400(self):
        response = self.make_client().post(
            "/api/loras", json=self.entry("lora-x", "no-existe")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertEqual(self.registry_ids(), ["lora-a", "lora-b"])

    def test_post_archivo_no_confinado_o_absoluto_400(self):
        escape_values = (
            "../fuera.safetensors",
            "..\\..\\fuera.safetensors",
            "anima/../../fuera.safetensors",
            str(self.loras_root / "anima" / "a.safetensors"),
        )
        for file_value in escape_values:
            with self.subTest(file=file_value):
                response = self.make_client().post(
                    "/api/loras",
                    json=self.entry("lora-x", "x", file=file_value),
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(self.registry_ids(), ["lora-a", "lora-b"])

    def test_post_validacion_400(self):
        for payload in (
            self.entry("lora-x", "x", family=""),
            self.entry("lora-x", "x", display_name=""),
            self.entry("lora-x", "x", default_weight=3),
            self.entry("Con Mayusculas", "x"),
            self.entry("lora-x", "x", trigger=5),
        ):
            with self.subTest(payload=payload):
                response = self.make_client().post("/api/loras", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(self.registry_ids(), ["lora-a", "lora-b"])

    def test_put_edita_y_persiste(self):
        response = self.make_client().put(
            "/api/loras/lora-a",
            json={
                "display_name": "Otra",
                "trigger": "t1",
                "default_weight": 0.5,
                "notes": "n",
            },
        )
        self.assertEqual(response.status_code, 200)
        item = response.json()["item"]
        self.assertEqual(item["id"], "lora-a")
        self.assertEqual(item["display_name"], "Otra")
        self.assertEqual(item["default_weight"], 0.5)
        saved = json.loads(self.loras_path.read_text(encoding="utf-8"))["loras"][0]
        self.assertEqual(saved["trigger"], "t1")
        self.assertEqual(saved["notes"], "n")
        self.assertEqual(saved["file"], "anima/a.safetensors")

    def test_put_cambia_file_si_existe(self):
        response = self.make_client().put(
            "/api/loras/lora-a", json={"file": "anima/c.safetensors"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item"]["file"], "anima/c.safetensors")

    def test_put_404_400_y_id_inmutable(self):
        client = self.make_client()
        before = self.loras_path.read_text(encoding="utf-8")
        self.assertEqual(
            client.put("/api/loras/no-existe", json={"trigger": "t"}).status_code, 404
        )
        self.assertEqual(
            client.put("/api/loras/lora-a", json={"id": "otro"}).status_code, 400
        )
        self.assertEqual(
            client.put(
                "/api/loras/lora-a", json={"file": "anima/no-existe.safetensors"}
            ).status_code,
            400,
        )
        self.assertEqual(
            client.put("/api/loras/lora-a", json={"display_name": ""}).status_code,
            400,
        )
        self.assertEqual(self.loras_path.read_text(encoding="utf-8"), before)

    def test_delete_quita_entrada_y_no_el_fichero(self):
        response = self.make_client().delete("/api/loras/lora-a")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["deleted"], "lora-a")
        self.assertEqual([item["id"] for item in data["items"]], ["lora-b"])
        self.assertEqual(data["families"], ["anima"])
        self.assertEqual(self.registry_ids(), ["lora-b"])
        self.assertTrue((self.loras_root / "anima" / "a.safetensors").is_file())

    def test_delete_404_no_toca_el_registro(self):
        response = self.make_client().delete("/api/loras/no-existe")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
        self.assertEqual(self.registry_ids(), ["lora-a", "lora-b"])


def lora_safetensors_bytes(metadata=None, tensors=None) -> bytes:
    header: dict = dict(tensors or {})
    if metadata is not None:
        header["__metadata__"] = metadata
    encoded = json.dumps(header).encode("utf-8")
    encoded += b" " * ((8 - len(encoded) % 8) % 8)
    return struct.pack("<Q", len(encoded)) + encoded + b"\x00" * 64


LORA_UPLOAD_METADATA = {
    "ss_network_dim": "32",
    "ss_network_alpha": "16",
    "ss_sd_model_name": "anima_baseV10",
    "modelspec.title": "Mi Lora Titulo",
    "ss_tag_frequency": json.dumps({"dataset": {"mi trigger": 50, "otro": 3}}),
}


class LoraUploadRouteTests(ServerTestCase):
    """Subida de .safetensors a models/loras (M10-5c): copia, registro y borrado."""

    def setUp(self):
        super().setUp()
        self.loras_path = self.config.data_dir / "loras-upload-test.json"
        self.loras_root = self.config.comfy_root / "models" / "loras"
        self.loras_path.parent.mkdir(parents=True, exist_ok=True)
        self.loras_path.write_text(
            json.dumps({"version": 1, "loras": []}), encoding="utf-8"
        )
        patcher = mock.patch.object(
            loras_module, "DEFAULT_PATH", self.loras_path
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        user = mock.patch.object(
            loras_module, "user_registry_path", lambda: self.loras_path
        )
        user.start()
        self.addCleanup(user.stop)

    def payload(self, raw=None, **overrides) -> dict:
        data = {
            "filename": "Mi Lora.safetensors",
            "family": "anima",
            "file_b64": base64.b64encode(
                raw if raw is not None else lora_safetensors_bytes(LORA_UPLOAD_METADATA)
            ).decode("ascii"),
        }
        data.update(overrides)
        return data

    def registry_entries(self) -> list[dict]:
        payload = json.loads(self.loras_path.read_text(encoding="utf-8"))
        return payload["loras"]

    def test_upload_200_copia_registra_e_infiere_metadata(self):
        raw = lora_safetensors_bytes(LORA_UPLOAD_METADATA)
        response = self.make_client().post(
            "/api/loras/upload", json=self.payload(raw=raw)
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"item", "file", "trigger_inferido"})
        item = data["item"]
        self.assertEqual(item["id"], "mi-lora")
        self.assertEqual(item["family"], "anima")
        self.assertEqual(item["file"], "anima\\Mi Lora.safetensors")
        self.assertEqual(item["display_name"], "Mi Lora Titulo")
        self.assertEqual(item["trigger"], "mi trigger")
        self.assertEqual(item["default_weight"], 1.0)
        self.assertEqual(item["source"], "subido desde la app")
        self.assertIn("no verificada", item["license"])
        self.assertIn("dim 32 / alpha 16", item["notes"])
        self.assertIn("base anima_baseV10", item["notes"])
        self.assertIn("editable", item["notes"])
        self.assertEqual(data["file"], "anima\\Mi Lora.safetensors")
        self.assertEqual(data["trigger_inferido"], "mi trigger")
        target = self.loras_root / "anima" / "Mi Lora.safetensors"
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(
            [entry["id"] for entry in self.registry_entries()], ["mi-lora"]
        )

    def test_upload_display_name_y_trigger_del_payload_ganan(self):
        response = self.make_client().post(
            "/api/loras/upload",
            json=self.payload(display_name="Nombre manual", trigger="trigger manual"),
        )
        self.assertEqual(response.status_code, 200)
        item = response.json()["item"]
        self.assertEqual(item["display_name"], "Nombre manual")
        self.assertEqual(item["trigger"], "trigger manual")
        self.assertEqual(response.json()["trigger_inferido"], "mi trigger")

    def test_upload_sin_metadata_usa_stem_y_notes_minimas(self):
        response = self.make_client().post(
            "/api/loras/upload",
            json=self.payload(raw=lora_safetensors_bytes({"otra": "x"})),
        )
        self.assertEqual(response.status_code, 200)
        item = response.json()["item"]
        self.assertEqual(item["display_name"], "Mi Lora")
        self.assertEqual(item["trigger"], "")
        self.assertEqual(response.json()["trigger_inferido"], "")
        self.assertEqual(
            item["notes"], "trigger inferido del safetensors (editable)"
        )

    def test_upload_data_uri_aceptada(self):
        raw = lora_safetensors_bytes(LORA_UPLOAD_METADATA)
        encoded = base64.b64encode(raw).decode("ascii")
        response = self.make_client().post(
            "/api/loras/upload",
            json=self.payload(
                file_b64=f"data:application/octet-stream;base64,{encoded}"
            ),
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_slug_duplicado_anade_sufijo(self):
        client = self.make_client()
        first = client.post("/api/loras/upload", json=self.payload())
        second = client.post(
            "/api/loras/upload",
            json=self.payload(filename="Mi-Lora.safetensors", family="otra"),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["item"]["id"], "mi-lora")
        self.assertEqual(second.json()["item"]["id"], "mi-lora-2")
        self.assertEqual(
            [entry["id"] for entry in self.registry_entries()],
            ["mi-lora", "mi-lora-2"],
        )
        self.assertTrue(
            (self.loras_root / "otra" / "Mi-Lora.safetensors").is_file()
        )

    def test_upload_400_validaciones(self):
        cases = (
            ("extension", {"filename": "lora.bin"}),
            ("ruta", {"filename": "anima/lora.safetensors"}),
            ("ruta_win", {"filename": "anima\\lora.safetensors"}),
            ("filename_vacio", {"filename": ""}),
            ("family_mayus", {"family": "Anima"}),
            ("family_vacia", {"family": ""}),
            ("family_escape", {"family": ".."}),
            ("b64_invalido", {"file_b64": "%%%"}),
            ("b64_vacio", {"file_b64": ""}),
            (
                "cabecera_invalida",
                {
                    "file_b64": base64.b64encode(b"no-es-safetensors").decode(
                        "ascii"
                    )
                },
            ),
            (
                "cabecera_no_dict",
                {
                    "file_b64": base64.b64encode(
                        struct.pack("<Q", 2) + b"[]"
                    ).decode("ascii")
                },
            ),
        )
        client = self.make_client()
        for label, overrides in cases:
            with self.subTest(caso=label):
                response = client.post(
                    "/api/loras/upload", json=self.payload(**overrides)
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        for field in ("filename", "family", "file_b64"):
            with self.subTest(campo=field):
                payload = self.payload()
                payload.pop(field)
                self.assertEqual(
                    client.post("/api/loras/upload", json=payload).status_code, 400
                )
        self.assertEqual(self.registry_entries(), [])
        self.assertFalse(self.loras_root.exists())

    def test_upload_409_si_el_destino_existe(self):
        target = self.loras_root / "anima" / "Mi Lora.safetensors"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ocupado")
        response = self.make_client().post("/api/loras/upload", json=self.payload())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"],
            "ya existe ese archivo en loras/anima/Mi Lora.safetensors",
        )
        self.assertEqual(target.read_bytes(), b"ocupado")
        self.assertEqual(self.registry_entries(), [])

    def test_upload_sin_huerfano_si_el_registro_falla(self):
        client = self.make_client()
        with mock.patch.object(
            server_module, "add_lora", side_effect=EngineError("registro roto")
        ):
            response = client.post("/api/loras/upload", json=self.payload())
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            (self.loras_root / "anima" / "Mi Lora.safetensors").exists()
        )
        self.assertEqual(self.registry_entries(), [])

    def upload(self, client, filename="Mi Lora.safetensors", family="anima"):
        response = client.post(
            "/api/loras/upload", json=self.payload(filename=filename, family=family)
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_delete_con_file_borra_archivo_y_entrada(self):
        client = self.make_client()
        data = self.upload(client)
        target = self.loras_root / "anima" / "Mi Lora.safetensors"
        self.assertTrue(target.is_file())
        response = client.delete(
            f"/api/loras/{data['item']['id']}", params={"file": "1"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["deleted"], "mi-lora")
        self.assertTrue(body["file_removed"])
        self.assertFalse(target.exists())
        self.assertEqual(self.registry_entries(), [])

    def test_delete_sin_file_no_borra_el_archivo(self):
        client = self.make_client()
        data = self.upload(client)
        target = self.loras_root / "anima" / "Mi Lora.safetensors"
        response = client.delete(f"/api/loras/{data['item']['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["file_removed"])
        self.assertTrue(target.is_file())
        self.assertEqual(self.registry_entries(), [])

    def test_delete_con_file_inexistente_no_es_error(self):
        self.loras_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "loras": [
                        {
                            "id": "fantasma",
                            "family": "anima",
                            "file": "anima/fantasma.safetensors",
                            "display_name": "Fantasma",
                            "trigger": "",
                            "default_weight": 1.0,
                            "source": "test",
                            "license": "test",
                            "notes": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        response = self.make_client().delete(
            "/api/loras/fantasma", params={"file": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["file_removed"])
        self.assertEqual(self.registry_entries(), [])

    def test_delete_con_file_no_confinado_400_y_conserva_todo(self):
        outside = self.config.comfy_root / "models" / "fuera.safetensors"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(b"fuera")
        self.loras_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "loras": [
                        {
                            "id": "fugada",
                            "family": "anima",
                            "file": "..\\fuera.safetensors",
                            "display_name": "Fugada",
                            "trigger": "",
                            "default_weight": 1.0,
                            "source": "test",
                            "license": "test",
                            "notes": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        response = self.make_client().delete(
            "/api/loras/fugada", params={"file": "1"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertTrue(outside.is_file())
        self.assertEqual(
            [entry["id"] for entry in self.registry_entries()], ["fugada"]
        )


class LoraLibraryUiStaticTests(ServerTestCase):
    def test_index_incluye_gestion_de_biblioteca(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="btn-lora-manage"',
            ">Gestionar biblioteca<",
            'id="btn-lora-manage-modal"',
            'id="lora-library-modal"',
            'id="btn-lora-library-close"',
            'id="lora-library-status"',
            'id="lora-library-list"',
            'id="lora-library-form"',
            'id="lora-library-form-title"',
            'id="lora-form-id"',
            'id="lora-form-family"',
            'id="lora-form-file"',
            'id="lora-form-display"',
            'id="lora-form-trigger"',
            'id="lora-form-weight"',
            'id="lora-form-source"',
            'id="lora-form-license"',
            'id="lora-form-notes"',
            'id="btn-lora-form-cancel"',
            'id="btn-lora-upload"',
            'id="lora-upload"',
            "Cargar desde disco",
            "NO se borra",
            "models\\loras",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_incluye_crud_biblioteca(self):
        text = self.get_static_js()
        for marker in (
            "putJson",
            "loadLoraLibrary",
            "renderLoraLibrary",
            "editLoraEntry",
            "saveLoraEntry",
            "deleteLoraEntry",
            "uploadLoraFile",
            "openLoraLibrary",
            "closeLoraLibrary",
            'postJson("/api/loras"',
            'postJson("/api/loras/upload"',
            "/api/loras/${encodeURIComponent",
            '{ method: "DELETE" }',
            "?file=1",
            "btn-lora-delete-file",
            "Registrado ✓",
            'on("btn-lora-manage", "click", openLoraLibrary);',
            'on("btn-lora-manage-modal", "click", openLoraLibrary);',
            '"lora-library-modal",',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


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
    def test_formats_15_y_default(self):
        response = self.make_client().get("/api/formats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["default"], DEFAULT_FORMAT)
        self.assertEqual(data["default"], "retrato_plan")
        self.assertEqual(len(data["formats"]), 15)
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

    def test_zones_subcats_other(self):
        response = self.make_client().post(
            "/api/prompt/zones",
            json={"text": "1girl, blue sky, tag_desconocido"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        general = next(item for item in data["zones"] if item["id"] == "general")
        subcats = {item["id"]: item["tags"] for item in general["subcats"]}
        self.assertEqual(subcats["fondo"], ["blue sky"])
        self.assertEqual(subcats["other"], ["tag_desconocido"])

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

    def test_options_general_200(self):
        response = self.make_client().get(
            "/api/prompt/options", params={"zone": "general"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"zone", "subgroups"})
        self.assertEqual(data["zone"], "general")
        ids = [sub["id"] for sub in data["subgroups"]]
        self.assertEqual(
            ids,
            [
                "rasgos",
                "ropa",
                "accesorios",
                "accion",
                "poses",
                "poses_sexuales",
                "poses_sexys",
                "expresion",
                "expresiones_nsfw",
                "camara",
                "fondo",
            ],
        )
        self.assertIn("camara", ids)
        self.assertIn("rasgos", ids)
        self.assertIn("poses", ids)
        self.assertNotIn("otros", ids)
        camara = next(sub for sub in data["subgroups"] if sub["id"] == "camara")
        self.assertEqual(
            [item["tag"] for item in camara["tags"]], list(CAMERA_TAGS)
        )
        poses = next(sub for sub in data["subgroups"] if sub["id"] == "poses")
        self.assertIn(
            "standing", [item["tag"] for item in poses["tags"]]
        )
        fondo = next(sub for sub in data["subgroups"] if sub["id"] == "fondo")
        self.assertIn(
            "blurry background", [item["tag"] for item in fondo["tags"]]
        )
        for item in camara["tags"]:
            self.assertEqual(set(item), {"tag", "label"})

    def test_options_quality_safety_subject_character_200(self):
        client = self.make_client()
        for zone in ("quality", "safety", "subject"):
            with self.subTest(zone=zone):
                response = client.get("/api/prompt/options", params={"zone": zone})
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["zone"], zone)
                self.assertEqual([sub["id"] for sub in data["subgroups"]], [zone])
                self.assertTrue(data["subgroups"][0]["tags"])
        character = client.get(
            "/api/prompt/options", params={"zone": "character"}
        ).json()
        self.assertEqual(character, {"zone": "character", "subgroups": []})

    def test_options_zona_invalida_400(self):
        client = self.make_client()
        for params in ({}, {"zone": ""}, {"zone": "nope"}):
            with self.subTest(params=params):
                response = client.get("/api/prompt/options", params=params)
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
        tags = [tag.strip() for tag in data["positive"].split(",")]
        self.assertIn("masterpiece", tags)
        self.assertIn("sfw", tags)
        self.assertIn("1girl", tags)
        self.assertIn("smile", tags)
        self.assertLess(tags.index("masterpiece"), tags.index("sfw"))
        self.assertLess(tags.index("sfw"), tags.index("1girl"))
        self.assertLess(tags.index("1girl"), tags.index("smile"))
        self.assertIn("worst quality", data["negative"])
        self.assertEqual(data["dropped"], [])

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


class EnhanceZonesRouteTests(ServerTestCase):
    """`POST /api/prompt/enhance_zones` (M9-C3a): backend del editor por zonas."""

    @staticmethod
    def zones_llm(system, user):
        return "masterpiece, 1girl, long hair, school uniform, blue sky"

    def test_400_texto_vacio(self):
        for payload in ({"text": None}, {"text": ""}, {"text": "   "}, {}):
            with self.subTest(payload=payload):
                response = self.make_client(llm=self.zones_llm).post(
                    "/api/prompt/enhance_zones", json=payload
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_400_zone_invalida(self):
        for zone in ("cabeza", "", 5, ["general"]):
            with self.subTest(zone=zone):
                response = self.make_client(llm=self.zones_llm).post(
                    "/api/prompt/enhance_zones", json={"text": "1girl", "zone": zone}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_400_strength_invalido(self):
        for strength in ("loco", "", 5, ["fiel"]):
            with self.subTest(strength=strength):
                response = self.make_client(llm=self.zones_llm).post(
                    "/api/prompt/enhance_zones",
                    json={"text": "1girl", "strength": strength},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_400_rating_invalido(self):
        for rating in ("explicit", "", 5):
            with self.subTest(rating=rating):
                response = self.make_client(llm=self.zones_llm).post(
                    "/api/prompt/enhance_zones",
                    json={"text": "1girl", "rating": rating},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_400_tags_invalidas(self):
        for tags in (5, "1girl", [1, 2], {"a": 1}):
            with self.subTest(tags=tags):
                response = self.make_client(llm=self.zones_llm).post(
                    "/api/prompt/enhance_zones",
                    json={"text": "1girl", "tags": tags},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_400_tags_maximo(self):
        response = self.make_client(llm=self.zones_llm).post(
            "/api/prompt/enhance_zones",
            json={"text": "1girl", "tags": ["tag"] * 121},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_tags_llegan_al_llm_con_dedup(self):
        llm = CapturingLLM(self.zones_llm("", ""))
        response = self.make_client(llm=llm).post(
            "/api/prompt/enhance_zones",
            json={"text": "1girl", "tags": ["Long Hair", "long hair", "wind"]},
        )
        self.assertEqual(response.status_code, 200)
        user = llm.calls[0]["user"]
        self.assertIn(
            "Tags ya aplicadas (NO las repitas en la salida): Long Hair, wind", user
        )
        self.assertIn("Instrucciones de tags:", user)

    def test_sin_tags_no_aparece_la_linea_pero_si_las_instrucciones(self):
        llm = CapturingLLM(self.zones_llm("", ""))
        response = self.make_client(llm=llm).post(
            "/api/prompt/enhance_zones", json={"text": "1girl"}
        )
        self.assertEqual(response.status_code, 200)
        user = llm.calls[0]["user"]
        self.assertNotIn("Tags ya aplicadas", user)
        self.assertIn("Instrucciones de tags:", user)

    def test_sin_llm_503_mismo_mensaje_que_enhance(self):
        response = self.make_client().post(
            "/api/prompt/enhance_zones", json={"text": "1girl"}
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "LLM no disponible"})

    def test_con_llm_zones_composed_y_negative(self):
        client = self.make_client(llm=self.zones_llm)
        response = client.post(
            "/api/prompt/enhance_zones", json={"text": "1girl", "rating": "sfw"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data), {"raw", "positive", "negative", "composed", "zones", "dropped"}
        )
        self.assertEqual(data["dropped"], [])
        self.assertEqual(data["raw"], "masterpiece, 1girl, long hair, school uniform, blue sky, sfw")
        zones = {item["id"]: item["tags"] for item in data["zones"]}
        self.assertIn("masterpiece", zones["quality"])
        self.assertEqual(zones["safety"], ["sfw"])
        self.assertEqual(zones["subject"], ["1girl"])
        self.assertEqual(zones["general"], ["long hair", "school uniform", "blue sky"])
        general = next(item for item in data["zones"] if item["id"] == "general")
        subcats = {item["id"]: item["tags"] for item in general["subcats"]}
        self.assertEqual(subcats["rasgos"], ["long hair"])
        self.assertEqual(subcats["ropa"], ["school uniform"])
        self.assertEqual(subcats["fondo"], ["blue sky"])
        self.assertEqual(data["composed"], canonical_order(data["positive"]))
        self.assertEqual(data["composed"], data["positive"])
        tags = [tag.strip().lower() for tag in data["negative"].split(",")]
        self.assertEqual(len(tags), len(set(tags)))
        self.assertTrue(data["negative"].startswith(BASE_NEGATIVE))

    def test_zone_general_el_fake_recibe_la_linea(self):
        llm = CapturingLLM(self.zones_llm("", ""))
        response = self.make_client(llm=llm).post(
            "/api/prompt/enhance_zones",
            json={"text": "1girl", "zone": "general", "strength": "fiel"},
        )
        self.assertEqual(response.status_code, 200)
        user = llm.calls[0]["user"]
        self.assertIn("Zona objetivo: general.", user)
        self.assertIn("si algo no pertenece, omítelo.", user)

    def test_sin_zone_no_aparece_la_linea(self):
        llm = CapturingLLM(self.zones_llm("", ""))
        response = self.make_client(llm=llm).post(
            "/api/prompt/enhance_zones", json={"text": "1girl"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Zona objetivo:", llm.calls[0]["user"])


class FakeVision:
    """Vision inyectada: registra llamadas y devuelve resultados fijos."""

    def __init__(
        self, *, available: bool = True, server_url: str | None = None
    ) -> None:
        self.available = available
        self.server_url = server_url
        self.calls: list[tuple[bytes, bool, bool]] = []
        self.unified_calls = 0

    def status(self) -> dict:
        return {
            "installed": self.available,
            "wd14": {"installed": self.available, "model": "wd14-fake"},
            "vl": {"installed": self.available, "model": "vl-fake"},
            "note": "fake",
        }

    def describe(
        self, image_bytes: bytes, *, use_tags: bool = True, use_caption: bool = True
    ) -> dict:
        if not self.available:
            raise VisionUnavailable("vision no instalada (fake)")
        self.calls.append((image_bytes, use_tags, use_caption))
        return {
            "tags": ["1girl"] if use_tags else None,
            "caption": "a girl" if use_caption else None,
            "model": {"wd14": "wd14-fake", "vl": "vl-fake"},
        }

    def describe_unified(self, image_bytes: bytes) -> dict:
        if not self.available:
            raise VisionUnavailable("vision no instalada (fake)")
        self.unified_calls += 1
        return {
            "tags": ["1girl", "long hair"],
            "caption": "a girl",
            "dropped": ["inventado"],
            "mode": "server",
            "model": {"wd14": "wd14-fake", "vl": "vl-fake"},
        }


class VisionRouteTests(ServerTestCase):
    def test_status_200(self):
        response = self.make_client(vision=FakeVision()).get("/api/vision/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["installed"])
        self.assertEqual(data["wd14"]["model"], "wd14-fake")
        self.assertEqual(data["vl"]["model"], "vl-fake")

    def test_image_to_prompt_por_gen_id(self):
        gen_id = self.store.add(MODEL_ID, "p", status="done")
        self.add_gallery_png(gen_id, "x.png")
        self.store.update(gen_id, outputs=["x.png"])
        vision = FakeVision()
        response = self.make_client(vision=vision).post(
            "/api/vision/image_to_prompt", json={"gen_id": str(gen_id)}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["tags"], ["1girl"])
        self.assertEqual(data["caption"], "a girl")
        raw, use_tags, use_caption = vision.calls[0]
        self.assertEqual(raw, PNG_BYTES)
        self.assertTrue(use_tags)
        self.assertTrue(use_caption)

    def test_image_to_prompt_por_b64_y_flags(self):
        vision = FakeVision()
        response = self.make_client(vision=vision).post(
            "/api/vision/image_to_prompt",
            json={
                "image_b64": base64.b64encode(PNG_BYTES).decode("ascii"),
                "use_caption": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["caption"])
        self.assertEqual(vision.calls[0][1:], (True, False))

    def test_400_gen_y_b64_a_la_vez_o_ninguno(self):
        client = self.make_client(vision=FakeVision())
        for payload in ({"gen_id": 1, "image_b64": "aGk="}, {}):
            with self.subTest(payload=payload):
                response = client.post("/api/vision/image_to_prompt", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_400_gen_id_invalido(self):
        client = self.make_client(vision=FakeVision())
        for value in (True, 3.5, [], "abc"):
            with self.subTest(value=value):
                response = client.post(
                    "/api/vision/image_to_prompt", json={"gen_id": value}
                )
                self.assertEqual(response.status_code, 400)

    def test_400_flags_invalidas(self):
        client = self.make_client(vision=FakeVision())
        for payload in (
            {"image_b64": "aGk=", "use_tags": "si"},
            {"image_b64": "aGk=", "use_tags": False, "use_caption": False},
        ):
            with self.subTest(payload=payload):
                response = client.post("/api/vision/image_to_prompt", json=payload)
                self.assertEqual(response.status_code, 400)

    def test_404_generacion_desconocida(self):
        response = self.make_client(vision=FakeVision()).post(
            "/api/vision/image_to_prompt", json={"gen_id": 999}
        )
        self.assertEqual(response.status_code, 404)

    def test_400_generacion_no_imagen(self):
        gen_id = self.store.add(MODEL_ID, "p", status="done", kind="video")
        self.add_gallery_png(gen_id, "x.png")
        self.store.update(gen_id, outputs=["x.png"])
        response = self.make_client(vision=FakeVision()).post(
            "/api/vision/image_to_prompt", json={"gen_id": gen_id}
        )
        self.assertEqual(response.status_code, 400)

    def test_503_sin_vision_disponible(self):
        response = self.make_client(vision=FakeVision(available=False)).post(
            "/api/vision/image_to_prompt",
            json={"image_b64": base64.b64encode(PNG_BYTES).decode("ascii")},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())


class VisionModeRouteTests(ServerTestCase):
    """`mode` unificado/tags/caption del `image_to_prompt` (M11-3G)."""

    B64 = base64.b64encode(PNG_BYTES).decode("ascii")

    def test_sin_mode_respuesta_exacta_sin_claves_nuevas(self):
        response = self.make_client(vision=FakeVision()).post(
            "/api/vision/image_to_prompt", json={"image_b64": self.B64}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"tags", "caption", "model"})

    def test_mode_unified_usa_describe_unified(self):
        vision = FakeVision()
        response = self.make_client(vision=vision).post(
            "/api/vision/image_to_prompt",
            json={"image_b64": self.B64, "mode": "unified"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["mode"], "unified")
        self.assertEqual(data["tags"], ["1girl", "long hair"])
        self.assertEqual(data["caption"], "a girl")
        self.assertEqual(data["dropped"], ["inventado"])
        self.assertEqual(data["model"], {"wd14": "wd14-fake", "vl": "vl-fake"})
        self.assertTrue(any(zone["tags"] for zone in data["zones"]))
        self.assertEqual(vision.unified_calls, 1)
        self.assertEqual(vision.calls, [])

    def test_mode_tags_ignora_flags_y_anade_zones(self):
        vision = FakeVision()
        response = self.make_client(vision=vision).post(
            "/api/vision/image_to_prompt",
            json={
                "image_b64": self.B64,
                "mode": "tags",
                "use_tags": False,
                "use_caption": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data), {"tags", "caption", "model", "mode", "dropped", "zones"}
        )
        self.assertEqual(data["mode"], "tags")
        self.assertEqual(data["tags"], ["1girl"])
        self.assertIsNone(data["caption"])
        self.assertEqual(data["dropped"], [])
        self.assertEqual(vision.calls[-1][1:], (True, False))

    def test_mode_caption_sin_zones(self):
        vision = FakeVision()
        response = self.make_client(vision=vision).post(
            "/api/vision/image_to_prompt",
            json={"image_b64": self.B64, "mode": "caption"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data), {"tags", "caption", "model", "mode", "dropped"}
        )
        self.assertIsNone(data["tags"])
        self.assertEqual(data["caption"], "a girl")
        self.assertEqual(data["dropped"], [])
        self.assertEqual(vision.calls[-1][1:], (False, True))

    def test_mode_invalido_400(self):
        client = self.make_client(vision=FakeVision())
        for mode in ("nope", 3, True):
            with self.subTest(mode=mode):
                response = client.post(
                    "/api/vision/image_to_prompt",
                    json={"image_b64": self.B64, "mode": mode},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("mode", response.json()["error"])

    def test_mode_unified_503_sin_vision(self):
        response = self.make_client(vision=FakeVision(available=False)).post(
            "/api/vision/image_to_prompt",
            json={"image_b64": self.B64, "mode": "unified"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json())


class FakeManager:
    """Manager falso para las rutas: status fijo y URLs configurables."""

    def __init__(
        self,
        status: dict,
        *,
        base_url: str = "http://127.0.0.1:8290",
        external_url: str | None = None,
        ensure_error: Exception | None = None,
    ):
        self._status = status
        self.base_url = base_url
        self._external_url = external_url
        self._ensure_error = ensure_error
        self.status_calls = 0
        self.ensure_calls = 0

    def external_url(self):
        return self._external_url

    def ensure(self):
        self.ensure_calls += 1
        if self._ensure_error is not None:
            raise self._ensure_error
        return self._external_url or self.base_url

    def status(self):
        self.status_calls += 1
        return self._status


class LlmStatusRouteTests(ServerTestCase):
    """`GET /api/llm/status` (M12-3): delega en el manager gestionado/externo."""

    MANAGED = {
        "mode": "managed",
        "state": "stopped",
        "url": "http://127.0.0.1:8290",
        "detail": "lo arranca la app al primer uso",
    }

    def test_gestionado_delega_en_el_manager(self):
        fake = FakeManager(dict(self.MANAGED))
        with mock.patch.object(server_module, "_manager", return_value=fake):
            response = self.make_client().get("/api/llm/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.MANAGED)
        self.assertEqual(fake.status_calls, 1)

    def test_externo_delega_en_el_manager(self):
        payload = {
            "mode": "external",
            "state": "loading",
            "url": "http://externo:9000",
            "detail": "HTTP 503: loading model",
        }
        fake = FakeManager(payload, external_url="http://externo:9000")
        with mock.patch.object(server_module, "_manager", return_value=fake):
            response = self.make_client().get("/api/llm/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)


class VisionManagedServerTests(ServerTestCase):
    """El caption/unified arranca el `llama-server` gestionado (M12-4)."""

    B64 = base64.b64encode(PNG_BYTES).decode("ascii")

    def _post(self, vision, fake, payload):
        with mock.patch.object(server_module, "_manager", return_value=fake):
            return self.make_client(vision=vision).post(
                "/api/vision/image_to_prompt", json=payload
            )

    def test_unified_arranca_el_servidor_antes_de_describir(self):
        vision = FakeVision(server_url="http://127.0.0.1:8290")
        fake = FakeManager(dict(LlmStatusRouteTests.MANAGED))
        response = self._post(
            vision, fake, {"image_b64": self.B64, "mode": "unified"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.ensure_calls, 1)
        self.assertEqual(vision.unified_calls, 1)

    def test_caption_arranca_el_servidor(self):
        vision = FakeVision(server_url="http://127.0.0.1:8290")
        fake = FakeManager(dict(LlmStatusRouteTests.MANAGED))
        response = self._post(
            vision, fake, {"image_b64": self.B64, "mode": "caption"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.ensure_calls, 1)

    def test_tags_no_arranca_el_servidor(self):
        vision = FakeVision(server_url="http://127.0.0.1:8290")
        fake = FakeManager(dict(LlmStatusRouteTests.MANAGED))
        response = self._post(
            vision, fake, {"image_b64": self.B64, "mode": "tags"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.ensure_calls, 0)

    def test_sin_caption_no_arranca_el_servidor(self):
        vision = FakeVision(server_url="http://127.0.0.1:8290")
        fake = FakeManager(dict(LlmStatusRouteTests.MANAGED))
        response = self._post(
            vision, fake, {"image_b64": self.B64, "use_caption": False}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.ensure_calls, 0)

    def test_vision_local_no_arranca_el_servidor(self):
        vision = FakeVision()
        fake = FakeManager(dict(LlmStatusRouteTests.MANAGED))
        response = self._post(
            vision, fake, {"image_b64": self.B64, "mode": "unified"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.ensure_calls, 0)

    def test_error_del_manager_llega_como_400(self):
        vision = FakeVision(server_url="http://127.0.0.1:8290")
        fake = FakeManager(
            dict(LlmStatusRouteTests.MANAGED),
            ensure_error=EngineError("faltan archivos del servidor LLM"),
        )
        response = self._post(
            vision, fake, {"image_b64": self.B64, "mode": "unified"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("faltan archivos", response.json()["error"])


class DefaultVisionWiringTests(ServerTestCase):
    """`create_app` sin vision inyectada usa el servidor gestionado (M12-3)."""

    def test_vision_usa_la_url_gestionada(self):
        fake = FakeManager(
            dict(LlmStatusRouteTests.MANAGED), base_url="http://127.0.0.1:9911"
        )
        with mock.patch.object(server_module, "_manager", return_value=fake):
            response = self.make_client().get("/api/vision/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("http://127.0.0.1:9911", response.json()["note"])

    def test_vision_respeta_la_url_externa(self):
        fake = FakeManager(
            dict(LlmStatusRouteTests.MANAGED),
            base_url="http://127.0.0.1:9911",
            external_url="http://externo:9000",
        )
        with mock.patch.object(server_module, "_manager", return_value=fake):
            response = self.make_client().get("/api/vision/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("http://externo:9000", response.json()["note"])


class ManagerLlmTests(ServerTestCase):
    """`_manager_llm` (M12-3): ensure perezoso y temperature por kwarg."""

    def test_ensure_y_temperature(self):
        fake_manager = mock.Mock()
        fake_manager.ensure.return_value = "http://127.0.0.1:9911"
        captured: dict = {}

        def fake_client(system, user, temperature=None):
            captured["temperature"] = temperature
            return "1girl"

        with mock.patch.object(
            server_module, "_manager", return_value=fake_manager
        ), mock.patch.object(
            server_module, "load_server_llm", return_value=fake_client
        ) as loader:
            llm = server_module._manager_llm()
            self.assertEqual(llm("S", "U", temperature=0.4), "1girl")
            self.assertEqual(llm("S", "U"), "1girl")
        loader.assert_called_with("http://127.0.0.1:9911")
        self.assertEqual(captured["temperature"], None)
        fake_manager.ensure.assert_called_with()

    def test_main_pasa_el_llm_gestionado(self):
        sentinel = lambda system, user: "ok"  # noqa: E731
        with mock.patch.object(
            server_module, "_manager_llm", return_value=sentinel
        ) as builder, mock.patch.object(
            server_module, "create_app", return_value=object()
        ) as create, mock.patch("uvicorn.run") as run:
            server_module.main()
        builder.assert_called_once_with()
        create.assert_called_once_with(llm=sentinel)
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["host"], server_module.APP_HOST)


class PromptGeneralUiStaticTests(ServerTestCase):
    """Generador general de prompt (M10-2e): cuadro natural + fusión por zonas."""

    def test_index_prompt_general_arriba_en_la_columna_2(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="prompt-general"',
            "Describe en lenguaje natural: escena, personaje, acción, estilo",
            'id="btn-enhance" type="button">Generar prompt</button>',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertLess(
            text.index("controls-column-zones"),
            text.index('id="prompt-general"'),
        )
        self.assertLess(
            text.index('id="prompt-general"'),
            text.index('id="btn-enhance"'),
        )

    def test_app_js_genera_desde_prompt_general_y_fusiona(self):
        text = self.get_static_js()
        for marker in (
            "enhancePrompt",
            'const generalField = $("prompt-general");',
            '"Escribe una descripción en el prompt general"',
            'button.textContent = "Generar prompt"',
            "applyZonesPayload(data.zones || [])",
            '$("negative").value = negative;',
            "zoneQuickRow",
            "mergeZonesText(selected.join",
            "positionZonePopover",
            '"prompt-general",',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        for removed in ("enhanceZoneDraft", "zoneNaturalRow", "zoneDrafts"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, text)


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

    def test_referencia_se_ajusta_cover_al_tamano_pedido(self):
        source = Image.new("RGB", (128, 256), (10, 20, 30))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        raw = base64.b64encode(buffer.getvalue()).decode("ascii")
        client = self.make_client()
        response = client.post(
            "/api/generate",
            json=self.payload(ref_image_b64=raw, size="cuadro_hd", strength=0.5),
        )
        self.assertEqual(response.status_code, 200)
        row = self.store.list()[0]
        path = self.config.comfy_root / "input" / row["params"]["ref_image"]
        with Image.open(path) as image:
            self.assertEqual(image.size, (1024, 1024))

    def test_referencia_sin_tamano_conserva_dimensiones(self):
        source = Image.new("RGB", (128, 256), (10, 20, 30))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        raw = base64.b64encode(buffer.getvalue()).decode("ascii")
        response = self.make_client().post(
            "/api/generate", json=self.payload(ref_image_b64=raw, strength=0.5)
        )
        self.assertEqual(response.status_code, 200)
        row = self.store.list()[0]
        path = self.config.comfy_root / "input" / row["params"]["ref_image"]
        with Image.open(path) as image:
            self.assertEqual(image.size, (128, 256))


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
    MIKU_FILE = "anima\\Miku_Nakano_Anima_v0.7.safetensors"

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
            json=self.payload(loras=[{"id": "miku-nakano-anima", "weight": 0.8}]),
        )
        self.assertEqual(response.status_code, 200)
        expected = [
            {
                "id": "miku-nakano-anima",
                "file": self.MIKU_FILE,
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
            [{"id": "miku-nakano-anima", "weight": 3.0}],
            [{"id": "miku-nakano-anima", "weight": True}],
            [{}],
            ["miku-nakano-anima"],
            {"id": "miku-nakano-anima"},
            "miku-nakano-anima",
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

    def test_cancel_queued_sin_store_inyectado_marca_el_store_real(self):
        """Camino real `create_app(start_worker=False)` sin store inyectado.

        Con el bug (handler usando el parametro `store`, None en produccion)
        este POST devolvia 500; debe usar `app.state.store` y marcar cancelled.
        """
        patcher = mock.patch.dict(
            os.environ, {"WAIFU_DATA_DIR": str(self.config.data_dir)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        registry_dir = self.config.data_dir / "registry"
        registry_dir.mkdir(parents=True, exist_ok=True)
        (registry_dir / "models.json").write_text(
            REGISTRY_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        app = create_app(start_worker=False)
        client = TestClient(app)
        self.addCleanup(client.close)
        response = client.post("/api/generate", json=self.payload())
        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        cancel = client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(cancel.json(), {"status": "cancelled"})
        real_store = Store(self.config.data_dir / "waifu.db")
        rows = real_store.list()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "cancelled")
        self.assertEqual(
            client.get(f"/api/jobs/{job_id}").json()["status"], "cancelled"
        )


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
            loras=[{"id": "miku-nakano-anima", "weight": 0.8}]
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
        self.assertEqual(graph["lora_1"]["class_type"], "WaifuAnimaPatch28to40")
        self.assertEqual(
            graph["lora_1"]["inputs"],
            {
                "model": ["1", 0],
                "lora_name": "anima\\Miku_Nakano_Anima_v0.7.safetensors",
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


class DownloadRouteTests(ServerTestCase):
    def test_download_200_adjunto(self):
        gen_id = self.store.add(MODEL_ID, "p", status="done")
        self.add_gallery_png(gen_id, "ok.png")
        response = self.make_client().get(f"/api/download/{gen_id}/ok.png")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "attachment", response.headers.get("content-disposition", "").lower()
        )
        self.assertIn("ok.png", response.headers.get("content-disposition", ""))
        self.assertEqual(response.content, PNG_BYTES)

    def test_download_404_y_confinamiento(self):
        client = self.make_client()
        missing = client.get("/api/download/999/ok.png")
        self.assertEqual(missing.status_code, 404)
        gen_id = self.store.add(MODEL_ID, "p", status="done")
        self.add_gallery_png(gen_id, "ok.png")
        outside = self.make_client().get(f"/api/download/{gen_id}/..%2F..%2Fescape.png")
        self.assertIn(outside.status_code, (403, 404))


class ApiRefsTests(ServerTestCase):
    def write_input(self, name: str, data: bytes = PNG_BYTES) -> Path:
        directory = self.config.comfy_root / "input"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(data)
        return path

    def test_200_sirve_png_temporal_de_comfy_input(self):
        self.write_input("ref_ok.png")
        response = self.make_client().get("/api/refs/ref_ok.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, PNG_BYTES)

    def test_200_formatos_jpg_y_webp(self):
        client = self.make_client()
        for name, media_type in (
            ("ref.jpg", "image/jpeg"),
            ("ref.webp", "image/webp"),
        ):
            with self.subTest(name=name):
                self.write_input(name)
                response = client.get(f"/api/refs/{name}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], media_type)

    def test_traversal_403(self):
        (self.config.comfy_root / "input").mkdir(parents=True, exist_ok=True)
        (self.config.comfy_root / "secret.png").write_bytes(PNG_BYTES)
        response = self.make_client().get("/api/refs/..%2F..%2Fsecret.png")
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_extension_no_permitida_403(self):
        self.write_input("nota.txt", b"hola")
        response = self.make_client().get("/api/refs/nota.txt")
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_ausente_404(self):
        response = self.make_client().get("/api/refs/nope.png")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_relee_la_referencia_guardada_por_generate(self):
        raw = base64.b64encode(PNG_BYTES).decode("ascii")
        client = self.make_client()
        response = client.post(
            "/api/generate",
            json={
                "model_id": MODEL_ID,
                "prompt": "1girl, smile",
                "preprompt": "ninguno",
                "params": {"seed": 7, "steps": 12},
                "ref_image_b64": raw,
                "strength": 0.45,
            },
        )
        self.assertEqual(response.status_code, 200)
        row = self.store.list()[0]
        self.assertEqual(row["params"]["seed"], 7)
        self.assertEqual(row["params"]["steps"], 12)
        self.assertEqual(row["params"]["strength"], 0.45)
        name = row["params"]["ref_image"]
        self.assertTrue(name.endswith(".png"))
        served = client.get(f"/api/refs/{name}")
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.content, PNG_BYTES)


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


class GalleryKindFilterTests(ServerTestCase):
    """M9-D2b-fix: `kind` filtra el feed y `count` (paginacion del visor)."""

    def seed_mixed(self) -> tuple[list[int], list[int]]:
        images = [self.store.add(MODEL_ID, f"1girl {index}") for index in range(3)]
        videos = [
            self.store.add("wan", f"motion {index}", "", {}, kind="video")
            for index in range(4)
        ]
        return images, videos

    def test_kind_video_filtra_count_y_orden_desc(self):
        _images, videos = self.seed_mixed()
        data = self.make_client().get(
            "/api/gallery", params={"kind": "video", "limit": 5}
        ).json()
        self.assertEqual(data["count"], 4)
        self.assertEqual([item["id"] for item in data["items"]], list(reversed(videos)))
        self.assertTrue(all(item["kind"] == "video" for item in data["items"]))

    def test_kind_image_filtra_y_pagina_con_offset(self):
        images, _videos = self.seed_mixed()
        client = self.make_client()
        page1 = client.get(
            "/api/gallery", params={"kind": "image", "limit": 2, "offset": 0}
        ).json()
        self.assertEqual(page1["count"], 3)
        self.assertEqual([item["id"] for item in page1["items"]], [images[2], images[1]])
        page2 = client.get(
            "/api/gallery", params={"kind": "image", "limit": 2, "offset": 2}
        ).json()
        self.assertEqual(page2["count"], 3)
        self.assertEqual([item["id"] for item in page2["items"]], [images[0]])

    def test_kind_desconocido_400(self):
        response = self.make_client().get("/api/gallery", params={"kind": "nope"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "kind invalido; usar image|video")

    def test_sin_kind_mantiene_feed_mixto(self):
        images, videos = self.seed_mixed()
        data = self.make_client().get("/api/gallery").json()
        self.assertEqual(data["count"], 7)
        self.assertEqual(
            [item["id"] for item in data["items"]],
            list(reversed(videos)) + list(reversed(images)),
        )


class TagsRoutesTests(ServerTestCase):
    def test_groups(self):
        response = self.make_client().get("/api/tags/groups")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"groups": list_groups()})
        self.assertEqual(len(response.json()["groups"]), len(list_groups()))

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
            {
                "tag": "long hair",
                "label": "Cabello largo",
                "group": "hair",
                "rank": 0,
            },
        )
        limited = client.get("/api/tags", params={"limit": 0}).json()
        self.assertEqual(len(limited["items"]), 1)


class CharactersRoutesTests(ServerTestCase):
    def test_crud(self):
        client = self.make_client()
        created = client.post(
            "/api/characters",
            json={"name": "Aiko", "tags": ["long hair", "school uniform"]},
        )
        self.assertEqual(created.status_code, 200)
        char_id = created.json()["id"]
        listing = client.get("/api/characters")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)
        self.assertEqual(listing.json()[0]["name"], "Aiko")
        self.assertEqual(listing.json()[0]["tags"], ["long hair"])
        self.assertEqual(listing.json()[0]["extras"], ["school uniform"])
        got = client.get(f"/api/characters/{char_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["tags"], ["long hair"])
        self.assertEqual(got.json()["extras"], ["school uniform"])
        updated = client.put(
            f"/api/characters/{char_id}",
            json={"name": "Mika", "rating": "nsfw", "extras": []},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Mika")
        self.assertEqual(updated.json()["rating"], "nsfw")
        self.assertEqual(updated.json()["extras"], [])
        deleted = client.delete(f"/api/characters/{char_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(client.get(f"/api/characters/{char_id}").status_code, 404)

    def test_add_con_extras_explicito(self):
        client = self.make_client()
        created = client.post(
            "/api/characters",
            json={
                "name": "Aiko",
                "tags": ["long hair"],
                "extras": ["blue sky"],
            },
        )
        self.assertEqual(created.status_code, 200)
        row = client.get(f"/api/characters/{created.json()['id']}").json()
        self.assertEqual(row["tags"], ["long hair"])
        self.assertEqual(row["extras"], ["blue sky"])

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


class CharacterProfileRoutesTests(ServerTestCase):
    def add_character(self, client, tags=None, extras=None) -> int:
        payload = {"name": "Aiko", "tags": tags if tags is not None else []}
        if extras is not None:
            payload["extras"] = extras
        return client.post("/api/characters", json=payload).json()["id"]

    def write_loras(self, entries: list[dict]) -> Path:
        path = self.config.data_dir / "loras-test.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"version": 1, "loras": entries}), encoding="utf-8"
        )
        return path

    def lora_entry(self, lora_id: str, trigger: str = "aiko") -> dict:
        return {
            "id": lora_id,
            "family": "anima",
            "file": f"{lora_id}.safetensors",
            "display_name": lora_id,
            "trigger": trigger,
            "default_weight": 0.7,
            "source": "test",
            "license": "test",
        }

    def test_200_traits_con_extras(self):
        client = self.make_client()
        char_id = self.add_character(
            client, ["long hair", "school uniform", "blue sky"]
        )
        path = self.write_loras([self.lora_entry("otro-lora")])
        with mock.patch.object(loras_module, "DEFAULT_PATH", path):
            response = client.get(f"/api/characters/{char_id}/profile")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "text": "long hair",
                "mode": "traits",
                "extras": ["school uniform", "blue sky"],
                "lora": None,
            },
        )

    def test_200_auto_trigger_y_traits_con_lora(self):
        client = self.make_client()
        char_id = self.add_character(client, ["long hair", "blue eyes"])
        path = self.write_loras([self.lora_entry(f"oc-{char_id}", "aiko_oc")])
        with mock.patch.object(loras_module, "DEFAULT_PATH", path):
            auto = client.get(f"/api/characters/{char_id}/profile")
            traits = client.get(
                f"/api/characters/{char_id}/profile", params={"mode": "traits"}
            )
            trigger = client.get(
                f"/api/characters/{char_id}/profile", params={"mode": "trigger"}
            )
        self.assertEqual(auto.status_code, 200)
        self.assertEqual(auto.json()["mode"], "trigger")
        self.assertEqual(auto.json()["text"], "aiko_oc")
        self.assertEqual(
            auto.json()["lora"], {"id": f"oc-{char_id}", "default_weight": 0.7}
        )
        self.assertEqual(traits.json()["mode"], "traits")
        self.assertEqual(traits.json()["text"], "long hair, blue eyes")
        self.assertEqual(traits.json()["lora"]["id"], f"oc-{char_id}")
        self.assertEqual(trigger.json()["text"], "aiko_oc")

    def test_404_oc_inexistente(self):
        client = self.make_client()
        response = client.get("/api/characters/99/profile")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_400_mode_invalido(self):
        client = self.make_client()
        char_id = self.add_character(client, ["long hair"])
        response = client.get(
            f"/api/characters/{char_id}/profile", params={"mode": "nope"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


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
        self.assertIs(ref["is_sheet"], False)
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
        self.assertTrue(Path(data["relpath"]).name.startswith("sheet_"))
        refs = client.get(f"/api/characters/{char_id}/refs").json()
        self.assertEqual(len(refs), len(before) + 1)
        self.assertEqual(refs[-1]["relpath"], data["relpath"])
        self.assertEqual(refs[-1]["url"], data["url"])
        self.assertIs(refs[-1]["is_sheet"], True)

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

    def test_auto_tags_y_tag_threshold_invalidos_400(self):
        client = self.make_client()
        char_id = self.add_character(client)
        for payload in (
            {"gen_ids": list(range(10)), "auto_tags": 1},
            {"gen_ids": list(range(10)), "auto_tags": "si"},
            {"gen_ids": list(range(10)), "auto_tags": None},
            {"gen_ids": list(range(10)), "tag_threshold": 0},
            {"gen_ids": list(range(10)), "tag_threshold": 1.0},
            {"gen_ids": list(range(10)), "tag_threshold": "0.5"},
            {"gen_ids": list(range(10)), "tag_threshold": True},
        ):
            with self.subTest(payload=payload):
                response = client.post(
                    f"/api/characters/{char_id}/train", json=payload
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(self.store.count(), 0)

    def test_encola_job_train_con_auto_tags_y_umbral(self):
        queue = RecordingQueue()
        client = self.make_client(queue=queue)
        char_id = self.add_character(client)
        response = client.post(
            f"/api/characters/{char_id}/train", json={"gen_ids": list(range(10))}
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[0]
        self.assertIs(job["auto_tags"], True)
        self.assertEqual(job["tag_threshold"], WD14_THRESHOLD)
        response = client.post(
            f"/api/characters/{char_id}/train",
            json={
                "gen_ids": list(range(10)),
                "auto_tags": False,
                "tag_threshold": 0.6,
            },
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[1]
        self.assertIs(job["auto_tags"], False)
        self.assertEqual(job["tag_threshold"], 0.6)
        rows = self.store.list(order="asc")
        self.assertEqual(rows[0]["params"]["auto_tags"], True)
        self.assertEqual(rows[0]["params"]["tag_threshold"], WD14_THRESHOLD)
        self.assertEqual(rows[1]["params"]["auto_tags"], False)
        self.assertEqual(rows[1]["params"]["tag_threshold"], 0.6)

    def test_job_status_train_progress_del_job(self):
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        char_id = self.add_character(client)
        job_id = client.post(
            f"/api/characters/{char_id}/train", json={"gen_ids": list(range(10))}
        ).json()["job_id"]
        queue.jobs[0]["progress"] = {
            "step": 3,
            "total": 10,
            "percent": 30.0,
            "node": "tags",
            "state": "running",
        }
        status = client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(
            status["progress"],
            {
                "step": 3,
                "total": 10,
                "percent": 30.0,
                "node": "tags",
                "state": "running",
            },
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


class FakeTrainerVision:
    """Vision falsa del entrenador: WD14 instalado configurable y tagger fijo."""

    def __init__(self, *, installed: bool = True, tags=None) -> None:
        self.installed = installed
        self.tags = ["long hair", "smile"] if tags is None else list(tags)
        self.tagger_calls: list[tuple] = []

    def wd14_installed(self) -> bool:
        return self.installed

    def tagger_for(self, threshold=None, character_threshold=None):
        self.tagger_calls.append((threshold, character_threshold))
        return lambda raw: list(self.tags)


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

    def add_images(self, count: int = 10) -> list[int]:
        gen_ids: list[int] = []
        for _ in range(count):
            gen_id = self.store.add(MODEL_ID, "1girl", kind="image")
            self.store.update(gen_id, status="done", outputs=["ok.png"])
            self.add_gallery_png(gen_id, "ok.png")
            gen_ids.append(gen_id)
        return gen_ids

    def run_with_fake_trainer(self, job: dict, vision=None) -> None:
        lora = self.config.data_dir / "trainer" / "1.safetensors"

        def fake_run(config_path, **kwargs) -> int:
            lora.parent.mkdir(parents=True, exist_ok=True)
            lora.write_bytes(b"lora")
            return 0

        with mock.patch.object(
            server_module.trainer, "run_training", side_effect=fake_run
        ), mock.patch.object(
            server_module.trainer, "register_lora", return_value={"id": "oc-1"}
        ):
            server_module.run_training_job(
                job, config=self.config, store=self.store, vision=vision
            )

    def read_manifest(self) -> dict:
        path = self.config.data_dir / "trainer" / "1" / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

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

    def test_auto_tags_escribe_manifest_y_progress(self):
        job = self.make_job(
            gen_ids=self.add_images(), auto_tags=True, tag_threshold=0.5
        )
        vision = FakeTrainerVision()
        self.run_with_fake_trainer(job, vision)
        self.assertIsNone(job["error"])
        manifest = self.read_manifest()
        self.assertIs(manifest["auto_tags"], True)
        self.assertEqual(manifest["tag_threshold"], 0.5)
        self.assertEqual(manifest["images"][0]["wd14_tags"], ["long hair", "smile"])
        self.assertEqual(manifest["images"][0]["prompt"], "aiko, long hair, smile")
        self.assertEqual(vision.tagger_calls, [(0.5, None)])
        self.assertEqual(job["progress"]["node"], "tags")
        self.assertEqual(job["progress"]["step"], 10)
        self.assertEqual(job["progress"]["total"], 10)
        self.assertEqual(job["progress"]["percent"], 100.0)
        self.assertEqual(self.store.get(job["gen_id"])["status"], "done")

    def test_sin_vision_o_auto_tags_false_cae_a_tags_oc(self):
        for overrides, vision in (
            ({"auto_tags": False}, FakeTrainerVision()),
            ({"auto_tags": True}, None),
            ({"auto_tags": True}, FakeTrainerVision(installed=False)),
        ):
            with self.subTest(overrides=overrides, vision=vision):
                job = self.make_job(
                    gen_ids=self.add_images(), tag_threshold=0.5, **overrides
                )
                self.run_with_fake_trainer(job, vision)
                self.assertIsNone(job["error"])
                manifest = self.read_manifest()
                self.assertIs(manifest["auto_tags"], False)
                self.assertEqual(manifest["tag_threshold"], 0.5)
                self.assertEqual(manifest["images"][0]["wd14_tags"], [])
                self.assertEqual(manifest["images"][0]["prompt"], "aiko, smile")
                if vision is not None:
                    self.assertEqual(vision.tagger_calls, [])
                self.assertEqual(job["progress"]["node"], "tags")


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
        self.assertIn("/static/js/main.js", response.text)
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
            'id="ref-preview"',
            'id="btn-ref-clear"',
            'id="lightbox"',
            'id="gallery-prev"',
            'id="gallery-next"',
            'id="btn-cancel"',
            'id="job-progress"',
            'id="job-progress-fill"',
            'id="job-progress-text"',
            'id="prompt-general"',
            'id="prompt-zones"',
            'id="zone-editor"',
            'id="prompt-final"',
            'id="btn-copy-prompt"',
            'id="zone-insert-form"',
            'id="zone-insert-input"',
            'id="zone-insert-cancel"',
            'id="zone-popover"',
            'id="zone-popover-search"',
            'id="zone-popover-tabs"',
            'id="zone-popover-groups"',
            'id="zone-popover-insert"',
            'id="oc-refs-note"',
            "IPAdapter",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_incluye_endpoints_y_features(self):
        text = self.get_static_js()
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
            "/api/prompt/options",
            "addTagsToZone",
            "composePrompt",
            "renderZoneEditor",
            "openZoneInsert",
            "zonePopover",
            "Fijado por el OC",
            "/api/refs/",
            "reuseGeneration",
            "applySavedReference",
            "isSheetRef",
            "Usar como referencia",
            "IPAdapter (M10)",
            "no se adjunta como referencia I2I",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class CacheHeaderTests(ServerTestCase):
    def test_ui_sin_cache_y_api_intacta(self):
        client = self.make_client()
        index = client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertEqual(index.headers.get("cache-control"), "no-store")
        script = client.get("/static/js/main.js")
        self.assertEqual(script.status_code, 200)
        self.assertEqual(script.headers.get("cache-control"), "no-store")
        models = client.get("/api/models")
        self.assertEqual(models.status_code, 200)
        self.assertNotIn("cache-control", models.headers)


class StartupHardeningUiStaticTests(ServerTestCase):
    def test_app_js_blindado_por_secciones(self):
        text = self.get_static_js()
        for marker in (
            "REQUIRED_IDS",
            "UI desactualizada: recarga con Ctrl+F5",
            "const settle = async",
            'setStatus(`Fallaron: ${failures.join(", ")}`, true)',
            "No hay LoRAs de imagen registradas",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_required_ids_todos_presentes_en_index_html(self):
        client = self.make_client()
        html = client.get("/").text
        main_js = client.get("/static/js/main.js").text
        import re

        html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', html))
        match = re.search(r"const REQUIRED_IDS = \[(.*?)\];", main_js, re.DOTALL)
        self.assertIsNotNone(match, "REQUIRED_IDS debe estar declarado en main.js")
        req_ids = [
            s.strip().strip('"\'')
            for s in match.group(1).split(",")
            if s.strip().strip('"\'')
        ]
        missing = [rid for rid in req_ids if rid not in html_ids]
        self.assertEqual(
            missing,
            [],
            f"Faltan elementos de REQUIRED_IDS en templates/index.html: {missing}",
        )


class CharacterProfileUiStaticTests(ServerTestCase):
    def test_index_incluye_oc_picker_y_extras(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="zone-popover-ocs"',
            'id="zone-ocs-list"',
            'id="zone-ocs-extras"',
            'id="zone-ocs-traits"',
            "aplicar extras del OC a General",
            "usar rasgos en vez del trigger",
            'id="oc-extras-box"',
            'id="btn-oc-extras-move"',
            "Mover a General",
            "Solo rasgos del personaje",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_compone_oc_via_profile(self):
        text = self.get_static_js()
        for marker in (
            "OC_TRAIT_GROUPS",
            "/api/characters/${character.id}/profile",
            "?mode=",
            "fetchCharacterProfile",
            "applyOcFromPicker",
            "zoneOcApplied",
            "selectLora",
            "moveOcExtrasToGeneral",
            "addTagsToZone",
            "removeTagsFromZones",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class EditorStatusTests(ServerTestCase):
    def test_status_forma_e_installed_false_con_temp_root(self):
        response = self.make_client().get("/api/editor/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"installed", "model", "expected", "note"})
        self.assertIs(data["installed"], False)
        self.assertEqual(data["model"], "qwen-image-2.1")
        self.assertIsInstance(data["expected"], list)
        self.assertEqual(data["expected"], list(server_module.EDITOR_MODEL_FILES))
        self.assertTrue(
            all(isinstance(item, str) and item for item in data["expected"])
        )
        self.assertTrue(
            all(not Path(item).is_absolute() for item in data["expected"])
        )
        self.assertIn("M10", data["note"])

    def test_expected_apunta_a_los_nombres_uc(self):
        data = self.make_client().get("/api/editor/status").json()
        self.assertEqual(
            data["expected"],
            [
                "unet/qwen-image-2.1-UC-Q4_K_M.gguf",
                "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
                "vae/qwen_image_2.1_vae_bf16.safetensors",
            ],
        )
        self.assertNotIn("vae/qwen_image_vae.safetensors", data["expected"])

    def test_vae_de_anima_no_desbloquea_el_editor(self):
        path = (
            self.config.comfy_root
            / "models"
            / "vae"
            / "qwen_image_vae.safetensors"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"anima-vae")
        data = self.make_client().get("/api/editor/status").json()
        self.assertIs(data["installed"], False)
        response = self.make_client().post(
            "/api/editor/generate", json={"prompt": "1girl"}
        )
        self.assertEqual(response.status_code, 503)

    def test_installed_true_solo_con_todos_los_archivos(self):
        for relative in server_module.EDITOR_MODEL_FILES:
            path = self.config.comfy_root / "models" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-model")
        data = self.make_client().get("/api/editor/status").json()
        self.assertIs(data["installed"], True)

    def test_installed_false_con_archivos_parciales(self):
        relative = server_module.EDITOR_MODEL_FILES[0]
        path = self.config.comfy_root / "models" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-model")
        data = self.make_client().get("/api/editor/status").json()
        self.assertIs(data["installed"], False)

    def test_gguf_en_diffusion_models_desbloquea_el_editor(self):
        for index, relative in enumerate(server_module.EDITOR_MODEL_FILES):
            if index == 0:
                relative = "diffusion_models/" + relative.split("/", 1)[1]
            path = self.config.comfy_root / "models" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-model")
        data = self.make_client().get("/api/editor/status").json()
        self.assertIs(data["installed"], True)


class EditorGenerateValidationTests(ServerTestCase):
    def install_editor(self):
        for relative in server_module.EDITOR_MODEL_FILES:
            path = self.config.comfy_root / "models" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-model")

    def test_size_original_hereda_la_primera_referencia(self):
        self.install_editor()
        source = Image.new("RGB", (640, 960), (5, 6, 7))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        raw = base64.b64encode(buffer.getvalue()).decode("ascii")
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/editor/generate",
            json={
                "prompt": "edit",
                "mode": "edit",
                "size": {"original": True},
                "ref_images_b64": [raw],
            },
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[0]
        self.assertEqual((job["width"], job["height"]), (640, 960))
        self.assertIs(job["params"]["original_size"], True)

    def test_size_original_sin_referencias_400(self):
        self.install_editor()
        response = self.make_client().post(
            "/api/editor/generate",
            json={"prompt": "edit", "mode": "edit", "size": {"original": True}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_edit_sin_referencias_400(self):
        self.install_editor()
        response = self.make_client().post(
            "/api/editor/generate", json={"prompt": "edit", "mode": "edit"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_prompt_vacio_o_no_str_400(self):
        client = self.make_client()
        for payload in ({}, {"prompt": ""}, {"prompt": "   "}, {"prompt": 7}):
            with self.subTest(payload=payload):
                response = client.post("/api/editor/generate", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_mode_invalido_400(self):
        response = self.make_client().post(
            "/api/editor/generate", json={"prompt": "1girl", "mode": "nope"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("mode", response.json()["error"])

    def test_mode_ausente_default_generate(self):
        response = self.make_client().post(
            "/api/editor/generate", json={"prompt": "1girl"}
        )
        self.assertEqual(response.status_code, 503)

    def test_mas_de_diez_refs_400(self):
        refs = [base64.b64encode(b"img").decode("ascii")] * 11
        response = self.make_client().post(
            "/api/editor/generate", json={"prompt": "1girl", "ref_images_b64": refs}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("10", response.json()["error"])

    def test_refs_no_lista_400(self):
        response = self.make_client().post(
            "/api/editor/generate", json={"prompt": "1girl", "ref_images_b64": "no"}
        )
        self.assertEqual(response.status_code, 400)

    def test_b64_invalido_400(self):
        client = self.make_client()
        for refs in (["@@no-base64@@"], [""], [None]):
            with self.subTest(refs=refs):
                response = client.post(
                    "/api/editor/generate",
                    json={"prompt": "1girl", "ref_images_b64": refs},
                )
                self.assertEqual(response.status_code, 400)

    def test_size_fuera_de_rango_o_no_multiplo_16_400(self):
        client = self.make_client()
        for size in (
            {"width": 511, "height": 1024},
            {"width": 1024, "height": 2049},
            {"width": 1000, "height": 1024},
            {"width": 1024.5, "height": 1024},
            {"width": "x", "height": 1024},
            {"width": 1024},
            {"width": True, "height": 1024},
        ):
            with self.subTest(size=size):
                response = client.post(
                    "/api/editor/generate", json={"prompt": "1girl", "size": size}
                )
                self.assertEqual(response.status_code, 400)

    def test_size_no_dict_400(self):
        response = self.make_client().post(
            "/api/editor/generate", json={"prompt": "1girl", "size": [1024, 1024]}
        )
        self.assertEqual(response.status_code, 400)

    def test_seed_invalida_400(self):
        response = self.make_client().post(
            "/api/editor/generate", json={"prompt": "1girl", "seed": "x"}
        )
        self.assertEqual(response.status_code, 400)

    def test_steps_invalidos_400(self):
        client = self.make_client()
        for steps in (9, 51, "x", True, 25.5):
            with self.subTest(steps=steps):
                response = client.post(
                    "/api/editor/generate",
                    json={"prompt": "1girl", "steps": steps},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_cfg_invalido_400(self):
        client = self.make_client()
        for cfg in (0.9, 10.1, "x", True):
            with self.subTest(cfg=cfg):
                response = client.post(
                    "/api/editor/generate",
                    json={"prompt": "1girl", "cfg": cfg},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_steps_y_cfg_validos_en_cola_y_params(self):
        self.install_editor()
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/editor/generate",
            json={"prompt": "1girl", "steps": 30, "cfg": 2.5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"job_id": "job-1"})
        job = queue.jobs[0]
        self.assertEqual(job["steps"], 30)
        self.assertEqual(job["cfg"], 2.5)
        self.assertEqual(job["params"]["steps"], 30)
        self.assertEqual(job["params"]["cfg"], 2.5)
        self.assertEqual(server_module._JOBS[1]["status"], "queued")

    def test_steps_y_cfg_ausentes_usan_defaults(self):
        self.install_editor()
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/editor/generate", json={"prompt": "1girl"}
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[0]
        self.assertEqual(job["steps"], server_module.EDITOR_DEFAULT_STEPS)
        self.assertEqual(job["cfg"], server_module.EDITOR_DEFAULT_CFG)
        self.assertEqual(job["params"]["steps"], server_module.EDITOR_DEFAULT_STEPS)
        self.assertEqual(job["params"]["cfg"], server_module.EDITOR_DEFAULT_CFG)

    def test_api_job_expone_params_prompt_y_negativo(self):
        self.install_editor()
        queue = StatusQueue()
        client = self.make_client(queue=queue)
        response = client.post(
            "/api/editor/generate",
            json={
                "prompt": "1girl",
                "negative": "lowres",
                "steps": 30,
                "cfg": 2.5,
            },
        )
        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        status = client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(status["status"], "queued")
        self.assertEqual(status["prompt"], "1girl")
        self.assertEqual(status["negative"], "lowres")
        self.assertEqual(status["params"]["steps"], 30)
        self.assertEqual(status["params"]["cfg"], 2.5)

    def test_validaciones_antes_de_la_guarda_503(self):
        response = self.make_client().post(
            "/api/editor/generate",
            json={"prompt": "", "mode": "nope", "size": {"width": 1, "height": 1}},
        )
        self.assertEqual(response.status_code, 400)


class EditorGenerateGuardTests(ServerTestCase):
    def test_503_sin_instalacion(self):
        response = self.make_client().post(
            "/api/editor/generate",
            json={
                "prompt": "1girl, smile",
                "mode": "generate",
                "size": {"width": 1024, "height": 1024},
                "seed": 42,
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "modelo no instalado (M10)"})

    def test_503_con_refs_y_edit(self):
        ref = base64.b64encode(PNG_BYTES).decode("ascii")
        response = self.make_client().post(
            "/api/editor/generate",
            json={"prompt": "edit this", "mode": "edit", "ref_images_b64": [ref]},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "modelo no instalado (M10)"})

    def test_encola_de_verdad_con_instalacion_completa(self):
        for relative in server_module.EDITOR_MODEL_FILES:
            path = self.config.comfy_root / "models" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-model")
        queue = RecordingQueue()
        response = self.make_client(queue=queue).post(
            "/api/editor/generate",
            json={
                "prompt": "1girl",
                "mode": "edit",
                "negative": "low quality",
                "ref_images_b64": [
                    base64.b64encode(PNG_BYTES).decode("ascii")
                ],
                "size": {"width": 512, "height": 2048},
                "seed": 7,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"job_id": "job-1"})
        self.assertEqual(len(queue.jobs), 1)
        job = queue.jobs[0]
        self.assertEqual(job["kind"], "editor")
        self.assertEqual(job["prompt"], "1girl")
        self.assertEqual(job["negative"], "low quality")
        self.assertEqual(job["seed"], 7)
        self.assertEqual((job["width"], job["height"]), (512, 2048))
        self.assertEqual(job["params"]["task"], "editor")
        self.assertEqual(job["params"]["mode"], "edit")
        self.assertEqual(len(job["params"]["ref_images"]), 1)
        ref_path = (
            self.config.comfy_root / "input" / job["params"]["ref_images"][0]
        )
        self.assertTrue(ref_path.is_file())
        self.assertEqual(ref_path.read_bytes(), PNG_BYTES)
        row = self.store.get(1)
        self.assertEqual(row["kind"], "image")
        self.assertEqual(row["model_id"], server_module.EDITOR_MODEL)
        self.assertEqual(row["negative"], "low quality")
        self.assertEqual(row["params"]["task"], "editor")
        self.assertEqual(server_module._JOBS[1]["kind"], "editor")
        self.assertEqual(server_module._JOBS[1]["status"], "queued")


class EditorUiStaticTests(ServerTestCase):
    def test_index_incluye_pestana_y_controles_editor(self):
        text = self.make_client().get("/").text
        self.assertIn('<option value="edit" selected>Editar</option>', text)
        for marker in (
            'id="tab-editor"',
            ">Editor<",
            'id="panel-editor"',
            'id="editor-banner"',
            'id="editor-prompt"',
            'id="editor-mode"',
            ">Generar<",
            ">Editar<",
            'id="editor-refs"',
            'id="editor-refs-preview"',
            'id="editor-size"',
            'id="editor-manual-size"',
            'id="editor-width"',
            'id="editor-height"',
            'id="editor-seed"',
            'id="editor-negative"',
            'id="editor-steps"',
            'id="editor-cfg"',
            'id="editor-cfg-note"',
            'id="editor-edit-hint"',
            'id="editor-refs-field"',
            'id="editor-refs-hint"',
            'id="editor-preview"',
            'id="editor-preview-img"',
            'id="editor-preview-empty"',
            'id="editor-result"',
            'id="btn-editor-open-gallery"',
            'id="btn-editor-generate"',
            'id="editor-progress"',
            'id="editor-progress-fill"',
            'id="editor-progress-text"',
            'id="editor-status"',
            "múltiplos de 16",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_incluye_editor_y_guarda(self):
        text = self.get_static_js()
        for marker in (
            "/api/editor/status",
            "/api/editor/generate",
            'switchTab("editor")',
            "Qwen-Image 2.1 no instalado",
            "Qwen-Image 2.1 instalado",
            "EDITOR_REF_LIMIT",
            "EDITOR_SIZE_MIN",
            "updateEditorControls",
            "state.editorInstalled",
            "addEditorRefs",
            "removeEditorRef",
            "setEditorProgress",
            "generateEditor",
            "fillEditorSizes",
            "applyEditorSizeSelection",
            "showEditorResult",
            "updateEditorMode",
            "syncEditorEditSource",
            "setEditorEditSource",
            "updateEditorPreview",
            "applyEditorMetadata",
            '$("editor-negative")',
            '$("editor-steps")',
            '$("editor-cfg")',
            "pollJob(",
            "reloadImageViewerFirstPage",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_editor_comparador_ui(self):
        html = self.make_client().get("/").text
        for marker in (
            'id="btn-editor-compare"',
            'id="editor-compare"',
            'id="editor-compare-stage"',
            'id="editor-compare-before"',
            'id="editor-compare-after"',
            'id="editor-compare-handle"',
            'id="editor-compare-ratio"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        script = self.get_static_js()
        for marker in (
            "function setEditorCompareEnabled",
            "function updateEditorCompare",
            "function applyEditorCompare",
            "function initEditorCompareInteractions",
            'on("btn-editor-compare", "click"',
            'stage.addEventListener("wheel", zoomEditorCompare, { passive: false })',
            '"btn-editor-compare",',
            '"editor-compare",',
            '"editor-compare-stage",',
            '"editor-compare-before",',
            '"editor-compare-after",',
            '"editor-compare-handle",',
            '"editor-compare-ratio",',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)


class LightboxUiStaticTests(ServerTestCase):
    def test_index_lightbox_sin_ids_duplicados(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="lightbox"',
            'id="lightbox-img"',
            'id="btn-lightbox-close"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertEqual(text.count('id="lightbox"'), 1)
        self.assertEqual(text.count('id="lightbox-img"'), 1)

    def test_app_js_expansion_y_zoom_del_lightbox(self):
        text = self.get_static_js()
        for marker in (
            "function openLightbox",
            "function zoomLightbox",
            "function resetLightboxView",
            "startLightboxPan",
            '"wheel"',
            "{ passive: false }",
            'on("editor-preview", "click"',
            'on("gallery-modal-media", "click"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class SeedDiceUiStaticTests(ServerTestCase):
    def test_index_dado_en_imagen_video_y_editor(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="btn-seed-random"',
            'id="btn-video-seed-random"',
            'id="btn-editor-seed-random"',
            'title="Seed aleatoria"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_dado_compartido_y_roll_por_pestana(self):
        text = self.get_static_js()
        for marker in (
            'applyRandomSeed("video-seed")',
            'applyRandomSeed("editor-seed")',
            "updateSeedRandomButton",
            'on("btn-video-seed-random", "click", () => toggleSeedRandom(setVideoStatus))',
            'on("btn-editor-seed-random", "click", () => toggleSeedRandom(setEditorStatus))',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class DescribeRefUiStaticTests(ServerTestCase):
    def test_index_boton_describir_referencia(self):
        text = self.make_client().get("/").text
        for marker in ('id="btn-describe-ref"', 'id="describe-file"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_flujo_describir_referencia(self):
        text = self.get_static_js()
        for marker in (
            "describeRefFromDisk",
            "describeSelectedRefFile",
            "image_b64: b64",
            'on("btn-describe-ref", "click", describeRefFromDisk)',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class UpscaleRouteTests(ServerTestCase):
    MODEL = "real-esrgan-x2"

    def make_source(self, *, kind: str = "image", outputs=("ok.png",)) -> int:
        gen_id = self.store.add(MODEL_ID, "1girl", "", {}, kind=kind)
        self.store.update(gen_id, status="done", outputs=list(outputs), kind=kind)
        for name in outputs:
            self.add_gallery_png(gen_id, name)
        return gen_id

    def test_modelos_200(self):
        response = self.make_client().get("/api/upscale/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["models"], data["items"])
        self.assertEqual(data["kinds"], ["image", "video", "fps"])
        self.assertEqual([item["id"] for item in data["items"]], [self.MODEL])
        entry = data["items"][0]
        for field in ("id", "label", "file", "scale", "note"):
            self.assertIn(field, entry)
        self.assertEqual(entry["file"], "RealESRGAN_x2.pth")
        self.assertEqual(entry["scale"], 2)
        self.assertEqual(entry["note"], "×2")
        section = data["frame_interpolation"]
        self.assertEqual(section["ckpts"], ["rife417.pth", "rife426.pth", "rife47.pth", "rife49.pth"])
        self.assertEqual(section["default"], "rife49.pth")
        self.assertEqual(section["multipliers"], [2, 4])
        self.assertTrue(section["label"])

    def test_encola_job_y_crea_imagen(self):
        queue = RecordingQueue()
        gen_id = self.make_source()
        response = self.make_client(queue=queue).post(
            "/api/upscale", json={"source_gen": gen_id, "model": self.MODEL}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"job_id": "job-1"})
        self.assertEqual(len(queue.jobs), 1)
        job = queue.jobs[0]
        self.assertEqual(job["kind"], "upscale")
        self.assertEqual(job["source_gen"], gen_id)
        self.assertEqual(job["source_file"], "ok.png")
        self.assertEqual(job["model"], self.MODEL)
        self.assertEqual(job["model_file"], "RealESRGAN_x2.pth")
        self.assertEqual(job["scale"], 2)
        self.assertEqual(job["passes"], 1)
        self.assertEqual(job["sharpen"], 0)
        self.assertEqual(job["params"]["task"], "upscale")
        files = sorted((self.config.comfy_root / "input").glob("*.png"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PNG_BYTES)
        self.assertEqual(job["image_name"], files[0].name)
        new_gen = self.store.list()[0]
        self.assertEqual(new_gen["kind"], "image")
        self.assertEqual(new_gen["status"], "queued")
        self.assertEqual(
            new_gen["params"],
            {
                "task": "upscale",
                "source_gen": gen_id,
                "source_file": "ok.png",
                "model": self.MODEL,
                "scale": 2,
                "passes": 1,
                "sharpen": 0,
            },
        )
        self.assertEqual(server_module._JOBS[new_gen["id"]]["kind"], "upscale")

    def test_image_b64_encola_job_y_escribe_input(self):
        queue = RecordingQueue()
        client = self.make_client(queue=queue)
        image_b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        response = client.post(
            "/api/upscale",
            json={"kind": "image", "image_b64": image_b64, "model": self.MODEL},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"job_id": "job-1"})
        self.assertEqual(len(queue.jobs), 1)
        job = queue.jobs[0]
        self.assertEqual(job["kind"], "upscale")
        self.assertIsNone(job["source_gen"])
        self.assertIsNone(job["source_file"])
        self.assertEqual(job["model"], self.MODEL)
        self.assertEqual(job["model_file"], "RealESRGAN_x2.pth")
        self.assertEqual(job["scale"], 2)
        self.assertEqual(job["passes"], 1)
        files = sorted((self.config.comfy_root / "input").glob("*.png"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PNG_BYTES)
        self.assertEqual(job["image_name"], files[0].name)
        new_gen = self.store.list()[0]
        self.assertEqual(new_gen["kind"], "image")
        self.assertEqual(new_gen["status"], "queued")
        self.assertEqual(
            new_gen["params"],
            {
                "task": "upscale",
                "source_gen": None,
                "source_file": None,
                "model": self.MODEL,
                "scale": 2,
                "passes": 1,
                "sharpen": 0,
            },
        )
        self.assertEqual(server_module._JOBS[new_gen["id"]]["kind"], "upscale")

    def test_image_b64_acepta_data_uri(self):
        queue = RecordingQueue()
        client = self.make_client(queue=queue)
        data_uri = (
            "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
        )
        response = client.post(
            "/api/upscale", json={"image_b64": data_uri, "model": self.MODEL}
        )
        self.assertEqual(response.status_code, 200)
        files = sorted((self.config.comfy_root / "input").glob("*.png"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PNG_BYTES)

    def test_image_b64_exclusivo_con_source_gen_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source()
        client = self.make_client(queue=queue)
        image_b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        response = client.post(
            "/api/upscale",
            json={
                "source_gen": gen_id,
                "image_b64": image_b64,
                "model": self.MODEL,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertEqual(queue.jobs, [])
        self.assertEqual(self.store.count(), 1)
        self.assertFalse((self.config.comfy_root / "input").exists())

    def test_image_sin_fuente_400(self):
        response = self.make_client().post(
            "/api/upscale", json={"model": self.MODEL}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_image_b64_invalido_400(self):
        queue = RecordingQueue()
        client = self.make_client(queue=queue)
        for value in ("", "  ", "no-es-base64!!", 5, True, []):
            with self.subTest(value=value):
                response = client.post(
                    "/api/upscale",
                    json={"image_b64": value, "model": self.MODEL},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(queue.jobs, [])
        self.assertFalse((self.config.comfy_root / "input").exists())

    def test_image_b64_con_video_o_fps_400(self):
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        client = self.make_client()
        image_b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        for kind in ("video", "fps"):
            with self.subTest(kind=kind):
                response = client.post(
                    "/api/upscale",
                    json={
                        "kind": kind,
                        "source_gen": gen_id,
                        "image_b64": image_b64,
                        "model": self.MODEL,
                        "multiplier": 2,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("image_b64", response.json()["error"])

    def test_passes_dos_en_flujo_completo_con_worker(self):
        transport = FakeTransport(self.config, output_name="upscaled_00001_.png")
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
            start_worker=True,
        )
        image_b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        with TestClient(app) as client:
            response = client.post(
                "/api/upscale",
                json={"image_b64": image_b64, "model": self.MODEL, "passes": 2},
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 10)
            status = client.get(f"/api/jobs/{job_id}").json()
            self.assertEqual(status["status"], "done")
            gallery = client.get("/api/gallery?kind=image").json()
            self.assertEqual(gallery["count"], 1)
            newest = gallery["items"][0]
            self.assertEqual(newest["kind"], "image")
            self.assertEqual(newest["params"]["task"], "upscale")
            self.assertEqual(newest["params"]["passes"], 2)
            self.assertIsNone(newest["params"]["source_gen"])
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["3"]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(graph["5"]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(graph["5"]["inputs"]["upscale_model"], ["2", 0])
        self.assertEqual(graph["5"]["inputs"]["image"], ["3", 0])
        self.assertEqual(graph["4"]["inputs"]["images"], ["5", 0])

    def test_passes_invalido_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source()
        client = self.make_client(queue=queue)
        for passes in (0, 3, -1, "2", True, 2.0, []):
            with self.subTest(passes=passes):
                response = client.post(
                    "/api/upscale",
                    json={
                        "source_gen": gen_id,
                        "model": self.MODEL,
                        "passes": passes,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(queue.jobs, [])
        self.assertFalse((self.config.comfy_root / "input").exists())

    def test_passes_con_video_o_fps_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        client = self.make_client(queue=queue)
        for passes in (0, 2, 3, True, "1", 1.0):
            with self.subTest(passes=passes):
                response = client.post(
                    "/api/upscale",
                    json={
                        "kind": "video",
                        "source_gen": gen_id,
                        "model": self.MODEL,
                        "passes": passes,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("passes", response.json()["error"])
        self.assertEqual(queue.jobs, [])
        response = client.post(
            "/api/upscale",
            json={
                "kind": "video",
                "source_gen": gen_id,
                "model": self.MODEL,
                "passes": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("passes", queue.jobs[-1]["params"])

    def test_sharpen_invalido_en_imagen_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source()
        client = self.make_client(queue=queue)
        for sharpen in (3, "x", True, 25.5, -1, [], {}):
            with self.subTest(sharpen=sharpen):
                response = client.post(
                    "/api/upscale",
                    json={
                        "source_gen": gen_id,
                        "model": self.MODEL,
                        "sharpen": sharpen,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(queue.jobs, [])
        self.assertFalse((self.config.comfy_root / "input").exists())

    def test_sharpen_con_video_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        client = self.make_client(queue=queue)
        for sharpen in (1, 2, "x", True, 25.5):
            with self.subTest(sharpen=sharpen):
                response = client.post(
                    "/api/upscale",
                    json={
                        "kind": "video",
                        "source_gen": gen_id,
                        "model": self.MODEL,
                        "sharpen": sharpen,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("sharpen", response.json()["error"])
        self.assertEqual(queue.jobs, [])
        response = client.post(
            "/api/upscale",
            json={
                "kind": "video",
                "source_gen": gen_id,
                "model": self.MODEL,
                "sharpen": 0,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("sharpen", queue.jobs[-1]["params"])

    def test_sharpen_dos_en_flujo_completo_con_worker(self):
        transport = FakeTransport(self.config, output_name="upscaled_00001_.png")
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
            start_worker=True,
        )
        image_b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        with TestClient(app) as client:
            response = client.post(
                "/api/upscale",
                json={"image_b64": image_b64, "model": self.MODEL, "sharpen": 2},
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 10)
            status = client.get(f"/api/jobs/{job_id}").json()
            self.assertEqual(status["status"], "done")
            gallery = client.get("/api/gallery?kind=image").json()
            self.assertEqual(gallery["count"], 1)
            newest = gallery["items"][0]
            self.assertEqual(newest["kind"], "image")
            self.assertEqual(newest["params"]["task"], "upscale")
            self.assertEqual(newest["params"]["sharpen"], 2)
            self.assertEqual(newest["params"]["passes"], 1)
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["6"]["class_type"], "ImageSharpen")
        self.assertEqual(graph["6"]["inputs"]["image"], ["3", 0])
        self.assertEqual(
            graph["6"]["inputs"],
            {
                "image": ["3", 0],
                "sharpen_radius": 2,
                "sigma": 1.0,
                "alpha": 1.2,
            },
        )
        self.assertEqual(graph["4"]["inputs"]["images"], ["6", 0])

    def test_file_explicito_se_usa(self):
        queue = RecordingQueue()
        gen_id = self.make_source(outputs=("a.png", "b.png"))
        response = self.make_client(queue=queue).post(
            "/api/upscale",
            json={"source_gen": gen_id, "file": "b.png", "model": self.MODEL},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(queue.jobs[0]["source_file"], "b.png")
        self.assertEqual(self.store.list()[0]["params"]["source_file"], "b.png")

    def test_modelo_invalido_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source()
        client = self.make_client(queue=queue)
        for model in (None, "", "nope", 5, True):
            with self.subTest(model=model):
                response = client.post(
                    "/api/upscale", json={"source_gen": gen_id, "model": model}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(queue.jobs, [])
        self.assertEqual(self.store.count(), 1)
        self.assertFalse((self.config.comfy_root / "input").exists())

    def test_source_gen_invalido_400(self):
        client = self.make_client()
        for source in (None, "1", 1.5, True, []):
            with self.subTest(source=source):
                response = client.post(
                    "/api/upscale", json={"source_gen": source, "model": self.MODEL}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_source_gen_inexistente_404(self):
        response = self.make_client().post(
            "/api/upscale", json={"source_gen": 999, "model": self.MODEL}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_origen_no_imagen_400(self):
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        response = self.make_client().post(
            "/api/upscale", json={"source_gen": gen_id, "model": self.MODEL}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_file_fuera_de_carpeta_403(self):
        gen_id = self.make_source()
        (self.config.data_dir / "secret.png").write_bytes(PNG_BYTES)
        response = self.make_client().post(
            "/api/upscale",
            json={"source_gen": gen_id, "file": "../secret.png", "model": self.MODEL},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_file_inexistente_o_no_imagen_404(self):
        gen_id = self.make_source()
        client = self.make_client()
        for name in ("missing.png", "nota.txt"):
            with self.subTest(name=name):
                response = client.post(
                    "/api/upscale",
                    json={"source_gen": gen_id, "file": name, "model": self.MODEL},
                )
                self.assertEqual(response.status_code, 404)

    def test_source_sin_salidas_404(self):
        gen_id = self.make_source(outputs=())
        response = self.make_client().post(
            "/api/upscale", json={"source_gen": gen_id, "model": self.MODEL}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_file_no_str_400(self):
        gen_id = self.make_source()
        response = self.make_client().post(
            "/api/upscale", json={"source_gen": gen_id, "file": 5, "model": self.MODEL}
        )
        self.assertEqual(response.status_code, 400)

    def test_video_encola_job_y_crea_video(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        response = self.make_client(queue=queue).post(
            "/api/upscale",
            json={"kind": "video", "source_gen": gen_id, "model": self.MODEL},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"job_id": "job-1"})
        self.assertEqual(len(queue.jobs), 1)
        job = queue.jobs[0]
        self.assertEqual(job["kind"], "upscale")
        self.assertEqual(job["task"], "upscale_video")
        self.assertEqual(job["source_gen"], gen_id)
        self.assertEqual(job["source_file"], "clip.mp4")
        self.assertEqual(job["model"], self.MODEL)
        self.assertEqual(job["model_file"], "RealESRGAN_x2.pth")
        self.assertEqual(job["scale"], 2)
        self.assertIsNone(job["fps"])
        self.assertEqual(
            job["params"],
            {
                "task": "upscale_video",
                "source_gen": gen_id,
                "source_file": "clip.mp4",
                "model": self.MODEL,
                "scale": 2,
                "fps": None,
            },
        )
        files = sorted((self.config.comfy_root / "input").glob("*.mp4"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PNG_BYTES)
        self.assertEqual(job["video_name"], files[0].name)
        new_gen = self.store.list()[0]
        self.assertEqual(new_gen["kind"], "video")
        self.assertEqual(new_gen["status"], "queued")
        self.assertEqual(new_gen["params"], job["params"])
        self.assertEqual(server_module._JOBS[new_gen["id"]]["kind"], "upscale")

    def test_video_file_explicito_se_usa(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("a.mp4", "b.mp4"))
        response = self.make_client(queue=queue).post(
            "/api/upscale",
            json={
                "kind": "video",
                "source_gen": gen_id,
                "file": "b.mp4",
                "model": self.MODEL,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(queue.jobs[0]["source_file"], "b.mp4")
        self.assertEqual(self.store.list()[0]["params"]["source_file"], "b.mp4")

    def test_kind_invalido_400(self):
        gen_id = self.make_source()
        client = self.make_client()
        for kind in ("", "nope", 5, True):
            with self.subTest(kind=kind):
                response = client.post(
                    "/api/upscale",
                    json={"kind": kind, "source_gen": gen_id, "model": self.MODEL},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_video_origen_imagen_400(self):
        gen_id = self.make_source()
        response = self.make_client().post(
            "/api/upscale",
            json={"kind": "video", "source_gen": gen_id, "model": self.MODEL},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("video", response.json()["error"])

    def test_video_file_fuera_de_carpeta_403(self):
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        (self.config.data_dir / "secret.mp4").write_bytes(MP4_BYTES)
        response = self.make_client().post(
            "/api/upscale",
            json={
                "kind": "video",
                "source_gen": gen_id,
                "file": "../secret.mp4",
                "model": self.MODEL,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_video_file_inexistente_o_no_video_404(self):
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        client = self.make_client()
        for name in ("missing.mp4", "nota.txt", "otra.png"):
            with self.subTest(name=name):
                response = client.post(
                    "/api/upscale",
                    json={
                        "kind": "video",
                        "source_gen": gen_id,
                        "file": name,
                        "model": self.MODEL,
                    },
                )
                self.assertEqual(response.status_code, 404)

    def test_video_source_sin_salidas_404(self):
        gen_id = self.make_source(kind="video", outputs=())
        response = self.make_client().post(
            "/api/upscale",
            json={"kind": "video", "source_gen": gen_id, "model": self.MODEL},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_fps_encola_job_y_crea_video(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        response = self.make_client(queue=queue).post(
            "/api/upscale",
            json={
                "kind": "fps",
                "source_gen": gen_id,
                "ckpt": "rife47.pth",
                "multiplier": 4,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"job_id": "job-1"})
        self.assertEqual(len(queue.jobs), 1)
        job = queue.jobs[0]
        self.assertEqual(job["kind"], "upscale")
        self.assertEqual(job["task"], "rife")
        self.assertEqual(job["source_gen"], gen_id)
        self.assertEqual(job["source_file"], "clip.mp4")
        self.assertEqual(job["ckpt"], "rife47.pth")
        self.assertEqual(job["ckpt_name"], "rife47.pth")
        self.assertEqual(job["multiplier"], 4)
        self.assertIsNone(job["fps_in"])
        self.assertIsNone(job["fps_out"])
        self.assertEqual(
            job["params"],
            {
                "task": "rife",
                "source_gen": gen_id,
                "source_file": "clip.mp4",
                "ckpt": "rife47.pth",
                "multiplier": 4,
                "fps_in": None,
                "fps_out": None,
            },
        )
        files = sorted((self.config.comfy_root / "input").glob("*.mp4"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PNG_BYTES)
        self.assertEqual(job["video_name"], files[0].name)
        new_gen = self.store.list()[0]
        self.assertEqual(new_gen["kind"], "video")
        self.assertEqual(new_gen["status"], "queued")
        self.assertEqual(new_gen["params"], job["params"])
        self.assertEqual(server_module._JOBS[new_gen["id"]]["kind"], "upscale")

    def test_fps_ckpt_por_defecto_y_fps_in(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        response = self.make_client(queue=queue).post(
            "/api/upscale",
            json={"kind": "fps", "source_gen": gen_id, "multiplier": 2, "fps_in": 24},
        )
        self.assertEqual(response.status_code, 200)
        job = queue.jobs[0]
        self.assertEqual(job["ckpt"], "rife49.pth")
        self.assertEqual(job["fps_in"], 24.0)
        self.assertEqual(job["fps_out"], 48.0)
        self.assertEqual(job["params"]["fps_out"], 48.0)

    def test_fps_ckpt_invalido_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        client = self.make_client(queue=queue)
        for ckpt in ("", "  ", "nope.pth", 5, True, "../rife49.pth"):
            with self.subTest(ckpt=ckpt):
                response = client.post(
                    "/api/upscale",
                    json={
                        "kind": "fps",
                        "source_gen": gen_id,
                        "ckpt": ckpt,
                        "multiplier": 2,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(queue.jobs, [])
        self.assertEqual(self.store.count(), 1)
        self.assertFalse((self.config.comfy_root / "input").exists())

    def test_fps_multiplier_invalido_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        client = self.make_client(queue=queue)
        for multiplier in (None, 1, 3, 0, True, "2", 4.0):
            with self.subTest(multiplier=multiplier):
                response = client.post(
                    "/api/upscale",
                    json={
                        "kind": "fps",
                        "source_gen": gen_id,
                        "ckpt": "rife49.pth",
                        "multiplier": multiplier,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(queue.jobs, [])
        self.assertFalse((self.config.comfy_root / "input").exists())

    def test_fps_fps_in_invalido_400(self):
        queue = RecordingQueue()
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        client = self.make_client(queue=queue)
        for fps_in in (0, -1, "24", True):
            with self.subTest(fps_in=fps_in):
                response = client.post(
                    "/api/upscale",
                    json={
                        "kind": "fps",
                        "source_gen": gen_id,
                        "multiplier": 2,
                        "fps_in": fps_in,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("fps_in", response.json()["error"])
        self.assertEqual(queue.jobs, [])

    def test_fps_origen_imagen_400(self):
        gen_id = self.make_source()
        response = self.make_client().post(
            "/api/upscale",
            json={"kind": "fps", "source_gen": gen_id, "multiplier": 2},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("video", response.json()["error"])

    def test_fps_source_gen_inexistente_404(self):
        response = self.make_client().post(
            "/api/upscale",
            json={"kind": "fps", "source_gen": 999, "multiplier": 2},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_fps_file_fuera_de_carpeta_403(self):
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        (self.config.data_dir / "secret.mp4").write_bytes(MP4_BYTES)
        response = self.make_client().post(
            "/api/upscale",
            json={
                "kind": "fps",
                "source_gen": gen_id,
                "file": "../secret.mp4",
                "multiplier": 2,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_fps_file_inexistente_o_no_video_404(self):
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        client = self.make_client()
        for name in ("missing.mp4", "nota.txt", "otra.png"):
            with self.subTest(name=name):
                response = client.post(
                    "/api/upscale",
                    json={
                        "kind": "fps",
                        "source_gen": gen_id,
                        "file": name,
                        "multiplier": 2,
                    },
                )
                self.assertEqual(response.status_code, 404)

    def test_fps_source_sin_salidas_404(self):
        gen_id = self.make_source(kind="video", outputs=())
        response = self.make_client().post(
            "/api/upscale",
            json={"kind": "fps", "source_gen": gen_id, "multiplier": 2},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_fps_flujo_completo_con_worker(self):
        transport = FakeVideoTransport(self.config, output_name="interp_00001_.mp4")
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
            start_worker=True,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/upscale",
                json={
                    "kind": "fps",
                    "source_gen": gen_id,
                    "ckpt": "rife49.pth",
                    "multiplier": 2,
                },
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 10)
            status = client.get(f"/api/jobs/{job_id}").json()
            self.assertEqual(status["status"], "done")
            self.assertEqual(status["outputs"][0]["name"], "interp_00001_.mp4")
            media = client.get(status["outputs"][0]["url"])
            self.assertEqual(media.status_code, 200)
            self.assertEqual(media.headers["content-type"], "video/mp4")
            self.assertEqual(media.content, MP4_BYTES)
            gallery = client.get("/api/gallery?kind=video").json()
            self.assertEqual(gallery["count"], 2)
            newest = gallery["items"][0]
            self.assertEqual(newest["kind"], "video")
            self.assertEqual(newest["params"]["task"], "rife")
            self.assertEqual(newest["params"]["source_gen"], gen_id)
            self.assertEqual(newest["params"]["ckpt"], "rife49.pth")
            self.assertEqual(newest["params"]["multiplier"], 2)
        graph = transport.submits[0]["prompt"]
        video_name = graph["1"]["inputs"]["file"]
        self.assertTrue(video_name.endswith(".mp4"))
        self.assertNotEqual(video_name, "clip.mp4")
        self.assertEqual(graph["1"]["class_type"], "LoadVideo")
        self.assertEqual(graph["2"]["inputs"]["video"], ["1", 0])
        self.assertEqual(graph["3"]["class_type"], "ComfyMathExpression")
        self.assertEqual(graph["3"]["inputs"]["values.a"], ["2", 2])
        self.assertEqual(graph["3"]["inputs"]["expression"], "a * 2")
        self.assertEqual(graph["4"]["class_type"], "RIFE VFI")
        self.assertEqual(graph["4"]["inputs"]["ckpt_name"], "rife49.pth")
        self.assertEqual(graph["4"]["inputs"]["frames"], ["2", 0])
        self.assertEqual(graph["4"]["inputs"]["multiplier"], 2)
        self.assertEqual(graph["5"]["inputs"]["images"], ["4", 0])
        self.assertEqual(graph["5"]["inputs"]["fps"], ["3", 0])
        self.assertEqual(graph["5"]["inputs"]["audio"], ["2", 1])
        self.assertEqual(graph["6"]["inputs"]["format"], "mp4")
        row = self.store.get(newest["id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["outputs"], ["interp_00001_.mp4"])

    def test_flujo_completo_video_con_worker(self):
        transport = FakeVideoTransport(self.config, output_name="upscaled_00001_.mp4")
        gen_id = self.make_source(kind="video", outputs=("clip.mp4",))
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
            start_worker=True,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/upscale",
                json={"kind": "video", "source_gen": gen_id, "model": self.MODEL},
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 10)
            status = client.get(f"/api/jobs/{job_id}").json()
            self.assertEqual(status["status"], "done")
            self.assertEqual(status["outputs"][0]["name"], "upscaled_00001_.mp4")
            media = client.get(status["outputs"][0]["url"])
            self.assertEqual(media.status_code, 200)
            self.assertEqual(media.headers["content-type"], "video/mp4")
            self.assertEqual(media.content, MP4_BYTES)
            gallery = client.get("/api/gallery?kind=video").json()
            self.assertEqual(gallery["count"], 2)
            newest = gallery["items"][0]
            self.assertEqual(newest["kind"], "video")
            self.assertEqual(newest["params"]["task"], "upscale_video")
            self.assertEqual(newest["params"]["source_gen"], gen_id)
        graph = transport.submits[0]["prompt"]
        video_name = graph["1"]["inputs"]["file"]
        self.assertTrue(video_name.endswith(".mp4"))
        self.assertNotEqual(video_name, "clip.mp4")
        self.assertEqual(graph["1"]["class_type"], "LoadVideo")
        self.assertEqual(graph["2"]["inputs"]["video"], ["1", 0])
        self.assertEqual(graph["5"]["inputs"]["fps"], ["2", 2])
        self.assertEqual(graph["5"]["inputs"]["audio"], ["2", 1])
        self.assertEqual(graph["6"]["inputs"]["format"], "mp4")
        row = self.store.get(newest["id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["outputs"], ["upscaled_00001_.mp4"])

    def test_flujo_completo_con_worker(self):
        transport = FakeTransport(self.config, output_name="upscaled_00001_.png")
        gen_id = self.make_source()
        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            engine_factory=self.fake_factory(transport),
            start_worker=True,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/upscale", json={"source_gen": gen_id, "model": self.MODEL}
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            app.state.queue.wait(job_id, 10)
            status = client.get(f"/api/jobs/{job_id}").json()
            self.assertEqual(status["status"], "done")
            self.assertEqual(status["outputs"][0]["name"], "upscaled_00001_.png")
            media = client.get(status["outputs"][0]["url"])
            self.assertEqual(media.status_code, 200)
            self.assertEqual(media.headers["content-type"], "image/png")
            self.assertEqual(media.content, PNG_BYTES)
            gallery = client.get("/api/gallery?kind=image").json()
            self.assertEqual(gallery["count"], 2)
            newest = gallery["items"][0]
            self.assertEqual(newest["kind"], "image")
            self.assertEqual(newest["params"]["task"], "upscale")
            self.assertEqual(newest["params"]["source_gen"], gen_id)
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["2"]["inputs"]["model_name"], "RealESRGAN_x2.pth")
        self.assertEqual(graph["4"]["inputs"]["images"], ["3", 0])
        row = self.store.get(newest["id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "image")
        self.assertEqual(row["outputs"], ["upscaled_00001_.png"])


class H3GuideUiStaticTests(ServerTestCase):
    def test_index_incluye_guia_de_prompt_h3(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="video-h3-guide"',
            "Guía de prompt H3",
            'id="btn-h3-insert-template"',
            "Insertar plantilla",
            'id="btn-h3-copy-guide"',
            "Copiar guía",
            'id="h3-guide-status"',
            "integrated_multimodal_description",
            "overall_soundscape",
            "non_diegetic_music",
            "[Español]",
            "speaker id estable",
            "~2/3",
            "sin cortes",
            "FL2VA",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertLess(
            text.index('id="video-prompt-field"'),
            text.index('id="video-h3-guide"'),
        )

    def test_app_js_incluye_guia_y_plantilla_h3(self):
        text = self.get_static_js()
        for marker in (
            "H3_PROMPT_TEMPLATE",
            "H3_GUIDE_TEXT",
            "insertH3Template",
            "copyH3Guide",
            "setH3GuideStatus",
            "${current}\\n\\n${H3_PROMPT_TEMPLATE}",
            'on("btn-h3-insert-template", "click", insertH3Template);',
            'on("btn-h3-copy-guide", "click", copyH3Guide);',
            '$("video-h3-guide").style.display = isWan ? "none" : "";',
            '"video-h3-guide",',
            '"btn-h3-insert-template",',
            '"btn-h3-copy-guide",',
            '"h3-guide-status",',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_improve_h3_prompt_envia_image_b64(self):
        text = self.get_static_js()
        self.assertIn('$("video-image")', text)
        self.assertIn("image_b64", text)
        self.assertIn('postJson("/api/video/h3_prompt"', text)

    def test_m16_video_redesign_controls_and_templates_present(self):
        html = self.make_client().get("/").text
        for marker in (
            'id="video-block-mode"',
            'id="video-block-prompt"',
            'id="video-block-settings"',
            'id="video-v2v-box"',
            'id="video-v2v-input"',
            'id="video-v2v-preview"',
            'id="video-h3-aspect"',
            'id="video-h3-prompt-strength"',
            'id="video-custom-settings-panel"',
            'id="btn-h3-template-portrait"',
            'id="btn-h3-template-walk"',
            'id="btn-h3-template-action"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)


class H3PromptServerTests(ServerTestCase):
    H3_OUTPUT = (
        "integrated_multimodal_description: 1girl in school uniform\n"
        "overall_soundscape: birds chirping\n"
        "non_diegetic_music: None"
    )

    def test_h3_prompt_con_image_b64_multimodal(self):
        calls = []

        def fake_llm(system, user):
            calls.append((system, user))
            return self.H3_OUTPUT

        client = self.make_client(llm=fake_llm)
        res = client.post(
            "/api/video/h3_prompt",
            json={"text": "chica", "image_b64": "fakeb64data"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"h3_prompt": self.H3_OUTPUT})
        self.assertEqual(len(calls), 1)
        system, user = calls[0]
        self.assertIn("primer fotograma", system)
        self.assertIsInstance(user, list)
        self.assertEqual(user[0]["type"], "text")
        self.assertEqual(user[1]["type"], "image_url")
        self.assertEqual(user[1]["image_url"]["url"], "data:image/jpeg;base64,fakeb64data")

    def test_h3_prompt_sin_image_b64_texto_plano(self):
        calls = []

        def fake_llm(system, user):
            calls.append((system, user))
            return self.H3_OUTPUT

        client = self.make_client(llm=fake_llm)
        res = client.post("/api/video/h3_prompt", json={"text": "chica"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"h3_prompt": self.H3_OUTPUT})
        self.assertEqual(len(calls), 1)
        _system, user = calls[0]
        self.assertIsInstance(user, str)
        self.assertIn("escena: chica", user)


class UpscaleUiStaticTests(ServerTestCase):
    def test_index_incluye_pestana_y_controles_upscaler(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="tab-upscaler"',
            ">Upscaler<",
            'id="panel-upscaler"',
            'id="upscale-kind"',
            ">Imagen<",
            ">Vídeo<",
            ">FPS<",
            'id="upscale-source-field"',
            'id="upscale-source-label"',
            'id="upscale-source-info"',
            'id="upscale-file-field"',
            'id="upscale-file"',
            'accept="image/*"',
            'id="upscale-passes-field"',
            'id="upscale-passes"',
            "×2 (1 pasada)",
            "×4 (2 pasadas)",
            'id="upscale-sharpen-field"',
            'id="upscale-sharpen"',
            ">OFF<",
            ">Suave<",
            ">Fuerte<",
            "Mejora de detalle",
            'id="upscale-gallery-thumbs"',
            'id="upscale-gallery-prev"',
            'id="upscale-gallery-next"',
            'id="upscale-gallery-info"',
            'id="upscale-model-field"',
            'id="upscale-model"',
            'id="upscale-model-note"',
            'id="upscale-ckpt-field"',
            'id="upscale-ckpt"',
            'id="upscale-ckpt-note"',
            'id="upscale-multiplier-field"',
            'id="upscale-multiplier"',
            ">×2<",
            ">×4<",
            'id="btn-upscale"',
            "Escalar",
            'id="upscale-status"',
            'id="upscale-progress"',
            'id="upscale-progress-fill"',
            'id="upscale-progress-text"',
            'id="upscale-preview"',
            'id="upscale-preview-img"',
            'id="upscale-preview-video"',
            'id="upscale-preview-empty"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertLess(text.index('id="tab-editor"'), text.index('id="tab-upscaler"'))

    def test_app_js_incluye_upscaler(self):
        text = self.get_static_js()
        for marker in (
            "/api/upscale/models",
            'postJson("/api/upscale"',
            'switchTab("upscaler")',
            "loadUpscaleGallery",
            "renderUpscaleGallery",
            "selectUpscaleSource",
            "useUpscaleLocalFile",
            "clearUpscaleSelection",
            "loadUpscaleModels",
            "loadUpscaleInterpolation",
            "frame_interpolation",
            "upscaleSourceKind",
            "upscaleCkptNote",
            "upscale-ckpt",
            "upscale-multiplier",
            "Interpolar",
            "generateUpscale",
            "finishUpscale",
            "finishVideoUpscale",
            "applyUpscaleKind",
            "setUpscaleProgress",
            "btn-upscale-cancel",
            "upscale-kind",
            "upscale-file",
            "upscale-passes",
            "upscale-sharpen",
            '$("upscale-sharpen")',
            "payload.sharpen",
            "upscale-gallery-thumbs",
            "upscale-gallery-prev",
            "upscale-gallery-next",
            "upscale-gallery-info",
            "image_b64",
            "readFileBase64",
            '"fps"',
            "upscale-preview-video",
            "reloadVideoViewerFirstPage",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


STARTUP_NEGATIVE_123 = (
    "worst quality, low quality, jpeg artifacts, blurry, mosaic censoring, "
    "bar censor, score_1, score_2, score_3, artist name"
)
STARTUP_NEGATIVE_ANTI_MINORS = "child, teen, loli, young-looking"
STARTUP_NEGATIVE_COMPOSED = (
    "worst quality, low quality, jpeg artifacts, child, teen, loli, young-looking, "
    "blurry, mosaic censoring, bar censor, score_1, score_2, score_3, artist name"
)


class StartupDefaultsUiStaticTests(ServerTestCase):
    """M10-2g/M10-2f: defaults de arranque (#123) + anti-menores y motor H3."""

    def test_index_fija_defaults_de_arranque(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="steps" type="number" value="30"',
            'id="cfg" type="number" value="6"',
            'id="seed" type="number" value="42"',
            '<option value="nsfw" selected>nsfw</option>',
            '<option value="h3" selected>',
            STARTUP_NEGATIVE_COMPOSED,
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertNotIn("839054188", text)

    def test_app_js_fija_defaults_de_arranque(self):
        text = self.get_static_js()
        for marker in (
            "const STARTUP_DEFAULTS = {",
            'model: "one-obsession-anima-v40"',
            "steps: 30",
            "cfg: 6",
            'sampler: "euler"',
            'scheduler: "normal"',
            "width: 1024",
            "height: 1024",
            "seed: 42",
            'preprompt: "anima_default"',
            'rating: "nsfw"',
            'video_engine: "h3"',
            "worst quality, low quality, jpeg artifacts, child, teen, loli, young-looking, ",
            "blurry, mosaic censoring, bar censor, score_1, score_2, score_3, artist name",
            STARTUP_NEGATIVE_ANTI_MINORS,
            "applyStartupDefaults",
            'await settle("defaults de arranque", applyStartupDefaults);',
            'other: "Otros"',
            'const GENERAL_SUBCAT_FALLBACK = "other";',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertNotIn("839054188", text)

    def test_default_del_negativo_es_la_composicion_dinamica(self):
        response = self.make_client().get(
            "/api/negative", params={"preprompt": "anima_default", "family": "anima"}
        )
        self.assertEqual(response.status_code, 200)
        negative = response.json()["negative"]
        self.assertEqual(negative, apply_preprompt("", "anima", "anima_default")[1])
        self.assertEqual(negative, STARTUP_NEGATIVE_COMPOSED)
        self.assertIn("child, teen, loli, young-looking", negative)
        self.assertNotEqual(negative, STARTUP_NEGATIVE_123)


class GalleryTabUiStaticTests(ServerTestCase):
    """Pestana Galeria: feed completo con filtro, pager y modal de detalle."""

    def test_index_incluye_pestana_galeria(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="tab-gallery"',
            ">Galería<",
            'id="panel-gallery"',
            'id="gallery-filter"',
            '<option value="">Todo</option>',
            '<option value="image">Imágenes</option>',
            '<option value="video">Vídeos</option>',
            'id="gallery-prev"',
            'id="gallery-info"',
            'id="gallery-next"',
            'id="gallery-grid"',
            'class="gallery-grid"',
            'id="gallery-empty"',
            'id="gallery-modal"',
            'id="gallery-modal-media"',
            'id="gallery-modal-info"',
            'id="btn-gallery-download"',
            'id="btn-gallery-close"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertLess(text.index('id="tab-upscaler"'), text.index('id="tab-gallery"'))
        self.assertLess(
            text.index('id="panel-upscaler"'), text.index('id="panel-gallery"')
        )

    def test_galeria_tiene_refresh_interno(self):
        index = self.make_client().get("/").text
        self.assertIn(
            '<button id="btn-gallery-refresh" type="button" '
            'title="Refrescar la galería">Refrescar</button>',
            index,
        )
        self.assertLess(
            index.index('id="gallery-filter"'), index.index('id="btn-gallery-refresh"')
        )
        script = self.get_static_js()
        self.assertIn('on("btn-gallery-refresh", "click"', script)

    def test_app_js_incluye_pestana_galeria(self):
        text = self.get_static_js()
        for marker in (
            "GALLERY_PAGE_SIZE",
            "state.galleryTab",
            "galleryTab: {",
            "loadGalleryTab",
            "renderGalleryTab",
            "openGalleryModal",
            "closeGalleryModal",
            "downloadGalleryItem",
            "galleryKindLabel",
            "galleryStatusLabel",
            "galleryPromptPreview",
            'switchTab("gallery")',
            'tab === "gallery"',
            "/api/gallery?limit=",
            "gallery-filter",
            "gallery-prev",
            "gallery-next",
            "gallery-grid",
            "gallery-empty",
            "gallery-modal-media",
            "gallery-modal-info",
            "gallery-modal-prompt",
            "btn-gallery-download",
            "btn-gallery-close",
            "downloadUrlFor",
            "isVideoUrl",
            '"tab-gallery",',
            '"panel-gallery",',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_index_incluye_acciones_modal_galeria(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="btn-gallery-use-ref"',
            'id="btn-gallery-animate"',
            'id="btn-gallery-edit"',
            'id="btn-gallery-upscale"',
            '<button id="btn-gallery-use-ref" type="button">Usar referencia</button>',
            '<button id="btn-gallery-animate" type="button">Animar</button>',
            '<button id="btn-gallery-edit" type="button">Editar</button>',
            '<button id="btn-gallery-upscale" type="button">Upscale</button>',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertLess(
            text.index('id="btn-gallery-upscale"'),
            text.index('id="btn-gallery-download"'),
        )
        self.assertIn(
            '<button id="btn-gallery-download" class="primary" type="button">Descargar</button>',
            text,
        )

    def test_app_js_incluye_acciones_modal_galeria(self):
        text = self.get_static_js()
        for marker in (
            "function useGalleryItemAsReference",
            "function animateGalleryItem",
            "function editGalleryItemInEditor",
            "function upscaleGalleryItem",
            'on("btn-gallery-use-ref", "click"',
            'on("btn-gallery-animate", "click"',
            'on("btn-gallery-edit", "click"',
            'on("btn-gallery-upscale", "click"',
            "function attachFileInputFromUrl",
            'attachFileInputFromUrl("video-image", galleryItemUrl(item)',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class ScrollbarUiStaticTests(ServerTestCase):
    """Barras de scroll ocultas en toda la app sin perder rueda/teclado."""

    def test_app_css_oculta_barras_sin_desactivar_scroll(self):
        text = self.make_client().get("/static/app.css").text
        self.assertIn(
            "* {\n  scrollbar-width: none;\n  -ms-overflow-style: none;\n}", text
        )
        for marker in (
            "scrollbar-width: none",
            "-ms-overflow-style: none",
            "*::-webkit-scrollbar",
            "display: none",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class ZoneCatalogSearchUiStaticTests(ServerTestCase):
    """Búsqueda del popover de zonas sobre el catálogo completo vía /api/tags."""

    def test_app_js_busqueda_catalogo(self):
        text = self.get_static_js()
        for marker in (
            "/api/tags?q=",
            "Catálogo completo",
            "zoneCatalogSearchSeq",
            "renderZoneCatalogSearch",
            "makeZoneOptionRow",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_css_titulo_catalogo(self):
        text = self.make_client().get("/static/app.css").text
        self.assertIn(".zone-catalog-title", text)


class UnifiedDescribeUiStaticTests(ServerTestCase):
    """UI del flujo unificado de vision + estado del LLM + tiempos (M11-3H)."""

    def test_index_marcadores(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="llm-status"',
            'id="vision-advanced"',
            'id="btn-vision-tags-only"',
            "Solo tags (rápido)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_marcadores(self):
        text = self.get_static_js()
        for marker in (
            'mode = "unified"',
            "visionLastPayload",
            "refreshLlmStatus",
            '"/api/llm/status"',
            "performance.now()",
            "dropped",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_etiquetas_de_estado_llm(self):
        text = self.get_static_js()
        for marker in (
            'ready: ["LLM: listo", "is-ok"]',
            'loading: ["LLM: cargando…", "is-warn"]',
            'stopped: ["LLM: en espera", "is-warn"]',
            'offline: ["LLM: parado", "is-off"]',
            'unavailable: ["LLM: no instalado", "is-off"]',
            'foreign: ["LLM: puerto ocupado", "is-off"]',
            'local: ["LLM: local", "is-warn"]',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_css_llm_status(self):
        text = self.make_client().get("/static/app.css").text
        self.assertIn(".llm-status", text)


class TrainAutoCaptionUiStaticTests(ServerTestCase):
    """UI del auto-caption WD14 en el modal de entrenamiento (M11-4J)."""

    def test_index_marcadores(self):
        text = self.make_client().get("/").text
        for marker in (
            'id="train-auto-tags"',
            "Generar tags automáticamente (WD14)",
            'id="train-tag-threshold"',
            'id="train-wd14-note"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_app_js_marcadores(self):
        text = self.get_static_js()
        for marker in (
            "train-auto-tags",
            "tag_threshold",
            "/api/vision/status",
            "etiquetando",
            "auto_tags",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class GalleryDeleteRoutesTests(ServerTestCase):
    """Pruebas para DELETE /api/gallery/{id} y POST /api/gallery/clean_failed."""

    def test_delete_gallery_item_success(self):
        gen_id = self.store.add("m1", "waifu test prompt", status="done")
        self.store.update(gen_id, outputs=["ok.png"])
        png_path = self.add_gallery_png(gen_id, "ok.png")
        self.assertTrue(png_path.is_file())

        gen_dir = self.config.data_dir / "generations" / str(gen_id)
        gen_dir.mkdir(parents=True, exist_ok=True)
        gen_file = gen_dir / "gen.png"
        gen_file.write_bytes(PNG_BYTES)
        self.assertTrue(gen_file.is_file())

        client = self.make_client()
        res = client.delete(f"/api/gallery/{gen_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True, "id": gen_id})

        self.assertIsNone(self.store.get(gen_id))
        self.assertFalse(png_path.exists())
        self.assertFalse((self.config.data_dir / "gallery" / str(gen_id)).exists())
        self.assertFalse(gen_file.exists())
        self.assertFalse(gen_dir.exists())

    def test_delete_gallery_item_404_not_found(self):
        client = self.make_client()
        res = client.delete("/api/gallery/99999")
        self.assertEqual(res.status_code, 404)
        self.assertIn("no encontrado", res.json()["error"])

    def test_delete_gallery_item_409_when_queued_or_running(self):
        client = self.make_client()
        for status in ("queued", "running"):
            with self.subTest(status=status):
                gen_id = self.store.add("m1", f"item {status}", status=status)
                res = client.delete(f"/api/gallery/{gen_id}")
                self.assertEqual(res.status_code, 409)
                self.assertIn(
                    "No se puede eliminar una generacion en cola o en ejecucion",
                    res.json()["detail"],
                )
                self.assertIsNotNone(self.store.get(gen_id))

    def test_clean_failed(self):
        self.store.add("m1", "done item", status="done")
        self.store.add("m1", "error item", status="error")
        self.store.add("m1", "failed item", status="failed")

        client = self.make_client()
        res = client.post("/api/gallery/clean_failed")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True, "cleaned": 2})
        self.assertEqual(self.store.count(), 1)

    def test_gallery_search_q(self):
        self.store.add("m1", "1girl blue hair smiling", status="done")
        self.store.add("m1", "1boy red jacket outdoors", status="done")

        client = self.make_client()
        res = client.get("/api/gallery?q=blue")
        self.assertEqual(res.status_code, 200)
        items = res.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["prompt"], "1girl blue hair smiling")


class CustomTagsRoutesTests(ServerTestCase):
    """Pruebas para endpoints /api/tags/custom (GET, POST, DELETE)."""

    def setUp(self):
        super().setUp()
        import os
        from app.tags import load_catalog

        self._old_data_dir = os.environ.get("WAIFU_DATA_DIR")
        os.environ["WAIFU_DATA_DIR"] = str(self.config.data_dir)
        load_catalog(force=True)

        def cleanup_env():
            if self._old_data_dir is not None:
                os.environ["WAIFU_DATA_DIR"] = self._old_data_dir
            else:
                os.environ.pop("WAIFU_DATA_DIR", None)
            load_catalog(force=True)

        self.addCleanup(cleanup_env)

    def test_custom_tags_crud(self):
        client = self.make_client()

        res = client.get("/api/tags/custom")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])

        payload = {"name": "cyber_dress", "category": "general", "count": 120}
        res = client.post("/api/tags/custom", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(res.json()["tag"]["name"], "cyber_dress")

        res = client.get("/api/tags/custom")
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "cyber_dress")
        self.assertEqual(items[0]["category"], "general")
        self.assertEqual(items[0]["count"], 120)

        res = client.delete("/api/tags/custom/cyber_dress")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True, "name": "cyber_dress"})

        res = client.get("/api/tags/custom")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])

    def test_custom_tags_validation_and_not_found(self):
        client = self.make_client()

        res = client.post("/api/tags/custom", json={"name": "   "})
        self.assertEqual(res.status_code, 400)

        res = client.delete("/api/tags/custom/no_such_tag")
        self.assertEqual(res.status_code, 404)


class GalleryUiPhase3Tests(ServerTestCase):
    """Pruebas de UI estática para Phase 3 (M14-5, M14-6, M14-7, M14-8)."""

    def test_index_html_phase3_elements(self):
        html = self.make_client().get("/").text
        for marker in (
            'id="gallery-tag-search"',
            'id="btn-gallery-clean-failed"',
            'id="btn-manage-custom-tags"',
            'id="btn-gallery-delete"',
            'id="custom-tags-modal"',
            'id="custom-tags-form"',
            'id="custom-tag-name"',
            'id="custom-tag-category"',
            'id="custom-tag-count"',
            'id="btn-custom-tag-add"',
            'id="custom-tags-list"',
            'id="btn-image-compare"',
            'id="image-compare"',
            'id="image-compare-stage"',
            'id="image-compare-before"',
            'id="image-compare-after"',
            'id="image-compare-handle"',
            'id="image-compare-ratio"',
            'id="btn-toggle-image-thumbs"',
            'id="btn-toggle-video-thumbs"',
            'id="btn-toggle-editor-thumbs"',
            'id="btn-toggle-upscale-thumbs"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_app_js_phase3_markers(self):
        script = self.get_static_js()
        for marker in (
            "function setImageCompareEnabled",
            "function setImageCompareSlot2",
            "function applyImageCompare",
            "function initImageCompareInteractions",
            "function toggleThumbs",
            "function openCustomTagsModal",
            "function closeCustomTagsModal",
            "function refreshCustomTagsList",
            "function submitCustomTag",
            "function deleteGalleryItem",
            "function cleanFailedGenerations",
            'on("gallery-tag-search"',
            'on("btn-gallery-clean-failed"',
            'on("btn-manage-custom-tags"',
            'on("btn-gallery-delete"',
            'on("btn-image-compare"',
            'on("btn-toggle-image-thumbs"',
            'on("btn-toggle-video-thumbs"',
            'on("btn-toggle-editor-thumbs"',
            'on("btn-toggle-upscale-thumbs"',
            '"btn-image-compare",',
            '"btn-toggle-image-thumbs",',
            '"btn-toggle-video-thumbs",',
            '"btn-toggle-editor-thumbs",',
            '"btn-toggle-upscale-thumbs",',
            '"gallery-tag-search",',
            '"btn-gallery-clean-failed",',
            '"btn-manage-custom-tags",',
            '"btn-gallery-delete",',
            '"custom-tags-modal",',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_app_css_gallery_and_custom_tags_classes(self):
        css = self.make_client().get("/static/app.css").text
        for marker in (
            ".image-compare",
            ".gallery-search-field",
            ".custom-tags-modal-box",
            ".custom-tags-body",
            ".custom-tags-form",
            ".custom-tags-list",
            ".custom-tag-item",
            "align-content: start;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, css)


if __name__ == "__main__":
    unittest.main()
