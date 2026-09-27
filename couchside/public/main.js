import { encode, decode, LIMITS } from './transfer.js';
import { matrix, svgPath } from './qr.js';
import { tieText, leaning, leaningHeading } from './format.js';
import { years, runtime, seasons, joinNames, parseRoute, withShow, hue, premiere, longDate, airs,
  whereToWatch, trailerSearch } from './format.js';

const boot = JSON.parse(document.getElementById('boot').textContent);
const $ = id => document.getElementById(id);
const KEY = 'couchside-v1';
const DEFAULTS = {
  text: 40, themes: 35, genres: 25, closest: .3, dislike: .35, language: 'all', type: 'all',
  status: 'all', year_min: 1900, runtime_min: 0, rating_min: 0, known_min: 60,
};
const REACH = [85, 60, 0];
// Version 2 widened the default reach to fairly known shows of any year, once the ranking
// learned which eras and how well known a list likes.
const VERSION = 2;
const MAX_RATED = 60;
const WEIGHTS = [1, .7, .35, 0, -1];
const RATES = [
  { weight: -1, label: 'Not for me', icon: 'down', said: 'Got it. You will see less like this.' },
  { weight: .7, label: 'I like this', icon: 'up', said: 'Liked. Your rows will lean toward it.' },
  { weight: 1, label: 'Love this!', icon: 'heart', said: 'Loved. Your rows will lean hard toward it.' },
];
const VIEWS = ['home', 'welcome', 'browse', 'new', 'list', 'search'];
const TITLES = {
  home: 'Couchside', welcome: 'Welcome · Couchside', new: 'New & Popular · Couchside',
  list: 'My List · Couchside', search: 'Search · Couchside', browse: 'Browse · Couchside',
};
// Thumb, heart, search and navigation shapes follow Feather icons (MIT, Cole Bemis).
const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5l-4.3-4.3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  close: '<path d="M18 6L6 18M6 6l12 12"/>',
  info: '<circle cx="12" cy="12" r="9.5"/><path d="M12 16v-4.5M12 8h.01"/>',
  left: '<path d="M15 18l-6-6 6-6"/>',
  right: '<path d="M9 18l6-6-6-6"/>',
  up: '<path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.3a2 2 0 002-1.7l1.4-9a2 2 0 00-2-2.3zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/>',
  down: '<path d="M10 15v4a3 3 0 003 3l4-9V2H5.7a2 2 0 00-2 1.7l-1.4 9a2 2 0 002 2.3zM17 2h2.7A2.3 2.3 0 0122 4v7a2.3 2.3 0 01-2.3 2H17"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 00-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 00-7.8 7.8l1 1.1L12 21.2l7.8-7.7 1-1.1a5.5 5.5 0 000-7.8z"/>',
  out: '<path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3"/>',
  home: '<path d="M3 9.5l9-7 9 7V20a2 2 0 01-2 2h-4v-7H9v7H5a2 2 0 01-2-2z"/>',
  spark: '<path d="M23 6l-9.5 9.5-5-5L1 18M17 6h6v6"/>',
  saved: '<path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/>',
  smile: '<circle cx="12" cy="12" r="9.5"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/>',
  play: '<path d="M7 4.5v15l12.5-7.5z" fill="currentColor"/>',
  more: '<path d="M6 9l6 6 6-6"/>',
  share: '<path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8M16 6l-4-4-4 4M12 2v13"/>',
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
};

/* ------------------------------------------------------------- storage */
const fresh = () => ({ version: VERSION, profile: [], saved: [], settings: { ...DEFAULTS }, onboarded: false });
const tidy = s => ({
  id: s.id, name: typeof s.name === 'string' ? s.name : '', year: Number.isInteger(s.year) ? s.year : null,
  poster: typeof s.poster === 'string' && s.poster.startsWith('https://static.tvmaze.com/') ? s.poster : null,
});

// A stored list is read defensively: anything malformed is dropped rather than trusted.
function sanitize(raw) {
  const valid = s => s && Number.isInteger(s.id) && s.id > 0;
  const profile = [], saved = [], seen = new Set(), kept = new Set();
  for (const p of Array.isArray(raw.profile) ? raw.profile : []) {
    if (valid(p) && WEIGHTS.includes(p.weight) && !seen.has(p.id) && profile.length < MAX_RATED) {
      seen.add(p.id);
      profile.push({ ...tidy(p), weight: p.weight });
    }
  }
  for (const s of Array.isArray(raw.saved) ? raw.saved : []) {
    if (valid(s) && !kept.has(s.id) && saved.length < LIMITS.saved) {
      kept.add(s.id);
      saved.push(tidy(s));
    }
  }
  // A list saved before version 2 reached only well known shows because that was the
  // default, so it moves to the new one once.
  let reach = raw.settings?.known_min;
  if (!(raw.version >= 2) && reach === 85) reach = DEFAULTS.known_min;
  return {
    version: VERSION,
    profile, saved, settings: { ...DEFAULTS, known_min: REACH.includes(reach) ? reach : DEFAULTS.known_min },
    onboarded: raw.onboarded === true || profile.length > 0,
  };
}

let state = fresh();
try {
  const raw = JSON.parse(localStorage.getItem(KEY));
  if (raw && typeof raw === 'object') state = sanitize(raw);
} catch { /* first visit, or storage is off */ }

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode */ }
}

/* ---------------------------------------------------------------- bits */
const known = new Map();
function remember(c) {
  if (c && Number.isInteger(c.id)) known.set(c.id, { ...(known.get(c.id) || {}), ...c });
  return c;
}
const info = id => known.get(id) || state.profile.find(p => p.id === id) || state.saved.find(s => s.id === id) || { id, name: '' };
const rated = id => state.profile.find(p => p.id === id)?.weight;
const inList = id => state.saved.some(s => s.id === id);
const motion = () => !matchMedia('(prefers-reduced-motion: reduce)').matches;
const wide = () => matchMedia('(min-width: 760px)').matches;

function el(tag, text = '', cls = '') {
  const n = document.createElement(tag);
  if (text !== '' && text !== null && text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function icon(name) {
  const span = el('span', '', 'i');
  span.setAttribute('aria-hidden', 'true');
  span.innerHTML = `<svg viewBox="0 0 24 24" focusable="false">${ICONS[name]}</svg>`;
  return span;
}
function button(cls, label, onClick, iconName) {
  const b = el('button', '', cls);
  b.type = 'button';
  if (iconName) b.append(icon(iconName));
  if (label) b.append(document.createTextNode(label));
  if (onClick) b.addEventListener('click', onClick);
  return b;
}
function picture(src, cls, onLoad) {
  const img = new Image();
  img.alt = '';
  img.decoding = 'async';
  img.referrerPolicy = 'no-referrer';
  if (cls) img.className = cls;
  if (onLoad) img.addEventListener('load', onLoad, { once: true });
  if (src) img.src = src;
  return img;
}
// A poster, over a tile in the show's own colour that names it until the image arrives.
function artEl(c, src = c.poster, lazy = true) {
  const box = el('span', '', 'art');
  box.style.setProperty('--h', String(hue(c.id)));
  box.append(el('span', c.name || '', 'art-name'));
  if (src) {
    const img = picture(null);
    if (lazy) img.loading = 'lazy';
    img.addEventListener('load', () => box.classList.add('loaded'), { once: true });
    img.addEventListener('error', () => img.remove(), { once: true });
    img.src = src;
    box.append(img);
  }
  return box;
}
function fact(label, value) {
  if (!value) return null;
  const p = el('p');
  p.append(el('span', `${label}: `, 'k'), document.createTextNode(value));
  return p;
}
function skelLines(n) {
  const box = el('div');
  for (let i = 0; i < n; i++) box.append(el('span', '', 'skel line'));
  return box;
}

const POPOVER = 'showPopover' in HTMLElement.prototype;
let toastTimer = 0;
function toast(text) {
  const t = $('toast');
  t.textContent = text;
  // As a popover the toast sits in the top layer, above an open title page.
  if (POPOVER) {
    if (t.matches(':popover-open')) t.hidePopover();
    t.showPopover();
  } else t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    if (!POPOVER) t.hidden = true;
    else if (t.matches(':popover-open')) t.hidePopover();
  }, 2800);
}
if (!POPOVER) $('toast').hidden = true;

