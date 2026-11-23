'use strict';

let genres = [
  {id: 'science-fiction', label: 'Sci-fi', name: 'Science fiction', color: 'blue'},
  {id: 'thriller', label: 'Thriller', name: 'Thriller', color: 'red'},
  {id: 'comedy', label: 'Comedy', name: 'Comedy', color: 'orange'},
  {id: 'adventure', label: 'Adventure', name: 'Adventure', color: 'green'},
  {id: 'animation', label: 'Animation', name: 'Animation', color: 'pink'},
  {id: 'romance', label: 'Romance', name: 'Romance', color: 'rose'},
];
const params = new URLSearchParams(location.search);
const roomId = location.pathname.match(/^\/g\/([A-Za-z0-9_-]+)$/)?.[1] || params.get('room');
const validRoomId = id => typeof id === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(id);
const roomPath = id => '/g/' + encodeURIComponent(id);
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;',
}[char]));
const label = id => entities.get(id)?.label ?? id.split(':').slice(1).join(':').replaceAll('-', ' ');
const tasteKey = genre => 'genre:' + genre.id;
const picks = new Map();
const entities = new Map();
let room = null;
let token = null;
let busy = false;
let reading = false;
let readVersion = 0;
let noticeTimer;
let catalogKind = 'film';
let catalogPage = [];
let catalogHasMore = false;
let searchRequest = 0;
let searchTimer;
let availableGenres = null;
let savedProfile = '';
try { if (validRoomId(roomId)) token = JSON.parse(sessionStorage.getItem('wt:' + roomId))?.token || null; }
catch { /* An invalid local record can be replaced by joining again. */ }

const stage = document.querySelector('#stage');
const screen = document.querySelector('#screen');
const index = document.querySelector('#film-index');
const frameCount = document.querySelector('#frame-count');
const tasteCount = document.querySelector('#taste-count');
const tasteBreakdown = document.querySelector('#taste-breakdown');
const shortlistButton = document.querySelector('#shortlist-button');
const announcement = document.querySelector('#announcement');
const progressHelp = document.querySelector('#progress-help');
const ballot = document.querySelector('#ballot-films');
const feature = document.querySelector('#final-feature');
const reduce = matchMedia('(prefers-reduced-motion: reduce)');
const views = [...document.querySelectorAll('.view')];
const steps = [...document.querySelectorAll('.chapters li')];
const rateButtons = [...document.querySelectorAll('.rate')];
let active = 0;
let chapter = 0;
let moving = false;
let matchConflict = null;
let touchStart;

function art(genre) {
  return `<img src="/static/cut-room/images/${genre.id}.webp" alt="" width="512" height="512" draggable="false">`;
}

function frame(genre, slot) {
  if (!genre) return `<figure class="stack-card stack-backing" data-slot="${slot}"><div class="frame"></div></figure>`;
  const picked = picks.get(tasteKey(genre));
  const caption = picked === 'like' ? 'Liked' : picked === 'avoid' ? 'Avoided' : '';
  return `<figure class="stack-card" data-slot="${slot}" data-art="${genre.color}">
    <div class="frame">${art(genre)}
      ${slot === 'active' ? `<div class="frame-label">${caption ? `<small>${caption}</small>` : ''}${genre.name}</div>` : ''}
    </div>
  </figure>`;
}

const deckFinished = () => active === genres.length;
const count = index => String(index + 1).padStart(2, '0');

function drawIndex() {
  index.innerHTML = genres.map((genre, position) => `
  <button type="button" data-genre="${position}" aria-label="${genre.name}">
    <b aria-hidden="true">${count(position)}</b> ${genre.label} <span class="mark" aria-hidden="true"></span>
  </button>`).join('');
}

function updateIndex(scrollCurrent = false) {
  for (const [position, button] of [...index.children].entries()) {
    const genre = genres[position];
    const pick = picks.get(tasteKey(genre));
    if (position === active) button.setAttribute('aria-current', 'true');
    else button.removeAttribute('aria-current');
    if (pick) button.dataset.pick = pick;
    else delete button.dataset.pick;
    button.querySelector('.mark').textContent = pick === 'like' ? '+' : '−';
    button.setAttribute('aria-label', [genre.name, pick === 'like' ? 'liked' : pick === 'avoid' ? 'avoided' : ''].filter(Boolean).join(', '));
  }
  if (scrollCurrent && !deckFinished() && index.scrollWidth > index.clientWidth) {
    const current = index.children[active];
    index.scrollTo({left: current.offsetLeft - (index.clientWidth - current.clientWidth) / 2,
      behavior: reduce.matches ? 'instant' : 'smooth'});
  }
}

