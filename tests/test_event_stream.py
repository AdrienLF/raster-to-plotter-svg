import queue
import unittest

import web.server as server


class EventStreamTest(unittest.TestCase):
    def setUp(self):
        self.old_subscribers = server._subscribers
        self.old_last_events = server._last_events
        server._subscribers = set()
        server._last_events = {}

    def tearDown(self):
        server._subscribers = self.old_subscribers
        server._last_events = self.old_last_events

    def test_emit_broadcasts_to_each_subscriber_queue(self):
        first = server._subscribe_events()
        second = server._subscribe_events()

        server.emit("log", msg="hello")

        self.assertEqual(first.get_nowait()["msg"], "hello")
        self.assertEqual(second.get_nowait()["msg"], "hello")

    def test_new_stream_receives_latest_process_state(self):
        server.emit("proc", state="running", pfm="random_stipple")

        q = server._subscribe_events()

        evt = q.get_nowait()
        self.assertEqual(evt["t"], "proc")
        self.assertEqual(evt["state"], "running")
        self.assertEqual(evt["pfm"], "random_stipple")

    def test_unsubscribe_stops_delivery(self):
        q = server._subscribe_events()
        server._unsubscribe_events(q)

        server.emit("log", msg="ignored")

        with self.assertRaises(queue.Empty):
            q.get_nowait()


if __name__ == "__main__":
    unittest.main()
