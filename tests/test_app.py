import unittest

from focus_guard import app

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


if __name__ == "__main__":
    unittest.main()
