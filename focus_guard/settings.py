"""The settings behind the gear: read for the window (never the phrase) and saved back into config.json safely.

A save is refused during a session and while config.json is not a JSON object (a hand edit is never overwritten).
The result of the change is checked with load_config before it replaces the old file, so a save can complete a fresh
config (placeholder phrase, no video) but a bad value never reaches config.json.
"""

import json
import os
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .config import VIDEO_SUFFIXES, Config, ConfigError, load_config, load_config_safe
from .paths import Paths
from .songs import SONG_SUFFIXES

SESSION_LOCKED = "אי אפשר לשנות הגדרות בזמן סשן."
CONFIG_BROKEN = "config.json שבור. צריך לתקן אותו ביד לפני שמירה מכאן."
PHRASES_DIFFER = "המשפטים לא זהים."
CONFIG_BUSY = "config.json תפוס כרגע. נסה שוב בעוד רגע."
REPLACE_ATTEMPTS = 5
REPLACE_PAUSE = 0.05  # seconds; another reader blocks os.replace on Windows for a moment
# One save at a time: the window's calls arrive on separate threads, and each save reads, changes and replaces.
_WRITE_LOCK = threading.Lock()
PLAIN_KEYS = ("songs", "song_files", "videos", "video_files", "grace_seconds", "start_with_windows")


def bundled_songs(bundled_dir: Path, suffixes: tuple[str, ...] = SONG_SUFFIXES) -> list[Path]:
    if not bundled_dir.is_dir():
        return []
    return sorted(path for path in bundled_dir.iterdir() if path.suffix.lower() in suffixes and path.is_file())


def _videos(cfg: Config | None, videos_dir: Path) -> list[dict]:
    """Bundled punishment videos, then the user's own; the older single `video.path` is one of the user's own and
    stays ticked while nothing else is, so opening settings changes nothing."""
    ticked = set(cfg.videos) if cfg is not None else set()
    own = list(cfg.video_files) if cfg is not None else []
    if cfg is not None and cfg.video_path and cfg.video_path not in own:
        own.append(cfg.video_path)
        if not ticked:
            ticked.add(cfg.video_path)
    found = [
        {"id": video.name, "name": video.stem, "ticked": video.name in ticked, "bundled": True}
        for video in bundled_songs(videos_dir, VIDEO_SUFFIXES)
    ]
    mine = [{"id": entry, "name": Path(entry).stem, "ticked": entry in ticked, "bundled": False} for entry in own]
    return found + mine


def read_settings(paths: Paths, bundled_dir: Path, videos_dir: Path | None = None) -> dict:
    cfg, _ = load_config_safe(paths.config, paths.config_last_good)
    ticked = set(cfg.songs) if cfg is not None else set()
    songs = [
        {"id": song.name, "name": song.stem, "ticked": song.name in ticked, "bundled": True}
        for song in bundled_songs(bundled_dir)
    ]
    for entry in cfg.song_files if cfg is not None else ():
        songs.append({"id": entry, "name": Path(entry).stem, "ticked": entry in ticked, "bundled": False})
    return {
        "songs": songs,
        "videos": _videos(cfg, videos_dir or bundled_dir.parent / "videos"),
        "grace_seconds": cfg.grace_seconds if cfg is not None else 20,
        "start_with_windows": cfg.start_with_windows if cfg is not None else True,
    }


def _changed(raw: dict, changes: Mapping[str, Any]) -> dict:
    data = json.loads(json.dumps(raw))  # a deep copy: the file's own dict is never changed in place
    for key in PLAIN_KEYS:
        if key in changes:
            data[key] = changes[key]
    if "video" in changes:
        data["video"] = {**data.get("video", {}), "path": changes["video"]}
    if changes.get("phrase"):
        data["emergency"] = {**data.get("emergency", {}), "phrase": changes["phrase"]}
    return data


def save_settings(paths: Paths, changes: Mapping[str, Any], session_running: bool) -> str:
    """ "" when saved, else the message for the window. config.json is untouched unless the new one is valid."""

    def change(raw: dict) -> dict:
        if (changes.get("phrase") or "") != (changes.get("phrase_again") or ""):
            raise ValueError(PHRASES_DIFFER)
        return _changed(raw, changes)

    return write_config(paths, change, session_running)


def write_config(paths: Paths, change: Callable[[dict], dict], session_running: bool) -> str:
    """Apply change to config.json's data: "" when saved, else the message for the window (a ValueError from change
    is one). Refused during a session and while config.json is not a JSON object; the result, not the old file, is
    checked before it replaces the old one, and every key change does not touch is kept as written."""
    if session_running:
        return SESSION_LOCKED
    with _WRITE_LOCK:
        return _write_locked(paths, change)


def _replace(source: Path, target: Path) -> bool:
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return True
        except PermissionError:
            if attempt < REPLACE_ATTEMPTS - 1:
                time.sleep(REPLACE_PAUSE)
    return False


def _write_locked(paths: Paths, change: Callable[[dict], dict]) -> str:
    try:
        raw = json.loads(paths.config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return CONFIG_BROKEN
    if not isinstance(raw, dict):
        return CONFIG_BROKEN
    try:
        data = change(raw)
    except ValueError as error:
        return str(error)
    except (TypeError, AttributeError, KeyError):  # a hand-edited section of the wrong type
        return CONFIG_BROKEN
    paths.state.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=paths.state, suffix=".config.tmp")
    candidate = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        load_config(candidate)
        if not _replace(candidate, paths.config):
            return CONFIG_BUSY
    except ConfigError as error:
        return str(error)
    finally:
        candidate.unlink(missing_ok=True)
    return ""
