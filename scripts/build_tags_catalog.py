"""Construye `registry/tags_danbooru.json` v2 desde el CSV de Danbooru (tagcomplete).

Conserva el catalogo curado (labels en espanol) y anade top-N por popularidad
en los grupos `general_top`, `character`, `series` y `artist` (`rank` = uso en
Danbooru). Uso:

    python scripts/build_tags_catalog.py [--refresh] [--csv PATH]
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
USER_AGENT = "WAIFU-tags-catalog/2.0 (+local)"


def download(refresh: bool) -> tuple[Path, str]:
    """Descarga el CSV a la cache (o la reutiliza) y devuelve (ruta, sha256)."""
    if refresh or not CACHE_PATH.is_file():
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(CSV_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
        CACHE_PATH.write_bytes(data)
    digest = hashlib.sha256(CACHE_PATH.read_bytes()).hexdigest().upper()
    return CACHE_PATH, digest


def load_curated() -> dict:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    groups = list(data["groups"])
    tags = list(data["tags"])
    for entry in tags:
        entry.setdefault("rank", 0)
    return {"groups": groups, "tags": tags}


def build(csv_path: Path, curated: dict) -> dict:
    seen = {entry["tag"].lower() for entry in curated["tags"]}
    buckets: dict[str, list[dict]] = {group: [] for group in ADDED_GROUPS}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) < 3:
                continue
            name = row[0].strip()
            group = CATEGORY_GROUP.get(row[1].strip())
            if not name or group is None:
                continue
            try:
                rank = int(row[2])
            except (TypeError, ValueError):
                continue
            if rank <= 0:
                continue
            tag = name.replace("_", " ")
            folded = tag.lower()
            if folded in seen:
                continue
            seen.add(folded)
            buckets[group].append(
                {"tag": tag, "label": tag, "group": group, "rank": rank}
            )
    added = 0
    for group in ADDED_GROUPS:
        entries = sorted(buckets[group], key=lambda item: item["rank"], reverse=True)
        curated["tags"].extend(entries[: TOPN[group]])
        added += len(entries[: TOPN[group]])
    curated["groups"].extend(ADDED_GROUPS)
    return {
        "schema_version": "tags-danbooru/v2",
        "descripcion": (
            "Catalogo Danbooru local (M10-5): base curada con labels es + top-N "
            "por popularidad en general_top/character/series/artist con rank de uso."
        ),
        "source": {
            "url": CSV_URL,
            "sha256": "",
            "downloaded_at": "",
            "topn": TOPN,
        },
        "groups": curated["groups"],
        "tags": curated["tags"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args()
    if args.csv is not None:
        csv_path = args.csv
        digest = hashlib.sha256(csv_path.read_bytes()).hexdigest().upper()
    else:
        csv_path, digest = download(args.refresh)
    data = build(csv_path, load_curated())
    data["source"]["sha256"] = digest
    data["source"]["downloaded_at"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    CATALOG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    counts = {}
    for entry in data["tags"]:
        counts[entry["group"]] = counts.get(entry["group"], 0) + 1
    print(f"catalogo: {len(data['tags'])} tags -> {CATALOG_PATH}")
    for group in data["groups"]:
        print(f"  {group}: {counts.get(group, 0)}")
    print(f"  sha256 csv: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
