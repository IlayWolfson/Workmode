"""Build dist/Hyperbolic-Time-Chamber.zip: the tool, the user's config and the video, ready for another PC."""

import json
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

SKIP_DIRS = {".git", "state", "dist", ".superpowers", "__pycache__", "media", ".mypy_cache", ".ruff_cache"}
SKIP_SUFFIXES = {".pyc"}
# Private notes stay on this PC; the package carries the user's config, never these.
SKIP_FILES = {
    "docs/manual-test.md",
    "docs/HANDOFF.md",
    "docs/song-candidates.md",
    "docs/google-calendar-setup.md",
    "leakscan.local.txt",
}
SKIP_PREFIXES = ("docs/superpowers/plans/", "docs/argon-")


def package_files(root: str | Path) -> Iterator[Path]:
    root = Path(root)
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        name = relative.as_posix()
        if not path.is_file() or set(relative.parts[:-1]) & SKIP_DIRS or path.suffix in SKIP_SUFFIXES:
            continue
        if name in SKIP_FILES or name.startswith(SKIP_PREFIXES):
            continue
        yield path


def host_config(data: dict, vm_name: str) -> dict:
    """The config for the PC that hosts the Hyper-V machine: same settings, apps suited to the host."""
    result = json.loads(json.dumps(data))
    result["allowed_apps"] = [
        {
            "process": "chrome.exe",
            "launch": [
                "C:/Program Files/Google/Chrome/Application/chrome.exe",
                "--profile-directory=Default",
                "--restore-last-session",
            ],
        },
        {"process": "WindowsTerminal.exe", "launch": ["wt.exe"]},
        {"process": "vmconnect.exe", "launch": ["C:/Windows/System32/vmconnect.exe", "localhost", vm_name]},
        {"process": "mmc.exe", "launch": ["C:/Windows/System32/mmc.exe", "virtmgmt.msc"]},
    ]
    return result


def build(root: str | Path, vm_name: str = "Virtual Windows For Testing") -> Path:
    root = Path(root)
    target = root / "dist" / "Hyperbolic-Time-Chamber.zip"
    target.parent.mkdir(exist_ok=True)
    video = Path(json.loads((root / "config.json").read_text(encoding="utf-8"))["video"]["path"])
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        base = json.loads((root / "config.json").read_text(encoding="utf-8"))
        for path in package_files(root):
            name = "Hyperbolic-Time-Chamber/" + path.relative_to(root).as_posix()
            if path.relative_to(root).as_posix() == "config.json":
                text = json.dumps(host_config(base, vm_name), ensure_ascii=False, indent=2)
                archive.writestr(name, text + chr(10))
            else:
                archive.write(path, name)
        if video.is_file():
            archive.write(video, f"Hyperbolic-Time-Chamber/media/{video.name}")
    return target


if __name__ == "__main__":
    print(build(Path(__file__).resolve().parent.parent))
    sys.exit(0)
