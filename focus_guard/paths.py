"""Where the tool keeps its files, relative to the project folder."""

from pathlib import Path


class Paths:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.state = self.root / "state"
        self.config = self.root / "config.json"
        self.example = self.root / "config.example.json"
        self.session = self.state / "session.json"
        self.attempts = self.state / "attempts.log"
        self.waiting = self.state / "waiting.json"
        self.mutes = self.state / "mutes.json"
        self.mute_request = self.state / "mute_request"
        self.exit_request = self.state / "exit_request"
        self.events = self.state / "events.json"
        self.outcomes = self.state / "outcomes.json"
        self.recent_songs = self.state / "recent_songs.json"
        self.youtube_names = self.state / "youtube_names.json"
        self.config_last_good = self.state / "config.last-good.json"
        self.guard_pid = self.state / "guard.pid"
        self.guardian_pid = self.state / "guardian.pid"
        self.app_pid = self.state / "app.pid"
        self.app_error_log = self.state / "app-error.log"
        self.extension_config = self.root / "extension" / "config.js"
        self.icon_source = self.root / "assets" / "icon_source.png"
        self.icon = self.root / "assets" / "focus_guard.ico"


DEFAULT = Paths(Path(__file__).resolve().parent.parent)
