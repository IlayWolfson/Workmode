import tempfile
import unittest
from pathlib import Path

from focus_guard.paths import Paths
from focus_guard.session import Session, load_session
from focus_guard.starting import begin_session


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


if __name__ == "__main__":
    unittest.main()
