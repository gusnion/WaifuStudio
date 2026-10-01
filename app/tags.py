"""Catalogo Danbooru local (M11-1): capa curada + catalogo completo v3.

``registry/tags_danbooru.json`` trae dos capas: la curada (``tags``:
{tag,label,group,rank}, labels en espanol) y el catalogo compacto (``catalog``:
{name,category,posts,aliases}, ordenado por posts desc; ausente en v2). Sobre
ellas este modulo expone la API curada por grupo (M9-B1), la busqueda por
substring con resultados del catalogo, la validacion/resolucion canonica de
tags (``is_valid``/``resolve``) y la recuperacion por tokens con FTS5
(``retrieve``; indice en memoria perezoso con sqlite3 stdlib y, si FTS5 no
estuviera disponible, scan lineal por prefijos con el mismo scoring sin bm25).
Solo stdlib: sin red, GPU ni dependencias.
"""

from __future__ import annotations

import copy
import json
import math
import re
import sqlite3
import threading
from pathlib import Path

from app.config import APP_ROOT
from app.engine import EngineError

CATALOG_PATH = APP_ROOT / "registry" / "tags_danbooru.json"
MAX_SEARCH_LIMIT = 200
DEFAULT_SEARCH_LIMIT = 50
BULK_GROUPS = ("general_top", "character", "series", "artist")

_CATALOG_CATEGORIES = ("general", "artist", "series", "character", "meta")
_CATALOG_KEYS = frozenset({"name", "category", "posts", "aliases"})
_MAX_RETRIEVE_LIMIT = 120
_ZONE_CATEGORIES = {"character": ("character", "series"), "general": ("general",)}
_SCORE_TAG_RE = re.compile(r"score_\d+")
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas",
        "y", "o", "u", "en", "al", "con", "sin", "por", "para", "su", "sus",
        "se", "que", "como", "muy", "mas", "más", "esta", "este", "esto",
        "eso", "esa", "ese", "lo", "le", "les", "mi", "mis", "tu", "tus",
        "te", "me", "nos", "os", "son", "es", "ser", "hay", "entre", "sobre",
        "bajo", "tras", "durante", "contra", "desde", "hasta", "cuando",
        "donde", "quien", "cual",
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "with",
        "without", "and", "or", "but", "is", "are", "was", "were", "be",
        "been", "by", "from", "into", "over", "under", "his", "her", "their",
        "its", "this", "that", "these", "those", "as", "it", "he", "she",
        "they", "we", "you", "your", "our", "do", "does", "did", "can",
        "could", "will", "would",
    }
)


def _fold(text: str) -> str:
    """Clave de busqueda canonica: strip, '_'->espacio (salvo ``score_<N>``), espacios colapsados y minusculas."""
    parts: list[str] = []
    for token in text.strip().split():
        if _SCORE_TAG_RE.fullmatch(token.lower()):
            parts.append(token.lower())
        else:
            parts.append(token.replace("_", " "))
    return " ".join(" ".join(parts).split()).lower()


