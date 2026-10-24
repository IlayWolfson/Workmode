# Focus Guard: Design Spec

Date: 2026-10-03

## 1. Purpose and success criteria

**Who:** students who study and play on the same Windows 11 PC. Leaving work for friends and games is one click away, and resisting it all day is draining.

**What:** a personal work-session tool. The user starts a session with a duration. Until it ends, only an **allow-list** of apps and websites can stay open, and every attempt to leave them meets friction. It is a commitment device, not a security product: the user owns the PC and can always uninstall it. The goal is that quitting early costs more effort than staying.

**Success criteria**
- A full session can be completed without relying on willpower for each urge.
- Every way of closing or hiding an allowed window (X, Alt+F4, Ctrl+W, minimize, restore-down, process kill) triggers the same friction.
- A non-allowed app or site cannot stay open for more than a few seconds.
- The tool can never lock the user out of Windows or lose unsaved work silently (see section 5).

**Non-goals:** unbreakable locking, other operating systems, browsers other than Chrome, keyboard hooks of any kind, admin rights, changing Windows or security settings.

## 2. Components (Python 3.12 on Windows 11)

| Part | Job |
|---|---|
| `guard` | Main loop: reads the allow-list, watches windows, reacts, shows popups and the video, logs attempts. |
| `guardian` | Tiny second process. Watches `guard` and restarts it if it dies during a session. `guard` restarts `guardian` the same way. |
| Chrome extension (Manifest V3) | Checks every tab against the allowed sites, closes disallowed tabs, and reports allowed-tab closures (Ctrl+W) to `guard`. |
| Local server inside `guard` | `127.0.0.1` only, random token, used by the extension. |
| Dependencies | pywin32, psutil, pywebview (WebView2; every UI window is an HTML page), Pillow (icon only); standard library `urllib`, `http.server`, `json`. |

The project lives in a folder the user chooses before implementation starts.

## 3. Behaviour

**Session:** `focus start <minutes>` writes `session.json` (start, end). `guard` and `guardian` resume from it after a crash (they restart each other). After a reboot nothing starts by itself (no autostart entry is installed on purpose); `focus start` or the window's Start button resumes the same session. At the end `guard` shows a summary ("11 attempts") and exits. Nothing is enforced outside a session.

**Blocked window** (visible top-level window whose process is not on the allow-list, excluding protected processes): ask it to close (WM_CLOSE); if it is still open after 3 s, terminate the process. Log `blocked_app`.

**Allowed window disappears** (any cause: X, Alt+F4, Ctrl+W on the last tab, process killed): show the roast popup and relaunch the app with its configured `launch` command. Log `closed`. This single rule covers every close shortcut, so no keyboard hook is used.

**Minimize or restore-down/maximize toggle on an allowed window** (the dash and the square): restore the previous window state immediately and play the configured video (a local file, see section 4), full screen and on top, looping seamlessly with no ads, for at least 20 s, then dismiss it. Log `minimized` or `resized`.

**Chrome:** the extension closes a tab whose domain is not allowed and replaces it with a "blocked" page. It reports an allowed tab being closed (Ctrl+W); `guard` then shows the roast popup (the tab is not reopened). Log `blocked_site` and `tab_closed`. Chrome windows that are not the user's normal profile window follow the blocked-window rule.

**Roast popup:** always on top, centered, with the roast text, a visible countdown, and a "Yes, quit" button. It **auto-closes after 10 s**. "Yes, quit" only dismisses the popup; the closed window is relaunched anyway. Only the emergency phrase ends the session.

**Roasts:** exactly **one short line per popup** (at most 12 words, readable in about 3 s).
- At session start `guard` asks the Gemini API once for 10 lines and keeps them as a stock, refilling when 3 remain.
- Request: key from the `GEMINI_API_KEY` environment variable (never stored in files or logs), model name from config (default `gemini-flash-latest`), 3 s timeout, language from config (default Hebrew).
- The instruction asks for playful roasts aimed at the act of quitting early ("left again?"), not at the user's worth, grades or appearance. This is one line in the config that the user can change.
- Each line is cleaned (single line, trimmed, length-capped). If the API fails, the key is missing or the stock is empty, a local fallback list of 15 lines is used, so the tool never breaks without internet.

**Emergency exit:** four different shortcuts open the **same** small input **at any time**, so forgetting one is harmless: **Del, PgUp, PgDn** and **Ctrl+Alt+Shift+Q**. The popup and the video always show the reminder "Emergency exit: hold Del / PgUp / PgDn, or Ctrl+Alt+Shift+Q".
- **Ctrl+Alt+Shift+Q** (and any other combo in `hotkeys`) is detected by key-state polling like the hold keys (no `RegisterHotKey`, no hooks) and opens the input immediately.
- **Del, PgUp, PgDn** are used constantly while working, so they open the input only when **held for 1.5 s** (`hold_ms`). The guard reads only the state of these configured keys by polling (about 20 times per second); it installs no keyboard hook, records no other keystrokes, and never swallows the keys, so deleting and scrolling keep working normally. Setting `hold_ms` to 0 makes them instant, but then every ordinary press would open the input.
- No shortcut ends the session by itself. Typing the exact configured phrase (Unicode-normalized, whitespace-trimmed) ends the session at once; a wrong phrase does nothing and the input stays open. The phrase lives in `config.json` and is a friction device, not a secret.

