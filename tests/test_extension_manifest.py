import json
import unittest
from pathlib import Path

from PIL import Image

EXTENSION = Path(__file__).resolve().parent.parent / "extension"


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    def test_icons_exist_in_every_size_chrome_shows(self):
        icons = self.manifest["icons"]
        self.assertEqual(sorted(icons, key=int), ["16", "32", "48", "128"])
        for size, name in icons.items():
            with self.subTest(size=size), Image.open(EXTENSION / name) as image:
                self.assertEqual(image.size, (int(size), int(size)))

    def test_name_and_description_say_workmode(self):
        self.assertEqual(self.manifest["name"], "Workmode")
        self.assertIn("Workmode", self.manifest["description"])
        self.assertNotIn("Focus Guard", self.manifest["description"])

    def test_toolbar_button_opens_the_update_popup(self):
        action = self.manifest["action"]
        self.assertEqual(action["default_popup"], "popup.html")
        self.assertTrue((EXTENSION / "popup.html").exists())
        for size, name in action["default_icon"].items():
            with self.subTest(size=size):
                self.assertEqual(name, self.manifest["icons"][size])

    def test_updating_needs_no_new_permission(self):
        self.assertEqual(self.manifest["permissions"], ["tabs", "webNavigation", "alarms", "storage"])
        self.assertEqual(self.manifest["host_permissions"], ["http://127.0.0.1/*", "https://www.youtube.com/*"])

    def test_version_equals_the_app_version(self):
        from focus_guard.version import VERSION

        self.assertEqual(self.manifest["version"], VERSION)


if __name__ == "__main__":
    unittest.main()
