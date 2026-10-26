"""May an update be applied now? Never during a session, close to a planned one, or in a git clone."""

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, tzinfo

from .events import EventStore, Occurrence, occurrences
from .outcomes import OutcomeStore
from .paths import Paths
from .session import load_session

SOON = 600  # seconds before a planned session in which updating is refused

GIT_CLONE = "זו תיקייה של git: עדכון דרך git pull"
SESSION_UNTIL = "יש סשן פעיל עד {}; העדכון יחכה"
SESSION_RUNNING = "יש סשן פעיל; העדכון יחכה"
PLANNED_SOON = "סשן מתוכנן מתחיל ב-{}; העדכון יחכה עד אחריו"


def _clock(epoch: float, tz: tzinfo | None) -> str:
    return datetime.fromtimestamp(epoch, tz).strftime("%H:%M")


def planned(paths: Paths, tz: tzinfo | None = None) -> Callable[[float], Sequence[Occurrence]]:
    """The planned occurrences from yesterday to tomorrow, read from events.json (errors: none planned)."""

    def around(now: float) -> Sequence[Occurrence]:
        events, _ = EventStore(paths.events).load()
        today = date.fromtimestamp(now) if tz is None else datetime.fromtimestamp(now, tz).date()
        return occurrences(events, today - timedelta(days=1), today + timedelta(days=1), tz)

    return around


def refusal(
    paths: Paths,
    now: float,
    guard_alive: Callable[[], bool],
    upcoming: Callable[[float], Sequence[Occurrence]],
    tz: tzinfo | None = None,
) -> str | None:
    """Why updating must wait (Hebrew, for the popup and Update.cmd), or None when it may go ahead."""
    if (paths.root / ".git").exists():
        return GIT_CLONE
    session = load_session(paths.session, now)
    if session is not None:
        return SESSION_UNTIL.format(_clock(session.end, tz))
    if guard_alive():
        return SESSION_RUNNING
    outcomes = OutcomeStore(paths.outcomes).load()
    for occurrence in upcoming(now):
        if occurrence.key not in outcomes and occurrence.start - SOON <= now < occurrence.end:
            return PLANNED_SOON.format(_clock(occurrence.start, tz))
    return None
