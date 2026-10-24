import tempfile
import time
import unittest
from pathlib import Path

from focus_guard.attempts import AttemptLog
from focus_guard.config import load_config
from focus_guard.guard import Guard
from focus_guard.muting import MuteStore
from focus_guard.session import Session
from focus_guard.waiting import Placement, WaitingStore, WaitingWindow
from focus_guard.watcher import WinInfo
from tests.helpers import base_config, write_config

CTRL, ALT, SHIFT, Q = 0x11, 0x12, 0x10, 0x51


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeWindows:
    def __init__(self):
        self.snapshot, self.error, self.alive = (), None, set()

    def own_pids(self):
        return set()

    def exists(self, hwnd):
        return hwnd in self.alive

    def list_windows(self, exclude_pids):
        if self.error:
            error, self.error = self.error, None
            raise error
        return tuple(self.snapshot)


DEFAULT_PLACEMENT = Placement(1, (0, 0, 100, 100))


class FakeActions:
    def __init__(self):
        self.calls, self.launch_ok, self.minimize_error = [], True, None
        self.placements = {}  # hwnd -> Placement, or None for a window that is gone
        self.pids = {}  # hwnd -> owner pid; default hwnd * 10, as win() builds them

    def owner_pid(self, hwnd):
        return None if self.placement(hwnd) is None else self.pids.get(hwnd, hwnd * 10)

    def minimize(self, hwnd):
        self.calls.append(("minimize", hwnd))
        if self.minimize_error:
            raise self.minimize_error

    def placement(self, hwnd):
        return self.placements.get(hwnd, DEFAULT_PLACEMENT)

    def set_placement(self, hwnd, placement):
        self.calls.append(("set_placement", hwnd, placement))

    def restore(self, hwnd, state):
        self.calls.append(("restore", hwnd, state))

    def launch(self, args):
        self.calls.append(("launch", tuple(args)))
        return self.launch_ok


class FakeUi:
    def __init__(self):
        self.calls, self.replies = [], []

    def show_popup(self, text, seconds):
        self.calls.append(("popup", text, seconds))

    def show_video(self, media, seconds):
        self.calls.append(("video", media, seconds))

    def show_summary(self, text):
        self.calls.append(("summary", text))

    def show_note(self, text, seconds):
        self.calls.append(("note", text, seconds))

    def ask_phrase(self):
        self.calls.append(("ask",))

    def poll_phrase(self):
        return self.replies.pop(0) if self.replies else None


class FakeAudio:
    def __init__(self):
        self.playing, self.muted, self.calls = set(), {}, []

    def audio_processes(self):
        return set(self.playing)

    def is_muted(self, process):
        return self.muted.get(process, False)

    def set_mute(self, process, muted):
        self.calls.append((process, muted))
        self.muted[process] = muted


class FakeKeys:
    def __init__(self):
        self.down = set()

    def pressed(self, vks):
        return self.down & set(vks)


class FakeRoasts:
    def next(self):
        return "ROAST"


def win(hwnd, process, state="normal"):
    return WinInfo(hwnd, hwnd * 10, process, f"{process} window", state)


class GuardCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.video = self.dir / "clip.mp4"
        self.video.write_bytes(b"x")
        self.cfg = self.config(grace_seconds=0)  # most tests check today's behaviour, without a grace period
        self.clock = FakeClock()
        self.session = Session(self.clock(), self.clock() + 600, True)
        self.windows, self.actions, self.ui, self.keys = FakeWindows(), FakeActions(), FakeUi(), FakeKeys()
        self.log = AttemptLog(self.dir / "attempts.log")
        self.waiting = WaitingStore(self.dir / "waiting.json")
        self.audio, self.mutes, self.mute_on = FakeAudio(), MuteStore(self.dir / "mutes.json"), False
        self.exit_on = False  # the window's "Emergency exit" button (state/exit_request)

    def config(self, **extra):
        return load_config(write_config(self.dir, {**base_config(self.video), **extra}))

    def make(self, dry_run=False, cfg=None, videos_dir=None):
        return Guard(
            cfg or self.cfg,
            self.session,
            self.windows,
            self.actions,
            self.ui,
            self.keys,
            self.log,
            FakeRoasts(),
            waiting=self.waiting,
            audio=self.audio,
            mutes=self.mutes,
            mute_requested=lambda: self.mute_on,
            exit_requested=lambda: self.exit_on,
            clear_exit_request=self.clear_exit,
            clock=self.clock,
            dry_run=dry_run,
            videos_dir=videos_dir,
        )

    def clear_exit(self):
        self.exit_on = False

    def logged(self):
        return [(entry["type"], entry["detail"]) for entry in self.log.read()]

    def settle(self, guard, *windows):
        self.windows.snapshot = windows
        guard.tick()
        self.clock.advance(1.5)
        guard.tick()

    def tick(self, guard, seconds=0.0):
        self.clock.advance(seconds)
        return guard.tick()


