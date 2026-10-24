// YouTube during a session: which channel or playlist an address belongs to, and whether it is on the list.
const HOSTS = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'];
const VIDEO_RE = /^[A-Za-z0-9_-]{11}$/;
const CHANNEL_ID_RE = /^UC[A-Za-z0-9_-]{22}$/;
const ENTITIES = { '&amp;': '&', '&quot;': '"', '&lt;': '<', '&gt;': '>' };

export function isYouTubeHost(host) {
  return HOSTS.includes(String(host || '').trim().toLowerCase().replace(/\.$/, ''));
}

export function normalizeName(text) {
  return String(text).normalize('NFC').trim().toLowerCase();
}

function handleKey(segment) {
  let value;
  try {
    value = decodeURIComponent(segment.slice(1));
  } catch {
    return null;
  }
  return value && !/[\s/]/.test(value) ? '@' + value.toLowerCase() : null;
}

// The channel an address points at, as {path, key}, or null. path keeps case; key is "@handle" or "UC...".
function channelOf(parts) {
  const [first, second] = parts;
  if (first && first.startsWith('@')) {
    const key = handleKey(first);
    return key ? { path: '/' + first, key } : null;
  }
  if (first === 'channel' && CHANNEL_ID_RE.test(second || '')) return { path: `/channel/${second}`, key: second };
  return null;
}

function video(id, list) {
  return VIDEO_RE.test(id || '') ? { kind: 'video', video: id, list: list || null } : { kind: 'other' };
}

export function classifyYouTube(url) {
  let parsed;
  try {
    parsed = new URL(String(url || '').trim());
  } catch {
    return null;
  }
  if ((parsed.protocol !== 'http:' && parsed.protocol !== 'https:') || !isYouTubeHost(parsed.hostname)) return null;
  const parts = parsed.pathname.split('/').filter(Boolean);
  const list = parsed.searchParams.get('list');
  if (parsed.hostname.toLowerCase().replace(/\.$/, '') === 'youtu.be') return video(parts[0], list);
  if (parts[0] === 'watch' && parts.length === 1) return video(parsed.searchParams.get('v'), list);
  if (['live', 'embed'].includes(parts[0]) && parts.length === 2) return video(parts[1], list);
  if (parts[0] === 'playlist' && parts.length === 1 && list) return { kind: 'playlist', list };
  const channel = channelOf(parts);
  return channel ? { kind: 'channel', ...channel } : { kind: 'other' };
}

function keysFromChannelUrl(url) {
  try {
    const parsed = new URL(url, 'https://www.youtube.com'); // oEmbed answers playlists with a relative address
    if (!isYouTubeHost(parsed.hostname)) return null;
    return channelOf(parsed.pathname.split('/').filter(Boolean));
  } catch {
    return null;
  }
}

function identity(key, name) {
  return {
    handle: key && key.startsWith('@') ? key : null,
    id: key && !key.startsWith('@') ? key : null,
    name,
  };
}

export function identityFromOembed(data) {
  if (!data || typeof data.author_name !== 'string' || typeof data.author_url !== 'string') return null;
  const channel = keysFromChannelUrl(data.author_url);
  return channel ? identity(channel.key, normalizeName(data.author_name)) : null;
}

function decode(text) {
  return text
    .replace(/&#x([0-9a-f]+);/gi, (_entity, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_entity, number) => String.fromCodePoint(Number(number)))
    .replace(/&(amp|quot|lt|gt);/g, (entity) => ENTITIES[entity]);
}

// The page's JSON may escape characters (ש); read the value as the JSON string it is.
function jsonString(raw) {
  try {
    return JSON.parse(`"${raw}"`);
  } catch {
    return null;
  }
}

export function identityFromChannelHtml(html) {
  const text = String(html || '');
  const title = text.match(/<meta property="og:title" content="([^"]*)"/);
  const canonical = text.match(/<link rel="canonical" href="https?:\/\/www\.youtube\.com\/channel\/(UC[A-Za-z0-9_-]{22})"/);
  const vanity = text.match(/"vanityChannelUrl":"((?:[^"\\]|\\.)*)"/);
  const name = title ? normalizeName(decode(title[1])) : null;
  const id = canonical ? canonical[1] : null;
  if (!name && !id) return null;
  const channel = vanity ? keysFromChannelUrl(jsonString(vanity[1]) || '') : null;
  return { handle: channel && channel.key.startsWith('@') ? channel.key : null, id, name };
}

function has(values, value) {
  if (!value) return false;
  const wanted = value.toLowerCase();
  return (values || []).some((item) => item.toLowerCase() === wanted);
}

export function hasYouTubeLists(youtube) {
  return Boolean(youtube) && ['handles', 'channel_ids', 'names', 'playlists', 'videos'].some((key) => (youtube[key] || []).length > 0);
}

export function channelAllowed(found, youtube) {
  if (!found || !youtube) return false;
  return has(youtube.handles, found.handle) || has(youtube.channel_ids, found.id) || has(youtube.names, found.name);
}

// Video ids are case-sensitive, so a listed video matches only exactly.
export function videoAllowed(video, youtube) {
  return Boolean(youtube) && Boolean(video) && (youtube.videos || []).includes(video);
}

export function playlistAllowed(list, youtube) {
  return Boolean(youtube) && has(youtube.playlists, list);
}