def _load_catalog(
    path: Path = CATALOG_PATH,
) -> tuple[list[str], list[dict], list[dict]]:
    """Lee y valida el JSON (curado + catalogo); EngineError con el detalle si esta corrupto."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"catalogo de tags ilegible en {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError(f"catalogo de tags invalido en {path}: se esperaba un objeto")
    groups = data.get("groups")
    tags = data.get("tags")
    if not isinstance(groups, list) or not all(
        isinstance(group, str) and group for group in groups
    ):
        raise EngineError(f"catalogo de tags sin 'groups' validos en {path}")
    if len(set(groups)) != len(groups):
        raise EngineError(f"catalogo de tags con grupos duplicados en {path}")
    if not isinstance(tags, list):
        raise EngineError(f"catalogo de tags sin 'tags' validos en {path}")
    seen: set[str] = set()
    entries: list[dict] = []
    for item in tags:
        if not isinstance(item, dict):
            raise EngineError(f"entrada de tag invalida en {path}: {item!r}")
        tag = item.get("tag")
        label = item.get("label")
        group = item.get("group")
        if not isinstance(tag, str) or not tag.strip():
            raise EngineError(f"tag invalido en {path}: {tag!r}")
        if not isinstance(label, str) or not label.strip():
            raise EngineError(f"label invalido para {tag!r} en {path}")
        if group not in groups:
            raise EngineError(f"grupo invalido para {tag!r} en {path}: {group!r}")
        folded = tag.strip().lower()
        if folded in seen:
            raise EngineError(f"tag duplicado en {path}: {tag!r}")
        seen.add(folded)
        rank = item.get("rank", 0)
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
            raise EngineError(f"rank invalido para {tag!r} en {path}: {rank!r}")
        entries.append(
            {"tag": tag.strip(), "label": label.strip(), "group": group, "rank": rank}
        )
    order = {group: index for index, group in enumerate(groups)}
    entries.sort(key=lambda entry: order[entry["group"]])
    catalog = _load_catalog_layer(data["catalog"] if "catalog" in data else None, path)
    return list(groups), entries, catalog


def _load_catalog_layer(raw: object, path: Path) -> list[dict]:
    """Valida la capa compacta v3; lista vacia si la clave ``catalog`` falta (compatibilidad v2)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise EngineError(f"catalogo de tags invalido en {path}: 'catalog' no es lista")
    entries: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise EngineError(f"entrada de catalogo invalida en {path}: {item!r}")
        if set(item) != _CATALOG_KEYS:
            raise EngineError(
                f"entrada de catalogo con claves invalidas en {path}: {sorted(item)!r}"
            )
        name = item["name"]
        if not isinstance(name, str) or not name.strip():
            raise EngineError(f"name invalido en catalogo de {path}: {name!r}")
        category = item["category"]
        if category not in _CATALOG_CATEGORIES:
            raise EngineError(
                f"categoria invalida para {name!r} en {path}: {category!r}"
            )
        posts = item["posts"]
        if isinstance(posts, bool) or not isinstance(posts, int) or posts <= 0:
            raise EngineError(f"posts invalidos para {name!r} en {path}: {posts!r}")
        aliases = item["aliases"]
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias for alias in aliases
        ):
            raise EngineError(
                f"aliases invalidos para {name!r} en {path}: {aliases!r}"
            )
        entries.append(
            {
                "name": name,
                "category": category,
                "posts": posts,
                "aliases": list(aliases),
            }
        )
    return entries


GROUPS, _ENTRIES, _CATALOG = _load_catalog()
_BY_GROUP: dict[str, list[dict]] = {group: [] for group in GROUPS}
for _entry in _ENTRIES:
    _BY_GROUP[_entry["group"]].append(_entry)
_INDEX: dict[str, dict] = {entry["tag"].lower(): entry for entry in _ENTRIES}
_CURATED_KEYS: dict[str, bool] = {}
_CURATED_CANON: dict[str, str] = {}
for _entry in _ENTRIES:
    _key = _fold(_entry["tag"])
    _CURATED_KEYS[_key] = True
    _CURATED_CANON[_key] = _entry["tag"]
_NAME_INDEX: dict[str, str] = {}
_ALIAS_INDEX: dict[str, str] = {}
for _item in _CATALOG:
    _key = _fold(_item["name"])
    if _key and _key not in _NAME_INDEX:
        _NAME_INDEX[_key] = _item["name"]
    for _alias in _item["aliases"]:
        _key = _fold(_alias)
        if _key and _key not in _ALIAS_INDEX:
            _ALIAS_INDEX[_key] = _item["name"]

_FTS_LOCK = threading.Lock()
_FTS_READY = False
_FTS_CONN: sqlite3.Connection | None = None


