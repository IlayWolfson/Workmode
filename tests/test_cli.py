import json
import shutil
import tempfile
import unittest
from pathlib import Path

from focus_guard import cli
from focus_guard.paths import Paths
from focus_guard.watcher import WinInfo
from tests.helpers import base_config
from tests.update_fixtures import UNFINISHED_JSON

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.json"


class CliCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "extension").mkdir()
        shutil.copyfile(EXAMPLE, self.root / "config.example.json")
        self.paths = Paths(self.root)
        self.lines, self.spawned, self.now = [], [], 1000.0
        self.which, self.guard_alive = (lambda name: name), True

    def run_cli(self, *argv, lister=None):
        return cli.main(
            list(argv),
            paths=self.paths,
            spawn=self.spawned.append,
            now=lambda: self.now,
            lister=lister,
            out=self.lines.append,
            which=self.which,
            guard_alive=lambda: self.guard_alive,
        )

    def write_config(self, **changes):
        video = self.root / "clip.mp4"
        video.write_bytes(b"x")
        data = base_config(video)
        data.update(changes)
        self.paths.config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def output(self):
        return "\n".join(self.lines)


class InitTest(CliCase):
    def test_creates_config_token_and_extension_config(self):
        self.assertEqual(self.run_cli("init"), 0)
        data = json.loads(self.paths.config.read_text(encoding="utf-8"))
        token = data["server"]["token"]
        self.assertEqual(len(token), 32)
        script = self.paths.extension_config.read_text(encoding="utf-8")
        self.assertIn(token, script)
        self.assertIn("47653", script)

    def test_second_init_keeps_the_token(self):
        self.run_cli("init")
        first = json.loads(self.paths.config.read_text(encoding="utf-8"))["server"]["token"]
        self.run_cli("init")
        self.assertEqual(json.loads(self.paths.config.read_text(encoding="utf-8"))["server"]["token"], first)

    def test_missing_example_is_reported(self):
        self.paths.example.unlink()
        self.assertEqual(self.run_cli("init"), 1)


class CheckTest(CliCase):
    def test_valid_config_passes(self):
        self.write_config()
        self.assertEqual(self.run_cli("check"), 0)
        self.assertIn("Config OK", self.output())
        self.assertIn("code.exe", self.output())

    def test_a_launch_command_that_cannot_be_found_fails_the_check(self):
        self.write_config()
        self.which = lambda name: None
        self.assertEqual(self.run_cli("check"), 1)
        self.assertIn("cannot be found", self.output())
        self.assertIn("chrome", self.output())

    def test_youtube_lists_are_counted(self):
        self.write_config(youtube={"channels": ["@a1", "Name"], "playlists": ["PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi"]})
        self.assertEqual(self.run_cli("check"), 0)
        self.assertIn("YouTube: 2 channels, 1 playlists, 0 videos", self.lines)

    def test_youtube_videos_are_counted(self):
        self.write_config(youtube={"channels": ["@a1"], "videos": ["aircAruvnKk", "dQw4w9WgXcQ"]})
        self.assertEqual(self.run_cli("check"), 0)
        self.assertIn("YouTube: 1 channels, 0 playlists, 2 videos", self.lines)

    def test_no_youtube_line_without_lists(self):
        self.write_config()
        self.run_cli("check")
        self.assertFalse(any(line.startswith("YouTube:") for line in self.lines))

    def test_placeholder_phrase_is_refused(self):
        self.write_config(emergency={"phrase": "CHANGE-ME-BEFORE-FIRST-USE"})
        self.assertEqual(self.run_cli("check"), 1)
        self.assertIn("phrase", self.output())


