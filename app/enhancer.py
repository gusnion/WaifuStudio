"""«Mejorar prompt» (M8-20): LLM local + RAG por keywords + preprompts.

Offline y sin GPU: el LLM se INYECTA (`llm(system, user) -> str`) para tests;
`load_local_llm` es el unico camino que toca `llama_cpp` y jamas se ejecuta en
tests; `load_server_llm` habla con un `llama-server` OpenAI-compatible y su
transporte es inyectable (`_http_transport` es el unico camino que abre
sockets). El SYS_PROMPT y `BASE_NEGATIVE` (negativo base: calidad + anti-menores +
anti-censura) son copias EXACTAS del planner legacy certificado (retirado el
2026-09-26; archivado en ``data\\gates\\m10\\evidencia-legacy``, fuera de git);
el RAG y el manual salen de las mismas fuentes (``docs/prompting_anima.md``). El negativo final es
SIEMPRE `BASE_NEGATIVE` + negativo del preprompt, con dedup case-insensitive.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from app import tags as tag_catalog
from app.config import load_config
from app.engine import EngineError
from app.preprompts import get_preprompt
from app.prompt_zones import (
    QUALITY_OPTIONS,
    SAFETY_OPTIONS,
    SUBJECT_OPTIONS,
    canonical_order,
)

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

# Copia EXACTA (texto, sin reformatear) de NEGATIVE del planner legacy (:41-44):
# negativo base de calidad + anti-menores + anti-censura, sin bloqueos SFW.
BASE_NEGATIVE = (
    "worst quality, low quality, jpeg artifacts, child, teen, loli, young-looking, "
    "blurry, mosaic censoring, bar censor"
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

# Servidor LLM opcional (M11-2F): `llama-server` OpenAI-compatible. Si
# `WAIFU_LLM_URL` esta definido y no vacio, la app lo usa; si no, sigue el
# camino local de `load_local_llm` (llama-cpp en CPU).
LLM_URL_ENV = "WAIFU_LLM_URL"
LLM_TIMEOUT_ENV = "WAIFU_LLM_TIMEOUT"
DEFAULT_LLM_URL = "http://127.0.0.1:8290"
DEFAULT_LLM_TIMEOUT = 120.0
LLM_USER_AGENT = "WAIFU-LLM/1.0 (local)"
Transport = Callable[[str, dict[str, Any] | None, float], dict[str, Any]]

# Fuerzas del mejorador (M9-A1): temperatura del LLM, notas RAG (`k`) e
# instruccion extra del mensaje de usuario. `balanceado` no anade instruccion.
STRENGTH_PRESETS: dict[str, dict[str, Any]] = {
    "fiel": {
        "temperature": 0.4,
        "k": 1,
        "instruction": (
            "Mantén exactamente lo pedido; no añadas elementos que el usuario "
            "no haya pedido."
        ),
    },
    "balanceado": {"temperature": 0.7, "k": 3, "instruction": ""},
    "creativo": {
        "temperature": 1.0,
        "k": 6,
        "instruction": (
            "Enriquece con detalles coherentes (pose, expresión, luz, fondo) "
            "sin contradecir lo pedido."
        ),
    },
}
DEFAULT_STRENGTH_PRESET = "balanceado"

SCORE_TAG_RE = re.compile(r"^score_\d+$", re.IGNORECASE)
WEIGHTED_TAG_RE = re.compile(r"^\((.+):([0-9]*\.?[0-9]+)\)$")
VOCAB_TAGS_K = 60
_OPTION_VOCAB: dict[str, tuple[str, ...]] = {
    "quality": QUALITY_OPTIONS,
    "safety": SAFETY_OPTIONS,
    "subject": SUBJECT_OPTIONS,
}
RATING_RULES: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {
    "nsfw": (("nsfw", "uncensored"), frozenset({"sfw"})),
    "sfw": (("sfw",), frozenset({"nsfw", "uncensored"})),
}


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


def _normalize_tag(tag: str) -> str:
    """`_` -> espacio salvo en `score_<N>`, que conserva el guion bajo."""
    if SCORE_TAG_RE.match(tag):
        return tag
    return tag.replace("_", " ")


def _normalize_tags(text: str) -> str:
    """Normaliza la lista de tags del LLM: `coastal_city` -> `coastal city`, `score_9` intacto."""
    return ", ".join(
        _normalize_tag(tag.strip()) for tag in str(text).split(",") if tag.strip()
    )


def _vocabulary(user_text: str, zone_hint: str | None) -> list[str]:
    """Vocabulario restringido de la zona pedida: opciones curadas o retrieve FTS5.

    `quality`/`safety`/`subject` devuelven las opciones curadas completas;
    `character`/`general` recuperan del catalogo por la zona; `None`, vacio u
    otro valor recuperan sin filtro de zona. `user_text` guia la recuperacion.
    """
    zone = zone_hint.strip() if isinstance(zone_hint, str) else None
    options = _OPTION_VOCAB.get(zone) if zone else None
    if options is not None:
        return list(options)
    if zone in ("character", "general"):
        return tag_catalog.retrieve(user_text, zone=zone, k=VOCAB_TAGS_K)
    return tag_catalog.retrieve(user_text, zone=None, k=VOCAB_TAGS_K)


def _validate_tags(text: str) -> tuple[str, list[str]]:
    """Valida fragmentos con `tag_catalog.resolve` y devuelve `(texto, dropped)`.

    Cada fragmento (separado por coma) se resuelve a su forma canonica de
    display; soporta pesos `(tag:1.2)` conservando envoltorio y peso. Si el
    nucleo ya es canonico (case-insensitive) se conserva el fragmento original
    tal cual; si es alias/forma distinta se sustituye el nucleo por el canonico.
    Los fragmentos sin resolucion (`resolve` -> None) van a `dropped` con su
    texto tal cual (strip) y no entran. Dedup case-insensitive del fragmento
    final conservando la 1a aparicion; los fragmentos vacios se ignoran.
    """
    fragments: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for part in str(text).split(","):
        fragment = part.strip()
        if not fragment:
            continue
        match = WEIGHTED_TAG_RE.match(fragment)
        if match is not None:
            core, weight = match.group(1), match.group(2)
        else:
            core, weight = fragment, None
        canonical = tag_catalog.resolve(core)
        if canonical is None:
            dropped.append(fragment)
            continue
        if core.strip().lower() == canonical.lower():
            final = fragment
        elif weight is not None:
            final = f"({canonical}:{weight})"
        else:
            final = canonical
        folded = final.lower()
        if folded in seen:
            continue
        seen.add(folded)
        fragments.append(final)
    return ", ".join(fragments), dropped


def _enforce_rating(text: str, rating: str | None) -> str:
    """Fuerza el rating pedido sobre los tags, case-insensitive y sin duplicar.

    `nsfw` garantiza `nsfw` y `uncensored` y elimina `sfw`; `sfw` garantiza `sfw`
    y elimina `nsfw`/`uncensored`; cualquier otro valor (p. ej. `None`) no toca el
    rating. La eliminacion y la deteccion de requeridos miran el nucleo del
    fragmento (soporta pesos `(tag:1.2)`): un `(sfw:0.9)` cae con `nsfw` y un
    `(uncensored:1.1)` ya cuenta como presente. Los tags repetidos del LLM se
    deduplican conservando la 1a aparicion, el texto conservado es el fragmento
    original tal cual y los que faltan se anaden al final, en el orden de la regla.
    """
    rule = RATING_RULES.get(rating) if isinstance(rating, str) else None
    if rule is None:
        return text
    required, removed = rule
    kept: list[str] = []
    seen: set[str] = set()
    present: set[str] = set()
    for raw_tag in str(text).split(","):
        tag = raw_tag.strip()
        if not tag:
            continue
        match = WEIGHTED_TAG_RE.match(tag)
        core = match.group(1).strip().lower() if match is not None else tag.lower()
        if core in removed or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        present.add(core)
        kept.append(tag)
    for tag in required:
        if tag not in present:
            kept.append(tag)
            present.add(tag)
            seen.add(tag)
    return ", ".join(kept)


def apply_preprompt(
    text: str, family: str = "anima", name: str = "glossy"
) -> tuple[str, str]:
    """Aplica el preprompt: positivo = prefijo + texto; negativo = base + sufijo.

    El negativo devuelto es SIEMPRE `BASE_NEGATIVE` (calidad + anti-menores +
    anti-censura) seguido del negativo del preprompt, unidos con dedup
    case-insensitive que conserva la primera aparicion (sin duplicar terminos).
    Determinista; usa `app.preprompts.get_preprompt` (EngineError si no existe).
    """
    preprompt = get_preprompt(family, name)
    positive = _dedup_tags([preprompt["positive"], text])
    negative = _dedup_tags([BASE_NEGATIVE, preprompt["negative"]])
    return positive, negative


def enhance(
    user_text: str,
    *,
    family: str = "anima",
    preprompt: str = "glossy",
    rating: str | None = None,
    llm: LlmFn | None = None,
    k: int | None = None,
    strength: str = DEFAULT_STRENGTH_PRESET,
    zone_hint: str | None = None,
    context_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Construye mensajes (SYS_PROMPT + texto + notas RAG + rating) y aplica preprompt.

    `strength` (``fiel|balanceado|creativo``, default ``balanceado``) elige la
    temperatura del LLM, las notas RAG (`k`; un `k` explicito manda) y la
    instruccion anadida al mensaje de usuario si no esta vacia. La temperatura
    se pasa al `llm` como kwarg; si el callable no lo acepta (TypeError) se
    reintenta sin el. Antes del preprompt, el texto del LLM se normaliza (en
    cada tag `_` -> espacio, salvo `score_<N>`, que queda intacto) y se fuerza
    el rating pedido: `nsfw` garantiza `nsfw` y `uncensored` y elimina `sfw`;
    `sfw` garantiza `sfw` y elimina `nsfw`/`uncensored`; `rating=None` no toca
    el rating. El forzado es case-insensitive, deduplica tags repetidos y no
    anade duplicados. `zone_hint` (opcional, p. ej. `quality|safety|subject|
    character|general`) anade al mensaje de usuario la linea interna
    ``Zona objetivo: <zone>. Coloca sólo etiquetas de esa zona; si algo no
    pertenece, omítelo.``; `None` o cadena vacia no anaden nada y dejan la
    salida identica al comportamiento previo. El positivo devuelto pasa por
    `app.prompt_zones.canonical_order` DESPUES de componer el preprompt
    (calidad/meta primero y general por subcategorias); el negativo devuelto es
    el compuesto de `apply_preprompt` (`BASE_NEGATIVE` + preprompt, dedup
    case-insensitive) y no se reordena. El mensaje de usuario incluye, si la
    hay, una linea con el vocabulario restringido de la zona (`zone_hint`:
    opciones curadas completas en quality/safety/subject y recuperacion del
    catalogo en character/general/sin zona). Tras normalizar, los tags del LLM
    pasan por `_validate_tags`: los no resolubles por el catalogo se descartan
    y se devuelven en `dropped` (lista de str) sin entrar en `raw`; los alias
    se sustituyen por su forma canonica y los pesos `(tag:1.2)` se conservan.
    Sin `llm` inyectado o con `strength` desconocido lanza EngineError.
    """
    text = user_text.strip() if isinstance(user_text, str) else ""
    if not text:
        raise EngineError("enhance: user_text vacio")
    preset = STRENGTH_PRESETS.get(strength) if isinstance(strength, str) else None
    if preset is None:
        raise EngineError(f"strength de mejora desconocido: {strength!r}")
    if llm is None:
        raise EngineError("LLM no inyectado")
    lines = [text]
    if rating:
        lines.append(f"rating tag: {rating}")
    if isinstance(zone_hint, str) and zone_hint.strip():
        lines.append(
            f"Zona objetivo: {zone_hint.strip()}. Coloca sólo etiquetas de esa zona; "
            "si algo no pertenece, omítelo."
        )
    if context_tags is not None:
        if not isinstance(context_tags, list) or any(
            not isinstance(tag, str) for tag in context_tags
        ):
            raise EngineError("enhance: context_tags debe ser lista de strings")
        seen_tags: set[str] = set()
        clean_tags: list[str] = []
        for tag in context_tags:
            spaced = " ".join(tag.split())
            folded = spaced.lower()
            if not folded or folded in seen_tags:
                continue
            seen_tags.add(folded)
            clean_tags.append(spaced)
            if len(clean_tags) >= 120:
                break
        if clean_tags:
            lines.append(
                "Tags ya aplicadas (NO las repitas en la salida): "
                + ", ".join(clean_tags)
            )
    lines.append(
        "Instrucciones de tags: convierte cada concepto en etiquetas danbooru canónicas "
        "en inglés, en minúsculas y separadas por comas; usa el nombre exacto del tag "
        "cuando exista (p. ej. 'pelo largo al viento' -> long hair, wind); añade solo "
        "etiquetas nuevas, sin frases ni traducciones."
    )
    vocabulary = _vocabulary(text, zone_hint)
    if vocabulary:
        lines.append(
            "Vocabulario de etiquetas (usa SOLO etiquetas de esta lista cuando exista "
            "una equivalente): " + ", ".join(vocabulary)
        )
    if preset["instruction"]:
        lines.append(f"instruccion: {preset['instruction']}")
    notes = retrieve(text, k=preset["k"] if k is None else k)
    if notes:
        lines.append("Notas de referencia (no copiar a la salida):")
        lines.extend(f"- {note}" for note in notes)
    user = "\n".join(lines)
    try:
        raw = llm(SYS_PROMPT, user, temperature=preset["temperature"])
    except TypeError:
        raw = llm(SYS_PROMPT, user)
    if not isinstance(raw, str):
        raise EngineError("enhance: el LLM no devolvio texto")
    validated, dropped = _validate_tags(_normalize_tags(raw))
    prepared = _enforce_rating(validated, rating)
    positive, negative = apply_preprompt(prepared, family=family, name=preprompt)
    positive = canonical_order(positive)
    return {
        "positive": positive,
        "negative": negative,
        "raw": prepared,
        "dropped": dropped,
    }


