"""Tests unitarios offline para AUDIO Modo B con MMAudio (C-16).

Verifica:
- Construcción y conexiones del grafo ComfyUI (VHS_LoadVideoPath -> MMAudioSampler -> VHS_VideoCombine).
- Herencia de duración y estandarización a 48 kHz.
- Comandos FFmpeg para reemplazar pista y mezclar con pista existente preservando el original.
- Rechazo explícito con motivo si se solicita síntesis de voz (Irodori deshabilitado).
- Endpoints de status y validación en la API FastAPI.
- Runner monohilo FIFO (run_audio_generation) con actualización de outputs en Store.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.audio import (
    AUDIO_TARGET_SAMPLE_RATE,
    IRODORI_DISABLED_REASON,
    build_mmaudio_mode_b_graph,
    extract_48k_wav,
    mux_video_audio,
    probe_clip_audio,
    run_audio_generation,
)
from app.config import EngineConfig
from app.engine import EngineError
from app.server import create_app
from app.store import Store

_OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    negative TEXT DEFAULT '',
    params TEXT DEFAULT '{}',
    status TEXT NOT NULL,
    outputs TEXT DEFAULT '[]',
    error TEXT,
    kind TEXT NOT NULL DEFAULT 'image'
)
"""


class TestAudioGraph(unittest.TestCase):
    """Comprueba la coherencia del grafo de ComfyUI para MMAudio Modo B."""

    def test_build_mmaudio_mode_b_graph_success(self) -> None:
        job = {
            "gen_id": 999,
            "video_path": "C:/fake/path/clip.mp4",
            "duration": 5.06,
            "fps": 16.0,
            "seed": 12345,
            "steps": 25,
            "cfg": 4.5,
            "prompt": "soft breathing, quiet moans",
            "negative": "speech, crowd",
        }
        graph = build_mmaudio_mode_b_graph(job)

        self.assertIn("1", graph)
        self.assertIn("2", graph)
        self.assertIn("3", graph)
        self.assertIn("4", graph)
        self.assertIn("5", graph)

        # Nodo 1: VHS_LoadVideoPath
        n1 = graph["1"]
        self.assertEqual(n1["class_type"], "VHS_LoadVideoPath")
        self.assertEqual(n1["inputs"]["video"], "C:/fake/path/clip.mp4")
        self.assertEqual(n1["inputs"]["force_rate"], 16.0)

        # Nodo 2: MMAudioModelLoader
        n2 = graph["2"]
        self.assertEqual(n2["class_type"], "MMAudioModelLoader")
        self.assertEqual(n2["inputs"]["mmaudio_model"], "mmaudio_large_44k_v2_fp16.safetensors")

        # Nodo 3: MMAudioFeatureUtilsLoader
        n3 = graph["3"]
        self.assertEqual(n3["class_type"], "MMAudioFeatureUtilsLoader")
        self.assertEqual(n3["inputs"]["mode"], "44k")

        # Nodo 4: MMAudioSampler
        n4 = graph["4"]
        self.assertEqual(n4["class_type"], "MMAudioSampler")
        self.assertEqual(n4["inputs"]["mmaudio_model"], ["2", 0])
        self.assertEqual(n4["inputs"]["feature_utils"], ["3", 0])
        self.assertEqual(n4["inputs"]["images"], ["1", 0])
        self.assertEqual(n4["inputs"]["duration"], 5.06)
        self.assertEqual(n4["inputs"]["steps"], 25)
        self.assertEqual(n4["inputs"]["cfg"], 4.5)
        self.assertEqual(n4["inputs"]["seed"], 12345)
        self.assertEqual(n4["inputs"]["prompt"], "soft breathing, quiet moans")
        self.assertEqual(n4["inputs"]["negative_prompt"], "speech, crowd")

        # Nodo 5: VHS_VideoCombine
        n5 = graph["5"]
        self.assertEqual(n5["class_type"], "VHS_VideoCombine")
        self.assertEqual(n5["inputs"]["images"], ["1", 0])
        self.assertEqual(n5["inputs"]["audio"], ["4", 0])
        self.assertEqual(n5["inputs"]["frame_rate"], 16.0)
        self.assertEqual(n5["inputs"]["format"], "video/h264-mp4")

    def test_build_graph_missing_video_path_raises(self) -> None:
        with self.assertRaises(EngineError):
            build_mmaudio_mode_b_graph({"gen_id": 1})


