"""The app's side of updating: the update-only bridge, the daily check, app-ready.json and recovery at start.

The app always runs, so its bridge (port + 1) answers the extension also outside a session. The bridge only reports
the state and starts the fixed command `python -m focus_guard.update --apply`; the updater decides everything else.
"""

import threading
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import instance
from .events import Occurrence
from .jsonfile import read_json, write_json
from .paths import Paths
from .procfiles import pid_alive
from .server import make_update_server, serve_in_thread
from .session import load_session
from .update_apply import UPDATE_MUTEX, UPDATER_MUTEX, is_applying, recover
from .update_check import last_result, ready_version
from .update_gate import planned, refusal
from .version import VERSION

ATTEMPT_ENV = "WORKMODE_UPDATE_ATTEMPT"  # set by the updater when it starts the new version
CHECK_SLEEP = 3600.0  # the loop wakes hourly; check() itself asks GitHub at most once a day
HEAL_EVERY = 300.0  # seconds between two tries to undo an update whose updater was killed
HEAL_TRIES = 3  # then the popup keeps saying what failed, and Update.cmd can try again by hand


def write_ready(paths: Paths, pid: int, environ: Mapping[str, str]) -> None:
    """Tell a waiting updater this app is up: its version, pid and the update attempt that started it."""
    write_json(paths.app_ready, {"version": VERSION, "pid": pid, "attempt": environ.get(ATTEMPT_ENV, "")})


class UpdateService:
    def __init__(
        self,
        paths: Paths,
        spawn_update: Callable[[], None],
        now: Callable[[], float] = time.time,
        held: Callable[[str], bool] = instance.exists,
        guard_alive: Callable[[], bool] | None = None,
        upcoming: Callable[[float], Sequence[Occurrence]] | None = None,
        installed: str = VERSION,
        spawn_recover: Callable[[], None] = lambda: None,
    ) -> None:
        self._paths, self._spawn_update, self._now = paths, spawn_update, now
        self._held, self._spawn_recover = held, spawn_recover
        self._guard_alive = guard_alive or (lambda: pid_alive(paths.guard_pid, "focus_guard.run_guard"))
        self._upcoming = upcoming or planned(paths)
        self._installed = installed

    def _updater_running(self) -> bool:
        """Only looks at the mutexes (never creates one), so it can never make a session start fail."""
        if self._held(UPDATE_MUTEX) or self._held(UPDATER_MUTEX):
            return True
        if is_applying(self._paths):  # an unfinished journal and no updater: it was killed; undo what it left
            self._heal()
            return True
        return False

    def _heal(self) -> None:
        """Start the undo, at most every HEAL_EVERY and HEAL_TRIES times per update. Kept in a file: the undo
        restarts the app, and a rollback that can never finish must not restart it over and over."""
        now = self._now()
        journal = read_json(self._paths.update_journal)
        attempt = journal.get("attempt") if isinstance(journal, dict) else None
        last = read_json(self._paths.update_heal)
        same = isinstance(last, dict) and last.get("attempt") == attempt
        count = last.get("count") if same and isinstance(last.get("count"), int) else 0
        at = last.get("at") if same else None
        if count >= HEAL_TRIES or (isinstance(at, (int, float)) and at <= now < at + HEAL_EVERY):
            return
        write_json(self._paths.update_heal, {"attempt": attempt, "count": count + 1, "at": now})
        self._spawn_recover()

    def _blocked(self, now: float) -> str | None:
        return refusal(self._paths, now, self._guard_alive, self._upcoming)

    def status(self) -> dict:
        """What the popup shows. Reads files only; never asks GitHub."""
        now = self._now()
        result = last_result(self._paths)
        state, available = (result.state, result.available) if result else ("none", None)
        if state == "ready" and ready_version(self._paths) is None:
            state, available = "none", None
        if self._updater_running():
            state = "applying"
        session = load_session(self._paths.session, now)
        outcome = read_json(self._paths.update_result)
        valid = isinstance(outcome, dict) and isinstance(outcome.get("message"), str)
        return {
            "installed": self._installed,
            "available": available,
            "state": state,
            "checked_at": result.checked_at if result else None,
            "blocked": self._blocked(now),
            "session_until": session.end if session else None,
            "result": {"ok": outcome.get("ok") is True, "message": outcome["message"]} if valid else None,
        }

    def start_apply(self) -> bool:
        """Start the updater unless one runs or the gate says no. The updater checks the gate again itself."""
        if self._updater_running() or self._blocked(self._now()) is not None:
            return False
        self._spawn_update()
        return True


def run_checks(
    check_once: Callable[[], None], stop: threading.Event, log: Callable[[str], None], every: float = CHECK_SLEEP
) -> None:
    """The background check loop: a failing check is logged and the next one runs on time."""
    while True:
        try:
            check_once()
        except Exception:
            log("update check failed:\n" + traceback.format_exc())
        if stop.wait(every):
            return


def start_update_bridge(
    port: int, token: str, service: UpdateService, log: Callable[[str], None]
) -> ThreadingHTTPServer | None:
    """The update bridge, or None when the port is taken (logged; no other port is tried, Update.cmd still works)."""
    try:
        server = make_update_server(port, token, service.status, service.start_apply)
    except OSError as error:
        log(f"update bridge not started on port {port}: {error}")
        return None
    serve_in_thread(server)
    return server


class _NoProcesses:
    """recover(restart_app=False) touches no process; this makes sure of it."""

    def stop_app(self, timeout: float) -> bool:
        raise RuntimeError("not used at start")

    def start_app(self, attempt: str) -> None:
        raise RuntimeError("not used at start")

    def wait_ready(self, version: str, attempt: str, timeout: float) -> bool:
        raise RuntimeError("not used at start")

    def stop_new_app(self) -> None:
        raise RuntimeError("not used at start")

    def free_bytes(self, path: Path) -> int:
        raise RuntimeError("not used at start")

    def pip_install(self, requirements: Path) -> bool:
        raise RuntimeError("not used at start")


def recover_at_start(paths: Paths, claim: Callable[[str], Any | None], release_handle: Callable[[Any], None]) -> bool:
    """Undo an interrupted update before the app starts. True only when installed files were put back completely (the
    app must restart to run the old code); a rollback that could not finish never restarts it, so it cannot loop.
    Skipped while an updater runs: it is starting this app as the new version."""
    handle = claim(UPDATE_MUTEX)
    if handle is None:
        return False
    try:
        journal = read_json(paths.update_journal)
        files_changed = isinstance(journal, dict) and journal.get("phase") in ("backup_done", "swapped")
        undone = recover(paths, _NoProcesses(), restart_app=False) is not None
        return files_changed and undone and not is_applying(paths)
    finally:
        release_handle(handle)
