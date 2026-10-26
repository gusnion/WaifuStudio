"""El instalador de FFmpeg debe fijar URL, tamaño y SHA256 (PL-30)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install" / "install.ps1"


class FfmpegInstallTests(unittest.TestCase):
    def test_url_y_hash_fijados(self):
        text = INSTALL.read_text(encoding="utf-8")
        self.assertNotIn("-Sha256 ''", text)
        self.assertIn("BtbN/FFmpeg-Builds/releases/download/autobuild-", text)
        self.assertRegex(text, r"\$sha256 = '[0-9a-f]{64}'")
        self.assertRegex(text, r"\$bytes = 193050101")

    def test_aviso_gpl(self):
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertRegex(notices, r"FFmpeg.*GPL")


if __name__ == "__main__":
    unittest.main()