function drawDeck(scrollCurrent = false) {
  const genre = genres[active];
  const finished = deckFinished();
  $('[data-action="previous"]').disabled = active === 0;
  const next = $('[data-action="next"]');
  next.disabled = finished;
  next.setAttribute('aria-label', active === genres.length - 1 ? 'Finish deck' : 'Next genre');
  $('#deck-actions').hidden = finished || !room?.me;
  frameCount.textContent = finished ? 'Deck complete' : `Card ${active + 1} of ${genres.length}`;
  if (finished) {
    delete screen.dataset.art;
    stage.removeAttribute('aria-hidden');
    stage.innerHTML = `<div class="deck-end">
      <h2 id="deck-end-title" tabindex="-1">Deck complete</h2>
      <p>Review your picks, or browse the catalogue to add more.</p>
      <div>
        <button type="button" class="rate rate-like" data-dialog="picks-dialog">See your choices</button>
        <button type="button" class="rate" data-dialog="catalog-dialog">Browse more tastes</button>
      </div>
    </div>`;
    updateIndex();
    return;
  }
  stage.setAttribute('aria-hidden', 'true');
  screen.dataset.art = genre.color;
  const supported = !availableGenres || availableGenres.has(tasteKey(genre));
  stage.innerHTML = frame(genres[active - 1], 'previous')
    + frame(genres[active + 1], 'next') + frame(genre, 'active');
  const pick = picks.get(tasteKey(genre));
  for (const button of rateButtons) {
    const action = button.dataset.action;
    button.setAttribute('aria-label', `${action[0].toUpperCase() + action.slice(1)} ${genre.name}`);
    if (action !== 'skip') {
      button.disabled = !supported;
      button.setAttribute('aria-pressed', String(pick === action));
      button.querySelector('.rate-label').textContent = action === 'like'
        ? (pick === action ? 'Liked' : 'Like')
        : (pick === action ? 'Avoided' : 'Avoid');
    }
  }
  updateIndex(scrollCurrent);
}

function announceGenre(prefix = '') {
  announcement.textContent = prefix + (deckFinished()
    ? 'Deck complete.'
    : `Card ${active + 1} of ${genres.length}. ${genres[active].name}.`);
}

function play(element, frames, options) {
  if (reduce.matches || !element?.animate) return;
  return element.animate(frames, options);
}

async function moveTo(next, action, direction = 1) {
  if (moving || busy || !room?.me || room.phase !== 'collecting') return;
  if (next === active || next < 0 || next > genres.length) return;
  moving = true;
  const current = genres[active];
  let prefix = '';
  if (action === 'like' || action === 'avoid') {
    const id = tasteKey(current);
    if (availableGenres && !availableGenres.has(id)) {
      moving = false;
      return;
    }
    if (!setPick(id, action)) {
      moving = false;
      return;
    }
    prefix = `${current.name} ${action === 'like' ? 'liked' : 'avoided'}. `;
  }

  const exit = action === 'avoid' ? -1 : action === 'like' ? 1 : -direction;
  const card = stage.querySelector('[data-slot="active"] .frame');
  const out = play(card, [
    {transform: 'none', opacity: 1},
    {transform: `translate(${exit * 58}%, ${action === 'like' ? '-18%' : '12%'}) rotate(${exit * 16}deg) scale(.88)`, opacity: 0},
  ], {duration: 230, easing: 'cubic-bezier(.52,0,.9,.48)', fill: 'forwards'});
  if (out) await out.finished.catch(() => {});
  active = Math.min(next, genres.length);
  drawDeck(true);
  play(stage.querySelector('[data-slot="active"] .frame'), [
    {transform: `translate(${direction * 21}%, 8%) rotate(${direction * 9}deg) scale(.87)`, opacity: .45},
    {transform: 'none', opacity: 1},
  ], {duration: 435, easing: 'cubic-bezier(.14,.94,.23,1)'});
  play(stage.querySelectorAll('[data-slot]:not([data-slot="active"]) .frame')[direction > 0 ? 1 : 0], [
    {transform: 'translateY(10px)', opacity: .45},
    {transform: 'none', opacity: 1},
  ], {duration: 360, easing: 'ease-out'});
  announceGenre(prefix);
  if (deckFinished()) $('#deck-end-title').focus({preventScroll: true});
  moving = false;
}

