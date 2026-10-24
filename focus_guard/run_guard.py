"""Entry point of the guard process: python -m focus_guard.run_guard (started by `start`)."""

import os
import sys
import time

from .attempts import AttemptLog
from .audio import Win32Audio
from .config import hint_text, load_config_safe
from .guard import Guard
from .launcher import spawn_module
from .leftovers import undo_all
from .muting import MuteStore
from .ownpids import app_tree
from .paths import DEFAULT as PATHS
from .procfiles import pid_alive, read_pid, remove_pid, write_pid
from .roasts import GeminiFetcher, RoastStock
from .server import make_server, serve_in_thread
from .session import clear_session_if, load_session
from .supervisor import Supervisor
from .uilauncher import SubprocessUi
from .waiting import WaitingStore
from .windows import Win32Actions, Win32Windows, process_children, process_name
from .winkeys import Win32Keys

GUARD, GUARDIAN, APP = "focus_guard.run_guard", "focus_guard.run_guardian", "focus_guard.app"
BUTTON = "כן, לצאת"
PROMPT = "הקלידו את משפט החירום:"


def app_pids() -> set[int]:
    """The background app and its windows (clock, notifications, errors): a session never touches them."""
    pid = read_pid(PATHS.app_pid)
    return app_tree(pid, pid is not None and pid_alive(PATHS.app_pid, APP), process_children, process_name)


def main() -> int:
    cfg, _ = load_config_safe(PATHS.config, PATHS.config_last_good)
    if cfg is None:
        return 1
    session = load_session(PATHS.session, time.time())
    if session is None:
        undo_all(PATHS)
        return 0
    existing = read_pid(PATHS.guard_pid)
    if existing not in (None, os.getpid()) and pid_alive(PATHS.guard_pid, GUARD):
        return 0
    write_pid(PATHS.guard_pid)

    log = AttemptLog(PATHS.attempts)
    roasts = RoastStock(
        GeminiFetcher(cfg.roast_model, cfg.roast_instruction, cfg.roast_language, cfg.roast_max_words),
        cfg.roast_stock,
        cfg.roast_refill_at,
    )
    roasts.prime()
    PATHS.exit_request.unlink(missing_ok=True)  # a press meant for an earlier session must not end this one
    guard = Guard(
        cfg,
        session,
        Win32Windows(app_pids),
        Win32Actions(),
        SubprocessUi(hint_text(cfg), BUTTON, PROMPT),
        Win32Keys(),
        log,
        roasts,
        waiting=WaitingStore(PATHS.waiting),
        audio=Win32Audio(),
        mutes=MuteStore(PATHS.mutes),
        mute_requested=PATHS.mute_request.exists,
        exit_requested=PATHS.exit_request.exists,
        clear_exit_request=lambda: PATHS.exit_request.unlink(missing_ok=True),
        dry_run=not session.live,
    )
    server = None
    try:
        sites = (lambda: cfg.allowed_sites) if session.live else (lambda: None)
        youtube = (lambda: cfg.youtube.as_json()) if session.live else (lambda: None)
        server = make_server(cfg.server_port, cfg.server_token, sites, guard.push_external, get_youtube=youtube)
        serve_in_thread(server)
    except OSError as error:
        log.record("error", f"bridge not started: {error}")
    peer = Supervisor(
        is_active=lambda: True,
        is_alive=lambda: pid_alive(PATHS.guardian_pid, GUARDIAN),
        start=lambda: spawn_module("focus_guard.run_guardian", PATHS.root),
    )
    try:
        guard.run(on_tick=peer.tick)
    finally:
        if server is not None:
            server.shutdown()
        if clear_session_if(PATHS.session, session):  # a follow-on session and its mute button are not ours
            PATHS.mute_request.unlink(missing_ok=True)
        remove_pid(PATHS.guard_pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
