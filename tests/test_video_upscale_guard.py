"""Tests de guarda de dimensiones y VRAM para escalado de video (BUG-UPSCALER-01).

Verifica que el escalado de video valide la resolucion de entrada, resolucion
de salida (<= 2160p / 3840 px), presupuesto de fotogramas (<= 300 frames)
y presupuesto de memoria en batch (input <= 4 GiB, output <= 16 GiB) para
proteger la VRAM de 12 GB, tanto en el helper como en la ruta HTTP y runners.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import EngineConfig
from app.engine import EngineError
from app.server import create_app
from app.store import Store
from app.upscale import (
    MAX_VIDEO_UPSCALE_FRAMES,
    MAX_VIDEO_UPSCALE_INPUT_BYTES,
    MAX_VIDEO_UPSCALE_INPUT_SIDE,
    MAX_VIDEO_UPSCALE_OUTPUT_BYTES,
    MAX_VIDEO_UPSCALE_OUTPUT_SIDE,
    plan_video_chunks,
    probe_video_metadata,
    run_fps,
    run_video_upscale,
    validate_video_upscale_dimensions,
)


class TestPlanVideoChunks(unittest.TestCase):
    def test_1080p_240_frames_plan(self):
        plan = plan_video_chunks(
            {"width": 1920, "height": 1080, "frames": 240, "duration": 10.0, "fps": 24.0},
            scale=2,
        )
        self.assertEqual(plan["chunk_frames"], 150)
        self.assertEqual(plan["chunks"], 2)
        self.assertTrue(plan["needs_chunks"])

    def test_720p_350_frames_plan(self):
        plan = plan_video_chunks(
            {"width": 1280, "height": 720, "frames": 350, "duration": 12.0, "fps": 30.0},
            scale=2,
        )
        self.assertEqual(plan["chunk_frames"], 300)
        self.assertEqual(plan["chunks"], 2)

    def test_rife_reduces_chunk_frames(self):
        plan = plan_video_chunks(
            {"width": 1920, "height": 1080, "frames": 240, "duration": 10.0, "fps": 24.0},
            scale=2,
            rife_multiplier=2,
        )
        self.assertLess(plan["chunk_frames"], 150)
        self.assertGreaterEqual(plan["chunks"], 3)

    def test_fps_over_120_rejected(self):
        with self.assertRaises(EngineError):
            plan_video_chunks(
                {"width": 1280, "height": 720, "frames": 60, "duration": 0.5, "fps": 121.0},
                scale=2,
            )

    def test_total_space_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            plan_video_chunks(
                {"width": 1920, "height": 1080, "frames": 500, "duration": 20.0, "fps": 25.0},
                scale=2,
            )
        self.assertIn("tope", str(ctx.exception).lower())


class TestVideoUpscaleGuard(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmp_dir.name)
        self.dummy_video = self.test_dir / "dummy.mp4"
        self.dummy_video.write_bytes(b"fake mp4 header")

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("app.upscale.probe_video_metadata")
    def test_hd_video_scale_2_passes(self, mock_probe):
        """Video 720p con escala 2x debe pasar la validacion."""
        mock_probe.return_value = {
            "width": 1280,
            "height": 720,
            "frames": 120,
            "duration": 5.0,
            "fps": 24.0,
        }
        meta = validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertEqual(meta["width"], 1280)
        self.assertEqual(meta["height"], 720)

    @patch("app.upscale.probe_video_metadata")
    def test_1080p_video_scale_2_passes(self, mock_probe):
        """Video 1080p x2 con 120 frames debe pasar (input ~2.99 GiB, output ~11.9 GiB)."""
        mock_probe.return_value = {
            "width": 1920,
            "height": 1080,
            "frames": 120,
            "duration": 5.0,
            "fps": 24.0,
        }
        meta = validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertEqual(meta["width"], 1920)
        self.assertEqual(meta["frames"], 120)

    @patch("app.upscale.probe_video_metadata")
    def test_1080p_video_scale_2_splits_240_frames(self, mock_probe):
        """1080p x2 con 240 frames ya no se rechaza: se planifica en tramos de 150."""
        mock_probe.return_value = {
            "width": 1920,
            "height": 1080,
            "frames": 240,
            "duration": 10.0,
            "fps": 24.0,
        }
        meta = validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertEqual(meta["chunks"], 2)
        self.assertEqual(meta["chunk_frames"], 150)
        self.assertTrue(meta["needs_chunks"])

    @patch("app.upscale.probe_video_metadata")
    def test_1080p_video_scale_4_rejected(self, mock_probe):
        """Video 1080p con escala 4x (salida 7680x4320 / 8K) debe ser rechazado."""
        mock_probe.return_value = {
            "width": 1920,
            "height": 1080,
            "frames": 120,
            "duration": 5.0,
            "fps": 24.0,
        }
        with self.assertRaises(EngineError) as ctx:
            validate_video_upscale_dimensions(self.dummy_video, scale=4)
        self.assertIn("supera el limite de salida permitido", str(ctx.exception))
        self.assertIn(str(MAX_VIDEO_UPSCALE_OUTPUT_SIDE), str(ctx.exception))

    @patch("app.upscale.probe_video_metadata")
    def test_2k_input_video_rejected(self, mock_probe):
        """Video 2K / 1440p (2560x1440) de entrada debe ser rechazado antes de escalar."""
        mock_probe.return_value = {
            "width": 2560,
            "height": 1440,
            "frames": 120,
            "duration": 5.0,
            "fps": 24.0,
        }
        with self.assertRaises(EngineError) as ctx:
            validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertIn("demasiado grande para escalar", str(ctx.exception))
        self.assertIn(str(MAX_VIDEO_UPSCALE_INPUT_SIDE), str(ctx.exception))

    @patch("app.upscale.probe_video_metadata")
    def test_excessive_frames_splits_into_chunks(self, mock_probe):
        """350 frames en 640x360 se planifican en 2 tramos, no se rechazan."""
        mock_probe.return_value = {
            "width": 640,
            "height": 360,
            "frames": 350,
            "duration": 14.5,
            "fps": 24.0,
        }
        meta = validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertEqual(meta["chunks"], 2)
        self.assertEqual(meta["chunk_frames"], 300)

    @patch("app.upscale.probe_video_metadata")
    def test_500_frames_1080p_rejected_by_total_space(self, mock_probe):
        """500 frames a 1080p superan el tope global de espacio (45 GiB)."""
        mock_probe.return_value = {
            "width": 1920,
            "height": 1080,
            "frames": 500,
            "duration": 20.0,
            "fps": 25.0,
        }
        with self.assertRaises(EngineError) as ctx:
            validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertIn("tope", str(ctx.exception).lower())

    @patch("app.upscale.probe_video_metadata")
    def test_240_frames_1920x1920_splits(self, mock_probe):
        """1920x1920 x2 se limita por bytes de salida y se parte en tramos."""
        mock_probe.return_value = {
            "width": 1920,
            "height": 1920,
            "frames": 240,
            "duration": 10.0,
            "fps": 24.0,
        }
        meta = validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertLess(meta["chunk_frames"], 300)
        self.assertGreaterEqual(meta["chunks"], 2)

    @patch("app.upscale.probe_video_metadata")
    def test_fps_over_120_rejected(self, mock_probe):
        mock_probe.return_value = {
            "width": 1280,
            "height": 720,
            "frames": 60,
            "duration": 0.4,
            "fps": 150.0,
        }
        with self.assertRaises(EngineError) as ctx:
            validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertIn("120", str(ctx.exception))

    @patch("app.upscale.probe_video_metadata")
    def test_duration_over_600_rejected(self, mock_probe):
        mock_probe.return_value = {
            "width": 640,
            "height": 360,
            "frames": 15000,
            "duration": 601.0,
            "fps": 25.0,
        }
        with self.assertRaises(EngineError) as ctx:
            validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertIn("600", str(ctx.exception))

    @patch("app.upscale.probe_video_metadata")
    def test_unknown_frames_with_duration_fps_calculated(self, mock_probe):
        """Si meta['frames'] es 0, debe calcular round(duration*fps) y pasar si no excede limites."""
        mock_probe.return_value = {
            "width": 1280,
            "height": 720,
            "frames": 0,
            "duration": 5.0,
            "fps": 24.0,
        }
        meta = validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertEqual(meta["frames"], 120)

    @patch("app.upscale.probe_video_metadata")
    def test_unknown_frames_with_invalid_duration_rejected(self, mock_probe):
        """Si meta['frames'] es 0 y duration*fps resulta 0, debe rechazarse con EngineError claro."""
        mock_probe.return_value = {
            "width": 1280,
            "height": 720,
            "frames": 0,
            "duration": 0.0,
            "fps": 0.0,
        }
        with self.assertRaises(EngineError) as ctx:
            validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertIn("no se pudo determinar el numero de fotogramas", str(ctx.exception).lower())

    @patch("app.upscale.probe_video_metadata")
    def test_zero_metadata_rejected(self, mock_probe):
        """Si width<=0 o height<=0, debe rechazarse inmediatamente con EngineError claro."""
        mock_probe.return_value = {
            "width": 0,
            "height": 0,
            "frames": 0,
            "duration": 0.0,
            "fps": 0.0,
        }
        with self.assertRaises(EngineError) as ctx:
            validate_video_upscale_dimensions(self.dummy_video, scale=2)
        self.assertIn("no se pudieron leer las dimensiones", str(ctx.exception).lower())

    def test_probe_fails_closed_and_logs_warning(self):
        """probe_video_metadata devuelve ceros y emite warning si las sondas fallan; la validacion falla cerrada."""
        with patch("app.upscale.subprocess.run", side_effect=OSError("ffprobe missing")), \
             patch.dict("sys.modules", {"cv2": None, "av": None}):
            with self.assertLogs("app.upscale", level="WARNING") as log_cm:
                meta = probe_video_metadata(self.dummy_video)
            self.assertEqual(meta["width"], 0)
            self.assertEqual(meta["height"], 0)
            self.assertTrue(any("no se pudieron sondear metadatos" in msg.lower() for msg in log_cm.output))

            # Falla cerrada en la validacion
            with self.assertRaises(EngineError) as ctx:
                validate_video_upscale_dimensions(self.dummy_video)
            self.assertIn("no se pudieron leer las dimensiones", str(ctx.exception).lower())

    @patch("app.upscale.subprocess.run")
    def test_probe_video_metadata_with_ffprobe(self, mock_run):
        """probe_video_metadata debe parsear la salida JSON de ffprobe."""
        ffprobe_json = {
            "streams": [
                {
                    "width": 1280,
                    "height": 720,
                    "nb_frames": "150",
                    "duration": "6.25",
                    "r_frame_rate": "24/1",
                }
            ]
        }
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(ffprobe_json)
        mock_run.return_value = mock_proc

        meta = probe_video_metadata(self.dummy_video, ffprobe_bin="mock_ffprobe")
        self.assertEqual(meta["width"], 1280)
        self.assertEqual(meta["height"], 720)
        self.assertEqual(meta["frames"], 150)
        self.assertEqual(meta["fps"], 24.0)

    @patch("app.upscale.validate_video_upscale_dimensions")
    def test_run_video_upscale_invokes_guard(self, mock_guard):
        """run_video_upscale debe invocar la guarda si el archivo de video existe."""
        mock_guard.side_effect = EngineError("guardia activada: video sobredimensionado")

        comfy_input = self.test_dir / "input"
        comfy_input.mkdir(parents=True, exist_ok=True)
        video_file = comfy_input / "input_vid.mp4"
        video_file.write_bytes(b"content")

        mock_config = MagicMock()
        mock_config.comfy_input_dir = comfy_input
        mock_config.comfy_root = self.test_dir

        job = {
            "gen_id": 999,
            "video_name": "input_vid.mp4",
            "model": "esrgan_2x",
            "scale": 2,
            "model_file": "RealESRGAN_x2.pth",
        }

        record = {"status": "queued"}
        run_video_upscale(job, config=mock_config, store=MagicMock(), record=record)
        self.assertIn("guardia activada", job.get("error", ""))
        self.assertEqual(record.get("status"), "error")
        mock_guard.assert_called_once()

    @patch("app.upscale.validate_video_upscale_dimensions")
    def test_run_fps_invokes_guard_and_rejects_oversized(self, mock_guard):
        """run_fps debe invocar la guarda (scale=2) y registrar error si el video es sobredimensionado."""
        mock_guard.side_effect = EngineError("guardia fps activada: video excede memoria")

        comfy_input = self.test_dir / "input"
        comfy_input.mkdir(parents=True, exist_ok=True)
        video_file = comfy_input / "fps_input.mp4"
        video_file.write_bytes(b"content")

        mock_config = MagicMock()
        mock_config.comfy_input_dir = comfy_input
        mock_config.comfy_root = self.test_dir

        job = {
            "gen_id": 1001,
            "video_name": "fps_input.mp4",
            "ckpt_name": "rife49.pth",
            "multiplier": 2,
        }

        record = {"status": "queued"}
        run_fps(job, config=mock_config, store=MagicMock(), record=record)
        self.assertIn("guardia fps activada", job.get("error", ""))
        self.assertEqual(record.get("status"), "error")
        mock_guard.assert_called_once_with(video_file, scale=2, model_file=None, rife_multiplier=2)

    def test_route_accepts_local_video_b64(self):
        """W15: /api/upscale acepta un video local y crea una generacion kind=video."""
        config = EngineConfig(
            comfy_root=self.test_dir / "comfy",
            comfy_url="http://127.0.0.1:1",
            data_dir=self.test_dir / "data",
        )
        config.data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(config.data_dir / "waifu.db")
        store.init()
        app = create_app(config=config, store=store, start_worker=False)
        video_b64 = base64.b64encode(b"dummy-local-video").decode("ascii")
        with patch(
            "app.routes.upscale.resolve_upscale_model_file",
            return_value="RealESRGAN_x2.pth",
        ), patch("app.routes.upscale.validate_video_upscale_dimensions") as mock_val:
            mock_val.return_value = {
                "chunks": 1,
                "chunk_frames": 300,
                "needs_chunks": False,
                "frames": 24,
                "fps": 24.0,
                "duration": 1.0,
            }
            with TestClient(app) as client:
                res = client.post(
                    "/api/upscale",
                    json={
                        "kind": "video",
                        "video_b64": video_b64,
                        "filename": "clip.mp4",
                        "model": "real-esrgan-x2",
                    },
                )
        self.assertEqual(res.status_code, 200, res.text)
        job_id = res.json().get("job_id")
        job = app.state.jobs.get(job_id)
        self.assertIsNotNone(job)
        gen_id = job["source_gen"]
        local_file = config.data_dir / "gallery" / str(gen_id) / f"local_{gen_id}.mp4"
        self.assertTrue(local_file.is_file())

    def test_plan_route_returns_chunks(self):
        """W15: /api/upscale/plan devuelve el plan sin encolar."""
        config = EngineConfig(
            comfy_root=self.test_dir / "comfy",
            comfy_url="http://127.0.0.1:1",
            data_dir=self.test_dir / "data",
        )
        config.data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(config.data_dir / "waifu.db")
        store.init()
        gen_id = store.add("wan", "clip", "neg", {}, kind="video")
        gal_dir = config.data_dir / "gallery" / str(gen_id)
        gal_dir.mkdir(parents=True, exist_ok=True)
        (gal_dir / "clip.mp4").write_bytes(b"dummy")
        store.update(gen_id, status="done", outputs=["clip.mp4"], kind="video")
        app = create_app(config=config, store=store, start_worker=False)
        plan = {
            "width": 1920,
            "height": 1080,
            "frames": 240,
            "duration": 10.0,
            "fps": 24.0,
            "chunk_frames": 150,
            "chunks": 2,
            "needs_chunks": True,
            "estimated_output_gb": 23.9,
        }
        with patch(
            "app.routes.upscale.resolve_upscale_model_file",
            return_value="RealESRGAN_x2.pth",
        ), patch(
            "app.routes.upscale.validate_video_upscale_dimensions",
            return_value=plan,
        ):
            with TestClient(app) as client:
                res = client.post(
                    "/api/upscale/plan",
                    json={"kind": "video", "source_gen": gen_id, "model": "real-esrgan-x2"},
                )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("chunks"), 2)

    def test_fps_route_rejects_oversized_video(self):
        """La ruta /api/upscale con kind=fps debe validar dimensiones y rechazar video sobredimensionado con HTTP 400."""
        config = EngineConfig(
            comfy_root=self.test_dir / "comfy",
            comfy_url="http://127.0.0.1:1",
            data_dir=self.test_dir / "data",
        )
        config.data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(config.data_dir / "waifu.db")
        store.init()
        gen_id = store.add("video", "test prompt", "neg", {}, kind="video")
        gal_dir = config.data_dir / "gallery" / str(gen_id)
        gal_dir.mkdir(parents=True, exist_ok=True)
        clip_path = gal_dir / "clip.mp4"
        clip_path.write_bytes(b"dummy mp4")
        store.update(gen_id, status="done", outputs=["clip.mp4"])

        app = create_app(
            config=config,
            store=store,
            start_worker=False,
        )

        with patch("app.routes.upscale.validate_video_upscale_dimensions") as mock_val:
            mock_val.side_effect = EngineError("El presupuesto de memoria de entrada supera el maximo permitido")
            with TestClient(app) as client:
                res = client.post(
                    "/api/upscale",
                    json={
                        "kind": "fps",
                        "source_gen": gen_id,
                        "multiplier": 2,
                        "ckpt": "rife49.pth",
                    },
                )
                self.assertEqual(res.status_code, 400)
                self.assertIn("presupuesto de memoria", res.json().get("error", "").lower())
                mock_val.assert_called_once()


if __name__ == "__main__":
    unittest.main()