function showChapter(next, animate = true) {
  chapter = next;
  for (const [position, view] of views.entries()) {
    view.hidden = position !== next;
    const step = steps[position];
    if (position === next) step.setAttribute('aria-current', 'step');
    else step.removeAttribute('aria-current');
    step.classList.toggle('is-complete', position < next);
  }
  const current = views[next];
  if (!animate) return;
  current.querySelector('h1').focus({preventScroll: true});
  window.scrollTo({top: 0, behavior: 'instant'});
  play(current.querySelector('.brief'), [
    {opacity: .5, transform: 'translateY(12px)'}, {opacity: 1, transform: 'none'},
  ], {duration: 320, easing: 'ease-out'});
}

async function api(path, method = 'GET', body) {
  const headers = {};
  if (token) headers.Authorization = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api' + path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    const message = Array.isArray(data.detail) ? data.detail.map(item => item.msg.replace('Value error, ', '')).join('. ') : data.detail;
    const conflict = response.headers.get('X-Recommendation-Conflict');
    throw Object.assign(new Error(message || 'Couldn’t complete that request. Try again.'), {status: response.status, conflict});
  }
  return data;
}

function note(message, error = false) {
  const display = $('#notice');
  display.classList.toggle('error', error);
  display.hidden = !message;
  display.textContent = message;
  clearTimeout(noticeTimer);
  if (message && !error) noticeTimer = setTimeout(() => { display.hidden = true; }, 3500);
}

function remember({group_id: id, token: roomToken, member_id: memberId}) {
  sessionStorage.setItem('wt:' + id, JSON.stringify({token: roomToken, member_id: memberId}));
  location.assign(roomPath(id));
}

function profile() {
  const result = {likes: [], dislikes: []};
  for (const [id, choice] of picks) result[choice === 'like' ? 'likes' : 'dislikes'].push(id);
  result.likes.sort();
  result.dislikes.sort();
  return result;
}
const dirty = () => JSON.stringify(profile()) !== savedProfile;
const host = () => !!room?.me && room.me.id === room.owner_id;
const editable = () => room?.phase === 'collecting' && !!room.me;

function drawPicks() {
  const list = $('#picks-list');
  list.innerHTML = picks.size ? `<ul>${[...picks].map(([id, pick]) => `
    <li><div><strong>${esc(label(id))}</strong><br><small>${pick === 'like' ? 'Like' : 'Avoid'}</small></div>
      ${editable() ? `<button type="button" data-remove="${esc(id)}" aria-label="Remove ${esc(label(id))}">Remove</button>` : ''}</li>
  `).join('')}</ul>` : '<p>No tastes picked yet. Like or avoid an item from the deck or catalogue.</p>';
}

function drawProgress() {
  if (!editable()) return;
  const choices = profile();
  const valid = picks.size >= 3 && choices.likes.length > 0;
  const saved = room.me.ready && JSON.stringify(choices) === savedProfile;
  const ready = room.member_count >= 2 && room.members.every(member => member.ready);
  const savedCount = room.members.filter(member => member.ready).length;
  tasteCount.textContent = `${picks.size} ${picks.size === 1 ? 'choice' : 'choices'}`;
  tasteBreakdown.textContent = `${choices.likes.length} liked · ${choices.dislikes.length} avoided`;
  const save = $('#save-button');
  save.disabled = busy || !valid || saved;
  save.hidden = saved && host();
  save.innerHTML = saved ? 'Tastes saved <span aria-hidden="true">✓</span>' : 'Save my tastes <span aria-hidden="true">↗</span>';
  shortlistButton.hidden = !host() || !saved;
  shortlistButton.disabled = busy || !ready;
  const recovery = $('#match-recovery');
  recovery.hidden = !matchConflict || shortlistButton.hidden || !ready;
  const compromise = $('#compromise-button');
  compromise.hidden = matchConflict !== 'no_full_match';
  compromise.disabled = busy;
  if (matchConflict) {
    const hasOption = matchConflict === 'no_full_match';
    $('#recovery-title').textContent = hasOption ? 'No film matches everyone' : 'No films fit these choices';
    $('#recovery-copy').textContent = hasOption
      ? 'A compromise ballot can match fewer guests while still respecting every Avoid.'
      : 'Even the compromise search found no film that matches a Like and respects every Avoid. Add another Like or remove an Avoid you’re flexible on, then save again.';
  }
  if (!valid) progressHelp.textContent = picks.size >= 3 ? 'Add at least one Like to continue.' : 'Pick at least three tastes.';
  else if (!saved) progressHelp.textContent = 'Save these tastes to mark yourself ready.';
  else if (room.member_count < 2) progressHelp.textContent = 'Invite at least one friend to build your shortlist.';
  else if (!ready) progressHelp.textContent = `${savedCount} of ${room.member_count} guests ready. Waiting for the rest to save.`;
  else if (!host()) progressHelp.textContent = 'Everyone is ready. The host can build the shortlist.';
  else progressHelp.textContent = 'Everyone is ready. Start the group ballot when you’re set.';
}

