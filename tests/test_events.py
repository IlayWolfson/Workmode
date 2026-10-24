import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from focus_guard.events import Edit, EventError, EventStore, new_event_id, occurrences, parse_event, parse_events

JLM = ZoneInfo("Asia/Jerusalem")


def D(text):
    return date.fromisoformat(text)


def raw(**changes):
    data = {"id": "e1", "title": "מתמטיקה", "date": "2026-10-25", "start": "14:00", "end": "16:00"}
    data.update(changes)
    return data


def ev(**changes):
    events, errors = parse_events({"version": 1, "events": [raw(**changes)]})
    assert not errors, errors
    return events[0]


class ParseTest(unittest.TestCase):
    def test_defaults(self):
        events, _ = parse_events({"events": [{"id": "e1", "date": "2026-10-25", "start": "14:00", "end": "16:00"}]})
        event = events[0]
        self.assertEqual((event.title, event.days, event.cue, event.live), ("", frozenset(), True, True))

    def test_bad_entry_is_skipped_and_reported(self):
        good, errors = parse_events({"events": [raw(id="a"), raw(id="b", end="25:00"), raw(id="c", days=[7])]})
        self.assertEqual([e.id for e in good], ["a"])
        self.assertEqual(len(errors), 2)
        self.assertIn("event 2", errors[0])

    def test_duplicate_ids_keep_the_first_and_report(self):
        good, errors = parse_events({"events": [raw(title="first"), raw(title="second")]})
        self.assertEqual([e.title for e in good], ["first"])
        self.assertEqual(len(errors), 1)

    def test_longer_than_720_minutes_is_rejected(self):
        good, errors = parse_events(
            {"events": [raw(start="08:00", end="20:01"), raw(id="ok", start="08:00", end="20:00")]}
        )
        self.assertEqual([e.id for e in good], ["ok"])
        self.assertEqual(len(errors), 1)

    def test_bad_values_are_reported(self):
        for change in [
            {"id": ""},
            {"id": 5},
            {"date": "25/10/2026"},
            {"start": "9:00"},
            {"start": "14:00", "end": "14:00"},
            {"days": "0"},
            {"days": [True]},
            {"cue": "yes"},
            {"live": 1},
            {"title": 3},
            {"extra": 1},
        ]:
            with self.subTest(change=change):
                good, errors = parse_events({"events": [raw(**change)]})
                self.assertEqual((good, len(errors)), ([], 1))

    def test_not_a_dict_gives_one_error_and_no_events(self):
        for data in [None, [], {"events": "x"}, {"nope": []}]:
            with self.subTest(data=data):
                good, errors = parse_events(data)
                self.assertEqual((good, len(errors)), ([], 1))
                self.assertTrue(errors[0].startswith("events.json"))


