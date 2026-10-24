import { returnTarget } from './allowed.js';

const target = returnTarget(location.search);
if (target) {
  document.getElementById('where').textContent = new URL(target).hostname;
  const check = () =>
    chrome.runtime.sendMessage({ type: 'status' }, (reply) => {
      if (!chrome.runtime.lastError && reply && reply.enforcing === false) location.replace(target);
    });
  setInterval(check, 5000);
}
