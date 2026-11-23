'use strict';

const app = document.querySelector('#app');
const toast = document.querySelector('#toast');
let toastTimer;
let pending = false;

document.body.classList.add('cinema-home');
app.replaceChildren(document.querySelector('#landing-view').content.cloneNode(true));

function notify(message) {
  toast.textContent = message;
  toast.className = 'toast visible error';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = 'toast'; }, 5500);
}

async function startRoom(path, body) {
  const headers = body === undefined ? {} : {'Content-Type': 'application/json'};
  const response = await fetch('/api' + path, {method: 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    let detail = data.detail;
    if (Array.isArray(detail)) detail = detail.map(item => item.msg.replace('Value error, ', '')).join('. ');
    throw new Error(detail || 'Couldn’t start the room. Try again.');
  }
  sessionStorage.setItem('wt:' + data.group_id, JSON.stringify({token: data.token, member_id: data.member_id}));
  location.assign(data.join_path);
}

document.addEventListener('click', async event => {
  const trigger = event.target.closest('[data-dialog]');
  if (trigger) {
    document.getElementById(trigger.dataset.dialog).showModal();
    return;
  }
  const dialog = event.target.closest('.club-dialog');
  if (dialog && (event.target === dialog || event.target.closest('[data-close]'))) dialog.close();

  const sample = event.target.closest('[data-action="demo"]');
  if (!sample || pending) return;
  pending = sample.disabled = true;
  try { await startRoom('/demo'); }
  catch (error) { notify(error.message); }
  finally { pending = sample.disabled = false; }
});

const form = document.querySelector('#create-form');
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (pending) return;
  const button = form.querySelector('button[type="submit"]');
  const feedback = form.querySelector('#form-error');
  feedback.textContent = '';
  pending = button.disabled = true;
  try { await startRoom('/groups', Object.fromEntries(new FormData(form))); }
  catch (error) { feedback.textContent = error.message; }
  finally { pending = button.disabled = false; }
});
