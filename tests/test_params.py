"""Tests CPU de los enums reales de sampler/scheduler (M9-A1). Sin red ni GPU.

Los goldens son las listas EXACTAS de ``ComfyUI/comfy/samplers.py``
(``KSampler.SAMPLERS``/``KSampler.SCHEDULERS``); si el engine local cambia,
estos tests avisan.
"""

from __future__ import annotations

import unittest

from app.params import (
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    SAMPLER_NAMES,
    SCHEDULER_NAMES,
    is_valid_sampler,
    is_valid_scheduler,
)

GOLDEN_SAMPLERS = (
    "euler",
    "euler_cfg_pp",
    "euler_ancestral",
    "euler_ancestral_cfg_pp",
    "heun",
    "heunpp2",
    "exp_heun_2_x0",
    "exp_heun_2_x0_sde",
    "dpm_2",
    "dpm_2_ancestral",
    "lms",
    "dpm_fast",
    "dpm_adaptive",
    "dpmpp_2s_ancestral",
    "dpmpp_2s_ancestral_cfg_pp",
    "dpmpp_sde",
    "dpmpp_sde_gpu",
    "dpmpp_2m",
    "dpmpp_2m_cfg_pp",
    "dpmpp_2m_sde",
    "dpmpp_2m_sde_gpu",
    "dpmpp_2m_sde_heun",
    "dpmpp_2m_sde_heun_gpu",
    "dpmpp_3m_sde",
    "dpmpp_3m_sde_gpu",
    "ddpm",
    "lcm",
    "ipndm",
    "ipndm_v",
    "deis",
    "res_multistep",
    "res_multistep_cfg_pp",
    "res_multistep_ancestral",
    "res_multistep_ancestral_cfg_pp",
    "gradient_estimation",
    "gradient_estimation_cfg_pp",
    "er_sde",
    "seeds_2",
    "seeds_3",
    "sa_solver",
    "sa_solver_pece",
    "ddim",
    "uni_pc",
    "uni_pc_bh2",
)

GOLDEN_SCHEDULERS = (
    "simple",
    "sgm_uniform",
    "karras",
    "exponential",
    "ddim_uniform",
    "beta",
    "normal",
    "linear_quadratic",
    "kl_optimal",
)


class SamplerNamesTests(unittest.TestCase):
    def test_golden_exacto_y_orden_real(self):
        self.assertEqual(SAMPLER_NAMES, GOLDEN_SAMPLERS)
        self.assertEqual(len(SAMPLER_NAMES), 44)

    def test_tipo_tuple_de_str_unicos(self):
        self.assertIsInstance(SAMPLER_NAMES, tuple)
        self.assertTrue(all(isinstance(name, str) and name for name in SAMPLER_NAMES))
        self.assertEqual(len(SAMPLER_NAMES), len(set(SAMPLER_NAMES)))

    def test_primer_sampler_y_cola_del_engine(self):
        self.assertEqual(SAMPLER_NAMES[0], "euler")
        self.assertEqual(SAMPLER_NAMES[-3:], ("ddim", "uni_pc", "uni_pc_bh2"))


class SchedulerNamesTests(unittest.TestCase):
    def test_golden_exacto_y_orden_real(self):
        self.assertEqual(SCHEDULER_NAMES, GOLDEN_SCHEDULERS)
        self.assertEqual(len(SCHEDULER_NAMES), 9)

    def test_tipo_tuple_de_str_unicos(self):
        self.assertIsInstance(SCHEDULER_NAMES, tuple)
        self.assertTrue(
            all(isinstance(name, str) and name for name in SCHEDULER_NAMES)
        )
        self.assertEqual(len(SCHEDULER_NAMES), len(set(SCHEDULER_NAMES)))

    def test_primer_scheduler(self):
        self.assertEqual(SCHEDULER_NAMES[0], "simple")


class DefaultsTests(unittest.TestCase):
    def test_defaults_presentes_en_los_enums(self):
        self.assertIn(DEFAULT_SAMPLER, SAMPLER_NAMES)
        self.assertIn(DEFAULT_SCHEDULER, SCHEDULER_NAMES)

    def test_defaults_golden(self):
        self.assertEqual(DEFAULT_SAMPLER, "euler")
        self.assertEqual(DEFAULT_SCHEDULER, "sgm_uniform")


class ValidationTests(unittest.TestCase):
    def test_is_valid_sampler_acepta_todos_los_reales(self):
        for name in SAMPLER_NAMES:
            with self.subTest(name=name):
                self.assertTrue(is_valid_sampler(name))

    def test_is_valid_scheduler_acepta_todos_los_reales(self):
        for name in SCHEDULER_NAMES:
            with self.subTest(name=name):
                self.assertTrue(is_valid_scheduler(name))

    def test_desconocidos_y_no_str_false(self):
        for value in ("nope", "Euler", "", None, 5, True, ["euler"], {"euler"}):
            with self.subTest(value=value):
                self.assertFalse(is_valid_sampler(value))
                self.assertFalse(is_valid_scheduler(value))

    def test_case_sensitive(self):
        self.assertFalse(is_valid_sampler("EULER"))
        self.assertFalse(is_valid_scheduler("SGM_UNIFORM"))


if __name__ == "__main__":
    unittest.main()
