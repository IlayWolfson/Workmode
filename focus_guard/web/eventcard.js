// The event card (edit, delete; the running event's "יציאת חירום"), the Google-style "this event / all events"
// dialog for a series, and dragging and resizing. Python refuses what is not allowed; a refused drag snaps back.
(function () {
  'use strict';

  const model = window.FG.model;
  const DAY_TITLE = new Intl.DateTimeFormat('he', { weekday: 'long', day: 'numeric', month: 'long' });
  const MARGIN = 12;

  let shown = null;  // the FullCalendar event whose card is open
  let shownAt = null;  // where it was clicked

  function $(id) { return document.getElementById(id); }

  let pendingScope = null;  // the open question's finish(); a new question cancels it, so no caller waits forever

  function scope(kind) {
    if (pendingScope) { pendingScope(null); }
    $('scopeTitle').textContent = kind === 'delete' ? 'מחיקת אירוע חוזר' : 'עריכת אירוע חוזר';
    $('scopeThis').checked = true;
    $('scopeDialog').hidden = false;
    return new Promise(function (resolve) {
      function finish(answer) {
        pendingScope = null;
        $('scopeDialog').hidden = true;
        $('scopeOk').onclick = null;
        $('scopeCancel').onclick = null;
        resolve(answer);
      }
      pendingScope = finish;
      $('scopeOk').onclick = function () { finish($('scopeAll').checked ? 'all' : 'this'); };
      $('scopeCancel').onclick = function () { finish(null); };
    });
  }

  function repeatLabel(fields) {
    if (fields.days.length === 0) { return ''; }
    const value = model.repeatValue(fields.days);
    if (value === 'custom') {
      return 'בימים ' + fields.days.map(function (day) { return model.DAY_NAMES[day]; }).join(', ');
    }
    return model.repeatOptions(fields.date).find(function (option) { return option.value === value; }).label;
  }

  function place(point) {
    const card = $('card');
    let left = point.x - card.offsetWidth - MARGIN;
    if (left < MARGIN) { left = Math.min(point.x + MARGIN, innerWidth - card.offsetWidth - MARGIN); }
    card.style.left = Math.max(MARGIN, left) + 'px';
    card.style.top = Math.max(MARGIN, Math.min(point.y - 40, innerHeight - card.offsetHeight - MARGIN)) + 'px';
  }

  function open(event, point) {
    const props = event.extendedProps;
    const trial = props.fields.live ? '' : ' (ניסיון)';
    const time = document.createElement('span');
    time.dir = 'ltr';
    time.textContent = model.hhmm(event.start) + ' – ' + model.hhmm(event.end);
    shown = event;
    shownAt = point;
    FG.form.close();
    $('cardTitle').textContent = (props.running ? '🔒 ' : '') + (event.title || 'סשן') + trial;
    $('cardWhen').replaceChildren(DAY_TITLE.format(event.start) + ' · ', time);
    $('cardRepeat').textContent = repeatLabel(props.fields);
    $('cardRunning').hidden = !props.running;
    $('cardRunning').textContent = props.running ? 'פועל עד ' + model.hhmm(event.end) : '';
    $('cardEdit').hidden = props.running || props.past;
    $('cardDelete').hidden = props.running;
    $('cardExit').hidden = !props.running;
    $('card').hidden = false;
    place(point);
  }

  function close() {
    $('card').hidden = true;
    shown = null;
  }

  function remove() {
    const event = shown;
    close();
    const ask = event.extendedProps.repeating ? scope('delete') : Promise.resolve('this');
    ask.then(function (answer) {
      if (answer === null) { return; }
      pywebview.api.delete_event(event.id, answer).then(function (result) {
        if (!result.ok) { FG.toast(result.message); }
        FG.calendar.refetch();
      });
    });
  }

  function edit() {
    const event = shown;
    const point = shownAt;
    close();
    FG.form.openEdit(event, point);
  }

  function exit() {
    pywebview.api.emergency_exit().then(close);
  }

  // A drag or a resize. The calendar already shows the new place; a refusal puts the event back.
  function moved(info) {
    const event = info.event;
    close();
    const ask = event.extendedProps.repeating ? scope('edit') : Promise.resolve('this');
    ask.then(function (answer) {
      if (answer === null) { info.revert(); return; }
      const start = model.wallClock(event.start);
      const end = model.wallClock(event.end);
      pywebview.api.move_event(event.id, start.date, start.time, end.time, answer, end.date).then(function (result) {
        if (!result.ok) {
          info.revert();
          FG.toast(result.message);
        }
        FG.calendar.refetch();
      });
    });
  }

  function clicked(info) {
    if (info.event.display === 'background') { return; }
    open(info.event, { x: info.jsEvent.clientX, y: info.jsEvent.clientY });
  }

  function init() {
    FG.calendar.option('editable', true);
    FG.calendar.option('eventClick', clicked);
    FG.calendar.option('eventDrop', moved);
    FG.calendar.option('eventResize', moved);
    $('cardClose').onclick = close;
    $('cardDelete').onclick = remove;
    $('cardEdit').onclick = edit;
    $('cardExit').onclick = exit;
    $('card').addEventListener('keydown', function (event) { if (event.key === 'Escape') { close(); } });
  }

  window.FG.scope = scope;
  window.FG.card = { init: init, close: close };
})();