function setPick(id, choice) {
  if (busy || !editable()) return false;
  if (picks.get(id) === choice) return true;
  const count = [...picks.values()].filter(value => value === choice).length;
  if (count >= 40) {
    note('You can choose up to 40 likes and 40 avoids.', true);
    return false;
  }
  picks.set(id, choice);
  matchConflict = null;
  drawProgress();
  updateIndex();
  return true;
}

function setEntry() {
  const open = !roomId || (room?.phase === 'collecting' && room.member_count < room.capacity);
  $('#entry-form').hidden = !open;
  $('#sample-button').hidden = !!roomId;
  $('#entry-catalog').hidden = false;
  $('#title-field').hidden = !!roomId;
  $('#entry-form').elements.title.required = !roomId;
  if (room) {
    $('#entry-copy').textContent = open ? `You’re invited to ${room.title}. Add a nickname to join.`
      : room.phase !== 'collecting' ? 'This round is already underway. Ask the host to start a new round so you can join.'
        : 'All the seats in this room are taken.';
  } else if (!roomId) {
    $('#entry-copy').textContent = 'Pick a film together. Create a room, send an invite, and let everyone weigh in.';
  }
  $('#entry-submit').innerHTML = (roomId ? 'Join room' : 'Create a room') + ' <span aria-hidden="true">↗</span>';
}

function updateRoom() {
  const member = !!room.me;
  const canInvite = editable() && !room.is_demo && room.member_count < room.capacity;
  $('#room-title').textContent = room.title;
  $('#sample-label').hidden = !room.is_demo;
  $('#invite-button').hidden = !member || room.is_demo;
  $('#invite-button').textContent = canInvite ? 'Invite friends ↗' : 'Room link ↗';
  $('#guests-button').hidden = !member;
  $('#chapters').hidden = !member;
  $('#room-entry').hidden = member;
  $('#room-controls').hidden = !member;
  $('#film-index').hidden = $('#deck-nav').hidden = $('#deck-actions').hidden = !member;
  if (!member) {
    setEntry();
    return;
  }
  $('#guest-button-label').textContent = 'Guests · ' + room.member_count;
  $('#avatars').innerHTML = room.members.slice(0, 3).map(member => `<b>${esc([...member.nickname][0].toUpperCase())}</b>`).join('');
  $('#delete-room').hidden = !host();
  if ($('#guests-dialog').open) drawGuests();
  if ($('#invite-dialog').open) drawInvite(false);

  const next = room.phase === 'collecting' ? 0 : room.phase === 'voting' ? 1 : 2;
  const changed = chapter !== next;
  if (changed) matchConflict = null;
  if (changed && $('#catalog-dialog').open) drawCatalogue();
  if (changed && $('#picks-dialog').open) drawPicks();
  if (next === 0) { drawProgress(); drawDeck(); }
  else if (next === 1) drawBallot(changed);
  else drawWinner(changed);
  showChapter(next, changed);
}

