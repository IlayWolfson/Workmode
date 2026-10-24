"""Win32 adapters: window listing and window actions. Verified by hand, not unit-tested."""

import ctypes
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from ctypes import wintypes

import psutil
import win32con
import win32gui
import win32process

from .ownpids import own_tree
from .waiting import Placement
from .watcher import WinInfo

DWMWA_CLOAKED = 14
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
PLACEMENT_STATE = {win32con.SW_SHOWMINIMIZED: "minimized", win32con.SW_SHOWMAXIMIZED: "maximized"}


def _cloaked(hwnd: int) -> bool:
    value = wintypes.DWORD(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    except OSError:
        return False
    return bool(value.value)


def _store_app_pid(frame_hwnd: int, frame_pid: int) -> int | None:
    """Store (UWP) apps show inside an ApplicationFrameHost window; the real app owns a child window."""
    pids = []

    def visit_child(hwnd: int, _: object) -> bool:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid != frame_pid:
            pids.append(pid)
        return True

    try:
        win32gui.EnumChildWindows(frame_hwnd, visit_child, None)
    except Exception:
        return None
    return pids[0] if pids else None


def process_children(pid: int) -> list[int]:
    try:
        return [child.pid for child in psutil.Process(pid).children()]
    except psutil.Error:
        return []


def process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return ""


class Win32Windows:
    def __init__(self, extra_pids: Callable[[], set[int]] | None = None) -> None:
        self._extra_pids = extra_pids or (lambda: set())

    def own_pids(self) -> set[int]:
        return own_tree(psutil.Process().pid, process_children, process_name) | set(self._extra_pids())

    def exists(self, hwnd: int) -> bool:
        return bool(win32gui.IsWindow(hwnd))

    def list_windows(self, exclude_pids: set[int]) -> tuple[WinInfo, ...]:
        found = []

        def visit(hwnd: int, _: object) -> bool:
            if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                return True
            if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title or _cloaked(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                name = psutil.Process(pid).name()
                if name.lower() == "applicationframehost.exe":
                    real = _store_app_pid(hwnd, pid)
                    if real is not None:
                        pid, name = real, psutil.Process(real).name()
            except psutil.Error:
                return True
            if pid in exclude_pids:
                return True
            state = PLACEMENT_STATE.get(win32gui.GetWindowPlacement(hwnd)[1], "normal")
            found.append(WinInfo(hwnd, pid, name, title, state))
            return True

        win32gui.EnumWindows(visit, None)
        return tuple(found)


class Win32Actions:
    """Never closes or kills anything: programs not on the list only wait minimized."""

    def minimize(self, hwnd: int) -> None:
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

    def owner_pid(self, hwnd: int) -> int | None:
        """The pid the window listing reports for this window (the real app for Store apps); None if gone."""
        if not win32gui.IsWindow(hwnd):
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            if psutil.Process(pid).name().lower() == "applicationframehost.exe":
                return _store_app_pid(hwnd, pid) or pid
        except psutil.Error:
            return None
        return pid

    def placement(self, hwnd: int) -> Placement | None:
        if not win32gui.IsWindow(hwnd):
            return None
        _, show_cmd, _, _, (left, top, right, bottom) = win32gui.GetWindowPlacement(hwnd)
        return Placement(show_cmd, (left, top, right, bottom))

    def set_placement(self, hwnd: int, placement: Placement) -> None:
        win32gui.SetWindowPlacement(hwnd, (0, placement.show_cmd, (-1, -1), (-1, -1), placement.normal_rect))

    def restore(self, hwnd: int, state: str) -> None:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE if state == "maximized" else win32con.SW_RESTORE)

    def launch(self, args: Sequence[str]) -> bool:
        first = os.path.expandvars(args[0])
        executable = shutil.which(first) or first
        try:
            subprocess.Popen(
                [executable, *args[1:]],
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return True
