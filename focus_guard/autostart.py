"""Start with Windows: a shortcut in the user's Startup folder (visible, removable by hand, sets the work folder).

Turning the setting off deletes the shortcut. A shortcut left under an old name is deleted either way.
"""

import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from .paths import Paths
from .shortcut import create_shortcut

NAME = "Workmode"
LEGACY_NAMES = ("Hyperbolic Time Chamber",)
STARTUP = Path("Microsoft") / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_link(env: Mapping[str, str] = os.environ) -> Path:
    return Path(env["APPDATA"]) / STARTUP / f"{NAME}.lnk"


def legacy_links(env: Mapping[str, str] = os.environ) -> list[Path]:
    return [Path(env["APPDATA"]) / STARTUP / f"{name}.lnk" for name in LEGACY_NAMES]


def remove_legacy(links: list[Path], remove: Callable[[Path], object]) -> list[Path]:
    """Delete old-name links that exist, so the app does not also start under its old name."""
    removed = [link for link in links if link.exists()]
    for link in removed:
        remove(link)
    return removed


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

    remove_legacy(legacy_links(), Path.unlink)
    return sync(enabled, startup_link(), make, Path.unlink)
