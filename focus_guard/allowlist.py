"""Pure allow-list rules. No Windows calls and no I/O."""

from collections.abc import Iterable
from urllib.parse import urlparse

SPECIAL_PREFIXES = ("chrome:", "about:", "chrome-extension:", "file:", "edge:", "devtools:")


def _site_matches(clean: str, site: str) -> bool:
    if site.startswith("*") and site.endswith("*"):  # "*word*": any host containing the word
        return site[1:-1] in clean
    return clean == site or clean.endswith("." + site)


def host_allowed(host: str, sites: Iterable[str]) -> bool:
    clean = host.strip().lower().rstrip(".")
    return bool(clean) and any(_site_matches(clean, site) for site in sites)


def url_allowed(url: str, sites: Iterable[str]) -> bool:
    text = url.strip().lower()
    if text.startswith(SPECIAL_PREFIXES):
        return True
    parts = urlparse(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    return host_allowed(parts.hostname, sites)