class OccurrenceTest(unittest.TestCase):
    def test_one_off_event_gives_one_occurrence_with_key(self):
        occ = occurrences([ev(date="2026-10-25", start="14:00", end="16:00")], D("2026-10-25"), D("2026-10-31"), JLM)
        self.assertEqual([o.key for o in occ], ["e1@2026-10-25"])
        self.assertEqual(occ[0].end - occ[0].start, 7200)
        self.assertEqual((occ[0].title, occ[0].live, occ[0].cue), ("מתמטיקה", True, True))

    def test_one_off_outside_range_gives_nothing(self):
        self.assertEqual(occurrences([ev(date="2026-10-24")], D("2026-10-25"), D("2026-10-31"), JLM), [])

    def test_weekly_days_start_from_the_event_date(self):  # 2026-10-25 is a Sunday
        occ = occurrences([ev(date="2026-10-27", days=[0, 2])], D("2026-10-25"), D("2026-11-03"), JLM)
        self.assertEqual([o.key for o in occ], ["e1@2026-10-27", "e1@2026-11-01", "e1@2026-11-03"])

    def test_results_are_sorted_by_start(self):
        late, early = ev(id="late", start="18:00", end="19:00"), ev(id="early", start="08:00", end="09:00")
        occ = occurrences([late, early], D("2026-10-25"), D("2026-10-25"), JLM)
        self.assertEqual([o.key for o in occ], ["early@2026-10-25", "late@2026-10-25"])

    def test_overnight_event_ends_next_day(self):
        (o,) = occurrences([ev(start="23:00", end="00:30")], D("2026-10-25"), D("2026-10-25"), JLM)
        self.assertEqual(o.end - o.start, 5400)

    def test_dst_gap_and_fold_give_one_occurrence(self):
        # Israel: clocks fall back 02:00→01:00 on Sun 2026-10-25 and jump 02:00→03:00 on Fri 2027-03-26
        gap = occurrences([ev(date="2027-03-26", start="02:30", end="03:30")], D("2027-03-26"), D("2027-03-26"), JLM)
        fold = occurrences([ev(date="2026-10-25", start="01:30", end="02:30")], D("2026-10-25"), D("2026-10-25"), JLM)
        self.assertEqual((len(gap), len(fold)), (1, 1))
        self.assertGreater(gap[0].end, gap[0].start)
        self.assertGreater(fold[0].end, fold[0].start)

    def test_short_event_inside_dst_gap_keeps_its_length(self):
        (o,) = occurrences([ev(date="2027-03-26", start="02:30", end="03:15")], D("2027-03-26"), D("2027-03-26"), JLM)
        self.assertEqual(o.end - o.start, 45 * 60)

    def test_event_across_the_fold_ends_at_the_wall_clock_end(self):
        (o,) = occurrences([ev(date="2026-10-25", start="00:00", end="03:00")], D("2026-10-25"), D("2026-10-25"), JLM)
        self.assertEqual(o.end - o.start, 4 * 3600)  # the hour 01:00–02:00 happens twice


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = EventStore(Path(tmp.name) / "state" / "events.json")

    def test_missing_file_is_empty_without_errors(self):
        self.assertEqual(self.store.load(), ([], []))
        self.assertIsNone(self.store.mtime())

    def test_add_then_load_round_trip(self):
        first, second = ev(id=new_event_id()), ev(id=new_event_id(), days=[0, 6], cue=False, live=False)
        self.store.add(first)
        self.store.add(second)
        self.assertEqual(self.store.load(), ([first, second], []))
        self.assertIsNotNone(self.store.mtime())

    def test_unreadable_file_reports_an_error(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text("{nope", encoding="utf-8")
        events, errors = self.store.load()
        self.assertEqual((events, len(errors)), ([], 1))

    def test_add_refuses_a_file_it_cannot_read(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text('{"events": [{"id": "x"},]}', encoding="utf-8")  # a hand edit with a stray comma
        with self.assertRaises(ValueError):
            self.store.add(ev())
        self.assertEqual(self.store.path.read_text(encoding="utf-8"), '{"events": [{"id": "x"},]}')

    def test_new_ids_are_eight_hex_characters_and_differ(self):
        ids = {new_event_id() for _ in range(20)}
        self.assertEqual(len(ids), 20)
        self.assertTrue(all(len(i) == 8 and int(i, 16) >= 0 for i in ids))

    def test_commit_keeps_invalid_entries(self):
        self.store.path.parent.mkdir(parents=True)
        raw_a = json.dumps(raw(id="a"), ensure_ascii=False)
        bad = '{"id": "bad", "end": "nope"}, {"id": [1]}, '
        self.store.path.write_text('{"version": 1, "events": [' + bad + raw_a + "]}", "utf-8")
        self.store.commit(Edit(remove=frozenset({"a"}), put=(ev(id="b"),)))
        items = json.loads(self.store.path.read_text(encoding="utf-8"))["events"]
        self.assertEqual(items[:2], [{"id": "bad", "end": "nope"}, {"id": [1]}])
        self.assertEqual([item["id"] for item in items[2:]], ["b"])

    def test_commit_replaces_an_entry_with_the_same_id_in_place_of_the_old(self):
        self.store.add(ev(id="a"))
        self.store.add(ev(id="c"))
        self.store.commit(Edit(put=(ev(id="a", title="new"),)))
        events, _ = self.store.load()
        self.assertEqual([(e.id, e.title) for e in events], [("c", "מתמטיקה"), ("a", "new")])

    def test_commit_refuses_unreadable_file(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(EventError):
            self.store.commit(Edit(put=(ev(id="b"),)))
        self.assertEqual(self.store.path.read_text(encoding="utf-8"), "{not json")

    def test_round_trip_writes_until_and_skip_only_when_set(self):
        plain = ev(id="p", days=[0])
        limited = ev(id="l", days=[0, 2], until="2026-12-01", skip=["2026-11-03", "2026-10-27"])
        self.store.add(plain)
        self.store.add(limited)
        items = json.loads(self.store.path.read_text(encoding="utf-8"))["events"]
        self.assertNotIn("until", items[0])
        self.assertNotIn("skip", items[0])
        self.assertEqual((items[1]["until"], items[1]["skip"]), ("2026-12-01", ["2026-10-27", "2026-11-03"]))
        self.assertEqual(self.store.load(), ([plain, limited], []))


class SeriesLimitTest(unittest.TestCase):
    def test_skip_and_until_limit_a_series(self):  # 2026-10-25 is a Sunday
        e = ev(date="2026-10-25", days=[0, 1, 2], skip=["2026-10-26"], until="2026-11-01")
        keys = [o.key for o in occurrences([e], D("2026-10-25"), D("2026-11-03"), JLM)]
        self.assertEqual(keys, ["e1@2026-10-25", "e1@2026-10-27", "e1@2026-11-01"])

    def test_until_before_date_and_skip_on_one_off_are_errors(self):
        for change in [
            {"days": [0], "until": "2026-10-24"},
            {"days": [0], "until": "1.11.2026"},
            {"days": [0], "skip": "2026-10-26"},
            {"days": [0], "skip": ["26/10"]},
            {"until": "2026-11-01"},
            {"skip": ["2026-10-26"]},
        ]:
            with self.subTest(change=change):
                good, errors = parse_events({"events": [raw(**change)]})
                self.assertEqual((good, len(errors)), ([], 1))

    def test_parse_event_uses_given_id_and_rejects_bad_times(self):
        item = {k: v for k, v in raw(days=[2]).items() if k != "id"}
        self.assertEqual(parse_event(item, "zz").id, "zz")
        self.assertEqual(parse_event(item, "zz").days, frozenset({2}))
        for bad in [{**item, "end": "25:00"}, {**item, "id": "x"}, {**item, "start": "08:00", "end": "20:01"}, "x"]:
            with self.subTest(bad=bad), self.assertRaises(EventError):
                parse_event(bad, "zz")


if __name__ == "__main__":
    unittest.main()
