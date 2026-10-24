import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from focus_guard.appapi import BAD_REQUEST, AppApi
from focus_guard.events import EventStore
from focus_guard.paths import Paths
from focus_guard.session import Session, load_session, write_session
from focus_guard.settings import SESSION_LOCKED
from focus_guard.waiting import Placement, WaitingStore, WaitingWindow
from tests.helpers import base_config


class AppApiCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.paths = Paths(self.root)
        # a real date: start_now writes a calendar event, and Windows cannot convert local times before 1970
        self.spawned, self.now, self.guard_alive, self.views = [], datetime(2026, 10, 20, 9, 0).timestamp(), True, []
        self.api = AppApi(
            self.paths,
            spawn=self.spawned.append,
            now=lambda: self.now,
            guard_alive=lambda: self.guard_alive,
            set_view=self.views.append,
        )

    def write_config(self):
        video = self.root / "clip.mp4"
        video.write_bytes(b"x")
        self.paths.config.write_text(json.dumps(base_config(video)), encoding="utf-8")


class StatusTest(AppApiCase):
    def test_problem_when_the_config_is_missing(self):
        status = self.api.status()
        self.assertEqual(status["state"], "problem")
        self.assertIn("config", status["message"].lower())

    def test_ready_lists_the_allowed_apps_and_the_emergency_hint(self):
        self.write_config()
        status = self.api.status()
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["apps"], ["code.exe", "chrome.exe"])
        self.assertEqual(status["sites"], 2)
        self.assertIn("Del", status["hint"])

    def test_running_reports_mode_and_minutes_left(self):
        self.write_config()
        self.api.start(25, True)
        self.now += 600
        status = self.api.status()
        self.assertEqual((status["state"], status["live"], status["minutes_left"]), ("running", True, 15))

    def test_a_session_without_a_running_guard_is_reported_stalled_and_start_resumes_it(self):
        self.write_config()
        self.api.start(25, True)
        self.assertFalse(self.api.status()["stalled"])
        self.guard_alive = False
        self.assertTrue(self.api.status()["stalled"])
        self.assertTrue(self.api.start(25, True)["ok"])
        self.assertEqual(len(self.spawned), 4)

    def test_status_lists_waiting_programs_without_exe(self):
        self.write_config()
        self.api.start(25, True)
        store = WaitingStore(self.paths.waiting)
        for hwnd, name in [(1, "Steam.exe"), (2, "notepad.EXE"), (3, "Steam.exe")]:
            store.add(WaitingWindow(hwnd, hwnd, name, Placement(1, (0, 0, 1, 1))))
        status = self.api.status()
        self.assertEqual((status["waiting"], status["muted"]), (["Steam", "notepad"], False))

    def test_mute_waiting_creates_the_request_file(self):
        self.write_config()
        self.api.start(25, True)
        self.assertEqual(self.api.mute_waiting(), {"ok": True})
        self.assertTrue(self.paths.mute_request.exists())
        self.assertTrue(self.api.status()["muted"])

    def test_unmute_waiting_removes_the_request(self):
        self.write_config()
        self.api.start(25, True)
        self.api.mute_waiting()
        self.assertEqual(self.api.unmute_waiting(), {"ok": True})
        self.assertFalse(self.paths.mute_request.exists())
        self.assertFalse(self.api.status()["muted"])

    def test_mute_waiting_without_a_session_does_nothing(self):
        self.write_config()
        self.assertFalse(self.api.mute_waiting()["ok"])
        self.assertFalse(self.paths.mute_request.exists())

    def test_minutes_left_rounds_up(self):
        self.write_config()
        self.api.start(1, False)
        self.now += 10
        self.assertEqual(self.api.status()["minutes_left"], 1)


