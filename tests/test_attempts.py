import tempfile
import unittest
from pathlib import Path

from focus_guard.attempts import AttemptLog


class AttemptLogTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "attempts.log"
        self.log = AttemptLog(self.path)

    def test_round_trip_keeps_hebrew_detail(self):
        self.log.record("closed", "חלון עבודה.exe", now=100)
        entry = self.log.read()[0]
        self.assertEqual((entry["type"], entry["detail"]), ("closed", "חלון עבודה.exe"))

    def test_detail_is_truncated(self):
        self.log.record("blocked_app", "x" * 500, now=100)
        self.assertEqual(len(self.log.read()[0]["detail"]), 80)

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            self.log.record("whatever", "")

    def test_missing_file_reads_empty_and_corrupt_lines_are_skipped(self):
        self.assertEqual(self.log.read(), [])
        self.log.record("closed", "a.exe", now=100)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("{broken\n")
        self.log.record("closed", "b.exe", now=101)
        self.assertEqual([entry["detail"] for entry in self.log.read()], ["a.exe", "b.exe"])

    def test_count_since_counts_only_attempts_after_the_cutoff(self):
        self.log.record("session_start", "", now=50)
        self.log.record("closed", "a.exe", now=100)
        self.log.record("closed", "a.exe", now=200)
        self.log.record("minimized", "chrome.exe", now=300)
        self.log.record("emergency_exit", "", now=310)
        self.assertEqual(self.log.count_since(150), {"closed": 1, "minimized": 1})


if __name__ == "__main__":
    unittest.main()
