"""Load and validate config.json. Refuses to start on anything it cannot be sure about."""

import json
import os
import re
import shutil
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .emergency import normalize_phrase
from .jsonfile import write_text_atomic
from .keys import parse_chord
from .youtube import YouTubeLists, parse_channel, parse_playlist, parse_video, youtube_lists

PLACEHOLDER_PREFIX = "CHANGE-ME"
MIN_PHRASE, MAX_PHRASE = 8, 200  # the typed phrase passes through a small pipe, see ui.MAX_TYPED
DEFAULT_PROTECTED = (
    "explorer.exe",
    "dwm.exe",
    "csrss.exe",
    "winlogon.exe",
    "sihost.exe",
    "taskhostw.exe",
    "ctfmon.exe",
    "searchhost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "textinputhost.exe",
    "lockapp.exe",
    "securityhealthsystray.exe",
    "applicationframehost.exe",
)
DEFAULT_INSTRUCTION = (
    "כתוב ירידות קצרות, מצחיקות ולא פוגעות בעברית, שמופנות למי שניסה לברוח באמצע סשן עבודה. "
    "הירידות הן על הניסיון לברוח בלבד, לא על הערך, הציונים או המראה של האדם. בלי קללות קשות ובלי שמות."
)
TOP_LEVEL_KEYS = frozenset(
    {
        "allowed_apps",
        "allowed_sites",
        "protected_processes",
        "popup_seconds",
        "grace_seconds",
        "window_percent",
        "start_with_windows",
        "songs",
        "song_files",
        "videos",
        "video_files",
        "video",
        "roasts",
        "emergency",
        "server",
        "youtube",
    }
)
VIDEO_SUFFIXES = (".mp4", ".webm")
SITE_RE = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")
WORD_SITE_RE = re.compile(r"^\*([a-z0-9-]+)\*$")  # "*word*": any host containing the word
WORD_MIN_LETTERS = 3
LABELS = {"pageup": "PgUp", "pagedown": "PgDn", "del": "Del", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}


class ConfigError(ValueError):
    """The configuration is invalid; the tool must not start."""


@dataclass(frozen=True)
class AllowedApp:
    process: str
    launch: tuple


@dataclass(frozen=True)
class Config:
    allowed_apps: tuple
    allowed_sites: tuple
    protected_processes: frozenset
    popup_seconds: int
    grace_seconds: int
    window_percent: int  # the calendar window's share of the screen
    start_with_windows: bool
    songs: tuple[str, ...]
    song_files: tuple[str, ...]  # song files the user added in settings (ticked or not)
    video_path: str
    video_fallback_url: str
    video_min_seconds: int
    roast_language: str
    roast_model: str
    roast_stock: int
    roast_refill_at: int
    roast_max_words: int
    roast_instruction: str
    hold_keys: tuple
    hold_chords: tuple
    hold_ms: int
    hotkeys: tuple
    hotkey_chords: tuple
    phrase: str
    server_port: int
    server_token: str
    youtube: YouTubeLists = YouTubeLists()
    videos: tuple[str, ...] = ()  # ticked punishment videos: bundled file names or paths
    video_files: tuple[str, ...] = ()  # video files the user added in settings (ticked or not)


def _need(condition: object, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _int(value: Any, name: str, low: int, high: int) -> int:
    _need(
        isinstance(value, int) and not isinstance(value, bool) and low <= value <= high,
        f"'{name}' must be an integer from {low} to {high}",
    )
    return value


def _text(value: Any, name: str, minimum: int = 1) -> str:
    _need(
        isinstance(value, str) and len(unicodedata.normalize("NFC", value).strip()) >= minimum,
        f"'{name}' must be text of at least {minimum} characters",
    )
    return value


def _section(data: dict, key: str, allowed_keys: set[str]) -> dict:
    section = data.get(key, {})
    _need(isinstance(section, dict), f"'{key}' must be an object")
    unknown = set(section) - allowed_keys
    _need(not unknown, f"unknown keys in '{key}': {sorted(unknown)}")
    return section


def _bool(value: Any, name: str) -> bool:
    _need(isinstance(value, bool), f"'{name}' must be true or false")
    return value


def _songs(value: Any, name: str = "songs") -> tuple[str, ...]:
    _need(
        isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value),
        f"'{name}' must be a list of file paths or bundled file names",
    )
    return tuple(value)


def _apps(value: Any) -> tuple[AllowedApp, ...]:
    _need(isinstance(value, list) and value, "'allowed_apps' must be a non-empty list")
    apps = []
    for item in value:
        _need(
            isinstance(item, dict) and set(item) <= {"process", "launch"},
            "each allowed app needs only 'process' and 'launch'",
        )
        process, launch = item.get("process"), item.get("launch")
        _need(isinstance(process, str) and process.lower().endswith(".exe"), f"bad process name: {process!r}")
        _need(
            isinstance(launch, list) and launch and all(isinstance(part, str) and part for part in launch),
            f"app {process} needs a non-empty 'launch' list",
        )
        apps.append(AllowedApp(process.lower(), tuple(launch)))
    return tuple(apps)


