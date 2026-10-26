"""Publish a signed release: python tools/release.py 1.3.0 (or --new-key once, to make the signing key).

Needs a clean tree on main. Asks once, then sets the version in focus_guard/version.py and extension/manifest.json,
builds Workmode-<version>.zip from the tracked files (protected paths left out), writes release.json, signs it with
the offline key, commits, pushes and creates the GitHub release with the three files.

The private key never goes into the repo, GitHub or a release. Losing it or leaking it: publish no more releases,
say so in the README, and users reinstall from a fresh clone that carries a new public key.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from focus_guard.update_archive import MAX_TOTAL, check_path, is_protected  # noqa: E402
from focus_guard.update_trust import FORMAT, PRODUCT, PUBLIC_KEY, verify_release  # noqa: E402
from focus_guard.version import parse_version  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEY = Path.home() / ".workmode" / "release-signing.key"
VERSION_FILE = "focus_guard/version.py"
MANIFEST_FILE = "extension/manifest.json"
_VERSION_LINE = re.compile(rb'^VERSION = "[0-9]+\.[0-9]+\.[0-9]+"', re.MULTILINE)
_MANIFEST_LINE = re.compile(rb'"version": "[0-9]+\.[0-9]+\.[0-9]+"')

Runner = Callable[[list[str], Path], str]


def _run(command: list[str], cwd: Path) -> str:
    return subprocess.run(command, cwd=str(cwd), check=True, capture_output=True, text=True).stdout


def release_files(root: Path, run: Runner = _run) -> list[str]:
    """The tracked files that go into a release: protected paths left out, every name checked like the updater does."""
    names = [name for name in run(["git", "ls-files", "-z"], root).split("\0") if name]
    files = sorted(name for name in names if not is_protected(name))
    for name in files:
        check_path(name)
    return files


def new_key(path: Path) -> bytes:
    """Write a new private key to `path` (never over an existing one). Returns the raw public key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # raises FileExistsError
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _replace_once(path: Path, pattern: re.Pattern[bytes], new: bytes) -> None:
    data = path.read_bytes()
    changed, count = pattern.subn(new, data)
    if count != 1:
        raise ValueError(f"{path} must hold exactly one version line")
    path.write_bytes(changed)  # bytes in, bytes out: line endings stay as they are


def set_version(root: Path, version: str) -> None:
    parse_version(version)
    _replace_once(root / VERSION_FILE, _VERSION_LINE, f'VERSION = "{version}"'.encode())
    _replace_once(root / MANIFEST_FILE, _MANIFEST_LINE, f'"version": "{version}"'.encode())


def build_release(root: Path, version: str, key_path: Path, out: Path, files: list[str]) -> tuple[Path, Path, Path]:
    """Workmode-<version>.zip, release.json and release.json.sig in `out`."""
    entries, total = [], 0
    for name in files:
        source = root / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"{name} is not a plain file")
        data = source.read_bytes()
        entries.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
        total += len(data)
    if total > MAX_TOTAL:
        raise ValueError("the release is too big")
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / f"Workmode-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(root / name, name)
    zip_bytes = zip_path.read_bytes()
    requirements = root / "requirements.txt"
    release = {
        "format": FORMAT,
        "product": PRODUCT,
        "version": version,
        "zip": {"name": zip_path.name, "sha256": hashlib.sha256(zip_bytes).hexdigest(), "size": len(zip_bytes)},
        "files": entries,
        "requirements_sha256": hashlib.sha256(requirements.read_bytes() if requirements.exists() else b"").hexdigest(),
    }
    data = (json.dumps(release, indent=1) + "\n").encode("utf-8")
    key = load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("the signing key is not an Ed25519 key")
    json_path, sig_path = out / "release.json", out / "release.json.sig"
    json_path.write_bytes(data)
    sig_path.write_bytes(key.sign(data))
    return zip_path, json_path, sig_path


