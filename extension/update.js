// Update state for the toolbar badge, the popup and the one-shot reload. Pure: background.js and popup.js wire it.

const UP_TO_DATE = 'יש לך את הגרסה העדכנית';
const REFUSED = 'העדכון נדחה: הוא לא חתום כמו שצריך';
const APPLYING = 'מעדכן…';
const UPDATE = 'עדכון לגרסה העדכנית';
const APP_DOWN = 'Workmode לא פועל עכשיו. הפעילו אותו כדי לבדוק עדכונים, או הריצו את Update.cmd שבתיקיית ההתקנה.';
const WRONG_FOLDER =
  'Chrome טוען את התוסף מתיקייה אחרת. פתח chrome://extensions, הסר את Workmode וטען מחדש את התיקייה extension שבתיקיית ההתקנה של Workmode.';

function parse(version) {
  const match = /^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$/.exec(typeof version === 'string' ? version : '');
  return match ? match.slice(1).map(Number) : null;
}

export function compareVersions(a, b) {
  const [left, right] = [parse(a) || [0, 0, 0], parse(b) || [0, 0, 0]];
  for (let i = 0; i < 3; i++) if (left[i] !== right[i]) return left[i] > right[i] ? 1 : -1;
  return 0;
}

// Chrome keeps running the old files after an update; one reload per new version makes it read the folder again.
// Still older after that reload: Chrome loads the extension from another folder.
export function reloadDecision(appVersion, extVersion, stored) {
  if (parse(appVersion) === null || compareVersions(appVersion, extVersion) <= 0) {
    return { reload: false, store: null, wrongFolder: false };
  }
  if (stored && stored.reloadTo === appVersion) return { reload: false, store: null, wrongFolder: true };
  return { reload: true, store: { reloadTo: appVersion }, wrongFolder: false };
}

export function badgeFor(status) {
  return status && status.state === 'ready' ? '!' : '';
}

function waitButton(status, clock) {
  if (status.session_until) return { label: `יותקן אחרי שהסשן ייגמר ב-${clock(status.session_until)}`, enabled: false };
  if (status.blocked) return { label: status.blocked, enabled: false };
  return { label: UPDATE, enabled: true };
}

// status: the app's GET /update answer, or null when the app does not answer. clock(seconds) -> "HH:MM".
export function popupView(status, extVersion, wrongFolder, clock) {
  if (status === null) return { text: APP_DOWN, note: null, button: null };
  if (wrongFolder) return { text: WRONG_FOLDER, note: null, button: null };
  if (status.state === 'applying') return { text: APPLYING, note: null, button: { label: APPLYING, enabled: false } };
  const checked = status.checked_at ? `בדיקה אחרונה: ${clock(status.checked_at)}` : null;
  const failed = status.result && !status.result.ok ? status.result.message : null;
  const note = failed || checked;
  if (status.state === 'ready') {
    return { text: `גרסה ${status.available} זמינה (יש לך ${status.installed})`, note, button: waitButton(status, clock) };
  }
  if (status.state === 'refused') return { text: REFUSED, note, button: null };
  if (status.result && status.result.ok) return { text: status.result.message, note: checked, button: null };
  return { text: UP_TO_DATE, note, button: null };
}
