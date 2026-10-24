import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "focus_guard" / "web"
API = (
    "allowed_view",
    "allowed_preview_site",
    "allowed_preview_youtube",
    "allowed_find",
    "allowed_add",
    "allowed_remove",
)


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class AllowedPanelTest(unittest.TestCase):
    def test_button_sits_under_the_settings_button(self):
        html = read("main.html")
        gear = '<button class="side-button" id="sideGear">⚙ הגדרות</button>'
        button = '<button class="side-button allow-btn" id="sideAllowed">✅ מה מותר בסשן</button>'
        self.assertIn(gear + "\n      " + button, html)
        self.assertIn('id="allowPanel"', html)
        self.assertIn('<link rel="stylesheet" href="allowed.css">', html)
        self.assertIn('<script src="allowed.js"></script>', html)

    def test_hidden_and_closed_during_a_session(self):
        main = read("main.js")
        self.assertIn("show('sideAllowed', !running);", main)
        self.assertIn("FG.allowed.close()", main)
        self.assertIn("FG.allowed.init();", main)

    def test_the_panel_uses_the_api(self):
        script = read("allowed.js")
        self.assertIn("window.FG.allowed = {", script)
        self.assertIn(".catch(", script)  # a failed call shows a message, never a dead click
        for name in API:
            self.assertIn(f"pywebview.api.{name}(", script, name)

    def test_the_approved_copy(self):
        html = read("main.html")
        for text in (
            "מה מותר בסשן",
            "תוכנות",
            "אתרים",
            "יוטיוב",
            "פתוחות עכשיו במחשב",
            "תוכנה אחרת",
            "הקלד שם תוכנה, או גרור לכאן קובץ / קיצור דרך",
            "הדבק קישור לאתר",
            "הדבק קישור לסרטון, ערוץ או פלייליסט",
            "מה להתיר?",
        ):
            self.assertIn(text, html, text)

    def test_the_button_uses_the_event_color_not_white_on_white(self):
        css = read("allowed.css")
        self.assertIn(".gcal .side-button.allow-btn { background: var(--g-event); color: var(--g-surface);", css)

    def test_no_raw_colors_in_the_new_css(self):
        css = read("allowed.css")
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", css))


class PunishVideoListTest(unittest.TestCase):
    def test_settings_has_a_video_list_like_the_songs(self):
        html = read("main.html")
        for text in (
            "<h3>סרטון עונש</h3>",
            'id="setVideos"',
            'id="setVideoDrop"',
            "+ הוספת סרטון משלי",
            "או גרור לכאן קובץ וידאו",
        ):
            self.assertIn(text, html, text)
        self.assertNotIn('id="setPickVideo"', html)
        script = read("settings.js")
        for text in ("video_files", "droppedVideo", "pywebview.api.choose_file('video')"):
            self.assertIn(text, script, text)
