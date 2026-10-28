"""C-27 — Extrae esqueletos COCO-17 de pose-db-01 con Ultralytics YOLOv8n-pose (CPU).

Procesa secuencialmente los PNG de ``pose-db-01/poses/img`` con YOLOv8n-pose en
CPU y genera ``static/pose-skeletons.json`` con 17 keypoints COCO
normalizados (x, y, confidence) y la bbox normalizada de la persona principal.

Reglas:
- No descarga modelos: requiere ``yolov8n-pose.pt`` ya presente en disco
  (``--model``, variable ``WAIFU_YOLO_POSE`` o ``E:\\IA\\yolov8n-pose.pt``).
- No escribe en ``data/`` ni toca pesos; solo lee imágenes/metadatos y escribe
  el JSON de salida (escritura atómica vía archivo temporal).
- Si una imagen no se puede abrir, procesar o no tiene detección, se guarda
  ``bbox``/``keypoints`` = null con ``motivo`` y se continúa.

Uso:
    .venv\\Scripts\\python.exe scripts\\extract_pose_skeletons.py
    .venv\\Scripts\\python.exe scripts\\extract_pose_skeletons.py --model E:\\IA\\yolov8n-pose.pt --limit 10
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path

# Evita cualquier intento de red/descarga de Ultralytics (assets, fuentes, telemetría).
os.environ.setdefault("YOLO_OFFLINE", "1")
os.environ.setdefault("YOLO_VERBOSE", "False")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(r"E:\IA\preservacion\pose-db-01")
DEFAULT_OUT = ROOT / "static" / "pose-skeletons.json"
DEFAULT_MODEL = Path(r"E:\IA\yolov8n-pose.pt")
PROGRESS_EVERY = 25
NUM_KEYPOINTS = 17
SCHEMA_VERSION = 2
DEVICE = "cpu"
CONF = 0.05
IMGSZ = 640

ATTRIBUTION = (
    "Poses de referencia: AI Pose Gallery (https://ai-pose-gallery.pages.dev). "
    "El autor publicó la colección como gratuita, con uso comercial, edición y uso "
    "secundario permitidos. Este archivo contiene solo keypoints derivados "
    "(YOLOv8n-pose, COCO-17); no redistribuye las imágenes originales."
)

KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]

# Conexiones COCO-17 (índices sobre KEYPOINT_NAMES) para dibujar el esqueleto.
SKELETON = [
    [15, 13], [13, 11], [16, 14], [14, 12], [11, 12],
    [5, 11], [6, 12], [5, 6], [5, 7], [6, 8], [7, 9], [8, 10],
    [1, 2], [0, 1], [0, 2], [1, 3], [2, 4], [3, 5], [4, 6],
]


def _log(msg: str) -> None:
    print(msg, flush=True)


def _basename(value: object) -> str:
    """Nombre de archivo a partir de 'img/x.png' o 'poses\\img\\x.png'."""
    if not value:
        return ""
    return str(value).replace("\\", "/").rsplit("/", 1)[-1].strip()


def load_metadata(meta_path: Path) -> dict[str, dict]:
    """Indexa poses.json por nombre de archivo (campo archivo / ruta_local)."""
    with meta_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, dict):
        raw = raw.get("poses") or raw.get("items") or []
    index: dict[str, dict] = {}
    duplicates = 0
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        names = {_basename(entry.get("archivo")), _basename(entry.get("ruta_local"))}
        names.discard("")
        for name in names:
            key = name.lower()
            if key in index and index[key] is not entry:
                duplicates += 1
                continue
            index[key] = entry
    if duplicates:
        _log(f"[WARN] {duplicates} nombres de archivo duplicados en metadatos; se usa el primero.")
    return index


def build_model(model_path: Path):
    try:
        from ultralytics import YOLO
    except Exception as exc:  # pragma: no cover - entorno
        raise SystemExit(f"[ERROR] No se pudo importar ultralytics: {exc}")
    return YOLO(str(model_path), task="pose")


def load_bgr(path: Path):
    """Abre el PNG, aplana transparencia sobre blanco y devuelve ndarray BGR uint8."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as img:
        img.load()
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, (255, 255, 255))
            canvas.paste(rgba, mask=rgba.split()[-1])
            rgb = canvas
        else:
            rgb = img.convert("RGB")
        width, height = rgb.size
        arr = np.asarray(rgb, dtype=np.uint8)[:, :, ::-1]  # RGB -> BGR (convención Ultralytics)
    return np.ascontiguousarray(arr), width, height


