"""Tests CPU del runner del Gate F1 (M8-11b) con transporte falso. Sin red ni GPU."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.config import EngineConfig
from app.engine import ComfyEngine, EngineError
from app.gate_f1 import build_graph_for, run
from app.registry import ModelEntry, ModelProfile, ModelRegistry

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "registry" / "models.json"

GRAPH_DEFAULTS = {
    "steps": 20,
    "cfg": 4.0,
    "sampler_name": "euler",
    "scheduler": "sgm_uniform",
    "width": 320,
    "height": 576,
}

AESTHETIC_SHA256 = "3C1868387A3A1FF504BBB87C33678321965EAD381FCF87AFBD0264DAA600C082"
AESTHETIC_BYTES = "4182230656 bytes"
OBSESSION_SHA256 = "2ACBD9F1D53845833FC8D5093FC11CC32C3E613A476097B8FAE9BA2B59ED677B"
OBSESSION_BYTES = "4182229969 bytes"


def json_bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


class FakeTransport:
    """Transporte falso: registra llamadas y sirve respuestas preprogramadas."""

    def __init__(self, responses=(), default=None):
        self.calls: list[dict] = []
        self._responses = list(responses)
        self._default = default

    def __call__(self, method, path, body=None, headers=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        if self._responses:
            return self._responses.pop(0)
        if self._default is not None:
            return self._default
        raise AssertionError(f"transporte falso sin respuesta para {method} {path}")


def make_entry(**overrides) -> ModelEntry:
    base = dict(
        id="modelo-test",
        family="anima",
        display_name="Modelo de test",
        profile=ModelProfile(
            unet_name="unet-nuevo.safetensors",
            clip_name="clip-nuevo.safetensors",
            clip_type="stable_diffusion",
            vae_name="vae-nuevo.safetensors",
        ),
        source="local (test)",
        license="Anima License (test)",
        defaults=dict(GRAPH_DEFAULTS),
    )
    base.update(overrides)
    return ModelEntry(**base)


def base_graph() -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "unet-viejo.safetensors", "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "clip-viejo.safetensors", "type": "stable_diffusion"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "vae-viejo.safetensors"},
        },
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 320, "height": 576, "batch_size": 1},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {"seed": 1, "steps": 20, "model": ["1", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "test"},
        },
    }


class BuildGraphForTests(unittest.TestCase):
    def test_parchea_unet_clip_vae_y_seed(self):
        graph = base_graph()
        entry = make_entry()

        patched = build_graph_for(graph, entry, 42)

        self.assertEqual(
            patched["1"]["inputs"]["unet_name"], "unet-nuevo.safetensors"
        )
        self.assertEqual(patched["2"]["inputs"]["clip_name"], "clip-nuevo.safetensors")
        self.assertEqual(patched["2"]["inputs"]["type"], "stable_diffusion")
        self.assertEqual(patched["3"]["inputs"]["vae_name"], "vae-nuevo.safetensors")
        self.assertEqual(patched["7"]["inputs"]["seed"], 42)
        self.assertEqual(patched["6"]["inputs"]["width"], 320)

    def test_no_muta_el_original(self):
        graph = base_graph()
        snapshot = copy.deepcopy(graph)

        build_graph_for(graph, make_entry(), 99)

        self.assertEqual(graph, snapshot)
        self.assertEqual(graph["1"]["inputs"]["unet_name"], "unet-viejo.safetensors")
        self.assertEqual(graph["7"]["inputs"]["seed"], 1)

    def test_aplica_seed_a_todos_los_nodos_con_widget(self):
        graph = base_graph()
        graph["8"] = {"class_type": "KSamplerAdvanced", "inputs": {"seed": 5, "steps": 8}}

        patched = build_graph_for(graph, make_entry(), 7)

        self.assertEqual(patched["7"]["inputs"]["seed"], 7)
        self.assertEqual(patched["8"]["inputs"]["seed"], 7)

    def test_busca_por_class_type_no_por_id(self):
        graph = base_graph()
        graph["20"] = graph.pop("1")
        graph["21"] = graph.pop("2")
        graph["22"] = graph.pop("3")

        patched = build_graph_for(graph, make_entry(), 42)

        self.assertEqual(patched["20"]["inputs"]["unet_name"], "unet-nuevo.safetensors")
        self.assertEqual(patched["21"]["inputs"]["clip_name"], "clip-nuevo.safetensors")
        self.assertEqual(patched["22"]["inputs"]["vae_name"], "vae-nuevo.safetensors")

    def test_sin_unet_lanza_engine_error(self):
        graph = base_graph()
        del graph["1"]

        with self.assertRaises(EngineError):
            build_graph_for(graph, make_entry(), 42)

    def test_sin_clip_lanza_engine_error(self):
        graph = base_graph()
        del graph["2"]

        with self.assertRaises(EngineError):
            build_graph_for(graph, make_entry(), 42)

    def test_sin_vae_lanza_engine_error(self):
        graph = base_graph()
        del graph["3"]

        with self.assertRaises(EngineError):
            build_graph_for(graph, make_entry(), 42)

    def test_sin_nodo_seed_lanza_engine_error(self):
        graph = base_graph()
        del graph["7"]["inputs"]["seed"]

        with self.assertRaises(EngineError):
            build_graph_for(graph, make_entry(), 42)


class RunTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        (self.tmp / "output").mkdir()

    def build_engine(self, transport, **kwargs) -> ComfyEngine:
        config = EngineConfig(
            comfy_root=self.tmp,
            comfy_url="http://test",
            data_dir=self.tmp / "data",
        )
        return ComfyEngine(config, transport=transport, **kwargs)

    def write_png(self, name: str = "imagen_00001_.png") -> Path:
        path = self.tmp / "output" / name
        path.write_bytes(b"png-bytes")
        return path.resolve()

    def history_ok(self, prompt_id: str, path: Path) -> bytes:
        return json_bytes(
            {
                prompt_id: {
                    "status": {"status_str": "success"},
                    "outputs": {
                        "9": {
                            "images": [
                                {
                                    "filename": path.name,
                                    "subfolder": "",
                                    "type": "output",
                                }
                            ]
                        }
                    },
                }
            }
        )


class RunTests(RunTestCase):
    def test_run_devuelve_png_parcheado_y_prompt_id(self):
        expected = self.write_png()
        transport = FakeTransport(
            [
                (200, json_bytes({"prompt_id": "pid-1"})),
                (200, self.history_ok("pid-1", expected)),
            ]
        )
        engine = self.build_engine(transport, poll_s=0.0)
        graph = base_graph()
        entry = make_entry()
        prompt_ids: list[str] = []

        paths = run(engine, graph, entry, 1234, on_prompt_id=prompt_ids.append)

        self.assertEqual(paths, [expected])
        self.assertEqual(prompt_ids, ["pid-1"])
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        sent = payload["prompt"]
        self.assertEqual(sent["1"]["inputs"]["unet_name"], entry.profile.unet_name)
        self.assertEqual(sent["2"]["inputs"]["clip_name"], entry.profile.clip_name)
        self.assertEqual(sent["2"]["inputs"]["type"], entry.profile.clip_type)
        self.assertEqual(sent["3"]["inputs"]["vae_name"], entry.profile.vae_name)
        self.assertEqual(sent["7"]["inputs"]["seed"], 1234)
        self.assertEqual(transport.calls[1]["path"], "/history/pid-1")
        self.assertEqual(graph["1"]["inputs"]["unet_name"], "unet-viejo.safetensors")
        self.assertEqual(graph["7"]["inputs"]["seed"], 1)

    def test_run_sin_png_devuelve_lista_vacia(self):
        transport = FakeTransport(
            [
                (200, json_bytes({"prompt_id": "pid-2"})),
                (200, json_bytes({"pid-2": {"status": {"status_str": "success"}}})),
            ]
        )
        engine = self.build_engine(transport, poll_s=0.0)

        self.assertEqual(run(engine, base_graph(), make_entry(), 42), [])

    def test_run_propaga_rechazo_del_submit(self):
        transport = FakeTransport([(400, json_bytes({"error": "bad prompt"}))])
        engine = self.build_engine(transport)

        with self.assertRaises(EngineError):
            run(engine, base_graph(), make_entry(), 42)

    def test_run_propaga_error_de_ejecucion(self):
        entry = {
            "status": {
                "status_str": "error",
                "messages": [["execution_error", {"node_id": "7"}]],
            }
        }
        transport = FakeTransport(
            [
                (200, json_bytes({"prompt_id": "pid-3"})),
                (200, json_bytes({"pid-3": entry})),
            ]
        )
        engine = self.build_engine(transport, poll_s=0.0)

        with self.assertRaises(EngineError) as ctx:
            run(engine, base_graph(), make_entry(), 42)

        self.assertIn("execution_error", str(ctx.exception))

    def test_run_falla_antes_de_enviar_si_el_grafo_no_tiene_seed(self):
        transport = FakeTransport()
        engine = self.build_engine(transport)
        graph = base_graph()
        del graph["7"]["inputs"]["seed"]

        with self.assertRaises(EngineError):
            run(engine, graph, make_entry(), 42)

        self.assertEqual(transport.calls, [])


class RealRegistryTests(unittest.TestCase):
    EXPECTED_IDS = [
        "anima-2.9b-preview",
        "anima-official-aesthetic-v11",
        "one-obsession-anima-v40",
    ]

    def test_load_real_tiene_tres_entradas_en_orden(self):
        registry = ModelRegistry.load(REGISTRY_PATH)

        self.assertEqual(len(registry), 3)
        self.assertEqual([entry.id for entry in registry.models], self.EXPECTED_IDS)

    def test_perfiles_coherentes_con_el_grafo_certificado(self):
        registry = ModelRegistry.load(REGISTRY_PATH)

        for entry in registry.models:
            with self.subTest(model_id=entry.id):
                self.assertEqual(entry.family, "anima")
                self.assertEqual(entry.preprompt, "glossy")
                self.assertEqual(entry.defaults, GRAPH_DEFAULTS)
                self.assertEqual(entry.profile.clip_name, "qwen_3_06b_base.safetensors")
                self.assertEqual(entry.profile.clip_type, "stable_diffusion")
                self.assertEqual(entry.profile.vae_name, "qwen_image_vae.safetensors")

    def test_nuevas_entradas_del_brief(self):
        registry = ModelRegistry.load(REGISTRY_PATH)
        aesthetic = registry.get("anima-official-aesthetic-v11")
        obsession = registry.get("one-obsession-anima-v40")

        self.assertEqual(aesthetic.display_name, "Anima [Official] aesthetic v1.1")
        self.assertEqual(aesthetic.profile.unet_name, "anima_aestheticV11.safetensors")
        self.assertEqual(aesthetic.source, "civitai.com/models/2458426 v3126581")
        self.assertEqual(
            aesthetic.license, "Anima License (CircleStone Labs LLC)"
        )
        self.assertIn(AESTHETIC_SHA256, aesthetic.notes)
        self.assertIn(AESTHETIC_BYTES, aesthetic.notes)
        self.assertIn("descargado 2026-09-21", aesthetic.notes)

        self.assertEqual(obsession.display_name, "One obsession_Anima v4.0")
        self.assertEqual(obsession.profile.unet_name, "oneObsessionAnima_v40.safetensors")
        self.assertEqual(obsession.source, "civitai.com/models/2695493 v3301424")
        self.assertEqual(
            obsession.license, "Anima License (CircleStone Labs LLC)"
        )
        self.assertIn(OBSESSION_SHA256, obsession.notes)
        self.assertIn(OBSESSION_BYTES, obsession.notes)
        self.assertIn("descargado 2026-09-21", obsession.notes)


if __name__ == "__main__":
    unittest.main()