class BlockedWindowTest(GuardCase):
    def end_text(self):
        return time.strftime("%H:%M", time.localtime(self.session.end))

    def show(self, guard, state, seconds):
        self.windows.snapshot = (win(5, "Discord.exe", state),)
        self.tick(guard, seconds)

    def notes(self):
        return [call for call in self.ui.calls if call[0] == "note"]

    def test_blocked_app_is_minimized_and_remembered_never_closed(self):
        self.actions.placements[5] = Placement(1, (1, 2, 3, 4))
        guard = self.make()
        self.show(guard, "normal", 0)
        self.assertEqual(self.actions.calls, [("minimize", 5)])
        self.assertEqual(self.waiting.load()[5].placement, Placement(1, (1, 2, 3, 4)))
        for _ in range(9):
            self.show(guard, "minimized", 1.0)
        self.assertEqual({call[0] for call in self.actions.calls}, {"minimize"})
        self.assertEqual(self.logged(), [("blocked_app", "Discord.exe")])

    def test_reopened_waiting_window_is_minimized_again_with_a_note(self):
        guard = self.make()
        self.show(guard, "normal", 0)
        self.show(guard, "minimized", 0.5)
        self.show(guard, "normal", 0.5)
        self.assertEqual(self.actions.calls, [("minimize", 5), ("minimize", 5)])
        expected = f"Discord is waiting until {self.end_text()} — everything keeps running"
        self.assertEqual(self.notes(), [("note", expected, 4)])

    def test_reopen_note_is_rate_limited(self):
        guard = self.make()
        self.show(guard, "normal", 0)
        for _ in range(3):  # reopened at +1, +2 and +3 seconds
            self.show(guard, "minimized", 0.5)
            self.show(guard, "normal", 0.5)
        self.assertEqual(len(self.notes()), 1)
        self.show(guard, "minimized", 7.6)
        self.show(guard, "normal", 0.5)  # 10.1 s after the first note
        self.assertEqual(len(self.notes()), 2)

    def test_failing_minimize_is_logged_once_per_window(self):
        self.actions.minimize_error = OSError("access denied")
        guard = self.make()
        self.show(guard, "normal", 0)
        for _ in range(4):  # the program keeps re-showing itself: 8 more ticks
            self.show(guard, "minimized", 0.25)
            self.show(guard, "normal", 0.25)
        self.assertEqual([kind for kind, _ in self.logged()].count("error"), 1)

    def test_window_that_refuses_to_minimize_is_minimized_again_each_tick(self):
        guard = self.make()  # the fake minimize "works" but the window stays normal, like an elevated program
        for _ in range(5):
            self.show(guard, "normal", 0.25)
        self.assertEqual(self.actions.calls, [("minimize", 5)] * 5)
        self.assertEqual([kind for kind, _ in self.logged()].count("error"), 1)
        self.assertEqual(self.notes(), [])

    def test_closed_waiting_window_leaves_the_waiting_list(self):
        guard = self.make()
        self.show(guard, "normal", 0)
        self.windows.snapshot = ()
        self.tick(guard, 0.25)
        self.assertEqual(self.waiting.load(), {})

    def test_hidden_waiting_window_stays_waiting_and_gets_the_note_when_it_comes_back(self):
        guard = self.make()
        self.show(guard, "normal", 0)
        self.windows.snapshot, self.windows.alive = (), {5}  # hidden to the tray
        self.tick(guard, 0.25)
        self.assertIn(5, self.waiting.load())
        self.show(guard, "normal", 0.25)
        self.assertEqual(self.actions.calls, [("minimize", 5), ("minimize", 5)])
        self.assertEqual(len(self.notes()), 1)

    def test_a_reused_handle_of_another_program_is_waited_with_its_own_placement(self):
        guard = self.make()
        self.show(guard, "normal", 0)
        self.actions.placements[5] = Placement(1, (9, 9, 9, 9))
        self.windows.snapshot = (WinInfo(5, 777, "Steam.exe", "Steam", "normal"),)
        self.tick(guard, 0.25)
        self.assertEqual(self.waiting.load()[5].pid, 777)
        self.assertEqual(self.waiting.load()[5].placement, Placement(1, (9, 9, 9, 9)))

    def test_restore_skips_windows_that_no_longer_exist(self):
        guard = self.make()
        self.actions.placements[6] = Placement(1, (5, 6, 7, 8))
        self.windows.snapshot = (win(5, "Discord.exe"), win(6, "Steam.exe"))
        self.tick(guard)
        self.actions.placements[5] = None
        self.assertFalse(self.tick(guard, 601))
        restored = [call for call in self.actions.calls if call[0] == "set_placement"]
        self.assertEqual(restored, [("set_placement", 6, Placement(1, (5, 6, 7, 8)))])
        self.assertEqual(self.waiting.load(), {})

    def test_waiting_windows_survive_a_guard_restart(self):
        self.actions.placements[5] = Placement(1, (1, 2, 3, 4))
        first = self.make()
        self.show(first, "normal", 0)
        self.actions.placements[5] = Placement(2, (0, 0, 0, 0))  # minimized now
        second = self.make()
        self.show(second, "minimized", 1.0)
        self.assertFalse(self.tick(second, 601))
        self.assertIn(("set_placement", 5, Placement(1, (1, 2, 3, 4))), self.actions.calls)

    def test_grace_period_ignores_allowed_windows_but_not_blocked_ones(self):
        guard = self.make(cfg=self.config(grace_seconds=20))
        self.windows.snapshot = (win(1, "Code.exe"),)
        self.tick(guard)
        self.windows.snapshot = (win(1, "Code.exe"), win(5, "Discord.exe"))
        self.tick(guard, 1.0)
        self.windows.snapshot = (win(1, "Code.exe", "minimized"), win(5, "Discord.exe", "minimized"))
        self.tick(guard, 4.0)
        self.assertEqual(self.actions.calls, [("minimize", 5)])
        self.assertEqual(self.ui.calls, [])

    def test_session_grace_override_zero_acts_at_once(self):
        self.session = Session(self.clock(), self.clock() + 600, True, "k@2026-10-25", 0)
        guard = self.make(cfg=self.config(grace_seconds=20))
        self.settle(guard, win(1, "Code.exe"))
        self.windows.snapshot = (win(1, "Code.exe", "minimized"),)
        self.tick(guard, 1.0)
        self.assertIn("video", [call[0] for call in self.ui.calls])

    def test_protected_windows_are_left_alone(self):
        guard = self.make()
        self.windows.snapshot = (win(1, "explorer.exe"),)
        self.tick(guard)
        self.assertEqual(self.actions.calls, [])


