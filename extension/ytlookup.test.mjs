import test from 'node:test';
import assert from 'node:assert/strict';
import { createLookup, urlAllowed, createTabGate, oembedUrl, playlistOembedUrl } from './ytlookup.js';

const EMPTY = { handles: [], channel_ids: [], names: [], playlists: [] };
const VIDEO = 'https://www.youtube.com/watch?v=aircAruvnKk';
const ID = 'UCYO_jab_esuFRV4b17AJtAw';
const PLAYLIST = 'PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi';
const OWN = JSON.stringify({ author_name: '3Blue1Brown', author_url: 'https://www.youtube.com/@3blue1brown' });
const OTHER = JSON.stringify({ author_name: 'Other', author_url: 'https://www.youtube.com/@other' });

function page(title, handle = '@3blue1brown') {
  return `<meta property="og:title" content="${title}"><link rel="canonical" href="https://www.youtube.com/channel/${ID}">"vanityChannelUrl":"http://www.youtube.com/${handle}"`;
}

function fake(answers) {
  const calls = [];
  const store = new Map();
  const lookup = createLookup({
    fetchText: async (url) => {
      calls.push(url);
      if (!(url in answers)) throw new Error('offline');
      return answers[url];
    },
    store: { get: async (key) => store.get(key), set: async (key, value) => void store.set(key, value) },
  });
  return { lookup, calls, store, answers };
}

test('oembedUrl is the exact public address', () => {
  assert.equal(oembedUrl('aircAruvnKk'), 'https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DaircAruvnKk&format=json');
});

test('allowed channel video is allowed and looked up once', async () => {
  const { lookup, calls } = fake({ [oembedUrl('aircAruvnKk')]: OWN });
  const lists = { ...EMPTY, handles: ['@3blue1brown'] };
  assert.equal(await lookup.decide(VIDEO, lists), true);
  assert.equal(await lookup.decide(VIDEO, lists), true);
  assert.equal(calls.length, 1);
});

test('decide blocks a video of another channel', async () => {
  const { lookup } = fake({ [oembedUrl('aircAruvnKk')]: OTHER });
  assert.equal(await lookup.decide(VIDEO, { ...EMPTY, handles: ['@3blue1brown'] }), false);
});

test('failed lookup blocks and is retried', async () => {
  const { lookup, store, answers } = fake({});
  const lists = { ...EMPTY, handles: ['@3blue1brown'] };
  assert.equal(await lookup.decide(VIDEO, lists), false);
  assert.equal(store.size, 0);
  answers[oembedUrl('aircAruvnKk')] = 'not json';
  assert.equal(await lookup.decide(VIDEO, lists), false);
  assert.equal(store.size, 0);
  answers[oembedUrl('aircAruvnKk')] = OWN;
  assert.equal(await lookup.decide(VIDEO, lists), true);
});

test('a video from an allowed playlist needs no lookup', async () => {
  const { lookup, calls } = fake({});
  assert.equal(await lookup.decide(`${VIDEO}&list=${PLAYLIST}`, { ...EMPTY, playlists: [PLAYLIST] }), true);
  assert.equal(await lookup.decide(`https://www.youtube.com/playlist?list=${PLAYLIST}`, { ...EMPTY, playlists: [PLAYLIST] }), true);
  assert.equal(calls.length, 0);
});

test('configured channel id is resolved to its handle', async () => {
  const { lookup, calls } = fake({
    [oembedUrl('aircAruvnKk')]: OWN,
    [`https://www.youtube.com/channel/${ID}`]: page('3Blue1Brown'),
  });
  assert.equal(await lookup.decide(VIDEO, { ...EMPTY, channel_ids: [ID] }), true);
  assert.ok(calls.includes(`https://www.youtube.com/channel/${ID}`));
});

test('an unresolved channel id is retried on the next check', async () => {
  const { lookup, answers } = fake({ [oembedUrl('aircAruvnKk')]: OWN });
  const lists = { ...EMPTY, channel_ids: [ID] };
  assert.equal(await lookup.decide(VIDEO, lists), false);
  answers[`https://www.youtube.com/channel/${ID}`] = page('3Blue1Brown');
  assert.equal(await lookup.decide(VIDEO, lists), true);
});

