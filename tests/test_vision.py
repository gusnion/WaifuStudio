"""Tests CPU de vision local (M10-4b). Sin onnxruntime, llama.cpp, red ni GPU."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.vision import (
    VL_MMPROJ_FILE,
    VL_MODEL_FILE,
    VisionService,
    VisionUnavailable,
    WD14_MODEL,
    _load_rows,
    _postprocess,
)


class PostprocessTests(unittest.TestCase):
    ROWS = [
        ("long hair", "0"),
        ("1girl", "0"),
        ("hatsune miku", "4"),
        ("rating explicit", "9"),
        ("solo", "0"),
    ]

    def test_umbrales_por_categoria_y_orden(self):
        probs = [0.90, 0.40, 0.90, 0.99, 0.20]
        self.assertEqual(
            _postprocess(self.ROWS, probs),
            ["hatsune miku", "long hair", "1girl"],
        )

    def test_personajes_exigen_umbral_alto(self):
        self.assertEqual(_postprocess(self.ROWS, [0.0, 0.0, 0.5, 0.0, 0.0]), [])

    def test_ratings_se_ignoran(self):
        self.assertEqual(_postprocess(self.ROWS, [0.0, 0.0, 0.0, 0.99, 0.0]), [])


class LoadRowsTests(unittest.TestCase):
    def test_parsea_y_normaliza(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.csv"
            path.write_text(
                "tag_id,name,category,count\n"
                "0,long_hair,0,10\n"
                "1,hatsune_miku,4,5\n"
                "2,x\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _load_rows(path),
                [("long hair", "0"), ("hatsune miku", "4")],
            )


def _write_assets(root: Path) -> Path:
    wd14 = root / "models" / "wd14"
    wd14.mkdir(parents=True, exist_ok=True)
    (wd14 / f"{WD14_MODEL}.onnx").write_bytes(b"onnx")
    (wd14 / f"{WD14_MODEL}.csv").write_bytes(b"tag_id,name,category,count\n")
    llm = root / "models" / "llm" / "qwen25vl-7b-abliterated-gguf"
    llm.mkdir(parents=True, exist_ok=True)
    (llm / VL_MODEL_FILE).write_bytes(b"gguf")
    (llm / VL_MMPROJ_FILE).write_bytes(b"mmproj")
    return root


class VisionServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_status_sin_assets(self):
        status = VisionService(self.root).status()
        self.assertFalse(status["installed"])
        self.assertFalse(status["wd14"]["installed"])
        self.assertFalse(status["vl"]["installed"])
        self.assertEqual(status["wd14"]["model"], WD14_MODEL)
        self.assertIn("note", status)

    def test_status_con_assets(self):
        _write_assets(self.root)
        status = VisionService(self.root).status()
        self.assertTrue(status["installed"])
        self.assertTrue(status["wd14"]["installed"])
        self.assertTrue(status["vl"]["installed"])

    def test_tags_usa_factoria_y_cachea(self):
        _write_assets(self.root)
        calls: list[tuple[str, str]] = []

        def factory(onnx_path: Path, csv_path: Path):
            calls.append((onnx_path.name, csv_path.name))
            return lambda raw: ["a", "b"]

        service = VisionService(self.root, tagger_factory=factory)
        self.assertEqual(service.tags(b"img"), ["a", "b"])
        self.assertEqual(service.tags(b"img"), ["a", "b"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (f"{WD14_MODEL}.onnx", f"{WD14_MODEL}.csv"))

    def test_tags_sin_wd14_lanza_vision_unavailable(self):
        with self.assertRaises(VisionUnavailable):
            VisionService(self.root).tags(b"img")

    def test_caption_sin_vl_lanza_vision_unavailable(self):
        with self.assertRaises(VisionUnavailable):
            VisionService(self.root).caption(b"img")

    def test_caption_usa_factoria_y_cachea(self):
        _write_assets(self.root)
        calls: list[tuple[str, str, int]] = []

        def factory(model_path: Path, mmproj_path: Path, gpu_layers: int):
            calls.append((model_path.name, mmproj_path.name, gpu_layers))
            return lambda raw: "a girl"

        service = VisionService(self.root, captioner_factory=factory)
        self.assertEqual(service.caption(b"img"), "a girl")
        self.assertEqual(service.caption(b"img"), "a girl")
        self.assertEqual(calls, [(VL_MODEL_FILE, VL_MMPROJ_FILE, 0)])

    def test_describe_combinaciones(self):
        _write_assets(self.root)
        service = VisionService(
            self.root,
            tagger_factory=lambda _o, _c: (lambda raw: ["tag"]),
            captioner_factory=lambda _m, _p, _g: (lambda raw: "cap"),
        )
        both = service.describe(b"img")
        self.assertEqual(both["tags"], ["tag"])
        self.assertEqual(both["caption"], "cap")
        self.assertIn("model", both)
        self.assertIsNone(service.describe(b"img", use_caption=False)["caption"])
        self.assertIsNone(service.describe(b"img", use_tags=False)["tags"])

    def test_describe_sin_assets_lanza(self):
        with self.assertRaises(VisionUnavailable):
            VisionService(self.root).describe(b"img", use_caption=False)
        with self.assertRaises(VisionUnavailable):
            VisionService(self.root).describe(b"img", use_tags=False)


class EnvOverrideTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_gpu_layers_env(self):
        with mock.patch.dict(os.environ, {"WAIFU_VL_GPU_LAYERS": "5"}):
            self.assertEqual(VisionService(self.root).gpu_layers, 5)
        with mock.patch.dict(os.environ, {"WAIFU_VL_GPU_LAYERS": ""}):
            self.assertEqual(VisionService(self.root).gpu_layers, 0)

    def test_vl_paths_env(self):
        model = self.root / "m.gguf"
        mmproj = self.root / "p.gguf"
        with mock.patch.dict(
            os.environ,
            {"WAIFU_VL_MODEL": str(model), "WAIFU_VL_MMPROJ": str(mmproj)},
        ):
            service = VisionService(self.root)
        self.assertEqual(service.vl_model, model)
        self.assertEqual(service.vl_mmproj, mmproj)


if __name__ == "__main__":
    unittest.main()
