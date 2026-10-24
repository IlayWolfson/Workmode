import tempfile
import unittest
from pathlib import Path

from focus_guard import ui


class UiHtmlTest(unittest.TestCase):
    def test_popup_escapes_text_and_is_right_to_left(self):
        page = ui.popup_html("<script>alert(1)</script>", 10, "רמז", "כן, לצאת")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn('dir="rtl"', page)
        self.assertIn("var n=10", page)
        self.assertIn("כן, לצאת", page)

    def test_note_page_escapes_text_and_has_no_button(self):
        page = ui.note_html("<b>Steam</b> is waiting until 14:00 — everything keeps running")
        self.assertNotIn("<button", page)
        self.assertNotIn("<b>Steam", page)
        self.assertIn("&lt;b&gt;Steam&lt;/b&gt; is waiting until 14:00", page)
        self.assertIn('dir="auto"', page)

    def test_popup_seconds_must_be_numeric(self):
        with self.assertRaises(ValueError):
            ui.popup_html("t", "10; evil()", "h", "b")

    def test_phrase_page_has_an_input_and_the_prompt(self):
        page = ui.phrase_html("הקלידו <b>משפט</b>")
        self.assertIn("<input", page)
        self.assertIn("&lt;b&gt;משפט&lt;/b&gt;", page)

    def test_video_source_distinguishes_urls_and_files(self):
        self.assertEqual(ui.video_source("https://example.com/v"), ("url", "https://example.com/v"))
        with tempfile.TemporaryDirectory() as folder:
            clip = Path(folder) / "clip.mp4"
            clip.write_bytes(b"x")
            kind, value = ui.video_source(str(clip))
        self.assertEqual(kind, "file")
        self.assertTrue(value.startswith("file:///"))

    def test_js_api_exposes_only_methods_and_never_the_window(self):
        # pywebview walks every public attribute of the js_api object; holding the
        # window there sends it into endless recursion and hangs the popup.
        api = ui._Api()
        api._window = object()
        public = sorted(name for name in dir(api) if not name.startswith("_"))
        self.assertEqual(public, ["close", "submit"])

    def test_phrase_input_is_capped_and_a_long_submit_is_truncated(self):
        # the typed text travels through a small pipe; an uncapped paste would hang the box
        self.assertIn(f'maxlength="{ui.MAX_TYPED}"', ui.phrase_html("p"))
        api = ui._Api()
        api._window = type("W", (), {"destroy": lambda self: None})()
        api.submit("x" * 5000)
        self.assertEqual(len(api._result), ui.MAX_TYPED)

    def test_local_video_page_is_opened_as_a_file_url(self):
        # a plain path makes pywebview serve it over http, and an http page may not load file:// videos
        url = ui.page_url(Path(tempfile.gettempdir()) / "focus_guard_video.html")
        self.assertTrue(url.startswith("file:///"))

    def test_video_page_loops_and_escapes_the_source_and_hint(self):
        page = ui.video_html('file:///C:/a"b.mp4', "<hint>")
        self.assertIn("autoplay loop", page)
        self.assertIn("&quot;", page)
        self.assertIn("&lt;hint&gt;", page)


if __name__ == "__main__":
    unittest.main()
