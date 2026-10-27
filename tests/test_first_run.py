"""Tests CPU del chequeo de primera ejecución (PL-21)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.config import EngineConfig
from app.first_run import _vram_check, first_run_report


class FirstRunReportTests(unittest.TestCase):
    def test_maquina_vacia_reporta_faltantes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = EngineConfig(
                comfy_root=root / "comfy",
                comfy_url="http://127.0.0.1:1",
                data_dir=root / "data",
            )
            report = first_run_report(cfg)
        self.assertFalse(report["ready"])
        self.assertTrue(report["missing"])
        labels = {item["label"] for item in report["items"]}
        self.assertIn("Motor ComfyUI", labels)
        self.assertIn("Modelos de imagen", labels)

    def test_modelos_presentes_marcan_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = EngineConfig(
                comfy_root=root / "comfy",
                comfy_url="http://127.0.0.1:1",
                data_dir=root / "data",
            )
            checkpoints = cfg.comfy_root / "models" / "checkpoints"
            checkpoints.mkdir(parents=True)
            for name in (
                "animagine-xl-4.0-opt.safetensors",
                "realvisxlV50_v50Bakedvae_full_fp16.safetensors",
                "juggernautXL_ragnarok.safetensors",
            ):
                (checkpoints / name).write_bytes(b"x")
            report = first_run_report(cfg)
        model = next(item for item in report["items"] if item["label"] == "Modelos de imagen")
        self.assertTrue(model["ok"])

    def test_vram_elige_la_gpu_mayor(self):
        output = "0, NVIDIA GeForce RTX 2060, 6144\n1, NVIDIA GeForce RTX 3060, 12288\n"
        with mock.patch("app.first_run.shutil.which", return_value="nvidia-smi"):
            with mock.patch("app.first_run.subprocess.run") as run:
                run.return_value = mock.Mock(stdout=output)
                check = _vram_check()
        self.assertTrue(check["ok"])
        self.assertIn("RTX 3060", check["detail"])
        self.assertIn("12288", check["detail"])


if __name__ == "__main__":
    unittest.main()
