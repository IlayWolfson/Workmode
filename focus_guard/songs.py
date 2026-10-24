"""Which song cues a planned session: one the user ticked (config `songs`), else a bundled one; never one of the
last few played (state/recent_songs.json)."""

import random
from collections.abc import Sequence
from pathlib import Path

from .jsonfile import read_json, write_json

SONG_SUFFIXES = (".mp3", ".wav")  # MCI cannot open m4a/mp4 on Windows without extra codecs (see cueplayer)
RECENT = 3


def _is_media(path: Path, suffixes: Sequence[str]) -> bool:
    return path.suffix.lower() in suffixes and path.is_file()


def library(bundled_dir: Path, configured: Sequence[str], suffixes: Sequence[str] = SONG_SUFFIXES) -> list[Path]:
    """The configured files that exist (a bare file name is looked up in `bundled_dir`), else every bundled one.
    Songs by default; the punishment videos use the same rules with their own suffixes."""
    chosen = []
    for entry in configured:
        path = Path(entry)
        candidate = bundled_dir / path.name if path.name == entry else path
        if _is_media(candidate, suffixes):
            chosen.append(candidate)
    if chosen:
        return chosen
    if not bundled_dir.is_dir():
        return []
    return sorted(path for path in bundled_dir.iterdir() if _is_media(path, suffixes))


def pick(songs: Sequence[Path], recent: Sequence[str], rng: random.Random) -> Path:
    """A random song, never one of the last min(3, len(songs) - 1) picks."""
    if not songs:
        raise ValueError("no songs to pick from")
    avoid = set(recent[-min(RECENT, len(songs) - 1) :]) if len(songs) > 1 else set()
    allowed = [song for song in songs if song.name not in avoid] or list(songs)
    return rng.choice(allowed)


class RecentSongs:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> list[str]:
        data = read_json(self._path)
        return [name for name in data if isinstance(name, str)][-RECENT:] if isinstance(data, list) else []

    def push(self, song: Path) -> None:
        write_json(self._path, [*self.load(), song.name][-RECENT:])
