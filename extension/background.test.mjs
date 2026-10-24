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
