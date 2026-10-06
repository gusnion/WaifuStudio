"""Tests unitarios CPU de app.video_chain (encadenado de video y extraccion de frames)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.engine import EngineError
from app.video_chain import concat_videos, extract_last_frame, plan_chain_segments


class VideoChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _create_synthetic_video(self, filename: str, num_frames: int = 5, w: int = 64, h: int = 64) -> Path:
        out_path = self.tmp_path / filename
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(out_path), fourcc, 24.0, (w, h))
        for i in range(num_frames):
            # Frame con color gradual para distinguir frames
            frame = np.full((h, w, 3), (i * 40) % 255, dtype=np.uint8)
            writer.write(frame)
        writer.release()
        return out_path

    def test_plan_chain_segments_unitarios(self):
        self.assertEqual(plan_chain_segments(5), [5])
        self.assertEqual(plan_chain_segments(8), [8])
        self.assertEqual(plan_chain_segments(10), [10])
        self.assertEqual(plan_chain_segments(12), [12])
        self.assertEqual(plan_chain_segments(15), [15])

        # Duraciones mayores a 15 se descomponen en bloques
        seg_20 = plan_chain_segments(20)
        self.assertEqual(sum(seg_20), 20)
        for s in seg_20:
            self.assertIn(s, (5, 8, 10, 12, 15))

        seg_24 = plan_chain_segments(24)
        self.assertEqual(sum(seg_24), 24)

    def test_plan_chain_segments_invalidos_lanza_error(self):
        with self.assertRaises(EngineError):
            plan_chain_segments(0)
        with self.assertRaises(EngineError):
            plan_chain_segments(-5)

    def test_extract_last_frame_crea_imagen_valida(self):
        vid_path = self._create_synthetic_video("test_clip.mp4", num_frames=6)
        out_img = self.tmp_path / "last_frame.png"
        res = extract_last_frame(vid_path, out_img)

        self.assertEqual(res, out_img)
        self.assertTrue(out_img.is_file())
        img = cv2.imread(str(out_img))
        self.assertIsNotNone(img)
        self.assertEqual(img.shape, (64, 64, 3))

    def test_concat_videos_une_multiples_clips(self):
        clip1 = self._create_synthetic_video("clip1.mp4", num_frames=5)
        clip2 = self._create_synthetic_video("clip2.mp4", num_frames=7)
        merged = self.tmp_path / "merged.mp4"

        res = concat_videos([clip1, clip2], merged)
        self.assertEqual(res, merged)
        self.assertTrue(merged.is_file())

        cap = cv2.VideoCapture(str(merged))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        self.assertEqual(total, 12)

    def test_concat_un_solo_video_copia_directamente(self):
        clip = self._create_synthetic_video("clip.mp4", num_frames=4)
        single_out = self.tmp_path / "single_copy.mp4"
        res = concat_videos([clip], single_out)
        self.assertEqual(res, single_out)
        self.assertTrue(single_out.is_file())


if __name__ == "__main__":
    unittest.main()
