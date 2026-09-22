"""Motion de video escrito por el LLM local (F4).

Reimplementación de ``local_prompt_planner.motion`` con el LLM INYECTADO
(`llm(system, user) -> str`) para que los tests corran offline: el loader real
se reutiliza de `app.enhancer.load_local_llm` y jamás se ejecuta en tests.
`SYS_PROMPT_MOTION` y `MOTION_NEGATIVE` son copias EXACTAS del legacy
certificado (`E:\\IA\\VIDEO\\local_prompt_planner\\motion.py`); el negativo es
determinista y el LLM solo escribe el positivo.
"""

from __future__ import annotations

from typing import Callable

from app.engine import EngineError
from app.enhancer import load_local_llm

LlmFn = Callable[[str, str], str]

# Negativo fijo del video (determinista): calidad + sin movimiento + anti-censura
# + anti-menores (obligatorio) + manos/anatomia. Copia EXACTA del legacy.
MOTION_NEGATIVE = (
    "worst quality, low quality, blurry, static image, no motion, mosaic censoring, "
    "bar censor, child, teen, loli, young-looking, deformed hands, extra limbs"
)

# Copia EXACTA (texto, sin reformatear) del SYS_PROMPT legacy.
SYS_PROMPT_MOTION = (
    "Eres el escritor de motion prompts de un generador de video anime local "
    "(Wan 2.2 I2V).\n"
    "Recibes en lenguaje natural (espanol) lo que debe pasar en el video y el rating activo.\n"
    "Escribe UN motion prompt en INGLES con 1-3 frases naturales (NO tags danbooru, "
    "NO listas, NO comillas, NO preambulo):\n"
    "- describe el movimiento de los cuerpos y de la camara (handheld, estatica, leve "
    "paneo...) manteniendo la coherencia con el frame de entrada (I2V);\n"
    "- si rating=nsfw se explicito con el acto y el movimiento, sin eufemismos; NUNCA "
    "describas ni pidas censura (nada de mosaic/bar censor);\n"
    "- HARD RULE: todos los personajes son adultos (21+); nunca menores ni los terminos "
    "child, teen, loli o young-looking;\n"
    "- las lineas internas de contexto (movimiento/rating/duracion) son referencia: "
    "nunca las copies literalmente;\n"
    "- responde SOLO con el motion prompt."
)


def clean_motion(text) -> str:
    """Una linea limpia (strip + colapso de espacios); comillas envolventes fuera.

    Misma semantica que `_clean_motion` legacy, con EngineError.
    """
    if not isinstance(text, str) or not text.strip():
        raise EngineError("motion: el modelo no devolvio motion prompt")
    cleaned = " ".join(text.split())
    for quote in ('"', "'", "`"):
        if len(cleaned) > 1 and cleaned.startswith(quote) and cleaned.endswith(quote):
            cleaned = cleaned[1:-1].strip()
    if not cleaned:
        raise EngineError("motion: motion prompt vacio tras limpieza")
    return cleaned


def write_motion(
    text, rating: str = "nsfw", llm: LlmFn | None = None
) -> dict[str, str]:
    """Escribe el motion positivo con el LLM y devuelve positivo + negativo fijo.

    `llm(system, user) -> str` es obligatorio (EngineError si falta); el rating
    debe ser `sfw` o `nsfw`; el texto debe ser no vacío. El resultado es
    determinista salvo por el LLM: negativo = `MOTION_NEGATIVE`.
    """
    if not isinstance(text, str) or not text.strip():
        raise EngineError("motion: movimiento vacio")
    if rating not in ("nsfw", "sfw"):
        raise EngineError(f"motion: rating invalido {rating!r}; usar nsfw|sfw")
    if llm is None:
        raise EngineError("LLM no inyectado")
    user = (
        "movimiento: " + text.strip()
        + "\nrating: " + rating
        + "\nEscribe solo el motion prompt en ingles."
    )
    raw = llm(SYS_PROMPT_MOTION, user)
    if not isinstance(raw, str):
        raise EngineError("motion: el LLM no devolvio texto")
    return {"motion_positive": clean_motion(raw), "motion_negative": MOTION_NEGATIVE}


__all__ = [
    "MOTION_NEGATIVE",
    "SYS_PROMPT_MOTION",
    "clean_motion",
    "load_local_llm",
    "write_motion",
]