def _installed_version(root: Path) -> str:
    match = _VERSION_LINE.search((root / VERSION_FILE).read_bytes())
    if match is None:
        raise ValueError("no version in focus_guard/version.py")
    return match.group().decode().split('"')[1]


def _key_matches(key_path: Path, public_key: bytes) -> bool:
    """A release signed with another key would be refused, for good, by every install."""
    try:
        key = load_pem_private_key(key_path.read_bytes(), password=None)
    except (OSError, ValueError):
        return False
    if not isinstance(key, Ed25519PrivateKey):
        return False
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) == public_key


def _refusal(root: Path, version: str, run: Runner, key_path: Path, public_key: bytes) -> str | None:
    try:
        if parse_version(version) <= parse_version(_installed_version(root)):
            return f"{version} is not newer than {_installed_version(root)}"
    except ValueError as error:
        return str(error)
    if not _key_matches(key_path, public_key):
        return f"the signing key {key_path} does not match update_trust.PUBLIC_KEY"
    if run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root).strip() != "main":
        return "releases are made from main only"
    if run(["git", "status", "--porcelain"], root).strip():
        return "the tree has uncommitted changes"
    return None


def _build_with_version(
    root: Path, version: str, key_path: Path, files: list[str], public_key: bytes
) -> tuple[Path, Path, Path]:
    """Set the version and build the signed release, checked as an install would check it. On any failure the two
    version files are put back, so a failed run leaves the tree clean."""
    originals = {name: (root / name).read_bytes() for name in (VERSION_FILE, MANIFEST_FILE)}
    try:
        set_version(root, version)
        assets = build_release(root, version, key_path, root / "dist" / f"release-{version}", files)
        verify_release(assets[1].read_bytes(), assets[2].read_bytes(), _previous(originals), public_key)
        return assets
    except BaseException:
        for name, data in originals.items():
            (root / name).write_bytes(data)
        raise


def _previous(originals: dict[str, bytes]) -> str:
    match = _VERSION_LINE.search(originals[VERSION_FILE])
    if match is None:
        raise ValueError("no version in focus_guard/version.py")
    return match.group().decode().split('"')[1]


def publish(
    root: Path, version: str, key_path: Path, run: Runner, out: Callable[[str], None], public_key: bytes
) -> None:
    files = release_files(root, run)  # before any change: an unsafe tracked name stops the release here
    assets = _build_with_version(root, version, key_path, files, public_key)
    run(["git", "commit", "-am", f"chore: release {version}"], root)
    run(["git", "push"], root)
    title = f"Workmode {version}"
    run(["gh", "release", "create", f"v{version}", *map(str, assets), "--title", title, "--notes", title], root)
    out(f"Published v{version}.")


def main(
    argv: list[str] | None = None,
    run: Runner = _run,
    confirm: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
    root: Path = ROOT,
    key_path: Path = DEFAULT_KEY,
    public_key: bytes = PUBLIC_KEY,
) -> int:
    parser = argparse.ArgumentParser(prog="tools/release.py")
    parser.add_argument("version", nargs="?", help="the new version, for example 1.3.0")
    parser.add_argument("--new-key", action="store_true", help="make the signing key (once, outside the repo)")
    args = parser.parse_args(argv)
    if args.new_key:
        public = new_key(key_path)
        out(f"Private key: {key_path} (back it up offline; never commit it)")
        out(f'PUBLIC_KEY = bytes.fromhex("{public.hex()}")  # put this line in focus_guard/update_trust.py')
        return 0
    if not args.version:
        parser.error("give the new version, or --new-key")
    problem = _refusal(root, args.version, run, key_path, public_key)
    if problem is not None:
        out(f"Not published: {problem}.")
        return 1
    question = f"Set version {args.version}, commit, push and publish the signed GitHub release v{args.version}? [y/N] "
    if confirm(question).strip().lower() != "y":
        out("Nothing changed.")
        return 1
    try:
        publish(root, args.version, key_path, run, out, public_key)
    except (ValueError, OSError) as error:  # before the commit nothing changed (the version files were put back)
        out(f"Not published: {error}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
