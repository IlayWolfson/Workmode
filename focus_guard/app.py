"""The background process: python -m focus_guard.app [--background].

One instance only (a second start shows the running one's window and exits). It keeps a tray icon, runs the
scheduler every second, and owns the main window (calendar, or the clock during a session). Closing the window
hides it. The Desktop shortcut starts it with the window shown; the Startup shortcut with --background.
"""

import argparse
import ctypes
import json
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import instance
from .appapi import AppApi
from .appupdate import UpdateService, recover_at_start, run_checks, start_update_bridge, write_ready
from .autostart import apply as apply_autostart
from .background import Background, SubprocessNotify
from .config import Config, load_config_safe, load_server
from .cueplayer import MciPlayer
from .launcher import spawn_module
from .leftovers import undo_all
from .paths import DEFAULT
from .procfiles import remove_pid, write_pid
from .scheduler import Scheduler
from .session import load_session
from .tray import run_tray
from .update_apply import QUIT_EVENT
from .update_check import UrllibHttp, check

TITLE = "Workmode"
APP_ID = "FocusGuard.App"
MUTEX = "Local\\FocusGuard.Background"
SHOW_EVENT = "Local\\FocusGuard.Show"
TICK_SECONDS = 1.0

WEB = Path(__file__).resolve().parent / "web"
SIZES = {"clock": (320, 240), "calendar": (1180, 780)}  # the calendar's size when the screen is unknown
MIN_SIZE = SIZES["clock"]
MIN_CALENDAR = (900, 600)
DEFAULT_PERCENT = 85
FILE_TYPES = {"song": ("Audio (*.mp3;*.wav)",), "video": ("Video (*.mp4;*.webm)",)}


def set_window_icon(title: str, icon_path: str | Path, wait: float = 10.0) -> None:
    import win32con
    import win32gui

    deadline = time.time() + wait
    hwnd = 0
    while not hwnd and time.time() < deadline:
        hwnd = win32gui.FindWindow(None, title)
        if not hwnd:
            time.sleep(0.25)
    if not hwnd:
        return
    for kind, size in ((win32con.ICON_BIG, 32), (win32con.ICON_SMALL, 16)):
        handle = win32gui.LoadImage(0, str(icon_path), win32con.IMAGE_ICON, size, size, win32con.LR_LOADFROMFILE)
        # pywin32 accepts the icon handle object here; its type stubs only list numbers
        win32gui.SendMessage(hwnd, win32con.WM_SETICON, kind, handle)  # type: ignore[arg-type]


def undo_leftovers() -> None:
    """No session is running, so nothing should still be waiting or muted (e.g. the PC restarted mid-session)."""
    if load_session(DEFAULT.session, time.time()) is None:
        undo_all(DEFAULT)


class ErrorLog:
    """state/app-error.log: each distinct error once, so a failing tick does not write every second."""

    def __init__(self, path: Path) -> None:
        self._path, self._last = path, ""

    def write(self, text: str) -> None:
        if text == self._last:
            return
        self._last = text
        try:
            with self._path.open("a", encoding="utf-8") as log:
                log.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}\n")
        except OSError:
            pass


def calendar_size(work: tuple[int, int] | None, scale: float, percent: int) -> tuple[int, int]:
    """The calendar window: `percent` of the screen's work area, in the logical pixels pywebview sizes windows in
    (work area / display scale), never below MIN_CALENDAR unless the screen itself is smaller."""
    if work is None:
        return SIZES["calendar"]
    width, height = (
        round(min(axis / scale, max(low, axis / scale * percent / 100)))
        for axis, low in zip(work, MIN_CALENDAR, strict=True)
    )
    return width, height


Rect = tuple[int, int, int, int]  # left, top, right, bottom


def screen_area() -> tuple[Rect | None, float]:
    """The primary screen's work area and display scale, measured in the same pixels: before pywebview makes the
    process DPI-aware both are virtualized (scale 1), after it both are physical."""
    try:
        from .ui import _work_area

        rect = _work_area()
        scale = ctypes.windll.user32.GetDpiForSystem() / 96
    except Exception:  # no monitor information: keep the planned size
        return None, 1.0
    return rect, scale or 1.0


def area_size(rect: Rect | None) -> tuple[int, int] | None:
    return (rect[2] - rect[0], rect[3] - rect[1]) if rect is not None else None


