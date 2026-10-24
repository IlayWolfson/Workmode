"""Roast lines: a small stock fetched in the background, cleaned, with a local fallback."""

import json
import os
import random
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LEADING_RE = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s*")
QUOTES = " \"'“”"

FALLBACK = (
    "שוב בורחים מהעבודה? איזו הפתעה.",
    "הקוד לא יכתוב את עצמו, לצערנו.",
    "החברים יחכו. התואר לא.",
    "זה היה ניסיון בריחה? חלש.",
    "עוד ניסיון כזה ותקבלו מדליית נשירה.",
    "הסשן עוד לא נגמר. התירוץ כבר כן.",
    "אפילו Alt+F4 לא יציל מהמטלה הזאת.",
    "הדדליין לא מתרגש מהדיסקורד.",
    "ברוכים השבים. לעבודה, בבקשה.",
    "מי שמתמיד מסיים. מי שבורח מקבל ירידות.",
    "כל בריחה כזו שווה עוד חמש דקות עבודה.",
    "נחמד לנסות. עכשיו חוזרים ללימודים.",
    "הכפתור הזה לא עובד. נסו להתרכז.",
    "התוכנה ראתה. התוכנה זוכרת. התוכנה צוחקת.",
    "עוד דקה ותוכלו לצאת. סתם, לא.",
)


def clean_line(text: str, max_words: int) -> str:
    first = str(text).replace("\r", "\n").split("\n")[0]
    line = LEADING_RE.sub("", " ".join(first.split())).strip(QUOTES)
    return " ".join(line.split()[:max_words])


def parse_lines(raw_text: str, max_words: int) -> list[str]:
    lines: list[str] = []
    for raw in str(raw_text).splitlines():
        line = clean_line(raw, max_words)
        if line and line not in lines:
            lines.append(line)
    return lines


def build_request(model: str, api_key: str, instruction: str, count: int, language: str) -> urllib.request.Request:
    prompt = f"{instruction}\n\nCount: {count}. Language: {language}. One line each, no numbering."
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    return urllib.request.Request(
        ENDPOINT.format(model=model),
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )


def parse_response(payload: Any) -> str:
    try:
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""


class GeminiFetcher:
    def __init__(
        self,
        model: str,
        instruction: str,
        language: str,
        max_words: int,
        env: Mapping[str, str] | None = None,
        opener: Callable | None = None,
        timeout: float = 5,
    ) -> None:
        self._model, self._instruction, self._language = model, instruction, language
        self._max_words, self._timeout = max_words, timeout
        self._env = os.environ if env is None else env
        self._opener = opener or urllib.request.urlopen

    def __call__(self, count: int) -> list[str]:
        key = self._env.get("GEMINI_API_KEY", "")
        if not key:
            return []
        request = build_request(self._model, key, self._instruction, count, self._language)
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return []
        return parse_lines(parse_response(payload), self._max_words)[:count]


class RoastStock:
    def __init__(
        self,
        fetch: Callable[[int], list[str]],
        size: int,
        refill_at: int,
        rng: random.Random | None = None,
        spawn: Callable[[Callable[[], None]], None] | None = None,
        fallback: tuple[str, ...] = FALLBACK,
    ) -> None:
        self._fetch, self._size, self._refill_at = fetch, size, refill_at
        self._rng = rng or random.Random()
        self._spawn = spawn or (lambda function: threading.Thread(target=function, daemon=True).start())
        self._fallback = fallback
        self._lines: list[str] = []
        self._refilling = False
        self._lock = threading.Lock()

    def prime(self) -> None:
        self._start_refill()

    def next(self) -> str:
        with self._lock:
            line = self._lines.pop(0) if self._lines else None
            low = len(self._lines) <= self._refill_at
        if low:
            self._start_refill()
        return line if line else self._rng.choice(self._fallback)

    def _start_refill(self) -> None:
        with self._lock:
            if self._refilling:
                return
            self._refilling = True
        self._spawn(self._refill)

    def _refill(self) -> None:
        fresh: list[str]
        try:
            fresh = self._fetch(self._size)
        except Exception:
            fresh = []
        with self._lock:
            self._lines.extend(fresh)
            self._refilling = False
