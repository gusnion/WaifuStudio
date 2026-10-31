"""Comprobaciones estáticas del despliegue Linux (scripts y manifiesto)."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "install-linux.sh",
    "start-linux.sh",
    "stop-linux.sh",
    "healthcheck.sh",
    "download-wan.sh",
    "download-wd14.sh",
)


class LinuxDeployFilesTests(unittest.TestCase):
    def test_scripts_presentes(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                path = ROOT / name
                self.assertTrue(path.is_file(), f"falta {name}")
                self.assertGreater(path.stat().st_size, 0)

    def test_scripts_sin_rutas_de_workspace(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertNotIn("/workspace/", text)

    def test_bash_syntax_si_hay_bash(self):
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash no disponible en este sistema")
        for name in SCRIPTS:
            with self.subTest(script=name):
                result = subprocess.run(
                    [bash, "-n", str(ROOT / name)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_readmes_enlazan_linux(self):
        for name in ("README.md", "README.es.md"):
            with self.subTest(readme=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("install-linux.sh", text)

    def test_manifiesto_llm_linux(self):
        path = ROOT / "install" / "manifest" / "manifest.llm.linux.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        files = data.get("files") or []
        runtimes = [item for item in files if item.get("kind") == "runtime"]
        self.assertEqual(len(runtimes), 1)
        runtime = runtimes[0]
        self.assertTrue(runtime["filename"].endswith(".tar.gz"))
        self.assertEqual(runtime.get("strip_components"), 1)
        self.assertTrue((ROOT / "scripts" / "download_llm.py").is_file())


if __name__ == "__main__":
    unittest.main()
