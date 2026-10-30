"""Descarga el índice de poses (505 KB) para la instalación limpia."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.poses import PoseError, download_pose_index, pose_status  # noqa: E402


def main() -> int:
    data_dir = ROOT / "data"
    status = pose_status(data_dir)
    if status.get("installed"):
        print(f"poses: ya instalado ({status.get('count')} fichas)")
        return 0
    try:
        target = download_pose_index(data_dir)
    except (PoseError, OSError) as exc:
        print(f"poses: no se pudo descargar: {exc}", file=sys.stderr)
        return 1
    print(f"poses: instalado en {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
