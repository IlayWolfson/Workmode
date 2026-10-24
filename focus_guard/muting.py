"""Programs the tool muted, with their mute state from before (state/mutes.json)."""

from pathlib import Path

from .jsonfile import read_json, write_json


class MuteStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, bool]:
        """Lower-case process name -> was it muted before the tool muted it."""
        data = read_json(self._path)
        if not isinstance(data, dict):
            return {}
        return {name: value for name, value in data.items() if isinstance(value, bool)}

    def remember(self, process: str, was_muted: bool) -> None:
        """Keep the first state seen, so muting twice never loses the original."""
        mutes, name = self.load(), process.lower()
        if name not in mutes:
            write_json(self._path, {**mutes, name: was_muted})

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
