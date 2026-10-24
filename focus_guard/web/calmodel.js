// Pure helpers for the calendar page: dates, repeat options, busy overlap, the side panel's month grid.
// A classic script (WebView2 does not load ES modules from file://): the page gets window.FG.model,
// node's tests get module.exports.
(function (root) {
  'use strict';

  const DAY_NAMES = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'];  // Sunday first
  const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];
  const WEEKDAYS = [0, 1, 2, 3, 4];  // Sunday to Thursday

  function two(n) { return String(n).padStart(2, '0'); }

  function ymd(date) { return date.getFullYear() + '-' + two(date.getMonth() + 1) + '-' + two(date.getDate()); }

  function hhmm(date) { return two(date.getHours()) + ':' + two(date.getMinutes()); }

  // A local date from 'YYYY-MM-DD', at noon so adding days never trips over a clock change.
  function parseDay(text) {
    const [y, m, d] = text.split('-').map(Number);
    return new Date(y, m - 1, d, 12);
  }

  function wallClock(date) { return { date: ymd(date), time: hhmm(date) }; }

  function repeatOptions(day) {
    const weekday = parseDay(day).getDay();
    return [
      { value: 'none', label: 'ללא חזרה', days: [] },
      { value: 'daily', label: 'כל יום', days: ALL_DAYS.slice() },
      { value: 'weekly', label: 'כל שבוע ביום ' + DAY_NAMES[weekday], days: [weekday] },
      { value: 'weekdays', label: 'כל יום חול (ראשון עד חמישי)', days: WEEKDAYS.slice() },
      { value: 'custom', label: 'בהתאמה אישית…', days: null },
    ];
  }

  function repeatValue(days) {
    const sorted = days.slice().sort().join(',');
    if (sorted === '') { return 'none'; }
    if (sorted === ALL_DAYS.join(',')) { return 'daily'; }
    if (days.length === 1) { return 'weekly'; }
    if (sorted === WEEKDAYS.join(',')) { return 'weekdays'; }
    return 'custom';
  }

  function overlapsBusy(start, end, busy) {
    return busy.some(function (block) { return block.start < end && block.end > start; });
  }

  function monthGrid(year, month0) {
    const first = new Date(year, month0, 1, 12);
    const cursor = new Date(year, month0, 1 - first.getDay(), 12);
    const rows = [];
    for (let row = 0; row < 6; row += 1) {
      const cells = [];
      for (let col = 0; col < 7; col += 1) {
        cells.push({ date: ymd(cursor), inMonth: cursor.getMonth() === month0 });
        cursor.setDate(cursor.getDate() + 1);
      }
      rows.push(cells);
    }
    return rows;
  }

  // The next half hour strictly after `now`, one hour long.
  function nextSlot(now) {
    const minutes = now.getMinutes() < 30 ? 30 : 60;
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours(), minutes);
    const end = new Date(start.getTime() + 60 * 60 * 1000);
    return { date: ymd(start), start: hhmm(start), end: hhmm(end) };
  }

  // A click handler that ignores more clicks until its promise settles (a fast double click saves once).
  function oneAtATime(fn) {
    let pending = null;
    return function () {
      if (pending) { return pending; }
      pending = Promise.resolve(fn.apply(this, arguments)).finally(function () { pending = null; });
      return pending;
    };
  }

  const model = {
    DAY_NAMES, wallClock, repeatOptions, repeatValue, overlapsBusy, monthGrid, nextSlot, parseDay, ymd, hhmm, oneAtATime,
  };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = model;
  } else {
    root.FG = root.FG || {};
    root.FG.model = model;
  }
})(typeof window !== 'undefined' ? window : globalThis);
