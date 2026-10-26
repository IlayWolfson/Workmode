# Workmode

A work-session tool for Windows 11. Start a session; until it ends only the apps and Chrome sites on your
allow-list stay in front: other programs wait minimized until the session ends (nothing is closed, they keep
running), and every attempt to leave meets friction (a popup with a roast, a looping video, the window comes
back). It is a commitment device, not a security product.

## Setup (once)
1. `python -m pip install -r requirements.txt`
2. `python -m focus_guard init`, then edit `config.json`: allowed apps (with a `launch` command each),
   allowed sites, `video.path` (a local .mp4/.webm), and **your own emergency phrase**. Punishment videos can also
   be managed in ⚙ הגדרות → "סרטון עונש": tick bundled ones, add your own with "+ הוספת סרטון משלי" or by dropping a
   file on the box (saved as `videos` / `video_files`); one of the ticked videos plays at random.
3. `python -m focus_guard windows` lists the open windows' process names. **Put your terminal and your code
   editor on the allow-list**, or in live mode they wait minimized until the session ends; nothing is closed.
4. Chrome: `chrome://extensions`, Developer mode, Load unpacked, choose the `extension` folder, and turn on
   "Allow in Incognito" for it (otherwise private windows are not covered).
5. Optional roasts from Gemini: set the `GEMINI_API_KEY` environment variable (a free key from Google AI
   Studio). Without it the built-in roasts are used.
6. `python -m focus_guard check` must print `Config OK`. It also refuses a `launch` command that cannot be found:
   use full paths (`%LOCALAPPDATA%` style variables work), because a relaunch cannot use Chrome's registry shortcut.

## Use
- `focus start 25` runs a **dry-run**: it only logs to `state/attempts.log` what it would do.
- `focus start 25 --live` enforces for 25 minutes.
- If a session is active but its guard is not running (both processes were ended, or after a reboot), run
  `focus start` again (or press Start in the window): it resumes enforcement of the same session. Nothing
  starts by itself after a reboot.
- `focus status` shows the remaining time. There is no stop command: wait, or use the emergency exit.
- The first `grace_seconds` (default 20, 0 to 120) of a session are a grace period: arranging allowed windows
  (maximize, minimize, close) does nothing. Programs not on the list are minimized from the first second.
- A waiting program that is opened again is minimized again with a short note. The window has a button that
  mutes the waiting programs; pressing it again gives their sound back. At the end every waiting window returns to where it was and its sound comes back;
  if the PC restarted mid-session, that happens the next time the tool starts.

## What is allowed: edit it from the window
In the calendar's side panel, "✅ מה מותר בסשן" opens three tabs:
- **תוכנות**: what is allowed, what is open now (one click to add), and a box where you type a program's name (up to
  5 matches from the Start menu) or drop a program or its shortcut.
- **אתרים**: paste a link; choose the site and everything under it (`uni.ac.il` also covers `moodle.uni.ac.il`) or
  any address that contains a word (at least 3 English letters).
- **יוטיוב**: paste a link to a video, channel or playlist and choose what to allow: the whole channel, the whole
  playlist or only that video.
Every change is saved at once into `config.json` (checked first, like the settings) and counts from the next session.
The button is hidden during a session; nothing is saved while `config.json` is not valid JSON, and a change is saved
only when the result passes the check.

Signing in: a sign-in page of Microsoft, Google or Apple (`login.microsoftonline.com`, `accounts.google.com`, …) opens
when the tab came from an allowed site (for example Moodle sending you to sign in). Opened directly, it is blocked.

## YouTube channels and playlists
`youtube.com` in `allowed_sites` allows all of YouTube. To allow only some of it, list channels and playlists:

```json
"youtube": {"channels": ["@3blue1brown", "https://www.youtube.com/channel/UCYO_jab_esuFRV4b17AJtAw", "Veritasium"],
            "playlists": ["https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi"],
            "videos": ["https://youtu.be/aircAruvnKk"]}
```

- A channel is an `@handle`, a channel link (`youtube.com/@handle` or `youtube.com/channel/UC...`) or the
  channel's exact full name (case and surrounding spaces do not matter; part of a name never matches). Old
  `/c/...` and `/user/...` links are refused by `check`: use the `@handle`.
- A playlist is its link or its id (the `list=` value).
- A video is its link or its 11-character id; only that video opens.
- During a session: videos of a listed channel, videos opened from a listed playlist, a listed channel's pages and
  playlists, and a listed playlist's page open. Search, the home feed, Shorts and everything else on YouTube go to the blocked page,
  also when YouTube switches videos inside the tab. The extension asks YouTube's public oEmbed address whose a video
  is (no account, no key) and remembers the answer until Chrome closes; when it cannot find out, the video is blocked.
