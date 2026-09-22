"""Catalogo de traits OC Maker (F3a).

``TRAIT_GROUPS`` agrupa traits clicables; cada trait tiene id slug, etiqueta en
espanol y tags danbooru estandar (nada inventado). ``build_prompt`` compone el
prompt positivo en orden de grupo, con dedup exacto de tags. Sin red ni GPU.
"""

from __future__ import annotations

import copy

from app.engine import EngineError

TRAIT_GROUPS: dict[str, list[dict]] = {
    "hair": [
        {"id": "long_hair", "label": "Pelo largo", "tags": ["long hair"]},
        {"id": "short_hair", "label": "Pelo corto", "tags": ["short hair"]},
        {"id": "twintails", "label": "Coletas", "tags": ["twintails"]},
        {"id": "ponytail", "label": "Coleta alta", "tags": ["ponytail"]},
        {"id": "side_ponytail", "label": "Coleta lateral", "tags": ["side ponytail"]},
        {"id": "bob_cut", "label": "Melena bob", "tags": ["bob cut"]},
        {"id": "braid", "label": "Trenza", "tags": ["braid"]},
        {"id": "hime_cut", "label": "Corte hime", "tags": ["hime cut"]},
        {"id": "drill_hair", "label": "Rizos taladro", "tags": ["drill hair"]},
        {"id": "ahoge", "label": "Ahoge", "tags": ["ahoge"]},
    ],
    "eyes": [
        {"id": "heterochromia", "label": "Heterocromia", "tags": ["heterochromia"]},
        {"id": "red_eyes", "label": "Ojos rojos", "tags": ["red eyes"]},
        {"id": "blue_eyes", "label": "Ojos azules", "tags": ["blue eyes"]},
        {"id": "green_eyes", "label": "Ojos verdes", "tags": ["green eyes"]},
        {"id": "purple_eyes", "label": "Ojos violetas", "tags": ["purple eyes"]},
        {"id": "yellow_eyes", "label": "Ojos dorados", "tags": ["yellow eyes"]},
        {"id": "closed_eyes", "label": "Ojos cerrados", "tags": ["closed eyes"]},
        {"id": "tsurime", "label": "Mirada tsurime", "tags": ["tsurime"]},
        {"id": "tareme", "label": "Mirada tareme", "tags": ["tareme"]},
    ],
    "face": [
        {"id": "freckles", "label": "Pecas", "tags": ["freckles"]},
        {"id": "mole_under_eye", "label": "Lunar bajo el ojo", "tags": ["mole under eye"]},
        {"id": "blush", "label": "Rubor", "tags": ["blush"]},
        {"id": "pointy_ears", "label": "Orejas puntiagudas", "tags": ["pointy ears"]},
        {"id": "fang", "label": "Colmillo", "tags": ["fang"]},
        {"id": "sharp_teeth", "label": "Dientes afilados", "tags": ["sharp teeth"]},
        {"id": "pale_skin", "label": "Piel palida", "tags": ["pale skin"]},
        {"id": "dark_skin", "label": "Piel oscura", "tags": ["dark skin"]},
    ],
    "body": [
        {"id": "large_breasts", "label": "Pecho grande", "tags": ["large breasts"]},
        {"id": "medium_breasts", "label": "Pecho medio", "tags": ["medium breasts"]},
        {"id": "small_breasts", "label": "Pecho pequeno", "tags": ["small breasts"]},
        {"id": "wide_hips", "label": "Caderas anchas", "tags": ["wide hips"]},
        {"id": "thick_thighs", "label": "Muslos gruesos", "tags": ["thick thighs"]},
        {"id": "muscular", "label": "Musculosa", "tags": ["muscular"]},
        {"id": "chubby", "label": "Rellenita", "tags": ["chubby"]},
        {"id": "abs", "label": "Abdominales", "tags": ["abs"]},
        {"id": "flat_chest", "label": "Pecho plano", "tags": ["flat chest"]},
    ],
    "outfit": [
        {"id": "school_uniform", "label": "Uniforme escolar", "tags": ["school uniform"]},
        {"id": "serafuku", "label": "Serafuku", "tags": ["serafuku"]},
        {"id": "maid", "label": "Traje de doncella", "tags": ["maid"]},
        {"id": "kimono", "label": "Kimono", "tags": ["kimono"]},
        {"id": "hoodie", "label": "Sudadera con capucha", "tags": ["hoodie"]},
        {"id": "dress", "label": "Vestido", "tags": ["dress"]},
        {"id": "swimsuit", "label": "Banador", "tags": ["swimsuit"]},
        {"id": "military_uniform", "label": "Uniforme militar", "tags": ["military uniform"]},
        {"id": "armor", "label": "Armadura", "tags": ["armor"]},
    ],
    "expression": [
        {"id": "smile", "label": "Sonrisa", "tags": ["smile"]},
        {"id": "open_mouth", "label": "Boca abierta", "tags": ["open mouth"]},
        {"id": "pout", "label": "Mohin", "tags": ["pout"]},
        {"id": "laughing", "label": "Risa", "tags": ["laughing"]},
        {"id": "crying", "label": "Llantos", "tags": ["crying"]},
        {"id": "angry", "label": "Enfado", "tags": ["angry"]},
        {"id": "smug", "label": "Sorna", "tags": ["smug"]},
        {"id": "wink", "label": "Guino", "tags": ["wink"]},
        {"id": "half_closed_eyes", "label": "Ojos entornados", "tags": ["half-closed eyes"]},
    ],
    "accessories": [
        {"id": "glasses", "label": "Gafas", "tags": ["glasses"]},
        {"id": "choker", "label": "Gargantilla", "tags": ["choker"]},
        {"id": "hair_ribbon", "label": "Cinta de pelo", "tags": ["hair ribbon"]},
        {"id": "hairband", "label": "Diadema", "tags": ["hairband"]},
        {"id": "earrings", "label": "Pendientes", "tags": ["earrings"]},
        {"id": "necklace", "label": "Collar", "tags": ["necklace"]},
        {"id": "thighhighs", "label": "Medias hasta el muslo", "tags": ["thighhighs"]},
        {
            "id": "zettai_ryouiki",
            "label": "Zettai ryouiki",
            "tags": ["zettai ryouiki", "thighhighs"],
        },
        {"id": "gloves", "label": "Guantes", "tags": ["gloves"]},
    ],
    "setting": [
        {"id": "cityscape", "label": "Paisaje urbano", "tags": ["cityscape"]},
        {"id": "classroom", "label": "Aula", "tags": ["classroom"]},
        {"id": "cherry_blossoms", "label": "Cerezos en flor", "tags": ["cherry blossoms"]},
        {"id": "beach", "label": "Playa", "tags": ["beach"]},
        {"id": "forest", "label": "Bosque", "tags": ["forest"]},
        {"id": "night", "label": "Noche", "tags": ["night"]},
        {"id": "sunset", "label": "Atardecer", "tags": ["sunset"]},
        {"id": "snow", "label": "Nieve", "tags": ["snow"]},
        {"id": "cafe", "label": "Cafeteria", "tags": ["cafe"]},
        {"id": "rooftop", "label": "Azotea", "tags": ["rooftop"]},
    ],
}

