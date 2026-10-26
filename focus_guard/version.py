"""The installed version. `tools/release.py` sets it together with extension/manifest.json (a test keeps them equal)."""

import re

VERSION = "1.2.5"

_PATTERN = re.compile(r"([0-9]{1,4})\.([0-9]{1,4})\.([0-9]{1,4})")


def parse_version(text: str) -> tuple[int, int, int]:
    """(major, minor, patch) for exactly "N.N.N"; raises ValueError for anything else."""
    match = _PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"not a version: {text!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch
