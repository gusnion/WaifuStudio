"""Prompt de video H3 escrito por el LLM local (M10-4e).

Igual que `app.motion` pero para MiniMax H3 (FL2VA): el LLM INYECTADO
(`llm(system, user) -> str`) escribe los tres bloques del prompt
(`integrated_multimodal_description`, `overall_soundscape`,
`non_diegetic_music`) a partir de una descripcion en lenguaje natural.
El loader real se reutiliza de `app.enhancer.load_local_llm` y jamas se
ejecuta en tests.
"""

from __future__ import annotations

from typing import Any, Callable

from app.engine import EngineError
from app.enhancer import load_local_llm

LlmFn = Callable[[str, Any], str]

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

SYS_PROMPT_H3_VISION = (
    "Eres el escritor de prompts del generador de video anime MiniMax H3 (FL2VA) local.\n"
    "Recibes el primer fotograma provisto, una descripcion en lenguaje natural (espanol) y el rating activo.\n"
    "Analiza el primer fotograma provisto (sujeto, vestimenta, cabello, rasgos faciales, pose, entorno y estilo) "
    "para que los tres bloques de H3 (integrated_multimodal_description, overall_soundscape, non_diegetic_music) "
    "describan y continuen con maxima fidelidad la escena y el personaje de esa imagen de partida.\n"
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


SYS_PROMPT_H3_REF2VA = (
    "Eres el escritor de prompts del generador de video anime MiniMax H3 (Ref2VA / R2V) local.\n"
    "Recibes imagenes de referencia del personaje, una descripcion en lenguaje natural (espanol) y el rating activo.\n"
    "Analiza minuciosamente los rasgos visuales, ropa, colores y estilo de las imagenes de referencia del personaje "
    "para redactar los tres bloques de H3 (integrated_multimodal_description, overall_soundscape, non_diegetic_music) "
    "describiendo una escena dinamica que preserve fielmente la identidad del personaje sin imponer una pose inicial fija.\n"
    "En 'integrated_multimodal_description', referencia las caracteristicas del personaje o elementos visuales "
    "usando las etiquetas correspondientes <Picture 1>, <Picture 2>, etc. para ligar la identidad de cada referencia.\n"
    "Devuelve EXACTAMENTE tres bloques, uno por linea y en este orden, sin preambulo, "
    "sin comillas y sin explicaciones:\n"
    "integrated_multimodal_description: <sujeto referenciando <Picture 1> etc., vestuario, entorno, luz, camara y movimiento continuo sin cortes>\n"
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


def _clean_b64(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    val = raw.strip()
    if not val:
        return None
    if "," in val:
        val = val.split(",", 1)[1].strip()
    return val or None


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
    text,
    rating: str = "nsfw",
    llm: LlmFn | None = None,
    image_b64: str | None = None,
    images_b64: list[str] | None = None,
) -> dict[str, str]:
    """Escribe el prompt H3 (tres bloques) con el LLM y lo devuelve limpio.

    `llm(system, user) -> str` es obligatorio (EngineError si falta); el rating
    debe ser `sfw` o `nsfw`; el texto debe ser no vacio. Si se recibe `images_b64`
    (o múltiples referencias) o `image_b64`, envia un payload multimodal compatible
    con OpenAI pidiendo al VLM analizar las referencias del personaje o el primer fotograma
    para continuar la escena con maxima fidelidad. La respuesta es `{"h3_prompt": <tres bloques>}`.
    """
    if not isinstance(text, str) or not text.strip():
        raise EngineError("h3_prompt: escena vacia")
    if rating not in ("nsfw", "sfw"):
        raise EngineError(f"h3_prompt: rating invalido {rating!r}; usar nsfw|sfw")
    if llm is None:
        raise EngineError("LLM no inyectado")

    valid_b64s: list[str] = []
    is_multi_ref = False
    if images_b64 is not None and isinstance(images_b64, list):
        for raw_img in images_b64:
            c = _clean_b64(raw_img)
            if c:
                valid_b64s.append(c)
        if valid_b64s:
            is_multi_ref = True
    elif image_b64:
        c = _clean_b64(image_b64)
        if c:
            valid_b64s.append(c)

    if is_multi_ref:
        user_prompt_text = (
            "Analiza los rasgos visuales, ropa, colores y estilo de las imágenes de referencia del personaje "
            "para que los tres bloques de H3 (integrated_multimodal_description, overall_soundscape, non_diegetic_music) "
            "describan una escena dinámica que preserve fielmente la identidad del personaje sin imponer una pose inicial fija.\n"
            "escena: " + text.strip()
            + "\nrating: " + rating
            + "\nDevuelve solo los tres bloques del prompt H3."
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt_text}]
        for b64 in valid_b64s:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        user: Any = content
        system = SYS_PROMPT_H3_REF2VA
    elif valid_b64s:
        user_prompt_text = (
            "Analiza el primer fotograma provisto (sujeto, vestimenta, cabello, rasgos faciales, pose, entorno y estilo) "
            "para que los tres bloques de H3 (integrated_multimodal_description, overall_soundscape, non_diegetic_music) "
            "describan y continuen con maxima fidelidad la escena y el personaje de esa imagen de partida.\n"
            "escena: " + text.strip()
            + "\nrating: " + rating
            + "\nDevuelve solo los tres bloques del prompt H3."
        )
        content = [{"type": "text", "text": user_prompt_text}]
        for b64 in valid_b64s:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        user = content
        system = SYS_PROMPT_H3_VISION
    else:
        user = (
            "escena: " + text.strip()
            + "\nrating: " + rating
            + "\nDevuelve solo los tres bloques del prompt H3."
        )
        system = SYS_PROMPT_H3

    raw = llm(system, user)
    if not isinstance(raw, str):
        raise EngineError("h3_prompt: el LLM no devolvio texto")
    return {"h3_prompt": clean_h3_prompt(raw)}


__all__ = [
    "H3_BLOCKS",
    "SYS_PROMPT_H3",
    "SYS_PROMPT_H3_REF2VA",
    "SYS_PROMPT_H3_VISION",
    "clean_h3_prompt",
    "load_local_llm",
    "write_h3_prompt",
]