def load_local_llm(
    model_path: str | Path | None = None,
    *,
    max_tokens: int = 192,
    temperature: float = 0.7,
) -> LlmFn:
    """Carga el GGUF local en CPU y devuelve `llm(system, user, temperature=None) -> str`.

    `n_gpu_layers=0`, `n_ctx=2048`, `verbose=False`; el callable acepta una
    `temperature` por llamada (override del default del cierre) y usa
    `Llama.create_chat_completion(messages=[system, user], max_tokens=...,
    temperature=...)`; exige contenido de texto no vacio en
    `choices[0]["message"]["content"]` (si no, `EngineError("LLM sin contenido")`).
    Import perezoso de llama_cpp; EngineError si falta el archivo (antes de
    importar). No usar en tests.
    """
    path = (
        Path(model_path)
        if model_path is not None
        else load_config().comfy_root / DEFAULT_LLM_RELATIVE
    )
    if not path.is_file():
        raise EngineError(f"modelo LLM local no encontrado: {path}")
    from llama_cpp import Llama

    llama = Llama(model_path=str(path), n_ctx=2048, n_gpu_layers=0, verbose=False)
    default_temperature = temperature

    def llm(system: str, user: str, temperature: float | None = None) -> str:
        response = llama.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=(
                temperature if temperature is not None else default_temperature
            ),
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str) or not content.strip():
            raise EngineError("LLM sin contenido")
        return content

    return llm


