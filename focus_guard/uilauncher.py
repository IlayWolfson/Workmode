"""Starts the UI subprocesses without ever blocking the guard."""

import subprocess
import sys
from collections.abc import Callable

CREATE_NO_WINDOW = 0x08000000


class SubprocessUi:
    def __init__(
        self,
        hint: str,
        button: str,
        prompt: str,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        python: str = sys.executable,
    ) -> None:
        self._hint, self._button, self._prompt = hint, button, prompt
        self._popen, self._python = popen, python
        self._popup: subprocess.Popen | None = None
        self._video: subprocess.Popen | None = None
        self._phrase: subprocess.Popen | None = None
        self._summary: subprocess.Popen | None = None
        self._note: subprocess.Popen | None = None

    def _spawn(self, mode: str, *options: str, capture: bool = False) -> subprocess.Popen:
        command = [self._python, "-m", "focus_guard.ui", mode, *options]
        return self._popen(
            command,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )

    @staticmethod
    def _running(process: subprocess.Popen | None) -> bool:
        return process is not None and process.poll() is None

    def show_popup(self, text: str, seconds: int) -> None:
        if self._running(self._popup):
            return
        self._popup = self._spawn(
            "popup", f"--text={text}", f"--seconds={seconds}", f"--hint={self._hint}", f"--button={self._button}"
        )

    def show_video(self, media: str, seconds: int) -> None:
        if self._running(self._video):
            return
        self._video = self._spawn("video", f"--media={media}", f"--seconds={seconds}", f"--hint={self._hint}")

    def show_summary(self, text: str) -> None:
        self._summary = self._spawn("summary", f"--text={text}", "--seconds=20")

    def show_note(self, text: str, seconds: int) -> None:
        if self._running(self._note):
            return
        self._note = self._spawn("note", f"--text={text}", f"--seconds={seconds}")

    def ask_phrase(self) -> None:
        if self._running(self._phrase):
            return
        self._phrase = self._spawn("phrase", f"--prompt={self._prompt}", capture=True)

    def poll_phrase(self) -> str | None:
        if self._phrase is None or self._phrase.poll() is None:
            return None
        stdout = self._phrase.stdout
        raw = stdout.read() if stdout is not None else b""
        self._phrase = None
        return raw.decode("utf-8", errors="replace")
