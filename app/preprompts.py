"""Catalogo de preprompts de calidad por familia (M8-12).

Textos copiados EXACTOS del planner legacy certificado:
``E:\\IA\\VIDEO\\local_prompt_planner\\local_planner.py`` (QUALITY_PREPROMPTS).
Aqui solo se catalogan; aplicarlos al prompt es responsabilidad de F2.
"""

from __future__ import annotations

from app.engine import EngineError

FAMILY_PREPROMPTS: dict[str, dict[str, dict[str, str]]] = {
    "anima": {
        "anima_default": {
            "positive": "masterpiece, best quality, score_8",
            "negative": (
                "worst quality, low quality, score_1, score_2, score_3, artist name"
            ),
        },
        "glossy": {
            "positive": (
                "masterpiece, best quality, absurdres, highres, score_7, score_8, "
                "score_9"
            ),
            "negative": (
                "worst quality, low quality, score_1, score_2, score_3, blurry, "
                "jpeg artifacts, sepia, bad anatomy, bad hands, mutated hands, "
                "fused fingers, extra fingers, watermark, signature, logo"
            ),
        },
        "not_glossy": {
            "positive": "newest, good quality, score_6, score_5, highres",
            "negative": "low quality, score_1, score_2",
        },
        "ninguno": {"positive": "", "negative": ""},
    },
}

DEFAULT_FAMILY = "anima"
DEFAULT_PREPROMPT = "glossy"


def list_families() -> list[str]:
    """Nombres de familia registrados, ordenados."""
    return sorted(FAMILY_PREPROMPTS)


def list_preprompts(family: str) -> list[str]:
    """Nombres de preprompt de una familia, ordenados; EngineError si no existe."""
    if family not in FAMILY_PREPROMPTS:
        raise EngineError(f"familia de preprompts desconocida: {family!r}")
    return sorted(FAMILY_PREPROMPTS[family])


def get_preprompt(family: str, name: str) -> dict[str, str]:
    """Copia de {"positive": str, "negative": str}; EngineError si familia o nombre no existen."""
    if family not in FAMILY_PREPROMPTS:
        raise EngineError(f"familia de preprompts desconocida: {family!r}")
    preprompts = FAMILY_PREPROMPTS[family]
    if name not in preprompts:
        raise EngineError(f"preprompt desconocido {name!r} en familia {family!r}")
    return dict(preprompts[name])


__all__ = [
    "DEFAULT_FAMILY",
    "DEFAULT_PREPROMPT",
    "FAMILY_PREPROMPTS",
    "get_preprompt",
    "list_families",
    "list_preprompts",
]
