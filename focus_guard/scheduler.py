"""When planned sessions cue, ask and start. Pure: the caller passes the time, the occurrences, the outcomes and
the running session, and carries out the returned actions (background.py)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .events import Occurrence
from .session import Session

CUE_LEAD = 60.0  # the cue song and the window come this many seconds before the start
SLEEP_GAP = 30.0  # a longer pause between ticks means the PC was asleep
END_SLACK = 5.0  # a session that disappears closer than this to its end completed; earlier, it was exited
RESTART_KEY = "restart"  # window key for a resumed session that has no occurrence (started from the CLI)

WindowKind = Literal["upcoming", "missed", "restart"]
Answer = Literal["start", "decline", "nerd", "closed"]


@dataclass(frozen=True)
class PlayCue:
    key: str


@dataclass(frozen=True)
class ShowWindow:
    kind: WindowKind
    occurrence: Occurrence


@dataclass(frozen=True)
class CloseWindow:
    key: str


@dataclass(frozen=True)
class StartSession:
    occurrence: Occurrence
    grace: int | None  # None: the configured grace period


@dataclass(frozen=True)
class ContinueSession:
    session: Session


@dataclass(frozen=True)
class DropSession:
    pass


@dataclass(frozen=True)
class Record:
    key: str
    outcome: str


Action = PlayCue | ShowWindow | CloseWindow | StartSession | ContinueSession | DropSession | Record


@dataclass(frozen=True)
class Running:
    session: Session
    guard_alive: bool


# Per-occurrence state. "upcoming"/"missed"/"restart" have an open window; "-nerd": it shows the nerd step.
WAITING_FOR_START = ("upcoming", "upcoming-nerd")
OPEN = ("upcoming", "upcoming-nerd", "missed", "missed-nerd", "restart", "restart-nerd")
EVENT_WINDOWS = ("upcoming", "upcoming-nerd", "missed", "missed-nerd")  # windows that belong to a calendar event


class Scheduler:
    def __init__(self) -> None:
        self._state: dict[str, str] = {}
        self._shown: dict[str, Occurrence] = {}
        self._last_tick: float | None = None
        self._first = True
        self._previous: Session | None = None  # the session running at the last tick
        self._restart: Session | None = None  # a session found after a restart, waiting for "Continue"

    def tick(
        self, now: float, occurrences: Sequence[Occurrence], outcomes: Mapping[str, str], running: Running | None
    ) -> list[Action]:
        slept = self._last_tick is not None and now - self._last_tick > SLEEP_GAP
        since, self._last_tick = self._last_tick, now
        first, self._first = self._first, False
        if running is not None and first and not running.guard_alive:
            return self._offer_restart(running.session)
        actions: list[Action] = self._close_vanished(occurrences)
        if self._restart is not None:
            if running is not None and running.session != self._restart:
                self._restart = None  # another session replaced it
            elif running is not None and running.guard_alive:
                actions += self._close_restart()  # resumed from the main window: the offer is answered
            else:
                running = None  # the stopped session enforces nothing while it waits for an answer
                actions += self._expire_restart(now)
        if running is not None:
            self._previous = running.session
            return actions + self._while_running(occurrences, outcomes, running.session)
        if self._previous is not None:
            actions += self._after_running(now, occurrences, outcomes, slept_through_end=slept)
            if actions and isinstance(actions[-1], StartSession):
                return actions
        for occurrence in occurrences:
            if occurrence.key in outcomes or self._state.get(occurrence.key) == "done":
                continue
            actions.extend(self._step(occurrence, now, slept, since))
            if actions and isinstance(actions[-1], StartSession):
                break  # the next tick sees the new session; other events are judged against it
        return actions

    def _close_vanished(self, occurrences: Sequence[Occurrence]) -> list[Action]:
        """An event deleted or moved in the calendar takes its open window with it; nothing starts or is recorded."""
        present = {occurrence.key for occurrence in occurrences}
        vanished = [key for key, state in self._state.items() if state in EVENT_WINDOWS and key not in present]
        for key in vanished:
            self._state[key] = "done"
        return [CloseWindow(key) for key in vanished]

    def _step(self, occurrence: Occurrence, now: float, slept: bool, since: float | None) -> list[Action]:
        key, state = occurrence.key, self._state.get(occurrence.key)
        if now >= occurrence.end:
            self._state[key] = "done"
            return [CloseWindow(key)] if state in EVENT_WINDOWS else []  # e.g. the PC slept through the event
        if state in WAITING_FOR_START and slept and since is not None and since < occurrence.start <= now:
            return [CloseWindow(key), *self._show("missed", occurrence)]
        if state is None:
            if now >= occurrence.start:
                return self._show("missed", occurrence)
            if now >= occurrence.start - CUE_LEAD:
                return [PlayCue(key)] * occurrence.cue + self._show("upcoming", occurrence)
            return []
        if state in WAITING_FOR_START and now >= occurrence.start:
            if state == "upcoming-nerd":
                return [CloseWindow(key), *self._finish(key, "declined")]
            return [CloseWindow(key), *self._start(occurrence, cue=True)]
        return []

    def _available(self, occurrence: Occurrence, outcomes: Mapping[str, str]) -> bool:
        return occurrence.key not in outcomes and self._state.get(occurrence.key) != "done"

    def _while_running(
        self, occurrences: Sequence[Occurrence], outcomes: Mapping[str, str], session: Session
    ) -> list[Action]:
        """No cue and no window while a session runs. Events inside it are skipped; later ones wait for its end."""
        actions: list[Action] = []
        for occurrence in occurrences:
            key = occurrence.key
            if (
                not self._available(occurrence, outcomes)
                or key == session.occurrence
                or occurrence.start >= session.end
            ):
                continue
            close: list[Action] = [CloseWindow(key)] if self._state.get(key) in OPEN else []
            if session.start < occurrence.end <= session.end:
                actions += [*close, *self._finish(key, "skipped")]
            elif occurrence.end > session.end and close:
                self._state[key] = "follow-on"
                actions += close
        return actions

    def _after_running(
        self, now: float, occurrences: Sequence[Occurrence], outcomes: Mapping[str, str], slept_through_end: bool
    ) -> list[Action]:
        previous, self._previous = self._previous, None
        assert previous is not None
        completed = now >= previous.end - END_SLACK
        actions: list[Action] = []
        if previous.occurrence:
            actions += self._finish(previous.occurrence, "completed" if completed else "exited")
        if not completed or slept_through_end:
            # after an emergency exit, or waking from sleep, events already started get the missed-start window:
            # never minimize windows under someone who just came back
            for key, state in list(self._state.items()):
                if state == "follow-on":
                    del self._state[key]
            return actions
        follow_ons = [
            o
            for o in occurrences
            if self._available(o, outcomes) and self._state.get(o.key) != "closed" and o.start <= now < o.end
        ]  # a missed-start window the user closed meant "no"
        if not follow_ons:
            return actions
        chosen = max(follow_ons, key=lambda occurrence: occurrence.end)
        for occurrence in follow_ons:
            if occurrence is not chosen:
                actions += self._finish(occurrence.key, "skipped")
        self._state[chosen.key] = "done"
        return [*actions, StartSession(chosen, 0)]

    def _offer_restart(self, session: Session) -> list[Action]:
        self._restart = session
        key = session.occurrence or RESTART_KEY
        return self._show("restart", Occurrence(key, "", session.start, session.end, session.live, False))

    def _expire_restart(self, now: float) -> list[Action]:
        assert self._restart is not None
        if now < self._restart.end:
            return []
        # ignored or closed: nothing starts, but what the stopped guard left minimized or muted comes back
        return [*self._close_restart(), DropSession()]

    def _close_restart(self) -> list[Action]:
        assert self._restart is not None
        key = self._restart.occurrence or RESTART_KEY
        self._restart = None
        was_open = self._state.get(key) in OPEN
        self._state[key] = "done"
        return [CloseWindow(key)] if was_open else []

    def _show(self, kind: WindowKind, occurrence: Occurrence) -> list[Action]:
        self._state[occurrence.key], self._shown[occurrence.key] = kind, occurrence
        return [ShowWindow(kind, occurrence)]

    def _start(self, occurrence: Occurrence, cue: bool) -> list[Action]:
        self._state[occurrence.key] = "done"
        actions: list[Action] = [PlayCue(occurrence.key)] if cue and occurrence.cue else []
        return [*actions, StartSession(occurrence, None)]

    def _finish(self, key: str, outcome: str) -> list[Action]:
        self._state[key] = "done"
        return [Record(key, outcome)]

    def answer(self, key: str, answer: Answer, now: float) -> list[Action]:
        state, occurrence = self._state.get(key), self._shown.get(key)
        if occurrence is None or state is None or state == "done":
            return []
        nerd = state.endswith("-nerd")
        if answer == "nerd":
            self._state[key] = state if nerd else f"{state}-nerd"
            return []
        restart = state.startswith("restart")
        if answer == "start":
            if restart:
                return [CloseWindow(key), *self._continue()]
            return [CloseWindow(key), *self._start(occurrence, cue=state in WAITING_FOR_START)]
        if answer == "decline" or nerd:  # closing the nerd step counts as the red button
            if restart:
                return [CloseWindow(key), *self._drop()]
            return [CloseWindow(key), *self._finish(key, "declined")]
        if state in ("missed", "restart"):  # the user closed the window: nothing starts
            self._state[key] = "closed"
        return []

    def _continue(self) -> list[Action]:
        session, self._restart = self._restart, None
        assert session is not None
        self._state[session.occurrence or RESTART_KEY] = "done"
        return [ContinueSession(session)]

    def _drop(self) -> list[Action]:
        session, self._restart = self._restart, None
        assert session is not None
        self._state[session.occurrence or RESTART_KEY] = "done"
        return [DropSession(), *([Record(session.occurrence, "declined")] if session.occurrence else [])]
