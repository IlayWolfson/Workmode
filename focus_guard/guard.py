"""The enforcement loop. Windows, UI and keyboard access are injected so the logic is testable."""

import queue
import random
import time
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path

from .attempts import AttemptLog
from .config import VIDEO_SUFFIXES, Config
from .emergency import EmergencyDetector, phrase_matches
from .leftovers import restore_mutes, restore_windows
from .muting import MuteStore
from .ports import AlertUi, AudioControl, KeyState, RoastSource, WindowActions, WindowSource
from .session import Session
from .songs import library
from .waiting import WaitingStore, WaitingWindow
from .watcher import Event, Watcher, WinInfo

LAUNCH_LIMIT = 3  # relaunches per app per minute
LAUNCH_WINDOW = 60.0
NOTE_SECONDS = 4  # how long the "is waiting" note stays up
NOTE_GAP = 10.0  # at most one note per program in this many seconds
NEVER_MUTED = frozenset({"python.exe", "pythonw.exe", "msedgewebview2.exe"})  # the tool's own processes
EXTERNAL_KINDS = frozenset({"tab_closed", "blocked_site"})
SUMMARY_TEXT = "הסשן הסתיים. כל הכבוד."


class Guard:
    def __init__(
        self,
        cfg: Config,
        session: Session,
        windows: WindowSource,
        actions: WindowActions,
        ui: AlertUi,
        keys: KeyState,
        log: AttemptLog,
        roasts: RoastSource,
        *,
        waiting: WaitingStore,
        audio: AudioControl,
        mutes: MuteStore,
        mute_requested: Callable[[], bool],
        exit_requested: Callable[[], bool] = lambda: False,
        clear_exit_request: Callable[[], None] = lambda: None,
        clock: Callable[[], float] = time.time,
        dry_run: bool = False,
        videos_dir: Path | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._cfg, self._session = cfg, session
        self._videos_dir = videos_dir or Path(__file__).resolve().parent.parent / "assets" / "videos"
        self._rng = rng or random.Random()
        self._windows, self._actions, self._ui, self._keys = windows, actions, ui, keys
        self._log, self._roasts, self._clock, self._dry = log, roasts, clock, dry_run
        self._waiting, self._audio, self._mutes, self._mute_requested = waiting, audio, mutes, mute_requested
        self._exit_requested, self._clear_exit_request = exit_requested, clear_exit_request
        self._mute_failed = False
        self._ended = False
        self._muting = bool(mutes.load())  # a restarted guard still undoes a mute withdrawn while it was down
        self._apps = {app.process: app for app in cfg.allowed_apps}
        grace = session.grace if session.grace is not None else cfg.grace_seconds
        grace_until = session.start + grace
        self._watcher = Watcher(frozenset(self._apps), cfg.protected_processes, grace_until=grace_until)
        self._minimize_failed: set[int] = set()  # hwnds whose minimize trouble is already logged
        self._waiting_pids = {hwnd: window.pid for hwnd, window in waiting.load().items()}  # survives a restart
        self._last_note: dict[str, float] = {}  # lower-case program name -> time of its last waiting note
        chords = set(cfg.hold_chords) | set(cfg.hotkey_chords)
        self._vks = frozenset(vk for chord in chords for vk in chord)
        self._detector = EmergencyDetector(cfg.hold_chords, cfg.hold_ms, cfg.hotkey_chords)
        self._external: queue.Queue[tuple[str, str]] = queue.Queue()
        self._launches: dict[str, deque[float]] = {}
        self._asking = False
        self._stopped = False

    def push_external(self, kind: str, detail: str) -> None:
        self._external.put((kind, detail))

    def run(
        self,
        sleep: Callable[[float], None] = time.sleep,
        interval: float = 0.25,
        on_tick: Callable[[], object] | None = None,
    ) -> None:
        self._note("session_start", "", self._clock())
        while True:
            try:
                keep_going = self.tick()
                if keep_going and on_tick:
                    on_tick()
            except Exception as error:
                self._log.record("error", repr(error), self._clock())
                keep_going = True
            if not keep_going:
                return
            sleep(interval)

    def tick(self) -> bool:
        now = self._clock()
        if self._ended:
            return False
        if self._stopped or self._session.finished(now):
            return self._finish(now)
        self._check_emergency(now)  # first, so a failing window listing cannot disable the exit
        windows = self._windows.list_windows(self._windows.own_pids())
        events = self._watcher.step(windows, now, getattr(self._windows, "exists", None))
        for event in events:
            self._handle_safely(event, now)
        if not self._dry:
            self._keep_waiting(windows, {event.hwnd for event in events}, now)
            self._apply_mutes(now)
        self._drain_external(now)
        return True

    def _handle_safely(self, event: Event, now: float) -> None:
        try:
            self._handle(event, now)
        except Exception as error:  # one failing action must not drop the rest of the tick's events
            self._log.record("error", f"{event.kind} {event.process}: {error!r}"[:80], now)

    def _act(self, action: Callable[[], object]) -> object:
        return None if self._dry else action()

    def _note(self, kind: str, detail: str, now: float) -> None:
        self._log.record(kind, f"dry-run: {detail}" if self._dry else detail, now)

    def _roast(self) -> None:
        self._act(lambda: self._ui.show_popup(self._roasts.next(), self._cfg.popup_seconds))

    def _video(self) -> None:
        # Ticked videos, else the user's own single file (older setting), else the bundled ones, else the address.
        configured = self._cfg.videos or ((self._cfg.video_path,) if self._cfg.video_path else ())
        choices = library(self._videos_dir, configured, VIDEO_SUFFIXES)
        media = str(self._rng.choice(choices)) if choices else self._cfg.video_path or self._cfg.video_fallback_url
        self._act(lambda: self._ui.show_video(media, self._cfg.video_min_seconds))

    def _handle(self, event: Event, now: float) -> None:
        if event.kind == "blocked_app":
            self._note("blocked_app", event.process, now)
            if not self._dry and self._start_waiting(event.hwnd, event.pid, event.process, now):
                if event.state != "minimized":  # back from the tray, or reopened while the guard restarted
                    self._waiting_note(event.process, now)
        elif event.kind == "blocked_reopened":
            self._note("blocked_app", event.process, now)
            if not self._dry:
                self._minimize(event.hwnd, now)
                self._waiting_note(event.process, now)
        elif event.kind == "closed":
            self._note("closed", event.process, now)
            self._roast()
            if event.others == 0:
                self._relaunch(event.process, now)
        elif event.kind in ("minimized", "resized"):
            self._note(event.kind, event.process, now)
            self._act(lambda: self._actions.restore(event.hwnd, event.state))
            self._video()

    def _start_waiting(self, hwnd: int, pid: int, process: str, now: float) -> bool:
        """Remember where the window was (the store keeps the first placement), then minimize it.

        Returns True when the same window was already waiting."""
        known = self._waiting_pids.get(hwnd)
        if known is not None and known != pid:  # Windows reused the handle for another program
            self._stop_waiting(hwnd)
            known = None
        placement = self._actions.placement(hwnd)
        if placement is not None:
            self._waiting.add(WaitingWindow(hwnd, pid, process, placement))
        self._waiting_pids[hwnd] = pid
        self._minimize(hwnd, now)
        return known is not None

    def _stop_waiting(self, hwnd: int) -> None:
        self._waiting.remove(hwnd)
        self._waiting_pids.pop(hwnd, None)
        self._minimize_failed.discard(hwnd)

    def _keep_waiting(self, windows: Sequence[WinInfo], handled: set[int], now: float) -> None:
        """Waiting windows stay minimized: re-minimize any that did not stay down, forget closed ones."""
        listed = {window.hwnd: window for window in windows}
        exists = getattr(self._windows, "exists", None)
        for hwnd, pid in list(self._waiting_pids.items()):
            window = listed.get(hwnd)
            if window is None:
                if exists is not None and not exists(hwnd):
                    self._stop_waiting(hwnd)
                continue
            if hwnd in handled or window.state == "minimized":
                continue
            if window.pid != pid:
                self._stop_waiting(hwnd)
                self._start_waiting(hwnd, window.pid, window.process, now)
                continue
            if hwnd not in self._minimize_failed:  # e.g. an elevated window ignores the request
                self._minimize_failed.add(hwnd)
                self._log.record("error", f"minimize {hwnd}: {window.process} stays open"[:80], now)
            self._minimize(hwnd, now)

    def _minimize(self, hwnd: int, now: float) -> None:
        try:
            self._actions.minimize(hwnd)
        except Exception as error:  # e.g. an elevated window; keep trying, but log it once
            if hwnd not in self._minimize_failed:
                self._minimize_failed.add(hwnd)
                self._log.record("error", f"minimize {hwnd}: {error!r}"[:80], now)

    def _waiting_note(self, process: str, now: float) -> None:
        name = process[:-4] if process.lower().endswith(".exe") else process
        last = self._last_note.get(name.lower())
        if last is not None and now - last < NOTE_GAP:
            return
        self._last_note[name.lower()] = now
        until = time.strftime("%H:%M", time.localtime(self._session.end))
        self._ui.show_note(f"{name} is waiting until {until} — everything keeps running", NOTE_SECONDS)

    def restore_waiting(self) -> None:
        restore_windows(self._waiting, self._actions, self._log_error)

    def _apply_mutes(self, now: float) -> None:
        """Once asked, mute every waiting program that has sound, including sound that starts later.
        When the request is withdrawn, every program gets its earlier mute state back."""
        if not self._mute_requested():
            if self._muting:
                self._muting = False
                self.unmute_all()
            return
        self._muting = True
        try:
            waiting = {window.process.lower() for window in self._waiting.load().values()}
            candidates = (waiting & self._audio.audio_processes()) - set(self._apps) - NEVER_MUTED
            already = self._mutes.load()
            for process in sorted(candidates):
                if process not in already:
                    self._mutes.remember(process, self._audio.is_muted(process))
                    self._audio.set_mute(process, True)
                elif not self._audio.is_muted(process):  # reopened: a new audio session; the first state is kept
                    self._audio.set_mute(process, True)
        except Exception as error:  # audio trouble must not stop the guard, nor flood the log
            if not self._mute_failed:
                self._mute_failed = True
                self._log.record("error", f"mute: {error!r}"[:80], now)

    def unmute_all(self) -> None:
        restore_mutes(self._mutes, self._audio, self._log_error)

    def _log_error(self, detail: str) -> None:
        self._log.record("error", detail, self._clock())

    def _relaunch(self, process: str, now: float) -> None:
        app = self._apps.get(process.lower())
        if app is None:
            return
        recent = self._launches.setdefault(app.process, deque())
        while recent and now - recent[0] > LAUNCH_WINDOW:
            recent.popleft()
        if len(recent) >= LAUNCH_LIMIT:
            self._note("launch_failed", f"{process}: too many relaunches", now)
            return
        recent.append(now)
        if self._act(lambda: self._actions.launch(app.launch)) is False:
            self._note("launch_failed", process, now)

    def _drain_external(self, now: float) -> None:
        while True:
            try:
                kind, detail = self._external.get_nowait()
            except queue.Empty:
                return
            if kind not in EXTERNAL_KINDS:
                continue
            self._note(kind, detail, now)
            if kind == "tab_closed":
                self._roast()

    def _check_emergency(self, now: float) -> None:
        if self._exit_requested():  # the "Emergency exit" button on the running event's card
            self._clear_exit_request()
            if self._dry:  # a trial touches nothing, so it ends without the phrase
                self._note("emergency_exit", "trial ended from the window", now)
                self._stopped = True
                return
            if not self._asking:
                self._asking = True
                self._ui.ask_phrase()
        pressed = self._keys.pressed(self._vks)
        if self._detector.update(pressed, int(now * 1000)) and not self._asking:
            if self._dry:
                self._note("emergency_exit", "shortcut seen, no input in dry-run", now)
            else:
                self._asking = True
                self._ui.ask_phrase()
        if not self._asking:
            return
        typed = self._ui.poll_phrase()
        if typed is None:
            return
        if not typed.strip():
            self._asking = False
            return
        if phrase_matches(typed, self._cfg.phrase):
            self._asking = False
            self._note("emergency_exit", "", now)
            self._stopped = True
            return
        self._ui.ask_phrase()

    def _finish(self, now: float) -> bool:
        """Runs once; a failing step is logged and the next one still runs."""
        self._ended = True
        self._note("session_end", "", now)
        steps: tuple[Callable[[], object], ...] = (
            self.restore_waiting,
            self.unmute_all,
            lambda: self._ui.show_summary(SUMMARY_TEXT),
        )
        for step in steps:
            try:
                self._act(step)
            except Exception as error:
                self._log.record("error", f"end: {error!r}"[:80], now)
        return False
