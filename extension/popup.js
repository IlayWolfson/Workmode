import { FOCUS } from './config.js';
import { popupView } from './update.js';

const URL_UPDATE = `http://127.0.0.1:${FOCUS.port + 1}/update`;
const POLL_MS = 2000;
const text = document.getElementById('text');
const note = document.getElementById('note');
const button = document.getElementById('update');

const clock = (seconds) =>
  new Date(seconds * 1000).toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit', hour12: false });

async function status() {
  try {
    const response = await fetch(`${URL_UPDATE}?token=${encodeURIComponent(FOCUS.token)}`);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function render(view) {
  text.textContent = view.text;
  note.textContent = view.note || '';
  note.hidden = !view.note;
  button.hidden = view.button === null;
  if (view.button) {
    button.textContent = view.button.label;
    button.disabled = !view.button.enabled;
  }
}

async function refresh() {
  const { wrongFolder } = await chrome.storage.local.get('wrongFolder');
  const current = await status();
  render(popupView(current, chrome.runtime.getManifest().version, Boolean(wrongFolder), clock));
  return current;
}

// The app installs the update and restarts; the popup keeps asking until it answers with the outcome.
async function follow() {
  const current = await refresh();
  if (current === null || current.state === 'applying') setTimeout(follow, POLL_MS);
}

button.addEventListener('click', async () => {
  button.disabled = true;
  try {
    await fetch(URL_UPDATE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: FOCUS.token }),
    });
  } catch {
    // the app went away; follow() shows what is true now
  }
  render({ text: 'מעדכן…', note: null, button: { label: 'מעדכן…', enabled: false } });
  setTimeout(follow, POLL_MS);
});

refresh();
