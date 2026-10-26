"""Signed test releases: a throwaway Ed25519 key per test run, zips and release.json built in memory."""

import hashlib
import io
import json
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from focus_guard.update_trust import Release, verify_release

KEY = Ed25519PrivateKey.generate()
PUBLIC = KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
OTHER_KEY = Ed25519PrivateKey.generate()

# A valid journal of an update that is replacing files right now.
UNFINISHED = {
    "phase": "swapped",
    "from": "1.2.2",
    "to": "1.3.0",
    "attempt": "a",
    "replaced": [],
    "added": [],
    "removed": [],
}
UNFINISHED_JSON = json.dumps(UNFINISHED)

FILES = {
    "focus_guard/app.py": b"print('new app')\n",
    "focus_guard/version.py": b'VERSION = "1.3.0"\n',
    "requirements.txt": b"psutil>=5.9\n",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def release_for(version: str = "1.3.0", files: dict[str, bytes] | None = None, zip_data: bytes | None = None) -> dict:
    files = FILES if files is None else files
    zip_data = zip_bytes(files) if zip_data is None else zip_data
    return {
        "format": 1,
        "product": "Workmode",
        "version": version,
        "zip": {"name": f"Workmode-{version}.zip", "sha256": sha(zip_data), "size": len(zip_data)},
        "files": [{"path": name, "sha256": sha(data), "size": len(data)} for name, data in files.items()],
        "requirements_sha256": sha(files.get("requirements.txt", b"")),
    }


def encode(release: dict) -> bytes:
    return json.dumps(release, indent=1).encode("utf-8")


def sign(data: bytes, key: Ed25519PrivateKey = KEY) -> bytes:
    return key.sign(data)


def trusted(release: dict, installed: str = "1.2.2") -> Release:
    """The Release the updater would get after checking the signature (signed with the test key)."""
    data = encode(release)
    return verify_release(data, sign(data), installed, public_key=PUBLIC)
