"""What creating, changing, moving and deleting an event does to the events file. Pure: no file access, no clock.

Every change gives the changed events new ids: outcomes are stored per "<id>@<date>", and an old outcome must never
block an occurrence that was moved or edited. The running occurrence is never touched. A series edited "for all
events" keeps the occurrences that already started and changes from the next day on (`until` on the old series).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Literal

from .events import Edit, Event, EventError, Occurrence, new_event_id, occurrences, parse_event
from .session import MAX_MINUTES

Scope = Literal["this", "all"]

RUNNING = "הסשן שרץ עכשיו נעול."
TOO_LONG = "אירוע יכול להימשך עד 12 שעות."
PAST = "אי אפשר לקבוע סשן שכבר נגמר."
GONE = "האירוע כבר לא קיים."
INVALID = "האירוע לא תקין: {}"


class EditRefused(ValueError):
    """The change is not allowed; the message is shown to the user as it is."""


@dataclass(frozen=True)
class Context:
    now: float
    running_key: str  # "" when no session runs
    tz: tzinfo | None = None  # None: system local time
    new_id: Callable[[], str] = new_event_id


def _parse(fields: Any, event_id: str) -> Event:
    try:
        return parse_event(fields, event_id)
    except EventError as error:
        raise EditRefused(TOO_LONG if "at most" in str(error) else INVALID.format(error)) from None


def _occurrence(event: Event, day: date, tz: tzinfo | None) -> Occurrence | None:
    key = f"{event.id}@{day.isoformat()}"
    return next((found for found in occurrences([event], day, day, tz) if found.key == key), None)


def _find(events: Sequence[Event], key: str, ctx: Context) -> tuple[Event, date, Occurrence]:
    event_id, _, day_text = key.rpartition("@")
    try:
        day = date.fromisoformat(day_text)
    except ValueError:
        raise EditRefused(GONE) from None
    event = next((found for found in events if found.id == event_id), None)
    found = _occurrence(event, day, ctx.tz) if event is not None else None
    if event is None or found is None:
        raise EditRefused(GONE)
    if key == ctx.running_key:
        raise EditRefused(RUNNING)
    return event, day, found


def _not_past(event: Event, ctx: Context) -> None:
    """The event's occurrence on its own date (where the user placed it) must end after now."""
    found = _occurrence(event, event.date, ctx.tz)
    if found is not None and found.end <= ctx.now:
        raise EditRefused(PAST)


def _today(ctx: Context) -> date:
    return datetime.fromtimestamp(ctx.now, ctx.tz).date() if ctx.tz is not None else date.fromtimestamp(ctx.now)


def _split_day(event: Event, ctx: Context) -> date | None:
    """The first day a series change may touch, or None when no occurrence of the series has started yet."""
    today = _today(ctx)
    started = [found for found in occurrences([event], event.date, today, ctx.tz) if found.start <= ctx.now]
    if not started:
        return None
    last = date.fromisoformat(started[-1].key.rpartition("@")[2])
    return max(today, last + timedelta(days=1))


def _shifted(day: date | None, shift: timedelta) -> date | None:
    return day + shift if day is not None else None


def _skips(event: Event, first: date, shift: timedelta) -> frozenset[date]:
    return frozenset(day + shift for day in event.skip if day + shift >= first)


def _change_all(event: Event, new: Event, shift: timedelta, ctx: Context) -> Edit:
    split = _split_day(event, ctx)
    until = _shifted(event.until, shift)
    if split is None:
        start = event.date + shift
        return Edit(
            remove=frozenset({event.id}), put=(replace(new, date=start, until=until, skip=_skips(event, start, shift)),)
        )
    old = replace(event, until=split - timedelta(days=1))
    if until is not None and until < split:
        return Edit(put=(old,))
    return Edit(put=(old, replace(new, date=split, until=until, skip=_skips(event, split, shift))))


def create(fields: Any, ctx: Context) -> Edit:
    event = _parse(fields, ctx.new_id())
    _not_past(event, ctx)
    return Edit(put=(event,))


def change(events: Sequence[Event], key: str, fields: Any, scope: Scope, ctx: Context) -> Edit:
    """`fields` is the window's form; its `date` is the day the edited occurrence now falls on."""
    event, day, found = _find(events, key, ctx)
    if found.end <= ctx.now:
        raise EditRefused(PAST)
    new = _parse(fields, ctx.new_id())
    single = replace(new, days=frozenset(), until=None, skip=frozenset())
    _not_past(single, ctx)  # the edited occurrence itself, where it now falls, must end after now
    if not event.days:
        return Edit(remove=frozenset({event.id}), put=(new,))
    if scope == "this":
        return Edit(put=(replace(event, skip=event.skip | {day}), single))
    if not new.days:  # "all events" made into a one-off: the series ends, the one-off stays where it was put
        ended = delete(events, key, "all", ctx)
        return Edit(remove=ended.remove, put=(*ended.put, single))
    return _change_all(event, new, new.date - day, ctx)


def move(
    events: Sequence[Event],
    key: str,
    day: date,
    start: time,
    end: time,
    scope: Scope,
    ctx: Context,
    end_day: date | None = None,
) -> Edit:
    """A drag or a resize: the occurrence now falls on `day` from `start` to `end` (on `end_day` when the page
    says it ends on a later day). "all" shifts the weekdays too."""
    event, old_day, _ = _find(events, key, ctx)
    if end_day is not None:
        length = datetime.combine(end_day, end) - datetime.combine(day, start)
        if length > timedelta(minutes=MAX_MINUTES) or length <= timedelta(0):
            raise EditRefused(TOO_LONG)
    shift = (day - old_day).days
    fields = {
        "title": event.title,
        "date": day.isoformat(),
        "start": start.strftime("%H:%M"),
        "end": end.strftime("%H:%M"),
        "days": sorted((weekday + shift) % 7 for weekday in event.days),
        "cue": event.cue,
        "live": event.live,
    }
    return change(events, key, fields, scope, ctx)


def delete(events: Sequence[Event], key: str, scope: Scope, ctx: Context) -> Edit:
    event, day, _ = _find(events, key, ctx)
    if not event.days:
        return Edit(remove=frozenset({event.id}))
    if scope == "this":
        return Edit(put=(replace(event, skip=event.skip | {day}),))
    split = _split_day(event, ctx)
    if split is None:
        return Edit(remove=frozenset({event.id}))
    return Edit(put=(replace(event, until=split - timedelta(days=1)),))