class StartStatusTest(CliCase):
    def test_start_defaults_to_dry_run_and_launches_both_processes(self):
        self.write_config()
        self.assertEqual(self.run_cli("start", "25"), 0)
        session = json.loads(self.paths.session.read_text(encoding="utf-8"))
        self.assertEqual((session["live"], session["end"] - session["start"]), (False, 1500.0))
        self.assertEqual(self.spawned, ["focus_guard.run_guard", "focus_guard.run_guardian"])
        self.assertIn("Dry-run", self.output())

    def test_live_flag_enforces_and_names_the_allowed_apps(self):
        self.write_config()
        self.assertEqual(self.run_cli("start", "10", "--live"), 0)
        self.assertTrue(json.loads(self.paths.session.read_text(encoding="utf-8"))["live"])
        self.assertIn("LIVE", self.output())
        self.assertIn("code.exe", self.output())

    def test_live_message_says_programs_wait_and_nothing_is_closed(self):
        self.write_config()
        self.run_cli("start", "10", "--live")
        self.assertIn("wait minimized", self.output())
        self.assertNotIn("will be closed", self.output())

    def test_new_session_drops_a_request_left_by_a_killed_guard(self):
        self.write_config()
        self.paths.state.mkdir(exist_ok=True)
        self.paths.mute_request.touch()
        self.assertEqual(self.run_cli("start", "10", "--live"), 0)
        self.assertFalse(self.paths.mute_request.exists())

    def test_second_start_is_refused(self):
        self.write_config()
        self.run_cli("start", "10")
        self.assertEqual(self.run_cli("start", "10"), 1)
        self.assertEqual(len(self.spawned), 2)

    def test_a_session_whose_guard_died_is_resumed_not_refused(self):
        self.write_config()
        self.run_cli("start", "10", "--live")
        self.guard_alive = False
        self.assertEqual(self.run_cli("start", "10"), 0)
        self.assertEqual(self.spawned[2:], ["focus_guard.run_guard", "focus_guard.run_guardian"])
        self.assertIn("resum", self.output().lower())

    def test_start_during_an_update_is_refused_with_a_message(self):
        self.write_config()
        self.paths.state.mkdir(exist_ok=True)
        self.paths.update_journal.write_text(UNFINISHED_JSON, encoding="utf-8")
        self.assertEqual(self.run_cli("start", "10"), 1)
        self.assertIn("מתעדכן", self.output())
        self.assertFalse(self.paths.session.exists())
        self.assertEqual(self.spawned, [])

    def test_bad_minutes_start_nothing(self):
        self.write_config()
        self.assertEqual(self.run_cli("start", "0"), 1)
        self.assertFalse(self.paths.session.exists())
        self.assertEqual(self.spawned, [])

    def test_broken_config_with_no_earlier_good_one_starts_nothing(self):
        self.paths.config.write_text("{nope", encoding="utf-8")
        self.assertEqual(self.run_cli("start", "10"), 1)
        self.assertFalse(self.paths.session.exists())
        self.assertEqual(self.spawned, [])

    def test_start_uses_last_good_when_config_is_broken(self):
        self.write_config()
        self.run_cli("status")
        self.run_cli("check")  # loads the good config once, which keeps a copy
        self.paths.config.write_text("{nope", encoding="utf-8")
        self.assertEqual(self.run_cli("start", "10"), 0)
        self.assertTrue(self.paths.session.exists())
        self.assertIn("config.json", self.output())

    def test_status_reports_remaining_time(self):
        self.write_config()
        self.run_cli("status")
        self.assertIn("No active session", self.output())
        self.run_cli("start", "30")
        self.now += 600
        self.run_cli("status")
        self.assertIn("20 min remaining", self.output())


class WindowsCommandTest(CliCase):
    def test_lists_process_and_title(self):
        windows = [WinInfo(1, 10, "Code.exe", "main.py", "normal"), WinInfo(2, 20, "chrome.exe", "Docs", "maximized")]
        self.assertEqual(self.run_cli("windows", lister=lambda: windows), 0)
        self.assertIn("Code.exe | main.py", self.output())
        self.assertIn("chrome.exe | Docs", self.output())


if __name__ == "__main__":
    unittest.main()
