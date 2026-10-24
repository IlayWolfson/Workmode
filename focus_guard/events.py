"""Planned sessions (state/events.json) and their occurrences. Pure apart from EventStore's file access.

Times are local wall-clock "HH:MM". `days` lists weekdays 0=Sunday … 6=Saturday; empty means a one-off event on
`date`. A repeating event starts on `date`. An `end` at or before `start` means the next day. A repeating event may
end on `until` (inclusive) and leave out the days in `skip`; both are written only when set.
"""

import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any

from .jsonfile import read_json, write_json
from .session import MAX_MINUTES

VERSION = 1
KEYS = frozenset({"id", "title", "date", "start", "end", "days", "cue", "live", "until", "skip"})
Day = date  # inside Event the field `date` hides the type, so its date-typed fields use this name
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    date: date
    start: time
    end: time
    days: frozenset[int]
    cue: bool
    live: bool
    until: Day | None = None  # last day of a repeating event, inclusive
    skip: frozenset[Day] = frozenset()  # days a repeating event leaves out


@dataclass(frozen=True)
class Occurrence:
    key: str  # "<event id>@<YYYY-MM-DD>"
    title: str
    start: float  # epoch seconds
    end: float
    live: bool
    cue: bool


class EventError(ValueError):
    pass


def _need(condition: object, message: str) -> None:
    if not condition:
        raise EventError(message)


def _hhmm(value: Any, name: str) -> time:
    match = HHMM_RE.match(value) if isinstance(value, str) else None
    if match is None:
        raise EventError(f"'{name}' must be HH:MM")
    return time(int(match.group(1)), int(match.group(2)))


def _minutes(start: time, end: time) -> int:
    length = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return length if length > 0 else length + 24 * 60


def _day(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise EventError(f"'{name}' must be YYYY-MM-DD") from None


def _flag(item: dict, name: str) -> bool:
    value = item.get(name, True)
    _need(isinstance(value, bool), f"'{name}' must be true or false")
    return value


def _limits(item: dict, day: date, repeating: bool) -> tuple[date | None, frozenset[date]]:
    if "until" not in item and "skip" not in item:
        return None, frozenset()
    _need(repeating, "'until' and 'skip' are only for repeating events")
    until = _day(item["until"], "until") if "until" in item else None
    _need(until is None or until >= day, "'until' must not be before 'date'")
    skip = item.get("skip", [])
    _need(isinstance(skip, list), "'skip' must be a list of YYYY-MM-DD")
    return until, frozenset(_day(value, "skip") for value in skip)


def _event(item: Any) -> Event:
    _need(isinstance(item, dict), "must be an object")
    unknown = set(item) - KEYS
    _need(not unknown, f"unknown keys {sorted(unknown)}")
    event_id, title = item.get("id"), item.get("title", "")
    _need(isinstance(event_id, str) and event_id.strip(), "'id' must be text")
    _need(isinstance(title, str), "'title' must be text")
    day = _day(item.get("date", ""), "date")
    start, end = _hhmm(item.get("start"), "start"), _hhmm(item.get("end"), "end")
    _need(start != end, "'end' must differ from 'start'")
    _need(_minutes(start, end) <= MAX_MINUTES, f"an event can last at most {MAX_MINUTES} minutes")
    days = item.get("days", [])
    _need(
        isinstance(days, list) and all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days),
        "'days' must be a list of weekday numbers 0 (Sunday) to 6",
    )
    until, skip = _limits(item, day, bool(days))
    return Event(
        event_id, title, day, start, end, frozenset(days), _flag(item, "cue"), _flag(item, "live"), until, skip
    )


def parse_event(item: Any, event_id: str) -> Event:
    """One entry from the window (it has no id; `event_id` is used). Raises EventError like parse_events reports."""
    _need(isinstance(item, dict), "must be an object")
    _need("id" not in item, "unknown keys ['id']")
    return _event({**item, "id": event_id})


