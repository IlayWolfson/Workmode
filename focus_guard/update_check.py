"""Ask GitHub for the latest release (at most once a day), download and verify a newer one into staging.

Only fixed hosts over HTTPS are contacted. Asset names are fixed; their URLs come from GitHub's answer but must be on
the same hosts. Staging never touches the installed files, so this may run during a session. Errors keep the last
result: an offline PC simply checks again at the next interval.
"""

import hashlib
import json
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from .jsonfile import read_json, write_json
from .paths import Paths
from .update_archive import MAX_TOTAL, ArchiveError, extract_to_staging
from .update_trust import PUBLIC_KEY, Release, TrustError, verify_release
from .version import VERSION, parse_version

REPO = "IlayWolfson/Workmode"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
# GitHub serves release downloads from github.com, then redirects to one of its asset hosts.
HOSTS = frozenset(
    {"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)
CHECK_EVERY = 24 * 3600
TIMEOUT = 30
MAX_BODY = MAX_TOTAL + 1024 * 1024
RELEASE_JSON, SIGNATURE = "release.json", "release.json.sig"
STATES = ("none", "ready", "refused", "error")


class HttpError(Exception):
    pass


class _Unusable(Exception):
    """GitHub's answer cannot be used now (bad JSON, missing asset): keep the last result."""


class Http(Protocol):
    def get(self, url: str, etag: str | None = None) -> tuple[int, bytes, dict[str, str]]: ...


def allowed_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in HOSTS and parts.port is None and not parts.username


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> urllib.request.Request | None:
        if not allowed_url(newurl):
            raise HttpError(f"redirect to a host that is not allowed: {urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibHttp:
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(SafeRedirect())

    def get(self, url: str, etag: str | None = None) -> tuple[int, bytes, dict[str, str]]:
        if not allowed_url(url):
            raise HttpError(f"not an allowed address: {url}")
        headers = {"User-Agent": "Workmode-updater", "Accept": "application/vnd.github+json, */*"}
        if etag:
            headers["If-None-Match"] = etag
        try:
            with self._opener.open(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as response:
                body = response.read(MAX_BODY + 1)
                if len(body) > MAX_BODY:
                    raise HttpError("the answer is too big")
                return response.status, complete_body(body, dict(response.headers)), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, b"", dict(error.headers or {})
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise HttpError(str(error)) from error


def complete_body(body: bytes, headers: dict[str, str]) -> bytes:
    """http.client returns a short body without an error when the connection drops; a cut answer is an HttpError."""
    lengths = [value for name, value in headers.items() if name.lower() == "content-length"]
    if lengths and lengths[0].strip().isdigit() and int(lengths[0]) != len(body):
        raise HttpError(f"the answer was cut off ({len(body)} of {lengths[0]} bytes)")
    return body


@dataclass(frozen=True)
class CheckResult:
    checked_at: float
    available: str | None
    state: str


def check(
    paths: Paths,
    http: Http,
    now: float,
    installed: str = VERSION,
    force: bool = False,
    public_key: bytes = PUBLIC_KEY,
) -> CheckResult:
    """The current update state; asks GitHub only when forced or the last check is older than CHECK_EVERY."""
    cache = _load_cache(paths)
    previous = _cached_result(cache)
    refused = tuple(item for item in cache.get("refused", []) if isinstance(item, str))
    if previous is not None and not force and previous.checked_at <= now < previous.checked_at + CHECK_EVERY:
        return previous
    etag = cache.get("etag") if isinstance(cache.get("etag"), str) else None
    if previous is None or (previous.state == "ready" and ready_version(paths) is None):
        etag = None  # a 304 must not bring back a result whose files are gone
    try:
        result, etag, refused = _ask(paths, http, now, installed, previous, etag, refused, public_key)
    except (HttpError, _Unusable, OSError):  # OSError: the disk, while staging
        result = CheckResult(now, previous.available, previous.state) if previous else CheckResult(now, None, "error")
    write_json(paths.update_check, {**result.__dict__, "etag": etag, "refused": list(refused)})
    return result


def last_result(paths: Paths) -> CheckResult | None:
    """The cached result of the last check, without asking GitHub."""
    return _cached_result(_load_cache(paths))


def ready_version(paths: Paths) -> str | None:
    """The version waiting in staging, or None."""
    result = _cached_result(_load_cache(paths))
    if result is None or result.state != "ready" or result.available is None:
        return None
    folder = paths.update_dir / result.available
    files = (folder / RELEASE_JSON, folder / SIGNATURE, folder / "staging")
    return result.available if all(item.exists() for item in files) else None


def load_staged(paths: Paths, installed: str = VERSION, public_key: bytes = PUBLIC_KEY) -> tuple[Release, Path] | None:
    """The staged release, its signature checked again, and its staging folder; None when there is none."""
    version = ready_version(paths)
    if version is None:
        return None
    folder = paths.update_dir / version
    try:
        release = verify_release(
            (folder / RELEASE_JSON).read_bytes(), (folder / SIGNATURE).read_bytes(), installed, public_key
        )
    except (OSError, TrustError):
        return None
    return (release, folder / "staging") if release.version == version else None


def _load_cache(paths: Paths) -> dict:
    data = read_json(paths.update_check)
    return data if isinstance(data, dict) else {}


def _cached_result(cache: dict) -> CheckResult | None:
    checked_at, available, state = cache.get("checked_at"), cache.get("available"), cache.get("state")
    if not isinstance(checked_at, (int, float)) or isinstance(checked_at, bool) or state not in STATES:
        return None
    if available is not None and not isinstance(available, str):
        return None
    return CheckResult(float(checked_at), available, state)


def _ask(
    paths: Paths,
    http: Http,
    now: float,
    installed: str,
    previous: CheckResult | None,
    etag: str | None,
    refused: tuple[str, ...],
    public_key: bytes,
) -> tuple[CheckResult, str | None, tuple[str, ...]]:
    status, body, headers = http.get(API_LATEST, etag)
    if status == 304:
        same = CheckResult(now, previous.available, previous.state) if previous else CheckResult(now, None, "none")
        return same, etag, refused
    if status == 404:  # no release published yet
        return CheckResult(now, None, "none"), None, refused
    if status != 200:
        raise _Unusable(f"GitHub answered {status}")
    listing, version = _latest(body)
    new_etag = headers.get("ETag") or headers.get("etag")
    if parse_version(version) <= parse_version(installed):
        return CheckResult(now, None, "none"), new_etag, refused
    if version in refused:
        return CheckResult(now, version, "refused"), new_etag, refused
    if ready_version(paths) != version:
        try:
            _download(paths, http, listing, version, installed, public_key)
        except (TrustError, ArchiveError):
            shutil.rmtree(paths.update_dir / version, ignore_errors=True)
            return CheckResult(now, version, "refused"), new_etag, (*refused, version)
    return CheckResult(now, version, "ready"), new_etag, refused


def _latest(body: bytes) -> tuple[dict, str]:
    try:
        listing = json.loads(body.decode("utf-8"))
    except ValueError as error:
        raise _Unusable("GitHub's answer is not JSON") from error
    tag = listing.get("tag_name") if isinstance(listing, dict) else None
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise _Unusable("no version tag")
    try:
        parse_version(tag[1:])
    except ValueError as error:
        raise _Unusable(f"bad version tag {tag!r}") from error
    return listing, tag[1:]


def _asset_urls(listing: dict, names: tuple[str, ...]) -> dict[str, str]:
    urls: dict[str, str] = {}
    for asset in listing.get("assets") or []:
        if (
            isinstance(asset, dict)
            and asset.get("name") in names
            and isinstance(asset.get("browser_download_url"), str)
        ):
            urls[asset["name"]] = asset["browser_download_url"]
    if set(urls) != set(names) or not all(allowed_url(url) for url in urls.values()):
        raise _Unusable("the release's files are missing or not on GitHub")
    return urls


def _fetch(http: Http, url: str) -> bytes:
    status, body, _ = http.get(url)
    if status != 200:
        raise HttpError(f"{url} answered {status}")
    return body


def _download(paths: Paths, http: Http, listing: dict, version: str, installed: str, public_key: bytes) -> None:
    zip_name = f"Workmode-{version}.zip"
    urls = _asset_urls(listing, (RELEASE_JSON, SIGNATURE, zip_name))
    data, signature = _fetch(http, urls[RELEASE_JSON]), _fetch(http, urls[SIGNATURE])
    release = verify_release(data, signature, installed, public_key)
    if release.version != version:
        raise TrustError(f"the tag says {version}, the signed release says {release.version}")
    folder = paths.update_dir / version
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    zip_data = _fetch(http, urls[zip_name])
    if len(zip_data) != release.zip_size or hashlib.sha256(zip_data).hexdigest() != release.zip_sha256:
        # the signature is fine, so the zip was cut or damaged on the way: try again, never mark it refused
        raise HttpError("the zip does not match its signed hash")
    zip_path = folder / zip_name
    zip_path.write_bytes(zip_data)
    extract_to_staging(zip_path, release, folder / "staging")
    zip_path.unlink()
    (folder / RELEASE_JSON).write_bytes(data)
    (folder / SIGNATURE).write_bytes(signature)