def centered(rect: Rect | None, scale: float, size: tuple[int, int]) -> tuple[int, int] | None:
    """Where a window of `size` (logical pixels) sits centered on the work area; None when the screen is unknown."""
    if rect is None:
        return None
    left, top, right, bottom = (value / scale for value in rect)
    return round(max(left, left + (right - left - size[0]) / 2)), round(max(top, top + (bottom - top - size[1]) / 2))


class ViewSizer:
    """Window size follows the page's view, but only while the window is shown: pywebview's resize() makes a
    hidden window visible, which would open it at login."""

    def __init__(
        self, resize: Callable[[int, int], None], visible: bool, sizes: dict[str, tuple[int, int]] | None = None
    ) -> None:
        self._resize, self._visible, self._view = resize, visible, "calendar"
        self._sizes = sizes or SIZES

    def set_view(self, view: str) -> None:
        self._view = view
        if self._visible:
            self._resize(*self._sizes[view])

    def shown(self) -> None:
        self._visible = True
        self._resize(*self._sizes[self._view])

    def hidden(self) -> None:
        self._visible = False


def run_loop(tick: Callable[[], None], stop: threading.Event, log: ErrorLog) -> None:
    """The scheduler heartbeat: a failing tick is logged and the loop goes on."""
    while not stop.wait(TICK_SECONDS):
        try:
            tick()
        except Exception:
            log.write(traceback.format_exc())


def _run(background: bool) -> int:
    log = ErrorLog(DEFAULT.app_error_log)
    DEFAULT.state.mkdir(exist_ok=True)
    write_pid(DEFAULT.app_pid)
    try:
        for step in (undo_leftovers, _sync_autostart):
            try:
                step()
            except Exception:  # the window must still open; the next start tries again
                log.write(traceback.format_exc())
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        _serve(background, log)
    except Exception:
        log.write(traceback.format_exc())
        return 1
    finally:
        remove_pid(DEFAULT.app_pid)
        DEFAULT.app_ready.unlink(missing_ok=True)
    return 0


def _sync_autostart() -> None:
    cfg, _ = load_config_safe(DEFAULT.config, DEFAULT.config_last_good)
    apply_autostart(DEFAULT, cfg.start_with_windows if cfg is not None else True)


def _serve(background: bool, log: ErrorLog) -> None:
    import webview

    stop, quitting = threading.Event(), threading.Event()

    def spawn(module: str) -> None:
        spawn_module(module, DEFAULT.root)

    player = MciPlayer(on_error=log.write)
    worker = Background(DEFAULT, Scheduler(), SubprocessNotify(), player, spawn)
    windows: list[Any] = []  # filled once the window exists

    def resize(width: int, height: int) -> None:
        if windows:
            windows[0].resize(width, height)

    cfg, _ = load_config_safe(DEFAULT.config, DEFAULT.config_last_good)
    rect, scale = screen_area()
    sizes = {**SIZES, "calendar": calendar_size(area_size(rect), scale, cfg.window_percent if cfg else DEFAULT_PERCENT)}
    where = centered(rect, scale, sizes["calendar"])
    sizer = ViewSizer(resize, visible=not background, sizes=sizes)

    def show(calendar: bool = False) -> None:
        window = windows[0]
        window.show()
        window.restore()
        sizer.shown()
        if calendar:
            window.evaluate_js("openCalendar()")

    def closing() -> bool:
        if quitting.is_set():
            return True
        sizer.hidden()
        windows[0].hide()  # the tool keeps running in the tray; closing the window is free
        return False

    def quit_all() -> None:
        quitting.set()
        stop.set()
        windows[0].destroy()

    def choose(kind: str) -> str:
        picked = windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=FILE_TYPES[kind])
        return str(picked[0]) if picked else ""

    api = AppApi(set_view=sizer.set_view, lock=worker.lock, play=player.play_clip, choose=choose)
    width, height = sizes["calendar"]
    url = (WEB / "main.html").as_uri()
    window = webview.create_window(
        TITLE,
        url=url,
        js_api=api,
        width=width,
        height=height,
        min_size=MIN_SIZE,
        hidden=background,
        x=where[0] if where else None,
        y=where[1] if where else None,
    )
    if window is None:
        raise RuntimeError("pywebview did not create the window")
    window.events.closing += closing
    watch_drops(window, api)
    windows.append(window)
    threading.Thread(target=run_loop, args=(worker.tick, stop, log), daemon=True).start()
    threading.Thread(target=instance.wait_show, args=(SHOW_EVENT, show, stop), daemon=True).start()
    threading.Thread(target=instance.wait_show, args=(QUIT_EVENT, quit_all, stop), daemon=True).start()
    bridge = _start_updates(_bridge_settings(cfg, DEFAULT.config), stop, log)
    tray = run_tray(show, lambda: show(calendar=True), quit_all, DEFAULT.icon)

    def started() -> None:
        try:
            write_ready(DEFAULT, os.getpid(), os.environ)  # tells a waiting updater the new version is up
        except OSError:
            log.write(traceback.format_exc())
        if DEFAULT.icon.exists():
            set_window_icon(TITLE, DEFAULT.icon)

    try:
        webview.start(started)
    finally:
        stop.set()
        tray.stop()
        if bridge is not None:
            bridge.shutdown()
            bridge.server_close()