async function refreshRoom({quiet = false, force = false} = {}) {
  if ((!force && reading) || !validRoomId(roomId)) return;
  reading = true;
  const request = ++readVersion;
  try {
    let data;
    try { data = await api('/groups/' + roomId); }
    catch (error) {
      if (error.status !== 401 || !token || request !== readVersion) throw error;
      token = null;
      sessionStorage.removeItem('wt:' + roomId);
      data = await api('/groups/' + roomId);
    }
    if (request !== readVersion || (busy && !force)) return;
    if (JSON.stringify(room) === JSON.stringify(data)) {
      drawProgress();
      return;
    }
    if (data.me) {
      for (const item of data.me.taste_items) entities.set(item.id, item);
      const incoming = {likes: [...data.me.likes].sort(), dislikes: [...data.me.dislikes].sort()};
      if (!room?.me || !dirty() || data.phase !== room.phase) {
        picks.clear();
        incoming.likes.forEach(id => picks.set(id, 'like'));
        incoming.dislikes.forEach(id => picks.set(id, 'avoid'));
      }
      savedProfile = JSON.stringify(incoming);
    }
    room = data;
    updateRoom();
  } catch (error) {
    if (request === readVersion && !quiet) {
      if (!room) {
        $('#entry-copy').textContent = error.message;
        $('#entry-catalog').hidden = false;
      } else note(error.message, true);
    }
  } finally {
    if (request === readVersion) reading = false;
  }
}

async function submit(action, method = 'POST', body) {
  if (busy) return;
  busy = true;
  ++readVersion;
  reading = false;
  note('');
  drawProgress();
  try {
    const pathname = '/groups/' + roomId;
    const result = await api(pathname + action, method, body);
    if (action === '/profile') {
      savedProfile = JSON.stringify(body);
      note('Tastes saved.');
    }
    if (method === 'DELETE') {
      sessionStorage.removeItem('wt:' + roomId);
      location.assign('/');
      return;
    }
    if (action === '/votes') note('Vote recorded.');
    await refreshRoom({force: true});
    return result;
  } catch (error) {
    if (['no_full_match', 'no_compromise'].includes(error.conflict)) {
      matchConflict = error.conflict;
      drawProgress();
      $('#recovery-title').focus();
    } else note(error.message, true);
  }
  finally {
    busy = false;
    drawProgress();
  }
}

const poster = movie => /^https:\/\//.test(movie.image || '')
  ? `<img src="${esc(movie.image)}" alt="" referrerpolicy="no-referrer">` : '';
const movieGenres = movie => movie.genres.slice(0, 2).map(value => value.replaceAll('-', ' ')).join(' · ');
const filmTally = movie => room.tally[movie.id] || 0;

function drawBallot(animate) {
  const open = new Set([...ballot.querySelectorAll('details[open]')].map(details => details.dataset.film));
  const compromise = room.recommendations.some(movie => movie.matches.some(match => !match.because.length));
  $('#ballot-label').textContent = compromise ? 'Compromise ballot' : 'Group ballot';
  $('#ballot-copy').textContent = room.my_vote
    ? 'Your vote is in. The result appears when everyone has voted or the host closes voting.'
    : compromise ? 'These films match some guests and respect every Avoid. Choose one to vote.'
      : 'Choose one film. The film with the most votes wins.';
  $('#vote-progress').textContent = `${room.vote_count} of ${room.member_count} voted`;
  $('#close-round').hidden = $('#reset-open').hidden = !host();
  $('#close-round').disabled = !room.vote_count;
  ballot.innerHTML = room.recommendations.map(movie => `
    <article class="ballot-film">
      <div class="film-poster" data-art="rose"><span aria-hidden="true">${esc(movie.title)}</span>${poster(movie)}</div>
      <h2>${esc(movie.title)}</h2>
      <p>${esc(movie.year)} · ${esc(movieGenres(movie))}</p>
      <details class="match-details" data-film="${esc(movie.id)}" ${open.has(movie.id) ? 'open' : ''}>
        <summary>${compromise ? `Matches ${movie.matches.filter(match => match.because.length).length} of ${movie.matches.length} guests` : `${Math.round(movie.score)}% taste match`}</summary>
        ${movie.matches.map(match => `<div><strong>${esc(match.nickname)} · ${match.match}%</strong>
          <p>${match.reasons?.map(reason => esc(reason.label) + (reason.why && reason.why !== 'genre' ? ' (' + esc(reason.why) + ')' : '')).join(', ') || match.because.map(esc).join(', ') || 'No matching likes.'}</p></div>`).join('')}
      </details>
      ${room.my_vote ? `<p class="vote-label">${room.my_vote === movie.id ? '✓ Your vote' : ''}</p>` :
        `<button class="vote-button" type="button" data-vote="${esc(movie.id)}" aria-label="Vote for ${esc(movie.title)}">Vote for this ↗</button>`}
    </article>`).join('');
  if (animate) for (const [position, tile] of [...ballot.children].entries()) {
    play(tile, [{opacity: 0, transform: 'translateY(24px)'}, {opacity: 1, transform: 'none'}],
      {duration: 460, delay: 75 * position, easing: 'cubic-bezier(.2,.8,.3,1)', fill: 'backwards'});
  }
}

