"""One-step setup on a new computer: python -m focus_guard.install (install.cmd runs it)."""

import io
import json
import sys
from collections.abc import Callable
from pathlib import Path

from .autostart import apply as apply_autostart
from .cli import _default_icon_maker, _default_shortcut_maker, cmd_check, cmd_init, cmd_shortcut
from .config import load_config_safe
from .paths import DEFAULT, Paths

VIDEO_SUFFIXES = (".mp4", ".webm")


def localize_video(config_path: str | Path, media_dir: str | Path) -> bool:
    """Point video.path at the copy bundled in media/. Returns True when the config was changed."""
    clips = sorted(path for path in Path(media_dir).glob("*") if path.suffix.lower() in VIDEO_SUFFIXES)
    if not clips or not Path(config_path).exists():
        return False
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    data.setdefault("video", {})["path"] = clips[0].resolve().as_posix()
    Path(config_path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def main(paths: Paths = DEFAULT, out: Callable[[str], None] = print) -> int:
    if localize_video(paths.config, paths.root / "media"):
        out("Video path set to the copy in the media folder.")
    code = cmd_init(paths, out)
    if code != 0:
        return code
    checked = cmd_check(paths, out)
    if checked != 0:
        out("Fix the problem above in config.json, then run: python -m focus_guard check")
    shortcut = cmd_shortcut(paths, out, _default_icon_maker(), _default_shortcut_maker())
    cfg, _ = load_config_safe(paths.config, paths.config_last_good)
    if apply_autostart(paths, cfg.start_with_windows if cfg is not None else True) == "created":
        out('Starts with Windows (in the tray). Turn it off with "start_with_windows": false in config.json.')
    return checked or shortcut


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
