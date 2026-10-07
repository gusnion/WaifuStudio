"""Cliente API del engine ComfyUI con transporte inyectable (contrato M8-03)."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from app.config import EngineConfig, load_config

Transport = Callable[
    [str, str, "bytes | None", "dict[str, str] | None", float],
    "tuple[int, bytes]",
]

_NET_ERRORS = (urllib.error.URLError, OSError, socket.timeout, TimeoutError)


class EngineError(RuntimeError):
    """Fallo generico del cliente del engine."""


class JobCancelledError(EngineError):
    """Ejecucion cancelada o interrumpida en ComfyUI."""


class EngineRejected(EngineError):
    """Rechazo 4xx al enviar un grafo (submit)."""


class EngineTimeout(EngineError):
    """El prompt no termino antes de history_timeout_s."""


class ComfyEngine:
    """Cliente HTTP minimo de la API de ComfyUI, sin dependencias externas."""

    def __init__(
        self,
        config: EngineConfig | None = None,
        *,
        transport: Transport | None = None,
        client_id: str | None = None,
        timeout_s: float = 30.0,
        poll_s: float = 1.0,
        history_timeout_s: float = 1800.0,
    ) -> None:
        self.config = config if config is not None else load_config()
        self.base_url = str(self.config.comfy_url).rstrip("/")
        self.output_dir = Path(self.config.comfy_output_dir)
        self.client_id = client_id if client_id is not None else uuid.uuid4().hex
        self.timeout_s = float(timeout_s)
        self.poll_s = float(poll_s)
        self.history_timeout_s = float(history_timeout_s)
        self._transport = transport if transport is not None else self._urllib_transport

    def _urllib_transport(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes]:
        """Transporte por defecto: urllib contra base_url."""
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=body if body is not None else None,
        )
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(
                request, timeout=(timeout if timeout is not None else self.timeout_s)
            ) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except _NET_ERRORS as exc:
            raise EngineError(
                f"transporte fallo {method} {self.base_url}{path}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def submit(
        self,
        graph: dict,
        *,
        partial_execution_targets: list[str] | None = None,
    ) -> str:
        """POST /prompt: encola el grafo y devuelve el prompt_id."""
        payload: dict[str, Any] = {"prompt": graph, "client_id": self.client_id}
        if partial_execution_targets is not None:
            payload["partial_execution_targets"] = list(partial_execution_targets)
        body = json.dumps(payload).encode("utf-8")
        status, raw = self._transport(
            "POST", "/prompt", body, {"Content-Type": "application/json"}, self.timeout_s
        )
        if 200 <= status < 300:
            data = self._json(raw)
            prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
            if isinstance(prompt_id, str) and prompt_id.strip():
                return prompt_id
            raise EngineError(f"POST /prompt 2xx sin prompt_id valido: {raw[:300]!r}")
        if 400 <= status < 500:
            raise EngineRejected(
                f"POST /prompt rechazado (HTTP {status}): {self._error_detail(raw)}"
            )
        raise EngineError(f"POST /prompt responde HTTP {status}: {raw[:300]!r}")

    def history_entry(self, prompt_id: str) -> dict | None:
        """GET /history/<id>: entry terminada, o None si aun no existe (404/vacio)."""
        quoted = urllib.parse.quote(prompt_id, safe="")
        status, raw = self._transport(
            "GET", f"/history/{quoted}", None, None, self.timeout_s
        )
        if status == 404:
            return None
        if not (200 <= status < 300):
            raise EngineError(f"history {status} para {prompt_id}: {raw[:300]!r}")
        data = self._json(raw)
        entry = data.get(prompt_id) if isinstance(data, dict) else None
        return entry if isinstance(entry, dict) else None

    def wait(self, prompt_id: str) -> dict:
        """Sondea el history hasta success; error, cancelado o timeout lanzan EngineError."""
        deadline = time.monotonic() + self.history_timeout_s
        while True:
            try:
                entry = self.history_entry(prompt_id)
            except EngineError:
                entry = None
            if isinstance(entry, dict):
                status = entry.get("status")
                state = status.get("status_str") if isinstance(status, dict) else None
                if state == "success":
                    return entry
                if state == "cancelled":
                    raise JobCancelledError(self._execution_detail(entry))
                if state == "error":
                    raise EngineError(self._execution_detail(entry))
            if time.monotonic() >= deadline:
                raise EngineTimeout(
                    f"prompt {prompt_id} no termino en {self.history_timeout_s:.0f}s "
                    f"(poll={self.poll_s}s)"
                )
            time.sleep(self.poll_s)

    def queue_state(self, prompt_id: str) -> str:
        """'running' | 'pending' | 'absent': posicion del prompt en /queue."""
        status, raw = self._transport("GET", "/queue", None, None, self.timeout_s)
        if not (200 <= status < 300):
            raise EngineError(f"queue {status}: {raw[:300]!r}")
        data = self._json(raw)
        if not isinstance(data, dict):
            raise EngineError(f"queue sin objeto JSON: {raw[:120]!r}")
        for key, label in (("queue_running", "running"), ("queue_pending", "pending")):
            for item in data.get(key) or []:
                if (
                    isinstance(item, (list, tuple))
                    and len(item) > 1
                    and item[1] == prompt_id
                ):
                    return label
        return "absent"

    def delete_queued(self, prompt_id: str) -> bool:
        """POST /queue: borra el prompt de la cola; True si responde 2xx."""
        body = json.dumps({"delete": [prompt_id]}).encode("utf-8")
        status, _ = self._transport(
            "POST", "/queue", body, {"Content-Type": "application/json"}, self.timeout_s
        )
        return 200 <= status < 300

    def interrupt(self) -> bool:
        """POST /interrupt: cancela la ejecucion en curso; True si responde 2xx."""
        status, _ = self._transport("POST", "/interrupt", None, None, self.timeout_s)
        return 200 <= status < 300

    def outputs(
        self,
        entry: dict,
        *,
        node_id: str | None = None,
        expected_ext: tuple[str, ...] = ("png",),
    ) -> list[Path]:
        """Rutas confinadas de los items type=output, filtradas por extension."""
        nodes = entry.get("outputs") or {}
        if not isinstance(nodes, dict):
            return []
        selected = [node_id] if node_id is not None else list(nodes)
        wanted = tuple("." + str(ext).lstrip(".").lower() for ext in expected_ext)
        result: list[Path] = []
        for current in selected:
            node_outputs = nodes.get(current)
            if not isinstance(node_outputs, dict):
                continue
            for items in node_outputs.values():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict) or item.get("type") != "output":
                        continue
                    filename = item.get("filename")
                    if not isinstance(filename, str) or not filename:
                        raise EngineError(
                            f"output del nodo {current} sin filename valido: {item!r}"
                        )
                    subfolder = item.get("subfolder")
                    subfolder = subfolder if isinstance(subfolder, str) else ""
                    path = self._confine_output(subfolder, filename)
                    if path.suffix.lower() not in wanted:
                        continue
                    if not path.is_file():
                        raise EngineError(f"output reportado no existe: {path}")
                    result.append(path)
        return result

    def system_stats(self) -> dict:
        """GET /system_stats: estado del engine como dict."""
        status, raw = self._transport("GET", "/system_stats", None, None, self.timeout_s)
        if not (200 <= status < 300):
            raise EngineError(f"system_stats {status}: {raw[:300]!r}")
        data = self._json(raw)
        if not isinstance(data, dict):
            raise EngineError(f"system_stats sin objeto JSON: {raw[:120]!r}")
        return data

    def _confine_output(self, subfolder: str, filename: str) -> Path:
        if Path(filename).is_absolute():
            raise EngineError(f"output con filename absoluto: {filename!r}")
        relative = Path(subfolder) / filename if subfolder else Path(filename)
        root = self.output_dir.resolve()
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise EngineError(f"output fuera de output_dir: {relative!s}")
        return resolved

    @staticmethod
    def _json(raw: bytes) -> Any:
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return None

    @staticmethod
    def _error_detail(raw: bytes) -> str:
        text = raw[:300].decode("utf-8", "replace")
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return text
        if isinstance(data, dict):
            parts = []
            if data.get("error"):
                parts.append(f"error={data['error']}")
            if data.get("node_errors"):
                parts.append(f"node_errors={data['node_errors']}")
            if parts:
                return "; ".join(parts)[:300]
        return str(data)[:300]

    @staticmethod
    def _execution_detail(entry: dict) -> str:
        status = entry.get("status")
        messages = status.get("messages") if isinstance(status, dict) else None
        if messages:
            return f"prompt termino en error: {str(messages)[:300]}"
        return f"prompt termino en error: {str(entry)[:300]}"


def load_graph(path: str | Path) -> dict:
    """Carga un grafo API-format desde JSON UTF-8 y valida su forma basica."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"grafo ilegible {path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict) or not payload:
        raise EngineError(f"grafo invalido {path}: se esperaba dict no vacio")
    for node_id, node in payload.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            raise EngineError(
                f"grafo invalido {path}: nodo {node_id!r} sin class_type str"
            )
    return payload


__all__ = [
    "ComfyEngine",
    "EngineError",
    "EngineRejected",
    "EngineTimeout",
    "JobCancelledError",
    "load_graph",
]