function drawWinner(animate) {
  const winner = room.recommendations.find(movie => movie.id === room.winner);
  if (!winner) return;
  $('#reset-finished').hidden = !host();
  const count = filmTally(winner);
  const tied = room.recommendations.some(movie => movie.id !== winner.id && filmTally(movie) === count);
  $('#final-copy').textContent = tied ? 'The vote tied. The higher ranked film won the tiebreak.' : 'The votes are in. This is your group’s pick.';
  feature.dataset.art = 'rose';
  feature.innerHTML = `<div class="final-image">${poster(winner)}</div><div class="final-caption">
    <p class="final-kicker">Tonight’s pick</p><h2>${esc(winner.title)}</h2>
    <p>${esc(winner.year)} · ${esc(movieGenres(winner))} · ${count} ${count === 1 ? 'vote' : 'votes'}</p>
    <details class="final-tally"><summary>See the final vote</summary>
      <ul>${room.recommendations.map(movie => `<li>${esc(movie.title)} <strong>${filmTally(movie)}</strong></li>`).join('')}</ul>
    </details>
  </div>`;
  if (animate) {
    play(feature, [
      {clipPath: 'inset(46% 0 46% 0 round 14px)', filter: 'brightness(1.55)'},
      {clipPath: 'inset(0 0 0 0 round 14px)', filter: 'brightness(1)'},
    ], {duration: 690, easing: 'cubic-bezier(.12,.85,.2,1)'});
    play(feature.querySelector('img'), [{transform: 'scale(1.12)'}, {transform: 'scale(1)'}],
      {duration: 1550, easing: 'cubic-bezier(.16,.7,.22,1)'});
    announcement.textContent = `Tonight’s pick is ${winner.title}.`;
  }
}

function drawGuests() {
  if (!room?.me) return;
  $('#guest-summary').textContent = room.is_demo ? 'This sample group includes automated guests.' : `${room.member_count} of ${room.capacity} seats filled.`;
  $('#guest-list').innerHTML = room.members.map(member => `
    <li><strong>${esc(member.nickname)}${member.id === room.me.id ? ' (you)' : ''}${member.id === room.owner_id ? ' · Host' : ''}</strong>
      <small>${room.phase === 'collecting' ? member.ready ? 'Tastes saved' : 'Choosing tastes'
        : member.voted ? 'Voted' : room.phase === 'finished' ? 'Voting closed' : 'Choosing a film'}</small></li>`).join('');
}

function drawInvite(reset = true) {
  $('#invite-url').value = new URL(roomPath(roomId), location.origin).href;
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  const closed = room.phase !== 'collecting' || room.member_count >= room.capacity;
  const message = $('#invite-note');
  message.textContent = [
    closed ? 'Joining is currently closed.' : '',
    local ? 'This address works on this device only. To invite friends, open the room on a reachable WatchTogether host and copy its link.' : '',
  ].filter(Boolean).join(' ');
  message.hidden = !message.textContent;
  if (reset) $('#copy-status').textContent = '';
}

async function copyInvite() {
  const input = $('#invite-url');
  try {
    await navigator.clipboard.writeText(input.value);
    $('#copy-status').textContent = 'Invite link copied.';
  } catch {
    input.focus();
    input.select();
    $('#copy-status').textContent = 'Link selected. Copy it to share.';
  }
}

const catalogueLabels = {film: 'film titles', genre: 'genres', actor: 'actors', director: 'directors'};
function drawCatalogue() {
  const results = $('#catalog-results');
  const buttons = editable() ? (item, choice) => {
    const pressed = picks.get(item.id) === choice;
    const title = choice === 'like' ? 'Like' : 'Avoid';
    return `<button type="button" data-catalog-choice="${choice}" data-id="${esc(item.id)}"
      aria-pressed="${pressed}" aria-label="${title} ${esc(item.label)}">${pressed ? choice === 'like' ? 'Liked' : 'Avoided' : title}</button>`;
  } : () => '';
  results.innerHTML = catalogPage.map(item => `
    <li>
      <span class="catalog-thumb" aria-hidden="true">${poster(item)}</span>
      <div class="catalog-label"><strong>${esc(item.label)}</strong><small>${esc(item.detail)}</small></div>
      <div class="catalog-picks">${buttons(item, 'like')}${buttons(item, 'avoid')}</div>
    </li>`).join('');
  $('#catalog-more').hidden = !catalogHasMore;
}

