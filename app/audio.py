"""Módulo de audio: generación condicional con MMAudio (Modo B) y API FastAPI.

Qué hace:
- Genera audio ambiental condicionado a los fotogramas de un clip de vídeo con MMAudio (Modo B).
- Hereda la duración del clip, estandariza a 48 kHz y reemplaza o mezcla con la pista existente.
- Guarda un WAV aparte (48 kHz) y un MP4 nuevo con la pista procesada; el clip original permanece intacto.
- Proporciona endpoints (/api/audio/*) y runner monohilo FIFO compatible con la cola de WaifuStudio.
- Irodori (TTS/voz) se expone deshabilitado con motivo transparente hasta su despliegue en :8291.

Dependencias: app.config, app.engine, app.progress, app.store, app.video, app.timeline.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.config import APP_ROOT
from app.engine import ComfyEngine, EngineError, JobCancelledError
from app.progress import ProgressTracker
from app.routes.jobs import _JOBS
from app.timeline import has_audio_stream
from app.video import WAN_AUDIO_NEGATIVE, WAN_AUDIO_POSITIVE, find_ffmpeg

logger = logging.getLogger(__name__)

AUDIO_DEFAULT_STEPS = 25
AUDIO_DEFAULT_CFG = 4.5
AUDIO_DEFAULT_SEED = 42
AUDIO_TARGET_SAMPLE_RATE = 48000
IRODORI_DISABLED_REASON = (
    "Irodori TTS no disponible todavía (requiere microservicio en localhost:8291 "
    "para síntesis de voz no verbal). Programado para C-17."
)

router = APIRouter(prefix="/api/audio", tags=["audio"])


def build_mmaudio_mode_b_graph(job: dict[str, Any]) -> dict[str, Any]:
    """Construye el grafo ComfyUI de MMAudio condicionado a frames (Modo B)."""
    video_path = str(job.get("video_path") or "").replace("\\", "/")
    if not video_path:
        raise EngineError("build_mmaudio_mode_b_graph requiere 'video_path'")

    duration = float(job.get("duration") or 5.0)
    fps = float(job.get("fps") or 16.0)
    seed = int(job.get("seed") if job.get("seed") is not None else AUDIO_DEFAULT_SEED)
    steps = int(job.get("steps") or AUDIO_DEFAULT_STEPS)
    cfg = float(job.get("cfg") or AUDIO_DEFAULT_CFG)
    prompt = str(job.get("prompt") or WAN_AUDIO_POSITIVE)
    negative = str(job.get("negative") or WAN_AUDIO_NEGATIVE)
    gen_id = job.get("gen_id", "audio")

    return {
        "1": {
            "class_type": "VHS_LoadVideoPath",
            "inputs": {
                "video": video_path,
                "force_rate": fps,
                "custom_width": 0,
                "custom_height": 0,
                "frame_load_cap": 0,
                "skip_first_frames": 0,
                "select_every_nth": 1,
            },
            "_meta": {"title": "Load Video (Path)"},
        },
        "2": {
            "class_type": "MMAudioModelLoader",
            "inputs": {
                "mmaudio_model": "mmaudio_large_44k_v2_fp16.safetensors",
                "base_precision": "fp16",
            },
            "_meta": {"title": "MMAudio Model Loader"},
        },
        "3": {
            "class_type": "MMAudioFeatureUtilsLoader",
            "inputs": {
                "vae_model": "mmaudio_vae_44k_fp16.safetensors",
                "synchformer_model": "mmaudio_synchformer_fp16.safetensors",
                "clip_model": "apple_DFN5B-CLIP-ViT-H-14-384_fp16.safetensors",
                "mode": "44k",
                "precision": "fp16",
            },
            "_meta": {"title": "MMAudio Feature Utils Loader"},
        },
        "4": {
            "class_type": "MMAudioSampler",
            "inputs": {
                "mmaudio_model": ["2", 0],
                "feature_utils": ["3", 0],
                "duration": duration,
                "steps": steps,
                "cfg": cfg,
                "seed": seed,
                "prompt": prompt,
                "negative_prompt": negative,
                "mask_away_clip": False,
                "force_offload": True,
                "images": ["1", 0],
            },
            "_meta": {"title": "MMAudio Sampler"},
        },
        "5": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["1", 0],
                "frame_rate": fps,
                "loop_count": 0,
                "filename_prefix": f"waifu/mmaudio_{gen_id}",
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
                "audio": ["4", 0],
            },
            "_meta": {"title": "Video Combine"},
        },
    }


def probe_clip_audio(video_path: Path, ffmpeg_bin: str | Path | None = None) -> dict[str, Any]:
    """Extrae duración, fps, dimensiones y presencia de pista de audio de un vídeo."""
    if not video_path.is_file():
        raise EngineError(f"Clip de vídeo no encontrado: {video_path}")

    exe = str(ffmpeg_bin) if ffmpeg_bin else find_ffmpeg()
    ffprobe_exe = (
        (Path(exe).with_name("ffprobe.exe") if exe else None)
        or (APP_ROOT / "tools" / "ffmpeg" / "ffprobe.exe" if (APP_ROOT / "tools" / "ffmpeg" / "ffprobe.exe").is_file() else None)
        or shutil.which("ffprobe")
    )

    width, height, frames, duration, fps_val = 0, 0, 0, 5.0, 16.0
    has_audio = False

    if ffprobe_exe and Path(str(ffprobe_exe)).is_file():
        try:
            cmd = [
                str(ffprobe_exe),
                "-v", "error",
                "-show_entries", "stream=codec_type,width,height,nb_frames,duration,r_frame_rate",
                "-of", "json",
                str(video_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                streams = data.get("streams") or []
                for s in streams:
                    ctype = s.get("codec_type")
                    if ctype == "video" and width == 0:
                        width = int(s.get("width") or 0)
                        height = int(s.get("height") or 0)
                        frames = int(s.get("nb_frames") or 0)
                        dur = float(s.get("duration") or 0.0)
                        if dur > 0:
                            duration = dur
                        r_fps = s.get("r_frame_rate")
                        if r_fps and "/" in str(r_fps):
                            num, den = str(r_fps).split("/", 1)
                            fps_val = float(num) / float(den) if float(den) else 16.0
                        elif r_fps:
                            fps_val = float(r_fps)
                    elif ctype == "audio":
                        has_audio = True
        except Exception as exc:
            logger.warning("ffprobe fallo en probe_clip_audio: %s", exc)

    if has_audio is False and exe:
        try:
            has_audio = has_audio_stream(video_path, ffmpeg_bin=exe)
        except Exception:
            pass

    return {
        "width": width,
        "height": height,
        "frames": frames,
        "duration": round(duration, 3),
        "fps": round(fps_val, 2),
        "has_audio": has_audio,
        "path": str(video_path),
        "name": video_path.name,
    }


def extract_48k_wav(temp_video: Path, output_wav: Path, ffmpeg_bin: str | Path | None = None) -> None:
    """Extrae la pista de audio a WAV PCM de 16 bits y 48 kHz exactos."""
    exe = str(ffmpeg_bin) if ffmpeg_bin else find_ffmpeg()
    if not exe:
        raise EngineError("ffmpeg no encontrado para extraer WAV a 48 kHz")
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(exe), "-y",
        "-i", str(temp_video),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(AUDIO_TARGET_SAMPLE_RATE),
        str(output_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise EngineError(f"Error de FFmpeg al extraer WAV 48 kHz: {proc.stderr.strip()}")


def mux_video_audio(
    original_video: Path,
    wav_path: Path,
    output_mp4: Path,
    action: str = "replace",
    ffmpeg_bin: str | Path | None = None,
) -> None:
    """Muxea el vídeo original con la pista generada (reemplazar o mezclar a 48 kHz). El original no se toca."""
    exe = str(ffmpeg_bin) if ffmpeg_bin else find_ffmpeg()
    if not exe:
        raise EngineError("ffmpeg no encontrado para muxing de audio y vídeo")
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    can_mix = False
    if action == "mix":
        try:
            can_mix = has_audio_stream(original_video, ffmpeg_bin=exe)
        except Exception:
            can_mix = False

    if can_mix:
        cmd = [
            str(exe), "-y",
            "-i", str(original_video),
            "-i", str(wav_path),
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2,aresample=48000[aout]",
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_mp4),
        ]
    else:
        cmd = [
            str(exe), "-y",
            "-i", str(original_video),
            "-i", str(wav_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_mp4),
        ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise EngineError(f"Error de FFmpeg al ensamblar MP4 con audio: {proc.stderr.strip()}")


def run_audio_generation(
    job: dict[str, Any],
    *,
    config: Any,
    store: Any,
    engine_factory: Callable[[], Any],
    ws_factory: Any = None,
    record: dict[str, Any] | None = None,
) -> None:
    """Ejecuta el job de Audio Modo B: Grafo ComfyUI -> Engine -> Extracción 48 kHz -> Muxing -> Galería."""
    gen_id = job["gen_id"]
    if record is not None and record.get("status") == "cancelled":
        job["outputs"] = []
        job["error"] = None
        return

    tracker = None
    try:
        engine = engine_factory()
        if record is not None:
            record["engine"] = engine

        base_comfy = str(config.comfy_url).rstrip("/")
        ws_scheme = "wss://" if base_comfy.startswith("https://") else "ws://"
        host_part = base_comfy.split("://", 1)[-1]
        ws_url = f"{ws_scheme}{host_part}/ws"

        tracker = ProgressTracker(ws_url, engine.client_id, "", ws_factory=ws_factory)
        if record is not None:
            record["tracker"] = tracker
            record["status"] = "running"
        tracker.start()

        gallery_dir = config.data_dir / "gallery" / str(gen_id)
        gallery_dir.mkdir(parents=True, exist_ok=True)

        graph = build_mmaudio_mode_b_graph(job)
        prompt_id = engine.submit(graph)
        if record is not None:
            record["prompt_id"] = prompt_id
        tracker.prompt_id = prompt_id

        history = engine.wait(prompt_id)
        paths = engine.outputs(history, expected_ext=("mp4",))
        if not paths:
            raise EngineError(f"El engine no devolvió ningún clip para {prompt_id}")
        temp_comfy_mp4 = paths[0]

        original_video = Path(job["video_path"])
        action = str(job.get("action") or "replace").lower()

        wav_name = f"audio_{gen_id}.wav"
        mp4_name = f"video_audio_{gen_id}.mp4"
        wav_target = gallery_dir / wav_name
        mp4_target = gallery_dir / mp4_name

        extract_48k_wav(temp_comfy_mp4, wav_target)
        mux_video_audio(original_video, wav_target, mp4_target, action=action)

        try:
            temp_comfy_mp4.unlink(missing_ok=True)
        except OSError:
            pass

        names = [mp4_name, wav_name]
        store.update(gen_id, status="done", outputs=names, kind="audio")
        job["outputs"] = names
        job["error"] = None
        if record is not None:
            record["status"] = "done"

    except JobCancelledError:
        job["outputs"] = []
        job["error"] = None
        if record is not None:
            record["status"] = "cancelled"
        try:
            store.update(gen_id, status="cancelled", kind="audio")
        except Exception:
            pass
    except Exception as exc:
        job["outputs"] = []
        is_cancelled = (record is not None and record.get("status") == "cancelled") or (
            tracker is not None and getattr(tracker, "is_cancelled", False)
        )
        if is_cancelled:
            job["error"] = None
            if record is not None:
                record["status"] = "cancelled"
            try:
                store.update(gen_id, status="cancelled", kind="audio")
            except Exception:
                pass
        else:
            job["error"] = str(exc)
            if record is not None:
                record["status"] = "error"
            try:
                store.update(gen_id, status="error", error=str(exc))
            except Exception:
                pass
    finally:
        if tracker is not None:
            tracker.stop()


@router.get("/status")
async def api_audio_status() -> dict[str, Any]:
    """Reporta el estado del motor MMAudio y la no disponibilidad justificada de Irodori."""
    return {
        "mmaudio_installed": True,
        "sample_rate_hz": AUDIO_TARGET_SAMPLE_RATE,
        "irodori_installed": False,
        "irodori_reason": IRODORI_DISABLED_REASON,
    }


@router.get("/clips")
async def api_audio_clips(request: Request) -> list[dict[str, Any]]:
    """Lista clips de vídeo de la galería para selección rápida en Modo B."""
    st = request.app.state.store
    records = st.list(kind="video", limit=30)
    cfg = request.app.state.config
    clips: list[dict[str, Any]] = []

    for row in records:
        gid = row.get("id")
        outputs = row.get("outputs") or []
        for out in outputs:
            if str(out).lower().endswith((".mp4", ".webm")):
                file_path = cfg.data_dir / "gallery" / str(gid) / str(out)
                if file_path.is_file():
                    clips.append({
                        "gen_id": gid,
                        "name": out,
                        "path": str(file_path),
                        "url": f"/media/{gid}/{out}",
                        "created_at": row.get("created_at"),
                        "prompt": row.get("prompt"),
                    })
                    break
    return clips


@router.post("/probe")
async def api_audio_probe(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Inspecciona metadatos y duración de un clip para herencia en Modo B."""
    cfg = request.app.state.config
    video_path_str = payload.get("path")
    gen_id = payload.get("gen_id")

    target_path: Path | None = None
    if gen_id is not None:
        st = request.app.state.store
        gen = st.get(int(gen_id))
        if gen:
            outputs = gen.get("outputs") or []
            for out in outputs:
                if str(out).lower().endswith((".mp4", ".webm")):
                    cand = cfg.data_dir / "gallery" / str(gen_id) / str(out)
                    if cand.is_file():
                        target_path = cand
                        break
    elif video_path_str:
        cand = Path(video_path_str)
        if not cand.is_absolute():
            cand = cfg.comfy_input_dir / cand
        if cand.is_file():
            target_path = cand

    if not target_path or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo de vídeo no encontrado")

    meta = probe_clip_audio(target_path)
    return meta


