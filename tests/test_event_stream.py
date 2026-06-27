import queue
import threading
import unittest

import web.server as server


class BlockingDrainQueue(queue.Queue):
    def __init__(self, drain_started, allow_drain):
        super().__init__()
        self.drain_started = drain_started
        self.allow_drain = allow_drain
        self.blocked = False

    def get_nowait(self):
        if not self.blocked:
            self.blocked = True
            self.drain_started.set()
            if not self.allow_drain.wait(5):
                raise RuntimeError("event reset was not released")
        return super().get_nowait()


class ObservedEvents(dict):
    def __init__(self, *args, read=None, written=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.read = read
        self.written = written

    def get(self, key, default=None):
        if self.read:
            self.read.set()
        return super().get(key, default)

    def __setitem__(self, key, value):
        if self.written:
            self.written.set()
        return super().__setitem__(key, value)


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

    def test_subscription_waits_for_atomic_event_reset(self):
        drain_started = threading.Event()
        allow_drain = threading.Event()
        cache_read = threading.Event()
        stale_event = {"t": "proc", "state": "running"}
        existing = BlockingDrainQueue(drain_started, allow_drain)
        existing.put_nowait(stale_event)
        server._subscribers = {existing}
        server._last_events = ObservedEvents({"proc": stale_event}, read=cache_read)
        result = {}

        reset_thread = threading.Thread(
            target=server._reset_events, args=("proc", "state")
        )
        subscribe_thread = threading.Thread(
            target=lambda: result.setdefault("queue", server._subscribe_events())
        )
        reset_thread.start()
        self.assertTrue(drain_started.wait(2))
        subscribe_thread.start()
        read_during_reset = cache_read.wait(0.2)
        allow_drain.set()
        reset_thread.join(5)
        subscribe_thread.join(5)

        self.assertFalse(reset_thread.is_alive())
        self.assertFalse(subscribe_thread.is_alive())
        self.assertFalse(read_during_reset)
        with self.assertRaises(queue.Empty):
            result["queue"].get_nowait()

    def test_emit_waits_for_atomic_event_reset(self):
        drain_started = threading.Event()
        allow_drain = threading.Event()
        cache_written = threading.Event()
        stale_event = {"t": "proc", "state": "running"}
        fresh_event = {"t": "proc", "state": "done"}
        existing = BlockingDrainQueue(drain_started, allow_drain)
        existing.put_nowait(stale_event)
        server._subscribers = {existing}
        server._last_events = ObservedEvents(
            {"proc": stale_event}, written=cache_written
        )

        reset_thread = threading.Thread(
            target=server._reset_events, args=("proc", "state")
        )
        emit_thread = threading.Thread(
            target=server.emit, args=("proc",), kwargs={"state": "done"}
        )
        reset_thread.start()
        self.assertTrue(drain_started.wait(2))
        emit_thread.start()
        written_during_reset = cache_written.wait(0.2)
        allow_drain.set()
        reset_thread.join(5)
        emit_thread.join(5)

        self.assertFalse(reset_thread.is_alive())
        self.assertFalse(emit_thread.is_alive())
        self.assertFalse(written_during_reset)
        self.assertEqual(server._last_events["proc"], fresh_event)


if __name__ == "__main__":
    unittest.main()
