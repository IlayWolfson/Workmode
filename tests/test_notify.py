import unittest
from datetime import datetime
from unittest import mock

from focus_guard import ui
from focus_guard.notify import NERD_NO, NERD_TEXT, NERD_YES, corner_position, nerd_deadline, notify_copy, window_args

START = datetime(2026, 10, 25, 14, 0).timestamp()
END = START + 2 * 3600


class CopyTest(unittest.TestCase):
    def test_upcoming_names_the_title_and_start_time(self):
        self.assertEqual(
            notify_copy("upcoming", "מתמטיקה", START, END, START - 60),
            {"text": "מתמטיקה מתחיל ב-14:00", "go": "התחלה עכשיו", "no": "לא היום"},
        )

    def test_empty_title_reads_session(self):
        self.assertEqual(notify_copy("upcoming", " ", START, END, START - 60)["text"], "סשן מתחיל ב-14:00")

    def test_missed_counts_minutes_left_rounded_up(self):
        copy = notify_copy("missed", "x", START, END, END - 35 * 60 + 1)
        self.assertEqual(copy, {"text": "פספסת את ההתחלה, נשארו 35 דק׳", "go": "התחלה עכשיו", "no": "לא היום"})

    def test_restart_offers_continue(self):
        copy = notify_copy("restart", "", START, END, END - 600)
        self.assertEqual(copy, {"text": "הסשן נעצר באמצע, נשארו 10 דק׳", "go": "להמשיך", "no": "לא היום"})

    def test_unknown_kind_is_an_error(self):
        with self.assertRaises(ValueError):
            notify_copy("other", "", START, END, START)

    def test_nerd_copy_is_exact(self):
        self.assertEqual(NERD_TEXT, "ידעתי שאתה לא מסוגל חי חה חי גרההה")
        self.assertEqual(NERD_YES, "התחרטתי אני רוצה לעבוד")
        self.assertEqual(NERD_NO, "אתה צודק המלך שלי נכנעתי")


class TimingTest(unittest.TestCase):
    def test_nerd_deadline_upcoming_is_the_planned_start(self):
        self.assertEqual(nerd_deadline("upcoming", START, START - 30), START)

    def test_nerd_deadline_missed_and_restart_is_two_minutes(self):
        for kind in ("missed", "restart"):
            self.assertEqual(nerd_deadline(kind, START, START + 500), START + 620)

    def test_window_args_carry_copy_nerd_and_times_in_ms(self):
        args = window_args("missed", "x", START, END, START + 60)
        self.assertEqual(args["text"], "פספסת את ההתחלה, נשארו 119 דק׳")
        self.assertEqual((args["nerd_text"], args["nerd_yes"], args["nerd_no"]), (NERD_TEXT, NERD_YES, NERD_NO))
        self.assertEqual(args["nerd_after_ms"], 120_000)
        self.assertEqual(args["close_after_ms"], int((END - START - 60) * 1000))

    def test_corner_position_is_bottom_left_of_the_work_area(self):
        self.assertEqual(corner_position((0, 0, 1920, 1040), 380, 190), (16, 1040 - 190 - 16))


class UiModeTest(unittest.TestCase):
    def test_notify_mode_parses_its_options(self):
        with mock.patch.object(ui, "run_notify") as run:
            ui.main(["notify", "--kind=upcoming", "--title=T", f"--start={START}", f"--end={END}"])
        run.assert_called_once_with("upcoming", "T", START, END)

    def test_error_page_escapes_text(self):
        page = ui.error_html("<b>bad</b>")
        self.assertIn("&lt;b&gt;bad&lt;/b&gt;", page)
        self.assertIn('dir="rtl"', page)


if __name__ == "__main__":
    unittest.main()
