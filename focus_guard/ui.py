"""UI windows as pywebview HTML pages (right-to-left safe).

Run as a subprocess: python -m focus_guard.ui <popup|phrase|video|summary|note|notify|error> [options].
The HTML builders are pure and unit-tested; the windows are verified by hand.
"""

import argparse
import html
import io
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from string import Template
from typing import Any

from .notify import corner_position, window_args

MAX_TYPED = 200  # characters; keeps the text written to the guard far below the pipe buffer

BASE_CSS = (
    "html,body{margin:0;height:100%;background:#16181d;color:#fff;font-family:'Segoe UI',system-ui,sans-serif}"
    ".box{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;"
    "text-align:center;padding:0 24px;box-sizing:border-box}"
    "h1{font-size:26px;margin:0;line-height:1.3}.soft{color:#9aa1ae;font-size:13px}"
    "button{font-size:16px;padding:8px 22px;border-radius:8px;border:0;cursor:pointer}"
    "input{font-size:18px;width:90%;padding:8px;border-radius:8px;border:1px solid #444;background:#0f1115;color:#fff}"
)

POPUP_TPL = Template(
    """<!doctype html><html dir="rtl" lang="he"><meta charset="utf-8"><style>$css</style>
<div class="box"><h1>$text</h1><div class="soft" id="c">$seconds</div>
<button onclick="pywebview.api.close()">$button</button><div class="soft" dir="auto">$hint</div></div>
<script>var n=$seconds;setInterval(function(){n=Math.max(0,n-1);document.getElementById('c').textContent=n;},1000);</script></html>"""
)

PHRASE_TPL = Template(
    """<!doctype html><html dir="rtl" lang="he"><meta charset="utf-8"><style>$css</style>
<div class="box"><div>$prompt</div><input id="t" dir="auto" autocomplete="off" maxlength="$maxlen"><button onclick="go()">OK</button></div>
<script>function go(){pywebview.api.submit(document.getElementById('t').value);}
document.getElementById('t').addEventListener('keydown',function(e){if(e.key==='Enter'){go();}});
window.addEventListener('pywebviewready',function(){document.getElementById('t').focus();});</script></html>"""
)

NOTE_TPL = Template(
    """<!doctype html><html lang="he"><meta charset="utf-8"><style>$css</style>
<div class="box"><div dir="auto">$text</div></div></html>"""
)

ERROR_TPL = Template(
    """<!doctype html><html dir="rtl" lang="he"><meta charset="utf-8"><style>$css</style>
<div class="box"><div dir="auto">$text</div><button onclick="pywebview.api.close()">סגירה</button></div></html>"""
)

WEB = Path(__file__).resolve().parent / "web"
NOTIFY_SIZE = (380, 190)
NOTIFY_TITLE = "Focus Guard Notice"  # distinct from the main window's title, so scripts can find each
NOTIFY_ANSWERS = ("start", "decline", "nerd")

VIDEO_TPL = Template(
    """<!doctype html><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:#000}
video{width:100%;height:100%;object-fit:contain}
.hint{position:fixed;left:0;right:0;bottom:14px;text-align:center;color:#fff;font:16px 'Segoe UI',sans-serif;opacity:.85;text-shadow:0 0 6px #000}</style>
<video src="$src" autoplay loop></video><div class="hint" dir="auto">$hint</div>"""
)


def popup_html(text: str, seconds: int | str, hint: str, button: str) -> str:
    return POPUP_TPL.substitute(
        css=BASE_CSS, text=html.escape(text), seconds=int(seconds), button=html.escape(button), hint=html.escape(hint)
    )


def note_html(text: str) -> str:
    return NOTE_TPL.substitute(css=BASE_CSS, text=html.escape(text))


def error_html(text: str) -> str:
    return ERROR_TPL.substitute(css=BASE_CSS, text=html.escape(text))


def phrase_html(prompt: str) -> str:
    return PHRASE_TPL.substitute(css=BASE_CSS, prompt=html.escape(prompt), maxlen=MAX_TYPED)


def video_source(media: str) -> tuple[str, str]:
    if media.lower().startswith(("http://", "https://")):
        return "url", media
    return "file", Path(media).resolve().as_uri()


def page_url(path: str | Path) -> str:
    return Path(path).resolve().as_uri()


def video_html(src: str, hint: str) -> str:
    return VIDEO_TPL.substitute(src=html.escape(src, quote=True), hint=html.escape(hint))


class _Api:
    """Exposed to the page. Only public methods; state stays private so pywebview does not walk the window."""

    def __init__(self) -> None:
        self._window: Any = None  # a pywebview Window, set once it exists
        self._result = ""

    def close(self) -> None:
        self._window.destroy()

    def submit(self, text: object) -> None:
        self._result = text[:MAX_TYPED] if isinstance(text, str) else ""
        self._window.destroy()


