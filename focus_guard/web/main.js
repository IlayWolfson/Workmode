// Main window: the session clock during a session, the calendar view otherwise. All state comes from
// pywebview.api.status(); the page only draws it. The window size follows the view (api.set_view).
'use strict';

let view = null;
let lastState = null;
let calendarDuringSession = false;
let muted = false;
let lastMarker = null;

function $(id) { return document.getElementById(id); }
function setText(id, text) { $(id).textContent = text; }
function show(id, visible) { $(id).hidden = !visible; }

function clockText(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const two = function (n) { return String(n).padStart(2, '0'); };
  return h > 0 ? h + ':' + two(m) + ':' + two(s) : two(m) + ':' + two(s);
}

function setView(next) {
  if (next === view) { return; }
  view = next;
  show('clockView', next === 'clock');
  show('calendarView', next === 'calendar');
  pywebview.api.set_view(next);
  if (next === 'calendar') { setTimeout(FG.calendar.resize, 50); }  // after the window has its new size
}

function renderClock(s) {
  setText('clockTitle', (s.title || '') + (s.live ? '' : ' (ניסיון)'));
  setText('remaining', clockText(s.seconds_left));
  $('barFill').style.width = Math.round(s.progress * 1000) / 10 + '%';
  setText('clockNote', s.grace_left > 0 ? 'מסדרים… ' + s.grace_left : 'עד ' + s.ends_at);
  const waiting = s.waiting || [];
  muted = !!s.muted;
  setText('waitingLine', waiting.length ? 'בהמתנה: ' + waiting.join(', ') : '');
  setText('mute', muted ? 'ביטול השתקה' : 'השתקת תוכנות בהמתנה');
  show('waitBox', s.live && (waiting.length > 0 || muted));
  show('stalledBox', !!s.stalled);
}

// The week view refetches only when the events file or the running session changed, and once a minute
// (an occurrence that just ended can no longer be dragged).
function maybeRefetch(s) {
  const marker = [s.events_version, s.occurrence || '', s.state, Math.floor(Date.now() / 60000)].join('|');
  if (marker !== lastMarker) {
    lastMarker = marker;
    FG.calendar.refetch();
  }
}

function renderCalendar(s) {
  const running = s.state === 'running';
  show('problem', s.state === 'problem');
  setText('problem', s.state === 'problem' ? 'יש בעיה בהגדרות: ' + (s.message || '') : '');
  show('toClock', running);
  setText('toClock', running ? 'פועל עד ' + s.ends_at + ' · חזרה לשעון' : '');
  show('createNow', s.state === 'ready');
  show('gear', !running);  // settings are locked during a session
  show('sideGear', !running);
  show('sideAllowed', !running);  // so is the allow-list
  if (running) { FG.settings.close(); FG.allowed.close(); }
  show('configError', !!s.config_error);
  setText('configError', s.config_error ? 'יש שגיאה ב-config.json: ' + s.config_error : '');
  setText('hint', s.hint || '');
  maybeRefetch(s);
}

function render(s) {
  if (s.state === 'running') {
    if (lastState !== 'running') { calendarDuringSession = false; }
    renderClock(s);
    renderCalendar(s);
    setView(calendarDuringSession ? 'calendar' : 'clock');
  } else {
    calendarDuringSession = false;
    renderCalendar(s);
    setView('calendar');
  }
  lastState = s.state;
}

function refresh() { pywebview.api.status().then(render); }

// Called by the tray menu ("יומן"): the calendar view, even during a session.
function openCalendar() { calendarDuringSession = true; refresh(); }

function openStartNow() {
  show('createMenu', false);
  setText('nowMsg', '');
  show('nowDialog', true);
  $('minutes').focus();
}

function startNow() {
  setText('nowMsg', '');
  pywebview.api.start($('minutes').value, $('nowLive').checked).then(function (r) {
    if (!r.ok) { setText('nowMsg', r.message); return; }
    show('nowDialog', false);
    refresh();
  });
}

window.addEventListener('pywebviewready', function () {
  FG.calendar.init();
  FG.form.init();
  FG.card.init();
  FG.settings.init();
  FG.allowed.init();
  $('create').onclick = function () { show('createMenu', $('createMenu').hidden); };
  $('createNow').onclick = openStartNow;
  $('nowStart').onclick = startNow;
  $('nowCancel').onclick = function () { show('nowDialog', false); };
  $('resume').onclick = function () { pywebview.api.resume().then(refresh); };
  $('mute').onclick = function () {
    (muted ? pywebview.api.unmute_waiting() : pywebview.api.mute_waiting()).then(refresh);
  };
  $('toCalendar').onclick = function () { calendarDuringSession = true; refresh(); };
  $('toClock').onclick = function () { calendarDuringSession = false; refresh(); };
  refresh();
  setInterval(refresh, 1000);
});
