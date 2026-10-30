"""Tests unitarios para el gestor de poses (app/poses.py, C51-08)."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from app.poses import (
    PoseError,
    build_pose_tags,
    download_pose_index,
    load_pose_index,
    pose_status,
)


class TestPoses(unittest.TestCase):
    def test_pose_status_without_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            status = pose_status(tmp_dir)
            self.assertFalse(status["installed"])
            self.assertEqual(status["version"], "1.0.0")
            self.assertIsInstance(status["count"], int)
            self.assertIsInstance(status["bytes"], int)
            self.assertTrue(status["url"].startswith("http"))

    def test_download_pose_index_success(self) -> None:
        payload = json.dumps({"schema": "waifu.poses/v1", "items": [{"id": "p1"}]}).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        payload_bytes = len(payload)

        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_file = Path(tmp_dir) / "catalog.json"
            catalog_file.write_text(
                json.dumps({
                    "url": "https://example.com/poses-index.json",
                    "bytes": payload_bytes,
                    "sha256": payload_sha256,
                    "count": 1,
                }),
                encoding="utf-8",
            )

            data_dir = Path(tmp_dir) / "data"

            class MockResponse:
                def __enter__(self):
                    return io.BytesIO(payload)

                def __exit__(self, exc_type, exc_val, exc_tb):
                    return False

            with patch("urllib.request.urlopen", return_value=MockResponse()):
                target = download_pose_index(data_dir, catalog_path=catalog_file)
                self.assertTrue(target.is_file())
                self.assertEqual(target.read_bytes(), payload)

            status = pose_status(data_dir)
            self.assertTrue(status["installed"])
            self.assertEqual(status["count"], 1)
            self.assertEqual(status["bytes"], payload_bytes)

    def test_download_pose_index_invalid_sha256(self) -> None:
        payload = b"fake payload"
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_file = Path(tmp_dir) / "catalog.json"
            catalog_file.write_text(
                json.dumps({
                    "url": "https://example.com/poses-index.json",
                    "bytes": len(payload),
                    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                }),
                encoding="utf-8",
            )
            data_dir = Path(tmp_dir) / "data"

            class MockResponse:
                def __enter__(self):
                    return io.BytesIO(payload)

                def __exit__(self, exc_type, exc_val, exc_tb):
                    return False

            with patch("urllib.request.urlopen", return_value=MockResponse()):
                with self.assertRaises(PoseError) as ctx:
                    download_pose_index(data_dir, catalog_path=catalog_file)
                self.assertIn("SHA256 no coincide", str(ctx.exception))

    def test_load_pose_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            self.assertEqual(load_pose_index(data_dir), [])

            poses_dir = data_dir / "poses"
            poses_dir.mkdir(parents=True, exist_ok=True)
            index_path = poses_dir / "poses-index.json"

            index_path.write_text(
                json.dumps({"schema": "waifu.poses/v1", "items": [{"id": "p1"}, {"id": "p2"}]}),
                encoding="utf-8",
            )
            items = load_pose_index(data_dir)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["id"], "p1")

    def test_build_pose_tags(self) -> None:
        tags = build_pose_tags(clase_es="Sentada", angulo_es="Diagonal")
        self.assertEqual(tags, ["sitting", "from side", "three-quarter view"])

        tags_dup = build_pose_tags(clase_es="Sentada de frente", angulo_es="Frontal")
        self.assertEqual(tags_dup, ["sitting", "front view", "from front"])

        tags_special = build_pose_tags(clase_es="Especial")
        self.assertEqual(tags_special, [])


class PoseLibraryStaticTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_image_card_sin_entrada_de_poses(self):
        html = (self.ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="btn-pose-open-image"', html)
        self.assertNotIn('id="btn-image-poses"', html)
        self.assertIn("Ajustes de referencia", html)
        self.assertNotIn("<span>Imagen de referencia (PNG)</span>", html)

    def test_pose_library_loads_catalog_download_and_tags(self):
        js = (self.ROOT / "static" / "js" / "components" / "pose_library.js").read_text(encoding="utf-8")
        self.assertIn("/api/poses", js)
        self.assertIn("/api/poses/download", js)
        self.assertIn("btn-pose-download", js)
        self.assertIn("pose.tags", js)
        catalog = json.loads((self.ROOT / "registry" / "pose-catalog-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["bytes"], 505624)
        self.assertEqual(catalog["count"], 1439)
        self.assertEqual(
            catalog["sha256"],
            "dc35f253d56b9eff973fd399b5a04bfd40257a0e72b2f0696a60de7837ecf3f0",
        )


if __name__ == "__main__":
    unittest.main()
