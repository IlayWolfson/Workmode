import itertools
import unittest
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from focus_guard.eventedit import GONE, PAST, RUNNING, TOO_LONG, Context, EditRefused, change, create, delete, move
from focus_guard.events import parse_events

JLM = ZoneInfo("Asia/Jerusalem")  # 2026-10-25 is a Sunday, 2026-10-27 a Tuesday


def D(text):
    return date.fromisoformat(text)


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=JLM).timestamp()


BEFORE = at("2026-10-26 08:00")


def ev(**changes):
    data = {"id": "a", "title": "מתמטיקה", "date": "2026-10-27", "start": "14:00", "end": "16:00"}
    data.update(changes)
    events, errors = parse_events({"events": [data]})
    assert not errors, errors
    return events[0]


def form(**changes):
    data = {"title": "מתמטיקה", "date": "2026-10-27", "start": "14:00", "end": "16:00", "days": [], "cue": True}
    data["live"] = True
    data.update(changes)
    return data


def ctx(now, running=""):
    counter = itertools.count(1)
    return Context(now, running, JLM, lambda: f"n{next(counter)}")


class CreateTest(unittest.TestCase):
    def test_create_gives_one_new_event(self):
        edit = create(form(days=[0, 2]), ctx(BEFORE))
        (new,) = edit.put
        self.assertEqual((new.id, new.days, edit.remove), ("n1", frozenset({0, 2}), frozenset()))

    def test_create_in_the_past_is_refused(self):
        with self.assertRaisesRegex(EditRefused, PAST):
            create(form(date="2026-10-20"), ctx(BEFORE))

    def test_create_longer_than_twelve_hours_is_refused(self):
        with self.assertRaisesRegex(EditRefused, TOO_LONG):
            create(form(start="08:00", end="20:30"), ctx(BEFORE))


