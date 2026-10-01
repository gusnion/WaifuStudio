"""Tests CPU de vision local (M10-4b). Sin onnxruntime, llama.cpp, red ni GPU."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from app.engine import EngineError
from app.enhancer import DEFAULT_LLM_URL, LLM_TIMEOUT_ENV, LLM_URL_ENV
from app.vision import (
    DESCRIBE_SYSTEM_PROMPT,
    DESCRIBE_USER_PROMPT,
    VL_MMPROJ_FILE,
    VL_MODEL_FILE,
    VL_SYSTEM_PROMPT,
    VL_USER_PROMPT,
    VisionService,
    VisionUnavailable,
    WD14_MODEL,
    _default_tagger,
    _load_rows,
    _parse_describe,
    _postprocess,
    load_server_captioner,
    load_server_describer,
)


class PostprocessTests(unittest.TestCase):
    ROWS = [
        ("long hair", "0"),
        ("1girl", "0"),
        ("hatsune miku", "4"),
        ("rating explicit", "9"),
        ("solo", "0"),
    ]

    def test_umbrales_por_categoria_y_orden(self):
        probs = [0.90, 0.40, 0.90, 0.99, 0.20]
        self.assertEqual(
            _postprocess(self.ROWS, probs),
            ["hatsune miku", "long hair", "1girl"],
        )

    def test_personajes_exigen_umbral_alto(self):
        self.assertEqual(_postprocess(self.ROWS, [0.0, 0.0, 0.5, 0.0, 0.0]), [])

    def test_ratings_se_ignoran(self):
        self.assertEqual(_postprocess(self.ROWS, [0.0, 0.0, 0.0, 0.99, 0.0]), [])


class LoadRowsTests(unittest.TestCase):
    def test_parsea_y_normaliza(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.csv"
            path.write_text(
                "tag_id,name,category,count\n"
                "0,long_hair,0,10\n"
                "1,hatsune_miku,4,5\n"
                "2,x\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _load_rows(path),
                [("long hair", "0"), ("hatsune miku", "4")],
            )


class DefaultTaggerTests(unittest.TestCase):
    def test_umbrales_llegan_a_postprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            onnx_path = root / "m.onnx"
            onnx_path.write_bytes(b"onnx")
            csv_path = root / "m.csv"
            csv_path.write_text(
                "tag_id,name,category,count\n0,long_hair,0,10\n", encoding="utf-8"
            )
            input_meta = types.SimpleNamespace(name="pixels", shape=[1, 448, 448, 3])
            session = mock.Mock()
            session.get_inputs.return_value = [input_meta]
            session.get_outputs.return_value = [
                types.SimpleNamespace(name="probs")
            ]
            session.run.return_value = [[0.9]]
            fake_ort = mock.Mock()
            fake_ort.InferenceSession.return_value = session
            captured: dict = {}

            def fake_postprocess(rows, probs, *, threshold, character_threshold):
                captured["rows"] = rows
                captured["probs"] = probs
                captured["threshold"] = threshold
                captured["character_threshold"] = character_threshold
                return ["tag"]

            with mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}), mock.patch(
                "app.vision._preprocess", return_value="tensor"
            ), mock.patch("app.vision._postprocess", side_effect=fake_postprocess):
                tagger = _default_tagger(
                    onnx_path, csv_path, threshold=0.6, character_threshold=0.7
                )
                self.assertEqual(tagger(b"img"), ["tag"])
            self.assertEqual(captured["threshold"], 0.6)
            self.assertEqual(captured["character_threshold"], 0.7)
            self.assertEqual(captured["rows"], [("long hair", "0")])
            self.assertEqual(captured["probs"], 0.9)
            session.run.assert_called_once_with(["probs"], {"pixels": "tensor"})


def _write_assets(root: Path) -> Path:
    wd14 = root / "models" / "wd14"
    wd14.mkdir(parents=True, exist_ok=True)
    (wd14 / f"{WD14_MODEL}.onnx").write_bytes(b"onnx")
    (wd14 / f"{WD14_MODEL}.csv").write_bytes(b"tag_id,name,category,count\n")
    llm = root / "models" / "llm" / "qwen25vl-7b-abliterated-gguf"
    llm.mkdir(parents=True, exist_ok=True)
    (llm / VL_MODEL_FILE).write_bytes(b"gguf")
    (llm / VL_MMPROJ_FILE).write_bytes(b"mmproj")
    return root


class VisionServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._clear_llm_env()

    def _clear_llm_env(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(LLM_URL_ENV, None)

    def test_status_sin_assets(self):
        status = VisionService(self.root).status()
        self.assertFalse(status["installed"])
        self.assertFalse(status["wd14"]["installed"])
        self.assertFalse(status["vl"]["installed"])
        self.assertEqual(status["wd14"]["model"], WD14_MODEL)
        self.assertIn("note", status)

    def test_status_con_assets(self):
        _write_assets(self.root)
        status = VisionService(self.root).status()
        self.assertTrue(status["installed"])
        self.assertTrue(status["wd14"]["installed"])
        self.assertTrue(status["vl"]["installed"])

    def test_tags_usa_factoria_y_cachea(self):
        _write_assets(self.root)
        calls: list[tuple[str, str]] = []

        def factory(onnx_path: Path, csv_path: Path):
            calls.append((onnx_path.name, csv_path.name))
            return lambda raw: ["a", "b"]

        service = VisionService(self.root, tagger_factory=factory)
        self.assertEqual(service.tags(b"img"), ["a", "b"])
        self.assertEqual(service.tags(b"img"), ["a", "b"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (f"{WD14_MODEL}.onnx", f"{WD14_MODEL}.csv"))

    def test_tags_sin_wd14_lanza_vision_unavailable(self):
        with self.assertRaises(VisionUnavailable):
            VisionService(self.root).tags(b"img")

    def test_tagger_for_sin_umbrales_devuelve_tags_con_cache(self):
        _write_assets(self.root)
        calls: list[tuple[str, str]] = []

        def factory(onnx_path: Path, csv_path: Path):
            calls.append((onnx_path.name, csv_path.name))
            return lambda raw: ["a", "b"]

        service = VisionService(self.root, tagger_factory=factory)
        tagger = service.tagger_for()
        self.assertIs(tagger.__self__, service)
        self.assertIs(tagger.__func__, VisionService.tags)
        self.assertEqual(tagger(b"img"), ["a", "b"])
        self.assertEqual(service.tags(b"img"), ["a", "b"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (f"{WD14_MODEL}.onnx", f"{WD14_MODEL}.csv"))

    def test_tagger_for_sin_wd14_lanza_vision_unavailable(self):
        service = VisionService(self.root)
        with self.assertRaises(VisionUnavailable):
            service.tagger_for(0.5)
        with self.assertRaises(VisionUnavailable):
            service.tagger_for(character_threshold=0.9)

    def test_tagger_for_con_umbrales_usa_factoria_sin_cache(self):
        _write_assets(self.root)
        calls: list[tuple[str, str, dict]] = []

        def factory(onnx_path: Path, csv_path: Path, **kwargs):
            calls.append((onnx_path.name, csv_path.name, kwargs))
            return lambda raw: ["tag"]

        service = VisionService(self.root, tagger_factory=factory)
        self.assertEqual(service.tagger_for(0.5, 0.9)(b"img"), ["tag"])
        self.assertEqual(service.tagger_for(0.4)(b"img"), ["tag"])
        self.assertEqual(
            calls,
            [
                (
                    f"{WD14_MODEL}.onnx",
                    f"{WD14_MODEL}.csv",
                    {"threshold": 0.5, "character_threshold": 0.9},
                ),
                (
                    f"{WD14_MODEL}.onnx",
                    f"{WD14_MODEL}.csv",
                    {"threshold": 0.4},
                ),
            ],
        )

    def test_caption_sin_vl_lanza_vision_unavailable(self):
        with self.assertRaises(VisionUnavailable):
            VisionService(self.root).caption(b"img")

    def test_caption_usa_factoria_y_cachea(self):
        _write_assets(self.root)
        calls: list[tuple[str, str, int]] = []

        def factory(model_path: Path, mmproj_path: Path, gpu_layers: int):
            calls.append((model_path.name, mmproj_path.name, gpu_layers))
            return lambda raw: "a girl"

        service = VisionService(self.root, captioner_factory=factory)
        self.assertEqual(service.caption(b"img"), "a girl")
        self.assertEqual(service.caption(b"img"), "a girl")
        self.assertEqual(calls, [(VL_MODEL_FILE, VL_MMPROJ_FILE, 0)])

    def test_describe_combinaciones(self):
        _write_assets(self.root)
        service = VisionService(
            self.root,
            tagger_factory=lambda _o, _c: (lambda raw: ["tag"]),
            captioner_factory=lambda _m, _p, _g: (lambda raw: "cap"),
        )
        both = service.describe(b"img")
        self.assertEqual(both["tags"], ["tag"])
        self.assertEqual(both["caption"], "cap")
        self.assertIn("model", both)
        self.assertIsNone(service.describe(b"img", use_caption=False)["caption"])
        self.assertIsNone(service.describe(b"img", use_tags=False)["tags"])

    def test_describe_sin_assets_lanza(self):
        with self.assertRaises(VisionUnavailable):
            VisionService(self.root).describe(b"img", use_caption=False)
        with self.assertRaises(VisionUnavailable):
            VisionService(self.root).describe(b"img", use_tags=False)


class EnvOverrideTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(LLM_URL_ENV, None)

    def test_gpu_layers_env(self):
        with mock.patch.dict(os.environ, {"WAIFU_VL_GPU_LAYERS": "5"}):
            self.assertEqual(VisionService(self.root).gpu_layers, 5)
        with mock.patch.dict(os.environ, {"WAIFU_VL_GPU_LAYERS": ""}):
            self.assertEqual(VisionService(self.root).gpu_layers, 0)

    def test_vl_paths_env(self):
        model = self.root / "m.gguf"
        mmproj = self.root / "p.gguf"
        with mock.patch.dict(
            os.environ,
            {"WAIFU_VL_MODEL": str(model), "WAIFU_VL_MMPROJ": str(mmproj)},
        ):
            service = VisionService(self.root)
        self.assertEqual(service.vl_model, model)
        self.assertEqual(service.vl_mmproj, mmproj)


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


class ServerCaptionerTests(unittest.TestCase):
    """Captioner contra `llama-server` OpenAI-compatible (M11-2F)."""

    IMAGE = b"\x89PNG fake bytes"
    RESPONSE = {"choices": [{"message": {"content": "  a   girl \n smiling "}}]}

    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(LLM_TIMEOUT_ENV, None)

    def test_timeout_por_env_cuando_el_parametro_no_se_pasa(self):
        with mock.patch.dict(os.environ, {LLM_TIMEOUT_ENV: "7"}):
            transport = RecordingTransport(self.RESPONSE)
            load_server_captioner("http://x", transport=transport)(self.IMAGE)
        self.assertEqual(transport.calls[0][2], 7.0)

    def test_timeout_explicito_manda_sobre_env(self):
        with mock.patch.dict(os.environ, {LLM_TIMEOUT_ENV: "7"}):
            transport = RecordingTransport(self.RESPONSE)
            load_server_captioner(
                "http://x", transport=transport, timeout=3.0
            )(self.IMAGE)
        self.assertEqual(transport.calls[0][2], 3.0)

    def test_data_uri_prompts_y_payload_exactos(self):
        transport = RecordingTransport(self.RESPONSE)
        captioner = load_server_captioner("http://127.0.0.1:8290/", transport=transport)
        self.assertEqual(captioner(self.IMAGE), "a girl smiling")
        self.assertEqual(len(transport.calls), 1)
        url, payload, timeout = transport.calls[0]
        self.assertEqual(url, "http://127.0.0.1:8290/v1/chat/completions")
        self.assertEqual(timeout, 120.0)
        expected_uri = "data:image/png;base64," + base64.b64encode(self.IMAGE).decode(
            "ascii"
        )
        self.assertEqual(
            payload,
            {
                "model": "qwen35-9b-abliterated",
                "messages": [
                    {"role": "system", "content": VL_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VL_USER_PROMPT},
                            {"type": "image_url", "image_url": {"url": expected_uri}},
                        ],
                    },
                ],
                "max_tokens": 180,
                "temperature": 0.4,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        self.assertTrue(
            payload["messages"][1]["content"][1]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        )

    def test_caption_vacio_o_no_texto_lanza_engine_error(self):
        for response in (
            {},
            {"choices": []},
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": "  "}}]},
            "texto",
        ):
            with self.subTest(response=response):
                transport = RecordingTransport(response)
                captioner = load_server_captioner("http://x", transport=transport)
                with self.assertRaises(EngineError) as ctx:
                    captioner(b"img")
                self.assertEqual(str(ctx.exception), "vision: caption vacio")

    def test_base_por_parametro_manda_sobre_env(self):
        with mock.patch.dict(os.environ, {LLM_URL_ENV: "http://env:1111"}):
            transport = RecordingTransport(self.RESPONSE)
            load_server_captioner("http://param:2222", transport=transport)(b"img")
        self.assertEqual(transport.calls[0][0], "http://param:2222/v1/chat/completions")

    def test_env_y_default_de_base(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(LLM_URL_ENV, None)
            transport = RecordingTransport(self.RESPONSE)
            load_server_captioner(transport=transport)(b"img")
            self.assertEqual(
                transport.calls[0][0], f"{DEFAULT_LLM_URL}/v1/chat/completions"
            )
        with mock.patch.dict(os.environ, {LLM_URL_ENV: "http://env:1111"}):
            transport = RecordingTransport(self.RESPONSE)
            load_server_captioner(transport=transport)(b"img")
            self.assertEqual(
                transport.calls[0][0], "http://env:1111/v1/chat/completions"
            )


class ParseDescribeTests(unittest.TestCase):
    """`_parse_describe` (M11-3G): JSON tolerante a fences y prosa."""

    def test_json_puro(self):
        self.assertEqual(
            _parse_describe('{"caption": "a girl", "tags": "1girl, long hair"}'),
            ("a girl", "1girl, long hair"),
        )

    def test_json_en_fences(self):
        raw = '```json\n{"caption": "a girl", "tags": "1girl"}\n```'
        self.assertEqual(_parse_describe(raw), ("a girl", "1girl"))

    def test_prosa_alrededor(self):
        raw = 'Aqui tienes: {"caption": "a girl", "tags": "1girl"} Espero que sirva.'
        self.assertEqual(_parse_describe(raw), ("a girl", "1girl"))

    def test_campos_no_str_o_ausentes_quedan_vacios(self):
        self.assertEqual(
            _parse_describe('{"caption": 3, "tags": ["1girl"]}'), ("", "")
        )
        self.assertEqual(_parse_describe('{"caption": "c"}'), ("c", ""))
        self.assertEqual(_parse_describe('{"tags": "1girl"}'), ("", "1girl"))

    def test_fallback_sin_json_limpia_fences(self):
        self.assertEqual(_parse_describe("a girl smiling"), ("a girl smiling", ""))
        self.assertEqual(_parse_describe("```\nsolo texto\n```"), ("solo texto", ""))
        self.assertEqual(_parse_describe("  \n  "), ("", ""))
        self.assertEqual(_parse_describe(None), ("", ""))

    def test_llaves_desbalanceadas_caen_al_fallback(self):
        self.assertEqual(_parse_describe("{no json"), ("{no json", ""))

    def test_llaves_dentro_de_strings_no_rompen_el_conteo(self):
        raw = '{"caption": "a } girl with {braces}", "tags": "1girl"}'
        self.assertEqual(
            _parse_describe(raw), ("a } girl with {braces}", "1girl")
        )
        self.assertEqual(
            _parse_describe('{"caption": "a } girl", "tags": "smile"}'),
            ("a } girl", "smile"),
        )
        self.assertEqual(
            _parse_describe('{"caption": "a {girl}", "tags": "smile"}'),
            ("a {girl}", "smile"),
        )

    def test_comillas_escapadas_dentro_de_strings(self):
        raw = '{"caption": "say \\"hi\\" }", "tags": "smile"}'
        self.assertEqual(_parse_describe(raw), ('say "hi" }', "smile"))

    def test_candidato_invalido_prueba_el_siguiente(self):
        raw = '{no json} {"caption": "ok", "tags": "smile"}'
        self.assertEqual(_parse_describe(raw), ("ok", "smile"))


class ServerDescriberTests(unittest.TestCase):
    """Descriptor unificado contra `llama-server` OpenAI-compatible (M11-3G)."""

    IMAGE = b"\x89PNG fake bytes"

    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(LLM_TIMEOUT_ENV, None)

    def test_timeout_por_env_cuando_el_parametro_no_se_pasa(self):
        with mock.patch.dict(os.environ, {LLM_TIMEOUT_ENV: "7"}):
            transport = RecordingTransport(
                {"choices": [{"message": {"content": "a girl"}}]}
            )
            load_server_describer("http://x", transport=transport)(self.IMAGE)
        self.assertEqual(transport.calls[0][2], 7.0)

    def test_timeout_explicito_manda_sobre_env(self):
        with mock.patch.dict(os.environ, {LLM_TIMEOUT_ENV: "7"}):
            transport = RecordingTransport(
                {"choices": [{"message": {"content": "a girl"}}]}
            )
            load_server_describer(
                "http://x", transport=transport, timeout=3.0
            )(self.IMAGE)
        self.assertEqual(transport.calls[0][2], 3.0)

    def _load(self, content, response=None):
        transport = RecordingTransport(
            {"choices": [{"message": {"content": content}}]}
            if response is None
            else response
        )
        return load_server_describer("http://127.0.0.1:8290/", transport=transport), transport

    def test_payload_exacto_y_validacion_de_tags(self):
        content = json.dumps(
            {"caption": " a girl ", "tags": "1girl, longhair, inventado, SCORE_9"}
        )
        describer, transport = self._load(content)
        self.assertEqual(
            describer(self.IMAGE),
            {
                "caption": "a girl",
                "tags": ["1girl", "long hair", "SCORE_9"],
                "dropped": ["inventado"],
                "mode": "server",
            },
        )
        self.assertEqual(len(transport.calls), 1)
        url, payload, timeout = transport.calls[0]
        self.assertEqual(url, "http://127.0.0.1:8290/v1/chat/completions")
        self.assertEqual(timeout, 120.0)
        expected_uri = "data:image/png;base64," + base64.b64encode(self.IMAGE).decode(
            "ascii"
        )
        self.assertEqual(
            payload,
            {
                "model": "qwen35-9b-abliterated",
                "messages": [
                    {"role": "system", "content": DESCRIBE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": DESCRIBE_USER_PROMPT},
                            {"type": "image_url", "image_url": {"url": expected_uri}},
                        ],
                    },
                ],
                "max_tokens": 512,
                "temperature": 0.4,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        self.assertTrue(
            payload["messages"][1]["content"][1]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        )

    def test_prosa_sin_json_va_al_caption(self):
        describer, _transport = self._load("a girl smiling")
        result = describer(self.IMAGE)
        self.assertEqual(result["caption"], "a girl smiling")
        self.assertEqual(result["tags"], [])
        self.assertEqual(result["dropped"], [])

    def test_vacio_total_lanza_engine_error(self):
        for content in ('{"caption": "", "tags": ""}', '{"caption": " ", "tags": "inventado"}'):
            with self.subTest(content=content):
                describer, _transport = self._load(content)
                with self.assertRaises(EngineError) as ctx:
                    describer(self.IMAGE)
                self.assertEqual(str(ctx.exception), "vision: descripcion vacia")

    def test_contenido_no_texto_o_vacio_lanza_engine_error(self):
        for response in (
            {},
            {"choices": []},
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": "   "}}]},
            "texto",
        ):
            with self.subTest(response=response):
                describer = load_server_describer(
                    "http://x", transport=RecordingTransport(response)
                )
                with self.assertRaises(EngineError) as ctx:
                    describer(self.IMAGE)
                self.assertEqual(str(ctx.exception), "vision: descripcion vacia")


class VisionServiceUnifiedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(LLM_URL_ENV, None)

    def test_servidor_usa_describer_factory_y_cachea(self):
        calls: list[str] = []

        def factory(url):
            calls.append(url)
            return lambda raw: {
                "caption": "cap srv",
                "tags": ["1girl"],
                "dropped": ["inventado"],
                "mode": "server",
            }

        service = VisionService(
            self.root,
            server_url="http://127.0.0.1:8290/",
            describer_factory=factory,
        )
        expected = {
            "caption": "cap srv",
            "tags": ["1girl"],
            "dropped": ["inventado"],
            "mode": "server",
            "model": {"wd14": WD14_MODEL, "vl": VL_MODEL_FILE},
        }
        self.assertEqual(service.describe_unified(b"img"), expected)
        self.assertEqual(calls, ["http://127.0.0.1:8290"])
        self.assertEqual(service.describe_unified(b"img"), expected)
        self.assertEqual(len(calls), 1)

    def test_local_dos_pasos_sin_dropped(self):
        _write_assets(self.root)
        service = VisionService(
            self.root,
            tagger_factory=lambda _o, _c: (lambda raw: ["1girl", "long hair"]),
            captioner_factory=lambda _m, _p, _g: (lambda raw: "a girl"),
        )
        result = service.describe_unified(b"img")
        self.assertEqual(result["tags"], ["1girl", "long hair"])
        self.assertEqual(result["caption"], "a girl")
        self.assertEqual(result["dropped"], [])
        self.assertEqual(result["mode"], "local")
        self.assertEqual(result["model"], {"wd14": WD14_MODEL, "vl": VL_MODEL_FILE})


class VisionServiceServerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(LLM_URL_ENV, None)

    def test_server_url_explicito_usa_load_server_captioner(self):
        with mock.patch(
            "app.vision.load_server_captioner", return_value=lambda raw: "cap srv"
        ) as loader:
            service = VisionService(self.root, server_url="http://127.0.0.1:8290")
            self.assertTrue(service.vl_installed())
            self.assertEqual(service.caption(b"img"), "cap srv")
        loader.assert_called_once_with("http://127.0.0.1:8290")

    def test_captioner_factory_inyectado_manda(self):
        calls: list[tuple] = []

        def factory(*args):
            calls.append(args)
            return lambda raw: "cap local"

        service = VisionService(
            self.root, server_url="http://x", captioner_factory=factory
        )
        self.assertEqual(service.caption(b"img"), "cap local")
        self.assertEqual(len(calls), 1)
        self.assertEqual(service.caption(b"img"), "cap local")
        self.assertEqual(len(calls), 1)

    def test_status_nota_de_servidor_con_url(self):
        service = VisionService(self.root, server_url="http://127.0.0.1:8290/")
        status = service.status()
        self.assertTrue(status["vl"]["installed"])
        self.assertIn("http://127.0.0.1:8290", status["note"])
        self.assertIn("servidor HTTP", status["note"])
        self.assertNotIn("Qwen2.5-VL", status["note"])

    def test_env_activa_el_modo_servidor(self):
        with mock.patch.dict(os.environ, {LLM_URL_ENV: "http://env:1111"}):
            service = VisionService(self.root)
            self.assertEqual(service.server_url, "http://env:1111")
            self.assertTrue(service.vl_installed())

    def test_server_url_explicito_no_depende_de_env(self):
        with mock.patch.dict(os.environ, {LLM_URL_ENV: "http://env:1111"}):
            service = VisionService(self.root, server_url="http://x")
        self.assertEqual(service.server_url, "http://x")
        self.assertTrue(service.vl_installed())

    def test_server_url_vacio_fuerza_modo_local_con_env(self):
        with mock.patch.dict(os.environ, {LLM_URL_ENV: "http://env:1111"}):
            service = VisionService(self.root, server_url="")
            self.assertIsNone(service.server_url)
            self.assertFalse(service.vl_installed())
            with self.assertRaises(VisionUnavailable):
                service.caption(b"img")

    def test_sin_env_ni_server_url_modo_local(self):
        service = VisionService(self.root)
        self.assertIsNone(service.server_url)
        self.assertFalse(service.vl_installed())
        status = service.status()
        self.assertIn("llama.cpp", status["note"])
        self.assertIn("legacy", status["note"])


if __name__ == "__main__":
    unittest.main()
