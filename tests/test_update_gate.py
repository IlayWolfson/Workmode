import tempfile
import unittest
from datetime import UTC
from pathlib import Path

from focus_guard.events import Occurrence
from focus_guard.outcomes import OutcomeStore
from focus_guard.paths import Paths
from focus_guard.session import Session, write_session
from focus_guard.update_gate import SOON, refusal

NOW = 1_800_000_000.0  # 2027-01-15 08:00 UTC


def planned(start: float, end: float, key: str = "e1@2027-01-15") -> Occurrence:
    return Occurrence(key, "Work", start, end, live=True, cue=False)


class RefusalTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = Paths(folder.name)
        self.paths.state.mkdir()
        self.guard = False
        self.upcoming: list[Occurrence] = []

    def ask(self, now=NOW):
        return refusal(self.paths, now, lambda: self.guard, lambda _: self.upcoming, tz=UTC)

    def test_nothing_running_allows(self):
        self.assertIsNone(self.ask())

    def test_active_session_refused_with_its_end_time(self):
        write_session(self.paths.session, Session(NOW - 600, NOW + 3600, live=True))
        self.assertEqual(self.ask(), "יש סשן פעיל עד 09:00; העדכון יחכה")

    def test_stale_session_past_end_allowed(self):
        write_session(self.paths.session, Session(NOW - 7200, NOW - 60, live=True))
        self.assertIsNone(self.ask())

    def test_guard_alive_refused(self):
        self.guard = True
        self.assertIn("סשן פעיל", self.ask())

    def test_planned_session_in_9_minutes_refused(self):
        self.upcoming = [planned(NOW + 9 * 60, NOW + 3600)]
        self.assertIn("08:09", self.ask())

    def test_planned_session_in_11_minutes_allowed(self):
        self.upcoming = [planned(NOW + 11 * 60, NOW + 3600)]
        self.assertIsNone(self.ask())

    def test_planned_session_exactly_at_the_limit_refused(self):
        self.upcoming = [planned(NOW + SOON, NOW + 3600)]
        self.assertIsNotNone(self.ask())

    def test_planned_session_now_running_but_not_started_refused(self):
        self.upcoming = [planned(NOW - 60, NOW + 3600)]
        self.assertIsNotNone(self.ask())

    def test_declined_occurrence_does_not_block(self):
        self.upcoming = [planned(NOW + 5 * 60, NOW + 3600)]
        OutcomeStore(self.paths.outcomes).record("e1@2027-01-15", "declined")
        self.assertIsNone(self.ask())

    def test_finished_planned_session_does_not_block(self):
        self.upcoming = [planned(NOW - 7200, NOW - 60)]
        self.assertIsNone(self.ask())

    def test_git_clone_refused_first(self):
        (Path(self.paths.root) / ".git").mkdir()
        self.guard = True
        self.assertIn("git pull", self.ask())


if __name__ == "__main__":
    unittest.main()
