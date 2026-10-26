import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from focus_guard import app
from focus_guard.appupdate import UpdateService, start_update_bridge
from focus_guard.config import ConfigError, load_config
from focus_guard.paths import Paths
from focus_guard.version import VERSION
from tests.helpers import base_config, write_config

# every page and script of the main window (not the bundled library)
PAGE = "".join(
    path.read_text(encoding="utf-8") for path in sorted(app.WEB.glob("*.*")) if path.suffix in (".html", ".js")
)


class TitleTest(unittest.TestCase):
    def test_window_is_called_workmode(self):
        self.assertEqual(app.TITLE, "Workmode")


class PageTest(unittest.TestCase):
    def test_page_has_both_start_buttons_and_the_status_call(self):
        self.assertIn('dir="rtl"', PAGE)
        self.assertIn("pywebview.api.status", PAGE)
        self.assertIn("pywebview.api.start", PAGE)
        self.assertIn("התחלה עכשיו", PAGE)
        self.assertIn("ניסיון", PAGE)

    def test_page_has_the_mute_button_and_waiting_line(self):
        self.assertIn("pywebview.api.mute_waiting", PAGE)
        self.assertIn("השתקת תוכנות בהמתנה", PAGE)
        self.assertIn("pywebview.api.unmute_waiting", PAGE)
        self.assertIn("ביטול השתקה", PAGE)
        self.assertIn("בהמתנה: ", PAGE)

    def test_page_has_the_clock_and_switches_views(self):
        self.assertIn("מסדרים… ", PAGE)
        self.assertIn("pywebview.api.set_view", PAGE)
        self.assertIn("פועל עד ", PAGE)

    def test_page_never_inserts_text_as_html(self):
        self.assertNotIn("innerHTML", PAGE)
        self.assertNotIn("document.write", PAGE)

    def test_there_is_no_stop_button(self):
        for word in ["stop", "עצירה:", "ביטול סשן"]:
            self.assertNotIn(f">{word}", PAGE)

    def test_window_sizes_cover_both_views(self):
        self.assertEqual(set(app.SIZES), {"clock", "calendar"})

    def test_calendar_view_size_is_wide(self):
        self.assertEqual(app.SIZES["calendar"], (1180, 780))

    def test_calendar_is_a_share_of_the_screen_in_logical_pixels(self):
        self.assertEqual(app.calendar_size((1668, 901), 1.0, 85), (1418, 766))
        self.assertEqual(app.calendar_size((1920, 1032), 1.5, 85), (1088, 600))  # 150%: 1280x688 logical, min height
        self.assertEqual(app.calendar_size((2560, 1400), 1.0, 70), (1792, 980))

    def test_calendar_never_smaller_than_the_minimum_unless_the_screen_is(self):
        self.assertEqual(app.calendar_size((1000, 700), 1.0, 50), (900, 600))
        self.assertEqual(app.calendar_size((800, 560), 1.0, 85), (800, 560))

    def test_window_is_centered_on_the_work_area_in_logical_pixels(self):
        self.assertEqual(app.centered((0, 0, 858, 869), 1.0, (858, 739)), (0, 65))
        self.assertEqual(app.centered((0, 0, 1920, 1032), 1.5, (1088, 600)), (96, 44))
        self.assertIsNone(app.centered(None, 1.0, (858, 739)))

    def test_calendar_without_screen_information_keeps_the_planned_size(self):
        self.assertEqual(app.calendar_size(None, 1.0, 85), app.SIZES["calendar"])


class DropTest(unittest.TestCase):
    def test_a_dropped_file_is_added_and_the_panel_redrawn(self):
        added, scripts = [], []

        class Api:
            def allowed_add_file(self, path):
                added.append(path)
                return {"ok": False, "message": "לא"}

        event = {"dataTransfer": {"files": [{"name": "Word.lnk", "pywebviewFullPath": "C:/Desktop/Word.lnk"}]}}
        app.on_drop(Api(), scripts.append, event)
        self.assertEqual(added, ["C:/Desktop/Word.lnk"])
        self.assertEqual(scripts, ['FG.allowed.refresh({"ok": false, "message": "לא"})'])

    def test_nothing_dropped_does_nothing(self):
        scripts = []
        app.on_drop(None, scripts.append, {"dataTransfer": {"files": []}})
        app.on_drop(None, scripts.append, {"dataTransfer": {"files": [{"name": "x"}]}})
        app.on_drop(None, scripts.append, {})
        self.assertEqual(scripts, [])

    def test_a_dropped_video_goes_to_the_settings_list(self):
        scripts = []
        event = {"dataTransfer": {"files": [{"name": "a.mp4", "pywebviewFullPath": "C:/v/a.mp4"}]}}
        app.on_video_drop(scripts.append, event)
        self.assertEqual(scripts, ['FG.settings.droppedVideo("C:/v/a.mp4")'])
        app.on_video_drop(scripts.append, {"dataTransfer": {"files": []}})
        self.assertEqual(len(scripts), 1)


