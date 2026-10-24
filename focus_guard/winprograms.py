"""Win32 side of the allow-list screen's programs: open windows, Start-menu shortcuts, dropped files, friendly names.

Verified by hand (the preview and the app), not unit-tested; the choices themselves live in programs.py.
"""

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psutil
import pythoncom
import win32api
from win32com.shell import shell

from .programs import Program, installer_icon, real_program
from .windows import Win32Windows

START_MENUS = (
    Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
)


def shortcut_target(path: str) -> str:
    """The file a .lnk points at, or "" when it cannot be read."""
    try:
        pythoncom.CoInitialize()
        link: Any = pythoncom.CoCreateInstance(  # pywin32's stubs do not know IShellLink
            shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
        )
        persist: Any = link.QueryInterface(pythoncom.IID_IPersistFile)
        persist.Load(path)
        return str(link.GetPath(shell.SLGP_RAWPATH)[0])
    except Exception:  # pywin32 raises com_error and others for broken or odd shortcuts
        return ""


def file_description(path: str) -> str:
    api: Any = win32api  # its stubs only accept literal version-info keys
    try:
        language, codepage = api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")[0]
        text = api.GetFileVersionInfo(path, f"\\StringFileInfo\\{language:04x}{codepage:04x}\\FileDescription")
    except Exception:  # no version info, or not a file Windows can read it from
        return ""
    return str(text or "").strip()


def _exe(path: str) -> bool:
    windir = os.environ.get("WINDIR", "C:/Windows")
    return path.lower().endswith(".exe") and Path(path).is_file() and not installer_icon(path, windir)


class WinPrograms:
    def __init__(self) -> None:
        self._installed: list[Program] | None = None  # the Start menu is read once per process

    def name_of(self, process: str, path: str) -> str:
        return file_description(path) or process.removesuffix(".exe").removesuffix(".EXE")

    def running(self) -> Sequence[Program]:
        windows = Win32Windows()
        found = []
        for window in windows.list_windows(windows.own_pids()):
            try:
                path = psutil.Process(window.pid).exe()
            except psutil.Error:
                continue
            process = Path(path).name.lower()
            found.append(Program(self.name_of(process, path), process, path))
        return found

    def installed(self) -> Sequence[Program]:
        if self._installed is None:
            found: dict[str, Program] = {}
            for folder in START_MENUS:
                for link in sorted(folder.rglob("*.lnk")) if folder.is_dir() else []:
                    target = real_program(os.path.expandvars(shortcut_target(str(link))), os.path.isfile)
                    if _exe(target):
                        found.setdefault(link.stem.lower(), Program(link.stem, Path(target).name.lower(), target))
            self._installed = list(found.values())
        return self._installed

    def from_file(self, path: str) -> Program | None:
        target = os.path.expandvars(shortcut_target(path)) if path.lower().endswith(".lnk") else path
        target = real_program(target, os.path.isfile)
        if not _exe(target):
            return None
        process = Path(target).name.lower()
        return Program(self.name_of(process, target), process, target)
