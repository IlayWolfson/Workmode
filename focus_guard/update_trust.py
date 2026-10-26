"""Which releases the updater trusts: release.json signed with the maintainer's offline Ed25519 key.

The signature covers the exact bytes of release.json, so the product, version, zip and every file hash are signed.
Nothing else (HTTPS, GitHub's checksums) is trusted. A release must be strictly newer than the installed version.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .version import parse_version

# The maintainer's release key (raw Ed25519 public key, made with `tools/release.py --new-key` on 2026-10-26).
PUBLIC_KEY = bytes.fromhex("166e66936b9cbee319462d4d89e5c39715ee144e134b1ddd736ac3814478e3ae")
PRODUCT = "Workmode"
FORMAT = 1
_HASH = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024


class TrustError(ValueError):
    pass


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Release:
    version: str
    zip_name: str
    zip_sha256: str
    zip_size: int
    files: tuple[FileEntry, ...]
    requirements_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify_release(data: bytes, signature: bytes, installed: str, public_key: bytes = PUBLIC_KEY) -> Release:
    """The parsed release when `signature` over `data` verifies with `public_key` and it is newer than `installed`."""
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
    except (InvalidSignature, ValueError) as error:
        raise TrustError("bad signature") from error
    try:
        raw = json.loads(data.decode("utf-8"))
    except ValueError as error:
        raise TrustError("release.json is not JSON") from error
    release = _parse(raw)
    if parse_version(release.version) <= parse_version(installed):
        raise TrustError(f"{release.version} is not newer than {installed}")
    return release


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise TrustError(message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _size(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _parse(raw: Any) -> Release:
    _need(isinstance(raw, dict), "release.json is not an object")
    _need(raw.get("format") == FORMAT, "unknown format")
    _need(raw.get("product") == PRODUCT, "wrong product")
    version = raw.get("version")
    _need(isinstance(version, str), "bad version")
    try:
        parse_version(version)
    except ValueError as error:
        raise TrustError("bad version") from error
    archive = raw.get("zip")
    _need(isinstance(archive, dict), "bad zip")
    _need(archive.get("name") == f"Workmode-{version}.zip", "zip name does not match the version")
    _need(_hash(archive.get("sha256")) and _size(archive.get("size")), "bad zip")
    _need(_hash(raw.get("requirements_sha256")), "bad requirements hash")
    return Release(
        version,
        archive["name"],
        archive["sha256"],
        archive["size"],
        _files(raw.get("files")),
        raw["requirements_sha256"],
    )


def _files(raw: Any) -> tuple[FileEntry, ...]:
    _need(isinstance(raw, list) and bool(raw), "no files")
    entries: list[FileEntry] = []
    seen: set[str] = set()
    for item in raw:
        _need(isinstance(item, dict), "bad file entry")
        path, digest, size = item.get("path"), item.get("sha256"), item.get("size")
        _need(_text(path) and _hash(digest) and _size(size), "bad file entry")
        _need(path.lower() not in seen, f"{path} listed twice")
        seen.add(path.lower())
        entries.append(FileEntry(path, digest, size))
    return tuple(entries)
