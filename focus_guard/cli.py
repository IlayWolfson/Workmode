"""Command line: python -m focus_guard <init|check|windows|start|status>."""

import argparse
import json
import secrets
import shutil
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .config import hint_text, load_config_safe, unresolved_launches
from .launcher import spawn_module
from .paths import DEFAULT, Paths
from .procfiles import pid_alive
from .session import MAX_MINUTES, Session, load_session
from .starting import UpdateInProgress, begin_session
from .watcher import WinInfo


def _extension_config(port: int, token: str) -> str:
    return f"export const FOCUS = {{ port: {port}, token: {json.dumps(token)} }};\n"


def cmd_init(paths: Paths, out: Callable[[str], None]) -> int:
    if not paths.example.exists():
        out("config.example.json is missing.")
        return 1
    paths.state.mkdir(exist_ok=True)
    if not paths.config.exists():
        shutil.copyfile(paths.example, paths.config)
        out("Created config.json from the example. Edit it (apps, sites, video, your phrase), then run: check")
    data = json.loads(paths.config.read_text(encoding="utf-8"))
    server = data.setdefault("server", {})
    token = server.get("token")
    if not isinstance(token, str) or len(token) < 16 or token.startswith("CHANGE-ME"):
        server["token"] = secrets.token_hex(16)
    server.setdefault("port", 47653)
    paths.config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths.extension_config.parent.mkdir(exist_ok=True)
    paths.extension_config.write_text(_extension_config(server["port"], server["token"]), encoding="utf-8")
    out(
        "Wrote extension/config.js. In Chrome: chrome://extensions, Developer mode, Load unpacked, "
        "choose the extension folder."
    )
    return 0


def cmd_check(paths: Paths, out: Callable[[str], None], which: Callable[[str], str | None] = shutil.which) -> int:
    cfg, error = load_config_safe(paths.config, paths.config_last_good)
    if cfg is None or error:
        out(f"Config problem: {error}")
        return 1
    missing = unresolved_launches(cfg, which)
    if missing:
        for process, command in missing:
            out(
                f"Config problem: the launch command {command!r} for {process} cannot be found. "
                "Use the full path to the program."
            )
        return 1
    media = cfg.video_path or f"{cfg.video_fallback_url} (fallback: the video file was not found)"
    out(f"Config OK: {len(cfg.allowed_apps)} apps, {len(cfg.allowed_sites)} sites, video: {media}")
    lists = cfg.youtube
    if not lists.is_empty():
        channels = len(lists.handles) + len(lists.channel_ids) + len(lists.names)
        out(f"YouTube: {channels} channels, {len(lists.playlists)} playlists, {len(lists.videos)} videos")
    out("Allowed apps: " + ", ".join(app.process for app in cfg.allowed_apps))
    out(hint_text(cfg))
    return 0


def cmd_windows(lister: Callable[[], Iterable[WinInfo]], out: Callable[[str], None]) -> int:
    for window in sorted(lister(), key=lambda item: (item.process.lower(), item.title)):
        out(f"{window.process} | {window.title}")
    return 0


def cmd_start(
    paths: Paths,
    minutes: int,
    live: bool,
    spawn: Callable[[str], None],
    now: float,
    out: Callable[[str], None],
    guard_alive: Callable[[], bool] = lambda: False,
) -> int:
    cfg, error = load_config_safe(paths.config, paths.config_last_good)
    if cfg is None:
        out(f"Config problem: {error}")
        return 1
    if error:
        out(f"Config problem in config.json: {error}. Using the last settings that loaded.")
    if load_session(paths.session, now) is not None:
        if guard_alive():
            out("A session is already running.")
            return 1
        spawn("focus_guard.run_guard")
        spawn("focus_guard.run_guardian")
        out("A session was active but its guard was not running: resumed enforcement.")
        return 0
    if not 1 <= minutes <= MAX_MINUTES:
        out(f"minutes must be from 1 to {MAX_MINUTES}")
        return 1
    try:
        begin_session(paths, Session(float(now), float(now) + minutes * 60.0, live), spawn)
    except UpdateInProgress as error:
        out(str(error))
        return 1
    if live:
        allowed = ", ".join(app.process for app in cfg.allowed_apps)
        out(
            f"LIVE session started for {minutes} min. Programs not on the allow-list wait minimized until it ends. "
            f"Allowed: {allowed}"
        )
    else:
        out(
            f"Dry-run session started for {minutes} min: nothing is closed; see state/attempts.log. "
            "Add --live to enforce."
        )
    return 0


def cmd_status(paths: Paths, now: float, out: Callable[[str], None]) -> int:
    session = load_session(paths.session, now)
    if session is None:
        out("No active session.")
        return 0
    mode = "LIVE" if session.live else "Dry-run"
    out(f"{mode} session: {int(session.remaining(now) // 60)} min remaining.")
    return 0


def _default_lister() -> Iterable[WinInfo]:
    from .windows import Win32Windows

    adapter = Win32Windows()
    return adapter.list_windows(adapter.own_pids())


def cmd_shortcut(
    paths: Paths,
    out: Callable[[str], None],
    icon_maker: Callable[[Path, Path], None],
    shortcut_maker: Callable[..., str],
) -> int:
    if not paths.icon_source.exists():
        out(f"Put your picture (a PNG) at {paths.icon_source} and run this again.")
        return 1
    icon_maker(paths.icon_source, paths.icon)
    target = str(Path(sys.executable).with_name("pythonw.exe"))
    link = shortcut_maker(
        name="Workmode",
        target=target,
        arguments="-m focus_guard.app",
        workdir=str(paths.root),
        icon=str(paths.icon),
        directory=str(paths.root),
    )
    out(f"Shortcut created: {link}")
    return 0


def _default_icon_maker() -> Callable[[Path, Path], None]:
    from .icon import make_icon

    return make_icon


def _default_shortcut_maker() -> Callable[..., str]:
    from .shortcut import create_shortcut

    return create_shortcut


def main(
    argv: list[str] | None = None,
    paths: Paths = DEFAULT,
    spawn: Callable[[str], None] | None = None,
    now: Callable[[], float] = time.time,
    lister: Callable[[], Iterable[WinInfo]] | None = None,
    out: Callable[[str], None] = print,
    icon_maker: Callable[[Path, Path], None] | None = None,
    shortcut_maker: Callable[..., str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    guard_alive: Callable[[], bool] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="focus_guard")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "check", "windows", "status", "shortcut"):
        commands.add_parser(name)
    start = commands.add_parser("start")
    start.add_argument("minutes", type=int)
    start.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    spawn = spawn or (lambda module: spawn_module(module, paths.root))

    if args.command == "init":
        return cmd_init(paths, out)
    if args.command == "check":
        return cmd_check(paths, out, which)
    if args.command == "windows":
        return cmd_windows(lister or _default_lister, out)
    if args.command == "status":
        return cmd_status(paths, now(), out)
    if args.command == "shortcut":
        return cmd_shortcut(
            paths, out, icon_maker or _default_icon_maker(), shortcut_maker or _default_shortcut_maker()
        )
    alive = guard_alive or (lambda: pid_alive(paths.guard_pid, "focus_guard.run_guard"))
    return cmd_start(paths, args.minutes, args.live, spawn, now(), out, alive)
