import json
import tempfile
import unittest
import urllib.request

from focus_guard.paths import Paths
from focus_guard.update_check import (
    API_LATEST,
    CHECK_EVERY,
    HttpError,
    SafeRedirect,
    UrllibHttp,
    check,
    complete_body,
    load_staged,
    ready_version,
)
from tests.update_fixtures import FILES, KEY, OTHER_KEY, PUBLIC, encode, release_for, zip_bytes

ASSET_BASE = "https://github.com/IlayWolfson/Workmode/releases/download"
NOW = 1_800_000_000.0


class FakeHttp:
    def __init__(self):
        self.routes: dict[str, tuple[int, bytes, dict[str, str]] | Exception] = {}
        self.calls: list[tuple[str, str | None]] = []
        self.etag_answer: str | None = None  # a request with this ETag gets 304

    def get(self, url, etag=None):
        self.calls.append((url, etag))
        if url == API_LATEST and etag is not None and etag == self.etag_answer:
            return 304, b"", {}
        answer = self.routes.get(url)
        if answer is None:
            return 404, b"", {}
        if isinstance(answer, Exception):
            raise answer
        return answer


class CheckTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = Paths(folder.name)
        self.http = FakeHttp()

    def publish(self, version="1.3.0", signed_version=None, key=KEY, assets=None, etag="abc"):
        signed_version = signed_version or version
        data = zip_bytes(FILES)
        release = encode(release_for(signed_version, FILES, data))
        files = {
            "release.json": release,
            "release.json.sig": key.sign(release),
            f"Workmode-{version}.zip": data,
        }
        names = list(files) if assets is None else assets
        listing = {
            "tag_name": f"v{version}",
            "assets": [{"name": name, "browser_download_url": f"{ASSET_BASE}/v{version}/{name}"} for name in names],
        }
        self.http.routes[API_LATEST] = (200, json.dumps(listing).encode(), {"ETag": etag})
        for name, body in files.items():
            self.http.routes[f"{ASSET_BASE}/v{version}/{name}"] = (200, body, {})

    def run_check(self, now=NOW, force=False):
        return check(self.paths, self.http, now, installed="1.2.2", force=force, public_key=PUBLIC)

    def asset_calls(self):
        return [url for url, _ in self.http.calls if url != API_LATEST]

    def test_newer_release_downloaded_and_staged_once(self):
        self.publish()
        result = self.run_check()
        self.assertEqual((result.state, result.available), ("ready", "1.3.0"))
        staging = self.paths.update_dir / "1.3.0" / "staging"
        self.assertEqual((staging / "focus_guard/app.py").read_bytes(), FILES["focus_guard/app.py"])
        self.assertEqual(ready_version(self.paths), "1.3.0")
        calls = len(self.http.calls)
        again = self.run_check(now=NOW + 100)
        self.assertEqual((again.state, again.available), ("ready", "1.3.0"))
        self.assertEqual(len(self.http.calls), calls)

    def test_staged_release_is_verified_again_when_loaded(self):
        self.publish()
        self.run_check()
        release, staging = load_staged(self.paths, installed="1.2.2", public_key=PUBLIC)
        self.assertEqual(release.version, "1.3.0")
        self.assertTrue((staging / "requirements.txt").exists())
        (self.paths.update_dir / "1.3.0" / "release.json").write_bytes(b"{}")
        self.assertIsNone(load_staged(self.paths, installed="1.2.2", public_key=PUBLIC))

    def test_no_newer_release(self):
        self.publish("1.2.2")
        result = self.run_check()
        self.assertEqual((result.state, result.available), ("none", None))
        self.assertEqual(self.asset_calls(), [])

    def test_check_waits_24_hours_unless_forced(self):
        self.publish("1.2.2")
        self.run_check()
        self.run_check(now=NOW + CHECK_EVERY - 1)
        self.assertEqual(len(self.http.calls), 1)
        self.run_check(now=NOW + 10, force=True)
        self.run_check(now=NOW + CHECK_EVERY + 20)
        self.assertEqual(len(self.http.calls), 3)

    def test_clock_moved_back_checks_again(self):
        self.publish("1.2.2")
        self.run_check()
        self.run_check(now=NOW - 3600)
        self.assertEqual(len(self.http.calls), 2)

    def test_offline_keeps_last_result(self):
        self.publish()
        self.run_check()
        self.http.routes[API_LATEST] = HttpError("offline")
        result = self.run_check(now=NOW + 10, force=True)
        self.assertEqual((result.state, result.available), ("ready", "1.3.0"))

    def test_offline_without_history_is_error_not_exception(self):
        self.http.routes[API_LATEST] = HttpError("offline")
        self.assertEqual(self.run_check().state, "error")

    def test_refused_version_not_downloaded_again(self):
        self.publish(key=OTHER_KEY)
        result = self.run_check()
        self.assertEqual((result.state, result.available), ("refused", "1.3.0"))
        self.assertFalse((self.paths.update_dir / "1.3.0").exists())
        before = len(self.asset_calls())
        again = self.run_check(now=NOW + 10, force=True)
        self.assertEqual(again.state, "refused")
        self.assertEqual(len(self.asset_calls()), before)

    def test_cut_download_is_an_error_and_is_tried_again(self):
        self.publish()
        url = f"{ASSET_BASE}/v1.3.0/Workmode-1.3.0.zip"
        full = self.http.routes[url]
        self.http.routes[url] = (200, full[1][:-10], {})
        result = self.run_check()
        self.assertEqual(result.state, "error")
        self.http.routes[url] = full
        self.assertEqual(self.run_check(now=NOW + 10, force=True).state, "ready")

    def test_disk_error_while_staging_is_error_not_exception(self):
        self.publish()
        self.http.routes[f"{ASSET_BASE}/v1.3.0/Workmode-1.3.0.zip"] = OSError("disk full")
        self.assertEqual(self.run_check().state, "error")

    def test_tag_must_match_the_signed_version(self):
        self.publish("1.3.0", signed_version="1.4.0")
        self.assertEqual(self.run_check().state, "refused")

    def test_304_reuses_cache(self):
        self.publish()
        self.run_check()
        self.http.etag_answer = "abc"
        result = self.run_check(now=NOW + 10, force=True)
        self.assertEqual((result.state, result.available), ("ready", "1.3.0"))
        self.assertEqual(self.http.calls[-1], (API_LATEST, "abc"))

    def test_304_without_cache_is_none(self):
        self.http.routes[API_LATEST] = (304, b"", {})
        self.assertEqual(self.run_check().state, "none")

    def test_404_is_none(self):
        self.assertEqual(self.run_check().state, "none")

    def test_missing_asset_and_bad_json_are_errors_not_exceptions(self):
        self.publish(assets=["release.json", "release.json.sig"])
        self.assertEqual(self.run_check().state, "error")
        self.http.routes[API_LATEST] = (200, b"{not json", {})
        self.assertEqual(self.run_check(force=True).state, "error")
        self.http.routes[API_LATEST] = (200, b'{"tag_name": 5}', {})
        self.assertEqual(self.run_check(force=True).state, "error")

    def test_asset_on_another_host_is_not_requested(self):
        self.publish()
        listing = json.loads(self.http.routes[API_LATEST][1])
        listing["assets"][0]["browser_download_url"] = "https://evil.example/release.json"
        self.http.routes[API_LATEST] = (200, json.dumps(listing).encode(), {})
        self.assertEqual(self.run_check().state, "error")
        self.assertNotIn("https://evil.example/release.json", self.asset_calls())

    def test_broken_cache_file_is_ignored(self):
        self.paths.state.mkdir()
        self.paths.update_check.write_text("[1, 2", encoding="utf-8")
        self.publish("1.2.2")
        self.assertEqual(self.run_check().state, "none")


