"""Undo what the tool changed: waiting windows back in place, muted programs back to their sound.

Used at session end, and at every start of the tool when no session is active (after a crash or a
restart in the middle of a session).
"""

from collections.abc import Callable

from .muting import MuteStore
from .paths import Paths
from .ports import AudioControl, WindowActions
from .waiting import WaitingStore


def _ignore(message: str) -> None:
    pass


def restore_windows(waiting: WaitingStore, actions: WindowActions, on_error: Callable[[str], None] = _ignore) -> None:
    """Put every waiting window back where it was; windows closed meanwhile are skipped, and so is a handle
    Windows has since given to another program."""
    for window in waiting.load().values():
        try:
            if actions.owner_pid(window.hwnd) == window.pid:
                actions.set_placement(window.hwnd, window.placement)
        except Exception as error:
            on_error(f"restore {window.process}: {error!r}"[:80])
    waiting.clear()


def restore_mutes(mutes: MuteStore, audio: AudioControl, on_error: Callable[[str], None] = _ignore) -> None:
    """Give every program the tool muted its earlier mute state back."""
    for process, was_muted in mutes.load().items():
        try:
            audio.set_mute(process, was_muted)
        except Exception as error:
            on_error(f"unmute {process}: {error!r}"[:80])
    mutes.clear()


def cleanup(
    waiting: WaitingStore,
    mutes: MuteStore,
    actions: WindowActions,
    audio: AudioControl,
    on_error: Callable[[str], None] = _ignore,
) -> None:
    restore_windows(waiting, actions, on_error)
    restore_mutes(mutes, audio, on_error)


def undo_all(paths: Paths) -> None:
    """No session is running: bring back anything a killed guard left waiting or muted, drop its mute request."""
    waiting, mutes = WaitingStore(paths.waiting), MuteStore(paths.mutes)
    if waiting.load() or mutes.load():
        from .audio import Win32Audio  # Windows-only adapters, loaded only when there is work
        from .windows import Win32Actions

        cleanup(waiting, mutes, Win32Actions(), Win32Audio())
    paths.mute_request.unlink(missing_ok=True)
