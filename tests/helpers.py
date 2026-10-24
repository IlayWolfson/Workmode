"""Shared test helpers."""

import json
from pathlib import Path


def base_config(video_path):
    return {
        "allowed_apps": [
            {"process": "Code.exe", "launch": ["code", "C:/project"]},
            {"process": "chrome.exe", "launch": ["chrome"]},
        ],
        "allowed_sites": ["github.com", "docs.python.org"],
        "video": {"path": str(video_path), "min_seconds": 20},
        "emergency": {"phrase": "a long enough test phrase"},
        "server": {"port": 47653, "token": "0123456789abcdef0123456789abcdef"},
    }


def write_config(directory, data):
    path = Path(directory) / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path
