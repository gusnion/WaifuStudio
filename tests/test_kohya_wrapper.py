"""Tests offline del wrapper del entrenador kohya (tools/kohya/run_waifu_train.py).

Cubren el mapeo puro config de la app -> dataset TOML/argv de sd-scripts y la
ejecucion con un runner falso (sin GPU ni entrenamiento real). El modulo se
carga por ruta: no vive en `app/` ni depende de torch.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from app.trainer import write_config


def _load_wrapper():
    source = Path(__file__).resolve().parents[1] / "tools" / "kohya" / "run_waifu_train.py"
    spec = importlib.util.spec_from_file_location("kohya_run_waifu_train", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = _load_wrapper()

APP_CONFIG = """# config de entrenamiento LoRA (M9-E1)
# consumida por tools/kohya/run_waifu_train.py (sd-scripts + networks.lora_anima)
source_image_dir = 'E:\\IA\\WAIFU\\data\\trainer\\7'
output_dir = 'E:\\IA\\WAIFU\\data\\trainer'
output_name = '7'
rank = 16
epochs = 10
lr = 0.0001
resolution = 512
batch_size = 1
gradient_checkpointing = true
optimizer = 'AdamW8bit'
"""


class ParseAppConfigTests(unittest.TestCase):
    def test_parsea_la_config_real_de_la_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            dataset_dir = out_dir / "7"
            dataset_dir.mkdir()
            path = write_config(dataset_dir, out_dir, rank=8, epochs=3, lr=5e-5)
            config = wrapper.parse_app_config(path.read_text(encoding="utf-8"))
        self.assertEqual(config["output_name"], "7")
        self.assertEqual(config["rank"], 8)
        self.assertEqual(config["epochs"], 3)
        self.assertEqual(config["lr"], 5e-5)
        self.assertTrue(config["gradient_checkpointing"])
        self.assertEqual(config["optimizer"], "AdamW8bit")
        self.assertEqual(config["resolution"], 512)

    def test_ignora_claves_desconocidas_y_comentarios(self):
        config = wrapper.parse_app_config(APP_CONFIG + "otra_clave = 3\n")
        self.assertNotIn("otra_clave", config)

    def test_config_incompleta_falla(self):
        with self.assertRaises(ValueError):
            wrapper.parse_app_config("rank = 16\n")


class DatasetTomlTests(unittest.TestCase):
    def test_apunta_al_img_de_la_app_con_captions(self):
        config = wrapper.parse_app_config(APP_CONFIG)
        text = wrapper.build_dataset_toml(config)
        self.assertIn("[general]", text)
        self.assertIn("enable_bucket = true", text)
        self.assertIn("[[datasets.subsets]]", text)
        self.assertIn("image_dir = 'E:\\IA\\WAIFU\\data\\trainer\\7\\img'", text)
        self.assertIn("caption_extension = '.txt'", text)
        self.assertIn("resolution = 512", text)
        self.assertIn("batch_size = 1", text)

    def test_imagen_dir_con_apostrofo_se_escapa(self):
        config = wrapper.parse_app_config(APP_CONFIG)
        config["source_image_dir"] = "E:\\O'Brien\\trainer\\7"
        text = wrapper.build_dataset_toml(config)
        expected = 'image_dir = "E:\\\\O\'Brien\\\\trainer\\\\7\\\\img"'
        self.assertIn(expected, text)
        self.assertNotIn("image_dir = 'E:\\O'Brien", text)


class TrainArgsTests(unittest.TestCase):
    def _args(self, **overrides):
        config = wrapper.parse_app_config(APP_CONFIG)
        config.update(overrides)
        weights = {
            "base_model": r"E:\base.safetensors",
            "qwen3": r"E:\te.safetensors",
            "vae": r"E:\vae.safetensors",
        }
        return wrapper.build_train_args(
            config, dataset_config=r"E:\t\train_dataset.toml", weights=weights
        )

    def test_incluye_network_module_y_pesos_anima(self):
        args = self._args()
        self.assertIn("--network_module", args)
        self.assertEqual(args[args.index("--network_module") + 1], "networks.lora_anima")
        self.assertEqual(
            args[args.index("--pretrained_model_name_or_path") + 1], r"E:\base.safetensors"
        )
        self.assertEqual(args[args.index("--qwen3") + 1], r"E:\te.safetensors")
        self.assertEqual(args[args.index("--vae") + 1], r"E:\vae.safetensors")

    def test_mapea_rank_epochs_lr_y_salida(self):
        args = self._args(rank=32, epochs=7, lr=0.0002)
        self.assertEqual(args[args.index("--network_dim") + 1], "32")
        self.assertEqual(args[args.index("--network_alpha") + 1], "32")
        self.assertEqual(args[args.index("--max_train_epochs") + 1], "7")
        self.assertEqual(args[args.index("--learning_rate") + 1], "0.0002")
        self.assertEqual(args[args.index("--output_name") + 1], "7")
        self.assertEqual(args[args.index("--save_model_as") + 1], "safetensors")
        self.assertEqual(args[args.index("--mixed_precision") + 1], "bf16")
        self.assertIn("--gradient_checkpointing", args)

    def test_sin_gradient_checkpointing_no_anade_flag(self):
        args = self._args(gradient_checkpointing=False)
        self.assertNotIn("--gradient_checkpointing", args)

    def test_optimizer_y_determinismo(self):
        args = self._args()
        self.assertEqual(args[args.index("--optimizer_type") + 1], "AdamW8bit")
        self.assertEqual(args[args.index("--seed") + 1], "0")
        self.assertIn("--cache_latents", args)


class ResolveWeightsTests(unittest.TestCase):
    def test_defaults_bajo_comfy_root(self):
        weights = wrapper.resolve_weights({"WAIFU_COMFY_ROOT": r"E:\COMFY"})
        self.assertEqual(
            weights["base_model"],
            r"E:\COMFY\models\diffusion_models\anima_aestheticV11.safetensors",
        )
        self.assertEqual(
            weights["qwen3"], r"E:\COMFY\models\text_encoders\qwen_3_06b_base.safetensors"
        )
        self.assertEqual(
            weights["vae"], r"E:\COMFY\models\vae\qwen_image_vae.safetensors"
        )

    def test_overrides_explicitos(self):
        env = {
            "WAIFU_COMFY_ROOT": r"E:\COMFY",
            "WAIFU_TRAIN_BASE": r"E:\otro\base.safetensors",
            "WAIFU_TRAIN_QWEN3": r"E:\otro\te.safetensors",
            "WAIFU_TRAIN_VAE": r"E:\otro\vae.safetensors",
        }
        weights = wrapper.resolve_weights(env)
        self.assertEqual(weights["base_model"], r"E:\otro\base.safetensors")
        self.assertEqual(weights["qwen3"], r"E:\otro\te.safetensors")
        self.assertEqual(weights["vae"], r"E:\otro\vae.safetensors")


class RunTests(unittest.TestCase):
    def _config_path(self, tmp: Path) -> Path:
        dataset_dir = tmp / "7"
        dataset_dir.mkdir()
        out_dir = tmp
        return write_config(dataset_dir, out_dir)

    def test_dry_run_escribe_dataset_y_no_ejecuta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config_path(Path(tmp))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = wrapper.run(path, dry_run=True)
            dataset_toml = Path(tmp) / "train_dataset.toml"
            self.assertEqual(code, 0)
            self.assertTrue(dataset_toml.is_file())
            self.assertIn("anima_train_network.py", buffer.getvalue())
            self.assertIn("networks.lora_anima", buffer.getvalue())

    def test_lanza_el_entrenador_con_cwd_y_argv(self):
        calls: list[dict] = []

        class FakeCompleted:
            returncode = 5

        def fake_runner(argv, *, cwd, env):
            calls.append({"argv": argv, "cwd": cwd, "env": env})
            return FakeCompleted()

        with tempfile.TemporaryDirectory() as tmp:
            path = self._config_path(Path(tmp))
            code = wrapper.run(path, runner=fake_runner)
        self.assertEqual(code, 5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["cwd"], str(wrapper.SD_SCRIPTS_DIR))
        self.assertEqual(calls[0]["argv"][1], str(wrapper.SD_SCRIPTS_DIR / "anima_train_network.py"))
        self.assertIn("--network_module", calls[0]["argv"])

    def test_run_falla_claro_sin_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config_path(Path(tmp))
            original = wrapper.SD_SCRIPTS_DIR
            try:
                wrapper.SD_SCRIPTS_DIR = Path(tmp) / "no-existe"
                with self.assertRaises(FileNotFoundError):
                    wrapper.run(path, dry_run=True)
            finally:
                wrapper.SD_SCRIPTS_DIR = original


class MainTests(unittest.TestCase):
    def test_uso_sin_config(self):
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = wrapper.main([])
        self.assertEqual(code, 2)
        self.assertIn("run_waifu_train.py", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
