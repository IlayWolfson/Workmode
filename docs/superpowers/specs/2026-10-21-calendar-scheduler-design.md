# Focus Guard (Hyperbolic Time Chamber): calendar and scheduled sessions

Date: 2026-10-21. Builds on `2026-10-03-focus-guard-design.md`.

## Why

The tool works, but sessions only start when the user remembers and chooses to start one. The goal of this
upgrade is that study time is planned in advance and then simply happens. The idea: the tool should
put people in a situation where finishing the study block is easier than leaving, and that only works if it feels
safe and pleasant to put study times in the calendar in the first place ("if you could make a diet easier, it is
more likely to stick"). So:

- Planning and cancelling **before** a session starts is cheap and free of guilt.
- Leaving **after** it starts costs the emergency phrase, exactly as today.
- Nothing in the tool confronts the user with failures.

The tool's philosophy: it is a prison of discomfort, not a hard prison. Someone determined to cheat it can
always uninstall it or configure an easier prison; the tool does not try to stop that, it only makes staying the
easier path.

## Goals

1. The main window is a weekly calendar that copies the Google Calendar web UI as closely as practical
   (right-to-left, Hebrew).
2. Sessions can be scheduled: one-off or repeating.
3. A scheduled session gives a short musical cue a minute before, then starts by itself in full enforcement.
4. A spontaneous session can be started at any time from the calendar ("+ Create" → "Start now").
5. During a session the window is a small, quiet clock.
6. The first seconds of every session are a grace period for arranging windows.
7. The tool starts with Windows and waits in the background, so schedules fire without the window open.
8. Nothing is ever closed or killed. Programs not on the allow-list are kept minimized ("waiting") for the
   session and come back exactly as they were; downloads, servers, music and unsaved text survive.
9. YouTube can be allowed per channel or per playlist, not only as a whole site.

## Non-goals (this upgrade)

- Statistics, streaks, history views, counts of escapes. **Anti-goal**: statistics can make people
  avoid opening the tool, because opening it means facing their failures. Do not add any.
- Phone notifications (SMS, WhatsApp, calendar invites). A sleeping or switched-off PC cannot send them; this needs
  an always-on cloud service and is a separate future project.
- Any Google Calendar connection (sign-in, sync or read-only). Planned for later; this upgrade only prepares for it
  (below).
- Editing allowed apps, sites and YouTube channels from the window (a later upgrade; the second reviewer also
  asked for it), Pomodoro-style breaks (later), the deferred
  review minors (later), public-release packaging (later).

## Behaviour

### The calendar window (outside a session)

- Layout copies Google Calendar's week view: top bar with previous/next week arrows, a "Today" button, the
  week's date range and a settings gear; a side panel with a "+ Create" button and a small month calendar; the
  main area is the week, Sunday to Saturday, hours down the side, today's date in a blue circle, a red line at the
  current time.
- The calendar is empty until the user adds sessions.
- **Creating**: clicking an empty slot (or dragging across several slots) opens a quick-create popover like Google's
  (as in Google: title field "הוספת שם", the date and the time range, a repeat dropdown
  starting at "ללא חזרה", "Save" and "More options"). Focus Guard adds two lines to it: "🎵 reminder a minute
  before" (on by default) and "🔒 full enforcement / trial (touches nothing)".
- **Repeat options**, as in Google, adapted to the Israeli week: does not repeat; daily; weekly on a chosen day (for example "every Tuesday");
  every weekday (Sunday–Thursday); custom (pick any days Sunday–Saturday).
- **Existing events** look like the user's Google events (solid blue block, white title and time). Clicking one
  opens a details card with edit and delete. Dragging moves it; dragging its edge resizes it. For a repeating event,
  edit and delete ask "this event" or "all events in the series", as in Google.
- **"+ Create" menu** includes "Start now", which starts a spontaneous session immediately (choose length; full or
  trial). This replaces today's minutes field and red button.

### Rules for changing events

- A future event can be edited or deleted freely.
- The event that is running now is **locked**: it cannot be moved, resized, extended, shortened, switched to trial
  or deleted. Its card says "running until 14:00" and has one button, "Emergency exit", which opens the phrase box
  as today. Reason: nobody should fiddle with a running session; to work longer, use
  "Start now" when it ends. This also removes any need to tell the running guard about a new end time: the guard
  reads the end once at start, as today.
- Series edits ("all events in the series") never touch the running occurrence; they apply from the next one.

### A scheduled session

1. **One minute before**: the first 5 seconds of a random song play, then stop. A small notification-style window
   appears and stays, with two buttons: **"Start now"** and **"Not today"**.
   - "Not today" does not cancel at once (third reviewer: one free click at the moment resistance peaks becomes a
     reflex). The window turns into the nerd emoji (`assets/nerd.jpg`, made for this project with AI, so it can ship)
     saying "ידעתי שאתה לא מסוגל חי חה חי גרההה", with two buttons:
     - green "התחרטתי אני רוצה לעבוד": the session starts now, as "Start now";
     - red "אתה צודק המלך שלי נכנעתי": only this occurrence is cancelled (a repeating series continues).
     - Still no phrase, and nothing is logged: the teasing is the cost, not a record.

     - Ignoring this window (no button pressed by the planned start, or the window closed) counts as the red button:
       this occurrence is cancelled. Reason: someone who pressed "Not today" and walked away is not at the
       computer. The first window is unchanged: ignoring it still starts the session.
     - The same two-step "Not today" applies to the missed-start and the restart windows. There the planned start
       is already past, so closing the nerd window, or 2 minutes without a click, counts as the red button.
   - "Start now" starts at once; the planned end time stays the same.
   - Ignoring the window: the session starts at the planned time.
   - This window (and the nerd window, the missed-start and the restart windows) is **always on top** and appears
     above full-screen browsers and games, so the user cannot miss it behind another window (fourth reviewer). It
     does not take keyboard focus, so typing in another program is not interrupted. The session clock stays not
     always-on-top.
2. **At the start time**: the first 5 seconds of the same song play, and the session starts in full enforcement
   (or trial, if the event says so). From here, the only way out is the emergency phrase, as today.
3. If a session is already running (for example a spontaneous one), a scheduled event that ends at or before the
   running session's end is skipped. One that ends later gets no cue and no window; it becomes a follow-on session
   that starts when the running one ends (see "Overlapping and back-to-back events").
4. **PC asleep or off at the start time**: nothing can happen while it is off. When the PC wakes or the user logs in during the event, the notification window
   appears at once: "You missed the start, X left", with "Start now" (until the planned end) and "Not today".
   After the event's end, nothing happens.

### Songs and videos

- No YouTube or Spotify (adverts; Spotify
  needs Premium to start playback by itself).
- The tool ships with a built-in **song library** (short, pleasant, not stressful clips) for the cue, and a built-in
  **video library** for the punishment video. In settings each library is a list to pick from, with a "+" button to
  add the user's own files (audio: mp3 and mp4/m4a; video: mp4 and webm). Most users never add anything.
- Everything bundled must be free to redistribute (CC0 or equivalent), because the tool will be released publicly.
  Files a user adds stay local additions, never part of the release.
- A random song each time from the songs the user has ticked, not repeating any of the last 3 when there are enough.
  If nothing is ticked, a built-in song is
  used, so there is always a cue.
- The session video (the punishment) is separate and is never used as a cue.

### Google Calendar: later, but designed for

Not in this upgrade. The user does not want to ask people for their secret iCal address, and prefers Google's
narrow "see when you are busy" permission (`https://www.googleapis.com/auth/calendar.freebusy`) with a normal Google
sign-in. It waits until the tool has users. Update: Google classifies `calendar.freebusy` as a non-sensitive
scope, so the 100-user cap for unverified apps does not apply and heavy verification is likely not needed. The
Google app registration (steps 1–3 of the guide) is already done.

What this upgrade must do so adding it later is easy:

- The calendar shows "busy blocks from outside" through one small interface (a port, like `ports.py`): it returns
  busy time ranges for a date range. This upgrade ships it with no source connected, so nothing is drawn.
- The week view already knows how to draw grey, read-only busy blocks from that interface, with tests using a fake
  source. Adding Google later means writing one adapter and a "Connect Google Calendar" button, nothing else.
- Busy blocks never block saving a session; at most the quick-create popover says "you are busy then".

Started now, outside the code: the Google app registration (Cloud project, consent screen with only the freebusy
scope, privacy-policy and home pages on GitHub Pages).

### Programs not on the list: waiting, never killed

This replaces today's behaviour (polite close, then terminate the process after 3 seconds). Reason:
killing loses unsaved text, stops downloads, servers and music, and users cannot
tell whether their program was killed or not. The tool should stop the user from *using* a program, not destroy it.

- At session start every visible window of a program not on the allow-list is minimized. It stays on the taskbar,
  so it is obvious that it is still alive.
- Clicking it (or Alt+Tab to it) minimizes it again at once and shows a small note: "Steam is waiting until
  14:00 — everything keeps running". New windows of such programs during the session are treated the same way.
- The tool never closes or terminates any process. Background work continues: downloads, servers, music.
- At the end of the session (time up, emergency phrase, or "Not today" on a resumed session) every waiting window
  is restored to its previous size, position and state.
- The list of waiting windows and their previous placement is saved to a file under `state/` as soon as it changes,
  so a guard restart or crash still restores them. After a PC restart there is nothing to restore (the programs are
  gone), and the file is cleared.
- The attempt log keeps a line when a waiting program is opened, as today's `blocked_app`, but no popup or video:
  the note is enough. Allowed windows keep today's behaviour (popup when closed, video when minimized or resized).
- The session clock shows a short line "waiting: Steam, Notepad".

### Mute waiting programs

- The session clock has one button that mutes every program that is waiting, using Windows' per-app volume (the
  same as the volume mixer). Allowed programs are never muted, so lectures and study music keep playing.
