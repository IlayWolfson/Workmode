"""Entry point of the guardian: restarts the guard while a session is active."""

import os
import sys
import time

from .launcher import spawn_module
from .paths import DEFAULT as PATHS
from .procfiles import pid_alive, read_pid, remove_pid, write_pid
from .session import load_session
from .supervisor import Supervisor

GUARD, GUARDIAN = "focus_guard.run_guard", "focus_guard.run_guardian"
GRACE_SECONDS = 5.0  # let a freshly started guard write its pid file first
IDLE_CHECKS = 3  # consecutive checks without a session before exiting


def main() -> int:
    existing = read_pid(PATHS.guardian_pid)
    if existing not in (None, os.getpid()) and pid_alive(PATHS.guardian_pid, GUARDIAN):
        return 0
    write_pid(PATHS.guardian_pid)
    time.sleep(GRACE_SECONDS)
    peer = Supervisor(
        is_active=lambda: load_session(PATHS.session, time.time()) is not None,
        is_alive=lambda: pid_alive(PATHS.guard_pid, GUARD),
        start=lambda: spawn_module("focus_guard.run_guard", PATHS.root),
        interval=1.0,
    )
    idle = 0
    try:
        while idle < IDLE_CHECKS:
            if load_session(PATHS.session, time.time()) is None:
                idle += 1
            else:
                idle = 0
                peer.tick()
            time.sleep(1.0)
    finally:
        remove_pid(PATHS.guardian_pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
