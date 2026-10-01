"""Tests offline del servidor LLM gestionado (M12-3).

Probe y spawn inyectables: jamas se arranca `llama-server` real ni se abre un
socket. El proceso falso simula vivo/muerto y registra terminate/kill.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app import llm_server as llm_server_module
from app.engine import EngineError
from app.enhancer import LLM_URL_ENV
from app.llm_server import (
    DEFAULT_PORT,
    DEFAULT_THREADS,
    MMPROJ_ENV,
    MMPROJ_REL,
    MODEL_ENV,
    MODEL_REL,
    PORT_ENV,
    SERVER_REL,
    THREADS_ENV,
    LlamaServerManager,
    probe,
)


class FakeProbe:
    """Probe falso: consume la secuencia y repite el ultimo estado."""

    def __init__(self, states):
        self.states = list(states)
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


class FakeProc:
    """Proceso falso estilo Popen: poll/terminate/wait/kill."""

    def __init__(self, alive: bool = True, returncode: int = 0):
        self.alive = alive
        self.returncode = returncode
        self.terminated = 0
        self.killed = 0
        self.waits: list = []

    def poll(self):
        return None if self.alive else self.returncode

    def terminate(self):
        self.terminated += 1
        self.alive = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.returncode

    def kill(self):
        self.killed += 1
        self.alive = False


class FakeSpawn:
    """Spawn falso: registra `(command, log_handle)` y devuelve el proceso.

    Con `procs` (lista) devuelve uno por llamada y repite el ultimo; con
    `proc` devuelve siempre el mismo.
    """

    def __init__(
        self, proc: FakeProc | None = None, procs: list[FakeProc] | None = None
    ):
        self.calls: list = []
        if procs is not None:
            self.procs = list(procs)
        else:
            self.procs = [proc if proc is not None else FakeProc(alive=True)]

    def __call__(self, command, log_handle):
        self.calls.append((list(command), log_handle))
        index = min(len(self.calls) - 1, len(self.procs) - 1)
        return self.procs[index]


class ManagerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in (LLM_URL_ENV, PORT_ENV, THREADS_ENV, MODEL_ENV, MMPROJ_ENV):
            os.environ.pop(name, None)

    def make_tree(self):
        for relative in (SERVER_REL, MODEL_REL, MMPROJ_REL):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake")

    def make_manager(self, **kwargs) -> LlamaServerManager:
        manager = LlamaServerManager(self.root, **kwargs)
        self.addCleanup(manager.stop)
        return manager


class ExternalModeTests(ManagerTestCase):
    def test_ensure_devuelve_la_url_externa_sin_probe_ni_spawn(self):
        os.environ[LLM_URL_ENV] = "http://otro:9000"
        probe_fn = FakeProbe(["offline"])
        spawn = FakeSpawn()
        manager = self.make_manager(
            probe_fn=probe_fn, spawn_fn=spawn
        )
        self.assertEqual(manager.ensure(), "http://otro:9000")
        self.assertEqual(probe_fn.calls, [])
        self.assertEqual(spawn.calls, [])

    def test_status_delega_en_server_llm_state(self):
        os.environ[LLM_URL_ENV] = "http://otro:9000"
        manager = self.make_manager()
        with mock.patch(
            "app.enhancer.server_llm_state",
            return_value=("loading", "HTTP 503: loading model"),
        ) as state:
            status = manager.status()
        self.assertEqual(
            status,
            {
                "mode": "external",
                "state": "loading",
                "url": "http://otro:9000",
                "detail": "HTTP 503: loading model",
            },
        )
        state.assert_called_once_with("http://otro:9000")


class MissingFilesTests(ManagerTestCase):
    def test_faltantes_lanzan_engine_error_con_pista_de_descarga(self):
        spawn = FakeSpawn()
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline"]), spawn_fn=spawn
        )
        with self.assertRaises(EngineError) as ctx:
            manager.ensure()
        message = str(ctx.exception)
        self.assertIn("download_llm.py", message)
        self.assertIn(str(self.root / SERVER_REL), message)
        self.assertEqual(spawn.calls, [])
        self.assertFalse(manager.installed())

    def test_status_unavailable_sin_archivos(self):
        manager = self.make_manager(probe_fn=FakeProbe(["offline"]))
        status = manager.status()
        self.assertEqual(status["mode"], "managed")
        self.assertEqual(status["state"], "unavailable")
        self.assertIn("download_llm.py", status["detail"])


class StatusProbeTests(ManagerTestCase):
    """`status()` prueba el puerto aunque la app no haya usado el servidor (M12-4)."""

    def test_ready_sin_uso_previo(self):
        manager = self.make_manager(probe_fn=FakeProbe(["ready"]))
        status = manager.status()
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["url"], manager.base_url)

    def test_loading_sin_uso_previo(self):
        manager = self.make_manager(probe_fn=FakeProbe(["loading"]))
        self.assertEqual(manager.status()["state"], "loading")

    def test_foreign_sin_uso_previo_es_foreign(self):
        manager = self.make_manager(probe_fn=FakeProbe(["foreign"]))
        status = manager.status()
        self.assertEqual(status["state"], "foreign")
        self.assertIn("ocupado", status["detail"])

    def test_offline_sin_archivos_es_unavailable(self):
        manager = self.make_manager(probe_fn=FakeProbe(["offline"]))
        status = manager.status()
        self.assertEqual(status["state"], "unavailable")
        self.assertIn("download_llm.py", status["detail"])

    def test_offline_con_archivos_es_stopped(self):
        self.make_tree()
        manager = self.make_manager(probe_fn=FakeProbe(["offline"]))
        status = manager.status()
        self.assertEqual(status["state"], "stopped")
        self.assertIn("primer uso", status["detail"])

    def test_offline_con_proceso_vivo_es_loading(self):
        self.make_tree()
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline", "ready", "offline"]),
            spawn_fn=FakeSpawn(FakeProc(alive=True)),
            poll_s=0.0,
        )
        manager.ensure()
        self.assertEqual(manager.status()["state"], "loading")


class SpawnFlowTests(ManagerTestCase):
    def test_ensure_arranca_una_vez_espera_ready_y_reutiliza(self):
        self.make_tree()
        probe_fn = FakeProbe(["offline", "loading", "ready"])
        spawn = FakeSpawn()
        manager = self.make_manager(
            probe_fn=probe_fn, spawn_fn=spawn, poll_s=0.0
        )
        self.assertEqual(manager.ensure(), manager.base_url)
        self.assertEqual(len(spawn.calls), 1)
        command, handle = spawn.calls[0]
        self.assertEqual(command[0], str(self.root / SERVER_REL))
        self.assertEqual(command[command.index("-m") + 1], str(self.root / MODEL_REL))
        self.assertEqual(
            command[command.index("--mmproj") + 1], str(self.root / MMPROJ_REL)
        )
        self.assertEqual(command[command.index("-ngl") + 1], "0")
        self.assertEqual(command[command.index("-c") + 1], "8192")
        self.assertEqual(command[command.index("-t") + 1], str(DEFAULT_THREADS))
        self.assertEqual(command[command.index("--port") + 1], str(DEFAULT_PORT))
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertIn("--jinja", command)
        self.assertIn("--reasoning", command)
        self.assertIn("--no-webui", command)
        self.assertFalse(handle.closed)
        self.assertEqual(manager.status()["state"], "ready")
        self.assertEqual(manager.ensure(), manager.base_url)
        self.assertEqual(len(spawn.calls), 1)

    def test_status_loading_con_servidor_arrancando(self):
        self.make_tree()
        probe_fn = FakeProbe(["offline", "ready", "loading"])
        manager = self.make_manager(
            probe_fn=probe_fn,
            spawn_fn=FakeSpawn(),
            poll_s=0.0,
        )
        manager.ensure()
        self.assertEqual(manager.status()["state"], "loading")

    def test_puerto_ocupado_lanza_engine_error_sin_spawn(self):
        self.make_tree()
        spawn = FakeSpawn()
        manager = self.make_manager(
            probe_fn=FakeProbe(["foreign"]), spawn_fn=spawn
        )
        with self.assertRaises(EngineError) as ctx:
            manager.ensure()
        self.assertIn("ocupado", str(ctx.exception))
        self.assertEqual(spawn.calls, [])

    def test_reutiliza_servidor_loading_hasta_ready(self):
        self.make_tree()
        spawn = FakeSpawn()
        probe_fn = FakeProbe(["loading", "loading", "ready"])
        manager = self.make_manager(
            probe_fn=probe_fn, spawn_fn=spawn, poll_s=0.0
        )
        self.assertEqual(manager.ensure(), manager.base_url)
        self.assertEqual(spawn.calls, [])

    def test_proceso_muerto_en_la_espera_lanza_con_log(self):
        self.make_tree()
        log = self.root / "data" / "llm-server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "\n".join(f"linea {index}" for index in range(15)), encoding="utf-8"
        )
        proc = FakeProc(alive=False, returncode=3)
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline"]),
            spawn_fn=FakeSpawn(proc),
            poll_s=0.0,
        )
        with self.assertRaises(EngineError) as ctx:
            manager.ensure()
        message = str(ctx.exception)
        self.assertIn("codigo 3", message)
        self.assertIn("linea 14", message)
        self.assertNotIn("linea 4", message)

    def test_timeout_lanza_engine_error(self):
        self.make_tree()
        proc = FakeProc(alive=True)
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline"]),
            spawn_fn=FakeSpawn(proc),
            timeout_s=0.0,
            poll_s=0.0,
        )
        with self.assertRaises(EngineError) as ctx:
            manager.ensure()
        self.assertIn("timeout", str(ctx.exception).lower())
        self.assertEqual(proc.terminated, 0)


class EnsureHardeningTests(ManagerTestCase):
    """M12-3 (condiciones de auditoria): un solo proceso, sin huerfanos."""

    def test_proceso_vivo_colgado_no_respawnea_y_timeout(self):
        self.make_tree()
        proc = FakeProc(alive=True)
        spawn = FakeSpawn(proc)
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline", "ready", "offline"]),
            spawn_fn=spawn,
            timeout_s=0.0,
            poll_s=0.0,
        )
        self.assertEqual(manager.ensure(), manager.base_url)
        self.assertEqual(len(spawn.calls), 1)
        with self.assertRaises(EngineError) as ctx:
            manager.ensure()
        self.assertIn("timeout", str(ctx.exception).lower())
        self.assertEqual(len(spawn.calls), 1)
        self.assertEqual(proc.terminated, 0)

    def test_proceso_vivo_ready_se_reutiliza_sin_spawn(self):
        self.make_tree()
        spawn = FakeSpawn()
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline", "ready"]),
            spawn_fn=spawn,
            poll_s=0.0,
        )
        manager.ensure()
        self.assertEqual(manager.ensure(), manager.base_url)
        self.assertEqual(len(spawn.calls), 1)
        self.assertTrue(manager.active)

    def test_proceso_muerto_se_reemplaza_con_stop_y_spawn(self):
        self.make_tree()
        first = FakeProc(alive=True)
        second = FakeProc(alive=True)
        spawn = FakeSpawn(procs=[first, second])
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline", "ready", "offline", "ready"]),
            spawn_fn=spawn,
            poll_s=0.0,
        )
        manager.ensure()
        first.alive = False
        self.assertFalse(manager.active)
        self.assertEqual(manager.ensure(), manager.base_url)
        self.assertEqual(len(spawn.calls), 2)
        self.assertEqual(first.terminated, 0)
        self.assertTrue(manager.active)
        self.assertIs(manager._proc, second)


class StopTests(ManagerTestCase):
    def test_stop_mata_solo_lo_spawneado_y_es_idempotente(self):
        self.make_tree()
        proc = FakeProc(alive=True)
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline", "ready", "offline"]),
            spawn_fn=FakeSpawn(proc),
            poll_s=0.0,
        )
        manager.ensure()
        self.assertTrue(manager.managed)
        manager.stop()
        self.assertEqual(proc.terminated, 1)
        self.assertEqual(proc.killed, 0)
        self.assertEqual(proc.waits, [10])
        self.assertFalse(manager.managed)
        self.assertEqual(manager.status()["state"], "stopped")
        manager.stop()
        self.assertEqual(proc.terminated, 1)

    def test_stop_no_mata_servidor_reutilizado(self):
        self.make_tree()
        spawn = FakeSpawn()
        manager = self.make_manager(
            probe_fn=FakeProbe(["ready"]), spawn_fn=spawn
        )
        self.assertEqual(manager.ensure(), manager.base_url)
        manager.stop()
        self.assertEqual(spawn.calls, [])
        self.assertFalse(manager.managed)
        self.assertEqual(manager.status()["state"], "ready")

    def test_stop_cierra_el_log(self):
        self.make_tree()
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline", "ready"]),
            spawn_fn=FakeSpawn(),
            poll_s=0.0,
        )
        manager.ensure()
        handle = manager._log_handle
        manager.stop()
        self.assertTrue(handle.closed)


class EnvSettingsTests(ManagerTestCase):
    def test_puerto_y_threads_por_env_y_por_parametro(self):
        os.environ[PORT_ENV] = "9911"
        os.environ[THREADS_ENV] = "3"
        manager = self.make_manager()
        self.assertEqual(manager.port, 9911)
        self.assertEqual(manager.threads, 3)
        self.assertEqual(manager.base_url, "http://127.0.0.1:9911")
        explicit = self.make_manager(port=8282, threads=9)
        self.assertEqual(explicit.port, 8282)
        self.assertEqual(explicit.threads, 9)

    def test_env_ilegible_cae_al_default(self):
        os.environ[PORT_ENV] = "no-numero"
        os.environ[THREADS_ENV] = ""
        manager = self.make_manager()
        self.assertEqual(manager.port, DEFAULT_PORT)
        self.assertEqual(manager.threads, DEFAULT_THREADS)

    def test_spawn_usa_puerto_y_threads_del_env(self):
        self.make_tree()
        os.environ[PORT_ENV] = "9911"
        os.environ[THREADS_ENV] = "3"
        spawn = FakeSpawn()
        manager = self.make_manager(
            probe_fn=FakeProbe(["offline", "ready"]),
            spawn_fn=spawn,
            poll_s=0.0,
        )
        manager.ensure()
        command, _handle = spawn.calls[0]
        self.assertEqual(command[command.index("--port") + 1], "9911")
        self.assertEqual(command[command.index("-t") + 1], "3")
        self.assertEqual(manager.base_url, "http://127.0.0.1:9911")

    def test_modelo_y_mmproj_por_env(self):
        custom_model = self.root / "otro.gguf"
        custom_mmproj = self.root / "otro-mmproj.gguf"
        os.environ[MODEL_ENV] = str(custom_model)
        os.environ[MMPROJ_ENV] = str(custom_mmproj)
        manager = self.make_manager()
        self.assertEqual(manager.model_path, custom_model)
        self.assertEqual(manager.mmproj_path, custom_mmproj)

    def test_ruta_env_relativa_cuelga_de_root(self):
        os.environ[MODEL_ENV] = "mi-modelo.gguf"
        manager = self.make_manager()
        self.assertEqual(manager.model_path, self.root / "mi-modelo.gguf")


class DefaultProbeTests(unittest.TestCase):
    @staticmethod
    def _response(status: int, body: bytes):
        response = mock.MagicMock()
        response.status = status
        response.read.return_value = body
        response.__enter__.return_value = response
        return response

    def test_200_con_status_es_ready(self):
        response = self._response(200, b'{"status": "ok"}')
        with mock.patch.object(
            llm_server_module.urllib.request, "urlopen", return_value=response
        ):
            self.assertEqual(probe("http://127.0.0.1:8290"), "ready")

    def test_200_sin_forma_de_llama_server_es_foreign(self):
        for body in (b"no json", b'{"foo": 1}', b"[]"):
            with self.subTest(body=body):
                response = self._response(200, body)
                with mock.patch.object(
                    llm_server_module.urllib.request, "urlopen", return_value=response
                ):
                    self.assertEqual(probe("http://x"), "foreign")

    def test_503_es_loading(self):
        error = urllib.error.HTTPError("http://x/health", 503, "loading", None, None)
        with mock.patch.object(
            llm_server_module.urllib.request, "urlopen", side_effect=error
        ):
            self.assertEqual(probe("http://x"), "loading")

    def test_otros_http_son_foreign(self):
        error = urllib.error.HTTPError("http://x/health", 500, "boom", None, None)
        with mock.patch.object(
            llm_server_module.urllib.request, "urlopen", side_effect=error
        ):
            self.assertEqual(probe("http://x"), "foreign")

    def test_error_de_red_es_offline(self):
        error = urllib.error.URLError("sin ruta")
        with mock.patch.object(
            llm_server_module.urllib.request, "urlopen", side_effect=error
        ):
            self.assertEqual(probe("http://x"), "offline")


if __name__ == "__main__":
    unittest.main()
