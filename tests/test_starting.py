import tempfile
import unittest
from pathlib import Path

from focus_guard.jsonfile import write_json
from focus_guard.paths import Paths
from focus_guard.session import Session, load_session
from focus_guard.starting import UpdateInProgress, begin_session
from focus_guard.update_apply import UPDATE_MUTEX
from tests.update_fixtures import UNFINISHED


class BeginSessionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = Paths(Path(tmp.name))

    def test_begin_session_undoes_leftovers_writes_and_spawns_both(self):
        self.paths.state.mkdir()
        self.paths.mute_request.touch()
        spawned: list[str] = []
        begin_session(self.paths, Session(10.0, 70.0, False, "e@2026-10-25"), spawned.append)
        self.assertEqual(spawned, ["focus_guard.run_guard", "focus_guard.run_guardian"])
        self.assertEqual(load_session(self.paths.session, 20.0).occurrence, "e@2026-10-25")
        self.assertFalse(self.paths.mute_request.exists())

    def test_begin_session_refused_while_update_mutex_held(self):
        spawned: list[str] = []
        with self.assertRaises(UpdateInProgress):
            begin_session(self.paths, Session(10.0, 70.0, True), spawned.append, claim=lambda name: None)
        self.assertFalse(self.paths.session.exists())
        self.assertEqual(spawned, [])

    def test_begin_session_refused_while_applying(self):
        write_json(self.paths.update_journal, UNFINISHED)
        spawned: list[str] = []
        released: list[object] = []
        with self.assertRaises(UpdateInProgress):
            begin_session(
                self.paths,
                Session(10.0, 70.0, True),
                spawned.append,
                claim=lambda name: "h",
                release_handle=released.append,
            )
        self.assertFalse(self.paths.session.exists())
        self.assertEqual(spawned, [])
        self.assertEqual(released, ["h"])

    def test_begin_session_takes_and_releases_the_update_mutex(self):
        claimed: list[str] = []
        released: list[object] = []

        def claim(name):
            claimed.append(name)
            return "h"

        begin_session(
            self.paths, Session(10.0, 70.0, False), lambda module: None, claim=claim, release_handle=released.append
        )
        self.assertEqual(claimed, [UPDATE_MUTEX])
        self.assertEqual(released, ["h"])

    def test_refusal_is_a_value_error_the_window_can_show(self):
        self.assertTrue(issubclass(UpdateInProgress, ValueError))


if __name__ == "__main__":
    unittest.main()