- Programs that start waiting after the button was pressed are muted too. At session end each program's mute state
  goes back to what it was before.
- After muting, the same button reads "ביטול השתקה" and undoes it at once: each program gets its earlier mute state
  back. Pressing it again mutes again.
- What was muted (and its previous state) is saved under `state/` as soon as it changes. Every time the tool starts,
  and on "Not today" after a restart, it undoes any mute it left behind, so a crash or restart never leaves Discord
  or Spotify silent in the volume mixer.
- Focus Guard's own sounds (the cue song, the punishment video) always play.

### YouTube channels and playlists

Lectures and study music often come from YouTube, but allowing all of `youtube.com` allows everything. The user
can now allow specific channels and playlists. Every channel lives on the same host, and a video's address does not
say which channel it belongs to, so the extension has to ask.

- Allowed during a session: a video whose channel is allowed; a video opened from an allowed playlist (the
  `list=` value in its address), even if its channel is not on the list; the page of an allowed channel and
  everything inside it (videos, playlists tabs); the page of an allowed playlist.
- Blocked: search, the home feed and recommendations, Shorts, and every other video and channel. The rule:
  "nobody should be searching mid-session; if you didn't find it, stop and prepare in advance."
- How the channel is found: YouTube's public oEmbed address (`https://www.youtube.com/oembed?url=<video>&format=json`,
  no key, no account) returns the channel's name and address. Answers are cached, so a video is only looked up once.
  Reading the channel from the page after it loads is a backup, not the main method.
