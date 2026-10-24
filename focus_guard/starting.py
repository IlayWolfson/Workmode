"""Start a session: clean up after an earlier one, write session.json, start the guard and the guardian."""

from collections.abc import Callable

from .leftovers import undo_all
from .paths import Paths
from .session import Session, write_session


def begin_session(paths: Paths, session: Session, spawn: Callable[[str], None]) -> None:
    undo_all(paths)  # a guard killed before it could clean up leaves nothing behind for the new session
    write_session(paths.session, session)
    spawn("focus_guard.run_guard")
    spawn("focus_guard.run_guardian")
