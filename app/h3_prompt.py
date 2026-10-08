"""Prompt de video H3 escrito por el LLM local (M10-4e).

Igual que `app.motion` pero para MiniMax H3 (FL2VA): el LLM INYECTADO
(`llm(system, user) -> str`) escribe los tres bloques del prompt
(`integrated_multimodal_description`, `overall_soundscape`,
`non_diegetic_music`) a partir de una descripcion en lenguaje natural.
El loader real se reutiliza de `app.enhancer.load_local_llm` y jamas se
ejecuta en tests.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from app.engine import EngineError
from app.enhancer import load_local_llm

LlmFn = Callable[[str, Any], str]

H3_BLOCKS = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)

H3_STRENGTH_PRESETS: dict[str, dict[str, Any]] = {
    "fiel": {
        "temperature": 0.3,
        "instruction": (
            "FIDELIDAD ESTRICTA: Cinete estrictamente a lo solicitado y a la imagen/referencias provistas. "
            "No agregues personajes, objetos o cambios de escenario no pedidos."
        ),
    },
    "balanceado": {
        "temperature": 0.7,
        "instruction": (
            "BALANCEADO: Preserva la identidad y la accion pedida, enriqueciendo con iluminacion cinematografica anime, "
            "movimiento fluido de camara y ambientacion sonora foley organica."
        ),
    },
    "creativo": {
        "temperature": 0.95,
        "instruction": (
            "CREATIVO: Enriquece matices atmosfericos, movimiento cinematico dinamico y profundidad auditiva, "
            "manteniendo siempre la identidad del personaje y la accion central pedida."
        ),
    },
}
DEFAULT_H3_STRENGTH = "balanceado"

SYS_PROMPT_H3 = (
    "Eres el escritor de prompts del generador de video anime MiniMax H3 (FL2VA) local.\n"
    "Recibes la descripcion de la escena en lenguaje natural (habitualmente en espanol) y el rating activo.\n"
    "REGLA DE IDIOMA MANDATORIA: Los tres bloques DEBEN escribirse SIEMPRE EN INGLES CINEMATOGRAFICO "
    "TECNICO PROFESIONAL (anime cinematography standard), sin importar el idioma de entrada. "
    "NUNCA escribas la descripcion visual en espanol. (El dialogo dentro de <d>[Language] ...</d> "
    "puede conservar el idioma especificado si aplica).\n"
    "REGLA DE FIDELIDAD ESTRICTA: Apegarse estrictamente a lo pedido por el usuario. "
    "Prohibido inventar personajes adicionales, objetos no solicitados o cambios drasticos de entorno.\n"
    "Devuelve EXACTAMENTE tres bloques, uno por linea y en este orden, sin preambulo, "
    "sin comillas, sin vinetas y sin explicaciones:\n"
    "integrated_multimodal_description: <sujeto, vestuario, entorno, luz, camara y "
    "movimiento restringido; una sola toma continua, sin cortes>\n"
    "overall_soundscape: <ambiente y efectos foley; dialogo solo si aplica>\n"
    "non_diegetic_music: <musica o None>\n"
    "- el dialogo va con idioma explicito: <d>[Language] texto</d>, con un speaker id "
    "estable declarado antes de las voces (p. ej. speaker_1) y sin llenar mas de ~2/3 "
    "de su plano;\n"
    "- si rating=nsfw se explicito con el acto y el movimiento, sin eufemismos; NUNCA "
    "describas ni pidas censura (nada de mosaic/bar censor);\n"
    "- HARD RULE: todos los personajes son adultos (21+); nunca menores ni los terminos "
    "child, teen, loli o young-looking;\n"
    "- las lineas internas de contexto (escena/rating/modo) son referencia: nunca las copies "
    "literalmente;\n"
    "- responde SOLO con los tres bloques."
)

SYS_PROMPT_H3_VISION = (
    "Eres el escritor de prompts del generador de video anime MiniMax H3 (FL2VA) local.\n"
    "Recibes el primer fotograma provisto, una descripcion en lenguaje natural y el rating activo.\n"
    "REGLA DE IDIOMA MANDATORIA: Los tres bloques DEBEN escribirse SIEMPRE EN INGLES CINEMATOGRAFICO "
    "TECNICO PROFESIONAL (anime cinematography standard), sin importar el idioma de entrada. "
    "NUNCA escribas la descripcion visual en espanol. (El dialogo dentro de <d>[Language] ...</d> "
    "puede conservar el idioma especificado si aplica).\n"
    "REGLA DE VISION Y FIDELIDAD: Analiza el primer fotograma provisto (sujeto, vestimenta, cabello, "
    "rasgos faciales, pose, entorno y estilo) para que los tres bloques continuen con MAXIMA FIDELIDAD "
    "la escena y el personaje de esa imagen de partida. Prohibido alucinar personajes nuevos, cambiar "
    "el vestuario o sustituir el entorno salvo que el usuario lo pida explicitamente.\n"
    "Devuelve EXACTAMENTE tres bloques, uno por linea y en este orden, sin preambulo, "
    "sin comillas, sin vinetas y sin explicaciones:\n"
    "integrated_multimodal_description: <sujeto, vestuario, entorno, luz, camara y "
    "movimiento restringido; una sola toma continua, sin cortes>\n"
    "overall_soundscape: <ambiente y efectos foley; dialogo solo si aplica>\n"
    "non_diegetic_music: <musica o None>\n"
    "- el dialogo va con idioma explicito: <d>[Language] texto</d>, con un speaker id "
    "estable declarado antes de las voces (p. ej. speaker_1) y sin llenar mas de ~2/3 "
    "de su plano;\n"
    "- si rating=nsfw se explicito con el acto y el movimiento, sin eufemismos; NUNCA "
    "describas ni pidas censura (nada de mosaic/bar censor);\n"
    "- HARD RULE: todos los personajes son adultos (21+); nunca menores ni los terminos "
    "child, teen, loli o young-looking;\n"
    "- las lineas internas de contexto (escena/rating/modo) son referencia: nunca las copies "
    "literalmente;\n"
    "- responde SOLO con los tres bloques."
)


SYS_PROMPT_H3_REF2VA = (
    "Eres el escritor de prompts del generador de video anime MiniMax H3 (Ref2VA / R2V) local.\n"
    "Recibes imagenes de referencia del personaje, una descripcion en lenguaje natural y el rating activo.\n"
    "REGLA DE IDIOMA MANDATORIA: Los tres bloques DEBEN escribirse SIEMPRE EN INGLES CINEMATOGRAFICO "
    "TECNICO PROFESIONAL (anime cinematography standard), sin importar el idioma de entrada. "
    "NUNCA escribas la descripcion visual en espanol. (El dialogo dentro de <d>[Language] ...</d> "
    "puede conservar el idioma especificado si aplica).\n"
    "REGLA DE IDENTIDAD Y REFERENCIA: Analiza minuciosamente los rasgos visuales, ropa, colores y estilo "
    "de las imagenes de referencia del personaje para redactar los tres bloques describiendo una escena dinamica "
    "que preserve fielmente la identidad del personaje sin imponer una pose inicial fija.\n"
    "En 'integrated_multimodal_description', referencia las caracteristicas del personaje o elementos visuales "
    "usando las etiquetas correspondientes <Picture 1>, <Picture 2>, etc. para ligar la identidad de cada referencia.\n"
    "Devuelve EXACTAMENTE tres bloques, uno por linea y en este orden, sin preambulo, "
    "sin comillas, sin vinetas y sin explicaciones:\n"
    "integrated_multimodal_description: <sujeto referenciando <Picture 1> etc., vestuario, entorno, luz, camara y movimiento continuo sin cortes>\n"
    "overall_soundscape: <ambiente y efectos foley; dialogo solo si aplica>\n"
    "non_diegetic_music: <musica o None>\n"
    "- el dialogo va con idioma explicito: <d>[Language] texto</d>, con un speaker id "
    "estable declarado antes de las voces (p. ej. speaker_1) y sin llenar mas de ~2/3 "
    "de su plano;\n"
    "- si rating=nsfw se explicito con el acto y el movimiento, sin eufemismos; NUNCA "
    "describas ni pidas censura (nada de mosaic/bar censor);\n"
    "- HARD RULE: todos los personajes son adultos (21+); nunca menores ni los terminos "
    "child, teen, loli o young-looking;\n"
    "- las lineas internas de contexto (escena/rating/modo) son referencia: nunca las copies "
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

    # Normalizar negritas o marcadores markdown que el LLM a veces inserta antes de los bloques:
    # Ej: **integrated_multimodal_description:** o - overall_soundscape:
    cleaned = re.sub(
        r"(?im)^[\s*\-#]*\**\s*(integrated_multimodal_description|overall_soundscape|non_diegetic_music)\s*(?::\**|\**\s*:)",
        r"\1:",
        cleaned,
    )
    cleaned = re.sub(
        r"(?im)^[\s*\-#]*\**\s*non-diegetic_music\s*(?::\**|\**\s*:)",
        "non_diegetic_music:",
        cleaned,
    )

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
    strength: str = DEFAULT_H3_STRENGTH,
) -> dict[str, str]:
    """Escribe el prompt H3 (tres bloques) con el LLM y lo devuelve limpio.

    `llm(system, user) -> str` es obligatorio (EngineError si falta); el rating
    debe ser `sfw` o `nsfw`; `strength` debe ser `fiel|balanceado|creativo`.
    Si se recibe `images_b64` (o múltiples referencias) o `image_b64`, envia un payload
    multimodal compatible con OpenAI pidiendo al VLM analizar las referencias del personaje
    o el primer fotograma para continuar la escena con maxima fidelidad.
    La respuesta es `{"h3_prompt": <tres bloques>}`.
    """
    if not isinstance(text, str) or not text.strip():
        raise EngineError("h3_prompt: escena vacia")
    if rating not in ("nsfw", "sfw"):
        raise EngineError(f"h3_prompt: rating invalido {rating!r}; usar nsfw|sfw")
    if not strength or strength not in H3_STRENGTH_PRESETS:
        raise EngineError(
            f"h3_prompt: strength invalido {strength!r}; usar fiel|balanceado|creativo"
        )
    if llm is None:
        raise EngineError("LLM no inyectado")

    preset = H3_STRENGTH_PRESETS[strength]

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
            "describan una escena dinámica en INGLÉS que preserve fielmente la identidad del personaje sin imponer una pose inicial fija.\n"
            f"Modo: {strength} ({preset['instruction']})\n"
            "escena: " + text.strip()
            + "\nrating: " + rating
            + "\nDevuelve solo los tres bloques del prompt H3 en inglés."
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
            "describan y continúen con máxima fidelidad la escena y el personaje en INGLÉS.\n"
            f"Modo: {strength} ({preset['instruction']})\n"
            "escena: " + text.strip()
            + "\nrating: " + rating
            + "\nDevuelve solo los tres bloques del prompt H3 en inglés."
        )
        content = [{"type": "text", "text": user_prompt_text}]
        for b64 in valid_b64s:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        user = content
        system = SYS_PROMPT_H3_VISION
    else:
        user = (
            f"Modo: {strength} ({preset['instruction']})\n"
            "escena: " + text.strip()
            + "\nrating: " + rating
            + "\nDevuelve solo los tres bloques del prompt H3 en inglés."
        )
        system = SYS_PROMPT_H3

    try:
        raw = llm(system, user, max_tokens=512, temperature=preset["temperature"])
    except TypeError:
        try:
            raw = llm(system, user, max_tokens=512)
        except TypeError:
            raw = llm(system, user)
    if not isinstance(raw, str):
        raise EngineError("h3_prompt: el LLM no devolvio texto")

    # Si el LLM genero la descripcion visual y sonido pero omitio el bloque de musica,
    # completar con el default oficial 'None' para no fallar la peticion al usuario
    if "integrated_multimodal_description" in raw:
        if "overall_soundscape" not in raw:
            raw = raw.rstrip() + "\noverall_soundscape: Quiet environment ambience and subtle clothing movement. No dialogue."
        if "non_diegetic_music" not in raw and "non-diegetic" not in raw:
            raw = raw.rstrip() + "\nnon_diegetic_music: None"

    return {"h3_prompt": clean_h3_prompt(raw)}


__all__ = [
    "DEFAULT_H3_STRENGTH",
    "H3_BLOCKS",
    "H3_STRENGTH_PRESETS",
    "SYS_PROMPT_H3",
    "SYS_PROMPT_H3_REF2VA",
    "SYS_PROMPT_H3_VISION",
    "clean_h3_prompt",
    "load_local_llm",
    "write_h3_prompt",
]

