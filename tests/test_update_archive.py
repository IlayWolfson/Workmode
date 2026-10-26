import tempfile
import unittest
import zipfile
from pathlib import Path

from focus_guard.update_archive import MAX_DEPTH, MAX_TOTAL, ArchiveError, check_path, extract_to_staging, is_protected
from tests.update_fixtures import FILES, release_for, sha, trusted, zip_bytes


class CheckPathTest(unittest.TestCase):
    def test_refuses_unsafe_paths(self):
        bad = [
            "",
            "../x.py",
            "a/../../x.py",
            "a/./b.py",
            "/abs.py",
            "\\abs.py",
            "a\\b.py",
            "C:x.py",
            "C:/x.py",
            "a.py:stream",
            "con.txt",
            "NUL",
            "focus_guard/com1.py",
            "lpt9",
            "a//b.py",
            "trailing.",
            "trailing ",
            "ctrl\x01.py",
            "/".join(["d"] * MAX_DEPTH) + "/x.py",
        ]
        for path in bad:
            with self.subTest(path=path), self.assertRaises(ArchiveError):
                check_path(path)

    def test_refuses_protected_paths_in_any_case(self):
        for path in (
            "config.json",
            "Config.JSON",
            "extension/config.js",
            "state/session.json",
            "media/x.mp4",
            ".git/config",
            "dist/a.zip",
            ".superpowers/x.md",
            "Docs/Superpowers/Plans/a.md",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_protected(path))
                with self.assertRaises(ArchiveError):
                    check_path(path)

    def test_allows_normal_paths(self):
        for path in (
            "focus_guard/app.py",
            "extension/background.js",
            "README.md",
            "docs/superpowers/specs/a.md",
            "/".join(["d"] * (MAX_DEPTH - 1)) + "/x.py",
            "configs.json",
            "statements/a.py",
        ):
            with self.subTest(path=path):
                check_path(path)
                self.assertFalse(is_protected(path))


class ExtractTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.zip_path = self.root / "Workmode-1.3.0.zip"
        self.staging = self.root / "staging"

    def extract(self, release: dict) -> None:
        extract_to_staging(self.zip_path, trusted(release), self.staging)

    def write_zip(self, files: dict[str, bytes]) -> bytes:
        data = zip_bytes(files)
        self.zip_path.write_bytes(data)
        return data

    def assert_refused(self, release: dict) -> None:
        with self.assertRaises(ArchiveError):
            self.extract(release)
        self.assertFalse(self.staging.exists())

    def test_valid_zip_extracts_every_file(self):
        self.write_zip(FILES)
        self.extract(release_for())
        for name, data in FILES.items():
            self.assertEqual((self.staging / name).read_bytes(), data)

    def test_old_staging_is_replaced(self):
        (self.staging / "leftover.py").parent.mkdir(parents=True)
        (self.staging / "leftover.py").write_bytes(b"old")
        self.write_zip(FILES)
        self.extract(release_for())
        self.assertFalse((self.staging / "leftover.py").exists())

    def test_zip_hash_must_match(self):
        self.write_zip(FILES)
        release = release_for()
        release["zip"]["sha256"] = sha(b"other")
        self.assert_refused(release)

    def test_zip_size_must_match(self):
        self.write_zip(FILES)
        release = release_for()
        release["zip"]["size"] += 1
        self.assert_refused(release)

    def test_extra_entry_refused(self):
        data = self.write_zip({**FILES, "focus_guard/extra.py": b"x"})
        self.assert_refused(release_for(files=FILES, zip_data=data))

    def test_missing_entry_refused(self):
        smaller = dict(list(FILES.items())[:2])
        data = self.write_zip(smaller)
        self.assert_refused(release_for(files=FILES, zip_data=data))

    def test_entry_hash_mismatch_refused(self):
        changed = {**FILES, "focus_guard/app.py": b"print('evil')\n!!"}
        data = self.write_zip(changed)
        release = release_for(files=FILES, zip_data=data)
        release["files"][0]["size"] = len(changed["focus_guard/app.py"])
        self.assert_refused(release)

    def test_entry_bigger_than_declared_refused(self):
        big = {**FILES, "focus_guard/app.py": b"a" * 100000}
        data = self.write_zip(big)
        release = release_for(files=big, zip_data=data)
        release["files"][0]["size"] = 10
        self.assert_refused(release)

    def test_entry_smaller_than_declared_refused(self):
        data = self.write_zip(FILES)
        release = release_for(files=FILES, zip_data=data)
        release["files"][0]["size"] += 5
        self.assert_refused(release)

    def test_total_over_cap_refused(self):
        data = self.write_zip(FILES)
        release = release_for(files=FILES, zip_data=data)
        release["files"][0]["size"] = MAX_TOTAL
        self.assert_refused(release)

    def test_unsafe_name_in_release_refused(self):
        files = {"../outside.py": b"x"}
        data = self.write_zip(files)
        self.assert_refused(release_for(files=files, zip_data=data))
        self.assertFalse((self.root / "outside.py").exists())

    def test_protected_name_refused(self):
        files = {"config.json": b"{}"}
        data = self.write_zip(files)
        self.assert_refused(release_for(files=files, zip_data=data))

    def test_symlink_entry_refused(self):
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            info = zipfile.ZipInfo("focus_guard/app.py")
            info.external_attr = 0o120777 << 16
            archive.writestr(info, b"../../evil")
        data = self.zip_path.read_bytes()
        self.assert_refused(release_for(files={"focus_guard/app.py": b"../../evil"}, zip_data=data))

    def test_duplicate_entry_in_zip_refused(self):
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            archive.writestr("a.py", b"one")
            archive.writestr("a.py", b"one")
        data = self.zip_path.read_bytes()
        self.assert_refused(release_for(files={"a.py": b"one"}, zip_data=data))

    def test_not_a_zip_refused(self):
        self.zip_path.write_bytes(b"not a zip")
        self.assert_refused(release_for(files=FILES, zip_data=b"not a zip"))


if __name__ == "__main__":
    unittest.main()
