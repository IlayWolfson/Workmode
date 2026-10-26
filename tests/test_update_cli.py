import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from focus_guard import update_apply
from focus_guard.jsonfile import write_json
from focus_guard.paths import Paths
from focus_guard.session import Session, write_session
from focus_guard.update import UPDATE_MUTEX, UPDATER_MUTEX, main
from focus_guard.update_check import API_LATEST
from tests.test_update_apply import NEW, OLD, FakeMachine
from tests.test_update_check import ASSET_BASE, FakeHttp
from tests.update_fixtures import KEY, PUBLIC, encode, release_for, zip_bytes

NOW = 1_800_000_000.0


class UpdateCliTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "ת יקייה with space"
        self.paths = Paths(self.root)
        for name, data in OLD.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(data)
        self.http = FakeHttp()
        self.machine = FakeMachine(self.paths)
        self.lines: list[str] = []
        self.claimed: list[str] = []
        self.released: list[object] = []
        self.free_mutex = True
        self.guard = False
        patcher = mock.patch.object(update_apply, "REPLACE_PAUSE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def claim(self, name):
        self.claimed.append(name)
        return name if self.free_mutex else None  # the name stands for the handle

    def held(self):
        """How often the session lock is held right now."""
        return self.claimed.count(UPDATE_MUTEX) - self.released.count(UPDATE_MUTEX)

    def publish(self, version="1.3.0", files=NEW):
        data = zip_bytes(files)
        release = encode(release_for(version, files, data))
        files = {"release.json": release, "release.json.sig": KEY.sign(release), f"Workmode-{version}.zip": data}
        listing = {
            "tag_name": f"v{version}",
            "assets": [{"name": n, "browser_download_url": f"{ASSET_BASE}/v{version}/{n}"} for n in files],
        }
        self.http.routes[API_LATEST] = (200, json.dumps(listing).encode(), {})
        for name, body in files.items():
            self.http.routes[f"{ASSET_BASE}/v{version}/{name}"] = (200, body, {})

    def run_main(self, *argv):
        return main(
            list(argv),
            paths=self.paths,
            http=self.http,
            machine=self.machine,
            claim=self.claim,
            release_handle=self.released.append,
            now=lambda: NOW,
            out=self.lines.append,
            guard_alive=lambda: self.guard,
            upcoming=lambda now: [],
            installed="1.2.2",
            public_key=PUBLIC,
        )

    def tree(self):
        return {name: (self.root / name).read_bytes() for name in OLD if (self.root / name).exists()}

    def test_apply_installs_the_newer_release(self):
        self.publish()
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual((self.root / "focus_guard/app.py").read_bytes(), NEW["focus_guard/app.py"])
        self.assertEqual(self.lines[-1], "עודכן לגרסה 1.3.0")
        self.assertEqual(self.claimed[0], UPDATER_MUTEX)
        self.assertIn(UPDATE_MUTEX, self.claimed)
        self.assertEqual(sorted(self.released), sorted(self.claimed))

    def test_pip_runs_before_the_lock_so_sessions_can_still_start(self):
        self.publish(files={**NEW, "requirements.txt": b"psutil>=6\n"})
        held_during_pip = []
        real = self.machine.pip_install

        def pip(requirements):
            held_during_pip.append(self.held())
            return real(requirements)

        self.machine.pip_install = pip
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(held_during_pip, [0])

    def test_gate_is_asked_again_after_pip(self):
        self.publish(files={**NEW, "requirements.txt": b"psutil>=6\n"})

        def pip_then_session(requirements):
            write_session(self.paths.session, Session(NOW - 60, NOW + 3600, live=True))
            return True

        self.machine.pip_install = pip_then_session
        self.assertEqual(self.run_main("--apply"), 1)
        self.assertEqual(self.tree(), OLD)
        self.assertIn("סשן פעיל", self.lines[-1])

    def test_root_with_spaces_and_hebrew(self):
        self.publish()
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertTrue((self.root / "focus_guard/new.py").exists())

    def test_apply_refused_during_session_via_cli(self):
        self.publish()
        write_session(self.paths.session, Session(NOW - 60, NOW + 3600, live=True))
        self.assertEqual(self.run_main("--apply"), 1)
        self.assertEqual(self.tree(), OLD)
        self.assertIn("סשן פעיל", self.lines[-1])
        self.assertNotIn("stop", self.machine.calls)

    def test_apply_refused_while_guard_runs(self):
        self.publish()
        self.guard = True
        self.assertEqual(self.run_main("--apply"), 1)
        self.assertEqual(self.tree(), OLD)

    def test_second_updater_exits_without_changes(self):
        self.publish()
        self.free_mutex = False
        self.assertEqual(self.run_main("--apply"), 1)
        self.assertEqual(self.tree(), OLD)
        self.assertEqual(self.lines, ["כבר מתעדכן"])
        self.assertEqual(self.http.calls, [])

    def test_recovery_runs_before_the_gate(self):
        journal = {"phase": "started", "from": "1.2.2", "to": "1.3.0", "attempt": "a"}
        write_json(self.paths.update_journal, {**journal, "replaced": [], "added": [], "removed": []})
        write_session(self.paths.session, Session(NOW - 60, NOW + 3600, live=True))
        self.run_main("--apply")
        self.assertFalse(update_apply.is_applying(self.paths))
        self.assertIn("סשן פעיל", self.lines[-1])

    def test_recover_only_undoes_and_never_updates(self):
        self.publish()
        journal = {"phase": "started", "from": "1.2.2", "to": "1.3.0", "attempt": "a"}
        write_json(self.paths.update_journal, {**journal, "replaced": [], "added": [], "removed": []})
        self.assertEqual(self.run_main("--recover"), 0)
        self.assertFalse(update_apply.is_applying(self.paths))
        self.assertEqual(self.http.calls, [])
        self.assertEqual(self.tree(), OLD)

    def test_recover_with_nothing_to_undo_does_nothing(self):
        self.assertEqual(self.run_main("--recover"), 0)
        self.assertEqual(self.machine.calls, [])

    def test_nothing_newer_says_so(self):
        self.publish("1.2.2")
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(self.lines[-1], "יש לך את הגרסה העדכנית")

    def test_unsigned_release_is_refused(self):
        self.publish()
        self.http.routes[f"{ASSET_BASE}/v1.3.0/release.json.sig"] = (200, b"x" * 64, {})
        self.assertEqual(self.run_main("--apply"), 1)
        self.assertEqual(self.lines[-1], "העדכון נדחה: הוא לא חתום כמו שצריך")
        self.assertEqual(self.tree(), OLD)

    def test_check_prints_available_version(self):
        self.publish()
        self.assertEqual(self.run_main("--check"), 0)
        self.assertIn("1.3.0", self.lines[-1])
        self.assertEqual(self.tree(), OLD)

    def test_needs_one_action(self):
        with self.assertRaises(SystemExit):
            self.run_main()


if __name__ == "__main__":
    unittest.main()