- Matching: a channel in `config.json` can be written as `@handle`, a channel link in any form
  (`youtube.com/@handle`, `https://www.youtube.com/channel/UC...`) or the channel's full name. Links and handles are
  normalized to one form; everything is compared case-insensitively with surrounding spaces ignored. A name must
  match the whole channel name, never part of it ("3Blue1Brown" does not match "3Blue1Brown Shorts"). Accepting
  names is deliberate: another channel with exactly the same name is an acceptable risk for a tool of
  discomfort.
- YouTube changes videos without loading a new page (a single-page app). The extension must check every change of
  address inside the tab, not only full page loads (today it only checks full loads), and cache answers by video
  id. A switch to a video from a channel that is not allowed is blocked at once.
- If the lookup fails (offline, YouTube changes), the video is blocked; the blocked page remembers it and returns to
  it at the end of the session, as for any blocked site.
- Configured in planning time by pasting a channel or playlist link (since 2026-10-23 also single videos, from the
  allow-list screen). Until list editing moves into the window (a
  later upgrade), they live in `config.json` next to the sites, for example
  `"youtube": {"channels": ["@3blue1brown"], "playlists": ["PL..."]}`. `youtube.com` in the site list still allows
  all of YouTube, as today.

### Grace period

- The first 20 seconds of every session (scheduled or "Start now"); the number is changeable in settings.
- During it, minimizing, maximizing, restoring and closing **allowed** windows does nothing: no video, no popup, no
  log line. At the end of the grace period each allowed window's state at that moment becomes its baseline.
