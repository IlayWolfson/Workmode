import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from focus_guard import jsonfile


class WriteJsonTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "state" / "x.json"

    def test_a_briefly_locked_target_is_retried(self):
        real = os.replace
        calls = []

        def flaky(source, target):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("another process has it open")
            real(source, target)

        with mock.patch.object(jsonfile.os, "replace", flaky), mock.patch.object(jsonfile.time, "sleep"):
            jsonfile.write_json(self.path, {"a": 1})
        self.assertEqual(jsonfile.read_json(self.path), {"a": 1})
        self.assertEqual(len(calls), 3)

    def test_write_text_atomic_writes_the_exact_text_and_leaves_no_temp_file(self):
        target = self.dir / "sub" / "copy.json"
        jsonfile.write_text_atomic(target, '{\n  "a": 1\n}\n')
        self.assertEqual(target.read_text(encoding="utf-8"), '{\n  "a": 1\n}\n')
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["copy.json"])

    def test_a_lasting_lock_raises_and_leaves_no_temp_file(self):
        def locked(source, target):
            raise PermissionError("locked")

        with mock.patch.object(jsonfile.os, "replace", locked), mock.patch.object(jsonfile.time, "sleep"):
            with self.assertRaises(PermissionError):
                jsonfile.write_json(self.path, {"a": 1})
        self.assertEqual(list(self.path.parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
