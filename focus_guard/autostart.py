"""Start with Windows: a shortcut in the user's Startup folder (visible, removable by hand, sets the work folder).

Turning the setting off deletes the shortcut.
"""

import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from .paths import Paths
from .shortcut import create_shortcut

NAME = "Hyperbolic Time Chamber"
STARTUP = Path("Microsoft") / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_link(env: Mapping[str, str] = os.environ) -> Path:
    return Path(env["APPDATA"]) / STARTUP / f"{NAME}.lnk"


def sync(enabled: bool, link: Path, make: Callable[[], object], remove: Callable[[Path], object]) -> str:
    """Make the link when enabled (every time, so a moved project folder is fixed), remove it when not."""
    if enabled:
        make()
        return "created"
    if link.exists():
        remove(link)
        return "removed"
    return "none"


def apply(paths: Paths, enabled: bool) -> str:
    def make() -> None:
        create_shortcut(
            name=NAME,
            target=str(Path(sys.executable).with_name("pythonw.exe")),
            arguments="-m focus_guard.app --background",
            workdir=str(paths.root),
            icon=str(paths.icon),
            folder="Startup",
        )

    return sync(enabled, startup_link(), make, Path.unlink)
