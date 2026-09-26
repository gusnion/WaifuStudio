"""Prompt de video H3 escrito por el LLM local (M10-4e).

Igual que `app.motion` pero para MiniMax H3 (FL2VA): el LLM INYECTADO
(`llm(system, user) -> str`) escribe los tres bloques del prompt
(`integrated_multimodal_description`, `overall_soundscape`,
`non_diegetic_music`) a partir de una descripcion en lenguaje natural.
El loader real se reutiliza de `app.enhancer.load_local_llm` y jamas se
ejecuta en tests.
"""

from __future__ import annotations

from typing import Callable

from app.engine import EngineError
from app.enhancer import load_local_llm

LlmFn = Callable[[str, str], str]

H3_BLOCKS = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)

SYS_PROMPT_H3 = (
    "Eres el escritor de prompts del generador de video anime MiniMax H3 (FL2VA) local.\n"
    "Recibes en lenguaje natural (espanol) lo que debe verse y oirse, y el rating activo.\n"
    "Devuelve EXACTAMENTE tres bloques, uno por linea y en este orden, sin preambulo, "
    "sin comillas y sin explicaciones:\n"
    "integrated_multimodal_description: <sujeto, vestuario, entorno, luz, camara y "
    "movimiento restringido; una sola toma continua, sin cortes>\n"
    "overall_soundscape: <ambiente y efectos; dialogo solo si aplica>\n"
    "non_diegetic_music: <musica o None>\n"
    "- el dialogo va con idioma explicito: <d>[Espanol] texto</d>, con un speaker id "
    "estable declarado antes de las voces (p. ej. speaker_1) y sin llenar mas de ~2/3 "
    "de su plano;\n"
    "- si rating=nsfw se explicito con el acto y el movimiento, sin eufemismos; NUNCA "
    "describas ni pidas censura (nada de mosaic/bar censor);\n"
    "- HARD RULE: todos los personajes son adultos (21+); nunca menores ni los terminos "
    "child, teen, loli o young-looking;\n"
    "- las lineas internas de contexto (escena/rating) son referencia: nunca las copies "
    "literalmente;\n"
    "- responde SOLO con los tres bloques."
)


def clean_h3_prompt(text) -> str:
    """Normaliza el prompt H3: exige los tres bloques y colapsa espacios sobrantes.

    Conserva los saltos de linea entre bloques; quita comillas envolventes y
    lineas vacias. EngineError si no hay texto o falta alguno de los bloques.
    """
    if not isinstance(text, str) or not text.strip():
        raise EngineError("h3_prompt: el modelo no devolvio prompt")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    for quote in ('"', "'", "`"):
        if len(cleaned) > 1 and cleaned.startswith(quote) and cleaned.endswith(quote):
            cleaned = cleaned[1:-1].strip()
    for block in H3_BLOCKS:
        if f"{block}:" not in cleaned:
            raise EngineError(f"h3_prompt: falta el bloque {block}")
    return cleaned


def write_h3_prompt(
    text, rating: str = "nsfw", llm: LlmFn | None = None
) -> dict[str, str]:
    """Escribe el prompt H3 (tres bloques) con el LLM y lo devuelve limpio.

    `llm(system, user) -> str` es obligatorio (EngineError si falta); el rating
    debe ser `sfw` o `nsfw`; el texto debe ser no vacio. La respuesta es
    `{"h3_prompt": <tres bloques>}`.
    """
    if not isinstance(text, str) or not text.strip():
        raise EngineError("h3_prompt: escena vacia")
    if rating not in ("nsfw", "sfw"):
        raise EngineError(f"h3_prompt: rating invalido {rating!r}; usar nsfw|sfw")
    if llm is None:
        raise EngineError("LLM no inyectado")
    user = (
        "escena: " + text.strip()
        + "\nrating: " + rating
        + "\nDevuelve solo los tres bloques del prompt H3."
    )
    raw = llm(SYS_PROMPT_H3, user)
    if not isinstance(raw, str):
        raise EngineError("h3_prompt: el LLM no devolvio texto")
    return {"h3_prompt": clean_h3_prompt(raw)}


__all__ = [
    "H3_BLOCKS",
    "SYS_PROMPT_H3",
    "clean_h3_prompt",
    "load_local_llm",
    "write_h3_prompt",
]
