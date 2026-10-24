import unittest

from focus_guard.events import Occurrence
from focus_guard.scheduler import (
    CloseWindow,
    ContinueSession,
    DropSession,
    PlayCue,
    Record,
    Running,
    Scheduler,
    ShowWindow,
    StartSession,
)
from focus_guard.session import Session


def occ(name="a", start=1000.0, end=4600.0, cue=True, live=True):
    return Occurrence(f"{name}@2026-10-25", name, start, end, live, cue)


OCC = occ()


class OneOccurrenceTest(unittest.TestCase):
    def setUp(self):
        self.s = Scheduler()

        self.last = None

    def tick(self, now, occurrences=(OCC,), outcomes=None):
        """Tick every 10 s up to `now`, as the 1-second driver loop would (no sleep gap); all actions."""
        actions = []
        step = self.last + 10 if self.last is not None else now
        while step < now:
            actions += self.s.tick(step, list(occurrences), outcomes or {}, None)
            step += 10
        self.last = now
        return actions + self.s.tick(now, list(occurrences), outcomes or {}, None)

    def jump(self, now, occurrences=(OCC,)):
        """One tick after a long pause (the PC slept)."""
        self.last = now
        return self.s.tick(now, list(occurrences), {}, None)

    def test_cue_and_window_one_minute_before(self):
        self.assertEqual(self.tick(939), [])
        self.assertEqual(self.tick(940), [PlayCue(OCC.key), ShowWindow("upcoming", OCC)])
        self.assertEqual(self.tick(941), [])

    def test_ignored_window_starts_at_planned_time_with_the_second_cue(self):
        self.tick(940)
        self.assertEqual(self.tick(1000), [CloseWindow(OCC.key), PlayCue(OCC.key), StartSession(OCC, None)])
        self.assertEqual(self.tick(1001), [])

    def test_closed_first_step_still_starts_at_planned_time(self):
        self.tick(940)
        self.assertEqual(self.s.answer(OCC.key, "closed", 950), [])
        self.assertEqual(self.tick(1000), [CloseWindow(OCC.key), PlayCue(OCC.key), StartSession(OCC, None)])

    def test_nerd_then_planned_start_declines(self):
        self.tick(940)
        self.assertEqual(self.s.answer(OCC.key, "nerd", 950), [])
        self.assertEqual(self.tick(1000), [CloseWindow(OCC.key), Record(OCC.key, "declined")])

    def test_nerd_then_closed_declines(self):
        self.tick(940)
        self.s.answer(OCC.key, "nerd", 950)
        self.assertEqual(self.s.answer(OCC.key, "closed", 955), [CloseWindow(OCC.key), Record(OCC.key, "declined")])
        self.assertEqual(self.tick(1000), [])

    def test_nerd_then_green_starts_now(self):
        self.tick(940)
        self.s.answer(OCC.key, "nerd", 950)
        self.assertEqual(
            self.s.answer(OCC.key, "start", 955), [CloseWindow(OCC.key), PlayCue(OCC.key), StartSession(OCC, None)]
        )
        self.assertEqual(self.tick(1000), [])

    def test_decline_is_recorded_and_never_offered_again(self):
        self.tick(940)
        self.assertEqual(self.s.answer(OCC.key, "decline", 950), [CloseWindow(OCC.key), Record(OCC.key, "declined")])
        self.assertEqual(self.tick(1000), [])
        self.assertEqual(self.tick(1500), [])

    def test_occurrence_with_outcome_is_ignored(self):
        for now in (940, 1000, 1500, 5000):
            self.assertEqual(self.tick(now, outcomes={OCC.key: "declined"}), [])

    def test_tool_started_late_shows_missed_window_once(self):
        self.assertEqual(self.tick(1500), [ShowWindow("missed", OCC)])
        self.assertEqual(self.tick(1501), [])

    def test_missed_window_start_begins_session_without_cue(self):
        self.tick(1500)
        self.assertEqual(self.s.answer(OCC.key, "start", 1510), [CloseWindow(OCC.key), StartSession(OCC, None)])

    def test_missed_window_ignored_starts_nothing_and_closes_at_end(self):
        self.tick(1500)
        self.assertEqual(self.tick(3000), [])
        self.assertEqual(self.tick(4600), [CloseWindow(OCC.key)])
        self.assertEqual(self.tick(4700), [])

    def test_missed_window_closed_starts_nothing(self):
        self.tick(1500)
        self.assertEqual(self.s.answer(OCC.key, "closed", 1510), [])
        self.assertEqual(self.tick(1520), [])
        self.assertEqual(self.tick(4600), [])

    def test_sleeping_through_the_whole_event_closes_its_upcoming_window(self):
        self.tick(940)
        self.assertEqual(self.jump(5000), [CloseWindow(OCC.key)])
        self.assertEqual(self.tick(5010), [])

    def test_sleeping_through_the_event_at_the_nerd_step_closes_it_without_a_record(self):
        self.tick(940)
        self.s.answer(OCC.key, "nerd", 950)
        self.assertEqual(self.jump(5000), [CloseWindow(OCC.key)])

    def test_sleep_across_start_gives_missed_window(self):
        self.tick(940)
        self.assertEqual(self.jump(2200), [CloseWindow(OCC.key), ShowWindow("missed", OCC)])
        self.assertEqual(self.tick(2201), [])

    def test_short_tick_gap_is_not_sleep(self):
        self.tick(940)
        self.jump(969)
        self.assertEqual(self.jump(999), [])  # 30 s apart: still awake
        self.assertEqual(self.jump(1001), [CloseWindow(OCC.key), PlayCue(OCC.key), StartSession(OCC, None)])

    def test_no_cue_event_shows_window_without_song(self):
        quiet = occ(cue=False)
        self.assertEqual(self.tick(940, [quiet]), [ShowWindow("upcoming", quiet)])
        self.assertEqual(self.tick(1000, [quiet]), [CloseWindow(quiet.key), StartSession(quiet, None)])

    def test_past_occurrence_without_outcome_is_silent(self):
        self.assertEqual(self.tick(5000), [])

    def test_answer_for_unknown_key_does_nothing(self):
        self.assertEqual(self.s.answer("nope@2026-10-25", "start", 950), [])

    def test_vanished_occurrence_closes_window_and_never_starts(self):
        self.tick(940)
        self.assertEqual(self.tick(950, occurrences=()), [CloseWindow(OCC.key)])
        self.assertEqual(self.tick(1000, occurrences=()), [])
        self.assertEqual(self.s.answer(OCC.key, "start", 1001), [])

    def test_vanished_missed_window_closes_too(self):
        self.tick(1500)  # the tool started late: missed-start window
        self.assertEqual(self.tick(1510, occurrences=()), [CloseWindow(OCC.key)])

    def test_moved_occurrence_gets_a_fresh_cue_at_its_new_time(self):
        moved = occ("b", 2000.0, 5600.0)
        self.tick(940)
        self.assertEqual(self.tick(950, occurrences=(moved,)), [CloseWindow(OCC.key)])
        self.assertEqual(self.tick(1940, occurrences=(moved,)), [PlayCue(moved.key), ShowWindow("upcoming", moved)])


