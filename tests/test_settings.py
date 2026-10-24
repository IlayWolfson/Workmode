import json
import tempfile
import unittest
from pathlib import Path

from focus_guard.appapi import AppApi
from focus_guard.paths import Paths
from focus_guard.session import Session, write_session
from focus_guard.settings import CONFIG_BROKEN, PHRASES_DIFFER, SESSION_LOCKED, read_settings, save_settings
from tests.helpers import base_config

PHRASE = "a long enough test phrase"  # base_config's phrase
NEW_PHRASE = "a new phrase here"


class SettingsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.paths = Paths(self.root)
        self.paths.state.mkdir()
        self.bundled = self.root / "assets" / "songs"
        self.bundled.mkdir(parents=True)
        for name in ("bards-tale.mp3", "chime.wav", "LICENSES.md"):
            (self.bundled / name).write_bytes(b"x")
        self.mine = self.root / "my song.mp3"
        self.mine.write_bytes(b"x")
        self.video = self.root / "clip.mp4"
        self.video.write_bytes(b"x")
        self.write({})

    def write(self, extra):
        data = {**base_config(self.video), **extra}
        self.paths.config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def config(self):
        return json.loads(self.paths.config.read_text(encoding="utf-8"))


class ReadTest(SettingsCase):
    def test_settings_never_contain_phrase(self):
        self.assertNotIn(PHRASE, json.dumps(read_settings(self.paths, self.bundled), ensure_ascii=False))

    def test_lists_bundled_and_user_songs_with_ticks(self):
        self.write({"songs": ["chime.wav", str(self.mine)], "song_files": [str(self.mine)]})
        settings = read_settings(self.paths, self.bundled)
        self.assertEqual(
            settings["songs"],
            [
                {"id": "bards-tale.mp3", "name": "bards-tale", "ticked": False, "bundled": True},
                {"id": "chime.wav", "name": "chime", "ticked": True, "bundled": True},
                {"id": str(self.mine), "name": "my song", "ticked": True, "bundled": False},
            ],
        )
        self.assertEqual((settings["grace_seconds"], settings["start_with_windows"]), (20, True))

    def test_videos_are_listed_like_songs_and_the_current_video_stays_ticked(self):
        videos = self.root / "assets" / "videos"
        videos.mkdir(parents=True)
        (videos / "built.mp4").write_bytes(b"x")
        self.assertEqual(
            read_settings(self.paths, self.bundled)["videos"],
            [
                {"id": "built.mp4", "name": "built", "ticked": False, "bundled": True},
                {"id": str(self.video), "name": "clip", "ticked": True, "bundled": False},
            ],
        )


class SaveTest(SettingsCase):
    def test_save_refused_when_config_broken_or_session_running(self):
        before = self.paths.config.read_text(encoding="utf-8")
        self.assertEqual(save_settings(self.paths, {"grace_seconds": 5}, True), SESSION_LOCKED)
        self.paths.config.write_text(before + "}", encoding="utf-8")
        self.assertEqual(save_settings(self.paths, {"grace_seconds": 5}, False), CONFIG_BROKEN)
        self.assertEqual(self.paths.config.read_text(encoding="utf-8"), before + "}")

    def test_save_keeps_other_keys_and_validates(self):
        apps = self.config()["allowed_apps"]
        self.assertEqual(save_settings(self.paths, {"grace_seconds": 5, "start_with_windows": False}, False), "")
        saved = self.config()
        self.assertEqual((saved["grace_seconds"], saved["start_with_windows"], saved["allowed_apps"]), (5, False, apps))
        before = self.paths.config.read_text(encoding="utf-8")
        self.assertIn("grace_seconds", save_settings(self.paths, {"grace_seconds": 999}, False))
        self.assertEqual(self.paths.config.read_text(encoding="utf-8"), before)
        self.assertEqual([p.name for p in self.paths.state.iterdir()], [])  # no temp file left behind

    def test_new_phrase_must_match_twice_and_empty_keeps_old(self):
        mismatch = {"phrase": NEW_PHRASE, "phrase_again": "other"}
        self.assertEqual(save_settings(self.paths, mismatch, False), PHRASES_DIFFER)
        self.assertEqual(save_settings(self.paths, {"phrase": "", "phrase_again": "", "grace_seconds": 3}, False), "")
        self.assertEqual(self.config()["emergency"]["phrase"], PHRASE)
        self.assertEqual(save_settings(self.paths, {"phrase": NEW_PHRASE, "phrase_again": NEW_PHRASE}, False), "")
        self.assertEqual(self.config()["emergency"]["phrase"], NEW_PHRASE)

    def test_added_song_file_is_listed_and_ticked(self):
        changes = {"song_files": [str(self.mine)], "songs": [str(self.mine)]}
        self.assertEqual(save_settings(self.paths, changes, False), "")
        (mine,) = [song for song in read_settings(self.paths, self.bundled)["songs"] if not song["bundled"]]
        self.assertEqual((mine["id"], mine["ticked"]), (str(self.mine), True))

    def test_added_video_is_saved_and_listed_ticked(self):
        mine = self.root / "mine.webm"
        mine.write_bytes(b"x")
        self.assertEqual(save_settings(self.paths, {"videos": [str(mine)], "video_files": [str(mine)]}, False), "")
        own = [video for video in read_settings(self.paths, self.bundled)["videos"] if not video["bundled"]]
        self.assertIn({"id": str(mine), "name": "mine", "ticked": True, "bundled": False}, own)
        self.assertEqual(self.config()["video"]["path"], str(self.video))  # the old setting stays as the fallback


class ApiSettingsTest(SettingsCase):
    def setUp(self):
        super().setUp()
        self.played, self.autostart, self.asked = [], [], []
        self.api = AppApi(
            self.paths,
            spawn=lambda module: None,
            now=lambda: 1_800_000_000.0,
            guard_alive=lambda: False,
            play=self.played.append,
            choose=lambda kind: self.asked.append(kind) or "C:/picked.mp3",
            apply_autostart=lambda paths, enabled: self.autostart.append(enabled),
        )

    def test_api_settings_never_contain_phrase(self):
        self.assertNotIn(PHRASE, json.dumps(self.api.settings(), ensure_ascii=False))

    def test_save_applies_autostart(self):
        self.assertEqual(self.api.save_settings({"start_with_windows": False}), {"ok": True})
        self.assertEqual(self.autostart, [False])
        self.assertEqual(self.api.save_settings({"grace_seconds": 4}), {"ok": True})
        self.assertEqual(self.autostart, [False])

    def test_save_during_a_session_is_refused(self):
        write_session(self.paths.session, Session(1_800_000_000.0 - 60, 1_800_000_000.0 + 600, True, "a@x"))
        self.assertEqual(self.api.save_settings({"grace_seconds": 4}), {"ok": False, "message": SESSION_LOCKED})

    def test_preview_plays_only_listed_songs(self):
        self.assertEqual(self.api.preview_song("chime.wav"), {"ok": True})
        self.assertEqual(self.played, [self.bundled / "chime.wav"])
        self.assertFalse(self.api.preview_song("LICENSES.md")["ok"])
        self.assertFalse(self.api.preview_song(str(self.mine))["ok"])  # not added yet
        self.assertFalse(self.api.preview_song(None)["ok"])

    def test_choose_file_passes_known_kinds_only(self):
        self.assertEqual(self.api.choose_file("song"), "C:/picked.mp3")
        self.assertEqual(self.api.choose_file("other"), "")
        self.assertEqual(self.asked, ["song"])


if __name__ == "__main__":
    unittest.main()
