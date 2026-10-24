"""Logic behind the main window (session clock and calendar view). The window itself is a thin pywebview page."""

import threading
import time
from collections.abc import Callable
from datetime import date
from datetime import time as clock_time
from pathlib import Path
from typing import Any

from . import autostart
from .allowedlists import AllowedLists
from .background import start_now
from .busy import NoBusy
from .config import Config, hint_text, load_config_safe
from .eventedit import Context, EditRefused, Scope, change, create, delete, move
from .events import HHMM_RE, Edit, Event, EventError, EventStore, Occurrence, occurrences
from .launcher import spawn_module
from .paths import DEFAULT, Paths
from .ports import BusySource, ProgramSource
from .procfiles import pid_alive
from .session import Session, load_session
from .settings import bundled_songs, read_settings, save_settings
from .waiting import WaitingStore
from .winprograms import WinPrograms
from .ytnames import fetch_url

VIEWS = ("clock", "calendar")
SCOPES: tuple[Scope, ...] = ("this", "all")
BROKEN_EVENTS = "יש שגיאה ב-events.json. צריך לתקן אותה לפני שינויים."
BAD_REQUEST = "הבקשה לא תקינה."
FILE_KINDS = ("song", "video")


def _hhmm(moment: float) -> str:
    return time.strftime("%H:%M", time.localtime(moment))


def _seconds(milliseconds: Any) -> float | None:
    if isinstance(milliseconds, bool) or not isinstance(milliseconds, int | float):
        return None
    return milliseconds / 1000.0


