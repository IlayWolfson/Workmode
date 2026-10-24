"""Small JSON files under state/: atomic writes, forgiving reads."""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

REPLACE_ATTEMPTS = 5
REPLACE_PAUSE = 0.05  # seconds; another process reading the file blocks os.replace on Windows for a moment


def read_json(path: str | Path) -> Any:
    """The file's JSON value, or None when it is missing or unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: str | Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data))


def write_text_atomic(path: str | Path, text: str) -> None:
    """Write `text` through a temp file in the same folder, so the target is always whole. Raises OSError."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_name, target)
                break
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_PAUSE)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