def _bridge_settings(cfg: Config | None, config_path: Path) -> tuple[int, str] | None:
    """The bridge port and token: the loaded config's, else config.json's own server section (or None)."""
    if cfg is not None:
        return cfg.server_port, cfg.server_token
    return load_server(config_path)


def _start_updates(server: tuple[int, str] | None, stop: threading.Event, log: ErrorLog) -> Any:
    """The daily update check and the update bridge on the bridge port + 1 (None when it could not start).

    The bridge needs only the port and token, so it also runs while another part of config.json is invalid.
    """
    service = UpdateService(
        DEFAULT,
        lambda: spawn_module("focus_guard.update", DEFAULT.root, ("--apply",)),
        spawn_recover=lambda: spawn_module("focus_guard.update", DEFAULT.root, ("--recover",)),
    )
    http = UrllibHttp()

    def check_once() -> None:
        service.status()  # also undoes an update whose updater was killed, when Chrome is not asking
        check(DEFAULT, http, time.time())

    threading.Thread(target=run_checks, args=(check_once, stop, log.write), daemon=True).start()
    if server is None:
        return None
    port, token = server
    return start_update_bridge(port + 1, token, service, log.write)


def on_drop(api: Any, evaluate: Callable[[str], object], event: dict) -> None:
    """A file dropped on the allow-list box: add it, then let the panel draw the answer."""
    files = event.get("dataTransfer", {}).get("files", [])
    path = files[0].get("pywebviewFullPath") if files else None
    if not path:
        return
    result = api.allowed_add_file(path)
    evaluate("FG.allowed.refresh(" + json.dumps(result, ensure_ascii=False) + ")")


def on_video_drop(evaluate: Callable[[str], object], event: dict) -> None:
    """A file dropped on the settings' video box joins the list there (settings.js checks it is a video)."""
    files = event.get("dataTransfer", {}).get("files", [])
    path = files[0].get("pywebviewFullPath") if files else None
    if path:
        evaluate("FG.settings.droppedVideo(" + json.dumps(path, ensure_ascii=False) + ")")


def watch_drops(window: Any, api: Any) -> None:
    """pywebview gives a dropped file's full path only to Python handlers, so the drop box is wired from here."""
    from webview.dom import DOMEventHandler

    def wire(selector: str, handler: Callable[[dict], None]) -> None:
        box = window.dom.get_element(selector)
        if box is None:
            return
        box.events.dragover += DOMEventHandler(lambda event: None, prevent_default=True)
        box.events.drop += DOMEventHandler(handler, prevent_default=True, stop_propagation=True)

    def loaded() -> None:
        wire("#alDrop", lambda event: on_drop(api, window.evaluate_js, event))
        wire("#setVideoDrop", lambda event: on_video_drop(window.evaluate_js, event))

    window.events.loaded += loaded


def main(
    argv: list[str] | None = None,
    claim: Callable[[str], Any | None] = instance.claim,
    signal_show: Callable[[str], None] = instance.signal_show,
    recover: Callable[[], bool] | None = None,
    restart: Callable[[], None] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="focus_guard.app")
    parser.add_argument("--background", action="store_true", help="start hidden, in the tray (used at login)")
    args = parser.parse_args(argv)
    handle = claim(MUTEX)
    if handle is None:  # already running: bring its window up instead (and never touch the files under it)
        signal_show(SHOW_EVENT)
        return 0
    try:
        undone = recover() if recover else recover_at_start(DEFAULT, claim, instance.release)
        if not undone:
            return _run(args.background)
    finally:
        instance.release(handle)
    # an interrupted update was undone after this process loaded the new code: start the old code, now that the
    # new process can claim the app's mutex
    (restart or (lambda: spawn_module("focus_guard.app", DEFAULT.root, ("--background",))))()
    return 0


if __name__ == "__main__":
    sys.exit(main())
