"""Windows of programs not on the list, minimized until the session ends (state/waiting.json)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonfile import read_json, write_json


@dataclass(frozen=True)
class Placement:
    show_cmd: int
    normal_rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class WaitingWindow:
    hwnd: int
    pid: int
    process: str
    placement: Placement


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse(entry: Any) -> WaitingWindow | None:
    if not isinstance(entry, dict):
        return None
    rect = entry.get("normal_rect")
    numbers = [entry.get("hwnd"), entry.get("pid"), entry.get("show_cmd")]
    if not all(_is_int(value) for value in numbers) or not isinstance(entry.get("process"), str):
        return None
    if not isinstance(rect, list) or len(rect) != 4 or not all(_is_int(value) for value in rect):
        return None
    left, top, right, bottom = rect
    placement = Placement(entry["show_cmd"], (left, top, right, bottom))
    return WaitingWindow(entry["hwnd"], entry["pid"], entry["process"], placement)


def _entry(window: WaitingWindow) -> dict[str, Any]:
    return {
        "hwnd": window.hwnd,
        "pid": window.pid,
        "process": window.process,
        "show_cmd": window.placement.show_cmd,
        "normal_rect": list(window.placement.normal_rect),
    }


class WaitingStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> dict[int, WaitingWindow]:
        data = read_json(self._path)
        entries = data.get("windows") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return {}
        windows = [window for window in map(_parse, entries) if window is not None]
        return {window.hwnd: window for window in windows}

    def _save(self, windows: dict[int, WaitingWindow]) -> None:
        write_json(self._path, {"windows": [_entry(window) for window in windows.values()]})

    def add(self, window: WaitingWindow) -> None:
        """Remember a window; one already stored keeps its first (pre-minimize) placement."""
        windows = self.load()
        if window.hwnd not in windows:
            self._save({**windows, window.hwnd: window})

    def remove(self, hwnd: int) -> None:
        windows = self.load()
        if hwnd in windows:
            self._save({key: value for key, value in windows.items() if key != hwnd})

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
