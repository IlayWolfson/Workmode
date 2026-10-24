import tempfile
import unittest
from pathlib import Path

from focus_guard.muting import MuteStore


class MuteStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "mutes.json"

    def test_remember_keeps_the_first_state(self):
        store = MuteStore(self.path)
        store.remember("spotify.exe", False)
        store.remember("spotify.exe", True)
        self.assertEqual(MuteStore(self.path).load(), {"spotify.exe": False})

    def test_names_are_lower_cased(self):
        store = MuteStore(self.path)
        store.remember("Spotify.EXE", False)
        self.assertEqual(store.load(), {"spotify.exe": False})

    def test_corrupt_file_loads_empty(self):
        self.path.write_text("{nope", encoding="utf-8")
        self.assertEqual(MuteStore(self.path).load(), {})

    def test_non_boolean_values_are_skipped(self):
        self.path.write_text('{"a.exe": 1, "b.exe": true}', encoding="utf-8")
        self.assertEqual(MuteStore(self.path).load(), {"b.exe": True})

    def test_clear_removes_the_file(self):
        store = MuteStore(self.path)
        store.remember("spotify.exe", False)
        store.clear()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