def _build_fts() -> sqlite3.Connection | None:
    """Crea el indice FTS5 en memoria (rowid 1-based, aliases unidos con espacios); None si falla."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE tag_fts USING fts5("
            "name, aliases, category UNINDEXED, posts UNINDEXED, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        rows = [
            (
                index + 1,
                entry["name"],
                " ".join(entry["aliases"]),
                entry["category"],
                entry["posts"],
            )
            for index, entry in enumerate(_CATALOG)
        ]
        with conn:
            conn.executemany(
                "INSERT INTO tag_fts(rowid, name, aliases, category, posts)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    except sqlite3.Error:
        conn.close()
        return None
    return conn


def _get_fts() -> sqlite3.Connection | None:
    """Indice perezoso bajo lock; None si sqlite no trae FTS5 o el build falla."""
    global _FTS_CONN, _FTS_READY
    if _FTS_READY:
        return _FTS_CONN
    with _FTS_LOCK:
        if not _FTS_READY:
            _FTS_CONN = _build_fts()
            _FTS_READY = True
    return _FTS_CONN


def _fts_prefix_and(tokens: list[str]) -> str:
    return " ".join(f'"{token}"*' for token in tokens)


def _fts_prefix_or(tokens: list[str]) -> str:
    return " OR ".join(f'"{token}"*' for token in tokens)


def _rank_rows(
    rows: list[tuple[str, str, int, float | None]],
) -> list[tuple[float, int, str, str, str]]:
    """Orden canonico (score desc, posts desc, name asc) de filas (name, category, posts, bm25|None)."""
    scored: list[tuple[float, int, str, str, str]] = []
    for name, category, posts, bm25 in rows:
        score = (0.0 if bm25 is None else -bm25) + 1.5 * math.log10(posts + 1)
        key = _fold(name)
        if key in _CURATED_KEYS:
            score += 1.5
        scored.append((score, posts, name, key, category))
    scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return scored


def _fallback_rows(
    tokens: list[str], categories: tuple[str, ...] | None, match_all: bool = True
) -> list[tuple[str, str, int, None]]:
    """Scan lineal por substring de token sobre ``_CATALOG`` (sin bm25) para sqlite sin FTS5.

    ``match_all`` replica la semantica AND de ``search``; con False, la OR de ``retrieve``.
    """
    rows: list[tuple[str, str, int, None]] = []
    for entry in _CATALOG:
        if categories is not None and entry["category"] not in categories:
            continue
        haystack = " ".join(
            [_fold(entry["name"])] + [_fold(alias) for alias in entry["aliases"]]
        )
        found = [token in haystack for token in tokens]
        if (all(found) if match_all else any(found)):
            rows.append((entry["name"], entry["category"], entry["posts"], None))
    return rows


def _catalog_matches(needle: str):
    """Genera (name, category, posts) del catalogo que casan el needle plegado, en orden determinista."""
    tokens = _TOKEN_RE.findall(needle)
    if not tokens:
        return
    conn = _get_fts()
    if conn is not None:
        with _FTS_LOCK:
            rows = conn.execute(
                "SELECT name, category, posts, bm25(tag_fts) FROM tag_fts"
                " WHERE tag_fts MATCH ?",
                (_fts_prefix_and(tokens),),
            ).fetchall()
    else:
        rows = _fallback_rows(tokens, None, match_all=True)
    for _score, posts, name, _key, category in _rank_rows(rows):
        yield name, category, posts


def list_groups() -> list[str]:
    """Nombres de grupo en orden canonico."""
    return list(GROUPS)


def by_group(group: str) -> list[dict]:
    """Entradas de un grupo como copias; EngineError si el grupo no existe."""
    if group not in _BY_GROUP:
        raise EngineError(f"grupo de tags desconocido: {group!r}")
    return copy.deepcopy(_BY_GROUP[group])


def catalog_count() -> int:
    """Numero de entradas de la capa compacta del catalogo v3."""
    return len(_CATALOG)


def is_valid(tag: str) -> bool:
    """True si el tag plegado existe en la capa curada, en el catalogo o en sus aliases."""
    if not isinstance(tag, str):
        return False
    key = _fold(tag)
    if not key:
        return False
    return key in _CURATED_KEYS or key in _NAME_INDEX or key in _ALIAS_INDEX


def resolve(tag: str) -> str | None:
    """Forma canonica de display del tag (curado > nombre de catalogo > alias), o None."""
    if not isinstance(tag, str):
        return None
    key = _fold(tag)
    if not key:
        return None
    curated = _CURATED_CANON.get(key)
    if curated is not None:
        return curated
    name = _NAME_INDEX.get(key)
    if name is not None:
        return name
    return _ALIAS_INDEX.get(key)


def validate_list(text: str) -> tuple[list[str], list[str]]:
    """Valida una lista de tags separadas por coma contra el catalogo.

    Cada fragmento (separado por coma) se limpia (strip); los vacios se
    ignoran. Los fragmentos no resolubles van a `dropped` con su texto tal
    cual (strip). Los resolubles se sustituyen por su forma canonica; si el
    fragmento ya es canonico case-insensitive se conserva el texto original
    tal cual (p. ej. `SCORE_9`). Dedup case-insensitive del resultado
    conservando la 1a aparicion. Devuelve `(kept, dropped)`.
    """
    kept: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for part in str(text).split(","):
        fragment = part.strip()
        if not fragment:
            continue
        canonical = resolve(fragment)
        if canonical is None:
            dropped.append(fragment)
            continue
        final = fragment if fragment.lower() == canonical.lower() else canonical
        folded = final.lower()
        if folded in seen:
            continue
        seen.add(folded)
        kept.append(final)
    return kept, dropped


def search(q: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict]:
    """Curados por substring (tag/label) y despues catalogo via FTS5; limit clamp 1..200 y copias."""
    if not isinstance(q, str):
        raise EngineError(f"consulta de tags invalida: {q!r}")
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"limit de tags invalido: {limit!r}") from exc
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    needle = _fold(q)
    if not needle:
        return copy.deepcopy(_ENTRIES[:limit])
    results: list[dict] = [
        entry
        for entry in _ENTRIES
        if needle in entry["tag"].lower() or needle in entry["label"].lower()
    ][:limit]
    if len(results) < limit and _CATALOG:
        seen = {_fold(entry["tag"]) for entry in results}
        for name, category, posts in _catalog_matches(needle):
            key = _fold(name)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {"tag": name, "label": name, "group": category, "rank": posts}
            )
            if len(results) >= limit:
                break
    return copy.deepcopy(results)


def retrieve(query: str, zone: str | None = None, k: int = 60) -> list[str]:
    """Nombres canonicos que casan los tokens de ``query`` (OR por prefijos FTS5), rankeados en Python.

    Descarta tokens de parada espanoles/ingleses (``_STOPWORDS``) antes de la query FTS; solo
    aplica a ``retrieve`` (``search`` conserva su comportamiento).
    """
    try:
        k = int(k)
    except (TypeError, ValueError):
        k = 60
    if k <= 0:
        return []
    k = min(k, _MAX_RETRIEVE_LIMIT)
    if not isinstance(query, str):
        return []
    tokens: list[str] = []
    seen_tokens: set[str] = set()
    for token in _TOKEN_RE.findall(query.lower()):
        if len(token) < 2 or token in _STOPWORDS or token in seen_tokens:
            continue
        seen_tokens.add(token)
        tokens.append(token)
    if not tokens:
        return []
    categories = _ZONE_CATEGORIES.get(zone) if isinstance(zone, str) else None
    conn = _get_fts()
    if conn is not None:
        sql = (
            "SELECT name, category, posts, bm25(tag_fts) FROM tag_fts"
            " WHERE tag_fts MATCH ?"
        )
        params: list[object] = [_fts_prefix_or(tokens)]
        if categories:
            sql += f" AND category IN ({', '.join('?' * len(categories))})"
            params.extend(categories)
        with _FTS_LOCK:
            rows = conn.execute(sql, params).fetchall()
    else:
        rows = _fallback_rows(tokens, categories, match_all=False)
    names: list[str] = []
    seen: set[str] = set()
    for _score, _posts, name, key, _category in _rank_rows(rows):
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        if len(names) >= k:
            break
    return names


def get(tag: str) -> dict | None:
    """Entrada curada por tag canonico (case-insensitive), o None si no existe."""
    if not isinstance(tag, str):
        return None
    entry = _INDEX.get(tag.strip().lower())
    return copy.deepcopy(entry) if entry is not None else None


def all_tags() -> list[dict]:
    """Todas las entradas curadas (copias) en orden de grupo canonico."""
    return copy.deepcopy(_ENTRIES)


__all__ = [
    "BULK_GROUPS",
    "CATALOG_PATH",
    "DEFAULT_SEARCH_LIMIT",
    "GROUPS",
    "MAX_SEARCH_LIMIT",
    "all_tags",
    "by_group",
    "catalog_count",
    "get",
    "is_valid",
    "list_groups",
    "resolve",
    "retrieve",
    "search",
    "validate_list",
]