class CompleteBodyTest(unittest.TestCase):
    def test_short_body_raises(self):
        with self.assertRaises(HttpError):
            complete_body(b"abc", {"Content-Length": "10"})

    def test_matching_or_missing_length_passes(self):
        self.assertEqual(complete_body(b"abc", {"Content-Length": "3"}), b"abc")
        self.assertEqual(complete_body(b"abc", {}), b"abc")


class UrllibHttpTest(unittest.TestCase):
    def redirect(self, url):
        request = urllib.request.Request("https://github.com/x")
        return SafeRedirect().redirect_request(request, None, 302, "Found", {}, url)

    def test_redirect_to_other_host_refused(self):
        with self.assertRaises(HttpError):
            self.redirect("https://evil.example/x")

    def test_http_redirect_refused(self):
        with self.assertRaises(HttpError):
            self.redirect("http://github.com/x")

    def test_redirect_to_release_assets_allowed(self):
        self.assertIsNotNone(self.redirect("https://release-assets.githubusercontent.com/x"))

    def test_get_refuses_url_outside_hosts_without_network(self):
        with self.assertRaises(HttpError):
            UrllibHttp().get("https://evil.example/")
        with self.assertRaises(HttpError):
            UrllibHttp().get("http://api.github.com/")


if __name__ == "__main__":
    unittest.main()
