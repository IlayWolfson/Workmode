import tempfile
import unittest
from pathlib import Path

from focus_guard.autostart import legacy_links, remove_legacy, startup_link, sync


class SyncTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.link = self.folder / "Workmode.lnk"
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
            Path("C:/Users/x/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/Workmode.lnk"),
        )

    def test_legacy_link_is_the_old_name_in_the_same_folder(self):
        links = legacy_links({"APPDATA": "C:/Users/x/AppData/Roaming"})
        self.assertEqual(
            links,
            [
                Path(
                    "C:/Users/x/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/"
                    "Hyperbolic Time Chamber.lnk"
                )
            ],
        )

    def test_remove_legacy_deletes_only_old_links_that_exist(self):
        old = self.folder / "Hyperbolic Time Chamber.lnk"
        old.write_bytes(b"lnk")
        missing = self.folder / "Gone.lnk"
        self.link.write_bytes(b"lnk")
        self.assertEqual(remove_legacy([old, missing], Path.unlink), [old])
        self.assertFalse(old.exists())
        self.assertTrue(self.link.exists())
        self.assertEqual(remove_legacy([old, missing], Path.unlink), [])


if __name__ == "__main__":
    unittest.main()
