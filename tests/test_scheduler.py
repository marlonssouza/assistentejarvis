import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from jarvis import scheduler


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._file = Path(self._tmp.name) / "scheduler.json"
        self._orig_file = scheduler.SCHEDULER_FILE
        self._orig_tasks = list(scheduler._tasks)
        scheduler.SCHEDULER_FILE = self._file
        scheduler._tasks = []

    def tearDown(self):
        scheduler.SCHEDULER_FILE = self._orig_file
        scheduler._tasks = self._orig_tasks
        scheduler.stop()
        self._tmp.cleanup()

    def test_schedule_with_relative_minutes(self):
        task = scheduler.schedule_task(name="teste", when="in 15")
        self.assertEqual(task["name"], "teste")
        self.assertEqual(len(scheduler.list_scheduled()), 1)
        run_at = datetime.fromisoformat(task["run_at"])
        self.assertGreater(run_at, datetime.now())

    def test_schedule_with_clock_time_rolls_to_next_day(self):
        task = scheduler.schedule_task(name="diario", when="00:01", repeat="daily")
        self.assertEqual(task["repeat"], "daily")
        run_at = datetime.fromisoformat(task["run_at"])
        self.assertGreater(run_at, datetime.now() - timedelta(minutes=1))

    def test_invalid_when_raises(self):
        with self.assertRaises(ValueError):
            scheduler.schedule_task(name="x", when="amanhã talvez")

    def test_cancel_task(self):
        task = scheduler.schedule_task(name="cancelar", when="in 5")
        self.assertTrue(scheduler.cancel_task(task["id"]))
        self.assertEqual(scheduler.list_scheduled(), [])
        self.assertFalse(scheduler.cancel_task("inexistente"))

    def test_persistence_roundtrip(self):
        scheduler.schedule_task(name="persistir", when="in 30")
        raw = json.loads(self._file.read_text(encoding="utf-8"))
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["name"], "persistir")

    def test_callback_registered_and_dispatchable(self):
        fired = []
        scheduler.register_callback("reminder", lambda task: fired.append(task))
        task = scheduler.schedule_task(name="alarme", when="in 1", kind="reminder")
        scheduler._fire(task)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["name"], "alarme")

    def test_unknown_kind_does_not_raise(self):
        with patch.object(scheduler.logger, "info"):
            scheduler._fire({"name": "x", "kind": "nao_existe", "payload": {}})


if __name__ == "__main__":
    unittest.main()
