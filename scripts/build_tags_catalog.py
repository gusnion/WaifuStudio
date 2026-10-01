"""Construye `registry/tags_danbooru.json` v3 desde el CSV de Danbooru (tagcomplete).

Conserva el catalogo curado (labels en espanol), anade top-N por popularidad en
los grupos `general_top`, `character`, `series` y `artist` (`rank` = uso en
Danbooru) y publica el catalogo completo por umbral de posts
(name/category/posts/aliases). Uso:

    python scripts/build_tags_catalog.py [--refresh] [--csv PATH] [--threshold N]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = APP_ROOT / "registry" / "tags_danbooru.json"
CSV_URL = (
    "https://raw.githubusercontent.com/DominikDoom/"
    "a1111-sd-webui-tagcomplete/main/tags/danbooru.csv"
)
CACHE_PATH = APP_ROOT / "data" / "downloads" / "tags" / "danbooru.csv"
TOPN = {"general_top": 1500, "character": 800, "series": 300, "artist": 300}
CATEGORY_GROUP = {"0": "general_top", "1": "artist", "3": "series", "4": "character"}
ADDED_GROUPS = ("general_top", "character", "series", "artist")
CATEGORY_NAME = {
    "0": "general",
    "1": "artist",
    "3": "series",
    "4": "character",
    "5": "meta",
}
DEFAULT_THRESHOLD = 50
SCHEMA_VERSION = "tags-danbooru/v3"
DESCRIPTION = (
    "Catalogo Danbooru local (M11-1): capa curada con labels es + catalogo "
    "completo por umbral de posts (name/category/posts/aliases)."
)
USER_AGENT = "WAIFU-tags-catalog/3.0 (+local)"


def download(refresh: bool) -> Path:
    """Descarga el CSV a la cache (o la reutiliza) y devuelve la ruta."""
    if refresh or not CACHE_PATH.is_file():
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(CSV_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
        CACHE_PATH.write_bytes(data)
    return CACHE_PATH


def load_curated() -> dict:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    groups = list(data["groups"])
    tags = list(data["tags"])
    for entry in tags:
        entry.setdefault("rank", 0)
    return {"groups": groups, "tags": tags}


def display_name(raw: str) -> str:
    """`a__b` -> `a b` (underscores a espacios y espacios colapsados)."""
    return " ".join(raw.strip().replace("_", " ").split())


def clean_aliases(raw: str, name: str) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        alias = part.strip()
        if not alias or alias.startswith("/") or alias.startswith(":"):
            continue
        if not any(character.isalnum() for character in alias):
            continue
        alias = display_name(alias)
        folded = alias.lower()
        if folded == name.lower() or folded in seen:
            continue
        seen.add(folded)
        aliases.append(alias)
    return aliases


def build(csv_path: Path, curated: dict, threshold: int = DEFAULT_THRESHOLD) -> dict:
    curated_tags = [
        dict(entry) for entry in curated["tags"] if entry.get("rank", 0) == 0
    ]
    seen = {entry["tag"].lower() for entry in curated_tags}
    buckets: dict[str, list[dict]] = {group: [] for group in ADDED_GROUPS}
    catalog: list[dict] = []
    csv_rows = 0
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            csv_rows += 1
            if len(row) < 3:
                continue
            name = row[0].strip()
            if not name:
                continue
            category = row[1].strip()
            try:
                posts = int(row[2])
            except (TypeError, ValueError):
                continue
            group = CATEGORY_GROUP.get(category)
            if group is not None and posts > 0:
                tag = name.replace("_", " ")
                folded = tag.lower()
                if folded not in seen:
                    seen.add(folded)
                    buckets[group].append(
                        {"tag": tag, "label": tag, "group": group, "rank": posts}
                    )
            catalog_name = CATEGORY_NAME.get(category)
            if catalog_name is None or posts < threshold:
                continue
            label = display_name(name)
            raw_aliases = row[3] if len(row) > 3 else ""
            catalog.append(
                {
                    "name": label,
                    "category": catalog_name,
                    "posts": posts,
                    "aliases": clean_aliases(raw_aliases, label),
                }
            )
    tags = curated_tags
    for group in ADDED_GROUPS:
        entries = sorted(buckets[group], key=lambda item: item["rank"], reverse=True)
        tags.extend(entries[: TOPN[group]])
    catalog.sort(key=lambda item: (-item["posts"], item["name"]))
    groups: list[str] = []
    for group in curated["groups"]:
        if group not in groups:
            groups.append(group)
    for group in ADDED_GROUPS:
        if group not in groups:
            groups.append(group)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest().upper()
    return {
        "schema_version": SCHEMA_VERSION,
        "descripcion": DESCRIPTION,
        "source": {
            "url": CSV_URL,
            "sha256": digest,
            "downloaded_at": "",
            "threshold": threshold,
            "csv_rows": csv_rows,
            "catalog_count": len(catalog),
            "topn": dict(TOPN),
        },
        "groups": groups,
        "tags": tags,
        "catalog": catalog,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)
    csv_path = args.csv if args.csv is not None else download(args.refresh)
    data = build(csv_path, load_curated(), threshold=args.threshold)
    data["source"]["downloaded_at"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    CATALOG_PATH.write_text(text, encoding="utf-8")
    curated_count = sum(1 for entry in data["tags"] if entry.get("rank", 0) == 0)
    bulk_count = len(data["tags"]) - curated_count
    print(
        f"catalogo: {len(data['tags'])} tags ({curated_count} curadas + "
        f"{bulk_count} top-N) -> {CATALOG_PATH}"
    )
    print(f"  catalog (posts>={args.threshold}): {data['source']['catalog_count']}")
    print(f"  sha256 csv: {data['source']['sha256']}")
    print(f"  tamano json: {CATALOG_PATH.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
