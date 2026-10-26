import tempfile
import unittest
from pathlib import Path

from focus_guard.update_trust import PRODUCT, Release, TrustError, sha256_file, verify_release
from tests.update_fixtures import OTHER_KEY, PUBLIC, encode, release_for, sha, sign

INSTALLED = "1.2.2"


def verify(release: dict, installed: str = INSTALLED) -> Release:
    data = encode(release)
    return verify_release(data, sign(data), installed, public_key=PUBLIC)


class VerifyReleaseTest(unittest.TestCase):
    def test_valid_release_parses(self):
        release = verify(release_for("1.3.0"))
        self.assertEqual(release.version, "1.3.0")
        self.assertEqual(release.zip_name, "Workmode-1.3.0.zip")
        self.assertEqual(
            {entry.path for entry in release.files},
            {"focus_guard/app.py", "focus_guard/version.py", "requirements.txt"},
        )
        self.assertEqual(PRODUCT, "Workmode")

    def test_wrong_key_refused(self):
        data = encode(release_for())
        with self.assertRaisesRegex(TrustError, "signature"):
            verify_release(data, sign(data, OTHER_KEY), INSTALLED, public_key=PUBLIC)

    def test_one_byte_changed_in_json_refused(self):
        data = encode(release_for())
        signature = sign(data)
        tampered = data.replace(b"1.3.0", b"1.3.1", 1)
        with self.assertRaisesRegex(TrustError, "signature"):
            verify_release(tampered, signature, INSTALLED, public_key=PUBLIC)

    def test_signature_checked_before_json_is_parsed(self):
        with self.assertRaisesRegex(TrustError, "signature"):
            verify_release(b"{not json", b"x" * 64, INSTALLED, public_key=PUBLIC)

    def test_built_in_placeholder_key_verifies_nothing(self):
        data = encode(release_for())
        with self.assertRaises(TrustError):
            verify_release(data, sign(data), INSTALLED)

    def test_equal_version_refused(self):
        with self.assertRaisesRegex(TrustError, "newer"):
            verify(release_for("1.2.2"))

    def test_older_version_refused(self):
        with self.assertRaisesRegex(TrustError, "newer"):
            verify(release_for("1.2.1"))

    def test_format_2_refused(self):
        with self.assertRaises(TrustError):
            verify({**release_for(), "format": 2})

    def test_other_product_refused(self):
        with self.assertRaisesRegex(TrustError, "product"):
            verify({**release_for(), "product": "Other"})

    def test_missing_product_refused(self):
        release = release_for()
        del release["product"]
        with self.assertRaisesRegex(TrustError, "product"):
            verify(release)

    def test_zip_name_must_match_version(self):
        release = release_for()
        release["zip"]["name"] = "Workmode-9.9.9.zip"
        with self.assertRaises(TrustError):
            verify(release)

    def test_duplicate_paths_refused(self):
        release = release_for()
        release["files"].append(dict(release["files"][0]))
        with self.assertRaisesRegex(TrustError, "twice"):
            verify(release)

    def test_bad_fields_refused(self):
        cases = {
            "hash not hex": lambda r: r["files"][0].update(sha256="Z" * 64),
            "hash upper case": lambda r: r["files"][0].update(sha256=r["files"][0]["sha256"].upper()),
            "negative size": lambda r: r["files"][0].update(size=-1),
            "bool size": lambda r: r["files"][0].update(size=True),
            "path not text": lambda r: r["files"][0].update(path=5),
            "no files": lambda r: r.update(files=[]),
            "bad version": lambda r: r.update(version="1.3"),
            "zip not object": lambda r: r.update(zip="Workmode-1.3.0.zip"),
            "requirements hash missing": lambda r: r.pop("requirements_sha256"),
            "not an object": None,
        }
        for name, change in cases.items():
            with self.subTest(name):
                if change is None:
                    data = b"[1, 2]"
                    with self.assertRaises(TrustError):
                        verify_release(data, sign(data), INSTALLED, public_key=PUBLIC)
                    continue
                release = release_for()
                change(release)
                with self.assertRaises(TrustError):
                    verify(release)


class Sha256FileTest(unittest.TestCase):
    def test_hashes_the_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.bin"
            path.write_bytes(b"abc" * 100000)
            self.assertEqual(sha256_file(path), sha(b"abc" * 100000))


if __name__ == "__main__":
    unittest.main()
