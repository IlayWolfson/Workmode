import tempfile
import unittest
from pathlib import Path

from focus_guard.leftovers import cleanup
from focus_guard.muting import MuteStore
from focus_guard.waiting import Placement, WaitingStore, WaitingWindow
from tests.test_guard import FakeActions, FakeAudio


class CleanupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.waiting, self.mutes = WaitingStore(self.dir / "waiting.json"), MuteStore(self.dir / "mutes.json")
        self.actions, self.audio = FakeActions(), FakeAudio()

    def test_cleanup_restores_windows_and_mutes_and_clears_both_stores(self):
        self.waiting.add(WaitingWindow(5, 50, "Steam.exe", Placement(1, (1, 2, 3, 4))))
        self.mutes.remember("spotify.exe", False)
        self.mutes.remember("discord.exe", True)
        cleanup(self.waiting, self.mutes, self.actions, self.audio)
        self.assertEqual(self.actions.calls, [("set_placement", 5, Placement(1, (1, 2, 3, 4)))])
        self.assertEqual(sorted(self.audio.calls), [("discord.exe", True), ("spotify.exe", False)])
        self.assertFalse((self.dir / "waiting.json").exists())
        self.assertFalse((self.dir / "mutes.json").exists())

    def test_cleanup_skips_windows_that_are_gone(self):
        self.waiting.add(WaitingWindow(5, 50, "Steam.exe", Placement(1, (1, 2, 3, 4))))
        self.waiting.add(WaitingWindow(6, 60, "Notepad.exe", Placement(3, (5, 6, 7, 8))))
        self.actions.placements[5] = None
        cleanup(self.waiting, self.mutes, self.actions, self.audio)
        self.assertEqual(self.actions.calls, [("set_placement", 6, Placement(3, (5, 6, 7, 8)))])

    def test_cleanup_skips_a_handle_now_owned_by_another_program(self):
        self.waiting.add(WaitingWindow(5, 50, "Steam.exe", Placement(1, (1, 2, 3, 4))))
        self.actions.pids[5] = 999
        cleanup(self.waiting, self.mutes, self.actions, self.audio)
        self.assertEqual(self.actions.calls, [])

    def test_one_failing_restore_does_not_stop_the_rest(self):
        self.waiting.add(WaitingWindow(5, 50, "Steam.exe", Placement(1, (1, 2, 3, 4))))
        self.mutes.remember("spotify.exe", False)
        errors = []

        def broken(hwnd, placement):
            raise OSError("denied")

        self.actions.set_placement = broken
        cleanup(self.waiting, self.mutes, self.actions, self.audio, on_error=errors.append)
        self.assertEqual(self.audio.calls, [("spotify.exe", False)])
        self.assertEqual(len(errors), 1)
        self.assertFalse((self.dir / "waiting.json").exists())


if __name__ == "__main__":
    unittest.main()
