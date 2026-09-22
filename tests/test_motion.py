"""Tests CPU del motion de video (F4). Sin red, GPU ni LLM real.

El golden de `SYS_PROMPT_MOTION`/`MOTION_NEGATIVE` se extrae por AST del archivo
legacy certificado (`E:\\IA\\VIDEO\\local_prompt_planner\\motion.py`, solo lectura);
si el legacy no esta montado, ese test se salta.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.engine import EngineError
from app.enhancer import load_local_llm as enhancer_load_local_llm
from app.motion import (
    MOTION_NEGATIVE,
    SYS_PROMPT_MOTION,
    clean_motion,
    load_local_llm,
    write_motion,
)

LEGACY_MOTION_PY = Path(r"E:\IA\VIDEO\local_prompt_planner\motion.py")

GOLDEN_MOTION_NEGATIVE = (
    "worst quality, low quality, blurry, static image, no motion, mosaic censoring, "
    "bar censor, child, teen, loli, young-looking, deformed hands, extra limbs"
)


def legacy_constants() -> dict:
    """Extrae las constantes del legacy por AST (sin importarlo)."""
    tree = ast.parse(LEGACY_MOTION_PY.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    continue
    return values


class FakeLLM:
    def __init__(self, output: str = "She walks slowly.") -> None:
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str):
        self.calls.append((system, user))
        return self.output


class GoldenTests(unittest.TestCase):
    def setUp(self):
        if not LEGACY_MOTION_PY.is_file():
            self.skipTest(f"legacy no disponible: {LEGACY_MOTION_PY}")
        self.legacy = legacy_constants()

    def test_sys_prompt_es_copia_exacta_del_legacy(self):
        self.assertEqual(SYS_PROMPT_MOTION, self.legacy["SYS_PROMPT_MOTION"])

    def test_motion_negative_es_copia_exacta_del_legacy(self):
        self.assertEqual(MOTION_NEGATIVE, self.legacy["MOTION_NEGATIVE"])

    def test_motion_negative_es_el_literal_certificado(self):
        self.assertEqual(MOTION_NEGATIVE, GOLDEN_MOTION_NEGATIVE)

    def test_sys_prompt_estructura(self):
        self.assertTrue(SYS_PROMPT_MOTION.startswith("Eres el escritor de motion prompts"))
        self.assertTrue(SYS_PROMPT_MOTION.endswith("responde SOLO con el motion prompt."))
        self.assertIn("HARD RULE", SYS_PROMPT_MOTION)
        self.assertNotIn("\r", SYS_PROMPT_MOTION)

    def test_loader_se_reutiliza_de_enhancer(self):
        self.assertIs(load_local_llm, enhancer_load_local_llm)


class CleanMotionTests(unittest.TestCase):
    def test_colapsa_espacios_y_saltos(self):
        self.assertEqual(clean_motion("  She   walks.\nSlowly.  "), "She walks. Slowly.")

    def test_quita_comillas_envolventes(self):
        self.assertEqual(clean_motion('"She walks."'), "She walks.")
        self.assertEqual(clean_motion("'She walks.'"), "She walks.")
        self.assertEqual(clean_motion("`She walks.`"), "She walks.")

    def test_no_toca_comillas_no_envolventes(self):
        self.assertEqual(clean_motion('She said "go" then left.'), 'She said "go" then left.')

    def test_texto_vacio_lanza_engine_error(self):
        for value in ("", "   ", "\n\t ", None, 42):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    clean_motion(value)


class WriteMotionTests(unittest.TestCase):
    MOTION = "la chica camina"

    def test_resultado_y_negativo_fijo(self):
        llm = FakeLLM('  "She walks   slowly."\n')
        result = write_motion(self.MOTION, rating="nsfw", llm=llm)
        self.assertEqual(
            result,
            {"motion_positive": "She walks slowly.", "motion_negative": MOTION_NEGATIVE},
        )

    def test_mensajes_al_llm(self):
        llm = FakeLLM()
        write_motion(self.MOTION, rating="sfw", llm=llm)
        self.assertEqual(len(llm.calls), 1)
        system, user = llm.calls[0]
        self.assertEqual(system, SYS_PROMPT_MOTION)
        self.assertTrue(user.startswith("movimiento: la chica camina"))
        self.assertIn("rating: sfw", user)
        self.assertIn("Escribe solo el motion prompt en ingles.", user)

    def test_rating_por_defecto_nsfw(self):
        llm = FakeLLM()
        write_motion(self.MOTION, llm=llm)
        _system, user = llm.calls[0]
        self.assertIn("rating: nsfw", user)

    def test_texto_se_normaliza(self):
        llm = FakeLLM()
        write_motion("  la chica camina  ", llm=llm)
        _system, user = llm.calls[0]
        self.assertIn("movimiento: la chica camina\n", user)

    def test_movimiento_vacio_lanza_engine_error(self):
        for value in ("", "   ", None, 7):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    write_motion(value, llm=FakeLLM())

    def test_rating_invalido_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            write_motion(self.MOTION, rating="explicit", llm=FakeLLM())

    def test_sin_llm_lanza_engine_error(self):
        with self.assertRaises(EngineError) as ctx:
            write_motion(self.MOTION)
        self.assertEqual(str(ctx.exception), "LLM no inyectado")

    def test_llm_no_texto_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            write_motion(self.MOTION, llm=lambda _s, _u: None)

    def test_llm_vacio_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            write_motion(self.MOTION, llm=lambda _s, _u: "   ")


if __name__ == "__main__":
    unittest.main()