def _r(value: object, nd: int = 5) -> float:
    try:
        return round(float(value), nd)
    except (TypeError, ValueError):
        return 0.0


def extract_pose(model, path: Path) -> tuple[list | None, dict | None, str | None, dict]:
    """Devuelve (keypoints, bbox, motivo, extra).

    keypoints = 17 x [x, y, confidence] normalizados (0..1 respecto a la imagen).
    bbox = {"x1","y1","x2","y2","conf"} normalizada. Se elige la detección de
    mayor confianza.
    """
    extra: dict = {}
    try:
        image, width, height = load_bgr(path)
    except Exception as exc:
        return None, None, f"error_abrir_imagen: {type(exc).__name__}: {exc}", extra
    extra["width"], extra["height"] = width, height

    try:
        results = model.predict(
            source=image, device=DEVICE, conf=CONF, imgsz=IMGSZ,
            verbose=False, save=False, stream=False,
        )
    except Exception as exc:
        return None, None, f"error_yolo: {type(exc).__name__}: {exc}", extra

    if not results:
        return None, None, "sin_resultado", extra
    res = results[0]
    boxes = getattr(res, "boxes", None)
    kpts = getattr(res, "keypoints", None)
    if boxes is None or len(boxes) == 0:
        return None, None, "sin_persona_detectada", extra
    if kpts is None or getattr(kpts, "xyn", None) is None or len(kpts.xyn) == 0:
        return None, None, "sin_keypoints", extra

    box_conf = boxes.conf.cpu().numpy()
    best = int(box_conf.argmax())
    xyn = kpts.xyn[best].cpu().numpy()
    if xyn.shape[0] != NUM_KEYPOINTS:
        return None, None, f"keypoints_inesperados: {xyn.shape[0]}", extra
    kconf = kpts.conf[best].cpu().numpy() if kpts.conf is not None else None

    keypoints = [
        [_r(xyn[j][0]), _r(xyn[j][1]), _r(kconf[j] if kconf is not None else 0.0, 4)]
        for j in range(NUM_KEYPOINTS)
    ]
    x1, y1, x2, y2 = boxes.xyxyn[best].cpu().numpy().tolist()
    bbox = {"x1": _r(x1), "y1": _r(y1), "x2": _r(x2), "y2": _r(y2), "conf": _r(box_conf[best], 4)}
    if len(boxes) > 1:
        extra["personas_detectadas"] = int(len(boxes))
    return keypoints, bbox, None, extra


def _guard_output(out_path: Path) -> None:
    resolved = out_path.resolve()
    forbidden = (ROOT / "data").resolve()
    if resolved == forbidden or forbidden in resolved.parents:
        raise SystemExit(f"[ERROR] Salida dentro de data/ no permitida: {resolved}")


