"""What happened to each planned occurrence (state/outcomes.json). Internal only: never shown to the user."""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from .jsonfile import read_json, write_json

OUTCOMES = ("declined", "exited", "completed", "skipped")
KEEP_DAYS = 60


def _day(key: str) -> date | None:
    try:
        return date.fromisoformat(key.rpartition("@")[2])
    except ValueError:
        return None


class OutcomeStore:
    def __init__(self, path: str | Path, today: Callable[[], date] = date.today) -> None:
        self._path, self._today = Path(path), today

    def load(self) -> dict[str, str]:
        data = read_json(self._path)
        if not isinstance(data, dict):
            return {}
        return {key: value for key, value in data.items() if isinstance(key, str) and value in OUTCOMES}

    def record(self, key: str, outcome: str) -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        oldest = self._today() - timedelta(days=KEEP_DAYS)
        kept = {name: value for name, value in self.load().items() if (_day(name) or oldest) >= oldest}
        write_json(self._path, {**kept, key: outcome})
