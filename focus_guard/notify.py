"""Copy and timing for the notification windows (upcoming, missed start, restart) and their nerd step. Pure."""

import math
import time

NERD_TEXT = "ידעתי שאתה לא מסוגל חי חה חי גרההה"
NERD_YES = "התחרטתי אני רוצה לעבוד"  # green: start now
NERD_NO = "אתה צודק המלך שלי נכנעתי"  # red: this occurrence is cancelled
NERD_SECONDS = 120.0  # missed-start and restart windows: the nerd step waits this long, then counts as red
START_NOW, NOT_TODAY, CONTINUE = "התחלה עכשיו", "לא היום", "להמשיך"
DEFAULT_TITLE = "סשן"
MARGIN = 16


def _minutes_left(end: float, now: float) -> int:
    return max(0, math.ceil((end - now) / 60))


def notify_copy(kind: str, title: str, start: float, end: float, now: float) -> dict[str, str]:
    if kind == "upcoming":
        name, at = title.strip() or DEFAULT_TITLE, time.strftime("%H:%M", time.localtime(start))
        return {"text": f"{name} מתחיל ב-{at}", "go": START_NOW, "no": NOT_TODAY}
    if kind == "missed":
        return {"text": f"פספסת את ההתחלה, נשארו {_minutes_left(end, now)} דק׳", "go": START_NOW, "no": NOT_TODAY}
    if kind == "restart":
        return {"text": f"הסשן נעצר באמצע, נשארו {_minutes_left(end, now)} דק׳", "go": CONTINUE, "no": NOT_TODAY}
    raise ValueError(f"unknown window kind {kind!r}")


def nerd_deadline(kind: str, start: float, now: float) -> float:
    """When the nerd step counts as the red button: the planned start, or two minutes once it has passed."""
    return start if kind == "upcoming" else now + NERD_SECONDS


def window_args(kind: str, title: str, start: float, end: float, now: float) -> dict:
    """Everything the page needs. Times are relative (ms from now), so the page needs no clock agreement."""
    return {
        "kind": kind,  # upcoming: the nerd deadline counts from opening; otherwise from entering the nerd step
        **notify_copy(kind, title, start, end, now),
        "nerd_text": NERD_TEXT,
        "nerd_yes": NERD_YES,
        "nerd_no": NERD_NO,
        "nerd_after_ms": int((nerd_deadline(kind, start, now) - now) * 1000),
        "close_after_ms": int((end - now) * 1000),
    }


def corner_position(work_area: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int]:
    """Bottom-left corner of the work area (left, top, right, bottom): the notification side in right-to-left."""
    left, _top, _right, bottom = work_area
    return left + MARGIN, bottom - height - MARGIN
