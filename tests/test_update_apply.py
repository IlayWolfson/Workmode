import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from focus_guard import update_apply
from focus_guard.jsonfile import read_json, write_json
from focus_guard.paths import Paths
from focus_guard.update_apply import apply, is_applying, prepare, ready_matches, recover
from tests.update_fixtures import release_for, trusted

OLD = {
    "focus_guard/app.py": b"print('old app')\n",
    "focus_guard/version.py": b'VERSION = "1.2.2"\n',
    "focus_guard/old.py": b"old only\n",
    "requirements.txt": b"psutil>=5.9\n",
}
NEW = {
    "focus_guard/app.py": b"print('new app')\n",
    "focus_guard/version.py": b'VERSION = "1.3.0"\n',
    "focus_guard/new.py": b"new only\n",
    "requirements.txt": b"psutil>=5.9\n",
}
USER = {
    "config.json": b'{"mine": true}',
    "extension/config.js": b"export const FOCUS = {};",
    "state/outcomes.json": b"{}",
    "focus_guard/user_extra.py": b"left alone\n",
}


class Crash(BaseException):
    """Stands for a power cut: nothing in the updater may catch it."""


class FakeMachine:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.free = 10**12
        self.pip_ok = True
        self.stop_ok = True
        self.ready = True
        self.ready_attempt: str | None = None  # None: answer with the attempt the updater passed
        self.calls: list = []
        self.ready_file_at_start: list[bool] = []
        self.crash_on: str | None = None

    def _maybe_crash(self, name):
        if self.crash_on == name:
            raise Crash(name)

    def stop_app(self, timeout):
        self.calls.append("stop")
        self._maybe_crash("stop")
        return self.stop_ok

    def start_app(self, attempt):
        self.calls.append(("start", attempt))
        self.ready_file_at_start.append(self.paths.app_ready.exists())
        self._maybe_crash("start")
        if self.ready and attempt:
            given = attempt if self.ready_attempt is None else self.ready_attempt
            write_json(self.paths.app_ready, {"version": "1.3.0", "pid": 4242, "attempt": given})

    def wait_ready(self, version, attempt, timeout):
        self.calls.append("wait")
        return ready_matches(self.paths, version, attempt, alive=lambda pid: True)

    def stop_new_app(self):
        self.calls.append("stop_new")

    def free_bytes(self, path):
        return self.free

    def pip_install(self, requirements):
        self.calls.append(("pip", Path(requirements)))
        return self.pip_ok


class ApplyCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.paths = Paths(self.root)
        self.write_tree(self.root, {**OLD, **USER})
        self.staging = self.paths.update_dir / "1.3.0" / "staging"
        self.machine = FakeMachine(self.paths)
        patcher = mock.patch.object(update_apply, "REPLACE_PAUSE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def write_tree(root: Path, files: dict[str, bytes]) -> None:
        for name, data in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(data)

    def run_apply(self, files=NEW):
        self.write_tree(self.staging, files)
        release = trusted(release_for("1.3.0", files))
        return apply(self.paths, release, self.staging, self.machine, "1.2.2")

    def tree(self, names) -> dict[str, bytes | None]:
        return {name: (self.root / name).read_bytes() if (self.root / name).exists() else None for name in names}

    def assert_old_install(self):
        self.assertEqual(self.tree(OLD), OLD)
        self.assertEqual(self.tree(USER), USER)
        self.assertFalse((self.root / "focus_guard/new.py").exists())

    def journal(self):
        return read_json(self.paths.update_journal)

    def result(self):
        return read_json(self.paths.update_result)


class ApplyTest(ApplyCase):
    def test_success_replaces_files_writes_installed_json_and_done(self):
        message = self.run_apply()
        self.assertEqual(message, "עודכן לגרסה 1.3.0")
        self.assertEqual(
            self.tree(["focus_guard/app.py", "focus_guard/version.py", "focus_guard/new.py"]),
            {name: NEW[name] for name in ("focus_guard/app.py", "focus_guard/version.py", "focus_guard/new.py")},
        )
        installed = read_json(self.paths.installed)
        self.assertEqual(installed["version"], "1.3.0")
        self.assertEqual(sorted(installed["files"]), sorted(NEW))
        self.assertEqual(self.journal()["phase"], "done")
        self.assertEqual(self.result(), {"ok": True, "message": message, "version": "1.3.0"})
        self.assertEqual([c if isinstance(c, str) else c[0] for c in self.machine.calls], ["stop", "start", "wait"])
        self.assertFalse(self.staging.exists())
        self.assertEqual(
            (self.paths.update_dir / "backup-1.2.2" / "focus_guard/app.py").read_bytes(), OLD["focus_guard/app.py"]
        )
        self.assertFalse(is_applying(self.paths))

    def test_protected_files_never_touched(self):
        self.run_apply()
        self.assertEqual(self.tree(USER), USER)

    def test_release_listing_a_protected_file_changes_nothing(self):
        message = self.run_apply({**NEW, "config.json": b"{}"})
        self.assertNotIn("עודכן", message)
        self.assert_old_install()
        self.assertEqual(self.machine.calls, [])

    def test_staged_file_changed_after_verification_changes_nothing(self):
        self.write_tree(self.staging, NEW)
        release = trusted(release_for("1.3.0", NEW))
        (self.staging / "focus_guard/app.py").write_bytes(b"print('swapped in later')\n")
        message = apply(self.paths, release, self.staging, self.machine, "1.2.2")
        self.assertIn("לא תקינים", message)
        self.assert_old_install()
        self.assertEqual(self.machine.calls, [])

    def test_first_update_without_installed_json_only_adds_and_replaces(self):
        self.run_apply()
        self.assertEqual((self.root / "focus_guard/old.py").read_bytes(), OLD["focus_guard/old.py"])

    def test_removed_files_deleted_only_when_listed_in_installed_json(self):
        write_json(self.paths.installed, {"version": "1.2.2", "files": sorted(OLD)})
        self.run_apply()
        self.assertFalse((self.root / "focus_guard/old.py").exists())
        self.assertEqual((self.root / "focus_guard/user_extra.py").read_bytes(), USER["focus_guard/user_extra.py"])

    def test_a_rename_that_only_changes_case_keeps_the_file(self):
        write_json(self.paths.installed, {"version": "1.2.2", "files": sorted(OLD)})
        renamed = {**NEW, "focus_guard/OLD.py": b"renamed\n"}
        del renamed["focus_guard/new.py"]
        self.run_apply(renamed)
        self.assertEqual((self.root / "focus_guard/OLD.py").read_bytes(), b"renamed\n")

    def test_installed_json_never_removes_protected_files(self):
        write_json(self.paths.installed, {"version": "1.2.2", "files": [*OLD, "config.json", "state/outcomes.json"]})
        self.run_apply()
        self.assertEqual(self.tree(USER), USER)

    def test_not_enough_space_changes_nothing(self):
        self.machine.free = 10
        message = self.run_apply()
        self.assertIn("מקום", message)
        self.assert_old_install()
        self.assertEqual(self.machine.calls, [])

    def run_prepare(self, files):
        self.write_tree(self.staging, files)
        return prepare(self.paths, trusted(release_for("1.3.0", files)), self.staging, self.machine)

    def test_pip_failure_changes_nothing(self):
        self.machine.pip_ok = False
        message = self.run_prepare({**NEW, "requirements.txt": b"psutil>=6\n"})
        self.assertIn("הספריות", message)
        self.assert_old_install()
        self.assertEqual(self.machine.calls, [("pip", self.staging / "requirements.txt")])

    def test_new_requirements_are_installed_by_prepare(self):
        self.assertIsNone(self.run_prepare({**NEW, "requirements.txt": b"psutil>=6\n"}))
        self.assertEqual(self.machine.calls, [("pip", self.staging / "requirements.txt")])

    def test_same_requirements_skip_pip(self):
        self.assertIsNone(self.run_prepare(NEW))
        self.assertEqual(self.machine.calls, [])

    def test_apply_itself_never_runs_pip(self):
        self.run_apply({**NEW, "requirements.txt": b"psutil>=6\n"})
        self.assertNotIn("pip", [c[0] for c in self.machine.calls if isinstance(c, tuple)])

    def test_failed_backup_changes_nothing_and_does_not_block_sessions(self):
        with mock.patch.object(update_apply.shutil, "copy2", side_effect=PermissionError("locked")):
            message = self.run_apply()
        self.assertIn("לא שונה כלום", message)
        self.assertNotIn("לא הושלמה", message)
        self.assert_old_install()
        self.assertEqual(self.journal()["phase"], "rolled_back")
        self.assertFalse(is_applying(self.paths))
        self.assertEqual(self.machine.calls[-1], ("start", ""))

    def test_app_that_does_not_stop_changes_nothing(self):
        self.machine.stop_ok = False
        message = self.run_apply()
        self.assertIn("לסגור", message)
        self.assert_old_install()
        self.assertEqual(self.journal()["phase"], "rolled_back")

    def test_app_not_ready_rolls_back(self):
        self.machine.ready = False
        message = self.run_apply()
        self.assertIn("חזרנו לגרסה 1.2.2", message)
        self.assert_old_install()
        self.assertEqual(self.journal()["phase"], "rolled_back")
        self.assertEqual(self.machine.calls[-2:], ["stop_new", ("start", "")])
        self.assertFalse(self.result()["ok"])

    def test_stale_app_ready_does_not_count(self):
        write_json(self.paths.app_ready, {"version": "1.3.0", "pid": 1, "attempt": "old"})
        self.machine.ready = False
        self.run_apply()
        self.assertEqual(self.machine.ready_file_at_start[0], False)
        self.assert_old_install()

    def test_ready_with_wrong_attempt_rolls_back(self):
        self.machine.ready_attempt = "someone-else"
        self.assertIn("חזרנו", self.run_apply())
        self.assert_old_install()

    def test_locked_file_rolls_back(self):
        real = os.replace

        def locked(src, dst):
            if str(dst).endswith("version.py"):
                raise PermissionError("in use")
            return real(src, dst)

        with mock.patch.object(update_apply.os, "replace", side_effect=locked):
            message = self.run_apply()
        self.assertIn("חזרנו", message)
        self.assert_old_install()
        self.assertEqual(list(self.root.rglob("*.new")), [])


class ReadyMatchesTest(ApplyCase):
    def test_needs_version_attempt_and_a_live_pid(self):
        write_json(self.paths.app_ready, {"version": "1.3.0", "pid": 7, "attempt": "a1"})
        self.assertTrue(ready_matches(self.paths, "1.3.0", "a1", alive=lambda pid: pid == 7))
        self.assertFalse(ready_matches(self.paths, "1.3.0", "a2", alive=lambda pid: True))
        self.assertFalse(ready_matches(self.paths, "1.3.1", "a1", alive=lambda pid: True))
        self.assertFalse(ready_matches(self.paths, "1.3.0", "a1", alive=lambda pid: False))
        self.paths.app_ready.write_text("[", encoding="utf-8")
        self.assertFalse(ready_matches(self.paths, "1.3.0", "a1", alive=lambda pid: True))


class RecoverTest(ApplyCase):
    def crash(self, where):
        self.machine.crash_on = where
        with self.assertRaises(Crash):
            self.run_apply()
        self.machine.crash_on = None

    def test_no_journal_or_finished_journal_is_left_alone(self):
        self.assertIsNone(recover(self.paths, self.machine, restart_app=True))
        write_json(self.paths.update_journal, {"phase": "done"})
        self.assertIsNone(recover(self.paths, self.machine, restart_app=True))

    def test_crash_before_backup_only_deletes_staging(self):
        self.crash("stop")
        self.assertEqual(self.journal()["phase"], "started")
        self.assertTrue(is_applying(self.paths))
        recover(self.paths, self.machine, restart_app=True)
        self.assert_old_install()
        self.assertFalse(self.staging.exists())
        self.assertEqual(self.journal()["phase"], "rolled_back")

    def test_crash_after_swap_restores_old_files(self):
        self.crash("start")
        self.assertEqual(self.journal()["phase"], "swapped")
        message = recover(self.paths, self.machine, restart_app=True)
        self.assertIn("1.2.2", message)
        self.assert_old_install()
        self.assertEqual(self.journal()["phase"], "rolled_back")
        self.assertEqual(self.machine.calls[-2:], ["stop", ("start", "")])

    def test_a_rollback_that_cannot_finish_leaves_the_running_app_alone(self):
        self.crash("start")
        (self.paths.update_dir / "backup-1.2.2" / "focus_guard/app.py").unlink()  # e.g. removed by an antivirus
        calls = len(self.machine.calls)
        message = recover(self.paths, self.machine, restart_app=True)
        self.assertIn("לא הושלמה", message)
        self.assertEqual(self.machine.calls[calls:], [])
        self.assertTrue(is_applying(self.paths))  # Update.cmd can try again

    def test_crash_in_the_middle_of_the_swap_restores_old_files(self):
        real = os.replace
        count = {"n": 0}

        def crash_on_second(src, dst):
            if str(dst).startswith(str(self.root / "focus_guard")) and not str(dst).endswith(".json"):
                count["n"] += 1
                if count["n"] == 2:
                    raise Crash("power cut")
            return real(src, dst)

        with mock.patch.object(update_apply.os, "replace", side_effect=crash_on_second), self.assertRaises(Crash):
            self.run_apply()
        self.assertEqual(self.journal()["phase"], "backup_done")
        recover(self.paths, self.machine, restart_app=False)
        self.assert_old_install()
        self.assertNotIn("start", [c[0] for c in self.machine.calls[-1:] if isinstance(c, tuple)])

    def test_recovery_without_restart_does_not_touch_the_app(self):
        self.crash("start")
        calls = len(self.machine.calls)
        recover(self.paths, self.machine, restart_app=False)
        self.assertEqual(len(self.machine.calls), calls)
        self.assert_old_install()

    def test_journal_versions_that_are_not_versions_are_ignored(self):
        outside = self.root / "keep" / "me.txt"
        outside.parent.mkdir()
        outside.write_bytes(b"x")
        for field in ("to", "from"):
            journal = {"phase": "started", "from": "1.2.2", "to": "1.3.0", "attempt": "a", field: "../../keep"}
            write_json(self.paths.update_journal, {**journal, "replaced": [], "added": [], "removed": []})
            with self.subTest(field=field):
                self.assertIsNone(recover(self.paths, self.machine, restart_app=False))
                self.assertTrue(outside.exists())

    def test_a_journal_recover_ignores_does_not_block_sessions_either(self):
        write_json(self.paths.update_journal, {"phase": "swapped", "from": "x", "to": "1.3.0"})
        self.assertFalse(is_applying(self.paths))

    def test_broken_journal_is_ignored(self):
        self.paths.update_journal.parent.mkdir(parents=True, exist_ok=True)
        self.paths.update_journal.write_text(json.dumps({"phase": 5}), encoding="utf-8")
        self.assertIsNone(recover(self.paths, self.machine, restart_app=True))
        self.assert_old_install()


if __name__ == "__main__":
    unittest.main()