def _resolve_base_url(base_url: str | None = None) -> str:
    """Base del servidor LLM: parametro, `WAIFU_LLM_URL` o default, sin '/' final."""
    base = base_url or os.environ.get(LLM_URL_ENV, "").strip() or DEFAULT_LLM_URL
    return str(base).strip().rstrip("/")


def _resolve_timeout(timeout: float | None = None) -> float:
    """Timeout del servidor en segundos: parametro, `WAIFU_LLM_TIMEOUT` o 120.0.

    El parametro explicito siempre manda; sin el, `WAIFU_LLM_TIMEOUT` se parsea
    como float y un valor vacio o no parseable cae al default.
    """
    if timeout is not None:
        return timeout
    text = os.environ.get(LLM_TIMEOUT_ENV, "").strip()
    if text:
        try:
            return float(text)
        except ValueError:
            return DEFAULT_LLM_TIMEOUT
    return DEFAULT_LLM_TIMEOUT


def _http_transport(url: str, payload: dict | None, timeout: float) -> dict:
    """Transporte HTTP por defecto (`urllib`): GET sin payload, POST JSON con el.

    Devuelve el JSON parseado; una respuesta 2xx sin JSON valido devuelve `{}`.
    Los errores HTTP, de red o de URL se envuelven en `EngineError` con detalle
    corto. Es el unico camino que abre sockets; en tests se inyecta otro.
    """
    headers = {"User-Agent": LLM_USER_AGENT}
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
        method = "POST"
    try:
        request = urllib.request.Request(
            url, data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise EngineError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise EngineError(f"red: {str(exc.reason)[:80]}") from exc
    except (OSError, ValueError) as exc:
        raise EngineError(f"url: {str(exc)[:80]}") from exc
    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_server_llm(
    base_url: str | None = None,
    *,
    transport: Transport | None = None,
    max_tokens: int = 192,
    temperature: float = 0.7,
    timeout: float | None = None,
    model: str = "qwen35-9b-abliterated",
) -> LlmFn:
    """Cliente del `llama-server` OpenAI-compatible: `llm(system, user, temperature=None) -> str`.

    La base es `base_url`, `WAIFU_LLM_URL` o `DEFAULT_LLM_URL` (sin '/' final).
    El `timeout` es el parametro explicito, `WAIFU_LLM_TIMEOUT` (float) o 120.0.
    Cada llamada hace POST a `{base}/v1/chat/completions` con `stream=False` y
    `chat_template_kwargs={"enable_thinking": False}`; la `temperature` por
    llamada manda sobre el default del cierre. Exige contenido de texto no
    vacio en `choices[0]["message"]["content"]` (si no,
    `EngineError("LLM sin contenido")`). El transporte es inyectable y la red
    jamas se toca en tests.
    """
    base = _resolve_base_url(base_url)
    send = transport if transport is not None else _http_transport
    effective_timeout = _resolve_timeout(timeout)
    default_temperature = temperature
    default_max_tokens = max_tokens

    def llm(
        system: str,
        user: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": (
                max_tokens if max_tokens is not None else default_max_tokens
            ),
            "temperature": (
                temperature if temperature is not None else default_temperature
            ),
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = send(f"{base}/v1/chat/completions", payload, effective_timeout)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str) or not content.strip():
            raise EngineError("LLM sin contenido")
        return content

    return llm