async function searchCatalogue(append = false) {
  const version = ++searchRequest;
  if (!append) {
    catalogPage = [];
    catalogHasMore = false;
    drawCatalogue();
  }
  const search = $('#catalog-search');
  const status = $('#catalog-status');
  status.textContent = 'Searching…';
  $('#catalog-more').disabled = true;
  try {
    const args = new URLSearchParams({q: search.value, kind: catalogKind, offset: append ? catalogPage.length : 0, limit: 16});
    const result = await api('/catalog?' + args);
    if (version !== searchRequest) return;
    const start = catalogPage.length;
    for (const item of result.items) entities.set(item.id, item);
    catalogPage.push(...result.items);
    catalogHasMore = result.has_more;
    drawCatalogue();
    status.textContent = catalogPage.length ? '' : 'No matches. Try a different search.';
    if (append && result.items.length) {
      const first = $('#catalog-results').children[start];
      const target = first.querySelector('button') || first;
      if (target === first) target.tabIndex = -1;
      target.focus();
    }
  } catch (error) {
    if (version === searchRequest) status.textContent = error.message;
  } finally {
    if (version === searchRequest) $('#catalog-more').disabled = false;
  }
}

async function loadCatalogueInfo() {
  try {
    const info = await api('/health');
    const count = new Intl.NumberFormat().format(info.films);
    $('#catalog-count').textContent = count + ' films · Genres, actors & directors';
    $('#catalog-summary').textContent = count + ' films. You can also search by genre, actor, or director.';
  } catch { $('#catalog-summary').textContent = 'Search for a film, genre, actor, or director.'; }
}

async function loadFeaturedGenres() {
  try {
    const supported = new Set();
    let offset = 0;
    let more;
    do {
      const result = await api('/catalog?kind=genre&limit=100&offset=' + offset);
      for (const item of result.items) {
        supported.add(item.id);
        entities.set(item.id, item);
      }
      offset += result.items.length;
      more = result.has_more && result.items.length > 0;
    } while (more && genres.some(genre => !supported.has(tasteKey(genre))));
    const matching = genres.filter(genre => supported.has(tasteKey(genre)));
    availableGenres = supported;
    if (matching.length > 0 && matching.length !== genres.length) {
      const current = genres[active];
      genres = matching;
      active = current ? Math.max(0, genres.indexOf(current)) : genres.length;
      drawIndex();
    }
    drawDeck();
  } catch { /* The catalogue search can retry separately if the network is busy. */ }
}

function rate(action) {
  if (chapter !== 0 || !editable()) return;
  if (deckFinished() && action !== 'previous') return;
  const direction = action === 'previous' ? -1 : 1;
  moveTo(active + direction, action, direction);
}

$('#entry-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  const button = $('#entry-submit');
  button.disabled = true;
  const {title, nickname} = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const result = roomId ? await api('/groups/' + roomId + '/members', 'POST', {nickname})
      : await api('/groups', 'POST', {title, nickname});
    remember(result);
  } catch (error) { note(error.message, true); }
  finally { busy = false; button.disabled = false; }
});

$('#catalog-search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  ++searchRequest;
  searchTimer = setTimeout(searchCatalogue, 160);
});

