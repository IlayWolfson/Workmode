// The allow-list panel ("מה מותר בסשן"): three tabs (programs, sites, YouTube), each with what is allowed now and a
// way to add. Python parses, validates and saves every change at once (pywebview.api.allowed_*); this file only
// draws the answers. Text is always set with textContent, never as HTML.
(function () {
  'use strict';

  const SAVED_MS = 2000;
  const TYPE_MS = 200;
  const YT_ICONS = { channel: '📺', playlist: '📃', video: '▶' };
  const YT_CHOICES = { channel: 'כל הערוץ', playlist: 'כל הפלייליסט', video: 'רק הסרטון הזה' };
  let site = null;  // the last site preview {host, covers, word}
  let ytChoices = [];
  let savedTimer = null;
  const timers = {};

  function $(id) { return document.getElementById(id); }

  // A call that fails in Python still answers the user, never a click that does nothing.
  function failed() { $('alMsg').textContent = 'משהו השתבש. נסה שוב.'; }

  function later(key, fn) {
    clearTimeout(timers[key]);
    timers[key] = setTimeout(fn, TYPE_MS);
  }

  function row(icon, label, button) {
    const line = document.createElement('div');
    line.className = 'al-row';
    const mark = document.createElement('span');
    mark.className = 'al-icon';
    mark.textContent = icon;
    const name = document.createElement('span');
    name.className = 'al-name';
    name.textContent = label;
    name.title = label;
    line.append(mark, name, button);
    return line;
  }

  function removeButton(kind, value, enabled, why) {
    const x = document.createElement('button');
    x.className = 'al-x';
    x.textContent = '✕';
    x.title = enabled ? 'הסרה' : why;
    x.setAttribute('aria-label', 'הסרה');
    x.disabled = !enabled;
    x.onclick = function () { pywebview.api.allowed_remove(kind, value).then(apply).catch(failed); };
    return x;
  }

  function addButton(onclick) {
    const add = document.createElement('button');
    add.className = 'al-add';
    add.textContent = '+ הוספה';
    add.onclick = onclick;
    return add;
  }

  function addApp(path) {
    pywebview.api.allowed_add('app', path).then(function (result) {
      if (result.ok) { $('alFind').value = ''; showFound([]); }
      apply(result);
    }).catch(failed);
  }

  function fillList(id, items) {
    const list = $(id);
    list.replaceChildren.apply(list, items);
  }

  function render(view) {
    fillList('alApps', view.apps.map(function (app) {
      return row('🖥', app.name, removeButton('app', app.process, app.removable, 'חייבת להישאר לפחות תוכנה אחת.'));
    }));
    fillList('alOpen', view.open.map(function (program) {
      return row('🪟', program.name, addButton(function () { addApp(program.path); }));
    }));
    fillList('alSites', view.sites.map(function (item) {
      return row(item.entry.charAt(0) === '*' ? '🔤' : '🌐', item.label, removeButton('site', item.entry, true, ''));
    }));
    fillList('alYt', view.youtube.map(function (item) {
      return row(YT_ICONS[item.kind], item.label, removeButton(item.kind, item.value, true, ''));
    }));
    $('alCountApps').textContent = String(view.apps.length);
    $('alCountSites').textContent = String(view.sites.length);
    $('alCountYt').textContent = String(view.youtube.length);
  }

  // Every change answers {ok, view} or {ok: false, message}.
  function apply(result) {
    if (!result) { return; }
    if (!result.ok) { $('alMsg').textContent = result.message; return; }
    $('alMsg').textContent = '';
    render(result.view);
    $('alSaved').hidden = false;
    clearTimeout(savedTimer);
    savedTimer = setTimeout(function () { $('alSaved').hidden = true; }, SAVED_MS);
  }

  function showFound(programs) {
    fillList('alFindList', programs.map(function (program) {
      return row('🔎', program.name, addButton(function () { addApp(program.path); }));
    }));
    $('alFindList').hidden = programs.length === 0;
  }

  function find() {
    const query = $('alFind').value;
    later('find', function () { pywebview.api.allowed_find(query).then(showFound).catch(failed); });
  }

  function previewSite() {
    const text = $('alSiteInput').value.trim();
    $('alMsg').textContent = '';
    if (!text) { $('alSiteChoice').hidden = true; return; }
    later('site', function () {
      pywebview.api.allowed_preview_site(text).then(function (result) {
        site = result.ok ? result : null;
        $('alSiteChoice').hidden = !result.ok;
        if (!result.ok) { $('alMsg').textContent = result.message; return; }
        $('alSiteHostText').textContent = 'האתר ' + result.host + ' וכל מה שמתחתיו';
        $('alSiteCovers').textContent = result.covers;
        $('alWord').value = result.word;
        $('alSiteHost').checked = true;
      }).catch(failed);
    });
  }

  function addSite() {
    if (!site) { return; }
    const word = $('alSiteWord').checked;
    pywebview.api.allowed_add(word ? 'word' : 'site', word ? $('alWord').value : site.host).then(function (result) {
      if (result.ok) { $('alSiteInput').value = ''; $('alSiteChoice').hidden = true; site = null; }
      apply(result);
    }).catch(failed);
  }

  function ytOption(choice, index) {
    const label = document.createElement('label');
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'alYtWhat';
    radio.value = String(index);
    radio.checked = index === 0;
    const name = document.createElement('b');
    name.textContent = choice.label || 'צריך חיבור לאינטרנט';
    label.append(radio, ' ' + YT_ICONS[choice.kind] + ' ' + YT_CHOICES[choice.kind] + ': ', name);
    return label;
  }

  function previewYouTube() {
    const text = $('alYtInput').value.trim();
    $('alMsg').textContent = '';
    if (!text) { $('alYtChoice').hidden = true; return; }
    later('yt', function () {
      pywebview.api.allowed_preview_youtube(text).then(function (result) {
        $('alYtChoice').hidden = !result.ok;
        if (!result.ok) { $('alMsg').textContent = result.message; return; }
        ytChoices = result.choices;
        fillList('alYtOptions', ytChoices.map(ytOption));
      }).catch(failed);
    });
  }

  function addYouTube() {
    const picked = document.querySelector('input[name="alYtWhat"]:checked');
    if (!picked) { return; }
    const choice = ytChoices[Number(picked.value)];
    const value = choice.value || $('alYtInput').value.trim();  // a channel still to look up goes as the link
    pywebview.api.allowed_add(choice.kind, value).then(function (result) {
      if (result.ok) { $('alYtInput').value = ''; $('alYtChoice').hidden = true; }
      apply(result);
    }).catch(failed);
  }

  function tab(name) {
    document.querySelectorAll('#allowPanel .al-tab').forEach(function (button) {
      button.classList.toggle('on', button.dataset.tab === name);
    });
    document.querySelectorAll('#allowPanel .al-pane').forEach(function (pane) {
      pane.classList.toggle('on', pane.dataset.pane === name);
    });
  }

  function open() {
    FG.form.close();
    FG.card.close();
    FG.settings.close();
    $('alMsg').textContent = '';
    $('alSaved').hidden = true;
    pywebview.api.allowed_view().then(function (view) {
      render(view);
      $('allowPanel').hidden = false;
    }).catch(failed);
  }

  function close() {
    $('allowPanel').hidden = true;
  }

  // Called from Python after a file is dropped on the box (pywebview gives the full path only there).
  function refresh(result) {
    if (result) { apply(result); return; }
    pywebview.api.allowed_view().then(render).catch(failed);
  }

  function init() {
    $('sideAllowed').onclick = open;
    $('alClose').onclick = close;
    document.querySelectorAll('#allowPanel .al-tab').forEach(function (button) {
      button.onclick = function () { tab(button.dataset.tab); };
    });
    $('alFind').addEventListener('input', find);
    $('alSiteInput').addEventListener('input', previewSite);
    $('alSiteAdd').onclick = addSite;
    $('alWord').addEventListener('focus', function () { $('alSiteWord').checked = true; });
    $('alYtInput').addEventListener('input', previewYouTube);
    $('alYtAdd').onclick = addYouTube;
    ['dragenter', 'dragover'].forEach(function (type) {
      $('alDrop').addEventListener(type, function () { $('alDrop').classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (type) {
      $('alDrop').addEventListener(type, function () { $('alDrop').classList.remove('over'); });
    });
    $('allowPanel').addEventListener('keydown', function (event) { if (event.key === 'Escape') { close(); } });
    tab('apps');
  }

  window.FG.allowed = { init: init, open: open, close: close, refresh: refresh };
})();