- Programs **not** on the allow-list are minimized ("waiting") immediately when the session starts, without
  waiting for the grace period, so the user sees that the session has begun. Nothing is lost (see below).
- The emergency exit works during the grace period as always.

### The session clock (during a session)

- The calendar window turns into a small, quiet clock: the remaining time and a thin progress bar. During the grace
  period it shows a countdown ("arranging… 14") instead.
- Not always-on-top. Minimizing or closing it is free (it is the tool's own window, so it is never punished or
  logged); the session continues. Reopening the app during a session shows the clock again.
- No stop button. When the session ends, the window goes back to the calendar.

### Restart or log-off during a session

When the tool starts at login and finds a session that was running and has not reached its end, it shows the same
notification window: "Continue" (until the planned end, with the grace period) and "Not today". No phrase is
needed; ignoring the window starts nothing. This is deliberate (see the philosophy above): restarting the PC is an
uncomfortable way out, and that is enough.

### End of a session

The guard's summary popup shows only "הסשן הסתיים. כל הכבוד." with no count of attempts and no list of
force-closed programs. This replaces today's summary (`guard.format_summary`).

### Background and start-up

- The tool starts with Windows and waits in the background with a small tray icon; no window opens at login.
  Clicking the tray icon opens the window (calendar, or the clock during a session).
- The scheduler runs in this background process. The existing guard and guardian processes are unchanged (except
  the summary text, waiting instead of closing, and muting) and are started by the
  scheduler the same way the window starts them today.
- Settings has a switch for "start with Windows", on by default.

### Settings (gear)

Song library, video library, grace-period seconds, start
with Windows, and the existing items that already live in `config.json` (emergency phrase). Lists of allowed apps and sites stay in `config.json` for now. (Changed 2026-10-23: they are edited in their own
screen, see `2026-10-23-allow-list-editing-design.md`.)

### Decisions made while writing