/* ----------------------------------------------------------------- api */
async function call(path, options = {}) {
  let res;
  try {
    res = await fetch(path, options);
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    const error = new Error(navigator.onLine === false
      ? 'You are offline. Couchside needs a connection to find shows.'
      : 'Couchside could not be reached. Try again in a moment.');
    error.status = 0;
    throw error;
  }
  let body = {};
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const error = new Error(body.error || 'Something went wrong. Try again in a moment.');
    error.status = res.status;
    throw error;
  }
  return body;
}
const wait = ms => new Promise(done => setTimeout(done, ms));
// Live lookups can find the server busy for a moment; one quiet retry covers that.
const patient = path => call(path).catch(e => (e.status === 503 ? wait(1500).then(() => call(path)) : Promise.reject(e)));
const post = (path, body, signal) => call(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
});
const taste = () => ({ profile: state.profile.map(({ id, weight }) => ({ id, weight })), settings: state.settings });

// Live details come once per show and are shared by the hero and the title page.
const extras = new Map();
function details(id) {
  if (!extras.has(id)) {
    extras.set(id, patient(`/api/extra?id=${id}`).then(r => r.details).catch(() => {
      extras.delete(id);
      return null;
    }));
  }
  return extras.get(id);
}

// Trailers and age ratings, once per show. A failure reads as none, and is asked again later.
const trailerCache = new Map(), ageCache = new Map();
function trailersOf(id) {
  if (!trailerCache.has(id)) {
    trailerCache.set(id, patient(`/api/trailer?id=${id}`).then(r => r.videos).catch(() => {
      trailerCache.delete(id);
      return [];
    }));
  }
  return trailerCache.get(id);
}
function ageOf(id) {
  if (!ageCache.has(id)) {
    ageCache.set(id, patient(`/api/rating?id=${id}`).catch(() => {
      ageCache.delete(id);
      return { rating: null, apple: null };
    }));
  }
  return ageCache.get(id);
}

// TMDB's data comes with a title, and with the hero, so those lookups are asked only for
// what it lacks. The Apple TV link matters only where TMDB lists nowhere to watch.
const videosOf = (id, tm) => (tm?.videos?.length ? Promise.resolve(tm.videos) : trailersOf(id));
function ratingOf(id, tm, watching = false) {
  if (tm?.rating && (!watching || tm.providers?.length)) return Promise.resolve({ rating: tm.rating, apple: null });
  return ageOf(id).then(age => ({ ...age, rating: tm?.rating || age.rating }));
}

/* -------------------------------------------------------------- routing */
let view = null;
const where = () => parseRoute(location.pathname, location.search);

function go(path) {
  if (path !== location.pathname + location.search) history.pushState(null, '', path);
  route();
}

function route() {
  const { page, q, show } = where();
  const name = page === 'home' && !state.profile.length && !state.onboarded ? 'welcome' : page;
  if (name !== view) showView(name);
  else if (name === 'browse') renderBrowse();
  if (name === 'search') search(q, false);
  if (show) {
    if (!$('title').open || titleId !== show) showTitle(show);
  } else if ($('title').open) hideTitle();
}

