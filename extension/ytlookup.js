// Looks up whose a YouTube address is (oEmbed for videos, the channel page as a backup) and decides.
// The network and the cache are passed in, so this runs under node tests as it does in Chrome.
import { isAllowedUrl } from './allowed.js';
import {
  classifyYouTube, identityFromOembed, identityFromChannelHtml, hasYouTubeLists, channelAllowed, playlistAllowed,
  videoAllowed,
} from './youtube.js';

const ORIGIN = 'https://www.youtube.com';

export function oembedUrl(video) {
  return `${ORIGIN}/oembed?url=${encodeURIComponent(`${ORIGIN}/watch?v=${video}`)}&format=json`;
}

export function playlistOembedUrl(list) {
  return `${ORIGIN}/oembed?url=${encodeURIComponent(`${ORIGIN}/playlist?list=${list}`)}&format=json`;
}

function json(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export function createLookup({ fetchText, store }) {
  // Only answers are cached; a failure returns null and is tried again next time.
  async function cached(key, url, read) {
    const known = await store.get(key);
    if (known) return known;
    let found = null;
    try {
      found = read(await fetchText(url));
    } catch {
      return null;
    }
    if (found) await store.set(key, found);
    return found;
  }

  const videoIdentity = (video) => cached(`v:${video}`, oembedUrl(video), (text) => identityFromOembed(json(text)));
  const playlistOwner = (list) => cached(`p:${list}`, playlistOembedUrl(list), (text) => identityFromOembed(json(text)));
  const pageIdentity = (path) => cached(`c:${path.toLowerCase()}`, ORIGIN + path, identityFromChannelHtml);

  // oEmbed answers with the handle, never the UC id, so configured ids also allow their channel's handle.
  async function effective(youtube) {
    const handles = [...(youtube.handles || [])];
    for (const id of youtube.channel_ids || []) {
      const found = await pageIdentity(`/channel/${id}`);
      if (found && found.handle) handles.push(found.handle);
    }
    return { ...youtube, handles };
  }

  async function decide(url, youtube) {
    const place = classifyYouTube(url);
    if (place === null) return null;
    if (place.kind === 'playlist') {
      if (playlistAllowed(place.list, youtube)) return true;
      const owner = await playlistOwner(place.list); // an allowed channel's own playlists are inside the channel
      return owner !== null && channelAllowed(owner, await effective(youtube));
    }
    if (place.kind === 'video') {
      if (videoAllowed(place.video, youtube)) return true;
      if (playlistAllowed(place.list, youtube)) return true;
      const found = await videoIdentity(place.video);
      return found !== null && channelAllowed(found, await effective(youtube));
    }
    if (place.kind === 'channel') {
      const direct = { handle: place.key.startsWith('@') ? place.key : null, id: place.key.startsWith('@') ? null : place.key, name: null };
      if (channelAllowed(direct, youtube)) return true;
      const lists = await effective(youtube);
      if (channelAllowed(direct, lists)) return true;
      return channelAllowed(await pageIdentity(place.path), lists);
    }
    return false;
  }

  return { decide };
}

export async function urlAllowed(url, allowed, lookup) {
  if (isAllowedUrl(url, allowed.sites)) return true;
  if (!hasYouTubeLists(allowed.youtube)) return false;
  return (await lookup.decide(url, allowed.youtube)) === true;
}

// Each tab's latest address wins: an answer that arrives for an older one is dropped.
export function createTabGate() {
  const latest = new Map();
  let counter = 0;
  return {
    begin(tabId) {
      counter += 1;
      latest.set(tabId, counter);
      return counter;
    },
    isCurrent: (tabId, ticket) => latest.get(tabId) === ticket,
    forget: (tabId) => void latest.delete(tabId),
  };
}
