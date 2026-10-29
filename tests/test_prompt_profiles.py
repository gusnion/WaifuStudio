"""Tests W2 base: perfiles y preprompts por modelo (Animagine propio, natural sin tags).

Sin red ni GPU: LLM falso, TestClient y registro/disco en directorios temporales.
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import EngineConfig
from app.enhancer import (
    NO_RAG_PROFILES,
    PROMPT_PROFILE_SYS_PROMPTS,
    SYS_PROMPT,
    SYS_PROMPT_ANIMAGINE,
    SYS_PROMPT_SDXL_NATURAL,
    SYS_PROMPT_SDXL_TAGS,
    enhance,
    get_sys_prompt,
    retrieve,
)
from app.preprompts import (
    DEFAULT_PREPROMPT_BY_PROFILE,
    default_preprompt,
    default_preprompt_for_profile,
    get_preprompt,
)
from app.registry import (
    PROMPT_PROFILES,
    ModelEntry,
    ModelProfile,
    ModelRegistry,
    infer_prompt_profile,
)
from app.server import create_app
from app.store import Store

SCORE_TAGS = ("score_7", "score_8", "score_9")
NOTES_HEADER = "Notas de referencia (no copiar a la salida):"


class CapturingLLM:
    """LLM falso que acepta `temperature` y captura (system, user)."""

    def __init__(self, output: str = "1girl, smile") -> None:
        self.output = output
        self.calls: list[dict] = []

    def __call__(self, system, user, temperature=None):
        self.calls.append({"system": system, "user": user})
        return self.output


def _checkpoint_profile(unet: str = "x.safetensors") -> ModelProfile:
    return ModelProfile(
        unet_name=unet,
        clip_name="__checkpoint__",
        clip_type="checkpoint",
        vae_name="__checkpoint__",
    )


class InferPromptProfileTests(unittest.TestCase):
    def test_perfiles_incluyen_animagine(self):
        self.assertIn("animagine", PROMPT_PROFILES)
        self.assertEqual(set(PROMPT_PROFILE_SYS_PROMPTS), set(PROMPT_PROFILES))
        self.assertEqual(set(DEFAULT_PREPROMPT_BY_PROFILE), set(PROMPT_PROFILES))

    def test_animagine_tiene_perfil_propio(self):
        self.assertEqual(infer_prompt_profile("animagine-xl-4-opt"), "animagine")
        self.assertEqual(
            infer_prompt_profile(display_name="Animagine XL 4.0 Opt", family="sdxl"),
            "animagine",
        )
        self.assertEqual(
            infer_prompt_profile(unet_name="animagine-xl-4.0-opt.safetensors"),
            "animagine",
        )

    def test_animagine_no_se_confunde_con_anima(self):
        self.assertNotEqual(infer_prompt_profile("animagine-xl-4", family="sdxl"), "anima")
        self.assertEqual(infer_prompt_profile("anima-2.9b-preview", family="anima"), "anima")

    def test_realvis_y_juggernaut_son_natural(self):
        self.assertEqual(infer_prompt_profile("realvisxl-v50"), "sdxl_natural")
        self.assertEqual(
            infer_prompt_profile("juggernaut-xl-ragnarok", family="sdxl"), "sdxl_natural"
        )

    def test_tags_genericos_son_sdxl_tags(self):
        self.assertEqual(infer_prompt_profile("modelo-custom", family="sdxl"), "sdxl_tags")
        self.assertEqual(
            infer_prompt_profile("illu-x", family="sdxl", subfamily="illustrious"),
            "sdxl_tags",
        )
        self.assertEqual(infer_prompt_profile("animapencil", family="sdxl"), "sdxl_tags")

    def test_model_entry_infiere_animagine(self):
        entry = ModelEntry(
            id="animagine-xl-4-opt",
            family="sdxl",
            display_name="Animagine XL 4.0 Opt",
            profile=_checkpoint_profile("animagine-xl-4.0-opt.safetensors"),
            source="local",
            license="x",
        )
        self.assertEqual(entry.prompt_profile, "animagine")

    def test_registro_acepta_perfil_animagine_explicito_y_serializa(self):
        raw = {
            "id": "animagine-xl-4-opt",
            "family": "sdxl",
            "display_name": "Animagine XL 4.0 Opt",
            "profile": {
                "unet_name": "animagine.safetensors",
                "clip_name": "__checkpoint__",
                "clip_type": "checkpoint",
                "vae_name": "__checkpoint__",
            },
            "source": "x",
            "license": "x",
            "prompt_profile": "animagine",
        }
        reg = ModelRegistry.from_dict({"version": 1, "models": [raw]})
        self.assertEqual(reg.get("animagine-xl-4-opt").prompt_profile, "animagine")


class DefaultPreprompTests(unittest.TestCase):
    def test_default_por_perfil(self):
        self.assertEqual(default_preprompt_for_profile("anima"), ("anima", "glossy"))
        self.assertEqual(default_preprompt_for_profile("animagine"), ("sdxl", "animagine"))
        self.assertEqual(default_preprompt_for_profile("sdxl_tags"), ("sdxl", "sdxl_default"))
        self.assertEqual(default_preprompt_for_profile("sdxl_natural"), ("sdxl", "ninguno"))
        self.assertEqual(default_preprompt_for_profile("qwen_edit"), ("sdxl", "ninguno"))

    def test_sdxl_default_no_es_fallback_de_natural(self):
        _, name = default_preprompt_for_profile("sdxl_natural", "sdxl")
        self.assertNotEqual(name, "sdxl_default")
        self.assertEqual(get_preprompt("sdxl", name), {"positive": "", "negative": ""})

    def test_perfil_manda_sobre_familia(self):
        self.assertEqual(
            default_preprompt_for_profile("animagine", "anima"), ("sdxl", "animagine")
        )

    def test_sin_perfil_cae_a_default_de_familia(self):
        self.assertEqual(default_preprompt_for_profile(None), ("anima", "glossy"))
        self.assertEqual(default_preprompt_for_profile("", "sdxl"), ("sdxl", "sdxl_default"))
        self.assertEqual(default_preprompt_for_profile("desconocido", "anima"), ("anima", "glossy"))
        self.assertEqual(default_preprompt("anima"), "glossy")

    def test_todos_los_defaults_existen_en_su_familia(self):
        for profile, (family, name) in DEFAULT_PREPROMPT_BY_PROFILE.items():
            with self.subTest(profile=profile):
                data = get_preprompt(family, name)
                self.assertIn("positive", data)

    def test_animagine_no_trae_scores_de_anima(self):
        data = get_preprompt(*default_preprompt_for_profile("animagine"))
        for tag in SCORE_TAGS:
            self.assertNotIn(tag, data["positive"])


def _safetensors_blob(tensors: dict) -> bytes:
    header = {name: {"dtype": "F16", "shape": [1], "data_offsets": [0, 0]} for name in tensors}
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


class ScanDiskModelsPreprompTests(unittest.TestCase):
    def test_checkpoint_animagine_y_realvis_reciben_perfil_y_preprompt(self):
        from app.routes.models import scan_disk_models

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comfy = root / "ComfyUI"
            ckpt = comfy / "models" / "checkpoints"
            ckpt.mkdir(parents=True)
            blob = _safetensors_blob(
                {
                    "model.diffusion_model.input_blocks.0.weight": 1,
                    "conditioner.embedders.0.weight": 1,
                    "first_stage_model.decoder.weight": 1,
                }
            )
            for name in ("animagine-xl-4.0-opt", "RealVisXL_V5.0", "genericilu"):
                (ckpt / f"{name}.safetensors").write_bytes(blob)
            cfg = EngineConfig(
                comfy_root=comfy,
                comfy_url="http://127.0.0.1:8288",
                data_dir=root / "data",
            )
            reg = ModelRegistry()
            scan_disk_models(cfg, reg)
        by_name = {entry.display_name.lower(): entry for entry in reg.models}
        animagine = by_name["animagine-xl-4.0-opt"]
        self.assertEqual((animagine.prompt_profile, animagine.preprompt), ("animagine", "animagine"))
        realvis = by_name["realvisxl_v5.0"]
        self.assertEqual((realvis.prompt_profile, realvis.preprompt), ("sdxl_natural", "ninguno"))
        generic = by_name["genericilu"]
        self.assertEqual((generic.prompt_profile, generic.preprompt), ("sdxl_tags", "sdxl_default"))


class EnhancerProfileTests(unittest.TestCase):
    def test_sys_prompt_animagine_propio(self):
        prompt = get_sys_prompt("animagine")
        self.assertEqual(prompt, SYS_PROMPT_ANIMAGINE)
        self.assertNotEqual(prompt, SYS_PROMPT_SDXL_TAGS)
        self.assertIn("NEVER use Anima score tags", prompt)

    def test_retrieve_sin_perfil_es_retrocompatible(self):
        self.assertEqual(retrieve("score_9", k=3), retrieve("score_9", k=3, profile="anima"))
        self.assertTrue(retrieve("score_9", k=3))

    def test_retrieve_animagine_y_sdxl_tags_sin_notas_de_anima(self):
        for profile in ("animagine", "sdxl_tags"):
            with self.subTest(profile=profile):
                notes = retrieve("score_9 preprompt glossy artista calidad", k=10, profile=profile)
                joined = " ".join(notes)
                for tag in SCORE_TAGS:
                    self.assertNotIn(tag, joined)
                self.assertNotIn("glossy", joined)
                self.assertNotIn("@", joined)

    def test_retrieve_natural_y_qwen_no_reciben_rag(self):
        for profile in NO_RAG_PROFILES:
            self.assertEqual(retrieve("score_9 calidad nsfw", k=10, profile=profile), [])

    def test_enhance_sin_perfil_mantiene_anima_glossy(self):
        result = enhance("1girl", llm=CapturingLLM("1girl, smile"))
        self.assertIn("score_8", result["positive"])
        self.assertIn("score_9", result["positive"])

    def test_enhance_animagine_no_inyecta_scores_de_anima(self):
        llm = CapturingLLM("1girl, smile, score_9, @someartist")
        result = enhance("1girl", prompt_profile="animagine", rating="sfw", llm=llm)
        self.assertEqual(llm.calls[0]["system"], SYS_PROMPT_ANIMAGINE)
        for tag in SCORE_TAGS:
            self.assertNotIn(tag, result["positive"])
        self.assertNotIn("@", result["positive"])
        self.assertIn("score_9", result["dropped"])
        self.assertIn("@someartist", result["dropped"])
        self.assertIn("high score", result["positive"])
        self.assertIn("great score", result["positive"])
        self.assertNotIn("score_1", result["negative"])
        self.assertIn("low score", result["negative"])
        self.assertNotIn("Calidad con la familia score_", llm.calls[0]["user"])

    def test_enhance_sdxl_tags_usa_sdxl_default(self):
        result = enhance("1girl", prompt_profile="sdxl_tags", llm=CapturingLLM("1girl, smile"))
        for tag in SCORE_TAGS:
            self.assertNotIn(tag, result["positive"])
        self.assertIn("masterpiece", result["positive"])

    def test_enhance_natural_sin_preprompt_no_hereda_anima_ni_rag(self):
        prose = "A woman reading on a sunlit bench, soft golden light."
        llm = CapturingLLM(prose)
        result = enhance("woman reading nsfw score_9 calidad", prompt_profile="sdxl_natural", llm=llm)
        self.assertEqual(llm.calls[0]["system"], SYS_PROMPT_SDXL_NATURAL)
        self.assertEqual(result["positive"], prose)
        self.assertNotIn("score_", result["negative"])
        self.assertNotIn(NOTES_HEADER, llm.calls[0]["user"])

    def test_enhance_preprompt_explicito_manda(self):
        llm = CapturingLLM("1girl, smile")
        result = enhance(
            "1girl",
            family="anima",
            preprompt="anima_default",
            prompt_profile="anima",
            llm=llm,
        )
        self.assertIn("score_8", result["positive"])
        self.assertNotIn("score_7", result["positive"])

    def test_enhance_preprompt_explicito_sin_familia_con_perfil_sdxl(self):
        result = enhance(
            "1girl",
            preprompt="animagine",
            prompt_profile="animagine",
            llm=CapturingLLM("1girl, smile"),
        )
        self.assertIn("high score", result["positive"])

    def test_enhance_sys_prompt_legacy_sin_perfil(self):
        llm = CapturingLLM()
        enhance("1girl", llm=llm)
        self.assertEqual(llm.calls[0]["system"], SYS_PROMPT)


class EnhanceZonesRouteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def client(self, llm) -> TestClient:
        from tests.test_server import REGISTRY_FIXTURE, make_config

        cfg = make_config(Path(self._tmp.name))
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(cfg.data_dir / "waifu.db")
        store.init()
        app = create_app(
            config=cfg,
            store=store,
            registry=ModelRegistry.load(REGISTRY_FIXTURE),
            llm=llm,
            start_worker=False,
        )
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def post(self, llm, **payload):
        payload.setdefault("text", "1girl")
        return self.client(llm).post("/api/prompt/enhance_zones", json=payload)

    def test_animagine_no_recibe_scores_de_anima(self):
        llm = CapturingLLM("1girl, smile, score_9")
        response = self.post(llm, prompt_profile="animagine", family="sdxl")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(llm.calls[0]["system"], SYS_PROMPT_ANIMAGINE)
        for tag in SCORE_TAGS:
            self.assertNotIn(tag, data["positive"])
            self.assertNotIn(tag, data["composed"])
        self.assertIn("score_9", data["dropped"])
        self.assertIn("high score", data["positive"])

    def test_animagine_sin_family_ni_preprompt_usa_default_del_perfil(self):
        llm = CapturingLLM("1girl, smile")
        response = self.post(llm, prompt_profile="animagine")
        self.assertEqual(response.status_code, 200)
        positive = response.json()["positive"]
        self.assertIn("high score", positive)
        self.assertNotIn("score_8", positive)

    def test_natural_sin_rag_ni_preprompt_de_anima(self):
        prose = "A photo-like portrait of a woman by a window."
        llm = CapturingLLM(prose)
        response = self.post(
            llm, text="woman nsfw score_9 calidad", prompt_profile="sdxl_natural"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(llm.calls[0]["system"], SYS_PROMPT_SDXL_NATURAL)
        self.assertNotIn(NOTES_HEADER, llm.calls[0]["user"])
        self.assertNotIn("score_", data["positive"])
        self.assertNotIn("score_", data["negative"])

    def test_preprompt_explicito_se_respeta(self):
        llm = CapturingLLM("1girl, smile")
        response = self.post(
            llm, prompt_profile="sdxl_tags", family="sdxl", preprompt="ninguno"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("masterpiece, best quality, highres", response.json()["positive"])

    def test_family_sdxl_sin_perfil_usa_sdxl_tags(self):
        llm = CapturingLLM("1girl, smile")
        response = self.post(llm, family="sdxl")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.calls[0]["system"], SYS_PROMPT_SDXL_TAGS)
        for tag in SCORE_TAGS:
            self.assertNotIn(tag, response.json()["positive"])

    def test_sin_family_ni_perfil_es_retrocompatible(self):
        llm = CapturingLLM("1girl, smile")
        response = self.post(llm)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(llm.calls[0]["system"], SYS_PROMPT)
        self.assertIn("score_8", response.json()["positive"])

    def test_family_y_preprompt_invalidos_400(self):
        for field, value in (
            ("family", 3),
            ("preprompt", ["x"]),
            ("family", "  "),
            ("preprompt", {}),
        ):
            with self.subTest(field=field, value=value):
                llm = CapturingLLM()
                response = self.post(llm, **{field: value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(llm.calls, [])

    def test_perfil_invalido_sigue_400(self):
        llm = CapturingLLM()
        response = self.post(llm, prompt_profile="perfil_falso")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(llm.calls, [])


if __name__ == "__main__":
    unittest.main()
