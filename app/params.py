"""Enums reales de sampler/scheduler del engine ComfyUI local.

Fuente EXACTA (solo lectura, copiada aqui a mano):
``E:\\IA\\WAIFU\\ComfyUI\\comfy\\samplers.py``.
- ``SAMPLER_NAMES`` = ``KSAMPLER_NAMES`` (:971-975) + ``["ddim", "uni_pc",
  "uni_pc_bh2"]`` (:1356); ``KSampler.SAMPLERS = SAMPLER_NAMES`` (:1401).
- ``SCHEDULER_NAMES`` = ``list(SCHEDULER_HANDLERS)`` (:1376), claves de
  ``SCHEDULER_HANDLERS`` (:1365-1375); ``KSampler.SCHEDULERS = SCHEDULER_NAMES``
  (:1400).

Orden real del engine (sin reordenar ni filtrar); solo stdlib, sin red.
"""

from __future__ import annotations

SAMPLER_NAMES: tuple[str, ...] = (
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

SCHEDULER_NAMES: tuple[str, ...] = (
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

DEFAULT_SAMPLER = "euler"
DEFAULT_SCHEDULER = "sgm_uniform"


def is_valid_sampler(name: object) -> bool:
    """True si ``name`` es un sampler del engine (compara exacto, case-sensitive)."""
    return isinstance(name, str) and name in SAMPLER_NAMES


def is_valid_scheduler(name: object) -> bool:
    """True si ``name`` es un scheduler del engine (compara exacto, case-sensitive)."""
    return isinstance(name, str) and name in SCHEDULER_NAMES


__all__ = [
    "DEFAULT_SAMPLER",
    "DEFAULT_SCHEDULER",
    "SAMPLER_NAMES",
    "SCHEDULER_NAMES",
    "is_valid_sampler",
    "is_valid_scheduler",
]