function showView(name) {
  view = name;
  for (const id of VIEWS) $(id).hidden = id !== name;
  const current = name === 'welcome' ? 'home' : name;
  for (const a of document.querySelectorAll('[data-page]')) {
    if (a.dataset.page === current) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  if (!$('title').open) document.title = TITLES[name];
  window.scrollTo(0, 0);
  syncNav();
  $('find').classList.toggle('open', name === 'search' && wide() && !!where().q);
  if (name === 'welcome') renderWelcome();
  if (name === 'list') renderList();
  if (name === 'new') renderNew();
  if (name === 'browse') renderBrowse();
  if (name === 'search') $('q-page').value = where().q;
}

function syncNav() {
  $('nav').classList.toggle('solid', view !== 'home' || window.scrollY > 40);
}

document.addEventListener('click', e => {
  const a = e.target.closest('a[data-link]');
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  const dialog = a.closest('dialog');
  if (dialog?.open) dialog.close();
  go(a.getAttribute('href'));
});
window.addEventListener('popstate', route);
window.addEventListener('scroll', syncNav, { passive: true });

/* ---------------------------------------------------------------- home */
let home = null, homeKey = '', homeReq = 0, homeAbort = null, homeTimer = 0;

function refresh(delay = 450) {
  clearTimeout(homeTimer);
  homeTimer = setTimeout(loadHome, delay);
}

async function loadHome() {
  const key = JSON.stringify(taste());
  if (home && key === homeKey) return;
  const id = ++homeReq;
  homeAbort?.abort();
  homeAbort = new AbortController();
  if (!home) renderHomeLoading();
  try {
    const data = await post('/api/home', { ...taste(), list: state.saved.map(s => s.id) }, homeAbort.signal);
    if (id !== homeReq) return;
    home = data;
    homeKey = key;
    remember(data.hero);
    for (const r of data.rows) r.items.forEach(remember);
    for (const list of [data.top10, data.fresh, data.soon, data.list]) list.forEach(remember);
    renderHome();
    if (view === 'new') renderNew();
    if (view === 'list') renderList();
    if (view === 'search' && where().q.trim().length < 2) suggestions();
  } catch (e) {
    if (e.name === 'AbortError' || id !== homeReq) return;
    if (home) toast(e.message);
    else {
      $('rows').replaceChildren(el('p', e.message, 'row-empty'));
      const again = button('btn ghost retry', 'Try again', () => loadHome());
      $('rows').append(again);
    }
  }
}

function skelRow() {
  const sec = el('section', '', 'row');
  sec.append(el('span', '', 'skel line row-skel'));
  const track = el('ul', '', 'track');
  for (let n = 0; n < 9; n++) {
    const li = el('li');
    li.append(el('span', '', 'skel card'));
    track.append(li);
  }
  sec.append(track);
  return sec;
}

function renderHomeLoading() {
  $('hero').replaceChildren();
  $('hero').classList.add('loading');
  $('rows').replaceChildren(skelRow(), skelRow(), skelRow());
}

function renderHome() {
  renderHero(home.hero);
  const holder = $('rows');
  holder.replaceChildren();
  if (!home.personal) {
    const invite = el('div', '', 'invite');
    const go = el('a', 'Pick shows you like', 'btn primary');
    go.href = '/welcome';
    go.dataset.link = '';
    invite.append(el('p', 'Rate a few shows and every row starts leaning your way.'), go);
    holder.append(invite);
  }
  if (home.message) holder.append(el('p', home.message, 'row-empty'));
  home.rows.forEach((r, n) => {
    holder.append(rowEl(r));
    if (n === 0) holder.append(listRow());
  });
  if (!home.rows.length) holder.append(listRow());
}

function renderHero(s) {
  const hero = $('hero');
  hero.classList.remove('has-backdrop', 'loading');
  const bg = el('div', '', 'hero-bg');
  if (s.art) bg.append(picture(s.art, 'hero-blur'));
  const backdrop = picture(null, 'hero-backdrop', () => hero.classList.add('has-backdrop'));
  bg.append(backdrop);
  const poster = artEl(s, s.art, false);
  poster.classList.add('hero-poster');
  const copy = el('div', '', 'hero-copy');
  copy.append(el('h1', s.name, 'hero-title'));
  if (s.because) {
    const why = el('p', `Because you ${s.because.loved ? 'loved' : 'liked'} ${s.because.name}`, 'hero-why');
    // A franchise or a maker in common is the strongest reason there is, so the hero says it.
    const tie = s.because.ties?.find(t => t.family === 'franchise' || t.family === 'maker');
    if (tie) why.append(document.createTextNode(` · ${tieText(tie)}`));
    copy.append(why);
  }
  const meta = metaEl(s, null, true);
  copy.append(meta);
  if (s.summary) copy.append(el('p', s.summary, 'hero-summary'));
  const acts = el('div', '', 'hero-acts');
  const more = button('btn primary', 'More info', () => openTitle(s.id), 'info');
  acts.append(more, listButton(s, 'btn'));
  copy.append(acts);
  videosOf(s.id, s.tmdb).then(videos => {
    if (!videos.length || !hero.contains(acts)) return;
    more.className = 'btn';
    acts.prepend(button('btn primary', 'Trailer', () => openTitle(s.id, { play: true }), 'play'));
  });
  ratingOf(s.id, s.tmdb).then(age => {
    if (age.rating && hero.contains(meta)) meta.insertBefore(el('span', age.rating, 'badge age'), meta.querySelector('.dot-list'));
  });
  const body = el('div', '', 'hero-body');
  body.append(poster, copy);
  hero.replaceChildren(bg, el('div', '', 'hero-shade'), body);
  // TMDB's backdrop when it has one, else TVmaze's.
  if (s.tmdb?.backdrop) backdrop.src = s.tmdb.backdrop;
  else {
    details(s.id).then(d => {
      if (d?.backdrop && hero.contains(backdrop)) backdrop.src = d.backdrop;
    });
  }
}

// "98% match · 2008–2013 · 5 Seasons", with genres instead of length over the hero.
function metaEl(s, live, hero = false, age = null) {
  const p = el('p', '', 'meta');
  if (s.match) p.append(el('b', `${s.match}% match`, 'match'));
  const span = years(s.year, s.ended);
  if (span) p.append(el('span', span));
  if (age) p.append(el('span', age, 'badge age'));
  const n = live?.seasons?.length;
  if (n) p.append(el('span', seasons(n), 'badge'));
  else if (!hero && s.runtime) p.append(el('span', `${runtime(s.runtime)} episodes`));
  if (!hero && s.type && s.type !== 'Scripted') p.append(el('span', s.type, 'badge'));
  if (hero && s.genres?.length) {
    const dots = el('span', '', 'dot-list');
    for (const g of s.genres.slice(0, 3)) dots.append(el('span', g));
    p.append(dots);
  }
  return p;
}

/* ---------------------------------------------------------- rows, cards */
let rowCount = 0;
const syncers = new Set();

function rowEl(r) {
  const sec = el('section', '', r.kind === 'soon' ? 'row soon' : 'row');
  const h = el('h2', r.title, 'row-title');
  h.id = `row-h-${++rowCount}`;
  sec.setAttribute('aria-labelledby', h.id);
  sec.dataset.key = r.key;
  const track = el('ul', '', r.kind === 'top10' ? 'track ranked' : 'track');
  r.items.forEach((c, n) => {
    const li = el('li');
    if (r.kind === 'top10') {
      const num = el('span', String(n + 1), 'num');
      num.setAttribute('aria-hidden', 'true');
      li.append(num);
    }
    li.append(cardEl(c, { rank: r.kind === 'top10' ? n + 1 : 0, soon: r.kind === 'soon' }));
    track.append(li);
  });
  const page = dir => track.scrollBy({ left: dir * track.clientWidth * .86, behavior: motion() ? 'smooth' : 'auto' });
  const prev = button('nudge prev', '', () => page(-1), 'left');
  const next = button('nudge next', '', () => page(1), 'right');
  prev.setAttribute('aria-label', `Back through ${r.title}`);
  next.setAttribute('aria-label', `More of ${r.title}`);
  const sync = () => {
    if (!track.isConnected) { syncers.delete(sync); return; }
    prev.hidden = track.scrollLeft < 8;
    next.hidden = track.scrollLeft + track.clientWidth >= track.scrollWidth - 8;
  };
  syncers.add(sync);
  track.addEventListener('scroll', () => requestAnimationFrame(sync), { passive: true });
  requestAnimationFrame(sync);
  const slider = el('div', '', 'slider');
  slider.append(prev, track, next);
  sec.append(h, slider);
  return sec;
}
window.addEventListener('resize', () => { for (const sync of [...syncers]) sync(); });

// A poster that opens the title page. On a mouse, hovering shows its match and quick
// buttons for My List and a rating; those skip the tab order, since the title page
// offers the same actions to everyone.
function cardEl(c, { rank = 0, soon = false, note = '' } = {}) {
  const card = el('div', '', 'card');
  card.dataset.id = c.id;
  const hit = button('card-hit', '', () => openTitle(c.id));
  hit.setAttribute('aria-label', [
    c.name, c.year, c.match ? `${c.match}% match` : '',
    rank ? `number ${rank} in the Top 10 today` : c.badge === 'top10' ? 'in the Top 10 today' : '',
    c.badge === 'new' ? 'new' : '', soon && c.premiered ? `premieres ${premiere(c.premiered)}` : '', note,
  ].filter(Boolean).join(', '));
  hit.append(artEl(c));
  if (c.badge === 'top10' && !rank) {
    const top = el('span', '', 'badge-top');
    top.setAttribute('aria-hidden', 'true');
    top.append(el('small', 'TOP'), el('b', '10'));
    hit.append(top);
  } else if (c.badge === 'new' && !soon) {
    const fresh = el('span', 'New', 'badge-new');
    fresh.setAttribute('aria-hidden', 'true');
    hit.append(fresh);
  }
  card.append(hit);
  const meta = el('div', '', 'card-meta');
  const quick = el('div', '', 'quick');
  const full = { ...c, ...(known.get(c.id) || {}) };
  quick.append(listButton(full, 'tiny'), ...rateButtons(full, [.7, 1], 'tiny'));
  const open = button('round tiny push', '', () => openTitle(c.id), 'more');
  open.setAttribute('aria-label', `More about ${c.name}`);
  quick.append(open);
  const words = el('div', '', 'card-words');
  words.setAttribute('aria-hidden', 'true');
  words.append(el('span', c.name, 'card-name'));
  if (c.match) words.append(el('b', `${c.match}% match`, 'match'));
  if (c.year) words.append(el('span', String(c.year)));
  if (c.genres?.length) words.append(el('span', c.genres.slice(0, 2).join(', '), 'card-genres'));
  meta.append(quick, words);
  for (const b of quick.querySelectorAll('button')) b.tabIndex = -1;
  card.append(meta);
  if (soon && c.premiered) card.append(el('span', `Premieres ${premiere(c.premiered)}`, 'soon-date'));
  return card;
}

function listRow() {
  const items = state.saved.slice().reverse().map(s => ({ ...s, ...(known.get(s.id) || {}) }));
  const sec = rowEl({ key: 'list', title: 'My List', kind: 'row', items });
  sec.id = 'row-list';
  sec.hidden = !items.length;
  return sec;
}
function updateListRow() {
  $('row-list')?.replaceWith(listRow());
}

/* ------------------------------------------------------ list and ratings */
function listButton(c, kind) {
  const cls = kind === 'btn' ? 'btn' : kind === 'wide' ? 'btn primary' : kind === 'tiny' ? 'round tiny' : 'round small';
  const b = el('button', '', cls);
  b.type = 'button';
  b.dataset.list = c.id;
  b.addEventListener('click', () => toggleList({ ...c, ...info(c.id) }));
  paintList(b);
  return b;
}
function paintList(b) {
  const id = Number(b.dataset.list);
  const on = inList(id);
  b.replaceChildren(icon(on ? 'check' : 'plus'));
  if (b.classList.contains('round')) b.setAttribute('aria-label', `My List: ${info(id).name}`);
  else b.append(document.createTextNode('My List'));
  b.setAttribute('aria-pressed', String(on));
}
function syncList(id) {
  for (const b of document.querySelectorAll(`[data-list="${id}"]`)) paintList(b);
}
function toggleList(c) {
  if (inList(c.id)) {
    state.saved = state.saved.filter(s => s.id !== c.id);
    toast(`Removed ${c.name} from My List.`);
  } else {
    if (state.saved.length >= LIMITS.saved) { toast(`My List holds ${LIMITS.saved} shows. Remove one first.`); return; }
    state.saved.push(tidy(c));
    toast(`Added ${c.name} to My List.`);
  }
  save();
  syncList(c.id);
  updateListRow();
  updateCounts();
  if (view === 'list') renderList();
}

function rateButtons(c, weights = RATES.map(r => r.weight), size = '') {
  return RATES.filter(r => weights.includes(r.weight)).map(r => {
    const b = button(`round ${r.icon}${size ? ` ${size}` : ''}`, '', () => rate({ ...c, ...info(c.id) }, r.weight), r.icon);
    b.dataset.rate = c.id;
    b.dataset.weight = String(r.weight);
    b.setAttribute('aria-label', size ? `${r.label}: ${c.name}` : r.label);
    b.title = r.label;
    b.setAttribute('aria-pressed', String(rated(c.id) === r.weight));
    return b;
  });
}
function rateGroup(c) {
  const group = el('div', '', 'rates');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', `Rate ${c.name}`);
  group.append(...rateButtons(c));
  return group;
}
function paintRates(id) {
  for (const b of document.querySelectorAll(`[data-rate="${id}"]`)) {
    b.setAttribute('aria-pressed', String(rated(id) === Number(b.dataset.weight)));
  }
}
// Tapping the pressed rating again takes it back.
function rate(c, weight) {
  const found = state.profile.find(p => p.id === c.id);
  if (found && found.weight === weight) {
    state.profile = state.profile.filter(p => p.id !== c.id);
    toast('Rating removed.');
  } else if (found) {
    found.weight = weight;
    toast(RATES.find(r => r.weight === weight).said);
  } else {
    if (state.profile.length >= MAX_RATED) {
      toast(`You have rated ${MAX_RATED} shows, the most Couchside reads. Remove a rating in My List first.`);
      return;
    }
    state.profile.push({ ...tidy(c), weight });
    toast(RATES.find(r => r.weight === weight).said);
  }
  state.onboarded = true;
  save();
  paintRates(c.id);
  updateCounts();
  if (view === 'list') renderList();
  refresh();
}

/* ----------------------------------------------------------- title page */
let T = null, titleId = null, titleToken = 0, seasonToken = 0;

function openTitle(id, { play = false } = {}) {
  const url = withShow(location.pathname, location.search, id);
  if ($('title').open) history.replaceState(history.state, '', url);
  else history.pushState({ modal: true }, '', url);
  showTitle(id, play);
}
function closeTitle() {
  if (history.state?.modal) history.back();
  else {
    history.replaceState(null, '', withShow(location.pathname, location.search, null));
    hideTitle();
  }
}
function hideTitle() {
  titleToken++;
  titleId = null;
  T = null;
  if ($('title').open) $('title').close();
  // Emptying the page also stops a trailer that is still playing.
  $('t-sheet').replaceChildren();
  document.documentElement.classList.remove('modal-open');
  document.title = TITLES[view] || 'Couchside';
}
$('title').addEventListener('cancel', e => { e.preventDefault(); closeTitle(); });
$('title').addEventListener('click', e => { if (e.target === $('title')) closeTitle(); });

function showTitle(id, play = false) {
  const token = ++titleToken;
  titleId = id;
  T = buildTitle({ ...info(id), id });
  const dialog = $('title');
  if (!dialog.open) {
    dialog.showModal();
    document.documentElement.classList.add('modal-open');
  }
  dialog.scrollTop = 0;
  T.close.focus({ preventScroll: true });
  document.title = `${T.card.name || 'Show'} · Couchside`;
  const loaded = post('/api/title', { ...taste(), id });
  loaded.then(data => {
    if (token !== titleToken) return;
    remember(data.show);
    data.more.forEach(remember);
    T.data = data;
    paintTitle();
    paintBackdrop();
    paintMore();
  }).catch(e => {
    if (token !== titleToken) return;
    T.error = e.message;
    paintTitle();
    paintBackdrop();
  });
  details(id).then(live => {
    if (token !== titleToken || !live) return;
    T.live = live;
    paintTitle();
    paintBackdrop();
    paintEpisodes();
  });
  // TMDB's trailers and rating arrive with the title; the live lookups fill in what it lacks.
  const tm = loaded.then(data => data.tmdb, () => null);
  tm.then(known => videosOf(id, known)).then(videos => {
    if (token !== titleToken) return;
    T.videos = videos;
    paintTrailerButton();
    paintVideos();
    if (play && videos.length) playVideo(videos[0]);
  });
  tm.then(known => ratingOf(id, known, true)).then(age => {
    if (token !== titleToken) return;
    T.age = age;
    paintTitle();
  });
}

// TMDB's backdrop when it has one, else TVmaze's, chosen once the title has loaded so
// one never replaces the other on screen.
function paintBackdrop() {
  if (!T || (!T.data && !T.error)) return;
  const src = T.data?.tmdb?.backdrop || T.live?.backdrop;
  if (src && T.backdrop.getAttribute('src') !== src) T.backdrop.src = src;
}

function buildTitle(c) {
  const close = button('icon-btn t-close', '', closeTitle, 'close');
  close.setAttribute('aria-label', 'Close');
  const hero = el('div', '', 't-hero');
  const art = c.art || c.poster;
  if (art) hero.append(picture(art, 't-blur'));
  const backdrop = picture(null, 't-backdrop', () => hero.classList.add('has-backdrop'));
  const poster = artEl(c, art, false);
  poster.classList.add('t-poster');
  const name = el('h2', c.name || '', 't-name');
  name.id = 't-name';
  const out = el('a', '', 'round');
  out.href = c.url || `https://www.tvmaze.com/shows/${c.id}`;
  out.target = '_blank';
  out.rel = 'noopener noreferrer';
  out.title = 'Open on TVmaze';
  out.append(icon('out'));
  const acts = el('div', '', 't-acts');
  const listed = listButton(c, 'wide');
  const share = button('round', '', shareTitle, 'share');
  share.setAttribute('aria-label', 'Share');
  share.title = 'Share';
  acts.append(listed, rateGroup(c), share, out);
  const head = el('div', '', 't-head');
  head.append(name, acts);
  hero.append(backdrop, poster, el('div', '', 't-fade'), head);
  const main = el('div', '', 't-main');
  main.append(metaEl(c, null), skelLines(4));
  const side = el('div', '', 'facts');
  const body = el('div', '', 't-body');
  body.append(main, side);
  const episodes = el('section', '', 't-section');
  episodes.hidden = true;
  episodes.setAttribute('aria-label', 'Episodes');
  const videos = el('section', '', 't-section');
  videos.hidden = true;
  videos.setAttribute('aria-label', 'Trailers and more');
  const more = el('section', '', 't-section');
  const moreH = el('h3', 'More like this');
  moreH.id = 't-more-h';
  more.setAttribute('aria-labelledby', moreH.id);
  const moreList = el('ul', '', 'more');
  for (let n = 0; n < 6; n++) {
    const li = el('li', '', 'more-card');
    li.append(el('span', '', 'skel card-fill'));
    moreList.append(li);
  }
  more.append(moreH, moreList);
  const about = el('section', '', 't-section about');
  $('t-sheet').replaceChildren(close, hero, body, episodes, videos, more, about);
  const t = { id: c.id, card: c, hero, backdrop, name, out, acts, listed, main, side, episodes, clips: videos, moreList,
              about, close, data: null, live: null, age: null, videos: null, error: '', eps: null };
  paintOut(t, c);
  return t;
}

function paintOut(t, s) {
  t.out.href = s.url || `https://www.tvmaze.com/shows/${s.id}`;
  t.out.setAttribute('aria-label', `${s.name || 'This show'} on TVmaze, opens in a new tab`);
}

function paintTitle() {
  if (!T) return;
  const s = { ...T.card, ...(T.data?.show || {}) };
  const live = T.live;
  T.name.textContent = s.name;
  document.title = `${s.name || 'Show'} · Couchside`;
  T.acts.querySelector('.rates')?.setAttribute('aria-label', `Rate ${s.name}`);
  paintOut(T, s);
  syncList(s.id);

  const main = [metaEl(s, live, false, T.age?.rating)];
  if (s.because) {
    const why = el('p', `Because you ${s.because.loved ? 'loved' : 'liked'} ${s.because.name}`, 't-why');
    if (s.because.ties?.length) why.append(el('span', ` · ${joinNames(s.because.ties.slice(0, 3).map(tieText))}`));
    else if (s.because.shared?.length) why.append(el('span', ` · shares ${s.because.shared.join(', ').toLowerCase()}`));
    main.push(why);
    if (s.because.fits?.length) main.push(el('p', `Fits your taste for ${joinNames(s.because.fits.map(leaning))}.`, 't-fits'));
  }
  const airing = live?.status === 'Running' ? airs(live.days) : '';
  if (airing) main.push(el('p', airing, 't-airs'));
  // Once the title has loaded, so TVmaze's channels never stand in for TMDB's services.
  const watch = T.data || T.error ? watchEl(s, live, T.age, T.data?.tmdb) : null;
  if (watch) main.push(watch);
  if (T.data) main.push(el('p', s.summary || 'TVmaze has no summary for this show yet.', 't-summary'));
  else if (T.error) main.push(el('p', T.error, 't-summary muted'));
  else main.push(skelLines(4));
  T.main.replaceChildren(...main);

  const cast = live?.cast?.map(p => p.name) || [];
  T.side.replaceChildren(...[
    fact('Cast', cast.length > 3 ? joinNames([...cast.slice(0, 3), 'more']) : joinNames(cast)),
    fact('Genres', s.genres?.join(', ')),
    fact('This show is about', s.themes?.slice(0, 4).join(', ').toLowerCase()),
    fact('On', s.channel),
  ].filter(Boolean));

  if (!T.data) return;
  const about = [el('h3', `About ${s.name}`)];
  if (live?.cast?.length) about.push(castEl(live.cast));
  const status = s.status === 'Ended' && s.ended ? `Ended in ${s.ended}` : s.status;
  about.push(...[
    fact('Genres', s.genres?.join(', ')),
    fact('This show is about', s.themes?.join(', ').toLowerCase()),
    fact('Network', s.channel),
    fact('Premiered', longDate(s.premiered) || (s.year ? String(s.year) : '')),
    fact('Status', status),
    fact('Seasons', live?.seasons?.length ? String(live.seasons.length) : ''),
    fact('Episodes run', s.runtime ? runtime(s.runtime) : ''),
    fact('Language', s.language),
    fact('Country', s.country),
    fact('Rating on TVmaze', s.rating ? `${s.rating} out of 10` : ''),
  ].filter(Boolean));
  const links = el('p', '', 'links-row');
  const link = (href, text) => {
    const a = el('a', text);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  };
  links.append(link(s.url || `https://www.tvmaze.com/shows/${s.id}`, 'TVmaze'));
  if (live?.imdb) links.append(document.createTextNode(' · '), link(`https://www.imdb.com/title/${live.imdb}/`, 'IMDb'));
  if (live?.site) links.append(document.createTextNode(' · '), link(live.site, 'Official site'));
  about.push(links);
  T.about.replaceChildren(...about);
}

// Where to watch: TMDB's services with their own logos, linking to TMDB's page for the
// show and credited to JustWatch; without them, where TVmaze says it streams or airs and
// Apple TV when iTunes sells it, each with the service's own small icon.
function watchEl(s, live, age, tm) {
  const { links, credit } = whereToWatch(s.name, tm, live?.site, live?.channels, age?.apple);
  if (!links.length) return null;
  const box = el('div', '', 'watch');
  box.append(el('span', 'Where to watch', 'k'));
  const list = el('div', '', 'watch-list');
  for (const w of links) {
    const a = el('a', '', 'watch-link');
    a.href = w.href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.title = w.title;
    a.setAttribute('aria-label', w.label);
    if (w.logo) {
      const logo = picture(w.logo, 'watch-icon');
      logo.width = 16;
      logo.height = 16;
      logo.addEventListener('error', () => logo.replaceWith(icon('out')), { once: true });
      a.append(logo);
    } else a.append(icon('out'));
    a.append(el('span', w.name));
    if (w.note) a.append(el('small', w.note));
    list.append(a);
  }
  box.append(list);
  if (credit) box.append(el('span', 'Streaming data from JustWatch', 'watch-credit'));
  return box;
}

// With a trailer, Trailer leads and My List steps back; without one, a search on YouTube.
function paintTrailerButton() {
  const s = { ...T.card, ...(T.data?.show || {}) };
  T.acts.querySelector('.trailer')?.remove();
  if (T.videos.length) {
    T.listed.className = 'btn';
    const b = button('btn primary trailer', 'Trailer', () => playVideo(T.videos[0]), 'play');
    T.acts.prepend(b);
  } else {
    const a = el('a', '', 'round trailer');
    a.href = trailerSearch(s.name, s.year);
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.title = 'Find a trailer on YouTube';
    a.setAttribute('aria-label', `Find a trailer for ${s.name} on YouTube, opens in a new tab`);
    a.append(icon('play'));
    T.acts.insertBefore(a, T.out);
  }
}

function paintVideos() {
  if (!T.videos.length) return;
  const list = el('ul', '', 'clips');
  for (const v of T.videos) {
    const li = el('li');
    const b = button('clip', '', () => playVideo(v));
    b.setAttribute('aria-label', `Play ${v.title || v.kind}`);
    const thumb = el('span', '', 'clip-thumb');
    const img = picture(null);
    img.loading = 'lazy';
    img.src = `https://i.ytimg.com/vi/${v.youtube}/mqdefault.jpg`;
    thumb.append(img, icon('play'));
    b.append(thumb, el('b', v.title || v.kind), el('small', [v.kind, v.published ? longDate(v.published) : ''].filter(Boolean).join(' · ')));
    li.append(b);
    list.append(li);
  }
  T.clips.replaceChildren(el('h3', 'Trailers & more'), list);
  T.clips.hidden = false;
}

// YouTube's no-cookie player, loaded only now. It takes the top of the title page, and
// the title and buttons move beneath it so nothing covers the player.
function playVideo(v) {
  if (!T) return;
  T.hero.querySelector('.t-player')?.remove();
  const frame = document.createElement('iframe');
  frame.src = `https://www.youtube-nocookie.com/embed/${v.youtube}?autoplay=1&rel=0&playsinline=1`;
  frame.title = v.title || 'Trailer';
  frame.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
  frame.allowFullscreen = true;
  // The page sends no referrer, but YouTube's player refuses to start without one.
  frame.referrerPolicy = 'strict-origin-when-cross-origin';
  const box = el('div', '', 't-player');
  box.append(frame);
  T.hero.prepend(box);
  T.hero.classList.add('playing');
  const stop = T.acts.querySelector('.trailer');
  if (stop?.tagName === 'BUTTON') {
    stop.replaceChildren(icon('close'), document.createTextNode('Stop trailer'));
    stop.onclick = stopVideo;
  }
  $('title').scrollTo({ top: 0, behavior: motion() ? 'smooth' : 'auto' });
}
function stopVideo() {
  if (!T) return;
  T.hero.querySelector('.t-player')?.remove();
  T.hero.classList.remove('playing');
  paintTrailerButton();
}

// A shared link opens straight to this title, and its preview shows the poster.
async function shareTitle() {
  if (!T) return;
  const s = { ...T.card, ...(T.data?.show || {}) };
  const url = `${location.origin}/?show=${s.id}`;
  if (navigator.share) {
    try {
      await navigator.share({ title: `${s.name} on Couchside`, text: `${s.name}${s.year ? ` (${s.year})` : ''}`, url });
    } catch { /* closed without sharing */ }
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    toast('Link copied. It opens straight to this show.');
  } catch {
    toast(`Copy this link to share it: ${url}`);
  }
}

function castEl(cast) {
  const list = el('ul', '', 'cast');
  for (const p of cast.slice(0, 12)) {
    const li = el('li');
    const face = el('span', '', 'face');
    if (p.photo) {
      const img = picture(null);
      img.loading = 'lazy';
      img.src = p.photo;
      face.append(img);
    }
    li.append(face, el('b', p.name), document.createTextNode(p.character ? `as ${p.character}` : ''));
    list.append(li);
  }
  return list;
}

function paintMore() {
  const items = T.data.more;
  T.moreList.replaceChildren(...(items.length ? items.map(moreCard)
    : [el('li', 'Nothing in the catalogue sits close enough to this one.', 'muted')]));
}
function moreCard(c) {
  const li = el('li', '', 'more-card');
  const open = button('more-open', '', () => openTitle(c.id));
  open.setAttribute('aria-label', [c.name, c.year, c.match ? `${c.match}% match` : ''].filter(Boolean).join(', '));
  open.append(artEl(c));
  const top = el('div', '', 'more-top');
  const facts = el('div', '', 'more-info');
  if (c.match) facts.append(el('b', `${c.match}% match`, 'match'));
  if (c.year) facts.append(el('span', String(c.year)));
  top.append(facts, listButton(c, 'round'));
  const body = el('div', '', 'more-body');
  body.append(el('h4', c.name), top);
  if (c.summary) body.append(el('p', c.summary));
  li.append(open, body);
  return li;
}

function paintEpisodes() {
  const list = T.live.seasons;
  if (!list.length) return;
  const head = el('div', '', 't-section-head');
  head.append(el('h3', 'Episodes'));
  let pick = null;
  if (list.length > 1) {
    pick = el('select');
    pick.setAttribute('aria-label', 'Season');
    for (const s of list) {
      const option = el('option', `Season ${s.number}${s.year ? ` (${s.year})` : ''}`);
      option.value = String(s.number);
      pick.append(option);
    }
    pick.addEventListener('change', () => loadSeason(Number(pick.value)));
    head.append(pick);
  } else head.append(el('span', `Season ${list[0].number}`, 'muted'));
  T.eps = el('ol', '', 'eps');
  T.episodes.replaceChildren(head, T.eps);
  T.episodes.hidden = false;
  loadSeason(list[0].number);
}

async function loadSeason(number) {
  const token = ++seasonToken, t = T;
  const skeleton = () => {
    const li = el('li', '', 'ep');
    li.append(el('span', '', 'ep-num'), el('span', '', 'ep-still skel'), skelLines(2));
    return li;
  };
  t.eps.replaceChildren(skeleton(), skeleton(), skeleton());
  try {
    const { episodes } = await patient(`/api/episodes?id=${t.id}&season=${number}`);
    if (token !== seasonToken || T !== t) return;
    t.eps.replaceChildren(...(episodes.length ? episodes.map(episodeEl)
      : [el('li', 'No episodes are listed for this season yet.', 'muted')]));
  } catch (e) {
    if (token === seasonToken && T === t) t.eps.replaceChildren(el('li', e.message, 'muted'));
  }
}

function episodeEl(ep) {
  const li = el('li', '', 'ep');
  li.append(el('span', ep.number ?? '', 'ep-num'));
  const still = el('span', '', 'ep-still');
  if (ep.still) {
    const img = picture(null);
    img.loading = 'lazy';
    img.src = ep.still;
    still.append(img);
  }
  const text = el('div');
  const h = el('h4', ep.number ? ep.name : `Special: ${ep.name}`);
  if (ep.runtime) h.append(el('span', runtime(ep.runtime)));
  text.append(h);
  if (ep.airdate) text.append(el('span', longDate(ep.airdate), 'ep-date'));
  if (ep.summary) text.append(el('p', ep.summary));
  li.append(still, text);
  return li;
}

/* --------------------------------------------------------------- browse */
let browseKey = null, browseReq = 0;
const genreLabel = key => boot.genres.find(g => g.key === key)?.label;

function renderBrowse() {
  const { genre } = where();
  const valid = genreLabel(genre) ? genre : '';
  const pick = $('genre-pick');
  if (!pick.options.length) {
    const all = el('option', 'All genres');
    all.value = '';
    pick.append(all, ...boot.genres.map(g => {
      const option = el('option', g.label);
      option.value = g.key;
      return option;
    }));
  }
  pick.value = valid;
  $('browse-h').textContent = valid ? genreLabel(valid) : 'Browse';
  if (!valid) {
    browseKey = '';
    const tiles = el('ul', '', 'tiles');
    tiles.append(...boot.genres.map(g => {
      const li = el('li');
      const a = el('a', '', 'tile');
      a.href = `/browse?genre=${encodeURIComponent(g.key)}`;
      a.dataset.link = '';
      a.append(artEl({ id: g.key.length * 97, name: '', poster: g.poster }), el('span', g.label, 'tile-name'));
      li.append(a);
      return li;
    }));
    $('browse-body').replaceChildren(tiles);
    return;
  }
  const key = `${valid}|${JSON.stringify(taste())}`;
  if (key === browseKey) return;
  browseKey = key;
  loadBrowse(valid);
}

async function loadBrowse(genre) {
  const id = ++browseReq;
  $('browse-body').replaceChildren(skelRow(), skelRow(), skelRow());
  try {
    const data = await post('/api/browse', { ...taste(), genre });
    if (id !== browseReq) return;
    for (const r of data.rows) r.items.forEach(remember);
    $('browse-body').replaceChildren(...(data.rows.length ? data.rows.map(rowEl)
      : [el('p', 'Nothing in this genre fits your settings yet.', 'row-empty')]));
  } catch (e) {
    if (id !== browseReq) return;
    browseKey = null;
    $('browse-body').replaceChildren(el('p', e.message, 'row-empty'));
  }
}
$('genre-pick').addEventListener('change', () => {
  const g = $('genre-pick').value;
  go(g ? `/browse?genre=${encodeURIComponent(g)}` : '/browse');
});

/* ----------------------------------------------------------- new & popular */
function renderNew() {
  const holder = $('new-body');
  if (!home) { holder.replaceChildren(skelRow(), skelRow()); return; }
  const rows = [{ key: 'top10', title: 'Top 10 shows today', kind: 'top10', items: home.top10 }];
  if (home.fresh.length) {
    rows.push({ key: 'fresh', title: home.personal ? 'New this year, picked for you' : 'New this year', kind: 'row', items: home.fresh });
  }
  if (home.soon.length) rows.push({ key: 'soon', title: 'Coming soon', kind: 'soon', items: home.soon });
  const popular = home.rows.find(r => r.key === 'popular');
  if (popular) rows.push(popular);
  holder.replaceChildren(...rows.map(rowEl));
}

/* -------------------------------------------------------------- my list */
let ratedFilter = 'all';
const GROUPS = {
  all: ['All', () => true], loved: ['Loved', p => p.weight === 1],
  liked: ['Liked', p => p.weight > 0 && p.weight < 1], down: ['Not for me', p => p.weight < 0],
};
const NOTES = { 1: 'you loved it', '-1': 'not for you' };

function fill(grid, items, options = () => ({})) {
  grid.replaceChildren(...items.map(c => {
    const li = el('li');
    li.append(cardEl(c, options(c)));
    return li;
  }));
}

function renderList() {
  const saved = state.saved.slice().reverse().map(s => ({ ...s, ...(known.get(s.id) || {}) }));
  $('list-note').textContent = saved.length
    ? `${saved.length} show${saved.length === 1 ? '' : 's'} saved for later.`
    : 'Nothing saved yet. Tap My List on any show and it waits here.';
  fill($('list-grid'), saved);

  const filters = $('rated-filter');
  filters.replaceChildren(...Object.entries(GROUPS).map(([key, [label, test]]) => {
    const b = button('chip', `${label} ${state.profile.filter(test).length}`, () => { ratedFilter = key; renderList(); });
    b.setAttribute('aria-pressed', String(ratedFilter === key));
    return b;
  }));
  filters.hidden = !state.profile.length;
  const list = state.profile.filter(GROUPS[ratedFilter][1]).slice().reverse();
  $('rated-note').textContent = !state.profile.length ? 'Nothing rated yet. Open a show and tap a thumb or the heart.'
    : list.length ? 'Open any show to change or take back its rating.' : 'Nothing here yet.';
  const grid = $('rated-grid');
  fill(grid, list.map(p => ({ ...p, ...(known.get(p.id) || {}), match: null })),
    c => ({ note: NOTES[String(rated(c.id))] || 'you liked it' }));
  for (const card of grid.querySelectorAll('.card')) {
    const weight = rated(Number(card.dataset.id));
    const badge = el('span', '', `badge-rate ${weight === 1 ? 'heart' : weight < 0 ? 'down' : 'up'}`);
    badge.setAttribute('aria-hidden', 'true');
    badge.append(icon(weight === 1 ? 'heart' : weight < 0 ? 'down' : 'up'));
    card.append(badge);
  }
}

/* --------------------------------------------------------------- search */
let searchReq = 0, searchTimer = 0;

function suggestions() {
  $('search-note').textContent = 'Search by title. Until then, here is what people are watching.';
  const popular = home?.rows.find(r => r.key === 'popular')?.items || [];
  fill($('results'), home ? [...home.top10, ...popular] : boot.starters);
}

function search(q, typed = true) {
  const query = q.trim();
  for (const input of [$('q'), $('q-page')]) if (document.activeElement !== input && input.value !== q) input.value = q;
  clearTimeout(searchTimer);
  const id = ++searchReq;
  if (query.length < 2) { suggestions(); return; }
  $('search-note').textContent = 'Searching…';
  searchTimer = setTimeout(async () => {
    try {
      const { shows } = await call(`/api/search?q=${encodeURIComponent(query)}`);
      if (id !== searchReq) return;
      shows.forEach(remember);
      $('search-note').textContent = shows.length ? `Shows matching “${query}”`
        : `Nothing in this snapshot matches “${query}”. Try a shorter title.`;
      fill($('results'), shows.map(s => ({ ...s, ...(known.get(s.id) || {}) })));
    } catch (e) {
      if (id === searchReq) $('search-note').textContent = e.message;
    }
  }, typed ? 200 : 0);
}

function typed(input) {
  const q = input.value;
  const url = q ? `/search?q=${encodeURIComponent(q)}` : '/search';
  if (view !== 'search') { history.pushState(null, '', url); showView('search'); }
  else history.replaceState(history.state, '', url);
  search(q);
}
for (const input of [$('q'), $('q-page')]) {
  input.addEventListener('input', () => typed(input));
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape' && input === $('q')) { input.value = ''; input.blur(); $('find').classList.remove('open'); }
  });
}
$('find-open').append(icon('search'));
$('find-open').addEventListener('click', () => {
  if (wide()) {
    $('find').classList.add('open');
    $('q').focus();
  } else {
    go('/search');
    $('q-page').focus();
  }
});
$('q').addEventListener('blur', () => { if (!$('q').value) $('find').classList.remove('open'); });
document.addEventListener('keydown', e => {
  if (e.key !== '/' || e.target.closest('input, textarea, select') || document.querySelector('dialog[open]')) return;
  e.preventDefault();
  $('find-open').click();
});