- After updating, reload the extension once in `chrome://extensions` (on every PC that has it).

## Planned sessions
Plan sessions in the window's week view, like Google Calendar: click or drag across empty time for the quick
popover (title, repeat, the song a minute before, full enforcement or trial), click an event for its card (edit,
delete; "this event" or "all events" for a repeating one), drag an event to move it, drag its edge to resize it.
The session that is running is locked: its card has only "יציאת חירום", which opens the phrase box (a trial ends at
once). "+ יצירה" → "התחלה עכשיו" starts a session now. The gear holds the settings (songs, video, grace seconds,
start with Windows, a new emergency phrase); it is hidden during a session and never saves a `config.json` that does
not pass the check, so it can also finish a fresh install (set the phrase and tick a video).

The calendar keeps its events in `state/events.json` (you can still edit it by hand; a broken entry is kept as it
is and reported):

```json
{"version": 1, "events": [
  {"id": "math1", "title": "מתמטיקה", "date": "2026-10-25", "start": "14:00", "end": "16:00",
   "days": [0, 2], "cue": true, "live": true}
]}
```

- `date` is the first day (`YYYY-MM-DD`); `start`/`end` are local `HH:MM` (an end at or before the start is the
  next day; at most 12 hours). `days` repeats it on weekdays, 0 = Sunday … 6 = Saturday; leave it out for a
  one-off. `cue` (default true) plays a 5-second song a minute before; `live: false` makes it a trial. A repeating
  event may also have `until` (its last day) and `skip` (days it leaves out); the calendar writes these when you
  change "this event" or "all events".
- A minute before, the song plays and a small window offers "Start now" and "Not today". Ignoring it starts the
  session at the planned time. "Not today" asks once more (the nerd); only the red button cancels that day.
- If the PC was asleep or off at the start, a window offers the rest of the session when it is back. A session
  cut short by a restart offers "Continue". Ignoring those starts nothing.
- A broken entry is skipped and reported once; the other events still happen.
- Songs: `"songs"` in `config.json` lists the ticked songs (your own mp3/wav files or names in `assets/songs/`);
  `"song_files"` remembers the files you added in settings. Nothing ticked means a bundled song. Windows cannot
  play m4a/mp4 here without extra codecs, so those are skipped.

## Emergency exit
Hold Del, PgUp or PgDn for 1.5 s, or press Ctrl+Alt+Shift+Q. A box opens; type your exact phrase.
A wrong phrase does nothing.

## Tests
Development tools: `python -m pip install -r requirements-dev.txt`, then `python -m ruff check .`, `python -m ruff format --check .` and `python -m mypy focus_guard tools`.

`python -m unittest discover -s tests -t . -v` and `node --test extension/*.test.mjs "tests/js/*.test.mjs"`.

`python tools/preview_calendar.py` opens the main window on scratch data (sample events, a dummy config) for
checking the calendar by hand. It never starts a guard and never touches your `config.json` or `state/`.

## Third-party code
- FullCalendar 6.1.21 (MIT, `focus_guard/web/vendor/fullcalendar/LICENSE.md`): the calendar's week view, bundled
  locally with its Hebrew locale.

## Desktop app
`python -m focus_guard shortcut` creates a shortcut called Workmode in the project folder, with your picture as
the icon. The app runs in the background with a tray icon (click it to open the window); closing the window only
hides it. Outside a session the window is the week view (see Planned sessions). During a session it is a small
clock with the time left, the waiting programs and the mute button; it has no stop button. The 📅 button on the
clock (or "יומן" in the tray menu) shows the calendar during a session.

The calendar window opens at `"window_percent"` of the screen (default 85, from 50 to 100; it follows Windows'
display scaling). It starts with Windows (a shortcut in your Startup folder). Set `"start_with_windows": false` in `config.json` to
turn that off; the shortcut is removed the next time the app starts. To quit it, use "יציאה" in the tray menu.
If `config.json` breaks, the app keeps the last settings that loaded and shows the error once.

## Known limits
- An allowed site written as `*word*` (for example `*portfolio*`) matches any host that contains the word; the
  word needs at least 3 English letters.
- Chrome profiles are not told apart; the extension must be loaded in the profile you work in.
- `chrome://extensions` stays reachable (browser pages are never blocked), so the extension can be turned off.
- Windows on another virtual desktop count as open; a window that was really closed shows a popup.
