import tempfile
import unittest
from pathlib import Path

from focus_guard.waiting import Placement, WaitingStore, WaitingWindow


class WaitingStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_add_load_remove_clear_round_trip(self):
        store = WaitingStore(self.dir / "waiting.json")
        first = WaitingWindow(7, 70, "Steam.exe", Placement(1, (10, 20, 300, 400)))
        store.add(first)
        self.assertEqual(WaitingStore(self.dir / "waiting.json").load(), {7: first})
        store.remove(7)
        self.assertEqual(store.load(), {})
        store.add(first)
        store.clear()
        self.assertFalse((self.dir / "waiting.json").exists())

    def test_second_add_keeps_the_original_placement(self):
        store = WaitingStore(self.dir / "waiting.json")
        store.add(WaitingWindow(7, 70, "Steam.exe", Placement(1, (10, 20, 300, 400))))
        store.add(WaitingWindow(7, 70, "Steam.exe", Placement(2, (0, 0, 1, 1))))
        self.assertEqual(store.load()[7].placement, Placement(1, (10, 20, 300, 400)))

    def test_corrupt_file_loads_empty(self):
        (self.dir / "waiting.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(WaitingStore(self.dir / "waiting.json").load(), {})

    def test_malformed_entries_are_skipped(self):
        (self.dir / "waiting.json").write_text(
            '{"windows": [{"hwnd": "x"}, {"hwnd": 7, "pid": 70, "process": "Steam.exe",'
            ' "show_cmd": 1, "normal_rect": [10, 20, 300, 400]}]}',
            encoding="utf-8",
        )
        self.assertEqual(list(WaitingStore(self.dir / "waiting.json").load()), [7])


if __name__ == "__main__":
    unittest.main()