/* -------------------------------------------------------------- welcome */
const picked = new Set();

function renderWelcome() {
  const grid = $('starters');
  grid.replaceChildren(...boot.starters.map(c => {
    remember(c);
    const li = el('li');
    const already = rated(c.id) > 0;
    const b = button('card pick', '', () => {
      if (picked.has(c.id)) picked.delete(c.id); else picked.add(c.id);
      b.setAttribute('aria-pressed', String(picked.has(c.id)));
      syncPicks();
    });
    b.setAttribute('aria-pressed', String(already || picked.has(c.id)));
    b.setAttribute('aria-label', already ? `${c.name}, already rated` : c.name);
    b.disabled = already;
    const tick = el('span', '', 'tick');
    tick.append(icon('check'));
    b.append(artEl(c), tick);
    li.append(b);
    return li;
  }));
  syncPicks();
}

function syncPicks() {
  const liked = state.profile.filter(p => p.weight > 0).length;
  const need = Math.max(0, 3 - liked - picked.size);
  $('picked-note').textContent = need ? `Pick ${need} more to continue.`
    : picked.size ? `${picked.size} picked. Ready when you are.` : 'Ready when you are.';
  $('continue').disabled = need > 0;
}

$('continue').addEventListener('click', () => {
  for (const id of picked) {
    if (!state.profile.some(p => p.id === id) && state.profile.length < MAX_RATED) {
      state.profile.push({ ...tidy(info(id)), weight: .7 });
    }
  }
  picked.clear();
  state.onboarded = true;
  save();
  updateCounts();
  go('/');
  loadHome();
});
$('skip').addEventListener('click', () => {
  picked.clear();
  state.onboarded = true;
  save();
  go('/');
});

