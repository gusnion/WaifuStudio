"""Encadenado de segmentos de video MiniMax H3 (>15 s) y extraccion de frames.

Permite superar el limite de 15 segundos por generacion de H3:
1. Divide la duracion objetivo en segmentos certificados H3 (8, 10, 12 o 15 s).
2. Extrae el ultimo frame del segmento N como first_frame del segmento N+1.
3. Concatena los clips generados en un unico archivo MP4 coherente.
Usa cv2 (OpenCV ya instalado en el venv) para portabilidad total sin depender de ffmpeg en PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

import cv2

from app.engine import EngineError
from app.h3_presets import H3_FPS, H3_SECONDS


def extract_last_frame(video_path: str | Path, output_image_path: str | Path) -> Path:
    """Extrae el ultimo fotograma de un video y lo guarda como imagen PNG/JPEG."""
    vid = Path(video_path)
    out = Path(output_image_path)
    if not vid.is_file():
        raise EngineError(f"video no encontrado: {vid}")

    cap = cv2.VideoCapture(str(vid))
    if not cap.isOpened():
        raise EngineError(f"no se pudo abrir el video {vid}")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            raise EngineError(f"video sin frames legibles: {vid}")

        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - 1))
        ret, frame = cap.read()
        if not ret or frame is None:
            # Fallback: leer secuencialmente hasta el final si el seek falla
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            last_good = None
            while True:
                r, f = cap.read()
                if not r or f is None:
                    break
                last_good = f
            if last_good is None:
                raise EngineError(f"no se pudo extraer ningun frame de {vid}")
            frame = last_good

        out.parent.mkdir(parents=True, exist_ok=True)
        success = cv2.imwrite(str(out), frame)
        if not success:
            raise EngineError(f"error al guardar frame en {out}")
        return out
    finally:
        cap.release()


def concat_videos(
    video_paths: Sequence[str | Path],
    output_path: str | Path,
    fps: float = H3_FPS,
) -> Path:
    """Concatena una lista de videos MP4 en un unico archivo."""
    paths = [Path(p) for p in video_paths]
    out = Path(output_path)
    if not paths:
        raise EngineError("lista de videos a concatenar vacia")

    for p in paths:
        if not p.is_file():
            raise EngineError(f"archivo de video no existe para concatenar: {p}")

    out.parent.mkdir(parents=True, exist_ok=True)
    if len(paths) == 1:
        shutil.copyfile(paths[0], out)
        return out

    cap0 = cv2.VideoCapture(str(paths[0]))
    if not cap0.isOpened():
        raise EngineError(f"no se pudo abrir {paths[0]}")
    width = int(cap0.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap0.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap_fps = cap0.get(cv2.CAP_PROP_FPS) or fps
    cap0.release()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out), fourcc, cap_fps, (width, height))
    try:
        for p in paths:
            cap = cv2.VideoCapture(str(p))
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret or frame is None:
                    break
                writer.write(frame)
            cap.release()
    finally:
        writer.release()

    return out


def plan_chain_segments(total_seconds: int) -> list[int]:
    """Planifica la particion de segundos en bloques validos de H3 (5, 8, 10, 12, 15)."""
    if total_seconds in H3_SECONDS:
        return [total_seconds]
    if total_seconds <= 0:
        raise EngineError(f"segundos invalidos: {total_seconds}")

    # Para > 15 s, descomponer en bloques equilibrados de la lista de H3
    segments: list[int] = []
    rem = total_seconds
    while rem > 0:
        # Elegir el bloque mas cercano menor o igual
        candidates = [s for s in (15, 12, 10, 8, 5) if s <= rem]
        if candidates:
            chosen = candidates[0]
            segments.append(chosen)
            rem -= chosen
        else:
            # Si el remanente es < 5, ajustar el ultimo segmento
            if segments:
                segments[-1] = min(15, segments[-1] + rem)
            else:
                segments.append(5)
            rem = 0
    return segments


__all__ = ["concat_videos", "extract_last_frame", "plan_chain_segments"]