class ClockTest(AppApiCase):
    def test_running_status_has_the_clock_fields(self):
        self.write_config()
        self.now = datetime(2026, 10, 25, 14, 0).timestamp()
        self.api.start(60, True)
        self.now += 900
        status = self.api.status()
        self.assertEqual((status["ends_at"], status["seconds_left"]), ("15:00", 2700))
        self.assertAlmostEqual(status["progress"], 0.25)
        self.assertEqual(status["title"], "")

    def test_grace_left_counts_down_then_zero(self):
        self.write_config()  # grace_seconds defaults to 20
        self.api.start(25, True)
        self.assertEqual(self.api.status()["grace_left"], 20)
        self.now += 5
        self.assertEqual(self.api.status()["grace_left"], 15)
        self.now += 30
        self.assertEqual(self.api.status()["grace_left"], 0)

    def test_follow_on_session_has_no_grace(self):
        self.write_config()
        write_session(self.paths.session, Session(self.now, self.now + 600, True, "k@2026-10-25", 0))
        self.assertEqual(self.api.status()["grace_left"], 0)

    def test_title_comes_from_the_event(self):
        self.write_config()
        self.paths.events.parent.mkdir(exist_ok=True)
        self.paths.events.write_text(
            json.dumps(
                {"events": [{"id": "m", "title": "מתמטיקה", "date": "2026-10-25", "start": "14:00", "end": "15:00"}]}
            ),
            encoding="utf-8",
        )
        write_session(self.paths.session, Session(self.now, self.now + 600, True, "m@2026-10-25"))
        self.assertEqual(self.api.status()["title"], "מתמטיקה")

    def test_set_view_passes_only_known_views(self):
        self.api.set_view("clock")
        self.api.set_view("calendar")
        self.api.set_view("other")
        self.assertEqual(self.views, ["clock", "calendar"])


class FakeBusy:
    def __init__(self, ranges):
        self.ranges, self.asked = ranges, []

    def busy(self, start, end):
        self.asked.append((start, end))
        return self.ranges


def at(text):
    return datetime.fromisoformat(text).timestamp()


def ms(text):
    return at(text) * 1000


FORM = {"title": "מתמטיקה", "date": "2026-10-27", "start": "14:00", "end": "16:00", "days": [], "cue": True}


