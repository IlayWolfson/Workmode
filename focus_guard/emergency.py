"""Emergency exit: recognise the shortcuts and check the typed phrase. No Windows calls."""

import unicodedata
from collections.abc import Iterable


def normalize_phrase(text: str) -> str:
    """NFKC, no invisible format marks (bidi, zero-width), runs of any spaces collapsed to one."""
    kept = (ch for ch in unicodedata.normalize("NFKC", text) if unicodedata.category(ch) != "Cf")
    return " ".join("".join(kept).split())


def phrase_matches(typed: str, expected: str) -> bool:
    wanted = normalize_phrase(expected)
    return bool(wanted) and normalize_phrase(typed) == wanted


class EmergencyDetector:
    def __init__(
        self, hold_chords: Iterable[tuple[int, ...]], hold_ms: int, instant_chords: Iterable[tuple[int, ...]]
    ) -> None:
        self._rules = [(frozenset(chord), 0) for chord in instant_chords]
        self._rules += [(frozenset(chord), hold_ms) for chord in hold_chords]
        self._since: dict[frozenset[int], int] = {}
        self._fired: set[frozenset[int]] = set()

    def update(self, pressed: Iterable[int], now_ms: int) -> bool:
        held = set(pressed)
        triggered = False
        for chord, needed in self._rules:
            if chord <= held:
                started = self._since.setdefault(chord, now_ms)
                if chord not in self._fired and now_ms - started >= needed:
                    self._fired.add(chord)
                    triggered = True
            else:
                self._since.pop(chord, None)
                self._fired.discard(chord)
        return triggered
