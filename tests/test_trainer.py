"""Tests CPU del entrenador de LoRA (M9-E1). Sin GPU, red ni entrenador real."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from app import loras
from app.config import EngineConfig
from app.engine import EngineError
from app.store import Store
from app.trainer import (
    MAX_IMAGES,
    MIN_IMAGES,
    TRAINER_CMD_ENV,
    prepare_dataset,
    register_lora,
    run_training,
    train_character,
    write_config,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"trainer-fake-png"
MODEL_ID = "anima-2.9b-preview"


class TrainerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.gallery_root = self.root / "data" / "gallery"
        self.out_dir = self.root / "data" / "trainer"
        self.store = Store(self.root / "data" / "waifu.db")
        self.store.init()

    def add_image(
        self,
        *,
        kind: str = "image",
        status: str = "done",
        write: bool = True,
        name: str = "ok.png",
        prompt: str = "1girl, smile",
    ) -> int:
        gen_id = self.store.add(MODEL_ID, prompt, kind=kind)
        if status != "queued":
            self.store.update(gen_id, status=status, outputs=[name] if write else [])
        if write:
            directory = self.gallery_root / str(gen_id)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / name).write_bytes(PNG_BYTES)
        return gen_id

    def ids(self, count: int = MIN_IMAGES, **kwargs) -> list[int]:
        return [self.add_image(**kwargs) for _ in range(count)]

    def char(self, **overrides) -> dict:
        data = {
            "id": 1,
            "name": "Aiko",
            "tags": ["long hair", "smile"],
            "preprompt": "glossy",
            "rating": "sfw",
            "notes": "",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        data.update(overrides)
        return data

    def prepare(self, char: dict, gen_ids: list[int], trigger: str = "aiko") -> dict:
        return prepare_dataset(
            char,
            gen_ids,
            store=self.store,
            gallery_root=self.gallery_root,
            out_dir=self.out_dir,
            trigger=trigger,
        )


class PrepareDatasetTests(TrainerTestCase):
    def test_ok_copia_captions_y_manifest(self):
        gen_ids = self.ids(10)
        result = self.prepare(self.char(), gen_ids)
        dataset_dir = Path(result["dataset_dir"])
        self.assertEqual(dataset_dir, self.out_dir / "1")
        self.assertEqual(result["images"], 10)
        self.assertEqual(result["captions"], 10)
        self.assertEqual(result["trigger"], "aiko")
        img_dir = dataset_dir / "img"
        names = sorted(path.name for path in img_dir.iterdir())
        self.assertEqual(
            names,
            [f"{index:02d}.{ext}" for index in range(1, 11) for ext in ("png", "txt")],
        )
        for index in range(1, 11):
            self.assertEqual((img_dir / f"{index:02d}.png").read_bytes(), PNG_BYTES)
            caption = (img_dir / f"{index:02d}.txt").read_text(encoding="utf-8")
            self.assertEqual(caption.strip(), "aiko, long hair, smile")
        manifest = json.loads(
            (dataset_dir / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["character_id"], 1)
        self.assertEqual(manifest["trigger"], "aiko")
        self.assertEqual(len(manifest["images"]), 10)
        self.assertEqual(manifest["images"][0]["gen_id"], gen_ids[0])
        self.assertEqual(manifest["images"][0]["image"], "img/01.png")
        self.assertEqual(manifest["images"][0]["prompt"], "aiko, long hair, smile")

    def test_caption_no_duplica_el_trigger(self):
        char = self.char(tags=["Aiko", "smile"])
        result = self.prepare(char, self.ids(10), trigger="aiko")
        caption = (
            Path(result["dataset_dir"]) / "img" / "01.txt"
        ).read_text(encoding="utf-8").strip()
        self.assertEqual(caption, "aiko, smile")

    def test_repreparar_borra_stems_sobrantes(self):
        self.prepare(self.char(), self.ids(12))
        result = self.prepare(self.char(), self.ids(10))
        names = sorted(
            path.name for path in (Path(result["dataset_dir"]) / "img").iterdir()
        )
        self.assertEqual(len(names), 20)
        self.assertNotIn("11.png", names)

    def test_menos_de_diez_lanza(self):
        with self.assertRaises(EngineError) as ctx:
            self.prepare(self.char(), self.ids(9))
        self.assertIn("entre 10 y 50", str(ctx.exception))

    def test_mas_de_cincuenta_lanza(self):
        with self.assertRaises(EngineError) as ctx:
            self.prepare(self.char(), self.ids(MAX_IMAGES + 1))
        self.assertIn("entre 10 y 50", str(ctx.exception))

    def test_gen_ids_no_lista_o_no_entera_lanza(self):
        for gen_ids in (None, "x", 10, [1, True], [1, "2"], [1, 2.5]):
            with self.subTest(gen_ids=gen_ids):
                with self.assertRaises(EngineError):
                    self.prepare(self.char(), gen_ids)

    def test_gen_ids_duplicados_lanza(self):
        gen_ids = self.ids(10)
        with self.assertRaises(EngineError) as ctx:
            self.prepare(self.char(), [*gen_ids[:-1], gen_ids[0]])
        self.assertIn("duplicado", str(ctx.exception))

    def test_gen_id_desconocido_lanza(self):
        gen_ids = [*self.ids(9), 9999]
        with self.assertRaises(EngineError) as ctx:
            self.prepare(self.char(), gen_ids)
        self.assertIn("desconocida", str(ctx.exception))

    def test_kind_no_imagen_lanza(self):
        gen_ids = [*self.ids(9), self.add_image(kind="video", name="clip.mp4")]
        with self.assertRaises(EngineError) as ctx:
            self.prepare(self.char(), gen_ids)
        self.assertIn("no es imagen", str(ctx.exception))

    def test_status_no_done_lanza(self):
        gen_ids = [*self.ids(9), self.add_image(status="queued")]
        with self.assertRaises(EngineError) as ctx:
            self.prepare(self.char(), gen_ids)
        self.assertIn("sin terminar", str(ctx.exception))

    def test_archivo_ausente_lanza(self):
        gen_ids = [*self.ids(9), self.add_image(write=False)]
        with self.assertRaises(EngineError) as ctx:
            self.prepare(self.char(), gen_ids)
        self.assertIn("no encontrado", str(ctx.exception))

    def test_char_o_trigger_invalidos_lanzan(self):
        for char in (None, "Aiko", {}, {"id": 0}, {"id": True}):
            with self.subTest(char=char):
                with self.assertRaises(EngineError):
                    self.prepare(char, self.ids(10))
        for trigger in ("", "   ", None, 5):
            with self.subTest(trigger=trigger):
                with self.assertRaises(EngineError):
                    self.prepare(self.char(), self.ids(10), trigger=trigger)


class WriteConfigTests(TrainerTestCase):
    def load(self, path: Path) -> dict:
        return tomllib.loads(path.read_text(encoding="utf-8"))

    def test_claves_valores_y_aviso_m10(self):
        dataset_dir = self.root / "dataset" / "7"
        path = write_config(dataset_dir, self.out_dir, rank=8, epochs=3, lr=2e-4)
        self.assertEqual(path, self.out_dir / "train_config.toml")
        self.assertTrue(path.is_file())
        data = self.load(path)
        self.assertEqual(data["source_image_dir"], str(dataset_dir))
        self.assertEqual(data["output_dir"], str(self.out_dir))
        self.assertEqual(data["output_name"], "7")
        self.assertEqual(data["rank"], 8)
        self.assertEqual(data["epochs"], 3)
        self.assertAlmostEqual(data["lr"], 2e-4)
        self.assertEqual(data["resolution"], 512)
        self.assertEqual(data["batch_size"], 1)
        self.assertIs(data["gradient_checkpointing"], True)
        self.assertEqual(data["optimizer"], "AdamW8bit")
        text = path.read_text(encoding="utf-8")
        self.assertIn("M10", text)
        self.assertIn("revisar claves contra el fork kohya de Anima", text)

    def test_defaults(self):
        path = write_config(self.root / "dataset" / "1", self.out_dir)
        data = self.load(path)
        self.assertEqual(data["rank"], 16)
        self.assertEqual(data["epochs"], 10)
        self.assertAlmostEqual(data["lr"], 1e-4)

    def test_parametros_invalidos_lanzan(self):
        for kwargs in (
            {"rank": 0},
            {"rank": True},
            {"rank": "16"},
            {"epochs": -1},
            {"lr": 0},
            {"lr": "abc"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(EngineError):
                    write_config(self.root / "dataset" / "1", self.out_dir, **kwargs)


class RunTrainingTests(TrainerTestCase):
    def setUp(self):
        super().setUp()
        self.config_path = self.root / "train_config.toml"
        self.config_path.write_text("rank = 1\n", encoding="utf-8")

    def test_cmd_falso_exit_0_y_log(self):
        log = self.root / "logs" / "train.log"
        code = run_training(
            self.config_path,
            cmd=["cmd", "/c", "echo", "hola"],
            log_path=log,
            timeout_s=30,
        )
        self.assertEqual(code, 0)
        self.assertIn("hola", log.read_text(encoding="utf-8"))

    def test_log_en_append(self):
        log = self.root / "train.log"
        run_training(
            self.config_path, cmd=["cmd", "/c", "echo", "hola"], log_path=log, timeout_s=30
        )
        run_training(
            self.config_path, cmd=["cmd", "/c", "echo", "hola"], log_path=log, timeout_s=30
        )
        self.assertEqual(log.read_text(encoding="utf-8").lower().count("hola"), 2)

    def test_env_define_el_comando(self):
        log = self.root / "train.log"
        code = run_training(
            self.config_path,
            env={TRAINER_CMD_ENV: "cmd /c echo env"},
            log_path=log,
            timeout_s=30,
        )
        self.assertEqual(code, 0)
        self.assertIn("env", log.read_text(encoding="utf-8"))

    def test_sin_cmd_ni_env_lanza(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EngineError) as ctx:
                run_training(self.config_path)
        self.assertEqual(str(ctx.exception), "entrenador no instalado (M10)")

    def test_cmd_invalido_o_config_ausente_lanzan(self):
        with self.assertRaises(EngineError):
            run_training(self.config_path, cmd=[], timeout_s=30)
        with self.assertRaises(EngineError):
            run_training(self.config_path, cmd="cmd /c echo x", timeout_s=30)
        with self.assertRaises(EngineError):
            run_training(self.root / "no-existe.toml", cmd=["cmd", "/c", "echo", "x"])

    def test_timeout_mata_y_lanza(self):
        with self.assertRaises(EngineError) as ctx:
            run_training(
                self.config_path,
                cmd=[sys.executable, "-c", "import time; time.sleep(30)"],
                timeout_s=1,
            )
        self.assertIn("excedio", str(ctx.exception))

    def test_exit_code_no_cero_se_devuelve(self):
        code = run_training(
            self.config_path,
            cmd=[sys.executable, "-c", "import sys; sys.exit(3)"],
            timeout_s=30,
        )
        self.assertEqual(code, 3)


class RegisterLoraTests(TrainerTestCase):
    def setUp(self):
        super().setUp()
        self.registry_path = self.root / "registry" / "loras.json"
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps({"version": 1, "loras": []}), encoding="utf-8"
        )
        self.comfy_loras = self.root / "comfy" / "models" / "loras"
        self.lora_file = self.root / "out" / "1.safetensors"
        self.lora_file.parent.mkdir(parents=True, exist_ok=True)
        self.lora_file.write_bytes(b"fake-safetensors")

    def register(self, **overrides) -> dict:
        char = overrides.pop("char", self.char())
        kwargs = {
            "comfy_loras_dir": self.comfy_loras,
            "trigger": "aiko",
            "registry_path": self.registry_path,
        }
        kwargs.update(overrides)
        return register_lora(char, self.lora_file, **kwargs)

    def test_copia_y_registra_entry(self):
        entry = self.register()
        target = self.comfy_loras / "waifu" / "1.safetensors"
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), b"fake-safetensors")
        self.assertEqual(entry["id"], "oc-1")
        self.assertEqual(entry["family"], "anima")
        self.assertEqual(entry["trigger"], "aiko")
        self.assertEqual(entry["default_weight"], 0.8)
        self.assertEqual(entry["source"], "entrenado local (M9-E)")
        self.assertEqual(entry["license"], "local")
        self.assertIn("entrenado", entry["notes"])
        registered = loras.get("oc-1", path=self.registry_path)
        self.assertEqual(
            registered["file"], str(Path("waifu") / "1.safetensors")
        )
        self.assertEqual(
            [item["id"] for item in loras.list_loras(path=self.registry_path)],
            ["oc-1"],
        )

    def test_display_name_personalizado_y_por_defecto(self):
        self.assertEqual(self.register()["display_name"], "OC Aiko")
        custom = self.register(char=self.char(id=2), display_name="Aiko v1")
        self.assertEqual(custom["display_name"], "Aiko v1")

    def test_archivo_inexistente_o_no_safetensors_lanza(self):
        with self.assertRaises(EngineError):
            register_lora(
                self.char(),
                self.root / "nope.safetensors",
                comfy_loras_dir=self.comfy_loras,
                trigger="aiko",
                registry_path=self.registry_path,
            )
        other = self.root / "1.ckpt"
        other.write_bytes(b"x")
        with self.assertRaises(EngineError):
            register_lora(
                self.char(),
                other,
                comfy_loras_dir=self.comfy_loras,
                trigger="aiko",
                registry_path=self.registry_path,
            )

    def test_duplicado_lanza_y_conserva_registro(self):
        self.register()
        with self.assertRaises(EngineError):
            self.register()
        self.assertEqual(
            [item["id"] for item in loras.list_loras(path=self.registry_path)],
            ["oc-1"],
        )

    def test_trigger_o_char_invalidos_lanzan(self):
        with self.assertRaises(EngineError):
            self.register(trigger="  ")
        with self.assertRaises(EngineError):
            register_lora(
                {"id": 0},
                self.lora_file,
                comfy_loras_dir=self.comfy_loras,
                trigger="aiko",
                registry_path=self.registry_path,
            )


class TrainCharacterTests(TrainerTestCase):
    FAKE_TRAINER = (
        "import pathlib, re, sys\n"
        "config = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "out_dir = re.search(r\"output_dir = '([^']+)'\", config).group(1)\n"
        "name = re.search(r\"output_name = '([^']+)'\", config).group(1)\n"
        "target = pathlib.Path(out_dir) / f'{name}.safetensors'\n"
        "target.write_bytes(b'lora-entrenada')\n"
        "print('entrenado', target)\n"
    )

    def setUp(self):
        super().setUp()
        self.config = EngineConfig(
            comfy_root=self.root / "comfy",
            comfy_url="http://127.0.0.1:1",
            data_dir=self.root / "data",
        )
        self.registry_path = self.root / "registry" / "loras.json"
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps({"version": 1, "loras": []}), encoding="utf-8"
        )
        self.script = self.root / "fake_train.py"
        self.script.write_text(self.FAKE_TRAINER, encoding="utf-8")

    def test_pipeline_completo_con_entrenador_falso(self):
        result = train_character(
            self.char(),
            self.ids(10),
            store=self.store,
            config=self.config,
            trigger="aiko",
            cmd=[sys.executable, str(self.script)],
            registry_path=self.registry_path,
            timeout_s=60,
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["character_id"], 1)
        self.assertEqual(result["trigger"], "aiko")
        self.assertEqual(result["dataset"]["images"], 10)
        self.assertTrue(Path(result["config_path"]).is_file())
        self.assertTrue(Path(result["lora_path"]).is_file())
        self.assertTrue(Path(result["log_path"]).is_file())
        self.assertIn("entrenado", Path(result["log_path"]).read_text(encoding="utf-8"))
        target = self.config.comfy_root / "models" / "loras" / "waifu" / "1.safetensors"
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), b"lora-entrenada")
        self.assertEqual(result["entry"]["id"], "oc-1")
        self.assertEqual(
            [item["id"] for item in loras.list_loras(path=self.registry_path)],
            ["oc-1"],
        )

    def test_trigger_por_defecto_es_el_nombre(self):
        result = train_character(
            self.char(),
            self.ids(10),
            store=self.store,
            config=self.config,
            cmd=[sys.executable, str(self.script)],
            registry_path=self.registry_path,
            timeout_s=60,
        )
        self.assertEqual(result["trigger"], "Aiko")

    def test_exit_no_cero_lanza(self):
        with self.assertRaises(EngineError) as ctx:
            train_character(
                self.char(),
                self.ids(10),
                store=self.store,
                config=self.config,
                cmd=[sys.executable, "-c", "import sys; sys.exit(3)"],
                registry_path=self.registry_path,
                timeout_s=60,
            )
        self.assertIn("codigo 3", str(ctx.exception))

    def test_sin_lora_de_salida_lanza(self):
        with self.assertRaises(EngineError) as ctx:
            train_character(
                self.char(),
                self.ids(10),
                store=self.store,
                config=self.config,
                cmd=[sys.executable, "-c", "pass"],
                registry_path=self.registry_path,
                timeout_s=60,
            )
        self.assertIn("no encontrada", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
