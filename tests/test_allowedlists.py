import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from focus_guard.allowedit import LAST_APP
from focus_guard.allowedlists import NEEDS_CONNECTION, NO_CHANNEL, AllowedLists
from focus_guard.paths import Paths
from focus_guard.programs import NOT_A_PROGRAM, Program
from focus_guard.settings import CONFIG_BROKEN, CONFIG_BUSY, SESSION_LOCKED, write_config
from tests.helpers import base_config

PLAYLIST = "PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi"
VIDEO_LINK = f"https://www.youtube.com/watch?v=aircAruvnKk&list={PLAYLIST}"
VIDEO_ANSWER = json.dumps({"title": "Neural networks?", "author_url": "https://www.youtube.com/@3blue1brown"})


def iso(text: str) -> str:
    """A name kept in its own direction inside a Hebrew line (FSI ... PDI)."""
    return "⁨" + text + "⁩"


class FakePrograms:
    def __init__(self, root: Path) -> None:
        self.zoom = Program("Zoom", "zoom.exe", str(root / "Zoom.exe"))
        self.word = Program("Word", "winword.exe", str(root / "WINWORD.EXE"))

    def running(self) -> Sequence[Program]:
        return [self.zoom, Program("Chrome", "chrome.exe", "C:/chrome.exe")]

    def installed(self) -> Sequence[Program]:
        return [self.word]

    def from_file(self, path: str) -> Program | None:
        return self.word if path.endswith("Word.lnk") else None

    def name_of(self, process: str, path: str) -> str:
        return {"code.exe": "Visual Studio Code", "chrome.exe": "Google Chrome"}.get(process.lower(), process)


class AllowedCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.paths = Paths(self.root)
        video = self.root / "clip.mp4"
        video.write_bytes(b"x")
        self.paths.config.write_text(json.dumps(base_config(video)), encoding="utf-8")
        self.running, self.online = False, True
        self.lists = AllowedLists(self.paths, FakePrograms(self.root), self.fetch, lambda: self.running)

    def fetch(self, url: str) -> str:
        if not self.online:
            raise OSError("offline")
        return VIDEO_ANSWER if "watch" in url else json.dumps({"title": "Deep learning"})

    def config(self) -> dict:
        return json.loads(self.paths.config.read_text(encoding="utf-8"))


class ViewTest(AllowedCase):
    def test_view_shows_names_and_what_is_open(self):
        view = self.lists.view()
        self.assertEqual(
            view["apps"],
            [
                {"process": "Code.exe", "name": "Visual Studio Code", "removable": True},
                {"process": "chrome.exe", "name": "Google Chrome", "removable": True},
            ],
        )
        self.assertEqual(view["open"], [{"path": str(self.root / "Zoom.exe"), "name": "Zoom"}])
        self.assertEqual(view["sites"][0], {"entry": "github.com", "label": "github.com"})

    def test_find_matches_installed_programs(self):
        self.assertEqual(self.lists.find("wo"), [{"path": str(self.root / "WINWORD.EXE"), "name": "Word"}])


class EditTest(AllowedCase):
    def test_add_and_remove_each_kind(self):
        self.assertTrue(self.lists.add("app", str(self.root / "Zoom.exe"))["ok"])
        self.assertIn({"process": "Zoom.exe", "launch": [str(self.root / "Zoom.exe")]}, self.config()["allowed_apps"])
        self.assertTrue(self.lists.add("site", "uni.ac.il")["ok"])
        answer = self.lists.add("word", "uni")
        self.assertIn({"entry": "*uni*", "label": "מילה: uni"}, answer["view"]["sites"])
        self.assertTrue(self.lists.add("playlist", PLAYLIST)["ok"])
        self.assertTrue(self.lists.add("video", "aircAruvnKk")["ok"])
        self.assertTrue(self.lists.add("channel", VIDEO_LINK)["ok"])
        self.assertEqual(
            self.config()["youtube"], {"playlists": [PLAYLIST], "videos": ["aircAruvnKk"], "channels": ["@3blue1brown"]}
        )
        labels = [item["label"] for item in self.lists.view()["youtube"]]
        self.assertEqual(
            labels,
            [f"ערוץ: {iso('@3blue1brown')}", f"פלייליסט: {iso('Deep learning')}", f"סרטון: {iso('Neural networks?')}"],
        )
        for kind, value in (("channel", "@3blue1brown"), ("site", "*uni*"), ("app", "zoom.exe")):
            self.assertTrue(self.lists.remove(kind, value)["ok"], kind)
        self.assertEqual(self.config()["youtube"]["channels"], [])
        self.assertNotIn("*uni*", self.config()["allowed_sites"])

    def test_a_dropped_file(self):
        self.assertTrue(self.lists.add_file("C:/Desktop/Word.lnk")["ok"])
        self.assertEqual(self.config()["allowed_apps"][-1]["process"], "winword.exe")
        self.assertEqual(self.lists.add_file("C:/Docs/x.pdf"), {"ok": False, "message": NOT_A_PROGRAM})

    def test_the_last_app_stays(self):
        self.assertTrue(self.lists.remove("app", "code.exe")["ok"])
        self.assertEqual(self.lists.remove("app", "chrome.exe"), {"ok": False, "message": LAST_APP})
        self.assertFalse(self.lists.view()["apps"][0]["removable"])


