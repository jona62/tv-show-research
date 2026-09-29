import { encode, decode, LIMITS } from './transfer.js';
import { matrix, svgPath } from './qr.js';
import { tieText, leaning, leaningHeading } from './format.js';
import { years, runtime, seasons, joinNames, parseRoute, withShow, hue, premiere, longDate, airs,
  whereToWatch, trailerSearch, searchNote } from './format.js';
import { pageKey, resumable, keptText, shownRows, withoutCard, viewedStore, noteViewed, recentlyViewed } from './format.js';
import { genreChoices, nextByLetter, searchText, recentStore, noteSearch, withoutSearch, recentMatches } from './format.js';
import { keeper, sessionAnswers } from './format.js';
import { SNIPPETS, snippet, revealLabel, fitsOnLine } from './format.js';
import { freshStore, today, dayNumber, noteSeen, noteEngaged, noteRow, noteHero, prune, freshness, watcher }
  from './fresh.js';
import { daySeed, startersQuery, mergeStarters, browserLanguage, MAX_ROUND, MAX_PICKED } from './starters.js';
import { sheets, closing, reveal, crossfade, peeks, edgeBack } from './gestures.js';

const boot = JSON.parse(document.getElementById('boot').textContent);
// iOS zooms into a field it judges small and stays zoomed. maximum-scale=1 in the page's
// viewport stops that, while iOS still lets fingers pinch; elsewhere the limit would stop
// the pinch as well, so it comes off.
const IOS = /iP(hone|ad|od)/.test(navigator.userAgent)
  || (!/Android/.test(navigator.userAgent) && navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
if (!IOS) {
  const viewport = document.querySelector('meta[name="viewport"]');
  if (viewport) viewport.content = viewport.content.replace(/,\s*maximum-scale=1/, '');
}
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
  clock: '<circle cx="12" cy="12" r="9.5"/><path d="M12 6.5V12l3.5 2"/>',
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

// What this browser has shown and what you engaged with (fresh.js), so each day's page
// is fresh: kept under its own key, one salt per browser, pruned on every load. Writes
// are batched, since a scroll can see dozens of titles.
const FRESH_KEY = 'couchside-fresh';
let memory;
try { memory = freshStore(JSON.parse(localStorage.getItem(FRESH_KEY))); } catch { memory = freshStore(null); }
prune(memory, today());
let memoryTimer = 0;
function keepMemory(now = false) {
  clearTimeout(memoryTimer);
  const write = () => { try { localStorage.setItem(FRESH_KEY, JSON.stringify(memory)); } catch { /* private mode */ } };
  if (now) write(); else memoryTimer = setTimeout(write, 1000);
}
// Written at once, so the welcome page's starters (starters.js) find this salt, not a second.
keepMemory(true);
// Engaging with a title (opening it, rating it, listing it, its trailer, a link out)
// spares it from fatigue for two weeks; engaging with a card also wakes the row it is in.
function engaged(id, row = '') {
  const day = today();
  noteEngaged(memory, id, day);
  if (row) noteRow(memory, row, day, true);
  keepMemory();
}
// What a request carries about the day: its date, its seed and the memory's counts. A
// browser without crypto.subtle (a page not served over https) sends none.
async function freshFields() {
  try { return await freshness(memory, today()); } catch { return {}; }
}
const TAG = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,3}$/;
const languages = () => (navigator.languages?.length ? [...navigator.languages] : [navigator.language || ''])
  .filter(t => TAG.test(t)).slice(0, 8);

