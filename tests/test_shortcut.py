import unittest
from types import SimpleNamespace

from focus_guard import shortcut


class BuildScriptTest(unittest.TestCase):
    def test_script_contains_every_part_and_looks_up_the_real_desktop(self):
        script = shortcut.build_script(
            "Focus Guard", "C:/Py/pythonw.exe", "-m focus_guard.app", "C:/proj", "C:/proj/assets/i.ico"
        )
        for text in [
            "GetFolderPath('Desktop')",
            "'Focus Guard.lnk'",
            "'C:/Py/pythonw.exe'",
            "'-m focus_guard.app'",
            "'C:/proj'",
            "'C:/proj/assets/i.ico,0'",
            "$link.Save()",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, script)

    def test_startup_script_uses_startup_folder(self):
        script = shortcut.build_script("N", "t", "-m focus_guard.app --background", "w", "i", folder="Startup")
        self.assertIn("GetFolderPath('Startup')", script)
        self.assertNotIn("Desktop", script)

    def test_directory_puts_the_shortcut_in_that_folder(self):
        script = shortcut.build_script("N", "t", "a", "w", "i", directory="C:/My Apps/Workmode")
        self.assertIn("$folder = 'C:/My Apps/Workmode'", script)
        self.assertNotIn("GetFolderPath", script)

    def test_create_shortcut_passes_the_directory_on(self):
        shortcut.create_shortcut("N", "t", "a", "w", "i", run=self.fake_run(), directory="C:/proj")
        self.assertIn("$folder = 'C:/proj'", self.commands[0][-1])

    def fake_run(self, returncode=0, stdout="", stderr=""):
        self.commands = []

        def run(command, **kwargs):
            self.commands.append(command)
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

        return run

    def test_single_quotes_are_doubled(self):
        script = shortcut.build_script("N", "C:/O'Brien/pythonw.exe", "-m x", "C:/p", "C:/p/i.ico")
        self.assertIn("'C:/O''Brien/pythonw.exe'", script)


class CreateShortcutTest(unittest.TestCase):
    def fake_run(self, returncode=0, stdout="C:\\Users\\x\\Desktop\\Focus Guard.lnk\n", stderr=""):
        self.commands = []

        def run(command, **kwargs):
            self.commands.append(command)
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

        return run

    def test_returns_the_shortcut_path_and_runs_powershell(self):
        path = shortcut.create_shortcut("Focus Guard", "t", "a", "w", "i", run=self.fake_run())
        self.assertEqual(path, "C:\\Users\\x\\Desktop\\Focus Guard.lnk")
        self.assertEqual(self.commands[0][0], "powershell")
        self.assertIn("-NoProfile", self.commands[0])

    def test_failure_raises_with_the_error_text(self):
        with self.assertRaises(RuntimeError) as context:
            shortcut.create_shortcut("n", "t", "a", "w", "i", run=self.fake_run(returncode=1, stderr="boom"))
        self.assertIn("boom", str(context.exception))


if __name__ == "__main__":
    unittest.main()
