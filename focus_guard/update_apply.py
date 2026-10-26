"""Install a staged release: journal, backup, swap, start the new app and check it, or roll back.

Every phase is written to state/update-journal.json before it starts. A journal that is not `done` or `rolled_back`
means the updater was interrupted; `recover` then puts the old files back. Protected paths (the user's settings,
history and notes) are never read from the release, backed up, replaced or removed.
"""

import ctypes
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .jsonfile import read_json, write_json
from .paths import Paths
from .update_archive import ArchiveError, check_path
from .update_trust import Release, sha256_file
from .version import parse_version

UPDATE_MUTEX = "Local\\FocusGuard.Update"  # held by the updater, and briefly by every session start
UPDATER_MUTEX = "Local\\FocusGuard.Updater"  # held for a whole updater run: one at a time
QUIT_EVENT = "Local\\FocusGuard.Quit"  # the app quits when it is set
PHASES = ("started", "backup_done", "swapped", "done", "rolled_back")
UNFINISHED = ("started", "backup_done", "swapped")
SPACE_FACTOR = 3
STOP_SECONDS = 15.0
READY_SECONDS = 60.0
REPLACE_ATTEMPTS = 3
REPLACE_PAUSE = 0.2

SUCCESS = "עודכן לגרסה {}"
ROLLED_BACK = "העדכון לא הצליח וחזרנו לגרסה {} (שלב: {})"
ROLLBACK_INCOMPLETE = "העדכון לא הצליח והחזרה לגרסה {} לא הושלמה ({}). הריצו את Update.cmd שוב."
NO_SPACE = "אין מספיק מקום בדיסק לעדכון; לא שונה כלום"
PIP_FAILED = "התקנת הספריות של הגרסה החדשה נכשלה; לא שונה כלום"
APP_STUCK = "לא הצלחתי לסגור את Workmode; לא שונה כלום"
BAD_FILES = "קבצי העדכון לא תקינים; לא שונה כלום"
INTERRUPTED = "עדכון שנקטע בוטל; לא שונה כלום"
BACKUP_FAILED = "לא הצלחתי לגבות את הקבצים לפני העדכון; לא שונה כלום"
STEP_SWAP = "החלפת הקבצים"
STEP_START = "הפעלת הגרסה החדשה"
STEP_RESUME = "המשך אחרי הפסקה"


class Machine(Protocol):
    """The processes and the disk around an update. WindowsMachine is the real one; tests use a fake."""

    def stop_app(self, timeout: float) -> bool: ...

    def start_app(self, attempt: str) -> None: ...  # attempt "" starts the app without an update to confirm

    def wait_ready(self, version: str, attempt: str, timeout: float) -> bool: ...

    def stop_new_app(self) -> None: ...

    def free_bytes(self, path: Path) -> int: ...

    def pip_install(self, requirements: Path) -> bool: ...


def is_applying(paths: Paths) -> bool:
    """An unfinished journal that recover would act on. One it ignores must not block sessions forever either."""
    journal = _read_journal(paths)
    return journal is not None and journal["phase"] in UNFINISHED


def ready_matches(paths: Paths, version: str, attempt: str, alive: Callable[[int], bool]) -> bool:
    """True when app-ready.json was written by a live app of `version` started for this `attempt`."""
    data = read_json(paths.app_ready)
    if not isinstance(data, dict) or not attempt:
        return False
    pid = data.get("pid")
    return (
        data.get("version") == version
        and data.get("attempt") == attempt
        and isinstance(pid, int)
        and not isinstance(pid, bool)
        and alive(pid)
    )


def apply(paths: Paths, release: Release, staging: Path, machine: Machine, installed: str) -> str:
    """Install `release` from `staging` (prepare ran and the gate was passed). Returns the Hebrew result message."""
    problem = _precheck(paths, release, staging, machine)
    if problem is not None:
        return _report(paths, False, problem, installed)
    journal = _new_journal(paths, release, installed)
    _write(paths, journal, "started")
    if not machine.stop_app(STOP_SECONDS):
        _write(paths, journal, "rolled_back")
        return _report(paths, False, APP_STUCK, installed)
    step = STEP_SWAP
    try:
        _backup(paths, journal)
        _write(paths, journal, "backup_done")
        _swap(paths, release, staging, journal)
        _write(paths, journal, "swapped")
        step = STEP_START
        paths.app_ready.unlink(missing_ok=True)  # an old marker must never pass for the new app
        machine.start_app(journal["attempt"])
        if not machine.wait_ready(release.version, journal["attempt"], READY_SECONDS):
            raise RuntimeError("the new version did not start")
    except Exception:
        if journal["phase"] == "started":  # the backup failed: no installed file was touched yet
            _write(paths, journal, "rolled_back")
            machine.start_app("")
            return _report(paths, False, BACKUP_FAILED, installed)
        machine.stop_new_app()
        message = _roll_back(paths, journal, step)
        machine.start_app("")
        return _report(paths, False, message, installed)
    _finish(paths, release, staging, journal)
    return _report(paths, True, SUCCESS.format(release.version), release.version)


