import unittest

from focus_guard.watcher import Watcher, WinInfo

ALLOWED = frozenset({"code.exe", "chrome.exe"})
PROTECTED = frozenset({"explorer.exe"})


def win(hwnd, process, state="normal", pid=None):
    return WinInfo(hwnd, pid if pid is not None else hwnd * 10, process, f"{process} window", state)


def kinds(events):
    return [event.kind for event in events]


class BlockedWindowTest(unittest.TestCase):
    def setUp(self):
        self.watcher = Watcher(ALLOWED, PROTECTED)

    def test_first_sighting_emits_blocked_app_once(self):
        discord = win(1, "Discord.exe")
        self.assertEqual(kinds(self.watcher.step([discord], 0.0)), ["blocked_app"])
        self.assertEqual(self.watcher.step([discord], 1.0), [])

    def test_blocked_window_reopened_after_being_minimized_is_reported(self):
        w = Watcher(ALLOWED, PROTECTED)
        self.assertEqual(kinds(w.step([win(1, "Discord.exe")], 0.0)), ["blocked_app"])
        self.assertEqual(w.step([win(1, "Discord.exe", "minimized")], 0.5), [])
        self.assertEqual(kinds(w.step([win(1, "Discord.exe", "normal")], 1.0)), ["blocked_reopened"])
        self.assertEqual(w.step([win(1, "Discord.exe", "normal")], 1.25), [])  # once per reopening

    def test_blocked_stuck_no_longer_exists(self):
        w = Watcher(ALLOWED, PROTECTED)
        w.step([win(1, "Discord.exe")], 0.0)
        self.assertEqual(w.step([win(1, "Discord.exe")], 9.0), [])

    def test_event_carries_the_window_details(self):
        event = self.watcher.step([win(7, "Game.exe", pid=700)], 0.0)[0]
        self.assertEqual((event.hwnd, event.pid, event.process), (7, 700, "Game.exe"))

    def test_protected_processes_are_ignored_case_insensitively(self):
        self.assertEqual(self.watcher.step([win(1, "Explorer.EXE")], 0.0), [])

    def test_same_handle_after_it_vanished_is_a_new_sighting(self):
        discord = win(1, "Discord.exe")
        self.watcher.step([discord], 0.0)
        self.watcher.step([], 1.0)
        self.assertEqual(kinds(self.watcher.step([discord], 2.0)), ["blocked_app"])


