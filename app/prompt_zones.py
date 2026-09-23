"""Zonas del prompt (M9-C): parser y compositor en orden Anima.

El prompt es una linea de tags separados por comas. ``classify_tag`` resuelve
cada tag a una de las cinco zonas (calidad/meta, safety, sujeto, personaje y
general) con las listas canonicas de calidad/safety/sujeto y el catalogo de
``app.tags`` para el resto; nunca se adivina la zona ``character``.
``split_zones`` reparte el prompt en zonas deduplicando case-insensitive y
``compose_zones`` lo vuelve a unir en el orden Anima. Sin red, GPU ni
dependencias.
"""

from __future__ import annotations

from app.engine import EngineError
from app.tags import get as tag_get

ZONE_ORDER = ("quality", "safety", "subject", "character", "general")
ZONE_LABELS = {
    "quality": "Calidad/meta",
    "safety": "Safety",
    "subject": "Sujeto",
    "character": "Personaje",
    "general": "General",
}

QUALITY_TAGS = frozenset(
    {
        "masterpiece",
        "best quality",
        "amazing quality",
        "high quality",
        "good quality",
        "normal quality",
        "average quality",
        "bad quality",
        "low quality",
        "worst quality",
        "absurdres",
        "highres",
        "lowres",
        "very aesthetic",
        "newest",
        "oldest",
        "jpeg artifacts",
        "sepia",
        "watermark",
        "signature",
        "logo",
    }
    | {f"score_{index}" for index in range(1, 10)}
)

SAFETY_TAGS = frozenset(
    {
        "sfw",
        "nsfw",
        "uncensored",
        "explicit",
        "sensitive",
        "safe",
        "questionable",
        "rating_safe",
        "rating_general",
        "rating_sensitive",
        "rating_questionable",
        "rating_explicit",
    }
)

SUBJECT_TAGS = frozenset(
    {
        "1girl",
        "1boy",
        "1other",
        "2girls",
        "2boys",
        "3girls",
        "3boys",
        "4girls",
        "4boys",
        "5girls",
        "5boys",
        "6+girls",
        "6+boys",
        "multiple girls",
        "multiple boys",
        "solo",
        "solo focus",
        "hetero",
        "yuri",
        "yaoi",
        "bara",
        "male focus",
        "female focus",
        "no humans",
        "everyone",
    }
)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _normalize_tag(tag: str) -> str:
    """Minusculas, espacios colapsados y peso ``(tag:1.2)`` eliminado."""
    if not isinstance(tag, str):
        raise EngineError(f"tag invalido: {tag!r}")
    text = " ".join(tag.strip().split())
    for _ in range(4):
        changed = False
        if text.startswith("(") and text.endswith(")"):
            inner = text[1:-1].strip()
            if inner:
                text = inner
                changed = True
        if ":" in text:
            head, _, tail = text.rpartition(":")
            if head.strip() and _is_number(tail.strip()):
                text = head.strip()
                changed = True
        if not changed:
            break
    return " ".join(text.lower().split())


def classify_tag(tag: str) -> str:
    """Zona canonica de un tag; los pesos se clasifican por el tag interior.

    Calidad/safety/sujeto salen de las listas canonicas. El resto (tags del
    catalogo de ``app.tags`` y desconocidos) cae siempre en ``general``: nunca
    se adivina la zona ``character``. ``EngineError`` si el tag no es str o
    queda vacio.
    """
    normalized = _normalize_tag(tag)
    if not normalized:
        raise EngineError(f"tag vacio: {tag!r}")
    if normalized in QUALITY_TAGS:
        return "quality"
    if normalized in SAFETY_TAGS:
        return "safety"
    if normalized in SUBJECT_TAGS:
        return "subject"
    entry = tag_get(normalized)
    if entry is not None:
        return "general"
    return "general"


def split_zones(prompt: str) -> dict[str, list[str]]:
    """Reparte un prompt en las cinco zonas, dedup case-insensitive por zona.

    Limpia espacios, ignora fragmentos vacios y conserva el texto original de
    cada tag (pesos incluidos) y su orden dentro de la zona.
    """
    if not isinstance(prompt, str):
        raise EngineError(f"prompt invalido: {prompt!r}")
    zones: dict[str, list[str]] = {zone: [] for zone in ZONE_ORDER}
    seen: set[str] = set()
    for fragment in prompt.split(","):
        tag = " ".join(fragment.strip().split())
        if not tag:
            continue
        folded = tag.lower()
        if folded in seen:
            continue
        seen.add(folded)
        zones[classify_tag(tag)].append(tag)
    return zones


def compose_zones(zones: dict[str, list[str]]) -> str:
    """Une las zonas en ``ZONE_ORDER`` deduplicando global case-insensitive.

    Solo entran las zonas con tags; ``EngineError`` si el mapa no es un dict,
    trae zonas desconocidas o valores que no son listas de str.
    """
    if not isinstance(zones, dict):
        raise EngineError(f"zones invalido: {zones!r}")
    for zone in zones:
        if zone not in ZONE_ORDER:
            raise EngineError(
                f"zona desconocida: {zone!r}; usar {'|'.join(ZONE_ORDER)}"
            )
    merged: list[str] = []
    seen: set[str] = set()
    for zone in ZONE_ORDER:
        tags = zones.get(zone)
        if tags is None:
            continue
        if not isinstance(tags, (list, tuple)):
            raise EngineError(f"zona {zone!r} debe ser lista de tags: {tags!r}")
        for raw in tags:
            if not isinstance(raw, str):
                raise EngineError(f"tag invalido en zona {zone!r}: {raw!r}")
            tag = " ".join(raw.strip().split())
            if not tag:
                continue
            folded = tag.lower()
            if folded in seen:
                continue
            seen.add(folded)
            merged.append(tag)
    return ", ".join(merged)


def insert_tag(prompt: str, tag: str, zone: str | None = None) -> str:
    """Inserta un tag en su zona (clasificada si ``zone`` es None) sin duplicar.

    Devuelve el prompt recompuesto en orden Anima; si el tag ya estaba
    (case-insensitive) devuelve el prompt intacto. ``EngineError`` si el prompt
    o el tag no son str, el tag queda vacio o la zona es desconocida.
    """
    if not isinstance(prompt, str):
        raise EngineError(f"prompt invalido: {prompt!r}")
    if not isinstance(tag, str) or not tag.strip():
        raise EngineError(f"tag requerido: {tag!r}")
    if zone is not None:
        if not isinstance(zone, str) or zone not in ZONE_ORDER:
            raise EngineError(
                f"zona desconocida: {zone!r}; usar {'|'.join(ZONE_ORDER)}"
            )
    target = zone if zone is not None else classify_tag(tag)
    cleaned = " ".join(tag.strip().split())
    zones = split_zones(prompt)
    existing = {item.lower() for items in zones.values() for item in items}
    if cleaned.lower() in existing:
        return prompt
    zones[target].append(cleaned)
    return compose_zones(zones)


def zones_payload(prompt: str) -> list[dict]:
    """Payload serializable de las zonas: id, label y tags en orden canonico."""
    zones = split_zones(prompt)
    return [
        {"id": zone, "label": ZONE_LABELS[zone], "tags": list(zones[zone])}
        for zone in ZONE_ORDER
    ]


__all__ = [
    "QUALITY_TAGS",
    "SAFETY_TAGS",
    "SUBJECT_TAGS",
    "ZONE_LABELS",
    "ZONE_ORDER",
    "classify_tag",
    "compose_zones",
    "insert_tag",
    "split_zones",
    "zones_payload",
]