def recover(paths: Paths, machine: Machine, restart_app: bool) -> str | None:
    """Undo an interrupted update. None when there is nothing to undo. Restarts the old app when asked."""
    journal = _read_journal(paths)
    if journal is None or journal["phase"] not in UNFINISHED:
        return None
    if journal["phase"] == "started":
        shutil.rmtree(paths.update_dir / journal["to"], ignore_errors=True)
        _write(paths, journal, "rolled_back")
        if restart_app:
            machine.start_app("")
        return _report(paths, False, INTERRUPTED, journal["from"])
    folder = _backup_dir(paths, journal)
    missing = [name for name in [*journal["replaced"], *journal["removed"]] if not (folder / name).is_file()]
    if missing:  # this undo cannot finish: leave the files and the running app as they are, say what is missing
        return _report(paths, False, ROLLBACK_INCOMPLETE.format(journal["from"], ", ".join(missing)), journal["from"])
    if restart_app:
        machine.stop_app(STOP_SECONDS)
    message = _roll_back(paths, journal, STEP_RESUME)
    if restart_app:
        machine.start_app("")
    return _report(paths, False, message, journal["from"])


def _precheck(paths: Paths, release: Release, staging: Path, machine: Machine) -> str | None:
    try:
        for entry in release.files:
            check_path(entry.path)
            staged = staging / entry.path
            if not staged.is_file() or sha256_file(staged) != entry.sha256:
                return BAD_FILES
    except (ArchiveError, OSError):
        return BAD_FILES
    if machine.free_bytes(paths.root) < SPACE_FACTOR * sum(entry.size for entry in release.files):
        return NO_SPACE
    return None


def prepare(paths: Paths, release: Release, staging: Path, machine: Machine) -> str | None:
    """Install the new version's packages, before the update lock and the last gate: pip can take minutes and
    must not hold up a session start. None when ready; else the Hebrew reason (nothing changed)."""
    problem = _precheck(paths, release, staging, machine)
    if problem is not None:
        return problem
    current = paths.root / "requirements.txt"
    current_hash = sha256_file(current) if current.exists() else ""
    staged_requirements = staging / "requirements.txt"
    if current_hash != release.requirements_sha256 and staged_requirements.exists():
        if not machine.pip_install(staged_requirements):
            return PIP_FAILED
    return None


def _new_journal(paths: Paths, release: Release, installed: str) -> dict[str, Any]:
    new = [entry.path for entry in release.files]
    replaced = [name for name in new if (paths.root / name).exists()]
    added = [name for name in new if not (paths.root / name).exists()]
    listed = read_json(paths.installed)
    old = listed.get("files") if isinstance(listed, dict) else None
    removed: list[str] = []
    kept = {name.lower() for name in new}  # Windows file names ignore case: README.md renamed Readme.md is kept
    for name in old if isinstance(old, list) else []:
        if isinstance(name, str) and name.lower() not in kept and _safe(name) and (paths.root / name).is_file():
            removed.append(name)
    return {
        "from": installed,
        "to": release.version,
        "attempt": secrets.token_hex(8),
        "replaced": replaced,
        "added": added,
        "removed": removed,
    }


def _is_version(value: Any) -> bool:
    try:
        parse_version(value)
    except (TypeError, ValueError):
        return False
    return True


def _safe(name: str) -> bool:
    try:
        check_path(name)
    except ArchiveError:
        return False
    return True


def _backup_dir(paths: Paths, journal: dict[str, Any]) -> Path:
    return paths.update_dir / f"backup-{journal['from']}"


def _backup(paths: Paths, journal: dict[str, Any]) -> None:
    folder = _backup_dir(paths, journal)
    shutil.rmtree(folder, ignore_errors=True)
    for name in [*journal["replaced"], *journal["removed"]]:
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.root / name, target)


def _swap(paths: Paths, release: Release, staging: Path, journal: dict[str, Any]) -> None:
    for entry in release.files:
        _put(staging / entry.path, paths.root / entry.path)
    for name in journal["removed"]:
        (paths.root / name).unlink(missing_ok=True)