class AllowedWindowTest(GuardCase):
    def test_closing_an_allowed_window_shows_a_roast_and_relaunches(self):
        guard = self.make()
        self.settle(guard, win(1, "Code.exe"))
        self.windows.snapshot = ()
        self.tick(guard, 0.5)
        self.assertEqual(self.ui.calls, [("popup", "ROAST", 10)])
        self.assertIn(("launch", ("code", "C:/project")), self.actions.calls)
        self.assertEqual(self.logged(), [("closed", "Code.exe")])

    def test_closing_one_of_several_windows_roasts_but_does_not_relaunch(self):
        guard = self.make()
        self.settle(guard, win(1, "Code.exe"), win(2, "Code.exe"))
        self.windows.snapshot = (win(2, "Code.exe"),)
        self.tick(guard, 0.5)
        self.assertEqual(self.ui.calls, [("popup", "ROAST", 10)])
        self.assertEqual([call for call in self.actions.calls if call[0] == "launch"], [])

    def test_a_hidden_but_existing_window_is_not_a_close(self):
        guard = self.make()
        self.settle(guard, win(1, "Code.exe"))
        self.windows.alive = {1}
        self.windows.snapshot = ()
        self.tick(guard, 0.5)
        self.assertEqual((self.ui.calls, self.actions.calls, self.logged()), ([], [], []))

    def test_one_failing_action_does_not_drop_the_other_events_of_the_tick(self):
        guard = self.make()
        self.settle(guard, win(1, "Code.exe"))
        self.actions.minimize_error = OSError("access denied")
        self.windows.snapshot = (win(5, "Discord.exe"),)
        self.tick(guard, 0.5)
        self.assertIn(("launch", ("code", "C:/project")), self.actions.calls)
        self.assertEqual([kind for kind, _ in self.logged()], ["blocked_app", "error", "closed"])

    def test_relaunches_are_rate_limited_and_logged(self):
        guard = self.make()
        for hwnd in range(1, 5):
            self.settle(guard, win(hwnd, "Code.exe"))
            self.windows.snapshot = ()
            self.tick(guard, 0.5)
        launches = [call for call in self.actions.calls if call[0] == "launch"]
        self.assertEqual(len(launches), 3)
        self.assertIn(("launch_failed", "Code.exe: too many relaunches"), self.logged())

    def test_failed_launch_is_logged(self):
        self.actions.launch_ok = False
        guard = self.make()
        self.settle(guard, win(1, "Code.exe"))
        self.windows.snapshot = ()
        self.tick(guard, 0.5)
        self.assertIn(("launch_failed", "Code.exe"), self.logged())

    def test_minimize_restores_the_window_and_plays_the_video(self):
        guard = self.make()
        self.settle(guard, win(1, "Code.exe"))
        self.windows.snapshot = (win(1, "Code.exe", "minimized"),)
        self.tick(guard, 0.5)
        self.assertIn(("restore", 1, "normal"), self.actions.calls)
        self.assertEqual(self.ui.calls, [("video", str(self.video), 20)])
        self.assertEqual(self.logged(), [("minimized", "Code.exe")])

    def test_video_plays_a_ticked_video(self):
        mine = self.dir / "mine.webm"
        mine.write_bytes(b"x")
        data = base_config(self.video)
        data["videos"], data["video_files"], data["grace_seconds"] = [str(mine)], [str(mine)], 0
        guard = self.make(cfg=load_config(write_config(self.dir, data)))
        self.settle(guard, win(1, "Code.exe"))
        self.windows.snapshot = (win(1, "Code.exe", "maximized"),)
        self.tick(guard, 0.5)
        self.assertEqual(self.ui.calls, [("video", str(mine), 20)])

    def test_the_users_own_video_beats_the_bundled_ones_when_nothing_is_ticked(self):
        bundled = self.dir / "videos"
        bundled.mkdir()
        (bundled / "built.mp4").write_bytes(b"x")
        data = base_config(self.video)
        data["grace_seconds"] = 0
        guard = self.make(cfg=load_config(write_config(self.dir, data)), videos_dir=bundled)
        self.settle(guard, win(1, "Code.exe"))
        self.windows.snapshot = (win(1, "Code.exe", "maximized"),)
        self.tick(guard, 0.5)
        self.assertEqual(self.ui.calls, [("video", str(self.video), 20)])

    def test_video_falls_back_to_the_url_when_the_file_is_missing(self):
        data = base_config(self.dir / "gone.mp4")
        data["video"]["fallback_url"] = "https://example.com/v"
        data["grace_seconds"] = 0
        guard = self.make(cfg=load_config(write_config(self.dir, data)))
        self.settle(guard, win(1, "Code.exe"))
        self.windows.snapshot = (win(1, "Code.exe", "maximized"),)
        self.tick(guard, 0.5)
        self.assertEqual(self.ui.calls, [("video", "https://example.com/v", 20)])