def word_site_ok(word: str) -> bool:
    """A "*word*" site: only a-z, 0-9 and '-', with at least three English letters (shorter words allow too much)."""
    return bool(re.fullmatch(r"[a-z0-9-]+", word)) and sum(char.isalpha() for char in word) >= WORD_MIN_LETTERS


def _site_ok(clean: str) -> bool:
    word = WORD_SITE_RE.match(clean)
    return bool(SITE_RE.match(clean)) or (word is not None and word_site_ok(word.group(1)))


def _sites(value: Any) -> tuple[str, ...]:
    _need(isinstance(value, list), "'allowed_sites' must be a list")
    sites = []
    for site in value:
        clean = site.strip().lower() if isinstance(site, str) else ""
        _need(_site_ok(clean), f"allowed_sites: bad domain {site!r}")
        sites.append(clean)
    return tuple(sites)


def _text_list(value: Any, message: str) -> list[str]:
    _need(isinstance(value, list) and all(isinstance(item, str) for item in value), message)
    return value


def _youtube(section: dict) -> YouTubeLists:
    channels = _text_list(
        section.get("channels", []), "'youtube.channels' must be a list of @handles, channel links or channel names"
    )
    playlists = _text_list(section.get("playlists", []), "'youtube.playlists' must be a list of playlist links or ids")
    for text in channels:
        try:
            parse_channel(text)
        except ValueError:
            raise ConfigError(
                f"youtube.channels: cannot use {text!r}; paste the @handle or the youtube.com/channel/ link"
            ) from None
    for text in playlists:
        try:
            parse_playlist(text)
        except ValueError:
            raise ConfigError(f"youtube.playlists: no playlist id in {text!r}") from None
    videos = _text_list(section.get("videos", []), "'youtube.videos' must be a list of video links or ids")
    for text in videos:
        try:
            parse_video(text)
        except ValueError:
            raise ConfigError(f"youtube.videos: no video id in {text!r}") from None
    return youtube_lists(channels, playlists, videos)


def _video(section: dict) -> tuple[str, str, int]:
    minimum = _int(section.get("min_seconds", 20), "video.min_seconds", 5, 300)
    path, fallback = section.get("path"), section.get("fallback_url")
    usable = ""
    if path:
        _need(
            isinstance(path, str) and path.lower().endswith(VIDEO_SUFFIXES), "video.path must be an .mp4 or .webm file"
        )
        if Path(path).is_file():
            usable = path
    if fallback:
        _need(
            isinstance(fallback, str) and urlparse(fallback).scheme == "https" and urlparse(fallback).hostname,
            "video.fallback_url must be an https URL",
        )
    return usable, fallback or "", minimum


def _chord(name: str) -> tuple[int, ...]:
    try:
        return parse_chord(name)
    except (ValueError, AttributeError) as error:
        raise ConfigError(f"emergency: {error}") from None


def _emergency(
    section: dict,
) -> tuple[tuple[str, ...], tuple[tuple[int, ...], ...], int, tuple[str, ...], tuple[tuple[int, ...], ...], str]:
    hold_keys = section.get("hold_keys", ["del", "pageup", "pagedown"])
    hotkeys = section.get("hotkeys", ["ctrl+alt+shift+q"])
    _need(isinstance(hold_keys, list) and isinstance(hotkeys, list), "emergency: key lists must be lists")
    hold_chords = []
    for name in hold_keys:
        chord = _chord(name)
        _need(len(chord) == 1, f"emergency: hold key must be a single key: {name!r}")
        hold_chords.append(chord)
    hotkey_chords = [_chord(name) for name in hotkeys]
    _need(hold_chords or hotkey_chords, "emergency: at least one shortcut is required")
    hold_ms = _int(section.get("hold_ms", 1500), "emergency.hold_ms", 0, 10000)
    phrase = _text(section.get("phrase"), "emergency.phrase", MIN_PHRASE)
    _need(len(normalize_phrase(phrase)) <= MAX_PHRASE, f"emergency.phrase: at most {MAX_PHRASE} characters")
    _need(not phrase.strip().startswith(PLACEHOLDER_PREFIX), "emergency.phrase: set your own phrase")
    return tuple(hold_keys), tuple(hold_chords), hold_ms, tuple(hotkeys), tuple(hotkey_chords), phrase


def unresolved_launches(cfg: Config, which: Callable[[str], str | None] = shutil.which) -> list[tuple[str, str]]:
    """(process, command) for every app whose launch command cannot be started as written."""
    missing = []
    for app in cfg.allowed_apps:
        command = os.path.expandvars(app.launch[0])
        if not (which(command) or Path(command).is_file()):
            missing.append((app.process, app.launch[0]))
    return missing


def load_config(path: str | Path) -> Config:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"cannot read config: {error}") from None
    return parse_config(text)


