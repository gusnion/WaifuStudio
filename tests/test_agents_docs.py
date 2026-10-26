"""Contratos mínimos de la documentación para agentes (PL-27/28)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDES = ROOT / "docs" / "agent-guides" / "README.md"
SKILL = ROOT / "SKILL.md"


class AgentDocumentationTests(unittest.TestCase):
    def test_ocho_guias(self):
        text = GUIDES.read_text(encoding="utf-8")
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertGreaterEqual(len(headings), 8)
        for topic in ("checkpoint", "imagen", "vídeo", "Editar", "Upscaler", "Galería", "Addons", "Diagnóstico"):
            self.assertIn(topic, text)

    def test_skill_once_secciones(self):
        text = SKILL.read_text(encoding="utf-8")
        for number in range(1, 12):
            self.assertIn(f"## {number}.", text)
        for endpoint in ("/api/generate", "/api/editor", "/api/upscale", "/api/addons"):
            self.assertIn(endpoint, text)


if __name__ == "__main__":
    unittest.main()
