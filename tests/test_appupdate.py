import tempfile
import threading
import unittest
from pathlib import Path

from focus_guard.appupdate import (
    ATTEMPT_ENV,
    UpdateService,
    recover_at_start,
    run_checks,
    start_update_bridge,
    write_ready,
)
from focus_guard.jsonfile import read_json, write_json
from focus_guard.paths import Paths
from focus_guard.server import make_update_server
from focus_guard.session import Session, write_session
from focus_guard.update_apply import UPDATE_MUTEX
from focus_guard.version import VERSION
from tests.update_fixtures import UNFINISHED

NOW = 1_800_000_000.0
TOKEN = "0123456789abcdef"


class AppReadyTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = Paths(folder.name)

    def test_app_ready_written_with_version_and_pid(self):
        write_ready(self.paths, 321, {})
        self.assertEqual(read_json(self.paths.app_ready), {"version": VERSION, "pid": 321, "attempt": ""})

    def test_app_ready_includes_attempt_from_env(self):
        write_ready(self.paths, 321, {ATTEMPT_ENV: "a1b2"})
        self.assertEqual(read_json(self.paths.app_ready)["attempt"], "a1b2")


class UpdateServiceTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = Paths(folder.name)
        self.paths.state.mkdir()
        self.spawned = 0
        self.recoveries = 0
        self.now = NOW
        self.mutex_free = True
        self.guard = False
        self.service = UpdateService(
            self.paths,
            now=lambda: self.now,
            spawn_update=self.spawn,
            held=lambda name: not self.mutex_free,
            guard_alive=lambda: self.guard,
            upcoming=lambda now: [],
            spawn_recover=self.recover,
        )

    def spawn(self):
        self.spawned += 1

    def recover(self):
        self.recoveries += 1

    def make_ready(self, version="1.3.0"):
        folder = self.paths.update_dir / version
        (folder / "staging").mkdir(parents=True)
        (folder / "release.json").write_bytes(b"{}")
        (folder / "release.json.sig").write_bytes(b"x")
        write_json(self.paths.update_check, {"checked_at": NOW - 5, "available": version, "state": "ready"})

    def test_status_without_any_check(self):
        status = self.service.status()
        self.assertEqual((status["installed"], status["available"], status["state"]), (VERSION, None, "none"))
        self.assertIsNone(status["blocked"])

    def test_status_ready(self):
        self.make_ready()
        status = self.service.status()
        self.assertEqual((status["available"], status["state"], status["checked_at"]), ("1.3.0", "ready", NOW - 5))

    def test_ready_without_its_files_is_not_ready(self):
        write_json(self.paths.update_check, {"checked_at": NOW - 5, "available": "1.3.0", "state": "ready"})
        self.assertEqual(self.service.status()["state"], "none")

    def test_status_during_session_is_blocked_with_its_end(self):
        self.make_ready()
        write_session(self.paths.session, Session(NOW - 60, NOW + 3600, live=True))
        status = self.service.status()
        self.assertIn("סשן פעיל", status["blocked"])
        self.assertEqual(status["session_until"], NOW + 3600)

    def test_status_while_the_updater_runs_is_applying(self):
        self.make_ready()
        self.mutex_free = False
        self.assertEqual(self.service.status()["state"], "applying")
        self.mutex_free = True
        write_json(self.paths.update_journal, UNFINISHED)
        self.assertEqual(self.service.status()["state"], "applying")

    def test_status_carries_the_last_result(self):
        write_json(self.paths.update_result, {"ok": False, "message": "העדכון לא הצליח", "version": "1.2.2"})
        self.assertEqual(self.service.status()["result"], {"ok": False, "message": "העדכון לא הצליח"})

    def test_start_apply_spawns_the_update(self):
        self.make_ready()
        self.assertTrue(self.service.start_apply())
        self.assertEqual(self.spawned, 1)

    def test_start_apply_refused_when_blocked(self):
        self.make_ready()
        self.guard = True
        self.assertFalse(self.service.start_apply())
        self.assertEqual(self.spawned, 0)

    def test_a_stale_journal_starts_recovery_once_in_a_while(self):
        write_json(self.paths.update_journal, UNFINISHED)
        self.service.status()
        self.service.status()
        self.assertEqual(self.recoveries, 1)
        self.now = NOW + 301
        self.service.status()
        self.assertEqual(self.recoveries, 2)

    def make_service(self):
        return UpdateService(
            self.paths,
            now=lambda: self.now,
            spawn_update=self.spawn,
            held=lambda name: False,
            guard_alive=lambda: False,
            upcoming=lambda now: [],
            spawn_recover=self.recover,
        )

    def test_the_heal_timer_survives_an_app_restart(self):
        write_json(self.paths.update_journal, UNFINISHED)
        self.make_service().status()
        self.make_service().status()  # the recovery restarted the app: a new process, a new service
        self.assertEqual(self.recoveries, 1)

    def test_healing_gives_up_after_three_tries_for_the_same_update(self):
        write_json(self.paths.update_journal, UNFINISHED)
        for step in range(6):
            self.now = NOW + step * 301
            self.make_service().status()
        self.assertEqual(self.recoveries, 3)
        write_json(self.paths.update_journal, {**UNFINISHED, "attempt": "another"})
        self.make_service().status()
        self.assertEqual(self.recoveries, 4)

    def test_journal_of_a_running_updater_is_not_stale(self):
        write_json(self.paths.update_journal, UNFINISHED)
        self.mutex_free = False
        self.service.status()
        self.assertEqual(self.recoveries, 0)

    def test_finished_journal_needs_no_recovery(self):
        write_json(self.paths.update_journal, {"phase": "done"})
        self.service.status()
        self.assertEqual(self.recoveries, 0)

    def test_start_apply_refused_while_the_updater_runs(self):
        self.make_ready()
        self.mutex_free = False
        self.assertFalse(self.service.start_apply())
        self.assertEqual(self.spawned, 0)


