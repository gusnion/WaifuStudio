"""Tests unitarios offline para AUDIO: Modo B con MMAudio (C-16) y Modo A con voz Irodori (C-18).

Verifica:
- Construcción y conexiones del grafo ComfyUI (VHS_LoadVideoPath -> MMAudioSampler -> VHS_VideoCombine).
- Herencia de duración y estandarización a 48 kHz.
- Comandos FFmpeg para reemplazar pista y mezclar con pista existente preservando el original.
- Rechazo explícito con motivo si se solicita voz en Modo B (la voz va por /api/audio/voice).
- Endpoints de status y validación en la API FastAPI.
- Runner monohilo FIFO (run_audio_generation) con actualización de outputs en Store.
- C-18: POST /api/audio/voice contra Irodori con HTTP mock (sin red), guardado de WAV en gallery y
  test estático de la UI (paleta de emojis, referencia de voz, enlace a audio.css).
"""

from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import tempfile
import unittest
import urllib.error
import wave
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.audio import (
    AUDIO_TARGET_SAMPLE_RATE,
    IRODORI_DISABLED_REASON,
    VOICE_EMOJI_PALETTE,
    IrodoriSpeechError,
    build_irodori_speech_body,
    build_mmaudio_mode_b_graph,
    extract_48k_wav,
    mux_video_audio,
    probe_clip_audio,
    request_irodori_speech,
    run_audio_generation,
    wav_duration_seconds,
)

from app.config import EngineConfig
from app.engine import EngineError
from app.irodori import (
    DEFAULT_IRODORI_PORT,
    DEFAULT_IRODORI_URL,
    detect_irodori,
    get_irodori_dir,
    get_irodori_url,
)
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

