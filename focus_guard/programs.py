"""Which programs the allow-list screen offers: open ones not yet allowed, and installed ones matching what is typed.

Pure: the Win32 side (winprograms.py) supplies Program values; tests use fakes.
"""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ports import ProgramSource

NOT_A_PROGRAM = "אפשר לגרור רק תוכנה (exe) או קיצור דרך לתוכנה."
MATCH_LIMIT = 5
# Parts of Windows and the tool's own Python: never worth offering.
HIDDEN = frozenset(
    {
        "explorer.exe",
        "pythonw.exe",
        "python.exe",
        "applicationframehost.exe",
        "shellexperiencehost.exe",
        "searchhost.exe",
        "startmenuexperiencehost.exe",
        "textinputhost.exe",
    }
)


@dataclass(frozen=True)
class Program:
    name: str  # what the user sees, e.g. "Google Chrome"
    process: str  # lowercase, e.g. "chrome.exe"
    path: str  # the full path to the program, stored as its launch command


def to_offer(running: Sequence[Program], allowed: Collection[str], hidden: Collection[str]) -> list[Program]:
    skip = {name.lower() for name in (*allowed, *hidden)}
    unique: dict[str, Program] = {}
    for program in running:
        if program.process.lower() not in skip:
            unique.setdefault(program.process.lower(), program)
    return sorted(unique.values(), key=lambda program: program.name.lower())


def match(query: str, programs: Sequence[Program], limit: int = MATCH_LIMIT) -> list[Program]:
    wanted = query.strip().lower()
    if not wanted:
        return []
    starts = [program for program in programs if program.name.lower().startswith(wanted)]
    contains = [program for program in programs if wanted in program.name.lower() and program not in starts]
    return (sorted(starts, key=lambda program: len(program.name)) + contains)[:limit]


def installer_icon(path: str, windir: str) -> bool:
    """MSI "advertised" shortcuts point at an icon file under %WINDIR%/Installer, never at the program itself."""

    def clean(text: str) -> str:
        return text.replace("\\", "/").lower().rstrip("/")

    return clean(path).startswith(clean(windir) + "/installer/")


LAUNCHER_SUFFIXES = ("-launcher", "_launcher", "launcher")


def real_program(target: str, exists: Callable[[str], bool]) -> str:
    """A shortcut to a launcher ("blender-launcher.exe") means the program next to it ("blender.exe"): the launcher
    exits once the program opens, and the program's own window is what a session sees."""
    cut = max(target.rfind("/"), target.rfind("\\")) + 1
    folder, name = target[:cut], target[cut:]
    stem, dot, suffix = name.rpartition(".")
    for ending in LAUNCHER_SUFFIXES:
        if dot and len(stem) > len(ending) and stem.lower().endswith(ending):
            candidate = f"{folder}{stem[: -len(ending)]}.{suffix}"
            if exists(candidate):
                return candidate
    return target


def program_from_drop(path: str, source: "ProgramSource") -> Program:
    found = source.from_file(path)
    if found is None:
        raise ValueError(NOT_A_PROGRAM)
    return found
