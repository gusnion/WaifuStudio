"""Zonas del prompt (M9-C): parser, compositor y opciones en orden Anima.

El prompt es una linea de tags separados por comas. ``classify_tag`` resuelve
cada tag a una de las cinco zonas (calidad/meta, safety, sujeto, personaje y
general) con las listas canonicas de calidad/safety/sujeto y el catalogo de
``app.tags`` para el resto; nunca se adivina la zona ``character``.
``split_zones`` reparte el prompt en zonas deduplicando case-insensitive y
``compose_zones`` lo vuelve a unir en el orden Anima. ``canonical_order``
reordena un texto completo por zonas y, dentro de general, por subcategorias
(``GENERAL_SUBCATS``, con subcategoria ``other`` como fallback desde
M14-2: las poses/expresiones NSFW son listas curadas con precedencia tipo
``CAMERA_TAGS`` y lo desconocido cae en ``GENERAL_FALLBACK_SUBCAT`` = 'other')
y ``prompt_options`` publica las opciones de una zona para la UI. Sin red, GPU
ni dependencias.
"""

from __future__ import annotations

from app.engine import EngineError
from app.tags import BULK_GROUPS, all_tags, get as tag_get

ZONE_ORDER = ("quality", "safety", "subject", "character", "artist", "general")
ZONE_LABELS = {
    "quality": "Calidad/meta",
    "safety": "Safety",
    "subject": "Sujeto",
    "character": "Personaje",
    "artist": "Artista",
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

# Subcategorias de la zona general (M9-C2 + M10-2f + M14-2), en orden canonico, con label
# ES. Lo desconocido cae en ``GENERAL_FALLBACK_SUBCAT`` ("other").
GENERAL_SUBCATS = (
    "rasgos",
    "ropa",
    "accesorios",
    "accion",
    "poses",
    "poses_sexuales",
    "poses_sexys",
    "expresion",
    "expresiones_nsfw",
    "camara",
    "fondo",
    "other",
)
GENERAL_SUBCAT_LABELS = {
    "rasgos": "Rasgos",
    "ropa": "Ropa",
    "accesorios": "Accesorios",
    "accion": "Acción/Pose",
    "poses": "Poses",
    "poses_sexuales": "Poses sexuales",
    "poses_sexys": "Poses sexys",
    "expresion": "Expresión",
    "expresiones_nsfw": "Expresiones NSFW",
    "camara": "Cámara",
    "fondo": "Fondo/Escena",
    "other": "Otros",
}

# Fallback de ``general_subcat`` (M14-2): el bucket 'other' cierra el orden
# general, dejando 'fondo' exclusivamente para tags de entorno/fondo reales.
GENERAL_FALLBACK_SUBCAT = "other"

# Grupo del catalogo -> subcategoria; lo no listado (meta) se resuelve por tag
# o cae en ``GENERAL_FALLBACK_SUBCAT``.
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

# Tags del grupo meta del catalogo con subcategoria propia (M10-2f): los 3 tags
# de fondo que antes caian en ``otros``.
CATALOG_TAG_SUBCAT = {
    "blurry background": "fondo",
    "detailed background": "fondo",
    "simple background": "fondo",
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

# Tags curados de las subcategorias nuevas (M10-2f), en orden de aparicion.
# Mandan sobre el catalogo en ``general_subcat`` (precedencia tipo
# ``CAMERA_TAGS``, que sigue mandando por encima de estas listas). NSFW sin
# filtros: el proyecto es NSFW-permisivo.
POSES_TAGS = (
    "standing",
    "sitting",
    "kneeling",
    "lying",
    "on back",
    "on stomach",
    "on side",
    "squatting",
    "crouching",
    "seiza",
    "wariza",
    "indian style",
    "all fours",
    "fetal position",
    "hugging own legs",
    "sitting on chair",
    "sitting on bed",
    "sitting on floor",
    "leaning forward",
    "leaning back",
    "leaning to the side",
    "leaning on wall",
    "standing on one leg",
    "tiptoes",
    "contrapposto",
    "dynamic pose",
    "fighting stance",
    "crossed arms",
    "arms up",
    "hands up",
    "arms behind back",
    "arms behind head",
    "arms at sides",
    "outstretched arms",
    "reaching towards viewer",
    "hand on hip",
    "hand on own hip",
    "hands on hips",
    "hand on own face",
    "hand on own cheek",
    "hand on own chin",
    "hand in hair",
    "adjusting hair",
    "adjusting glasses",
    "finger to mouth",
    "shushing",
    "head tilt",
    "stretching",
    "waving",
    "pointing",
    "peace sign",
    "double v",
    "v over eye",
    "heart hands",
    "thumbs up",
    "salute",
    "bowing",
)
POSES_SEXUALES_TAGS = (
    "sex",
    "vaginal sex",
    "anal sex",
    "oral",
    "fellatio",
    "deepthroat",
    "irrumatio",
    "licking penis",
    "testicle sucking",
    "cooperative fellatio",
    "cunnilingus",
    "anilingus",
    "paizuri",
    "cooperative paizuri",
    "paizuri under clothes",
    "naizuri",
    "handjob",
    "double handjob",
    "nursing handjob",
    "fingering",
    "prostate milking",
    "masturbation",
    "thighjob",
    "footjob",
    "buttjob",
    "armpit sex",
    "hairjob",
    "frottage",
    "sumata",
    "tribadism",
    "girl on top",
    "boy on top",
    "sex from behind",
    "mating press",
    "missionary",
    "doggy style",
    "prone bone",
    "cowgirl position",
    "reverse cowgirl position",
    "upright straddle",
    "reverse upright straddle",
    "full nelson",
    "suspended congress",
    "reverse suspended congress",
    "standing sex",
    "against wall",
    "spooning",
    "69",
    "anvil position",
    "legs on shoulders",
    "folded",
    "leg lock",
    "amazon position",
    "piledriver",
    "wheelbarrow",
    "butterfly position",
    "straddling",
    "pinned",
    "grabbing from behind",
    "reach-around",
    "spitroast",
    "double penetration",
    "triple penetration",
    "threesome",
    "ffm threesome",
    "mmf threesome",
    "group sex",
    "gangbang",
    "orgy",
    "daisy chain",
    "breast sucking",
    "nipple tweak",
    "sex toy",
    "dildo",
    "vibrator",
    "anal beads",
    "butt plug",
    "creampie",
    "facial",
    "bukkake",
    "cum in mouth",
    "cum on breasts",
    "cum on body",
    "aftersex",
    "x-ray",
)
POSES_SEXYS_TAGS = (
    "presenting",
    "presenting breasts",
    "presenting panties",
    "presenting ass",
    "arched back",
    "top-down bottom-up",
    "jack-o' challenge",
    "spread legs",
    "legs up",
    "knee up",
    "crossed legs",
    "bent over",
    "ass focus",
    "breast focus",
    "hip focus",
    "crotch focus",
    "pussy focus",
    "hand on own chest",
    "hand between legs",
    "breast grab",
    "own breast grab",
    "ass grab",
    "spreading own pussy",
    "spread ass",
    "lifting skirt",
    "lifting shirt",
    "clothes pull",
    "bra pull",
    "bikini pull",
    "panties aside",
    "panties around one leg",
    "covering breasts",
    "covering crotch",
    "hand bra",
    "convenient censoring",
    "thigh gap",
    "cameltoe",
    "wedgie",
    "pelvic curtain",
    "undressing",
)
EXPRESIONES_NSFW_TAGS = (
    "ahegao",
    "torogao",
    "naughty face",
    "seductive smile",
    "fucked silly",
    "orgasm",
    "ecstasy",
    "moaning",
    "gasping",
    "screaming",
    "heavy breathing",
    "drooling",
    "saliva",
    "saliva trail",
    "tongue out",
    "biting lip",
    "licking lips",
    "clenched teeth",
    "half-closed eyes",
    "rolling eyes",
    "tears of pleasure",
    "full-face blush",
    "heavy blush",
    "trembling",
    "twitching",
    "mind break",
)

_CURATED_LABELS: dict[str, str] = {
    # Poses
    "squatting": "En cuclillas",
    "crouching": "Agachada",
    "seiza": "Sentada formal (seiza)",
    "wariza": "Sentada en W (wariza)",
    "indian style": "Piernas cruzadas en el suelo",
    "all fours": "A cuatro patas",
    "fetal position": "Posición fetal",
    "hugging own legs": "Abrazando sus piernas",
    "sitting on chair": "Sentada en silla",
    "sitting on bed": "Sentada en la cama",
    "sitting on floor": "Sentada en el suelo",
    "leaning back": "Inclinada hacia atrás",
    "leaning to the side": "Inclinada hacia un lado",
    "leaning on wall": "Apoyada en la pared",
    "standing on one leg": "De pie sobre una pierna",
    "tiptoes": "De puntillas",
    "contrapposto": "Cadera ladeada (contrapposto)",
    "dynamic pose": "Pose dinámica",
    "fighting stance": "Postura de combate",
    "arms behind back": "Brazos detrás de la espalda",
    "arms behind head": "Brazos detrás de la cabeza",
    "arms at sides": "Brazos a los lados",
    "outstretched arms": "Brazos extendidos",
    "reaching towards viewer": "Extendiendo la mano al espectador",
    "hand on own hip": "Mano en su propia cadera",
    "hands on hips": "Manos en las caderas",
    "hand on own cheek": "Mano en la mejilla",
    "hand on own chin": "Mano en la barbilla",
    "hand in hair": "Mano en el cabello",
    "adjusting hair": "Ajustándose el cabello",
    "adjusting glasses": "Ajustándose las gafas",
    "finger to mouth": "Dedo en los labios",
    "shushing": "Gesto de silencio",
    "double v": "Doble signo de paz",
    "v over eye": "Signo V sobre el ojo",
    "heart hands": "Corazón con las manos",
    # Poses sexuales
    "sex": "Sexo",
    "vaginal sex": "Sexo vaginal",
    "anal sex": "Sexo anal",
    "oral": "Sexo oral",
    "fellatio": "Felación (mamada)",
    "deepthroat": "Garganta profunda",
    "irrumatio": "Irrumación (agarre oral)",
    "licking penis": "Lamiendo el pene",
    "testicle sucking": "Chupando testículos",
    "cooperative fellatio": "Felación compartida (2 chicas)",
    "cunnilingus": "Cunnilingus",
    "anilingus": "Beso negro (anilingus)",
    "paizuri": "Paizuri (con los pechos)",
    "cooperative paizuri": "Paizuri compartido",
    "paizuri under clothes": "Paizuri bajo la ropa",
    "naizuri": "Naizuri (pecho plano)",
    "handjob": "Masturbación manual (handjob)",
    "double handjob": "Handjob a dos manos",
    "nursing handjob": "Handjob amamantando",
    "fingering": "Dedos (fingering)",
    "prostate milking": "Estimulación prostática",
    "masturbation": "Masturbación",
    "thighjob": "Con los muslos (thighjob)",
    "footjob": "Con los pies (footjob)",
    "buttjob": "Con los glúteos (buttjob)",
    "armpit sex": "Con la axila",
    "hairjob": "Con el cabello",
    "frottage": "Frotamiento cuerpo a cuerpo",
    "sumata": "Roce entre los muslos (sumata)",
    "tribadism": "Tijeras / tribadismo",
    "girl on top": "Chica arriba",
    "boy on top": "Chico arriba",
    "sex from behind": "Sexo por detrás",
    "mating press": "Prensa de apareamiento (mating press)",
    "missionary": "Misionero",
    "doggy style": "Perrito (doggy style)",
    "prone bone": "Boca abajo penetrada (prone bone)",
    "cowgirl position": "Vaquera (cowgirl)",
    "reverse cowgirl position": "Vaquera invertida (de espaldas)",
    "upright straddle": "Sentada a horcajadas de frente",
    "reverse upright straddle": "Sentada a horcajadas de espaldas",
    "full nelson": "Full Nelson (piernas alzadas)",
    "suspended congress": "En brazos en el aire (suspended congress)",
    "reverse suspended congress": "En brazos de espaldas",
    "standing sex": "Sexo de pie",
    "against wall": "Contra la pared",
    "spooning": "Cucharita (de lado)",
    "69": "Posición 69",
    "anvil position": "Piernas hacia los hombros (anvil)",
    "legs on shoulders": "Piernas sobre los hombros",
    "folded": "Doblada por la mitad (folded)",
    "leg lock": "Candado de piernas en cintura",
    "amazon position": "Posición amazona",
    "piledriver": "Posición piledriver",
    "wheelbarrow": "Posición carretilla",
    "butterfly position": "Posición mariposa (borde de cama)",
    "straddling": "Montada a horcajadas",
    "pinned": "Inmovilizada / sujeta",
    "grabbing from behind": "Agarrando caderas por detrás",
    "reach-around": "Acariciando por detrás",
    "spitroast": "Spitroast (ambos extremos)",
    "double penetration": "Doble penetración",
    "triple penetration": "Triple penetración",
    "threesome": "Trío",
    "ffm threesome": "Trío (2 chicas, 1 chico)",
    "mmf threesome": "Trío (2 chicos, 1 chica)",
    "group sex": "Sexo grupal",
    "gangbang": "Gangbang",
    "orgy": "Orgía",
    "daisy chain": "Cadena sexual",
    "breast sucking": "Chupando pechos",
    "nipple tweak": "Pellizcando pezones",
    "sex toy": "Juguete sexual",
    "dildo": "Consolador (dildo)",
    "vibrator": "Vibrador",
    "anal beads": "Bolas anales",
    "butt plug": "Plug anal",
    "creampie": "Creampie (eyaculación interna)",
    "facial": "Eyaculación facial",
    "bukkake": "Bukkake",
    "cum in mouth": "Semen en la boca",
    "cum on breasts": "Semen en los pechos",
    "cum on body": "Semen en el cuerpo",
    "aftersex": "Post-coito (aftersex)",
    "x-ray": "Vista interna (rayos X)",
    # Poses sexys
    "presenting": "Mostrando el cuerpo (presenting)",
    "presenting breasts": "Mostrando los pechos",
    "presenting panties": "Mostrando la ropa interior",
    "presenting ass": "Mostrando el trasero",
    "arched back": "Espalda arqueada",
    "top-down bottom-up": "Pecho en el suelo y cadera alzada",
    "jack-o' challenge": "Pose Jack-O'",
    "spread legs": "Piernas abiertas",
    "legs up": "Piernas levantadas",
    "knee up": "Rodilla levantada",
    "crossed legs": "Piernas cruzadas",
    "bent over": "Inclinada hacia adelante",
    "ass focus": "Enfoque en el trasero",
    "breast focus": "Enfoque en los pechos",
    "hip focus": "Enfoque en las caderas",
    "crotch focus": "Enfoque en la entrepierna",
    "pussy focus": "Enfoque íntimo",
    "hand on own chest": "Mano en el pecho",
    "hand between legs": "Mano entre las piernas",
    "breast grab": "Agarrando los pechos",
    "own breast grab": "Apretando sus propios pechos",
    "ass grab": "Agarrando los glúteos",
    "spreading own pussy": "Abriéndose con los dedos",
    "spread ass": "Abriendo los glúteos",
    "lifting skirt": "Levantándose la falda",
    "lifting shirt": "Levantándose la blusa/camiseta",
    "clothes pull": "Tirando de la ropa",
    "bra pull": "Tirando del sujetador",
    "bikini pull": "Tirando del bikini",
    "panties aside": "Bragas hechas a un lado",
    "panties around one leg": "Bragas colgando de una pierna",
    "covering breasts": "Cubriéndose los pechos",
    "covering crotch": "Cubriéndose la entrepierna",
    "hand bra": "Cubriendo pechos con las manos",
    "convenient censoring": "Censura conveniente",
    "thigh gap": "Hueco entre los muslos",
    "cameltoe": "Marca en la entrepierna (cameltoe)",
    "wedgie": "Ropa interior metida (wedgie)",
    "pelvic curtain": "Falda con abertura pélvica",
    "undressing": "Desvistiéndose",
    # Expresiones NSFW
    "ahegao": "Ahegao (éxtasis extremo)",
    "torogao": "Torogao (rostro derretido de placer)",
    "naughty face": "Cara pícara / traviesa",
    "seductive smile": "Sonrisa seductora",
    "fucked silly": "Aturdida de placer",
    "orgasm": "Orgasmo",
    "ecstasy": "Éxtasis",
    "moaning": "Gimiendo",
    "gasping": "Jadeando",
    "screaming": "Gritando de placer",
    "heavy breathing": "Respiración agitada",
    "drooling": "Babeando",
    "saliva": "Saliva",
    "saliva trail": "Hilo de saliva",
    "tongue out": "Lengua afuera",
    "biting lip": "Mordiéndose el labio",
    "licking lips": "Lamiéndose los labios",
    "clenched teeth": "Dientes apretados",
    "half-closed eyes": "Ojos entrecerrados",
    "rolling eyes": "Ojos en blanco",
    "tears of pleasure": "Lágrimas de placer",
    "full-face blush": "Sonrojo en toda la cara",
    "heavy blush": "Sonrojo intenso",
    "trembling": "Temblando",
    "twitching": "Espasmos corporales",
    "mind break": "Pérdida de razón (mind break)",
}

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
_CURATED_SUBCAT: dict[str, str] = {}
for _subcat, _tags in (
    ("poses", POSES_TAGS),
    ("poses_sexuales", POSES_SEXUALES_TAGS),
    ("poses_sexys", POSES_SEXYS_TAGS),
    ("expresiones_nsfw", EXPRESIONES_NSFW_TAGS),
):
    for _tag in _tags:
        _CURATED_SUBCAT[_tag] = _subcat


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

    ``CAMERA_TAGS`` manda siempre (incluso si el tag esta en el catalogo o en
    las listas curadas); despues mandan las listas curadas (``poses``,
    ``poses_sexuales``, ``poses_sexys``, ``expresiones_nsfw``); si el tag esta
    en el catalogo se usa ``CATALOG_TAG_SUBCAT`` (los 3 tags de fondo del grupo
    ``meta``) o el grupo (``hair/eyes/face/body`` -> rasgos, ``outfit`` ->
    ropa, ...). Desconocido, no-catalogo o vacio -> ``GENERAL_FALLBACK_SUBCAT``
    ('other').
    ``EngineError`` si el tag no es str.
    """
    if not isinstance(tag, str):
        raise EngineError(f"tag invalido: {tag!r}")
    normalized = _normalize_tag(tag)
    if not normalized:
        return GENERAL_FALLBACK_SUBCAT
    if normalized in _CAMERA_TAG_SET:
        return "camara"
    curated = _CURATED_SUBCAT.get(normalized)
    if curated is not None:
        return curated
    entry = tag_get(normalized)
    if entry is None:
        return GENERAL_FALLBACK_SUBCAT
    if normalized in CATALOG_TAG_SUBCAT:
        return CATALOG_TAG_SUBCAT[normalized]
    return CATALOG_GROUP_SUBCAT.get(entry["group"], GENERAL_FALLBACK_SUBCAT)


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
    """Opcion serializable ``{tag, label}``: label del catalogo, curado o el propio tag."""
    entry = tag_get(tag)
    label = entry["label"] if entry is not None else _CURATED_LABELS.get(tag, tag)
    return {"tag": tag, "label": label}


def _general_option_subgroups() -> list[dict]:
    """Subgrupos de general: curadas (camara/poses/expresiones) + catalogo.

    Las subcategorias salen en orden ``GENERAL_SUBCATS`` y solo se publican las
    que tienen tags. ``CAMERA_TAGS`` y las listas curadas de M10-2f van primero
    en su subcategoria; los tags del catalogo que clasifican a otra zona
    (calidad/safety/sujeto) no se publican en general y un tag no se repite.
    """
    camera = [_option_tag(tag) for tag in CAMERA_TAGS]
    seen = {item["tag"].lower() for item in camera}
    buckets: dict[str, list[dict]] = {subcat: [] for subcat in GENERAL_SUBCATS}
    for tag in POSES_TAGS + POSES_SEXUALES_TAGS + POSES_SEXYS_TAGS + EXPRESIONES_NSFW_TAGS:
        folded = tag.lower()
        if folded in seen:
            continue
        seen.add(folded)
        buckets[_CURATED_SUBCAT[tag]].append(_option_tag(tag))
    for entry in all_tags():
        if entry["group"] in BULK_GROUPS:
            continue
        folded = entry["tag"].lower()
        if folded in seen or classify_tag(entry["tag"]) != "general":
            continue
        seen.add(folded)
        buckets[general_subcat(entry["tag"])].append(
            {"tag": entry["tag"], "label": entry["label"]}
        )
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
    elif zone in ("character", "artist"):
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
    "CATALOG_TAG_SUBCAT",
    "EXPRESIONES_NSFW_TAGS",
    "GENERAL_FALLBACK_SUBCAT",
    "GENERAL_SUBCATS",
    "GENERAL_SUBCAT_LABELS",
    "POSES_SEXUALES_TAGS",
    "POSES_SEXYS_TAGS",
    "POSES_TAGS",
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
