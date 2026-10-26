"""Start a session: clean up after an earlier one, write session.json, start the guard and the guardian."""

from collections.abc import Callable
from typing import Any

from . import instance
from .leftovers import undo_all
from .paths import Paths
from .session import Session, write_session
from .update_apply import UPDATE_MUTEX, is_applying

UPDATING = "Workmode מתעדכן עכשיו; אפשר להתחיל סשן בעוד דקה"


class UpdateInProgress(ValueError):
    """A ValueError so the window shows it like any other reason a session cannot start."""


def begin_session(
    paths: Paths,
    session: Session,
    spawn: Callable[[str], None],
    claim: Callable[[str], Any | None] = instance.claim,
    release_handle: Callable[[Any], None] = instance.release,
) -> None:
    """The update mutex is held while session.json is written: the updater either sees this session at its gate or
    has the mutex first, and then the session waits. Raises UpdateInProgress and writes nothing in that case."""
    handle = claim(UPDATE_MUTEX)
    if handle is None:
        raise UpdateInProgress(UPDATING)
    try:
        if is_applying(paths):
            raise UpdateInProgress(UPDATING)
        undo_all(paths)  # a guard killed before it could clean up leaves nothing behind for the new session
        write_session(paths.session, session)
        spawn("focus_guard.run_guard")
        spawn("focus_guard.run_guardian")
    finally:
        release_handle(handle)
