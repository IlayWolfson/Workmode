import test from 'node:test';
import assert from 'node:assert/strict';
import { badgeFor, compareVersions, popupView, reloadDecision } from './update.js';

const clock = (seconds) => new Date(seconds * 1000).toISOString().slice(11, 16); // HH:MM in UTC
const status = (fields) => ({
  installed: '1.2.2', available: null, state: 'none', checked_at: null, blocked: null, session_until: null, result: null,
  ...fields,
});

test('versions compare by number, not by text', () => {
  assert.equal(compareVersions('1.10.0', '1.9.9'), 1);
  assert.equal(compareVersions('1.2.2', '1.2.2'), 0);
  assert.equal(compareVersions('1.2.2', '1.3.0'), -1);
});

test('a newer app reloads the extension once, then reports the wrong folder', () => {
  const first = reloadDecision('1.3.0', '1.2.2', {});
  assert.deepEqual(first, { reload: true, store: { reloadTo: '1.3.0' }, wrongFolder: false });
  const second = reloadDecision('1.3.0', '1.2.2', first.store);
  assert.deepEqual(second, { reload: false, store: null, wrongFolder: true });
});

test('a later version gets its own reload', () => {
  assert.equal(reloadDecision('1.4.0', '1.2.2', { reloadTo: '1.3.0' }).reload, true);
});

test('no reload when the versions match or the app is older', () => {
  for (const app of ['1.2.2', '1.2.1', undefined, null, 'bad']) {
    assert.deepEqual(reloadDecision(app, '1.2.2', {}), { reload: false, store: null, wrongFolder: false }, String(app));
  }
});

test('badge shows only when an update is ready', () => {
  assert.equal(badgeFor(status({ state: 'ready', available: '1.3.0' })), '!');
  for (const state of ['none', 'error', 'refused', 'applying']) assert.equal(badgeFor(status({ state })), '');
  assert.equal(badgeFor(null), '');
});

test('ready: says the versions and offers the button', () => {
  const view = popupView(status({ state: 'ready', available: '1.3.0' }), '1.2.2', false, clock);
  assert.equal(view.text, 'גרסה 1.3.0 זמינה (יש לך 1.2.2)');
  assert.deepEqual(view.button, { label: 'עדכון לגרסה העדכנית', enabled: true });
});

test('during a session the button waits for its end and is disabled', () => {
  const s = status({ state: 'ready', available: '1.3.0', blocked: 'יש סשן פעיל עד 14:00; העדכון יחכה', session_until: 1_800_000_000 + 6 * 3600 });
  const view = popupView(s, '1.2.2', false, clock);
  assert.deepEqual(view.button, { label: 'יותקן אחרי שהסשן ייגמר ב-14:00', enabled: false });
});

test('another reason to wait is shown on a disabled button', () => {
  const s = status({ state: 'ready', available: '1.3.0', blocked: 'סשן מתוכנן מתחיל ב-09:00; העדכון יחכה עד אחריו' });
  assert.deepEqual(popupView(s, '1.2.2', false, clock).button, { label: 'סשן מתוכנן מתחיל ב-09:00; העדכון יחכה עד אחריו', enabled: false });
});

test('while installing', () => {
  const view = popupView(status({ state: 'applying' }), '1.2.2', false, clock);
  assert.equal(view.text, 'מעדכן…');
  assert.equal(view.button.enabled, false);
});

test('up to date, with the last check time', () => {
  const view = popupView(status({ checked_at: 1_800_000_000 }), '1.2.2', false, clock);
  assert.equal(view.text, 'יש לך את הגרסה העדכנית');
  assert.equal(view.button, null);
  assert.equal(view.note, 'בדיקה אחרונה: 08:00');
});

test('a refused release says so and offers nothing', () => {
  const view = popupView(status({ state: 'refused', available: '1.3.0' }), '1.2.2', false, clock);
  assert.equal(view.text, 'העדכון נדחה: הוא לא חתום כמו שצריך');
  assert.equal(view.button, null);
});

test('the last result is shown', () => {
  const failed = popupView(status({ result: { ok: false, message: 'העדכון לא הצליח וחזרנו לגרסה 1.2.2 (שלב: x)' } }), '1.2.2', false, clock);
  assert.equal(failed.note, 'העדכון לא הצליח וחזרנו לגרסה 1.2.2 (שלב: x)');
  const done = popupView(status({ installed: '1.3.0', result: { ok: true, message: 'עודכן לגרסה 1.3.0' } }), '1.3.0', false, clock);
  assert.equal(done.text, 'עודכן לגרסה 1.3.0');
});

test('the app is not running', () => {
  const view = popupView(null, '1.2.2', false, clock);
  assert.match(view.text, /Update\.cmd/);
  assert.equal(view.button, null);
});

test('the extension is loaded from another folder', () => {
  const view = popupView(status({ installed: '1.3.0' }), '1.2.2', true, clock);
  assert.match(view.text, /chrome:\/\/extensions/);
  assert.match(view.text, /^Chrome טוען את התוסף מתיקייה אחרת/);
});
