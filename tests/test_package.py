import json
import tempfile
import unittest
from pathlib import Path

from focus_guard.install import localize_video
from tools.build_package import host_config, package_files


class LocalizeVideoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "media").mkdir()
        self.config = self.root / "config.json"

    def write(self, path):
        self.config.write_text(json.dumps({"video": {"path": path}, "other": 1}), encoding="utf-8")

    def read(self):
        return json.loads(self.config.read_text(encoding="utf-8"))

    def test_points_the_video_at_the_bundled_copy(self):
        (self.root / "media" / "clip.mp4").write_bytes(b"x")
        self.write("C:/Users/Old/Desktop/clip.mp4")
        self.assertTrue(localize_video(self.config, self.root / "media"))
        data = self.read()
        self.assertEqual(Path(data["video"]["path"]), self.root / "media" / "clip.mp4")
        self.assertEqual(data["other"], 1)

    def test_leaves_the_config_alone_without_a_bundled_copy(self):
        self.write("C:/Users/Old/Desktop/clip.mp4")
        self.assertFalse(localize_video(self.config, self.root / "media"))
        self.assertEqual(self.read()["video"]["path"], "C:/Users/Old/Desktop/clip.mp4")


class HostConfigTest(unittest.TestCase):
    def test_host_config_keeps_the_settings_and_swaps_the_apps_without_mutating_the_input(self):
        original = {
            "allowed_sites": ["a.com"],
            "emergency": {"phrase": "p"},
            "allowed_apps": [{"process": "Claude.exe", "launch": ["x"]}],
        }
        result = host_config(original, "My VM")
        self.assertEqual(original["allowed_apps"][0]["process"], "Claude.exe")
        self.assertEqual(result["allowed_sites"], ["a.com"])
        self.assertEqual(result["emergency"], {"phrase": "p"})
        processes = [app["process"] for app in result["allowed_apps"]]
        self.assertEqual(processes, ["chrome.exe", "WindowsTerminal.exe", "vmconnect.exe", "mmc.exe"])
        vm = result["allowed_apps"][2]["launch"]
        self.assertEqual(vm[-2:], ["localhost", "My VM"])

    def test_host_config_keeps_youtube(self):
        youtube = {"channels": ["@3blue1brown"], "playlists": ["PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi"]}
        original = {"allowed_apps": [], "youtube": youtube}
        self.assertEqual(host_config(original, "My VM")["youtube"], youtube)


class PackageFilesTest(unittest.TestCase):
    def test_selects_the_tool_and_skips_state_and_caches(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in [
                "focus_guard/a.py",
                "focus_guard/__pycache__/a.pyc",
                "state/session.json",
                "extension/config.js",
                "config.json",
                ".git/HEAD",
                "dist/old.zip",
                ".superpowers/x.md",
                "README.md",
                "assets/focus_guard.ico",
            ]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            chosen = {item.relative_to(root).as_posix() for item in package_files(root)}
        self.assertEqual(
            chosen,
            {"focus_guard/a.py", "extension/config.js", "config.json", "README.md", "assets/focus_guard.ico"},
        )

    def test_skips_private_notes_and_tool_caches(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in [
                "docs/manual-test.md",
                "docs/HANDOFF.md",
                "docs/argon-briefing.md",
                "docs/song-candidates.md",
                "docs/google-calendar-setup.md",
                "docs/superpowers/plans/2026-10-24-x.md",
                "docs/superpowers/specs/design.md",
                ".mypy_cache/x.json",
                ".ruff_cache/x",
                "leakscan.local.txt",
            ]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            chosen = {item.relative_to(root).as_posix() for item in package_files(root)}
        self.assertEqual(chosen, {"docs/superpowers/specs/design.md"})

    def test_the_real_package_ships_the_windows_pages_songs_and_nerd_picture(self):
        root = Path(__file__).resolve().parent.parent
        chosen = {item.relative_to(root).as_posix() for item in package_files(root)}
        for needed in [
            "focus_guard/web/main.html",
            "focus_guard/web/main.js",
            "focus_guard/web/notify.html",
            "focus_guard/web/common.css",
            "assets/songs/bards-tale.mp3",
            "assets/songs/kings-feast.mp3",
            "assets/songs/minstrel-dance.mp3",
            "assets/songs/LICENSES.md",
            "assets/nerd.jpg",
        ]:
            with self.subTest(file=needed):
                self.assertIn(needed, chosen)
        self.assertFalse(any(name.startswith("state/") for name in chosen))

    def test_package_ships_fullcalendar(self):
        root = Path(__file__).resolve().parent.parent
        chosen = {item.relative_to(root).as_posix() for item in package_files(root)}
        for needed in [
            "focus_guard/web/vendor/fullcalendar/index.global.min.js",
            "focus_guard/web/vendor/fullcalendar/he.global.min.js",
            "focus_guard/web/vendor/fullcalendar/LICENSE.md",
            "focus_guard/web/calmodel.js",
            "focus_guard/web/calendar.js",
            "focus_guard/web/eventform.js",
            "focus_guard/web/eventcard.js",
            "focus_guard/web/settings.js",
            "focus_guard/web/calendar.css",
        ]:
            with self.subTest(file=needed):
                self.assertIn(needed, chosen)


if __name__ == "__main__":
    unittest.main()
