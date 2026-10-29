"""Tests unitarios del módulo y rutas de Timeline / Estudio (M20 T-03a)."""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import APP_ROOT, EngineConfig
from app.engine import EngineError
from app.registry import DEFAULT_PATH as REGISTRY_PATH, ModelRegistry
from app.server import create_app
from app.store import Store
from app.timeline import (
    _resolve_clip_source,
    export_timeline_project,
    extract_clip_frame,
    has_audio_stream,
    image_to_video_clip,
    normalize_video_clip,
    resolve_gallery_path,
)

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-content"
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"fake-mp4-content"
FAKE_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"fake-mp3-content"


class TimelineStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "waifu.db"
        self.store = Store(self.db_path)
        self.store.init()

    def test_crud_timeline_projects(self):
        # 1. Crear nuevo proyecto
        proj = self.store.save_timeline_project(
            None, "Mi Pelicula", {"clips": [{"kind": "image", "duration": 2.5}]}
        )
        self.assertTrue(proj["id"].startswith("tl_"))
        self.assertEqual(proj["name"], "Mi Pelicula")
        self.assertEqual(len(proj["data"]["clips"]), 1)
        self.assertTrue(proj["created_at"])
        self.assertTrue(proj["updated_at"])

        pid = proj["id"]
        created = proj["created_at"]

        # 2. Obtener proyecto
        fetched = self.store.get_timeline_project(pid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], pid)
        self.assertEqual(fetched["name"], "Mi Pelicula")

        # 3. Actualizar proyecto
        updated = self.store.save_timeline_project(
            pid, "Mi Pelicula Editada", {"clips": [{"kind": "video"}]}
        )
        self.assertEqual(updated["id"], pid)
        self.assertEqual(updated["name"], "Mi Pelicula Editada")
        self.assertEqual(updated["created_at"], created)

        # 4. Listar proyectos
        items = self.store.list_timeline_projects()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], pid)

        # 5. Eliminar proyecto
        deleted = self.store.delete_timeline_project(pid)
        self.assertTrue(deleted)
        self.assertIsNone(self.store.get_timeline_project(pid))
        self.assertFalse(self.store.delete_timeline_project(pid))


class TimelineModuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.video_file = self.root / "sample.mp4"
        self.video_file.write_bytes(FAKE_MP4)
        self.image_file = self.root / "sample.png"
        self.image_file.write_bytes(FAKE_PNG)

    @patch("subprocess.run")
    def test_has_audio_stream(self, mock_run):
        mock_proc = MagicMock(returncode=0, stderr="Stream #0:1: Audio: aac (LC)")
        mock_run.return_value = mock_proc
        self.assertTrue(has_audio_stream(self.video_file, ffmpeg_bin="ffmpeg"))

        mock_proc.stderr = "Stream #0:0: Video: h264"
        self.assertFalse(has_audio_stream(self.video_file, ffmpeg_bin="ffmpeg"))

    @patch("subprocess.run")
    def test_extract_clip_frame_first_and_last(self, mock_run):
        def fake_run(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.write_bytes(FAKE_PNG)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        out_first = self.root / "frame_first.png"
        res_first = extract_clip_frame(self.video_file, out_first, position="first", ffmpeg_bin="ffmpeg")
        self.assertEqual(res_first, out_first)
        self.assertTrue(out_first.is_file())

        out_last = self.root / "frame_last.png"
        res_last = extract_clip_frame(self.video_file, out_last, position="last", ffmpeg_bin="ffmpeg")
        self.assertEqual(res_last, out_last)
        self.assertTrue(out_last.is_file())

        with self.assertRaises(EngineError):
            extract_clip_frame(self.video_file, self.root / "err.png", position="middle", ffmpeg_bin="ffmpeg")

    @patch("subprocess.run")
    def test_image_to_video_clip_effects(self, mock_run):
        def fake_run(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.write_bytes(FAKE_MP4)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        out_mp4 = self.root / "img_clip.mp4"
        res = image_to_video_clip(
            self.image_file, out_mp4, duration=2.0, effect="zoom_in", ffmpeg_bin="ffmpeg"
        )
        self.assertEqual(res, out_mp4)
        self.assertTrue(out_mp4.is_file())

    @patch("subprocess.run")
    def test_normalize_video_clip(self, mock_run):
        def fake_run(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.write_bytes(FAKE_MP4)
            return MagicMock(returncode=0, stderr="Stream #0:1: Audio: aac")

        mock_run.side_effect = fake_run

        out_mp4 = self.root / "norm_clip.mp4"
        res = normalize_video_clip(
            self.video_file,
            out_mp4,
            width=1280,
            height=720,
            fps=24,
            mute=True,
            transition_in="fade",
            transition_out="fade",
            duration=4.0,
            ffmpeg_bin="ffmpeg",
        )
        self.assertEqual(res, out_mp4)
        self.assertTrue(out_mp4.is_file())

    @patch("app.timeline.concat_videos")
    @patch("app.timeline.normalize_video_clip")
    @patch("app.timeline.image_to_video_clip")
    @patch("subprocess.run")
    def test_export_timeline_project(self, mock_run, mock_img, mock_norm, mock_concat):
        work_dir = self.root / "work"
        gallery_dir = self.root / "gallery"
        gallery_dir.mkdir(parents=True, exist_ok=True)
        image_src = gallery_dir / "sample.png"
        video_src = gallery_dir / "sample.mp4"
        image_src.write_bytes(self.image_file.read_bytes())
        video_src.write_bytes(self.video_file.read_bytes())
        out_mp4 = self.root / "final.mp4"
        audio_dir = self.root / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_file = audio_dir / "audio.mp3"
        audio_file.write_bytes(FAKE_MP3)

        def fake_img(src, out, **kwargs):
            out.write_bytes(FAKE_MP4)
            return out

        def fake_norm(src, out, **kwargs):
            out.write_bytes(FAKE_MP4)
            return out

        def fake_concat(paths, out, **kwargs):
            out.write_bytes(FAKE_MP4)
            return out

        def fake_run(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.write_bytes(FAKE_MP4)
            return MagicMock(returncode=0, stderr="")

        mock_img.side_effect = fake_img
        mock_norm.side_effect = fake_norm
        mock_concat.side_effect = fake_concat
        mock_run.side_effect = fake_run

        project_data = {
            "width": 1280,
            "height": 720,
            "fps": 24,
            "clips": [
                {"kind": "image", "source_path": str(image_src), "duration": 2.0},
                {"kind": "video", "source_path": str(video_src), "duration": 3.0},
            ],
            "audio_tracks": [
                {"source_path": str(audio_file), "start_time": 0.5, "volume": 1.2}
            ],
        }

        res = export_timeline_project(
            project_data,
            out_mp4,
            work_dir=work_dir,
            gallery_dir=gallery_dir,
            ffmpeg_bin="ffmpeg",
        )
        self.assertEqual(res, out_mp4)
        self.assertTrue(out_mp4.is_file())

    @patch("subprocess.run")
    def test_image_to_video_clip_fade(self, mock_run):
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            out_file = Path(cmd[-1])
            out_file.write_bytes(FAKE_MP4)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        out_mp4 = self.root / "img_clip_fade.mp4"
        res = image_to_video_clip(
            self.image_file,
            out_mp4,
            duration=3.0,
            transition_in="fade",
            transition_out="fade",
            ffmpeg_bin="ffmpeg",
        )
        self.assertEqual(res, out_mp4)
        self.assertTrue(out_mp4.is_file())
        vf_idx = captured_cmd.index("-vf")
        vf_val = captured_cmd[vf_idx + 1]
        self.assertIn("fade=t=in:st=0:d=0.5", vf_val)
        self.assertIn("fade=t=out:st=2.50:d=0.5", vf_val)

    @patch("app.timeline.concat_videos")
    @patch("app.timeline.normalize_video_clip")
    @patch("app.timeline.image_to_video_clip")
    @patch("subprocess.run")
    def test_export_timeline_project_image_fade(self, mock_run, mock_img, mock_norm, mock_concat):
        work_dir = self.root / "work_fade"
        gallery_dir = self.root / "gallery_fade"
        gallery_dir.mkdir(parents=True, exist_ok=True)
        image_src = gallery_dir / "sample_fade.png"
        image_src.write_bytes(self.image_file.read_bytes())
        out_mp4 = self.root / "final_fade.mp4"

        mock_img.side_effect = lambda src, out, **kw: out.write_bytes(FAKE_MP4) or out
        mock_concat.side_effect = lambda paths, out, **kw: out.write_bytes(FAKE_MP4) or out

        project_data = {
            "width": 1280,
            "height": 720,
            "fps": 24,
            "clips": [
                {
                    "kind": "image",
                    "source_path": str(image_src),
                    "duration": 4.0,
                    "transition_in": "fade",
                    "transition_out": "fade",
                },
            ],
        }

        export_timeline_project(
            project_data,
            out_mp4,
            work_dir=work_dir,
            gallery_dir=gallery_dir,
            ffmpeg_bin="ffmpeg",
        )
        self.assertEqual(mock_img.call_count, 1)
        _, kwargs = mock_img.call_args
        self.assertEqual(kwargs.get("transition_in"), "fade")
        self.assertEqual(kwargs.get("transition_out"), "fade")

    def test_resolve_clip_source_valid_url(self):
        gallery_dir = self.root / "gallery_valid_url"
        clip_dir = gallery_dir / "101"
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip_file = clip_dir / "scene.mp4"
        clip_file.write_bytes(FAKE_MP4)

        # 1. URL relativa /media/...
        resolved, kind = _resolve_clip_source(
            {"source_path": "/media/101/scene.mp4"}, gallery_dir
        )
        self.assertEqual(resolved, clip_file.resolve())
        self.assertEqual(kind, "video")

        # 2. URL completa http://...
        resolved_full, kind_full = _resolve_clip_source(
            {"source_path": "http://localhost:8765/media/101/scene.mp4"}, gallery_dir
        )
        self.assertEqual(resolved_full, clip_file.resolve())
        self.assertEqual(kind_full, "video")

    def test_resolve_clip_source_traversal(self):
        gallery_dir = self.root / "gallery_traversal"
        gallery_dir.mkdir(parents=True, exist_ok=True)

        # 1. Traversal relativo
        with self.assertRaises(EngineError):
            _resolve_clip_source({"source_path": "../secret.mp4"}, gallery_dir)

        # 2. Traversal con prefijo /media/
        with self.assertRaises(EngineError):
            _resolve_clip_source({"source_path": "/media/../secret.mp4"}, gallery_dir)

        # 3. Ruta externa arbitraria absoluta
        external = Path(tempfile.gettempdir()) / "outside_clip.mp4"
        external.write_bytes(FAKE_MP4)
        try:
            with self.assertRaises(EngineError):
                _resolve_clip_source({"source_path": str(external)}, gallery_dir)
        finally:
            external.unlink(missing_ok=True)

    @patch("app.timeline.concat_videos")
    @patch("app.timeline.normalize_video_clip")
    @patch("app.timeline.image_to_video_clip")
    @patch("subprocess.run")
    def test_export_audio_confinement_and_traversal(self, mock_run, mock_img, mock_norm, mock_concat):
        work_dir = self.root / "work_audio"
        gallery_dir = self.root / "gallery_audio"
        gallery_dir.mkdir(parents=True, exist_ok=True)
        video_src = gallery_dir / "sample_audio.mp4"
        video_src.write_bytes(self.video_file.read_bytes())
        audio_dir = self.root / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        legit_audio = audio_dir / "valid.mp3"
        legit_audio.write_bytes(FAKE_MP3)

        external_audio = Path(tempfile.gettempdir()) / "secret.mp3"
        external_audio.write_bytes(FAKE_MP3)

        mock_norm.side_effect = lambda src, out, **kw: out.write_bytes(FAKE_MP4) or out
        mock_concat.side_effect = lambda paths, out, **kw: out.write_bytes(FAKE_MP4) or out

        captured_inputs = []

        def fake_run(cmd, **kwargs):
            captured_inputs.extend(cmd)
            out_file = Path(cmd[-1])
            out_file.write_bytes(FAKE_MP4)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        try:
            project_data = {
                "clips": [{"kind": "video", "source_path": str(video_src)}],
                "audio_tracks": [
                    {"source_path": "/media/audio/valid.mp3", "start_time": 0.0},
                    {"source_path": "../secret.mp3", "start_time": 0.0},
                    {"source_path": str(external_audio), "start_time": 0.0},
                ],
            }
            out_mp4 = self.root / "final_audio.mp4"
            export_timeline_project(
                project_data,
                out_mp4,
                work_dir=work_dir,
                gallery_dir=gallery_dir,
                ffmpeg_bin="ffmpeg",
            )
            self.assertIn(str(legit_audio.resolve()), captured_inputs)
            self.assertNotIn(str(external_audio.resolve()), captured_inputs)
        finally:
            external_audio.unlink(missing_ok=True)


class TimelineRouteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = EngineConfig(
            comfy_root=self.root / "comfy",
            data_dir=self.root / "data",
            comfy_url="http://127.0.0.1:8188",
        )
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.comfy_input_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.config.data_dir / "waifu.db")
        self.store.init()
        self.registry = ModelRegistry.load(REGISTRY_PATH)

        app = create_app(
            config=self.config,
            store=self.store,
            registry=self.registry,
            start_worker=False,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_projects_crud_routes(self):
        # 1. Listar inicialmente vacio
        res = self.client.get("/api/timeline/projects")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["items"], [])

        # 2. Guardar proyecto
        res = self.client.post(
            "/api/timeline/projects",
            json={"name": "Timeline 1", "data": {"clips": []}},
        )
        self.assertEqual(res.status_code, 200)
        proj = res.json()
        pid = proj["id"]
        self.assertTrue(pid.startswith("tl_"))
        self.assertEqual(proj["name"], "Timeline 1")

        # 3. Obtener proyecto
        res = self.client.get(f"/api/timeline/projects/{pid}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["id"], pid)

        # 4. Actualizar proyecto
        res = self.client.post(
            "/api/timeline/projects",
            json={"id": pid, "name": "Timeline Modificado", "data": {"clips": [{"kind": "image"}]}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "Timeline Modificado")

        # 5. Eliminar proyecto
        res = self.client.delete(f"/api/timeline/projects/{pid}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["ok"], True)

        res = self.client.get(f"/api/timeline/projects/{pid}")
        self.assertEqual(res.status_code, 404)

    @patch("app.routes.timeline.extract_clip_frame")
    def test_extract_frame_route(self, mock_extract):
        def fake_extract(vpath, out_png, **kwargs):
            out_png.parent.mkdir(parents=True, exist_ok=True)
            out_png.write_bytes(FAKE_PNG)
            return out_png

        mock_extract.side_effect = fake_extract

        # Crear generacion simulada en store con video
        gen_id = self.store.add("video_model", "prompt", "", {}, kind="video")
        gdir = self.config.data_dir / "gallery" / str(gen_id)
        gdir.mkdir(parents=True, exist_ok=True)
        video_path = gdir / "clip.mp4"
        video_path.write_bytes(FAKE_MP4)
        self.store.update(gen_id, status="done", outputs=["clip.mp4"], kind="video")

        res = self.client.post(
            "/api/timeline/extract_frame",
            json={"generation_id": gen_id, "position": "first"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["image_name"], f"tl_frame_{gen_id}_first.png")
        self.assertEqual(data["preview_url"], f"/api/refs/tl_frame_{gen_id}_first.png")

    @patch("app.routes.timeline.extract_clip_frame")
    def test_extract_frame_route_source_path_media_url_and_fallback(self, mock_extract):
        def fake_extract(vpath, out_png, **kwargs):
            out_png.parent.mkdir(parents=True, exist_ok=True)
            out_png.write_bytes(FAKE_PNG)
            return out_png

        mock_extract.side_effect = fake_extract

        # Crear generacion video con output clip.mp4
        gen_id = self.store.add("video_model", "prompt", "", {}, kind="video")
        gdir = self.config.data_dir / "gallery" / str(gen_id)
        gdir.mkdir(parents=True, exist_ok=True)
        video_path = gdir / "clip.mp4"
        video_path.write_bytes(FAKE_MP4)
        self.store.update(gen_id, status="done", outputs=["clip.mp4"], kind="video")

        # 1. payload con source_path="/media/<id>/clip.mp4" + generation_id=<id> => 200 y frame
        res1 = self.client.post(
            "/api/timeline/extract_frame",
            json={
                "source_path": f"/media/{gen_id}/clip.mp4",
                "generation_id": gen_id,
                "position": "first",
            },
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertTrue(data1["ok"])
        self.assertTrue(data1["image_b64"])
        self.assertEqual(data1["image_name"], f"tl_frame_{gen_id}_first.png")

        # 2. payload con source_path invalido + generation_id valido => 200 (fallback)
        res2 = self.client.post(
            "/api/timeline/extract_frame",
            json={
                "source_path": f"/media/{gen_id}/nonexistent.mp4",
                "generation_id": gen_id,
                "position": "last",
            },
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2["ok"])
        self.assertTrue(data2["image_b64"])
        self.assertEqual(data2["image_name"], f"tl_frame_{gen_id}_last.png")

        # 3. source_path "../secret.mp4" => 403/404, no leer fuera
        outside_secret = self.root / "secret.mp4"
        outside_secret.write_bytes(FAKE_MP4)
        res3 = self.client.post(
            "/api/timeline/extract_frame",
            json={"source_path": "../secret.mp4", "position": "first"},
        )
        self.assertIn(res3.status_code, (403, 404))

    def test_upload_and_serve_audio_route(self):
        b64_audio = base64.b64encode(FAKE_MP3).decode("ascii")
        res = self.client.post(
            "/api/timeline/upload_audio",
            json={"filename": "musica.mp3", "audio_b64": b64_audio},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["filename"].endswith("_musica.mp3"))
        audio_url = data["audio_url"]

        # Servir el archivo via /media/audio/...
        get_res = self.client.get(audio_url)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.headers["content-type"], "audio/mpeg")
        self.assertEqual(get_res.content, FAKE_MP3)

        # Probar extension no permitida
        bad_res = self.client.post(
            "/api/timeline/upload_audio",
            json={"filename": "virus.exe", "audio_b64": b64_audio},
        )
        self.assertEqual(bad_res.status_code, 400)

    @patch("app.routes.timeline.export_timeline_project")
    def test_export_timeline_route(self, mock_export):
        def fake_export(pdata, out_mp4, **kwargs):
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
            out_mp4.write_bytes(FAKE_MP4)
            return out_mp4

        mock_export.side_effect = fake_export

        res = self.client.post(
            "/api/timeline/export",
            json={
                "name": "Export Video",
                "project_data": {
                    "clips": [{"kind": "video", "source_path": "clip.mp4"}],
                },
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        gen_id = data["generation_id"]
        row = self.store.get(gen_id)
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["kind"], "video")
        self.assertEqual(data["output_url"], f"/media/{gen_id}/timeline_{gen_id}.mp4")
        expected_path = (self.config.data_dir / "gallery" / str(gen_id) / f"timeline_{gen_id}.mp4").resolve()
        self.assertEqual(data["output_path"], str(expected_path))
        self.assertTrue(Path(data["output_path"]).is_absolute())

    @patch("app.routes.timeline.subprocess.Popen")
    def test_reveal_timeline_route(self, mock_popen):
        gallery_mp4 = self.config.data_dir / "gallery" / "42" / "timeline_42.mp4"
        gallery_mp4.parent.mkdir(parents=True, exist_ok=True)
        gallery_mp4.write_bytes(FAKE_MP4)

        exports_mp4 = self.config.data_dir / "exports" / "custom_export.mp4"
        exports_mp4.parent.mkdir(parents=True, exist_ok=True)
        exports_mp4.write_bytes(FAKE_MP4)

        with patch("app.routes.timeline.os.name", "nt"):
            # 1. Ruta dentro de data/gallery abre Explorer con /select
            res_gal = self.client.post(
                "/api/timeline/reveal",
                json={"path": str(gallery_mp4.resolve())},
            )
            self.assertEqual(res_gal.status_code, 200)
            self.assertTrue(res_gal.json()["ok"])
            self.assertEqual(res_gal.json()["path"], str(gallery_mp4.resolve()))
            mock_popen.assert_called_with(["explorer.exe", f"/select,{gallery_mp4.resolve()}"])

            # 2. Ruta dentro de data/exports abre Explorer
            mock_popen.reset_mock()
            res_exp = self.client.post(
                "/api/timeline/reveal",
                json={"path": str(exports_mp4.resolve())},
            )
            self.assertEqual(res_exp.status_code, 200)
            self.assertTrue(res_exp.json()["ok"])
            mock_popen.assert_called_with(["explorer.exe", f"/select,{exports_mp4.resolve()}"])

            # 3. Rutas fuera de data/gallery o data/exports => 403
            mock_popen.reset_mock()
            outside = self.root / "outside.mp4"
            outside.write_bytes(FAKE_MP4)
            for forbidden in (
                str(outside.resolve()),
                "../outside.mp4",
                str((self.config.data_dir / "waifu.db").resolve()),
            ):
                res_bad = self.client.post("/api/timeline/reveal", json={"path": forbidden})
                self.assertEqual(res_bad.status_code, 403)
            mock_popen.assert_not_called()

            # 4. Archivo inexistente dentro de gallery => 404
            missing = self.config.data_dir / "gallery" / "999" / "missing.mp4"
            res_404 = self.client.post("/api/timeline/reveal", json={"path": str(missing.resolve())})
            self.assertEqual(res_404.status_code, 404)

            # 5. Payload sin path => 400
            res_400 = self.client.post("/api/timeline/reveal", json={})
            self.assertEqual(res_400.status_code, 400)

    def test_w12_timeline_export_reveal_ui_contract(self):
        html = (APP_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="timeline-export-actions"', html)
        self.assertIn('id="btn-timeline-open-folder"', html)
        self.assertIn("Abrir carpeta", html)
        self.assertIn('id="btn-timeline-copy-path"', html)
        self.assertIn("Copiar ruta", html)

        js = (APP_ROOT / "static" / "js" / "tabs" / "timeline.js").read_text(encoding="utf-8")
        self.assertIn("/api/timeline/reveal", js)
        self.assertIn("revealTimelineExport", js)
        self.assertIn("copyTimelineExportPath", js)
        self.assertIn("res.output_path", js)


if __name__ == "__main__":
    unittest.main()
