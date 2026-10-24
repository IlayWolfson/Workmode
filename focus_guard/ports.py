"""What the guard needs from the outside world. Win32 adapters implement these; tests use fakes."""

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .programs import Program
from .waiting import Placement
from .watcher import WinInfo

if TYPE_CHECKING:  # events and scheduler import nothing from here; this keeps the import graph one-way
    from .events import Occurrence
    from .scheduler import Answer


class WindowSource(Protocol):
    def own_pids(self) -> set[int]: ...

    def list_windows(self, exclude_pids: set[int]) -> Sequence[WinInfo]: ...


class WindowActions(Protocol):
    def minimize(self, hwnd: int) -> None: ...

    def placement(self, hwnd: int) -> Placement | None: ...  # None when the window is gone

    def owner_pid(self, hwnd: int) -> int | None: ...  # None when the window is gone

    def set_placement(self, hwnd: int, placement: Placement) -> None: ...

    def restore(self, hwnd: int, state: str) -> None: ...

    def launch(self, args: Sequence[str]) -> bool: ...


class ProgramSource(Protocol):
    """Programs for the allow-list screen: open now, installed (Start menu), or a dropped file."""

    def running(self) -> Sequence[Program]: ...

    def installed(self) -> Sequence[Program]: ...

    def from_file(self, path: str) -> Program | None: ...  # None when the file is not a program or a shortcut to one

    def name_of(self, process: str, path: str) -> str: ...


class AlertUi(Protocol):
    def show_popup(self, text: str, seconds: int) -> None: ...

    def show_video(self, media: str, seconds: int) -> None: ...

    def show_summary(self, text: str) -> None: ...

    def show_note(self, text: str, seconds: int) -> None: ...

    def ask_phrase(self) -> None: ...

    def poll_phrase(self) -> str | None: ...


class AudioControl(Protocol):
    def audio_processes(self) -> set[str]: ...  # lower-case names that have an audio session now

    def is_muted(self, process: str) -> bool: ...

    def set_mute(self, process: str, muted: bool) -> None: ...


class KeyState(Protocol):
    def pressed(self, vks: Iterable[int]) -> set[int]: ...


class RoastSource(Protocol):
    def next(self) -> str: ...


class NotifyUi(Protocol):
    """The background process's windows: notifications (upcoming, missed start, restart) and errors."""

    def open(self, kind: str, occurrence: "Occurrence") -> None: ...

    def close(self, key: str) -> None: ...

    def poll(self) -> "list[tuple[str, Answer]]": ...  # answers so far: (occurrence key, answer)

    def error(self, text: str) -> None: ...


class BusySource(Protocol):
    """Busy time from outside the tool (later: Google Calendar's free/busy). Read-only; never blocks saving."""

    def busy(self, start: float, end: float) -> Sequence[tuple[float, float]]: ...  # epoch seconds


class CuePlayer(Protocol):
    def play_clip(self, path: Path, seconds: float = 5.0) -> None: ...
