import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

from focus_guard.background import Background, SubprocessNotify, start_now
from focus_guard.events import EventStore, Occurrence
from focus_guard.outcomes import OutcomeStore
from focus_guard.paths import Paths
from focus_guard.scheduler import Scheduler
from focus_guard.session import Session, load_session, write_session
from tests.helpers import base_config
from tests.update_fixtures import UNFINISHED_JSON

START = datetime(2026, 10, 25, 14, 0).timestamp()
KEY = "math@2026-10-25"
OCC = Occurrence(KEY, "t", START, START + 60, True, True)


class FakeNotify:
    def __init__(self):
        self.opened, self.closed, self.errors, self.answers = [], [], [], []

    def open(self, kind, occurrence):
        self.opened.append((kind, occurrence.key))

    def close(self, key):
        self.closed.append(key)

    def poll(self):
        answers, self.answers = self.answers, []
        return answers

    def error(self, text):
        self.errors.append(text)


class FakePlayer:
    def __init__(self):
        self.played = []

    def play_clip(self, path, seconds=5.0):
        self.played.append(path)


class BackgroundCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.paths = Paths(self.root)
        self.paths.state.mkdir()
        video = self.root / "clip.mp4"
        video.write_bytes(b"x")
        self.paths.config.write_text(json.dumps(base_config(video)), encoding="utf-8")
        self.songs = self.root / "songs"
        self.songs.mkdir()
        for name in ("a.wav", "b.wav", "c.wav", "d.wav"):
            (self.songs / name).write_bytes(b"x")
        self.now, self.alive, self.spawned = START - 61, False, []  # no guard runs until a session starts
        self.notify, self.player = FakeNotify(), FakePlayer()
        self.bg = self.make()

    def make(self):
        return Background(
            self.paths,
            Scheduler(),
            self.notify,
            self.player,
            self.spawned.append,
            now=lambda: self.now,
            guard_alive=lambda: self.alive,
            songs_dir=self.songs,
        )

    def write_events(self, *events):
        self.paths.events.write_text(json.dumps({"version": 1, "events": list(events)}), encoding="utf-8")

    def math_event(self, **changes):
        return {"id": "math", "title": "מתמטיקה", "date": "2026-10-25", "start": "14:00", "end": "15:00", **changes}

    def run_to(self, target, step=5):
        while self.now < target:
            self.now = min(target, self.now + step)
            self.bg.tick()


