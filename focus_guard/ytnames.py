"""Titles for the allow-list screen: what a YouTube video or playlist is called, and whose channel a video is.

From YouTube's public oEmbed address (no key, no account). Titles are only for display and are cached under state/;
config.json keeps only the ids.
"""

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .jsonfile import read_json, write_json
from .youtube import CHANNEL_ID_RE

ORIGIN = "https://www.youtube.com"
TIMEOUT = 5  # seconds


@dataclass(frozen=True)
class Found:
    title: str
    channel: str  # the video's channel as "@handle" or a "UC..." id, or ""


def _oembed(address: str) -> str:
    return f"{ORIGIN}/oembed?url={quote(address, safe='')}&format=json"


def _handle(author_url: str) -> str:
    """The channel as config.json can hold it: "@handle" or a "UC..." id; "" for old /user/ or /c/ addresses."""
    parts = author_url.rstrip("/").split("/")
    if parts[-1].startswith("@"):
        return parts[-1].lower()
    if len(parts) >= 2 and parts[-2] == "channel" and CHANNEL_ID_RE.match(parts[-1]):
        return parts[-1]
    return ""


def lookup(kind: str, value: str, fetch: Callable[[str], str]) -> Found | None:
    """None when offline, when YouTube answers something unexpected, or for a channel (shown by its handle)."""
    if kind == "video":
        address = f"{ORIGIN}/watch?v={value}"
    elif kind == "playlist":
        address = f"{ORIGIN}/playlist?list={value}"
    else:
        return None
    try:
        data = json.loads(fetch(_oembed(address)))
        return Found(str(data["title"]), _handle(str(data.get("author_url", ""))) if kind == "video" else "")
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fetch_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:  # noqa: S310 - a fixed https address
        return str(answer.read().decode("utf-8"))


class TitleCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _all(self) -> dict:
        data = read_json(self.path)
        return data if isinstance(data, dict) else {}

    def get(self, kind: str, value: str) -> str:
        title = self._all().get(f"{kind}:{value}", "")
        return title if isinstance(title, str) else ""

    def put(self, kind: str, value: str, title: str) -> None:
        write_json(self.path, {**self._all(), f"{kind}:{value}": title})