_IRODORI_ABSENT = {
    "installed": False,
    "status": "absent",
    "directory": "E:/IA/WAIFU/tools/irodori_absent",
    "directory_exists": False,
    "service_url": "http://127.0.0.1:8291",
    "service_online": False,
    "reason": "Irodori TTS no disponible: directorio no encontrado (microservicio localhost:8291 ausente).",
}


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

    @patch("app.audio.detect_irodori", return_value=_IRODORI_ABSENT)
    def test_api_audio_status(self, _mock_detect: MagicMock) -> None:
        res = self.client.get("/api/audio/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("mmaudio_installed"))
        self.assertEqual(data.get("sample_rate_hz"), 48000)
        self.assertFalse(data.get("irodori_installed"))
        self.assertIn("localhost:8291", data.get("irodori_reason", ""))
        self.assertEqual(data.get("irodori_status"), "absent")

    @patch("app.audio.detect_irodori")
    def test_api_audio_status_simulated_present(self, mock_detect: MagicMock) -> None:
        mock_detect.return_value = {
            "installed": True,
            "status": "installed",
            "directory": "E:/IA/WAIFU/tools/irodori",
            "directory_exists": True,
            "service_url": "http://127.0.0.1:8291",
            "service_online": True,
            "reason": "Irodori microservicio listo y conectado en http://127.0.0.1:8291.",
        }
        res = self.client.get("/api/audio/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("irodori_installed"))
        self.assertEqual(data.get("irodori_status"), "installed")
        self.assertTrue(data.get("irodori_dir_exists"))
        self.assertTrue(data.get("irodori_service_online"))
        self.assertIn("listo", data.get("irodori_reason", ""))

    @patch("app.audio.detect_irodori")
    def test_api_audio_status_simulated_offline(self, mock_detect: MagicMock) -> None:
        mock_detect.return_value = {
            "installed": False,
            "status": "offline",
            "directory": "E:/IA/WAIFU/tools/irodori",
            "directory_exists": True,
            "service_url": "http://127.0.0.1:8291",
            "service_online": False,
            "reason": "tools/irodori presente pero el microservicio no responde en localhost:8291.",
        }
        res = self.client.get("/api/audio/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data.get("irodori_installed"))
        self.assertEqual(data.get("irodori_status"), "offline")
        self.assertTrue(data.get("irodori_dir_exists"))
        self.assertFalse(data.get("irodori_service_online"))

    @patch("app.audio.detect_irodori", return_value=_IRODORI_ABSENT)
    def test_api_audio_generate_rejects_voice_with_reason(self, _mock_detect: MagicMock) -> None:
        res = self.client.post("/api/audio/generate", json={"voice_enabled": True})
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertIn("Irodori TTS no disponible", data.get("detail", ""))

    @patch("app.audio.detect_irodori")
    def test_api_audio_generate_voice_in_mode_b_points_to_mode_a(self, mock_detect: MagicMock) -> None:
        mock_detect.return_value = {"installed": True, "status": "installed", "reason": "listo"}
        res = self.client.post("/api/audio/generate", json={"voice_enabled": True})
        self.assertEqual(res.status_code, 400)
        self.assertIn("/api/audio/voice", res.json().get("detail", ""))

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



class TestIrodoriDetector(unittest.TestCase):
    """Pruebas offline del detector opcional de Irodori en app/irodori.py."""

    def test_detect_absent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            missing_dir = Path(td) / "tools" / "irodori_absent"
            res = detect_irodori(irodori_dir=missing_dir)
            self.assertFalse(res["installed"])
            self.assertEqual(res["status"], "absent")
            self.assertFalse(res["directory_exists"])
            self.assertFalse(res["service_online"])
            self.assertIn("no encontrado", res["reason"])
            self.assertIn("localhost:8291", res["reason"])

    def test_detect_present_directory_service_offline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tool_dir = Path(td) / "tools" / "irodori"
            tool_dir.mkdir(parents=True, exist_ok=True)
            res = detect_irodori(
                irodori_dir=tool_dir,
                probe_fn=lambda url: False,
            )
            self.assertFalse(res["installed"])
            self.assertEqual(res["status"], "offline")
            self.assertTrue(res["directory_exists"])
            self.assertFalse(res["service_online"])
            self.assertIn("detenido o no responde", res["reason"])

    def test_detect_present_directory_service_online_installed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tool_dir = Path(td) / "tools" / "irodori"
            tool_dir.mkdir(parents=True, exist_ok=True)
            res = detect_irodori(
                irodori_dir=tool_dir,
                probe_fn=lambda url: True,
            )
            self.assertTrue(res["installed"])
            self.assertEqual(res["status"], "installed")
            self.assertTrue(res["directory_exists"])
            self.assertTrue(res["service_online"])
            self.assertIn("listo", res["reason"])

    def test_configurable_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            custom_dir = Path(td) / "custom_irodori"
            custom_dir.mkdir()
            with patch.dict(os.environ, {"IRODORI_PATH": str(custom_dir)}):
                self.assertEqual(get_irodori_dir(), custom_dir.resolve())

    def test_configurable_env_url(self) -> None:
        custom_url = "http://127.0.0.1:9299"
        with patch.dict(os.environ, {"IRODORI_URL": custom_url}):
            self.assertEqual(get_irodori_url(), custom_url)


def _make_wav_bytes(seconds: float = 0.5, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def _fake_urlopen_response(data: bytes, seed: str | None = "777") -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = data
    resp.headers = {"X-Irodori-Seed": seed} if seed is not None else {}
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestIrodoriSpeechClient(unittest.TestCase):
    """Cuerpo y llamada HTTP a POST /v1/audio/speech con urlopen mockeado (sin red)."""

    def test_body_without_reference_uses_none_voice_and_caption(self) -> None:
        body = build_irodori_speech_body("hola \U0001F975", caption="voz baja", seed=42)
        self.assertEqual(body["model"], "irodori-tts")
        self.assertEqual(body["input"], "hola \U0001F975")
        self.assertEqual(body["response_format"], "wav")
        self.assertEqual(body["voice"], "none")
        self.assertEqual(body["irodori"], {"seed": 42, "caption": "voz baja"})

    def test_body_with_ref_wav_or_ref_embed_omits_none_voice(self) -> None:
        wav_body = build_irodori_speech_body("hola", ref_wav="C:/refs/a.wav")
        self.assertEqual(wav_body["irodori"]["ref_wav"], "C:/refs/a.wav")
        self.assertNotIn("voice", wav_body)
        self.assertNotIn("ref_embed", wav_body["irodori"])

        embed_body = build_irodori_speech_body("hola", ref_embed="C:/refs/a.speaker.safetensors")
        self.assertEqual(embed_body["irodori"]["ref_embed"], "C:/refs/a.speaker.safetensors")
        self.assertNotIn("voice", embed_body)
        self.assertNotIn("ref_wav", embed_body["irodori"])

    def test_request_posts_json_to_default_8291_and_returns_wav_and_seed(self) -> None:
        wav = _make_wav_bytes()
        env = {k: v for k, v in os.environ.items() if k != "IRODORI_URL"}
        with patch.dict(os.environ, env, clear=True), patch(
            "app.audio.urllib.request.urlopen", return_value=_fake_urlopen_response(wav, "123")
        ) as mock_open:
            data, seed = request_irodori_speech(build_irodori_speech_body("\U0001F975 hola", seed=5))

        self.assertEqual(data, wav)
        self.assertEqual(seed, 123)
        req = mock_open.call_args[0][0]
        self.assertEqual(req.full_url, "http://127.0.0.1:8291/v1/audio/speech")
        self.assertEqual(req.get_method(), "POST")
        sent = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent["model"], "irodori-tts")
        self.assertEqual(sent["response_format"], "wav")
        self.assertIn("\U0001F975", sent["input"])
        self.assertEqual(sent["irodori"]["seed"], 5)
        self.assertGreater(mock_open.call_args.kwargs["timeout"], 0)

    def test_request_http_400_maps_to_400_with_detail(self) -> None:
        err = urllib.error.HTTPError(
            "http://127.0.0.1:8291/v1/audio/speech", 400, "Bad Request", {}, io.BytesIO(b'{"detail": "Unsupported model"}')
        )
        with patch("app.audio.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(IrodoriSpeechError) as ctx:
                request_irodori_speech({"model": "x", "input": "y"}, base_url="http://127.0.0.1:8291")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Unsupported model", ctx.exception.detail)

    def test_request_connection_refused_maps_to_503(self) -> None:
        with patch("app.audio.urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(IrodoriSpeechError) as ctx:
                request_irodori_speech({"model": "x", "input": "y"}, base_url="http://127.0.0.1:8291")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("8291", ctx.exception.detail)

    def test_wav_duration_seconds(self) -> None:
        self.assertAlmostEqual(wav_duration_seconds(_make_wav_bytes(0.5, 8000)), 0.5, places=2)
        self.assertIsNone(wav_duration_seconds(b"no-wav"))


class TestAudioVoiceRoute(unittest.TestCase):
    """POST /api/audio/voice (Modo A): Irodori mockeado, WAV guardado en gallery y servido."""

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
        self.client = TestClient(create_app(config=self.cfg, store=self.store))
        self.wav = _make_wav_bytes()

    def tearDown(self) -> None:
        self.client.close()
        self.td.cleanup()

    def _sent_body(self, mock_open: MagicMock) -> dict:
        return json.loads(mock_open.call_args[0][0].data.decode("utf-8"))

    def test_voice_success_saves_wav_in_gallery_and_serves_it(self) -> None:
        text = " ".join(VOICE_EMOJI_PALETTE) + " no pares"
        with patch(
            "app.audio.urllib.request.urlopen", return_value=_fake_urlopen_response(self.wav, "99")
        ) as mock_open:
            res = self.client.post(
                "/api/audio/voice", json={"text": text, "caption": "voz suave", "seed": 7}
            )

        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["name"], f"voice_{data['gen_id']}.wav")
        self.assertEqual(data["url"], f"/api/audio/media/{data['gen_id']}/{data['name']}")
        self.assertEqual(data["seed"], 99)
        self.assertEqual(data["ref"], "none")
        self.assertFalse(data["has_ref"])
        self.assertAlmostEqual(data["duration"], 0.5, places=2)

        sent = self._sent_body(mock_open)
        self.assertEqual(sent["input"], text)
        self.assertEqual(sent["voice"], "none")
        self.assertEqual(sent["irodori"]["caption"], "voz suave")
        self.assertEqual(sent["irodori"]["seed"], 7)

        saved = self.cfg.data_dir / "gallery" / str(data["gen_id"]) / data["name"]
        self.assertEqual(saved.read_bytes(), self.wav)
        stored = self.store.get(data["gen_id"])
        self.assertEqual(stored["status"], "done")
        self.assertEqual(stored["kind"], "audio")
        self.assertEqual(stored["outputs"], [data["name"]])

        media = self.client.get(data["url"])
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media.headers["content-type"], "audio/wav")
        self.assertEqual(media.content, self.wav)

    def test_voice_negative_seed_gets_random_non_negative_seed(self) -> None:
        with patch(
            "app.audio.urllib.request.urlopen", return_value=_fake_urlopen_response(self.wav, None)
        ) as mock_open:
            res = self.client.post("/api/audio/voice", json={"text": "hola", "seed": -1})
        self.assertEqual(res.status_code, 200, res.text)
        sent_seed = self._sent_body(mock_open)["irodori"]["seed"]
        self.assertGreaterEqual(sent_seed, 0)
        self.assertEqual(res.json()["seed"], sent_seed)

    def test_voice_uploaded_ref_wav_is_stored_and_forwarded(self) -> None:
        ref_bytes = _make_wav_bytes(0.2)
        with patch(
            "app.audio.urllib.request.urlopen", return_value=_fake_urlopen_response(self.wav)
        ) as mock_open:
            res = self.client.post(
                "/api/audio/voice",
                json={
                    "text": "hola",
                    "ref_wav_data": base64.b64encode(ref_bytes).decode("ascii"),
                    "ref_wav_name": "mi voz.wav",
                },
            )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["ref"], "wav")
        sent = self._sent_body(mock_open)
        ref_path = Path(sent["irodori"]["ref_wav"])
        self.assertEqual(ref_path.name, f"ref_{data['gen_id']}.wav")
        self.assertEqual(ref_path.read_bytes(), ref_bytes)
        self.assertNotIn("voice", sent)

    def test_voice_ref_embed_path_is_forwarded_without_computing_inversion(self) -> None:
        embed = self.root / "voz.speaker.safetensors"
        embed.write_bytes(b"embed")
        with patch(
            "app.audio.urllib.request.urlopen", return_value=_fake_urlopen_response(self.wav)
        ) as mock_open:
            res = self.client.post("/api/audio/voice", json={"text": "hola", "ref_embed": str(embed)})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["ref"], "embed")
        self.assertEqual(self._sent_body(mock_open)["irodori"]["ref_embed"], str(embed))

    def test_voice_validation_errors_do_not_call_irodori(self) -> None:
        ref_wav = self.root / "a.wav"
        ref_wav.write_bytes(self.wav)
        embed = self.root / "a.pt"
        embed.write_bytes(b"x")
        cases = [
            ({"text": "   "}, 400),
            ({"text": "x" * 4097}, 400),
            ({"text": "hola", "seed": "abc"}, 400),
            ({"text": "hola", "ref_wav": "relativa.wav"}, 400),
            ({"text": "hola", "ref_wav": str(self.root / "nope.wav")}, 404),
            ({"text": "hola", "ref_embed": str(ref_wav)}, 400),
            ({"text": "hola", "ref_wav": str(ref_wav), "ref_embed": str(embed)}, 400),
            ({"text": "hola", "ref_wav_data": "###", "ref_wav_name": "a.wav"}, 400),
            ({"text": "hola", "ref_wav_data": "AAAA", "ref_wav_name": "a.txt"}, 400),
        ]
        with patch("app.audio.urllib.request.urlopen") as mock_open:
            for payload, expected in cases:
                res = self.client.post("/api/audio/voice", json=payload)
                self.assertEqual(res.status_code, expected, f"{payload} -> {res.text}")
            mock_open.assert_not_called()

    def test_voice_irodori_offline_returns_503_and_marks_error(self) -> None:
        with patch("app.audio.urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            res = self.client.post("/api/audio/voice", json={"text": "hola"})
        self.assertEqual(res.status_code, 503)
        self.assertIn("8291", res.json()["detail"])
        rows = self.store.list(kind="audio", limit=5)
        self.assertEqual(rows[0]["status"], "error")

    def test_voice_non_wav_response_is_502(self) -> None:
        with patch(
            "app.audio.urllib.request.urlopen", return_value=_fake_urlopen_response(b"<html>oops</html>")
        ):
            res = self.client.post("/api/audio/voice", json={"text": "hola"})
        self.assertEqual(res.status_code, 502)


class TestAudioVoiceStaticUI(unittest.TestCase):
    """Test estático: Modo A en index.html / audio.js / audio.css (sin servidor)."""

    ROOT = Path(__file__).resolve().parents[1]

    @staticmethod
    def _norm(value: str) -> str:
        return value.replace("\ufe0f", "")

    def _read(self, rel: str) -> str:
        return (self.ROOT / rel).read_text(encoding="utf-8")

    def _panel_audio(self) -> str:
        html = self._read("templates/index.html")
        start = html.index('id="panel-audio"')
        return html[start : html.index('id="panel-social"', start)]

    def test_panel_has_voice_mode_controls(self) -> None:
        panel = self._panel_audio()
        for element_id in (
            "audio-voice-text",
            "audio-voice-palette",
            "audio-voice-caption",
            "audio-voice-seed",
            "audio-voice-ref-file",
            "audio-voice-ref-embed",
            "btn-audio-voice-generate",
            "audio-voice-preview",
            "btn-audio-voice-download",
            "audio-mode-a-sidebar",
            "audio-mode-b-sidebar",
        ):
            self.assertIn(f'id="{element_id}"', panel, element_id)
        self.assertNotIn("no disponible en este hito", panel)
        self.assertNotIn("C-17", panel)

    def test_palette_contains_all_seven_emojis(self) -> None:
        panel = self._norm(self._panel_audio())
        self.assertEqual(len(VOICE_EMOJI_PALETTE), 7)
        for emoji in VOICE_EMOJI_PALETTE:
            self.assertIn(f'data-emoji="{self._norm(emoji)}"', panel, emoji.encode("unicode_escape"))
        self.assertEqual(panel.count('class="audio-emoji-btn'), 7)

    def test_js_wires_voice_endpoint_and_palette(self) -> None:
        js = self._read("static/js/tabs/audio.js")
        self.assertIn("/api/audio/voice", js)
        self.assertIn("btn-audio-voice-generate", js)
        self.assertIn("audio-voice-palette", js)
        self.assertIn("ref_wav_data", js)
        self.assertIn("ref_embed", js)
        self.assertIn("insertEmojiAtCursor", js)

    def test_audio_css_exists_and_is_linked(self) -> None:
        self.assertIn('href="/static/css/tabs/audio.css"', self._read("templates/index.html"))
        css = self._read("static/css/tabs/audio.css")
        self.assertIn(".audio-emoji-palette", css)
        self.assertIn(".audio-mode-group", css)


if __name__ == "__main__":
    unittest.main()
