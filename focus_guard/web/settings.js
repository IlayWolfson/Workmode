// The settings panel behind the gear: cue songs (tick, ▶ to hear the first seconds, add your own), punishment
// videos (tick, add your own with the button or by dropping a file), grace seconds, start with Windows and a new emergency phrase. The phrase is never read back: the two
// fields start empty and an empty phrase keeps the old one. Python validates and writes config.json.
(function () {
  'use strict';

  let songs = [];  // [{id, name, ticked, bundled}]
  let videos = [];  // the same shape, for punishment videos
  const VIDEO_RE = /\.(mp4|webm)$/i;

  function $(id) { return document.getElementById(id); }

  function baseName(path) {
    const name = path.split(/[\\/]/).pop();
    return name.replace(/\.[^.]+$/, '');
  }

  function renderSongs() {
    renderList('setSongs', songs, true);
  }

  function renderVideos() {
    renderList('setVideos', videos, false);
  }

  // One row per item: a tick, its name, "(שלי)" for the user's own; songs also get ▶ to hear the first seconds.
  function renderList(id, items, playable) {
    const list = $(id);
    list.replaceChildren();
    items.forEach(function (song) {
      const row = document.createElement('div');
      row.className = 'song';
      const label = document.createElement('label');
      const tick = document.createElement('input');
      tick.type = 'checkbox';
      tick.checked = song.ticked;
      tick.onchange = function () { song.ticked = tick.checked; };
      label.append(tick, song.name);
      if (!song.bundled) {
        const mine = document.createElement('span');
        mine.className = 'mine';
        mine.textContent = '(שלי)';
        label.append(mine);
      }
      if (!playable) { row.append(label); list.append(row); return; }
      const play = document.createElement('button');
      play.className = 'round small';
      play.textContent = '▶';
      play.title = 'השמעה';
      play.setAttribute('aria-label', 'השמעה');
      play.onclick = function () { pywebview.api.preview_song(song.id); };
      row.append(label, play);
      list.append(row);
    });
  }

  function fill(settings) {
    songs = settings.songs.map(function (song) { return Object.assign({}, song); });
    videos = settings.videos.map(function (item) { return Object.assign({}, item); });
    renderSongs();
    renderVideos();
    $('setGrace').value = String(settings.grace_seconds);
    $('setAutostart').checked = settings.start_with_windows;
    $('setPhrase').value = '';
    $('setPhrase2').value = '';
    $('setMsg').textContent = '';
  }

  function open() {
    FG.form.close();
    FG.card.close();
    FG.allowed.close();
    pywebview.api.settings().then(function (settings) {
      fill(settings);
      $('settingsPanel').hidden = false;
    });
  }

  function close() {
    $('settingsPanel').hidden = true;
    $('setPhrase').value = '';
    $('setPhrase2').value = '';
  }

  function addSong() {
    pywebview.api.choose_file('song').then(function (path) {
      if (!path || songs.some(function (song) { return song.id === path; })) { return; }
      songs.push({ id: path, name: baseName(path), ticked: true, bundled: false });
      renderSongs();
    });
  }

  // A video picked in the dialog or dropped on the box joins the list ticked; saving writes it to config.json.
  function droppedVideo(path) {
    if (!path) { return; }
    if (!VIDEO_RE.test(path)) { $('setMsg').textContent = 'אפשר להוסיף רק קובץ mp4 או webm.'; return; }
    $('setMsg').textContent = '';
    if (videos.some(function (item) { return item.id === path; })) { return; }
    videos.push({ id: path, name: baseName(path), ticked: true, bundled: false });
    renderVideos();
  }

  function addVideo() {
    pywebview.api.choose_file('video').then(droppedVideo);
  }

  function save() {
    const grace = $('setGrace').value.trim();
    const changes = {
      songs: songs.filter(function (song) { return song.ticked; }).map(function (song) { return song.id; }),
      song_files: songs.filter(function (song) { return !song.bundled; }).map(function (song) { return song.id; }),
      videos: videos.filter(function (item) { return item.ticked; }).map(function (item) { return item.id; }),
      video_files: videos.filter(function (item) { return !item.bundled; }).map(function (item) { return item.id; }),
      grace_seconds: /^\d+$/.test(grace) ? Number(grace) : grace,
      start_with_windows: $('setAutostart').checked,
      phrase: $('setPhrase').value,
      phrase_again: $('setPhrase2').value,
    };
    pywebview.api.save_settings(changes).then(function (result) {
      if (!result.ok) { $('setMsg').textContent = result.message; return; }
      close();
    });
  }

  function init() {
    $('gear').onclick = open;
    $('sideGear').onclick = open;
    $('setCancel').onclick = close;
    $('setSave').onclick = save;
    $('setAddSong').onclick = addSong;
    $('setAddVideo').onclick = addVideo;
    ['dragenter', 'dragover'].forEach(function (type) {
      $('setVideoDrop').addEventListener(type, function () { $('setVideoDrop').classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (type) {
      $('setVideoDrop').addEventListener(type, function () { $('setVideoDrop').classList.remove('over'); });
    });
    $('settingsPanel').addEventListener('keydown', function (event) { if (event.key === 'Escape') { close(); } });
  }

  window.FG.settings = { init: init, open: open, close: close, droppedVideo: droppedVideo };
})();
