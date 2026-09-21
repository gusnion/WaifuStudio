"""Cola 1-GPU de trabajos en serie (F3a).

Un unico hilo daemon ejecuta los jobs en el orden de submit: el engine es
single-GPU y no admite concurrencia. Una excepcion en un job pasa a estado
``error`` sin matar al worker. Solo stdlib; sin red ni GPU.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from typing import Any, Callable

from app.engine import EngineError

_STOP = object()
_FINISHED = ("done", "error")


class JobQueue:
    """Cola FIFO con un worker daemon y estado por job."""

    def __init__(self, run_job: Callable[[dict], None]) -> None:
        if not callable(run_job):
            raise EngineError("JobQueue requiere un run_job invocable")
        self._run_job = run_job
        self._queue: queue.Queue = queue.Queue()
        self._condition = threading.Condition()
        self._records: dict[str, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None

    def submit(self, job: dict) -> str:
        """Encola ``job`` y devuelve su id ``uuid4().hex``; el worker va en orden."""
        job_id = uuid.uuid4().hex
        with self._condition:
            self._records[job_id] = {"job": job, "status": "queued", "error": None}
            self._queue.put(job_id)
            self._condition.notify_all()
        return job_id

    def status(self, job_id: str) -> str:
        """``queued`` | ``running`` | ``done`` | ``error``; EngineError si no existe."""
        with self._condition:
            return self._record(job_id)["status"]

    def result(self, job_id: str) -> BaseException | None:
        """Excepcion guardada del job o None; EngineError si el id no existe."""
        with self._condition:
            return self._record(job_id)["error"]

    def wait(self, job_id: str, timeout: float | None = None) -> str:
        """Espera al estado final y lo devuelve; al agotar ``timeout`` da el actual."""
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        with self._condition:
            record = self._record(job_id)
            while record["status"] not in _FINISHED:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return record["status"]

    def start(self) -> None:
        """Arranca el worker si no esta vivo; idempotente."""
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker, name="waifu-job-queue", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        """Marca el final y espera a que el worker drene la cola; idempotente."""
        with self._condition:
            thread = self._thread
            if thread is None or not thread.is_alive():
                self._thread = None
                return
        self._queue.put(_STOP)
        if thread is not threading.current_thread():
            thread.join()
        with self._condition:
            if self._thread is thread:
                self._thread = None

    def _record(self, job_id: str) -> dict:
        record = self._records.get(job_id)
        if record is None:
            raise EngineError(f"job desconocido: {job_id!r}")
        return record

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is _STOP:
                return
            with self._condition:
                record = self._records.get(job_id)
                if record is None or record["status"] != "queued":
                    self._condition.notify_all()
                    continue
                record["status"] = "running"
                job = record["job"]
                self._condition.notify_all()
            try:
                self._run_job(job)
            except BaseException as exc:
                with self._condition:
                    record["status"] = "error"
                    record["error"] = exc
                    self._condition.notify_all()
            else:
                with self._condition:
                    record["status"] = "done"
                    record["error"] = None
                    self._condition.notify_all()


__all__ = ["JobQueue"]