class AllowedWindowTest(unittest.TestCase):
    def setUp(self):
        self.watcher = Watcher(ALLOWED, PROTECTED)

    def settle(self, *windows):
        self.watcher.step(windows, 0.0)
        self.watcher.step(windows, 1.5)

    def test_closing_a_tracked_window_emits_closed(self):
        self.settle(win(1, "Code.exe"))
        events = self.watcher.step([], 2.0)
        self.assertEqual([(e.kind, e.process, e.pid) for e in events], [("closed", "Code.exe", 10)])

    def test_transient_window_vanishing_quickly_is_ignored(self):
        self.watcher.step([win(1, "Code.exe")], 0.0)
        self.assertEqual(self.watcher.step([], 0.5), [])

    def test_allowed_names_match_case_insensitively(self):
        self.settle(win(1, "CODE.EXE"))
        self.assertEqual(kinds(self.watcher.step([], 2.0)), ["closed"])

    def test_minimize_is_reported_with_the_state_to_restore(self):
        self.settle(win(1, "Code.exe"))
        events = self.watcher.step([win(1, "Code.exe", "minimized")], 2.0)
        self.assertEqual([(e.kind, e.state) for e in events], [("minimized", "normal")])

    def test_restore_down_is_resized_and_remembers_maximized(self):
        self.settle(win(1, "chrome.exe", "maximized"))
        events = self.watcher.step([win(1, "chrome.exe", "normal")], 2.0)
        self.assertEqual([(e.kind, e.state) for e in events], [("resized", "maximized")])

    def test_maximize_is_resized_and_remembers_normal(self):
        self.settle(win(1, "chrome.exe", "normal"))
        events = self.watcher.step([win(1, "chrome.exe", "maximized")], 2.0)
        self.assertEqual([(e.kind, e.state) for e in events], [("resized", "normal")])

    def test_no_flip_flop_once_the_window_is_restored(self):
        self.settle(win(1, "Code.exe"))
        self.assertEqual(kinds(self.watcher.step([win(1, "Code.exe", "minimized")], 2.0)), ["minimized"])
        self.assertEqual(self.watcher.step([win(1, "Code.exe", "normal")], 2.3), [])
        self.assertEqual(self.watcher.step([win(1, "Code.exe", "normal")], 5.0), [])

    def test_a_window_that_stays_changed_repeats_only_after_the_cooldown(self):
        self.settle(win(1, "Code.exe"))
        minimized = win(1, "Code.exe", "minimized")
        self.assertEqual(len(self.watcher.step([minimized], 2.0)), 1)
        self.assertEqual(self.watcher.step([minimized], 3.0), [])
        self.assertEqual(len(self.watcher.step([minimized], 4.1)), 1)

    def test_a_window_that_starts_minimized_is_not_an_event(self):
        minimized = win(1, "Code.exe", "minimized")
        for moment in (0.0, 1.5, 3.0):
            self.assertEqual(self.watcher.step([minimized], moment), [])

    def test_a_window_minimized_at_first_sight_and_restored_by_the_user_is_not_an_event(self):
        minimized = win(1, "Code.exe", "minimized")
        self.watcher.step([minimized], 0.0)
        self.watcher.step([minimized], 1.5)
        for moment in (2.0, 2.3, 5.0):
            self.assertEqual(self.watcher.step([win(1, "Code.exe", "normal")], moment), [])
        self.assertEqual(kinds(self.watcher.step([], 6.0)), ["closed"])

    def test_a_minimized_window_whose_restore_fails_stops_after_three_events(self):
        self.settle(win(1, "Code.exe"))
        minimized = win(1, "Code.exe", "minimized")
        fired = [len(self.watcher.step([minimized], 2.0 + 2.1 * i)) for i in range(8)]
        self.assertEqual(sum(fired), 3)
        for moment in (30.0, 31.0):
            self.assertEqual(self.watcher.step([win(1, "Code.exe", "normal")], moment), [])

    def test_a_window_that_stays_resized_becomes_the_new_baseline_after_three_events(self):
        self.settle(win(1, "Code.exe"))
        maximized = win(1, "Code.exe", "maximized")
        fired = [len(self.watcher.step([maximized], 2.0 + 2.1 * i)) for i in range(8)]
        self.assertEqual(sum(fired), 3)

    def test_a_window_that_still_exists_but_is_not_listed_is_not_closed(self):
        # e.g. cloaked while another virtual desktop is active
        self.settle(win(1, "Code.exe"))
        self.assertEqual(self.watcher.step([], 2.0, still_exists=lambda hwnd: True), [])
        self.assertEqual(self.watcher.step([win(1, "Code.exe")], 3.0), [])
        self.assertEqual(kinds(self.watcher.step([], 4.0, still_exists=lambda hwnd: False)), ["closed"])

    def test_closed_event_counts_the_other_windows_of_the_same_program(self):
        self.settle(win(1, "Code.exe"), win(2, "Code.exe"), win(3, "chrome.exe"))
        event = self.watcher.step([win(2, "Code.exe"), win(3, "chrome.exe")], 2.0)[0]
        self.assertEqual((event.kind, event.others), ("closed", 1))
        last = self.watcher.step([win(3, "chrome.exe")], 3.0)[0]
        self.assertEqual(last.others, 0)

    def test_windows_are_tracked_independently(self):
        self.settle(win(1, "Code.exe"), win(2, "chrome.exe"))
        events = self.watcher.step([win(1, "Code.exe", "minimized")], 2.0)
        self.assertEqual(sorted((e.kind, e.hwnd) for e in events), [("closed", 2), ("minimized", 1)])


class GracePeriodTest(unittest.TestCase):
    def test_grace_period_silences_allowed_windows_and_adopts_their_final_state(self):
        w = Watcher(ALLOWED, PROTECTED, grace_until=20.0)
        w.step([win(1, "Code.exe")], 0.0)
        self.assertEqual(w.step([win(1, "Code.exe", "maximized")], 5.0), [])
        self.assertEqual(w.step([win(1, "Code.exe", "maximized")], 21.0), [])
        self.assertEqual(kinds(w.step([win(1, "Code.exe", "normal")], 22.0)), ["resized"])

    def test_closing_an_allowed_window_during_grace_is_silent(self):
        w = Watcher(ALLOWED, PROTECTED, grace_until=20.0)
        w.step([win(1, "Code.exe")], 0.0)
        w.step([win(1, "Code.exe")], 1.5)
        self.assertEqual(w.step([], 5.0), [])

    def test_blocked_windows_are_reported_during_grace(self):
        w = Watcher(ALLOWED, PROTECTED, grace_until=20.0)
        self.assertEqual(kinds(w.step([win(5, "Discord.exe")], 0.0)), ["blocked_app"])

    def test_zero_grace_behaves_like_today(self):
        w = Watcher(ALLOWED, PROTECTED, grace_until=0.0)
        w.step([win(1, "Code.exe")], 0.0)
        w.step([win(1, "Code.exe")], 1.5)
        self.assertEqual(kinds(w.step([win(1, "Code.exe", "minimized")], 2.0)), ["minimized"])


if __name__ == "__main__":
    unittest.main()
