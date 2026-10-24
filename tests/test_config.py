import tempfile
import unittest
from pathlib import Path
from unittest import mock

from focus_guard.config import (
    ConfigError,
    hint_text,
    load_config,
    load_config_safe,
    unresolved_launches,
    word_site_ok,
)
from tests.helpers import base_config, write_config


class ConfigCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.video = self.dir / "clip.mp4"
        self.video.write_bytes(b"x")
        self.data = base_config(self.video)

    def load(self):
        return load_config(write_config(self.dir, self.data))

    def assertRejected(self, fragment):
        with self.assertRaises(ConfigError) as context:
            self.load()
        self.assertIn(fragment, str(context.exception))


class ValidConfigTest(ConfigCase):
    def test_loads_and_applies_defaults(self):
        cfg = self.load()
        self.assertEqual([app.process for app in cfg.allowed_apps], ["code.exe", "chrome.exe"])
        self.assertEqual(cfg.allowed_apps[0].launch, ("code", "C:/project"))
        self.assertEqual(cfg.popup_seconds, 10)
        self.assertEqual(cfg.hold_ms, 1500)
        self.assertEqual(cfg.hold_chords, ((0x2E,), (0x21,), (0x22,)))
        self.assertEqual(cfg.hotkey_chords, ((0x11, 0x12, 0x10, 0x51),))
        self.assertEqual((cfg.roast_stock, cfg.roast_refill_at, cfg.roast_max_words), (10, 3, 12))
        self.assertEqual(cfg.roast_model, "gemini-flash-latest")
        self.assertEqual(cfg.video_path, str(self.video))
        self.assertIn("explorer.exe", cfg.protected_processes)

    def test_user_protected_processes_are_added_lowercase(self):
        self.data["protected_processes"] = ["MyTool.EXE"]
        cfg = self.load()
        self.assertIn("mytool.exe", cfg.protected_processes)
        self.assertIn("explorer.exe", cfg.protected_processes)

    def test_site_names_are_lowercased(self):
        self.data["allowed_sites"] = ["GitHub.com"]
        self.assertEqual(self.load().allowed_sites, ("github.com",))

    def test_missing_video_file_falls_back_to_https_url(self):
        self.data["video"] = {"path": str(self.dir / "gone.mp4"), "fallback_url": "https://example.com/v"}
        cfg = self.load()
        self.assertEqual(cfg.video_path, "")
        self.assertEqual(cfg.video_fallback_url, "https://example.com/v")

    def test_grace_seconds_defaults_to_20_and_is_validated(self):
        self.assertEqual(self.load().grace_seconds, 20)
        self.data["grace_seconds"] = 0
        self.assertEqual(self.load().grace_seconds, 0)
        for bad in [-1, 121, "20", True]:
            with self.subTest(value=bad):
                self.data["grace_seconds"] = bad
                self.assertRejected("grace_seconds")

    def test_new_keys_have_defaults_and_are_validated(self):
        self.assertTrue(self.load().start_with_windows)
        self.assertEqual(self.load().songs, ())
        self.data["songs"] = ["C:/music/a.mp3", "chime.wav"]
        self.assertEqual(self.load().songs, ("C:/music/a.mp3", "chime.wav"))
        for key, bad in [("start_with_windows", "yes"), ("songs", "a.mp3"), ("songs", [3]), ("songs", [""])]:
            with self.subTest(key=key, value=bad):
                self.data[key] = bad
                self.assertRejected(key)
            self.data.pop(key)

    def test_window_percent_default_and_validated(self):
        self.assertEqual(self.load().window_percent, 85)
        self.data["window_percent"] = 70
        self.assertEqual(self.load().window_percent, 70)
        for bad in [49, 101, "85", True]:
            with self.subTest(value=bad):
                self.data["window_percent"] = bad
                self.assertRejected("window_percent")

    def test_song_files_default_and_validated(self):
        self.assertEqual(self.load().song_files, ())
        self.data["song_files"] = ["C:/music/a.mp3"]
        self.assertEqual(self.load().song_files, ("C:/music/a.mp3",))
        for bad in ["a.mp3", [3], [""]]:
            with self.subTest(value=bad):
                self.data["song_files"] = bad
                self.assertRejected("song_files")

    def test_hint_text_lists_every_shortcut(self):
        self.assertEqual(
            hint_text(self.load()),
            "יציאת חירום: להחזיק Del / PgUp / PgDn, או Ctrl+Alt+Shift+Q",
        )


