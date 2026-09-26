"""Tests CPU del motion de video (F4). Sin red, GPU ni LLM real.

El golden de `SYS_PROMPT_MOTION`/`MOTION_NEGATIVE` está INTERNALIZADO como
literal certificado (copiado exacto del legacy retirado el 2026-09-26 y
archivado en `data\\gates\\m10\\evidencia-legacy\\motion.py`, fuera de git):
la suite no depende de ninguna ruta legacy en disco.
"""

from __future__ import annotations

import unittest

from app.engine import EngineError
from app.enhancer import load_local_llm as enhancer_load_local_llm
from app.motion import (
    MOTION_NEGATIVE,
    SYS_PROMPT_MOTION,
    clean_motion,
    load_local_llm,
    write_motion,
)

GOLDEN_MOTION_NEGATIVE = (
    "worst quality, low quality, blurry, static image, no motion, mosaic censoring, "
    "bar censor, child, teen, loli, young-looking, deformed hands, extra limbs"
)

GOLDEN_SYS_PROMPT_MOTION = (
    "Eres el escritor de motion prompts de un generador de video anime local "
    "(Wan 2.2 I2V).\n"
    "Recibes en lenguaje natural (espanol) lo que debe pasar en el video y el rating activo.\n"
    "Escribe UN motion prompt en INGLES con 1-3 frases naturales (NO tags danbooru, "
    "NO listas, NO comillas, NO preambulo):\n"
    "- describe el movimiento de los cuerpos y de la camara (handheld, estatica, leve "
    "paneo...) manteniendo la coherencia con el frame de entrada (I2V);\n"
    "- si rating=nsfw se explicito con el acto y el movimiento, sin eufemismos; NUNCA "
    "describas ni pidas censura (nada de mosaic/bar censor);\n"
    "- HARD RULE: todos los personajes son adultos (21+); nunca menores ni los terminos "
    "child, teen, loli o young-looking;\n"
    "- las lineas internas de contexto (movimiento/rating/duracion) son referencia: "
    "nunca las copies literalmente;\n"
    "- responde SOLO con el motion prompt."
)


class FakeLLM:
    def __init__(self, output: str = "She walks slowly.") -> None:
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str):
        self.calls.append((system, user))
        return self.output


class GoldenTests(unittest.TestCase):
    def test_sys_prompt_es_la_copia_certificada_del_legacy(self):
        self.assertEqual(SYS_PROMPT_MOTION, GOLDEN_SYS_PROMPT_MOTION)

    def test_motion_negative_es_la_copia_certificada_del_legacy(self):
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
