"""Zonas del prompt (M9-C): parser, compositor y opciones en orden Anima.

El prompt es una linea de tags separados por comas. ``classify_tag`` resuelve
cada tag a una de las cinco zonas (calidad/meta, safety, sujeto, personaje y
general) con las listas canonicas de calidad/safety/sujeto y el catalogo de
``app.tags`` para el resto; nunca se adivina la zona ``character``.
``split_zones`` reparte el prompt en zonas deduplicando case-insensitive y
``compose_zones`` lo vuelve a unir en el orden Anima. ``canonical_order``
reordena un texto completo por zonas y, dentro de general, por subcategorias
(``GENERAL_SUBCATS``) y ``prompt_options`` publica las opciones de una zona
para la UI. Sin red, GPU ni dependencias.
"""

from __future__ import annotations

from app.engine import EngineError
from app.tags import all_tags, get as tag_get

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

# Subcategorias de la zona general (M9-C2), en orden canonico, con label ES.
GENERAL_SUBCATS = (
    "rasgos",
    "ropa",
    "accesorios",
    "accion",
    "expresion",
    "camara",
    "fondo",
    "otros",
)
GENERAL_SUBCAT_LABELS = {
    "rasgos": "Rasgos",
    "ropa": "Ropa",
    "accesorios": "Accesorios",
    "accion": "Acción/Pose",
    "expresion": "Expresión",
    "camara": "Cámara",
    "fondo": "Fondo/Escena",
    "otros": "Otros",
}

# Grupo del catalogo -> subcategoria; lo no listado (p. ej. ``meta``) va a otros.
CATALOG_GROUP_SUBCAT = {
    "hair": "rasgos",
    "eyes": "rasgos",
    "face": "rasgos",
    "body": "rasgos",
    "outfit": "ropa",
    "accessories": "accesorios",
    "action": "accion",
    "expression": "expresion",
    "setting": "fondo",
}

# Tags de camara/encuadre (M9-C2): manda sobre el catalogo en ``general_subcat``.
CAMERA_TAGS = (
    "close-up",
    "portrait",
    "upper body",
    "lower body",
    "full body",
    "cowboy shot",
    "from above",
    "from below",
    "from side",
    "from behind",
    "dutch angle",
    "wide shot",
    "panorama",
    "looking at viewer",
    "looking away",
    "looking back",
    "looking down",
    "looking up",
    "dynamic angle",
    "foreshortening",
    "depth of field",
)

# Opciones cortas de las zonas curadas de C1, en el orden con que se muestran.
QUALITY_OPTIONS = (
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
    "score_1",
    "score_2",
    "score_3",
    "score_4",
    "score_5",
    "score_6",
    "score_7",
    "score_8",
    "score_9",
)
SAFETY_OPTIONS = (
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
)
SUBJECT_OPTIONS = (
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
)
_OPTION_TAGS = {
    "quality": QUALITY_OPTIONS,
    "safety": SAFETY_OPTIONS,
    "subject": SUBJECT_OPTIONS,
}
_CAMERA_TAG_SET = frozenset(CAMERA_TAGS)


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


def general_subcat(tag: str) -> str:
    """Subcategoria general de un tag (``GENERAL_SUBCATS``).

    ``CAMERA_TAGS`` manda siempre (incluso si el tag esta en el catalogo); si
    esta, se usa el grupo del catalogo (``hair/eyes/face/body`` -> rasgos,
    ``outfit`` -> ropa, ...); desconocido, no-catalogo o vacio -> ``otros``.
    ``EngineError`` si el tag no es str.
    """
    if not isinstance(tag, str):
        raise EngineError(f"tag invalido: {tag!r}")
    normalized = _normalize_tag(tag)
    if not normalized:
        return "otros"
    if normalized in _CAMERA_TAG_SET:
        return "camara"
    entry = tag_get(normalized)
    if entry is None:
        return "otros"
    return CATALOG_GROUP_SUBCAT.get(entry["group"], "otros")


def _general_buckets(tags: list[str]) -> dict[str, list[str]]:
    """Reparte tags generales por subcategoria conservando su orden."""
    buckets: dict[str, list[str]] = {subcat: [] for subcat in GENERAL_SUBCATS}
    for tag in tags:
        buckets[general_subcat(tag)].append(tag)
    return buckets


def _ordered_general(tags: list[str]) -> list[str]:
    """Tags generales ordenados por ``GENERAL_SUBCATS`` (orden estable)."""
    buckets = _general_buckets(tags)
    return [tag for subcat in GENERAL_SUBCATS for tag in buckets[subcat]]


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


