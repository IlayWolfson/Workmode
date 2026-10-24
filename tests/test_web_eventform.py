import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "focus_guard" / "web"


class EventFormTest(unittest.TestCase):
    def test_save_runs_one_at_a_time(self):
        script = (WEB / "eventform.js").read_text(encoding="utf-8")
        self.assertIn("model.oneAtATime(", script)

    def test_a_new_scope_question_cancels_the_open_one(self):
        # otherwise the event form's one-at-a-time Save waits forever on the first question
        script = (WEB / "eventcard.js").read_text(encoding="utf-8")
        self.assertIn("if (pendingScope) { pendingScope(null); }", script)