class MuteTest(GuardCase):
    def test_mute_request_mutes_only_waiting_programs(self):
        guard = self.make()
        self.audio.playing = {"spotify.exe", "chrome.exe"}
        self.windows.snapshot = (win(5, "Spotify.exe"), win(1, "chrome.exe"))
        self.tick(guard)
        self.assertEqual(self.audio.calls, [])
        self.mute_on = True
        self.tick(guard, 0.25)
        self.assertEqual(self.audio.calls, [("spotify.exe", True)])

    def test_mute_applies_to_audio_that_starts_later(self):
        guard = self.make()
        self.mute_on = True
        self.windows.snapshot = (win(5, "Spotify.exe", "minimized"),)
        self.tick(guard, 1.0)
        self.assertEqual(self.audio.calls, [])
        self.audio.playing = {"spotify.exe"}
        self.tick(guard, 2.0)
        self.assertEqual(self.audio.calls, [("spotify.exe", True)])
        self.tick(guard, 0.25)
        self.assertEqual(self.audio.calls, [("spotify.exe", True)])

    def test_session_end_restores_previous_mute_state(self):
        guard = self.make()
        self.audio.playing, self.audio.muted = {"spotify.exe", "discord.exe"}, {"spotify.exe": True}
        self.mute_on = True
        self.windows.snapshot = (win(5, "Spotify.exe"), win(6, "Discord.exe"))
        self.tick(guard)
        self.assertFalse(self.tick(guard, 601))
        self.assertEqual(self.audio.muted, {"spotify.exe": True, "discord.exe": False})
        self.assertEqual(self.mutes.load(), {})

    def test_cancelling_the_mute_gives_the_sound_back_and_muting_again_works(self):
        guard = self.make()
        self.audio.playing, self.audio.muted = {"spotify.exe", "discord.exe"}, {"discord.exe": True}
        self.windows.snapshot = (win(5, "Spotify.exe", "minimized"), win(6, "Discord.exe", "minimized"))
        self.mute_on = True
        self.tick(guard)
        self.mute_on = False
        self.tick(guard, 0.25)
        self.assertEqual(self.audio.muted, {"spotify.exe": False, "discord.exe": True})
        self.assertEqual(self.mutes.load(), {})
        self.mute_on = True
        self.tick(guard, 0.25)
        self.assertEqual(self.audio.muted, {"spotify.exe": True, "discord.exe": True})

    def test_a_restarted_guard_gives_the_sound_back_if_the_mute_was_cancelled_meanwhile(self):
        self.mutes.remember("spotify.exe", False)
        self.audio.muted = {"spotify.exe": True}
        guard = self.make()
        self.tick(guard)
        self.assertEqual(self.audio.muted, {"spotify.exe": False})

    def test_a_muted_program_reopened_mid_session_is_muted_again(self):
        guard = self.make()
        self.audio.playing = {"spotify.exe"}
        self.mute_on = True
        self.windows.snapshot = (win(5, "Spotify.exe"),)
        self.tick(guard)
        self.audio.muted["spotify.exe"] = False  # closed and reopened: Windows gives it a new, unmuted audio session
        self.tick(guard, 0.25)
        self.assertTrue(self.audio.muted["spotify.exe"])
        self.assertFalse(self.tick(guard, 601))
        self.assertEqual(self.audio.muted, {"spotify.exe": False})  # the state from before the first mute

    def test_no_mute_without_request(self):
        guard = self.make()
        self.audio.playing = {"spotify.exe"}
        self.windows.snapshot = (win(5, "Spotify.exe"),)
        for _ in range(4):
            self.tick(guard, 0.25)
        self.assertEqual(self.audio.calls, [])

    def test_dry_run_mutes_nothing(self):
        self.waiting.add(WaitingWindow(5, 50, "Spotify.exe", DEFAULT_PLACEMENT))  # left over from a live run
        guard = self.make(dry_run=True)
        self.audio.playing, self.mute_on = {"spotify.exe"}, True
        self.windows.snapshot = (win(5, "Spotify.exe"),)
        self.tick(guard)
        self.tick(guard, 601)
        self.assertEqual(self.audio.calls, [])