def _put(source: Path, target: Path) -> None:
    """Copy next to the target, then replace it in one step, so a file is always either old or new."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    shutil.copyfile(source, temporary)
    try:
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, target)
                return
            except PermissionError:  # antivirus or a preview can hold a file for a moment
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_PAUSE)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _roll_back(paths: Paths, journal: dict[str, Any], step: str) -> str:
    """Put every backed-up file back and delete the added ones. Never raises; says what could not be undone."""
    folder = _backup_dir(paths, journal)
    failed: list[str] = []
    for name in [*journal["replaced"], *journal["removed"]]:
        saved, target = folder / name, paths.root / name
        try:
            if not target.exists() or sha256_file(target) != sha256_file(saved):
                _put(saved, target)
        except OSError:
            failed.append(name)
    for name in journal["added"]:
        try:
            (paths.root / name).unlink(missing_ok=True)
            (paths.root / (name + ".new")).unlink(missing_ok=True)
        except OSError:
            failed.append(name)
    if failed:
        return ROLLBACK_INCOMPLETE.format(journal["from"], ", ".join(failed))
    _write(paths, journal, "rolled_back")
    return ROLLED_BACK.format(journal["from"], step)


def _finish(paths: Paths, release: Release, staging: Path, journal: dict[str, Any]) -> None:
    write_json(paths.installed, {"version": release.version, "files": [entry.path for entry in release.files]})
    _write(paths, journal, "done")
    shutil.rmtree(staging.parent if staging.parent.parent == paths.update_dir else staging, ignore_errors=True)
    keep = _backup_dir(paths, journal).name
    for old in paths.update_dir.glob("backup-*"):
        if old.name != keep:
            shutil.rmtree(old, ignore_errors=True)


def _write(paths: Paths, journal: dict[str, Any], phase: str) -> None:
    journal["phase"] = phase
    write_json(paths.update_journal, journal)


def _read_journal(paths: Paths) -> dict[str, Any] | None:
    data = read_json(paths.update_journal)
    if not isinstance(data, dict) or data.get("phase") not in PHASES:
        return None
    if not all(_is_version(data.get(key)) for key in ("from", "to")):  # they name folders under state/update
        return None
    lists = [data.get(key) for key in ("replaced", "added", "removed")]
    if not all(isinstance(items, list) and all(isinstance(n, str) and _safe(n) for n in items) for items in lists):
        return None
    return data


def _report(paths: Paths, ok: bool, message: str, version: str) -> str:
    write_json(paths.update_result, {"ok": ok, "message": message, "version": version})
    return message


class WindowsMachine:
    """The real processes: the app is asked to quit through a named event, then ended only if it is ours."""

    def __init__(self, paths: Paths, quit_event: str, python: str = sys.executable) -> None:
        self._paths, self._quit_event = paths, quit_event
        folder = Path(python).parent
        self._python = str(folder / "python.exe") if (folder / "python.exe").exists() else python
        self._pythonw = str(folder / "pythonw.exe") if (folder / "pythonw.exe").exists() else python

    def _app_alive(self) -> bool:
        from .procfiles import pid_alive

        return pid_alive(self._paths.app_pid, "focus_guard.app")

    def stop_app(self, timeout: float) -> bool:
        if not self._app_alive():
            return True
        _set_event(self._quit_event)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._app_alive():
                return True
            time.sleep(0.25)
        return self._kill_app()

    def _kill_app(self) -> bool:
        import psutil

        from .procfiles import read_pid

        pid = read_pid(self._paths.app_pid)
        if pid is not None and self._app_alive():  # the pid file's process is ours (its command line says so)
            try:
                psutil.Process(pid).kill()
                psutil.Process(pid).wait(5)
            except psutil.Error:
                pass
        return not self._app_alive()

    def start_app(self, attempt: str) -> None:
        if self._app_alive():
            return
        env = {**os.environ, "WORKMODE_UPDATE_ATTEMPT": attempt}
        subprocess.Popen(
            [self._pythonw, "-m", "focus_guard.app", "--background"],
            cwd=str(self._paths.root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x00000008 | 0x08000000,  # DETACHED_PROCESS | CREATE_NO_WINDOW
            close_fds=True,
        )

    def wait_ready(self, version: str, attempt: str, timeout: float) -> bool:
        import psutil

        deadline = time.time() + timeout
        while time.time() < deadline:
            if ready_matches(self._paths, version, attempt, psutil.pid_exists) and self._app_alive():
                return True
            time.sleep(0.5)
        return False

    def stop_new_app(self) -> None:
        self.stop_app(STOP_SECONDS)

    def free_bytes(self, path: Path) -> int:
        return shutil.disk_usage(path).free

    def pip_install(self, requirements: Path) -> bool:
        command = [self._python, "-m", "pip", "install", "-r", str(requirements)]
        try:
            # without a console (started from the popup) pip gets none either; from Update.cmd its output shows
            has_console = ctypes.windll.kernel32.GetConsoleWindow() != 0
            flags = 0 if has_console else 0x08000000  # CREATE_NO_WINDOW
            done = subprocess.run(command, cwd=str(self._paths.root), timeout=900, check=False, creationflags=flags)
            return done.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False


def _set_event(name: str) -> None:
    import pywintypes
    import win32api
    import win32event

    try:
        event = win32event.OpenEvent(win32event.EVENT_MODIFY_STATE, False, name)
    except pywintypes.error:
        return
    try:
        win32event.SetEvent(event)
    finally:
        win32api.CloseHandle(event)
