"""Play the first seconds of a song through Windows MCI (built in, no dependency).

The commands are pure and unit-tested; the sound itself is verified by hand. "play … to N wait" ran ~9 s for a
5 s mp3 clip on the VM, so the clip is timed here: play, sleep, stop. MCI cannot open m4a/mp4 there (error 277).
"""

import itertools
import threading
import time
from collections.abc import Callable
from pathlib import Path

MCI_TYPES = {".wav": "waveaudio"}  # everything else (mp3, m4a, mp4) goes through DirectShow


def mci_commands(path: Path, alias: str) -> tuple[str, str, str, str]:
    """open, play, stop, close: the caller waits between play and stop."""
    text = str(path)
    if '"' in text:
        raise ValueError(f"cannot play a path with a quote: {text}")
    kind = MCI_TYPES.get(path.suffix.lower(), "mpegvideo")
    return f'open "{text}" type {kind} alias {alias}', f"play {alias} from 0", f"stop {alias}", f"close {alias}"


def _winmm_send(command: str) -> int:
    import ctypes

    return int(ctypes.windll.winmm.mciSendStringW(command, None, 0, None))


def _in_thread(job: Callable[[], None]) -> None:
    threading.Thread(target=job, daemon=True).start()


def _ignore(message: str) -> None:
    pass


class MciPlayer:
    def __init__(
        self,
        send: Callable[[str], int] = _winmm_send,
        on_error: Callable[[str], None] = _ignore,
        run: Callable[[Callable[[], None]], None] = _in_thread,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._send, self._on_error, self._run, self._sleep = send, on_error, run, sleep
        self._numbers = itertools.count(1)  # a new alias per play: a second cue never finds its alias busy

    def play_clip(self, path: Path, seconds: float = 5.0) -> None:
        alias = f"cue{next(self._numbers)}"
        try:
            commands = mci_commands(path, alias)
        except ValueError as error:
            self._on_error(str(error))
            return
        self._run(lambda: self._play(commands, seconds))

    def _play(self, commands: tuple[str, str, str, str], seconds: float) -> None:
        open_cmd, play_cmd, stop_cmd, close_cmd = commands
        try:
            for command in (open_cmd, play_cmd):
                code = self._send(command)
                if code:
                    self._on_error(f"mci error {code}: {command}")
                    return
            self._sleep(seconds)
            self._send(stop_cmd)
        finally:
            self._send(close_cmd)