class ExternalEventTest(GuardCase):
    def test_closed_tab_shows_a_roast(self):
        guard = self.make()
        guard.push_external("tab_closed", "github.com")
        self.tick(guard)
        self.assertEqual(self.ui.calls, [("popup", "ROAST", 10)])
        self.assertEqual(self.logged(), [("tab_closed", "github.com")])

    def test_blocked_site_is_only_logged_and_unknown_kinds_are_ignored(self):
        guard = self.make()
        guard.push_external("blocked_site", "youtube.com")
        guard.push_external("format_disk", "c:")
        self.tick(guard)
        self.assertEqual(self.ui.calls, [])
        self.assertEqual(self.logged(), [("blocked_site", "youtube.com")])


class DryRunTest(GuardCase):
    def test_dry_run_minimizes_nothing(self):
        guard = self.make(dry_run=True)
        self.windows.snapshot = (win(5, "Discord.exe"),)
        self.tick(guard)
        self.tick(guard, 601)
        self.assertEqual(self.actions.calls, [])
        self.assertIn(("blocked_app", "dry-run: Discord.exe"), self.logged())
        self.assertFalse((self.dir / "waiting.json").exists())

    def test_dry_run_logs_but_never_acts(self):
        guard = self.make(dry_run=True)
        self.settle(guard, win(1, "Code.exe"))
        self.windows.snapshot = (win(5, "Discord.exe"),)
        self.tick(guard, 0.5)
        self.assertEqual(self.actions.calls, [])
        self.assertEqual(self.ui.calls, [])
        self.assertEqual(self.logged()[0], ("blocked_app", "dry-run: Discord.exe"))
        self.assertIn(("closed", "dry-run: Code.exe"), self.logged())

    def test_dry_run_notes_the_shortcut_without_asking(self):
        guard = self.make(dry_run=True)
        self.keys.down = {CTRL, ALT, SHIFT, Q}
        self.tick(guard)
        self.assertEqual(self.ui.calls, [])
        self.assertEqual(self.logged()[0][0], "emergency_exit")


class EmergencyTest(GuardCase):
    COMBO = {CTRL, ALT, SHIFT, Q}

    def test_shortcut_opens_the_input_once_and_the_phrase_ends_the_session(self):
        guard = self.make()
        self.keys.down = set(self.COMBO)
        self.tick(guard)
        self.tick(guard, 0.25)
        self.assertEqual(self.ui.calls, [("ask",)])
        self.keys.down = set()
        self.ui.replies.append(self.cfg.phrase)
        self.assertTrue(self.tick(guard, 0.25))
        self.assertFalse(self.tick(guard, 0.25))
        self.assertEqual(self.ui.calls[-1][0], "summary")
        self.assertIn(("emergency_exit", ""), self.logged())

    def test_wrong_phrase_reopens_the_input_and_the_session_continues(self):
        guard = self.make()
        self.keys.down = set(self.COMBO)
        self.tick(guard)
        self.keys.down = set()
        self.ui.replies.append("nope")
        self.assertTrue(self.tick(guard, 0.25))
        self.assertEqual(self.ui.calls, [("ask",), ("ask",)])
        self.assertTrue(self.tick(guard, 0.25))

    def test_closing_the_input_empty_ends_nothing(self):
        guard = self.make()
        self.keys.down = set(self.COMBO)
        self.tick(guard)
        self.keys.down = set()
        self.ui.replies.append("")
        self.assertTrue(self.tick(guard, 0.25))
        self.assertTrue(self.tick(guard, 0.25))
        self.assertEqual(self.ui.calls, [("ask",)])


