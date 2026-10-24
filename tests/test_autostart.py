import tempfile
import unittest
from pathlib import Path

from focus_guard.autostart import startup_link, sync


class SyncTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.link = Path(tmp.name) / "Hyperbolic Time Chamber.lnk"
        self.made = []

    def make(self):
        self.made.append(1)
        self.link.write_bytes(b"lnk")

    def test_sync_creates_removes_and_noops(self):
        self.assertEqual(sync(True, self.link, self.make, Path.unlink), "created")
        self.assertTrue(self.link.exists())
        self.assertEqual(sync(True, self.link, self.make, Path.unlink), "created")  # remade: a moved folder is fixed
        self.assertEqual(len(self.made), 2)
        self.assertEqual(sync(False, self.link, self.make, Path.unlink), "removed")
        self.assertFalse(self.link.exists())
        self.assertEqual(sync(False, self.link, self.make, Path.unlink), "none")
        self.assertEqual(len(self.made), 2)

    def test_startup_link_is_in_the_users_startup_folder(self):
        link = startup_link({"APPDATA": "C:/Users/x/AppData/Roaming"})
        self.assertEqual(
            link,
            Path(
                "C:/Users/x/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/Hyperbolic Time Chamber.lnk"
            ),
        )


if __name__ == "__main__":
    unittest.main()
