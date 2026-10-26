# Workmode: updating from GitHub Releases

Date: 2026-10-24. Status: approved 2026-10-24 with the recommended choice in D1-D5. Builds on
`2026-10-21-calendar-scheduler-design.md`.

## Intent

A user who installed Workmode from GitHub (app folder + Chrome extension loaded with "Load unpacked") learns in
Chrome that a newer version exists and gets it with one button, in the extension or by double-clicking `Update.cmd`
in the install folder. Updates come only from published GitHub Releases, never from every commit. Later, if there are
users, the extension may move to the Chrome Web Store; this design must not block that.

Goals: one action; settings and history kept; never a half-installed tool; never an update in the middle of a session.
Non-goals: silent automatic installs, delta updates, multiple update channels, updating Python itself.
Anti-goals: anything that lets a web page, another extension or a compromised GitHub account make the PC run code
the maintainer did not sign; any update path that ends or weakens a running session.

## Facts from the code (checked 2026-10-24)

- There is no version number in the Python code; only `extension/manifest.json` has one (1.2.2).
- Session state is `state/session.json`; `session.load_session(path, now)` returns None when it is missing,
  unreadable or past its end. A session survives crashes and reboots by design (it resumes), so a stale file can keep
  "active" true at most until its end time (at most 12 hours, `MAX_MINUTES`).
- The guard's liveness is `procfiles.pid_alive(paths.guard_pid, "focus_guard.run_guard")` (pid file + command line).
  The app writes `state/app.pid`; one app instance is enforced by the named mutex `Local\FocusGuard.Background`.
- The bridge (`server.py`) has exactly two routes, `GET /allowed` and `POST /event`, both token-checked with
  `hmac.compare_digest`, body capped at 2 KB, 127.0.0.1 only. The extension polls `/allowed` every 30 s
  (`chrome.alarms`) and has one internal message (`status`). It never calls `chrome.runtime.reload`.
- Atomic writes exist (`jsonfile.write_text_atomic`: temp file + `os.replace` in the same folder).
- `.gitignore` keeps local: `config.json`, `extension/config.js`, `state/`, `media/`, `dist/`, `.superpowers/`.
- `cryptography` is installed on the dev VM only as a dependency of other tools; it is not in `requirements.txt`.
- Known open minor M1 (security review): the bridge socket allows port sharing (`SO_REUSEADDR`), so another local
  process could listen on the same port and receive the token. New update routes raise its weight (see Trust).

## Trust model

Who can trigger what:

| Actor | Can | Cannot |
|---|---|---|
| A web page in Chrome | nothing (no token, no CORS) | reach the update routes |
| The extension (has the token) | ask "is there an update?", ask "install the verified update" | pass a URL, path, version or command |
| A local process that steals the token | the same two requests | make the PC install anything not signed by the release key |
| Someone with the GitHub account / a stolen GitHub token | publish a release | get it installed without the offline signing key |
| Someone with the offline signing key | publish an update that installs | (accepted risk: this key is the root of trust) |

**Authenticity: one Ed25519 signing key, kept offline.**
- The maintainer creates a key pair once. The private key lives only on the maintainer's PC, outside the repo (for
  example `%USERPROFILE%\.workmode\release-signing.key`, ideally also backed up on a USB stick); it is never in
  GitHub, Actions or a release. The public key is a constant in `focus_guard/update_trust.py` and ships with every
  install.
- Each release has three assets: `Workmode-<version>.zip`, `release.json`, `release.json.sig` (detached Ed25519
  signature over the exact bytes of `release.json`).
- `release.json`: `{"format": 1, "version": "1.3.0", "zip": {"name": "Workmode-1.3.0.zip", "sha256": "...",
  "size": 123}, "files": [{"path": "focus_guard/app.py", "sha256": "...", "size": 4567}, ...],
  "requirements_sha256": "..."}`.
- The updater trusts nothing that is not inside a release.json whose signature verifies with the built-in key.
  HTTPS and GitHub's checksums are only transport; a checksum next to the zip is not trusted on its own.
- **Downgrade protection:** the signed version must be strictly greater than the installed version (numeric
  `major.minor.patch` comparison). The installed version comes from `focus_guard/version.py`, itself one of the signed
  files. A replayed old signed release is therefore refused.
- **Key loss or theft:** no automatic rotation (too much machinery for this project). If the key leaks, the
  maintainer publishes no more signed releases, posts a notice in the README, and users reinstall from a fresh clone
  carrying a new public key. If the key is lost, the same. This is written in the release docs.
- **Library:** verification with `cryptography` (PyCA), added to `requirements.txt` with a lower bound on a version
  without known CVEs. Alternative without a new package: Windows' built-in OpenSSH `ssh-keygen -Y verify` (decision D1).