/* ---------------------------------------------------------- the profile */
function updateCounts() {
  $('account-counts').textContent = `${state.profile.length} rated · ${state.saved.length} in My List`;
}
let resetArmed = false;
function armReset(on) {
  resetArmed = on;
  $('reset').textContent = on ? 'Tap again to clear your ratings and list' : 'Start over';
}
for (const avatar of document.querySelectorAll('.avatar')) avatar.append(icon('smile'));
$('account-open').addEventListener('click', () => {
  updateCounts();
  $('reach').value = String(state.settings.known_min);
  armReset(false);
  $('account').showModal();
});
$('reach').addEventListener('change', () => {
  state.settings.known_min = Number($('reach').value);
  save();
  toast('Your rows will update.');
  loadHome();
});
$('reset').addEventListener('click', () => {
  if (!resetArmed) { armReset(true); return; }
  state = fresh();
  save();
  picked.clear();
  home = null;
  homeKey = '';
  $('account').close();
  go('/');
  loadHome();
  toast('Everything is cleared. Pick a few shows to start again.');
});
for (const b of document.querySelectorAll('[data-close]')) b.addEventListener('click', () => b.closest('dialog').close());
for (const d of [$('account'), $('move'), $('about'), $('taste')]) {
  d.addEventListener('click', e => { if (e.target === d) d.close(); });
}
$('open-about').addEventListener('click', () => $('about').showModal());
$('open-taste').addEventListener('click', () => { $('account').close(); paintTaste(); $('taste').showModal(); });

