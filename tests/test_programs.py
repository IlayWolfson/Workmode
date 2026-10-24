import unittest
from collections.abc import Sequence

from focus_guard.programs import (
    NOT_A_PROGRAM,
    Program,
    installer_icon,
    match,
    program_from_drop,
    real_program,
    to_offer,
)


def prog(name: str, process: str = "") -> Program:
    exe = process or name.replace(" ", "").lower() + ".exe"
    return Program(name, exe, f"C:/Apps/{exe}")


class FakeSource:
    def __init__(self, files: dict[str, Program]) -> None:
        self.files = files

    def running(self) -> Sequence[Program]:
        return []

    def installed(self) -> Sequence[Program]:
        return []

    def from_file(self, path: str) -> Program | None:
        return self.files.get(path)

    def name_of(self, process: str, path: str) -> str:
        return process


class ToOfferTest(unittest.TestCase):
    def test_one_per_process_minus_allowed_and_hidden_sorted(self):
        running = [
            prog("Zoom"),
            prog("Visual Studio Code", "code.exe"),
            prog("Zoom"),
            prog("Chrome"),
            prog("Shell", "explorer.exe"),
        ]
        offered = to_offer(running, allowed=["CHROME.EXE"], hidden=["explorer.exe"])
        self.assertEqual([item.name for item in offered], ["Visual Studio Code", "Zoom"])


class MatchTest(unittest.TestCase):
    def test_names_that_start_with_the_query_come_first(self):
        programs = [prog("Paint"), prog("Notepad Words"), prog("WordPad"), prog("Word")]
        self.assertEqual([item.name for item in match("wo", programs)], ["Word", "WordPad", "Notepad Words"])

    def test_at_most_five(self):
        programs = [prog(f"Tool {index}") for index in range(7)]
        self.assertEqual(len(match("tool", programs)), 5)

    def test_a_blank_query_matches_nothing(self):
        self.assertEqual(match("  ", [prog("Word")]), [])


class DropTest(unittest.TestCase):
    def test_a_program_file_is_accepted(self):
        word = prog("Word")
        self.assertEqual(program_from_drop("C:/Desktop/Word.lnk", FakeSource({"C:/Desktop/Word.lnk": word})), word)

    def test_anything_else_is_refused(self):
        for path in ("C:/Docs/x.pdf", "C:/Desktop/Folder.lnk"):
            with self.subTest(path=path), self.assertRaises(ValueError) as caught:
                program_from_drop(path, FakeSource({}))
            self.assertEqual(str(caught.exception), NOT_A_PROGRAM)


class InstallerIconTest(unittest.TestCase):
    def test_msi_shortcut_icons_are_not_programs(self):
        windir = r"C:\Windows"
        self.assertTrue(installer_icon(r"C:\Windows\Installer\{90160000}\wordicon.exe", windir))
        self.assertTrue(installer_icon("c:/windows/installer/{1}/x.exe", windir))
        self.assertFalse(installer_icon(r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE", windir))
        self.assertFalse(installer_icon(r"C:\Windows\notepad.exe", windir))


class LauncherTest(unittest.TestCase):
    def test_a_launcher_gives_the_program_next_to_it(self):
        folder = "C:/Program Files/Blender Foundation/Blender 5.2/"
        present = {folder + "blender-launcher.exe", folder + "blender.exe"}
        self.assertEqual(real_program(folder + "blender-launcher.exe", present.__contains__), folder + "blender.exe")

    def test_other_launcher_names(self):
        present = {"C:/A/game_launcher.exe", "C:/A/game.exe", "C:/B/ToolLauncher.exe", "C:/B/Tool.exe"}
        self.assertEqual(real_program("C:/A/game_launcher.exe", present.__contains__), "C:/A/game.exe")
        self.assertEqual(real_program("C:/B/ToolLauncher.exe", present.__contains__), "C:/B/Tool.exe")

    def test_without_a_program_next_to_it_the_target_stays(self):
        self.assertEqual(real_program("C:/X/app-launcher.exe", lambda path: False), "C:/X/app-launcher.exe")
        self.assertEqual(real_program("C:/X/code.exe", lambda path: True), "C:/X/code.exe")