class PlannedSessionTest(BackgroundCase):
    def test_planned_session_plays_same_song_twice_and_starts_guard(self):
        self.write_events(self.math_event(live=False))
        self.run_to(START - 60)
        self.assertEqual(self.notify.opened, [("upcoming", KEY)])
        self.assertEqual(len(self.player.played), 1)
        self.run_to(START)
        self.assertEqual(self.notify.closed, [KEY])
        self.assertEqual(self.player.played[0], self.player.played[1])
        self.assertEqual(self.spawned, ["focus_guard.run_guard", "focus_guard.run_guardian"])
        session = load_session(self.paths.session, START + 1)
        self.assertEqual(
            (session.occurrence, session.live, session.grace, session.end), (KEY, False, None, START + 3600)
        )

    def test_songs_rotate_between_sessions(self):
        self.write_events(*[self.math_event(id=f"m{day}", date=f"2026-10-{day}") for day in range(25, 29)])
        played = []
        for day in range(4):
            self.now = START + day * 86400 - 61
            self.player.played = []
            self.bg = self.make()
            self.run_to(START + day * 86400 - 60)
            played.append(self.player.played[0].name)
        self.assertEqual(len(set(played)), 4)

    def test_decline_answer_records_outcome_file(self):
        self.write_events(self.math_event())
        self.run_to(START - 60)
        self.notify.answers.append((KEY, "decline"))
        self.run_to(START - 55)
        self.assertEqual(OutcomeStore(self.paths.outcomes).load(), {KEY: "declined"})
        self.run_to(START + 10)
        self.assertEqual(self.spawned, [])

    def test_events_error_shown_once(self):
        self.paths.events.write_text('{"events": [{"id": "x", "end": "nope"}]}', encoding="utf-8")
        for _ in range(5):
            self.bg.tick()
        self.assertEqual(len(self.notify.errors), 1)
        self.assertIn("events.json", self.notify.errors[0])

    def test_broken_config_error_shown_once_and_session_still_starts(self):
        self.write_events(self.math_event())
        self.bg.tick()  # a good config: its copy is kept
        self.paths.config.write_text("{nope", encoding="utf-8")
        self.run_to(START)
        self.assertEqual(len(self.notify.errors), 1)
        self.assertIn("config.json", self.notify.errors[0])
        self.assertIn("ממשיכים עם ההגדרות הקודמות", self.notify.errors[0])
        self.assertEqual(load_session(self.paths.session, START + 1).occurrence, KEY)

    def test_a_failing_action_does_not_stop_the_next_one(self):
        self.write_events(self.math_event(end="14:02"), self.math_event(id="next", start="14:02", end="14:30"))
        self.run_to(START)
        self.run_to(START + 115, step=5)

        def broken(key, outcome):
            raise PermissionError("outcomes.json is locked")

        self.bg._outcomes.record = broken
        self.paths.session.unlink()
        self.run_to(START + 125, step=5)
        self.assertEqual(load_session(self.paths.session, START + 126).occurrence, "next@2026-10-25")
        self.assertEqual(len(self.notify.errors), 1)
        self.assertIn("outcomes.json is locked", self.notify.errors[0])

    def test_completed_session_is_recorded(self):
        self.write_events(self.math_event())
        self.run_to(START)
        self.run_to(START + 3595, step=20)
        self.paths.session.unlink()  # the guard clears session.json at the end
        self.now = START + 3601
        self.bg.tick()
        self.assertEqual(OutcomeStore(self.paths.outcomes).load(), {KEY: "completed"})

    def test_follow_on_waits_for_the_old_guard_to_exit(self):
        self.write_events(self.math_event(end="14:02"), self.math_event(id="next", start="14:02", end="14:30"))
        self.run_to(START)
        self.alive = True  # A's guard runs
        self.run_to(START + 115, step=5)
        self.paths.session.unlink()  # A's guard reached the end and cleared its session; it is still exiting
        self.run_to(START + 125, step=5)
        self.assertEqual(len(self.spawned), 2)  # B not started over the exiting guard
        self.alive = False
        self.run_to(START + 130, step=5)
        self.assertEqual(len(self.spawned), 4)
        self.assertEqual(load_session(self.paths.session, START + 131).occurrence, "next@2026-10-25")

    def test_a_planned_start_during_an_update_waits_and_starts_after_it(self):
        self.write_events(self.math_event())
        self.paths.update_journal.write_text(UNFINISHED_JSON, encoding="utf-8")
        self.run_to(START + 10)
        self.assertEqual(self.spawned, [])
        self.assertFalse(self.paths.session.exists())
        self.paths.update_journal.unlink()
        self.run_to(START + 20)
        self.assertEqual(self.spawned, ["focus_guard.run_guard", "focus_guard.run_guardian"])
        self.assertEqual(load_session(self.paths.session, START + 21).occurrence, KEY)

    def test_follow_on_starts_anyway_when_the_old_guard_hangs(self):
        self.write_events(self.math_event(end="14:02"), self.math_event(id="next", start="14:02", end="14:30"))
        self.run_to(START)
        self.alive = True
        self.run_to(START + 115, step=5)
        self.paths.session.unlink()
        self.run_to(START + 145, step=5)
        self.assertEqual(len(self.spawned), 4)


class RestartTest(BackgroundCase):
    def setUp(self):
        super().setUp()
        self.now, self.alive = START + 600, False
        write_session(self.paths.session, Session(START, START + 3600, True, KEY))

    def test_restart_continue_rewrites_start_and_spawns(self):
        self.bg.tick()
        self.assertEqual(self.notify.opened, [("restart", KEY)])
        self.notify.answers.append((KEY, "start"))
        self.now += 5
        self.bg.tick()
        session = load_session(self.paths.session, self.now)
        self.assertEqual((session.start, session.end, session.occurrence), (self.now, START + 3600, KEY))
        self.assertEqual(self.spawned, ["focus_guard.run_guard", "focus_guard.run_guardian"])

    def test_restart_decline_drops_session_and_records(self):
        self.bg.tick()
        self.notify.answers.append((KEY, "decline"))
        self.now += 5
        self.bg.tick()
        self.assertFalse(self.paths.session.exists())
        self.assertEqual(OutcomeStore(self.paths.outcomes).load(), {KEY: "declined"})
        self.assertEqual(self.spawned, [])