class RejectedConfigTest(ConfigCase):
    def test_invalid_json(self):
        (self.dir / "config.json").write_text("{nope", encoding="utf-8")
        with self.assertRaises(ConfigError) as context:
            load_config(self.dir / "config.json")
        self.assertIn("cannot read config", str(context.exception))

    def test_unknown_keys(self):
        self.data["extra"] = 1
        self.assertRejected("unknown")
        del self.data["extra"]
        self.data["video"]["colour"] = "red"
        self.assertRejected("unknown")

    def test_allowed_apps_rules(self):
        self.data["allowed_apps"] = []
        self.assertRejected("allowed_apps")
        self.data["allowed_apps"] = [{"process": "Code.exe"}]
        self.assertRejected("launch")
        self.data["allowed_apps"] = [{"process": "Code", "launch": ["code"]}]
        self.assertRejected("process")
        self.data["allowed_apps"] = [{"process": "Code.exe", "launch": ["code"], "x": 1}]
        self.assertRejected("each allowed app")

    def test_site_rules(self):
        for bad in ["https://github.com", "not a domain", "localhost", ""]:
            with self.subTest(site=bad):
                self.data["allowed_sites"] = [bad]
                self.assertRejected("allowed_sites")

    def test_starred_word_sites(self):
        self.data["allowed_sites"] = ["*PortFolio*", "github.com"]
        self.assertEqual(self.load().allowed_sites, ("*portfolio*", "github.com"))
        for bad in ["*a*", "*port folio*", "*portfolio", "portfolio*", "**", "*.com*"]:
            with self.subTest(site=bad):
                self.data["allowed_sites"] = [bad]
                self.assertRejected("allowed_sites")

    def test_word_site_needs_three_letters(self):
        for good in ("uni", "uni2", "a-b-c"):
            self.assertTrue(word_site_ok(good), good)
        for bad in ("a1b", "123", "ai", "h t", ""):
            self.assertFalse(word_site_ok(bad), bad)
        self.data["allowed_sites"] = ["*uni*"]
        self.assertEqual(self.load().allowed_sites, ("*uni*",))
        self.data["allowed_sites"] = ["*ai*"]
        self.assertRejected("allowed_sites: bad domain '*ai*'")

    def test_popup_seconds_range(self):
        for bad in [2, 61, "10", True]:
            with self.subTest(value=bad):
                self.data["popup_seconds"] = bad
                self.assertRejected("popup_seconds")

    def test_video_rules(self):
        self.data["video"] = {"path": str(self.dir / "gone.mp4")}
        self.assertRejected("video")
        self.data["video"] = {"path": str(self.dir / "gone.mp4"), "fallback_url": "http://example.com/v"}
        self.assertRejected("https")
        self.data["video"] = {"path": str(self.dir / "clip.mkv")}
        self.assertRejected(".mp4 or .webm")
        self.data["video"] = {"path": str(self.video), "min_seconds": 1}
        self.assertRejected("min_seconds")

    def test_emergency_rules(self):
        self.data["emergency"] = {"phrase": "CHANGE-ME-BEFORE-FIRST-USE"}
        self.assertRejected("phrase")
        self.data["emergency"] = {"phrase": "short"}
        self.assertRejected("phrase")
        self.data["emergency"] = {"phrase": "x" * 201}
        self.assertRejected("phrase")
        self.data["emergency"] = {"phrase": "a long enough test phrase", "hotkeys": ["ctrl+nope"]}
        self.assertRejected("ctrl+nope")
        self.data["emergency"] = {"phrase": "a long enough test phrase", "hold_keys": ["ctrl+del"]}
        self.assertRejected("single key")
        self.data["emergency"] = {"phrase": "a long enough test phrase", "hold_keys": [], "hotkeys": []}
        self.assertRejected("at least one shortcut")
        self.data["emergency"] = {"phrase": "a long enough test phrase", "hold_ms": -1}
        self.assertRejected("hold_ms")

    def test_launch_commands_that_do_not_resolve_are_reported(self):
        cfg = self.load()
        found = {"code": "C:/bin/code.cmd"}
        self.assertEqual(unresolved_launches(cfg, which=found.get), [("chrome.exe", "chrome")])
        self.assertEqual(unresolved_launches(cfg, which=lambda name: name), [])

    def test_a_full_path_to_an_existing_file_resolves_and_variables_are_expanded(self):
        import os

        self.data["allowed_apps"] = [{"process": "Code.exe", "launch": ["%FG_TEST_DIR%/clip.mp4"]}]
        os.environ["FG_TEST_DIR"] = str(self.dir)
        self.addCleanup(os.environ.pop, "FG_TEST_DIR", None)
        self.assertEqual(unresolved_launches(self.load(), which=lambda name: None), [])

    def test_server_rules(self):
        self.data["server"] = {"port": 47653, "token": "short"}
        self.assertRejected("token")
        self.data["server"] = {"port": 47653, "token": "CHANGE-ME-RUN-INIT-0000"}
        self.assertRejected("token")
        self.data["server"] = {"port": 80, "token": "0123456789abcdef0123456789abcdef"}
        self.assertRejected("port")

    def test_roast_rules(self):
        self.data["roasts"] = {"stock": 5, "refill_at": 6}
        self.assertRejected("refill_at")
        self.data["roasts"] = {"max_words": 2}
        self.assertRejected("max_words")


