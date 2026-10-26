import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// background.js needs chrome.*, so its wiring is checked as text.
const source = readFileSync(new URL('./background.js', import.meta.url), 'utf8');

test('both navigation listeners refresh a sleeping worker before checking', () => {
  assert.match(source, /async function navigated\(tabId, url\) \{\s*if \(allowed === null\) await refreshSites\(\);\s*await check\(tabId, url\);/);
  for (const name of ['onBeforeNavigate', 'onHistoryStateUpdated']) {
    const listener = source.slice(source.indexOf(name), source.indexOf(name) + 200);
    assert.match(listener, /navigated\(details\.tabId, details\.url\)/, name);
  }
});

test('the sweep checks each tab at the address it is loading', () => {
  assert.match(source, /for \(const \{ id, url \} of tabsToCheck\(tabs, allowed\.sites\)\) await check\(id, url\);/);
});

test('the update state comes from the app bridge on port + 1 with the token only', () => {
  assert.match(source, /http:\/\/127\.0\.0\.1:\$\{FOCUS\.port \+ 1\}\/update\?token=\$\{encodeURIComponent\(FOCUS\.token\)\}/);
});

test('the extension reloads itself only when reloadDecision says so, and only there', () => {
  assert.equal(source.split('chrome.runtime.reload()').length - 1, 1);
  assert.match(source, /const decision = reloadDecision\(status\.installed, chrome\.runtime\.getManifest\(\)\.version, stored\);/);
  assert.match(source, /if \(decision\.reload\) \{\s*await chrome\.storage\.local\.set\(decision\.store\);\s*chrome\.runtime\.reload\(\);/);
});

test('the badge follows the update state on start and on every alarm', () => {
  assert.match(source, /chrome\.action\.setBadgeText\(\{ text: badgeFor\(status\) \}\)/);
  assert.match(source, /chrome\.alarms\.onAlarm\.addListener\(refreshUpdate\);/);
  assert.match(source, /\nrefreshUpdate\(\);/);
});
