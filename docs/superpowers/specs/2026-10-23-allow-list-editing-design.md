# Focus Guard: editing what is allowed, from the window

Builds on
`2026-10-21-calendar-scheduler-design.md`; where the two differ, this one wins.

## Why

Today the allowed apps, sites and YouTube channels/playlists can only be changed by hand in `config.json`, which
is hard to find and easy to break. The allow-list is one of the most important settings, so a new user must be able to change it without
help, and the screen itself must show how.

## Goals

- A separate screen, "מה מותר בסשן", reached from a second button in the calendar's side panel, under "⚙ הגדרות".
  It is not part of the settings panel (that one is already full).
- Three tabs: **תוכנות**, **אתרים**, **יוטיוב**, each with a count of what is allowed.
- Every tab shows what is allowed now, each item with ✕ to remove it, and a way to add.
- Each tab explains itself in a hint line (what to type or paste), so no outside instructions are needed.
- Every add and remove is saved at once ("✓ נשמר"); there is no save button.
- Locked during a session, like the settings.
- Signing in to an allowed site works, even when the sign-in page is on another domain.

## Non-goals

- Per-session lists (still one list for all sessions, as decided before).
- Editing `protected_processes`, `launch` arguments, or any other config key from this screen.
- A full list of every installed program (too heavy).

## Anti-goals

- An escape hatch: nothing on this screen can be reached or changed while a session runs, and the sign-in rule must
  not open a way to other sites.
- Overwriting a hand edit: if `config.json` is broken, the screen refuses to save (same rule as the settings).
- A game-like look. It follows the calendar's existing Google-Calendar style.

## Behaviour

### Entry and locking

- A button "✅ מה מותר בסשן" in the side panel, under the blue "⚙ הגדרות" button: white with a blue border, so it
  does not compete with the settings button (seen and accepted in the preview mockup).
- During a session the button is hidden, like the settings button today, and the panel closes if open. The API
  refuses every change during a session too (`SESSION_LOCKED`), so a hidden button is not the only lock.
- The panel is a dialog like the settings panel, about 460 px wide, scrolls if the window is short; Escape closes it.

### Tab: תוכנות (apps)

From top to bottom:

1. **מותר עכשיו**: the allowed apps by friendly name, each with ✕.
2. **פתוחות עכשיו במחשב**: programs that have a visible window right now and are not yet allowed, each with
   "+ הוספה". Not shown: already allowed apps, the tool itself, and protected/system processes.
3. **תוכנה אחרת**: one dashed drop box with a text field, hint "הקלד שם תוכנה, או גרור לכאן קובץ / קיצור דרך".
   - Typing shows up to 5 matching installed programs under the box, each with "+ הוספה". Source: the Start menu
     shortcuts (all users and current user). The full list is never shown, only matches (a full list is too heavy).
   - Dropping an `.exe` or a shortcut (`.lnk`) onto the box adds that program.
- The user never sees process names or paths. Adding stores `{"process": "<name>.exe", "launch": ["<full path>"]}`,
  taken from the running process, the shortcut's target, or the dropped file.
- An app already in the list keeps its entry exactly as it is (for example Chrome with its profile arguments).
- Friendly name: the program's file description from its version info (for example "Google Chrome"), else the
  process name without `.exe`. Computed when shown; nothing extra is stored in `config.json` (the config schema stays
  as it is).
- The last app cannot be removed (`allowed_apps` must not be empty); its ✕ is disabled with a short tooltip.

### Tab: אתרים (sites)

1. **הוספת אתר**: a drop box with a field, hint "הדבק קישור לאתר". Pasting a link or typing a domain shows a choice:
   - (•) **האתר `uni.ac.il` וכל מה שמתחתיו**: stores the host without `www.` (default). The line spells out what
     it covers, for example "כולל moodle.uni.ac.il".
   - ( ) **כל כתובת שמכילה את המילה**: an editable word, stored as `*word*`.
   Then "הוספה".
2. **מותר עכשיו**: the list, each with ✕. Word entries are shown as "מילה: uni".
- **Word rule change:** a word needs at least 3 English letters (a-z); digits and `-` are allowed
  on top of those. `uni` and `uni2` pass; `a1b` and `123` do not. Today's rule (4+ characters) in
  `focus_guard/config.py` (`WORD_SITE_RE`) changes to this one; the extension's matching is unchanged.
