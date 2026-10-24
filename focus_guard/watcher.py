"""Pure window-watching logic: snapshots in, events out. No Windows calls."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

MIN_AGE = 1.0  # seconds a window must exist before it is tracked (ignores splash screens)
EVENT_COOLDOWN = 2.0  # minimum gap between repeated state events for one window
MAX_REPEATS = 3  # state events for one change; after that the new state is accepted


@dataclass(frozen=True)
class WinInfo:
    hwnd: int
    pid: int
    process: str
    title: str
    state: str


@dataclass(frozen=True)
class Event:
    kind: str
    hwnd: int
    pid: int
    process: str
    state: str = ""
    others: int = 0  # closed events: other tracked windows of the same program still open


class Watcher:
    def __init__(self, allowed: frozenset[str], protected: frozenset[str], grace_until: float = 0.0) -> None:
        self._allowed = allowed
        self._protected = protected
        self._grace_until = grace_until  # before this, allowed windows only set their baseline
        self._first_seen: dict[int, float] = {}  # hwnd -> time first seen (allowed windows)
        self._tracked: dict[int, tuple[str, int, str]] = {}  # hwnd -> (process, pid, baseline state)
        self._blocked: dict[int, bool] = {}  # hwnd -> was minimized when last seen
        self._last_event: dict[int, float] = {}  # hwnd -> time of the last state event
        self._repeats: dict[int, int] = {}  # hwnd -> state events fired since the window last matched its baseline

    def step(
        self, windows: Iterable[WinInfo], now: float, still_exists: Callable[[int], bool] | None = None
    ) -> list[Event]:
        events, present = [], set()
        for window in windows:
            name = window.process.lower()
            if name in self._protected:
                continue
            present.add(window.hwnd)
            if name in self._allowed:
                events.extend(self._allowed_window(window, now))
            else:
                events.extend(self._blocked_window(window, now))
        events.extend(self._disappeared(present, still_exists or (lambda hwnd: False), now))
        for hwnd in [hwnd for hwnd in self._blocked if hwnd not in present]:
            del self._blocked[hwnd]
        return events

    def _allowed_window(self, window: WinInfo, now: float) -> list[Event]:
        first = self._first_seen.setdefault(window.hwnd, now)
        if now < self._grace_until:
            self._adopt(window)
            return []
        if window.hwnd not in self._tracked:
            # A minimized window is never a baseline: restoring cannot bring it back to "minimized".
            if now - first >= MIN_AGE and window.state != "minimized":
                self._tracked[window.hwnd] = (window.process, window.pid, window.state)
            return []
        process, pid, baseline = self._tracked[window.hwnd]
        if window.state == baseline:
            self._repeats.pop(window.hwnd, None)
            return []
        last = self._last_event.get(window.hwnd)
        if last is not None and now - last < EVENT_COOLDOWN:
            return []
        repeats = self._repeats.get(window.hwnd, 0)
        if repeats >= MAX_REPEATS:
            self._accept_state(window, process, pid)
            return []
        self._repeats[window.hwnd] = repeats + 1
        self._last_event[window.hwnd] = now
        kind = "minimized" if window.state == "minimized" else "resized"
        return [Event(kind, window.hwnd, window.pid, window.process, state=baseline)]

    def _accept_state(self, window: WinInfo, process: str, pid: int) -> None:
        """The restore did not take (or dry-run): stop repeating and treat the new state as normal."""
        self._repeats.pop(window.hwnd, None)
        if window.state == "minimized":
            del self._tracked[window.hwnd]  # re-tracked once the window is seen restored
        else:
            self._tracked[window.hwnd] = (process, pid, window.state)

    def _adopt(self, window: WinInfo) -> None:
        """Grace period: the window's current state silently becomes its baseline."""
        self._repeats.pop(window.hwnd, None)
        if window.state == "minimized":
            self._tracked.pop(window.hwnd, None)  # a minimized window is never a baseline
        else:
            self._tracked[window.hwnd] = (window.process, window.pid, window.state)

    def _blocked_window(self, window: WinInfo, now: float) -> list[Event]:
        minimized = window.state == "minimized"
        was_minimized = self._blocked.get(window.hwnd)
        self._blocked[window.hwnd] = minimized
        if was_minimized is None:
            return [Event("blocked_app", window.hwnd, window.pid, window.process, state=window.state)]
        if was_minimized and not minimized:
            return [Event("blocked_reopened", window.hwnd, window.pid, window.process)]
        return []

    def _disappeared(self, present: set[int], still_exists: Callable[[int], bool], now: float) -> list[Event]:
        gone = []
        for hwnd in [hwnd for hwnd in self._tracked if hwnd not in present]:
            if still_exists(hwnd):
                continue  # hidden or cloaked (another virtual desktop), not closed
            process, pid, _ = self._tracked.pop(hwnd)
            self._first_seen.pop(hwnd, None)
            self._last_event.pop(hwnd, None)
            self._repeats.pop(hwnd, None)
            if now >= self._grace_until:
                gone.append((hwnd, process, pid))
        for hwnd in [hwnd for hwnd in self._first_seen if hwnd not in present and hwnd not in self._tracked]:
            del self._first_seen[hwnd]
        return [Event("closed", hwnd, pid, process, others=self._open_count(process)) for hwnd, process, pid in gone]

    def _open_count(self, process: str) -> int:
        return sum(1 for name, _, _ in self._tracked.values() if name.lower() == process.lower())
