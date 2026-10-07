"""Tracker de progreso del engine por WebSocket, con hilo daemon propio (M9-A2)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import urllib.parse
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any, AsyncContextManager, Callable

WsFactory = Callable[[str], AsyncContextManager[AsyncIterable[Any]]]


@contextlib.asynccontextmanager
async def _aiohttp_ws_factory(url: str) -> AsyncIterator[Any]:
    """Factory por defecto: sesion aiohttp efimera contra ws_connect (import perezoso)."""
    import aiohttp

    session = aiohttp.ClientSession()
    try:
        async with session.ws_connect(url) as ws:
            yield ws
    finally:
        await session.close()


class ProgressTracker:
    """Sigue los mensajes WS de un prompt y publica step/total/node/state."""

    def __init__(
        self,
        base_ws_url: str,
        client_id: str,
        prompt_id: str,
        *,
        ws_factory: WsFactory | None = None,
        retry_s: float = 1.0,
    ) -> None:
        self.base_ws_url = str(base_ws_url)
        self.client_id = str(client_id)
        self.prompt_id = str(prompt_id)
        self.retry_s = float(retry_s)
        self._factory = ws_factory if ws_factory is not None else _aiohttp_ws_factory
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "step": None,
            "total": None,
            "node": None,
            "state": "unknown",
        }
        self._cancelled = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Arranca el hilo daemon con event loop propio; idempotente si ya vive."""
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"waifu-progress-{self.prompt_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Cierra el WS, cancela la tarea y une el hilo con timeout; idempotente."""
        self._stop_event.set()
        loop = self._loop
        task = self._task
        if loop is not None and task is not None and not task.done():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)

    def snapshot(self) -> dict:
        """Copia del estado actual con claves step/total/node/state."""
        with self._lock:
            return dict(self._state)

    @property
    def is_cancelled(self) -> bool:
        """True si la ejecucion fue cancelada o marcada como tal."""
        with self._lock:
            return self._cancelled or self._state.get("state") == "cancelled"

    @is_cancelled.setter
    def is_cancelled(self, value: bool) -> None:
        with self._lock:
            self._cancelled = bool(value)
            if self._cancelled:
                self._state["state"] = "cancelled"

    def percent(self) -> float | None:
        """Avance 0-100 redondeado a 2 decimales; None si falta step o total."""
        with self._lock:
            step = self._state["step"]
            total = self._state["total"]
        if not isinstance(step, (int, float)) or isinstance(step, bool):
            return None
        if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:
            return None
        return round(max(0.0, min(100.0, float(step) * 100.0 / float(total))), 2)

    def _ws_url(self) -> str:
        sep = "&" if "?" in self.base_ws_url else "?"
        quoted = urllib.parse.quote(self.client_id, safe="")
        return f"{self.base_ws_url}{sep}clientId={quoted}"

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._task = loop.create_task(self._listen())
            try:
                loop.run_until_complete(self._task)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        finally:
            self._task = None
            self._loop = None
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass
            loop.close()

    async def _listen(self) -> None:
        url = self._ws_url()
        for attempt in range(2):
            if self._stop_event.is_set():
                return
            try:
                async with self._factory(url) as ws:
                    await self._consume(ws)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                self._set_state("unknown")
            if attempt == 0:
                try:
                    await asyncio.sleep(self.retry_s)
                except asyncio.CancelledError:
                    raise

    async def _consume(self, ws: AsyncIterable[Any]) -> None:
        async for raw in ws:
            if self._stop_event.is_set():
                return
            message = self._decode(raw)
            if isinstance(message, dict):
                self._apply(message)

    @staticmethod
    def _decode(raw: Any) -> dict | None:
        """Normaliza dict, texto/bytes JSON o WSMessage a dict; None si no aplica."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode("utf-8", "replace")
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except ValueError:
                return None
            return data if isinstance(data, dict) else None
        data = getattr(raw, "data", None)
        if data is None or data is raw:
            return None
        return ProgressTracker._decode(data)

    def _apply(self, message: dict) -> None:
        msg_type = message.get("type")
        data = message.get("data")
        data = data if isinstance(data, dict) else {}
        pid = data.get("prompt_id")
        if pid is None:
            pid = message.get("prompt_id")
        if pid is not None and str(pid) != self.prompt_id:
            return
        with self._lock:
            if msg_type == "execution_start":
                self._state["state"] = "running"
            elif msg_type == "progress":
                value = data.get("value")
                maximum = data.get("max")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self._state["step"] = int(value)
                if isinstance(maximum, (int, float)) and not isinstance(maximum, bool):
                    self._state["total"] = int(maximum)
                self._state["state"] = "running"
            elif msg_type == "executing":
                node = data.get("node")
                if node is None:
                    self._state["state"] = "done"
                else:
                    self._state["node"] = node if isinstance(node, str) else str(node)
                    self._state["state"] = "running"
            elif msg_type == "execution_error":
                self._state["state"] = "error"

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state["state"] = state


__all__ = ["ProgressTracker"]
