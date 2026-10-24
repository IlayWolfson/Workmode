// Notification window: first step "Start now" / "Not today", then the nerd step. Each choice goes to Python,
// which prints it for the background process. The nerd step counts as red when its deadline passes.
'use strict';

let openedAt = Date.now();
let decided = false;

function choose(choice) {
  if (decided) {
    return;
  }
  if (choice !== 'nerd') {
    decided = true;
  }
  pywebview.api.choose(choice);
}

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

function showNerd(args) {
  document.getElementById('first').hidden = true;
  document.getElementById('nerdStep').hidden = false;
  choose('nerd');
  // upcoming: until the planned start (counted from opening); missed/restart: two minutes from now
  const deadline = args.kind === 'upcoming' ? openedAt + args.nerd_after_ms : Date.now() + args.nerd_after_ms;
  setTimeout(function () { choose('decline'); }, Math.max(0, deadline - Date.now()));
}

window.addEventListener('pywebviewready', function () {
  pywebview.api.args().then(function (args) {
    openedAt = Date.now();
    setText('text', args.text);
    setText('go', args.go);
    setText('no', args.no);
    setText('nerdText', args.nerd_text);
    setText('yes', args.nerd_yes);
    setText('red', args.nerd_no);
    document.getElementById('go').onclick = function () { choose('start'); };
    document.getElementById('no').onclick = function () { showNerd(args); };
    document.getElementById('yes').onclick = function () { choose('start'); };
    document.getElementById('red').onclick = function () { choose('decline'); };
  });
});
