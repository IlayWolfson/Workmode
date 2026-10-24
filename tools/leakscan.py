"""Find what git would publish that should stay private: python tools/leakscan.py [--history]

It only reports, never changes anything. Kinds: secret (the emergency phrase, the bridge token, key-shaped strings;
never printed in full), personal (git name and email, a Windows user folder, every line of the gitignored
leakscan.local.txt), private-note (files kept local by the user's rule) and stray (local-only files that are tracked).
Exit code 1 when anything is found.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_TERMS = ROOT / "leakscan.local.txt"
KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{36}|sk-[A-Za-z0-9_-]{20,}|GOCSPX-[A-Za-z0-9_-]{10,}")
USER_DIR_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'`<>]+)", re.IGNORECASE)
NOT_A_USER = {"public", "default", "all users", "default user"}
PRIVATE_NOTES = (re.compile(r"^\.superpowers/"), re.compile(r"(^|/)argon-[^/]*$"), re.compile(r"ledger", re.I))
PRIVATE_FILES = {"docs/HANDOFF.md"}  # notes about the user and how they work
STRAY = (
    re.compile(r"^config\.json$"),
    re.compile(r"^state/"),
    re.compile(r"^dist/"),
    re.compile(r"^media/"),
    re.compile(r"^extension/config\.js$"),
    re.compile(r"daily-tech-digest"),  # another project's documents
)


@dataclass(frozen=True)
class Terms:
    secrets: tuple[str, ...] = ()
    personal: tuple[str, ...] = ()  # matched case-insensitively


@dataclass(frozen=True)
class Hit:
    where: str  # a path, or "<commit>:<path>" for history
    line: int  # 0 for a whole file
    kind: str
    shown: str


def mask(value: str) -> str:
    return value[:2] + "…"


def scan_text(where: str, text: str, terms: Terms) -> list[Hit]:
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        secret = next((term for term in terms.secrets if term and term in line), None)
        found = KEY_RE.search(line)
        if secret or found:
            hits.append(Hit(where, number, "secret", mask(secret or (found.group(0) if found else ""))))
        users = [match.group(1) for match in USER_DIR_RE.finditer(line) if match.group(1).lower() not in NOT_A_USER]
        named = next((term for term in terms.personal if term and term.lower() in lowered), None)
        if users or named:
            hits.append(Hit(where, number, "personal", named or users[0]))
    return hits


def scan_paths(paths: Sequence[str]) -> list[Hit]:
    hits = []
    for path in paths:
        clean = path.replace("\\", "/")
        if clean in PRIVATE_FILES or any(rule.search(clean) for rule in PRIVATE_NOTES):
            hits.append(Hit(clean, 0, "private-note", clean))
        elif any(rule.search(clean) for rule in STRAY):
            hits.append(Hit(clean, 0, "stray", clean))
    return hits


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout


def load_terms() -> Terms:
    """The phrase and token from the local files (kept in memory only), git's name and email, and local extra terms."""
    secrets: list[str] = []
    try:
        data = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        secrets += [data.get("emergency", {}).get("phrase", ""), data.get("server", {}).get("token", "")]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        secrets += re.findall(r"token:\s*'([^']+)'", (ROOT / "extension" / "config.js").read_text(encoding="utf-8"))
    except OSError:
        pass
    personal = [_git("config", "user.name").strip(), _git("config", "user.email").strip()]
    if LOCAL_TERMS.exists():
        personal += [line.strip() for line in LOCAL_TERMS.read_text(encoding="utf-8").splitlines() if line.strip()]
    keep = [term for term in secrets if len(term) >= 8 and not term.startswith("CHANGE-ME")]
    return Terms(tuple(dict.fromkeys(keep)), tuple(dict.fromkeys(term for term in personal if term)))


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None  # binary or unreadable: only its path is checked


def scan_tracked(terms: Terms) -> list[Hit]:
    paths = [line for line in _git("ls-files").splitlines() if line]
    hits = scan_paths(paths)
    for path in paths:
        text = _read(ROOT / path)
        if text is not None:
            hits += scan_text(path, text, terms)
    return hits


def scan_history(terms: Terms) -> list[Hit]:
    seen: set[str] = set()
    hits: list[Hit] = []
    for line in _git("rev-list", "--all", "--objects").splitlines():
        blob, _, path = line.partition(" ")
        if not path or blob in seen or _git("cat-file", "-t", blob).strip() != "blob":
            continue
        seen.add(blob)
        hits += [Hit(f"{blob[:7]}:{hit.where}", 0, hit.kind, hit.shown) for hit in scan_paths([path])]
        raw = subprocess.run(["git", "cat-file", "-p", blob], cwd=ROOT, capture_output=True, check=False).stdout
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        hits += scan_text(f"{blob[:7]}:{path}", text, terms)
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leakscan")
    parser.add_argument("--history", action="store_true", help="also scan every file version in the git history")
    args = parser.parse_args(argv)
    terms = load_terms()
    hits = scan_history(terms) if args.history else scan_tracked(terms)
    for hit in hits:
        print(f"{hit.kind:13} {hit.where}:{hit.line}  {hit.shown}")
    counts = Counter(hit.kind for hit in hits)
    print("found: " + (", ".join(f"{kind} {count}" for kind, count in sorted(counts.items())) or "nothing"))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