class RefusedTest(AllowedCase):
    def test_during_a_session_nothing_changes(self):
        before = self.paths.config.read_bytes()
        self.running = True
        self.assertEqual(self.lists.add("site", "uni.ac.il"), {"ok": False, "message": SESSION_LOCKED})
        self.assertEqual(self.lists.remove("site", "github.com"), {"ok": False, "message": SESSION_LOCKED})
        self.assertEqual(self.paths.config.read_bytes(), before)

    def test_a_broken_config_is_never_overwritten(self):
        broken = self.paths.config.read_text(encoding="utf-8") + "}"
        self.paths.config.write_text(broken, encoding="utf-8")
        self.assertEqual(self.lists.add("site", "uni.ac.il"), {"ok": False, "message": CONFIG_BROKEN})
        self.assertEqual(self.paths.config.read_text(encoding="utf-8"), broken)

    def test_an_invalid_config_is_not_written_by_the_lists(self):
        data = self.config()
        data["emergency"]["phrase"] = "CHANGE-ME-BEFORE-FIRST-USE"
        self.paths.config.write_text(json.dumps(data), encoding="utf-8")
        before = self.paths.config.read_bytes()
        result = self.lists.add("site", "uni.ac.il")
        self.assertFalse(result["ok"])
        self.assertIn("emergency.phrase", result["message"])
        self.assertEqual(self.paths.config.read_bytes(), before)

    def test_a_list_of_the_wrong_type_is_broken(self):
        self.paths.config.write_text(json.dumps({**self.config(), "allowed_sites": 5}), encoding="utf-8")
        before = self.paths.config.read_bytes()
        self.assertEqual(self.lists.add("site", "uni.ac.il"), {"ok": False, "message": CONFIG_BROKEN})
        self.assertEqual(self.paths.config.read_bytes(), before)

    def test_offline_youtube(self):
        self.online = False
        self.assertTrue(self.lists.add("playlist", f"https://www.youtube.com/playlist?list={PLAYLIST}")["ok"])
        self.assertEqual(self.lists.add("channel", VIDEO_LINK), {"ok": False, "message": NEEDS_CONNECTION})
        self.assertTrue(self.lists.add("video", VIDEO_LINK)["ok"])
        self.assertEqual(self.config()["youtube"], {"playlists": [PLAYLIST], "videos": ["aircAruvnKk"]})

    def test_bad_input_is_a_message(self):
        for kind, value in (("site", "hello world"), ("word", "ai"), ("video", "nope"), ("nonsense", "x")):
            with self.subTest(kind=kind):
                answer = self.lists.add(kind, value)
                self.assertFalse(answer["ok"])
                self.assertTrue(answer["message"])


class PreviewTest(AllowedCase):
    def test_site_preview(self):
        self.assertEqual(
            self.lists.site_preview("https://moodle.uni.ac.il/course"),
            {
                "ok": True,
                "host": "moodle.uni.ac.il",
                "covers": "כולל כל מה שמתחתיו, למשל www.moodle.uni.ac.il",
                "word": "moodle",
            },
        )
        self.assertFalse(self.lists.site_preview("hello world")["ok"])

    def test_youtube_preview_names_each_choice(self):
        answer = self.lists.youtube_preview(VIDEO_LINK)
        self.assertEqual(
            answer["choices"],
            [
                {"kind": "channel", "value": "@3blue1brown", "label": iso("@3blue1brown")},
                {"kind": "playlist", "value": PLAYLIST, "label": iso("Deep learning")},
                {"kind": "video", "value": "aircAruvnKk", "label": iso("Neural networks?")},
            ],
        )


class WriteConfigTest(AllowedCase):
    def test_write_config_keeps_every_other_key(self):
        before = self.config()
        self.assertEqual(write_config(self.paths, lambda raw: {**raw, "grace_seconds": 7}, False), "")
        self.assertEqual(self.config(), {**before, "grace_seconds": 7})


class ConcurrentWriteTest(AllowedCase):
    def test_two_saves_at_once_both_land(self):
        import threading
        import time

        def slow(key: str):
            def change(raw: dict) -> dict:
                time.sleep(0.2)  # the other save runs meanwhile
                return {**raw, "allowed_sites": [*raw["allowed_sites"], key]}

            return change

        threads = [
            threading.Thread(target=write_config, args=(self.paths, slow(site), False)) for site in ("a.com", "b.com")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue({"a.com", "b.com"} <= set(self.config()["allowed_sites"]))

    def test_a_locked_file_is_a_message_and_nothing_breaks(self):
        from unittest import mock

        before = self.paths.config.read_text(encoding="utf-8")
        with mock.patch("focus_guard.settings.os.replace", side_effect=PermissionError("in use")):
            self.assertEqual(self.lists.add("site", "uni.ac.il"), {"ok": False, "message": CONFIG_BUSY})
        self.assertEqual(self.paths.config.read_text(encoding="utf-8"), before)


class ChannelOfVideoTest(AllowedCase):
    def test_online_without_a_handle_says_so(self):
        self.fetch = lambda url: json.dumps({"title": "T", "author_url": "https://www.youtube.com/user/someone"})
        self.lists = AllowedLists(self.paths, FakePrograms(self.root), self.fetch, lambda: False)
        self.assertEqual(self.lists.add("channel", VIDEO_LINK), {"ok": False, "message": NO_CHANNEL})