// What the list leans toward and away from, and its interests, from the last home answer.
function paintTaste() {
  const body = $('taste-body');
  body.replaceChildren();
  const taste = home?.personal ? home.taste : null;
  const interests = home?.personal ? home.interests || [] : [];
  if (!taste || (!taste.leans.length && !taste.avoids.length && interests.length < 2)) {
    body.append(el('p', 'Rate a few more shows and what they lean toward will show up here.'));
    return;
  }
  const section = (title, rows) => {
    if (!rows.length) return;
    body.append(el('h3', title, 'leanings-h'));
    const list = el('ul', '', 'leanings');
    for (const [head, detail] of rows) {
      const item = el('li');
      item.append(el('b', head), el('span', detail));
      list.append(item);
    }
    body.append(list);
  };
  section('What your list leans toward',
    taste.leans.map(f => [leaningHeading(f), `${f.shows} of your liked shows · ${f.base}% of all shows`]));
  section('What you steer clear of',
    taste.avoids.map(f => [leaningHeading(f), f.why === 'disliked' ? `You marked ${f.shows} not for you` : 'None on your list']));
  if (interests.length > 1) {
    section('Your interests', interests.map(it => [
      it.leans.length ? it.leans.map(l => leaningHeading({ family: '', label: l.split(' / ')[0] })).join(' · ') : `Like ${it.names[0]}`,
      it.names.join(', ')]));
    body.append(el('p', 'Your rows are shared out across these, and each Because you loved row follows one of them.', 'leanings-note'));
  }
}
$('open-about-2').addEventListener('click', () => { $('account').close(); $('about').showModal(); });

