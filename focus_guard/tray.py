"""The tray icon of the background process (pystray). Verified by hand."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

TOOLTIP = "Workmode"


def run_tray(
    on_open: Callable[[], None], on_calendar: Callable[[], None], on_quit: Callable[[], None], icon: Path
) -> Any:
    """Show the icon in its own thread and return it (call .stop() to remove it). Clicking it opens the window."""
    import pystray
    from PIL import Image

    image = Image.open(icon) if icon.exists() else Image.new("RGB", (64, 64), (26, 115, 232))
    menu = pystray.Menu(
        pystray.MenuItem("פתיחה", lambda: on_open(), default=True),
        pystray.MenuItem("יומן", lambda: on_calendar()),
        pystray.MenuItem("יציאה", lambda: on_quit()),
    )
    tray = pystray.Icon("focus_guard", image, TOOLTIP, menu)
    tray.run_detached()
    return tray
