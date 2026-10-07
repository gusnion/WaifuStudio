"""Tests CPU de los manipuladores de grafos (F3a) con el grafo real certificado."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from app.engine import EngineError, load_graph
from app.graphs import (
    ANIMA_PATCH_CLASS,
    IMG_ENC_ID,
    IMG_REF_ID,
    LORA_CLASS,
    apply_loras,
    patch_model,
    patch_params,
    to_img2img,
)
from app.registry import ModelEntry, ModelProfile
from app.video import prepare_h3_graph

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


class ApplyLorasTests(unittest.TestCase):
    def test_un_lora_estructura_exacta_y_rewire(self):
        graph = real_graph()

        patched = apply_loras(
            graph, [{"file": "reika.safetensors", "weight": 0.8}]
        )

        self.assertEqual(len(graph), 9)
        self.assertEqual(len(patched), 10)
        self.assertEqual(
            patched["lora_1"],
            {
                "class_type": LORA_CLASS,
                "inputs": {
                    "model": ["1", 0],
                    "lora_name": "reika.safetensors",
                    "strength_model": 0.8,
                },
            },
        )
        self.assertEqual(patched["7"]["inputs"]["model"], ["lora_1", 0])
        self.assertEqual(graph["7"]["inputs"]["model"], ["1", 0])
        self.assertNotIn("lora_1", graph)

    def test_weight_por_defecto_uno(self):
        patched = apply_loras(real_graph(), [{"file": "x.safetensors"}])

        self.assertEqual(patched["lora_1"]["inputs"]["strength_model"], 1.0)

    def test_resuelve_file_y_weight_por_id(self):
        patched = apply_loras(
            real_graph(), [{"id": "kurashiki-reika-saimin-anima", "weight": 0.8}]
        )

        self.assertEqual(
            patched["lora_1"]["inputs"]["lora_name"],
            "anima\\Kurashiki Reika Saimin Seishidou.safetensors",
        )
        self.assertEqual(patched["lora_1"]["inputs"]["strength_model"], 0.8)

    def test_id_sin_weight_usa_el_default_del_registro(self):
        patched = apply_loras(real_graph(), [{"id": "shuuko-komi-s1s2-anima"}])

        self.assertEqual(patched["lora_1"]["inputs"]["strength_model"], 1.0)

    def test_id_miku_anima_usa_su_file_y_peso_uno(self):
        patched = apply_loras(real_graph(), [{"id": "miku-nakano-anima"}])

        self.assertEqual(
            patched["lora_1"]["inputs"]["lora_name"],
            "anima\\Miku_Nakano_Anima_v0.7.safetensors",
        )
        self.assertEqual(patched["lora_1"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(patched["7"]["inputs"]["model"], ["lora_1", 0])

    def test_id_desconocido_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            apply_loras(real_graph(), [{"id": "no-existe"}])

    def test_cadena_de_dos_loras(self):
        patched = apply_loras(
            real_graph(),
            [
                {"file": "primera.safetensors", "weight": 0.7},
                {"file": "segunda.safetensors", "weight": 1.2},
            ],
        )

        self.assertEqual(patched["lora_1"]["inputs"]["model"], ["1", 0])
        self.assertEqual(patched["lora_1"]["inputs"]["lora_name"], "primera.safetensors")
        self.assertEqual(patched["lora_2"]["inputs"]["model"], ["lora_1", 0])
        self.assertEqual(patched["lora_2"]["inputs"]["lora_name"], "segunda.safetensors")
        self.assertEqual(patched["lora_2"]["inputs"]["strength_model"], 1.2)
        self.assertEqual(patched["7"]["inputs"]["model"], ["lora_2", 0])
        self.assertEqual(len(patched), 11)

    def test_lista_vacia_devuelve_copia_sin_cambios(self):
        graph = real_graph()
        graph["lora_1"] = {"class_type": "Otro", "inputs": {}}

        patched = apply_loras(graph, [])

        self.assertEqual(patched, graph)
        self.assertIsNot(patched, graph)

    def test_lista_vacia_sin_loader_no_falla(self):
        graph = real_graph()
        del graph["1"]

        patched = apply_loras(graph, [])

        self.assertEqual(patched, graph)

    def test_localiza_unetloader_gguf(self):
        graph = real_graph()
        graph["1"]["class_type"] = "UnetLoaderGGUF"

        patched = apply_loras(graph, [{"file": "x.safetensors", "weight": 1.0}])

        self.assertEqual(patched["lora_1"]["inputs"]["model"], ["1", 0])
        self.assertEqual(patched["7"]["inputs"]["model"], ["lora_1", 0])

    def test_sin_loader_lanza_engine_error(self):
        graph = real_graph()
        del graph["1"]

        with self.assertRaises(EngineError):
            apply_loras(graph, [{"file": "x.safetensors", "weight": 1.0}])

    def test_ids_lora_ocupados_lanzan_engine_error(self):
        for node_id in ("lora_1", "lora_2"):
            with self.subTest(node_id=node_id):
                graph = real_graph()
                graph[node_id] = {"class_type": "Otro", "inputs": {}}
                with self.assertRaises(EngineError):
                    apply_loras(
                        graph,
                        [
                            {"file": "a.safetensors", "weight": 1.0},
                            {"file": "b.safetensors", "weight": 1.0},
                        ],
                    )

    def test_rewirea_todos_los_inputs_model_del_loader(self):
        graph = real_graph()
        graph["10"] = {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["1", 0], "steps": 4},
        }
        graph["11"] = {
            "class_type": "Otro",
            "inputs": {"clip": ["1", 0], "model": ["3", 0]},
        }

        patched = apply_loras(graph, [{"file": "x.safetensors", "weight": 1.0}])

        self.assertEqual(patched["10"]["inputs"]["model"], ["lora_1", 0])
        self.assertEqual(patched["11"]["inputs"]["clip"], ["1", 0])
        self.assertEqual(patched["11"]["inputs"]["model"], ["3", 0])

    def test_loras_no_lista_lanza_engine_error(self):
        for loras in (None, {}, "x"):
            with self.subTest(loras=loras):
                with self.assertRaises(EngineError):
                    apply_loras(real_graph(), loras)

    def test_item_no_dict_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            apply_loras(real_graph(), ["x"])

    def test_falta_file_lanza_engine_error(self):
        for file in (None, "", "   "):
            with self.subTest(file=file):
                with self.assertRaises(EngineError):
                    apply_loras(real_graph(), [{"file": file, "weight": 1.0}])

    def test_weight_invalido_lanza_engine_error(self):
        for weight in (True, -0.5, 2.5, "abc", [1.0], float("nan")):
            with self.subTest(weight=weight):
                with self.assertRaises(EngineError):
                    apply_loras(
                        real_graph(), [{"file": "x.safetensors", "weight": weight}]
                    )

    def test_no_muta_el_original_con_dos_loras(self):
        graph = real_graph()
        snapshot = copy.deepcopy(graph)

        apply_loras(
            graph,
            [
                {"file": "a.safetensors", "weight": 0.5},
                {"file": "b.safetensors", "weight": 1.0},
            ],
        )

        self.assertEqual(graph, snapshot)

    def test_anima_29b_preview_usa_nodo_waifu_anima_patch(self):
        graph = real_graph()
        patched = apply_loras(
            graph,
            [{"file": "reika.safetensors", "weight": 0.8}],
            model_id="anima-2.9b-preview",
        )
        self.assertEqual(patched["lora_1"]["class_type"], ANIMA_PATCH_CLASS)

    def test_one_obsession_v40_usa_nodo_estandar_lora_loader(self):
        # one-obsession-anima-v40 es de 28 bloques (v4.0 no significa 40 bloques);
        # debe usar LoraLoaderModelOnly para no desalinear pesos LoRA.
        graph = real_graph()
        patched = apply_loras(
            graph,
            [{"file": "reika.safetensors", "weight": 0.8}],
            model_id="one-obsession-anima-v40",
        )
        self.assertEqual(patched["lora_1"]["class_type"], LORA_CLASS)

    def test_modelo_estandar_usa_lora_loader_normal(self):
        graph = real_graph()
        patched = apply_loras(
            graph,
            [{"file": "reika.safetensors", "weight": 0.8}],
            model_id="anima-official-aesthetic-v11",
        )
        self.assertEqual(patched["lora_1"]["class_type"], LORA_CLASS)


class PrepareH3Ref2VAGraphTests(unittest.TestCase):
    def test_wiring_minimax_h3_reference_to_video(self):
        ref2va_path = ROOT / "workflows" / "h3_ref2va.api.json"
        graph = load_graph(ref2va_path)

        ref_names = ["ref_a.png", "ref_b.png", "ref_c.png"]
        patched = prepare_h3_graph(
            graph,
            ref_image_names=ref_names,
            prompt="1girl looking at camera",
            seed=42,
            width=576,
            height=1024,
            frames=192,
        )

        self.assertEqual(patched["131"]["class_type"], "MiniMaxH3ReferenceToVideo")
        inputs = patched["131"]["inputs"]
        self.assertEqual(inputs["prompt"], "1girl looking at camera")
        self.assertEqual(inputs["width"], 576)
        self.assertEqual(inputs["height"], 1024)
        self.assertEqual(inputs["length"], 192)
        self.assertEqual(inputs["ref_image_size"], "match")

        self.assertEqual(inputs["ref_image_1"], ["140", 0])
        self.assertEqual(inputs["ref_image_2"], ["141", 0])
        self.assertEqual(inputs["ref_image_3"], ["142", 0])
        self.assertNotIn("ref_image_4", inputs)

        self.assertEqual(patched["140"]["inputs"]["image"], "ref_a.png")
        self.assertEqual(patched["141"]["inputs"]["image"], "ref_b.png")
        self.assertEqual(patched["142"]["inputs"]["image"], "ref_c.png")
        self.assertNotIn("143", patched)

        self.assertEqual(patched["126"]["inputs"]["conditioning"], ["131", 0])
        self.assertEqual(patched["125"]["inputs"]["latent_image"], ["131", 1])
        self.assertEqual(patched["136"]["class_type"], "ApplyVDNH3")
        self.assertEqual(
            patched["136"]["inputs"]["vdn_checkpoint"],
            "vdn-minimax-h3-int8-convrot-comfyui-ref2va",
        )
        self.assertEqual(patched["126"]["inputs"]["model"], ["136", 0])
        self.assertEqual(patched["124"]["inputs"]["model"], ["136", 0])

    def test_wiring_minimax_h3_reference_sin_referencias_lanza_error(self):
        ref2va_path = ROOT / "workflows" / "h3_ref2va.api.json"
        graph = load_graph(ref2va_path)
        with self.assertRaises(EngineError):
            prepare_h3_graph(
                graph,
                prompt="test",
                seed=42,
            )


if __name__ == "__main__":
    unittest.main()