def write_json_atomic(out_path: Path, payload: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    os.replace(tmp, out_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="C-27: extrae esqueletos COCO-17 (YOLOv8n-pose, CPU) de pose-db-01.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="Raíz de pose-db-01.")
    ap.add_argument("--meta", type=Path, default=None, help="poses.json (por defecto <db>/_meta/poses.json).")
    ap.add_argument("--img-dir", type=Path, default=None, help="Carpeta PNG (por defecto <db>/poses/img).")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON de salida.")
    ap.add_argument(
        "--model", type=Path, default=Path(os.environ.get("WAIFU_YOLO_POSE") or DEFAULT_MODEL),
        help="Modelo local yolov8n-pose.pt (no se descarga). También WAIFU_YOLO_POSE.",
    )
    ap.add_argument("--limit", type=int, default=0, help="Procesar solo N imágenes (0 = todas).")
    return ap.parse_args(argv)


def _empty_record(meta: dict | None, image_name: str, motivo: str) -> dict:
    meta = meta or {}
    return {
        "id": meta.get("id") or Path(image_name).stem,
        "sistema_es": meta.get("sistema_es"),
        "clase_es": meta.get("clase_es"),
        "angulo_es": meta.get("angulo_es"),
        "archivo": meta.get("archivo") or f"img/{image_name}",
        "imagen": image_name,
        "bbox": None,
        "keypoints": None,
        "motivo": motivo,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db: Path = args.db
    meta_path: Path = args.meta or (db / "_meta" / "poses.json")
    img_dir: Path = args.img_dir or (db / "poses" / "img")
    out_path: Path = args.out
    model_path = Path(args.model)

    _guard_output(out_path)
    if not meta_path.is_file():
        _log(f"[ERROR] No existe metadatos: {meta_path}")
        return 2
    if not img_dir.is_dir():
        _log(f"[ERROR] No existe carpeta de imágenes: {img_dir}")
        return 2
    if not model_path.is_file():
        _log(f"[ERROR] Modelo no encontrado: {model_path} (este script no descarga modelos).")
        return 2

    meta_index = load_metadata(meta_path)
    pngs = sorted((p for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"),
                  key=lambda p: p.name.lower())
    if args.limit and args.limit > 0:
        pngs = pngs[: args.limit]
    total = len(pngs)
    _log(f"[INFO] Metadatos: {len(meta_index)} archivos indexados | PNG a procesar: {total}")
    _log(f"[INFO] Modelo: {model_path} | device={DEVICE} conf={CONF} imgsz={IMGSZ}")

    model = build_model(model_path)
    poses_out: list[dict] = []
    errors: list[dict] = []
    stats = {"con_pose": 0, "sin_pose": 0, "errores": 0, "sin_metadatos": 0}
    seen: set[str] = set()
    t0 = time.monotonic()

    for i, png in enumerate(pngs, start=1):
        key = png.name.lower()
        seen.add(key)
        meta = meta_index.get(key)
        if meta is None:
            stats["sin_metadatos"] += 1
        keypoints, bbox, motivo, extra = extract_pose(model, png)

        record = _empty_record(meta, png.name, motivo or "")
        record["bbox"] = bbox
        record["keypoints"] = keypoints
        if extra.get("width"):
            record["width"] = extra["width"]
            record["height"] = extra["height"]
        if extra.get("personas_detectadas"):
            record["personas_detectadas"] = extra["personas_detectadas"]
        if meta is None:
            record["sin_metadatos"] = True
        if keypoints is None:
            if motivo and motivo.startswith("error_"):
                stats["errores"] += 1
                errors.append({"imagen": png.name, "error": motivo})
                _log(f"[WARN] {png.name}: {motivo}")
            else:
                stats["sin_pose"] += 1
        else:
            record.pop("motivo", None)
            stats["con_pose"] += 1
        poses_out.append(record)

        if i % PROGRESS_EVERY == 0 or i == total:
            elapsed = time.monotonic() - t0
            _log(
                f"[{i}/{total}] con_pose={stats['con_pose']} sin_pose={stats['sin_pose']} "
                f"errores={stats['errores']} ({elapsed:.1f}s)"
            )

    # Entradas de metadatos cuyo PNG no está en la carpeta (solo si se procesó todo).
    if not (args.limit and args.limit > 0):
        missing: dict[str, dict] = {}
        for key, entry in meta_index.items():
            if key in seen:
                continue
            ident = entry.get("id") or key
            if ident in missing:
                continue
            name = _basename(entry.get("archivo") or entry.get("ruta_local"))
            missing[ident] = _empty_record(entry, name, "archivo_no_encontrado")
        if missing:
            _log(f"[WARN] {len(missing)} entradas de metadatos sin PNG en {img_dir}")
            poses_out.extend(missing.values())
            stats["archivo_no_encontrado"] = len(missing)

    payload = {
        "version": SCHEMA_VERSION,
        "generated": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "dataset": "pose-db-01",
            "url": "https://ai-pose-gallery.pages.dev",
            "metadata": "_meta/poses.json",
            "images": "poses/img",
            "extractor": "Ultralytics YOLOv8n-pose",
            "model": model_path.name,
            "device": DEVICE,
            "conf": CONF,
            "imgsz": IMGSZ,
        },
        "attribution": ATTRIBUTION,
        "count": len(poses_out),
        "stats": stats,
        "keypoint_format": ["x", "y", "confidence"],
        "keypoint_names": KEYPOINT_NAMES,
        "skeleton": SKELETON,
        "bbox_format": ["x1", "y1", "x2", "y2", "conf"],
        "errors": errors,
        "poses": poses_out,
    }
    write_json_atomic(out_path, payload)
    _log(
        f"[OK] {out_path} | count={len(poses_out)} con_pose={stats['con_pose']} "
        f"sin_pose={stats['sin_pose']} errores={stats['errores']} "
        f"({time.monotonic() - t0:.1f}s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
