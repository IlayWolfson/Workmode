import tempfile
import unittest
from datetime import date
from pathlib import Path

from focus_guard.outcomes import OutcomeStore


class OutcomeStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state" / "outcomes.json"
        self.today = date(2026, 10, 25)
        self.store = OutcomeStore(self.path, today=lambda: self.today)

    def test_record_then_load_round_trip(self):
        self.store.record("e1@2026-10-25", "declined")
        self.store.record("e2@2026-10-26", "completed")
        self.assertEqual(OutcomeStore(self.path).load(), {"e1@2026-10-25": "declined", "e2@2026-10-26": "completed"})

    def test_unknown_outcome_is_refused(self):
        with self.assertRaises(ValueError):
            self.store.record("e1@2026-10-25", "maybe")

    def test_outcome_store_drops_entries_older_than_60_days(self):
        self.store.record("old@2026-08-25", "declined")  # 61 days before
        self.store.record("kept@2026-08-26", "declined")  # 60 days before
        self.store.record("new@2026-10-25", "exited")
        self.assertEqual(set(self.store.load()), {"kept@2026-08-26", "new@2026-10-25"})

    def test_missing_corrupt_and_malformed_files_load_empty(self):
        self.assertEqual(self.store.load(), {})
        self.path.parent.mkdir(parents=True)
        for payload in ["{nope", "[1]", '{"a@2026-10-25": 5, "b@2026-10-25": "nonsense"}']:
            with self.subTest(payload=payload):
                self.path.write_text(payload, encoding="utf-8")
                self.assertEqual(self.store.load(), {})


if __name__ == "__main__":
    unittest.main()
