import { isAllowedUrl, tabsToCheck, blockedPageUrl } from './allowed.js';
import { createLookup, createTabGate, urlAllowed } from './ytlookup.js';
import { createSignInTrail, isSignInUrl } from './signin.js';
import { FOCUS } from './config.js';
import { badgeFor, reloadDecision } from './update.js';

const BASE = `http://127.0.0.1:${FOCUS.port}`;
// The app's own bridge: it runs all the time, the session bridge above only during a session.
const UPDATE_URL = `http://127.0.0.1:${FOCUS.port + 1}/update?token=${encodeURIComponent(FOCUS.token)}`;
let allowed = null; // {sites, youtube}; null = bridge unreachable or not enforcing: fail open
const tabUrls = new Map();
const gate = createTabGate();

async function fetchText(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(String(response.status));
  return response.text();
}

// Looked-up channels survive the service worker sleeping and are forgotten when Chrome closes.
const store = {
  get: async (key) => (await chrome.storage.session.get(key))[key],
  set: (key, value) => chrome.storage.session.set({ [key]: value }),
};
const lookup = createLookup({ fetchText, store });
const trail = createSignInTrail(store);

async function refreshSites() {
  try {
    const response = await fetch(`${BASE}/allowed?token=${encodeURIComponent(FOCUS.token)}`);
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    allowed = data.sites === null ? null : { sites: data.sites, youtube: data.youtube || null };
  } catch {
    allowed = null;
  }
  await sweepOpenTabs();
}

function block(tabId, url) {
  report('blocked_site', hostOf(url));
  chrome.tabs.update(tabId, { url: blockedPageUrl(chrome.runtime.getURL('blocked.html'), url) });
}

async function sweepOpenTabs() {
  if (allowed === null) return;
  const tabs = await chrome.tabs.query({});
  for (const { id, url } of tabsToCheck(tabs, allowed.sites)) await check(id, url);
}

// YouTube answers can take a moment; only the tab's latest address may be blocked.
// A sign-in page opens when the tab came from an allowed site (signin.js).
async function check(tabId, url) {
  if (allowed === null) return;
  const ticket = gate.begin(tabId, url);
  const ok = (await urlAllowed(url, allowed, lookup)) || (isSignInUrl(url) && (await trail.mayEnter(tabId)));
  if (!gate.isCurrent(tabId, ticket)) return;
  await trail.settle(tabId, ok, url);
  if (!ok && allowed !== null) block(tabId, url);
}

async function report(type, detail) {
  try {
    await fetch(`${BASE}/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: FOCUS.token, type, detail }),
    });
  } catch {
    // the guard is not running: nothing to report to
  }
}

function hostOf(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return '';
  }
}

chrome.tabs.query({}, (tabs) => {
  for (const tab of tabs) if (tab.id !== undefined && tab.url) tabUrls.set(tab.id, tab.url);
});

// A worker that just woke has no list yet: fetch it first, or the address would pass unchecked.
async function navigated(tabId, url) {
  if (allowed === null) await refreshSites();
  await check(tabId, url);
}

chrome.webNavigation.onBeforeNavigate.addListener(async (details) => {
  if (details.frameId !== 0) return;
  await navigated(details.tabId, details.url);
});

// YouTube changes videos without loading a page; those address changes arrive here.
chrome.webNavigation.onHistoryStateUpdated.addListener(async (details) => {
  if (details.frameId !== 0) return;
  await navigated(details.tabId, details.url);
});

// Sign-in popups opened by a trusted tab are trusted too.
chrome.webNavigation.onCreatedNavigationTarget.addListener(async (details) => {
  await trail.opened(details.sourceTabId, details.tabId);
});

chrome.tabs.onUpdated.addListener((tabId, _changeInfo, tab) => {
  if (tab.url) tabUrls.set(tabId, tab.url);
});

chrome.tabs.onRemoved.addListener((tabId, removeInfo) => {
  const url = tabUrls.get(tabId);
  tabUrls.delete(tabId);
  gate.forget(tabId);
  trail.forget(tabId);
  if (removeInfo.isWindowClosing || !url || allowed === null) return;
  if (/^https?:/i.test(url) && isAllowedUrl(url, allowed.sites)) report('tab_closed', hostOf(url));
});

// The orange "!" when an update is ready. After the app was updated, one reload makes Chrome read the new files.
async function refreshUpdate() {
  let status = null;
  try {
    const response = await fetch(UPDATE_URL);
    if (response.ok) status = await response.json();
  } catch {
    // the app is not running: no badge
  }
  await chrome.action.setBadgeText({ text: badgeFor(status) });
  await chrome.action.setBadgeBackgroundColor({ color: '#F28C28' });
  if (status === null) return;
  const stored = await chrome.storage.local.get('reloadTo');
  const decision = reloadDecision(status.installed, chrome.runtime.getManifest().version, stored);
  await chrome.storage.local.set({ wrongFolder: decision.wrongFolder });
  if (decision.reload) {
    await chrome.storage.local.set(decision.store);
    chrome.runtime.reload();
  }
}

chrome.alarms.create('refresh', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(refreshSites);
chrome.alarms.onAlarm.addListener(refreshUpdate);
refreshSites();
refreshUpdate();

// The blocked page asks whether enforcement is still on; when it is not, it sends the tab back.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.type === 'status') {
    refreshSites().then(() => sendResponse({ enforcing: allowed !== null }));
    return true;
  }
  return false;
});