**Attempt log:** `attempts.log`, one JSON line per event (time, type, app or domain). Never contains the API key or typed text.

## 4. Configuration (`config.json`)

```
{
  "allowed_apps": [{"process": "Code.exe", "launch": ["code", "C:/path/to/project"]}],
  "allowed_sites": ["github.com", "docs.python.org", "claude.ai"],
  "protected_processes": ["explorer.exe", "dwm.exe", "csrss.exe", "winlogon.exe", "sihost.exe", "taskhostw.exe", "ctfmon.exe", "SearchHost.exe", "ShellExperienceHost.exe", "StartMenuExperienceHost.exe", "TextInputHost.exe", "LockApp.exe", "SecurityHealthSystray.exe"],
  "popup_seconds": 10,
  "video": {"path": "C:/focus-guard/media/punish.mp4", "fallback_url": null, "min_seconds": 20},
  "roasts": {"language": "he", "model": "gemini-flash-latest", "stock": 10, "refill_at": 3, "max_words": 12, "instruction": "<default roast instruction written in the implementation; the user can replace it>"},
  "emergency": {"hold_keys": ["del", "pageup", "pagedown"], "hold_ms": 1500, "hotkeys": ["ctrl+alt+shift+q"], "phrase": "<the phrase the user chose, stored only here>"}
}
```
The `protected_processes` list above is the default; the tool's own processes are always protected as well.

**Video:** the user supplies a local video file (`video.path`, mp4 or webm). It plays from disk in a looping HTML video element inside the fullscreen window, so there are no ads, no internet dependency and no start-up delay. `fallback_url` is optional and used only when the file is missing; if neither a valid file nor a fallback URL exists, the tool refuses to start. The tool never downloads video itself. Obtaining the file (own video, licensed video, or a screen recording the user makes) is the user's responsibility.
The config is validated at start (unknown keys, empty allow-list, bad URL, missing launch command) and the tool refuses to start with a clear message instead of guessing.

## 5. Safety rules for the tool itself

1. Dry-run is the default: `start` logs what would be closed, killed or relaunched and does nothing else; only `start --live` enforces.
2. Protected processes (shell, taskbar, input and security components, the tool itself) are never closed or killed.
3. Polite close first; kill only after 3 s. The summary lists every app that was force-closed so lost work is traceable.
4. The local server binds to `127.0.0.1`, requires the token, and accepts only `GET /allowed`, `POST /event`.
5. No network access except the Gemini call (and the fallback video URL, only when the local file is missing). No keyboard hooks, no screen capture, no admin rights.
6. The tool is never run for real in an unattended or automated session: real enforcement is tested only with the user present.

## 6. Testing

- **Unit tests** (no Windows needed) for the pure logic behind small adapter interfaces (windows, processes, clock, HTTP): allow-list matching, protected-process rules, window-state transition detection, session timing and resume, roast stock/refill/fallback/cleaning, phrase check, config validation, log format.
- **Dry-run integration:** scripted fake window events produce the expected log lines and no side effects.
- **Manual checklist** on the user's PC with the user watching: each close path, minimize, restore-down, blocked app, blocked site, popup auto-close at 10 s, video minimum duration, emergency phrase, killing `guard` from Task Manager and seeing it return, and a full 5-minute session.

## 7. Failure behaviour

- Gemini unreachable or key missing: fallback roasts, one line in the log.
- Extension not connected: apps are still enforced; the log notes that sites are unchecked; the tool shows a one-time warning at session start.
- `launch` command fails: popup still shows, the failure is logged, and the app is not retried more than 3 times per minute.
- Unknown error in the main loop: log it and keep enforcing; never exit silently during a session.
- Both processes killed together: the session ends (documented limit; a Windows-level lock is out of scope).

## 8. Open items to verify during the build

- Which Gemini model names are available on the free tier (the model is configurable).
- Whether WebView2 autoplays the local video with sound (an autoplay-policy flag may be needed) and which codecs the installed WebView2 plays.
- Reliable identification of the user's Chrome window versus other Chrome windows.
- Whether polling the held state of Del, PgUp and PgDn (GetAsyncKeyState) works reliably while other apps have focus, including elevated windows (which may hide key state from a normal-privilege process).
- How the extension is installed (one-time "Load unpacked" in Chrome developer mode).

## 9. Desktop app (added requirement)

The tool is used as a program, not only from a command line:
- **Desktop shortcut "Focus Guard"** whose icon is a picture the user supplied (cropped to a centered square and converted to a multi-size `.ico`). It is created by `python -m focus_guard shortcut` and runs `pythonw.exe -m focus_guard.app` (no console window).
- **GUI window** (dark, right-to-left, Hebrew): shows the state (ready, running with minutes left, or a configuration problem with the reason), the allowed apps, and the emergency-exit reminder; lets the user type the minutes and press "start session (enforced)" or "trial (closes nothing)". It refreshes every few seconds.
- `init` generates the bridge token and `extension/config.js`. Telling Chrome profiles apart is out of scope.
- **No stop button** anywhere: a session ends only by time or by the emergency phrase.
- The window's process is excluded from enforcement (its pid is recorded in `state/app.pid`), so a live session never closes the user's own control window.
- The window and taskbar show the same picture as the icon (window icon set after the window appears, with an explicit application id).