test('channel page by name', async () => {
  const good = fake({ 'https://www.youtube.com/@3blue1brown': page('3Blue1Brown') });
  assert.equal(await good.lookup.decide('https://www.youtube.com/@3blue1brown/videos', { ...EMPTY, names: ['3blue1brown'] }), true);
  assert.deepEqual(good.calls, ['https://www.youtube.com/@3blue1brown']);
  const bad = fake({ 'https://www.youtube.com/@3blue1brown': page('3Blue1Brown Shorts') });
  assert.equal(await bad.lookup.decide('https://www.youtube.com/@3blue1brown/videos', { ...EMPTY, names: ['3blue1brown'] }), false);
});

test('direct channel key needs no fetch', async () => {
  const { lookup, calls } = fake({});
  assert.equal(await lookup.decide('https://www.youtube.com/@3Blue1Brown', { ...EMPTY, handles: ['@3blue1brown'] }), true);
  assert.equal(await lookup.decide(`https://www.youtube.com/channel/${ID.toLowerCase().replace('uc', 'UC')}`, { ...EMPTY, channel_ids: [ID] }), true);
  assert.equal(calls.length, 0);
});

test('search and shorts are blocked; non-YouTube is null', async () => {
  const { lookup } = fake({});
  const lists = { ...EMPTY, handles: ['@3blue1brown'] };
  assert.equal(await lookup.decide('https://www.youtube.com/results?search_query=x', lists), false);
  assert.equal(await lookup.decide('https://www.youtube.com/shorts/aircAruvnKk', lists), false);
  assert.equal(await lookup.decide('https://github.com/', lists), null);
});

test('urlAllowed: site list youtube.com allows everything', async () => {
  const { lookup, calls } = fake({});
  const search = 'https://www.youtube.com/results?search_query=x';
  assert.equal(await urlAllowed(search, { sites: ['youtube.com'], youtube: null }, lookup), true);
  assert.equal(await urlAllowed(search, { sites: [], youtube: null }, lookup), false);
  assert.equal(await urlAllowed('https://github.com/x', { sites: ['github.com'] }, lookup), true);
  assert.equal(await urlAllowed('https://evil.example/', { sites: [], youtube: { ...EMPTY, handles: ['@a1'] } }, lookup), false);
  assert.equal(calls.length, 0);
});

test('tab gate drops answers for older addresses', () => {
  const gate = createTabGate();
  const a = gate.begin(1, 'u1');
  const b = gate.begin(1, 'u2');
  const c = gate.begin(2, 'u1');
  assert.equal(gate.isCurrent(1, a), false);
  assert.equal(gate.isCurrent(1, b), true);
  assert.equal(gate.isCurrent(2, c), true);
  gate.forget(1);
  assert.equal(gate.isCurrent(1, b), false);
  assert.equal(gate.isCurrent(2, c), true);
});

test('a playlist page of an allowed channel is allowed', async () => {
  const url = `https://www.youtube.com/playlist?list=${PLAYLIST}`;
  const owner = (author) => JSON.stringify({ author_name: author, author_url: `/@${author.toLowerCase()}` });
  const lists = { ...EMPTY, handles: ['@crashcourse'] };
  const own = fake({ [playlistOembedUrl(PLAYLIST)]: owner('CrashCourse') });
  assert.equal(await own.lookup.decide(url, lists), true);
  assert.equal(await own.lookup.decide(url, lists), true);
  assert.equal(own.calls.length, 1);
  const other = fake({ [playlistOembedUrl(PLAYLIST)]: owner('Other') });
  assert.equal(await other.lookup.decide(url, lists), false);
  assert.equal(await fake({}).lookup.decide(url, lists), false);
});

test('a listed video is allowed without a lookup', async () => {
  const { lookup, calls } = fake({});
  const youtube = { ...EMPTY, videos: ['aircAruvnKk'] };
  assert.equal(await lookup.decide(VIDEO, youtube), true);
  assert.equal(await lookup.decide('https://youtu.be/aircAruvnKk', youtube), true);
  assert.equal(await lookup.decide('https://www.youtube.com/watch?v=AIRCARUVNKK', youtube), false);
  assert.equal(calls.filter((url) => url.includes('aircAruvnKk')).length, 0);
});

test('urlAllowed lets a listed video through when it is the only list', async () => {
  const { lookup } = fake({});
  assert.equal(await urlAllowed(VIDEO, { sites: [], youtube: { ...EMPTY, videos: ['aircAruvnKk'] } }, lookup), true);
});
