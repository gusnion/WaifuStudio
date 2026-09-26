"""Tests CPU del prompt de video H3 (M10-4e). Sin red, GPU ni LLM real.

El golden de `SYS_PROMPT_H3` esta INTERNALIZADO como literal: si se cambia el
prompt de sistema, el test obliga a actualizarlo a conciencia.
"""

from __future__ import annotations

import unittest

from app.engine import EngineError
from app.enhancer import load_local_llm as enhancer_load_local_llm
from app.h3_prompt import (
    H3_BLOCKS,
    SYS_PROMPT_H3,
    clean_h3_prompt,
    load_local_llm,
    write_h3_prompt,
)

GOLDEN_SYS_PROMPT_H3 = (
    "Eres el escritor de prompts del generador de video anime MiniMax H3 (FL2VA) local.\n"
    "Recibes en lenguaje natural (espanol) lo que debe verse y oirse, y el rating activo.\n"
    "Devuelve EXACTAMENTE tres bloques, uno por linea y en este orden, sin preambulo, "
    "sin comillas y sin explicaciones:\n"
    "integrated_multimodal_description: <sujeto, vestuario, entorno, luz, camara y "
    "movimiento restringido; una sola toma continua, sin cortes>\n"
    "overall_soundscape: <ambiente y efectos; dialogo solo si aplica>\n"
    "non_diegetic_music: <musica o None>\n"
    "- el dialogo va con idioma explicito: <d>[Espanol] texto</d>, con un speaker id "
    "estable declarado antes de las voces (p. ej. speaker_1) y sin llenar mas de ~2/3 "
    "de su plano;\n"
    "- si rating=nsfw se explicito con el acto y el movimiento, sin eufemismos; NUNCA "
    "describas ni pidas censura (nada de mosaic/bar censor);\n"
    "- HARD RULE: todos los personajes son adultos (21+); nunca menores ni los terminos "
    "child, teen, loli o young-looking;\n"
    "- las lineas internas de contexto (escena/rating) son referencia: nunca las copies "
    "literalmente;\n"
    "- responde SOLO con los tres bloques."
)

H3_OUTPUT = (
    "integrated_multimodal_description: 1girl walks by the sea at sunset\n"
    "overall_soundscape: waves and wind\n"
    "non_diegetic_music: None"
)


class FakeLLM:
    def __init__(self, output: str = H3_OUTPUT) -> None:
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.output


class GoldenTests(unittest.TestCase):
    def test_sys_prompt_h3_internalizado(self):
        self.assertEqual(SYS_PROMPT_H3, GOLDEN_SYS_PROMPT_H3)

    def test_bloques_y_estructura(self):
        self.assertEqual(
            H3_BLOCKS,
            (
                "integrated_multimodal_description",
                "overall_soundscape",
                "non_diegetic_music",
            ),
        )
        self.assertTrue(SYS_PROMPT_H3.startswith("Eres el escritor de prompts"))
        self.assertTrue(SYS_PROMPT_H3.endswith("responde SOLO con los tres bloques."))
        self.assertIn("HARD RULE", SYS_PROMPT_H3)
        self.assertNotIn("\r", SYS_PROMPT_H3)

    def test_loader_se_reutiliza_de_enhancer(self):
        self.assertIs(load_local_llm, enhancer_load_local_llm)


class CleanH3PromptTests(unittest.TestCase):
    def test_colapsa_espacios_y_conserva_bloques(self):
        raw = (
            "  integrated_multimodal_description:  a   girl  \n"
            "\n"
            "overall_soundscape:  sea   waves \n"
            "non_diegetic_music: None  "
        )
        self.assertEqual(
            clean_h3_prompt(raw),
            "integrated_multimodal_description: a girl\n"
            "overall_soundscape: sea waves\n"
            "non_diegetic_music: None",
        )

    def test_quita_comillas_envolventes(self):
        quoted = '"' + H3_OUTPUT + '"'
        self.assertEqual(clean_h3_prompt(quoted), H3_OUTPUT)

    def test_falta_bloque_lanza_engine_error(self):
        for raw in (
            "integrated_multimodal_description: a\noverall_soundscape: b",
            "overall_soundscape: b\nnon_diegetic_music: None",
            "solo texto plano",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(EngineError):
                    clean_h3_prompt(raw)

    def test_texto_vacio_lanza_engine_error(self):
        for value in ("", "   ", "\n\t ", None, 42):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    clean_h3_prompt(value)


class WriteH3PromptTests(unittest.TestCase):
    ESCENA = "la chica camina junto al mar"

    def test_resultado_limpio(self):
        llm = FakeLLM('  "' + H3_OUTPUT + '"\n')
        result = write_h3_prompt(self.ESCENA, rating="nsfw", llm=llm)
        self.assertEqual(result, {"h3_prompt": H3_OUTPUT})

    def test_mensajes_al_llm(self):
        llm = FakeLLM()
        write_h3_prompt(self.ESCENA, rating="sfw", llm=llm)
        self.assertEqual(len(llm.calls), 1)
        system, user = llm.calls[0]
        self.assertEqual(system, SYS_PROMPT_H3)
        self.assertTrue(user.startswith("escena: la chica camina junto al mar"))
        self.assertIn("rating: sfw", user)
        self.assertIn("Devuelve solo los tres bloques del prompt H3.", user)

    def test_rating_por_defecto_nsfw(self):
        llm = FakeLLM()
        write_h3_prompt(self.ESCENA, llm=llm)
        _system, user = llm.calls[0]
        self.assertIn("rating: nsfw", user)

    def test_escena_vacia_lanza_engine_error(self):
        for value in ("", "   ", None, 7):
            with self.subTest(value=value):
                with self.assertRaises(EngineError):
                    write_h3_prompt(value, llm=FakeLLM())

    def test_rating_invalido_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            write_h3_prompt(self.ESCENA, rating="explicit", llm=FakeLLM())

    def test_sin_llm_lanza_engine_error(self):
        with self.assertRaises(EngineError) as ctx:
            write_h3_prompt(self.ESCENA)
        self.assertEqual(str(ctx.exception), "LLM no inyectado")

    def test_llm_no_texto_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            write_h3_prompt(self.ESCENA, llm=lambda _s, _u: None)

    def test_llm_sin_bloques_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            write_h3_prompt(self.ESCENA, llm=lambda _s, _u: "   ")


if __name__ == "__main__":
    unittest.main()
