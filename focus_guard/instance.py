"""Only one background process: a named mutex. A second start asks the first to show its window and exits.

Verified by unit tests with unique names (real Windows objects).
"""

import ctypes
import threading
from collections.abc import Callable
from typing import Any

import pywintypes
import win32api
import win32event
import winerror

POLL_MS = 250
ASFW_ANY = -1
SYNCHRONIZE = 0x00100000


def claim(name: str) -> Any | None:
    """A mutex handle when this process is the first with `name`, else None."""
    # pywin32 accepts None for default security; its type stubs do not say so
    handle = win32event.CreateMutex(None, False, name)  # type: ignore[arg-type]
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        handle.Close()
        return None
    return handle


def release(handle: Any) -> None:
    handle.Close()


def exists(name: str) -> bool:
    """True while some process holds the named mutex. Only looks: unlike claim, it never creates the mutex, so it can
    never make another process's claim fail."""
    try:
        handle = win32event.OpenMutex(SYNCHRONIZE, False, name)
    except pywintypes.error:
        return False
    win32api.CloseHandle(handle)
    return True


def signal_show(name: str) -> None:
    """Tell the running process to show its window. Nothing happens when nobody waits."""
    # this start came from the user's click and may bring windows to the front; a background process may not,
    # so hand that right over (ASFW_ANY) or the shown window stays behind the others
    ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    try:
        event = win32event.OpenEvent(win32event.EVENT_MODIFY_STATE, False, name)
    except pywintypes.error:
        return
    try:
        win32event.SetEvent(event)
    finally:
        win32api.CloseHandle(event)


def wait_show(name: str, on_show: Callable[[], None], stop: threading.Event) -> None:
    """Call on_show each time another start signals `name`, until stop is set. Run it in a thread."""
    event = win32event.CreateEvent(None, False, False, name)  # type: ignore[arg-type]  # auto-reset
    try:
        while not stop.is_set():
            if win32event.WaitForSingleObject(event, POLL_MS) == win32event.WAIT_OBJECT_0:
                on_show()
    finally:
        win32api.CloseHandle(event)