- A bad entry shows a clear Hebrew message under the field and nothing is saved.
- A duplicate is not added twice; the field says it is already allowed.

### Signing in to an allowed site (new)

- The rule: "login is included in an allowed site." Example: Moodle at `uni.ac.il` sends the user to
  `login.microsoftonline.com` to sign in; that page must open during a session without adding it by hand.
- A short built-in list of sign-in hosts (Microsoft, Google, and similar), allowed only when
  the tab arrives there from an allowed site (redirect or link in the same tab); opened directly, they stay blocked.
  The exact list and the "arrived from" check are settled in the plan.

### Tab: יוטיוב (YouTube)

1. **הוספה מיוטיוב**: a drop box, hint "הדבק קישור לסרטון, ערוץ או פלייליסט". After pasting, "מה להתיר?" offers only
   what the link allows:
   - 📺 **כל הערוץ: <channel name>**: for a channel link, or a video link (the channel is looked up).
   - 📃 **כל הפלייליסט: <playlist title>**: when the link has `list=` or is a playlist link.
   - ▶ **רק הסרטון הזה: <video title>**: for a video link. **New:** single videos can be allowed.
   The first offered choice is selected; then "הוספה".
2. **מותר עכשיו**: "ערוץ: …", "פלייליסט: …", "סרטון: …", each with ✕.
- Names and titles come from YouTube's public oEmbed address (no key), looked up by the Python side when adding. If
  the lookup fails (offline), a channel or playlist link is still added under its handle or id; a video link can
  still be added as "רק הסרטון הזה", and "כל הערוץ" says it needs a connection.
- Titles are only for display: they are cached under `state/` (program-managed), never in `config.json`. If a title
  is missing, the raw handle or id is shown.

### Single videos (new, extension and config)

- `config.json` gains `"youtube": {"channels": [...], "playlists": [...], "videos": [...]}`; `videos` holds 11-char
  video ids. `focus_guard/youtube.py` accepts a video id or any video link and normalizes to the id; `check` counts
  them.
- The bridge sends the video ids with the other lists. The extension allows `watch?v=<id>` and `youtu.be/<id>` when
  the id is on the list, without a channel lookup. Shorts stay blocked.

### Saving

- Every add and remove goes through the same safe path as the settings (`focus_guard/settings.py`): refused during a
  session, refused while `config.json` is broken, the new file is checked with `load_config` before it replaces the
  old one, and other keys (and the phrase) are kept as they are.
- After a save the panel reloads its lists from the file, so what is shown is what is stored.
- A change takes effect from the next session (the guard and extension read the lists at session start, as today).

## Constraints

- Same as the calendar design: Windows 11, Python 3.12, pywebview (6.2.1 installed); HTML, CSS and JS in their own
  files under `focus_guard/web/`; all Python typed; `ruff check`, `ruff format --check`, `mypy` pass; tests first
  for all logic. Node tests: `node --test extension/*.test.mjs "tests/js/*.test.mjs"`.
- Logic (link parsing, the choices a link offers, the word rule, adding/removing entries, the list of open programs
  minus allowed and protected ones, Start-menu matching, the sign-in rule) is pure and unit-tested, separate from
  Win32 and UI code, behind small adapters like the existing `ports.py`.
- No new third-party package unless needed; pywin32 is already present (shortcut targets, version info, windows).

## Changes to the earlier design

- "Settings (gear)": "Lists of allowed apps and sites stay in `config.json` for now" no longer holds; they are edited
  in this screen.
- "Safety nets / First run": the reason given for no trial-only lock ("list editing is not in the window yet") is
  gone. No lock is added now; that stays a later decision.
- "YouTube channels and playlists": single videos can now be allowed too.

## Decisions made while writing

- Instant save, no save button.
- The entry button is hidden during a session (the API also refuses).
- Friendly app names are computed when shown, not stored.
- YouTube titles are cached under `state/`, not in `config.json`.
- Up to 5 Start-menu matches while typing.
- The last allowed app cannot be removed.

## Left to the builder

- How the open-programs list is gathered (top-level visible windows → process → exe path) and which system processes
  to hide beyond `protected_processes` and the tool itself.
- Store apps (for example Claude from `WindowsApps`): use the running process path when open; if a Start-menu entry
  has no `.lnk` target, it may be left out of the matches.
- How pywebview passes a dropped file's full path to Python.
- Layout details, as long as they match the approved mockup (three tabs, drop boxes, the "מה להתיר?" box).