def server_llm_state(
    base_url: str | None = None,
    *,
    transport: Transport | None = None,
    timeout: float = 2.0,
) -> tuple[str, str]:
    """Estado del servidor LLM: GET `{base}/health` -> `(estado, detalle)`.

    Estados: `ready` (el transporte no lanza), `loading` (EngineError cuyo
    mensaje empieza por `HTTP 503`: el modelo se esta cargando), `offline`
    (cualquier otro fallo del transporte) y `unknown` (URL no parseable o sin
    host, sin red). Sin `base_url` se resuelve como en `load_server_llm`
    (env o default).
    """
    if base_url is None:
        base = _resolve_base_url(None)
    else:
        base = str(base_url).strip().rstrip("/")
        if not base:
            return "unknown", "URL invalida"
    try:
        parts = urllib.parse.urlsplit(base)
    except ValueError:
        return "unknown", "URL invalida"
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "unknown", "URL invalida"
    send = transport if transport is not None else _http_transport
    try:
        send(f"{base}/health", None, timeout)
    except EngineError as exc:
        message = str(exc)[:80]
        if message.startswith("HTTP 503"):
            return "loading", message
        return "offline", message
    except Exception as exc:
        return "offline", str(exc)[:80]
    return "ready", "OK"


def server_llm_status(
    base_url: str | None = None,
    *,
    transport: Transport | None = None,
    timeout: float = 2.0,
) -> tuple[bool, str]:
    """Estado booleano del servidor LLM: `(ok, detalle)` sobre `server_llm_state`.

    `ok` es True solo con estado `ready`; el detalle es el de
    `server_llm_state` ("OK", mensaje de error o "URL invalida"). Sin
    `base_url` se resuelve como en `load_server_llm` (env o default).
    """
    state, detail = server_llm_state(base_url, transport=transport, timeout=timeout)
    return state == "ready", detail


__all__ = [
    "BASE_NEGATIVE",
    "DEFAULT_LLM_RELATIVE",
    "DEFAULT_LLM_TIMEOUT",
    "DEFAULT_LLM_URL",
    "DEFAULT_STRENGTH_PRESET",
    "LLM_TIMEOUT_ENV",
    "LLM_URL_ENV",
    "RAG_ENTRIES",
    "STRENGTH_PRESETS",
    "SYS_PROMPT",
    "Transport",
    "apply_preprompt",
    "enhance",
    "load_local_llm",
    "load_server_llm",
    "retrieve",
    "server_llm_state",
    "server_llm_status",
]
