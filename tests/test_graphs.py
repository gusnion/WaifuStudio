"""Tests CPU de los manipuladores de grafos (F3a) con el grafo real certificado."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from app.engine import EngineError, load_graph
from app.graphs import IMG_ENC_ID, IMG_REF_ID, patch_model, patch_params, to_img2img
from app.registry import ModelEntry, ModelProfile

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = ROOT / "workflows" / "anima_base.json"


def real_graph() -> dict:
    return load_graph(GRAPH_PATH)


def make_entry() -> ModelEntry:
    return ModelEntry(
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
    )


class PatchModelTests(unittest.TestCase):
    def test_aplica_perfil_y_seed(self):
        patched = patch_model(real_graph(), make_entry(), 1234)

        self.assertEqual(patched["1"]["inputs"]["unet_name"], "unet-nuevo.safetensors")
        self.assertEqual(patched["1"]["inputs"]["weight_dtype"], "default")
        self.assertEqual(patched["2"]["inputs"]["clip_name"], "clip-nuevo.safetensors")
        self.assertEqual(patched["2"]["inputs"]["type"], "stable_diffusion")
        self.assertEqual(patched["3"]["inputs"]["vae_name"], "vae-nuevo.safetensors")
        self.assertEqual(patched["7"]["inputs"]["seed"], 1234)

    def test_sin_seed_no_toca_el_sampler(self):
        patched = patch_model(real_graph(), make_entry())

        self.assertEqual(patched["7"]["inputs"]["seed"], 42)
        self.assertEqual(patched["7"]["inputs"]["steps"], 20)

    def test_no_muta_el_original(self):
        graph = real_graph()
        snapshot = copy.deepcopy(graph)

        patched = patch_model(graph, make_entry(), 7)

        self.assertEqual(graph, snapshot)
        self.assertIsNot(patched, graph)

    def test_seed_en_todos_los_nodos_con_widget(self):
        graph = real_graph()
        graph["10"] = {"class_type": "KSamplerAdvanced", "inputs": {"seed": 5, "steps": 8}}

        patched = patch_model(graph, make_entry(), 7)

        self.assertEqual(patched["7"]["inputs"]["seed"], 7)
        self.assertEqual(patched["10"]["inputs"]["seed"], 7)

    def test_clip_con_widget_clip_type(self):
        graph = real_graph()
        graph["2"]["inputs"] = {"clip_name": "viejo.safetensors", "clip_type": "viejo"}

        patched = patch_model(graph, make_entry(), 1)

        self.assertEqual(patched["2"]["inputs"]["clip_type"], "stable_diffusion")
        self.assertNotIn("type", patched["2"]["inputs"])

    def test_falta_loader_lanza_engine_error(self):
        for node_id, label in (("1", "UNETLoader"), ("2", "CLIPLoader"), ("3", "VAELoader")):
            with self.subTest(loader=label):
                graph = real_graph()
                del graph[node_id]
                with self.assertRaises(EngineError):
                    patch_model(graph, make_entry(), 1)

    def test_seed_sin_nodo_seed_lanza_engine_error(self):
        graph = real_graph()
        del graph["7"]["inputs"]["seed"]

        with self.assertRaises(EngineError):
            patch_model(graph, make_entry(), 1)

    def test_entrada_sin_profile_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            patch_model(real_graph(), object(), 1)

    def test_seed_invalida_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            patch_model(real_graph(), make_entry(), "abc")


class PatchParamsTests(unittest.TestCase):
    def test_solo_aplica_lo_no_none(self):
        patched = patch_params(real_graph(), steps=8, cfg=5.5, width=512)

        inputs = patched["7"]["inputs"]
        self.assertEqual(inputs["steps"], 8)
        self.assertEqual(inputs["cfg"], 5.5)
        self.assertEqual(inputs["seed"], 42)
        self.assertEqual(inputs["sampler_name"], "euler")
        self.assertEqual(inputs["scheduler"], "sgm_uniform")
        self.assertEqual(inputs["denoise"], 1.0)
        self.assertEqual(patched["6"]["inputs"]["width"], 512)
        self.assertEqual(patched["6"]["inputs"]["height"], 576)

    def test_aplica_todos_los_parametros(self):
        patched = patch_params(
            real_graph(),
            seed=99,
            steps=30,
            cfg=6.5,
            sampler_name="dpmpp_2m",
            scheduler="karras",
            width=640,
            height=960,
        )

        inputs = patched["7"]["inputs"]
        self.assertEqual(
            (inputs["seed"], inputs["steps"], inputs["cfg"]), (99, 30, 6.5)
        )
        self.assertEqual(inputs["sampler_name"], "dpmpp_2m")
        self.assertEqual(inputs["scheduler"], "karras")
        self.assertEqual(
            (patched["6"]["inputs"]["width"], patched["6"]["inputs"]["height"]),
            (640, 960),
        )

    def test_no_muta_el_original(self):
        graph = real_graph()
        snapshot = copy.deepcopy(graph)

        patch_params(
            graph,
            seed=1,
            steps=2,
            cfg=3.0,
            sampler_name="euler",
            scheduler="normal",
            width=64,
            height=64,
        )

        self.assertEqual(graph, snapshot)

    def test_convierte_valores_de_texto(self):
        patched = patch_params(
            real_graph(),
            seed="11",
            steps="12",
            cfg="7.5",
            width="384",
            height="512",
        )

        self.assertEqual(patched["7"]["inputs"]["seed"], 11)
        self.assertEqual(patched["7"]["inputs"]["steps"], 12)
        self.assertEqual(patched["7"]["inputs"]["cfg"], 7.5)
        self.assertEqual(patched["6"]["inputs"]["width"], 384)
        self.assertEqual(patched["6"]["inputs"]["height"], 512)

    def test_parametro_invalido_lanza_engine_error(self):
        for kwargs in ({"steps": "abc"}, {"cfg": [1.0]}, {"seed": "x"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(EngineError):
                    patch_params(real_graph(), **kwargs)

    def test_sin_nodo_ksampler_lanza_engine_error(self):
        graph = real_graph()
        del graph["7"]

        with self.assertRaises(EngineError):
            patch_params(graph, steps=10)

    def test_sin_nodo_latente_lanza_engine_error(self):
        graph = real_graph()
        del graph["6"]

        with self.assertRaises(EngineError):
            patch_params(graph, width=512)

    def test_sin_widget_lanza_engine_error(self):
        graph = real_graph()
        del graph["7"]["inputs"]["scheduler"]

        with self.assertRaises(EngineError):
            patch_params(graph, scheduler="normal")

    def test_sin_widget_height_lanza_engine_error(self):
        graph = real_graph()
        del graph["6"]["inputs"]["height"]

        with self.assertRaises(EngineError):
            patch_params(graph, height=512)


class ToImg2ImgTests(unittest.TestCase):
    def test_estructura_exacta(self):
        graph = real_graph()

        patched = to_img2img(graph, "ref.png", 0.55)

        self.assertEqual(len(graph), 9)
        self.assertEqual(len(patched), 10)
        self.assertNotIn("6", patched)
        self.assertEqual(
            patched[IMG_REF_ID],
            {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
        )
        self.assertEqual(
            patched[IMG_ENC_ID],
            {
                "class_type": "VAEEncode",
                "inputs": {"pixels": [IMG_REF_ID, 0], "vae": ["3", 0]},
            },
        )
        self.assertEqual(patched["7"]["inputs"]["latent_image"], [IMG_ENC_ID, 0])
        self.assertEqual(patched["7"]["inputs"]["denoise"], 0.55)
        self.assertEqual(graph["6"]["inputs"]["width"], 320)
        self.assertEqual(graph["7"]["inputs"]["latent_image"], ["6", 0])
        self.assertEqual(graph["7"]["inputs"]["denoise"], 1.0)

    def test_strength_por_defecto(self):
        patched = to_img2img(real_graph(), "ref.png")

        self.assertEqual(patched["7"]["inputs"]["denoise"], 0.6)

    def test_strength_uno_es_valido(self):
        patched = to_img2img(real_graph(), "ref.png", 1)

        self.assertEqual(patched["7"]["inputs"]["denoise"], 1.0)

    def test_strength_invalido_lanza_engine_error(self):
        for strength in (0, -0.5, 1.01, 2, "abc", None):
            with self.subTest(strength=strength):
                with self.assertRaises(EngineError):
                    to_img2img(real_graph(), "ref.png", strength)

    def test_ids_ocupados_lanzan_engine_error(self):
        for node_id in (IMG_REF_ID, IMG_ENC_ID):
            with self.subTest(node_id=node_id):
                graph = real_graph()
                graph[node_id] = {
                    "class_type": "LoadImage",
                    "inputs": {"image": "x.png"},
                }
                with self.assertRaises(EngineError):
                    to_img2img(graph, "ref.png", 0.5)

    def test_vae_se_localiza_por_class_type(self):
        graph = real_graph()
        graph["30"] = graph.pop("3")

        patched = to_img2img(graph, "ref.png", 0.5)

        self.assertEqual(patched[IMG_ENC_ID]["inputs"]["vae"], ["30", 0])

    def test_falta_vae_ksampler_o_latente(self):
        for node_id in ("3", "7", "6"):
            with self.subTest(node_id=node_id):
                graph = real_graph()
                del graph[node_id]
                with self.assertRaises(EngineError):
                    to_img2img(graph, "ref.png", 0.5)

    def test_imagen_invalida_lanza_engine_error(self):
        for image_name in ("", None):
            with self.subTest(image_name=image_name):
                with self.assertRaises(EngineError):
                    to_img2img(real_graph(), image_name, 0.5)

    def test_varios_ksampler_se_rewirean(self):
        graph = real_graph()
        graph["10"] = copy.deepcopy(graph["7"])

        patched = to_img2img(graph, "ref.png", 0.4)

        self.assertEqual(patched["10"]["inputs"]["latent_image"], [IMG_ENC_ID, 0])
        self.assertEqual(patched["10"]["inputs"]["denoise"], 0.4)


if __name__ == "__main__":
    unittest.main()
