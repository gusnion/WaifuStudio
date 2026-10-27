"""Contratos estáticos del tema claro y los iconos de pestañas."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LightThemeAssetsTests(unittest.TestCase):
    def test_light_theme_css_carga_y_cubre_componentes(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "light-theme.css").read_text(encoding="utf-8")
        self.assertIn("/static/css/light-theme.css", html)
        for selector in (
            ".image-category-header",
            ".image-preview",
            "#btn-seed-random",
            ".gallery-badge",
            ".guide-hero",
            ".guide-step-card",
            ".guide-section",
            "#panel-upscaler #upscale-preview",
            ".tooltip-popover",
            ".btn-help",
        ):
            self.assertIn(selector, css)

    def test_pestanas_llevan_icono_svg(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="tab-icon"'), 8)
        nav = html.split('<nav class="tabs">', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("🎬 Estudio", nav)
        self.assertNotIn("📖 Guía", nav)


if __name__ == "__main__":
    unittest.main()
