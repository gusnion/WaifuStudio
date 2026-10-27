"""Motion de video escrito por el LLM local (F4).

Reimplementación del planner de motion legacy con el LLM INYECTADO
(`llm(system, user) -> str`) para que los tests corran offline: el loader real
se reutiliza de `app.enhancer.load_local_llm` y jamás se ejecuta en tests.
`SYS_PROMPT_MOTION` y `MOTION_NEGATIVE` son copias EXACTAS del legacy
certificado (retirado el 2026-09-26; archivado en
``data\\gates\\m10\\evidencia-legacy\\motion.py``, fuera de git); el negativo es
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

# Prompt de sistema para Wan 2.2 I2V/FLF2V. Las reglas de formato son
# deliberadamente estrictas: el modelo pequeno tiende a escribir parrafos,
# tags o acciones nuevas si no se le acota.
SYS_PROMPT_MOTION = (
    "Eres el escritor de motion prompts de un generador de video anime local "
    "(Wan 2.2 I2V/FLF2V).\n"
    "Recibes en lenguaje natural (espanol) lo que debe pasar en el video, el rating activo, "
    "un enfoque y una fuerza opcionales.\n"
    "Escribe UN motion prompt en INGLES, en presente, con 1-3 frases naturales y maximo 70 palabras. "
    "NO uses tags danbooru, listas, JSON, comillas, markdown ni preambulo.\n"
    "Reglas obligatorias:\n"
    "- Empieza por el sujeto y la accion solicitada; conserva identidad, ropa, cara y composicion "
    "del frame de entrada (I2V);\n"
    "- describe UN movimiento corporal principal y, solo si aporta, un movimiento secundario "
    "(pelo, tela, respiracion);\n"
    "- indica explicitamente UN movimiento de camara: static camera, slow push-in, slow pull-out, "
    "slow pan left/right, slow orbit o subtle handheld movement;\n"
    "- menciona entorno o iluminacion solo si ayuda; no inventes personajes, objetos, ropa, "
    "acciones ni dialogos nuevos;\n"
    "- una sola toma continua: prohibido cuts, scene changes, transitions o multiple shots;\n"
    "- no anadas romance, invitaciones, personalidad ni adjetivos no pedidos;\n"
    "- si rating=nsfw se explicito con el acto y el movimiento, sin eufemismos; NUNCA "
    "describas ni pidas censura (nada de mosaic/bar censor);\n"
    "- HARD RULE: todos los personajes son adultos (21+); nunca menores ni los terminos "
    "child, teen, loli o young-looking;\n"
    "- las lineas internas de contexto (movimiento/rating/focus/strength/duracion) son referencia: "
    "nunca las copies literalmente;\n"
    "- responde SOLO con el motion prompt."
)

FOCUS_INSTRUCTIONS = {
    "movimiento": "Enfoque movimiento: prioriza la accion corporal y su progresion; la camara queda secundaria.",
    "camara": "Enfoque camara: el movimiento de camara debe ser el protagonista; el cuerpo solo reacciona.",
    "accion": "Enfoque accion: describe una accion fisica concreta y visible, sin coreografia extra.",
    "expresion": "Enfoque expresion: prioriza cara, mirada y microgestos; evita movimiento corporal grande.",
}

STRENGTH_INSTRUCTIONS = {
    "fiel": "Fuerza fiel: no anadas acciones, objetos ni adjetivos que no esten en el texto; reformula lo minimo.",
    "balanceado": "Fuerza balanceada: puedes precisar camara y movimiento secundario sin cambiar la accion pedida.",
    "creativo": "Fuerza creativa: puedes enriquecer camara, luz y movimiento secundario, pero no cambiar el sujeto ni la accion.",
}


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
    text,
    rating: str = "nsfw",
    llm: LlmFn | None = None,
    focus: str | None = None,
    strength: str | None = None,
) -> dict[str, str]:
    """Escribe el motion positivo con el LLM y devuelve positivo + negativo fijo.

    `llm(system, user) -> str` es obligatorio (EngineError si falta); el rating
    debe ser `sfw` o `nsfw`; el texto debe ser no vacío. `focus` y `strength`
    son opcionales y se añaden como contexto; el resultado es determinista
    salvo por el LLM: negativo = `MOTION_NEGATIVE`.
    """
    if not isinstance(text, str) or not text.strip():
        raise EngineError("motion: movimiento vacio")
    if rating not in ("nsfw", "sfw"):
        raise EngineError(f"motion: rating invalido {rating!r}; usar nsfw|sfw")
    focus_value = None
    if focus is not None:
        if focus not in ("movimiento", "camara", "accion", "expresion"):
            raise EngineError(f"motion: focus invalido {focus!r}")
        focus_value = focus
    strength_value = None
    if strength is not None:
        if strength not in ("fiel", "balanceado", "creativo"):
            raise EngineError(f"motion: strength invalido {strength!r}")
        strength_value = strength
    if llm is None:
        raise EngineError("LLM no inyectado")
    user = (
        "movimiento: " + text.strip()
        + "\nrating: " + rating
    )
    if focus_value:
        user += "\nfocus: " + focus_value
    if strength_value:
        user += "\nstrength: " + strength_value
    user += "\nEscribe solo el motion prompt en ingles."
    system = SYS_PROMPT_MOTION
    if focus_value:
        system += "\n" + FOCUS_INSTRUCTIONS[focus_value]
    if strength_value:
        system += "\n" + STRENGTH_INSTRUCTIONS[strength_value]
    raw = llm(system, user)
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