/* ------------------------------------------------------- moving devices */
function moveLink() { return `${location.origin}/#t=${encode(state)}`; }

// Dark modules on white whatever the theme: a camera needs the contrast the spec assumes.
function drawCode(link) {
  const svg = $('qr');
  svg.replaceChildren();
  const grid = link ? matrix(link) : null;
  $('qr-wrap').hidden = !grid;
  if (!grid) return;
  const { path, size } = svgPath(grid);
  svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
  const shape = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  shape.setAttribute('d', path);
  shape.setAttribute('fill', '#141414');
  const ground = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  ground.setAttribute('width', size);
  ground.setAttribute('height', size);
  ground.setAttribute('fill', '#fff');
  svg.append(ground, shape);
  $('qr-note').textContent = (grid.length - 17) / 4 > 20
    ? 'Point a camera at this. A long list makes a dense code, so fill the screen with it or send the link instead.'
    : 'Point the other phone’s camera at this.';
}

function openMove() {
  const code = state.profile.length || state.saved.length ? moveLink() : '';
  drawCode(code);
  $('move-link').value = code;
  $('move-count').textContent = code
    ? `${state.profile.length} rated and ${state.saved.length} in My List, packed into ${code.length} characters.`
    : 'Nothing to move yet. Rate a show or add one to My List first.';
  for (const id of ['copy-link', 'copy-code']) $(id).disabled = !code;
  $('copy-said').textContent = '';
  $('move-status').textContent = '';
  $('move-paste').value = '';
  $('move').showModal();
}
$('open-move').addEventListener('click', () => { $('account').close(); openMove(); });