class OneOffTest(unittest.TestCase):
    def test_change_one_off_gets_new_id(self):
        edit = change([ev(id="a")], "a@2026-10-27", form(start="16:00", end="17:00"), "this", ctx(BEFORE))
        self.assertEqual(edit.remove, frozenset({"a"}))
        (new,) = edit.put
        self.assertNotEqual(new.id, "a")
        self.assertEqual(new.start, time(16, 0))

    def test_move_across_midnight_and_refusals(self):
        one = ev(id="a", date="2026-10-27", start="22:00", end="23:00")
        ok = move([one], "a@2026-10-27", D("2026-10-27"), time(23, 30), time(0, 30), "this", ctx(BEFORE))
        self.assertEqual(ok.put[0].end, time(0, 30))
        for day, s, e, message in [
            (D("2026-10-27"), time(8, 0), time(21, 0), TOO_LONG),
            (D("2026-10-20"), time(9, 0), time(10, 0), PAST),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(EditRefused, message):
                move([one], "a@2026-10-27", day, s, e, "this", ctx(BEFORE))

    def test_delete_one_off_removes_it(self):
        self.assertEqual(delete([ev(id="a")], "a@2026-10-27", "this", ctx(BEFORE)).remove, frozenset({"a"}))

    def test_running_occurrence_is_refused_for_every_operation(self):
        now, key, events = at("2026-10-27 15:00"), "a@2026-10-27", [ev(id="a")]
        for operation in [
            lambda: change(events, key, form(start="15:00"), "this", ctx(now, key)),
            lambda: move(events, key, D("2026-10-27"), time(14, 0), time(17, 0), "all", ctx(now, key)),
            lambda: delete(events, key, "this", ctx(now, key)),
        ]:
            with self.assertRaisesRegex(EditRefused, RUNNING):
                operation()

    def test_past_occurrence_can_only_be_deleted(self):
        events, key, now = [ev(id="a", date="2026-10-20")], "a@2026-10-20", BEFORE
        with self.assertRaisesRegex(EditRefused, PAST):
            change(events, key, form(date="2026-10-28"), "this", ctx(now))
        with self.assertRaisesRegex(EditRefused, PAST):
            move(events, key, D("2026-10-28"), time(9, 0), time(10, 0), "this", ctx(now))
        self.assertEqual(delete(events, key, "this", ctx(now)).remove, frozenset({"a"}))

    def test_unknown_key_is_refused(self):
        for key in ["zz@2026-10-27", "a@2026-10-28", "a@nope", "garbage"]:
            with self.subTest(key=key), self.assertRaisesRegex(EditRefused, GONE):
                delete([ev(id="a")], key, "this", ctx(BEFORE))


class SeriesTest(unittest.TestCase):
    def series(self, **changes):
        return ev(id="s", date="2026-10-25", days=[0, 2], start="16:00", end="17:00", **changes)

    def test_this_event_skips_the_day_and_adds_a_one_off(self):
        form_ = form(start="18:00", end="19:00", days=[0, 2])
        edit = change([self.series()], "s@2026-10-27", form_, "this", ctx(BEFORE))
        old, new = edit.put
        self.assertEqual((old.id, old.skip), ("s", frozenset({D("2026-10-27")})))
        self.assertEqual((new.id, new.date, new.start, new.days), ("n1", D("2026-10-27"), time(18, 0), frozenset()))
        self.assertEqual(edit.remove, frozenset())

    def test_delete_this_event_only_skips(self):
        edit = delete([self.series()], "s@2026-10-27", "this", ctx(BEFORE))
        self.assertEqual([(e.id, e.skip) for e in edit.put], [("s", frozenset({D("2026-10-27")}))])

    def test_all_events_after_todays_start_applies_from_tomorrow(self):
        daily = ev(id="d", date="2026-10-20", days=list(range(7)), start="10:00", end="11:00")
        now = at("2026-10-27 12:00")
        later = form(date="2026-10-28", start="18:00", end="19:00", days=list(range(7)))
        edit = change([daily], "d@2026-10-28", later, "all", ctx(now))
        old, new = sorted(edit.put, key=lambda e: e.date)
        self.assertEqual((old.id, old.until), ("d", D("2026-10-27")))
        self.assertEqual((new.date, new.start), (D("2026-10-28"), time(18, 0)))
        self.assertNotIn("d", edit.remove)

    def test_all_events_before_any_start_replaces_whole_series(self):
        series = ev(id="s", date="2026-10-27", days=[2], start="16:00", end="17:00")
        edit = change([series], "s@2026-10-27", form(start="18:00", end="19:00", days=[2]), "all", ctx(BEFORE))
        (new,) = edit.put
        self.assertEqual(edit.remove, frozenset({"s"}))
        self.assertEqual((new.id, new.date, new.start, new.days), ("n1", D("2026-10-27"), time(18, 0), frozenset({2})))

    def test_all_events_never_touches_the_running_occurrence(self):
        daily = ev(id="d", date="2026-10-20", days=list(range(7)), start="10:00", end="11:00")
        now, running = at("2026-10-27 10:30"), "d@2026-10-27"
        edit = delete([daily], "d@2026-10-28", "all", ctx(now, running))
        self.assertEqual([(e.id, e.until) for e in edit.put], [("d", D("2026-10-27"))])

    def test_delete_all_before_any_start_removes_the_series(self):
        series = ev(id="s", date="2026-10-27", days=[2])
        edit = delete([series], "s@2026-10-27", "all", ctx(BEFORE))
        self.assertEqual((edit.remove, edit.put), (frozenset({"s"}), ()))

    def test_move_all_shifts_weekdays(self):
        series = ev(id="s", date="2026-11-01", days=[0, 2], start="16:00", end="17:00")
        edit = move([series], "s@2026-11-01", D("2026-11-02"), time(16, 0), time(17, 0), "all", ctx(BEFORE))
        (new,) = edit.put
        self.assertEqual((new.date, new.days), (D("2026-11-02"), frozenset({1, 3})))

    def test_all_events_to_no_repeat_ends_the_series_and_keeps_the_one_off(self):
        daily = ev(id="d", date="2026-10-20", days=list(range(7)), start="10:00", end="11:00", skip=["2026-10-30"])
        now = at("2026-10-23 12:00")
        edit = change([daily], "d@2026-10-27", form(start="18:00", end="19:00", days=[]), "all", ctx(now))
        old, new = sorted(edit.put, key=lambda e: e.id)
        self.assertEqual((old.id, old.until), ("d", D("2026-10-23")))
        self.assertEqual((new.date, new.days, new.until, new.skip), (D("2026-10-27"), frozenset(), None, frozenset()))

    def test_all_events_drop_into_the_past_is_refused(self):
        daily = ev(id="d", date="2026-10-20", days=list(range(7)), start="10:00", end="11:00")
        now = at("2026-10-23 12:00")
        with self.assertRaisesRegex(EditRefused, PAST):
            move([daily], "d@2026-10-25", D("2026-10-22"), time(9, 0), time(10, 0), "all", ctx(now))

    def test_resize_into_the_next_day_counts_the_whole_length(self):
        one = ev(id="a", date="2026-10-27", start="22:00", end="23:00")
        key, day = "a@2026-10-27", D("2026-10-27")
        with self.assertRaisesRegex(EditRefused, TOO_LONG):
            move([one], key, day, time(22, 0), time(23, 0), "this", ctx(BEFORE), D("2026-10-28"))
        with self.assertRaisesRegex(EditRefused, TOO_LONG):
            move([one], key, day, time(22, 0), time(22, 0), "this", ctx(BEFORE), D("2026-10-28"))
        ok = move([one], key, day, time(22, 0), time(1, 0), "this", ctx(BEFORE), D("2026-10-28"))
        self.assertEqual(ok.put[0].end, time(1, 0))

    def test_all_events_keeps_until_and_later_skips(self):
        series = self.series(until="2026-12-01", skip=["2026-11-03"])
        now = at("2026-10-27 12:00")  # the Sunday 10-25 occurrence has started
        edit = change([series], "s@2026-10-27", form(start="18:00", end="19:00", days=[0, 2]), "all", ctx(now))
        old, new = sorted(edit.put, key=lambda e: e.date)
        self.assertEqual(old.until, D("2026-10-26"))
        self.assertEqual(
            (new.date, new.until, new.skip), (D("2026-10-27"), D("2026-12-01"), frozenset({D("2026-11-03")}))
        )


if __name__ == "__main__":
    unittest.main()
