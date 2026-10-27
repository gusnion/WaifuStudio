"""Tests para verificar que registry/recommended-v1.json contiene exactamente
los 4 modelos del set recomendado (Anima, Animagine, RealVisXL, JuggernautXL)
con sus correspondientes familias (anima para Anima y sdxl para el resto).
"""

import json
from pathlib import Path
import unittest


class TestRecommendedModels(unittest.TestCase):
    def test_recommended_models_set_and_families(self):
        repo_root = Path(__file__).resolve().parent.parent
        recommended_path = repo_root / "registry" / "recommended-v1.json"
        self.assertTrue(recommended_path.exists(), f"No existe {recommended_path}")

        with open(recommended_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        models = data.get("models", [])
        expected_models = {
            "anima-official-aesthetic-v11": {
                "display_name_substring": "Anima",
                "family": "anima",
            },
            "animagine-xl-4-opt": {
                "display_name_substring": "Animagine",
                "family": "sdxl",
            },
            "realvisxl-v50": {
                "display_name_substring": "RealVisXL",
                "family": "sdxl",
            },
            "juggernaut-xl-ragnarok": {
                "display_name_substring": "Juggernaut",
                "family": "sdxl",
            },
        }

        self.assertEqual(
            len(models),
            4,
            f"Se esperaban exactamente 4 modelos en recommended-v1.json, encontrados: {len(models)}",
        )

        model_map = {m["id"]: m for m in models}
        self.assertEqual(
            set(model_map.keys()),
            set(expected_models.keys()),
            "El set de IDs de modelos no coincide exactamente con los 4 esperados.",
        )

        for model_id, expected_info in expected_models.items():
            model = model_map[model_id]
            self.assertEqual(
                model.get("family"),
                expected_info["family"],
                f"Familia incorrecta para {model_id}. Esperada: {expected_info['family']}, obtenida: {model.get('family')}",
            )
            self.assertIn(
                expected_info["display_name_substring"].lower(),
                model.get("display_name", "").lower(),
                f"El display_name de {model_id} no contiene '{expected_info['display_name_substring']}'",
            )


if __name__ == "__main__":
    unittest.main()
