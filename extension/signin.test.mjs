import test from 'node:test';
import assert from 'node:assert/strict';
import { SIGN_IN_HOSTS, isSignInUrl, createSignInTrail } from './signin.js';

function memory() {
  const data = new Map();
  return { get: async (key) => data.get(key), set: async (key, value) => void data.set(key, value) };
}

test('sign-in is allowed only after an allowed site', async () => {
  const trail = createSignInTrail(memory());
  assert.equal(await trail.mayEnter(1), false); // opened directly: blocked
  await trail.settle(1, true, 'https://moodle.uni.ac.il/');
  assert.equal(await trail.mayEnter(1), true);
  await trail.settle(1, true, 'https://login.microsoftonline.com/x'); // still trusted inside the sign-in flow
  assert.equal(await trail.mayEnter(1), true);
  await trail.settle(1, false, 'https://reddit.com/');
  assert.equal(await trail.mayEnter(1), false);
});

test('a popup opened from a trusted tab is trusted', async () => {
  const trail = createSignInTrail(memory());
  await trail.settle(1, true, 'https://uni.ac.il/');
  await trail.opened(1, 2);
  assert.equal(await trail.mayEnter(2), true);
  await trail.opened(3, 4);
  assert.equal(await trail.mayEnter(4), false);
});

test('a closed tab is forgotten', async () => {
  const trail = createSignInTrail(memory());
  await trail.settle(1, true, 'https://uni.ac.il/');
  await trail.forget(1);
  assert.equal(await trail.mayEnter(1), false);
});

test('trust survives the service worker sleeping', async () => {
  const store = memory();
  await createSignInTrail(store).settle(7, true, 'https://uni.ac.il/');
  assert.equal(await createSignInTrail(store).mayEnter(7), true); // a fresh worker reads the same session store
});

test('only exact sign-in hosts over https count', () => {
  assert.equal(isSignInUrl('https://accounts.google.com/signin'), true);
  assert.equal(isSignInUrl('https://LOGIN.microsoftonline.com/common/oauth2'), true);
  assert.equal(isSignInUrl('https://mail.google.com/'), false);
  assert.equal(isSignInUrl('http://accounts.google.com/'), false);
  assert.equal(isSignInUrl('https://accounts.google.com.evil.io/'), false);
  assert.equal(isSignInUrl('not a url'), false);
});

test('the built-in list is the agreed one', () => {
  assert.deepEqual(SIGN_IN_HOSTS, [
    'login.microsoftonline.com', 'login.microsoft.com', 'login.live.com', 'accounts.google.com', 'appleid.apple.com',
  ]);
});

test('a new tab or a browser page does not trust sign-in', async () => {
  const trail = createSignInTrail(memory());
  await trail.settle(1, true, 'chrome://newtab/');
  assert.equal(await trail.mayEnter(1), false);
  await trail.settle(1, true, 'https://uni.ac.il/');
  await trail.settle(1, true, 'chrome-extension://abc/blocked.html');
  assert.equal(await trail.mayEnter(1), false);
});