def canonical_order(text: str) -> str:
    """Reordena un prompt por zonas y, dentro de general, por subcategorias.

    Orden de zonas ``ZONE_ORDER``; general por ``GENERAL_SUBCATS`` conservando
    el orden relativo dentro de cada subcategoria. Dedup global
    case-insensitive preservando la primera aparicion, sintaxis de pesos
    intacta (``(tag:1.2)``) y cadenas vacias ignoradas; una entrada sin tags
    devuelve el texto limpio (``""``). ``EngineError`` si ``text`` no es str.
    """
    if not isinstance(text, str):
        raise EngineError(f"prompt invalido: {text!r}")
    zones = split_zones(text)
    zones["general"] = _ordered_general(zones["general"])
    return compose_zones(zones)


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
    """Payload serializable de las zonas: id, label y tags en orden canonico.

    ``general`` anade ademas ``subcats``: ``[{id, label, tags}]`` por
    subcategoria con tags, en orden ``GENERAL_SUBCATS`` (solo las no vacias).
    """
    zones = split_zones(prompt)
    payload: list[dict] = []
    for zone in ZONE_ORDER:
        item = {"id": zone, "label": ZONE_LABELS[zone], "tags": list(zones[zone])}
        if zone == "general":
            buckets = _general_buckets(zones["general"])
            item["subcats"] = [
                {
                    "id": subcat,
                    "label": GENERAL_SUBCAT_LABELS[subcat],
                    "tags": buckets[subcat],
                }
                for subcat in GENERAL_SUBCATS
                if buckets[subcat]
            ]
        payload.append(item)
    return payload


def _option_tag(tag: str) -> dict[str, str]:
    """Opcion serializable ``{tag, label}``: label del catalogo o el propio tag."""
    entry = tag_get(tag)
    label = entry["label"] if entry is not None else tag
    return {"tag": tag, "label": label}


def _general_option_subgroups() -> list[dict]:
    """Subgrupos de general: ``CAMERA_TAGS`` + catalogo por subcategoria.

    Las subcategorias salen en orden ``GENERAL_SUBCATS`` y solo se publican las
    que tienen tags. Los tags de camara no se repiten en su grupo de catalogo.
    """
    camera = [_option_tag(tag) for tag in CAMERA_TAGS]
    seen = {item["tag"].lower() for item in camera}
    buckets: dict[str, list[dict]] = {subcat: [] for subcat in GENERAL_SUBCATS}
    for entry in all_tags():
        if entry["tag"].lower() in seen:
            continue
        subcat = CATALOG_GROUP_SUBCAT.get(entry["group"], "otros")
        buckets[subcat].append({"tag": entry["tag"], "label": entry["label"]})
    subgroups: list[dict] = []
    for subcat in GENERAL_SUBCATS:
        tags = camera if subcat == "camara" else buckets[subcat]
        if tags:
            subgroups.append(
                {
                    "id": subcat,
                    "label": GENERAL_SUBCAT_LABELS[subcat],
                    "tags": tags,
                }
            )
    return subgroups


def prompt_options(zone: str) -> dict:
    """Opciones de una zona para la UI: ``{zone, subgroups}``.

    ``subgroups`` es ``[{id, label, tags: [{tag, label}]}]``: quality/safety/
    subject desde las listas curadas de C1 (un subgrupo con el id de la zona),
    general desde ``CAMERA_TAGS`` + el catalogo por subcategoria (sin duplicar)
    y character vacio (los OCs llegan en M9-B3). ``EngineError`` si la zona no
    es una de ``ZONE_ORDER``.
    """
    if not isinstance(zone, str) or zone not in ZONE_ORDER:
        raise EngineError(
            f"zona desconocida: {zone!r}; usar {'|'.join(ZONE_ORDER)}"
        )
    if zone == "general":
        subgroups = _general_option_subgroups()
    elif zone == "character":
        subgroups = []
    else:
        subgroups = [
            {
                "id": zone,
                "label": ZONE_LABELS[zone],
                "tags": [_option_tag(tag) for tag in _OPTION_TAGS[zone]],
            }
        ]
    return {"zone": zone, "subgroups": subgroups}


__all__ = [
    "CAMERA_TAGS",
    "CATALOG_GROUP_SUBCAT",
    "GENERAL_SUBCATS",
    "GENERAL_SUBCAT_LABELS",
    "QUALITY_OPTIONS",
    "QUALITY_TAGS",
    "SAFETY_OPTIONS",
    "SAFETY_TAGS",
    "SUBJECT_OPTIONS",
    "SUBJECT_TAGS",
    "ZONE_LABELS",
    "ZONE_ORDER",
    "canonical_order",
    "classify_tag",
    "compose_zones",
    "general_subcat",
    "insert_tag",
    "prompt_options",
    "split_zones",
    "zones_payload",
]