def _show(
    *,
    html_text: str | None = None,
    url: str | None = None,
    width: int = 640,
    height: int = 300,
    frameless: bool = True,
    fullscreen: bool = False,
    seconds: float | None = None,
    focus: bool = True,
) -> str:
    import webview

    api = _Api()
    api._window = webview.create_window(
        "Focus Guard Alert",
        url=url,
        html=html_text,
        js_api=api,
        width=width,
        height=height,
        frameless=frameless,
        on_top=True,
        fullscreen=fullscreen,
        focus=focus,
    )
    if seconds:
        timer = threading.Timer(seconds, api._window.destroy)
        timer.daemon = True
        timer.start()
    webview.start()
    return api._result


class _NotifyApi:
    """The notification page reports each step on stdout, one line: nerd, then start or decline."""

    def __init__(self, make_args: Callable[[], dict]) -> None:
        self._make_args = make_args
        self._window: Any = None

    def args(self) -> dict:
        return self._make_args()  # computed when the page asks, so its timers start from the right moment

    def choose(self, choice: object) -> None:
        if choice not in NOTIFY_ANSWERS:
            return
        sys.stdout.write(f"{choice}\n")
        sys.stdout.flush()
        if choice != "nerd":
            self._window.destroy()


def _work_area() -> tuple[int, int, int, int]:
    import win32api

    monitor = win32api.MonitorFromPoint((0, 0))
    left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Work"]
    return left, top, right, bottom


def run_notify(kind: str, title: str, start: float, end: float) -> None:
    import webview

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    width, height = NOTIFY_SIZE
    x, y = corner_position(_work_area(), width, height)
    api = _NotifyApi(lambda: window_args(kind, title, start, end, time.time()))
    api._window = webview.create_window(
        NOTIFY_TITLE,
        url=page_url(WEB / "notify.html"),
        js_api=api,
        width=width,
        height=height,
        x=x,
        y=y,
        frameless=True,
        on_top=True,
        focus=False,
    )
    timer = threading.Timer(max(1.0, end - time.time()), api._window.destroy)
    timer.daemon = True
    timer.start()
    previous = _foreground()
    api._window.events.shown += lambda: _give_focus_back(previous)
    webview.start()


def _foreground() -> int:
    import win32gui

    return int(win32gui.GetForegroundWindow())


def _give_focus_back(hwnd: int) -> None:
    """pywebview focuses the page after showing it even with focus=False; typing elsewhere must not stop."""
    import win32gui

    time.sleep(0.3)  # let pywebview's own Focus() call happen first
    try:
        if hwnd and win32gui.IsWindow(hwnd):
            win32gui.SetForegroundWindow(hwnd)
    except Exception:  # Windows may refuse; the window still works, it just keeps the focus
        pass


def run_video(media: str, seconds: int, hint: str) -> None:
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"
    kind, value = video_source(media)
    if kind == "url":
        _show(url=value, fullscreen=True, frameless=False, seconds=seconds)
        return
    page = Path(tempfile.gettempdir()) / "focus_guard_video.html"
    page.write_text(video_html(value, hint), encoding="utf-8")
    _show(url=page_url(page), fullscreen=True, frameless=False, seconds=seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="focus_guard.ui")
    modes = parser.add_subparsers(dest="mode", required=True)
    popup = modes.add_parser("popup")
    popup.add_argument("--text", required=True)
    popup.add_argument("--seconds", type=int, default=10)
    popup.add_argument("--hint", default="")
    popup.add_argument("--button", default="OK")
    phrase = modes.add_parser("phrase")
    phrase.add_argument("--prompt", default="")
    video = modes.add_parser("video")
    video.add_argument("--media", required=True)
    video.add_argument("--seconds", type=int, default=20)
    video.add_argument("--hint", default="")
    summary = modes.add_parser("summary")
    summary.add_argument("--text", required=True)
    summary.add_argument("--seconds", type=int, default=20)
    note = modes.add_parser("note")
    note.add_argument("--text", required=True)
    note.add_argument("--seconds", type=int, default=4)
    notify = modes.add_parser("notify")
    notify.add_argument("--kind", required=True, choices=["upcoming", "missed", "restart"])
    notify.add_argument("--title", default="")
    notify.add_argument("--start", type=float, required=True)
    notify.add_argument("--end", type=float, required=True)
    error = modes.add_parser("error")
    error.add_argument("--text", required=True)
    args = parser.parse_args(argv)

    if args.mode == "popup":
        _show(html_text=popup_html(args.text, args.seconds, args.hint, args.button), seconds=args.seconds, height=300)
    elif args.mode == "summary":
        _show(html_text=popup_html(args.text, args.seconds, "", "OK"), seconds=args.seconds, height=300)
    elif args.mode == "note":
        _show(html_text=note_html(args.text), seconds=args.seconds, width=360, height=90, focus=False)
    elif args.mode == "phrase":
        typed = _show(html_text=phrase_html(args.prompt), height=220)
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(typed)
        sys.stdout.flush()
    elif args.mode == "video":
        run_video(args.media, args.seconds, args.hint)
    elif args.mode == "notify":
        run_notify(args.kind, args.title, args.start, args.end)
    elif args.mode == "error":
        _show(html_text=error_html(args.text), width=440, height=200, focus=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