document.addEventListener('click', async event => {
  const button = event.target.closest('button');
  const dialog = event.target.closest('dialog');
  if (event.target === dialog) dialog?.close();
  if (!button || button.disabled) return;
  const {action, genre, vote, remove, kind, catalogChoice, id, dialog: dialogId} = button.dataset;

  if (dialogId) {
    if (dialogId === 'picks-dialog') drawPicks();
    if (dialogId === 'guests-dialog') drawGuests();
    if (dialogId === 'invite-dialog') drawInvite();
    document.getElementById(dialogId).showModal();
    if (dialogId === 'catalog-dialog') {
      $('#catalog-search').focus();
      searchCatalogue();
    }
    return;
  }
  if (button.hasAttribute('data-close')) { dialog.close(); return; }
  if (kind) {
    clearTimeout(searchTimer);
    catalogKind = kind;
    for (const filter of document.querySelectorAll('[data-kind]')) {
      filter.setAttribute('aria-pressed', String(filter.dataset.kind === kind));
    }
    $('#catalog-search').value = '';
    $('#catalog-search').placeholder = 'Search ' + catalogueLabels[kind] + '…';
    searchCatalogue();
    return;
  }
  if (catalogChoice) {
    if (setPick(id, catalogChoice)) {
      const selected = picks.get(id) === catalogChoice;
      button.setAttribute('aria-pressed', String(selected));
      button.textContent = selected ? catalogChoice === 'like' ? 'Liked' : 'Avoided' : catalogChoice === 'like' ? 'Like' : 'Avoid';
      const other = [...button.parentElement.children].find(choice => choice !== button);
      other.setAttribute('aria-pressed', 'false');
      other.textContent = catalogChoice === 'like' ? 'Avoid' : 'Like';
      drawDeck();
    }
    return;
  }
  if (remove && editable() && !busy) {
    picks.delete(remove);
    matchConflict = null;
    drawPicks();
    drawProgress();
    drawDeck();
    (dialog.querySelector('[data-remove]') || dialog.querySelector('[data-close]')).focus();
    return;
  }
  if (button === $('#save-button')) { await submit('/profile', 'PUT', profile()); return; }
  if (button === shortlistButton) { await submit('/recommendations'); return; }
  if (action === 'start-compromise') { await submit('/recommendations?allow_compromise=true'); return; }
  if (genre !== undefined && editable()) { moveTo(Number(genre), null, Math.sign(Number(genre) - active)); return; }
  if (vote && room?.phase === 'voting' && !room.my_vote) {
    button.disabled = true;
    await submit('/votes', 'POST', {film_id: vote});
    button.disabled = false;
    return;
  }

  if (action === 'demo' && !busy) {
    busy = true;
    button.disabled = true;
    try { remember(await api('/demo', 'POST')); }
    catch (error) { note(error.message, true); }
    finally { busy = false; button.disabled = false; }
  } else if (action === 'copy-invite') await copyInvite();
  else if (action === 'more-catalog') await searchCatalogue(true);
  else if (action === 'close-round' && host() && confirm('Close voting and reveal the winner?')) await submit('/close');
  else if (action === 'reset' && host() && confirm('Start a new round? Your tastes will be kept.')) await submit('/reset');
  else if (action === 'delete' && host() && confirm('Delete this room and its data? This cannot be undone.')) await submit('', 'DELETE');
  else if (['next', 'previous', 'like', 'avoid', 'skip'].includes(action)) rate(action);
});

document.addEventListener('keydown', event => {
  if (chapter !== 0 || !editable() || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
    || event.repeat || $('dialog[open]') || event.target.matches('input, textarea, select, [contenteditable]')) return;
  const actions = {ArrowLeft: 'previous', ArrowRight: 'next', a: 'avoid', s: 'skip', d: 'like'};
  if (!Object.hasOwn(actions, event.key) || (event.key.length === 1 && !screen.contains(event.target))) return;
  event.preventDefault();
  rate(actions[event.key]);
});

stage.addEventListener('pointerdown', event => {
  if (event.pointerType === 'touch' && event.isPrimary) touchStart = [event.clientX, event.clientY];
});
stage.addEventListener('pointercancel', () => { touchStart = null; });
stage.addEventListener('pointerup', event => {
  if (!touchStart || event.pointerType !== 'touch' || !event.isPrimary) return;
  const [x, y] = touchStart;
  touchStart = null;
  const delta = event.clientX - x;
  if (Math.abs(delta) > 38 && Math.abs(delta) > Math.abs(event.clientY - y) * 1.25) {
    rate(delta < 0 ? 'next' : 'previous');
  }
});

document.addEventListener('error', event => {
  if (event.target.matches?.('.catalog-thumb img, .film-poster img, .final-image img')) event.target.remove();
}, true);

drawIndex();
drawDeck();
loadCatalogueInfo();
if (validRoomId(roomId)) {
  if (params.has('room')) history.replaceState(null, '', roomPath(roomId));
  refreshRoom();
  loadFeaturedGenres();
  setInterval(() => { if (!document.hidden && !busy) refreshRoom({quiet: true}); }, 2500);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !busy) refreshRoom({quiet: true}); });
} else if (roomId || location.pathname.startsWith('/g/')) {
  $('#entry-copy').textContent = 'This room link is invalid.';
  $('#entry-catalog').hidden = false;
} else setEntry();