def _clock_time(text: Any) -> clock_time:
    match = HHMM_RE.match(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError("expected HH:MM")
    return clock_time(int(match.group(1)), int(match.group(2)))


def _refused(message: str) -> dict:
    return {"ok": False, "message": message}


def _item(occurrence: Occurrence, event: Event, now: float, running_key: str) -> dict:
    """One occurrence as a FullCalendar event. The running and past ones cannot be dragged or resized."""
    running = occurrence.key == running_key
    past = occurrence.end <= now and not running
    classes = ["fg-event"] + ["fg-running"] * running + ["fg-past"] * past + ["fg-trial"] * (not event.live)
    fields = {
        "title": event.title,
        "date": occurrence.key.rpartition("@")[2],
        "start": event.start.strftime("%H:%M"),
        "end": event.end.strftime("%H:%M"),
        "days": sorted(event.days),
        "cue": event.cue,
        "live": event.live,
    }
    return {
        "id": occurrence.key,
        "title": event.title,
        "start": occurrence.start * 1000,
        "end": occurrence.end * 1000,
        "editable": not running and not past,
        "classNames": classes,
        "extendedProps": {"repeating": bool(event.days), "running": running, "past": past, "fields": fields},
    }


def _ignore_view(view: str) -> None:
    pass


def _no_play(path: Path) -> None:
    pass


def _no_choice(kind: str) -> str:
    return ""


class AppApi:
    def __init__(
        self,
        paths: Paths = DEFAULT,
        spawn: Callable[[str], None] | None = None,
        now: Callable[[], float] = time.time,
        guard_alive: Callable[[], bool] | None = None,
        set_view: Callable[[str], None] = _ignore_view,
        lock: "threading.Lock | None" = None,  # quoted: threading.Lock is a function at run time
        busy: BusySource | None = None,
        play: Callable[[Path], None] = _no_play,
        choose: Callable[[str], str] = _no_choice,
        apply_autostart: Callable[[Paths, bool], object] = autostart.apply,
        songs_dir: Path | None = None,
        programs: ProgramSource | None = None,
        fetch: Callable[[str], str] = fetch_url,
    ) -> None:
        self._paths, self._now, self._set_view = paths, now, set_view
        self._busy = busy or NoBusy()
        self._play, self._choose, self._apply_autostart = play, choose, apply_autostart
        self._bundled = songs_dir or paths.root / "assets" / "songs"
        self._guard_alive = guard_alive or (lambda: pid_alive(paths.guard_pid, "focus_guard.run_guard"))
        self._spawn = spawn or (lambda module: spawn_module(module, paths.root))
        self._allowed = AllowedLists(
            paths,
            programs or WinPrograms(),
            fetch,
            lambda: load_session(paths.session, self._now()) is not None,
        )
        self._lock = lock or threading.Lock()  # the background loop's lock, so a tick never sees half a start

    def status(self) -> dict:
        now = self._now()
        cfg, problem = load_config_safe(self._paths.config, self._paths.config_last_good)
        session = load_session(self._paths.session, now)
        if session is not None:
            return self._running(session, cfg, now)
        if cfg is None:
            return {"state": "problem", "message": problem}
        return {
            "state": "ready",
            "apps": [app.process for app in cfg.allowed_apps],
            "sites": len(cfg.allowed_sites),
            "hint": hint_text(cfg),
            "events_version": EventStore(self._paths.events).mtime(),
            "config_error": problem,
        }

    def _running(self, session: Session, cfg: Config | None, now: float) -> dict:
        grace = session.grace if session.grace is not None else (cfg.grace_seconds if cfg else 0)
        length = session.end - session.start
        return {
            "state": "running",
            "live": session.live,
            "minutes_left": int(-(-session.remaining(now) // 60)),
            "seconds_left": int(-(-session.remaining(now) // 1)),
            "ends_at": _hhmm(session.end),
            "progress": min(1.0, max(0.0, (now - session.start) / length)) if length > 0 else 1.0,
            "grace_left": max(0, int(-(-(session.start + grace - now) // 1))),
            "title": self._title(session.occurrence),
            "hint": hint_text(cfg) if cfg else "",
            "stalled": not self._guard_alive(),
            "waiting": self._waiting_names(),
            "muted": self._paths.mute_request.exists(),
            "occurrence": session.occurrence,
            "events_version": EventStore(self._paths.events).mtime(),
        }

    def _title(self, occurrence: str) -> str:
        event_id = occurrence.rpartition("@")[0]
        events, _ = EventStore(self._paths.events).load()
        return next((event.title for event in events if event.id == event_id), "")

    def _running_key(self, now: float) -> str:
        session = load_session(self._paths.session, now)
        return session.occurrence if session is not None else ""

    def week(self, start_ms: Any, end_ms: Any) -> list[dict]:
        """The occurrences that start on the shown days, and the busy blocks, as FullCalendar events."""
        start, end = _seconds(start_ms), _seconds(end_ms)
        if start is None or end is None or end <= start:
            return []
        now = self._now()
        running_key = self._running_key(now)
        events, _ = EventStore(self._paths.events).load()
        by_id = {event.id: event for event in events}
        found = occurrences(events, date.fromtimestamp(start), date.fromtimestamp(end - 1))
        items = [_item(o, by_id[o.key.rpartition("@")[0]], now, running_key) for o in found]
        busy = [
            {"start": low * 1000, "end": high * 1000, "display": "background", "classNames": ["fg-busy"]}
            for low, high in self._busy.busy(start, end)
        ]
        return items + busy

    def save_event(self, fields: Any, key: Any, scope: Any) -> dict:
        """A new event (empty key) or a change to the occurrence `key`; `scope` is "this" or "all"."""
        if not isinstance(fields, dict) or not isinstance(key, str) or scope not in SCOPES:
            return _refused(BAD_REQUEST)
        if not key:
            return self._edit(lambda events, ctx: create(fields, ctx))
        return self._edit(lambda events, ctx: change(events, key, fields, scope, ctx))

    def move_event(self, key: Any, day: Any, start: Any, end: Any, scope: Any, end_day: Any = None) -> dict:
        """A drag or a resize: the occurrence `key` now falls on `day` ("YYYY-MM-DD") from `start` to `end`, which
        is on `end_day` when given (a resize can reach into the next day's column)."""
        try:
            moved = (date.fromisoformat(day), _clock_time(start), _clock_time(end))
            last = date.fromisoformat(end_day) if end_day is not None else None
        except (TypeError, ValueError):
            return _refused(BAD_REQUEST)
        if not isinstance(key, str) or scope not in SCOPES:
            return _refused(BAD_REQUEST)
        return self._edit(lambda events, ctx: move(events, key, *moved, scope, ctx, last))

    def delete_event(self, key: Any, scope: Any) -> dict:
        if not isinstance(key, str) or scope not in SCOPES:
            return _refused(BAD_REQUEST)
        return self._edit(lambda events, ctx: delete(events, key, scope, ctx))

    def _edit(self, make: Callable[[list[Event], Context], Edit]) -> dict:
        """Read, change and write the events file under the background loop's lock."""
        store = EventStore(self._paths.events)
        with self._lock:
            now = self._now()
            try:
                store.check_writable()
                events, _ = store.load()
                store.commit(make(events, Context(now, self._running_key(now))))
            except EditRefused as error:
                return _refused(str(error))
            except EventError:
                return _refused(BROKEN_EVENTS)
        return {"ok": True}

    def settings(self) -> dict:
        """What the gear shows. Never the phrase."""
        return read_settings(self._paths, self._bundled)

    def save_settings(self, changes: Any) -> dict:
        if not isinstance(changes, dict):
            return _refused(BAD_REQUEST)
        running = load_session(self._paths.session, self._now()) is not None
        problem = save_settings(self._paths, changes, running)
        if problem:
            return _refused(problem)
        if "start_with_windows" in changes:
            self._apply_autostart(self._paths, bool(changes["start_with_windows"]))
        return {"ok": True}

    def allowed_view(self) -> dict:
        """What the allow-list screen shows."""
        return self._allowed.view()

    def allowed_preview_site(self, text: Any) -> dict:
        return self._allowed.site_preview(text) if isinstance(text, str) else _refused(BAD_REQUEST)

    def allowed_preview_youtube(self, text: Any) -> dict:
        return self._allowed.youtube_preview(text) if isinstance(text, str) else _refused(BAD_REQUEST)

    def allowed_find(self, query: Any) -> list[dict]:
        return self._allowed.find(query) if isinstance(query, str) else []

    def allowed_add(self, kind: Any, value: Any) -> dict:
        if not (isinstance(kind, str) and isinstance(value, str)):
            return _refused(BAD_REQUEST)
        return self._allowed.add(kind, value)

    def allowed_remove(self, kind: Any, value: Any) -> dict:
        if not (isinstance(kind, str) and isinstance(value, str)):
            return _refused(BAD_REQUEST)
        return self._allowed.remove(kind, value)

    def allowed_add_file(self, path: Any) -> dict:
        return self._allowed.add_file(path) if isinstance(path, str) else _refused(BAD_REQUEST)

    def choose_file(self, kind: Any) -> str:
        """A file picked in the system dialog ("song" or "video"); "" when cancelled."""
        return self._choose(kind) if kind in FILE_KINDS else ""

    def preview_song(self, song_id: Any) -> dict:
        """Play the first seconds of a song listed in settings (a bundled one or one the user added)."""
        listed = {song["id"] for song in read_settings(self._paths, self._bundled)["songs"]}
        if not isinstance(song_id, str) or song_id not in listed:
            return _refused(BAD_REQUEST)
        bundled = {song.name: song for song in bundled_songs(self._bundled)}
        self._play(bundled.get(song_id, Path(song_id)))
        return {"ok": True}

    def emergency_exit(self) -> dict:
        """Ask the guard for the phrase box (a trial ends at once); the guard watches for this file each tick."""
        if load_session(self._paths.session, self._now()) is None:
            return {"ok": False, "message": "No session is running."}
        self._paths.exit_request.parent.mkdir(parents=True, exist_ok=True)
        self._paths.exit_request.touch()
        return {"ok": True}

    def _waiting_names(self) -> list[str]:
        names = {window.process for window in WaitingStore(self._paths.waiting).load().values()}
        return sorted({name[:-4] if name.lower().endswith(".exe") else name for name in names})

    def set_view(self, view: Any) -> None:
        """The page switched between the clock and the calendar; the window changes size to match."""
        if view in VIEWS:
            self._set_view(view)

    def mute_waiting(self) -> dict:
        """Ask the guard to mute the waiting programs (it watches for this file each tick)."""
        if load_session(self._paths.session, self._now()) is None:
            return {"ok": False, "message": "No session is running."}
        self._paths.mute_request.parent.mkdir(parents=True, exist_ok=True)
        self._paths.mute_request.touch()
        return {"ok": True}

    def unmute_waiting(self) -> dict:
        """Withdraw the request; the guard gives every program its earlier mute state back."""
        self._paths.mute_request.unlink(missing_ok=True)
        return {"ok": True}

    def resume(self) -> dict:
        """Restart the guard of a session whose guard is not running. Never starts a new session."""
        if load_session(self._paths.session, self._now()) is None or self._guard_alive():
            return {"ok": False, "message": "No stopped session to resume."}
        self._spawn("focus_guard.run_guard")
        self._spawn("focus_guard.run_guardian")
        return {"ok": True, "message": "Resumed enforcement."}

    def start(self, minutes: Any, live: Any) -> dict:
        """ "Start now": a real one-off event on the calendar and its session. Resumes a session whose guard died."""
        try:
            count = int(minutes)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Enter the number of minutes."}
        now = self._now()
        cfg, problem = load_config_safe(self._paths.config, self._paths.config_last_good)
        if cfg is None:
            return {"ok": False, "message": f"Config problem: {problem}"}
        if load_session(self._paths.session, now) is not None:
            if self._guard_alive():
                return {"ok": False, "message": "A session is already running."}
            self._spawn("focus_guard.run_guard")
            self._spawn("focus_guard.run_guardian")
            return {"ok": True, "message": "Resumed enforcement."}
        try:
            start_now(self._paths, count, bool(live), now, self._spawn, self._lock)
        except ValueError as error:
            return {"ok": False, "message": str(error)}
        return {"ok": True, "message": ""}
