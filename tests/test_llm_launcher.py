"""Tests offline de los launchers del LLM M11-2E (scripts/*.ps1 + .bat).

Solo leen el contenido de los archivos: no ejecutan PowerShell ni arrancan
llama-server. Cubren la existencia de los 4 launchers y los marcadores del
contrato de `scripts/start_llm.ps1` y `scripts/stop_llm.ps1`.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherFilesTests(unittest.TestCase):
    def test_existen_los_cuatro_launchers(self):
        for name in (
            "scripts/start_llm.ps1",
            "scripts/stop_llm.ps1",
            "INICIAR_LLM.bat",
            "DETENER_LLM.bat",
        ):
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file(), f"falta {name}")

    def test_bat_llaman_a_sus_ps1(self):
        self.assertIn(
            'scripts\\start_llm.ps1',
            (ROOT / "INICIAR_LLM.bat").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'scripts\\stop_llm.ps1',
            (ROOT / "DETENER_LLM.bat").read_text(encoding="utf-8"),
        )


class StartLlmScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "scripts" / "start_llm.ps1").read_text(encoding="utf-8")

    def test_marcadores_del_comando(self):
        for marker in (
            "llama-server.exe",
            "--mmproj",
            "--jinja",
            "-fa on",
            "--spec-type draft-mtp",
            "--spec-draft-n-max",
            "--no-mmproj-offload",
            "-np 1",
            "--reasoning off",
            "--fit on",
            "draft-mtp",
            "--device",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_dispositivo_por_defecto_cuda0(self):
        self.assertIn("CUDA0", self.text)
        self.assertIn("WAIFU_LLM_DEVICE", self.text)

    def test_modelo_y_mmproj_del_manifiesto(self):
        self.assertIn("qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf", self.text)
        self.assertIn(
            "mmproj-Qwen3.8-27B-AEON-ULTIMATE-UNCENSORED-BF16.gguf", self.text
        )

    def test_puerto_por_defecto_y_entorno(self):
        for marker in (
            "8290",
            "WAIFU_LLM_PORT",
            "WAIFU_LLM_CTX",
            "WAIFU_LLM_DRAFT_NMAX",
            "WAIFU_LLM_NGL",
            "WAIFU_LLM_MMPROJ_GPU",
            "WAIFU_LLM_EXTRA_ARGS",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_avisa_si_faltan_archivos_y_sugiere_descarga(self):
        self.assertIn("download_llm.py", self.text)
        self.assertIn("exit 1", self.text)

    def test_reutiliza_el_patron_de_propietario_del_puerto(self):
        self.assertIn("Get-NetTCPConnection", self.text)
        self.assertIn("tools\\llama.cpp", self.text)
        self.assertIn("exit 0", self.text)


class VerifyWaifuBatTests(unittest.TestCase):
    def test_reenvia_argumentos_a_app_health(self):
        text = (ROOT / "VERIFICAR_WAIFU.bat").read_text(encoding="utf-8")
        self.assertIn("app.health", text)
        self.assertIn("%*", text)


class StartAppScriptTests(unittest.TestCase):
    def test_llm_url_solo_con_exe_modelo_y_mmproj(self):
        text = (ROOT / "scripts" / "start_app.ps1").read_text(encoding="utf-8")
        for marker in (
            "WAIFU_LLM_URL",
            "llama-server.exe",
            "ComfyUI\\models\\llm\\qwen38-27b-uncensored",
            "qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf",
            "mmproj-Qwen3.8-27B-AEON-ULTIMATE-UNCENSORED-BF16.gguf",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class StopLlmScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "scripts" / "stop_llm.ps1").read_text(encoding="utf-8")

    def test_solo_para_procesos_de_llama_cpp(self):
        self.assertIn("tools\\llama.cpp", self.text)
        self.assertIn("Stop-Process", self.text)
        self.assertIn("exit 1", self.text)
        self.assertIn("exit 0", self.text)

    def test_usa_el_puerto_por_defecto_y_entorno(self):
        self.assertIn("8290", self.text)
        self.assertIn("WAIFU_LLM_PORT", self.text)


if __name__ == "__main__":
    unittest.main()
