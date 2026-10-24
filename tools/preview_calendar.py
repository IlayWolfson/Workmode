"""Open the main window on scratch data, for hand checks of the calendar: python tools/preview_calendar.py [--state DIR]

It never starts a guard (spawn only prints) and never touches the real config.json or state/: everything lives in
a scratch folder seeded with sample events and a copy of config.example.json with a dummy phrase and token.
"""

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from focus_guard.app import (  # noqa: E402
    DEFAULT_PERCENT,
    area_size,
    calendar_size,
    centered,
    screen_area,
    watch_drops,
)
from focus_guard.appapi import AppApi  # noqa: E402
from focus_guard.events import Event, EventStore  # noqa: E402
from focus_guard.paths import Paths  # noqa: E402

TITLE = "Workmode preview"
DUMMY_PHRASE = "preview phrase that is long enough"
DUMMY_TOKEN = "0123456789abcdef0123456789abcdef"
DUMMY_VIDEO_URL = "https://example.com/preview.mp4"


def _sunday(day: date) -> date:
    return day - timedelta(days=(day.weekday() + 1) % 7)


def sample_events(today: date) -> list[Event]:
    """A one-off tomorrow, a Sunday+Tuesday series from this week, and a trial event the day after tomorrow."""
    return [
        Event("pv-math", "מתמטיקה", today + timedelta(days=1), time(10, 0), time(11, 30), frozenset(), True, True),
        Event("pv-eng", "אנגלית", _sunday(today), time(16, 0), time(17, 30), frozenset({0, 2}), True, True),
        Event("pv-try", "", today + timedelta(days=2), time(20, 0), time(20, 45), frozenset(), False, False),
    ]


def seed(root: Path, today: date) -> Paths:
    """Scratch Paths with a config copy and sample events; an existing scratch folder is reused as it is."""
    paths = Paths(root)
    paths.state.mkdir(parents=True, exist_ok=True)
    if not paths.config.exists():
        data = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        data["emergency"]["phrase"] = DUMMY_PHRASE
        data["server"]["token"] = DUMMY_TOKEN
        data["video"]["fallback_url"] = DUMMY_VIDEO_URL  # the example's video file does not exist here
        paths.config.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not paths.events.exists():
        store = EventStore(paths.events)
        for event in sample_events(today):
            store.add(event)
    return paths


class FakeBusy:
    """Two grey blocks this week (tomorrow 12:00-13:30, the day after 09:00-10:00), so the busy layer shows."""

    def __init__(self, today: date) -> None:
        def at(day: date, hour: int, minute: int = 0) -> float:
            return datetime.combine(day, time(hour, minute)).timestamp()

        tomorrow, after = today + timedelta(days=1), today + timedelta(days=2)
        self._ranges = [(at(tomorrow, 12), at(tomorrow, 13, 30)), (at(after, 9), at(after, 10))]

    def busy(self, start: float, end: float) -> Sequence[tuple[float, float]]:
        return [(low, high) for low, high in self._ranges if low < end and high > start]


def _print_spawn(module: str) -> None:
    print(f"preview: would start {module}")


def _print_autostart(paths: Paths, enabled: bool) -> None:
    print(f"preview: would set start with Windows to {enabled}")  # the real Startup shortcut is never touched


def main(argv: list[str] | None = None) -> int:
    import webview

    parser = argparse.ArgumentParser(prog="preview_calendar")
    parser.add_argument("--state", type=Path, help="scratch folder (default: a new temp folder)")
    args = parser.parse_args(argv)
    root = args.state or Path(tempfile.mkdtemp(prefix="fg-preview-"))
    paths = seed(root, date.today())
    print(f"preview data: {root}")
    api = AppApi(
        paths,
        spawn=_print_spawn,
        guard_alive=lambda: False,
        busy=FakeBusy(date.today()),
        apply_autostart=_print_autostart,
        songs_dir=ROOT / "assets" / "songs",
    )
    url = (ROOT / "focus_guard" / "web" / "main.html").as_uri()
    rect, scale = screen_area()
    width, height = calendar_size(area_size(rect), scale, DEFAULT_PERCENT)
    where = centered(rect, scale, (width, height))
    x, y = where if where else (None, None)
    window = webview.create_window(TITLE, url=url, js_api=api, width=width, height=height, x=x, y=y)
    if window is None:
        raise RuntimeError("pywebview did not create the window")
    watch_drops(window, api)  # the allow-list's drop box, as in the app
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
