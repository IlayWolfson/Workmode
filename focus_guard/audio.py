"""Per-program mute through Windows Core Audio (pycaw). Verified by hand, not unit-tested."""

import warnings
from collections.abc import Iterator
from typing import Any

import comtypes
from pycaw.pycaw import AudioUtilities


def _sessions() -> Iterator[tuple[str, Any]]:
    """(lower-case process name, session) for every audio session that belongs to a program."""
    with warnings.catch_warnings():  # pycaw warns about devices it cannot describe; harmless
        warnings.simplefilter("ignore")
        sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        process = session.Process
        if process is None:  # system sounds
            continue
        try:
            yield process.name().lower(), session
        except Exception:  # the process ended meanwhile
            continue


class Win32Audio:
    def __init__(self) -> None:
        comtypes.CoInitialize()

    def audio_processes(self) -> set[str]:
        return {name for name, _ in _sessions()}

    def is_muted(self, process: str) -> bool:
        """True only when every audio session of the program is muted: a new window or call is heard otherwise."""
        name = process.lower()
        states = [bool(session.SimpleAudioVolume.GetMute()) for found, session in _sessions() if found == name]
        return bool(states) and all(states)

    def set_mute(self, process: str, muted: bool) -> None:
        name = process.lower()
        for found, session in _sessions():
            if found == name:
                session.SimpleAudioVolume.SetMute(int(muted), None)
