import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "focus_guard" / "web"


class SidePanelTest(unittest.TestCase):
    def test_side_panel_has_a_settings_button_hidden_during_a_session(self):
        html = (WEB / "main.html").read_text(encoding="utf-8")
        self.assertIn('<button class="side-button" id="sideGear">⚙ הגדרות</button>', html)
        self.assertIn("$('sideGear').onclick = open;", (WEB / "settings.js").read_text(encoding="utf-8"))
        self.assertIn("show('sideGear', !running);", (WEB / "main.js").read_text(encoding="utf-8"))

    def test_emergency_hint_is_a_blue_box(self):
        self.assertIn('<div class="side-box" id="hint"></div>', (WEB / "main.html").read_text(encoding="utf-8"))
        css = (WEB / "calendar.css").read_text(encoding="utf-8")
        self.assertIn(".gcal .side-button, .side-box {", css)
        self.assertIn(".gcal .side-button { background: var(--g-blue); color: #fff;", css)

    def test_emergency_box_does_not_look_like_the_button(self):
        css = (WEB / "calendar.css").read_text(encoding="utf-8")
        self.assertIn(".side-box { background: var(--g-week); color: #174ea6; border: 1px solid #d2e3fc;", css)
        self.assertIn("box-shadow: 0 1px 3px rgba(60, 64, 67, 0.4)", css)  # the button is raised; the box is flat
