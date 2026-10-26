import json
import tempfile
import unittest
from pathlib import Path

from focus_guard.update_archive import ArchiveError, extract_to_staging
from focus_guard.update_trust import verify_release
from tools.release import build_release, main, new_key, release_files, set_version

ROOT = Path(__file__).resolve().parent.parent
VERSION_PY = b'"""The installed version."""\r\n\r\nimport re\r\n\r\nVERSION = "1.2.2"\r\n'
MANIFEST = b'{\r\n  "name": "Workmode",\r\n  "version": "1.2.2",\r\n  "icons": {}\r\n}\r\n'
FILES = {
    "focus_guard/version.py": VERSION_PY,
    "focus_guard/app.py": b"print('app')\n",
    "extension/manifest.json": MANIFEST,
    "requirements.txt": b"psutil>=5.9\n",
    "README.md": b"# Workmode\n",
}


class FakeGit:
    def __init__(self, files, branch="main", dirty=""):
        self.files, self.branch, self.dirty = files, branch, dirty
        self.commands: list[list[str]] = []

    def __call__(self, command, cwd):
        self.commands.append(command)
        if command[:2] == ["git", "ls-files"]:
            return "\0".join(self.files) + "\0"
        if command[:2] == ["git", "rev-parse"]:
            return self.branch + "\n"
        if command[:2] == ["git", "status"]:
            return self.dirty
        return ""


class ReleaseCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "repo"
        for name, data in FILES.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(data)
        self.key = Path(folder.name) / "keys" / "release-signing.key"
        self.public = new_key(self.key)


class ReleaseFilesTest(ReleaseCase):
    def test_release_files_skip_protected(self):
        listed = [*FILES, "config.json", "extension/config.js", "state/x.json", "docs/superpowers/plans/a.md", "dist/a"]
        self.assertEqual(release_files(self.root, FakeGit(listed)), sorted(FILES))

    def test_unsafe_tracked_name_refused(self):
        with self.assertRaises(ArchiveError):
            release_files(self.root, FakeGit([*FILES, "con.txt"]))


class BuildTest(ReleaseCase):
    def test_built_release_verifies_with_matching_key(self):
        out = self.root.parent / "out"
        zip_path, json_path, sig_path = build_release(self.root, "1.3.0", self.key, out, sorted(FILES))
        release = verify_release(json_path.read_bytes(), sig_path.read_bytes(), "1.2.2", public_key=self.public)
        self.assertEqual(release.version, "1.3.0")
        self.assertEqual(json.loads(json_path.read_bytes())["product"], "Workmode")
        self.assertEqual(zip_path.name, "Workmode-1.3.0.zip")
        staging = out / "staging"
        extract_to_staging(zip_path, release, staging)
        self.assertEqual((staging / "README.md").read_bytes(), FILES["README.md"])

    def test_new_key_refuses_to_overwrite(self):
        with self.assertRaises(FileExistsError):
            new_key(self.key)

    def test_public_key_is_32_raw_bytes(self):
        self.assertEqual(len(self.public), 32)


class SetVersionTest(ReleaseCase):
    def test_set_version_keeps_crlf(self):
        set_version(self.root, "1.3.0")
        self.assertEqual((self.root / "focus_guard/version.py").read_bytes(), VERSION_PY.replace(b"1.2.2", b"1.3.0"))
        self.assertEqual((self.root / "extension/manifest.json").read_bytes(), MANIFEST.replace(b"1.2.2", b"1.3.0"))

    def test_repo_version_files_agree(self):
        version = (ROOT / "focus_guard/version.py").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))
        self.assertIn(f'VERSION = "{manifest["version"]}"', version)


class MainTest(ReleaseCase):
    def run_main(self, git, answer="y", version="1.3.0", public_key=None):
        self.lines: list[str] = []
        return main(
            [version],
            run=git,
            confirm=lambda prompt: answer,
            out=self.lines.append,
            root=self.root,
            key_path=self.key,
            public_key=self.public if public_key is None else public_key,
        )

    def test_refuses_a_key_that_is_not_the_built_in_one(self):
        git = FakeGit(sorted(FILES))
        self.assertEqual(self.run_main(git, public_key=bytes(32)), 1)
        self.assertIn("key", self.lines[-1])
        self.assertEqual((self.root / "focus_guard/version.py").read_bytes(), VERSION_PY)
        self.assertFalse(any(c[0] == "gh" or c[:2] == ["git", "commit"] for c in git.commands))

    def test_a_failure_while_building_puts_the_version_back(self):
        git = FakeGit([*sorted(FILES), "focus_guard/missing.py"])
        self.assertEqual(self.run_main(git), 1)
        self.assertEqual((self.root / "focus_guard/version.py").read_bytes(), VERSION_PY)
        self.assertEqual((self.root / "extension/manifest.json").read_bytes(), MANIFEST)
        self.assertFalse(any(c[0] == "gh" or c[:2] == ["git", "commit"] for c in git.commands))

    def test_refuses_dirty_tree(self):
        git = FakeGit(sorted(FILES), dirty=" M focus_guard/app.py\n")
        self.assertEqual(self.run_main(git), 1)
        self.assertFalse(any(c[0] == "gh" for c in git.commands))
        self.assertEqual((self.root / "focus_guard/version.py").read_bytes(), VERSION_PY)

    def test_refuses_other_branch(self):
        git = FakeGit(sorted(FILES), branch="feature")
        self.assertEqual(self.run_main(git), 1)
        self.assertFalse(any(c[0] == "gh" for c in git.commands))

    def test_refuses_a_version_that_is_not_newer(self):
        self.assertEqual(self.run_main(FakeGit(sorted(FILES)), version="1.2.2"), 1)

    def test_no_means_nothing_changes(self):
        git = FakeGit(sorted(FILES))
        self.assertEqual(self.run_main(git, answer="n"), 1)
        self.assertEqual((self.root / "focus_guard/version.py").read_bytes(), VERSION_PY)
        self.assertFalse(any(c[0] == "gh" or c[:2] == ["git", "commit"] for c in git.commands))

    def test_yes_bumps_commits_pushes_and_publishes_three_assets(self):
        git = FakeGit(sorted(FILES))
        self.assertEqual(self.run_main(git), 0)
        self.assertIn(b'"1.3.0"', (self.root / "focus_guard/version.py").read_bytes())
        kinds = [c[:2] for c in git.commands]
        self.assertLess(kinds.index(["git", "commit"]), kinds.index(["git", "push"]))
        publish = next(c for c in git.commands if c[0] == "gh")
        self.assertEqual(publish[:4], ["gh", "release", "create", "v1.3.0"])
        assets = [Path(item).name for item in publish if item.endswith((".zip", ".json", ".sig"))]
        self.assertEqual(sorted(assets), ["Workmode-1.3.0.zip", "release.json", "release.json.sig"])


class UpdateCmdTest(unittest.TestCase):
    def test_update_cmd_uses_the_same_gated_entry(self):
        text = (ROOT / "Update.cmd").read_bytes()
        self.assertIn(b'cd /d "%~dp0"', text)
        self.assertIn(b"python -m focus_guard.update --apply\r\n", text)
        self.assertNotIn(b"--force", text)
        self.assertIn(b"pause", text)


if __name__ == "__main__":
    unittest.main()