async function copy(text, said) {
  try {
    await navigator.clipboard.writeText(text);
    $('copy-said').textContent = said;
  } catch {
    $('move-link').select();
    $('copy-said').textContent = 'Copy it by hand: the link is selected.';
  }
  setTimeout(() => { $('copy-said').textContent = ''; }, 4000);
}
$('copy-link').addEventListener('click', () => copy(moveLink(), 'Link copied.'));
$('copy-code').addEventListener('click', () => copy(encode(state), 'Code copied.'));

const codeFrom = text => (text.trim().split('#t=').pop() || '').trim();

async function bringIn(replace) {
  const raw = codeFrom($('move-paste').value);
  if (!raw) { $('move-status').textContent = 'Paste the link or code first.'; return; }
  $('move-status').textContent = 'Reading it…';
  try {
    await apply(decode(raw), replace);
    $('move').close();
  } catch (e) {
    $('move-status').textContent = e.message || 'That code could not be read.';
  }
}
$('do-merge').addEventListener('click', () => bringIn(false));
$('do-replace').addEventListener('click', () => bringIn(true));

// Titles and posters are not in the code, so the catalogue fills them back in.
async function apply(incoming, replace) {
  const ids = [...incoming.profile.map(s => s.id), ...incoming.saved.map(s => s.id)];
  const { shows } = await post('/api/shows', { ids });
  const found = new Map(shows.map(s => [s.id, remember(s)]));
  const ratings = incoming.profile.filter(s => found.has(s.id)).map(s => ({ ...tidy(found.get(s.id)), weight: s.weight }));
  const kept = incoming.saved.filter(s => found.has(s.id)).map(s => tidy(found.get(s.id)));
  if (!ratings.length && !kept.length) throw new Error('None of those shows are in this catalogue.');
  if (replace) {
    const reach = incoming.settings.known_min;
    state = {
      version: VERSION, profile: ratings.slice(0, MAX_RATED), saved: kept.slice(0, LIMITS.saved),
      settings: { ...DEFAULTS, known_min: REACH.includes(reach) ? reach : DEFAULTS.known_min }, onboarded: true,
    };
  } else {
    // Your own ratings win, so bringing the same list in twice changes nothing.
    const mine = new Set(state.profile.map(s => s.id));
    state.profile = [...state.profile, ...ratings.filter(s => !mine.has(s.id))].slice(0, MAX_RATED);
    const held = new Set([...state.profile.map(s => s.id), ...state.saved.map(s => s.id)]);
    state.saved = [...state.saved, ...kept.filter(s => !held.has(s.id))].slice(0, LIMITS.saved);
    state.onboarded = true;
  }
  save();
  updateCounts();
  go('/');
  loadHome();
  updateListRow();
  const dropped = ids.length - found.size;
  toast(`Brought in ${ratings.length} rated and ${kept.length} saved`
    + `${dropped ? `, and skipped ${dropped} no longer in the catalogue` : ''}.`);
}

// A shared link lands here. Pasting one while the app is open changes only the
// fragment, so the same read runs on hashchange too.
window.addEventListener('hashchange', () => readLink());
async function readLink() {
  const raw = location.hash.startsWith('#t=') ? location.hash.slice(3) : '';
  if (!raw) return;
  history.replaceState(history.state, '', location.pathname + location.search);
  let incoming;
  try {
    incoming = decode(raw);
  } catch (e) {
    toast(e.message || 'That shared link could not be read.');
    return;
  }
  if (!state.profile.length && !state.saved.length) {
    try {
      await apply(incoming, true);
    } catch (e) {
      openMove();
      $('move-status').textContent = e.message || 'That shared link could not be read.';
    }
    return;
  }
  openMove();
  $('move-paste').value = raw;
  $('move-status').textContent = `This link holds ${incoming.profile.length} rated and ${incoming.saved.length} saved. `
    + 'You already have a list here, so choose what to do with it.';
}

/* ------------------------------------------------------------ connection */
window.addEventListener('offline', () => toast('You are offline. Couchside will catch up when you are back.'));
window.addEventListener('online', () => {
  toast('Back online.');
  if (!home) loadHome();
  if (view === 'browse') { browseKey = null; renderBrowse(); }
});
// Offline, the service worker serves a page asking for the connection back.
if ('serviceWorker' in navigator && window.isSecureContext) {
  const register = () => navigator.serviceWorker.register('/sw.js').catch(() => {});
  if (document.readyState === 'complete') register(); else window.addEventListener('load', register);
}

/* ---------------------------------------------------------------- start */
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
for (const a of document.querySelectorAll('.dock [data-icon]')) a.prepend(icon(a.dataset.icon));
for (const b of document.querySelectorAll('.close-btn')) b.append(icon('close'));
updateCounts();
route();
loadHome();
readLink();
