const SPECIAL = ['chrome:', 'about:', 'chrome-extension:', 'file:', 'edge:', 'devtools:'];

function siteMatches(clean, site) {
  if (site.startsWith('*') && site.endsWith('*')) return clean.includes(site.slice(1, -1)); // "*word*"
  return clean === site || clean.endsWith('.' + site);
}

export function hostAllowed(host, sites) {
  const clean = String(host || '').trim().toLowerCase().replace(/\.$/, '');
  return clean !== '' && sites.some((site) => siteMatches(clean, site));
}

export function isAllowedUrl(url, sites) {
  const text = String(url || '').trim().toLowerCase();
  if (SPECIAL.some((prefix) => text.startsWith(prefix))) return true;
  let parsed;
  try {
    parsed = new URL(text);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false;
  return hostAllowed(parsed.hostname, sites);
}

// Ids of already-open tabs that a new allow-list rules out. null means "not enforcing".
// The tabs to check, each at the address it is loading (pendingUrl) or showing: checking the old address of a tab
// that is loading would take the gate's ticket from the check of the new one.
export function tabsToCheck(tabs, sites) {
  if (sites === null) return [];
  return tabs
    .filter((tab) => tab.id !== undefined)
    .map((tab) => ({ id: tab.id, url: tab.pendingUrl || tab.url }))
    .filter((tab) => tab.url && !isAllowedUrl(tab.url, sites));
}

// The blocked page keeps the address it replaced, so it can send the tab back once the session is over.
export function blockedPageUrl(base, original) {
  return `${base}?u=${encodeURIComponent(original)}`;
}

export function returnTarget(search) {
  const value = new URLSearchParams(search).get('u');
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
}
