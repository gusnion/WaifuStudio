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
            "-ngl",
            "--reasoning off",
            "--no-webui",
            "-np 1",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_modelo_y_mmproj_nuevos(self):
        self.assertIn("qwen35-9b-abliterated", self.text)
        self.assertIn("Qwen3.5-9B-abliterated-Q4_K_M.gguf", self.text)
        self.assertIn("mmproj-F16.gguf", self.text)

    def test_modelo_y_mmproj_captioning(self):
        self.assertIn("qwen35-9b-nsfw-captioning", self.text)
        self.assertIn("qwen3.5-9b-nsfw-captioning-v5.Q4_K_M.gguf", self.text)
        self.assertIn("qwen3.5-9b-nsfw-captioning-v5.mmproj-Q8_0.gguf", self.text)

    def test_sin_restos_del_27b(self):
        for marker in (
            "qwen38-27b",
            "3.69bpw",
            "draft-mtp",
            "CUDA0",
            "--device",
            "-fa on",
            "--fit",
            "-ctk",
            "-ctv",
            "WAIFU_LLM_DEVICE",
            "WAIFU_LLM_DRAFT_NMAX",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.text)

    def test_puerto_cpu_y_entorno(self):
        for marker in (
            "8290",
            "WAIFU_LLM_PORT",
            "WAIFU_LLM_CTX",
            "WAIFU_LLM_THREADS",
            "WAIFU_LLM_NGL",
            "WAIFU_LLM_EXTRA_ARGS",
            "ProcessorCount",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_avisa_modo_externo_opcional(self):
        self.assertIn("Modo externo opcional", self.text)

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
    """M12-3: la app gestiona `llama-server`; el launcher ya no toca la env."""

    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "scripts" / "start_app.ps1").read_text(encoding="utf-8")

    def test_ya_no_define_waifu_llm_url(self):
        self.assertNotIn("WAIFU_LLM_URL", self.text)

    def test_mantiene_el_arranque_de_la_app(self):
        for marker in (
            "WAIFU_APP_PORT",
            "app.server",
            "Get-NetTCPConnection",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)


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
