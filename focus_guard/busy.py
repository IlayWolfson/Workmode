"""Sources of busy time for the calendar. No source is connected yet, so nothing is drawn."""

from collections.abc import Sequence


class NoBusy:
    def busy(self, start: float, end: float) -> Sequence[tuple[float, float]]:
        return []