**The extension cannot steer the updater.** The two new bridge routes take only the token:
- `GET /update?token=…` → `{"installed": "1.2.2", "available": "1.3.0" | null, "state": "...", "session_until": ...}`
- `POST /update` with body `{"token": "..."}` → starts the fixed command `pythonw -m focus_guard.update --apply`.
  No field of the request reaches the command line, a path or a URL. Any other field is ignored.
- Repository, asset names and allowed download hosts (`api.github.com`, `github.com`,
  `objects.githubusercontent.com`) are constants. Redirects outside these hosts are refused.

**Archive safety.** The zip is never extracted blindly. For each entry the updater requires:
- the name is in the signed `files` list (no extras), its size and SHA-256 match, total size under a cap (50 MB);
- a relative POSIX path with no `..`, no drive letter, no leading `/` or `\`, no `:` (alternate data streams), no
  reserved Windows names, no symlinks (zip external attributes), and at most 8 levels deep;
- it is not a protected path: `config.json`, `extension/config.js`, `state/`, `media/`, `.git/`, `dist/`,
  `.superpowers/`, `docs/superpowers/plans/` (the release builder also refuses to include them).
Files are written into staging only, then moved in.

## The update flow

### Checking (background, cheap)
- The app checks `releases/latest` once at startup and then every 24 hours; the result and an ETag go to
  `state/update-check.json`, so restarts do not re-ask. Offline or GitHub errors: keep the last result, try again at the
  next interval, show nothing alarming. GitHub's unauthenticated limit (60 per hour) is far away.
- When a newer version is seen, the app downloads the three assets into `state/update/<version>/`, verifies the
  signature, the zip hash and every entry, and extracts into `state/update/<version>/staging/`. This is allowed during
  a session (it does not touch the installed files). After that the update is "ready".
- Checks never notify twice for the same version: the extension shows the state, it does not pop up.

### What the user sees in Chrome
- No update: plain icon. Update ready: an orange `!` badge on the Workmode toolbar icon and the popup (new
  `popup.html`) says "Version 1.3.0 is available (you have 1.2.2)" with the button "עדכון לגרסה העדכנית".
- During a session: the badge stays, the button is disabled with "יותקן אחרי שהסשן ייגמר ב-14:00". It is not
  installed automatically when the session ends; the button becomes active (decision D2).
- While installing: "מעדכן…". Afterwards: "עודכן לגרסה 1.3.0" or an honest failure message with what to do.

### Applying (`python -m focus_guard.update --apply`, from the popup or `Update.cmd`)
One code path for both entry points. Steps, each written to `state/update-journal.json` before it starts:
1. **Lock and gate.** Take the named mutex `Local\FocusGuard.Update` (a second updater exits). Refuse when
   `load_session(...)` is not None or the guard is alive: "יש סשן פעיל עד 14:00; העדכון יחכה". Refuse when a planned
   session starts within 10 minutes (decision D3). Refuse in a git clone (`.git` present): "עדכון דרך git pull"
   (decision D4).
2. **Make sure the update is ready.** If not staged yet, download and verify now (same code as Checking).
3. **Space.** Require free space of at least 3× the staged size on the install drive.
4. **Requirements.** If `requirements_sha256` differs from the installed `requirements.txt`, run
   `python -m pip install -r <staged requirements.txt>` now, before touching files; on failure stop with nothing changed.
5. **Stop the app.** Ask the running app to quit (a new named event `Local\FocusGuard.Quit`; the app exits cleanly),
   wait up to 15 s, then end the pid from `state/app.pid` only if its command line is `focus_guard.app`. Starting a
   session is refused while the journal says an update is applying (one check in `starting.begin_session`).
6. **Back up.** Copy every file that will be replaced or removed into `state/update/backup-<old version>/`, then write
   journal phase `backup_done`.
7. **Swap.** For each file: copy from staging to `<target>.new` in the same folder, then `os.replace` onto the target.
   Files listed in the old installed manifest (`state/installed.json`) but not in the new one are removed. An install
   without `installed.json` (the first update after this feature) only adds and replaces. Journal phase `swapped`.
8. **Start and verify.** Start the app (`pythonw -m focus_guard.app --background`) and wait up to 60 s for
   `state/app-ready.json` with the new version and the app's pid (the app writes it after config, bridge and tray are
   up). Success: write `installed.json`, journal phase `done`, clean staging, keep the last backup.
9. **Failure after step 6:** roll back: stop the new app if any, restore every backed-up file, delete added files,
   start the old app, journal `rolled_back`, and leave a message for the popup and `Update.cmd`.

**Interrupted (power cut, killed, full disk):** at every app start and every `Update.cmd` run, a journal whose phase
is not `done` or `rolled_back` triggers the rollback from step 9 before anything else. A crash before `backup_done`
has not changed any installed file (only staging), so recovery just deletes staging.

**`Update.cmd`** (next to `install.cmd`): `cd /d "%~dp0"` then `python -m focus_guard.update --apply`, shows the result in
Hebrew and pauses. It works when the app is not running, and obeys the same gate (it cannot bypass a session).

### The Chrome extension after an update
Replacing the files does not change what Chrome runs. So:
- `GET /update` (and `/allowed`) include the app's version. The service worker compares it with
  `chrome.runtime.getManifest().version`. When the app's version is newer, it records the target version in
  `chrome.storage.local` and calls `chrome.runtime.reload()`, which for an unpacked extension re-reads the folder
  (assumption A1, to verify by hand).
- After the reload, if the versions still differ (Chrome loads the extension from another folder), it does
  not try again for that version and the popup says: "Chrome טוען את התוסף מתיקייה
  אחרת. פתח chrome://extensions, הסר את Workmode וטען מחדש את התיקייה <app folder>\extension".
- Chrome closed during the update: on the next start the worker sees the mismatch and reloads once.
- `extension/config.js` (token) is a protected path, so it survives.

## Failure messages (all in Hebrew in the UI)
- Offline / GitHub down: nothing shown; the popup's "בדיקה" line says when it last checked.
- No newer release: "יש לך את הגרסה העדכנית".
- Signature or hash mismatch: "העדכון נדחה: הוא לא חתום כמו שצריך" (the staged files are deleted, the version is
  remembered as refused so it is not re-downloaded every day).
- Rolled back: "העדכון לא הצליח וחזרנו לגרסה 1.2.2" plus the step that failed.

## Publishing a release (maintainer)
`python tools/release.py 1.3.0`: requires a clean git tree on `main`, sets `focus_guard/version.py` and the manifest
version (a test keeps them equal), builds the zip from `git ls-files` minus protected paths, writes and signs
`release.json` with the offline key, and runs `gh release create v1.3.0` with the three assets after a confirmation.

## Decisions (approved 2026-10-24)
- D1. Signature library: `cryptography`, added to `requirements.txt`.
- D2. After a session ends the update waits for the user's click; it is never installed automatically.
- D3. Updating is refused within 10 minutes of a planned session.
- D4. In a git clone (`.git` present) the updater refuses and says to use `git pull`.
- D5. Existing installs (1.2.2) have no updater yet: one last manual update is needed to get it.

## Assumptions to verify
- A1. `chrome.runtime.reload()` in an unpacked MV3 extension reloads from disk, including a changed manifest.
- A2. Replacing `.py` files while no Workmode process runs is safe; nothing else (antivirus, Explorer previews) holds
  them open long enough to break `os.replace`; retry 3 times with a short pause.
- A3. The release zip size stays well under 50 MB (today about 2 MB).
- A4. `pythonw` can be found next to `sys.executable` on user PCs (already assumed by the shortcuts).

## Smallest implementation plan (test-first, in this order)
1. `version.py` + test that it equals `manifest.json`.
2. `update_trust.py`: verify signature, parse release.json, version compare. Tests: valid, wrong key, tampered
   json, older/equal version refused.
3. `update_archive.py`: validate entries and extract to staging. Tests: `..`, absolute, drive, `:`, symlink, protected
   path, extra entry, size/hash mismatch, zip bomb cap.
4. `update_apply.py`: gate, backup, swap, verify, rollback, journal recovery, all on temp folders with fakes for
   processes and time. Tests: session active refused (also via the CLI entry), stale session past its end allowed,
   planned session soon refused, crash at each journal phase recovers to the old files, full disk before swap leaves
   the install untouched, app not ready in 60 s rolls back, protected files never touched, removed files deleted only
   when listed.
5. `update_check.py`: GitHub check with cache and ETag (fake HTTP). Tests: offline, no newer, newer once, refused
   version not re-downloaded, host allow-list on redirects.
6. Bridge routes `GET/POST /update` with token, no parameters reaching the command. Tests: no token 403, extra
   fields ignored, POST spawns only the fixed command.
7. Extension: add `"action": {"default_popup": "popup.html", "default_icon": ...}` to the manifest (today it has no
   toolbar button at all), `popup.html/js`, badge, version compare and one-shot reload (node tests with a fake
   `chrome`). No new permission is needed (`chrome.action` and `chrome.runtime.reload` need none).
8. `Update.cmd`, `tools/release.py`, README section; app writes `app-ready.json` and listens for the quit event.
9. Hand check: a real signed test release on a private test repo, update from the popup and from `Update.cmd`,
   kill the updater mid-swap, and confirm rollback (needs the user's approval; no live session involved).
Also fix minor M1 (exclusive port) in the same release, since the token now guards more.