def parse_config(text: str) -> Config:
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ConfigError(f"cannot read config: {error}") from None
    _need(isinstance(data, dict), "config must be a JSON object")
    unknown = set(data) - TOP_LEVEL_KEYS
    _need(not unknown, f"unknown keys: {sorted(unknown)}")

    extra_protected = data.get("protected_processes", [])
    _need(
        isinstance(extra_protected, list) and all(isinstance(name, str) for name in extra_protected),
        "'protected_processes' must be a list of names",
    )
    video_path, video_url, video_min = _video(_section(data, "video", {"path", "fallback_url", "min_seconds"}))
    videos = _songs(data.get("videos", []), "videos")
    _need(
        video_path or video_url or videos,
        "video: the file in 'path' was not found, there is no 'fallback_url' and no video is ticked in 'videos'",
    )
    roasts = _section(data, "roasts", {"language", "model", "stock", "refill_at", "max_words", "instruction"})
    stock = _int(roasts.get("stock", 10), "roasts.stock", 3, 30)
    hold_keys, hold_chords, hold_ms, hotkeys, hotkey_chords, phrase = _emergency(
        _section(data, "emergency", {"hold_keys", "hold_ms", "hotkeys", "phrase"})
    )
    server_port, server_token = _server(data)

    return Config(
        allowed_apps=_apps(data.get("allowed_apps")),
        allowed_sites=_sites(data.get("allowed_sites", [])),
        protected_processes=frozenset(DEFAULT_PROTECTED) | frozenset(name.lower() for name in extra_protected),
        popup_seconds=_int(data.get("popup_seconds", 10), "popup_seconds", 3, 60),
        grace_seconds=_int(data.get("grace_seconds", 20), "grace_seconds", 0, 120),
        window_percent=_int(data.get("window_percent", 85), "window_percent", 50, 100),
        start_with_windows=_bool(data.get("start_with_windows", True), "start_with_windows"),
        songs=_songs(data.get("songs", [])),
        song_files=_songs(data.get("song_files", []), "song_files"),
        video_path=video_path,
        video_fallback_url=video_url,
        video_min_seconds=video_min,
        roast_language=_text(roasts.get("language", "he"), "roasts.language"),
        roast_model=_text(roasts.get("model", "gemini-flash-latest"), "roasts.model"),
        roast_stock=stock,
        roast_refill_at=_int(roasts.get("refill_at", 3), "roasts.refill_at", 0, stock),
        roast_max_words=_int(roasts.get("max_words", 12), "roasts.max_words", 4, 30),
        roast_instruction=_text(roasts.get("instruction", DEFAULT_INSTRUCTION), "roasts.instruction", 10),
        hold_keys=hold_keys,
        hold_chords=hold_chords,
        hold_ms=hold_ms,
        hotkeys=hotkeys,
        hotkey_chords=hotkey_chords,
        phrase=phrase,
        server_port=server_port,
        server_token=server_token,
        youtube=_youtube(_section(data, "youtube", {"channels", "playlists", "videos"})),
        videos=videos,
        video_files=_songs(data.get("video_files", []), "video_files"),
    )


def _server(data: dict) -> tuple[int, str]:
    server = _section(data, "server", {"port", "token"})
    token = _text(server.get("token"), "server.token", 16)
    _need(not token.startswith(PLACEHOLDER_PREFIX), "server.token: run 'init' to generate one")
    return _int(server.get("port", 47653), "server.port", 1024, 65535), token


def load_server(path: str | Path) -> tuple[int, str] | None:
    """The bridge port and token from config.json even when another section is invalid, or None. Never raises."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _server(data)
    except ConfigError:
        return None


def load_config_safe(path: str | Path, last_good: str | Path) -> tuple[Config | None, str]:
    """The config and "" when it loads; otherwise the last config that loaded (or None) and the error.

    A broken hand edit never stops the background process or a scheduled session. Never raises.
    """
    try:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigError(f"cannot read config: {error}") from None
        cfg = parse_config(text)  # the text that loaded is the one copied: read once
    except ConfigError as error:
        try:
            return load_config(last_good), str(error)
        except ConfigError:
            return None, str(error)
    copy = Path(last_good)
    try:
        if not copy.exists() or copy.read_text(encoding="utf-8") != text:
            write_text_atomic(copy, text)  # never a half-written copy
    except OSError:
        pass  # the copy is a safety net; failing to refresh it must not stop anything
    return cfg, ""


def _label(chord_text: str) -> str:
    return "+".join(LABELS.get(part, part.upper()) for part in chord_text.lower().split("+"))


def hint_text(cfg: Config) -> str:
    parts = []
    if cfg.hold_keys:
        parts.append("להחזיק " + " / ".join(_label(name) for name in cfg.hold_keys))
    if cfg.hotkeys:
        parts.append(" / ".join(_label(name) for name in cfg.hotkeys))
    return "יציאת חירום: " + ", או ".join(parts)
