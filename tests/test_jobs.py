"""Tests CPU de la cola 1-GPU (F3a). Sin red, GPU ni dependencias externas."""

from __future__ import annotations

import threading
import time
import unittest

from app.engine import EngineError
from app.jobs import JobQueue


class JobQueueTests(unittest.TestCase):
    def make_queue(self, run_job) -> JobQueue:
        queue = JobQueue(run_job)
        self.addCleanup(queue.stop)
        return queue

    def test_ids_unicos_y_hex(self):
        queue = self.make_queue(lambda job: None)

        ids = [queue.submit({}) for _ in range(5)]

        self.assertEqual(len(set(ids)), 5)
        for job_id in ids:
            self.assertRegex(job_id, r"^[0-9a-f]{32}$")

    def test_ejecuta_en_serie_en_orden_de_submit(self):
        events = []

        def run_job(job):
            events.append(("start", job["n"]))
            time.sleep(0.02)
            events.append(("end", job["n"]))

        queue = self.make_queue(run_job)
        queue.start()
        ids = [queue.submit({"n": n}) for n in range(3)]

        for job_id in ids:
            self.assertEqual(queue.wait(job_id, 5), "done")

        self.assertEqual(
            events,
            [
                ("start", 0),
                ("end", 0),
                ("start", 1),
                ("end", 1),
                ("start", 2),
                ("end", 2),
            ],
        )
        for job_id in ids:
            self.assertIsNone(queue.result(job_id))

    def test_error_aislado_no_mata_al_worker(self):
        done = []

        def run_job(job):
            if job.get("fail"):
                raise ValueError("boom")
            done.append(job["ok"])

        queue = self.make_queue(run_job)
        queue.start()
        bad = queue.submit({"fail": True})
        good = queue.submit({"ok": 7})

        self.assertEqual(queue.wait(bad, 5), "error")
        self.assertEqual(queue.wait(good, 5), "done")
        error = queue.result(bad)
        self.assertIsInstance(error, ValueError)
        self.assertIn("boom", str(error))
        self.assertIsNone(queue.result(good))
        self.assertEqual(done, [7])

        after = queue.submit({"ok": 8})
        self.assertEqual(queue.wait(after, 5), "done")
        self.assertEqual(done, [7, 8])

    def test_id_desconocido_lanza_engine_error(self):
        queue = self.make_queue(lambda job: None)

        with self.assertRaises(EngineError):
            queue.status("no-existe")
        with self.assertRaises(EngineError):
            queue.result("no-existe")
        with self.assertRaises(EngineError):
            queue.wait("no-existe", 0.01)

    def test_wait_timeout_devuelve_estado_actual(self):
        release = threading.Event()
        running = threading.Event()

        def run_job(job):
            running.set()
            release.wait(5)

        queue = self.make_queue(run_job)
        queued = queue.submit({})

        self.assertEqual(queue.wait(queued, 0.02), "queued")

        queue.start()
        self.assertTrue(running.wait(5))
        self.assertEqual(queue.status(queued), "running")
        self.assertEqual(queue.wait(queued, 0.02), "running")
        self.assertIsNone(queue.result(queued))

        release.set()
        self.assertEqual(queue.wait(queued, 5), "done")

    def test_start_stop_idempotentes(self):
        queue = JobQueue(lambda job: None)
        self.addCleanup(queue.stop)

        queue.stop()
        queue.start()
        queue.start()
        workers = [t for t in threading.enumerate() if t.name == "waifu-job-queue"]
        self.assertEqual(len(workers), 1)

        self.assertEqual(queue.wait(queue.submit({}), 5), "done")
        queue.stop()
        queue.stop()
        self.assertFalse(
            any(t.name == "waifu-job-queue" for t in threading.enumerate())
        )

        queue.start()
        self.assertEqual(queue.wait(queue.submit({}), 5), "done")

    def test_stop_drena_la_cola(self):
        seen = []

        def run_job(job):
            seen.append(job["n"])

        queue = self.make_queue(run_job)
        ids = [queue.submit({"n": n}) for n in range(3)]

        queue.start()
        queue.stop()

        self.assertEqual(seen, [0, 1, 2])
        for job_id in ids:
            self.assertEqual(queue.status(job_id), "done")


if __name__ == "__main__":
    unittest.main()
