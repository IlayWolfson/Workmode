"""Start a module of this package as a detached background process without a console window."""

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000


def spawn_module(module: str, root: str | Path, args: Sequence[str] = ()) -> None:
    subprocess.Popen(
        [sys.executable, "-m", module, *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        close_fds=True,
    )
