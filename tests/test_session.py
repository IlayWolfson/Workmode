import tempfile
import unittest
from pathlib import Path

from focus_guard import session


class SessionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state" / "session.json"

    def test_start_then_load_round_trip(self):
        started = session.start_session(self.path, 25, True, now=1000.0)
        self.assertEqual((started.start, started.end, started.live), (1000.0, 2500.0, True))
        self.assertEqual(session.load_session(self.path, now=1100.0), started)

    def test_remaining_and_finished(self):
        started = session.Session(0.0, 60.0, False)
        self.assertEqual(started.remaining(45.0), 15.0)
        self.assertFalse(started.finished(59.9))
        self.assertTrue(started.finished(60.0))

    def test_finished_session_loads_as_none(self):
        session.start_session(self.path, 1, False, now=0.0)
        self.assertIsNone(session.load_session(self.path, now=61.0))

    def test_missing_corrupt_and_malformed_files_load_as_none(self):
        self.assertIsNone(session.load_session(self.path, now=0.0))
        self.path.parent.mkdir(parents=True)
        for payload in [
            "{nope",
            "[1]",
            '{"start": 1, "end": 2}',
            '{"start": "a", "end": 9, "live": true}',
            '{"start": 5, "end": 5, "live": true}',
        ]:
            with self.subTest(payload=payload):
                self.path.write_text(payload, encoding="utf-8")
                self.assertIsNone(session.load_session(self.path, now=0.0))

    def test_minutes_bounds(self):
        for bad in [0, -5, 721]:
            with self.subTest(minutes=bad):
                with self.assertRaises(ValueError):
                    session.start_session(self.path, bad, True, now=0.0)

    def test_clear_removes_the_file_and_is_idempotent(self):
        session.start_session(self.path, 5, True, now=0.0)
        session.clear_session(self.path)
        session.clear_session(self.path)
        self.assertFalse(self.path.exists())

    def test_occurrence_and_grace_round_trip(self):
        session.write_session(self.path, session.Session(100.0, 700.0, True, "ev1@2026-10-25", 0))
        loaded = session.load_session(self.path, now=200.0)
        self.assertEqual(loaded, session.Session(100.0, 700.0, True, "ev1@2026-10-25", 0))

    def test_old_file_without_new_fields_still_loads(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"start": 100, "end": 700, "live": false}', encoding="utf-8")
        self.assertEqual(session.load_session(self.path, now=200.0), session.Session(100.0, 700.0, False, "", None))

    def test_bad_grace_and_occurrence_are_ignored(self):  # a hand-broken value must not stop enforcement
        self.path.parent.mkdir(parents=True)
        for grace in ['"x"', "-1", "121", "true"]:
            with self.subTest(grace=grace):
                self.path.write_text(
                    f'{{"start": 100, "end": 700, "live": true, "grace": {grace}, "occurrence": 5}}', encoding="utf-8"
                )
                loaded = session.load_session(self.path, now=200.0)
                self.assertEqual((loaded.grace, loaded.occurrence), (None, ""))

    def test_clear_if_mine_leaves_a_newer_session_alone(self):
        mine = session.Session(100.0, 700.0, True, "a@2026-10-25")
        session.write_session(self.path, session.Session(700.0, 1300.0, True, "b@2026-10-25", 0))
        self.assertFalse(session.clear_session_if(self.path, mine))
        self.assertTrue(self.path.exists())
        session.write_session(self.path, mine)
        self.assertTrue(session.clear_session_if(self.path, mine))
        self.assertFalse(self.path.exists())
        session.clear_session_if(self.path, mine)  # missing file: nothing to do


if __name__ == "__main__":
    unittest.main()
