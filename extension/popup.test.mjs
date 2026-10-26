import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// popup.js needs chrome.* and a page, so its wiring is checked as text.
const script = readFileSync(new URL('./popup.js', import.meta.url), 'utf8');
const page = readFileSync(new URL('./popup.html', import.meta.url), 'utf8');

test('the button sends only the token', () => {
  assert.match(script, /body: JSON\.stringify\(\{ token: FOCUS\.token \}\)/);
  assert.equal(script.split('JSON.stringify(').length - 1, 1);
});

test('text from the app is never inserted as HTML', () => {
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
  assert.match(script, /\.textContent = /);
});

test('the page is right-to-left Hebrew and loads only its own module', () => {
  assert.match(page, /<html lang="he" dir="rtl">/);
  assert.match(page, /<script type="module" src="popup\.js"><\/script>/);
  assert.equal(page.split('<script').length - 1, 1);
});
