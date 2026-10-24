import test from 'node:test';
import assert from 'node:assert/strict';
import {
  classifyYouTube, normalizeName, identityFromOembed, identityFromChannelHtml,
  hasYouTubeLists, channelAllowed, playlistAllowed, isYouTubeHost, videoAllowed,
} from './youtube.js';

const LISTS = {
  handles: ['@3blue1brown'],
  channel_ids: ['UCYO_jab_esuFRV4b17AJtAw'],
  names: ['3blue1brown'],
  playlists: ['PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi'],
};

test('YouTube hosts', () => {
  for (const host of ['youtube.com', 'WWW.YOUTUBE.COM', 'm.youtube.com', 'youtu.be', 'www.youtube.com.']) {
    assert.equal(isYouTubeHost(host), true, host);
  }
  for (const host of ['music.youtube.com', 'youtube.com.evil.example', 'notyoutube.com', '']) {
    assert.equal(isYouTubeHost(host), false, host);
  }
});

test('video addresses in every form', () => {
  for (const url of [
    'https://www.youtube.com/watch?v=aircAruvnKk',
    'https://m.youtube.com/watch?v=aircAruvnKk&t=5',
    'https://youtu.be/aircAruvnKk',
    'https://www.youtube.com/live/aircAruvnKk',
    'https://www.youtube.com/embed/aircAruvnKk',
  ]) {
    assert.deepEqual(classifyYouTube(url), { kind: 'video', video: 'aircAruvnKk', list: null }, url);
  }
  assert.deepEqual(classifyYouTube('https://www.youtube.com/watch?v=aircAruvnKk&list=PLx1234567890'), {
    kind: 'video', video: 'aircAruvnKk', list: 'PLx1234567890',
  });
});

test('channel pages keep their path and give a key', () => {
  assert.deepEqual(classifyYouTube('https://www.youtube.com/@3Blue1Brown/videos'), {
    kind: 'channel', path: '/@3Blue1Brown', key: '@3blue1brown',
  });
  assert.deepEqual(classifyYouTube('https://www.youtube.com/channel/UCYO_jab_esuFRV4b17AJtAw/playlists'), {
    kind: 'channel', path: '/channel/UCYO_jab_esuFRV4b17AJtAw', key: 'UCYO_jab_esuFRV4b17AJtAw',
  });
  assert.deepEqual(classifyYouTube('https://www.youtube.com/@%D7%A9%D7%9C%D7%95%D7%9D'), {
    kind: 'channel', path: '/@%D7%A9%D7%9C%D7%95%D7%9D', key: '@שלום',
  });
});

test('playlist pages', () => {
  assert.deepEqual(classifyYouTube('https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi'), {
    kind: 'playlist', list: 'PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi',
  });
});

test('search, home, feed, shorts and old links are "other"', () => {
  for (const url of [
    'https://www.youtube.com/',
    'https://www.youtube.com/results?search_query=x',
    'https://www.youtube.com/feed/subscriptions',
    'https://www.youtube.com/shorts/aircAruvnKk',
    'https://www.youtube.com/c/Numberphile',
    'https://www.youtube.com/user/x',
    'https://www.youtube.com/watch',
    'https://www.youtube.com/watch?v=short',
    'https://www.youtube.com/playlist',
  ]) {
    assert.deepEqual(classifyYouTube(url), { kind: 'other' }, url);
  }
});

test('other hosts are not YouTube', () => {
  for (const url of [
    'https://music.youtube.com/watch?v=aircAruvnKk',
    'https://youtube.com.evil.example/watch?v=aircAruvnKk',
    'https://github.com/',
    'not a url',
    'chrome://newtab/',
  ]) {
    assert.equal(classifyYouTube(url), null, url);
  }
});

test('oEmbed answers become identities', () => {
  assert.deepEqual(identityFromOembed({ author_name: '3Blue1Brown', author_url: 'https://www.youtube.com/@3blue1brown' }), {
    handle: '@3blue1brown', id: null, name: '3blue1brown',
  });
  assert.deepEqual(identityFromOembed({ author_name: 'X', author_url: 'https://www.youtube.com/channel/UCYO_jab_esuFRV4b17AJtAw' }), {
    handle: null, id: 'UCYO_jab_esuFRV4b17AJtAw', name: 'x',
  });
  for (const bad of [
    null, {}, { author_name: 'x' },
    { author_name: 5, author_url: 'https://www.youtube.com/@x' },
    { author_name: 'x', author_url: 'https://evil.com/@x' },
  ]) {
    assert.equal(identityFromOembed(bad), null);
  }
});

test('channel page HTML becomes an identity', () => {
  const html = '<meta property="og:title" content="Tom &amp; Jerry"><link rel="canonical" href="https://www.youtube.com/channel/UCYO_jab_esuFRV4b17AJtAw">"vanityChannelUrl":"http://www.youtube.com/@TomJerry"';
  assert.deepEqual(identityFromChannelHtml(html), { handle: '@tomjerry', id: 'UCYO_jab_esuFRV4b17AJtAw', name: 'tom & jerry' });
  assert.equal(identityFromChannelHtml('<html>nothing</html>'), null);
});

test('channelAllowed matches whole names only', () => {
  assert.equal(channelAllowed({ handle: null, id: null, name: normalizeName(' 3Blue1Brown ') }, LISTS), true);
  assert.equal(channelAllowed({ handle: null, id: null, name: '3blue1brown shorts' }, LISTS), false);
  assert.equal(channelAllowed({ handle: '@3blue1brown', id: null, name: 'renamed' }, LISTS), true);
  assert.equal(channelAllowed({ handle: null, id: 'ucyo_jab_esufrv4b17ajtaw', name: null }, LISTS), true);
  assert.equal(channelAllowed(null, LISTS), false);
});

test('playlists compare case-insensitively; empty lists mean nothing to allow', () => {
  assert.equal(playlistAllowed('plzhqobowtqdnu6r1_67000dx_zcjb-3pi', LISTS), true);
  assert.equal(playlistAllowed(null, LISTS), false);
  assert.equal(hasYouTubeLists({ handles: [], channel_ids: [], names: [], playlists: [] }), false);
  assert.equal(hasYouTubeLists(null), false);
  assert.equal(hasYouTubeLists(LISTS), true);
});

test('oEmbed author_url may be relative', () => {
  assert.deepEqual(identityFromOembed({ author_name: 'CrashCourse', author_url: '/@crashcourse' }), {
    handle: '@crashcourse', id: null, name: 'crashcourse',
  });
});

test('channel page escapes and entities are decoded', () => {
  const html = '<meta property="og:title" content="Let&#x27;s &#39;Go&#39; &#1488;">"vanityChannelUrl":"http://www.youtube.com/@\u05e9x"';
  assert.deepEqual(identityFromChannelHtml(html), { handle: '@שx', id: null, name: "let's 'go' א" });
});

test('hasYouTubeLists counts videos', () => {
  assert.equal(hasYouTubeLists({ videos: ['aircAruvnKk'] }), true);
});

test('videoAllowed matches the exact id', () => {
  assert.equal(videoAllowed('aircAruvnKk', { videos: ['aircAruvnKk'] }), true);
  assert.equal(videoAllowed('AIRCARUVNKK', { videos: ['aircAruvnKk'] }), false);
  assert.equal(videoAllowed('aircAruvnKk', null), false);
});