def parse_events(data: Any) -> tuple[list[Event], list[str]]:
    """The valid events and one error line per invalid entry. Never raises."""
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        return [], ["events.json: expected an object with an 'events' list"]
    events: list[Event] = []
    errors: list[str] = []
    seen: set[str] = set()
    for number, item in enumerate(data["events"], start=1):
        try:
            event = _event(item)
            _need(event.id not in seen, f"duplicate id {event.id!r}")
        except EventError as error:
            errors.append(f"event {number}: {error}")
            continue
        seen.add(event.id)
        events.append(event)
    return events, errors


def _epoch(day: date, at: time, tz: tzinfo | None) -> float:
    moment = datetime.combine(day, at)
    return (moment.replace(tzinfo=tz) if tz is not None else moment).timestamp()


def _occurrence(event: Event, day: date, tz: tzinfo | None) -> Occurrence:
    start = _epoch(day, event.start, tz)
    end_day = day if event.end > event.start else day + timedelta(days=1)
    end = _epoch(end_day, event.end, tz)
    if end <= start:  # starts inside the spring-forward gap: keep the planned length
        end = start + _minutes(event.start, event.end) * 60
    return Occurrence(f"{event.id}@{day.isoformat()}", event.title, start, end, event.live, event.cue)


def _sunday_based(day: date) -> int:
    return (day.weekday() + 1) % 7


def _occurs_on(event: Event, day: date) -> bool:
    if not event.days:
        return day == event.date
    if (event.until is not None and day > event.until) or day in event.skip:
        return False
    return _sunday_based(day) in event.days


def occurrences(events: Sequence[Event], first: date, last: date, tz: tzinfo | None = None) -> list[Occurrence]:
    """Every occurrence that starts on a day from `first` to `last`, sorted by start. tz=None: system local time."""
    found: list[Occurrence] = []
    for event in events:
        day = max(first, event.date)
        end = last if event.until is None else min(last, event.until)
        while day <= end:
            if _occurs_on(event, day):
                found.append(_occurrence(event, day, tz))
            if not event.days:
                break
            day += timedelta(days=1)
    return sorted(found, key=lambda occurrence: (occurrence.start, occurrence.key))


def _to_json(event: Event) -> dict:
    data: dict[str, Any] = {
        "id": event.id,
        "title": event.title,
        "date": event.date.isoformat(),
        "start": event.start.strftime("%H:%M"),
        "end": event.end.strftime("%H:%M"),
        "days": sorted(event.days),
        "cue": event.cue,
        "live": event.live,
    }
    if event.until is not None:
        data["until"] = event.until.isoformat()
    if event.skip:
        data["skip"] = sorted(day.isoformat() for day in event.skip)
    return data


@dataclass(frozen=True)
class Edit:
    """A change to the events file: entries to drop by id, events to write (an event replaces its id's entry)."""

    remove: frozenset[str] = frozenset()
    put: tuple[Event, ...] = ()


def new_event_id() -> str:
    return secrets.token_hex(4)


def _raw_id(item: dict) -> str | None:
    """The id of a raw entry; None for a hand-written id that is not text (such an entry is always kept)."""
    value = item.get("id")
    return value if isinstance(value, str) else None


class EventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[list[Event], list[str]]:
        if not self.path.exists():
            return [], []
        return parse_events(read_json(self.path))

    def _items(self) -> list:
        """The raw entries; refuses a file that exists but cannot be read, so adding never wipes a hand edit."""
        if not self.path.exists():
            return []
        data = read_json(self.path)
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            raise EventError("events.json cannot be read: fix it (or remove it) before adding a session")
        return data["events"]

    def check_writable(self) -> None:
        self._items()

    def add(self, event: Event) -> None:
        self.commit(Edit(put=(event,)))

    def commit(self, edit: Edit) -> None:
        """Write an edit atomically. Every other entry stays exactly as it is, even one that is not valid."""
        dropped = edit.remove | {event.id for event in edit.put}
        kept = [item for item in self._items() if not (isinstance(item, dict) and _raw_id(item) in dropped)]
        write_json(self.path, {"version": VERSION, "events": [*kept, *(_to_json(event) for event in edit.put)]})

    def mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None
