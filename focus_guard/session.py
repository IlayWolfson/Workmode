"""Session timing and resume (session.json)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonfile import write_json

MAX_MINUTES = 720
MAX_GRACE = 120


@dataclass(frozen=True)
class Session:
    start: float
    end: float
    live: bool
    occurrence: str = ""  # "<event id>@<YYYY-MM-DD>" for a scheduled session, "" for one started from the CLI
    grace: int | None = None  # overrides the configured grace period (0 for a follow-on session)

    def remaining(self, now: float) -> float:
        return max(0.0, self.end - now)

    def finished(self, now: float) -> bool:
        return now >= self.end


def write_session(path: str | Path, session: Session) -> None:
    data = {"start": session.start, "end": session.end, "live": session.live, "occurrence": session.occurrence}
    write_json(path, {**data, "grace": session.grace})


def start_session(path: str | Path, minutes: int, live: bool, now: float) -> Session:
    if not 1 <= minutes <= MAX_MINUTES:
        raise ValueError(f"minutes must be from 1 to {MAX_MINUTES}")
    session = Session(float(now), float(now) + minutes * 60.0, bool(live))
    write_session(path, session)
    return session


def _read(path: str | Path) -> Session | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    start: Any = data.get("start")
    end: Any = data.get("end")
    live: Any = data.get("live")
    numeric = all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (start, end))
    if not numeric or not isinstance(live, bool) or end <= start:
        return None
    grace: Any = data.get("grace")
    occurrence: Any = data.get("occurrence")
    valid_grace = isinstance(grace, int) and not isinstance(grace, bool) and 0 <= grace <= MAX_GRACE
    return Session(
        float(start),
        float(end),
        live,
        occurrence if isinstance(occurrence, str) else "",
        grace if valid_grace else None,
    )


def load_session(path: str | Path, now: float) -> Session | None:
    session = _read(path)
    return None if session is None or session.finished(now) else session


def clear_session(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)


def clear_session_if(path: str | Path, session: Session) -> bool:
    """Remove session.json only while it still holds `session`: an exiting guard must not delete the follow-on
    session the background process may already have written."""
    current = _read(path)
    if current is not None and (current.start, current.end, current.occurrence) == (
        session.start,
        session.end,
        session.occurrence,
    ):
        clear_session(path)
        return True
    return False