class TestAudioFFmpegCommands(unittest.TestCase):
    """Verifica las llamadas FFmpeg: muestreo a 48 kHz y modos reemplazar/mezclar."""

    def test_target_sample_rate_is_48k(self) -> None:
        self.assertEqual(AUDIO_TARGET_SAMPLE_RATE, 48000)

    @patch("subprocess.run")
    def test_extract_48k_wav_invokes_correct_args(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as td:
            temp_vid = Path(td) / "temp.mp4"
            temp_vid.write_bytes(b"dummy")
            out_wav = Path(td) / "out.wav"

            extract_48k_wav(temp_vid, out_wav, ffmpeg_bin="ffmpeg")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]

            self.assertEqual(args[0], "ffmpeg")
            self.assertIn("-vn", args)
            self.assertIn("-acodec", args)
            self.assertIn("pcm_s16le", args)
            self.assertIn("-ar", args)
            self.assertIn("48000", args)
            self.assertEqual(args[-1], str(out_wav))

    @patch("subprocess.run")
    def test_mux_video_audio_replace_invokes_correct_args(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as td:
            orig_vid = Path(td) / "orig.mp4"
            orig_vid.write_bytes(b"original-video-data")
            wav = Path(td) / "audio.wav"
            wav.write_bytes(b"wav-data")
            out_mp4 = Path(td) / "out.mp4"

            mux_video_audio(orig_vid, wav, out_mp4, action="replace", ffmpeg_bin="ffmpeg")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]

            self.assertEqual(args[0], "ffmpeg")
            self.assertIn("-map", args)
            self.assertIn("0:v:0", args)
            self.assertIn("1:a:0", args)
            self.assertIn("-c:v", args)
            self.assertIn("copy", args)
            self.assertIn("-c:a", args)
            self.assertIn("aac", args)
            self.assertIn("-b:a", args)
            self.assertIn("192k", args)
            self.assertIn("-shortest", args)
            self.assertEqual(args[-1], str(out_mp4))
            # Comprueba que el archivo original no fue sobreescrito
            self.assertEqual(orig_vid.read_bytes(), b"original-video-data")

    @patch("app.audio.has_audio_stream", return_value=True)
    @patch("subprocess.run")
    def test_mux_video_audio_mix_invokes_amix_and_resample(
        self, mock_run: MagicMock, _mock_has_audio: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as td:
            orig_vid = Path(td) / "orig.mp4"
            orig_vid.write_bytes(b"original")
            wav = Path(td) / "audio.wav"
            out_mp4 = Path(td) / "out.mp4"

            mux_video_audio(orig_vid, wav, out_mp4, action="mix", ffmpeg_bin="ffmpeg")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]

            self.assertIn("-filter_complex", args)
            filter_idx = args.index("-filter_complex")
            filter_expr = args[filter_idx + 1]
            self.assertIn("amix=inputs=2", filter_expr)
            self.assertIn("aresample=48000", filter_expr)
            self.assertIn("-shortest", args)


