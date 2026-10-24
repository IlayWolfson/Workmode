"""The allow-list screen's logic: what a pasted link offers, and adding or removing entries in config.json's data.

Every edit takes the raw config dict and returns a new one; the input is never changed. Problems are a ValueError
whose text is the Hebrew message the window shows.
"""

import copy
from dataclasses import dataclass
from typing import Literal
from urllib.parse import ParseResult, parse_qs, urlparse

from .config import SITE_RE, word_site_ok
from .youtube import HOSTS, parse_channel, parse_playlist, parse_video

BAD_SITE = "זה לא נראה כמו כתובת של אתר."
SHORT_WORD = "המילה צריכה לפחות 3 אותיות באנגלית."
ALREADY = "זה כבר מותר."
LAST_APP = "חייבת להישאר לפחות תוכנה אחת."
NOT_YOUTUBE = "זה לא קישור של יוטיוב."

YouTubeKind = Literal["channel", "playlist", "video"]
YOUTUBE_KEYS: dict[str, str] = {"channel": "channels", "playlist": "playlists", "video": "videos"}


@dataclass(frozen=True)
class SiteChoice:
    host: str  # "uni.ac.il": the site and everything under it
    word: str  # "uni": suggested for "any address containing the word", or "" when no part of the host qualifies


@dataclass(frozen=True)
class YouTubeChoice:
    kind: YouTubeKind
    value: str  # "" for the channel of a video link: it must be looked up


def _parts(text: str) -> ParseResult:
    return urlparse(text if "://" in text else "https://" + text)


def site_choice(text: str) -> SiteChoice:
    host = (_parts(text.strip()).hostname or "").lower().rstrip(".").removeprefix("www.")
    if not SITE_RE.match(host):
        raise ValueError(BAD_SITE)
    labels = [label for label in host.split(".")[:-1] if word_site_ok(label)]
    return SiteChoice(host, max(labels, key=len, default=""))


def word_entry(word: str) -> str:
    clean = word.strip().lower()
    if not word_site_ok(clean):
        raise ValueError(SHORT_WORD)
    return f"*{clean}*"


def _playlist_in(text: str) -> str:
    found = parse_qs(_parts(text).query).get("list", [""])[0]
    try:
        return parse_playlist(found) if found else ""
    except ValueError:
        return ""


def youtube_choices(text: str) -> tuple[YouTubeChoice, ...]:
    """What a pasted link can allow, in the order channel, playlist, video. Bare names are not accepted here."""
    clean = text.strip()
    if clean.startswith("@"):
        try:
            return (YouTubeChoice("channel", parse_channel(clean)[1]),)
        except ValueError:
            raise ValueError(NOT_YOUTUBE) from None
    if not clean or (_parts(clean).hostname or "").lower() not in HOSTS | {"youtu.be"}:
        raise ValueError(NOT_YOUTUBE)
    playlist = _playlist_in(clean)
    try:
        video = parse_video(clean)
    except ValueError:
        video = ""
    if video:
        middle = (YouTubeChoice("playlist", playlist),) if playlist else ()
        return (YouTubeChoice("channel", ""), *middle, YouTubeChoice("video", video))
    if playlist:
        return (YouTubeChoice("playlist", playlist),)
    try:
        kind, value = parse_channel(clean)
    except ValueError:
        raise ValueError(NOT_YOUTUBE) from None
    if kind == "name":
        raise ValueError(NOT_YOUTUBE)
    return (YouTubeChoice("channel", value),)


def _with(raw: dict, key: str, value: object) -> dict:
    data = copy.deepcopy(raw)
    data[key] = value
    return data


def add_site(raw: dict, entry: str) -> dict:
    sites = list(raw.get("allowed_sites", []))
    if entry.lower() in (site.lower() for site in sites):
        raise ValueError(ALREADY)
    return _with(raw, "allowed_sites", [*sites, entry])


def remove_site(raw: dict, entry: str) -> dict:
    return _with(raw, "allowed_sites", [site for site in raw.get("allowed_sites", []) if site != entry])


def add_app(raw: dict, process: str, launch: str) -> dict:
    apps = list(raw.get("allowed_apps", []))
    if process.lower() in (app.get("process", "").lower() for app in apps):
        raise ValueError(ALREADY)
    return _with(raw, "allowed_apps", [*apps, {"process": process, "launch": [launch]}])


def remove_app(raw: dict, process: str) -> dict:
    kept = [app for app in raw.get("allowed_apps", []) if app.get("process", "").lower() != process.lower()]
    if not kept:
        raise ValueError(LAST_APP)
    return _with(raw, "allowed_apps", kept)


def _same(kind: str, one: str, other: str) -> bool:
    return one.lower() == other.lower() if kind == "channel" else one == other  # ids are case-sensitive


def add_youtube(raw: dict, kind: str, value: str) -> dict:
    key = YOUTUBE_KEYS[kind]
    section = dict(raw.get("youtube", {}))
    values = list(section.get(key, []))
    if any(_same(kind, value, item) for item in values):
        raise ValueError(ALREADY)
    return _with(raw, "youtube", {**section, key: [*values, value]})


def remove_youtube(raw: dict, kind: str, value: str) -> dict:
    key = YOUTUBE_KEYS[kind]
    section = dict(raw.get("youtube", {}))
    return _with(raw, "youtube", {**section, key: [item for item in section.get(key, []) if item != value]})
