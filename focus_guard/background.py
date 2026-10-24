"""The background process's scheduling loop: reads the files, asks the scheduler, carries out its actions.

Ports (NotifyUi, CuePlayer, spawn) keep it testable; app.py wires the real ones and calls tick() every second.
"""

import queue
import random
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

from .config import load_config_safe
from .events import Event, EventStore, Occurrence, new_event_id, occurrences
from .leftovers import undo_all
from .outcomes import OutcomeStore
from .paths import Paths
from .ports import CuePlayer, NotifyUi
from .procfiles import pid_alive
from .scheduler import (
    Action,
    Answer,
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
from .session import MAX_MINUTES, Session, clear_session, load_session
from .songs import RecentSongs, library, pick
from .starting import begin_session

CREATE_NO_WINDOW = 0x08000000
CONFIG_ERROR = "יש שגיאה ב-config.json: {}. ממשיכים עם ההגדרות הקודמות."
EVENTS_ERROR = "יש שגיאה ב-events.json: {}"
ACTION_ERROR = "תקלה בתזמון: {}"
FINAL_ANSWERS = ("start", "decline")
HANDOVER_SECONDS = 15.0  # how long a new session waits for the previous guard to finish exiting


class Background:
    def __init__(
        self,
        paths: Paths,
        scheduler: Scheduler,
        notify: NotifyUi,
        player: CuePlayer,
        spawn: Callable[[str], None],
        now: Callable[[], float] = time.time,
        guard_alive: Callable[[], bool] | None = None,
        songs_dir: Path | None = None,
        tz: tzinfo | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._paths, self._scheduler, self._notify, self._player = paths, scheduler, notify, player
        self._spawn, self._now, self._tz = spawn, now, tz
        self._guard_alive = guard_alive or (lambda: pid_alive(paths.guard_pid, "focus_guard.run_guard"))
        self._songs_dir = songs_dir or paths.root / "assets" / "songs"
        self._rng = rng or random.Random()
        self._events_store, self._outcomes = EventStore(paths.events), OutcomeStore(paths.outcomes)
        self._recent = RecentSongs(paths.recent_songs)
        self._events: list[Event] = []
        self._events_mtime: float | None = -1.0  # forces the first load
        self._songs: dict[str, Path] = {}  # the cue song of each occurrence, so its second cue is the same
        self._reported: set[str] = set()
        self._pending: list[tuple[Session, float]] = []  # sessions waiting for the previous guard to exit
        self.lock = threading.Lock()  # shared with start_now: a tick never sees half a start

    def tick(self) -> None:
        with self.lock:
            now = self._now()
            cfg, config_error = load_config_safe(self._paths.config, self._paths.config_last_good)
            if config_error:
                self._report(CONFIG_ERROR.format(config_error))
            songs = cfg.songs if cfg is not None else ()
            self._start_pending(now)
            for key, answer in self._notify.poll():
                self._carry_out(self._scheduler.answer(key, answer, now), now, songs)
            session = load_session(self._paths.session, now)
            running = Running(session, self._guard_alive()) if session is not None else None
            actions = self._scheduler.tick(now, self._occurrences(now), self._outcomes.load(), running)
            self._carry_out(actions, now, songs)

    def _occurrences(self, now: float) -> list[Occurrence]:
        mtime = self._events_store.mtime()
        if mtime != self._events_mtime:
            self._events_mtime = mtime
            self._events, errors = self._events_store.load()
            if errors:
                self._report(EVENTS_ERROR.format("; ".join(errors)))
        today = date.fromtimestamp(now)
        return occurrences(self._events, today - timedelta(days=1), today + timedelta(days=1), self._tz)

    def _report(self, text: str) -> None:
        if text not in self._reported:
            self._reported.add(text)
            self._notify.error(text)

    def _carry_out(self, actions: list[Action], now: float, songs: tuple[str, ...]) -> None:
        """Every action is tried: a failing one (a locked file) must not drop the session start after it."""
        for action in actions:
            try:
                self._do(action, now, songs)
            except Exception as error:
                self._report(ACTION_ERROR.format(error))

    def _do(self, action: Action, now: float, songs: tuple[str, ...]) -> None:
        if isinstance(action, PlayCue):
            self._play_cue(action.key, songs)
        elif isinstance(action, ShowWindow):
            self._notify.open(action.kind, action.occurrence)
        elif isinstance(action, CloseWindow):
            self._notify.close(action.key)
        elif isinstance(action, StartSession):
            occurrence = action.occurrence
            self._begin(Session(now, occurrence.end, occurrence.live, occurrence.key, action.grace), now)
        elif isinstance(action, ContinueSession):
            old = action.session
            self._begin(Session(now, old.end, old.live, old.occurrence, old.grace), now)
        elif isinstance(action, DropSession):
            clear_session(self._paths.session)
            undo_all(self._paths)
        elif isinstance(action, Record):
            self._outcomes.record(action.key, action.outcome)

    def _begin(self, session: Session, now: float) -> None:
        """A guard that is still exiting (its session just ended) would remove the new session.json on its way
        out, so the new session waits until it is gone (at most HANDOVER_SECONDS)."""
        if self._guard_alive():
            self._pending.append((session, now + HANDOVER_SECONDS))
            return
        begin_session(self._paths, session, self._spawn)

    def _start_pending(self, now: float) -> None:
        if not self._pending or (self._guard_alive() and now < self._pending[0][1]):
            return
        pending, self._pending = self._pending, []
        for session, _ in pending:
            begin_session(self._paths, session, self._spawn)

    def _play_cue(self, key: str, configured: tuple[str, ...]) -> None:
        song = self._songs.get(key)
        if song is None:
            choices = library(self._songs_dir, configured)
            if not choices:
                return
            song = pick(choices, self._recent.load(), self._rng)
            self._songs[key] = song
            self._recent.push(song)
        self._player.play_clip(song)


def start_now(
    paths: Paths, minutes: int, live: bool, now: float, spawn: Callable[[str], None], lock: threading.Lock
) -> str:
    """Start a session now and put it on the calendar as a one-off event (no cue). Returns its occurrence key.

    The session is written before the event: a tick that saw the event first would offer a missed start for it.
    """
    if not 1 <= minutes <= MAX_MINUTES:
        raise ValueError(f"minutes must be from 1 to {MAX_MINUTES}")
    with lock:
        if load_session(paths.session, now) is not None:
            raise ValueError("A session is already running.")
        store = EventStore(paths.events)
        store.check_writable()  # before the session: never a session without its calendar event
        started = datetime.fromtimestamp(now)
        event = Event(
            new_event_id(),
            "",
            started.date(),
            started.time().replace(second=0, microsecond=0),
            (started + timedelta(minutes=minutes)).time().replace(second=0, microsecond=0),
            frozenset(),
            cue=False,
            live=live,
        )
        key = f"{event.id}@{event.date.isoformat()}"
        begin_session(paths, Session(now, now + minutes * 60.0, live, key), spawn)
        store.add(event)
    return key


class _Window:
    def __init__(self, process: Any) -> None:
        self.process = process
        self.cancelled = threading.Event()


class SubprocessNotify:
    """Each notification window is a `focus_guard.ui notify` process; its stdout lines are the answers."""

    def __init__(self, popen: Callable[..., Any] = subprocess.Popen, python: str = sys.executable) -> None:
        self._popen, self._python = popen, python
        self._windows: dict[str, _Window] = {}
        self._answers: queue.Queue[tuple[str, Answer]] = queue.Queue()

    def _spawn(self, *args: str, capture: bool) -> Any:
        return self._popen(
            [self._python, "-m", "focus_guard.ui", *args],
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )

    def open(self, kind: str, occurrence: Occurrence) -> None:
        self.close(occurrence.key)
        process = self._spawn(
            "notify",
            f"--kind={kind}",
            f"--title={occurrence.title}",
            f"--start={occurrence.start}",
            f"--end={occurrence.end}",
            capture=True,
        )
        window = _Window(process)
        self._windows[occurrence.key] = window
        threading.Thread(target=self._read, args=(occurrence.key, window), daemon=True).start()

    def _read(self, key: str, window: _Window) -> None:
        final = False
        for raw in iter(window.process.stdout.readline, b""):
            answer = raw.decode("utf-8", errors="replace").strip()
            if answer in ("nerd", *FINAL_ANSWERS) and not window.cancelled.is_set():
                self._answers.put((key, answer))  # type: ignore[arg-type]  # checked just above
                final = final or answer in FINAL_ANSWERS
        if not final and not window.cancelled.is_set():
            self._answers.put((key, "closed"))

    def close(self, key: str) -> None:
        window = self._windows.pop(key, None)
        if window is None:
            return
        window.cancelled.set()
        if window.process.poll() is None:
            try:
                window.process.kill()
            except OSError:
                pass  # it ended meanwhile

    def poll(self) -> list[tuple[str, Answer]]:
        answers = []
        while True:
            try:
                answers.append(self._answers.get_nowait())
            except queue.Empty:
                return answers

    def error(self, text: str) -> None:
        self._spawn("error", f"--text={text}", capture=False)