- **Reaching the calendar during a session**: the clock has a small calendar icon (and the tray menu has "Open
  calendar") that shows the calendar with the running event highlighted. The clock stays the default view. The
  phrase box for running-event changes is the same phrase box the guard uses today.
- **Ignoring the missed-start window** (after wake or login): it waits; nothing starts by itself. A user who was not
  at the screen should not have windows minimized under them.
- **Overlapping and back-to-back events** are allowed. While one session runs, an event that starts during it does
  not start a second session. When the running session reaches its end, the scheduler at once starts a follow-on
  session until the later event's end, with no cue song, no notification window and no grace period. The guard
  therefore still reads its end time once at start.
- **"Start now"** creates a real event on the calendar from now to the chosen end, so it shows in the week; like any running event it is locked.
- **Per-occurrence outcome** is stored (declined, exited with the phrase, completed). An occurrence that was
  declined or exited is never offered again, including after a restart or wake.

### Safety nets for new users (needed before any public release, cheap to build now)

- **First run**: the shipped `config.json` already allows a browser, Windows Terminal and the tool itself, so a
  curious first "Start now" does not minimize everything. 
  No trial-only lock (the reason below no longer holds since list editing moved into the window on 2026-10-23; a
  lock stays a later decision): list editing is not in the window yet, so a
  user happy with the shipped list could never unlock it.
- **One instance**: only one background process may run (a Windows named mutex). Opening the app again, from the
  Desktop shortcut or the Start menu, just tells the running one to show its window, then exits.
- **Broken `config.json`**: a syntax error never stops the background process. It keeps the last settings that
  loaded correctly and shows a small window with the error and its line number. Scheduled sessions keep working.

## Constraints

- Windows 11, Python 3.12, existing stack: pywebview for windows, the guard/guardian/extension architecture as built.
- The week view is built on **FullCalendar** (standard, MIT-licensed packages only: timegrid, interaction, and the
  rrule plugin for repeating events), styled to look like Google Calendar (writing drag,
  resize and overlap layout from scratch is a large source of bugs). Focus Guard's own code builds the quick-create
  popover, the event card, the "this event / all events" choice, the locked running event and the busy-block
  layer. No premium FullCalendar plugin may be used. The library is bundled locally, not loaded from the internet.
  To verify at the start of the build: right-to-left (`direction: 'rtl'`) and the Hebrew locale.
- Maintainability: the calendar's HTML, CSS and JavaScript live in their own files, not as
  strings inside Python; all Python is type-annotated; `ruff check`, `ruff format --check` and `mypy` pass;
  test-first for all logic.
- Scheduling logic (recurrence, "next occurrence", missed-start, grace timing, running-event edit rules) must be pure
  and unit-tested, separate from Win32, audio and UI code, like the existing watcher and guard.
- Local time, including daylight-saving changes in Israel.
- The user works inside a Hyper-V VM and also installs the tool on the host; nothing may depend on reaching the VM.
- A virtual machine is a separate computer. The tool on the host never reaches inside a VM; whoever wants
  enforcement inside the VM installs the tool there too. This holds for any VM software. On the host the VM window
  (`vmconnect.exe` for Hyper-V) is allowed by default in the host package, so it is never minimized.
- Known and accepted: the one-minute cue window on the host can be hidden behind a full-screen VM. Since nothing
  is closed or killed any more, the worst case is that host programs not on the list wait until the session ends.

## Configuration and stored data

- Format stays JSON: it is the easiest format for the program itself to read and write,
  in Python and in the extension, with no extra libraries. Hand-editing JSON is the weak point, and the answer is to
  move editing into the window over time, not to change format. Until then `check` reports exactly what is wrong.
- Two kinds of file, never mixed:
  - `config.json`: only what the user chooses (allow-lists, YouTube channels and playlists, phrase, libraries,
    grace seconds, start with Windows). Written by the settings window and by hand.
  - Files under `state/`: only what the program manages (calendar events and per-occurrence outcomes, waiting
    windows, mute state, the running session). Never edited by hand.
- A broken hand edit of `config.json` can therefore never delete the calendar.
- One list of allowed apps and sites for all sessions. Per-session lists were considered and dropped: not worth the
  complexity.

### Build order

Each stage is usable on its own:

1. **A**: waiting instead of killing, muting, grace period (changes the existing guard first, so that automatic
   sessions are safe to use while the rest is built).
2. **B1**: scheduling logic, session clock, notification and nerd windows, tray icon, start with Windows, the
   safety nets. Testable against a hand-written events file before any calendar UI exists.
3. **B2**: the FullCalendar week view with Google styling.
4. **C**: YouTube channels and playlists.

## Left to the builder

- The shape of the JSON under
  `state/` and how recurrence is stored.
- The tray-icon library, the autostart mechanism (registry Run key or Startup folder), and how it is removed when the
  switch is turned off.
- The audio playback method. Which free (CC0) songs and videos to bundle, a handful of each.
- Exact visual details beyond "like Google Calendar", and the size and placement of the clock and notification
  windows.
