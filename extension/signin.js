// Signing in to an allowed site: a sign-in page on another domain opens only when the tab came from an allowed
// site (or is a popup opened by such a tab). Opened directly, it stays blocked.
export const SIGN_IN_HOSTS = [
  'login.microsoftonline.com', 'login.microsoft.com', 'login.live.com', 'accounts.google.com', 'appleid.apple.com',
];

export function isSignInUrl(url) {
  let parsed;
  try {
    parsed = new URL(String(url || '').trim());
  } catch {
    return false;
  }
  return parsed.protocol === 'https:' && SIGN_IN_HOSTS.includes(parsed.hostname.toLowerCase().replace(/\.$/, ''));
}

// Per tab: was its last settled address an allowed web page? A blocked address, a new tab or a browser page clears it.
// Kept in the session store (chrome.storage.session), so it survives the service worker sleeping between pages.
const KEY = 'signin-trusted';

export function createSignInTrail(store) {
  const read = async () => new Set((await store.get(KEY)) || []);
  const write = (trusted) => store.set(KEY, [...trusted]);
  return {
    async settle(tabId, ok, url) {
      const trusted = await read();
      if (ok && /^https?:\/\//i.test(String(url || ''))) trusted.add(tabId);
      else trusted.delete(tabId);
      await write(trusted);
    },
    async opened(sourceTabId, tabId) {
      const trusted = await read();
      if (!trusted.has(sourceTabId)) return;
      trusted.add(tabId);
      await write(trusted);
    },
    mayEnter: async (tabId) => (await read()).has(tabId),
    async forget(tabId) {
      const trusted = await read();
      if (trusted.delete(tabId)) await write(trusted);
    },
  };
}
