"""Tests CPU del registro de modelos (M8-10). Sin red ni GPU."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

from app.engine import EngineError
from app.registry import (
    DEFAULT_PROMPT_PROFILE,
    DEFAULT_SUBFAMILY,
    KNOWN_SUBFAMILIES,
    ModelEntry,
    ModelProfile,
    ModelRegistry,
    infer_prompt_profile,
    infer_subfamily,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tests" / "fixtures" / "models.json"
GRAPH_PATH = ROOT / "workflows" / "anima_base.json"

GRAPH_DEFAULTS = {
    "steps": 20,
    "cfg": 4.0,
    "sampler_name": "euler",
    "scheduler": "sgm_uniform",
    "width": 320,
    "height": 576,
}


def graph_profile() -> ModelProfile:
    """Perfil UNETLoader/CLIPLoader/VAELoader del grafo certificado anima_base.json."""
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    loaders: dict[str, dict] = {}
    for node in graph.values():
        loaders.setdefault(node["class_type"], node["inputs"])
    return ModelProfile(
        unet_name=loaders["UNETLoader"]["unet_name"],
        clip_name=loaders["CLIPLoader"]["clip_name"],
        clip_type=loaders["CLIPLoader"]["type"],
        vae_name=loaders["VAELoader"]["vae_name"],
    )


def make_entry(model_id: str = "modelo-test", **overrides) -> ModelEntry:
    base = dict(
        id=model_id,
        family="anima",
        display_name="Modelo de test",
        profile=ModelProfile(
            unet_name="unet.safetensors",
            clip_name="clip.safetensors",
            clip_type="stable_diffusion",
            vae_name="vae.safetensors",
        ),
        source="local (test)",
        license="ver README (test)",
    )
    base.update(overrides)
    return ModelEntry(**base)


class RealRegistryTests(unittest.TestCase):
    def test_load_real_tiene_tres_modelos(self):
        registry = ModelRegistry.load(REGISTRY_PATH)

        self.assertEqual(len(registry), 3)
        self.assertEqual(
            [entry.id for entry in registry.models],
            [
                "anima-2.9b-preview",
                "anima-official-aesthetic-v11",
                "one-obsession-anima-v40",
            ],
        )

    def test_entrada_real_coincide_con_el_brief(self):
        registry = ModelRegistry.load(REGISTRY_PATH)
        entry = registry.get("anima-2.9b-preview")

        self.assertEqual(entry.family, "anima")
        self.assertEqual(entry.display_name, "Anima 2.9B preview v1")
        self.assertEqual(entry.source, "local (ComfyUI/models)")
        self.assertEqual(entry.license, "ver README del modelo en ComfyUI/models (no inventar)")
        self.assertEqual(entry.preprompt, "glossy")
        self.assertEqual(entry.defaults, GRAPH_DEFAULTS)
        self.assertEqual(
            entry.notes,
            "Modelo inicial; Anima [Official] y One obsession se añaden en M8-11 (descarga)",
        )

    def test_perfil_real_igual_al_grafo_certificado(self):
        registry = ModelRegistry.load(REGISTRY_PATH)

        self.assertEqual(registry.get("anima-2.9b-preview").profile, graph_profile())

    def test_by_family(self):
        registry = ModelRegistry.load(REGISTRY_PATH)

        self.assertEqual(len(registry.by_family("anima")), 3)
        self.assertEqual(registry.by_family("wan"), [])

    def test_to_dict_es_versionado(self):
        payload = ModelRegistry.load(REGISTRY_PATH).to_dict()

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["models"][0]["id"], "anima-2.9b-preview")
        expected = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        for item in expected["models"]:
            item["prompt_profile"] = "anima"
            item["subfamily"] = "sin_clasificar"
        self.assertEqual(expected, payload)


class AddTests(unittest.TestCase):
    def test_add_y_get(self):
        registry = ModelRegistry()
        entry = make_entry()

        self.assertEqual(registry.add(entry), entry)
        self.assertEqual(len(registry), 1)
        self.assertEqual(registry.get("modelo-test"), entry)

    def test_add_id_duplicado_lanza_engine_error(self):
        registry = ModelRegistry()
        registry.add(make_entry())

        with self.assertRaises(EngineError):
            registry.add(make_entry(display_name="Otro nombre"))

    def test_get_desconocido_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            ModelRegistry().get("no-existe")


class ValidationTests(unittest.TestCase):
    def test_id_fuera_de_slug(self):
        for bad_id in ("Mayusculas", "con espacio", "acentué", ""):
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(EngineError):
                    ModelRegistry().add(make_entry(bad_id))

    def test_campos_str_vacios(self):
        for field in ("family", "display_name", "source", "license"):
            with self.subTest(field=field):
                with self.assertRaises(EngineError):
                    ModelRegistry().add(make_entry(**{field: "   "}))

    def test_profile_con_campo_vacio(self):
        profile = ModelProfile("", "clip", "stable_diffusion", "vae")

        with self.assertRaises(EngineError):
            ModelRegistry().add(make_entry(profile=profile))

    def test_profile_invalido(self):
        with self.assertRaises(EngineError):
            ModelRegistry().add(make_entry(profile={"unet_name": "u"}))

    def test_defaults_no_dict(self):
        with self.assertRaises(EngineError):
            ModelRegistry().add(make_entry(defaults=["steps"]))


class RoundtripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_roundtrip_save_load(self):
        registry = ModelRegistry()
        registry.add(make_entry())
        registry.add(make_entry("otro-modelo", family="otra", defaults={"steps": 8}))
        path = self.tmp / "sub" / "models.json"

        registry.save(path)
        loaded = ModelRegistry.load(path)

        self.assertEqual(loaded.to_dict(), registry.to_dict())
        self.assertEqual(loaded.get("otro-modelo").defaults, {"steps": 8})

    def test_load_json_corrupto_lanza_engine_error(self):
        path = self.tmp / "corrupto.json"
        path.write_text("{no-json", encoding="utf-8")

        with self.assertRaises(EngineError):
            ModelRegistry.load(path)

    def test_load_lista_raiz_lanza_engine_error(self):
        path = self.tmp / "lista.json"
        path.write_text("[1, 2]", encoding="utf-8")

        with self.assertRaises(EngineError):
            ModelRegistry.load(path)

    def test_load_sin_models_lanza_engine_error(self):
        path = self.tmp / "sin_models.json"
        path.write_text(json.dumps({"version": 1}), encoding="utf-8")

        with self.assertRaises(EngineError):
            ModelRegistry.load(path)

    def test_load_version_no_soportada_lanza_engine_error(self):
        path = self.tmp / "v2.json"
        path.write_text(json.dumps({"version": 2, "models": []}), encoding="utf-8")

        with self.assertRaises(EngineError):
            ModelRegistry.load(path)

    def test_load_entrada_sin_campos_lanza_engine_error(self):
        path = self.tmp / "incompleta.json"
        path.write_text(
            json.dumps({"version": 1, "models": [{"id": "x"}]}), encoding="utf-8"
        )

        with self.assertRaises(EngineError):
            ModelRegistry.load(path)

    def test_from_dict_acepta_lo_que_produce_to_dict(self):
        registry = ModelRegistry()
        registry.add(make_entry())

        reloaded = ModelRegistry.from_dict(json.loads(json.dumps(registry.to_dict())))

        self.assertEqual(reloaded.to_dict(), registry.to_dict())
        expected = asdict(make_entry())
        if expected.get("owner_addon") is None:
            expected.pop("owner_addon", None)
        self.assertEqual(
            json.loads(json.dumps(reloaded.to_dict()["models"][0])),
            json.loads(json.dumps(expected)),
        )

    def test_dataclasses_frozen(self):
        entry = make_entry()

        with self.assertRaises(FrozenInstanceError):
            entry.id = "mutado"
        with self.assertRaises(FrozenInstanceError):
            entry.profile = replace(entry.profile, unet_name="otro.safetensors")


class PromptProfileInferenceTests(unittest.TestCase):
    def test_default_retrocompatible_para_modelo_desconocido(self):
        entry = make_entry(
            model_id="modelo-desconocido",
            family="sdxl",
            display_name="Modelo Desconocido",
        )
        self.assertEqual(entry.prompt_profile, "sdxl_tags")
        self.assertEqual(infer_prompt_profile("modelo-custom", family="sdxl"), "sdxl_tags")
        self.assertEqual(infer_prompt_profile(""), DEFAULT_PROMPT_PROFILE)

    def test_perfiles_4_modelos_conocidos(self):
        # 1. Anima -> anima
        anima_entry = make_entry(
            model_id="anima-2.9b-preview",
            family="anima",
            display_name="Anima 2.9B preview v1",
        )
        self.assertEqual(anima_entry.prompt_profile, "anima")
        self.assertEqual(infer_prompt_profile("anima-model", family="anima"), "anima")

        # 2. Animagine -> animagine
        animagine_entry = make_entry(
            model_id="animagine-xl-4-opt",
            family="sdxl",
            display_name="Animagine XL 4.0 Opt",
        )
        self.assertEqual(animagine_entry.prompt_profile, "animagine")
        self.assertEqual(infer_prompt_profile("animagine-xl-4-opt"), "animagine")

        # 3. RealVisXL -> sdxl_natural
        realvis_entry = make_entry(
            model_id="realvisxl-v50",
            family="sdxl",
            display_name="RealVisXL V5.0 (Baked VAE)",
        )
        self.assertEqual(realvis_entry.prompt_profile, "sdxl_natural")
        self.assertEqual(infer_prompt_profile("realvisxl-v50"), "sdxl_natural")

        # 4. Juggernaut -> sdxl_natural
        juggernaut_entry = make_entry(
            model_id="juggernaut-xl-ragnarok",
            family="sdxl",
            display_name="Juggernaut XL Ragnarok",
        )
        self.assertEqual(juggernaut_entry.prompt_profile, "sdxl_natural")
        self.assertEqual(infer_prompt_profile("juggernaut-xl-ragnarok"), "sdxl_natural")

    def test_from_dict_sin_prompt_profile_infiere_retrocompatible(self):
        raw = {
            "id": "juggernaut-xl-ragnarok",
            "family": "sdxl",
            "display_name": "Juggernaut XL Ragnarok",
            "profile": {
                "unet_name": "juggernautXL_ragnarok.safetensors",
                "clip_name": "__checkpoint__",
                "clip_type": "checkpoint",
                "vae_name": "__checkpoint__",
            },
            "source": "https://civitai.com",
            "license": "OpenRAIL",
        }
        reg = ModelRegistry.from_dict({"version": 1, "models": [raw]})
        self.assertEqual(reg.get("juggernaut-xl-ragnarok").prompt_profile, "sdxl_natural")

    def test_prompt_profile_explicito_se_respeta(self):
        raw = {
            "id": "juggernaut-xl-ragnarok",
            "family": "sdxl",
            "display_name": "Juggernaut XL Ragnarok",
            "profile": {
                "unet_name": "juggernautXL_ragnarok.safetensors",
                "clip_name": "__checkpoint__",
                "clip_type": "checkpoint",
                "vae_name": "__checkpoint__",
            },
            "source": "https://civitai.com",
            "license": "OpenRAIL",
            "prompt_profile": "sdxl_tags",
        }
        reg = ModelRegistry.from_dict({"version": 1, "models": [raw]})
        self.assertEqual(reg.get("juggernaut-xl-ragnarok").prompt_profile, "sdxl_tags")

    def test_recommended_v1_perfiles(self):
        rec_path = ROOT / "registry" / "recommended-v1.json"
        data = json.loads(rec_path.read_text(encoding="utf-8"))
        profiles = {m["id"]: m.get("prompt_profile") for m in data["models"]}
        self.assertEqual(profiles.get("animagine-xl-4-opt"), "animagine")
        self.assertEqual(profiles.get("realvisxl-v50"), "sdxl_natural")
        self.assertEqual(profiles.get("juggernaut-xl-ragnarok"), "sdxl_natural")


class SubfamilyInferenceTests(unittest.TestCase):
    def test_infer_illustrious(self):
        self.assertEqual(
            infer_subfamily({"modelspec.architecture": "illustrious"}),
            "illustrious",
        )
        self.assertEqual(
            infer_subfamily({"ss_base_model_version": "illustrious-xl-v1.0"}),
            "illustrious",
        )
        self.assertEqual(
            infer_subfamily(
                {
                    "modelspec.architecture": "sdxl/illustrious",
                    "ss_base_model_version": "sdxl_v1-0",
                }
            ),
            "illustrious",
        )
        self.assertEqual(infer_subfamily(modelspec_architecture="illustrious-xl"), "illustrious")

    def test_infer_pony(self):
        self.assertEqual(
            infer_subfamily({"modelspec.architecture": "pony"}),
            "pony",
        )
        self.assertEqual(
            infer_subfamily({"ss_base_model_version": "pony_v6"}),
            "pony",
        )
        self.assertEqual(
            infer_subfamily(
                {
                    "modelspec.architecture": "sdxl/pony",
                    "ss_base_model_version": "sdxl_v1-0",
                }
            ),
            "pony",
        )
        self.assertEqual(infer_subfamily(modelspec_architecture="pony"), "pony")

    def test_infer_sdxl_generico(self):
        self.assertEqual(
            infer_subfamily(
                {
                    "ss_base_model_version": "sdxl_v1-0",
                    "modelspec.architecture": "sdxl",
                }
            ),
            "sdxl_base",
        )
        self.assertEqual(
            infer_subfamily({"ss_base_model_version": "sdxl_base"}),
            "sdxl_base",
        )
        self.assertEqual(
            infer_subfamily({"ss_base_model_version": "sdxl_v1-0"}),
            "sdxl_base",
        )
        self.assertEqual(infer_subfamily(modelspec_architecture="stable-diffusion-xl"), "sdxl_base")

    def test_infer_sin_clasificar(self):
        self.assertEqual(infer_subfamily({}), "sin_clasificar")
        self.assertEqual(infer_subfamily(None), "sin_clasificar")
        self.assertEqual(infer_subfamily({"ss_base_model_version": "v1-5"}), "sin_clasificar")
        self.assertEqual(infer_subfamily({"modelspec.architecture": "desconocida"}), "sin_clasificar")

    def test_infer_otras_familias(self):
        self.assertEqual(infer_subfamily({"modelspec.architecture": "noobai"}), "noobai")
        self.assertEqual(infer_subfamily({"modelspec.architecture": "anima"}), "anima")
        self.assertEqual(infer_subfamily({"modelspec.architecture": "wan2.1"}), "wan")
        self.assertEqual(infer_subfamily({"modelspec.architecture": "minimax_h3"}), "h3")


class SubfamilySerializationAndEditTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_serializacion_subfamily(self):
        registry = ModelRegistry()
        entry = make_entry("modelo-pony", subfamily="pony")
        registry.add(entry)
        path = self.tmp / "pony_models.json"
        registry.save(path)

        loaded = ModelRegistry.load(path)
        self.assertEqual(loaded.get("modelo-pony").subfamily, "pony")
        self.assertEqual(loaded.to_dict()["models"][0]["subfamily"], "pony")

    def test_retrocompatibilidad_sin_subfamily(self):
        raw = {
            "version": 1,
            "models": [
                {
                    "id": "modelo-antiguo",
                    "family": "sdxl",
                    "display_name": "Modelo Antiguo",
                    "profile": {
                        "unet_name": "old.safetensors",
                        "clip_name": "__checkpoint__",
                        "clip_type": "checkpoint",
                        "vae_name": "__checkpoint__",
                    },
                    "source": "antiguo",
                    "license": "MIT",
                }
            ],
        }
        registry = ModelRegistry.from_dict(raw)
        entry = registry.get("modelo-antiguo")
        self.assertEqual(entry.subfamily, "sin_clasificar")

    def test_edicion_subfamily_manual_y_persistencia(self):
        registry = ModelRegistry()
        registry.add(make_entry("modelo-edit", subfamily="sin_clasificar"))
        # Edicion via update
        updated = registry.update("modelo-edit", subfamily="illustrious")
        self.assertEqual(updated.subfamily, "illustrious")
        self.assertEqual(registry.get("modelo-edit").subfamily, "illustrious")

        path = self.tmp / "edited_models.json"
        registry.save(path)
        loaded = ModelRegistry.load(path)
        self.assertEqual(loaded.get("modelo-edit").subfamily, "illustrious")

    def test_subfamily_invalida_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            make_entry("modelo-bad", subfamily="no_existe")

        with self.assertRaises(EngineError):
            ModelRegistry.from_dict(
                {
                    "version": 1,
                    "models": [
                        {
                            "id": "modelo-bad",
                            "family": "sdxl",
                            "display_name": "Bad",
                            "profile": {
                                "unet_name": "u.safetensors",
                                "clip_name": "c.safetensors",
                                "clip_type": "checkpoint",
                                "vae_name": "v.safetensors",
                            },
                            "source": "src",
                            "license": "lic",
                            "subfamily": "subfamilia_inventada",
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
