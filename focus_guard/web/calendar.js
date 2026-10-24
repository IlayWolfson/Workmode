// The week view: FullCalendar set up like Google Calendar (right to left, Hebrew, Sunday first), the top bar and
// the side panel's month. Occurrences and busy blocks come from pywebview.api.week(); nothing is computed here.
(function () {
  'use strict';

  const model = window.FG.model;
  const SHORT_DAYS = ['א׳', 'ב׳', 'ג׳', 'ד׳', 'ה׳', 'ו׳', 'ש׳'];
  const MONTH_TITLE = new Intl.DateTimeFormat('he', { month: 'long', year: 'numeric' });
  const TIME_FORMAT = { hour: '2-digit', minute: '2-digit', hour12: false };
  const TOAST_MS = 4000;

  let calendar = null;
  let busy = [];
  let shownMonth = null;  // {year, month0} of the side panel's month
  let toastTimer = null;

  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  function dayHeader(arg) {
    const number = el('span', 'day-num' + (arg.isToday ? ' today' : ''), String(arg.date.getDate()));
    return { domNodes: [el('span', 'day-name', SHORT_DAYS[arg.date.getDay()]), number] };
  }

  function eventContent(arg) {
    if (arg.event.display === 'background') { return { domNodes: [] }; }
    const props = arg.event.extendedProps;
    const trial = props.fields && !props.fields.live ? ' (ניסיון)' : '';
    const title = el('div', 'ev-title', (props.running ? '🔒 ' : '') + (arg.event.title || 'סשן') + trial);
    const time = el('div', 'ev-time', arg.timeText);
    time.dir = 'ltr';  // "10:00 - 11:30" would read backwards inside right-to-left text
    return { domNodes: [title, time] };
  }

  function load(info, ok, fail) {
    pywebview.api.week(info.start.getTime(), info.end.getTime()).then(function (items) {
      busy = items.filter(function (item) { return item.display === 'background'; })
        .map(function (item) { return { start: item.start, end: item.end }; });
      ok(items);
    }, fail);
  }

  function shownWeek() {
    const view = calendar.view;
    return { first: model.ymd(view.currentStart), last: model.ymd(new Date(view.currentEnd.getTime() - 1)) };
  }

  function miniHead() {
    const head = el('div', 'mini-head');
    const before = el('button', 'round small', '›');
    const after = el('button', 'round small', '‹');
    before.title = 'החודש הקודם';
    after.title = 'החודש הבא';
    before.onclick = function () { stepMonth(-1); };
    after.onclick = function () { stepMonth(1); };
    const title = MONTH_TITLE.format(new Date(shownMonth.year, shownMonth.month0, 1));
    head.append(el('span', 'mini-title', title), before, after);
    return head;
  }

  function renderMini() {
    const today = model.ymd(new Date());
    const week = shownWeek();
    const grid = el('div', 'mini-grid');
    SHORT_DAYS.forEach(function (name) { grid.append(el('span', 'mini-day', name)); });
    model.monthGrid(shownMonth.year, shownMonth.month0).forEach(function (row) {
      row.forEach(function (cell) {
        const button = el('button', 'mini-cell', String(model.parseDay(cell.date).getDate()));
        if (!cell.inMonth) { button.classList.add('out'); }
        if (cell.date >= week.first && cell.date <= week.last) { button.classList.add('week'); }
        if (cell.date === today) { button.classList.add('today'); }
        button.onclick = function () { calendar.gotoDate(model.parseDay(cell.date)); };
        grid.append(button);
      });
    });
    $('mini').replaceChildren(miniHead(), grid);
  }

  function stepMonth(step) {
    const moved = new Date(shownMonth.year, shownMonth.month0 + step, 1);
    shownMonth = { year: moved.getFullYear(), month0: moved.getMonth() };
    renderMini();
  }

  function datesSet(info) {
    $('rangeTitle').textContent = info.view.title;
    const start = info.view.currentStart;
    shownMonth = { year: start.getFullYear(), month0: start.getMonth() };
    renderMini();
  }

  function init() {
    const scroll = new Date(Date.now() - 60 * 60 * 1000);
    calendar = new FullCalendar.Calendar($('calendar'), {
      locale: 'he',
      direction: 'rtl',
      initialView: 'timeGridWeek',
      firstDay: 0,
      headerToolbar: false,
      allDaySlot: false,
      nowIndicator: true,
      slotDuration: '00:30:00',
      slotLabelInterval: '01:00',
      snapDuration: '00:15:00',
      slotLabelFormat: TIME_FORMAT,
      eventTimeFormat: TIME_FORMAT,
      scrollTime: model.hhmm(scroll) + ':00',
      height: '100%',
      dayHeaderContent: dayHeader,
      eventContent: eventContent,
      events: load,
      datesSet: datesSet,
    });
    calendar.render();
    $('today').onclick = function () { calendar.today(); };
    $('prev').onclick = function () { calendar.prev(); };
    $('next').onclick = function () { calendar.next(); };
  }

  function toast(message) {
    const box = $('toast');
    box.textContent = message;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.hidden = true; }, TOAST_MS);
  }

  window.FG.calendar = {
    init: init,
    refetch: function () { if (calendar) { calendar.refetchEvents(); } },
    resize: function () { if (calendar) { calendar.updateSize(); } },
    gotoDate: function (day) { calendar.gotoDate(model.parseDay(day)); },
    select: function (start, end) { calendar.select(start, end); },
    unselect: function () { if (calendar) { calendar.unselect(); } },
    option: function (name, value) { calendar.setOption(name, value); },
    busyBlocks: function () { return busy; },
  };
  window.FG.toast = toast;
})();
