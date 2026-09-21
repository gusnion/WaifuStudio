"""Tests CPU de app.engine con transporte falso (offline, sin GPU)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.config import EngineConfig
from app.engine import (
    ComfyEngine,
    EngineError,
    EngineRejected,
    EngineTimeout,
    load_graph,
)


def json_bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


class FakeTransport:
    """Transporte falso: registra llamadas y sirve respuestas preprogramadas."""

    def __init__(self, responses=(), default=None):
        self.calls: list[dict] = []
        self._responses = list(responses)
        self._default = default

    def __call__(self, method, path, body=None, headers=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        if self._responses:
            return self._responses.pop(0)
        if self._default is not None:
            return self._default
        raise AssertionError(f"transporte falso sin respuesta para {method} {path}")


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        (self.tmp / "output").mkdir()

    def build_engine(self, transport, **kwargs) -> ComfyEngine:
        config = EngineConfig(
            comfy_root=self.tmp,
            comfy_url="http://test",
            data_dir=self.tmp / "data",
        )
        return ComfyEngine(config, transport=transport, **kwargs)


class SubmitTests(EngineTestCase):
    def test_submit_ok_devuelve_prompt_id_y_payload(self):
        transport = FakeTransport([(200, json_bytes({"prompt_id": "pid-1"}))])
        engine = self.build_engine(transport)
        graph = {"1": {"class_type": "KSampler"}}

        prompt_id = engine.submit(graph)

        self.assertEqual(prompt_id, "pid-1")
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/prompt")
        self.assertEqual(call["headers"].get("Content-Type"), "application/json")
        payload = json.loads(call["body"].decode("utf-8"))
        self.assertEqual(payload["prompt"], graph)
        self.assertEqual(payload["client_id"], engine.client_id)
        self.assertNotIn("partial_execution_targets", payload)
        self.assertEqual(len(engine.client_id), 32)

    def test_submit_incluye_partial_execution_targets_si_no_es_none(self):
        transport = FakeTransport([(200, json_bytes({"prompt_id": "pid-2"}))])
        engine = self.build_engine(transport)

        engine.submit({"1": {"class_type": "KSampler"}}, partial_execution_targets=["9"])

        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["partial_execution_targets"], ["9"])

    def test_submit_400_lanza_engine_rejected_con_detalle(self):
        transport = FakeTransport(
            [
                (
                    400,
                    json_bytes(
                        {
                            "error": {"type": "prompt_no_outputs"},
                            "node_errors": {"1": "invalid input"},
                        }
                    ),
                )
            ]
        )
        engine = self.build_engine(transport)

        with self.assertRaises(EngineRejected) as ctx:
            engine.submit({"1": {"class_type": "KSampler"}})

        message = str(ctx.exception)
        self.assertIn("400", message)
        self.assertIn("prompt_no_outputs", message)
        self.assertIn("invalid input", message)

    def test_submit_2xx_sin_prompt_id_lanza_engine_error(self):
        transport = FakeTransport([(200, json_bytes({"number": 3}))])
        engine = self.build_engine(transport)

        with self.assertRaises(EngineError) as ctx:
            engine.submit({"1": {"class_type": "KSampler"}})

        self.assertNotIsInstance(ctx.exception, EngineRejected)


class WaitTests(EngineTestCase):
    def test_wait_sondea_hasta_success(self):
        entry = {"status": {"status_str": "success"}}
        transport = FakeTransport(
            [
                (200, b"{}"),
                (200, json_bytes({"pid-1": entry})),
            ]
        )
        engine = self.build_engine(transport, poll_s=0.0)

        result = engine.wait("pid-1")

        self.assertEqual(result, entry)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0]["method"], "GET")
        self.assertEqual(transport.calls[0]["path"], "/history/pid-1")

    def test_wait_tolera_error_de_red_transitorio(self):
        entry = {"status": {"status_str": "success"}}
        calls: list[str] = []

        def transport(method, path, body=None, headers=None, timeout=None):
            calls.append(path)
            if len(calls) == 1:
                raise EngineError("transporte fallo simulado")
            return 200, json_bytes({"pid-1": entry})

        engine = self.build_engine(transport, poll_s=0.0)

        self.assertEqual(engine.wait("pid-1"), entry)
        self.assertEqual(len(calls), 2)

    def test_wait_state_error_lanza_engine_error_con_mensajes(self):
        entry = {
            "status": {
                "status_str": "error",
                "messages": [["execution_error", {"node_id": "1"}]],
            }
        }
        transport = FakeTransport([(200, json_bytes({"pid-1": entry}))])
        engine = self.build_engine(transport, poll_s=0.0)

        with self.assertRaises(EngineError) as ctx:
            engine.wait("pid-1")

        self.assertIn("execution_error", str(ctx.exception))
        self.assertIn("node_id", str(ctx.exception))

    def test_wait_timeout_lanza_engine_timeout(self):
        transport = FakeTransport(default=(200, b"{}"))
        engine = self.build_engine(transport, poll_s=0.0, history_timeout_s=0.0)

        with self.assertRaises(EngineTimeout):
            engine.wait("pid-1")


class QueueStateTests(EngineTestCase):
    def test_queue_running(self):
        transport = FakeTransport(
            [(200, json_bytes({"queue_running": [[0, "pid-1"]], "queue_pending": []}))]
        )
        engine = self.build_engine(transport)

        self.assertEqual(engine.queue_state("pid-1"), "running")
        self.assertEqual(transport.calls[0]["path"], "/queue")

    def test_queue_pending(self):
        transport = FakeTransport(
            [
                (
                    200,
                    json_bytes(
                        {
                            "queue_running": [[0, "otro"]],
                            "queue_pending": [[1, "pid-1"]],
                        }
                    ),
                )
            ]
        )
        engine = self.build_engine(transport)

        self.assertEqual(engine.queue_state("pid-1"), "pending")

    def test_queue_absent(self):
        transport = FakeTransport(
            [(200, json_bytes({"queue_running": [], "queue_pending": []}))]
        )
        engine = self.build_engine(transport)

        self.assertEqual(engine.queue_state("pid-1"), "absent")


class OutputsTests(EngineTestCase):
    def _write(self, name: str) -> Path:
        path = self.tmp / "output" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png-bytes")
        return path.resolve()

    def test_outputs_devuelve_ruta_existente(self):
        expected = self._write("foo.png")
        entry = {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "foo.png", "subfolder": "", "type": "output"}
                    ]
                }
            }
        }
        engine = self.build_engine(FakeTransport())

        result = engine.outputs(entry)

        self.assertEqual(result, [expected])
        self.assertTrue(result[0].is_file())

    def test_outputs_recorre_todos_los_nodos_en_orden(self):
        first = self._write("a.png")
        second = self._write("b.png")
        entry = {
            "outputs": {
                "1": {"images": [{"filename": "a.png", "type": "output"}]},
                "2": {"images": [{"filename": "b.png", "type": "output"}]},
            }
        }
        engine = self.build_engine(FakeTransport())

        self.assertEqual(engine.outputs(entry), [first, second])
        self.assertEqual(engine.outputs(entry, node_id="2"), [second])

    def test_outputs_ignora_items_que_no_son_output(self):
        self._write("tmp.png")
        entry = {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "tmp.png", "subfolder": "", "type": "temp"}
                    ]
                }
            }
        }
        engine = self.build_engine(FakeTransport())

        self.assertEqual(engine.outputs(entry), [])

    def test_outputs_filtra_extension_no_esperada(self):
        self._write("foto.jpg")
        entry = {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "foto.jpg", "subfolder": "", "type": "output"}
                    ]
                }
            }
        }
        engine = self.build_engine(FakeTransport())

        self.assertEqual(engine.outputs(entry), [])
        self.assertEqual(len(engine.outputs(entry, expected_ext=("jpg",))), 1)

    def test_outputs_rechaza_escape_por_subfolder(self):
        entry = {
            "outputs": {
                "9": {
                    "images": [
                        {
                            "filename": "evil.png",
                            "subfolder": r"..\..",
                            "type": "output",
                        }
                    ]
                }
            }
        }
        engine = self.build_engine(FakeTransport())

        with self.assertRaises(EngineError):
            engine.outputs(entry)

    def test_outputs_rechaza_filename_absoluto(self):
        entry = {
            "outputs": {
                "9": {
                    "images": [
                        {
                            "filename": str(self.tmp / "output" / "x.png"),
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                }
            }
        }
        engine = self.build_engine(FakeTransport())

        with self.assertRaises(EngineError):
            engine.outputs(entry)

    def test_outputs_lanza_si_el_archivo_no_existe(self):
        entry = {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "missing.png", "subfolder": "", "type": "output"}
                    ]
                }
            }
        }
        engine = self.build_engine(FakeTransport())

        with self.assertRaises(EngineError):
            engine.outputs(entry)


class SystemStatsTests(EngineTestCase):
    def test_system_stats_ok(self):
        payload = {"system": {"comfyui_version": "0.3"}, "devices": []}
        transport = FakeTransport([(200, json_bytes(payload))])
        engine = self.build_engine(transport)

        self.assertEqual(engine.system_stats(), payload)
        self.assertEqual(transport.calls[0]["path"], "/system_stats")


class LoadGraphTests(EngineTestCase):
    def test_load_graph_valido(self):
        path = self.tmp / "graph.json"
        graph = {"1": {"class_type": "KSampler", "inputs": {}}}
        path.write_text(json.dumps(graph), encoding="utf-8")

        self.assertEqual(load_graph(path), graph)
        self.assertEqual(load_graph(str(path)), graph)

    def test_load_graph_json_lista_lanza_engine_error(self):
        path = self.tmp / "lista.json"
        path.write_text("[1, 2]", encoding="utf-8")

        with self.assertRaises(EngineError):
            load_graph(path)

    def test_load_graph_nodo_sin_class_type_lanza_engine_error(self):
        path = self.tmp / "sin_tipo.json"
        path.write_text(json.dumps({"1": {"inputs": {}}}), encoding="utf-8")

        with self.assertRaises(EngineError):
            load_graph(path)

    def test_load_graph_vacio_lanza_engine_error(self):
        path = self.tmp / "vacio.json"
        path.write_text("{}", encoding="utf-8")

        with self.assertRaises(EngineError):
            load_graph(path)


if __name__ == "__main__":
    unittest.main()
