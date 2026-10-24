import test from 'node:test';
import assert from 'node:assert/strict';
import { hostAllowed, isAllowedUrl, tabsToCheck, blockedPageUrl, returnTarget } from './allowed.js';

const SITES = ['github.com', 'docs.python.org', 'claude.ai'];

test('exact and subdomain hosts match', () => {
  for (const host of ['github.com', 'gist.github.com', 'DOCS.PYTHON.ORG', 'github.com.']) {
    assert.equal(hostAllowed(host, SITES), true, host);
  }
});

test('lookalike hosts do not match', () => {
  for (const host of ['evilgithub.com', 'github.com.evil.example', 'notclaude.ai', 'python.org', '']) {
    assert.equal(hostAllowed(host, SITES), false, host);
  }
});

test('http and https follow the host rule', () => {
  assert.equal(isAllowedUrl('https://github.com/anthropics', SITES), true);
  assert.equal(isAllowedUrl('http://docs.python.org/3/', SITES), true);
  assert.equal(isAllowedUrl('https://www.youtube.com/watch?v=1', SITES), false);
});

test('the userinfo trick uses the real host', () => {
  assert.equal(isAllowedUrl('https://github.com@evil.example/x', SITES), false);
});

test('browser internal pages are allowed', () => {
  for (const url of ['chrome://newtab/', 'about:blank', 'chrome-extension://abc/blocked.html', 'file:///C:/notes.txt']) {
    assert.equal(isAllowedUrl(url, SITES), true, url);
  }
});

test('other schemes and junk are blocked', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,hi', 'ftp://github.com/x', '', '   ', 'not a url']) {
    assert.equal(isAllowedUrl(url, SITES), false, url);
  }
});

test('an empty site list blocks every website', () => {
  assert.equal(isAllowedUrl('https://github.com/', []), false);
});

test('tabsToCheck picks only tabs on disallowed sites', () => {
  const tabs = [
    { id: 1, url: 'https://github.com/x' },
    { id: 2, url: 'https://www.youtube.com/watch?v=1' },
    { id: 3, url: 'chrome://newtab/' },
    { id: 4 },
    { id: 5, url: 'https://news.example/' },
    { url: 'https://www.youtube.com/' },
  ];
  assert.deepEqual(tabsToCheck(tabs, SITES), [
    { id: 2, url: 'https://www.youtube.com/watch?v=1' },
    { id: 5, url: 'https://news.example/' },
  ]);
  assert.deepEqual(tabsToCheck(tabs, null), []);
});

test('tabsToCheck uses the address a tab is loading', () => {
  const tabs = [
    { id: 1, url: 'https://docs.python.org/3/', pendingUrl: 'https://www.youtube.com/watch?v=abc' },
    { id: 2, url: 'https://www.youtube.com/watch?v=abc', pendingUrl: 'https://docs.python.org/3/' },
  ];
  assert.deepEqual(tabsToCheck(tabs, SITES), [{ id: 1, url: 'https://www.youtube.com/watch?v=abc' }]);
});

test('the blocked page remembers the original address', () => {
  const page = blockedPageUrl('chrome-extension://abc/blocked.html', 'https://www.youtube.com/watch?v=1&t=5');
  const search = new URL(page).search;
  assert.equal(returnTarget(search), 'https://www.youtube.com/watch?v=1&t=5');
});

test('only http and https addresses can be returned to', () => {
  for (const bad of ['javascript:alert(1)', 'chrome://settings', 'file:///C:/x', 'data:text/html,hi', 'not a url', '']) {
    const search = '?u=' + encodeURIComponent(bad);
    assert.equal(returnTarget(search), null, bad);
  }
  assert.equal(returnTarget(''), null);
  assert.equal(returnTarget('?x=1'), null);
});

test('a starred word matches any host containing it', () => {
  const sites = ['*portfolio*'];
  for (const host of ['portfolio.github.io', 'www.portfolio.com', 'my-portfolio.netlify.app']) {
    assert.equal(hostAllowed(host, sites), true, host);
  }
  for (const host of ['github.io', 'example.com', 'port.folio.com', '']) {
    assert.equal(hostAllowed(host, sites), false, host);
  }
  assert.equal(isAllowedUrl('https://example.com/portfolio', sites), false);
});
