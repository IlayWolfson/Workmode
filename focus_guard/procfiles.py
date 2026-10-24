"""Pid files for the guard, the guardian and the desktop window."""

import os
from pathlib import Path

import psutil


def write_pid(path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(os.getpid()), encoding="utf-8")


def read_pid(path: str | Path) -> int | None:
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def remove_pid(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)


def pid_alive(path: str | Path, marker: str) -> bool:
    pid = read_pid(path)
    if pid is None:
        return False
    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        return marker.lower() in " ".join(process.cmdline()).lower()
    except (psutil.Error, OSError):
        return False