_TRAIT_INDEX: dict[str, dict] = {
    trait["id"]: trait for traits in TRAIT_GROUPS.values() for trait in traits
}


def build_prompt(selected_ids: list[str]) -> str:
    """Tags de los traits elegidos, unidos con ', '; EngineError si el id no existe.

    El orden es el del catalogo (por grupo) y los tags repetidos se emiten una
    sola vez.
    """
    if not isinstance(selected_ids, (list, tuple)):
        raise EngineError(f"seleccion de traits invalida: {selected_ids!r}")
    selected: set[str] = set()
    for trait_id in selected_ids:
        if not isinstance(trait_id, str) or trait_id not in _TRAIT_INDEX:
            raise EngineError(f"trait desconocido: {trait_id!r}")
        selected.add(trait_id)
    tags: list[str] = []
    seen: set[str] = set()
    for traits in TRAIT_GROUPS.values():
        for trait in traits:
            if trait["id"] not in selected:
                continue
            for tag in trait["tags"]:
                if tag in seen:
                    continue
                seen.add(tag)
                tags.append(tag)
    return ", ".join(tags)


def list_traits() -> dict:
    """Copia profunda y serializable del catalogo para la API."""
    return copy.deepcopy(TRAIT_GROUPS)


__all__ = ["TRAIT_GROUPS", "build_prompt", "list_traits"]
