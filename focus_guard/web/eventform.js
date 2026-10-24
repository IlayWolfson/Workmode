// The quick-create popover, which "אפשרויות נוספות" (or "בהתאמה אישית…") expands into the full form. The same
// form edits an event from its card. Every rule (past, too long, running, series split) is checked in Python;
// the popover only shows the message it gets back.
(function () {
  'use strict';

  const model = window.FG.model;
  const DAY_LETTERS = ['א׳', 'ב׳', 'ג׳', 'ד׳', 'ה׳', 'ו׳', 'ש׳'];
  const DAY_TITLE = new Intl.DateTimeFormat('he', { weekday: 'long', day: 'numeric', month: 'long' });
  const MARGIN = 12;
  const HOUR_MS = 60 * 60 * 1000;

  let mode = 'create';  // or 'edit'
  let editKey = '';
  let editRepeating = false;
  let anchor = null;  // where the popover opened: {x, y} in the window, or null for the middle

  function $(id) { return document.getElementById(id); }

  function epoch(day, hhmm) {
    const date = model.parseDay(day);
    const [h, m] = hhmm.split(':').map(Number);
    date.setHours(h, m, 0, 0);
    return date.getTime();
  }

  function range() {
    const start = epoch($('fDate').value, $('fStart').value);
    let end = epoch($('fDate').value, $('fEnd').value);
    if (end <= start) { end += 24 * HOUR_MS; }  // an end at or before the start means the next day
    return { start: start, end: end };
  }

  function buildDays() {
    const box = $('fDays');
    box.replaceChildren();
    DAY_LETTERS.forEach(function (letter, day) {
      const label = document.createElement('label');
      const tick = document.createElement('input');
      tick.type = 'checkbox';
      tick.value = String(day);
      label.append(tick, letter);
      box.append(label);
    });
  }

  function checkedDays() {
    return Array.from($('fDays').querySelectorAll('input:checked')).map(function (tick) { return Number(tick.value); });
  }

  function setDays(days) {
    $('fDays').querySelectorAll('input').forEach(function (tick) { tick.checked = days.indexOf(Number(tick.value)) >= 0; });
  }

  function fillRepeat(selected) {
    const select = $('fRepeat');
    select.replaceChildren();
    model.repeatOptions($('fDate').value).forEach(function (option) {
      const item = document.createElement('option');
      item.value = option.value;
      item.textContent = option.label;
      select.append(item);
    });
    select.value = selected;
  }

  function repeatDays() {
    const value = $('fRepeat').value;
    if (value === 'custom') { return checkedDays(); }
    return model.repeatOptions($('fDate').value).find(function (option) { return option.value === value; }).days;
  }

  function showWhen() {
    const time = document.createElement('span');
    time.dir = 'ltr';
    time.textContent = $('fStart').value + ' – ' + $('fEnd').value;
    $('fWhen').replaceChildren(DAY_TITLE.format(model.parseDay($('fDate').value)) + ' · ', time);
    const span = range();
    $('fBusy').hidden = !model.overlapsBusy(span.start, span.end, FG.calendar.busyBlocks());
  }

  // Next to the click, inside the window (Google puts it beside the slot).
  function place() {
    const pop = $('popover');
    const point = anchor || { x: innerWidth / 2 + pop.offsetWidth / 2, y: innerHeight / 4 };
    let left = point.x - pop.offsetWidth - MARGIN;
    if (left < MARGIN) { left = Math.min(point.x + MARGIN, innerWidth - pop.offsetWidth - MARGIN); }
    const top = Math.max(MARGIN, Math.min(point.y - 40, innerHeight - pop.offsetHeight - MARGIN));
    pop.style.left = Math.max(MARGIN, left) + 'px';
    pop.style.top = top + 'px';
  }

  function expand() {
    $('fMore').hidden = false;
    $('fMoreBtn').hidden = true;
    place();
  }

  function open(fields, point, repeat) {
    anchor = point || null;
    $('fTitle').value = fields.title || '';
    $('fDate').value = fields.date;
    $('fStart').value = fields.start;
    $('fEnd').value = fields.end;
    setDays(fields.days || []);
    fillRepeat(repeat);
    $('fCue').checked = fields.cue !== false;
    $('fLive').checked = fields.live !== false;
    $('fTrial').checked = fields.live === false;
    $('fMsg').textContent = '';
    $('fMore').hidden = true;
    $('fMoreBtn').hidden = false;
    $('popover').hidden = false;
    showWhen();
    place();
    $('fTitle').focus();
  }

  function openCreate(slot, point) {
    mode = 'create';
    editKey = '';
    editRepeating = false;
    open({ date: slot.date, start: slot.start, end: slot.end, days: [] }, point, 'none');
  }

  function openEdit(event, point) {
    const props = event.extendedProps;
    mode = 'edit';
    editKey = event.id;
    editRepeating = props.repeating;
    open(props.fields, point, model.repeatValue(props.fields.days));
    expand();
  }

  function close() {
    $('popover').hidden = true;
    FG.calendar.unselect();
  }

  function collect() {
    return {
      title: $('fTitle').value.trim(),
      date: $('fDate').value,
      start: $('fStart').value,
      end: $('fEnd').value,
      days: repeatDays(),
      cue: $('fCue').checked,
      live: $('fLive').checked,
    };
  }

  // One save at a time: a second click while the scope question or the call is pending does nothing.
  const save = model.oneAtATime(function () {
    const fields = collect();
    const ask = mode === 'edit' && editRepeating ? FG.scope('edit') : Promise.resolve('this');
    return ask.then(function (scope) {
      if (scope === null) { return; }
      return pywebview.api.save_event(fields, editKey, scope).then(function (result) {
        if (!result.ok) { $('fMsg').textContent = result.message; return; }
        close();
        FG.calendar.refetch();
      });
    });
  });

  function onSelect(info) {
    const start = info.start;
    let end = info.end;
    if (end - start <= 30 * 60 * 1000) { end = new Date(start.getTime() + HOUR_MS); }  // a click: one hour, as in Google
    const a = model.wallClock(start);
    const b = model.wallClock(end);
    const point = info.jsEvent ? { x: info.jsEvent.clientX, y: info.jsEvent.clientY } : null;
    openCreate({ date: a.date, start: a.time, end: b.time }, point);
  }

  function init() {
    buildDays();
    FG.calendar.option('selectable', true);
    FG.calendar.option('selectMirror', true);
    FG.calendar.option('unselectAuto', false);
    FG.calendar.option('selectAllow', function (info) { return info.end > new Date(); });
    FG.calendar.option('select', onSelect);
    $('popClose').onclick = close;
    $('fSave').onclick = save;
    $('fMoreBtn').onclick = expand;
    $('fRepeat').onchange = function () {
      if ($('fRepeat').value !== 'custom') { return; }
      if (checkedDays().length === 0) { setDays([model.parseDay($('fDate').value).getDay()]); }
      expand();
    };
    $('fDate').onchange = function () { fillRepeat($('fRepeat').value); showWhen(); };
    $('fStart').onchange = showWhen;
    $('fEnd').onchange = showWhen;
    $('popover').addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { close(); }
      if (event.key === 'Enter' && event.target.id === 'fTitle') { save(); }
    });
    $('createEvent').onclick = function () {
      $('createMenu').hidden = true;
      openCreate(model.nextSlot(new Date()), null);
    };
  }

  window.FG.form = { init: init, openCreate: openCreate, openEdit: openEdit, close: close };
})();