@router.post("/generate")
async def api_audio_generate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Encola un trabajo de audio Modo B (MMAudio condicionado a frames)."""
    if payload.get("voice_enabled") or payload.get("engine_voice"):
        raise HTTPException(status_code=400, detail=IRODORI_DISABLED_REASON)

    cfg = request.app.state.config
    st = request.app.state.store
    queue = request.app.state.queue

    # Resolución de ruta de vídeo
    video_path_str = payload.get("video_path")
    source_gen_id = payload.get("source_gen_id")
    target_path: Path | None = None

    if source_gen_id is not None:
        gen = st.get(int(source_gen_id))
        if gen:
            outputs = gen.get("outputs") or []
            for out in outputs:
                if str(out).lower().endswith((".mp4", ".webm")):
                    cand = cfg.data_dir / "gallery" / str(source_gen_id) / str(out)
                    if cand.is_file():
                        target_path = cand
                        break
    elif video_path_str:
        cand = Path(video_path_str)
        if not cand.is_absolute():
            cand = cfg.comfy_input_dir / cand
        if cand.is_file():
            target_path = cand

    if not target_path or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Clip de vídeo no encontrado para Modo B")

    meta = probe_clip_audio(target_path)
    duration = float(payload.get("duration") or meta["duration"] or 5.0)
    fps = float(meta["fps"] or 16.0)

    prompt = str(payload.get("prompt") or WAN_AUDIO_POSITIVE)
    negative = str(payload.get("negative") or WAN_AUDIO_NEGATIVE)
    action = str(payload.get("action") or "replace").lower()
    if action not in ("replace", "mix"):
        action = "replace"

    seed = int(payload.get("seed") if payload.get("seed") is not None else AUDIO_DEFAULT_SEED)
    steps = int(payload.get("steps") or AUDIO_DEFAULT_STEPS)
    cfg_val = float(payload.get("cfg") or AUDIO_DEFAULT_CFG)

    stored_params = {
        "engine": "mmaudio",
        "mode": "b",
        "action": action,
        "duration": duration,
        "fps": fps,
        "steps": steps,
        "cfg": cfg_val,
        "seed": seed,
        "source_clip": target_path.name,
        "source_gen_id": source_gen_id,
        "sample_rate": AUDIO_TARGET_SAMPLE_RATE,
    }

    gen_id = st.add(
        "mmaudio",
        prompt,
        negative,
        stored_params,
        kind="audio",
    )

    job = {
        "gen_id": gen_id,
        "kind": "audio",
        "video_path": str(target_path),
        "duration": duration,
        "fps": fps,
        "prompt": prompt,
        "negative": negative,
        "action": action,
        "steps": steps,
        "cfg": cfg_val,
        "seed": seed,
        "params": stored_params,
    }

    _JOBS[gen_id] = {
        "prompt_id": None,
        "tracker": None,
        "status": "queued",
        "engine": None,
        "kind": "audio",
    }

    job_id = queue.submit(job)
    request.app.state.jobs[job_id] = job

    return {
        "job_id": job_id,
        "gen_id": gen_id,
        "duration": duration,
        "action": action,
        "sample_rate": AUDIO_TARGET_SAMPLE_RATE,
    }


@router.get("/media/{gen_id}/{name:path}")
async def api_audio_media(gen_id: int, name: str, request: Request) -> Any:
    """Sirve archivos generados (WAV o MP4) del directorio de galería correspondiente."""
    cfg = request.app.state.config
    target = (cfg.data_dir / "gallery" / str(gen_id) / name).resolve()
    base_dir = (cfg.data_dir / "gallery" / str(gen_id)).resolve()

    try:
        target.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta de archivo no permitida")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    suf = target.suffix.lower()
    media_type = "audio/wav" if suf == ".wav" else ("video/mp4" if suf == ".mp4" else "application/octet-stream")
    return FileResponse(target, media_type=media_type)
