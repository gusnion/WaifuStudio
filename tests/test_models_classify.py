"""Tests CPU de la clasificacion BASE de modelos (W1). Sin red ni GPU."""

from __future__ import annotations

import unittest

from app.registry import DEFAULT_SUBFAMILY, infer_prompt_profile, infer_subfamily

SDXL_TENSORS = (
    "conditioner.embedders.0.transformer.text_model.embeddings.token_embedding.weight",
    "conditioner.embedders.1.model.token_embedding.weight",
    "first_stage_model.encoder.conv_in.weight",
    "model.diffusion_model.input_blocks.0.0.weight",
    "model.diffusion_model.output_blocks.0.0.weight",
)
ANIMA_TENSORS = (
    "model.diffusion_model.blocks.0.self_attn.q_proj.weight",
    "model.diffusion_model.blocks.1.self_attn.q_proj.weight",
    "model.diffusion_model.final_layer.linear.weight",
)


class InferSubfamilyBaseTests(unittest.TestCase):
    def test_sdxl_layout_sin_metadata_es_sdxl_base(self):
        self.assertEqual(infer_subfamily({}, SDXL_TENSORS), "sdxl_base")
        self.assertEqual(infer_subfamily(None, list(SDXL_TENSORS), "modelo.safetensors"), "sdxl_base")

    def test_anima_layout_es_anima(self):
        self.assertEqual(infer_subfamily({}, ANIMA_TENSORS), "anima")
        self.assertEqual(infer_subfamily({}, ("net.blocks.0.attn.weight",)), "anima")

    def test_sdxl_layout_no_es_anima_aunque_nombre_diga_anima(self):
        self.assertEqual(infer_subfamily({}, SDXL_TENSORS, "AnimaPencil_anima.safetensors"), "sdxl_base")

    def test_animagine_no_es_anima(self):
        self.assertNotEqual(infer_subfamily({}, None, "animagine-xl-4.safetensors"), "anima")
        self.assertEqual(infer_subfamily({}, None, "animagine-xl-4.safetensors"), "sdxl_base")
        self.assertEqual(infer_subfamily({"ss_base_model_version": "animagine-xl-4"}), "sdxl_base")
        self.assertEqual(infer_subfamily({}, SDXL_TENSORS, "animagine-xl-4.safetensors"), "sdxl_base")

    def test_nombre_anima_solo_es_pista(self):
        self.assertEqual(infer_subfamily({}, None, "anima-preview.safetensors"), "anima")
        self.assertEqual(infer_subfamily({}, ANIMA_TENSORS, "ilustrious-lookalike.safetensors"), "anima")

    def test_nombre_refina_layout_sdxl(self):
        self.assertEqual(infer_subfamily({}, SDXL_TENSORS, "ilxl/Illustrious-XL-v1.safetensors"), "illustrious")

    def test_desconocido_es_sin_clasificar(self):
        self.assertEqual(infer_subfamily(), DEFAULT_SUBFAMILY)
        self.assertEqual(infer_subfamily({}, ("foo.weight", "bar.bias"), "modelo.safetensors"), DEFAULT_SUBFAMILY)
        self.assertEqual(infer_subfamily({}, [], ""), DEFAULT_SUBFAMILY)

    def test_layout_video_no_se_confunde_con_anima(self):
        wan = ("patch_embedding.weight", "blocks.0.self_attn.q.weight", "model.diffusion_model.blocks.0.x")
        self.assertEqual(infer_subfamily({}, wan), DEFAULT_SUBFAMILY)

    def test_metadata_manda_sobre_tensores_y_nombre(self):
        self.assertEqual(
            infer_subfamily({"modelspec.architecture": "pony"}, ANIMA_TENSORS, "anima.safetensors"),
            "pony",
        )
        self.assertEqual(
            infer_subfamily({"ss_base_model_version": "illustrious-xl-v1.0"}, SDXL_TENSORS, "pony.safetensors"),
            "illustrious",
        )

    def test_compat_firma_legacy(self):
        self.assertEqual(infer_subfamily(modelspec_architecture="pony"), "pony")
        self.assertEqual(infer_subfamily("sdxl_v1-0"), "sdxl_base")


class InferPromptProfileSubfamilyTests(unittest.TestCase):
    def test_sdxl_con_nombre_anima_no_usa_perfil_anima(self):
        self.assertEqual(infer_prompt_profile("animapencil", family="sdxl"), "sdxl_tags")

    def test_anima_por_familia_o_subfamilia(self):
        self.assertEqual(infer_prompt_profile("x", family="anima"), "anima")
        self.assertEqual(infer_prompt_profile("x", subfamily="anima"), "anima")

    def test_nombre_manda_para_natural(self):
        self.assertEqual(infer_prompt_profile("realvisxl-v5", family="sdxl", subfamily="sdxl_base"), "sdxl_natural")


if __name__ == "__main__":
    unittest.main()