class RunningSessionTest(unittest.TestCase):
    def setUp(self):
        self.s = Scheduler()
        self.last = None

    def tick(self, now, occurrences, running=None):
        """Tick every 10 s up to `now` with the same running session; all actions."""
        actions = []
        step = self.last + 10 if self.last is not None else now
        while step < now:
            actions += self.s.tick(step, list(occurrences), {}, running)
            step += 10
        self.last = now
        return actions + self.s.tick(now, list(occurrences), {}, running)

    @staticmethod
    def running(occurrence, start=None, end=None, alive=True):
        start = occurrence.start if start is None else start
        end = occurrence.end if end is None else end
        return Running(Session(start, end, occurrence.live, occurrence.key), alive)

    def test_completed_session_is_recorded(self):
        a = occ("a")
        self.tick(1000, [a], self.running(a))
        self.assertEqual(self.tick(4590, [a], self.running(a)), [])
        self.assertEqual(self.tick(4600, [a]), [Record(a.key, "completed")])
        self.assertEqual(self.tick(4700, [a]), [])

    def test_session_gone_early_is_exited_and_no_follow_on(self):
        a, b = occ("a", 1000, 4600), occ("b", 2000, 8000)
        self.tick(2500, [a, b], self.running(a))
        self.assertEqual(self.tick(3000, [a, b]), [Record(a.key, "exited"), ShowWindow("missed", b)])

    def test_covered_event_is_skipped_without_cue(self):
        a, c = occ("a", 1000, 4600), occ("c", 2000, 3000)
        self.assertEqual(self.tick(4590, [a, c], self.running(a)), [Record(c.key, "skipped")])
        self.assertEqual(self.tick(4600, [a, c]), [Record(a.key, "completed")])

    def test_open_upcoming_window_closes_when_a_session_covers_it(self):
        b = occ("b", 1000, 2000)
        self.tick(940, [b])
        spontaneous = occ("x", 950, 3000)
        self.assertEqual(self.tick(950, [b], self.running(spontaneous)), [CloseWindow(b.key), Record(b.key, "skipped")])

    def test_back_to_back_events_chain_without_cue(self):
        a, b = occ("a", 1000, 4600), occ("b", 4600, 8200)
        self.tick(940, [a, b])
        self.assertEqual(self.tick(1000, [a, b])[-1], StartSession(a, None))
        self.assertEqual(self.tick(4590, [a, b], self.running(a)), [])  # no cue for b at 4540
        self.assertEqual(self.tick(4600, [a, b]), [Record(a.key, "completed"), StartSession(b, 0)])
        self.assertEqual(self.tick(4700, [a, b], self.running(b, start=4600)), [])

    def test_waking_after_the_end_offers_the_follow_on_instead_of_starting_it(self):
        a, b = occ("a", 1000, 4600), occ("b", 4600, 8200)
        self.tick(2000, [a, b], self.running(a))
        self.last = 5800  # the PC slept from 2000 to 5800
        actions = self.s.tick(5800, [a, b], {}, None)
        self.assertEqual(actions, [Record(a.key, "completed"), ShowWindow("missed", b)])

    def test_follow_on_with_open_window_gets_missed_window_after_an_exit(self):
        b = occ("b", 1000, 2000)
        self.tick(940, [b])
        x = occ("x", 950, 1500)
        self.tick(1200, [b], self.running(x))  # b's window closed, b waits as the follow-on
        self.assertEqual(self.tick(1210, [b]), [Record(x.key, "exited"), ShowWindow("missed", b)])

    def test_a_closed_missed_window_does_not_start_as_a_follow_on(self):
        b = occ("b", 1000, 8000)
        self.assertEqual(self.tick(1500, [b]), [ShowWindow("missed", b)])
        self.assertEqual(self.s.answer(b.key, "closed", 1510), [])
        x = occ("x", 1600, 2000)  # a "Start now" session after closing b's window
        self.tick(1990, [b], self.running(x))
        self.assertEqual(self.tick(2000, [b]), [Record(x.key, "completed")])
        self.assertEqual(self.tick(2100, [b]), [])

    def test_two_overlapping_follow_ons_start_the_latest_ending(self):
        a, b, c = occ("a", 1000, 4600), occ("b", 2000, 6000), occ("c", 3000, 7000)
        self.tick(4590, [a, b, c], self.running(a))
        self.assertEqual(
            self.tick(4600, [a, b, c]),
            [Record(a.key, "completed"), Record(b.key, "skipped"), StartSession(c, 0)],
        )

    def test_restart_window_on_first_tick_when_guard_is_dead(self):
        a = occ("a")
        run = self.running(a, alive=False)
        shown = Occurrence(a.key, "", 1000, 4600, True, False)
        self.assertEqual(self.tick(2000, [a], run), [ShowWindow("restart", shown)])
        self.assertEqual(self.tick(2100, [a], run), [])
        self.assertEqual(self.s.answer(a.key, "start", 2100), [CloseWindow(a.key), ContinueSession(run.session)])

    def test_restart_decline_drops_session_and_records(self):
        a = occ("a")
        self.tick(2000, [a], self.running(a, alive=False))
        self.assertEqual(
            self.s.answer(a.key, "decline", 2010), [CloseWindow(a.key), DropSession(), Record(a.key, "declined")]
        )

    def test_restart_nerd_then_closed_declines(self):
        a = occ("a")
        self.tick(2000, [a], self.running(a, alive=False))
        self.s.answer(a.key, "nerd", 2010)
        self.assertEqual(
            self.s.answer(a.key, "closed", 2020), [CloseWindow(a.key), DropSession(), Record(a.key, "declined")]
        )

    def test_ignored_restart_window_closes_at_end_undoes_leftovers_and_records_nothing(self):
        a = occ("a")
        run = self.running(a, alive=False)
        self.tick(2000, [a], run)
        self.assertEqual(self.tick(4590, [a], run), [])
        self.assertEqual(self.tick(4600, [a]), [CloseWindow(a.key), DropSession()])
        self.assertEqual(self.tick(4700, [a]), [])

    def test_closed_restart_window_undoes_leftovers_at_end(self):
        a = occ("a")
        run = self.running(a, alive=False)
        self.tick(2000, [a], run)
        self.assertEqual(self.s.answer(a.key, "closed", 2010), [])
        self.assertEqual(self.tick(4600, [a]), [DropSession()])

    def test_restart_window_closes_when_the_session_is_resumed_elsewhere(self):
        a = occ("a")
        self.tick(2000, [a], self.running(a, alive=False))
        self.assertEqual(self.tick(2010, [a], self.running(a, alive=True)), [CloseWindow(a.key)])
        self.assertEqual(self.s.answer(a.key, "decline", 2020), [])  # a late click on the closed window
        self.assertEqual(self.tick(4590, [a], self.running(a, alive=True)), [])
        self.assertEqual(self.tick(4600, [a]), [Record(a.key, "completed")])

    def test_ignored_restart_does_not_block_the_next_event(self):
        a, b = occ("a", 1000, 4600), occ("b", 3000, 5000)
        run = self.running(a, alive=False)
        self.tick(2000, [a, b], run)
        self.assertEqual(self.tick(2940, [a, b], run), [PlayCue(b.key), ShowWindow("upcoming", b)])

    def test_background_restart_with_live_guard_shows_no_window(self):
        a = occ("a")
        self.assertEqual(self.tick(2000, [a], self.running(a)), [])

    def test_cli_session_without_occurrence_records_nothing(self):
        run = Running(Session(1000, 4600, True), True)
        self.tick(2000, [], run)
        self.assertEqual(self.tick(4600, []), [])

    def test_cli_session_with_dead_guard_offers_restart_without_record(self):
        run = Running(Session(1000, 4600, True), False)
        (action,) = self.tick(2000, [], run)
        self.assertEqual(action.kind, "restart")
        self.assertEqual(self.s.answer(action.occurrence.key, "decline", 2010)[-1], DropSession())


if __name__ == "__main__":
    unittest.main()