class TestAudioRouter(unittest.TestCase):
    """Comprueba las rutas FastAPI de audio."""

    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.cfg = EngineConfig(
            comfy_root=self.root / "comfy",
            comfy_url="http://127.0.0.1:8288",
            data_dir=self.root / "data",
        )
        self.cfg.comfy_output_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.comfy_input_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.cfg.data_dir / "waifu.db"
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.executescript(_OLD_SCHEMA)
        self.store = Store(db_path)
        self.store.init()
        self.app = create_app(config=self.cfg, store=self.store)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.td.cleanup()

    def test_api_audio_status(self) -> None:
        res = self.client.get("/api/audio/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("mmaudio_installed"))
        self.assertEqual(data.get("sample_rate_hz"), 48000)
        self.assertFalse(data.get("irodori_installed"))
        self.assertIn("localhost:8291", data.get("irodori_reason", ""))

    def test_api_audio_generate_rejects_voice_with_reason(self) -> None:
        res = self.client.post("/api/audio/generate", json={"voice_enabled": True})
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertIn("Irodori TTS no disponible", data.get("detail", ""))

    def test_api_audio_generate_missing_clip_404(self) -> None:
        res = self.client.post("/api/audio/generate", json={"video_path": "non_existent.mp4"})
        self.assertEqual(res.status_code, 404)

    @patch("app.audio.probe_clip_audio")
    def test_api_audio_generate_success_enqueued(self, mock_probe: MagicMock) -> None:
        mock_probe.return_value = {
            "duration": 5.06,
            "fps": 16.0,
            "width": 432,
            "height": 768,
            "has_audio": False,
        }
        vid_gen_id = self.store.add("wan", "a waifu dancing", kind="video")
        gal_dir = self.cfg.data_dir / "gallery" / str(vid_gen_id)
        gal_dir.mkdir(parents=True, exist_ok=True)
        clip_path = gal_dir / "clip.mp4"
        clip_path.write_bytes(b"dummy-mp4")
        self.store.update(vid_gen_id, status="done", outputs=["clip.mp4"], kind="video")

        res = self.client.post(
            "/api/audio/generate",
            json={
                "video_path": str(clip_path),
                "prompt": "soft breathing",
                "action": "replace",
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("job_id", data)
        self.assertIn("gen_id", data)
        self.assertEqual(data.get("duration"), 5.06)
        self.assertEqual(data.get("sample_rate"), 48000)


class TestRunAudioGeneration(unittest.TestCase):
    """Comprueba la ejecución del runner con Mock del Engine."""

    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.cfg = EngineConfig(
            comfy_root=self.root / "comfy",
            comfy_url="http://127.0.0.1:8288",
            data_dir=self.root / "data",
        )
        self.cfg.comfy_output_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.cfg.data_dir / "waifu.db"
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.executescript(_OLD_SCHEMA)
        self.store = Store(db_path)
        self.store.init()

    def tearDown(self) -> None:
        self.td.cleanup()

    @patch("app.audio.extract_48k_wav")
    @patch("app.audio.mux_video_audio")
    def test_run_audio_generation_creates_outputs_and_updates_store(
        self, mock_mux: MagicMock, mock_extract: MagicMock
    ) -> None:
        gen_id = self.store.add("mmaudio", "prompt", "", kind="audio")
        orig_video = self.root / "input.mp4"
        orig_video.write_bytes(b"orig-video")

        temp_comfy_output = self.cfg.comfy_output_dir / "waifu_temp.mp4"
        temp_comfy_output.write_bytes(b"comfy-output-video")

        mock_engine = MagicMock()
        mock_engine.client_id = "test-client"
        mock_engine.submit.return_value = "prompt-123"
        mock_engine.wait.return_value = {"outputs": {}}
        mock_engine.outputs.return_value = [temp_comfy_output]

        job = {
            "gen_id": gen_id,
            "video_path": str(orig_video),
            "duration": 5.0,
            "fps": 16.0,
            "prompt": "ambient sounds",
            "negative": "",
            "action": "replace",
        }

        record = {"status": "queued", "tracker": None, "prompt_id": None}
        run_audio_generation(
            job,
            config=self.cfg,
            store=self.store,
            engine_factory=lambda: mock_engine,
            record=record,
        )

        self.assertEqual(record["status"], "done")
        self.assertEqual(job["error"], None)
        self.assertIn("video_audio_1.mp4", job["outputs"])
        self.assertIn("audio_1.wav", job["outputs"])

        # Verifica Store
        stored = self.store.get(gen_id)
        self.assertEqual(stored["status"], "done")
        self.assertEqual(stored["kind"], "audio")
        self.assertIn("video_audio_1.mp4", stored["outputs"])
        self.assertIn("audio_1.wav", stored["outputs"])

        # Comprueba llamadas a extracción y muxing
        mock_extract.assert_called_once()
        mock_mux.assert_called_once()


if __name__ == "__main__":
    unittest.main()
