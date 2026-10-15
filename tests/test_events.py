import unittest
from unittest.mock import patch

from jarvis import events


class EventsTests(unittest.TestCase):
    def setUp(self):
        events.clear()

    def tearDown(self):
        events.clear()

    def test_emit_delivers_to_all_listeners(self):
        seen = []
        events.subscribe(seen.append)
        events.subscribe(lambda event: seen.append(event["type"]))

        events.emit({"type": "ping"})

        self.assertEqual(seen, [{"type": "ping"}, "ping"])

    def test_unsubscribe_stops_delivery(self):
        seen = []
        listener = events.subscribe(seen.append)
        events.unsubscribe(listener)

        events.emit({"type": "x"})

        self.assertEqual(seen, [])

    def test_listener_error_does_not_break_others(self):
        seen = []

        def bad(_event):
            raise RuntimeError("boom")

        events.subscribe(bad)
        events.subscribe(seen.append)

        with patch.object(events.logger, "exception"):
            events.emit({"type": "ok"})

        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
