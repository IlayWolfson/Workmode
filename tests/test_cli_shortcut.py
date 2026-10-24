import tempfile
import unittest
from pathlib import Path

from focus_guard import cli
from focus_guard.paths import Paths


class ShortcutCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "assets").mkdir()
        self.paths = Paths(self.root)
        self.made, self.created = [], []

    def run_cli(self):
        lines = []

        def make_shortcut(**options):
            self.created.append(options)
            return "C:/Desktop/Focus Guard.lnk"

        code = cli.main(
            ["shortcut"],
            paths=self.paths,
            out=lines.append,
            icon_maker=lambda source, target: self.made.append((source, target)),
            shortcut_maker=make_shortcut,
        )
        return code, "\n".join(lines)

    def test_missing_picture_is_reported_and_nothing_is_made(self):
        code, output = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("icon_source.png", output)
        self.assertEqual((self.made, self.created), ([], []))

    def test_creates_the_icon_and_the_shortcut(self):
        self.paths.icon_source.write_bytes(b"png")
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(self.made, [(self.paths.icon_source, self.paths.icon)])
        options = self.created[0]
        self.assertEqual(options["name"], "Hyperbolic Time Chamber")
        self.assertEqual(options["arguments"], "-m focus_guard.app")
        self.assertEqual(options["icon"], str(self.paths.icon))
        self.assertEqual(options["workdir"], str(self.root))
        self.assertTrue(options["target"].lower().endswith("pythonw.exe"))
        self.assertIn("C:/Desktop/Focus Guard.lnk", output)


if __name__ == "__main__":
    unittest.main()
