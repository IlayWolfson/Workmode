import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const model = createRequire(import.meta.url)('../../focus_guard/web/calmodel.js');

test('wallClock reads local date and time', () => {
  assert.deepEqual(model.wallClock(new Date(2026, 9, 27, 9, 5)), { date: '2026-10-27', time: '09:05' });
});

test('weekly label uses the clicked weekday', () => {
  const weekly = model.repeatOptions('2026-10-27').find((o) => o.value === 'weekly');
  assert.equal(weekly.label, 'כל שבוע ביום שלישי');
  assert.deepEqual(weekly.days, [2]);
});

test('repeat options come in the Google order with their day sets', () => {
  const options = model.repeatOptions('2026-10-25');
  assert.deepEqual(options.map((o) => o.value), ['none', 'daily', 'weekly', 'weekdays', 'custom']);
  assert.deepEqual(options.map((o) => o.label), [
    'ללא חזרה', 'כל יום', 'כל שבוע ביום ראשון', 'כל יום חול (ראשון עד חמישי)', 'בהתאמה אישית…',
  ]);
  assert.deepEqual(options.map((o) => o.days), [[], [0, 1, 2, 3, 4, 5, 6], [0], [0, 1, 2, 3, 4], null]);
});

test('repeatValue maps day sets back', () => {
  assert.equal(model.repeatValue([]), 'none');
  assert.equal(model.repeatValue([6, 5, 4, 3, 2, 1, 0]), 'daily');
  assert.equal(model.repeatValue([3]), 'weekly');
  assert.equal(model.repeatValue([0, 1, 2, 3, 4]), 'weekdays');
  assert.equal(model.repeatValue([1, 3]), 'custom');
});

test('touching busy edges do not overlap', () => {
  const busy = [{ start: 11, end: 12 }];
  assert.equal(model.overlapsBusy(10, 11, busy), false);
  assert.equal(model.overlapsBusy(12, 13, busy), false);
  assert.equal(model.overlapsBusy(10, 12, [{ start: 11, end: 13 }]), true);
  assert.equal(model.overlapsBusy(10, 12, []), false);
});

test('month grid starts on Sunday and has 42 days', () => {
  const grid = model.monthGrid(2026, 9);
  assert.equal(grid.length, 6);
  assert.ok(grid.every((row) => row.length === 7));
  assert.deepEqual(grid[0][0], { date: '2026-09-27', inMonth: false });
  assert.deepEqual(grid[0][4], { date: '2026-10-01', inMonth: true });
  assert.deepEqual(grid[5][6], { date: '2026-11-07', inMonth: false });
});

test('nextSlot rounds up to the half hour', () => {
  assert.deepEqual(model.nextSlot(new Date(2026, 9, 27, 14, 10)), { date: '2026-10-27', start: '14:30', end: '15:30' });
  assert.deepEqual(model.nextSlot(new Date(2026, 9, 27, 14, 30)), { date: '2026-10-27', start: '15:00', end: '16:00' });
  assert.deepEqual(model.nextSlot(new Date(2026, 9, 27, 23, 50)), { date: '2026-10-28', start: '00:00', end: '01:00' });
});

test('oneAtATime ignores calls while the first one is pending', async () => {
  let calls = 0;
  let finish;
  const once = model.oneAtATime(() => {
    calls += 1;
    return calls === 1 ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve();
  });
  const first = once();
  assert.equal(once(), first);
  assert.equal(calls, 1);
  finish();
  await first;
  await once();
  assert.equal(calls, 2);
});

test('oneAtATime runs again after a failure', async () => {
  let calls = 0;
  const once = model.oneAtATime(() => {
    calls += 1;
    return calls === 1 ? Promise.reject(new Error('x')) : Promise.resolve();
  });
  await assert.rejects(once());
  await once();
  assert.equal(calls, 2);
});
