"""Append-only attempt log: one JSON object per line. Never stores keystrokes or secrets."""

import json
from datetime import UTC, datetime
from pathlib import Path

ATTEMPT_KINDS = frozenset({"blocked_app", "closed", "minimized", "resized", "blocked_site", "tab_closed"})
KINDS = ATTEMPT_KINDS | frozenset(
    {"force_closed", "launch_failed", "emergency_exit", "session_start", "session_end", "error"}
)
MAX_DETAIL = 80


class AttemptLog:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def record(self, kind: str, detail: str = "", now: float | None = None) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown attempt kind: {kind!r}")
        moment = datetime.fromtimestamp(now, tz=UTC) if now is not None else datetime.now(UTC)
        line = json.dumps(
            {"t": moment.isoformat(), "type": kind, "detail": str(detail)[:MAX_DETAIL]}, ensure_ascii=False
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def read(self) -> list[dict]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and "type" in entry and "t" in entry:
                entries.append(entry)
        return entries

    def count_since(self, since_epoch: float) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.read():
            try:
                when = datetime.fromisoformat(entry["t"]).timestamp()
            except (ValueError, TypeError):
                continue
            if when >= since_epoch and entry["type"] in ATTEMPT_KINDS:
                counts[entry["type"]] = counts.get(entry["type"], 0) + 1
        return counts
