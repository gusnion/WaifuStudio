"""«Mejorar prompt» (M8-20): LLM local + RAG por keywords + preprompts.

Offline y sin GPU: el LLM se INYECTA (`llm(system, user) -> str`) para tests;
`load_local_llm` es el unico camino que toca `llama_cpp` y jamas se ejecuta en
tests. El SYS_PROMPT es copia EXACTA del planner legacy certificado
(``E:\\IA\\VIDEO\\local_prompt_planner\\local_planner.py``); el RAG y el manual
salen de las mismas fuentes (``docs/prompting_anima.md``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from app.config import load_config
from app.engine import EngineError
from app.preprompts import get_preprompt

# Copia EXACTA (texto, sin reformatear) del SYS_PROMPT legacy (:69-80).
SYS_PROMPT = (
    "You are the local prompt planner for an anime image generator trained on danbooru tags.\n"
    "Output rules:\n"
    "1) Output EXACTLY ONE line of danbooru-style tags in English, separated by commas. No section labels (never write \"quality tags:\", \"rating tag:\", \"outfit/pose:\", \"art style:\"), no prose, no sentences, no explanations.\n"
    "2) Start with the subject count tags: \"1girl\" for one woman; add \"1boy\" and/or \"2girls\" etc. when the request implies other people. A sex act or sex position ALWAYS involves two people: ALWAYS include \"1boy\", \"hetero\" (or \"2girls\" when both are women) and the act tags when the user requests one.\n"
    "3) Then the content tags with danbooru vocabulary: character traits, clothing or \"nude\"/\"completely nude\", pose and, when the user requests it, the explicit act and body parts with danbooru tags (e.g. \"sex\", \"vaginal sex\", \"full nelson\"). Keep the user's intent exactly as requested; never censor, soften or replace it with euphemisms like \"seductive\", \"confident\" or \"sensual\". For nsfw content ALWAYS include the tag \"uncensored\" and NEVER include censorship tags (e.g. \"mosaic censoring\", \"bar censor\"): the image must be uncensored.\n"
    "4) Quality tags must be danbooru/anime style: \"masterpiece, best quality, very aesthetic, absurdres\". NEVER use photorealistic tags (realistic, hyper-realistic, cinematic, photo, lifelike).\n"
    "5) Include the rating as a tag: \"nsfw\" for adult content, \"sfw\" for safe content.\n"
    "6) Art style is anime illustration: use \"anime\", \"2D\", \"cel shading\" when useful; never photorealism.\n"
    "7) The user message contains internal context lines in Spanish (\"rating tag:\", \"framing:\", \"video:\"). They are reference ONLY: NEVER copy them, their words, or any translation of them into the output. The output must contain only English danbooru tags about the scene.\n"
    "8) HARD RULE: all characters are adults (21+). NEVER include minors, child/teen/loli terms, school settings, or any content implying minors."
)

# Notas de recuperacion (RAG) por keywords. Todo el contenido sale del manual
# docs/prompting_anima.md (SYS_PROMPT/NEGATIVE legacy + preprompts + guia Anima).
RAG_ENTRIES: list[dict[str, Any]] = [
    {
        "keywords": ["orden", "tags", "estructura", "calidad", "safety", "character", "general"],
        "text": (
            "Orden canonico de tags: [calidad/meta/safety] [1girl/1boy] [character] "
            "[general]. Primero calidad y safety, luego el conteo de sujetos, despues "
            "el personaje y al final ropa, pose, cuerpo y entorno."
        ),
    },
    {
        "keywords": ["calidad", "score", "score_7", "score_8", "score_9", "meta"],
        "text": (
            "Calidad con la familia score_: score_7, score_8, score_9 para calidad alta. "
            "Tags de calidad anime: masterpiece, best quality, very aesthetic, absurdres."
        ),
    },
    {
        "keywords": ["safety", "rating", "safe", "sensitive", "nsfw", "explicit"],
        "text": (
            "Safety/rating: safe, sensitive, nsfw, explicit. El planner usa nsfw para "
            "adulto y sfw para seguro; el rating va como tag, no como prosa."
        ),
    },
    {
        "keywords": ["preprompt", "glossy", "anima_default", "not_glossy", "ninguno"],
        "text": (
            "Preprompts Anima: glossy (default), anima_default, not_glossy y ninguno. "
            "El LLM no los decide: se aplican de forma determinista como prefijo del "
            "positivo y sufijo del negativo."
        ),
    },
    {
        "keywords": ["negativo", "anatomy", "anatomia", "hands", "manos", "fingers", "dedos"],
        "text": (
            "Negativo de anatomia del preprompt glossy: bad anatomy, bad hands, mutated "
            "hands, fused fingers, extra fingers, watermark, signature, logo."
        ),
    },
    {
        "keywords": ["negativo", "base", "child", "loli", "young", "mosaic", "censor", "calidad"],
        "text": (
            "Negativo base del planner: worst quality, low quality, jpeg artifacts, child, "
            "teen, loli, young-looking, blurry, mosaic censoring, bar censor."
        ),
    },
    {
        "keywords": ["artista", "artist", "estilo", "firma"],
        "text": (
            "Los tags de artista se escriben con @ (p. ej. @artist_name) y van en la zona "
            "general/estilo; el negativo glossy rechaza artist name."
        ),
    },
    {
        "keywords": ["frases", "descriptivo", "detalle", "escena", "prompt"],
        "text": (
            "Prompts descriptivos de 2+ frases: describir sujeto, accion, entorno, "
            "iluminacion y encuadre con detalle en vez de una lista minima."
        ),
    },
    {
        "keywords": ["uncensored", "censura", "mosaic", "bar", "censor"],
        "text": (
            "Anti-censura: en nsfw el positivo SIEMPRE incluye uncensored y NUNCA tags de "
            "censura (mosaic censoring, bar censor); sin bloqueos SFW."
        ),
    },
    {
        "keywords": ["espacios", "score", "separador", "comas", "underscore"],
        "text": (
            "Los tags se separan con ', '; la unica excepcion es score_X, que usa guion "
            "bajo: score_8, nunca 'score 8'."
        ),
    },
    {
        "keywords": ["fotorrealista", "photorealistic", "realistic", "cinematic", "anime", "2d"],
        "text": (
            "Nada de fotorrealismo: prohibido realistic, hyper-realistic, cinematic, photo "
            "o lifelike. El estilo es ilustracion anime (anime, 2D, cel shading)."
        ),
    },
    {
        "keywords": ["intencion", "eufemismo", "censurar", "seductive", "sensual"],
        "text": (
            "Mantener la intencion exacta del usuario: nunca censurar, suavizar ni sustituir "
            "el acto o las partes del cuerpo por eufemismos (seductive, confident, sensual)."
        ),
    },
]

DEFAULT_LLM_RELATIVE = Path(
    "models/llm/Qwen25-7B-abliterated/"
    "Josiefied-Qwen2.5-7B-Instruct-abliterated.Q3_K_M.gguf"
)

LlmFn = Callable[[str, str], str]


def _tokens(text: Any) -> set[str]:
    """Tokens alfanumericos en minusculas (score_9 -> {score, 9})."""
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))


def retrieve(query: str, k: int = 3) -> list[str]:
    """Textos RAG ordenados por solape de keywords (score desc, orden estable).

    Query vacia o sin tokens, o `k <= 0` -> []. Solo entran entradas con score > 0.
    """
    if k <= 0:
        return []
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    scored: list[tuple[int, int, str]] = []
    for index, entry in enumerate(RAG_ENTRIES):
        entry_tokens: set[str] = set()
        for keyword in entry["keywords"]:
            entry_tokens |= _tokens(keyword)
        score = len(query_tokens & entry_tokens)
        if score > 0:
            scored.append((score, index, entry["text"]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [text for _score, _index, text in scored[:k]]


def _dedup_tags(parts: list[str]) -> str:
    """Une fragmentos con ', ' deduplicando case-insensitive; manda la 1a aparicion."""
    seen: set[str] = set()
    merged: list[str] = []
    for part in parts:
        for tag in str(part or "").split(","):
            tag = tag.strip()
            if not tag:
                continue
            folded = tag.lower()
            if folded not in seen:
                seen.add(folded)
                merged.append(tag)
    return ", ".join(merged)


def apply_preprompt(
    text: str, family: str = "anima", name: str = "glossy"
) -> tuple[str, str]:
    """Aplica el preprompt: positivo = prefijo + texto; negativo = sufijo; dedup CI.

    Determinista; usa `app.preprompts.get_preprompt` (EngineError si no existe).
    """
    preprompt = get_preprompt(family, name)
    positive = _dedup_tags([preprompt["positive"], text])
    negative = _dedup_tags([preprompt["negative"]])
    return positive, negative


def enhance(
    user_text: str,
    *,
    family: str = "anima",
    preprompt: str = "glossy",
    rating: str | None = None,
    llm: LlmFn | None = None,
    k: int = 3,
) -> dict[str, str]:
    """Construye mensajes (SYS_PROMPT + texto + notas RAG + rating) y aplica preprompt.

    Sin censurar ni forzar el rating: si viene, se anade como linea de contexto.
    Sin `llm` inyectado lanza EngineError.
    """
    text = user_text.strip() if isinstance(user_text, str) else ""
    if not text:
        raise EngineError("enhance: user_text vacio")
    if llm is None:
        raise EngineError("LLM no inyectado")
    lines = [text]
    if rating:
        lines.append(f"rating tag: {rating}")
    notes = retrieve(text, k=k)
    if notes:
        lines.append("Notas de referencia (no copiar a la salida):")
        lines.extend(f"- {note}" for note in notes)
    user = "\n".join(lines)
    raw = llm(SYS_PROMPT, user)
    if not isinstance(raw, str):
        raise EngineError("enhance: el LLM no devolvio texto")
    positive, negative = apply_preprompt(raw, family=family, name=preprompt)
    return {"positive": positive, "negative": negative, "raw": raw}


def load_local_llm(model_path: str | Path | None = None):
    """Carga el GGUF local en CPU (n_gpu_layers=0, n_ctx=2048, verbose=False).

    Import perezoso de llama_cpp; EngineError si falta el archivo. No usar en tests.
    """
    path = (
        Path(model_path)
        if model_path is not None
        else load_config().comfy_root / DEFAULT_LLM_RELATIVE
    )
    if not path.is_file():
        raise EngineError(f"modelo LLM local no encontrado: {path}")
    from llama_cpp import Llama

    return Llama(model_path=str(path), n_ctx=2048, n_gpu_layers=0, verbose=False)


__all__ = [
    "DEFAULT_LLM_RELATIVE",
    "RAG_ENTRIES",
    "SYS_PROMPT",
    "apply_preprompt",
    "enhance",
    "load_local_llm",
    "retrieve",
]