class StartNowTest(BackgroundCase):
    def test_start_now_writes_session_before_event(self):
        seen = []

        def spawn(module):
            seen.append((EventStore(self.paths.events).load()[0], self.paths.session.exists()))

        key = start_now(self.paths, 25, True, START + 30, spawn, self.bg.lock)
        self.assertEqual(seen[0], ([], True))
        events, errors = EventStore(self.paths.events).load()
        self.assertEqual((len(events), errors), (1, []))
        self.assertEqual(key, f"{events[0].id}@2026-10-25")
        self.assertEqual((events[0].start.strftime("%H:%M"), events[0].end.strftime("%H:%M")), ("14:00", "14:25"))
        self.assertFalse(events[0].cue)
        session = load_session(self.paths.session, START + 60)
        self.assertEqual((session.occurrence, session.end, session.live), (key, START + 30 + 1500, True))

    def test_start_now_then_ticks_offer_nothing(self):
        self.now = START + 30
        start_now(self.paths, 25, False, self.now, self.spawned.append, self.bg.lock)
        self.alive = True  # the guard it spawned
        self.run_to(START + 120)
        self.assertEqual((self.notify.opened, self.player.played), ([], []))

    def test_start_now_refuses_bad_minutes_and_a_running_session(self):
        for bad in (0, 721):
            with self.assertRaises(ValueError):
                start_now(self.paths, bad, True, START, self.spawned.append, self.bg.lock)
        start_now(self.paths, 10, True, START, self.spawned.append, self.bg.lock)
        with self.assertRaises(ValueError):
            start_now(self.paths, 10, True, START + 5, self.spawned.append, self.bg.lock)

    def test_start_now_refuses_when_events_file_is_broken(self):
        self.paths.events.write_text("{nope", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            start_now(self.paths, 25, True, START, self.spawned.append, self.bg.lock)
        self.assertIn("events.json", str(caught.exception))
        self.assertEqual((self.paths.events.read_text(encoding="utf-8"), self.spawned), ("{nope", []))
        self.assertFalse(self.paths.session.exists())

    def test_tick_waits_for_start_now_lock(self):
        self.bg.lock.acquire()
        worker = threading.Thread(target=self.bg.tick)
        worker.start()
        time.sleep(0.1)
        self.assertTrue(worker.is_alive())
        self.bg.lock.release()
        worker.join(2)
        self.assertFalse(worker.is_alive())


class FakeStdout:
    """Gives its lines, then blocks until the process is killed (like a window left open)."""

    def __init__(self, lines, ended):
        self._lines, self._ended = [f"{line}\n".encode() for line in lines], ended

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        self._ended.wait(5)
        return b""


class FakeProcess:
    def __init__(self, lines, stays_open):
        self._ended = threading.Event()
        if not stays_open:
            self._ended.set()
        self.stdout = FakeStdout(lines, self._ended)

    def poll(self):
        return 1 if self._ended.is_set() else None

    def kill(self):
        self._ended.set()


class SubprocessNotifyTest(unittest.TestCase):
    def make(self, lines, stays_open=False):
        self.commands = []

        def popen(command, **_):
            self.commands.append(command)
            return FakeProcess(lines, stays_open)

        return SubprocessNotify(popen=popen, python="py")

    def wait_answers(self, notify, count):
        answers = []
        for _ in range(200):
            answers += notify.poll()
            if len(answers) >= count:
                break
            time.sleep(0.01)
        return answers

    def test_lines_become_answers_for_the_key(self):
        notify = self.make(["nerd", "decline"])
        notify.open("upcoming", OCC)
        self.assertEqual(self.wait_answers(notify, 2), [(KEY, "nerd"), (KEY, "decline")])
        self.assertIn("--kind=upcoming", self.commands[0])

    def test_exit_without_a_choice_is_closed(self):
        notify = self.make([])
        notify.open("missed", OCC)
        self.assertEqual(self.wait_answers(notify, 1), [(KEY, "closed")])

    def test_window_closed_by_the_scheduler_reports_nothing(self):
        notify = self.make([], stays_open=True)
        notify.open("upcoming", OCC)
        notify.close(KEY)
        time.sleep(0.1)
        self.assertEqual(notify.poll(), [])


if __name__ == "__main__":
    unittest.main()