// Titles opened lately, for Recently viewed.
const VIEWED_KEY = 'couchside-viewed';
let viewed = [];
try { viewed = viewedStore(JSON.parse(localStorage.getItem(VIEWED_KEY))); } catch { /* first visit */ }
function noteOpened(c) {
  viewed = noteViewed(viewed, c, dayNumber(today()));
  try { localStorage.setItem(VIEWED_KEY, JSON.stringify(viewed)); } catch { /* private mode */ }
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
// Every image is asked for with CORS, which TVmaze, TMDB and YouTube's image servers all
// allow, so the service worker can keep a readable copy (sw.js) rather than an opaque one.
function picture(src, cls, onLoad) {
  const img = new Image();
  img.alt = '';
  img.decoding = 'async';
  img.referrerPolicy = 'no-referrer';
  img.crossOrigin = 'anonymous';
  if (cls) img.className = cls;
  if (onLoad) img.addEventListener('load', onLoad, { once: true });
  if (src) img.src = src;
  return img;
}
// Posters a view is about to draw again, by address, while redraw runs: artEl hands them
// over instead of making new ones, so drawing a list again neither asks for a poster
// again nor fades it in a second time.
let spare = null;
function redraw(holder, draw) {
  const outer = spare;
  spare = new Map();
  for (const art of holder.querySelectorAll('.art[data-src]')) spare.set(art.dataset.src, art);
  try { return draw(); } finally { spare = outer; }
}
// A poster, over a tile in the show's own colour that names it until the image arrives.
function artEl(c, src = c.poster, lazy = true) {
  const kept = src && spare?.get(src);
  if (kept) {
    spare.delete(src);
    return kept;
  }
  const box = el('span', '', 'art');
  box.style.setProperty('--h', String(hue(c.id)));
  box.append(el('span', c.name || '', 'art-name'));
  if (src) {
    box.dataset.src = src;
    const img = picture(null);
    if (lazy) img.loading = 'lazy';
    img.addEventListener('load', () => box.classList.add('loaded'), { once: true });
    img.addEventListener('error', () => img.remove(), { once: true });
    img.src = src;
    // One this page already holds shows at once, without fading in again.
    if (img.complete && img.naturalWidth) box.classList.add('loaded');
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
async function request(path, options = {}) {
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

// What the page has been told is kept by what it asked (keeper in format.js): a title, a
// genre's rows, a search and a show's live details come back without a request for a
// while, and two asking at once share one. Live details, which the server fetches from
// TVmaze, KinoCheck and iTunes, also outlast a reload of the tab in sessionStorage. The
// home page keeps itself (keepPage).
const MINUTE = 60_000;
const KEEP = {
  '/api/extra': 30, '/api/trailer': 30, '/api/rating': 30, '/api/episodes': 30,
  '/api/search': 10, '/api/title': 10, '/api/browse': 10,
};
const LIVE = ['/api/extra', '/api/trailer', '/api/rating', '/api/episodes'];
const ANSWERS_KEY = 'couchside-answers';
const asked = keeper();
let answers = {};
try { answers = sessionAnswers(JSON.parse(sessionStorage.getItem(ANSWERS_KEY)), Date.now(), 30 * MINUTE); } catch { /* none yet */ }
function keepAnswers() {
  answers = sessionAnswers(answers, Date.now(), 30 * MINUTE);
  try { sessionStorage.setItem(ANSWERS_KEY, JSON.stringify(answers)); } catch { /* storage full or off */ }
}
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') keepAnswers(); });
window.addEventListener('pagehide', keepAnswers);

function call(path, options) {
  const route = path.split('?')[0];
  if (options || !KEEP[route]) return request(path, options);
  const ms = KEEP[route] * MINUTE;
  return asked(path, ms, () => {
    const held = answers[path];
    if (held && Date.now() - held.at < ms) return held.value;
    return request(path).then(value => {
      if (LIVE.includes(route)) answers[path] = { at: Date.now(), value };
      return value;
    });
  });
}
const wait = ms => new Promise(done => setTimeout(done, ms));
// Live lookups can find the server busy for a moment; one quiet retry covers that.
const patient = path => call(path).catch(e => (e.status === 503 ? wait(1500).then(() => call(path)) : Promise.reject(e)));
// A title's page and a genre's rows follow your list, your settings and what is asked,
// not what this browser has seen since, so they are kept by those alone.
function post(path, body, signal) {
  const send = () => request(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  });
  if (!KEEP[path]) return send();
  const { profile, settings, id, genre } = body;
  return asked(`${path} ${JSON.stringify([profile, settings, id, genre])}`, KEEP[path] * MINUTE, send);
}
const taste = () => ({ profile: state.profile.map(({ id, weight }) => ({ id, weight })), settings: state.settings });

// Live details, trailers and age ratings, shared by the hero and the title page. A
// failure reads as none, and is asked again next time.
const details = id => patient(`/api/extra?id=${id}`).then(r => r.details).catch(() => null);
const trailersOf = id => patient(`/api/trailer?id=${id}`).then(r => r.videos).catch(() => []);
const ageOf = id => patient(`/api/rating?id=${id}`).catch(() => ({ rating: null, apple: null }));

// TMDB's data comes with a title, and with the hero, so those lookups are asked only for
// what it lacks. The Apple TV link matters only where TMDB lists nowhere to watch.
const videosOf = (id, tm) => (tm?.videos?.length ? Promise.resolve(tm.videos) : trailersOf(id));
function ratingOf(id, tm, watching = false) {
  if (tm?.rating && (!watching || tm.providers?.length)) return Promise.resolve({ rating: tm.rating, apple: null });
  return ageOf(id).then(age => ({ ...age, rating: tm?.rating || age.rating }));
}

/* -------------------------------------------------------------- routing */
let view = null;
let dockY = 0;       // where the page was when the dock last tucked or came back
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
  // A tab changes at once, as a phone's own tab bars do: a crossfade here made the whole
  // page, dock and all, shimmer through two copies of itself.
  paintView(name);
}

function paintView(name) {
  for (const id of VIEWS) $(id).hidden = id !== name;
  const current = name === 'welcome' ? 'home' : name;
  for (const a of document.querySelectorAll('[data-page]')) {
    if (a.dataset.page === current) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  if (!$('title').open) document.title = TITLES[name];
  window.scrollTo(0, 0);
  // A new view starts at the top with the dock whole, not easing out of its tuck.
  const dock = $('dock');
  if (dock.classList.contains('tucked')) {
    dock.classList.add('still');
    dock.classList.remove('tucked');
    requestAnimationFrame(() => requestAnimationFrame(() => dock.classList.remove('still')));
  }
  dockY = 0;
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
// Installed, a swipe in from the left edge goes back from a title page or a view off home.
edgeBack(() => !!titleId || (view !== 'home' && !document.querySelector('dialog[open]')),
  () => (titleId ? closeTitle() : history.back()));

/* ---------------------------------------------------------------- home */
// The page arrives eight rows at a time: the first answer brings the hero and the first
// eight, and as the reader nears the end the next six are asked for, telling the server
// which rows are already shown so it builds the same page. Within a visit the page holds
// still: a reload within half an hour on the same day with the same list shows it again
// as it was, and a rating or a My List change merges into it rather than laying it out
// again. Impressions are only written down, never a reason to re-render.
let home = null, homeKey = '', homeReq = 0, homeAbort = null, homeTimer = 0, moreBusy = false;
const PAGE_KEY = 'couchside-home';
const currentKey = () => pageKey(taste(), state.saved.map(s => s.id));

function refresh(delay = 450) {
  clearTimeout(homeTimer);
  homeTimer = setTimeout(loadHome, delay);
}

// The page kept for this tab: what was shown, for the day and list it was made for. A
// page grown past KEEP_CHARS keeps its first rows and asks for the rest again (keptText).
function keepPage() {
  if (!home) return;
  try {
    sessionStorage.setItem(PAGE_KEY, keptText({ v: 1, at: Date.now(), day: home.day, key: homeKey, home }));
  } catch { /* storage full or off: the page is simply asked for again next time */ }
}
function keptPage(key, day) {
  try {
    const kept = JSON.parse(sessionStorage.getItem(PAGE_KEY));
    return resumable(kept, { key, day, now: Date.now() }) ? kept.home : null;
  } catch { return null; }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') { keepPage(); keepMemory(true); }
});
window.addEventListener('pagehide', () => { keepPage(); keepMemory(true); });

function rememberHome(data) {
  if (data.hero) remember(data.hero);
  for (const r of data.rows) r.items.forEach(remember);
  for (const list of [data.top10, data.fresh, data.soon, data.list, data.popular]) (list || []).forEach(remember);
}

async function loadHome() {
  const key = currentKey();
  if (home && key === homeKey) return;
  const id = ++homeReq;
  homeAbort?.abort();
  homeAbort = new AbortController();
  const day = today();
  const kept = keptPage(key, day);
  if (kept) {
    home = kept;
    homeKey = key;
    rememberHome(home);
    renderHome();
    return;
  }
  if (!home) renderHomeLoading();
  try {
    const data = await post('/api/home', {
      ...taste(), list: state.saved.map(s => s.id), ...await freshFields(), lang: languages(),
    }, homeAbort.signal);
    if (id !== homeReq) return;
    home = { ...data, day, tasteKey: key };
    homeKey = key;
    rememberHome(data);
    redraw($('rows'), renderHome);
    keepPage();
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

// What asking for more rows carries: the list as it is now, the day, and the rows shown.
async function moreBody(count) {
  const listIds = state.saved.slice().reverse().map(s => s.id);
  return {
    ...taste(), list: state.saved.map(s => s.id), ...await freshFields(), lang: languages(),
    shown: shownRows(home.rows, listIds), count,
  };
}

// The next rows, once the reader is within a screen of the end. After a rating or a My
// List change the request carries the new list, so the rows not yet shown are built
// from it while those on screen stay as they are.
async function loadMore() {
  if (!home?.more || moreBusy) return;
  moreBusy = true;
  const id = homeReq;
  try {
    const data = await post('/api/home', await moreBody(6));
    if (id !== homeReq || !home) return;
    rememberHome(data);
    home.rows.push(...data.rows);
    Object.assign(home, { more: data.more, taste: data.taste, interests: data.interests, tasteKey: homeKey });
    appendRows(data.rows);
    keepPage();
    syncFoot();
  } catch (e) {
    moreButton.hidden = !home?.more;
    toast(e.message);
  } finally {
    moreBusy = false;
    // Rows that arrive short of filling the screen leave the end in view: look again.
    if (moreWatch && home?.more) { moreWatch.unobserve(sentinel); moreWatch.observe(sentinel); }
  }
}
const sentinel = el('div', '', 'more-rows');
const moreButton = button('btn ghost', 'More rows', () => loadMore());
// The foot of the page, once the server has no more rows: a quiet note and a way back up.
const pageEnd = el('div', '', 'page-end');
pageEnd.append(el('p', 'That’s everything for today. Rate more shows to grow your rows.'),
  button('btn ghost', 'Back to top', () => {
    $('page').focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: motion() ? 'smooth' : 'auto' });
  }));
sentinel.append(moreButton, pageEnd);
const moreWatch = 'IntersectionObserver' in window
  ? new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) loadMore(); },
    { rootMargin: '0px 0px 100% 0px' })
  : null;
// More rows where the scroll cannot be watched, and the end once there are no more.
function syncFoot() {
  moreButton.hidden = !home?.more || !!moreWatch;
  pageEnd.hidden = !home || home.more || !home.rows.length;
}

// Impressions: a card half on screen for a second counts as seen once a day, and a row
// seen that way counts as passed over for the day unless a card in it is engaged with.
const seenWatch = watcher(id => { noteSeen(memory, id, today()); keepMemory(); });
const rowWatch = watcher(key => { noteRow(memory, key, today()); keepMemory(); });

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
  // The hero rests for a week once shown, so the next days' are others.
  noteHero(memory, home.hero.id, today());
  keepMemory();
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
  holder.append(sentinel);
  appendRows(home.rows);
  // My List keeps a place after the first row even while empty, so adding a show shows it.
  if (!$('row-list')) {
    const first = holder.querySelector('section.row');
    if (first) first.after(listRow()); else holder.insertBefore(listRow(), sentinel);
  }
  syncFoot();
  if (moreWatch) {
    moreWatch.unobserve(sentinel);
    if (home.more) moreWatch.observe(sentinel);
  }
}

