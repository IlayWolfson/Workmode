import unittest

from focus_guard.ownpids import TOOL_NAMES, app_tree, own_tree

TREE = {1: [2, 3], 2: [4], 3: [], 4: [], 5: []}
NAMES = {1: "python.exe", 2: "msedgewebview2.exe", 3: "chrome.exe", 4: "msedgewebview2.exe", 5: "python.exe"}


class OwnTreeTest(unittest.TestCase):
    def test_includes_tool_children_and_their_helpers_but_not_relaunched_apps(self):
        found = own_tree(1, lambda pid: TREE[pid], lambda pid: NAMES[pid], TOOL_NAMES)
        self.assertEqual(found, {1, 2, 4})

    def test_a_relaunched_apps_own_children_stay_out(self):
        tree = {1: [3], 3: [6], 6: []}
        names = {1: "python.exe", 3: "chrome.exe", 6: "msedgewebview2.exe"}
        self.assertEqual(own_tree(1, lambda p: tree[p], lambda p: names[p], TOOL_NAMES), {1})

    def test_names_match_case_insensitively(self):
        tree, names = {1: [2], 2: []}, {1: "Python.EXE", 2: "MSEDGEWEBVIEW2.EXE"}
        self.assertEqual(own_tree(1, lambda p: tree[p], lambda p: names[p], TOOL_NAMES), {1, 2})


class AppTreeTest(unittest.TestCase):
    def test_app_pids_include_window_children(self):
        tree = {10: [11, 12], 11: [13], 12: [], 13: []}
        names = {10: "pythonw.exe", 11: "python.exe", 12: "notepad.exe", 13: "msedgewebview2.exe"}
        self.assertEqual(app_tree(10, True, tree.get, names.get), {10, 11, 13})

    def test_no_app_or_dead_app_gives_nothing(self):
        self.assertEqual(app_tree(None, True, lambda pid: [], lambda pid: ""), set())
        self.assertEqual(app_tree(10, False, lambda pid: [11], lambda pid: "python.exe"), set())


if __name__ == "__main__":
    unittest.main()
