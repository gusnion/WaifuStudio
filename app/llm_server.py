"""Servidor LLM gestionado (M12-3): arranque/parada perezosa de `llama-server`.

Sin `WAIFU_LLM_URL` en el entorno, la app es duena del ciclo de vida: la primera
llamada al LLM (`/api/enhance`, `/api/motion`, vision) arranca
`tools/llama.cpp/llama-server.exe` como proceso hijo en CPU (`-ngl 0`) con el
GGUF + mmproj del manifiesto, y el cierre de la app lo para. Con
`WAIFU_LLM_URL` definida se respeta el modo externo: ni se arranca ni se mata
nada. `probe_fn` y `spawn_fn` son inyectables para que los tests corran offline
(sin red ni procesos reales).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from app.config import APP_ROOT
from app.engine import EngineError
from app.enhancer import LLM_URL_ENV

PORT_ENV = "WAIFU_LLM_PORT"
MODEL_ENV = "WAIFU_LLM_MODEL"
MMPROJ_ENV = "WAIFU_LLM_MMPROJ"
THREADS_ENV = "WAIFU_LLM_THREADS"
SERVER_REL = "tools/llama.cpp/llama-server.exe"
MODEL_REL = (
    "ComfyUI/models/llm/qwen35-9b-nsfw-captioning/"
    "qwen3.5-9b-nsfw-captioning-v5.Q4_K_M.gguf"
)
MMPROJ_REL = (
    "ComfyUI/models/llm/qwen35-9b-nsfw-captioning/"
    "qwen3.5-9b-nsfw-captioning-v5.mmproj-Q8_0.gguf"
)
LEGACY_MODEL_REL = (
    "ComfyUI/models/llm/qwen35-9b-abliterated/"
    "Qwen3.5-9B-abliterated-Q4_K_M.gguf"
)
LEGACY_MMPROJ_REL = "ComfyUI/models/llm/qwen35-9b-abliterated/mmproj-F16.gguf"
LOG_REL = "data/llm-server.log"
DEFAULT_PORT = 8290
DEFAULT_THREADS = max(4, min(8, (os.cpu_count() or 8) // 2))
PROBE_TIMEOUT_S = 2.0
DOWNLOAD_HINT = "& .\\.venv\\Scripts\\python.exe scripts\\download_llm.py"
LOG_TAIL_LINES = 10
KILL_WAIT_S = 10

SpawnFn = Callable[[list[str], Any], Any]


def probe(url: str) -> str:
    """Estado del `llama-server` en `url`: ready/loading/foreign/offline.

    GET `{url}/health`: 200 con JSON de clave `status` -> `"ready"`; 503 ->
    `"loading"`; 200 sin forma de llama-server (o 4xx/5xx que no sea 503, o
    cualquier otro HTTP en el puerto) -> `"foreign"`; fallo de red -> `"offline"`.
    Es el unico camino que abre sockets; en tests se inyecta otro probe.
    """
    endpoint = url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(endpoint, timeout=PROBE_TIMEOUT_S) as response:
            status = int(getattr(response, "status", 200))
            body = response.read()
    except urllib.error.HTTPError as exc:
        return "loading" if int(exc.code) == 503 else "foreign"
    except (urllib.error.URLError, OSError, ValueError):
        return "offline"
    if status == 503:
        return "loading"
    if status != 200:
        return "foreign"
    try:
        parsed = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return "foreign"
    if isinstance(parsed, dict) and "status" in parsed:
        return "ready"
    return "foreign"


def _env_int(name: str, default: int) -> int:
    """Entero de la env; ausente o no parseable cae al default."""
    text = os.environ.get(name, "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _env_path(name: str, default: Path, root: Path) -> Path:
    """Ruta de la env (relativa a `root` si no es absoluta); vacia -> default."""
    text = os.environ.get(name, "").strip()
    if not text:
        return Path(default)
    path = Path(text)
    return path if path.is_absolute() else Path(root) / path


def _default_spawn(command: list[str], log_handle: Any) -> Any:
    """Arranca el proceso con la salida al log; Popen con `CREATE_NO_WINDOW`."""
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    return subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )


class LlamaServerManager:
    """Ciclo de vida del `llama-server` gestionado (lazy, hilo-seguro).

    `ensure()` devuelve la URL externa si `WAIFU_LLM_URL` esta definida. En modo
    gestionado nunca duplica procesos: con un proceso propio vivo espera su
    `ready`; si hay un servidor ajeno en el puerto lo reutiliza (sin matarlo);
    si hay que arrancar y quedo un proceso anterior muerto, lo limpia con
    `stop()` antes de spawnear. `stop()` para solo lo que arranco este manager;
    es idempotente.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        port: int | None = None,
        threads: int | None = None,
        server_path: str | Path | None = None,
        model_path: str | Path | None = None,
        mmproj_path: str | Path | None = None,
        log_path: str | Path | None = None,
        probe_fn: Callable[[str], str] | None = None,
        spawn_fn: SpawnFn | None = None,
        timeout_s: float = 240.0,
        poll_s: float = 1.0,
    ) -> None:
        self.root = Path(root) if root is not None else APP_ROOT
        self.port = int(port) if port is not None else _env_int(PORT_ENV, DEFAULT_PORT)
        self.threads = (
            int(threads) if threads is not None else _env_int(THREADS_ENV, DEFAULT_THREADS)
        )
        self.server_path = (
            Path(server_path)
            if server_path is not None
            else self.root / SERVER_REL
        )
        if model_path is not None:
            self.model_path = Path(model_path)
        elif os.environ.get(MODEL_ENV, "").strip():
            self.model_path = _env_path(MODEL_ENV, self.root / MODEL_REL, self.root)
        else:
            primary = self.root / MODEL_REL
            legacy = self.root / LEGACY_MODEL_REL
            self.model_path = (
                primary if primary.is_file() or not legacy.is_file() else legacy
            )
        if mmproj_path is not None:
            self.mmproj_path = Path(mmproj_path)
        elif os.environ.get(MMPROJ_ENV, "").strip():
            self.mmproj_path = _env_path(MMPROJ_ENV, self.root / MMPROJ_REL, self.root)
        else:
            primary_mm = self.root / MMPROJ_REL
            legacy_mm = self.root / LEGACY_MMPROJ_REL
            self.mmproj_path = (
                primary_mm
                if primary_mm.is_file() or not legacy_mm.is_file()
                else legacy_mm
            )
        self.log_path = Path(log_path) if log_path is not None else self.root / LOG_REL
        self.timeout_s = float(timeout_s)
        self.poll_s = float(poll_s)
        self._probe_fn = probe_fn if probe_fn is not None else probe
        self._spawn_fn = spawn_fn if spawn_fn is not None else _default_spawn
        self._lock = threading.RLock()
        self._proc: Any = None
        self._managed = False
        self._log_handle: Any = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def external_url(self) -> str | None:
        """URL externa de `WAIFU_LLM_URL` (o `None` si no hay modo externo)."""
        url = os.environ.get(LLM_URL_ENV, "").strip()
        return url or None

    def missing_files(self) -> list[Path]:
        """Rutas del runtime/modelo/mmproj que no existen."""
        return [
            path
            for path in (self.server_path, self.model_path, self.mmproj_path)
            if not Path(path).is_file()
        ]

    def installed(self) -> bool:
        """True si estan los tres archivos del servidor gestionado."""
        return not self.missing_files()

    @property
    def managed(self) -> bool:
        return self._managed

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ensure(self) -> str:
        """URL lista para usar: externa si hay env; si no, servidor gestionado.

        Un unico proceso por manager: con un proceso propio vivo espera su
        `ready` (nunca lanza otro); reutiliza un servidor ya presente en el
        puerto (ready, o loading con espera); si quedo un proceso anterior
        muerto lo limpia con `stop()` antes de spawnear. Error claro si el
        puerto lo ocupa otra aplicacion, si faltan archivos o si el proceso
        muere/expira durante la espera.
        """
        with self._lock:
            external = self.external_url()
            if external:
                return external
            if self.active:
                self._wait_ready(self._proc)
                return self.base_url
            state = self._probe_fn(self.base_url)
            if state == "ready":
                return self.base_url
            if state == "loading":
                self._wait_ready(None)
                return self.base_url
            if state == "foreign":
                raise EngineError(
                    f"puerto {self.port} ocupado por otra aplicacion"
                )
            missing = self.missing_files()
            if missing:
                raise EngineError(self._missing_error(missing))
            if self._proc is not None:
                self.stop()
            self._start()
            self._wait_ready(self._proc)
            return self.base_url

    def stop(self) -> None:
        """Para el proceso arrancado por este manager (idempotente).

        Los servidores externos o reutilizados no se matan; si nunca arranco
        nada solo cierra el log. `terminate` -> `wait(10)` -> `kill`.
        """
        with self._lock:
            proc = self._proc
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=KILL_WAIT_S)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=KILL_WAIT_S)
                    except subprocess.TimeoutExpired:
                        pass
            self._proc = None
            self._managed = False
            self._close_log()

    def status(self) -> dict:
        """Estado del LLM: `{mode, state, url, detail}` (sin arrancar nada).

        En modo gestionado prueba siempre el puerto, aunque la app no lo haya
        usado todavia: `ready`/`loading`; puerto ocupado por otro HTTP ->
        `foreign`; ficheros ausentes -> `unavailable`; `offline` con proceso
        vivo -> `loading`; si no, `stopped`. El modo external delega en
        `server_llm_state` como antes.
        """
        external = self.external_url()
        if external:
            from app.enhancer import server_llm_state

            state, detail = server_llm_state(external)
            return {
                "mode": "external",
                "state": state,
                "url": external,
                "detail": detail,
            }
        state = self._probe_fn(self.base_url)
        if state == "ready":
            return {
                "mode": "managed",
                "state": "ready",
                "url": self.base_url,
                "detail": "servidor gestionado",
            }
        if state == "loading":
            return {
                "mode": "managed",
                "state": "loading",
                "url": self.base_url,
                "detail": "cargando modelo",
            }
        if state == "foreign":
            return {
                "mode": "managed",
                "state": "foreign",
                "url": self.base_url,
                "detail": f"puerto {self.port} ocupado por otra aplicacion",
            }
        if self.active:
            return {
                "mode": "managed",
                "state": "loading",
                "url": self.base_url,
                "detail": "cargando modelo",
            }
        missing = self.missing_files()
        if missing:
            return {
                "mode": "managed",
                "state": "unavailable",
                "url": self.base_url,
                "detail": self._missing_error(missing).replace("\n", " "),
            }
        return {
            "mode": "managed",
            "state": "stopped",
            "url": self.base_url,
            "detail": "lo arranca la app al primer uso",
        }

    def _missing_error(self, missing: list[Path]) -> str:
        lines = "\n".join(f"  - {path}" for path in missing)
        return f"faltan archivos del servidor LLM:\n{lines}\ndescargalos con: {DOWNLOAD_HINT}"

    def _command(self) -> list[str]:
        return [
            str(self.server_path),
            "-m",
            str(self.model_path),
            "--mmproj",
            str(self.mmproj_path),
            "-ngl",
            "0",
            "-c",
            "8192",
            "-t",
            str(self.threads),
            "--jinja",
            "--reasoning",
            "off",
            "--no-webui",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        ]

    def _start(self) -> None:
        command = self._command()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.log_path.open("a", encoding="utf-8")
        handle.write(
            f"\n=== llama-server {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
        )
        handle.flush()
        self._log_handle = handle
        try:
            self._proc = self._spawn_fn(command, handle)
        except Exception:
            self._close_log()
            raise
        self._managed = True

    def _wait_ready(self, proc: Any) -> None:
        deadline = time.monotonic() + self.timeout_s
        while True:
            state = self._probe_fn(self.base_url)
            if state == "ready":
                return
            if state == "foreign":
                raise EngineError(f"puerto {self.port} ocupado por otra aplicacion")
            if proc is not None and proc.poll() is not None:
                raise EngineError(self._exit_error(proc))
            if time.monotonic() >= deadline:
                raise EngineError(
                    f"timeout de {self.timeout_s:g}s esperando llama-server en "
                    f"{self.base_url}{self._log_suffix()}"
                )
            time.sleep(self.poll_s)

    def _exit_error(self, proc: Any) -> str:
        code = getattr(proc, "returncode", None)
        return f"llama-server termino (codigo {code}){self._log_suffix()}"

    def _log_suffix(self) -> str:
        tail = self._log_tail()
        return f"; ultimas lineas:\n{tail}" if tail else ""

    def _log_tail(self) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-LOG_TAIL_LINES:])

    def _close_log(self) -> None:
        handle = self._log_handle
        self._log_handle = None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass


__all__ = [
    "DEFAULT_PORT",
    "DEFAULT_THREADS",
    "DOWNLOAD_HINT",
    "LEGACY_MMPROJ_REL",
    "LEGACY_MODEL_REL",
    "LLM_URL_ENV",
    "LOG_REL",
    "MMPROJ_ENV",
    "MMPROJ_REL",
    "MODEL_ENV",
    "MODEL_REL",
    "PORT_ENV",
    "SERVER_REL",
    "THREADS_ENV",
    "LlamaServerManager",
    "probe",
]