// Rows go in before the sentinel as they arrive; Recently viewed, which the browser
// makes itself, goes in after the third.
function appendRows(rows) {
  const holder = $('rows');
  for (const r of rows) {
    holder.insertBefore(r.kind === 'list' ? listRow() : rowEl(r, { watch: true }), sentinel);
    if (!$('row-recent') && holder.querySelectorAll('section.row').length === 3) {
      holder.insertBefore(recentRow(), sentinel);
    }
  }
  if (!$('row-recent') && !home.more) holder.insertBefore(recentRow(), sentinel);
  // On phones each new row eases in as it comes into view (gestures.js).
  reveal(holder.querySelectorAll('section.row'));
}

// After a rating or a My List change: the card leaves the rows chosen for you, and every
// other card and row keeps its place. The rows not yet shown will come from the new list.
// A first liked show turns a first visit's page into a personal one, so that one reloads.
function settleHome(id) {
  if (!home) return;
  if (!home.personal && state.profile.some(p => p.weight > 0)) { refresh(); return; }
  home.rows = withoutCard(home.rows, id);
  for (const card of $('rows').querySelectorAll(`section.row[data-kind="row"] .card[data-id="${id}"]`)) {
    card.closest('li')?.remove();
  }
  homeKey = currentKey();
  updateRecentRow();
  keepPage();
}

// Recently viewed: titles you opened in the last fortnight and have not rated or listed.
function recentRow() {
  const rated = new Set(state.profile.map(p => p.id)), saved = new Set(state.saved.map(s => s.id));
  const items = recentlyViewed(viewed, dayNumber(today()), { rated, saved })
    .map(v => ({ ...v, ...(known.get(v.id) || {}) }));
  const sec = rowEl({ key: 'recent', title: 'Recently viewed', kind: 'recent', items });
  sec.id = 'row-recent';
  sec.hidden = !items.length;
  return sec;
}
function updateRecentRow() {
  const row = $('row-recent');
  if (row) redraw(row, () => row.replaceWith(recentRow()));
}

