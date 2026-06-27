import queue
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

from engine import project as project_mod
import web.server as server


class AliveThread:
    def is_alive(self):
        return True


class ProjectsApiTest(unittest.TestCase):
    """Exercises the project endpoints against a throwaway projects dir."""

    def setUp(self):
        self._orig_dir = project_mod.PROJECTS_DIR
        self._orig_project = server._project
        self._orig_process_thread = server._process_thread
        self._orig_plot_thread = server._plot_thread
        self._orig_subscribers = server._subscribers
        self._orig_last_events = server._last_events
        self._tmp = tempfile.TemporaryDirectory()
        project_mod.PROJECTS_DIR = Path(self._tmp.name)
        # Start on a fresh project inside the temp workspace.
        server._project = project_mod.create_project("Start")
        server._process_thread = None
        server._plot_thread = None
        server._subscribers = set()
        server._last_events = {}
        self.client = server.app.test_client()

    def tearDown(self):
        project_mod.PROJECTS_DIR = self._orig_dir
        server._project = self._orig_project
        server._process_thread = self._orig_process_thread
        server._plot_thread = self._orig_plot_thread
        server._subscribers = self._orig_subscribers
        server._last_events = self._orig_last_events
        self._tmp.cleanup()

    def test_create_open_rename_delete_flow(self):
        a = self.client.post("/api/projects", json={"name": "Alpha"}).get_json()
        self.assertEqual(a["current"]["name"], "Alpha")
        aid = a["current"]["id"]

        b = self.client.post("/api/projects", json={"name": "Beta"}).get_json()
        bid = b["current"]["id"]
        self.assertEqual(b["current"]["name"], "Beta")
        self.assertGreaterEqual(len(b["projects"]), 2)

        # Open Alpha again.
        opened = self.client.post(f"/api/projects/{aid}/open").get_json()
        self.assertEqual(opened["current"]["id"], aid)
        self.assertEqual(server._project.id, aid)

        # Rename current.
        renamed = self.client.patch(f"/api/projects/{aid}", json={"name": "Alpha2"}).get_json()
        self.assertEqual(renamed["current"]["name"], "Alpha2")

        # Delete current → switches to another existing project.
        deleted = self.client.delete(f"/api/projects/{aid}").get_json()
        self.assertNotEqual(deleted["current"]["id"], aid)
        ids = [p["id"] for p in deleted["projects"]]
        self.assertNotIn(aid, ids)
        self.assertIn(bid, ids)

    def test_open_unknown_project_404s(self):
        server._process_thread = AliveThread()
        self.assertEqual(self.client.post("/api/projects/nope/open").status_code, 404)

    def test_create_is_blocked_while_processing(self):
        current_id = server._project.id
        project_ids = [project["id"] for project in project_mod.list_projects()]
        server._process_thread = AliveThread()

        response = self.client.post("/api/projects", json={"name": "Blocked"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(server._project.id, current_id)
        self.assertEqual(
            [project["id"] for project in project_mod.list_projects()],
            project_ids,
        )

    def test_open_is_blocked_while_plotting(self):
        current_id = server._project.id
        target = project_mod.create_project("Target")
        server._plot_thread = AliveThread()

        response = self.client.post(f"/api/projects/{target.id}/open")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(server._project.id, current_id)

    def test_delete_current_is_blocked_while_processing(self):
        current_id = server._project.id
        project_file = project_mod.PROJECTS_DIR / current_id / "project.json"
        server._process_thread = AliveThread()

        response = self.client.delete(f"/api/projects/{current_id}")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(server._project.id, current_id)
        self.assertTrue(project_file.exists())

    def test_worker_start_waits_for_project_transition(self):
        transition_entered = Event()
        allow_transition = Event()
        worker_started = Event()
        real_create_project = project_mod.create_project
        responses = {}

        def blocking_create_project(name):
            transition_entered.set()
            if not allow_transition.wait(5):
                raise RuntimeError("project transition was not released")
            return real_create_project(name)

        class WorkerThread:
            def __init__(self, **kwargs):
                pass

            def start(self):
                worker_started.set()

            def is_alive(self):
                return True

        def create_project_request():
            with server.app.test_client() as client:
                responses["project"] = client.post(
                    "/api/projects", json={"name": "Next"}
                )

        def generate_request():
            generator_id = next(iter(server.GENERATORS))
            with server.app.test_client() as client:
                responses["generate"] = client.post(
                    "/api/generate", json={"generator_id": generator_id}
                )

        project_request = Thread(target=create_project_request)
        worker_request = Thread(target=generate_request)
        with (
            patch.object(project_mod, "create_project", side_effect=blocking_create_project),
            patch.object(server.threading, "Thread", WorkerThread),
        ):
            project_request.start()
            self.assertTrue(transition_entered.wait(2))
            worker_request.start()
            started_during_transition = worker_started.wait(0.2)
            allow_transition.set()
            project_request.join(5)
            worker_request.join(5)

        self.assertFalse(project_request.is_alive())
        self.assertFalse(worker_request.is_alive())
        self.assertFalse(started_during_transition)
        self.assertEqual(responses["project"].status_code, 200)
        self.assertEqual(responses["generate"].status_code, 200)

    def test_switch_resets_transient_state(self):
        server._current_svg = b"<svg/>"
        self.client.post("/api/projects", json={"name": "Fresh"})
        self.assertIsNone(server._current_svg)

    def test_switch_clears_transient_events(self):
        subscriber = server._subscribe_events()
        server.emit("proc", state="running")
        server.emit("state", state="drawing")

        self.client.post("/api/projects", json={"name": "Fresh"})

        self.assertEqual(server._last_events, {})
        with self.assertRaises(queue.Empty):
            subscriber.get_nowait()


if __name__ == "__main__":
    unittest.main()