class WeekTest(AppApiCase):
    def setUp(self):
        super().setUp()
        self.write_config()
        self.now = at("2026-10-27 09:00")  # a Tuesday
        self.paths.state.mkdir()

    def write_events(self, *events):
        self.paths.events.write_text(json.dumps({"version": 1, "events": list(events)}), encoding="utf-8")

    def run_session(self, key, start="2026-10-27 08:30", end="2026-10-27 10:00"):
        write_session(self.paths.session, Session(at(start), at(end), True, key))

    def test_week_marks_running_and_past_and_adds_busy(self):
        busy = FakeBusy([(at("2026-10-27 12:00"), at("2026-10-27 13:00"))])
        api = AppApi(self.paths, spawn=self.spawned.append, now=lambda: self.now, guard_alive=lambda: True, busy=busy)
        self.write_events(
            {"id": "r", "title": "רץ", "date": "2026-10-27", "start": "08:30", "end": "10:00"},
            {"id": "p", "date": "2026-10-26", "start": "10:00", "end": "11:00", "live": False},
            {"id": "s", "title": "סדרה", "date": "2026-10-28", "start": "10:00", "end": "11:00", "days": [3]},
        )
        self.run_session("r@2026-10-27")
        items = api.week(ms("2026-10-25 00:00"), ms("2026-11-01 00:00"))
        by_id = {item["id"]: item for item in items if "id" in item}
        self.assertEqual(sorted(by_id), ["p@2026-10-26", "r@2026-10-27", "s@2026-10-28"])
        running, past, series = by_id["r@2026-10-27"], by_id["p@2026-10-26"], by_id["s@2026-10-28"]
        self.assertFalse(running["editable"])
        self.assertIn("fg-running", running["classNames"])
        self.assertTrue(running["extendedProps"]["running"])
        self.assertEqual((past["editable"], past["classNames"]), (False, ["fg-event", "fg-past", "fg-trial"]))
        self.assertTrue(series["editable"])
        self.assertTrue(series["extendedProps"]["repeating"])
        self.assertEqual(series["start"], ms("2026-10-28 10:00"))
        fields = {"title": "סדרה", "date": "2026-10-28", "start": "10:00", "end": "11:00", "days": [3]}
        self.assertEqual(series["extendedProps"]["fields"], {**fields, "cue": True, "live": True})
        background = [item for item in items if item.get("display") == "background"]
        expected = {"start": ms("2026-10-27 12:00"), "end": ms("2026-10-27 13:00")}
        self.assertEqual(background, [{**expected, "display": "background", "classNames": ["fg-busy"]}])
        self.assertEqual(busy.asked, [(at("2026-10-25 00:00"), at("2026-11-01 00:00"))])

    def test_week_with_bad_arguments_is_empty(self):
        self.assertEqual(self.api.week("x", None), [])

    def test_save_move_delete_round_trip(self):
        self.assertEqual(self.api.save_event({**FORM, "live": True}, "", "this"), {"ok": True})
        (event,), _ = EventStore(self.paths.events).load()
        key = f"{event.id}@2026-10-27"
        self.assertEqual(self.api.move_event(key, "2026-10-28", "15:00", "16:30", "this"), {"ok": True})
        (moved,), _ = EventStore(self.paths.events).load()
        self.assertEqual((moved.date.isoformat(), moved.start.strftime("%H:%M")), ("2026-10-28", "15:00"))
        self.assertNotEqual(moved.id, event.id)
        self.assertEqual(self.api.delete_event(f"{moved.id}@2026-10-28", "this"), {"ok": True})
        self.assertEqual(EventStore(self.paths.events).load(), ([], []))

    def test_move_with_an_end_day_refuses_more_than_twelve_hours(self):
        self.write_events({"id": "a", "date": "2026-10-27", "start": "22:00", "end": "23:00"})
        result = self.api.move_event("a@2026-10-27", "2026-10-27", "22:00", "23:00", "this", "2026-10-28")
        self.assertEqual(result, {"ok": False, "message": "אירוע יכול להימשך עד 12 שעות."})

    def test_save_with_a_key_changes_the_series_for_all(self):
        self.write_events({"id": "s", "date": "2026-10-28", "start": "10:00", "end": "11:00", "days": [3]})
        form = {**FORM, "date": "2026-10-28", "start": "12:00", "end": "13:00", "days": [3], "live": True}
        self.assertEqual(self.api.save_event(form, "s@2026-10-28", "all"), {"ok": True})
        (event,), _ = EventStore(self.paths.events).load()
        self.assertEqual((event.start.strftime("%H:%M"), event.days), ("12:00", frozenset({3})))

    def test_running_occurrence_refused_even_from_stale_page(self):
        self.write_events({"id": "r", "date": "2026-10-27", "start": "08:30", "end": "10:00"})
        self.run_session("r@2026-10-27")
        before = self.paths.events.read_text(encoding="utf-8")
        refused = {"ok": False, "message": "הסשן שרץ עכשיו נעול."}
        self.assertEqual(self.api.move_event("r@2026-10-27", "2026-10-27", "09:00", "11:00", "this"), refused)
        self.assertEqual(self.api.delete_event("r@2026-10-27", "this"), refused)
        self.assertEqual(self.api.save_event({**FORM, "live": False}, "r@2026-10-27", "this"), refused)
        self.assertEqual(self.paths.events.read_text(encoding="utf-8"), before)

    def test_broken_events_file_gives_message_not_exception(self):
        self.paths.events.write_text("{nope", encoding="utf-8")
        broken = {"ok": False, "message": "יש שגיאה ב-events.json. צריך לתקן אותה לפני שינויים."}
        self.assertEqual(self.api.save_event({**FORM, "live": True}, "", "this"), broken)
        self.assertEqual(self.api.delete_event("a@2026-10-27", "all"), broken)
        self.assertEqual(self.paths.events.read_text(encoding="utf-8"), "{nope")

    def test_bad_arguments_give_a_message(self):
        for result in [
            self.api.save_event("x", 5, "both"),
            self.api.move_event("a@2026-10-27", "27.10", "9", "10:00", "this"),
            self.api.delete_event(None, "this"),
        ]:
            with self.subTest(result=result):
                self.assertFalse(result["ok"])
                self.assertTrue(result["message"])

    def test_emergency_exit_touches_request_only_during_session(self):
        self.assertFalse(self.api.emergency_exit()["ok"])
        self.assertFalse(self.paths.exit_request.exists())
        self.run_session("r@2026-10-27")
        self.assertTrue(self.api.emergency_exit()["ok"])
        self.assertTrue(self.paths.exit_request.exists())

    def test_status_reports_events_version_and_running_occurrence(self):
        self.assertIsNone(self.api.status()["events_version"])
        self.write_events({"id": "r", "date": "2026-10-27", "start": "08:30", "end": "10:00"})
        version = self.paths.events.stat().st_mtime
        self.assertEqual(self.api.status()["events_version"], version)
        self.run_session("r@2026-10-27")
        status = self.api.status()
        self.assertEqual((status["occurrence"], status["events_version"]), ("r@2026-10-27", version))


class CalendarTest(AppApiCase):
    def test_start_creates_event_and_session(self):
        self.write_config()
        self.assertTrue(self.api.start(25, True)["ok"])
        (event,), _ = EventStore(self.paths.events).load()
        session = load_session(self.paths.session, self.now)
        self.assertEqual(session.occurrence, f"{event.id}@{event.date.isoformat()}")

    def test_status_survives_broken_config(self):
        self.write_config()
        self.api.status()  # keeps a copy of the good config
        self.paths.config.write_text("{nope", encoding="utf-8")
        status = self.api.status()
        self.assertEqual(status["state"], "ready")
        self.assertIn("cannot read config", status["config_error"])


