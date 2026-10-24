"""YouTube channels and playlists allowed during a session: parsed and normalized once, for the extension."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
PLAYLIST_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})

ChannelKind = Literal["handle", "id", "name"]


@dataclass(frozen=True)
class YouTubeLists:
    handles: tuple[str, ...] = ()  # "@3blue1brown"
    channel_ids: tuple[str, ...] = ()  # "UC..." as written: addresses with it are case-sensitive
    names: tuple[str, ...] = ()  # normalized, matched against the whole channel name
    playlists: tuple[str, ...] = ()
    videos: tuple[str, ...] = ()  # 11-character video ids, case-sensitive

    def is_empty(self) -> bool:
        return not (self.handles or self.channel_ids or self.names or self.playlists or self.videos)

    def as_json(self) -> dict[str, list[str]]:
        return {
            "handles": list(self.handles),
            "channel_ids": list(self.channel_ids),
            "names": list(self.names),
            "playlists": list(self.playlists),
            "videos": list(self.videos),
        }


def normalize_name(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip().lower()


def _handle(rest: str) -> str:
    value = unquote(rest)
    if not value or "/" in value or any(char.isspace() for char in value):
        raise ValueError(f"not a channel handle: @{rest}")
    return "@" + value.lower()


def _from_link(text: str) -> tuple[ChannelKind, str]:
    parts = urlparse(text if "://" in text else "https://" + text)
    if (parts.hostname or "") not in HOSTS:
        raise ValueError(f"not a YouTube channel link: {text}")
    segments = [segment for segment in parts.path.split("/") if segment]
    if segments and segments[0].startswith("@"):
        return "handle", _handle(segments[0][1:])
    if len(segments) >= 2 and segments[0] == "channel" and CHANNEL_ID_RE.match(segments[1]):
        return "id", segments[1]
    raise ValueError(f"not a channel link: {text}")


def parse_channel(text: str) -> tuple[ChannelKind, str]:
    clean = text.strip()
    if not clean:
        raise ValueError("empty channel")
    if clean.startswith("@"):
        return "handle", _handle(clean[1:])
    if CHANNEL_ID_RE.match(clean):
        return "id", clean
    if "://" in clean or "youtube.com/" in clean.lower():  # a link, never a name
        return _from_link(clean)
    return "name", normalize_name(clean)


def parse_playlist(text: str) -> str:
    clean = text.strip()
    if "list=" in clean:
        clean = parse_qs(urlparse(clean).query).get("list", [""])[0]
    if not PLAYLIST_RE.match(clean):
        raise ValueError(f"no playlist id in {text!r}")
    return clean


def parse_video(text: str) -> str:
    """The video id of a bare id or a watch, youtu.be, live or embed link. Shorts are never a video here."""
    clean = text.strip()
    if VIDEO_RE.match(clean):
        return clean
    parts = urlparse(clean if "://" in clean else "https://" + clean)
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]
    found = ""
    if host == "youtu.be" and len(segments) == 1:
        found = segments[0]
    elif host in HOSTS and segments == ["watch"]:
        found = parse_qs(parts.query).get("v", [""])[0]
    elif host in HOSTS and len(segments) == 2 and segments[0] in ("live", "embed"):
        found = segments[1]
    if not VIDEO_RE.match(found):
        raise ValueError(f"no video id in {text!r}")
    return found


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def youtube_lists(channels: Sequence[str], playlists: Sequence[str], videos: Sequence[str] = ()) -> YouTubeLists:
    found: dict[ChannelKind, list[str]] = {"handle": [], "id": [], "name": []}
    for text in channels:
        kind, value = parse_channel(text)
        found[kind].append(value)
    return YouTubeLists(
        handles=_unique(found["handle"]),
        channel_ids=_unique(found["id"]),
        names=_unique(found["name"]),
        playlists=_unique([parse_playlist(text) for text in playlists]),
        videos=_unique([parse_video(text) for text in videos]),
    )
