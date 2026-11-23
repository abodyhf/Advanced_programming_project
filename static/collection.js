(() => {
  const shelf = document.querySelector('#collection');
  if (!shelf) return;

  const chevron = direction => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true"><path d="${direction === 'left' ? 'm14 6-6 6 6 6' : 'm10 6 6 6-6 6'}" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  shelf.innerHTML = `
    <div class="collection-heading">
      <h2 id="collection-title">From the collection</h2>
      <div class="collection-controls" aria-label="Browse collection">
        <button type="button" data-direction="-1" aria-label="Previous films" aria-controls="collection-films" disabled>${chevron('left')}</button>
        <button type="button" data-direction="1" aria-label="Next films" aria-controls="collection-films" disabled>${chevron('right')}</button>
      </div>
    </div>
    <ul class="collection-films" id="collection-films"></ul>
    <p class="collection-message" role="status">Loading films…</p>
    <dialog class="collection-dialog" aria-labelledby="collection-film-title">
      <button type="button" class="collection-close" aria-label="Close film details" autofocus>×</button>
      <div class="collection-detail"></div>
    </dialog>`;

  const track = shelf.querySelector('.collection-films');
  const [back, forward] = shelf.querySelectorAll('[data-direction]');
  const message = shelf.querySelector('.collection-message');
  const dialog = shelf.querySelector('dialog');
  const detail = dialog.querySelector('.collection-detail');
  const close = dialog.querySelector('.collection-close');
  const element = (tag, className, content) => {
    const node = document.createElement(tag);
    node.className = className;
    if (content != null) node.textContent = content;
    return node;
  };
  const genreNames = genres => genres.map(genre => genre.replaceAll('-', ' ')).join(' · ');

  function poster(film) {
    const frame = element('span', 'collection-poster');
    frame.setAttribute('aria-hidden', 'true');
    const setFallback = () => {
      frame.dataset.genre = film.genres[0] || 'drama';
      frame.replaceChildren(element('span', 'collection-fallback-title', film.title));
    };
    if (film.image && film.image.startsWith('https://')) {
      const image = new Image();
      image.alt = '';
      image.loading = 'lazy';
      image.decoding = 'async';
      image.referrerPolicy = 'no-referrer';
      image.addEventListener('error', setFallback, {once: true});
      frame.append(image);
      image.src = film.image;
    } else {
      setFallback();
    }
    return frame;
  }

  function showFilm(film) {
    const copy = element('div', 'collection-detail-copy');
    const heading = element('h2', 'collection-detail-title', film.title);
    heading.id = 'collection-film-title';
    const credits = document.createElement('dl');
    for (const [label, names] of [['Directed by', film.directors], ['Cast', film.cast]]) {
      if (names.length) {
        credits.append(element('dt', '', label), element('dd', '', names.join(', ')));
      }
    }
    copy.append(element('p', 'collection-year', String(film.year)), heading,
      element('p', 'collection-genres', genreNames(film.genres)), credits);
    detail.replaceChildren(poster(film), copy);
    dialog.showModal();
  }

  function filmCard(film) {
    const item = document.createElement('li');
    const button = element('button', 'collection-film');
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'dialog');
    button.append(poster(film), element('span', 'collection-film-title', film.title),
      element('span', 'collection-year', String(film.year)));
    button.addEventListener('click', () => showFilm(film));
    item.append(button);
    return item;
  }

  function syncControls() {
    back.disabled = track.scrollLeft < 2;
    forward.disabled = track.scrollLeft + track.clientWidth >= track.scrollWidth - 2;
  }
  for (const control of [back, forward]) {
    control.addEventListener('click', () => {
      const width = track.firstElementChild?.getBoundingClientRect().width;
      if (!width) return;
      const stride = width + parseFloat(getComputedStyle(track).columnGap);
      const visibleFilms = Math.max(1, Math.round(track.clientWidth / stride));
      track.scrollBy({left: Number(control.dataset.direction) * visibleFilms * stride,
        behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    });
  }
  track.addEventListener('scroll', syncControls, {passive: true});
  new ResizeObserver(syncControls).observe(track);
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });

  async function load() {
    try {
      const response = await fetch('/api/collection');
      if (!response.ok) throw new Error('Collection unavailable');
      const {films} = await response.json();
      if (!films.length) {
        shelf.hidden = true;
        return;
      }
      track.replaceChildren(...films.map(filmCard));
      message.hidden = true;
      syncControls();
    } catch {
      const retry = element('button', 'collection-retry', 'Try again');
      retry.type = 'button';
      retry.addEventListener('click', load, {once: true});
      message.replaceChildren('The collection could not load. ', retry);
    }
  }
  load();
})();
