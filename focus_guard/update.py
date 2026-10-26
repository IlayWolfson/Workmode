"""python -m focus_guard.update --apply | --check. The one entry point for the popup's button and Update.cmd.

--apply: one updater at a time (UPDATER_MUTEX, held for the whole run). First an interrupted update is undone, then
the gate decides (no session, none planned within 10 minutes, not a git clone), then a verified release is
downloaded and its packages installed if needed, and the gate is asked again just before the files change.
UPDATE_MUTEX, the lock a session start takes too, is held only around the undo and the swap, so a session cannot
begin while files are being replaced and is never held up by a download or pip.
"""

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

from . import instance
from .events import Occurrence
from .jsonfile import read_json
from .paths import DEFAULT, Paths
from .procfiles import pid_alive
from .update_apply import (
    QUIT_EVENT,
    UPDATE_MUTEX,
    UPDATER_MUTEX,
    Machine,
    WindowsMachine,
    apply,
    prepare,
    recover,
)
from .update_check import Http, UrllibHttp, check, load_staged
from .update_gate import planned, refusal
from .update_trust import PUBLIC_KEY
from .version import VERSION

__all__ = ["QUIT_EVENT", "UPDATE_MUTEX", "UPDATER_MUTEX", "main"]

BUSY = "כבר מתעדכן"
UP_TO_DATE = "יש לך את הגרסה העדכנית"
REFUSED = "העדכון נדחה: הוא לא חתום כמו שצריך"
CHECK_FAILED = "לא הצלחתי לבדוק אם יש עדכון; נסו שוב מאוחר יותר"
AVAILABLE = "גרסה {} זמינה (יש לך {})"


def main(
    argv: list[str] | None = None,
    *,
    paths: Paths = DEFAULT,
    http: Http | None = None,
    machine: Machine | None = None,
    claim: Callable[[str], Any | None] = instance.claim,
    release_handle: Callable[[Any], None] = instance.release,
    now: Callable[[], float] = time.time,
    out: Callable[[str], None] = print,
    guard_alive: Callable[[], bool] | None = None,
    upcoming: Callable[[float], Sequence[Occurrence]] | None = None,
    installed: str = VERSION,
    public_key: bytes = PUBLIC_KEY,
) -> int:
    parser = argparse.ArgumentParser(prog="focus_guard.update")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply", action="store_true", help="install the newest signed release now")
    action.add_argument("--check", action="store_true", help="ask GitHub whether a newer release exists")
    action.add_argument("--recover", action="store_true", help="only undo an update that was interrupted")
    args = parser.parse_args(argv)
    http = http or UrllibHttp()
    if args.check:
        result = check(paths, http, now(), installed, force=True, public_key=public_key)
        out(AVAILABLE.format(result.available, installed) if result.state == "ready" else _not_ready(result.state))
        return 0
    updater = _Updater(
        paths,
        http,
        machine or WindowsMachine(paths, QUIT_EVENT),
        claim,
        release_handle,
        now,
        out,
        guard_alive or (lambda: pid_alive(paths.guard_pid, "focus_guard.run_guard")),
        upcoming or planned(paths),
        installed,
        public_key,
    )
    return updater.recover_only() if args.recover else updater.run()


def _not_ready(state: str) -> str:
    return {"none": UP_TO_DATE, "refused": REFUSED}.get(state, CHECK_FAILED)


class _Updater:
    def __init__(
        self,
        paths: Paths,
        http: Http,
        machine: Machine,
        claim: Callable[[str], Any | None],
        release_handle: Callable[[Any], None],
        now: Callable[[], float],
        out: Callable[[str], None],
        guard_alive: Callable[[], bool],
        upcoming: Callable[[float], Sequence[Occurrence]],
        installed: str,
        public_key: bytes,
    ) -> None:
        self._paths, self._http, self._machine = paths, http, machine
        self._claim, self._release, self._now, self._out = claim, release_handle, now, out
        self._guard_alive, self._upcoming = guard_alive, upcoming
        self._installed, self._key = installed, public_key

    def _refusal(self) -> str | None:
        return refusal(self._paths, self._now(), self._guard_alive, self._upcoming)

    def run(self) -> int:
        return self._as_the_only_updater(self._update)

    def recover_only(self) -> int:
        """Undo an update whose updater was killed (the app starts this when it finds such a journal)."""
        return self._as_the_only_updater(self._undo_only)

    def _undo_only(self) -> int:
        busy = self._undo_then(lambda: None)
        if busy is not None:
            self._out(busy)
            return 1
        return 0

    def _as_the_only_updater(self, work: Callable[[], int]) -> int:
        runner = self._claim(UPDATER_MUTEX)
        if runner is None:
            self._out(BUSY)
            return 1
        try:
            return work()
        finally:
            self._release(runner)

    def _undo_then(self, ask: Callable[[], str | None]) -> str | None:
        """Under the session lock: undo an interrupted update, then return what `ask` says. BUSY if the lock is held."""
        handle = self._claim(UPDATE_MUTEX)
        if handle is None:
            return BUSY
        try:
            recovered = recover(self._paths, self._machine, restart_app=True)
            if recovered is not None:
                self._out(recovered)
            return ask()
        finally:
            self._release(handle)

    def _update(self) -> int:
        reason = self._undo_then(self._refusal)
        if reason is not None:
            self._out(reason)
            return 1
        return self._install()

    def _install(self) -> int:
        staged = load_staged(self._paths, self._installed, self._key)
        if staged is None:  # the download may take a while, so it runs without blocking session starts
            result = check(self._paths, self._http, self._now(), self._installed, force=True, public_key=self._key)
            staged = load_staged(self._paths, self._installed, self._key)
            if staged is None:
                self._out(_not_ready(result.state))
                return 0 if result.state == "none" else 1
        release, staging = staged
        problem = prepare(self._paths, release, staging, self._machine)  # pip, also outside the session lock
        if problem is not None:
            self._out(problem)
            return 1
        handle = self._claim(UPDATE_MUTEX)
        if handle is None:
            self._out(BUSY)
            return 1
        try:
            reason = self._refusal()
            if reason is not None:
                self._out(reason)
                return 1
            self._out(apply(self._paths, release, staging, self._machine, self._installed))
        finally:
            self._release(handle)
        result_file = read_json(self._paths.update_result)
        return 0 if isinstance(result_file, dict) and result_file.get("ok") is True else 1


if __name__ == "__main__":
    sys.exit(main())