class ResumeTest(AppApiCase):
    def test_resume_spawns_only_for_a_stalled_session(self):
        self.write_config()
        self.api.start(25, True)
        self.assertFalse(self.api.resume()["ok"])  # its guard runs
        self.guard_alive = False
        self.assertTrue(self.api.resume()["ok"])
        self.assertEqual(self.spawned[2:], ["focus_guard.run_guard", "focus_guard.run_guardian"])

    def test_resume_never_starts_a_new_session(self):
        self.write_config()
        self.guard_alive = False
        self.assertFalse(self.api.resume()["ok"])
        self.assertEqual(self.spawned, [])
        self.assertFalse(self.paths.session.exists())


class SurfaceTest(AppApiCase):
    def test_only_status_and_start_are_public(self):
        # pywebview walks every public attribute of the js_api object (see ui._Api).
        public = sorted(name for name in dir(self.api) if not name.startswith("_"))
        calendar = ["choose_file", "delete_event", "emergency_exit", "move_event", "mute_waiting", "preview_song"]
        rest = ["resume", "save_event", "save_settings", "set_view", "settings", "start", "status", "unmute_waiting"]
        allowed = ["allowed_add", "allowed_add_file", "allowed_find", "allowed_preview_site"]
        allowed += ["allowed_preview_youtube", "allowed_remove", "allowed_view"]
        self.assertEqual(public, [*allowed, *calendar, *rest, "week"])


class StartTest(AppApiCase):
    def test_accepts_numbers_and_numeric_strings(self):
        self.write_config()
        self.assertTrue(self.api.start("25", False)["ok"])
        self.assertEqual(self.spawned, ["focus_guard.run_guard", "focus_guard.run_guardian"])

    def test_rejects_non_numbers_and_out_of_range_minutes(self):
        self.write_config()
        for bad in ["abc", None, "", 0, 721]:
            with self.subTest(minutes=bad):
                self.assertFalse(self.api.start(bad, True)["ok"])
        self.assertEqual(self.spawned, [])

    def test_refuses_a_second_session(self):
        self.write_config()
        self.api.start(10, True)
        result = self.api.start(10, True)
        self.assertFalse(result["ok"])
        self.assertIn("already running", result["message"])

    def test_reports_a_config_problem_and_starts_nothing(self):
        result = self.api.start(10, True)
        self.assertFalse(result["ok"])
        self.assertIn("Config problem", result["message"])
        self.assertEqual(self.spawned, [])


class AllowedApiTest(AppApiCase):
    def test_lists_go_through_the_api_and_lock_during_a_session(self):
        self.write_config()
        api = AppApi(self.paths, now=lambda: self.now, programs=NoPrograms(), fetch=offline)
        self.assertEqual([site["entry"] for site in api.allowed_view()["sites"]], ["github.com", "docs.python.org"])
        self.assertTrue(api.allowed_add("site", "uni.ac.il")["ok"])
        self.assertTrue(api.allowed_remove("site", "uni.ac.il")["ok"])
        self.assertEqual(api.allowed_preview_site("uni.ac.il")["host"], "uni.ac.il")
        self.assertFalse(api.allowed_preview_youtube("nope")["ok"])
        self.assertEqual(api.allowed_find("x"), [])
        self.assertFalse(api.allowed_add_file("C:/x.pdf")["ok"])
        write_session(self.paths.session, Session(self.now, self.now + 600, True, "k@2026-10-25"))
        self.assertEqual(api.allowed_add("site", "uni.ac.il"), {"ok": False, "message": SESSION_LOCKED})

    def test_bad_arguments_are_refused(self):
        api = AppApi(self.paths, programs=NoPrograms(), fetch=offline)
        bad = {"ok": False, "message": BAD_REQUEST}
        self.assertEqual(api.allowed_add(5, None), bad)
        self.assertEqual(api.allowed_remove("site", 3), bad)
        self.assertEqual(api.allowed_add_file(None), bad)
        self.assertEqual(api.allowed_find(None), [])
        self.assertEqual(api.allowed_preview_site(None), bad)


class NoPrograms:
    def running(self):
        return []

    def installed(self):
        return []

    def from_file(self, path):
        return None

    def name_of(self, process, path):
        return process


def offline(url):
    raise OSError("offline")


if __name__ == "__main__":
    unittest.main()
