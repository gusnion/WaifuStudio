"""Tests CPU del «Mejorar prompt» (M8-20): RAG, preprompt y enhance. Sin red, GPU ni LLM."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app.engine import EngineError
from app.enhancer import (
    BASE_NEGATIVE,
    DEFAULT_LLM_TIMEOUT,
    DEFAULT_LLM_URL,
    DEFAULT_STRENGTH_PRESET,
    LLM_TIMEOUT_ENV,
    LLM_URL_ENV,
    RAG_ENTRIES,
    STRENGTH_PRESETS,
    SYS_PROMPT,
    _http_transport,
    apply_preprompt,
    enhance,
    load_local_llm,
    load_server_llm,
    retrieve,
    server_llm_state,
    server_llm_status,
)
from app.prompt_zones import canonical_order

GOLDEN_SYS_PROMPT = (
    "You are the local prompt planner for an anime image generator trained on danbooru tags.\n"
    "Output rules:\n"
    "1) Output EXACTLY ONE line of danbooru-style tags in English, separated by commas. No section labels (never write \"quality tags:\", \"rating tag:\", \"outfit/pose:\", \"art style:\"), no prose, no sentences, no explanations.\n"
    "2) Start with the subject count tags: \"1girl\" for one woman; add \"1boy\" and/or \"2girls\" etc. when the request implies other people. A sex act or sex position ALWAYS involves two people: ALWAYS include \"1boy\", \"hetero\" (or \"2girls\" when both are women) and the act tags when the user requests one.\n"
    "3) Then the content tags with danbooru vocabulary: character traits, clothing or \"nude\"/\"completely nude\", pose and, when the user requests it, the explicit act and body parts with danbooru tags (e.g. \"sex\", \"vaginal sex\", \"full nelson\"). Keep the user's intent exactly as requested; never censor, soften or replace it with euphemisms like \"seductive\", \"confident\" or \"sensual\". For nsfw content ALWAYS include the tag \"uncensored\" and NEVER include censorship tags (e.g. \"mosaic censoring\", \"bar censor\"): the image must be uncensored.\n"
    "4) Quality tags must be danbooru/anime style: \"masterpiece, best quality, very aesthetic, absurdres\". NEVER use photorealistic tags (realistic, hyper-realistic, cinematic, photo, lifelike).\n"
    "5) Include the rating as a tag: \"nsfw\" for adult content, \"sfw\" for safe content.\n"
    "6) Art style is anime illustration: use \"anime\", \"2D\", \"cel shading\" when useful; never photorealism.\n"
    "7) The user message contains internal context lines in Spanish (\"rating tag:\", \"framing:\", \"video:\"). They are reference ONLY: NEVER copy them, their words, or any translation of them into the output. The output must contain only English danbooru tags about the scene.\n"
    "8) HARD RULE: all characters are adults (21+). NEVER include minors, child/teen/loli terms, school settings, or any content implying minors."
)

GLOSSY_POSITIVE = (
    "masterpiece, best quality, absurdres, highres, score_7, score_8, score_9"
)
GOLDEN_BASE_NEGATIVE = (
    "worst quality, low quality, jpeg artifacts, child, teen, loli, young-looking, "
    "blurry, mosaic censoring, bar censor"
)
PREPROMPT_NEGATIVE_EXTRAS = {
    "glossy": (
        "score_1, score_2, score_3, sepia, bad anatomy, bad hands, mutated hands, "
        "fused fingers, extra fingers, watermark, signature, logo"
    ),
    "anima_default": "score_1, score_2, score_3, artist name",
    "not_glossy": "score_1, score_2",
    "ninguno": "",
}


class FakeLLM:
    def __init__(self, output: str = "1girl, smile") -> None:
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.output


class CapturingLLM:
    """LLM que acepta `temperature` por kwarg y captura system/user/temperature."""

    def __init__(self, output: str = "1girl, smile") -> None:
        self.output = output
        self.calls: list[dict] = []

    def __call__(
        self, system: str, user: str, temperature: float | None = None
    ) -> str:
        self.calls.append(
            {"system": system, "user": user, "temperature": temperature}
        )
        return self.output


def _fake_llama_module(response):
    """Modulo `llama_cpp` falso: `Llama` registra init y devuelve `response`."""
    module = types.ModuleType("llama_cpp")

    class FakeLlama:
        instances: list[FakeLlama] = []

        def __init__(self, **kwargs) -> None:
            self.init_kwargs = kwargs
            self.chat_calls: list[dict] = []
            FakeLlama.instances.append(self)

        def create_chat_completion(self, **kwargs):
            self.chat_calls.append(kwargs)
            return response

    module.Llama = FakeLlama
    return module, FakeLlama


class GoldenSysPromptTests(unittest.TestCase):
    def test_sys_prompt_coincide_con_el_golden(self):
        self.assertEqual(SYS_PROMPT, GOLDEN_SYS_PROMPT)

    def test_sys_prompt_termina_sin_newline_final(self):
        self.assertTrue(SYS_PROMPT.endswith("implying minors."))


class RagTests(unittest.TestCase):
    def test_entradas_tienen_forma_valida(self):
        self.assertGreaterEqual(len(RAG_ENTRIES), 8)
        self.assertLessEqual(len(RAG_ENTRIES), 12)
        for entry in RAG_ENTRIES:
            with self.subTest(entry=entry["text"][:40]):
                self.assertIsInstance(entry["keywords"], list)
                self.assertTrue(entry["keywords"])
                self.assertTrue(all(isinstance(kw, str) and kw for kw in entry["keywords"]))
                self.assertIsInstance(entry["text"], str)
                self.assertTrue(entry["text"].strip())

    def test_query_vacia_o_sin_tokens_devuelve_vacio(self):
        self.assertEqual(retrieve(""), [])
        self.assertEqual(retrieve("   ... !!! "), [])

    def test_query_sin_match_devuelve_vacio(self):
        self.assertEqual(retrieve("xyzzy plugh quux"), [])

    def test_match_por_keywords_y_orden_estable(self):
        result = retrieve("score_9", k=3)
        self.assertTrue(result)
        self.assertIn("score_7, score_8, score_9", result[0])
        self.assertEqual(retrieve("score_9", k=1), result[:1])
        self.assertEqual(retrieve("score_9", k=10)[: len(result)], result)

    def test_k_no_positivo_devuelve_vacio(self):
        self.assertEqual(retrieve("score_9", k=0), [])
        self.assertEqual(retrieve("score_9", k=-1), [])

    def test_uncensored_prioriza_anti_censura(self):
        result = retrieve("uncensored", k=1)
        self.assertEqual(len(result), 1)
        self.assertIn("uncensored", result[0])


class BaseNegativeTests(unittest.TestCase):
    def test_golden_base_negative_texto_exacto(self):
        self.assertEqual(BASE_NEGATIVE, GOLDEN_BASE_NEGATIVE)

    def test_base_sin_duplicados_ci(self):
        tags = [tag.strip().lower() for tag in BASE_NEGATIVE.split(",")]
        self.assertEqual(len(tags), len(set(tags)))

    def test_base_incluye_anti_menores_y_anti_censura(self):
        for term in (
            "child",
            "teen",
            "loli",
            "young-looking",
            "mosaic censoring",
            "bar censor",
        ):
            with self.subTest(term=term):
                self.assertIn(term, BASE_NEGATIVE)


class NegativeCompositionTests(unittest.TestCase):
    def expected(self, name: str) -> str:
        extra = PREPROMPT_NEGATIVE_EXTRAS[name]
        return f"{GOLDEN_BASE_NEGATIVE}, {extra}" if extra else GOLDEN_BASE_NEGATIVE

    def test_los_4_preprompts_componen_base_mas_extra(self):
        for name in PREPROMPT_NEGATIVE_EXTRAS:
            with self.subTest(preprompt=name):
                _positive, negative = apply_preprompt("1girl", name=name)
                self.assertEqual(negative, self.expected(name))

    def test_composicion_sin_duplicados_ci_y_orden_estable(self):
        for name in PREPROMPT_NEGATIVE_EXTRAS:
            with self.subTest(preprompt=name):
                _positive, negative = apply_preprompt("1girl", name=name)
                tags = [tag.strip().lower() for tag in negative.split(",")]
                self.assertEqual(len(tags), len(set(tags)))
                self.assertTrue(
                    negative == GOLDEN_BASE_NEGATIVE
                    or negative.startswith(GOLDEN_BASE_NEGATIVE + ", ")
                )
                self.assertEqual(
                    negative, apply_preprompt("1girl", name=name)[1]
                )


class ApplyPrepromptTests(unittest.TestCase):
    def test_glossy_prefijo_y_sufijo(self):
        positive, negative = apply_preprompt("1girl, smile")
        self.assertEqual(positive, f"{GLOSSY_POSITIVE}, 1girl, smile")
        self.assertEqual(
            negative, f"{GOLDEN_BASE_NEGATIVE}, {PREPROMPT_NEGATIVE_EXTRAS['glossy']}"
        )

    def test_dedup_case_insensitive_conserva_primera_aparicion(self):
        positive, _negative = apply_preprompt("Masterpiece, SCORE_9, 1girl, smile")
        self.assertEqual(positive, f"{GLOSSY_POSITIVE}, 1girl, smile")

    def test_ninguno_no_anade_prefijo_ni_sufijo(self):
        self.assertEqual(
            apply_preprompt("1girl", name="ninguno"), ("1girl", GOLDEN_BASE_NEGATIVE)
        )

    def test_anima_default_y_not_glossy(self):
        positive, negative = apply_preprompt("1girl", name="anima_default")
        self.assertEqual(positive, "masterpiece, best quality, score_8, 1girl")
        self.assertEqual(
            negative,
            f"{GOLDEN_BASE_NEGATIVE}, score_1, score_2, score_3, artist name",
        )
        positive, negative = apply_preprompt("1girl", name="not_glossy")
        self.assertEqual(positive, "newest, good quality, score_6, score_5, highres, 1girl")
        self.assertEqual(negative, f"{GOLDEN_BASE_NEGATIVE}, score_1, score_2")

    def test_determinista(self):
        self.assertEqual(apply_preprompt("1girl, smile"), apply_preprompt("1girl, smile"))

    def test_familia_o_nombre_desconocido_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            apply_preprompt("1girl", family="no-existe")
        with self.assertRaises(EngineError):
            apply_preprompt("1girl", name="no-existe")


class EnhanceTests(unittest.TestCase):
    USER_TEXT = "1girl, smile, score_9"

    def test_mensajes_y_resultado(self):
        llm = FakeLLM("1girl, smile, masterpiece")
        result = enhance(self.USER_TEXT, rating="nsfw", llm=llm, k=3)
        self.assertEqual(len(llm.calls), 1)
        system, user = llm.calls[0]
        self.assertEqual(system, SYS_PROMPT)
        self.assertTrue(user.startswith(self.USER_TEXT))
        self.assertIn("rating tag: nsfw", user)
        self.assertIn("Notas de referencia (no copiar a la salida):", user)
        for note in retrieve(self.USER_TEXT, k=3):
            self.assertIn(note, user)
        expected_raw = "1girl, smile, masterpiece, nsfw, uncensored"
        expected_positive, expected_negative = apply_preprompt(expected_raw)
        self.assertEqual(result["positive"], canonical_order(expected_positive))
        self.assertEqual(result["negative"], expected_negative)
        self.assertEqual(result["raw"], expected_raw)

    def test_sin_rating_no_hay_linea_de_contexto(self):
        llm = FakeLLM()
        enhance(self.USER_TEXT, llm=llm)
        _system, user = llm.calls[0]
        self.assertNotIn("rating tag:", user)

    def test_k_cero_sin_notas(self):
        llm = FakeLLM()
        enhance(self.USER_TEXT, llm=llm, k=0)
        _system, user = llm.calls[0]
        self.assertNotIn("Notas de referencia", user)

    def test_preprompt_inyectado_se_aplica(self):
        llm = FakeLLM("1girl, smile")
        result = enhance("1girl", preprompt="ninguno", llm=llm)
        self.assertEqual(result["positive"], "1girl, smile")
        self.assertEqual(result["negative"], GOLDEN_BASE_NEGATIVE)

    def test_negative_de_enhance_es_el_compuesto(self):
        llm = FakeLLM("1girl, smile")
        result = enhance("1girl", preprompt="glossy", llm=llm, k=0)
        self.assertEqual(
            result["negative"],
            f"{GOLDEN_BASE_NEGATIVE}, {PREPROMPT_NEGATIVE_EXTRAS['glossy']}",
        )
        tags = [tag.strip().lower() for tag in result["negative"].split(",")]
        self.assertEqual(len(tags), len(set(tags)))
        self.assertIn("mosaic censoring", tags)

    def test_texto_se_normaliza_sin_espacios_exteriores(self):
        llm = FakeLLM()
        enhance("  1girl, smile  ", llm=llm)
        _system, user = llm.calls[0]
        self.assertTrue(user.startswith("1girl, smile"))

    def test_texto_vacio_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            enhance("", llm=FakeLLM())
        with self.assertRaises(EngineError):
            enhance("   ", llm=FakeLLM())

    def test_sin_llm_lanza_engine_error(self):
        with self.assertRaises(EngineError) as ctx:
            enhance(self.USER_TEXT)
        self.assertEqual(str(ctx.exception), "LLM no inyectado")

    def test_llm_no_texto_lanza_engine_error(self):
        with self.assertRaises(EngineError):
            enhance(self.USER_TEXT, llm=lambda _s, _u: None)

    def test_linea_de_contexto_rating_sfw(self):
        llm = FakeLLM()
        enhance(self.USER_TEXT, rating="sfw", llm=llm)
        _system, user = llm.calls[0]
        self.assertIn("rating tag: sfw", user)
        self.assertNotIn("uncensored", user)


class ZoneHintTests(unittest.TestCase):
    """`zone_hint` añade una línea interna y no toca la salida (M9-C3a)."""

    LINE = (
        "Zona objetivo: quality. Coloca sólo etiquetas de esa zona; "
        "si algo no pertenece, omítelo."
    )

    def test_zone_hint_aparece_en_el_mensaje_de_usuario(self):
        llm = FakeLLM()
        enhance("1girl, smile", llm=llm, k=0, zone_hint="quality")
        system, user = llm.calls[0]
        self.assertEqual(system, SYS_PROMPT)
        self.assertIn(self.LINE, user)

    def test_sin_zone_hint_no_aparece_la_linea(self):
        llm = FakeLLM()
        enhance("1girl, smile", llm=llm, k=0)
        self.assertNotIn("Zona objetivo:", llm.calls[0][1])

    def test_zone_hint_vacio_o_en_blanco_no_aparece(self):
        for hint in ("", "   "):
            with self.subTest(hint=hint):
                llm = FakeLLM()
                enhance("1girl, smile", llm=llm, k=0, zone_hint=hint)
                self.assertNotIn("Zona objetivo:", llm.calls[0][1])

    def test_zone_hint_convive_con_rating_e_instruccion(self):
        llm = CapturingLLM()
        enhance(
            "1girl",
            rating="sfw",
            strength="fiel",
            llm=llm,
            k=0,
            zone_hint="safety",
        )
        user = llm.calls[0]["user"]
        self.assertIn("rating tag: sfw", user)
        self.assertIn("instruccion:", user)
        self.assertIn("Zona objetivo: safety.", user)

    def test_zone_hint_no_altera_la_salida(self):
        base = enhance("1girl, smile", llm=FakeLLM("1girl, smile"), k=0)
        hinted = enhance(
            "1girl, smile", llm=FakeLLM("1girl, smile"), k=0, zone_hint="general"
        )
        self.assertEqual(base, hinted)

    def test_hint_vacio_salida_identica_al_comportamiento_previo(self):
        base = enhance("1girl, smile", llm=FakeLLM("1girl, smile"), k=0)
        for hint in (None, "", "  "):
            with self.subTest(hint=hint):
                result = enhance(
                    "1girl, smile", llm=FakeLLM("1girl, smile"), k=0, zone_hint=hint
                )
                self.assertEqual(result, base)


class RatingEnforcementTests(unittest.TestCase):
    def test_nsfw_garantiza_nsfw_y_uncensored_y_elimina_sfw(self):
        llm = FakeLLM("1girl, sfw, smile, uncensored")
        result = enhance("1girl", rating="nsfw", llm=llm, k=0)
        self.assertEqual(result["raw"], "1girl, smile, uncensored, nsfw")
        raw_tags = [tag.strip().lower() for tag in result["raw"].split(",")]
        self.assertNotIn("sfw", raw_tags)

    def test_nsfw_no_duplica_ni_pisa_la_capitalizacion(self):
        llm = FakeLLM("1girl, NSFW, Uncensored, smile")
        result = enhance("1girl", rating="nsfw", llm=llm, k=0)
        self.assertEqual(result["raw"], "1girl, NSFW, Uncensored, smile")

    def test_nsfw_deduplica_tags_repetidos_del_llm(self):
        llm = FakeLLM("1girl, smile, smile, uncensored, uncensored")
        result = enhance("1girl", rating="nsfw", llm=llm, k=0)
        self.assertEqual(result["raw"], "1girl, smile, uncensored, nsfw")

    def test_sfw_garantiza_sfw_y_elimina_nsfw_y_uncensored(self):
        llm = FakeLLM("1girl, nsfw, uncensored, smile")
        result = enhance("1girl", rating="sfw", llm=llm, k=0)
        self.assertEqual(result["raw"], "1girl, smile, sfw")

    def test_rating_none_no_toca_el_rating(self):
        llm = FakeLLM("1girl, nsfw, uncensored, smile")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(result["raw"], "1girl, nsfw, uncensored, smile")

    def test_sfw_elimina_rating_con_peso(self):
        llm = FakeLLM("(nsfw:1.1), smile")
        result = enhance("1girl", rating="sfw", llm=llm, k=0)
        self.assertEqual(result["raw"], "smile, sfw")
        raw_tags = [tag.strip().lower() for tag in result["raw"].split(",")]
        self.assertNotIn("nsfw", raw_tags)
        self.assertNotIn("(nsfw:1.1)", raw_tags)

    def test_nsfw_no_duplica_uncensored_con_peso(self):
        llm = FakeLLM("(uncensored:1.1), smile")
        result = enhance("1girl", rating="nsfw", llm=llm, k=0)
        self.assertEqual(result["raw"], "(uncensored:1.1), smile, nsfw")
        raw_tags = [tag.strip().lower() for tag in result["raw"].split(",")]
        self.assertNotIn("uncensored", raw_tags)

    def test_nsfw_elimina_sfw_con_peso(self):
        llm = FakeLLM("(sfw:0.9), smile")
        result = enhance("1girl", rating="nsfw", llm=llm, k=0)
        self.assertEqual(result["raw"], "smile, nsfw, uncensored")
        raw_tags = [tag.strip().lower() for tag in result["raw"].split(",")]
        self.assertNotIn("sfw", raw_tags)
        self.assertNotIn("(sfw:0.9)", raw_tags)


class TagNormalizationTests(unittest.TestCase):
    def test_underscore_a_espacio_salvo_score(self):
        llm = FakeLLM("school_uniform, completely_nude, score_9, score_7, smile")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(
            result["raw"],
            "school uniform, completely nude, score_9, score_7, smile",
        )
        self.assertEqual(result["dropped"], [])

    def test_normalizacion_antes_del_preprompt(self):
        llm = FakeLLM("school_uniform, score_9")
        result = enhance("1girl", preprompt="ninguno", llm=llm, k=0)
        self.assertEqual(result["positive"], "score_9, school uniform")

    def test_score_en_mayusculas_queda_intacto(self):
        llm = FakeLLM("SCORE_9, score_12")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(result["raw"], "SCORE_9")
        self.assertEqual(result["dropped"], ["score_12"])

    def test_sin_cambios_no_muta_el_texto(self):
        raw = "1girl, smile, masterpiece"
        result = enhance("1girl", llm=FakeLLM(raw), k=0)
        self.assertEqual(result["raw"], raw)
        self.assertEqual(result["dropped"], [])
        self.assertEqual(result["positive"], apply_preprompt(raw)[0])


class TagValidationTests(unittest.TestCase):
    """Validacion estricta contra el catalogo y reporte de descartes (M11-1c)."""

    def test_alias_se_sustituye_por_el_canonico(self):
        llm = FakeLLM("longhair, smile")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(result["raw"], "long hair, smile")
        self.assertEqual(result["dropped"], [])

    def test_inventado_se_descarta_y_se_reporta_en_dropped(self):
        llm = FakeLLM("1girl, glittery sparkle, smile")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(result["raw"], "1girl, smile")
        self.assertEqual(result["dropped"], ["glittery sparkle"])
        self.assertNotIn("glittery sparkle", result["raw"])

    def test_tag_solo_del_catalogo_se_conserva(self):
        llm = FakeLLM("absurdly long hair")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(result["raw"], "absurdly long hair")
        self.assertEqual(result["dropped"], [])

    def test_dedup_tras_alias(self):
        llm = FakeLLM("longhair, long hair, smile")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(result["raw"], "long hair, smile")
        self.assertEqual(result["dropped"], [])

    def test_peso_con_nucleo_valido_se_conserva(self):
        llm = FakeLLM("(long hair:1.2), smile")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(result["raw"], "(long hair:1.2), smile")
        self.assertEqual(result["dropped"], [])

    def test_peso_con_nucleo_inventado_se_descarta(self):
        llm = FakeLLM("(inventado:1.1), smile")
        result = enhance("1girl", llm=llm, k=0)
        self.assertEqual(result["raw"], "smile")
        self.assertEqual(result["dropped"], ["(inventado:1.1)"])


class VocabularyTests(unittest.TestCase):
    """Vocabulario restringido de la zona en el mensaje de usuario (M11-1c)."""

    def _user(self, text, **kwargs):
        llm = FakeLLM("1girl, smile")
        enhance(text, llm=llm, k=0, **kwargs)
        return llm.calls[0][1]

    def test_query_con_matches_incluye_la_linea(self):
        user = self._user("long hair")
        self.assertIn("Vocabulario de etiquetas", user)
        line = next(
            item
            for item in user.splitlines()
            if item.startswith("Vocabulario de etiquetas")
        )
        self.assertIn("long hair", line)

    def test_zone_hint_quality_lista_las_opciones_curadas(self):
        user = self._user("1girl", zone_hint="quality")
        self.assertIn("Vocabulario de etiquetas", user)
        self.assertIn("masterpiece", user)
        self.assertIn("score_9", user)

    def test_sin_matches_no_aparece_la_linea(self):
        user = self._user("xyzzy plugh quux")
        self.assertNotIn("Vocabulario de etiquetas", user)

    def test_la_linea_no_lleva_prefijo_de_nota_rag(self):
        user = self._user("long hair")
        line = next(
            item
            for item in user.splitlines()
            if item.startswith("Vocabulario de etiquetas")
        )
        self.assertFalse(line.startswith("- "))
        self.assertNotIn("\n- Vocabulario", user)


class CanonicalPositiveTests(unittest.TestCase):
    """El positivo de `enhance` sale reordenado por `canonical_order` (M9-C2)."""

    def test_llm_desordenado_queda_canonico_sin_preprompt(self):
        llm = FakeLLM("blue sky, long hair, nsfw, 1girl, masterpiece, school uniform")
        result = enhance("dibujo", rating="nsfw", preprompt="ninguno", llm=llm, k=0)
        self.assertEqual(
            result["raw"],
            "blue sky, long hair, nsfw, 1girl, masterpiece, school uniform, "
            "uncensored",
        )
        self.assertEqual(
            result["positive"],
            "masterpiece, nsfw, uncensored, 1girl, long hair, school uniform, "
            "blue sky",
        )

    def test_calidad_primero_y_general_por_subcategorias_con_preprompt(self):
        llm = FakeLLM("blue sky, long hair, 1girl, smile")
        result = enhance("x", llm=llm, k=0)
        self.assertEqual(
            result["positive"],
            "masterpiece, best quality, absurdres, highres, score_7, score_8, "
            "score_9, 1girl, long hair, smile, blue sky",
        )

    def test_negativo_no_se_reordena(self):
        llm = FakeLLM("1girl, smile")
        result = enhance("x", llm=llm, k=0)
        self.assertEqual(
            result["negative"], apply_preprompt("1girl, smile", "anima", "glossy")[1]
        )

    def test_raw_conserva_el_orden_del_llm(self):
        llm = FakeLLM("blue sky, long hair, nsfw, 1girl, masterpiece")
        result = enhance("x", rating="nsfw", preprompt="ninguno", llm=llm, k=0)
        self.assertEqual(
            result["raw"],
            "blue sky, long hair, nsfw, 1girl, masterpiece, uncensored",
        )

    def test_canonical_order_ubica_other_tras_fondo(self):
        ordered = canonical_order("blue sky, tag_desconocido, 1girl, masterpiece")
        self.assertEqual(ordered, "masterpiece, 1girl, blue sky, tag_desconocido")



class StrengthPresetTests(unittest.TestCase):
    QUERY = "score_9, quality, safety, nsfw, artist, uncensored"

    def test_presets_golden(self):
        self.assertEqual(
            STRENGTH_PRESETS,
            {
                "fiel": {
                    "temperature": 0.4,
                    "k": 1,
                    "instruction": (
                        "Mantén exactamente lo pedido; no añadas elementos que el "
                        "usuario no haya pedido."
                    ),
                },
                "balanceado": {"temperature": 0.7, "k": 3, "instruction": ""},
                "creativo": {
                    "temperature": 1.0,
                    "k": 6,
                    "instruction": (
                        "Enriquece con detalles coherentes (pose, expresión, luz, "
                        "fondo) sin contradecir lo pedido."
                    ),
                },
            },
        )
        self.assertEqual(DEFAULT_STRENGTH_PRESET, "balanceado")

    def test_balanceado_default_sin_instruccion_y_temperature_0_7(self):
        llm = CapturingLLM()
        result = enhance("1girl", llm=llm)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(llm.calls[0]["temperature"], 0.7)
        self.assertNotIn("instruccion:", llm.calls[0]["user"])
        self.assertEqual(result["positive"], apply_preprompt("1girl, smile")[0])

    def test_fiel_usa_k_1_e_instruccion_y_temperature_0_4(self):
        llm = CapturingLLM()
        enhance(self.QUERY, strength="fiel", llm=llm)
        user = llm.calls[0]["user"]
        self.assertEqual(llm.calls[0]["temperature"], 0.4)
        self.assertIn("instruccion:", user)
        self.assertIn(STRENGTH_PRESETS["fiel"]["instruction"], user)
        self.assertEqual(user.count("\n- "), 1)

    def test_creativo_usa_k_6_e_instruccion_y_temperature_1_0(self):
        self.assertEqual(len(retrieve(self.QUERY, k=6)), 6)
        llm = CapturingLLM()
        enhance(self.QUERY, strength="creativo", llm=llm)
        user = llm.calls[0]["user"]
        self.assertEqual(llm.calls[0]["temperature"], 1.0)
        self.assertIn("instruccion:", user)
        self.assertIn(STRENGTH_PRESETS["creativo"]["instruction"], user)
        self.assertEqual(user.count("\n- "), 6)

    def test_balanceado_usa_k_3(self):
        llm = CapturingLLM()
        enhance(self.QUERY, strength="balanceado", llm=llm)
        self.assertEqual(llm.calls[0]["user"].count("\n- "), 3)

    def test_k_explicito_manda_sobre_el_preset(self):
        llm = CapturingLLM()
        enhance(self.QUERY, strength="creativo", k=0, llm=llm)
        self.assertNotIn("Notas de referencia", llm.calls[0]["user"])

    def test_strength_desconocido_lanza_engine_error_sin_llamar(self):
        for strength in ("loco", "", None, 5, ["fiel"]):
            with self.subTest(strength=strength):
                llm = CapturingLLM()
                with self.assertRaises(EngineError):
                    enhance("1girl", strength=strength, llm=llm)
                self.assertEqual(llm.calls, [])

    def test_llm_sin_kwarg_temperature_reintenta_sin_el(self):
        llm = FakeLLM()
        enhance("1girl", strength="fiel", llm=llm)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("instruccion:", llm.calls[0][1])


class LoadLocalLlmTests(unittest.TestCase):
    def test_archivo_ausente_lanza_engine_error_sin_importar_llama(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no-existe.gguf"
            with self.assertRaises(EngineError) as ctx:
                load_local_llm(missing)
            self.assertIn(str(missing), str(ctx.exception))


class LlmWrapperTests(unittest.TestCase):
    def _llm(self, response):
        module, fake = _fake_llama_module(response)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        model = Path(tmp.name) / "fake.gguf"
        model.write_bytes(b"")
        patcher = mock.patch.dict(sys.modules, {"llama_cpp": module})
        patcher.start()
        self.addCleanup(patcher.stop)
        llm = load_local_llm(model, max_tokens=64, temperature=0.2)
        return llm, fake.instances[0]

    def test_chat_completion_valido_devuelve_el_contenido(self):
        llm, _llama = self._llm({"choices": [{"message": {"content": "1girl, smile"}}]})
        self.assertEqual(llm("SYS", "USER"), "1girl, smile")

    def test_mensajes_y_parametros_del_chat(self):
        llm, llama = self._llm({"choices": [{"message": {"content": "ok"}}]})
        llm("SYS", "USER")
        call = llama.chat_calls[0]
        self.assertEqual(
            call["messages"],
            [
                {"role": "system", "content": "SYS"},
                {"role": "user", "content": "USER"},
            ],
        )
        self.assertEqual(call["max_tokens"], 64)
        self.assertEqual(call["temperature"], 0.2)
        self.assertEqual(llama.init_kwargs["n_gpu_layers"], 0)
        self.assertEqual(llama.init_kwargs["n_ctx"], 2048)

    def test_temperature_por_llamada_override_del_default(self):
        llm, llama = self._llm({"choices": [{"message": {"content": "ok"}}]})
        llm("SYS", "USER")
        llm("SYS", "USER", temperature=1.0)
        self.assertEqual(llama.chat_calls[0]["temperature"], 0.2)
        self.assertEqual(llama.chat_calls[1]["temperature"], 1.0)

    def test_respuesta_no_dict_o_sin_choices_lanza_engine_error(self):
        for response in ("texto", {"choices": []}, {}):
            with self.subTest(response=response):
                llm, _llama = self._llm(response)
                with self.assertRaises(EngineError) as ctx:
                    llm("SYS", "USER")
                self.assertEqual(str(ctx.exception), "LLM sin contenido")

    def test_contenido_no_texto_o_vacio_lanza_engine_error(self):
        for content in (None, {"x": 1}, "", "   "):
            with self.subTest(content=content):
                llm, _llama = self._llm({"choices": [{"message": {"content": content}}]})
                with self.assertRaises(EngineError) as ctx:
                    llm("SYS", "USER")
                self.assertEqual(str(ctx.exception), "LLM sin contenido")


class RecordingTransport:
    """Transporte falso: registra `(url, payload, timeout)` y devuelve o levanta."""

    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict | None, float]] = []
        self.response = {} if response is None else response
        self.error = error

    def __call__(self, url, payload, timeout):
        self.calls.append((url, payload, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, *args) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class ServerLlmTests(unittest.TestCase):
    """Adaptador HTTP OpenAI-compatible del `llama-server` (M11-2F)."""

    RESPONSE = {"choices": [{"message": {"content": "1girl, smile"}}]}

    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(LLM_TIMEOUT_ENV, None)

    def test_endpoint_y_payload_exactos(self):
        transport = RecordingTransport(self.RESPONSE)
        llm = load_server_llm("http://127.0.0.1:8290/", transport=transport)
        self.assertEqual(llm("SYS", "USER"), "1girl, smile")
        self.assertEqual(len(transport.calls), 1)
        url, payload, timeout = transport.calls[0]
        self.assertEqual(url, "http://127.0.0.1:8290/v1/chat/completions")
        self.assertEqual(timeout, 120.0)
        self.assertEqual(
            payload,
            {
                "model": "qwen35-9b-abliterated",
                "messages": [
                    {"role": "system", "content": "SYS"},
                    {"role": "user", "content": "USER"},
                ],
                "max_tokens": 192,
                "temperature": 0.7,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )

    def test_parametros_configurables(self):
        transport = RecordingTransport(self.RESPONSE)
        llm = load_server_llm(
            "http://x",
            transport=transport,
            max_tokens=64,
            temperature=0.2,
            timeout=5.0,
            model="otro-modelo",
        )
        llm("S", "U")
        url, payload, timeout = transport.calls[0]
        self.assertEqual(url, "http://x/v1/chat/completions")
        self.assertEqual(timeout, 5.0)
        self.assertEqual(payload["max_tokens"], 64)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["model"], "otro-modelo")

    def test_timeout_por_env_cuando_el_parametro_no_se_pasa(self):
        with mock.patch.dict(os.environ, {LLM_TIMEOUT_ENV: "5"}):
            transport = RecordingTransport(self.RESPONSE)
            load_server_llm("http://x", transport=transport)("S", "U")
        self.assertEqual(transport.calls[0][2], 5.0)

    def test_timeout_explicito_manda_sobre_env(self):
        with mock.patch.dict(os.environ, {LLM_TIMEOUT_ENV: "5"}):
            transport = RecordingTransport(self.RESPONSE)
            load_server_llm("http://x", transport=transport, timeout=9.0)("S", "U")
        self.assertEqual(transport.calls[0][2], 9.0)

    def test_timeout_env_ausente_vacio_o_invalido_cae_al_default(self):
        for value in (None, "", "  ", "abc"):
            with self.subTest(value=value):
                if value is None:
                    transport = RecordingTransport(self.RESPONSE)
                    load_server_llm("http://x", transport=transport)("S", "U")
                else:
                    with mock.patch.dict(os.environ, {LLM_TIMEOUT_ENV: value}):
                        transport = RecordingTransport(self.RESPONSE)
                        load_server_llm("http://x", transport=transport)("S", "U")
                self.assertEqual(transport.calls[0][2], DEFAULT_LLM_TIMEOUT)

    def test_temperature_por_llamada_manda_sobre_el_default(self):
        transport = RecordingTransport(self.RESPONSE)
        llm = load_server_llm("http://x", transport=transport)
        llm("S", "U")
        llm("S", "U", temperature=1.0)
        self.assertEqual(transport.calls[0][1]["temperature"], 0.7)
        self.assertEqual(transport.calls[1][1]["temperature"], 1.0)

    def test_base_url_por_parametro_manda_sobre_env(self):
        with mock.patch.dict(os.environ, {LLM_URL_ENV: "http://env:1111"}):
            transport = RecordingTransport(self.RESPONSE)
            load_server_llm("http://param:2222/", transport=transport)("S", "U")
        self.assertEqual(
            transport.calls[0][0], "http://param:2222/v1/chat/completions"
        )

    def test_env_y_default_de_base(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(LLM_URL_ENV, None)
            transport = RecordingTransport(self.RESPONSE)
            load_server_llm(transport=transport)("S", "U")
            self.assertEqual(
                transport.calls[0][0], f"{DEFAULT_LLM_URL}/v1/chat/completions"
            )
        with mock.patch.dict(os.environ, {LLM_URL_ENV: "http://env:1111"}):
            transport = RecordingTransport(self.RESPONSE)
            load_server_llm(transport=transport)("S", "U")
            self.assertEqual(
                transport.calls[0][0], "http://env:1111/v1/chat/completions"
            )

    def test_respuesta_sin_contenido_texto_lanza_engine_error(self):
        for response in (
            {},
            {"choices": []},
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": ""}}]},
            {"choices": [{"message": {"content": "   "}}]},
            "texto",
        ):
            with self.subTest(response=response):
                transport = RecordingTransport(response)
                llm = load_server_llm("http://x", transport=transport)
                with self.assertRaises(EngineError) as ctx:
                    llm("S", "U")
                self.assertEqual(str(ctx.exception), "LLM sin contenido")

    def test_error_del_transporte_se_propaga(self):
        transport = RecordingTransport(error=EngineError("servidor caido"))
        llm = load_server_llm("http://x", transport=transport)
        with self.assertRaises(EngineError) as ctx:
            llm("S", "U")
        self.assertEqual(str(ctx.exception), "servidor caido")


class HttpTransportTests(unittest.TestCase):
    """Transporte por defecto: sin red real (urlopen parcheado)."""

    def test_post_json_con_cabeceras_y_timeout(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(b'{"ok": true}')

        with mock.patch("app.enhancer.urllib.request.urlopen", fake_urlopen):
            result = _http_transport("http://x/v1/chat/completions", {"a": 1}, 3.5)
        self.assertEqual(result, {"ok": True})
        request = captured["request"]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.get_header("Content-type"), "application/json; charset=utf-8"
        )
        self.assertTrue(request.get_header("User-agent"))
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"a": 1})
        self.assertEqual(captured["timeout"], 3.5)

    def test_get_sin_payload_y_2xx_sin_json_devuelve_vacio(self):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["method"] = request.get_method()
            seen["data"] = request.data
            return FakeResponse(b"")

        with mock.patch("app.enhancer.urllib.request.urlopen", fake_urlopen):
            self.assertEqual(_http_transport("http://x/health", None, 2.0), {})
        self.assertEqual(seen["method"], "GET")
        self.assertIsNone(seen["data"])

        def fake_urlopen_no_json(request, timeout=None):
            return FakeResponse(b"no-json")

        with mock.patch("app.enhancer.urllib.request.urlopen", fake_urlopen_no_json):
            self.assertEqual(_http_transport("http://x/health", None, 2.0), {})

    def test_url_invalida_se_envuelve_en_engine_error(self):
        with self.assertRaises(EngineError) as ctx:
            _http_transport("no-es-url", None, 0.1)
        self.assertIn("no-es-url", str(ctx.exception))

    def test_http_error_se_envuelve_corto(self):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError("http://x", 500, "boom", None, None)

        with mock.patch("app.enhancer.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(EngineError) as ctx:
                _http_transport("http://x", None, 1.0)
        self.assertEqual(str(ctx.exception), "HTTP 500: boom")

    def test_http_503_lleva_codigo_y_reason(self):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                "http://x", 503, "Service Unavailable", None, None
            )

        with mock.patch("app.enhancer.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(EngineError) as ctx:
                _http_transport("http://x/v1/chat/completions", {"a": 1}, 1.0)
        self.assertEqual(str(ctx.exception), "HTTP 503: Service Unavailable")


class ServerLlmStatusTests(unittest.TestCase):
    def test_ok_cuando_el_transporte_no_lanza(self):
        transport = RecordingTransport({})
        ok, reason = server_llm_status("http://127.0.0.1:8290/", transport=transport)
        self.assertTrue(ok)
        self.assertEqual(reason, "OK")
        url, payload, timeout = transport.calls[0]
        self.assertEqual(url, "http://127.0.0.1:8290/health")
        self.assertIsNone(payload)
        self.assertEqual(timeout, 2.0)

    def test_ko_cuando_el_transporte_lanza(self):
        for error in (EngineError("red: refused"), RuntimeError("boom")):
            with self.subTest(error=type(error).__name__):
                transport = RecordingTransport(error=error)
                ok, reason = server_llm_status(
                    "http://127.0.0.1:8290", transport=transport
                )
                self.assertFalse(ok)
                self.assertIn(str(error), reason)
                self.assertEqual(len(transport.calls), 1)

    def test_url_invalida_sin_red(self):
        transport = RecordingTransport({})
        for base in ("no-es-url", "localhost:8290", "http://", "   ", "", "http://[::1"):
            with self.subTest(base=base):
                ok, reason = server_llm_status(base, transport=transport)
                self.assertFalse(ok)
                self.assertEqual(reason, "URL invalida")
        self.assertEqual(transport.calls, [])


class ServerLlmStateTests(unittest.TestCase):
    """`server_llm_state` (M11-3G): ready/loading/offline/unknown sin red."""

    def test_ready_cuando_el_transporte_no_lanza(self):
        transport = RecordingTransport({})
        state, detail = server_llm_state("http://127.0.0.1:8290/", transport=transport)
        self.assertEqual((state, detail), ("ready", "OK"))
        url, payload, timeout = transport.calls[0]
        self.assertEqual(url, "http://127.0.0.1:8290/health")
        self.assertIsNone(payload)
        self.assertEqual(timeout, 2.0)

    def test_loading_con_http_503(self):
        transport = RecordingTransport(error=EngineError("HTTP 503: loading model"))
        state, detail = server_llm_state(
            "http://127.0.0.1:8290", transport=transport
        )
        self.assertEqual((state, detail), ("loading", "HTTP 503: loading model"))

    def test_offline_con_otro_error(self):
        for error in (EngineError("red: refused"), RuntimeError("boom")):
            with self.subTest(error=type(error).__name__):
                transport = RecordingTransport(error=error)
                state, detail = server_llm_state(
                    "http://127.0.0.1:8290", transport=transport
                )
                self.assertEqual(state, "offline")
                self.assertIn(str(error), detail)

    def test_http_503_solo_en_el_prefijo(self):
        transport = RecordingTransport(error=EngineError("error HTTP 503 interno"))
        state, _detail = server_llm_state("http://x", transport=transport)
        self.assertEqual(state, "offline")

    def test_url_invalida_sin_red(self):
        transport = RecordingTransport({})
        for base in ("no-es-url", "localhost:8290", "http://", "   ", ""):
            with self.subTest(base=base):
                state, detail = server_llm_state(base, transport=transport)
                self.assertEqual((state, detail), ("unknown", "URL invalida"))
        self.assertEqual(transport.calls, [])

    def test_status_sigue_siendo_booleano_sobre_el_estado(self):
        transport = RecordingTransport({})
        self.assertEqual(
            server_llm_status("http://x", transport=transport), (True, "OK")
        )
        transport = RecordingTransport(error=EngineError("HTTP 503: loading"))
        self.assertEqual(
            server_llm_status("http://x", transport=transport),
            (False, "HTTP 503: loading"),
        )


if __name__ == "__main__":
    unittest.main()
