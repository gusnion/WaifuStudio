"""Tests CPU de grafos y runner de video (F4/M9-F1). Sin red, GPU ni engine real."""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.config import EngineConfig
from app.engine import ComfyEngine, EngineError, load_graph
from app.h3_presets import h3_frames_for_seconds, h3_template_path, resolve_h3_profile
from app.motion import MOTION_NEGATIVE
from app.store import Store
from app.video import (
    H3_SAGE_MODE,
    H3_SAGE_NODE_CLASS,
    H3_TEMPLATE_PATH,
    WAN_DEFAULT_SAMPLER,
    WAN_DEFAULT_SCHEDULER,
    WAN_DEFAULT_SHIFT,
    WAN_DEFAULT_STEPS,
    WAN_FLF_TEMPLATE_PATH,
    WAN_TEMPLATE_PATH,
    build_video_graph,
    frames_for_seconds,
    prepare_h3_graph,
    prepare_wan_flf_graph,
    prepare_wan_graph,
    resolve_wan_profile,
    run_video_generation,
    vram_hint,
)

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"waifu-fake-mp4"

H3_LORA_4STEP = "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"
H3_LORA_8STEP = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"

_OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    negative TEXT DEFAULT '',
    params TEXT DEFAULT '{}',
    status TEXT NOT NULL,
    outputs TEXT DEFAULT '[]',
    error TEXT
)
"""


class PrepareWanTests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph(WAN_TEMPLATE_PATH)
        self.snapshot = copy.deepcopy(self.graph)

    def test_plantilla_certificada(self):
        self.assertEqual(len(self.graph), 15)
        self.assertEqual(self.graph["5"]["inputs"]["text"], "1girl, walking, cinematic motion")
        self.assertEqual(self.graph["6"]["inputs"]["text"], MOTION_NEGATIVE)
        self.assertEqual(self.graph["7"]["inputs"]["image"], "ref.png")
        self.assertEqual(self.graph["9"]["class_type"], "WanImageToVideo")
        self.assertEqual(self.graph["9"]["inputs"]["width"], 432)
        self.assertEqual(self.graph["9"]["inputs"]["height"], 768)
        self.assertEqual(self.graph["9"]["inputs"]["length"], 81)
        self.assertEqual(self.graph["15"]["inputs"]["fps"], 16.0)
        self.assertEqual(self.graph["16"]["inputs"]["filename_prefix"], "waifu/video")
        self.assertEqual(self.graph["12"]["inputs"]["noise_seed"], 42)

    def test_parcheo_exacto(self):
        patched = prepare_wan_graph(
            self.graph,
            image_name="frame-0001.png",
            motion_positive="She walks slowly toward the camera.",
            motion_negative="no motion",
            width=432,
            height=768,
            seed=7,
        )
        self.assertEqual(
            patched["5"]["inputs"]["text"], "She walks slowly toward the camera."
        )
        self.assertEqual(patched["6"]["inputs"]["text"], "no motion")
        self.assertEqual(patched["7"]["inputs"]["image"], "frame-0001.png")
        self.assertEqual(patched["9"]["inputs"]["width"], 432)
        self.assertEqual(patched["9"]["inputs"]["height"], 768)
        self.assertEqual(patched["12"]["inputs"]["noise_seed"], 7)
        self.assertEqual(patched["13"]["inputs"]["noise_seed"], 7)

    def test_tamano_horizontal(self):
        patched = prepare_wan_graph(
            self.graph,
            image_name="frame.png",
            motion_positive="She walks.",
            motion_negative="no motion",
            width=768,
            height=432,
            seed=1,
        )
        self.assertEqual(patched["9"]["inputs"]["width"], 768)
        self.assertEqual(patched["9"]["inputs"]["height"], 432)

    def test_no_muta_el_original(self):
        prepare_wan_graph(
            self.graph,
            image_name="otro.png",
            motion_positive="She runs.",
            motion_negative="blur",
            seed=99,
        )
        self.assertEqual(self.graph, self.snapshot)

    def test_nodo_ausente_lanza_engine_error(self):
        for node_id in ("5", "6", "7", "9"):
            with self.subTest(node_id=node_id):
                broken = copy.deepcopy(self.graph)
                del broken[node_id]
                with self.assertRaises(EngineError):
                    prepare_wan_graph(
                        broken, image_name="f.png", motion_positive="m", motion_negative="n", seed=1
                    )

    def test_clase_incorrecta_lanza_engine_error(self):
        broken = copy.deepcopy(self.graph)
        broken["7"]["class_type"] = "CLIPTextEncode"
        with self.assertRaises(EngineError):
            prepare_wan_graph(
                broken, image_name="f.png", motion_positive="m", motion_negative="n", seed=1
            )

    def test_campo_ausente_lanza_engine_error(self):
        for node_id, field in (("5", "text"), ("7", "image"), ("9", "width")):
            with self.subTest(node_id=node_id, field=field):
                broken = copy.deepcopy(self.graph)
                del broken[node_id]["inputs"][field]
                with self.assertRaises(EngineError):
                    prepare_wan_graph(
                        broken, image_name="f.png", motion_positive="m", motion_negative="n", seed=1
                    )

    def test_sin_samplers_lanza_engine_error(self):
        broken = copy.deepcopy(self.graph)
        del broken["12"]
        del broken["13"]
        with self.assertRaises(EngineError):
            prepare_wan_graph(
                broken, image_name="f.png", motion_positive="m", motion_negative="n", seed=1
            )

    def test_entradas_invalidas_lanzan_engine_error(self):
        cases = (
            {"image_name": "  "},
            {"motion_positive": ""},
            {"motion_negative": None},
            {"width": 431},
            {"height": "alto"},
            {"seed": "abc"},
        )
        base = {
            "image_name": "f.png",
            "motion_positive": "m",
            "motion_negative": "n",
            "width": 432,
            "height": 768,
            "seed": 1,
        }
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    prepare_wan_graph(self.graph, **(base | override))


class PrepareWanFlfTests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph(WAN_FLF_TEMPLATE_PATH)
        self.snapshot = copy.deepcopy(self.graph)

    def test_plantilla_certificada(self):
        self.assertEqual(len(self.graph), 16)
        self.assertEqual(
            self.graph["5"]["inputs"]["text"], "1girl, walking, cinematic motion"
        )
        self.assertEqual(self.graph["6"]["inputs"]["text"], MOTION_NEGATIVE)
        self.assertEqual(self.graph["7"]["inputs"]["image"], "ref_first.png")
        self.assertEqual(self.graph["8"]["inputs"]["image"], "ref_last.png")
        self.assertEqual(self.graph["9"]["class_type"], "WanFirstLastFrameToVideo")
        self.assertEqual(self.graph["9"]["inputs"]["start_image"], ["7", 0])
        self.assertEqual(self.graph["9"]["inputs"]["end_image"], ["8", 0])
        self.assertEqual(self.graph["9"]["inputs"]["width"], 432)
        self.assertEqual(self.graph["9"]["inputs"]["height"], 768)
        self.assertEqual(self.graph["9"]["inputs"]["length"], 81)
        self.assertEqual(self.graph["15"]["inputs"]["fps"], 16.0)
        self.assertEqual(self.graph["16"]["inputs"]["filename_prefix"], "waifu/video_flf")
        self.assertEqual(self.graph["12"]["inputs"]["noise_seed"], 42)

    def test_parcheo_exacto(self):
        patched = prepare_wan_flf_graph(
            self.graph,
            first_image_name="first-0001.png",
            last_image_name="last-0001.png",
            motion_positive="She walks slowly toward the camera.",
            motion_negative="no motion",
            width=432,
            height=768,
            seed=7,
        )
        self.assertEqual(
            patched["5"]["inputs"]["text"], "She walks slowly toward the camera."
        )
        self.assertEqual(patched["6"]["inputs"]["text"], "no motion")
        self.assertEqual(patched["7"]["inputs"]["image"], "first-0001.png")
        self.assertEqual(patched["8"]["inputs"]["image"], "last-0001.png")
        self.assertEqual(patched["9"]["inputs"]["width"], 432)
        self.assertEqual(patched["9"]["inputs"]["height"], 768)
        self.assertEqual(patched["9"]["inputs"]["length"], 81)
        self.assertEqual(patched["12"]["inputs"]["noise_seed"], 7)
        self.assertEqual(patched["13"]["inputs"]["noise_seed"], 7)

    def test_frames_patch_4n1(self):
        patched = prepare_wan_flf_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            motion_positive="m",
            motion_negative="n",
            seed=1,
            frames=129,
        )
        self.assertEqual(patched["9"]["inputs"]["length"], 129)
        for bad in (128, 4, 0, True, "81"):
            with self.subTest(frames=bad):
                with self.assertRaises(EngineError):
                    prepare_wan_flf_graph(
                        self.graph,
                        first_image_name="a.png",
                        last_image_name="b.png",
                        motion_positive="m",
                        motion_negative="n",
                        seed=1,
                        frames=bad,
                    )

    def test_localiza_loadimage_por_orden(self):
        reordered = {
            key: self.graph[key]
            for key in ("8", "7", *(key for key in self.graph if key not in ("7", "8")))
        }
        patched = prepare_wan_flf_graph(
            reordered,
            first_image_name="A.png",
            last_image_name="B.png",
            motion_positive="m",
            motion_negative="n",
            seed=1,
        )
        self.assertEqual(patched["8"]["inputs"]["image"], "A.png")
        self.assertEqual(patched["7"]["inputs"]["image"], "B.png")

    def test_no_muta_el_original(self):
        prepare_wan_flf_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            motion_positive="m",
            motion_negative="n",
            seed=9,
            frames=129,
        )
        self.assertEqual(self.graph, self.snapshot)

    def test_nodos_ausentes_o_menos_de_dos_loadimage(self):
        for node_id in ("5", "6", "9"):
            with self.subTest(node_id=node_id):
                broken = copy.deepcopy(self.graph)
                del broken[node_id]
                with self.assertRaises(EngineError):
                    prepare_wan_flf_graph(
                        broken,
                        first_image_name="a.png",
                        last_image_name="b.png",
                        motion_positive="m",
                        motion_negative="n",
                        seed=1,
                    )
        broken = copy.deepcopy(self.graph)
        del broken["8"]
        with self.assertRaises(EngineError):
            prepare_wan_flf_graph(
                broken,
                first_image_name="a.png",
                last_image_name="b.png",
                motion_positive="m",
                motion_negative="n",
                seed=1,
            )

    def test_clase_incorrecta_o_campo_ausente(self):
        broken = copy.deepcopy(self.graph)
        broken["9"]["class_type"] = "WanImageToVideo"
        with self.assertRaises(EngineError):
            prepare_wan_flf_graph(
                broken,
                first_image_name="a.png",
                last_image_name="b.png",
                motion_positive="m",
                motion_negative="n",
                seed=1,
            )
        for node_id, field in (("5", "text"), ("7", "image"), ("9", "width"), ("9", "length")):
            with self.subTest(node_id=node_id, field=field):
                broken = copy.deepcopy(self.graph)
                del broken[node_id]["inputs"][field]
                with self.assertRaises(EngineError):
                    prepare_wan_flf_graph(
                        broken,
                        first_image_name="a.png",
                        last_image_name="b.png",
                        motion_positive="m",
                        motion_negative="n",
                        seed=1,
                        frames=129 if field == "length" else None,
                    )

    def test_sin_samplers_lanza_engine_error(self):
        broken = copy.deepcopy(self.graph)
        del broken["12"]
        del broken["13"]
        with self.assertRaises(EngineError):
            prepare_wan_flf_graph(
                broken,
                first_image_name="a.png",
                last_image_name="b.png",
                motion_positive="m",
                motion_negative="n",
                seed=1,
            )

    def test_entradas_invalidas_lanzan_engine_error(self):
        cases = (
            {"first_image_name": "  "},
            {"last_image_name": None},
            {"motion_positive": ""},
            {"motion_negative": None},
            {"width": 431},
            {"height": "alto"},
            {"seed": "abc"},
        )
        base = {
            "first_image_name": "a.png",
            "last_image_name": "b.png",
            "motion_positive": "m",
            "motion_negative": "n",
            "width": 432,
            "height": 768,
            "seed": 1,
        }
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    prepare_wan_flf_graph(self.graph, **(base | override))


class WanOverrideTests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph(WAN_TEMPLATE_PATH)

    def prepare(self, **overrides) -> dict:
        base = {
            "image_name": "f.png",
            "motion_positive": "m",
            "motion_negative": "n",
            "seed": 3,
        }
        return prepare_wan_graph(self.graph, **(base | overrides))

    def test_sampler_y_scheduler_en_ambos_samplers(self):
        patched = self.prepare(sampler_name="er_sde", scheduler="karras")
        for node_id in ("12", "13"):
            with self.subTest(node_id=node_id):
                self.assertEqual(patched[node_id]["inputs"]["sampler_name"], "er_sde")
                self.assertEqual(patched[node_id]["inputs"]["scheduler"], "karras")

    def test_steps_30_reparte_15_15(self):
        patched = self.prepare(steps=30)
        for node_id in ("12", "13"):
            self.assertEqual(patched[node_id]["inputs"]["steps"], 30)
        self.assertEqual(patched["12"]["inputs"]["start_at_step"], 0)
        self.assertEqual(patched["12"]["inputs"]["end_at_step"], 15)
        self.assertEqual(patched["13"]["inputs"]["start_at_step"], 15)
        self.assertEqual(patched["13"]["inputs"]["end_at_step"], 10000)
        self.assertEqual(patched["12"]["inputs"]["add_noise"], "enable")
        self.assertEqual(patched["13"]["inputs"]["add_noise"], "disable")

    def test_steps_20_reproduce_lo_certificado(self):
        patched = self.prepare(
            sampler_name="euler", scheduler="simple", steps=20, shift=8.0
        )
        self.assertEqual(patched, self.prepare())

    def test_shift_en_ambos_model_sampling(self):
        patched = self.prepare(shift=5.0)
        self.assertEqual(patched["10"]["inputs"]["shift"], 5.0)
        self.assertEqual(patched["11"]["inputs"]["shift"], 5.0)

    def test_no_muta_el_original_con_overrides(self):
        snapshot = copy.deepcopy(self.graph)
        self.prepare(sampler_name="er_sde", scheduler="karras", steps=30, shift=5.0)
        self.assertEqual(self.graph, snapshot)

    def test_steps_invalidos(self):
        for value in (True, 0, 201, 20.5, "20", float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    self.prepare(steps=value)

    def test_shift_invalidos(self):
        for value in (True, 0, -1, "8", float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    self.prepare(shift=value)

    def test_sampler_y_scheduler_invalidos(self):
        with self.assertRaises(EngineError):
            self.prepare(sampler_name="nope")
        with self.assertRaises(EngineError):
            self.prepare(scheduler="nope")

    def test_nodo_ausente_lanza_engine_error(self):
        broken = copy.deepcopy(self.graph)
        del broken["12"]
        with self.assertRaises(EngineError):
            prepare_wan_graph(
                broken, image_name="f.png", motion_positive="m", motion_negative="n",
                seed=1, steps=30,
            )
        broken = copy.deepcopy(self.graph)
        del broken["10"]
        del broken["11"]
        with self.assertRaises(EngineError):
            prepare_wan_graph(
                broken, image_name="f.png", motion_positive="m", motion_negative="n",
                seed=1, shift=5.0,
            )


class WanFlfOverrideTests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph(WAN_FLF_TEMPLATE_PATH)

    def prepare(self, **overrides) -> dict:
        base = {
            "first_image_name": "a.png",
            "last_image_name": "b.png",
            "motion_positive": "m",
            "motion_negative": "n",
            "seed": 3,
        }
        return prepare_wan_flf_graph(self.graph, **(base | overrides))

    def test_overrides_en_samplers_y_shift(self):
        patched = self.prepare(sampler_name="er_sde", scheduler="simple", steps=30, shift=5.0)
        for node_id in ("12", "13"):
            with self.subTest(node_id=node_id):
                self.assertEqual(patched[node_id]["inputs"]["sampler_name"], "er_sde")
                self.assertEqual(patched[node_id]["inputs"]["steps"], 30)
        self.assertEqual(patched["12"]["inputs"]["end_at_step"], 15)
        self.assertEqual(patched["13"]["inputs"]["start_at_step"], 15)
        self.assertEqual(patched["10"]["inputs"]["shift"], 5.0)
        self.assertEqual(patched["11"]["inputs"]["shift"], 5.0)

    def test_steps_20_reproduce_lo_certificado(self):
        patched = self.prepare(steps=20)
        self.assertEqual(patched, self.prepare())

    def test_invalidos(self):
        for override in (
            {"sampler_name": "nope"},
            {"scheduler": "nope"},
            {"steps": True},
            {"steps": 0},
            {"steps": 201},
            {"shift": 0},
            {"shift": "8"},
        ):
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    self.prepare(**override)


class ResolveWanProfileTests(unittest.TestCase):
    def test_sin_preset_es_el_perfil_certificado(self):
        for preset in (None, "", "manual", " manual "):
            with self.subTest(preset=preset):
                profile = resolve_wan_profile(preset=preset, aspect="horizontal")
                self.assertEqual(
                    profile,
                    {
                        "preset": "manual",
                        "sampler_name": WAN_DEFAULT_SAMPLER,
                        "scheduler": WAN_DEFAULT_SCHEDULER,
                        "steps": WAN_DEFAULT_STEPS,
                        "shift": WAN_DEFAULT_SHIFT,
                        "width": 768,
                        "height": 432,
                    },
                )

    def test_preset_rapido_es_el_certificado(self):
        profile = resolve_wan_profile(preset="rapido", aspect="vertical")
        self.assertEqual(profile["width"], 432)
        self.assertEqual(profile["height"], 768)
        self.assertEqual(profile["sampler_name"], "euler")
        self.assertEqual(profile["scheduler"], "simple")
        self.assertEqual(profile["steps"], 20)
        self.assertEqual(profile["shift"], 8.0)
        self.assertEqual(profile["preset"], "rapido")

    def test_preset_calidad_y_horizontal(self):
        profile = resolve_wan_profile(preset="calidad", aspect="vertical")
        self.assertEqual((profile["width"], profile["height"]), (512, 896))
        self.assertEqual(profile["sampler_name"], "er_sde")
        self.assertEqual(profile["steps"], 30)
        self.assertEqual(profile["shift"], 5.0)
        horizontal = resolve_wan_profile(preset="calidad", aspect="horizontal")
        self.assertEqual((horizontal["width"], horizontal["height"]), (896, 512))

    def test_overrides_ganan_al_preset(self):
        profile = resolve_wan_profile(
            preset="calidad",
            aspect="vertical",
            sampler_name="euler",
            scheduler="karras",
            steps=20,
            shift=8.0,
        )
        self.assertEqual(profile["preset"], "calidad")
        self.assertEqual(profile["sampler_name"], "euler")
        self.assertEqual(profile["scheduler"], "karras")
        self.assertEqual(profile["steps"], 20)
        self.assertEqual(profile["shift"], 8.0)
        self.assertEqual((profile["width"], profile["height"]), (512, 896))

    def test_preset_desconocido_o_aspect_invalido(self):
        with self.assertRaises(EngineError):
            resolve_wan_profile(preset="nope")
        with self.assertRaises(EngineError):
            resolve_wan_profile(aspect="cuadrado")

    def test_overrides_invalidos(self):
        for override in (
            {"sampler_name": "nope"},
            {"scheduler": "nope"},
            {"steps": 0},
            {"steps": True},
            {"shift": 0},
            {"shift": True},
        ):
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    resolve_wan_profile(**override)


class BuildVideoGraphWanProfileTests(unittest.TestCase):
    def job(self, **overrides) -> dict:
        base = {
            "engine": "wan",
            "template": str(WAN_TEMPLATE_PATH),
            "image_name": "f.png",
            "motion_positive": "m",
            "motion_negative": "n",
            "seed": 3,
        }
        return base | overrides

    def test_sin_overrides_identico_al_actual(self):
        expected = prepare_wan_graph(
            load_graph(WAN_TEMPLATE_PATH),
            image_name="f.png",
            motion_positive="m",
            motion_negative="n",
            seed=3,
        )
        self.assertEqual(build_video_graph(self.job()), expected)

    def test_preset_calidad_cambia_tamano_y_perfil(self):
        graph = build_video_graph(self.job(preset="calidad"))
        self.assertEqual(graph["9"]["inputs"]["width"], 512)
        self.assertEqual(graph["9"]["inputs"]["height"], 896)
        for node_id in ("12", "13"):
            self.assertEqual(graph[node_id]["inputs"]["sampler_name"], "er_sde")
            self.assertEqual(graph[node_id]["inputs"]["steps"], 30)
        self.assertEqual(graph["10"]["inputs"]["shift"], 5.0)
        self.assertEqual(graph["11"]["inputs"]["shift"], 5.0)

    def test_preset_calidad_horizontal(self):
        graph = build_video_graph(self.job(preset="calidad", aspect="horizontal"))
        self.assertEqual(graph["9"]["inputs"]["width"], 896)
        self.assertEqual(graph["9"]["inputs"]["height"], 512)

    def test_overrides_ganan_sobre_preset(self):
        graph = build_video_graph(self.job(preset="calidad", steps=20, shift=8.0))
        self.assertEqual(graph["12"]["inputs"]["steps"], 20)
        self.assertEqual(graph["12"]["inputs"]["end_at_step"], 10)
        self.assertEqual(graph["13"]["inputs"]["start_at_step"], 10)
        self.assertEqual(graph["10"]["inputs"]["shift"], 8.0)
        self.assertEqual(graph["12"]["inputs"]["sampler_name"], "er_sde")
        self.assertEqual(graph["9"]["inputs"]["width"], 512)

    def test_preset_desconocido_o_manual(self):
        with self.assertRaises(EngineError):
            build_video_graph(self.job(preset="nope"))
        manual = build_video_graph(self.job(preset="manual"))
        self.assertEqual(manual["9"]["inputs"]["width"], 432)
        self.assertEqual(manual["10"]["inputs"]["shift"], 8.0)

    def test_flf_con_preset(self):
        graph = build_video_graph(
            self.job(
                template=str(WAN_FLF_TEMPLATE_PATH),
                last_image_name="b.png",
                preset="calidad",
            )
        )
        self.assertEqual(graph["9"]["inputs"]["width"], 512)
        self.assertEqual(graph["9"]["inputs"]["height"], 896)
        self.assertEqual(graph["13"]["inputs"]["start_at_step"], 15)

    def test_h3_ignora_preset(self):
        graph = build_video_graph(
            {
                "engine": "h3",
                "template": str(H3_TEMPLATE_PATH),
                "image_name": "a.png",
                "last_image_name": "b.png",
                "prompt": "p",
                "seed": 3,
                "preset": "calidad",
            }
        )
        self.assertEqual(graph["131"]["inputs"]["width"], 576)
        self.assertEqual(graph["131"]["inputs"]["length"], 192)


class FramesForSecondsTests(unittest.TestCase):
    def test_tabla_certificada(self):
        for seconds, frames in ((1, 17), (5, 81), (8, 129), (15, 241)):
            with self.subTest(seconds=seconds):
                self.assertEqual(frames_for_seconds(seconds), frames)

    def test_siempre_4n1(self):
        for seconds in range(1, 16):
            with self.subTest(seconds=seconds):
                self.assertEqual(frames_for_seconds(seconds) % 4, 1)

    def test_fps_distinto_y_fracciones(self):
        self.assertEqual(frames_for_seconds(1, fps=8), 9)
        self.assertEqual(frames_for_seconds(1, fps=24), 25)
        self.assertEqual(frames_for_seconds(1.5), 25)

    def test_fuera_de_rango_o_invalidos(self):
        for value in (0, 0.5, 15.1, 16, 20, -1, "abc", None, True):
            with self.subTest(seconds=value):
                with self.assertRaises(EngineError):
                    frames_for_seconds(value)
        for value in (0, -16, "16", None, True):
            with self.subTest(fps=value):
                with self.assertRaises(EngineError):
                    frames_for_seconds(5, fps=value)


class VramHintTests(unittest.TestCase):
    def test_tramos(self):
        self.assertIn("cabe en 12 GB (perfil certificado)", vram_hint(81, 432, 768))
        self.assertIn("cabe en 12 GB (perfil certificado)", vram_hint(17, 432, 768))
        self.assertIn("ajustado, más lento", vram_hint(82, 432, 768))
        self.assertIn("ajustado, más lento", vram_hint(121, 432, 768))
        self.assertIn(
            "riesgo de OOM en 12 GB; no certificado", vram_hint(122, 432, 768)
        )
        self.assertIn(
            "riesgo de OOM en 12 GB; no certificado", vram_hint(241, 432, 768)
        )

    def test_incluye_frames_y_tamano(self):
        self.assertIn("81 frames a 432x768", vram_hint(81, 432, 768))

    def test_invalidos(self):
        for args in (
            (0, 432, 768),
            ("81", 432, 768),
            (True, 432, 768),
            (81, 0, 768),
            (81, 432, "alto"),
        ):
            with self.subTest(args=args):
                with self.assertRaises(EngineError):
                    vram_hint(*args)


class PrepareH3Tests(unittest.TestCase):
    def setUp(self):
        self.graph = load_graph(H3_TEMPLATE_PATH)
        self.snapshot = copy.deepcopy(self.graph)

    def test_plantilla_certificada(self):
        self.assertEqual(len(self.graph), 17)
        self.assertEqual(self.graph["140"]["inputs"]["image"], "frames/FIRST_FRAME.png")
        self.assertEqual(self.graph["141"]["inputs"]["image"], "frames/LAST_FRAME.png")
        self.assertEqual(self.graph["131"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(self.graph["131"]["inputs"]["width"], 576)
        self.assertEqual(self.graph["131"]["inputs"]["height"], 1024)
        self.assertEqual(self.graph["131"]["inputs"]["length"], 192)
        self.assertEqual(self.graph["129"]["inputs"]["noise_seed"], 57003060)
        self.assertEqual(self.graph["92"]["inputs"]["filename_prefix"], "video/H3_FL2VA_VERTICAL")

    def test_parcheo_exacto(self):
        patched = prepare_h3_graph(
            self.graph,
            first_image_name="first.png",
            last_image_name="last.png",
            prompt="integrated_multimodal_description: test",
            seed=9,
        )
        self.assertEqual(patched["140"]["inputs"]["image"], "first.png")
        self.assertEqual(patched["141"]["inputs"]["image"], "last.png")
        self.assertEqual(
            patched["131"]["inputs"]["prompt"], "integrated_multimodal_description: test"
        )
        self.assertEqual(patched["129"]["inputs"]["noise_seed"], 9)

    def test_variante_default_turbo4(self):
        patched = prepare_h3_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            prompt="p",
            seed=1,
        )
        self.assertEqual(patched["134"]["inputs"]["lora_name"], H3_LORA_4STEP)
        self.assertEqual(patched["124"]["inputs"]["steps"], 4)
        self.assertNotIn(
            H3_SAGE_NODE_CLASS,
            [node.get("class_type") for node in patched.values()],
        )

    def test_variante_turbo8_parchea_lora_y_pasos(self):
        patched = prepare_h3_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            prompt="p",
            seed=1,
            variant="turbo8",
        )
        self.assertEqual(patched["134"]["inputs"]["lora_name"], H3_LORA_8STEP)
        self.assertEqual(patched["124"]["inputs"]["steps"], 8)
        self.assertEqual(patched["134"]["inputs"]["model"], ["127", 0])

    def test_variante_invalida(self):
        for value in ("nope", "TURBO8", 5, True, ["turbo8"]):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    prepare_h3_graph(
                        self.graph,
                        first_image_name="a.png",
                        last_image_name="b.png",
                        prompt="p",
                        seed=1,
                        variant=value,
                    )

    def test_sage_inserta_patch_entre_lora_y_consumidores(self):
        patched = prepare_h3_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            prompt="p",
            seed=1,
            sage=True,
        )
        sage_nodes = [
            (node_id, node)
            for node_id, node in patched.items()
            if node.get("class_type") == H3_SAGE_NODE_CLASS
        ]
        self.assertEqual(len(sage_nodes), 1)
        sage_id, sage = sage_nodes[0]
        self.assertEqual(
            sage["inputs"], {"model": ["134", 0], "sage_attention": H3_SAGE_MODE}
        )
        self.assertEqual(patched["134"]["inputs"]["model"], ["127", 0])
        for consumer in ("126", "124"):
            with self.subTest(consumer=consumer):
                self.assertEqual(patched[consumer]["inputs"]["model"], [sage_id, 0])

    def test_sage_con_variante_turbo8(self):
        patched = prepare_h3_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            prompt="p",
            seed=1,
            variant="turbo8",
            sage=True,
        )
        self.assertEqual(patched["134"]["inputs"]["lora_name"], H3_LORA_8STEP)
        self.assertEqual(patched["124"]["inputs"]["steps"], 8)
        sage = next(
            node
            for node in patched.values()
            if node.get("class_type") == H3_SAGE_NODE_CLASS
        )
        self.assertEqual(sage["inputs"]["model"], ["134", 0])

    def test_sage_sin_consumidores_del_lora(self):
        broken = copy.deepcopy(self.graph)
        broken["124"]["inputs"]["model"] = ["127", 0]
        broken["126"]["inputs"]["model"] = ["127", 0]
        prepare_h3_graph(
            broken,
            first_image_name="a.png",
            last_image_name="b.png",
            prompt="p",
            seed=1,
            sage=False,
        )
        with self.assertRaises(EngineError):
            prepare_h3_graph(
                broken,
                first_image_name="a.png",
                last_image_name="b.png",
                prompt="p",
                seed=1,
                sage=True,
            )

    def test_sage_invalido(self):
        for value in (1, "si", None):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    prepare_h3_graph(
                        self.graph,
                        first_image_name="a.png",
                        last_image_name="b.png",
                        prompt="p",
                        seed=1,
                        sage=value,
                    )

    def test_no_muta_el_original(self):
        prepare_h3_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            prompt="p",
            seed=3,
            variant="turbo8",
            sage=True,
        )
        self.assertEqual(self.graph, self.snapshot)

    def test_nodo_campo_o_clase_mal_lanza_engine_error(self):
        for node_id in ("140", "141", "131", "129"):
            with self.subTest(node_id=node_id):
                broken = copy.deepcopy(self.graph)
                del broken[node_id]
                with self.assertRaises(EngineError):
                    prepare_h3_graph(
                        broken,
                        first_image_name="a.png",
                        last_image_name="b.png",
                        prompt="p",
                        seed=1,
                    )
        broken = copy.deepcopy(self.graph)
        del broken["131"]["inputs"]["prompt"]
        with self.assertRaises(EngineError):
            prepare_h3_graph(
                broken, first_image_name="a.png", last_image_name="b.png", prompt="p", seed=1
            )
        broken = copy.deepcopy(self.graph)
        broken["129"]["class_type"] = "KSampler"
        with self.assertRaises(EngineError):
            prepare_h3_graph(
                broken, first_image_name="a.png", last_image_name="b.png", prompt="p", seed=1
            )

    def test_entradas_invalidas_lanzan_engine_error(self):
        base = {
            "first_image_name": "a.png",
            "last_image_name": "b.png",
            "prompt": "p",
            "seed": 1,
        }
        for override in ({"first_image_name": ""}, {"last_image_name": "  "}, {"prompt": " "}):
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    prepare_h3_graph(self.graph, **(base | override))

    def test_i2v_sin_last_quita_nodo_y_entrada(self):
        patched = prepare_h3_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name=None,
            prompt="p",
            seed=1,
        )
        self.assertNotIn("141", patched)
        self.assertNotIn("last_frame", patched["131"]["inputs"])
        self.assertEqual(patched["140"]["inputs"]["image"], "a.png")
        self.assertIn("141", self.graph)

    def test_tamano_y_frames_patch(self):
        patched = prepare_h3_graph(
            self.graph,
            first_image_name="a.png",
            last_image_name="b.png",
            prompt="p",
            seed=1,
            width=768,
            height=1344,
            frames=243,
        )
        self.assertEqual(patched["131"]["inputs"]["width"], 768)
        self.assertEqual(patched["131"]["inputs"]["height"], 1344)
        self.assertEqual(patched["131"]["inputs"]["length"], 243)

    def test_tamano_o_frames_invalidos(self):
        base = {
            "first_image_name": "a.png",
            "last_image_name": "b.png",
            "prompt": "p",
            "seed": 1,
        }
        for frames in (81, 120, 123, 363, True, "192", 192.0):
            with self.subTest(frames=frames):
                with self.assertRaises(EngineError):
                    prepare_h3_graph(self.graph, **(base | {"frames": frames}))
        for width, height in ((600, 1024), (2048, 576), (1024, 1024), (576, 1024.0)):
            with self.subTest(width=width, height=height):
                with self.assertRaises(EngineError):
                    prepare_h3_graph(
                        self.graph, **(base | {"width": width, "height": height})
                    )


class BuildVideoGraphTests(unittest.TestCase):
    def test_engine_invalido(self):
        with self.assertRaises(EngineError):
            build_video_graph({"engine": "nope", "template": str(WAN_TEMPLATE_PATH)})

    def test_template_ausente(self):
        with self.assertRaises(EngineError):
            build_video_graph({"engine": "wan", "template": ""})

    def test_aspect_invalido(self):
        with self.assertRaises(EngineError):
            build_video_graph(
                {
                    "engine": "wan",
                    "template": str(WAN_TEMPLATE_PATH),
                    "image_name": "f.png",
                    "motion_positive": "m",
                    "motion_negative": "n",
                    "aspect": "cuadrado",
                    "seed": 1,
                }
            )

    def test_mode_invalido(self):
        with self.assertRaises(EngineError):
            build_video_graph(
                {
                    "engine": "wan",
                    "template": str(WAN_TEMPLATE_PATH),
                    "mode": "nope",
                    "image_name": "f.png",
                    "motion_positive": "m",
                    "motion_negative": "n",
                    "seed": 1,
                }
            )

    def test_flf_por_plantilla_y_frames(self):
        graph = build_video_graph(
            {
                "engine": "wan",
                "template": str(WAN_FLF_TEMPLATE_PATH),
                "image_name": "a.png",
                "last_image_name": "b.png",
                "motion_positive": "m",
                "motion_negative": "n",
                "seed": 1,
                "frames": 129,
            }
        )
        self.assertEqual(graph["9"]["class_type"], "WanFirstLastFrameToVideo")
        self.assertEqual(graph["9"]["inputs"]["length"], 129)
        self.assertEqual(graph["7"]["inputs"]["image"], "a.png")
        self.assertEqual(graph["8"]["inputs"]["image"], "b.png")

    def test_i2v_frames_patch(self):
        graph = build_video_graph(
            {
                "engine": "wan",
                "template": str(WAN_TEMPLATE_PATH),
                "image_name": "a.png",
                "motion_positive": "m",
                "motion_negative": "n",
                "seed": 1,
                "frames": 129,
            }
        )
        self.assertEqual(graph["9"]["inputs"]["length"], 129)


class BuildVideoGraphH3Tests(unittest.TestCase):
    def job(self, **overrides) -> dict:
        base = {
            "engine": "h3",
            "image_name": "a.png",
            "last_image_name": "b.png",
            "prompt": "integrated_multimodal_description: test",
            "seed": 3,
        }
        return base | overrides

    def assert_grafo_valido(self, graph: dict) -> None:
        self.assertEqual(graph["140"]["inputs"]["image"], "a.png")
        self.assertEqual(graph["141"]["inputs"]["image"], "b.png")
        self.assertEqual(
            graph["131"]["inputs"]["prompt"],
            "integrated_multimodal_description: test",
        )

    def test_sin_perfil_usa_referencia(self):
        graph = build_video_graph(self.job())
        self.assert_grafo_valido(graph)
        self.assertEqual(graph["128"]["inputs"]["type"], "minimax")
        self.assertEqual(graph["131"]["inputs"]["clip"], ["128", 0])
        self.assertEqual(graph["131"]["inputs"]["width"], 576)
        self.assertEqual(graph["131"]["inputs"]["height"], 1024)
        self.assertEqual(graph["131"]["inputs"]["length"], 192)

    def test_perfil_calidad_usa_plantilla_clipproj(self):
        profile = resolve_h3_profile("calidad")
        graph = build_video_graph(self.job(profile="calidad"))
        self.assert_grafo_valido(graph)
        self.assertEqual(graph["127"]["inputs"]["unet_name"], profile["dit"])
        self.assertEqual(graph["119"]["inputs"]["vae_name"], profile["vae_video"])
        self.assertEqual(graph["120"]["inputs"]["vae_name"], profile["vae_audio"])
        self.assertEqual(graph["128"]["inputs"]["clip_name"], profile["encoder"])
        self.assertEqual(graph["128"]["inputs"]["type"], "krea2")
        self.assertEqual(graph["135"]["inputs"]["projection"], profile["projection"])
        self.assertEqual(graph["135"]["inputs"]["clip"], ["128", 0])
        self.assertEqual(graph["131"]["inputs"]["clip"], ["135", 0])
        self.assertEqual(graph["131"]["inputs"]["length"], 192)

    def test_perfil_ligero_con_segundos_y_resolucion(self):
        profile = resolve_h3_profile("ligero")
        graph = build_video_graph(
            self.job(profile="ligero", seconds=10, width=768, height=1344)
        )
        self.assert_grafo_valido(graph)
        self.assertEqual(graph["127"]["inputs"]["unet_name"], profile["dit"])
        self.assertEqual(graph["119"]["inputs"]["vae_name"], profile["vae_video"])
        self.assertEqual(graph["131"]["inputs"]["length"], h3_frames_for_seconds(10))
        self.assertEqual(graph["131"]["inputs"]["width"], 768)
        self.assertEqual(graph["131"]["inputs"]["height"], 1344)

    def test_calidad_horizontal_y_frames_explicitos(self):
        graph = build_video_graph(
            self.job(profile="calidad", aspect="horizontal", frames=294)
        )
        self.assertEqual(graph["131"]["inputs"]["width"], 1024)
        self.assertEqual(graph["131"]["inputs"]["height"], 576)
        self.assertEqual(graph["131"]["inputs"]["length"], 294)

    def test_plantilla_del_job_gana_al_perfil(self):
        graph = build_video_graph(
            self.job(profile="calidad", template=str(H3_TEMPLATE_PATH))
        )
        self.assertEqual(graph["131"]["inputs"]["clip"], ["128", 0])

    def test_cada_perfil_carga_su_plantilla(self):
        for profile in ("referencia", "calidad", "ligero"):
            with self.subTest(profile=profile):
                entry = resolve_h3_profile(profile)
                job = self.job(profile=profile, template=str(h3_template_path(entry)))
                graph = build_video_graph(job)
                self.assert_grafo_valido(graph)

    def test_variante_default_turbo4_sin_campo(self):
        graph = build_video_graph(self.job())
        self.assertEqual(graph["134"]["inputs"]["lora_name"], H3_LORA_4STEP)
        self.assertEqual(graph["124"]["inputs"]["steps"], 4)

    def test_variante_turbo8_en_cada_perfil(self):
        for profile in ("referencia", "calidad", "ligero"):
            with self.subTest(profile=profile):
                graph = build_video_graph(self.job(profile=profile, variant="turbo8"))
                self.assertEqual(graph["134"]["inputs"]["lora_name"], H3_LORA_8STEP)
                self.assertEqual(graph["124"]["inputs"]["steps"], 8)

    def test_sage_rewira_guider_y_scheduler(self):
        graph = build_video_graph(self.job(sage=True))
        sage_id = next(
            node_id
            for node_id, node in graph.items()
            if node.get("class_type") == H3_SAGE_NODE_CLASS
        )
        self.assertEqual(
            graph[sage_id]["inputs"],
            {"model": ["134", 0], "sage_attention": H3_SAGE_MODE},
        )
        self.assertEqual(graph["126"]["inputs"]["model"], [sage_id, 0])
        self.assertEqual(graph["124"]["inputs"]["model"], [sage_id, 0])
        self.assertEqual(graph["131"]["inputs"]["clip"], ["128", 0])

    def test_sin_sage_no_inserta_nodo(self):
        graph = build_video_graph(self.job(sage=False))
        self.assertNotIn(
            H3_SAGE_NODE_CLASS,
            [node.get("class_type") for node in graph.values()],
        )
        self.assertEqual(graph["126"]["inputs"]["model"], ["134", 0])
        self.assertEqual(graph["124"]["inputs"]["model"], ["134", 0])

    def test_invalidos(self):
        cases = (
            {"profile": "nope"},
            {"profile": 5},
            {"variant": "nope"},
            {"variant": "TURBO8"},
            {"variant": 5},
            {"variant": True},
            {"sage": 1},
            {"sage": "si"},
            {"sage": None},
            {"seconds": 6},
            {"seconds": 0},
            {"seconds": "8"},
            {"frames": 81},
            {"frames": True},
            {"width": 600, "height": 1024},
            {"width": 2048, "height": 576},
            {"width": 576},
            {"height": 1024},
            {"aspect": "cuadrado"},
        )
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(EngineError):
                    build_video_graph(self.job(**override))


class VideoTestCase(unittest.TestCase):
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


class FakeVideoTransport:
    """Transporte falso: submit y history success con un mp4 escrito en disco."""

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


class BlockingWs:
    """WS falso que se queda abierto hasta que el tracker se cancela."""

    async def __aenter__(self):
        await asyncio.Event().wait()
        raise AssertionError("inalcanzable")

    async def __aexit__(self, exc_type, exc, tb):
        return False


def blocking_ws_factory(url: str) -> BlockingWs:
    return BlockingWs()


class RunVideoTests(VideoTestCase):
    def make_job(self, **overrides) -> dict:
        gen_id = self.store.add("wan", "motion", "", {"seed": 7}, kind="video")
        job = {
            "kind": "video",
            "gen_id": gen_id,
            "engine": "wan",
            "template": str(WAN_TEMPLATE_PATH),
            "image_name": "frame.png",
            "last_image_name": None,
            "motion_positive": "She walks slowly.",
            "motion_negative": "no motion",
            "prompt": "",
            "aspect": "vertical",
            "seed": 7,
        }
        job.update(overrides)
        return job

    def factory(self, transport):
        return lambda: ComfyEngine(
            self.config, transport=transport, poll_s=0.01, history_timeout_s=5.0
        )

    def test_wan_end_to_end_copia_a_galeria(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job()
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["outputs"], ["clip.mp4"])
        self.assertIsNone(row["error"])
        copied = self.config.data_dir / "gallery" / str(job["gen_id"]) / "clip.mp4"
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), MP4_BYTES)
        self.assertEqual(job["outputs"], ["clip.mp4"])
        self.assertIsNone(job["error"])
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["5"]["inputs"]["text"], "She walks slowly.")
        self.assertEqual(graph["6"]["inputs"]["text"], "no motion")
        self.assertEqual(graph["7"]["inputs"]["image"], "frame.png")
        self.assertEqual(graph["12"]["inputs"]["noise_seed"], 7)
        self.assertEqual(graph["9"]["inputs"]["width"], 432)
        self.assertEqual(graph["9"]["inputs"]["height"], 768)

    def test_horizontal_patch(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job(aspect="horizontal")
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["9"]["inputs"]["width"], 768)
        self.assertEqual(graph["9"]["inputs"]["height"], 432)

    def test_preset_del_job_se_aplica_al_grafo(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job(preset="calidad")
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["9"]["inputs"]["width"], 512)
        self.assertEqual(graph["9"]["inputs"]["height"], 896)
        self.assertEqual(graph["12"]["inputs"]["sampler_name"], "er_sde")
        self.assertEqual(graph["12"]["inputs"]["steps"], 30)
        self.assertEqual(graph["12"]["inputs"]["end_at_step"], 15)
        self.assertEqual(graph["13"]["inputs"]["start_at_step"], 15)
        self.assertEqual(graph["10"]["inputs"]["shift"], 5.0)
        self.assertEqual(graph["11"]["inputs"]["shift"], 5.0)

    def test_overrides_del_job_ganan_al_preset(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job(preset="calidad", steps=20, shift=8.0)
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["12"]["inputs"]["steps"], 20)
        self.assertEqual(graph["12"]["inputs"]["sampler_name"], "er_sde")

    def test_h3_end_to_end(self):
        transport = FakeVideoTransport(self.config, output_name="h3.webm")
        gen_id = self.store.add("h3", "prompt h3", "", {}, kind="video")
        job = {
            "kind": "video",
            "gen_id": gen_id,
            "engine": "h3",
            "template": str(H3_TEMPLATE_PATH),
            "image_name": "first.png",
            "last_image_name": "last.png",
            "motion_positive": "",
            "motion_negative": "",
            "prompt": "integrated_multimodal_description: test",
            "aspect": "vertical",
            "seed": 11,
        }
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(gen_id)
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(row["outputs"], ["h3.webm"])
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["140"]["inputs"]["image"], "first.png")
        self.assertEqual(graph["141"]["inputs"]["image"], "last.png")
        self.assertEqual(
            graph["131"]["inputs"]["prompt"], "integrated_multimodal_description: test"
        )
        self.assertEqual(graph["129"]["inputs"]["noise_seed"], 11)

    def test_negativo_por_defecto_si_falta(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job(motion_negative=None)
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["6"]["inputs"]["text"], MOTION_NEGATIVE)

    def test_sin_video_marca_error_sin_propagar(self):
        transport = FakeVideoTransport(self.config, write_output=False)
        job = self.make_job()
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["kind"], "video")
        self.assertTrue(row["error"])
        self.assertEqual(job["outputs"], [])
        self.assertTrue(job["error"])

    def test_engine_desconocido_marca_error(self):
        transport = FakeVideoTransport(self.config)
        job = self.make_job(engine="nope")
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(job["gen_id"])
        self.assertEqual(row["status"], "error")
        self.assertIn("engine invalido", row["error"])
        self.assertEqual(transport.submits, [])

    def test_flf2v_end_to_end(self):
        transport = FakeVideoTransport(self.config)
        gen_id = self.store.add("wan", "motion", "", {"seed": 7}, kind="video")
        job = {
            "kind": "video",
            "gen_id": gen_id,
            "engine": "wan",
            "mode": "flf2v",
            "template": str(WAN_FLF_TEMPLATE_PATH),
            "image_name": "first.png",
            "last_image_name": "last.png",
            "motion_positive": "She walks slowly.",
            "motion_negative": "no motion",
            "prompt": "",
            "aspect": "vertical",
            "frames": 129,
            "seed": 7,
        }
        run_video_generation(
            job, config=self.config, store=self.store, engine_factory=self.factory(transport)
        )
        row = self.store.get(gen_id)
        self.assertEqual(row["status"], "done")
        graph = transport.submits[0]["prompt"]
        self.assertEqual(graph["7"]["inputs"]["image"], "first.png")
        self.assertEqual(graph["8"]["inputs"]["image"], "last.png")
        self.assertEqual(graph["9"]["inputs"]["length"], 129)
        self.assertEqual(graph["5"]["inputs"]["text"], "She walks slowly.")

    def test_registra_engine_prompt_id_y_tracker(self):
        transport = FakeVideoTransport(self.config)
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
            "kind": "video",
        }
        job = self.make_job()
        run_video_generation(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            ws_factory=blocking_ws_factory,
            record=record,
        )
        self.assertIsNotNone(record["engine"])
        self.assertEqual(record["prompt_id"], "p1")
        self.assertEqual(record["status"], "done")
        tracker = record["tracker"]
        self.assertIsNotNone(tracker)
        self.assertFalse(tracker._thread is not None and tracker._thread.is_alive())

    def test_record_cancelado_antes_de_arrancar_no_ejecuta(self):
        transport = FakeVideoTransport(self.config)
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "cancelled",
            "engine": None,
            "kind": "video",
        }
        job = self.make_job()
        run_video_generation(
            job,
            config=self.config,
            store=self.store,
            engine_factory=self.factory(transport),
            record=record,
        )
        self.assertEqual(transport.submits, [])
        self.assertEqual(job["outputs"], [])
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(self.store.get(job["gen_id"])["status"], "queued")

    def test_fallo_tras_cancelar_conserva_cancelled(self):
        record = {
            "prompt_id": None,
            "tracker": None,
            "status": "queued",
            "engine": None,
            "kind": "video",
        }

        class CancelThenFail:
            client_id = "cancel-fail"

            def submit(self, graph):
                record["status"] = "cancelled"
                return "p1"

            def wait(self, prompt_id):
                raise EngineError("prompt interrumpido por cancelacion")

        job = self.make_job()
        run_video_generation(
            job,
            config=self.config,
            store=self.store,
            engine_factory=lambda: CancelThenFail(),
            ws_factory=blocking_ws_factory,
            record=record,
        )
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(self.store.get(job["gen_id"])["status"], "cancelled")
        self.assertIsNone(job["error"])
        self.assertEqual(job["outputs"], [])


class StoreKindMigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "waifu.db"

    def _old_db_with_row(self) -> None:
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute(_OLD_SCHEMA)
            conn.execute(
                "INSERT INTO generations (created_at, model_id, prompt, status) "
                "VALUES ('2026-01-01T00:00:00+00:00', 'm', 'p', 'done')"
            )

    def test_init_migra_db_existente_sin_kind(self):
        self._old_db_with_row()
        store = Store(self.db_path)
        store.init()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            columns = [
                row[1] for row in conn.execute("PRAGMA table_info(generations)")
            ]
        self.assertIn("kind", columns)
        self.assertEqual(store.get(1)["kind"], "image")
        video_id = store.add("wan", "motion", kind="video")
        self.assertEqual(store.get(video_id)["kind"], "video")
        self.assertEqual(
            [row["kind"] for row in store.list(order="asc")], ["image", "video"]
        )

    def test_init_idempotente(self):
        store = Store(self.db_path)
        store.init()
        store.init()
        self.assertEqual(store.count(), 0)


if __name__ == "__main__":
    unittest.main()