class BridgeTest(unittest.TestCase):
    def test_busy_update_port_logs_and_skips_bridge(self):
        taken = make_update_server(0, TOKEN, dict, lambda: False)
        self.addCleanup(taken.server_close)
        port = taken.server_address[1]
        lines: list[str] = []
        service = UpdateService(Paths(tempfile.gettempdir()), spawn_update=lambda: None)
        self.assertIsNone(start_update_bridge(port, TOKEN, service, lines.append))
        self.assertEqual(len(lines), 1)
        self.assertIn(str(port), lines[0])

    def test_bridge_starts_on_a_free_port(self):
        service = UpdateService(Paths(tempfile.gettempdir()), spawn_update=lambda: None)
        server = start_update_bridge(0, TOKEN, service, lambda line: None)
        self.assertIsNotNone(server)
        server.shutdown()
        server.server_close()


class CheckLoopTest(unittest.TestCase):
    def test_errors_are_logged_and_the_loop_goes_on_until_stopped(self):
        stop = threading.Event()
        calls: list[int] = []
        lines: list[str] = []

        def check_once():
            calls.append(1)
            if len(calls) == 1:
                raise OSError("disk full")
            stop.set()

        run_checks(check_once, stop, lines.append, every=0)
        self.assertEqual(len(calls), 2)
        self.assertIn("disk full", lines[0])


class RecoverAtStartTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = Paths(folder.name)
        self.root = Path(folder.name)
        (self.root / "a.py").write_bytes(b"new")
        backup = self.paths.update_dir / "backup-1.2.2"
        backup.mkdir(parents=True)
        (backup / "a.py").write_bytes(b"old")
        journal = {"phase": "swapped", "from": "1.2.2", "to": "1.3.0", "attempt": "x"}
        write_json(self.paths.update_journal, {**journal, "replaced": ["a.py"], "added": [], "removed": []})
        self.claimed: list[str] = []

    def claim(self, free):
        def take(name):
            self.claimed.append(name)
            return object() if free else None

        return take

    def test_restores_when_no_updater_runs(self):
        self.assertTrue(recover_at_start(self.paths, self.claim(True), lambda handle: None))
        self.assertEqual((self.root / "a.py").read_bytes(), b"old")
        self.assertEqual(self.claimed, [UPDATE_MUTEX])

    def test_leaves_the_files_alone_while_the_updater_runs(self):
        self.assertFalse(recover_at_start(self.paths, self.claim(False), lambda handle: None))
        self.assertEqual((self.root / "a.py").read_bytes(), b"new")

    def test_a_rollback_that_cannot_finish_does_not_restart_the_app(self):
        (self.paths.update_dir / "backup-1.2.2" / "a.py").unlink()  # e.g. removed by an antivirus
        self.assertFalse(recover_at_start(self.paths, self.claim(True), lambda handle: None))

    def test_an_update_stopped_before_the_backup_needs_no_restart(self):
        journal = {"phase": "started", "from": "1.2.2", "to": "1.3.0", "attempt": "x"}
        write_json(self.paths.update_journal, {**journal, "replaced": [], "added": [], "removed": []})
        self.assertFalse(recover_at_start(self.paths, self.claim(True), lambda handle: None))

    def test_nothing_to_recover(self):
        self.paths.update_journal.unlink()
        self.assertFalse(recover_at_start(self.paths, self.claim(True), lambda handle: None))


if __name__ == "__main__":
    unittest.main()
