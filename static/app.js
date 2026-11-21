"use strict";
const app = document.querySelector('#app');
const roomId = location.pathname.match(/^\/g\/([A-Za-z0-9_-]+)$/)?.[1];
let credentials = roomId ? JSON.parse(sessionStorage.getItem('wt:' + roomId) || 'null') : null;
let group = null, signature = '', filter = 'genre', query = '', searchTimer, toastTimer;
let likes = [], dislikes = [], dirty = false, items = [], hasMore = false, entities = new Map(), fetching = false;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const entityLabel = id => entities.get(id)?.label || id.split(':').slice(1).join(':').replaceAll('-', ' ');
const genreLabel = id => id.replaceAll('-', ' ');
const isOwner = () => group?.me?.id === group?.owner_id;
// Film pictures are remote (Wikimedia or TMDB). One that fails to load is removed so the built-in artwork shows.
const picture = (url, className) => /^https:\/\//.test(url || '') ? `<img class="${className}" src="${esc(url)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : '';
document.addEventListener('error', event => { if (event.target.matches?.('img.entity-thumb, img.movie-poster')) { event.target.parentElement.classList.remove('has-thumb'); event.target.remove(); } }, true);
document.body.classList.toggle('room-page', !!roomId);
const icon = (name, size = 18) => {
  const paths = {
    copy: '<rect x="8" y="8" width="12" height="12" rx="3"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    invite: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 4a4 4 0 0 1 0 8M20 13v6M17 16h6"/><circle cx="9" cy="7" r="4"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 10.5 6.8-4M8.6 13.5l6.8 4"/>',
    heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
    skip: '<circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/>',
    film: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/>',
    person: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>'
  };
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.film}</svg>`;
};
// One locally stored atlas keeps the genre gallery fast and available offline.
const genreScenes = {
  action: [0, 'For the adrenaline rush.'],
  adventure: [1, 'Somewhere beyond the ordinary.'],
  animation: [2, 'A little imagination. A lot of magic.'],
  comedy: [3, 'Let the good times roll.'],
  crime: [4, 'On the wrong side of the law.'],
  drama: [5, 'Stories that stay with you.'],
  family: [6, 'Something for every generation.'],
  fantasy: [7, 'Leave the everyday behind.'],
  history: [8, 'Another time. Another world.'],
  horror: [9, 'Keep the lights on.'],
  musical: [10, 'Life needs a soundtrack.'],
  mystery: [11, 'Follow the clues. Trust no one.'],
  romance: [12, 'For the hopeless romantics.'],
  'science-fiction': [13, 'To other worlds and what ifs.'],
  thriller: [14, 'One more twist. One less breath.'],
  war: [15, 'Courage against the odds.'],
  anime: [2, 'Big worlds. Unforgettable stories.'],
  heist: [4, 'The perfect plan. Almost.'],
  music: [10, 'Feel every beat.'],
  'psychological-thriller': [14, 'A beautiful game of doubt.'],
  'romantic-comedy': [12, 'Meet cute. Laugh. Fall in love.'],
  superhero: [0, 'Extraordinary people. Epic stakes.']
};
function notify(message, error = false) {
  const toast = document.querySelector('#toast');
  toast.textContent = message; toast.className = 'toast visible' + (error ? ' error' : '');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.className = 'toast', 5500);
}
async function api(path, method = 'GET', body) {
  const headers = {};
  if (credentials) headers.Authorization = 'Bearer ' + credentials.token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api' + path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    let detail = data.detail;
    if (Array.isArray(detail)) detail = detail.map(x => x.msg.replace('Value error, ', '')).join('. ');
    const error = new Error(detail || 'Something went wrong. Please try again.');
    error.status = response.status; throw error;
  }
  return data;
}
function enterRoom(result) {
  sessionStorage.setItem('wt:' + result.group_id, JSON.stringify({token: result.token, member_id: result.member_id}));
  location.href = '/g/' + result.group_id;
}
function landing() {
  app.innerHTML = `<section class="hero"><div><div class="eyebrow">The movie night starts here</div><h1>Good company.<br><em>Better movies.</em></h1><p class="hero-copy">Different tastes. One sofa. Find a film everyone can get behind, without the endless scrolling.</p><form id="create-form" class="create-panel"><div class="input-row"><div><label for="title">Your movie night</label><input id="title" name="title" placeholder="Friday film club" maxlength="60" required></div><div><label for="nickname">Your nickname</label><input id="nickname" name="nickname" placeholder="What should we call you?" maxlength="24" required autocomplete="off"></div></div><button class="button full" type="submit">Start a movie night <span>↗</span></button><div class="form-error" id="form-error" role="alert"></div><button class="demo-link" data-action="demo" type="button">Just looking? Try a sample group →</button></form><div class="no-account"><span>No account needed</span><span>2–8 friends</span><span>Everyone gets a say</span></div></div><div class="hero-art" aria-hidden="true"><div class="orbit"></div><div class="orbit two"></div><div class="cover back"><small>Find your next favorite</small><div class="shape"></div><strong>KNIVES<br>OUT</strong></div><div class="cover middle"><small>A little movie magic</small><div class="shape"></div><strong>SPIRITED<br>AWAY</strong></div><div class="cover front"><small>A Wes Anderson film</small><div class="shape"></div><strong>THE GRAND<br>BUDAPEST<br>HOTEL</strong></div><div class="art-caption"><div class="mini-avatars"><span>A</span><span>C</span><span>Y</span></div>A little something for everyone <span>✦</span></div></div></section><section class="how-it-works" aria-label="How it works"><div class="how-item"><span class="step-no">01</span><div><h3>Get your people together</h3><p>Create a room and send your friends the link.</p></div></div><div class="how-item"><span class="step-no">02</span><div><h3>Tell us what you love</h3><p>Films, genres, actors, directors. Dislikes count, too.</p></div></div><div class="how-item"><span class="step-no">03</span><div><h3>Find it. Vote. Press play.</h3><p>A shortlist for the whole group. One final pick.</p></div></div></section>`;
}
function joinScreen(info) {
  const closed = info.phase !== 'collecting' || info.member_count >= 8;
  app.innerHTML = `<div class="join-wrap panel"><div class="eyebrow">You’re invited</div><h1>${esc(info.title)}</h1><p>${info.member_count} of 8 seats taken. Add your tastes and help the group find tonight’s movie.</p>${closed ? '<div class="vote-note">' + (info.phase !== 'collecting' ? 'This round has already started. Ask the organiser to start a new round so you can join.' : 'This group is full.') + '</div>' : '<form id="join-form"><label for="nickname">Your nickname</label><input id="nickname" name="nickname" placeholder="Choose a nickname" maxlength="24" required autocomplete="off"><button class="button full" type="submit">I’m in →</button><div id="form-error" class="form-error" role="alert"></div></form>'}<p class="privacy-note">No sign-up. Just a nickname and your film tastes.<br>Inactive groups are deleted after 30 days.</p></div>`;
}
function sidebar() {
  const ready = group.members.filter(m => m.ready).length;
  return `<aside class="room-sidebar"><div class="panel company-panel"><div class="section-kicker">Better with friends</div><div class="panel-title"><h2>The good company</h2><span class="count">${group.member_count} / 8</span></div>${group.members.map(m => `<div class="member"><span class="avatar">${esc(m.nickname.slice(0,1).toUpperCase())}</span><div><div class="member-name">${esc(m.nickname)}${m.id === group.me.id ? ' (you)' : ''}${m.id === group.owner_id ? '<span class="host-badge">HOST</span>' : ''}</div><div class="member-state">${m.voted ? 'Vote is in' : m.ready ? 'Ready to go' : 'Choosing tastes'}</div></div><span class="member-check">${m.ready ? '✓' : '·'}</span></div>`).join('')}<div class="company-footer"><span>${ready} of ${group.member_count} ready</span><span>✦ Your kind of people.</span></div></div>${group.is_demo ? '<div class="demo-note"><strong>A little preview of movie night.</strong><br>Ada and Cem are sample friends. Their tastes and votes are added automatically.</div>' : ''}<div class="privacy-note">Just friends. Just film tastes.<br>No account needed. Inactive rooms disappear after 30 days.</div>${isOwner() ? '<button class="subtle-link" data-action="delete">Delete this group and its data</button>' : ''}</aside>`;
}
function inviteBanner() {
  const url = location.origin + '/g/' + roomId;
  const open = group.phase === 'collecting' && group.member_count < 8;
  return `<section class="invite-banner" id="invite-banner" aria-label="Invite friends"><div class="invite-banner-copy"><span class="invite-banner-icon">${icon('invite', 24)}</span><div><h2>${open ? 'Good movies deserve good company.' : 'Your movie-night link.'}</h2><p>${open ? 'Send the link. Bring your people. No sign-up needed.' : group.member_count >= 8 ? 'All eight seats are taken. Your group is complete.' : 'Your group is set. New friends can join when the host starts a new round.'}</p></div></div><div class="invite-controls"><div class="invite-line"><input id="invite-url" aria-label="Group invitation link" readonly title="${esc(url)}" value="${esc(url)}"><button class="button" data-action="copy" aria-label="Copy invitation link">${icon('copy', 16)}<span class="copy-label">Copy invite</span></button></div>${typeof navigator.share === 'function' ? `<button class="share-button" data-action="share" aria-label="Share invitation link">${icon('share', 18)}</button>` : ''}</div></section>`;
}
function roomView() {
  const step = group.phase === 'collecting' ? 0 : group.phase === 'voting' ? 1 : 2;
  app.innerHTML = `<div class="room-heading"><div><div class="eyebrow">Your movie night</div><h1>${esc(group.title)}</h1><p>${group.phase === 'finished' ? 'The group has spoken. Get the popcorn.' : 'Different tastes. One great movie. Make it yours.'}</p></div><div class="room-heading-actions"><span class="live-pill">${group.phase === 'collecting' ? 'Room is open' : group.phase === 'voting' ? 'Voting is live' : 'It’s movie time'}</span><button class="invite-trigger" data-action="invite">${icon('invite', 16)} Invite friends</button></div></div>${inviteBanner()}<nav class="workflow" aria-label="Movie night progress">${['Your tastes','The group shortlist','Tonight’s pick'].map((s,i)=>`<span class="${i===step?'active':''}" ${i===step?'aria-current="step"':''}><b>${i<step?'✓':'0'+(i+1)}</b> ${s}</span>`).join('')}</nav><div class="room-grid"><div class="room-main">${group.phase === 'collecting' ? profileView() : shortlistView()}</div>${sidebar()}</div>`;
  if (group.phase === 'collecting') { drawSelection(); drawResults(); updateReady(); }
}
function profileView() {
  return `<section class="panel taste-panel"><div class="section-top"><div><div class="section-kicker">A little you. A little movie magic.</div><h2>What’s your kind of movie?</h2><p>Pick at least 3 tastes, including one like. We’ll find your common ground.</p></div><span class="ready-badge" id="taste-count"><span class="selection-number">${likes.length + dislikes.length}</span> tastes picked</span></div><div class="profile-layout"><div class="taste-browser"><div class="filter-tabs" role="group" aria-label="Search category">${[['genre','Genres'],['film','Films'],['actor','Actors'],['director','Directors']].map(([id,label])=>`<button class="tab ${filter===id?'selected':''}" aria-pressed="${filter===id}" data-action="filter" data-filter="${id}">${label}</button>`).join('')}</div><div class="search-box">${icon('search', 18)}<label class="sr-only" for="taste-search" hidden>Search tastes</label><input id="taste-search" aria-label="Search films, genres, actors or directors" placeholder="Find your ${filter === 'genre' ? 'favorite genre' : filter === 'film' ? 'favorite film' : 'favorite ' + filter}…" value="${esc(query)}" maxlength="80"></div><div class="browse-caption"><span>${filter === 'genre' ? 'Explore the genres' : 'Find your favorites'}</span><span>Love it or leave it.</span></div><div class="entity-list" id="entity-list"></div></div><div class="chosen-panel"><div class="selection-section"><div class="taste-heading">${icon('heart', 14)} The things you love</div><div id="likes-chips" class="chips"></div></div><div class="selection-section"><div class="taste-heading negative">${icon('skip', 14)} Rather skip it</div><div id="dislikes-chips" class="chips"></div></div></div></div><div class="profile-actions"><span class="hint" id="profile-hint">You can change your tastes until voting starts.</span><button class="button small" id="save-button" data-action="save">Save my tastes ✓</button></div></section><div class="start-panel"><div><strong id="ready-title"></strong><p id="ready-description"></p></div>${isOwner() ? '<button class="button" id="start-button" data-action="start">Find our movies →</button>' : '<span class="count">The host starts the shortlist</span>'}</div>`;
}
function drawSelection() {
  for (const [ids, node, negative] of [[likes,'likes-chips',false],[dislikes,'dislikes-chips',true]]) {
    document.getElementById(node).innerHTML = ids.length ? ids.map(id => `<span class="chip ${negative?'negative':''}">${esc(entityLabel(id))}<button data-action="remove" data-id="${esc(id)}" aria-label="Remove ${esc(entityLabel(id))}">×</button></span>`).join('') : `<p class="empty-tastes">${negative ? 'Not your thing? We’ll keep it out.' : 'Tap Like on anything that feels like you.'}</p>`;
  }
  document.getElementById('taste-count').innerHTML = `<span class="selection-number">${likes.length + dislikes.length}</span> tastes picked`;
  document.getElementById('save-button').disabled = likes.length === 0 || likes.length + dislikes.length < 3;
  document.getElementById('save-button').textContent = !dirty && group.me.ready ? 'Tastes saved ✓' : 'Save my tastes ✓';
  document.getElementById('profile-hint').textContent = dirty ? 'Unsaved changes. Save when you’re ready.' : 'You can change your tastes until voting starts.';
}
function drawResults() {
  const node = document.querySelector('#entity-list');
  if (!node) return;
  const focused = node.contains(document.activeElement) ? {id: document.activeElement.dataset.id, action: document.activeElement.dataset.action} : null;
  node.className = 'entity-list ' + (filter === 'genre' ? 'genre-grid' : 'standard-list');
  const tasteActions = item => `<button class="taste-button ${likes.includes(item.id)?'chosen':''}" data-action="like" data-id="${esc(item.id)}" aria-label="Like ${esc(item.label)}" aria-pressed="${likes.includes(item.id)}">${icon(likes.includes(item.id)?'check':'heart', 14)} ${likes.includes(item.id)?'Liked':'Like'}</button><button class="taste-button avoid ${dislikes.includes(item.id)?'chosen':''}" data-action="dislike" data-id="${esc(item.id)}" aria-label="Avoid ${esc(item.label)}" aria-pressed="${dislikes.includes(item.id)}">${icon(dislikes.includes(item.id)?'check':'skip', 14)} Avoid</button>`;
  node.innerHTML = items.length ? items.map((item,index) => {
    if (item.kind === 'genre') {
      const [scene, description] = genreScenes[item.id.replace('genre:', '')] || [7, 'Discover a different kind of story.'];
      const liked = likes.includes(item.id), avoided = dislikes.includes(item.id);
      return `<article class="genre-card ${liked?'state-liked':avoided?'state-avoided':''}" aria-label="${esc(item.label)} genre"><div class="genre-art scene-${scene}" aria-hidden="true"></div><div class="genre-vignette" aria-hidden="true"></div><div class="genre-card-top"><span class="genre-number">${String(index+1).padStart(2,'0')} / GENRE</span>${liked||avoided?`<span class="genre-state">${icon('check',12)} ${liked?'Liked':'Avoided'}</span>`:''}</div><div class="genre-content"><h3>${esc(item.label)}</h3><p>${description}</p></div><div class="genre-actions">${tasteActions(item)}</div></article>`;
    }
    return `<div class="entity-row"><span class="entity-icon ${item.image?'has-thumb':''}" aria-hidden="true">${icon(item.kind==='film'?'film':'person',20)}${picture(item.image,'entity-thumb')}</span><div class="entity-copy"><div class="entity-name">${esc(item.label)}</div><div class="entity-detail">${esc(item.detail)}</div></div>${tasteActions(item)}</div>`;
  }).join('') + (hasMore ? `<div class="load-more-row"><button class="button secondary small" data-action="more">Load more</button><span>${items.length} shown</span></div>` : '') : '<div class="empty-results">No matches in this catalogue.<br>Try another name or category.</div>';
  if (focused) [...node.querySelectorAll('button')].find(b => b.dataset.id === focused.id && b.dataset.action === focused.action)?.focus({preventScroll:true});
}
async function searchCatalog(append = false) {
  const capturedQuery = query, capturedFilter = filter, offset = append ? items.length : 0;
  try {
    const result = await api('/catalog?q=' + encodeURIComponent(query) + '&kind=' + filter + '&offset=' + offset);
    if (capturedQuery !== query || capturedFilter !== filter) return;
    items = append ? items.concat(result.items.filter(item => !items.some(shown => shown.id === item.id))) : result.items;
    hasMore = !!result.has_more;
    if (filter === 'genre') {
      const order = ['action','musical','comedy','adventure','science-fiction','fantasy','animation','romance','thriller','drama','horror','crime','family'];
      const rank = id => { const index = order.indexOf(id.replace('genre:', '')); return index < 0 ? order.length : index; };
      items.sort((a,b) => rank(a.id)-rank(b.id) || a.label.localeCompare(b.label));
    }
    items.forEach(i => entities.set(i.id, i)); drawResults();
  } catch (error) { notify(error.message, true); }
}
function updateReady() {
  const ready = group.members.filter(m=>m.ready).length;
  document.querySelector('#ready-title').textContent = `${ready} of ${group.member_count} people ready`;
  document.querySelector('#ready-description').textContent = group.member_count < 2 ? 'Invite at least one friend using your group link.' : dirty ? 'Save your latest tastes before finding movies.' : ready === group.member_count ? 'Everyone’s tastes are in. Let’s find the overlap.' : 'The shortlist unlocks when everyone saves their tastes.';
  const button = document.querySelector('#start-button');
  if (button) button.disabled = ready !== group.member_count || group.member_count < 2 || dirty;
}
function shortlistView() {
  const winner = group.recommendations.find(movie=>movie.id===group.winner);
  return `${winner ? `<section class="winner-banner"><div class="eyebrow">Tonight, you’re watching</div><h2>${esc(winner.title)}</h2><p>${winner.year} · ${winner.genres.map(genreLabel).map(esc).join(' / ')} · ${group.tally[winner.id] || 0} vote(s)</p><div class="result-label">Picked by your people. Enjoy the movie.</div></section>` : ''}<div class="shortlist-intro"><div><h2>${winner?'The group’s shortlist':'Your common ground.'}</h2><p>Every film matches at least one like from each person. All dislikes respected.</p></div><span class="count">${group.vote_count} / ${group.member_count} votes</span></div>${!winner ? `<div class="vote-note">${group.my_vote ? 'Your vote is in. Waiting for the rest of the group…' : 'One vote each. Pick your favorite below.'} Ties go to the higher taste match.</div>` : ''}<div class="movie-grid">${group.recommendations.map((movie,index)=>movieCard(movie,index)).join('')}</div>${isOwner()?`<div class="owner-controls">${group.phase === 'voting' ? `<button class="button secondary small" data-action="close" ${group.vote_count?'':'disabled'}>Close voting with ${group.vote_count} vote(s)</button>` : ''}<button class="button secondary small" data-action="reset">Start a new round</button></div>`:''}`;
}
function movieCard(movie,index) {
  const voted = group.my_vote === movie.id;
  const disabled = group.phase !== 'voting' || !!group.my_vote;
  const scene = genreScenes[movie.genres[0]]?.[0] ?? 5;
  return `<article class="movie-card"><div class="movie-art swatch-${index%6}" aria-hidden="true"><div class="movie-scene scene-${scene}"></div>${picture(movie.image,'movie-poster')}<div class="movie-vignette"></div><span class="film-no">THE SHORTLIST / 0${index+1}</span><span class="art-title">${esc(movie.title)}</span></div><div class="movie-body"><div class="movie-meta"><span>${movie.year} · ${esc(movie.genres.slice(0,2).map(genreLabel).join(' / '))}</span><span class="match-score">${Math.round(movie.score)}% taste match</span></div><h3>${esc(movie.title)}</h3><div class="director-line">Directed by ${esc(movie.directors.join(', '))}</div><div class="cast-line">With ${esc(movie.cast.slice(0,3).join(', '))}</div><details class="match-details"><summary>Why it works for your group</summary>${movie.matches.map(match=>`<div class="match-person"><strong><span>${esc(match.nickname)}</span><span>${match.match}%</span></strong><p>Connected to: ${match.because.map(esc).join(', ')}</p></div>`).join('')}<p class="cast-line">Match scores describe shared tastes, not a prediction of how much you’ll enjoy a film.</p></details><div class="movie-vote"><span class="vote-tally">${group.tally[movie.id] || 0} vote(s)</span><button class="button ${voted?'':'secondary'} small" data-action="vote" data-id="${esc(movie.id)}" ${disabled?'disabled':''}>${voted?'Your vote ✓':group.phase==='finished'?(group.winner===movie.id?'Tonight’s pick ✦':'Voting closed'):'Vote for this →'}</button></div></div></article>`;
}
async function loadGroup(silent = false) {
  if (fetching) return;
  fetching = true;
  try {
    const result = await api('/groups/' + roomId);
    if (!credentials) { group = result; joinScreen(result); return; }
    const nextSignature = JSON.stringify(result);
    if (nextSignature === signature) return;
    const previousPhase = group?.phase;
    group = result; signature = nextSignature;
    (group.me.taste_items || []).forEach(item=>entities.set(item.id,item));
    if (!dirty || previousPhase !== group.phase) { likes = [...group.me.likes]; dislikes = [...group.me.dislikes]; dirty = false; }
    const active = document.activeElement?.id;
    const caret = document.activeElement?.selectionStart;
    roomView();
    if (active && document.getElementById(active)) { document.getElementById(active).focus(); if (caret != null) document.getElementById(active).setSelectionRange(caret,caret); }
  } catch (error) {
    if (!silent || error.status === 404 || error.status === 410) notify(error.message, true);
    if (!silent) app.innerHTML = `<div class="join-wrap panel"><h1>Couldn’t open this room</h1><p>${esc(error.message)}</p><a class="button" href="/">Back to the start →</a></div>`;
  } finally { fetching = false; }
}
document.addEventListener('submit', async event => {
  if (!['create-form','join-form'].includes(event.target.id)) return;
  event.preventDefault();
  const form = event.target, button = form.querySelector('button');
  button.disabled = true;
  const values = Object.fromEntries(new FormData(form));
  try { enterRoom(await api(form.id === 'create-form' ? '/groups' : '/groups/' + roomId + '/members','POST',values)); }
  catch (error) { form.querySelector('#form-error').textContent = error.message; button.disabled = false; }
});
document.addEventListener('input', event => {
  if (event.target.id !== 'taste-search') return;
  query = event.target.value; clearTimeout(searchTimer); searchTimer = setTimeout(searchCatalog,180);
});
document.addEventListener('click', async event => {
  const button = event.target.closest('[data-action]');
  if (!button || button.disabled) return;
  const action = button.dataset.action, id = button.dataset.id;
  try {
    if (action === 'like' || action === 'dislike' || action === 'remove') {
      const wasChosen = action === 'like' ? likes.includes(id) : dislikes.includes(id);
      likes = likes.filter(value=>value!==id); dislikes = dislikes.filter(value=>value!==id);
      if (action !== 'remove' && !wasChosen) {
        const target = action === 'like' ? likes : dislikes;
        if (target.length >= 40) { notify('Choose up to 40 likes and 40 dislikes.',true); return; }
        target.push(id);
      }
      dirty = true; drawSelection(); drawResults(); updateReady(); return;
    }
    if (action === 'more') {
      button.disabled = true; button.textContent = 'Loading…'; await searchCatalog(true); return;
    }
    if (action === 'filter') {
      filter = button.dataset.filter; query = ''; items = []; hasMore = false; roomView(); await searchCatalog(); document.querySelector('#taste-search').focus(); return;
    }
    if (action === 'invite') {
      document.querySelector('#invite-banner').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});
      document.querySelector('#invite-url').focus({preventScroll:true}); return;
    }
    if (action === 'share') {
      try { await navigator.share({title:group.title + ' · WatchTogether',text:'Join our movie night and help pick the film.',url:location.origin+'/g/'+roomId}); }
      catch (error) { if (error.name !== 'AbortError') notify('Use Copy invite to share the room link.'); }
      return;
    }
    if (action === 'copy') {
      const input = document.querySelector('#invite-url');
      try {
        await navigator.clipboard.writeText(input.value); notify('Invitation link copied. Send it to your friends.');
        button.querySelector('.copy-label').textContent = 'Copied!';
        setTimeout(() => { if (button.isConnected) button.querySelector('.copy-label').textContent = 'Copy invite'; },2400);
      }
      catch { input.focus(); input.select(); notify('Link selected. Copy it and send it to your friends.'); }
      return;
    }
    if (action === 'reset' && !confirm('Start a new round? This clears this round’s votes and shortlist. Everyone keeps their tastes.')) return;
    if (action === 'delete' && !confirm('Delete this group, all profiles, and all votes? This cannot be undone.')) return;
    button.disabled = true;
    if (action === 'demo') { enterRoom(await api('/demo','POST')); return; }
    const path = '/groups/' + roomId;
    if (action === 'save') {
      await api(path + '/profile','PUT',{likes,dislikes}); dirty = false; signature = ''; notify('Tastes saved. You’re ready!');
    } else if (action === 'start') await api(path + '/recommendations','POST');
    else if (action === 'vote') { await api(path + '/votes','POST',{film_id:id}); notify('Your vote is in!'); }
    else if (action === 'close') await api(path + '/close','POST');
    else if (action === 'reset') await api(path + '/reset','POST');
    else if (action === 'delete') { await api(path,'DELETE'); sessionStorage.removeItem('wt:' + roomId); location.href='/'; return; }
    await loadGroup();
  } catch (error) { notify(error.message,true); }
  finally { if (button.isConnected) button.disabled = false; }
});
if (roomId) {
  loadGroup().then(searchCatalog);
  setInterval(()=> { if (credentials && !document.hidden) loadGroup(true); },3000);
} else landing();
