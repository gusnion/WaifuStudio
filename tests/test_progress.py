"""Tests CPU de app.progress con ws_factory falso (offline, sin red)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import unittest

from app.progress import ProgressTracker


def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class FakeSocket:
    """Iterable async: sirve guiones y luego queda bloqueado (WS abierto)."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.received = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            item = self._messages.pop(0)
            self.received += 1
            return item if isinstance(item, str) else json.dumps(item)
        await asyncio.Event().wait()
        raise AssertionError("inalcanzable")


class FakeContext:
    def __init__(self, socket):
        self.socket = socket
        self.closed = False

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True
        return False


class FakeFactory:
    def __init__(self, messages=(), fail=False):
        self.calls: list[str] = []
        self.contexts: list[FakeContext] = []
        self._messages = list(messages)
        self._fail = fail

    def __call__(self, url: str) -> FakeContext:
        self.calls.append(url)
        if self._fail:
            raise ConnectionError("engine ausente")
        context = FakeContext(FakeSocket(self._messages))
        self.contexts.append(context)
        return context


class ProgressTrackerTests(unittest.TestCase):
    def build(self, factory, **kwargs) -> ProgressTracker:
        tracker = ProgressTracker(
            "ws://127.0.0.1:9/ws",
            "cid",
            "pid",
            ws_factory=factory,
            retry_s=0.01,
            **kwargs,
        )
        self.addCleanup(tracker.stop)
        return tracker

    def test_secuencia_completa_termina_en_done(self):
        factory = FakeFactory(
            [
                {"type": "execution_start", "data": {"prompt_id": "pid"}},
                {"type": "progress", "data": {"value": 3, "max": 20, "prompt_id": "pid"}},
                {"type": "executing", "data": {"node": "9", "prompt_id": "pid"}},
                {"type": "executing", "data": {"node": None, "prompt_id": "pid"}},
            ]
        )
        tracker = self.build(factory)

        tracker.start()
        self.assertTrue(wait_for(lambda: tracker.snapshot()["state"] == "done"))

        snapshot = tracker.snapshot()
        self.assertEqual(snapshot["step"], 3)
        self.assertEqual(snapshot["total"], 20)
        self.assertEqual(snapshot["node"], "9")
        self.assertEqual(snapshot["state"], "done")
        self.assertEqual(tracker.percent(), 15.0)

        tracker.stop()
        self.assertTrue(factory.contexts[0].closed)

    def test_execution_error_pasa_a_error(self):
        factory = FakeFactory(
            [{"type": "execution_error", "data": {"prompt_id": "pid", "node_id": "3"}}]
        )
        tracker = self.build(factory)

        tracker.start()
        self.assertTrue(wait_for(lambda: tracker.snapshot()["state"] == "error"))

        self.assertEqual(tracker.snapshot()["state"], "error")

    def test_ignora_mensajes_de_otro_prompt_id(self):
        factory = FakeFactory(
            [
                {"type": "progress", "data": {"value": 5, "max": 10, "prompt_id": "otro"}},
                {"type": "executing", "data": {"node": "3", "prompt_id": "otro"}},
                {"type": "execution_start", "data": {"prompt_id": "pid"}},
            ]
        )
        tracker = self.build(factory)

        tracker.start()
        self.assertTrue(wait_for(lambda: tracker.snapshot()["state"] == "running"))

        snapshot = tracker.snapshot()
        self.assertIsNone(snapshot["step"])
        self.assertIsNone(snapshot["total"])
        self.assertIsNone(snapshot["node"])
        self.assertIsNone(tracker.percent())

    def test_fallo_de_conexion_deja_unknown_sin_excepcion(self):
        factory = FakeFactory(fail=True)
        tracker = self.build(factory)

        tracker.start()
        self.assertTrue(wait_for(lambda: len(factory.calls) >= 2))
        thread = tracker._thread
        self.assertTrue(wait_for(lambda: thread is None or not thread.is_alive()))

        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(tracker.snapshot()["state"], "unknown")
        self.assertIsNone(tracker.percent())

    def test_stop_idempotente_y_sin_hilos_vivos(self):
        factory = FakeFactory(
            [{"type": "execution_start", "data": {"prompt_id": "pid"}}]
        )
        tracker = self.build(factory)

        tracker.start()
        self.assertTrue(wait_for(lambda: tracker.snapshot()["state"] == "running"))

        started = time.monotonic()
        tracker.stop()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 5.0)
        tracker.stop()
        thread = tracker._thread
        self.assertIsNotNone(thread)
        self.assertFalse(thread.is_alive())
        self.assertTrue(factory.contexts[0].closed)
        live = [
            t.name
            for t in threading.enumerate()
            if t.name.startswith("waifu-progress-") and t.is_alive()
        ]
        self.assertEqual(live, [])

    def test_percent_none_sin_total_o_total_cero(self):
        factory = FakeFactory(
            [
                {"type": "execution_start", "data": {"prompt_id": "pid"}},
                {"type": "progress", "data": {"value": 2, "prompt_id": "pid"}},
                {"type": "progress", "data": {"value": 4, "max": 0, "prompt_id": "pid"}},
            ]
        )
        tracker = self.build(factory)

        tracker.start()
        self.assertTrue(wait_for(lambda: tracker.snapshot()["step"] == 4))

        self.assertIsNone(tracker.percent())

    def test_snapshot_es_copia(self):
        factory = FakeFactory(
            [{"type": "execution_start", "data": {"prompt_id": "pid"}}]
        )
        tracker = self.build(factory)

        tracker.start()
        self.assertTrue(wait_for(lambda: tracker.snapshot()["state"] == "running"))

        snapshot = tracker.snapshot()
        snapshot["state"] = "mutado"

        self.assertEqual(tracker.snapshot()["state"], "running")

    def test_percent_redondea(self):
        factory = FakeFactory(
            [{"type": "progress", "data": {"value": 1, "max": 3, "prompt_id": "pid"}}]
        )
        tracker = self.build(factory)

        tracker.start()
        self.assertTrue(wait_for(lambda: tracker.percent() is not None))

        self.assertEqual(tracker.percent(), 33.33)


if __name__ == "__main__":
    unittest.main()