class SingleInstanceTest(unittest.TestCase):
    def test_second_app_start_signals_and_exits(self):
        signals = []
        code = app.main([], claim=lambda name: None, signal_show=signals.append)
        self.assertEqual((code, signals), (0, [app.SHOW_EVENT]))

    def test_after_undoing_an_interrupted_update_the_app_restarts_on_the_old_code(self):
        events = []

        class Handle:
            def Close(self):
                events.append("released")

        def claim(name):
            events.append(name)
            return Handle()

        code = app.main(
            [], claim=claim, recover=lambda: events.append("recover") or True, restart=lambda: events.append("restart")
        )
        self.assertEqual(code, 0)
        self.assertEqual(events, [app.MUTEX, "recover", "released", "restart"])  # the new process can claim the app

    def test_a_second_start_never_touches_the_files(self):
        undone = []
        app.main([], claim=lambda name: None, signal_show=lambda name: None, recover=lambda: undone.append(1) or True)
        self.assertEqual(undone, [])

    def test_quit_event_name(self):
        self.assertEqual(app.QUIT_EVENT, "Local\\FocusGuard.Quit")


class ViewSizerTest(unittest.TestCase):
    def test_hidden_window_is_not_resized_until_shown(self):
        sizes = []
        sizer = app.ViewSizer(lambda width, height: sizes.append((width, height)), visible=False)
        sizer.set_view("clock")
        self.assertEqual(sizes, [])  # pywebview's resize would show a hidden window
        sizer.shown()
        self.assertEqual(sizes, [app.SIZES["clock"]])

    def test_visible_window_follows_the_view_and_hiding_stops_it(self):
        sizes = []
        sizer = app.ViewSizer(lambda width, height: sizes.append((width, height)), visible=True)
        sizer.set_view("clock")
        sizer.hidden()
        sizer.set_view("calendar")
        self.assertEqual(sizes, [app.SIZES["clock"]])
        sizer.shown()
        self.assertEqual(sizes, [app.SIZES["clock"], app.SIZES["calendar"]])

    def test_sizer_uses_the_sizes_it_was_given(self):
        sizes = []
        given = {"clock": (320, 240), "calendar": (1418, 766)}
        sizer = app.ViewSizer(lambda width, height: sizes.append((width, height)), visible=True, sizes=given)
        sizer.set_view("calendar")
        self.assertEqual(sizes, [(1418, 766)])


class BridgeSettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.data = base_config(self.dir / "missing.mp4")  # the video is missing: the whole config is invalid
        self.data["emergency"]["phrase"] = "CHANGE-ME-BEFORE-FIRST-USE"

    def test_valid_config_uses_its_values(self):
        video = self.dir / "clip.mp4"
        video.write_bytes(b"x")
        path = write_config(self.dir, base_config(video))
        cfg = load_config(path)
        path.write_text("{", encoding="utf-8")
        self.assertEqual(app._bridge_settings(cfg, path), (cfg.server_port, cfg.server_token))

    def test_no_config_reads_the_server_section(self):
        path = write_config(self.dir, self.data)
        self.assertEqual(app._bridge_settings(None, path), (47653, self.data["server"]["token"]))

    def test_no_config_and_placeholder_token_gives_none(self):
        self.data["server"]["token"] = "CHANGE-ME-0123456789abcdef"
        self.assertIsNone(app._bridge_settings(None, write_config(self.dir, self.data)))


class UpdateBridgeIntegrationTest(unittest.TestCase):
    """The real path an invalid config takes: load_server -> _bridge_settings -> start_update_bridge (no app, no
    update-check thread; the OS picks the port)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.data = base_config(self.dir / "missing.mp4")  # the video is missing: the whole config is invalid
        self.data["emergency"]["phrase"] = "CHANGE-ME-BEFORE-FIRST-USE"
        self.data["server"]["port"] = 47700
        self.service = UpdateService(Paths(self.dir), spawn_update=lambda: None)

    def start(self):
        path = write_config(self.dir, self.data)
        with self.assertRaises(ConfigError):
            load_config(path)
        settings = app._bridge_settings(None, path)
        self.assertEqual(settings, (47700, self.data["server"]["token"]))
        server = start_update_bridge(0, settings[1], self.service, self.fail)
        self.assertIsNotNone(server)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)  # cleanups run last-in first: shutdown, then close
        return server.server_address[1]

    def get(self, port, token):
        url = f"http://127.0.0.1:{port}/update?token={token}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a system proxy
        with opener.open(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_invalid_config_still_serves_the_status_with_the_right_token(self):
        port = self.start()
        status, body = self.get(port, self.data["server"]["token"])
        self.assertEqual((status, body["installed"]), (200, VERSION))

    def test_wrong_token_gets_403(self):
        port = self.start()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get(port, "wrong-token-0000000000")
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)

    def test_placeholder_token_starts_no_bridge(self):
        self.data["server"]["token"] = "CHANGE-ME-0123456789abcdef"
        self.assertIsNone(app._bridge_settings(None, write_config(self.dir, self.data)))


if __name__ == "__main__":
    unittest.main()