class ExitRequestTest(GuardCase):
    def test_exit_request_asks_phrase_in_live_session(self):
        guard = self.make()
        self.exit_on = True
        self.assertTrue(self.tick(guard))
        self.assertEqual((self.ui.calls, self.exit_on), ([("ask",)], False))
        self.ui.replies.append(self.cfg.phrase)
        self.tick(guard, 0.25)
        self.assertFalse(self.tick(guard, 0.25))
        self.assertIn(("emergency_exit", ""), self.logged())

    def test_exit_request_while_the_box_is_open_does_not_open_a_second(self):
        guard = self.make()
        self.exit_on = True
        self.tick(guard)
        self.exit_on = True
        self.tick(guard, 0.25)
        self.assertEqual(self.ui.calls, [("ask",)])

    def test_exit_request_ends_trial_at_once(self):
        guard = self.make(dry_run=True)
        self.exit_on = True
        self.tick(guard)
        self.assertFalse(self.tick(guard, 0.25))
        self.assertIn(("emergency_exit", "dry-run: trial ended from the window"), self.logged())
        self.assertNotIn(("ask",), self.ui.calls)


class FinishTest(GuardCase):
    def test_session_end_shows_only_the_congratulation(self):
        guard = self.make()
        self.windows.snapshot = (win(5, "Discord.exe"),)
        self.tick(guard)
        self.tick(guard, 601)
        self.assertEqual(self.ui.calls[-1], ("summary", "הסשן הסתיים. כל הכבוד."))

    def test_run_survives_an_exception_in_a_tick(self):
        guard = self.make()
        self.windows.error = RuntimeError("boom")
        guard.run(sleep=lambda seconds: self.clock.advance(300))
        kinds = [kind for kind, _ in self.logged()]
        self.assertIn("error", kinds)
        self.assertEqual(kinds[0], "session_start")
        self.assertIn("session_end", kinds)


if __name__ == "__main__":
    unittest.main()


class SessionEndTest(GuardCase):
    def test_a_failing_window_restore_still_unmutes_and_shows_the_summary(self):
        guard = self.make()
        self.audio.playing, self.mute_on = {"spotify.exe"}, True
        self.windows.snapshot = (win(5, "Spotify.exe"),)
        self.tick(guard)

        def broken() -> None:
            raise OSError("waiting.json locked")

        guard.restore_waiting = broken  # type: ignore[method-assign]
        self.assertFalse(self.tick(guard, 601))
        self.assertEqual(self.audio.muted, {"spotify.exe": False})
        self.assertEqual(self.ui.calls[-1], ("summary", "הסשן הסתיים. כל הכבוד."))
        self.assertIn("error", [kind for kind, _ in self.logged()])

    def test_the_end_happens_once_even_if_the_summary_fails(self):
        guard = self.make()
        attempts = []

        def broken(text: str) -> None:
            attempts.append(text)
            raise RuntimeError("no window")

        self.ui.show_summary = broken
        self.assertFalse(self.tick(guard, 601))
        self.assertFalse(self.tick(guard, 0.25))
        self.assertEqual(len(attempts), 1)
        self.assertEqual([kind for kind, _ in self.logged()].count("session_end"), 1)
