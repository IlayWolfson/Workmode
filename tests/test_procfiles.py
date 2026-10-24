import tempfile
import unittest
from pathlib import Path

from focus_guard import procfiles


class PidFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state" / "guard.pid"

    def test_own_pid_is_alive_with_a_matching_marker(self):
        procfiles.write_pid(self.path)
        self.assertTrue(procfiles.pid_alive(self.path, "python"))

    def test_wrong_marker_means_a_different_program(self):
        procfiles.write_pid(self.path)
        self.assertFalse(procfiles.pid_alive(self.path, "definitely-not-this-program"))

    def test_stale_missing_and_corrupt_pid_files_are_not_alive(self):
        self.assertFalse(procfiles.pid_alive(self.path, "python"))
        self.path.parent.mkdir(parents=True)
        self.path.write_text("4000000", encoding="utf-8")
        self.assertFalse(procfiles.pid_alive(self.path, "python"))
        self.path.write_text("garbage", encoding="utf-8")
        self.assertFalse(procfiles.pid_alive(self.path, "python"))
        self.assertIsNone(procfiles.read_pid(self.path))

    def test_remove_is_idempotent(self):
        procfiles.write_pid(self.path)
        procfiles.remove_pid(self.path)
        procfiles.remove_pid(self.path)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
