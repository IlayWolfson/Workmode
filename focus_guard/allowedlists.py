"""The allow-list screen's service: what the window shows, and every add or remove, saved safely into config.json.

Each change answers {"ok": True, "view": ...} or {"ok": False, "message": ...}; the window never sees a stack trace.
"""

import json
from collections.abc import Callable
from pathlib import Path

from .allowedit import (
    NOT_YOUTUBE,
    add_app,
    add_site,
    add_youtube,
    remove_app,
    remove_site,
    remove_youtube,
    site_choice,
    word_entry,
    youtube_choices,
)
from .paths import Paths
from .ports import ProgramSource
from .programs import HIDDEN, match, program_from_drop, to_offer
from .settings import write_config
from .youtube import parse_playlist, parse_video
from .ytnames import TitleCache, lookup

NEEDS_CONNECTION = "כדי להתיר את כל הערוץ צריך חיבור לאינטרנט."
NO_CHANNEL = "לא מצאתי את הערוץ של הסרטון. הדבק קישור לדף הערוץ עצמו."
UNKNOWN = "בקשה לא מוכרת."
KIND_LABELS = {"channel": "ערוץ", "playlist": "פלייליסט", "video": "סרטון"}
YOUTUBE_KINDS = (("channel", "channels"), ("playlist", "playlists"), ("video", "videos"))


def _isolated(text: str) -> str:
    """Keeps an English name (or "@handle") in its own direction inside a Hebrew line: FSI ... PDI."""
    return f"⁨{text}⁩" if text else ""


def _youtube_value(parse: Callable[[str], str], text: str) -> str:
    try:
        return parse(text)
    except ValueError:
        raise ValueError(NOT_YOUTUBE) from None


class AllowedLists:
    def __init__(
        self,
        paths: Paths,
        programs: ProgramSource,
        fetch: Callable[[str], str],
        session_running: Callable[[], bool],
    ) -> None:
        self._paths, self._programs, self._fetch, self._running = paths, programs, fetch, session_running
        self._titles = TitleCache(paths.youtube_names)

    def _raw(self) -> dict:
        try:
            data = json.loads(self._paths.config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def view(self) -> dict:
        raw = self._raw()
        apps = [app for app in raw.get("allowed_apps", []) if isinstance(app, dict)]
        processes = [str(app.get("process", "")) for app in apps]
        hidden = HIDDEN | {str(name).lower() for name in raw.get("protected_processes", [])}
        youtube = raw.get("youtube", {}) if isinstance(raw.get("youtube"), dict) else {}
        return {
            "apps": [
                {
                    "process": process,
                    "name": self._programs.name_of(process, str((app.get("launch") or [""])[0])),
                    "removable": len(apps) > 1,
                }
                for process, app in zip(processes, apps, strict=True)
            ],
            "open": [
                {"path": program.path, "name": program.name}
                for program in to_offer(self._programs.running(), processes, hidden)
            ],
            "sites": [
                {"entry": site, "label": f"מילה: {site.strip('*')}" if site.startswith("*") else site}
                for site in raw.get("allowed_sites", [])
            ],
            "youtube": [
                {
                    "kind": kind,
                    "value": value,
                    "label": f"{KIND_LABELS[kind]}: {_isolated(self._titles.get(kind, value) or value)}",
                }
                for kind, key in YOUTUBE_KINDS
                for value in youtube.get(key, [])
            ],
        }

    def site_preview(self, text: str) -> dict:
        try:
            choice = site_choice(text)
        except ValueError as error:
            return {"ok": False, "message": str(error)}
        covers = f"כולל כל מה שמתחתיו, למשל www.{choice.host}"
        return {"ok": True, "host": choice.host, "covers": covers, "word": choice.word}

    def youtube_preview(self, text: str) -> dict:
        try:
            choices = youtube_choices(text)
        except ValueError as error:
            return {"ok": False, "message": str(error)}
        video = next((choice.value for choice in choices if choice.kind == "video"), "")
        found = lookup("video", video, self._fetch) if video else None
        if found is not None:
            self._titles.put("video", video, found.title)
        answer = []
        for choice in choices:
            value = found.channel if choice.kind == "channel" and not choice.value and found else choice.value
            answer.append({"kind": choice.kind, "value": value, "label": _isolated(self._label(choice.kind, value))})
        return {"ok": True, "choices": answer}

    def _label(self, kind: str, value: str) -> str:
        if kind == "channel" or not value:
            return value
        title = self._titles.get(kind, value)
        if not title:
            found = lookup(kind, value, self._fetch)
            title = found.title if found else ""
            if title:
                self._titles.put(kind, value, title)
        return title or value

    def find(self, query: str) -> list[dict]:
        return [{"path": program.path, "name": program.name} for program in match(query, self._programs.installed())]

    def add(self, kind: str, value: str) -> dict:
        try:
            change = self._adder(kind, value)
        except ValueError as error:
            return {"ok": False, "message": str(error)}
        return self._save(change)

    def _adder(self, kind: str, value: str) -> Callable[[dict], dict]:
        if kind == "app":
            return lambda raw: add_app(raw, Path(value).name, value)
        if kind == "site":
            host = site_choice(value).host
            return lambda raw: add_site(raw, host)
        if kind == "word":
            entry = word_entry(value)
            return lambda raw: add_site(raw, entry)
        if kind in ("playlist", "video"):
            parse = parse_playlist if kind == "playlist" else parse_video
            found = _youtube_value(parse, value)
            self._label(kind, found)  # caches the title for the list
            return lambda raw: add_youtube(raw, kind, found)
        if kind == "channel":
            channel = self._channel(value)
            return lambda raw: add_youtube(raw, "channel", channel)
        raise ValueError(UNKNOWN)

    def _channel(self, text: str) -> str:
        first = youtube_choices(text)[0]
        if first.kind != "channel":
            raise ValueError(NOT_YOUTUBE)
        if first.value:
            return first.value
        found = lookup("video", parse_video(text), self._fetch)
        if found is None:
            raise ValueError(NEEDS_CONNECTION)
        if not found.channel:
            raise ValueError(NO_CHANNEL)
        return found.channel

    def remove(self, kind: str, value: str) -> dict:
        if kind == "app":
            return self._save(lambda raw: remove_app(raw, value))
        if kind in ("site", "word"):
            return self._save(lambda raw: remove_site(raw, value))
        if kind in KIND_LABELS:
            return self._save(lambda raw: remove_youtube(raw, kind, value))
        return {"ok": False, "message": UNKNOWN}

    def add_file(self, path: str) -> dict:
        try:
            program = program_from_drop(path, self._programs)
        except ValueError as error:
            return {"ok": False, "message": str(error)}
        return self._save(lambda raw: add_app(raw, program.process, program.path))

    def _save(self, change: Callable[[dict], dict]) -> dict:
        problem = write_config(self._paths, change, self._running())
        return {"ok": False, "message": problem} if problem else {"ok": True, "view": self.view()}
