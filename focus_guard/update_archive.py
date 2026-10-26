"""Unpack a verified release zip into staging, entry by entry, refusing anything the signed release.json does not list.

Nothing is extracted blindly: each name must be a safe relative path, not protected, listed once, with the signed
size and SHA-256. Bytes are counted while they stream, so a zip header that lies about sizes cannot fill the disk.
"""

import hashlib
import re
import shutil
import stat
import zipfile
from pathlib import Path

from .update_trust import Release, sha256_file

MAX_TOTAL = 50 * 1024 * 1024
MAX_DEPTH = 8
# Never shipped in a release and never touched by the updater: the user's settings, history and local notes.
PROTECTED = (
    "config.json",
    "extension/config.js",
    "state/",
    "media/",
    ".git/",
    "dist/",
    ".superpowers/",
    "docs/superpowers/plans/",
)
_RESERVED = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", re.IGNORECASE)
_CHUNK = 64 * 1024


class ArchiveError(ValueError):
    pass


def is_protected(path: str) -> bool:
    name = path.replace("\\", "/").lower()
    for item in PROTECTED:
        if item.endswith("/") and (name == item[:-1] or name.startswith(item)):
            return True
        if name == item:
            return True
    return False


def check_path(path: str) -> None:
    """Raise ArchiveError unless `path` is a plain relative POSIX path that is safe to write on Windows."""
    if not path or "\\" in path or ":" in path or path.startswith("/"):
        raise ArchiveError(f"unsafe path: {path!r}")
    if any(ord(char) < 32 for char in path):
        raise ArchiveError(f"unsafe path: {path!r}")
    parts = path.split("/")
    if len(parts) > MAX_DEPTH:
        raise ArchiveError(f"too deep: {path!r}")
    for part in parts:
        if part in ("", ".", "..") or part.endswith((".", " ")) or _RESERVED.fullmatch(part):
            raise ArchiveError(f"unsafe path: {path!r}")
    if is_protected(path):
        raise ArchiveError(f"protected path: {path!r}")


def extract_to_staging(zip_path: Path, release: Release, staging: Path) -> None:
    """Fill `staging` with exactly the release's files. On any problem `staging` is deleted and the error raised."""
    shutil.rmtree(staging, ignore_errors=True)
    try:
        _check_zip_file(zip_path, release)
        with zipfile.ZipFile(zip_path) as archive:
            entries = _matching_entries(archive, release)
            for entry in release.files:
                _extract_one(archive, entries[entry.path], entry.size, entry.sha256, staging / entry.path)
    except zipfile.BadZipFile as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise ArchiveError("not a zip file") from error
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _check_zip_file(zip_path: Path, release: Release) -> None:
    if zip_path.stat().st_size != release.zip_size or sha256_file(zip_path) != release.zip_sha256:
        raise ArchiveError("the zip does not match release.json")
    if sum(entry.size for entry in release.files) > MAX_TOTAL:
        raise ArchiveError("the release is too big")
    for entry in release.files:
        check_path(entry.path)


def _matching_entries(archive: zipfile.ZipFile, release: Release) -> dict[str, zipfile.ZipInfo]:
    entries: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        if info.filename in entries:
            raise ArchiveError(f"{info.filename} is in the zip twice")
        if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
            raise ArchiveError(f"{info.filename} is not a plain file")
        entries[info.filename] = info
    if set(entries) != {entry.path for entry in release.files}:
        raise ArchiveError("the zip's files differ from release.json")
    return entries


def _extract_one(archive: zipfile.ZipFile, info: zipfile.ZipInfo, size: int, digest: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    hasher, written = hashlib.sha256(), 0
    with archive.open(info) as source, target.open("wb") as out:
        while chunk := source.read(min(_CHUNK, size + 1 - written)):
            written += len(chunk)
            if written > size:
                raise ArchiveError(f"{info.filename} is bigger than release.json says")
            hasher.update(chunk)
            out.write(chunk)
    if written != size or hasher.hexdigest() != digest:
        raise ArchiveError(f"{info.filename} does not match release.json")