function renderHero(s) {
  const hero = $('hero');
  hero.classList.remove('has-backdrop', 'loading');
  const bg = el('div', '', 'hero-bg');
  if (s.art) bg.append(picture(s.art, 'hero-blur'));
  const backdrop = picture(null, 'hero-backdrop', () => hero.classList.add('has-backdrop'));
  // Phones hide the backdrop, and a lazy image that is hidden is never fetched.
  backdrop.loading = 'lazy';
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
  // On phones a new hero crossfades over the one before (gestures.js).
  crossfade(hero, bg, el('div', '', 'hero-shade'), body);
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

// A row of posters. On the home page (watch) its cards count toward what this browser
// has seen, and the row toward rows passed over; a click on any card in it counts as
// engaging with the row.
function rowEl(r, { watch = false } = {}) {
  const sec = el('section', '', r.kind === 'soon' ? 'row soon' : 'row');
  const h = el('h2', r.title, 'row-title');
  h.id = `row-h-${++rowCount}`;
  sec.setAttribute('aria-labelledby', h.id);
  sec.dataset.key = r.key;
  sec.dataset.kind = r.kind;
  const track = el('ul', '', r.kind === 'top10' ? 'track ranked' : 'track');
  const row = watch && (r.kind === 'row' || r.kind === 'top10') ? r.key : '';
  r.items.forEach((c, n) => {
    const li = el('li');
    if (r.kind === 'top10') {
      const num = el('span', String(n + 1), 'num');
      num.setAttribute('aria-hidden', 'true');
      li.append(num);
    }
    const card = cardEl(c, { rank: r.kind === 'top10' ? n + 1 : 0, soon: r.kind === 'soon', row });
    if (watch) seenWatch.observe(card, c.id);
    li.append(card);
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
  sec.append(h);
  // "For fans of Breaking Bad and The Wire", read out as part of the row's name.
  if (r.subtitle) {
    const sub = el('p', r.subtitle, 'row-sub');
    sub.id = `row-s-${rowCount}`;
    sec.setAttribute('aria-describedby', sub.id);
    sec.append(sub);
  }
  sec.append(slider);
  if (row) rowWatch.observe(sec, row);
  return sec;
}
window.addEventListener('resize', () => { for (const sync of [...syncers]) sync(); });

// A poster that opens the title page. On a mouse, hovering shows its match and quick
// buttons for My List and a rating; those skip the tab order, since the title page
// offers the same actions to everyone. A card may carry one call-out, such as "Same
// creator as Breaking Bad".
function cardEl(c, { rank = 0, soon = false, note = '', row = '' } = {}) {
  const card = el('div', '', 'card');
  card.dataset.id = c.id;
  const hit = button('card-hit', '', () => openTitle(c.id, { row }));
  hit.setAttribute('aria-label', [
    c.name, c.year, c.match ? `${c.match}% match` : '',
    rank ? `number ${rank} in the Top 10 today` : c.badge === 'top10' ? 'in the Top 10 today' : '',
    c.badge === 'new' ? 'new' : '', soon && c.premiered ? `premieres ${premiere(c.premiered)}` : '', c.callout, note,
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
  if (c.callout) {
    const said = el('span', c.callout, 'callout');
    said.setAttribute('aria-hidden', 'true');
    hit.append(said);
    card.classList.add('has-callout');
  }
  card.append(hit);
  if (row) card.addEventListener('click', () => { noteRow(memory, row, today(), true); keepMemory(); });
  const meta = el('div', '', 'card-meta');
  const quick = el('div', '', 'quick');
  const full = { ...c, ...(known.get(c.id) || {}) };
  quick.append(listButton(full, 'tiny'), ...rateButtons(full, [.7, 1], 'tiny'));
  const open = button('round tiny push', '', () => openTitle(c.id, { row }), 'more');
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

// A long press on a poster, on a touch screen, lifts it into a peek (gestures.js) with the
// quick buttons the hover shows: more info, My List, I like this and Love this. More info
// and the poster do what a tap on the card does.
function peekOf(card, close) {
  const c = info(Number(card.dataset.id));
  const open = () => { close(true); card.querySelector('.card-hit').click(); };
  const art = button('peek-art', '', open);
  art.setAttribute('aria-label', `Open ${c.name}`);
  art.append(artEl(c, c.poster, false));
  const panel = el('div', '', 'peek-panel');
  panel.append(el('h2', c.name, 'peek-name'), metaEl(c, null));
  if (c.genres?.length) panel.append(el('p', c.genres.join(', '), 'peek-genres'));
  // Two actions fit a phone's peek: the title page, one tap on, rates it.
  const acts = el('div', '', 'peek-acts');
  acts.append(button('btn primary', 'More info', open, 'info'), listButton(c, 'btn'));
  panel.append(acts);
  const box = el('div', '', 'peek-box');
  box.append(art, panel);
  return box;
}
peeks(peekOf);

function listRow() {
  const items = state.saved.slice().reverse().slice(0, 20).map(s => ({ ...s, ...(known.get(s.id) || {}) }));
  const sec = rowEl({ key: 'list', title: 'My List', kind: 'list', items });
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
  engaged(c.id);
  syncList(c.id);
  updateListRow();
  updateCounts();
  if (view === 'list') renderList();
  settleHome(c.id);
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
  engaged(c.id);
  paintRates(c.id);
  updateCounts();
  if (view === 'list') renderList();
  if (home) settleHome(c.id); else refresh();
}

/* ----------------------------------------------------------- title page */
let T = null, titleId = null, titleToken = 0, seasonToken = 0;

function openTitle(id, { play = false, row = '' } = {}) {
  engaged(id, row);
  noteOpened(info(id));
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
  // A trailer stops at once. The rest of the page goes once the sheet has slid away.
  $('t-sheet').querySelector('.t-player iframe')?.remove();
  if ($('title').open) $('title').close();
  document.documentElement.classList.remove('modal-open');
  document.title = TITLES[view] || 'Couchside';
  if (view === 'home') updateRecentRow();
}
// The page is emptied once its sheet has closed, unless a title opened again meanwhile.
$('title').addEventListener('close', () => { if (!titleId) $('t-sheet').replaceChildren(); });
$('title').addEventListener('cancel', e => { e.preventDefault(); closeTitle(); });
$('t-sheet').addEventListener('click', e => { if (titleId && e.target.closest('a[target="_blank"]')) engaged(titleId); });
$('title').addEventListener('click', e => { if (e.target === $('title')) closeTitle(); });
// Every dialog is a sheet (gestures.js): a swipe down closes it as its close button does,
// and the title page through its history.
sheets(d => (d === $('title') ? closeTitle() : d.close()));

function showTitle(id, play = false) {
  const token = ++titleToken;
  titleId = id;
  T = buildTitle({ ...info(id), id });
  const dialog = $('title');
  // A title page still sliding away comes back up.
  if (!dialog.open || closing(dialog)) {
    dialog.showModal();
    document.documentElement.classList.add('modal-open');
  }
  dialog.scrollTop = 0;
  T.close.focus({ preventScroll: true });
  document.title = `${T.card.name || 'Show'} · Couchside`;
  const loaded = freshFields().then(fresh => post('/api/title', { ...taste(), ...fresh, id }));
  loaded.then(data => {
    if (token !== titleToken) return;
    remember(data.show);
    [...data.more, ...(data.fans || [])].forEach(remember);
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
  backdrop.loading = 'lazy';
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
  // The round buttons keep to a line of their own on a phone, under Trailer and My List.
  const icons = el('div', '', 't-icons');
  icons.append(rateGroup(c), share, out);
  acts.append(listed, icons);
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
  // Fans also like: what this title's readers also look up, which may be nothing like it.
  const fans = el('section', '', 't-section');
  fans.hidden = true;
  const fansH = el('h3', 'Fans also like');
  fansH.id = 't-fans-h';
  fans.setAttribute('aria-labelledby', fansH.id);
  const fansSub = el('p', '', 't-sub');
  fansSub.id = 't-fans-sub';
  fans.setAttribute('aria-describedby', fansSub.id);
  const fansList = el('ul', '', 'more');
  fans.append(fansH, fansSub, fansList);
  const about = el('section', '', 't-section about');
  $('t-sheet').replaceChildren(close, hero, body, episodes, videos, more, fans, about);
  // Where to watch, the season's episodes and the trailers start short (unfold); each part
  // remembers whether it was opened, so a repaint or another season keeps it so.
  const t = { id: c.id, card: c, hero, backdrop, name, out, acts, listed, main, side, episodes, clips: videos, moreList,
              fans, fansSub, fansList, about, close, data: null, live: null, age: null, videos: null, error: '',
              eps: null, epsMore: null, clipList: null, clipsMore: null,
              open: { watch: false, episodes: false, clips: false } };
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
  // A title opened before the page knew the show (a shared link) gets its poster once the
  // show has loaded, instead of keeping the blank tile it opened with.
  const art = s.art || s.poster;
  const poster = T.hero.querySelector('.t-poster');
  if (art && poster && !poster.dataset.src) {
    const shown = artEl(s, art, false);
    shown.classList.add('t-poster');
    poster.replaceWith(shown);
    if (!T.hero.querySelector('.t-blur')) T.hero.prepend(picture(art, 't-blur'));
  }
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
  if (watch) fitWatch(watch);

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
// Apple TV when iTunes sells it, each with the service's own small icon. They keep to
// one line that fades out where it runs over, and a caret at its end opens the rest.
function watchEl(s, live, age, tm) {
  const { links, credit } = whereToWatch(s.name, tm, live?.site, live?.channels, age?.apple);
  if (!links.length) return null;
  const box = el('div', '', 'watch');
  box.append(el('span', 'Where to watch', 'k'));
  const list = el('div', '', 'watch-list');
  list.id = 't-watch';
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
  const more = el('button', '', 'round watch-more');
  more.type = 'button';
  more.setAttribute('aria-controls', list.id);
  more.setAttribute('aria-label', `All ${links.length} places to watch ${s.name}`);
  more.append(icon('more'));
  more.addEventListener('click', () => {
    if (busy(list)) return;
    T.open.watch = !T.open.watch;
    unfold(list, open => setWatch(box, open), T.open.watch);
  });
  const line = el('div', '', 'watch-line');
  line.append(list, more);
  box.append(line);
  if (credit) box.append(el('span', 'Streaming data from JustWatch', 'watch-credit'));
  return box;
}

// Which services one line shows whole, measured on the page: when they run over, the caret
// shows and the line fades out at its end, and the pills past the fade leave the tab order
// until the line is opened.
const FADE = 40;
function fitWatch(box) {
  const list = box.querySelector('.watch-list'), more = box.querySelector('.watch-more');
  box.classList.remove('open', 'clipped');
  more.hidden = true;
  let shown = list.children.length;
  if (list.scrollWidth > list.clientWidth + 1) {
    box.classList.add('clipped');
    more.hidden = false;
    shown = fitsOnLine([...list.children].map(a => a.offsetLeft + a.offsetWidth), list.clientWidth, FADE);
  }
  box.dataset.shown = String(shown);
  setWatch(box, T.open.watch);
}
function setWatch(box, open) {
  const clipped = box.classList.contains('clipped');
  const shown = Number(box.dataset.shown);
  box.classList.toggle('open', clipped && open);
  const more = box.querySelector('.watch-more');
  more.setAttribute('aria-expanded', String(clipped && open));
  more.title = open ? 'Show fewer' : 'Show all';
  [...box.querySelector('.watch-list').children].forEach((a, n) => { a.inert = clipped && !open && n >= shown; });
}
window.addEventListener('resize', () => requestAnimationFrame(() => {
  const box = T?.main.querySelector('.watch');
  if (box && !busy(box.querySelector('.watch-list'))) fitWatch(box);
  if (T?.clipList && !busy(T.clipList)) setClips(T.open.clips);
}));

// A long part of a title page opens with a button that closes it again (aria-expanded,
// with a caret that turns). Opening runs the part's height up from what it was, so what
// is below slides down; closing runs it back, and when the button sits below the part
// the page moves with it, so the button stays under the finger. Quick, and at once under
// reduced motion.
const REVEAL = 220;
const easeOut = k => 1 - (1 - k) ** 3;
const busy = box => box.classList.contains('sizing');
function unfold(box, set, open, anchor = null) {
  // A hidden page runs no animations, so one begun there would hold the part half open.
  const still = !motion() || document.hidden;
  const page = $('title');
  const from = box.offsetHeight;
  // While a part runs, the page is not moved to keep what is below it in place.
  const done = () => {
    box.classList.remove('sizing');
    page.classList.remove('unfolding');
  };
  if (open) {
    set(true);
    const to = box.offsetHeight;
    if (still || to <= from || !box.animate) return;
    box.classList.add('sizing');
    page.classList.add('unfolding');
    const run = box.animate({ height: [`${from}px`, `${to}px`] }, { duration: REVEAL, easing: 'cubic-bezier(.22,1,.36,1)' });
    run.onfinish = run.oncancel = done;
    return;
  }
  const y = anchor ? anchor.getBoundingClientRect().top : 0;
  set(false);
  const to = box.offsetHeight;
  if (still || to >= from) {
    if (anchor) page.scrollTop += anchor.getBoundingClientRect().top - y;
    return;
  }
  // Closed for a moment to measure, then open again while it runs back down.
  set(true);
  const top = page.scrollTop, began = performance.now();
  box.classList.add('sizing');
  page.classList.add('unfolding');
  const step = now => {
    // A title page closed meanwhile has nothing left to close.
    if (!T || !box.isConnected) {
      done();
      return;
    }
    const k = Math.min(1, (now - began) / REVEAL);
    const height = from - (from - to) * easeOut(k);
    box.style.height = `${height}px`;
    if (anchor) page.scrollTop = top - (from - height);
    if (k < 1) {
      requestAnimationFrame(step);
      return;
    }
    set(false);
    box.style.height = '';
    done();
  };
  requestAnimationFrame(step);
}
function revealButton(part, onClick) {
  const b = el('button', '', 'reveal');
  b.type = 'button';
  b.setAttribute('aria-controls', part.id);
  b.addEventListener('click', onClick);
  const bar = el('div', '', 'reveal-bar');
  bar.append(b);
  return b;
}
function paintReveal(b, text, open) {
  b.setAttribute('aria-expanded', String(open));
  b.replaceChildren(document.createTextNode(text), icon('more'));
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
    T.out.before(a);
  }
}

// The first two trailers, and a button for the rest, so More like this is not far below.
function paintVideos() {
  if (!T.videos.length) return;
  const list = el('ul', '', 'clips');
  list.id = 't-clips';
  for (const v of T.videos) {
    const li = el('li');
    const b = button('clip', '', () => playVideo(v));
    b.setAttribute('aria-label', `Play ${v.title || v.kind}${v.season ? `, season ${v.season}` : ''}`);
    const thumb = el('span', '', 'clip-thumb');
    const img = picture(null);
    img.loading = 'lazy';
    img.src = `https://i.ytimg.com/vi/${v.youtube}/mqdefault.jpg`;
    thumb.append(img, icon('play'));
    // A trailer TMDB keeps on a season says which, since its name seldom does.
    const said = [v.kind, v.season ? `Season ${v.season}` : '', v.published ? longDate(v.published) : ''];
    b.append(thumb, el('b', v.title || v.kind), el('small', said.filter(Boolean).join(' · ')));
    li.append(b);
    list.append(li);
  }
  T.clipList = list;
  T.clipsMore = revealButton(list, () => {
    if (busy(list)) return;
    T.open.clips = !T.open.clips;
    unfold(list, setClips, T.open.clips, T.clipsMore);
  });
  T.clips.replaceChildren(el('h3', 'Trailers & more'), list, T.clipsMore.parentElement);
  setClips(T.open.clips);
  T.clips.hidden = false;
}
// Two trailers side by side on a phone, and a whole row of three on a wide screen.
function setClips(open) {
  const items = [...T.clipList.children];
  const shown = snippet(items.length, wide() ? SNIPPETS.clipsWide : SNIPPETS.clips);
  items.forEach((li, n) => { li.hidden = !open && n >= shown; });
  T.clipsMore.parentElement.hidden = shown === items.length;
  paintReveal(T.clipsMore, revealLabel('clips', items.length, open), open);
}

// YouTube's no-cookie player, loaded only now. It takes the top of the title page, and
// the title and buttons move beneath it so nothing covers the player.
function playVideo(v) {
  if (!T) return;
  engaged(T.id);
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
  // The server sends none when fewer than four qualify, and the section stays hidden.
  const fans = T.data.fans || [];
  const name = T.data.show?.name || T.card.name;
  T.fansSub.textContent = name ? `Shows that ${name} fans also look up` : 'Shows its fans also look up';
  T.fansList.replaceChildren(...fans.map(moreCard));
  T.fans.hidden = !fans.length;
}
// A show like this one: how similar it is to this title, in the green a match wears, and
// why it is here (the same world, the same creator). Never a match: how close a show sits
// to this title says nothing of how well it fits a list, so it reads "% similar".
function moreCard(c) {
  const li = el('li', '', 'more-card');
  const open = button('more-open', '', () => openTitle(c.id));
  const similar = c.similar ? `${c.similar}% similar` : '';
  open.setAttribute('aria-label', [c.name, c.year, similar, c.why].filter(Boolean).join(', '));
  open.append(artEl(c));
  const top = el('div', '', 'more-top');
  const facts = el('div', '', 'more-info');
  if (c.year) facts.append(el('span', String(c.year)));
  top.append(facts, listButton(c, 'round'));
  const body = el('div', '', 'more-body');
  body.append(el('h4', c.name));
  if (similar || c.why) {
    const why = el('div', '', 'more-why');
    if (similar) why.append(el('b', similar, 'match'));
    if (c.why) why.append(el('span', c.why));
    body.append(why);
  }
  body.append(top);
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
  T.eps.id = 't-eps';
  T.epsMore = revealButton(T.eps, () => {
    if (busy(T.eps)) return;
    T.open.episodes = !T.open.episodes;
    unfold(T.eps, setEpisodes, T.open.episodes, T.epsMore);
  });
  T.episodes.replaceChildren(head, T.eps, T.epsMore.parentElement);
  T.episodes.hidden = false;
  loadSeason(list[0].number);
}

// A season shows its first few episodes until they are all asked for, and every season
// after that shows whole until they are closed again.
function setEpisodes(open) {
  const items = [...T.eps.children];
  const shown = snippet(items.length, SNIPPETS.episodes);
  items.forEach((li, n) => { li.hidden = !open && n >= shown; });
  T.epsMore.parentElement.hidden = shown === items.length;
  paintReveal(T.epsMore, revealLabel('episodes', items.length, open), open);
}

async function loadSeason(number) {
  const token = ++seasonToken, t = T;
  const skeleton = () => {
    const li = el('li', '', 'ep');
    li.append(el('span', '', 'ep-num'), el('span', '', 'ep-still skel'), skelLines(2));
    return li;
  };
  t.eps.replaceChildren(skeleton(), skeleton(), skeleton());
  setEpisodes(t.open.episodes);
  try {
    const { episodes } = await patient(`/api/episodes?id=${t.id}&season=${number}`);
    if (token !== seasonToken || T !== t) return;
    t.eps.replaceChildren(...(episodes.length ? episodes.map(episodeEl)
      : [el('li', 'No episodes are listed for this season yet.', 'muted')]));
  } catch (e) {
    if (token !== seasonToken || T !== t) return;
    t.eps.replaceChildren(el('li', e.message, 'muted'));
  }
  setEpisodes(t.open.episodes);
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
// Genres are picked from a row of chips, or from All genres: a sheet on phones and a
// panel under its button on wide screens. Both are listboxes, and choosing a genre
// changes the address as a link does, so Back steps through the genres chosen.
let browseKey = null, browseReq = 0, browseShown = null;
const genreLabel = key => boot.genres.find(g => g.key === key)?.label;
const GENRES = genreChoices(boot.genres);
const genreHref = key => (key ? `/browse?genre=${encodeURIComponent(key)}` : '/browse');

function genreOption(g, cls) {
  const b = el('button', '', cls);
  b.type = 'button';
  b.tabIndex = -1;
  b.dataset.genre = g.key;
  b.setAttribute('role', 'option');
  b.append(g.short);
  return b;
}

// Marks the option for a genre as chosen and gives it the listbox's one tab stop, which
// the first option takes when none is chosen.
function markGenre(box, key) {
  const options = [...box.querySelectorAll('[role=option]')];
  const chosen = options.find(o => o.dataset.genre === key) || null;
  for (const o of options) {
    o.setAttribute('aria-selected', String(o === chosen));
    o.tabIndex = o === (chosen || options[0]) ? 0 : -1;
  }
  return chosen;
}

// Arrow keys move along a listbox, Home and End go to either end and a letter to the next
// option it begins; Enter, Space or a click chooses.
function listboxKeys(box, back, ahead) {
  box.addEventListener('keydown', e => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const options = [...box.querySelectorAll('[role=option]')];
    const at = options.indexOf(e.target);
    if (at < 0) return;
    const k = e.key;
    const to = k === ahead ? Math.min(at + 1, options.length - 1) : k === back ? Math.max(at - 1, 0)
      : k === 'Home' ? 0 : k === 'End' ? options.length - 1
        : k.length === 1 && k.trim() ? nextByLetter(options.map(o => o.textContent), at, k) : -1;
    if (to < 0) return;
    e.preventDefault();
    for (const o of options) o.tabIndex = o === options[to] ? 0 : -1;
    options[to].focus();
  });
}

// Brings a chip into view near the middle of the row, unless it is in full view already.
function showChip(chip) {
  const bar = $('genre-scroll');
  if (!chip) { bar.scrollLeft = 0; return; }
  const inset = parseFloat(getComputedStyle(bar).paddingLeft) || 0;
  const start = chip.offsetLeft, end = start + chip.offsetWidth;
  if (start >= bar.scrollLeft + inset && end <= bar.scrollLeft + bar.clientWidth - inset) return;
  bar.scrollLeft = start - (bar.clientWidth - chip.offsetWidth) / 2;
}

// On a mouse, arrows at either end page through the chips, as they do through a row.
const syncGenreNudges = (() => {
  const bar = $('genre-scroll');
  const page = dir => bar.scrollBy({ left: dir * bar.clientWidth * .8, behavior: motion() ? 'smooth' : 'auto' });
  const prev = button('nudge prev', '', () => page(-1), 'left');
  const next = button('nudge next', '', () => page(1), 'right');
  prev.setAttribute('aria-label', 'Back through the genres');
  next.setAttribute('aria-label', 'More genres');
  $('genre-bar').prepend(prev);
  $('genre-bar').append(next);
  const sync = () => {
    prev.hidden = bar.scrollLeft < 8;
    next.hidden = bar.scrollLeft + bar.clientWidth >= bar.scrollWidth - 8;
  };
  bar.addEventListener('scroll', () => requestAnimationFrame(sync), { passive: true });
  window.addEventListener('resize', sync);
  return sync;
})();

function renderBrowse() {
  const { genre } = where();
  const valid = genreLabel(genre) ? genre : '';
  const row = $('genre-pick');
  if (!row.childElementCount) row.append(...GENRES.map(g => genreOption(g, 'genre-chip')));
  const chip = markGenre(row, valid);
  $('genre-all').classList.toggle('on', !valid);
  if (valid !== browseShown) {
    // A new choice starts from the top of the page, with its chip in sight.
    if (browseShown !== null && window.scrollY) window.scrollTo(0, 0);
    browseShown = valid;
    showChip(chip);
  }
  syncGenreNudges();
  $('browse-h').textContent = valid ? genreLabel(valid) : 'Browse';
  if (!valid) {
    browseKey = '';
    const tiles = el('ul', '', 'tiles');
    tiles.append(...GENRES.map(g => {
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
    const data = await post('/api/browse', { ...taste(), ...await freshFields(), genre });
    if (id !== browseReq) return;
    for (const r of data.rows) r.items.forEach(remember);
    $('browse-body').replaceChildren(...(data.rows.length ? data.rows.map(rowEl)
      : [el('p', 'Nothing in this genre fits your settings yet.', 'row-empty')]));
    reveal($('browse-body').querySelectorAll('section.row'));
  } catch (e) {
    if (id !== browseReq) return;
    browseKey = null;
    $('browse-body').replaceChildren(el('p', e.message, 'row-empty'));
  }
}
$('genre-pick').addEventListener('click', e => {
  const option = e.target.closest('[role=option]');
  if (option) go(genreHref(option.dataset.genre));
});
listboxKeys($('genre-pick'), 'ArrowLeft', 'ArrowRight');

// All genres: every genre A to Z after All genres itself, with the one on screen ticked.
function openGenres() {
  const list = $('genre-list');
  if (!list.childElementCount) {
    list.append(...[{ key: '', short: 'All genres' }, ...GENRES].map(g => {
      const option = genreOption(g, 'genre-opt');
      option.append(icon('check'));
      return option;
    }));
  }
  const { genre } = where();
  const chosen = markGenre(list, genreLabel(genre) ? genre : '');
  placeGenres();
  $('genres').showModal();
  $('genre-all').setAttribute('aria-expanded', 'true');
  chosen.focus();
}
function placeGenres() {
  if (!wide()) return;
  const r = $('genre-all').getBoundingClientRect();
  $('genres').style.setProperty('--x', `${Math.round(r.left)}px`);
  $('genres').style.setProperty('--y', `${Math.round(r.bottom + 8)}px`);
}
$('genre-all').append(icon('more'));
$('genre-all').addEventListener('click', openGenres);
$('genre-list').addEventListener('click', e => {
  const option = e.target.closest('[role=option]');
  if (!option) return;
  $('genres').close();
  go(genreHref(option.dataset.genre));
});
listboxKeys($('genre-list'), 'ArrowUp', 'ArrowDown');
$('genres').addEventListener('click', e => { if (e.target === $('genres')) $('genres').close(); });
$('genres').addEventListener('close', () => $('genre-all').setAttribute('aria-expanded', 'false'));
const followGenres = () => { if ($('genres').open) placeGenres(); };
window.addEventListener('resize', followGenres);
window.addEventListener('scroll', followGenres, { passive: true });

/* ----------------------------------------------------------- new & popular */
function renderNew() {
  const holder = $('new-body');
  if (!home) { holder.replaceChildren(skelRow(), skelRow()); return; }
  const rows = [{ key: 'top10', title: 'Top 10 shows today', kind: 'top10', items: home.top10 }];
  if (home.fresh.length) {
    rows.push({ key: 'fresh', title: home.personal ? 'New this year, picked for you' : 'New this year', kind: 'row', items: home.fresh });
  }
  if (home.soon.length) rows.push({ key: 'soon', title: 'Coming soon', kind: 'soon', items: home.soon });
  if (home.popular?.length) rows.push({ key: 'popular', title: 'Popular right now', kind: 'row', items: home.popular });
  redraw(holder, () => holder.replaceChildren(...rows.map(rowEl)));
  reveal(holder.children);
}

/* -------------------------------------------------------------- my list */
let ratedFilter = 'all';
const GROUPS = {
  all: ['All', () => true], loved: ['Loved', p => p.weight === 1],
  liked: ['Liked', p => p.weight > 0 && p.weight < 1], down: ['Not for me', p => p.weight < 0],
};
const NOTES = { 1: 'you loved it', '-1': 'not for you' };

function fill(grid, items, options = () => ({})) {
  redraw(grid, () => grid.replaceChildren(...items.map(c => {
    const li = el('li');
    const o = options(c);
    li.append(cardEl(c, o));
    // A caption under the poster, already read out as part of the card's own label.
    if (o.caption) {
      const caption = el('span', o.caption, 'grid-caption');
      caption.setAttribute('aria-hidden', 'true');
      li.append(caption);
    }
    return li;
  })));
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
// searchShown is the search on screen or on its way, and resultsFor the one whose
// results are showing ('' for the suggestions).
let searchReq = 0, searchTimer = 0, searchShown = null, resultsFor = '';

function suggestions() {
  resultsFor = '';
  $('search-note').textContent = 'Search by title. Until then, here is what people are watching.';
  const popular = home?.popular || [];
  fill($('results'), home ? [...home.top10, ...popular] : boot.starters);
  $('missing').hidden = true;
}

// The server forgives typos, spacing and other titles, and asks TVmaze about shows
// too new for the catalogue, so a search here rarely comes back empty. Coming back to
// the search on screen, such as by closing a title opened from it, keeps its results.
function search(q, typed = true) {
  const query = q.trim();
  for (const input of [$('q'), $('q-page')]) if (document.activeElement !== input && input.value !== q) input.value = q;
  paintRecent();
  if (query === searchShown) return;
  searchShown = query;
  clearTimeout(searchTimer);
  const id = ++searchReq;
  if (!query) { suggestions(); return; }
  // One character finds only a show of that one letter, such as V, so until one turns
  // up the page keeps its suggestions.
  const quiet = query.length < 2;
  if (quiet) suggestions();
  else $('search-note').textContent = 'Searching…';
  searchTimer = setTimeout(async () => {
    try {
      const { shows, missing = [], missing_first: first = false } = await call(`/api/search?q=${encodeURIComponent(query)}`);
      if (id !== searchReq || (quiet && !shows.length)) return;
      shows.forEach(remember);
      resultsFor = query;
      $('search-note').textContent = searchNote(query, shows.length, missing.length);
      fill($('results'), shows.map(s => ({ ...s, ...(known.get(s.id) || {}), aka: s.aka })),
        c => (c.aka ? { note: `also known as ${c.aka}`, caption: `Also known as ${c.aka}` } : {}));
      showMissing(missing, first);
    } catch (e) {
      if (id !== searchReq) return;
      searchShown = null;
      if (!quiet) $('search-note').textContent = e.message;
    }
  }, typed ? 200 : 0);
}

// Shows TVmaze has that the catalogue does not yet, each linked to its TVmaze page;
// ahead of the results when TVmaze ranks one of them first.
function showMissing(missing, first) {
  const box = $('missing');
  box.hidden = !missing.length;
  $('missing-list').replaceChildren(...missing.map(m => {
    const li = el('li');
    const link = el('a', 'See it on TVmaze');
    link.href = m.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', `${m.name} on TVmaze, opens in a new tab`);
    li.append(el('b', m.name), el('span', m.year ? String(m.year) : 'New', 'muted'), link);
    return li;
  }));
  $('search').insertBefore(box, first ? $('results') : null);
}

// What is typed shows at /search?q= at once. Typing while already searching replaces the
// address, so Back leaves the search rather than stepping back through it letter by letter.
function toSearch(q, typed = true) {
  const url = q ? `/search?q=${encodeURIComponent(q)}` : '/search';
  if (view !== 'search') { history.pushState(null, '', url); showView('search'); }
  else history.replaceState(history.state, '', url);
  search(q, typed);
}

// Recent searches (format.js keeps the list): a search counts once it is committed, by
// Enter, by opening one of its results or by choosing it here again.
const SEARCHES_KEY = 'couchside-searches';
const readRecents = text => { try { return recentStore(JSON.parse(text)); } catch { return []; } };
let recents = [];
try { recents = readRecents(localStorage.getItem(SEARCHES_KEY)); } catch { /* storage is off */ }
function keepRecents(list) {
  if (list === recents) return;
  recents = list;
  try { localStorage.setItem(SEARCHES_KEY, JSON.stringify(recents)); } catch { /* private mode */ }
  paintRecent();
}
const commitSearch = q => keepRecents(noteSearch(recents, q));
window.addEventListener('storage', e => {
  if (e.key !== SEARCHES_KEY) return;
  recents = readRecents(e.newValue);
  paintRecent();
});

// They show under the search page's box on phones while it has the focus or is empty,
// and drop from the nav's box on wide screens while it has the focus. Once something is
// typed, only those it begins, or begins a word of, stay.
const holdsFocus = (...nodes) => nodes.some(n => n.contains(document.activeElement));
function paintRecent() {
  const phone = !wide(), page = $('q-page');
  fillRecent($('recent-page'), page,
    phone && view === 'search' && (holdsFocus(page, $('recent-page')) || !searchText(page.value)));
  fillRecent($('recent-drop'), $('q'), !phone && $('find').classList.contains('open') && holdsFocus($('find')));
}
function fillRecent(box, input, show) {
  const items = show ? recentMatches(recents, input.value) : [];
  box.hidden = !items.length;
  const drawn = items.join('\n');
  if (box.dataset.drawn === drawn) return;
  box.dataset.drawn = drawn;
  if (!items.length) { box.replaceChildren(); return; }
  const h = el('h2', 'Recent searches', 'recent-h');
  h.id = `${box.id}-h`;
  const clear = button('recent-clear', 'Clear', () => {
    const inside = box.contains(document.activeElement);
    keepRecents([]);
    if (inside) input.focus();
  });
  clear.setAttribute('aria-label', 'Clear recent searches');
  const head = el('div', '', 'recent-head');
  head.append(h, clear);
  const list = el('ul', '', 'recent-list');
  list.setAttribute('aria-labelledby', h.id);
  list.append(...items.map(q => {
    const li = el('li');
    const again = button('recent-q', '', () => searchAgain(q), 'clock');
    again.append(el('span', q, 'recent-text'));
    const x = button('icon-btn recent-x', '', () => forget(box, input, q), 'close');
    x.setAttribute('aria-label', `Remove “${q}” from recent searches`);
    li.append(again, x);
    return li;
  }));
  box.replaceChildren(head, list);
}
function searchAgain(q) {
  for (const input of [$('q'), $('q-page')]) input.value = q;
  toSearch(q, false);
  commitSearch(q);
  document.activeElement?.blur();
}
// Taking one out from the keyboard leaves the focus on the next one's x, or in the box.
function forget(box, input, q) {
  const at = [...box.querySelectorAll('.recent-x')].indexOf(document.activeElement);
  keepRecents(withoutSearch(recents, q));
  if (at < 0) return;
  const left = box.querySelectorAll('.recent-x');
  (left[Math.min(at, left.length - 1)] || input).focus();
}
for (const [box, input] of [[$('recent-page'), $('q-page')], [$('recent-drop'), $('q')]]) {
  // Pressing one keeps the focus, and a phone's keyboard, in the box.
  box.addEventListener('mousedown', e => { if (e.target.closest('button')) e.preventDefault(); });
  box.addEventListener('keydown', e => {
    const items = [...box.querySelectorAll('.recent-q')];
    const at = items.indexOf(e.target);
    if (e.key === 'Escape') { e.preventDefault(); input.focus(); }
    else if (at >= 0 && e.key === 'ArrowDown') { e.preventDefault(); items[Math.min(at + 1, items.length - 1)].focus(); }
    else if (at >= 0 && e.key === 'ArrowUp') { e.preventDefault(); (items[at - 1] || input).focus(); }
  });
  input.addEventListener('keydown', e => {
    const first = box.hidden ? null : box.querySelector('.recent-q');
    if (e.key === 'ArrowDown' && first) { e.preventDefault(); first.focus(); }
  });
}
// The nav's box folds away once it is empty and the focus has gone elsewhere.
function settleFind() {
  if (!$('q').value && !$('find').contains(document.activeElement)) $('find').classList.remove('open');
  paintRecent();
}
for (const area of [$('find'), $('search')]) {
  area.addEventListener('focusin', paintRecent);
  area.addEventListener('focusout', () => requestAnimationFrame(settleFind));
}
window.addEventListener('resize', paintRecent);

for (const input of [$('q'), $('q-page')]) {
  input.addEventListener('input', () => toSearch(input.value));
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { commitSearch(input.value); input.blur(); }
    if (e.key === 'Escape' && input === $('q')) { input.value = ''; input.blur(); $('find').classList.remove('open'); }
  });
}
// Opening one of a search's results commits it too.
$('results').addEventListener('click', e => { if (e.target.closest('.card-hit, .push')) commitSearch(resultsFor); });
$('missing').addEventListener('click', e => { if (e.target.closest('a')) commitSearch(resultsFor); });

// Search from the nav or the dock: coming from another page starts afresh with recent
// searches showing, while on the search page it keeps what is there and takes the focus.
function openSearch() {
  if (view !== 'search') go('/search');
  else window.scrollTo(0, 0);
  $('q-page').focus();
}
$('find-open').append(icon('search'));
$('find-open').addEventListener('click', () => {
  if (!wide()) { openSearch(); return; }
  if (view !== 'search') $('q').value = '';
  $('find').classList.add('open');
  $('q').focus();
});
for (const a of document.querySelectorAll('a[data-page="search"]')) {
  a.addEventListener('click', e => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openSearch();
  });
}
document.addEventListener('keydown', e => {
  if (e.key !== '/' || e.target.closest('input, textarea, select') || document.querySelector('dialog[open]')) return;
  e.preventDefault();
  $('find-open').click();
});

/* -------------------------------------------------------------- welcome */
// Starters come from /api/starters: drawn for this browser and day across distinct kinds
// of show, and each pick swaps three of the rest for a contrast, a neighbour and a kind
// not yet explored (starters.py says how). A search adds any show. Three picks are
// needed, five to ten make the best rows, and the prompting stops at ten. The posters
// the server filled in stand in when the request fails.
const FRESH = 'couchside-fresh';
const NEEDED = 3, SUGGESTED = 5, PLENTY = 10;
const picked = new Set();
const opening = { shows: [], round: 0, asked: '', req: 0, seed: null, tiles: new Map() };

// Liked shows already rated go first, so what is picked here only ever adds to the end.
const welcomePicks = () =>
  [...state.profile.filter(p => p.weight > 0).map(p => p.id).slice(-10), ...picked].slice(0, MAX_PICKED);

function renderWelcome() {
  drawWelcome();
  loadWelcome();
}

async function loadWelcome() {
  const ids = welcomePicks();
  const asking = `${opening.round}|${ids.join(',')}`;
  if (asking === opening.asked) return;
  opening.asked = asking;
  const id = ++opening.req;
  opening.seed ??= daySeed(FRESH);
  const query = startersQuery({ seed: await opening.seed, round: opening.round, picked: ids, lang: browserLanguage() });
  try {
    const { shows } = await call('/api/starters?' + query);
    if (id !== opening.req) return;
    opening.shows = mergeStarters(opening.shows, shows.map(remember), n => picked.has(n));
  } catch {
    if (id !== opening.req) return;
    opening.asked = '';
    if (!opening.shows.length) opening.shows = boot.starters.map(remember);
  }
  if (view === 'welcome') drawWelcome();
}

// A poster to pick. Starters keep theirs by id, so a redraw moves a poster rather than
// loading it again.
function pickTile(c, tiles) {
  let li = tiles.get(c.id);
  if (!li) {
    li = el('li');
    const b = button('card pick', '', () => togglePick(c));
    b.dataset.pick = c.id;
    const tick = el('span', '', 'tick');
    tick.append(icon('check'));
    b.append(artEl(c), tick);
    li.append(b);
    tiles.set(c.id, li);
  }
  paintPick(li.firstChild, c);
  return li;
}

function paintPick(b, c) {
  const already = rated(c.id) > 0;
  b.setAttribute('aria-pressed', String(already || picked.has(c.id)));
  b.setAttribute('aria-label', already ? `${c.name}, already rated` : c.name);
  b.disabled = already;
}

function togglePick(c) {
  if (rated(c.id) > 0) return;
  if (picked.has(c.id)) picked.delete(c.id);
  else picked.add(remember(c).id);
  for (const b of document.querySelectorAll(`[data-pick="${c.id}"]`)) paintPick(b, c);
  drawAlso();
  syncPicks();
  loadWelcome();
}

function drawWelcome() {
  const keep = new Set(opening.shows.map(c => c.id));
  for (const id of opening.tiles.keys()) if (!keep.has(id)) opening.tiles.delete(id);
  $('starters').replaceChildren(...opening.shows.map(c => pickTile(c, opening.tiles)));
  drawAlso();
  syncPicks();
}

// Shows picked from a search sit off the grid; they are listed here, and a tap takes one back.
function drawAlso() {
  const shown = new Set(opening.shows.map(c => c.id));
  const extra = [...picked].filter(id => !shown.has(id));
  $('also-picked').hidden = !extra.length;
  $('also-picked').replaceChildren(...extra.map(id => {
    const c = info(id);
    const b = button('chip', c.name, () => togglePick(c));
    b.setAttribute('aria-pressed', 'true');
    b.setAttribute('aria-label', `${c.name}, picked. Take it back`);
    return b;
  }));
}

function syncPicks() {
  const liked = state.profile.filter(p => p.weight > 0).length;
  const total = liked + picked.size;
  const need = Math.max(0, NEEDED - total);
  const said = picked.size ? `${picked.size} picked. ` : '';
  $('picked-note').textContent = need ? `Pick ${need} more to continue.`
    : total >= PLENTY ? `${said}That is plenty.`
      : total < SUGGESTED ? `${said}Five to ten makes the best rows.`
        : `${said}Ready when you are.`;
  $('continue').disabled = need > 0;
}

$('starters-more').addEventListener('click', () => {
  opening.round = (opening.round + 1) % (MAX_ROUND + 1);
  loadWelcome();
});

// Add a show you love: the same search as the rest of the app, its results picked like starters.
let foundReq = 0, foundTimer = 0;
function clearFound() {
  foundReq++;
  clearTimeout(foundTimer);
  $('q-welcome').value = '';
  $('found').hidden = $('found-note').hidden = true;
}
$('q-welcome').addEventListener('input', () => {
  const q = $('q-welcome').value.trim();
  const id = ++foundReq;
  clearTimeout(foundTimer);
  if (q.length < 2) {
    $('found').hidden = $('found-note').hidden = true;
    return;
  }
  $('found-note').hidden = false;
  $('found-note').textContent = 'Searching…';
  foundTimer = setTimeout(async () => {
    try {
      const { shows, missing = [] } = await call(`/api/search?q=${encodeURIComponent(q)}`);
      if (id !== foundReq) return;
      $('found').replaceChildren(...shows.slice(0, 12).map(c => pickTile(remember(c), new Map())));
      $('found').hidden = !shows.length;
      $('found-note').textContent = searchNote(q, shows.length, missing.length);
    } catch (e) {
      if (id === foundReq) $('found-note').textContent = e.message;
    }
  }, 200);
});
$('q-welcome').addEventListener('keydown', e => { if (e.key === 'Escape') clearFound(); });

$('continue').addEventListener('click', () => {
  for (const id of picked) {
    if (!state.profile.some(p => p.id === id) && state.profile.length < MAX_RATED) {
      state.profile.push({ ...tidy(info(id)), weight: .7 });
    }
  }
  picked.clear();
  clearFound();
  state.onboarded = true;
  save();
  updateCounts();
  go('/');
  loadHome();
});
$('skip').addEventListener('click', () => {
  picked.clear();
  clearFound();
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
$('open-taste').addEventListener('click', async () => {
  $('account').close();
  paintTaste();
  $('taste').showModal();
  // Rated since the page was made: ask for the list's taste alone, with no rows.
  if (!home?.personal || home.tasteKey === homeKey) return;
  try {
    const data = await post('/api/home', await moreBody(0));
    Object.assign(home, { taste: data.taste, interests: data.interests, tasteKey: homeKey });
    if ($('taste').open) paintTaste();
  } catch { /* the sheet keeps what it had */ }
});

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
// The service worker (sw.js) starts the app from the build it keeps, online or not, and
// keeps the posters. A new build it finds waits until this page has loaded all its own
// files, then takes over, so the next load is the new build whole.
if ('serviceWorker' in navigator && window.isSecureContext) {
  const takeOver = worker => worker?.postMessage('take-over');
  const register = () => navigator.serviceWorker.register('/sw.js').then(reg => {
    takeOver(reg.waiting);
    reg.addEventListener('updatefound', () => {
      const worker = reg.installing;
      worker?.addEventListener('statechange', () => { if (worker.state === 'installed') takeOver(worker); });
    });
  }).catch(() => {});
  if (document.readyState === 'complete') register(); else window.addEventListener('load', register);
}

/* ---------------------------------------------------------------- start */
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
for (const a of document.querySelectorAll('.dock [data-icon]')) a.prepend(icon(a.dataset.icon));
// The dock tucks itself smaller while the page scrolls down and comes back on the way up,
// as iOS 26 tab bars do. The empty touchstart lets iOS show a pressed tab.
dockY = window.scrollY;
window.addEventListener('scroll', () => {
  const y = window.scrollY;
  if (Math.abs(y - dockY) < 10) return;
  $('dock').classList.toggle('tucked', y > dockY && y > 160 && motion());
  dockY = y;
}, { passive: true });
$('dock').addEventListener('touchstart', () => {}, { passive: true });
for (const b of document.querySelectorAll('.close-btn')) b.append(icon('close'));
updateCounts();
route();
loadHome();
readLink();