class LastGoodTest(ConfigCase):
    def setUp(self):
        super().setUp()
        self.config = write_config(self.dir, self.data)
        self.last_good = self.dir / "state" / "config.last-good.json"

    def test_good_config_is_copied_and_returned(self):
        cfg, error = load_config_safe(self.config, self.last_good)
        self.assertEqual((cfg, error), (load_config(self.config), ""))
        self.assertEqual(self.last_good.read_text(encoding="utf-8"), self.config.read_text(encoding="utf-8"))

    def test_syntax_error_falls_back_to_last_good_and_names_the_line(self):
        cfg, _ = load_config_safe(self.config, self.last_good)
        self.config.write_text('{\n"allowed_apps": [\n,]}', encoding="utf-8")
        cfg2, error = load_config_safe(self.config, self.last_good)
        self.assertEqual(cfg2, cfg)
        self.assertIn("line 3", error)

    def test_invalid_value_falls_back_too(self):
        cfg, _ = load_config_safe(self.config, self.last_good)
        self.data["grace_seconds"] = 500
        write_config(self.dir, self.data)
        cfg2, error = load_config_safe(self.config, self.last_good)
        self.assertEqual(cfg2, cfg)
        self.assertIn("grace_seconds", error)

    def test_a_failed_backup_write_keeps_the_old_backup_whole(self):
        load_config_safe(self.config, self.last_good)
        before = self.last_good.read_text(encoding="utf-8")
        self.data["grace_seconds"] = 7
        write_config(self.dir, self.data)
        with mock.patch("focus_guard.jsonfile.os.replace", side_effect=OSError("disk full")):
            cfg, error = load_config_safe(self.config, self.last_good)
        self.assertEqual((cfg.grace_seconds if cfg else None, error), (7, ""))
        self.assertEqual(self.last_good.read_text(encoding="utf-8"), before)
        self.assertEqual(sorted(p.name for p in self.last_good.parent.iterdir()), ["config.last-good.json"])

    def test_config_vanishing_right_after_it_loaded_never_raises(self):
        text = self.config.read_text(encoding="utf-8")
        with mock.patch.object(Path, "read_text", side_effect=[text, FileNotFoundError("gone")]):
            cfg, error = load_config_safe(self.config, self.last_good)
        self.assertEqual((cfg, error), (load_config(self.config), ""))

    def test_no_last_good_and_broken_gives_none(self):
        self.config.write_text("{nope", encoding="utf-8")
        cfg, error = load_config_safe(self.config, self.last_good)
        self.assertIsNone(cfg)
        self.assertIn("cannot read config", error)


if __name__ == "__main__":
    unittest.main()


class YouTubeConfigTest(ConfigCase):
    def test_youtube_is_optional(self):
        self.assertTrue(self.load().youtube.is_empty())

    def test_youtube_lists_load(self):
        self.data["youtube"] = {"channels": ["@3blue1brown"], "playlists": ["PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi"]}
        cfg = self.load()
        self.assertEqual(cfg.youtube.handles, ("@3blue1brown",))
        self.assertEqual(cfg.youtube.playlists, ("PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi",))

    def test_youtube_videos_are_read(self):
        self.data["youtube"] = {"videos": ["https://youtu.be/aircAruvnKk", "dQw4w9WgXcQ"]}
        cfg = self.load()
        self.assertEqual(cfg.youtube.videos, ("aircAruvnKk", "dQw4w9WgXcQ"))
        self.assertFalse(cfg.youtube.is_empty())

    def test_youtube_mistakes_are_rejected(self):
        for bad in [
            [],
            {"channels": "@x"},
            {"channels": [5]},
            {"channels": ["youtube.com/c/x"]},
            {"playlists": ["WL"]},
            {"videos": ["not a video"]},
            {"films": []},
        ]:
            with self.subTest(bad=bad):
                self.data["youtube"] = bad
                self.assertRejected("youtube")


class VideoListConfigTest(ConfigCase):
    def test_video_lists_load_and_a_ticked_video_is_enough(self):
        self.data["videos"] = ["built.mp4"]
        self.data["video_files"] = ["C:/videos/mine.mp4"]
        self.data["video"] = {"path": str(self.dir / "gone.mp4")}
        cfg = self.load()
        self.assertEqual((cfg.videos, cfg.video_files), (("built.mp4",), ("C:/videos/mine.mp4",)))

    def test_bad_video_lists_are_refused(self):
        self.data["videos"] = [5]
        self.assertRejected("'videos'")
        self.data["videos"] = []
        self.data["video_files"] = "x.mp4"
        self.assertRejected("'video_files'")
