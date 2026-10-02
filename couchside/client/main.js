import { mountEpisodeRatings } from './episode-ratings.js';
import { mountCompare, comparisonURL } from './compare.js';
import { mountTitleSections } from './title-sections.js';
import { enhanceShowCard,receiveMatrices,matrixPreference } from './show-cards.js';
import { mountTaste } from './taste.js';
import { mergeTransferredList } from './list-transfer.js';
import { apiFetch } from './network.js';
import { mountAccounts } from './accounts.js';
import {filtersFor,filterKey,selectShows,setFilters} from './filter-state.js';
import {filterBar} from './filters.js';
import { cachedRatings, ratings, seasons as ratingSeasons } from './ratings.js';
import { encode, decode, LIMITS, codeFrom } from './transfer.js';
import { matrix, svgPath } from './qr.js';
import { tieText, leaning } from './format.js';
import { years, runtime, seasons, joinNames, parseRoute, withShow, hue, premiere, longDate, airs,
  whereToWatch, trailerSearch, searchNote } from './format.js';
import { pageKey, ongoing, resumable, keptText, shownRows, withoutCard, viewedStore, noteViewed, recentlyViewed }
  from './format.js';
import { POSTERS_AHEAD, POSTERS_AT_ONCE, FLUNG, FLUNG_AT_ONCE, STILL_FLUNG, SLOW_POSTER, ROWS_AHEAD, postersToLoad,
  loopPosters, posterPace, catchingUp, rowsToAsk, retryAfter } from './format.js';
import { genreChoices, searchText, recentStore, noteSearch, withoutSearch, recentMatches, keepsRow } from './format.js';
import { keeper, sessionAnswers } from './format.js';
import { TURN_EVERY, slideIn, slotOf, reach, slideLabel, landing, TURN_OWN_MS, glideTime, turnTime } from './format.js';
import { heading, wandered } from './gestures.js';
import { SNIPPETS, snippet, revealLabel } from './format.js';
import { withEpisode, episodeCode, episodeSaid, neighbours, credits, airing } from './format.js';
import { withPerson, isoDay, yearsBetween, bornOn, diedOn, selfHeading, creditLines, knownFor } from './format.js';
import { merged, today, dayNumber, noteSeen, noteEngaged, noteRow, noteHero, watcher } from './fresh.js';
import { daySeed, startersQuery, mergeStarters, browserLanguage, MAX_ROUND, MAX_PICKED } from './starters.js';
import { sheets, closing, reveal, crossfade, peeks, edgeBack, speed } from './gestures.js';
import { REST, LOOP_WAIT, goesRound, loopCopies, copiesOf, lapHome, restPlace, toCard } from './gestures.js';
import { KEY, DEFAULTS, REACH, VERSION, MAX_RATED, fresh, tidy, stored, FRESH_KEY, readMemory, remembered, opened,
  newVisit, keepVisit, tasteOf, homeBody, packed, PAGE_KEY, take, sanitize } from './start.js';

const boot = JSON.parse(document.getElementById('boot').textContent);
const $ = id => document.getElementById(id);
const RATES = [
  { weight: -1, label: 'Not for me', icon: 'down', said: 'Got it. You will see less like this.' },
  { weight: .7, label: 'I like this', icon: 'up', said: 'Liked. Your rows will lean toward it.' },
  { weight: 1, label: 'Love this!', icon: 'heart', said: 'Loved. Your rows will lean hard toward it.' },
];
const VIEWS = ['home', 'welcome', 'browse', 'new', 'list', 'search', 'compare'];
const pageFilters = new Map();
const TITLES = {
  home: 'Couchside', welcome: 'Welcome · Couchside', new: 'New & Popular · Couchside',
  list: 'My List · Couchside', search: 'Search · Couchside', browse: 'Browse · Couchside',
  compare: 'Compare shows · Couchside',
};
// Thumb, heart, star, search and navigation shapes follow Feather icons (MIT, Cole Bemis).
const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5l-4.3-4.3"/>',
  filter: '<path d="M22 3H2l8 9.5V19l4 2v-8.5L22 3z"/>',
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
  pause: '<path d="M8 5v14M16 5v14" stroke-width="3.4"/>',
  more: '<path d="M6 9l6 6 6-6"/>',
  share: '<path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8M16 6l-4-4-4 4M12 2v13"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4a1 1 0 001 1h14a1 1 0 001-1v-4"/>',
  compare: '<rect x="3" y="4" width="7" height="16" rx="2"/><rect x="14" y="4" width="7" height="16" rx="2"/><path d="M6 8h1m10 0h1M6 12h1m10 0h1M6 16h1m10 0h1"/>',
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
  star: '<path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" fill="currentColor"/>',
};

/* ------------------------------------------------------------- storage */
// The list, the memory and the visit as they stood when the page started (start.js, which
// has asked for the home page with them already).
let state = stored;
let accounts = null;
let tastePanel = null;
let accountOwner = '';
let accountEpoch = 0;

function save() {
  tastePanel?.refresh();
  if (accounts) { accounts.changed(); return; }
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode */ }
}

// What this browser has shown and what you engaged with (fresh.js), so each visit's page
// is fresh. Writes are batched, since a scroll can see dozens of titles.
let memory = remembered;
// What other tabs have written since joins this tab's memory, so that writing it never
// loses their visits, heroes or titles seen to this tab's older copy (fresh.js's merged).
function catchUp() {
  const theirs = readMemory();
  if (theirs) memory = merged(theirs, memory);
}
let memoryTimer = 0;
function keepMemory(now = false) {
  clearTimeout(memoryTimer);
  const write = () => {
    catchUp();
    try { localStorage.setItem(FRESH_KEY, JSON.stringify(memory)); } catch { /* private mode */ }
  };
  if (now) write(); else memoryTimer = setTimeout(write, 1000);
}
// Engaging with a title (opening it, rating it, listing it, its trailer, a link out)
// spares it from fatigue for two weeks; engaging with a card also wakes the row it is in.
function engaged(id, row = '') {
  const day = today();
  noteEngaged(memory, id, day);
  if (row) noteRow(memory, row, day, true);
  keepMemory();
}
// The visit the tab is on (start.js, which says what a visit is and begins the first when
// the tab has none going on), and what its requests carry.
let { visit, ask: visitAsk } = opened;
function startVisit() {
  // Another tab may have begun a visit, shown a hero or seen titles since this one read
  // the memory, and the new visit counts them.
  catchUp();
  ({ visit, ask: visitAsk } = newVisit(memory));
  keepMemory(true);
}
const freshFields = () => visitAsk;
// The visit's number for what is seen on its own day; past 04:00 a title counts for the day alone.
const visitToday = () => (visit.day === today() ? visit.n : 0);
// Leaving the tab marks when, so that coming back after long enough away begins a new
// visit (comeBack), and the page gives way to that visit's own (renewHome).
function leaveVisit() {
  visit.at = Date.now();
  keepVisit(visit);
}
function comeBack() {
  // A visit still working out what it asks for has only just begun.
  if (!visit.ask || ongoing(visit, { day: today(), now: Date.now() })) return;
  startVisit();
  renewHome();
}

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
// A show TVmaze added since the catalogue was built: its title page says so once it has
// loaded, and before that its id does, since TVmaze numbers shows as it adds them and the
// server tells them apart the same way (boot.newest is the newest show the catalogue holds).
// Its page comes from TVmaze alone, and it cannot be rated until the nightly refresh brings
// it in, since ratings rank the catalogue's shows.
const newer = id => known.get(id)?.newer ?? id > boot.newest;
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
// `load` says when: true once the browser finds it near (lazy), false at once, 'first'
// at once and ahead of everything else, and 'ahead' when its row's turn comes (see
// startPosters), so a row's posters are in before it is seen. A full-size picture (the
// featured show's, a title page's) shows the show's poster first, which is a twentieth of
// its size and often held already, and fades in over it once it is here: on a slow
// connection the poster is there in a moment and the full picture takes seconds.
function artEl(c, src = c.poster, load = true) {
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
    img.addEventListener('load', () => box.classList.add('loaded'), { once: true });
    img.addEventListener('error', () => img.remove(), { once: true });
    box.append(img);
    if (c.poster && c.poster !== src) {
      // After the picture, so the picture is what loadPoster starts and startPosters counts.
      const preview = picture(null, 'preview', () => box.classList.add('previewed'));
      preview.addEventListener('error', () => preview.remove(), { once: true });
      box.dataset.preview = c.poster;
      box.append(preview);
    }
    if (load === 'ahead' && rowsNear) return box;
    if (load === true || load === 'ahead') img.loading = 'lazy';
    loadPoster(box, load === 'first');
  }
  return box;
}
// Starts a poster's image, unless it has started already, and its preview unless the
// picture is held already; and its copies' in a row that goes round, from the same
// address, which the browser fetches once.
function loadPoster(box, urgent = false) {
  const img = box.querySelector('img');
  if (!img || img.getAttribute('src') !== null) return;
  if (urgent) img.fetchPriority = 'high';
  img.src = box.dataset.src;
  const preview = box.querySelector('img.preview');
  // One this page already holds shows at once, without fading in again.
  if (img.complete && img.naturalWidth) {
    box.classList.add('loaded');
    preview?.remove();
  } else if (preview) {
    preview.fetchPriority = img.fetchPriority;
    preview.loading = img.loading;
    preview.src = box.dataset.preview;
  }
  for (const copy of copiedArt.get(box) || []) {
    const shown = copy.querySelector('img');
    if (shown && shown.getAttribute('src') === null) shown.src = box.dataset.src;
  }
}
function fact(label, value) {
  if (!value) return null;
  const p = el('p');
  p.append(el('span', `${label}: `, 'k'), document.createTextNode(value));
  return p;
}
// Skeletons stand in for what is on its way in its own shape, so nothing moves when it
// lands. A line of text is a bar inside an element of the kind that will hold the text,
// so it takes a line of that text's own height; a poster, a still, a face or a button is
// a block of its size. They are hidden from screen readers, which hear the page once it is
// here, and they shimmer except under reduced motion (style.css).
function skelText(width = '') {
  const bar = el('span', '', 'skel text');
  if (width) bar.style.width = width;
  return bar;
}
// A tag.cls holding a line for each width: a p.t-summary of four lines, say. The lines sit
// in a block of their own, which keeps their height in a flex line (a meta line) too.
function skelIn(tag, cls, ...widths) {
  const box = el(tag, '', cls);
  box.setAttribute('aria-hidden', 'true');
  const lines = el('span', '', 'skel-lines');
  lines.append(...widths.map(skelText));
  box.append(lines);
  return box;
}
// n lines of text in tag.cls, the last one shorter.
function skelLines(n, tag = 'div', cls = '') {
  return skelIn(tag, cls, ...Array.from({ length: n }, (_, i) => (i === n - 1 && n > 1 ? '62%' : '100%')));
}
// A poster on its way, sized as a card is where it stands: in a row, a grid or the Top 10.
function skelCard(soon = false) {
  const card = el('div', '', 'card skel-card');
  card.setAttribute('aria-hidden', 'true');
  card.append(el('span', '', 'art skel'));
  // Coming soon says when each premieres, under its poster.
  if (soon) card.append(skelIn('span', 'soon-date', '6.5em'));
  return card;
}
// A grid's n posters on their way, as fill lays them out, with the name and year under
// each where the grid will show them (titled).
function skelGrid(n, titled = false) {
  return Array.from({ length: n }, () => {
    const li = el('li', '', 'skel-item');
    li.setAttribute('aria-hidden', 'true');
    li.append(skelCard());
    if (titled) li.append(titledCaption(skelIn('span', 'cap-name', '82%'), skelIn('span', 'cap-meta', '2.6em')));
    return li;
  });
}

const POPOVER = 'showPopover' in HTMLElement.prototype;
let toastTimer = 0;
function toast(text, duration=2800) {
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
  }, duration);
}
if (!POPOVER) $('toast').hidden = true;

/* ----------------------------------------------------------------- api */
// started is the same request's answer on its way already, as the home page's is from start.js.
async function request(path, options = {}, started = null) {
  let res;
  try {
    res = await (started || apiFetch(path, options));
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
  receiveMatrices(body.matrices);
  return body;
}

// What the page has been told is kept by what it asked (keeper in format.js): a title, a
// genre's rows, a search, a show's live details and a person come back without a request
// for a while, and two asking at once share one. Live details and people, which the server
// fetches from TVmaze, KinoCheck, iTunes, Wikidata and Wikipedia, also outlast a reload of
// the tab in sessionStorage. The home page keeps itself (keepPage).
const MINUTE = 60_000;
const KEEP = {
  '/api/extra': 30, '/api/trailer': 30, '/api/rating': 30, '/api/episodes': 30, '/api/episode': 30,
  '/api/person': 30, '/api/biography': 30,
  '/api/search': 10, '/api/title': 10, '/api/browse': 10,
};
const LIVE = ['/api/extra', '/api/trailer', '/api/rating', '/api/episodes', '/api/episode', '/api/person', '/api/biography'];
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
const patient = path => call(path);
// A title's page and a genre's rows follow your list, your settings and what is asked,
// not what this browser has seen since, so they are kept by those alone. The list goes
// packed (start.js).
function post(path, body, signal) {
  const send = () => request(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: packed(body), signal,
  });
  if (!KEEP[path]) return send();
  const { profile, settings, id, genre, filters, matrix, recommendation_filters } = body;
  return asked(`${path} ${JSON.stringify([profile, settings, id, genre, filters, matrix, recommendation_filters])}`, KEEP[path] * MINUTE, send);
}
const taste = () => tasteOf(state);

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
let compareDispose = null, compareKey = '';
const comparisonKey = search => {
  const params = new URLSearchParams(search);
  return ['compare', 'mode', 'compare-inverted', 'averages', 'seasons'].map(key => `${key}=${params.get(key) || ''}`).join('&');
};
function renderCompare() {
  const key = comparisonKey(location.search);
  if (compareDispose && key === compareKey) return;
  compareDispose?.();
  compareKey = key;
  compareDispose = mountCompare($('compare-body'), {
    search: location.search,
    replaceURL: path => {
      const target = new URL(path, location.origin), current = new URLSearchParams(location.search);
      for (const key of ['show', 'episode', 'person', 'rating-view', 'rating-season', 'rating-inverted']) {
        if (current.has(key)) target.searchParams.set(key, current.get(key));
      }
      history.replaceState(history.state, '', target.pathname + target.search);
      compareKey = comparisonKey(target.search);
    },
    openShow: id => openTitle(id), saveSnapshot: saveRatingSnapshot, announce: toast,
  });
}
let dockRest = 0;    // the pause after a scroll that brings the dock back
const where = () => parseRoute(location.pathname, location.search);

function go(path) {
  if (path !== location.pathname + location.search) history.pushState(null, '', path);
  route();
}

// A title, one of its episodes and a person open over the page are sheets of their own,
// each above the one before. Back to a title or a person after a title opened from someone's
// page builds it again, and it returns to where it was left (keepPlace).
function route() {
  let { page, q, show, episode, person } = where();
  if (page === 'welcome' && (state.onboarded || state.profile.length)) {
    history.replaceState(history.state, '', '/');
    page = 'home';
  }
  const name = page === 'home' && !state.profile.length && !state.onboarded ? 'welcome' : page;
  if (name !== view) showView(name);
  else if (name === 'browse') renderBrowse();
  if (name === 'search') search(q, false);
  if (name === 'compare') renderCompare();
  const place = history.state?.place || {};
  if (show) {
    if (!$('title').open || titleId !== show) {
      // A title opening beneath someone's page would open over it, so theirs goes and comes back.
      if (person && personId && !$('title').open) hidePerson(true);
      showTitle(show, false, place.title);
    } else T?.ratingRestore?.();
    if (episode && episodeId !== episode) {
      // So would an episode.
      if (person && personId && !$('episode').open) hidePerson(true);
      showEpisode(episode);
    } else if (!episode && episodeId) hideEpisode();
  } else if ($('title').open) hideTitle();
  if (person) {
    if (!$('person').open || personId !== person) showPerson(person, place.person);
  } else if ($('person').open) hidePerson();
  renewHome();
}

function showView(name) {
  view = name;
  // A tab changes at once, as a phone's own tab bars do: a crossfade here made the whole
  // page, dock and all, shimmer through two copies of itself.
  paintView(name);
}

function paintView(name) {
  if (name !== 'compare') { compareDispose?.(); compareDispose = null; compareKey = ''; }
  for (const id of VIEWS) $(id).hidden = id !== name;
  const current = name === 'welcome' ? 'home' : name;
  for (const a of document.querySelectorAll('[data-page]')) {
    if (a.dataset.page === current) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  if (!$('title').open) document.title = TITLES[name];
  window.scrollTo(0, 0);
  // A new view starts at the top with the dock whole at once, not easing back in, and the
  // button that stands in for it while the page scrolls shows the section it is now in.
  clearTimeout(dockRest);
  const dock = $('dock');
  if (dock.classList.contains('away')) {
    dock.classList.add('still');
    dockAway(false);
    requestAnimationFrame(() => requestAnimationFrame(() => dock.classList.remove('still')));
  }
  paintDockMini();
  syncNav();
  expandFind(name === 'search' && $('find').contains(document.activeElement));
  $('q').value = name === 'search' ? where().q : '';
  if (name === 'welcome') renderWelcome();
  if (name === 'list') renderList();
  if (name === 'new') renderNew();
  if (name === 'browse') renderBrowse();
  paintHeaderFilters();
}

function syncNav() {
  $('nav').classList.toggle('solid', view !== 'home' || window.scrollY > 40);
}

function paintHeaderFilters() {
  const control = pageFilters.get(view), trigger = $('filter-open');
  trigger.hidden = !control;
  const count = control?.count() || 0;
  const page = {home:'Home',browse:'Browse',new:'New & Popular',list:'My List',search:'Search'}[view];
  trigger.setAttribute('aria-label', `Filter ${page || 'shows'}${page ? ' shows' : ''}${count ? `, ${count} active` : ''}`);
  trigger.classList.toggle('active', !!count);
}

// How long the page rests after a scroll before the dock comes back, in ms.
const DOCK_REST = 350;
// The dock folded away, or back. While it is away its one button is what a tap or a Tab finds.
function dockAway(away) {
  const dock = $('dock');
  if (dock.classList.contains('away') === away) return;
  dock.classList.toggle('away', away);
  const mini = $('dock-mini');
  mini.tabIndex = away ? 0 : -1;
  mini.setAttribute('aria-hidden', String(!away));
}
// The button that stands in for the dock: the icon and name of the section you are in.
function paintDockMini() {
  const on = document.querySelector('.dock [aria-current=page]');
  const mini = $('dock-mini');
  if (!on) {
    mini.replaceChildren(icon('more'));
    mini.setAttribute('aria-label', 'Show every section');
    return;
  }
  mini.replaceChildren(icon(on.dataset.icon));
  mini.setAttribute('aria-label', `${on.getAttribute('aria-label') || on.textContent.trim()}. Show every section`);
}

// A link the app opens itself: a plain click, not one asking for a new tab or window.
const plainClick = e => e.button === 0 && !e.defaultPrevented && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
document.addEventListener('click', e => {
  const a = e.target.closest('a[data-link]');
  if (!a || !plainClick(e)) return;
  e.preventDefault();
  const dialog = a.closest('dialog');
  if (dialog?.open) dialog.close();
  go(a.getAttribute('href'));
});
window.addEventListener('popstate', route);
window.addEventListener('scroll', syncNav, { passive: true });
// Installed, a swipe in from the left edge goes back from a person's page, an episode, a
// title page, or a view off home.
edgeBack(() => !!titleId || !!personId || (view !== 'home' && !document.querySelector('dialog[open]')),
  () => (personId ? closePerson() : episodeId ? closeEpisode() : titleId ? closeTitle() : history.back()));

/* ---------------------------------------------------------------- home */
// The page arrives a few rows at a time: the first answer brings the hero and the first
// eight, and the next six are asked for while three screens of rows are still to come
// (loadMore), telling the server which rows are already shown so it builds the same
// page. Each visit gets a page of its own, and within one the page holds still: a reload
// shows it again as it was, asking for more carries what the page was made with, and a
// rating or a My List change merges into it rather than laying it out again.
// Impressions are only written down, never a reason to re-render.
let home = null, homeKey = '', homeReq = 0, homeAbort = null, homeTimer = 0, moreBusy = false;
// Why the page could not be had, if it could not, so the views drawn from it stop waiting.
let homeFailed = '';
const currentKey = () => pageKey(taste(), state.saved.map(s => s.id)) + filterKey('home');

function refresh(delay = 450) {
  clearTimeout(homeTimer);
  homeTimer = setTimeout(loadHome, delay);
}

// The page kept for this tab: what was shown, for the visit and list it was made for. A
// page grown past KEEP_CHARS keeps its first rows and asks for the rest again (keptText).
function keepPage() {
  if (!home) return;
  try {
    sessionStorage.setItem(PAGE_KEY,
      keptText({ v: 2, at: Date.now(), day: home.day, visit: home.visit, key: homeKey, home }));
  } catch { /* storage full or off: the page is simply asked for again next time */ }
}
function keptPage(key) {
  try {
    const kept = JSON.parse(sessionStorage.getItem(PAGE_KEY));
    return resumable(kept, { key, visit }) && kept.home.ask ? kept.home : null;
  } catch { return null; }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') { keepPage(); keepMemory(true); leaveVisit(); } else comeBack();
});
window.addEventListener('pagehide', () => { keepPage(); keepMemory(true); leaveVisit(); });

// A page made for an earlier visit gives way to this visit's own once it is in view with
// nothing open over it, from the top, as an app opened again starts at the top: on coming
// back, or else once a sheet over it has closed or the home tab is chosen (route). Until
// then it goes on as it was, asking for more with what it was made with.
function renewHome() {
  if (!home || (home.day === visit.day && home.visit === visit.n) || view !== 'home' || titleId || personId
      || document.querySelector('dialog[open]')) return;
  home = null;
  homeKey = '';
  window.scrollTo(0, 0);
  loadHome();
}
for (const d of document.querySelectorAll('dialog')) d.addEventListener('close', renewHome);

function rememberHome(data) {
  receiveMatrices(data.matrices);
  if (data.hero) remember(data.hero);
  (data.featured || []).forEach(remember);
  for (const r of data.rows) r.items.forEach(remember);
  for (const list of [data.top10, data.fresh, data.soon, data.list, data.popular]) (list || []).forEach(remember);
}

// The views drawn from the home page's answer, drawn again once it is here, or once it
// cannot be had: a view opened first (a link to /new, a reload on My List) drew
// placeholders while it was on its way.
function homeArrived() {
  if (view === 'new') renderNew();
  if (view === 'list') renderList();
  if (view === 'search' && where().q.trim().length < 2) suggestions();
}

async function loadHome() {
  const key = currentKey();
  if (home && key === homeKey) return;
  const id = ++homeReq;
  homeAbort?.abort();
  homeAbort = new AbortController();
  const kept = keptPage(key);
  if (kept) {
    home = kept;
    homeKey = key;
    rememberHome(home);
    renderHome();
    homeArrived();
    return;
  }
  if (!home) {
    homeFailed = '';
    renderHomeLoading();
  }
  try {
    // The page belongs to the visit it was asked for in, and keeps what that visit asked
    // with for asking for more (moreBody).
    const { day, n } = visit;
    const ask = await freshFields();
    const body = homeBody(state, ask);
    // The same page asked for as the page started (start.js) is on its way already.
    const started = await take(packed(body));
    const data = await (started ? request('/api/home', {}, started) : post('/api/home', body, homeAbort.signal));
    if (id !== homeReq) return;
    home = { ...data, day, visit: n, ask, tasteKey: key };
    homeKey = key;
    rememberHome(data);
    redraw($('rows'), renderHome);
    keepPage();
    homeArrived();
  } catch (e) {
    if (e.name === 'AbortError' || id !== homeReq) return;
    if (home) toast(e.message);
    else {
      homeFailed = e.message;
      $('hero').classList.remove('loading');
      $('hero').replaceChildren();
      $('rows').replaceChildren(el('p', e.message, 'row-empty'));
      const again = button('btn ghost retry', 'Try again', () => loadHome());
      $('rows').append(again);
      homeArrived();
    }
  }
}

// What asking for more rows carries: what asking for the page does (homeBody), with the
// list as it is now and what the page's visit asked with, unchanged however much it has
// shown since, and the rows shown. So the request is the page's own, and the server answers
// it from the page it keeps for it (library.Kept).
function moreBody(count) {
  const listIds = state.saved.slice().reverse().map(s => s.id);
  return { ...homeBody(state, home.ask), shown: shownRows(home.rows, listIds), count };
}

// The next rows, asked for while ROWS_AHEAD screens of rows are still to come below the
// reader, and asked for again as soon as a page lands if they still are, so a reader
// scrolling on does not meet the end. A reader within a screen of it gets a longer page,
// and posters ahead wait for it (startPosters). After a rating or a My List change the
// request carries the new list, so the rows not yet shown are built from it while those
// on screen stay as they are.
let moreFailures = 0, moreTimer = 0;
async function loadMore() {
  if (!home?.more || moreBusy) return;
  moreBusy = true;
  const id = homeReq;
  const left = sentinel.getBoundingClientRect().top - innerHeight;
  rowsWanted = catchingUp(left, innerHeight);
  try {
    const data = await post('/api/home', await moreBody(rowsToAsk(left, innerHeight)));
    if (id !== homeReq || !home) return;
    moreFailures = 0;
    rememberHome(data);
    home.rows.push(...data.rows);
    Object.assign(home, { more: data.more, taste: data.taste, interests: data.interests, tasteKey: homeKey });
    appendRows(data.rows);
    keepPage();
    syncFoot();
  } catch (e) {
    moreButton.hidden = !home?.more;
    // Asking again goes on by itself, so a failure is said once, not at every try.
    if (++moreFailures === 1) toast(e.message);
  } finally {
    moreBusy = false;
    rowsWanted = false;
    startPosters();
    // Look again, since rows that arrive short of the look-ahead leave the end within it;
    // after a failure, a little later each time.
    clearTimeout(moreTimer);
    moreTimer = setTimeout(watchEnd, retryAfter(moreFailures));
  }
}
function watchEnd() {
  if (!moreWatch) return;
  moreWatch.unobserve(sentinel);
  if (home?.more) moreWatch.observe(sentinel);
}
const sentinel = el('div', '', 'more-rows');
const moreButton = button('btn ghost', 'More rows', () => loadMore());
// Rows still to come stand in at the foot, so a reader who catches up with them sees the
// page going on rather than ending. Not section.row, which the page counts as its rows.
const moreLoading = el('div', '', 'more-loading unseen');
moreLoading.setAttribute('aria-hidden', 'true');
moreLoading.append(skelRow('div', { title: '11em' }), skelRow('div', { title: '8em' }));
// They wait at the foot for as long as the page has more, and a shimmer repaints every
// frame, so they shimmer only while they are on screen.
if ('IntersectionObserver' in window) {
  new IntersectionObserver(entries => moreLoading.classList.toggle('unseen', !entries.at(-1).isIntersecting)).observe(moreLoading);
} else moreLoading.classList.remove('unseen');
// The foot of the page, once the server has no more rows: a quiet note and a way back up.
const pageEnd = el('div', '', 'page-end');
pageEnd.append(el('p', 'That’s everything for today. Rate more shows to grow your rows.'),
  button('btn ghost', 'Back to top', () => {
    $('page').focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: motion() ? 'smooth' : 'auto' });
  }));
sentinel.append(moreLoading, moreButton, pageEnd);
const moreWatch = 'IntersectionObserver' in window
  ? new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) loadMore(); },
    { rootMargin: `0px 0px ${ROWS_AHEAD * 100}% 0px` })
  : null;
// More rows where the scroll cannot be watched, and the end once there are no more.
function syncFoot() {
  moreLoading.hidden = !home?.more;
  moreButton.hidden = !home?.more || !!moreWatch;
  pageEnd.hidden = !home || home.more || !home.rows.length;
}

// Impressions: a card half on screen for a second counts as seen once a day, and once in
// each visit for the day's later visits, and a row seen that way counts as passed over for
// the day unless a card in it is engaged with.
const seenWatch = watcher(id => { noteSeen(memory, id, today(), visitToday()); keepMemory(); });
const rowWatch = watcher(key => { noteRow(memory, key, today()); keepMemory(); });

// A row on its way, laid out as rowEl lays one out: its title a bar of the title's height
// over posters of the row's size. The Top 10's are numbered as it numbers them, and Coming
// soon's leave room for their dates.
function skelRow(tag = 'section', { kind = 'row', title = '10em' } = {}) {
  const sec = el(tag, '', kind === 'soon' ? 'row soon' : 'row');
  sec.setAttribute('aria-hidden', 'true');
  const track = el('ul', '', kind === 'top10' ? 'track ranked' : 'track');
  for (let n = 0; n < 12; n++) {
    const li = el('li');
    if (kind === 'top10') li.append(el('span', String(n + 1), 'num'));
    li.append(skelCard(kind === 'soon'));
    track.append(li);
  }
  const slider = el('div', '', 'slider');
  slider.append(track);
  sec.append(skelIn('h2', 'row-title', title), slider);
  return sec;
}

// Before anything is liked, the page opens with an invitation to pick a few shows.
function inviteEl() {
  const invite = el('div', '', 'invite');
  const go = el('a', 'Find a show to rate', 'btn primary');
  go.href = '/browse';
  go.dataset.link = '';
  invite.append(el('p', 'Rate a few shows and every row starts leaning your way.'), go);
  return invite;
}

// The home page on its way, in the shape it lands in: the featured shows' whole footprint,
// a slide in a track laid out by the rules a featured slide is (featuredSlide), with a
// poster, why it is here, its facts and three buttons on a phone and a title, facts,
// summary and buttons, with the poster beside them until the backdrop comes, on a wide
// screen; then rows. On a wide screen the carousel is the hero's set height; on a phone it
// is as tall as its tallest slide, which is most often one whose facts run to two lines,
// with Trailer, More info and My List on two, and, on a personal page, why it is here on
// one. Whether the page is personal is known already: it is once anything is liked, and
// otherwise it opens with the invitation.
function renderHomeLoading() {
  const personal = state.profile.some(p => p.weight > 0);
  // A phone on its side holds the hero to the screen (style.css), which a title of a line
  // and a summary of two fit.
  const low = matchMedia('(min-width: 760px) and (max-height: 520px)').matches;
  const copy = el('div', '', 'hero-copy');
  copy.append(skelIn('h1', 'hero-title', ...(low ? ['70%'] : ['88%', '56%'])));
  if (personal) copy.append(skelIn('p', 'hero-why', '15em'));
  // Each line of the facts a flex line of its own, with the gap its lines have between them;
  // a wide screen has room for them on one.
  const meta = el('p', '', 'meta');
  meta.setAttribute('aria-hidden', 'true');
  for (const width of personal && !wide() ? ['17em', '11em'] : ['17em']) {
    const line = el('span', '', 'skel-lines');
    line.append(skelText(width));
    meta.append(line);
  }
  copy.append(meta, skelIn('p', 'hero-summary', ...(low ? ['100%', '72%'] : ['100%', '100%', '72%'])));
  const acts = el('div', '', 'hero-acts');
  for (let n = 0; n < 3; n++) acts.append(el('span', '', 'btn skel'));
  copy.append(acts);
  const body = el('div', '', 'hero-body');
  body.append(el('span', '', 'art hero-poster skel'), copy);
  const slide = el('div', '', 'hero-slide');
  slide.append(body);
  const track = el('div', '', 'hero-track');
  track.setAttribute('aria-hidden', 'true');
  track.append(slide);
  const hero = $('hero');
  hero.classList.add('loading');
  hero.replaceChildren(track);
  $('rows').replaceChildren(...(personal ? [] : [inviteEl()]), skelRow('section', { title: '9em' }),
    skelRow('section', { title: '13em' }), skelRow('section', { title: '8em' }));
}

function renderHome() {
  $('hero').hidden=!home.hero;
  // The featured shows, the visit's hero first; a page kept from before them has its hero alone.
  if (home.hero) renderFeatured(home.featured?.length ? home.featured : [home.hero]);
  else { $('hero').replaceChildren(); $('hero').classList.remove('loading'); }
  // The hero rests for the rest of the day and, the day's first, for a week, so the next
  // visits' are others (fresh.js).
  if(home.hero) noteHero(memory, home.hero.id, today());
  keepMemory();
  const holder = $('rows');
  holder.replaceChildren();
  if (!home.personal) holder.append(inviteEl());
  if (home.message) holder.append(el('p', home.message, 'row-empty'));
  holder.append(sentinel);
  appendRows(home.rows);
  // My List keeps a place after the first row even while empty, so adding a show shows it.
  if (!$('row-list')) {
    const first = holder.querySelector('section.row');
    if (first) first.after(listRow()); else holder.insertBefore(listRow(), sentinel);
  }
  syncFoot();
  moreFailures = 0;
  watchEnd();
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
  // On phones a row that lands on screen eases in; the rest are simply there (gestures.js).
  reveal(holder.querySelectorAll('section.row'));
}

// After a rating or a My List change: the card leaves the rows chosen for you, and every
// other card and row keeps its place. The rows not yet shown will come from the new list.
// A first liked show turns a first visit's page into a personal one, so that one reloads.
function settleHome(id) {
  if (!home) return;
  if (!home.personal && state.profile.some(p => p.weight > 0)) { refresh(); return; }
  home.rows = withoutCard(home.rows, id);
  // In a row that goes round its copies go with it (dropCard).
  for (const card of $('rows').querySelectorAll(`section.row[data-kind="row"] .card[data-id="${id}"]`)) {
    const li = card.closest('li');
    if (li && !li.inert) dropCard(li);
  }
  homeKey = currentKey();
  updateRecentRow();
  keepPage();
}

// Recently viewed: titles you opened in the last fortnight and have not rated or listed.
function recentRow() {
  const rated = new Set(state.profile.map(p => p.id)), saved = new Set(state.saved.map(s => s.id));
  const items = selectShows(recentlyViewed(viewed, dayNumber(today()), { rated, saved })
    .map(v => ({ ...v, ...(known.get(v.id) || {}) })),'home');
  const sec = rowEl({ key: 'recent', title: 'Recently viewed', kind: 'recent', items });
  sec.id = 'row-recent';
  sec.hidden = !items.length;
  return sec;
}
function updateRecentRow() {
  const row = $('row-recent');
  if (row) redraw(row, () => row.replaceWith(recentRow()));
}

/* ------------------------------------------------------------ featured */
// The featured shows, in the hero's place: a carousel that goes round (slotOf in format.js).
// Each slide is laid out as the hero always was, all of them in one place, so the carousel
// is as tall as its tallest and the page below never moves, and each is set in its slot
// beside the others by a transform. A swipe, a button, a key, a dot or the carousel's own
// turn moves the track they sit in, so the compositor slides them with no layout on the
// way; once it rests, every slide is set again beside the one shown, which moves nothing on
// screen. Only the slide shown and its neighbours are drawn, and only they have asked for
// their images and details: the rest wait unseen until they are next to come.
const wideScreen = matchMedia('(min-width: 760px)');
const EASE_OUT = 'cubic-bezier(.22,1,.36,1)';     // quick, then settling, for a button or a key
const EASE_THROWN = 'cubic-bezier(.3,.6,.6,1)';   // going on at the speed a swipe let go
const EASE_TURN = 'cubic-bezier(.45,0,.2,1)';     // unhurried, for a turn of its own
let featured = null;    // the carousel on the page: { end }

function renderFeatured(shows) {
  featured?.end();
  featured = carousel($('hero'), shows);
}

// One featured show, laid out as the hero always was. What TMDB's data says is drawn at
// once, so the carousel has its height from the start; its images, and the trailer and
// age rating TMDB lacks, wait for ready(), which the carousel calls once it is shown or
// next to come, the first slide first of all. What comes late goes in only where it
// fits (fits(add, undo)), since the carousel growing would move the page below.
function featuredSlide(s, i, n, fits) {
  const slide = el('div', '', 'hero-slide');
  if (n > 1) {
    slide.setAttribute('role', 'group');
    slide.setAttribute('aria-roledescription', 'slide');
    slide.setAttribute('aria-label', slideLabel(i, n, s.name));
  }
  const bg = el('div', '', 'hero-bg');
  const blur = s.art ? picture(null, 'hero-blur') : null;
  const backdrop = picture(null, 'hero-backdrop', () => slide.classList.add('has-backdrop'));
  if (blur) bg.append(blur);
  bg.append(backdrop);
  // On a phone the poster is the first screen's largest picture.
  const poster = artEl(s, s.art, 'ahead');
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
  const meta = metaEl(s, null, true, s.tmdb?.rating || null);
  copy.append(meta);
  if (s.summary) copy.append(el('p', s.summary, 'hero-summary'));
  const acts = el('div', '', 'hero-acts');
  const more = button('btn primary', 'More info', () => openTitle(s.id), 'info');
  acts.append(more, listButton(s, 'btn'));
  copy.append(acts);
  const clip = button('btn primary', 'Trailer', () => openTitle(s.id, { play: true }), 'play');
  const trailer = () => {
    more.className = 'btn';
    acts.prepend(clip);
  };
  if (s.tmdb?.videos?.length) trailer();
  const body = el('div', '', 'hero-body');
  body.append(poster, copy);
  slide.append(bg, el('div', '', 'hero-shade'), body);
  let asked = false, backdropAsked = false;
  // Only a wide screen shows the backdrop: TMDB's when it has one, else TVmaze's.
  const widen = (urgent = false) => {
    if (!asked || backdropAsked || !wideScreen.matches) return;
    backdropAsked = true;
    if (urgent) backdrop.fetchPriority = 'high';
    if (s.tmdb?.backdrop) backdrop.src = s.tmdb.backdrop;
    else details(s.id).then(d => { if (d?.backdrop) backdrop.src = d.backdrop; });
  };
  // Blurred this much the small poster looks the same as the full picture, and it is there
  // in a moment, often held already as the poster's preview.
  const glow = () => { if (blur && !blur.getAttribute('src')) blur.src = s.poster || s.art; };
  return {
    node: slide, show: s, poster, rel: null, drawn: null, widen,
    // The small poster alone, for a slide beside the one shown that nothing has asked for
    // yet: a swipe that brings it in has a picture, and the full one, often a megabyte or
    // two, waits for ready.
    glimpse() {
      if (asked) return;
      glow();
      const preview = poster.querySelector('img.preview');
      if (preview && preview.getAttribute('src') === null) preview.src = poster.dataset.preview;
    },
    ready(urgent = false) {
      if (asked) return;
      asked = true;
      glow();
      loadPoster(poster, urgent);
      widen(urgent);
      if (!s.tmdb?.videos?.length) {
        videosOf(s.id, s.tmdb).then(videos => {
          if (videos.length) fits(trailer, () => { clip.remove(); more.className = 'btn primary'; });
        });
      }
      if (!s.tmdb?.rating) {
        ratingOf(s.id, s.tmdb).then(age => {
          if (!age.rating) return;
          const badge = el('span', age.rating, 'badge age');
          fits(() => meta.insertBefore(badge, meta.querySelector('.dot-list')), () => badge.remove());
        });
      }
    },
  };
}

// The featured shows in `box`, going round. It turns on its own every TURN_EVERY ms while
// it plays and nothing holds it: not while a pointer or a finger is on it, less than half
// of it is on screen, the page is hidden or a title is open over it, and never under
// reduced motion. Anything the reader does to it (a swipe, an arrow, a key, a dot, a
// button in a slide, keyboard focus coming in) stops those turns until play is pressed.
function carousel(box, shows) {
  const n = shows.length;
  // What a slide adds late stays only if the carousel is no taller for it; one show alone
  // is the hero as it always was, and takes it.
  const fits = (add, undo) => {
    const before = track.offsetHeight;
    add();
    if (n > 1 && track.offsetHeight > before) undo();
  };
  const slides = shows.map((s, i) => featuredSlide(s, i, n, fits));
  const track = el('div', '', 'hero-track');
  track.append(...slides.map(x => x.node));
  box.classList.remove('has-backdrop', 'loading');
  // A slide the reader looks at for a second counts as seen, as a card does.
  for (const x of slides) seenWatch.observe(x.node, x.show.id);
  const ends = new AbortController();
  const on = (target, type, fn, options = {}) => target.addEventListener(type, fn, { ...options, signal: ends.signal });
  on(wideScreen, 'change', () => { for (const x of slides) x.widen(); });
  // Nothing in it is scrolled into view, whatever asks: its slides stay where they are set.
  on(box, 'scroll', () => { box.scrollLeft = 0; box.scrollTop = 0; });
  if (n < 2) {
    for (const name of ['role', 'aria-roledescription', 'aria-label']) box.removeAttribute(name);
    // On phones a new hero crossfades over the one before (gestures.js).
    crossfade(box, track);
    slides[0]?.ready(true);
    return { end: () => ends.abort() };
  }
  box.setAttribute('role', 'region');
  box.setAttribute('aria-roledescription', 'carousel');
  box.setAttribute('aria-label', 'Featured shows');

  const play = button('hero-play', '', () => (playing ? pause() : resume()));
  const dots = el('div', '', 'hero-dots');
  dots.setAttribute('role', 'group');
  dots.setAttribute('aria-label', 'Choose a featured show');
  const dotFor = shows.map((s, i) => {
    const dot = button('hero-dot', '', () => goTo(i));
    dot.setAttribute('aria-label', slideLabel(i, n, s.name));
    // A dot about to be pressed readies its slide.
    for (const type of ['pointerenter', 'focus']) on(dot, type, () => slides[i].ready());
    dots.append(dot);
    return dot;
  });
  const controls = el('div', '', 'hero-controls');
  controls.append(play, dots);
  const prev = button('hero-arrow prev', '', () => step(-1), 'left');
  const next = button('hero-arrow next', '', () => step(1), 'right');
  prev.setAttribute('aria-label', 'Previous featured show');
  next.setAttribute('aria-label', 'Next featured show');
  // Where a move the reader made lands is said; the carousel's own turns go unsaid.
  const said = el('p', '', 'sr');
  said.setAttribute('aria-live', 'polite');

  let current = 0;        // the slide at rest, which places on the strip are counted from
  let offset = 0;         // where the strip is, in slots past the current slide's
  let bound = null;       // the slot a move under way is bound for
  let moving = null;      // its animation
  let grab = null;        // a pointer or finger on the strip
  let dragged = false;    // a drag has just ended, so the click it leaves is not a press
  let playing = motion();
  let timer = 0;
  let ended = false;
  let sight = null;       // whether half of it is on screen
  const held = new Set(['screen']);   // what holds its own turns for now; it is off screen until seen

  const shift = value => `translate3d(${-value * 100}%,0,0)`;
  const slide = value => {
    offset = value;
    track.style.transform = shift(value);
  };
  // Each slide in its slot nearest the strip while it goes from lo to hi, drawn if it is on
  // screen on the way or next to it.
  function place(lo, hi = lo) {
    const middle = current + (lo + hi) / 2;
    slides.forEach((x, i) => {
      const rel = slotOf(i, middle, n) - current;
      const drawn = rel > lo - 2 && rel < hi + 2;
      if (rel !== x.rel) {
        x.rel = rel;
        x.node.style.transform = `translate3d(${rel * 100}%,0,0)`;
      }
      if (drawn !== x.drawn) {
        x.drawn = drawn;
        x.node.style.visibility = drawn ? '' : 'hidden';
      }
    });
  }
  // The slide a keyboard, a screen reader and the dots have: the one a move is bound for,
  // from the moment it sets off. Focus in the slide it leaves goes to the same button in it.
  function show(i) {
    const to = slides[i].node;
    to.inert = false;
    const active = document.activeElement;
    const from = active?.closest?.('.hero-slide');
    if (from && from !== to && track.contains(from)) {
      const buttons = [...to.querySelectorAll('button')];
      (buttons.find(b => b.textContent === active.textContent) || buttons[0])?.focus({ preventScroll: true });
    }
    slides.forEach((x, k) => { x.node.inert = k !== i; });
    dots.style.setProperty('--at', String(i));
    dotFor.forEach((dot, k) => {
      if (k === i) dot.setAttribute('aria-current', 'true');
      else dot.removeAttribute('aria-current');
      dot.tabIndex = k === i ? 0 : -1;
    });
    if (dots.contains(document.activeElement)) dotFor[i].focus({ preventScroll: true });
  }
  const neighbours = () => { for (const k of [-1, 1]) slides[slideIn(current + k, n)].ready(); };

  // Where the strip is: while a move is under way, where it has got to on screen, and it
  // stops there.
  function halt() {
    if (moving) {
      const t = getComputedStyle(track).transform;
      const x = t && t !== 'none' ? new DOMMatrixReadOnly(t).m41 : 0;
      moving.cancel();
      moving = null;
      slide(-x / (track.offsetWidth || innerWidth));
    }
    return offset;
  }
  // Sends the strip from wherever it is to slot `to`: after a swipe let go at `v` px a ms,
  // on at its speed, and for a turn of its own, unhurried and unsaid.
  function move(to, { v = null, width = 0, own = false } = {}) {
    if (ended) return;
    const from = halt();
    to = reach(from, to, n);
    const i = slideIn(current + to, n);
    clearTimeout(timer);
    bound = to;
    place(Math.min(from, to), Math.max(from, to));
    show(i);
    slides[i].ready();
    if (!own) said.textContent = slideLabel(i, n, shows[i].name);
    if (from === to || !motion()) {
      slide(to);
      land();
      return;
    }
    const time = v !== null ? glideTime(Math.abs(to - from) * width, v) : own ? TURN_OWN_MS : turnTime(to - from);
    slide(to);
    const a = track.animate([{ transform: shift(from) }, { transform: shift(to) }],
      { duration: time, easing: v !== null ? EASE_THROWN : own ? EASE_TURN : EASE_OUT });
    moving = a;
    const done = () => { if (moving === a) land(); };
    a.finished.then(done, () => {});
    // A hidden page animates nothing, so there the move counts as done once it would be.
    setTimeout(() => { if (document.visibilityState === 'hidden' || a.playState !== 'running') done(); }, time + 250);
  }
  // At rest in slot `offset`: the slide there is the current one, and every slide is set
  // beside it again, so the strip is back at its start with nothing moved on screen.
  function land() {
    moving?.cancel();
    moving = null;
    bound = null;
    current = slideIn(current + Math.round(offset), n);
    slide(0);
    place(0);
    neighbours();
    schedule();
  }
  // The next slide or the one before, from where a move under way is bound.
  function step(way) {
    pause();
    move((bound ?? Math.round(halt())) + way);
  }
  // Slide i, the shorter way round.
  function goTo(i) {
    pause();
    move(slotOf(i, current + halt(), n) - current);
  }

  function schedule() {
    clearTimeout(timer);
    timer = 0;
    if (playing && !held.size && !moving && !grab?.on && !ended && motion()) timer = setTimeout(turn, TURN_EVERY);
  }
  function turn() {
    timer = 0;
    if (!track.isConnected) { end(); return; }
    // Behind a title page the page stays as it was left.
    if (document.querySelector('dialog[open]')) schedule();
    else move(1, { own: true });
  }
  function paintPlay() {
    play.replaceChildren(icon(playing ? 'pause' : 'play'));
    play.setAttribute('aria-label', playing ? 'Pause the featured shows' : 'Play the featured shows');
  }
  function pause() {
    if (!playing) return;
    playing = false;
    paintPlay();
    schedule();
  }
  function resume() {
    playing = true;
    paintPlay();
    schedule();
  }
  const hold = (why, on) => {
    if (on) held.add(why);
    else held.delete(why);
    schedule();
  };
  // Replaced by another, it stops: a move under way finishes where it was going, unsettled.
  function end() {
    ended = true;
    moving = null;
    ends.abort();
    sight?.disconnect();
    clearTimeout(timer);
  }

  // A swipe or a drag across the strip moves it under the finger, and a scroll up or down
  // is left to the page (touch-action: pan-y).
  on(track, 'pointerdown', e => {
    if (!e.isPrimary || e.button > 0 || grab?.on) return;
    grab = { id: e.pointerId, x: e.clientX, y: e.clientY, on: false, from: 0, home: null, width: 1, samples: [] };
  });
  on(track, 'pointermove', e => {
    const g = grab;
    if (!g || e.pointerId !== g.id) return;
    const dx = e.clientX - g.x, dy = e.clientY - g.y;
    if (!g.on) {
      if (!wandered(dx, dy)) return;
      if (heading(dx, dy) !== 'x') {
        grab = null;
        return;
      }
      g.on = true;
      pause();
      g.width = track.offsetWidth || innerWidth;
      // Caught on its way, the strip stops under the finger; from rest, the slide shown is
      // where the swipe sets off.
      g.home = moving ? null : Math.round(offset);
      g.from = halt();
      bound = null;
      clearTimeout(timer);
      try { track.setPointerCapture(e.pointerId); } catch { /* the pointer has gone */ }
      box.classList.add('dragging');
      getSelection()?.removeAllRanges();
      neighbours();
    }
    const value = g.from - dx / g.width;
    // Past a whole slide, the next one on is where the swipe now sets off.
    if (g.home !== null && Math.abs(value - g.home) >= 1) g.home += Math.sign(value - g.home);
    slide(value);
    place(value);
    g.samples.push([performance.now(), e.clientX]);
    if (g.samples.length > 8) g.samples.shift();
  });
  const letGo = e => {
    const g = grab;
    if (!g || e.pointerId !== g.id) return;
    grab = null;
    if (!g.on) return;
    box.classList.remove('dragging');
    dragged = true;
    setTimeout(() => { dragged = false; });
    const v = e.type === 'pointerup' ? speed(g.samples, performance.now()) : 0;
    move(landing(offset, v, g.width, g.home), { v, width: g.width });
  };
  on(track, 'pointerup', letGo);
  on(track, 'pointercancel', letGo);
  // The strip losing the pointer ends the drag; the slide the finger first touched giving
  // it up to the strip, which bubbles here too, does not.
  on(track, 'lostpointercapture', e => { if (e.target === track) letGo(e); });
  // The click a drag leaves where it ends is not a press.
  on(box, 'click', e => {
    if (!dragged) return;
    dragged = false;
    e.preventDefault();
    e.stopPropagation();
  }, { capture: true });
  on(box, 'dragstart', e => e.preventDefault());
  on(track, 'click', e => { if (e.target.closest('button, a')) pause(); });
  on(box, 'keydown', e => {
    if ((e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    step(e.key === 'ArrowRight' ? 1 : -1);
  });
  on(box, 'focusin', e => {
    neighbours();
    if (box.contains(e.relatedTarget)) return;
    let keyboard = false;
    try { keyboard = e.target.matches(':focus-visible'); } catch { /* a browser without :focus-visible */ }
    if (keyboard) pause();
  });
  // A mouse over it, or a finger on it, holds it, and readies the slides either side.
  on(box, 'pointerenter', () => {
    neighbours();
    hold('pointer', true);
  });
  on(box, 'pointerleave', () => hold('pointer', false));
  on(document, 'visibilitychange', () => hold('page', document.visibilityState === 'hidden'));
  on(matchMedia('(prefers-reduced-motion: reduce)'), 'change', e => { if (e.matches) pause(); });
  if ('IntersectionObserver' in window) {
    sight = new IntersectionObserver(entries => hold('screen', entries.at(-1).intersectionRatio < .5), { threshold: [0, .5] });
    sight.observe(box);
  } else held.delete('screen');
  if (document.visibilityState === 'hidden') held.add('page');

  paintPlay();
  place(0);
  slide(0);
  crossfade(box, controls, prev, next, track, said);
  show(0);
  slides[0].ready(true);
  // The slides either side show their small posters from the start. The next one's full
  // picture, which its turn brings in, follows the first slide's, so the first has the
  // connection to itself; the one before waits for the reader to reach for the carousel
  // (neighbours).
  for (const k of [-1, 1]) slides[slideIn(k, n)].glimpse();
  const upNext = () => { if (!ended) slides[slideIn(current + 1, n)].ready(); };
  const first = slides[0].poster.querySelector('img');
  if (!first || (first.complete && first.naturalWidth)) upNext();
  else {
    first.addEventListener('load', upNext, { once: true, signal: ends.signal });
    first.addEventListener('error', upNext, { once: true, signal: ends.signal });
  }
  schedule();
  return { end };
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

// Posters load ahead of the reader. A row's wait until it comes within POSTERS_AHEAD
// screens below the screen, or one above; then those it shows are wanted, with the
// next two for a swipe, and, swiped along, the next two past wherever it has got to
// (postersToLoad). Where a browser's own lazy loading waits until a row is near, and
// Safari's until it is almost on screen, these are in before the row is seen.
//
// On a slow connection every image asked for shares it, and a crowd of posters no one
// sees yet made those on screen, and the next rows, wait seconds for their turn. So
// they start a few at a time (POSTERS_AT_ONCE): those each row shows before any row's
// next two, nearest the screen first, while a row on screen starts those it shows at
// once, up to as many again, and over a fast connection its next two with them. A page
// flung over a slow connection, though, loads FLUNG_AT_ONCE at a time, rows on screen
// included, leaving it to the rows the reader is heading for; and while the reader waits
// at the end for rows (rowsWanted), no poster starts until they land.
const wanted = new Map();       // rows within reach: the posters they show, and the next ones, not yet started
const scrolls = [];             // the page's last few [time, scrollY], for its speed
let postersLoading = 0, postersFrame = 0, postersTimer = 0, rowsWanted = false;
let flungUntil = 0;             // a page flung is still being flung until a moment after it last went fast
let pace = 0;                   // how long posters take, a running average in ms
const rowsNear = 'IntersectionObserver' in window
  ? new IntersectionObserver(entries => {
    for (const { target, isIntersecting } of entries) {
      if (isIntersecting) want(target); else wanted.delete(target);
    }
    startPosters();
  }, { rootMargin: `100% 0px ${POSTERS_AHEAD * 100}% 0px` })
  : null;
const begun = box => box.querySelector('img')?.getAttribute('src') !== null;
function waiting() {
  for (const [shows, next] of wanted.values()) if (shows.length || next.length) return true;
  return false;
}
// The posters a row within reach wants now and has not started: those it shows, and the
// next ones. A row that goes round wants its cards' posters wherever they show, in their
// own places or through copies, and the next ones the way it is going (loopPosters).
function want(sec) {
  const track = sec.querySelector('.track');
  if (!track) return;
  const box = track.getBoundingClientRect(), loop = loopOf.get(track);
  const shows = [], next = [];
  if (loop?.on) {
    // Which way the reader is taking it: the row's own moves by a lap leave `seen` where
    // they put it, so only the reader's count.
    const left = track.scrollLeft;
    if (Math.abs(left - loop.seen) > .5) loop.back = left < loop.seen;
    loop.seen = left;
    // The places keep their spacing as the row moves, so one of them says where all are.
    const zero = loop.holder[0].getBoundingClientRect().left;
    const places = loop.spans.map(([from, to], order) => [zero + from, zero + to, loop.cardAt[order]]);
    const [shown, ahead] = loopPosters(places, box.left, box.right, loop.back);
    for (const [cards, into] of [[shown, shows], [ahead, next]]) {
      for (const n of cards) {
        const art = loop.cards[n].querySelector('.art');
        if (art && !begun(art)) into.push(art);
      }
    }
  } else {
    const cards = [...track.children];
    const lefts = cards.map(li => li.getBoundingClientRect().left);
    cards.slice(0, postersToLoad(lefts, box.right)).forEach((li, i) => {
      const art = li.querySelector('.art');
      if (art && !begun(art)) (lefts[i] < box.right ? shows : next).push(art);
    });
  }
  wanted.set(sec, [shows, next]);
}
function startPosters() {
  // Rows the reader is waiting for come before any poster.
  if (rowsWanted) return;
  const rows = [];
  for (const [sec, lists] of wanted) {
    if (!sec.isConnected) {
      wanted.delete(sec);
      rowsNear.unobserve(sec);
    } else if (lists[0].length || lists[1].length) {
      const r = sec.getBoundingClientRect();
      rows.push([r.top >= innerHeight ? r.top - innerHeight : r.bottom <= 0 ? -r.bottom : 0, lists]);
    }
  }
  rows.sort((a, b) => a[0] - b[0]);
  // A page flung over a fast connection loads as one stopped at does.
  const slow = pace > SLOW_POSTER;
  const flung = slow && performance.now() < flungUntil;
  const most = flung ? FLUNG_AT_ONCE : POSTERS_AT_ONCE;
  // What each row shows, then each row's next ones; a row on screen, those it shows at
  // once, up to twice as many, and over a fast connection its next ones with them.
  for (const pass of [0, 1]) {
    for (const [gap, lists] of rows) {
      const boxes = lists[pass];
      const now = !gap && !flung && (!pass || !slow);
      while (boxes.length && (begun(boxes[0]) || postersLoading < (now ? 2 * most : most))) {
        const box = boxes.shift();
        if (!begun(box)) startPoster(box, now && !pass);
      }
    }
  }
}
function startPoster(box, shown) {
  const img = box.querySelector('img');
  const from = performance.now();
  let done = false;
  const settle = () => {
    if (done) return;
    done = true;
    postersLoading--;
    startPosters();
  };
  postersLoading++;
  img.addEventListener('load', () => {
    pace = posterPace(pace, performance.now() - from);
    settle();
  }, { once: true });
  img.addEventListener('error', settle, { once: true });
  // A poster that never answers gives up its turn.
  setTimeout(settle, 15_000);
  loadPoster(box, shown);
}
// A row that comes on screen while its posters wait starts them, and so does a page that
// stops. A flick that lands on the page stops it for a moment, so a page counts as flung
// until STILL_FLUNG ms after it last went fast.
window.addEventListener('scroll', () => {
  const now = performance.now();
  scrolls.push([now, scrollY]);
  if (scrolls.length > 8) scrolls.shift();
  if (Math.abs(speed(scrolls, now)) > FLUNG) flungUntil = now + STILL_FLUNG;
  // Rows asked for ahead become the ones the reader waits for once they catch up.
  if (moreBusy && !rowsWanted) rowsWanted = catchingUp(sentinel.getBoundingClientRect().top - innerHeight, innerHeight);
  if (!waiting()) return;
  postersFrame ||= requestAnimationFrame(() => {
    postersFrame = 0;
    startPosters();
  });
  clearTimeout(postersTimer);
  postersTimer = setTimeout(startPosters, STILL_FLUNG + 50);
}, { passive: true });

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
    const card = cardEl(c, { rank: r.kind === 'top10' ? c.rank || n + 1 : 0, soon: r.kind === 'soon', row, ahead: true });
    if (watch) seenWatch.observe(card, c.id);
    li.append(card);
    track.append(li);
  });
  // A row that goes round pages on into its copies, which reach three pages past either
  // end, and moves among its own cards once it rests (settleLoop): moved mid-page, from
  // between two cards, it would jump to one.
  const page = dir => track.scrollBy({ left: dir * track.clientWidth * .86, behavior: motion() ? 'smooth' : 'auto' });
  const prev = button('nudge prev', '', () => page(-1), 'left');
  const next = button('nudge next', '', () => page(1), 'right');
  prev.setAttribute('aria-label', `Back through ${r.title}`);
  next.setAttribute('aria-label', `More of ${r.title}`);
  // Swiped along, or resized, a row within reach wants the posters it now shows and the
  // next two. Both arrows stay on a row that goes round, which has no end to reach.
  const sync = () => {
    if (!track.isConnected) { syncers.delete(sync); return; }
    const round = loopOf.get(track)?.on;
    prev.hidden = !round && track.scrollLeft < 8;
    next.hidden = !round && track.scrollLeft + track.clientWidth >= track.scrollWidth - 8;
    if (wanted.has(sec)) {
      want(sec);
      startPosters();
    }
  };
  syncers.add(sync);
  track.addEventListener('scroll', () => requestAnimationFrame(sync), { passive: true });
  requestAnimationFrame(sync);
  loopRow(track, sync);
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
  rowsNear?.observe(sec);
  return sec;
}
window.addEventListener('resize', () => { for (const sync of [...syncers]) sync(); });

/* ------------------------------------------------------------ rows that go round */
// A row whose cards run past the screen goes round (the maths is in gestures.js): past
// its last card it carries straight on into its first, and back past its first into its
// last, with the same momentum and snapping, on a finger, a trackpad or the arrows. While
// it is near the screen, copies of its last cards wait before its first and copies of its
// first after its last. Once it comes to rest it moves by whole laps back among its own
// cards, and a card that shows through a copy's place trades places with that copy. Every
// place keeps a flex order, so the two trade without anything else in the row moving, and
// what shows at rest is always the cards themselves, to tap, hold, hover and count as seen.
//
// A copy is its card less what only a hover shows, inert and hidden from assistive
// technology, so Tab and a screen reader meet each card once, in its own order; it never
// counts as seen, and its poster starts only with its card's, from the same address, which
// the browser fetches once. A row well off the screen that rests where it started lets
// its copies go, so a long page holds them only for the few rows near the reader.
const loopOf = new WeakMap();         // a row's track: how it goes round
const copiedArt = new WeakMap();      // a card's poster: its copies' posters
const SCROLL_ENDS = 'onscrollend' in window;
// The scroll a row's own move sets off arrives within a frame or two of it.
const OWN_MOVE = 50;

// Watches a row for the moments it may have come to rest: when its scroll ends, or, where
// no event says so, once it has not moved for REST ms; and when a finger lifts from it, as
// nothing moves under one. Its scroll events read nothing of the page, so they never make
// it lay out early.
function loopRow(track, sync) {
  const loop = { track, sync, on: false, near: false, held: false, moved: -Infinity, put: -Infinity, seen: 0, back: false,
    timer: 0, width: 0, pad: 0, before: 0, cards: [], ...unlooped() };
  loopOf.set(track, loop);
  track.addEventListener('scroll', () => {
    const now = performance.now();
    if (now - loop.put < OWN_MOVE) return;
    loop.moved = now;
    if (!SCROLL_ENDS) waitLoop(loop);
  }, { passive: true });
  track.addEventListener('scrollend', () => settleLoop(loop));
  track.addEventListener('touchstart', () => { loop.held = true; }, { passive: true });
  const lift = e => {
    loop.held = e.touches.length > 0;
    if (!loop.held) waitLoop(loop);
  };
  track.addEventListener('touchend', lift, { passive: true });
  track.addEventListener('touchcancel', lift, { passive: true });
  loopsNear?.observe(track);
}

// What a row that goes round knows of its places, each numbered by its flex order: what
// holds it (holder), whose card it is (cardAt) and where it spans along the row from the
// first (spans), and for each card its places, its own first (places), and what fills
// them, the card and then its copies (items). A row without copies knows none of it.
const unlooped = () => ({ all: [], holder: [], cardAt: [], spans: [], places: [], items: [], cardOf: new Map() });

// Puts a row `left` px along, as its own move rather than the reader's.
function putLoop(loop, left) {
  loop.track.scrollLeft = left;
  loop.put = performance.now();
  loop.seen = loop.track.scrollLeft;
}

// Looks again in a moment, once the row has been still for REST ms.
function waitLoop(loop) {
  clearTimeout(loop.timer);
  loop.timer = setTimeout(() => {
    if (performance.now() - loop.moved < REST) waitLoop(loop);
    else settleLoop(loop);
  }, REST);
}

// How far a row is from resting on a card, as one that snaps does once its scroll is over.
function offCard(loop) {
  const { track } = loop;
  const edge = track.getBoundingClientRect().left + (parseFloat(getComputedStyle(track).paddingLeft) || 0);
  return toCard([...track.children].map(li => li.getBoundingClientRect().left), edge,
    track.scrollLeft, track.scrollWidth - track.clientWidth);
}
const resting = loop => !loop.held && performance.now() - loop.moved >= REST;

// A row at rest moves by whole laps back among its own cards (lapHome), and each card
// takes whichever of its places shows (restPlace), so no copy shows. It rests only on a
// card: a row short of one is on its way there, and has LOOP_WAIT ms to arrive before it
// eases the rest of the way itself, for a lap from anywhere else would be snapped to a card
// at once, a visible jump. A row near the screen without copies gets them, and one of
// another width is copied anew for it.
function settleLoop(loop) {
  clearTimeout(loop.timer);
  const { track } = loop;
  if (loop.held || !track.isConnected || !track.clientWidth) return;
  if (!loop.on) {
    if (loop.near) copyLoops([loop]);
    return;
  }
  if (track.clientWidth !== loop.width) {
    holdPlace(track, () => {
      uncopyLoop(loop);
      copyLoops([loop]);
    });
    if (!loop.on) return;
  }
  // At either end of its scroll, where a fling past all its copies stops, no browser will
  // snap it further, so it goes on to a card at once.
  const off = offCard(loop), end = track.scrollLeft <= 1 || track.scrollLeft >= track.scrollWidth - track.clientWidth - 1;
  if (off && !end && performance.now() - loop.moved < LOOP_WAIT) {
    waitLoop(loop);
    return;
  }
  // To the card itself, as a scroll by a distance snaps on to the next card beyond it.
  if (off) {
    track.scrollTo({ left: track.scrollLeft + off, behavior: motion() ? 'smooth' : 'auto' });
    return;
  }
  const box = track.getBoundingClientRect();
  const rects = loop.holder.map(li => li.getBoundingClientRect());
  const start = rects[loop.before].left;
  const move = lapHome(box.left + loop.pad - start, rects[loop.before + loop.cards.length].left - start);
  // Where it goes is read before anything trades places: a browser that keeps a row on the
  // card it snapped to may scroll the row as that card trades, so the row is put where it
  // belongs, not moved by a distance.
  const target = track.scrollLeft + move;
  let traded = false;
  loop.places.forEach((orders, n) => {
    const t = restPlace(orders.map(o => [rects[o].left - move, rects[o].right - move]), box.left, box.right);
    const [card, ...copies] = loop.items[n];
    const others = orders.filter((_, k) => k !== t);
    for (const [li, order] of [[card, orders[t]], ...copies.map((copy, k) => [copy, others[k]])]) {
      if (loop.holder[order] === li) continue;
      li.style.order = order;
      loop.holder[order] = li;
      traded = true;
    }
  });
  if (move || traded) putLoop(loop, target);
}

// Copies go into rows as they come near the screen. However many arrive together, the
// page is laid out twice for them: every row measured, then all of them copied, then each
// scrolled on by the copies now before its first card, to show what it showed.
function copyLoops(list) {
  const plans = [];
  for (const loop of list) {
    const { track } = loop;
    if (loop.on || loop.held || !track.isConnected || !track.clientWidth) continue;
    const cards = [...track.children];
    if (cards.length < 2) continue;
    const style = getComputedStyle(track);
    const pad = parseFloat(style.paddingLeft) || 0, gap = parseFloat(style.columnGap) || 0;
    const box = track.getBoundingClientRect(), rects = cards.map(li => li.getBoundingClientRect());
    const lap = rects.at(-1).right + gap - rects[0].left;
    if (!goesRound(lap, gap, pad, track.clientWidth)) continue;
    // A browser scrolls by whole pixels, and rounds a place a fraction along one way as a
    // fling ends and another as the row moves by a lap, a pixel's jump. So every place is
    // whole pixels wide, and every place a whole number of pixels along: the Top 10's cards,
    // beside their numbers, are rounded up by what they lack, less than a pixel after each.
    const whole = rects.some(r => Math.abs(r.width - Math.round(r.width)) > .01) ? rects.map(r => Math.ceil(r.width - .01)) : null;
    plans.push({ loop, cards, pad, whole, scroll: track.scrollLeft, at: rects[0].left - box.left + track.scrollLeft,
      ...loopCopies(track.clientWidth, lap / cards.length) });
  }
  for (const plan of plans) copyLoop(plan);
  // Where each place spans, and where each first card is now along its row, however far a
  // browser scrolled the row as the copies went in before it.
  for (const plan of plans) {
    const { loop } = plan, { track } = loop;
    const rects = loop.holder.map(li => li.getBoundingClientRect());
    loop.spans = rects.map(r => [r.left - rects[0].left, r.right - rects[0].left]);
    plan.by = rects[plan.before].left - track.getBoundingClientRect().left + track.scrollLeft - plan.at;
  }
  for (const { loop, scroll, by } of plans) {
    putLoop(loop, scroll + by);
    loop.sync();
  }
}
// A row's copies go in either side of its cards, and every place is numbered in the order
// it is laid out: the copies before, the cards, then the copies after.
function copyLoop({ loop, cards, pad, whole, before, after }) {
  const { track } = loop;
  if (whole) cards.forEach((li, n) => { li.style.width = `${whole[n]}px`; });
  const which = copiesOf(cards.length, before, after);
  for (const li of cards) {
    const art = li.querySelector('.art');
    if (art) copiedArt.delete(art);
  }
  loop.cardOf = new Map(cards.map((li, n) => [li, n]));
  const copy = n => {
    const li = copyOf(cards[n]);
    loop.cardOf.set(li, n);
    return li;
  };
  const befores = which.before.map(copy), afters = which.after.map(copy);
  track.prepend(...befores);
  track.append(...afters);
  loop.all = [...befores, ...cards, ...afters];
  loop.all.forEach((li, n) => { li.style.order = n; });
  loop.holder = [...loop.all];
  loop.cardAt = loop.all.map(li => loop.cardOf.get(li));
  loop.items = cards.map(li => [li]);
  loop.places = cards.map((_, n) => [before + n]);
  which.before.forEach((n, k) => {
    loop.items[n].push(befores[k]);
    loop.places[n].push(k);
  });
  which.after.forEach((n, k) => {
    loop.items[n].push(afters[k]);
    loop.places[n].push(before + cards.length + k);
  });
  Object.assign(loop, { on: true, cards, pad, before, width: track.clientWidth });
}

// A card's copy: the card less the buttons and words only a hover shows, inert and
// hidden from assistive technology. Its poster shows once its card's starts (loadPoster).
function copyOf(li) {
  const copy = li.cloneNode(false);
  for (const part of li.children) {
    if (!part.classList.contains('card')) {
      copy.append(part.cloneNode(true));
      continue;
    }
    const card = part.cloneNode(false);
    for (const bit of part.children) if (!bit.classList.contains('card-meta')) card.append(bit.cloneNode(true));
    copy.append(card);
  }
  copy.inert = true;
  copy.setAttribute('aria-hidden', 'true');
  const own = li.querySelector('.art'), art = copy.querySelector('.art'), img = art?.querySelector('img');
  if (own && img) {
    // Not a poster redraw may hand to a new card, which it finds by address.
    art.removeAttribute('data-src');
    img.addEventListener('load', () => art.classList.add('loaded'), { once: true });
    img.addEventListener('error', () => img.remove(), { once: true });
    if (img.complete && img.naturalWidth) art.classList.add('loaded');
    copiedArt.set(own, [...(copiedArt.get(own) || []), art]);
  }
  return copy;
}

// A row's copies go, and its cards back to their own places and widths.
function uncopyLoop(loop) {
  if (!loop.on) return;
  for (const li of loop.all) {
    if (li.inert) li.remove();
    else li.style.removeProperty('order');
  }
  for (const li of loop.cards) {
    li.style.removeProperty('width');
    const art = li.querySelector('.art');
    if (art) copiedArt.delete(art);
  }
  Object.assign(loop, { on: false, ...unlooped() });
}

// Whether a row rests where it started, on its first card in that card's own place.
function atFirst(loop) {
  const { track } = loop;
  const first = loop.cards[0];
  if (!first || !resting(loop) || !track.clientWidth) return false;
  return loop.holder[loop.before] === first
    && Math.abs(first.getBoundingClientRect().left - track.getBoundingClientRect().left - loop.pad) < 1;
}

// Runs `change` on a row and keeps it showing what it showed: the first card it shows
// stays where it is on screen, or, when that card is `gone`, the next takes its place. In
// a row that goes round the card comes back in its own place, which looks the same.
function holdPlace(track, change, gone = null) {
  const loop = loopOf.get(track);
  const box = track.getBoundingClientRect();
  const shown = [];
  for (const li of track.children) {
    const r = li.getBoundingClientRect();
    if (r.right > box.left + .5 && r.left < box.right - .5) shown.push([r.left, loop?.on ? loop.cards[loop.cardOf.get(li)] : li]);
  }
  shown.sort((a, b) => a[0] - b[0]);
  const [first, second] = shown;
  const [at, card] = first?.[1] === gone ? [first[0], second?.[1]] : first || [];
  change();
  if (!card?.isConnected) return;
  const left = card.getBoundingClientRect().left - track.getBoundingClientRect().left + track.scrollLeft - (at - box.left);
  if (loop) putLoop(loop, left); else track.scrollLeft = left;
}

// A card leaves its row, and its copies with it, and the row keeps its place.
function dropCard(li) {
  const track = li.parentElement, loop = track && loopOf.get(track);
  if (!loop) {
    li.remove();
    return;
  }
  const round = loop.on;
  holdPlace(track, () => {
    uncopyLoop(loop);
    li.remove();
    if (round) copyLoops([loop]);
  }, li);
  settleLoop(loop);
  loop.sync();
}

// Rows get their copies within half a screen of it, those at rest at once and any on the
// move once they rest; a row further off that rests where it started lets them go.
const loopsNear = 'IntersectionObserver' in window
  ? new IntersectionObserver(entries => {
    const coming = [], going = [];
    for (const { target, isIntersecting } of entries) {
      const loop = loopOf.get(target);
      if (!loop) continue;
      if (!target.isConnected) {
        loopsNear.unobserve(target);
        continue;
      }
      loop.near = isIntersecting;
      if (!isIntersecting) going.push(loop);
      else if (resting(loop) && loop.on) settleLoop(loop);
      else if (resting(loop)) coming.push(loop);
    }
    copyLoops(coming);
    // Only a row holding copies has any to let go.
    for (const loop of going.filter(loop => loop.on && atFirst(loop))) {
      uncopyLoop(loop);
      putLoop(loop, 0);
      loop.sync();
    }
  }, { rootMargin: '50% 0px' })
  : null;

// Resized, the rows near the screen settle again: copied anew for their width, or letting
// their copies go once all their cards fit, while a row that no longer fits gets them.
let loopsResized = 0;
window.addEventListener('resize', () => {
  clearTimeout(loopsResized);
  loopsResized = setTimeout(() => {
    for (const track of document.querySelectorAll('.track')) {
      const loop = loopOf.get(track);
      if (loop && (loop.near || loop.on) && resting(loop)) settleLoop(loop);
    }
  }, REST);
});

// A poster that opens the title page. On a mouse, hovering shows its match and quick
// buttons for My List and a rating; those skip the tab order, since the title page
// offers the same actions to everyone. A card may carry one call-out, such as "Same
// creator as Breaking Bad". In a row (ahead) its poster loads when the row asks.
function cardEl(c, { rank = 0, soon = false, note = '', row = '', ahead = false, related = false } = {}) {
  const card = el('div', '', 'card');
  card.dataset.id = c.id;
  const hit = button('card-hit', '', () => openTitle(c.id, { row }));
  hit.setAttribute('aria-label', [
    c.name, c.year, c.match ? `${c.match}% match` : '',
    rank ? `number ${rank} in the Top 10 today` : c.badge === 'top10' ? 'in the Top 10 today' : '',
    c.badge === 'new' ? 'new' : '', soon && c.premiered ? `premieres ${premiere(c.premiered)}` : '', c.callout, note,
  ].filter(Boolean).join(', '));
  hit.append(artEl(c, c.poster, ahead ? 'ahead' : true));
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
  quick.append(listButton(full, 'tiny'), ...(newer(c.id) ? [] : rateButtons(full, [.7, 1], 'tiny')));
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
  enhanceShowCard(card, { ...full, similar: c.similar, why: c.why }, related);
  return card;
}

// A title page is asked for as a poster is pressed rather than as the press lifts, so the
// tap that follows finds its answer and live details on their way (titleOf and details keep
// what they asked). A mouse press is a click on its way. A finger that lands on a poster
// may be starting a scroll instead, and scrolling past posters must ask for nothing, so a
// finger asks only once it has rested a moment where it landed.
const PRESS_REST = 60;      // ms a finger stays put on a poster before its title is asked for
const PRESS_SLOP = 6;       // px it may wander meanwhile
let pressing = null;
function pressed(id) {
  titleOf(id).catch(() => {});
  ratings(id).catch(() => {});
  // A show newer than the catalogue has its live details with its title (showTitle).
  if (!newer(id)) details(id);
}
document.addEventListener('pointerdown', e => {
  clearTimeout(pressing?.timer);
  pressing = null;
  if (!e.isPrimary || e.button !== 0) return;
  const id = Number(e.target.closest('.card-hit, .more-open')?.closest('[data-id]')?.dataset.id);
  if (!id) return;
  if (e.pointerType === 'mouse') { pressed(id); return; }
  pressing = { x: e.clientX, y: e.clientY, timer: setTimeout(() => { pressing = null; pressed(id); }, PRESS_REST) };
}, { passive: true });
document.addEventListener('pointermove', e => {
  if (pressing && Math.hypot(e.clientX - pressing.x, e.clientY - pressing.y) > PRESS_SLOP) {
    clearTimeout(pressing.timer);
    pressing = null;
  }
}, { passive: true });
for (const type of ['pointerup', 'pointercancel']) {
  document.addEventListener(type, () => {
    clearTimeout(pressing?.timer);
    pressing = null;
  }, { passive: true });
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
  const items = selectShows(state.saved.slice().reverse().map(s => ({ ...s, ...(known.get(s.id) || {}) })),'home').slice(0,20);
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
  if (newer(c.id)) {
    toast(`${c.name || 'This show'} can be rated once the nightly refresh adds it to the catalogue.`);
    return;
  }
  const found = state.profile.find(p => p.id === c.id);
  if (found && found.weight === weight) {
    state.profile = state.profile.filter(p => p.id !== c.id);
    toast('Rating removed.');
  } else if (found) {
    found.weight = weight;
    toast(RATES.find(r => r.weight === weight).said);
  } else {
    if (state.profile.length >= MAX_RATED) {
      toast(`You have rated ${MAX_RATED.toLocaleString()} shows, the most Couchside reads. Remove a rating in My List first.`);
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
  // From someone's page a title is a step on from them, so Back comes back to them: their
  // page makes way, and the title leaves them out of its address.
  const fromPerson = !!personId;
  const url = withShow(location.pathname, fromPerson ? withPerson('', location.search, null) : location.search, id);
  if ($('title').open && !fromPerson) history.replaceState(history.state, '', url);
  else {
    if (fromPerson) keepPlace();
    history.pushState({ modal: true }, '', url);
  }
  if (fromPerson) hidePerson(true);
  showTitle(id, play);
}
function closeTitle() {
  if (history.state?.modal) {
    keepPlace();
    history.back();
  } else {
    history.replaceState(null, '', withShow(location.pathname, location.search, null));
    hideTitle();
  }
}
function hideTitle() {
  if (episodeId) hideEpisode();
  T?.ratingsDispose?.();
  T?.sectionsDispose?.();
  titleToken++;
  titleId = null;
  T = null;
  // A trailer stops at once. The rest of the page goes once the sheet has slid away.
  $('t-sheet').querySelector('.t-player iframe')?.remove();
  if ($('title').open) $('title').close();
  modalOpen();
  document.title = TITLES[view] || 'Couchside';
  if (view === 'home') updateRecentRow();
}
// The page beneath holds still while a title or a person is open over it.
const modalOpen = () => document.documentElement.classList.toggle('modal-open', !!titleId || !!personId);
// The page is emptied once its sheet has closed, unless a title opened again meanwhile.
$('title').addEventListener('close', () => { if (!titleId) $('t-sheet').replaceChildren(); });
$('title').addEventListener('cancel', e => { e.preventDefault(); closeTitle(); });
$('t-sheet').addEventListener('click', e => { if (titleId && e.target.closest('a[target="_blank"]')) engaged(titleId); });
$('title').addEventListener('click', e => { if (e.target === $('title')) closeTitle(); });
// Every dialog is a sheet (gestures.js): a swipe down closes it as its close button does,
// and a title, an episode over it and a person through their history.
sheets(d => (d === $('title') ? closeTitle() : d === $('episode') ? closeEpisode()
  : d === $('person') ? closePerson() : d.close()));

// Where the open sheets are scrolled to and which of their long parts are open, kept in the
// history entry being left, so a sheet Back builds again comes back to the same place.
function keepPlace() {
  const place = {};
  if (T) place.title = { y: $('title').scrollTop, open: { ...T.open } };
  if (P) place.person = { y: $('person').scrollTop, open: { ...P.open } };
  history.replaceState({ ...history.state, place }, '');
}
// A sheet built again returns to `place`, each time more of what was above it paints, while
// it still shows the same page (`same`) and until the reader moves it themselves.
function returnTo(dialog, place, same) {
  if (!place?.y) return () => {};
  let moved = false;
  for (const type of ['wheel', 'touchstart', 'keydown']) {
    dialog.addEventListener(type, () => { moved = true; }, { once: true, passive: true });
  }
  return () => { if (!moved && same()) dialog.scrollTop = place.y; };
}

function showTitle(id, play = false, place = null) {
  if (E && E.show !== id) hideEpisode();
  T?.ratingsDispose?.();
  T?.sectionsDispose?.();
  const token = ++titleToken;
  titleId = id;
  T = buildTitle({ ...info(id), id });
  if (place?.open) Object.assign(T.open, place.open);
  const dialog = $('title');
  // A title page still sliding away comes back up.
  if (!dialog.open || closing(dialog)) dialog.showModal();
  modalOpen();
  dialog.scrollTop = 0;
  const settle = returnTo(dialog, place, () => token === titleToken);
  T.close.focus({ preventScroll: true });
  document.title = `${T.card.name || 'Show'} · Couchside`;
  paintTitle();
  // The durable episode answer can land before cast or recommendations. Ask at once,
  // rather than fetching a season first and then asking for those episodes again.
  ratings(id).then(data => {
    if (token !== titleToken) return;
    T.episodeData = data;
    paintEpisodes(settle);
  }).catch(() => {
    if (token !== titleToken) return;
    T.ratingsFailed = true;
    paintEpisodes(settle);
  });
  const loaded = titleOf(id);
  loaded.then(data => {
    if (token !== titleToken) return;
    remember({ ...data.show, newer: !!data.show.newer });
    [...data.more, ...(data.fans || [])].forEach(remember);
    T.data = data;
    paintTitle();
    paintBackdrop();
    paintMore();
    settle();
  }).catch(e => {
    if (token !== titleToken) return;
    T.error = e.message;
    paintTitle();
    paintBackdrop();
  });
  // A show newer than the catalogue has its live details with its title, from the same
  // TVmaze answer, so the server asks TVmaze once for both; a catalogue show asks apart.
  const lived = newer(id) ? loaded.then(data => data.details || details(id), () => null) : details(id);
  lived.then(live => {
    if (token !== titleToken) return;
    if (!live) {
      // Saved episodes remain usable when cast and other live details are unavailable.
      T.liveFailed = true;
      paintTitle();
      paintEpisodes(settle);
      return;
    }
    T.live = live;
    paintTitle();
    paintBackdrop();
    paintEpisodes(settle);
    settle();
  });
  // TMDB's trailers and rating arrive with the title; the live lookups fill in what it lacks.
  const tm = loaded.then(data => data.tmdb, () => null);
  tm.then(known => videosOf(id, known)).then(videos => {
    if (token !== titleToken) return;
    T.videos = videos;
    paintTrailerButton();
    paintVideos();
    settle();
    if (play && videos.length) playVideo(videos[0]);
  });
  tm.then(known => ratingOf(id, known, true)).then(age => {
    if (token !== titleToken) return;
    T.age = age;
    paintTitle();
    settle();
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
  // Blurred, the small poster looks as the full picture does, and it is here sooner.
  if (art) hero.append(picture(c.poster || art, 't-blur'));
  const backdrop = picture(null, 't-backdrop', () => hero.classList.add('has-backdrop'));
  backdrop.loading = 'lazy';
  // The page's largest picture on a phone, asked for ahead of the rest.
  const poster = artEl(c, art, 'first');
  poster.classList.add('t-poster');
  // A title opened before the page knew it (a shared link) shows its poster and name on
  // their way, until it loads (paintTitle).
  if (!art) poster.classList.add('skel');
  const name = el('h2', c.name || '', 't-name');
  name.id = 't-name';
  if (!c.name) name.append(skelIn('span', '', '9em'));
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
  const snapshot = button('round', '', () => saveTitleSnapshot(t), 'download');
  snapshot.setAttribute('aria-label', 'Save image');
  snapshot.title = 'Save image';
  snapshot.disabled = true;
  const compare = button('round', '', () => {
    try { go(comparisonURL(c.id, location.search)); }
    catch (error) { toast(error.message || 'This show could not be added. Try again.'); }
  }, 'compare');
  compare.setAttribute('aria-label', 'Add to compare');
  compare.title = 'Add to compare';
  // The round buttons keep to a line of their own on a phone, under Trailer and My List.
  const icons = el('div', '', 't-icons');
  icons.append(...(newer(c.id) ? [] : [rateGroup(c)]), share, snapshot, compare, out);
  // Trailer's place, until the title says whether it has one (paintTrailerButton).
  const trailer = el('span', '', 'btn skel trailer');
  trailer.setAttribute('aria-hidden', 'true');
  acts.append(trailer, listed, icons);
  const head = el('div', '', 't-head');
  head.append(name, acts);
  hero.append(backdrop, poster, el('div', '', 't-fade'), head);
  const main = el('div', '', 't-main');
  const side = el('div', '', 'facts');
  const body = el('div', '', 't-body');
  body.append(main, side);
  // The sections below stand in as they land, and go if the title has none of theirs.
  const episodes = el('section', '', 't-section');
  episodes.setAttribute('aria-label', 'Episodes');
  episodes.append(...episodesSkeleton());
  const videos = el('section', '', 't-section');
  videos.setAttribute('aria-label', 'Trailers and more');
  videos.append(...videosSkeleton());
  const more = el('section', '', 't-section');
  // A show newer than the catalogue has no shows like it until the nightly refresh (paintMore).
  more.hidden = newer(c.id);
  const moreH = el('h3', 'More like this');
  moreH.id = 't-more-h';
  more.setAttribute('aria-labelledby', moreH.id);
  const moreList = el('ul', '', 'more');
  for (let n = 0; n < 6; n++) moreList.append(moreSkeleton());
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
  about.append(skelIn('h3', '', '10em'), ...['70%', '45%', '60%', '38%', '52%'].map(w => skelIn('p', '', w)));
  $('t-sheet').replaceChildren(close, hero, body, episodes, videos, more, fans, about);
  // Where to watch, the season's episodes and the trailers start short (unfold); each part
  // remembers whether it was opened, so a repaint or another season keeps it so. The season
  // shown is kept (season) for its episodes to step through, and picked from its menu (pick).
  const t = { id: c.id, card: c, hero, backdrop, name, out, acts, listed, main, side, episodes, clips: videos, moreList,
              fans, fansSub, fansList, about, close, data: null, live: null, liveFailed: false, age: null, videos: null, error: '',
              eps: null, epsMore: null, clipList: null, clipsMore: null, pick: null, season: null, episodeSeason: null,
              episodeData: null, ratingsFailed: false,
              open: { watch: false, episodes: false, clips: false } };
  t.saveSnapshot = snapshot;
  t.snapshotReady = false;
  t.snapshotBusy = false;
  t.ratingSnapshotReady = ready => {
    t.snapshotReady = ready;
    snapshot.disabled = !canSaveTitleSnapshot(t) || t.snapshotBusy;
  };
  paintOut(t, c);
  mountTitleSections(t, { revealButton, paintReveal, unfold, busy, edges });
  for(const [page,section] of [['more',more],['fans',fans]]){
    const controls=filterBar(page,{genres:boot.genres,languages:boot.languages||[],compact:true,onChange:()=>{
      titleOf(t.id).then(data=>{if(T!==t)return;t.data=data;[...data.more,...(data.fans||[])].forEach(remember);paintMore();},e=>toast(e.message));
    }});
    section.querySelector('h3').after(controls.element);
  }
  return t;
}

function paintOut(t, s) {
  t.out.href = s.url || `https://www.tvmaze.com/shows/${s.id}`;
  t.out.setAttribute('aria-label', `${s.name || 'This show'} on TVmaze, opens in a new tab`);
}

// A title's page for this list, asked for once however many ask: a finger landing on a
// poster asks (prefetch), and opening it finds the answer on its way (post keeps it).
const titleOf = id => freshFields().then(fresh => post('/api/title', { ...taste(), ...fresh, id, matrix:matrixPreference(), recommendation_filters:{more:filtersFor('more'),fans:filtersFor('fans')} }));

// Where to watch on its way: its heading over a line of pills, as watchEl lays it out.
function watchSkeleton() {
  const box = el('div', '', 'watch');
  box.setAttribute('aria-hidden', 'true');
  const list = el('div', '', 'watch-list');
  list.append(el('span', '', 'watch-link skel'), el('span', '', 'watch-link skel'));
  const line = el('div', '', 'watch-line');
  line.append(list);
  box.append(skelIn('span', 'k', '7.5em'), line);
  return box;
}

// An episode on its way, as episodeEl lays one out: its still beside its name, date and summary.
function episodeSkeleton() {
  const li = el('li', '', 'ep');
  li.setAttribute('aria-hidden', 'true');
  const text = el('div');
  text.append(skelIn('h4', '', '58%'), skelIn('span', 'ep-date', '7em'), skelLines(3, 'p'));
  li.append(el('span', '', 'ep-num'), el('span', '', 'ep-still skel'), text);
  return li;
}

// A title's episodes on their way (paintEpisodes): the heading and season menu, the first
// few episodes of the season and the button for the rest.
function episodesSkeleton() {
  const head = el('div', '', 't-section-head');
  const pick = el('span', '', 'skel pick');
  pick.setAttribute('aria-hidden', 'true');
  head.append(el('h3', 'Episodes'), pick);
  const list = el('ol', '', 'eps');
  list.append(...Array.from({ length: SNIPPETS.episodes }, episodeSkeleton));
  const bar = el('div', '', 'reveal-bar');
  bar.setAttribute('aria-hidden', 'true');
  bar.append(el('span', '', 'reveal skel'));
  return [head, list, bar];
}

// Trailers on their way, as paintVideos lays them out folded: a row of thumbnails.
function videosSkeleton() {
  const list = el('ul', '', 'clips rail');
  list.setAttribute('aria-hidden', 'true');
  for (let n = 0; n < 4; n++) {
    const li = el('li');
    const clip = el('span', '', 'clip');
    clip.append(el('span', '', 'clip-thumb skel'), skelIn('b', '', '80%'), skelIn('small', '', '45%'));
    li.append(clip);
    list.append(li);
  }
  return [el('h3', 'Trailers & more'), list];
}

// A show like this one on its way, in the shape of its card (moreCard): the poster over its
// name, why it is here, its year beside My List, and a few lines of its summary.
function moreSkeleton() {
  const li = el('li', '', 'more-card skel-item');
  li.setAttribute('aria-hidden', 'true');
  const top = el('div', '', 'more-top');
  top.append(skelIn('div', 'more-info', '2.6em'), el('span', '', 'round skel'));
  const body = el('div', '', 'more-body');
  body.append(skelIn('h4', '', '75%'), skelIn('div', 'more-why', '60%'), top, skelLines(4, 'p'));
  li.append(el('span', '', 'art skel'), body);
  return li;
}

function paintTitle() {
  if (!T) return;
  const s = { ...T.card, ...(T.data?.show || {}) };
  const live = T.live;
  T.ratingSnapshotReady?.(T.snapshotReady);
  // Until the title is here, what it will say stands in, in its own shape.
  const waiting = !T.data && !T.error;
  if (s.name || !waiting) T.name.textContent = s.name || '';
  // An episode open over the page names the tab, and its way back names the show; a title
  // painting beneath someone's page leaves the tab named after them.
  if (E) nameEpisode();
  else if (!personId) document.title = `${s.name || 'Show'} · Couchside`;
  // A title opened before the page knew the show (a shared link) gets its poster once the
  // show has loaded, instead of keeping the blank tile it opened with.
  const art = s.art || s.poster;
  const poster = T.hero.querySelector('.t-poster');
  if (art && poster && !poster.dataset.src) {
    const shown = artEl(s, art, 'first');
    shown.classList.add('t-poster');
    poster.replaceWith(shown);
    if (!T.hero.querySelector('.t-blur')) T.hero.prepend(picture(s.poster || art, 't-blur'));
  } else if (!waiting) poster?.classList.remove('skel');
  // Once the title is here it says whether the show can be rated: not one newer than the
  // catalogue, while a page kept from before the nightly refresh may have taken a show it
  // brought in for one.
  if (T.data) {
    const rates = T.acts.querySelector('.rates');
    if (s.newer) rates?.remove();
    else if (!rates) T.acts.querySelector('.t-icons').prepend(rateGroup(s));
  }
  T.acts.querySelector('.rates')?.setAttribute('aria-label', `Rate ${s.name}`);
  paintOut(T, s);
  syncList(s.id);

  const meta = metaEl(s, live, false, T.age?.rating);
  if (waiting && !meta.childElementCount) meta.append(skelIn('span', '', '14em'));
  const main = [meta];
  if (s.because) {
    const why = el('p', `Because you ${s.because.loved ? 'loved' : 'liked'} ${s.because.name}`, 't-why');
    if (s.because.ties?.length) why.append(el('span', ` · ${joinNames(s.because.ties.slice(0, 3).map(tieText))}`));
    else if (s.because.shared?.length) why.append(el('span', ` · shares ${s.because.shared.join(', ').toLowerCase()}`));
    main.push(why);
    if (s.because.fits?.length) main.push(el('p', `Fits your taste for ${joinNames(s.because.fits.map(leaning))}.`, 't-fits'));
  } else if (s.newer) {
    main.push(el('p', 'Just added to TVmaze. It joins the catalogue in the nightly refresh, and then you can rate it '
      + 'and see shows like it.', 't-new'));
  } else if (waiting && state.profile.some(p => p.weight > 0) && rated(T.id) === undefined && !newer(T.id)) {
    // A title the list likes something near and has not rated says why it is here.
    main.push(skelIn('p', 't-why', '17em'));
  }
  const airing = live?.status === 'Running' ? airs(live.days) : '';
  if (airing) main.push(el('p', airing, 't-airs'));
  // Once the title has loaded, so TVmaze's channels never stand in for TMDB's services.
  const watch = waiting ? watchSkeleton() : watchEl(s, live, T.age, T.data?.tmdb);
  if (watch) main.push(watch);
  if (s.summary || T.data) main.push(el('p', s.summary || 'TVmaze has no summary for this show yet.', 't-summary'));
  else if (T.error) main.push(el('p', T.error, 't-summary muted'));
  // A show's summary runs about six lines of a wide sheet and eight of a phone's.
  else main.push(skelLines(wide() ? 6 : 8, 'p', 't-summary'));
  T.main.replaceChildren(...main);
  if (watch && !waiting) fitWatch(watch);

  // The cast comes with TVmaze's details, after the title, and has its line kept till then.
  T.side.replaceChildren(...[
    live || T.liveFailed ? castFact(live?.cast || []) : skelIn('p', '', '90%'),
    fact('Genres', s.genres?.join(', ')),
    fact('This show is about', s.themes?.slice(0, 4).join(', ').toLowerCase()),
    fact('On', s.channel),
  ].filter(Boolean));

  if (!T.data && !live) {
    // A title that could not be had has no shows like it or facts about it to wait for.
    if (T.error) {
      T.moreList.closest('section').hidden = true;
      T.about.replaceChildren();
    }
    return;
  }
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
  T.sectionsUpdate?.();
}

// Where to watch: TMDB's services with their own logos, linking to TMDB's page for the
// show and credited to JustWatch; without them, where TVmaze says it streams or airs and
// Apple TV when iTunes sells it, each with the service's own small icon. They keep to
// one line that scrolls sideways, and a caret at its end lays them all out.
function watchEl(s, live, age, tm) {
  const { links, credit } = whereToWatch(s.name, tm, live?.site, live?.channels, age?.apple);
  if (!links.length) return null;
  const box = el('div', '', 'watch');
  box.append(el('span', 'Where to watch', 'k'));
  const list = el('div', '', 'watch-list');
  list.id = 't-watch';
  list.addEventListener('scroll', () => edges(list), { passive: true });
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

// Whether the services run past one line, measured on the page: when they do, the caret
// shows, and until it is pressed the line scrolls sideways, every service a swipe or a
// Tab away.
function fitWatch(box) {
  const list = box.querySelector('.watch-list'), more = box.querySelector('.watch-more');
  // A resize can arrive while this row still contains its loading placeholders.
  if (!list || !more) return;
  box.classList.remove('open', 'clipped');
  more.hidden = true;
  if (list.scrollWidth > list.clientWidth + 1) {
    box.classList.add('clipped');
    more.hidden = false;
  }
  setWatch(box, T.open.watch);
}
function setWatch(box, open) {
  const clipped = box.classList.contains('clipped');
  const list = box.querySelector('.watch-list');
  // Opened or closed, the line starts again from its first service; a resize, which a
  // phone's toolbar makes as the page scrolls, leaves it where it was swiped to.
  const turned = box.classList.contains('open') !== (clipped && open);
  box.classList.toggle('open', clipped && open);
  if (turned) list.scrollLeft = 0;
  const more = box.querySelector('.watch-more');
  more.setAttribute('aria-expanded', String(clipped && open));
  more.title = open ? 'Show fewer' : 'Show all';
  edges(list);
}
// A line that scrolls sideways fades out at each end with more past it.
function edges(list) {
  const left = list.scrollLeft;
  list.classList.toggle('more-before', left > 1);
  list.classList.toggle('more-after', left + list.clientWidth < list.scrollWidth - 1);
}
window.addEventListener('resize', () => requestAnimationFrame(() => {
  const box = T?.main.querySelector('.watch');
  if (box && !busy(box.querySelector('.watch-list'))) fitWatch(box);
  if (T?.clipList && !busy(T.clipList)) setClips(T.open.clips);
}));

// A long part of a title page, an episode or a person's page opens with a button that
// closes it again (aria-expanded, with a caret that turns). Opening runs the part's height
// up from what it was, so what is below slides down; closing runs it back, and when the
// button sits below the part the sheet moves with it, so the button stays under the
// finger. Quick, and at once under reduced motion.
const REVEAL = 220;
const easeOut = k => 1 - (1 - k) ** 3;
const busy = box => box.classList.contains('sizing');
function unfold(box, set, open, anchor = null) {
  // A hidden page runs no animations, so one begun there would hold the part half open.
  const still = !motion() || document.hidden;
  const page = box.closest('dialog');
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
    // A sheet closed meanwhile, or drawn again, has nothing left to close.
    if (!box.isConnected || !page.open || closing(page)) {
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

// The trailers in one row that scrolls sideways, and a button that lays them all out, so
// More like this is not far below.
function paintVideos() {
  if (!T.videos.length) {
    T.clips.hidden = true;
    return;
  }
  const list = el('ul', '', 'clips');
  list.id = 't-clips';
  list.addEventListener('scroll', () => edges(list), { passive: true });
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
// More trailers than two on a phone or three on a wide screen keep to one row, which
// scrolls sideways to the rest with the next one peeking in, until Show all lays every
// one out, two or three to a line.
function setClips(open) {
  const items = [...T.clipList.children];
  const shown = snippet(items.length, wide() ? SNIPPETS.clipsWide : SNIPPETS.clips);
  const rail = !open && shown < items.length;
  const turned = T.clipList.classList.contains('rail') !== rail;
  T.clipList.classList.toggle('rail', rail);
  if (turned) T.clipList.scrollLeft = 0;
  T.clipsMore.parentElement.hidden = shown === items.length;
  paintReveal(T.clipsMore, revealLabel('clips', items.length, open), open);
  edges(T.clipList);
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
  const params = new URLSearchParams({show: String(s.id)}), current = new URLSearchParams(location.search);
  for (const key of ['rating-view', 'rating-season', 'rating-inverted']) {
    if (current.has(key)) params.set(key, current.get(key));
  }
  await shareLink(`${location.origin}/?${params}`, `${s.name} on Couchside`, `${s.name}${s.year ? ` (${s.year})` : ''}`,
    'Link copied. It opens straight to this show.');
}
async function saveRatingSnapshot(model) {
  const frozen = structuredClone(model);
  const { downloadRatingSnapshot } = await import('./rating-snapshots.js');
  const result = await downloadRatingSnapshot(frozen);
  toast(result.pages.length > 1 ? 'Images saved together in one ZIP.' : 'Image saved.');
  return result;
}
function canSaveTitleSnapshot(t) {
  return t.snapshotReady && Boolean(t.data?.show?.name || t.card?.name)
    && Boolean(t.data || t.card?.art || t.card?.poster);
}
async function saveTitleSnapshot(t) {
  if (!t.ratingSnapshot || t.saveSnapshot.disabled) return;
  const model = t.ratingSnapshot();
  t.snapshotBusy = true;
  t.saveSnapshot.disabled = true;
  t.saveSnapshot.setAttribute('aria-busy', 'true');
  toast('Preparing your image…');
  try { await saveRatingSnapshot(model); }
  catch (error) { toast(error.message || 'The image could not be saved. Try again.', 8000); }
  finally {
    t.snapshotBusy = false;
    t.saveSnapshot.removeAttribute('aria-busy');
    t.saveSnapshot.disabled = !canSaveTitleSnapshot(t);
  }
}
// The phone's own share sheet where there is one, and the clipboard elsewhere.
async function shareLink(url, title, text, copied) {
  if (navigator.share) {
    try {
      await navigator.share({ title, text, url });
    } catch { /* closed without sharing */ }
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    toast(copied);
  } catch {
    toast(`Copy this link to share it: ${url}`);
  }
}

// The cast under About, each with their own page when TVmaze gives their id.
function castEl(cast) {
  const list = el('ul', '', 'cast');
  for (const p of cast) {
    const li = el('li');
    const face = el('span', '', 'face');
    if (p.photo) {
      const img = picture(null);
      img.loading = 'lazy';
      img.src = p.photo;
      face.append(img);
    }
    const who = p.id ? personLink(p, 'who') : el('span', '', 'who');
    // The space keeps the name and the part apart when the link is read out.
    who.append(face, el('b', p.name), document.createTextNode(p.character ? ` as ${p.character}` : ''));
    li.append(who);
    list.append(li);
  }
  return list;
}

// "Cast: A, B, C and more" near the top of a title page: each name opens their page, and
// "more" goes down to the whole cast under About.
function castFact(cast) {
  if (!cast.length) return null;
  const names = cast.slice(0, 3).map(c => {
    if (!c.id) return document.createTextNode(c.name);
    const a = personLink(c, 'name-link');
    a.textContent = c.name;
    return a;
  });
  if (cast.length > 3) {
    const more = button('name-link', 'more', () => {
      const list = T?.about.querySelector('.cast');
      if (!list) return;
      list.scrollIntoView({ behavior: motion() ? 'smooth' : 'auto', block: 'start' });
      list.querySelector('a')?.focus({ preventScroll: true });
    });
    more.setAttribute('aria-label', 'More of the cast');
    names.push(more);
  }
  const p = el('p');
  p.append(el('span', 'Cast: ', 'k'));
  names.forEach((name, n) => p.append(...(n ? [n === names.length - 1 ? ' and ' : ', '] : []), name));
  return p;
}

function paintMore() {
  const items = T.data.more;
  // A show newer than the catalogue has none until the nightly refresh brings it in.
  T.moreList.closest('section').hidden = !!T.data.show?.newer;
  T.moreList.replaceChildren(...(items.length ? items.map(moreCard)
    : [el('li', 'Nothing in the catalogue sits close enough to this one.', 'muted')]));
  // The server sends none when fewer than four qualify, and the section stays hidden.
  const fans = T.data.fans || [];
  const name = T.data.show?.name || T.card.name;
  T.fansSub.textContent = name ? `Shows that ${name} fans also look up` : 'Shows its fans also look up';
  T.fansList.replaceChildren(...fans.map(moreCard));
  T.fans.hidden = !fans.length&&!filterKey('fans');
  if(!fans.length&&filterKey('fans'))T.fansList.append(el('li','No recommendations match these filters.','muted'));
  T.sectionsUpdate?.();
}
// A show like this one: how similar it is to this title, in the green a match wears, and
// why it is here (the same world, the same creator). Never a match: how close a show sits
// to this title says nothing of how well it fits a list, so it reads "% similar".
function moreCard(c) {
  const li = el('li', '', 'ratings-related-card');
  li.append(cardEl(c, { related: true, note: [c.similar ? `${c.similar}% similar` : '', c.why].filter(Boolean).join(' · ') }));
  return li;
}

function paintEpisodes(painted = () => {}) {
  if (T.eps || (!T.episodeData && !T.ratingsFailed)) return;
  const saved = T.episodeData;
  const list = saved?.episodes.length ? ratingSeasons(saved).map(number => {
    const first = saved.episodes.find(e => e.season === number);
    return {number, year: Number(first.airdate?.slice(0, 4)) || null};
  }) : T.live?.seasons;
  if (!list) {
    if (T.liveFailed) T.episodes.hidden = true;
    return;
  }
  if (!list.length) {
    T.episodes.hidden = true;
    return;
  }
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
  // A page opened under one of its episodes starts at that episode's season (syncSeason).
  const first = list.find(s => s.number === T.episodeSeason) || list[0];
  if (pick) pick.value = String(first.number);
  T.pick = pick;
  T.eps = el('ol', '', 'eps');
  T.eps.id = 't-eps';
  T.epsMore = revealButton(T.eps, () => {
    if (busy(T.eps)) return;
    T.open.episodes = !T.open.episodes;
    unfold(T.eps, setEpisodes, T.open.episodes, T.epsMore);
  });
  T.episodes.replaceChildren(head, T.eps, T.epsMore.parentElement);
  T.episodes.hidden = false;
  const t = T;
  const mount = async () => {
    if (T !== t) return;
    await mountEpisodeRatings(t, { openEpisode, episodeEl, revealButton, paintReveal, unfold, busy, snippet, revealLabel }, saved);
    if (T === t) painted();
  };
  if (saved?.episodes.length) {
    t.season = { show: t.id, number: first.number, episodes: saved.episodes.filter(e => e.season === first.number).map(e => ({ ...e, still: e.image })) };
    mount();
  } else loadSeason(first.number).then(mount);
}

// A season shows its first few episodes until they are all asked for, and every season
// after that shows whole until they are closed again.
function setEpisodes(open) {
  const items = [...T.eps.children];
  const shown = snippet(items.length, SNIPPETS.episodes);
  items.forEach((li, n) => { li.hidden = !open && n >= shown; });
  T.epsMore.parentElement.hidden = shown === items.length;
  paintReveal(T.epsMore, revealLabel('episodes', items.length, open), open);
  T.ratingsUpdate?.();
}

async function loadSeason(number) {
  const token = ++seasonToken, t = T;
  t.season = null;
  t.eps.replaceChildren(...Array.from({ length: SNIPPETS.episodes }, episodeSkeleton));
  setEpisodes(t.open.episodes);
  try {
    const cached = cachedRatings(t.id);
    const { episodes } = cached ? { episodes: cached.episodes.filter(ep => ep.season === number)
      .map(ep => ({ ...ep, still: ep.image })) } : await patient(`/api/episodes?id=${t.id}&season=${number}`);
    if (token !== seasonToken || T !== t) return;
    // Kept with its show, for an episode opened from it to step through the season.
    t.season = { show: t.id, number, episodes };
    t.eps.replaceChildren(...(episodes.length ? episodes.map(ep => episodeEl(ep, t.season))
      : [el('li', 'No episodes are listed for this season yet.', 'muted')]));
  } catch (e) {
    if (token !== seasonToken || T !== t) return;
    t.eps.replaceChildren(el('li', e.message, 'muted'));
  }
  setEpisodes(t.open.episodes);
}

// An episode in its season's list. One with an id opens in full (openEpisode): its name is
// a link to the episode's own address, stretched over the whole row, so the row is one
// tap or click, the link reads out as the episode, and a new tab or a copied link works.
function episodeEl(ep, season) {
  const li = el('li', '', 'ep');
  const num = el('span', ep.number ?? '', 'ep-num');
  li.append(num);
  const still = el('span', '', 'ep-still');
  if (ep.still) {
    const img = picture(null);
    img.loading = 'lazy';
    img.src = ep.still;
    still.append(img);
  }
  const text = el('div');
  const name = ep.number ? ep.name : `Special: ${ep.name}`;
  const h = el('h4');
  if (Number.isInteger(ep.id)) {
    const a = el('a', name, 'ep-open');
    a.href = `/?show=${season.show}&episode=${ep.id}`;
    // The number is read out with the name rather than before it.
    a.setAttribute('aria-label', ep.number ? `Episode ${ep.number}: ${ep.name}` : name);
    num.setAttribute('aria-hidden', 'true');
    a.addEventListener('click', e => {
      if (!plainClick(e)) return;
      e.preventDefault();
      openEpisode(ep, season, a);
    });
    h.append(a);
    li.classList.add('opens');
  } else h.append(name);
  if (ep.runtime) h.append(el('span', runtime(ep.runtime)));
  text.append(h);
  if (ep.airdate) text.append(el('span', longDate(ep.airdate), 'ep-date'));
  if (ep.summary) text.append(el('p', ep.summary));
  li.append(still, text);
  return li;
}

/* ------------------------------------------------------------- an episode */
// An episode opens in a sheet of its own over its title page, which waits beneath it just
// as it was left, scrolled where it was with its season chosen; closing the sheet, by its
// back button, Back, Escape or a swipe down, uncovers it again. The sheet shows at once
// what the season's list knew (the still, name, date and runtime) and fills in the rest
// from TVmaze: the largest still, the whole summary, the rating, who directed and wrote
// it, and the guest stars. Previous and Next step through the season in the same sheet,
// replacing the address, so Back still returns to the title page. The address carries
// the episode beside its show (?show=169&episode=12203), so a reload or a shared link
// opens it again over its title page.
let E = null, episodeId = null, episodeToken = 0, episodeFrom = null;
const showName = () => (T ? { ...T.card, ...(T.data?.show || {}) }.name || '' : '');

function openEpisode(ep, season, from) {
  if (!T) return;
  engaged(T.id);
  history.pushState({ modal: true, episode: true }, '', withEpisode(location.pathname, location.search, ep.id));
  showEpisode(ep.id, { card: { ...ep, season: season.number }, season, from });
}
function stepEpisode(ep, way) {
  if (!E?.season) return;
  history.replaceState(history.state, '', withEpisode(location.pathname, location.search, ep.id));
  showEpisode(ep.id, { card: { ...ep, season: E.season.number }, season: E.season, from: E.from, way });
}
function closeEpisode() {
  if (history.state?.episode) history.back();
  else {
    history.replaceState(history.state, '', withEpisode(location.pathname, location.search, null));
    hideEpisode();
  }
}
function hideEpisode() {
  episodeToken++;
  episodeId = null;
  episodeFrom = E?.from || null;
  E = null;
  // Escape can close the sheet before Back gets here, since a browser stops a page holding
  // a sheet open with Escape; then it is settled now rather than once it closes.
  if ($('episode').open) $('episode').close(); else settleEpisode();
  if (T) document.title = `${showName() || 'Show'} · Couchside`;
}
// The sheet is emptied once it has closed, unless an episode opened again meanwhile, and
// the focus goes back to the episode in the list it was opened from.
function settleEpisode() {
  $('e-sheet').replaceChildren();
  $('e-sheet').removeAttribute('aria-busy');
  if (titleId && episodeFrom?.isConnected && !episodeFrom.closest('[hidden]')) episodeFrom.focus({ preventScroll: true });
  episodeFrom = null;
}
$('episode').addEventListener('close', () => { if (!episodeId) settleEpisode(); });
$('episode').addEventListener('cancel', e => { e.preventDefault(); closeEpisode(); });
$('episode').addEventListener('click', e => { if (e.target === $('episode')) closeEpisode(); });
// The left and right arrows step through the season, as Previous and Next do.
$('episode').addEventListener('keydown', e => {
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || !E) return;
  const way = { ArrowLeft: 'prev', ArrowRight: 'next' }[e.key];
  const step = way && E.steps.querySelector(`[data-step="${way}"]`);
  if (!step) return;
  e.preventDefault();
  step.click();
});

function showEpisode(id, { card = null, season = null, from = null, way = '' } = {}) {
  if (!titleId) return;
  const token = ++episodeToken;
  // Every guest star shows for each episode after, once asked for, until they are closed.
  const open = E?.open || { guests: false };
  episodeId = id;
  E = buildEpisode({ id, show: titleId, card, season, from, open });
  const dialog = $('episode');
  const opening = !dialog.open || closing(dialog);
  if (opening) dialog.showModal();
  dialog.scrollTop = 0;
  paintEpisode();
  if (opening) E.back.focus({ preventScroll: true });
  else {
    // A step lands on the new episode's name, read out as the page it now is, and the
    // page slides in from the side it was stepped to.
    E.name.focus({ preventScroll: true });
    if (way && motion()) {
      E.page.animate([{ opacity: 0, transform: `translateX(${way === 'next' ? 28 : -28}px)` }, { opacity: 1, transform: 'none' }],
        { duration: 240, easing: 'cubic-bezier(.22,1,.36,1)' });
    }
  }
  loadEpisode(token);
}

function buildEpisode(e) {
  const back = button('e-back', '', closeEpisode, 'left');
  const backName = el('span', '', 'e-back-name');
  back.append(backName);
  const hero = el('div', '', 'e-hero');
  hero.style.setProperty('--h', String(hue(e.show)));
  // The still the season's list showed comes at once, and the largest TVmaze keeps fades
  // in over it.
  const still = picture(null, 'e-still', () => hero.classList.add('has-still'));
  const image = picture(null, 'e-image', () => hero.classList.add('has-image'));
  hero.append(still, image, el('div', '', 'e-fade'));
  const code = el('p', '', 'e-code');
  const name = el('h2', '', 'e-name');
  name.id = 'e-name';
  name.tabIndex = -1;
  const meta = el('p', '', 'e-meta dot-list');
  const share = button('round small', '', shareEpisode, 'share');
  share.setAttribute('aria-label', 'Share this episode');
  share.title = 'Share';
  const words = el('div', '', 'e-words');
  words.append(code, name, meta);
  const head = el('div', '', 'e-head');
  head.append(words, share);
  const summary = el('div', '', 'e-summary');
  const note = el('div', '', 'e-note');
  const crew = el('div', '', 'e-crew');
  const guests = el('section', '', 'e-guests');
  const guestsH = el('h3', 'Guest stars');
  guestsH.id = 'e-guests-h';
  guests.setAttribute('aria-labelledby', guestsH.id);
  const guestList = el('ul', '', 'cast');
  guestList.id = 'e-guest-list';
  const guestsMore = revealButton(guestList, () => {
    if (!E || busy(guestList)) return;
    E.open.guests = !E.open.guests;
    unfold(guestList, setGuests, E.open.guests, E.guestsMore);
  });
  guests.append(guestsH, guestList, guestsMore.parentElement);
  const steps = el('nav', '', 'e-steps');
  const body = el('div', '', 'e-body');
  body.append(summary, note, crew, guests, steps);
  const page = el('div', '', 'e-page');
  page.append(hero, head, body);
  $('e-sheet').replaceChildren(back, page);
  return { ...e, back, backName, page, hero, still, image, code, name, meta, share, summary, note, crew, guests, guestList,
           guestsMore, steps, detail: null, error: '', retry: false };
}

// What is known so far: the list's own line for the episode at first, then TVmaze's whole
// answer, with skeletons standing in for what is still on its way.
function paintEpisode() {
  const e = E;
  if (!e) return;
  const ep = { ...e.card, ...e.detail };
  const waiting = !e.detail && !e.error;
  if (waiting) $('e-sheet').setAttribute('aria-busy', 'true'); else $('e-sheet').removeAttribute('aria-busy');
  nameEpisode();
  if (ep.still && !e.still.getAttribute('src')) e.still.src = ep.still;
  // Without a still of its own, the show's backdrop stands in.
  const art = ep.image || (e.detail ? T?.data?.tmdb?.backdrop || T?.live?.backdrop : null);
  if (art && art !== ep.still && !e.image.getAttribute('src')) e.image.src = art;
  e.hero.classList.toggle('loading', waiting && !ep.still);

  if (ep.name) {
    const code = el('span', episodeCode(ep.season, ep.number));
    code.setAttribute('aria-hidden', 'true');
    e.code.replaceChildren(code, el('span', episodeSaid(ep.season, ep.number), 'sr'));
    e.name.textContent = ep.name;
  } else if (waiting) {
    e.code.replaceChildren(skelIn('span', '', '3.4em'));
    e.name.replaceChildren(skelIn('span', '', '62%'));
  } else {
    e.code.replaceChildren();
    e.name.textContent = 'Episode';
  }
  e.meta.replaceChildren(...[airing(ep.airdate, ep.airstamp), ep.runtime ? runtime(ep.runtime) : '']
    .filter(Boolean).map(fact => el('span', fact)));
  if (ep.rating) e.meta.append(ratingEl(ep.rating, ep.rating_source));
  else if (waiting && !ep.name) e.meta.append(skelIn('span', '', '11em'));
  e.share.hidden = !ep.name;

  // A summary is a few sentences: about three lines of a wide sheet and five of a phone's.
  const said = ep.summary ? el('p', ep.summary)
    : waiting ? skelLines(wide() ? 3 : 5, 'p') : e.detail ? el('p', 'TVmaze has no summary for this episode yet.', 'muted') : null;
  e.summary.replaceChildren(...(said ? [said] : []));
  e.note.replaceChildren();
  if (e.error) {
    e.note.append(el('p', e.error, 'muted'));
    if (e.retry) {
      e.note.append(button('btn ghost', 'Try again', () => {
        if (!E) return;
        E.error = '';
        paintEpisode();
        loadEpisode(episodeToken);
      }));
    }
  }

  const made = e.detail ? credits(e.detail.crew) : [];
  // Who directed it and who wrote it, a line each, while they are on their way.
  e.crew.replaceChildren(...(waiting ? [skelIn('p', '', '46%'), skelIn('p', '', '40%')] : made.map(creditEl)));
  e.crew.hidden = !waiting && !made.length;

  const guests = e.detail?.guests || [];
  e.guests.hidden = !waiting && !guests.length;
  if (waiting) {
    // Faces, each over a name and a part.
    e.guestList.replaceChildren(...Array.from({ length: 6 }, () => {
      const li = el('li', '', 'skel-item');
      li.setAttribute('aria-hidden', 'true');
      li.append(el('span', '', 'face skel'), skelIn('b', '', '75%'), skelIn('span', '', '55%'));
      return li;
    }));
    e.guestsMore.parentElement.hidden = true;
  } else {
    e.guestList.replaceChildren(...guests.map(guestEl));
    setGuests(e.open.guests);
  }
  paintSteps();
}

// The tab and the way back name the episode and its show, once they are known.
function nameEpisode() {
  if (!E) return;
  const show = showName();
  const ep = { ...E.card, ...E.detail };
  E.backName.textContent = show || 'Back';
  E.back.setAttribute('aria-label', show ? `Back to ${show}` : 'Back');
  // Someone's page opened from its guest stars keeps the tab named after them.
  if (!personId) document.title = [ep.name, show || 'Show', 'Couchside'].filter(Boolean).join(' · ');
}

// TVmaze's rating in the meta line, where the dots between facts fall only between spans.
function ratingEl(rating, source = 'TVmaze') {
  const span = el('span', '', 'e-rating');
  span.title = `Rating on ${source}`;
  span.append(icon('star'), el('b', rating.toFixed(1)), el('span', ` out of 10 on ${source}`, 'sr'));
  return span;
}

// Guest stars and crew each carry their TVmaze person id (data-person), for a person's own
// page to open from.
// A guest star or a name in the credits opens their page, as a link, so it can also open
// in a tab of its own (personLink).
const personEl = (p, cls) => personLink(p, `e-person ${cls}`);
function creditEl({ label, people }) {
  const line = el('p');
  line.append(el('span', `${label} `, 'k'));
  people.forEach((p, n) => {
    if (n) line.append(n === people.length - 1 ? ' and ' : ', ');
    const name = personEl(p, 'e-credit');
    name.textContent = p.name;
    line.append(name);
  });
  return line;
}
// A guest star's face, name and part, as the title page's cast shows them.
function guestEl(p) {
  const li = el('li');
  const b = personEl(p, 'e-guest');
  const face = el('span', '', 'face');
  if (p.photo) {
    const img = picture(null);
    img.loading = 'lazy';
    img.src = p.photo;
    face.append(img);
  }
  b.append(face, el('b', p.name));
  if (p.character) b.append(el('span', `as ${p.character}`));
  li.append(b);
  return li;
}
// An episode's guest stars start with the first twelve until they are all asked for.
function setGuests(open) {
  const items = [...E.guestList.children];
  const shown = snippet(items.length, SNIPPETS.guests);
  items.forEach((li, n) => { li.hidden = !open && n >= shown; });
  E.guestsMore.parentElement.hidden = shown === items.length;
  paintReveal(E.guestsMore, revealLabel('guests', items.length, open), open);
}

// Previous and Next, for reading through the season: each with its still and name.
function paintSteps() {
  const e = E;
  const { prev, next } = neighbours(e.season?.episodes, e.id);
  e.steps.hidden = !prev && !next;
  if (e.season) e.steps.setAttribute('aria-label', `Season ${e.season.number}`);
  e.steps.replaceChildren(...[prev && stepEl(prev, 'prev'), next && stepEl(next, 'next')].filter(Boolean));
}
function stepEl(ep, way) {
  const said = way === 'prev' ? 'Previous' : 'Next';
  const a = el('a', '', `e-step ${way}`);
  a.href = `/?show=${E.show}&episode=${ep.id}`;
  a.dataset.step = way;
  a.setAttribute('aria-label', `${said}, ${episodeSaid(null, ep.number).toLowerCase()}: ${ep.name}`);
  const thumb = el('span', '', 'e-step-still');
  if (ep.still) {
    const img = picture(null);
    img.loading = 'lazy';
    img.src = ep.still;
    thumb.append(img);
  }
  const small = el('small');
  small.append(...(way === 'prev' ? [icon('left'), said] : [said, icon('right')]));
  const words = el('span', '', 'e-step-words');
  words.append(small, el('b', `${episodeCode(null, ep.number)} · ${ep.name}`));
  a.append(thumb, words);
  a.addEventListener('click', e => {
    if (!plainClick(e)) return;
    e.preventDefault();
    stepEpisode(ep, way);
  });
  return a;
}

async function loadEpisode(token) {
  const e = E;
  try {
    const { episode } = await patient(`/api/episode?id=${e.id}`);
    if (token !== episodeToken) return;
    // An address can pair an episode with another show; the episode is shown only over its own.
    if (episode.show !== e.show) e.error = 'That episode belongs to another show.';
    else {
      e.detail = episode;
      syncSeason(episode.season);
      if (e.season?.number !== episode.season) loadSteps(token, episode.season);
    }
  } catch (err) {
    if (token !== episodeToken) return;
    e.error = err.message;
    e.retry = err.status !== 404;
  }
  paintEpisode();
}

// The season an episode opened from its address steps through: the title page's own list
// when it shows that season, else the same list asked for here.
async function loadSteps(token, number) {
  if (!Number.isInteger(number)) return;
  const e = E;
  if (T?.season?.show === e.show && T.season.number === number) {
    e.season = T.season;
    paintSteps();
    return;
  }
  try {
    const { episodes } = await patient(`/api/episodes?id=${e.show}&season=${number}`);
    if (token !== episodeToken) return;
    e.season = { show: e.show, number, episodes };
    paintSteps();
  } catch { /* no steps, and the episode itself is still there */ }
}

// A title page opened under one of its episodes, as the episode's address opens it, shows
// that episode's season, so closing the episode uncovers the season it belongs to.
function syncSeason(number) {
  if (!T || !Number.isInteger(number)) return;
  T.episodeSeason = number;
  const pick = T.pick;
  if (!pick || pick.value === String(number) || ![...pick.options].some(o => o.value === String(number))) return;
  pick.value = String(number);
  loadSeason(number);
}

async function shareEpisode() {
  if (!E) return;
  const ep = { ...E.card, ...E.detail };
  const show = showName();
  await shareLink(`${location.origin}/?show=${E.show}&episode=${E.id}`, `${ep.name} · ${show} on Couchside`,
    `${show} ${episodeCode(ep.season, ep.number)}: ${ep.name}`, 'Link copied. It opens straight to this episode.');
}

/* ------------------------------------------------------------ a person's page */
// Anyone in a cast has a page of their own: who they are, from TVmaze, with a biography
// from Wikipedia and a birthplace from Wikidata (people.py), and the shows they are in,
// each one the catalogue holds opening its own title page. It is a sheet over the title
// page it was opened from, which stays as it was beneath, and it lives in the address
// beside that title (?show=169&person=14245), so it reloads and shares, Back goes to the
// title, and Back from a title opened on it comes back to them. openPerson(id) opens
// someone from anywhere, and personLink(p) makes a link that does.
let P = null, personId = null, personToken = 0;
// The name and photo of everyone a cast has shown, for their page to open with.
const faces = new Map();
const LICENSE = 'https://creativecommons.org/licenses/by-sa/4.0/';
const personOf = id => patient(`/api/person?id=${id}`);
// A biography that cannot be had reads as none, and is asked for again next time.
const biographyOf = id => patient(`/api/biography?id=${id}`).then(r => r.biography).catch(() => null);

function openPerson(id) {
  const url = withPerson(location.pathname, location.search, id);
  if (personId) history.replaceState(history.state, '', url);
  else history.pushState({ modal: true }, '', url);
  showPerson(id);
}
function closePerson() {
  if (history.state?.modal) {
    keepPlace();
    history.back();
  } else {
    history.replaceState(null, '', withPerson(location.pathname, location.search, null));
    hidePerson();
  }
}
// `now` closes the sheet at once, for a title opened from it that is already in its place.
function hidePerson(now = false) {
  personToken++;
  personId = null;
  P = null;
  const dialog = $('person');
  if (dialog.open) {
    if (now) HTMLDialogElement.prototype.close.call(dialog);
    else dialog.close();
  }
  modalOpen();
  if (E) nameEpisode();
  else document.title = T ? `${T.name.textContent || 'Show'} · Couchside` : TITLES[view] || 'Couchside';
}
$('person').addEventListener('close', () => { if (!personId) $('p-sheet').replaceChildren(); });
$('person').addEventListener('cancel', e => { e.preventDefault(); closePerson(); });
$('person').addEventListener('click', e => { if (e.target === $('person')) closePerson(); });

// A link to someone's page. Its address keeps whatever is open, so a new tab shows the same
// title with them over it; a plain click opens them here.
function personLink(p, cls) {
  const a = el('a', '', cls);
  a.href = withPerson(location.pathname, location.search, p.id);
  a.dataset.person = String(p.id);
  faces.set(p.id, { id: p.id, name: p.name || '', photo: p.photo || null });
  return a;
}
document.addEventListener('click', e => {
  const a = e.target.closest('a[data-person]');
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  openPerson(Number(a.dataset.person));
});

function showPerson(id, place = null) {
  const token = ++personToken;
  personId = id;
  P = buildPerson(faces.get(id) || { id, name: '', photo: null });
  if (place?.open) Object.assign(P.open, place.open);
  const dialog = $('person');
  if (!dialog.open || closing(dialog)) dialog.showModal();
  modalOpen();
  dialog.scrollTop = 0;
  const settle = returnTo(dialog, place, () => token === personToken);
  P.close.focus({ preventScroll: true });
  document.title = P.who.name ? `${P.who.name} · Couchside` : 'Couchside';
  personOf(id).then(data => {
    if (token !== personToken) return;
    for (const c of [...data.roles, ...data.appearances, ...data.crew]) if (c.show) remember(c.show);
    P.data = data;
    paintPerson();
    settle();
    // The server began the lookup as it answered, so this is seldom long behind.
    biographyOf(id).then(bio => {
      if (token !== personToken) return;
      P.bio = bio;
      paintAbout();
      settle();
    });
  }, e => {
    if (token !== personToken) return;
    P.error = e;
    paintPerson();
  });
}

function buildPerson(who) {
  const close = button('icon-btn t-close', '', closePerson, 'close');
  close.setAttribute('aria-label', 'Close');
  const hero = el('div', '', 't-hero p-hero');
  const name = el('h2', who.name, 't-name');
  name.id = 'p-name';
  // Someone opened before the page knew them (a shared link) has their name on its way.
  if (!who.name) name.append(skelIn('span', '', '8em'));
  // Wikipedia's few words on them, "American actor (born 1956)", once they come, and their
  // place kept until then.
  const said = el('p', '', 'p-said');
  said.append(skelIn('span', '', '12em'));
  const shared = button('round', '', sharePerson, 'share');
  shared.setAttribute('aria-label', 'Share');
  shared.title = 'Share';
  const acts = el('div', '', 't-acts');
  acts.append(shared);
  const head = el('div', '', 't-head');
  head.append(name, said, acts);
  hero.append(el('div', '', 't-fade'), head);
  paintPhoto(hero, who, true);
  const main = el('div', '', 't-main');
  main.append(...bioSkeleton());
  // What is known of them: when and where they were born, their age, what they are known for
  // and what they created, the longer ones two lines.
  const side = el('div', '', 'facts');
  side.append(skelIn('p', '', '100%', '45%'), skelIn('p', '', '28%'), skelIn('p', '', '100%', '40%'),
    skelIn('p', '', '100%', '30%'));
  const body = el('div', '', 't-body p-body');
  body.append(main, side);
  const parts = {};
  for (const [part, title] of [['roles', 'TV shows'], ['appearances', 'As themselves'], ['crew', 'Behind the camera']]) {
    const box = el('section', '', 't-section');
    const h = el('h3', title);
    h.id = `p-${part}-h`;
    box.setAttribute('aria-labelledby', h.id);
    const grid = el('ul', '', 'grid p-grid');
    grid.id = `p-${part}`;
    box.append(h, grid);
    box.hidden = part !== 'roles';
    parts[part] = { box, h, grid, more: null };
  }
  // Their shows on their way, each poster with whom they played and when beneath it.
  parts.roles.grid.append(...Array.from({ length: 6 }, () => {
    const li = el('li', '', 'skel-item');
    li.setAttribute('aria-hidden', 'true');
    const caption = el('span', '', 'grid-caption p-caption');
    caption.append(skelIn('span', 'p-as', '70%'), skelIn('span', 'p-when', '50%'));
    li.append(skelCard(), caption);
    return li;
  }));
  const links = el('p', '', 'links-row');
  const foot = el('section', '', 't-section about');
  foot.hidden = true;
  foot.append(links);
  $('p-sheet').replaceChildren(close, hero, body, parts.roles.box, parts.appearances.box, parts.crew.box, foot);
  const controls=filterBar('person',{genres:boot.genres,languages:boot.languages||[],search:true,compact:true,
    extra:[{name:'credit-role',label:'Credit type',get:()=>P?.id===who.id?P.creditRole||'':'',
      options:[['','All credits'],['roles','TV roles'],['appearances','As themselves'],['crew','Behind the camera']],
      apply:value=>{if(P?.id===who.id)P.creditRole=value;}}],onChange:query=>{
    if(P?.id===who.id){P.filterQuery=query;paintCredits();}
  }});
  controls.element.querySelector('input').placeholder='Find a show in these credits';
  controls.element.querySelector('.sr').textContent='Find a show in these credits';
  parts.roles.box.before(controls.element);
  return { id: who.id, who, close, hero, name, said, main, side, body, parts, foot, links, data: null, bio: undefined,
           error: null, fitBio: null, open: { roles: false, appearances: false, crew: false, bio: false } };
}

// Their photo, as a title's poster is shown, and the same blurred behind it; on its way while
// they are (waiting) and the page does not know it yet.
function paintPhoto(hero, who, waiting = false) {
  hero.querySelector('.p-photo')?.remove();
  hero.querySelector('.t-blur')?.remove();
  const photo = artEl({ id: who.id, name: who.name }, who.photo || null, false);
  photo.classList.add('t-poster', 'p-photo');
  if (waiting && !who.photo) photo.classList.add('skel');
  hero.prepend(photo);
  if (who.photo) hero.prepend(picture(who.photo, 't-blur'));
}

function paintPerson() {
  if (!P) return;
  if (P.error) {
    // TVmaze having no such person is final; anything else may pass.
    const again = P.error.status === 404 ? [] : [button('btn ghost', 'Try again', () => showPerson(P.id))];
    P.main.replaceChildren(el('p', P.error.message, 't-summary muted'), ...again);
    P.side.replaceChildren();
    P.said.hidden = true;
    P.name.textContent = P.who.name;
    P.hero.querySelector('.p-photo')?.classList.remove('skel');
    for (const s of Object.values(P.parts)) s.box.hidden = true;
    return;
  }
  const who = P.data.person;
  P.who = { ...P.who, ...who };
  P.name.textContent = who.name;
  document.title = `${who.name} · Couchside`;
  // A page opened before the page knew them (a shared link) gets their photo now.
  const shown = P.hero.querySelector('.p-photo');
  if ((who.photo || undefined) !== shown?.dataset.src || shown?.classList.contains('skel')) paintPhoto(P.hero, who);
  paintAbout();
  paintCredits();
}

// What is known of them: Wikipedia's description under their name; when and where they were
// born, their age or when they died, what they are known for and what they created; their
// biography; and where else to read about them.
function paintAbout() {
  const who = P.data.person, bio = P.bio;
  if (bio !== undefined) {
    P.said.textContent = bio?.description || '';
    P.said.hidden = !bio?.description;
  }
  const age = who.deathday ? null : yearsBetween(who.birthday, isoDay());
  const created = P.data.crew.filter(c => /^(Co-)?Creator$/.test(c.jobs[0])).map(c => c.name);
  const born = fact('Born', bornOn(who.birthday, bio?.birthplace));
  // Where they were born comes with the biography, and keeps its place until then: most run
  // onto a second line.
  if (born && bio === undefined) born.append(' ', skelText('75%'));
  P.side.replaceChildren(...[
    born,
    fact('Age', age === null ? '' : String(age)),
    fact('Died', diedOn(who.birthday, who.deathday)),
    fact('Known for', knownFor(P.data.roles, created)),
    fact('Created', joinNames(created.slice(0, 3))),
  ].filter(Boolean));
  P.fitBio = null;
  if (bio === undefined) P.main.replaceChildren(...bioSkeleton());
  else if (bio?.text) P.main.replaceChildren(...bioEl(bio));
  else P.main.replaceChildren();
  P.fitBio?.();
  // With no biography, what is known of them takes the whole width.
  P.body.classList.toggle('no-bio', bio !== undefined && !bio?.text);
  const out = (href, text, label) => {
    const a = el('a', text);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.setAttribute('aria-label', `${label}, opens in a new tab`);
    return a;
  };
  const links = [out(who.url, 'TVmaze', `${who.name} on TVmaze`)];
  if (bio?.imdb) links.push(out(`https://www.imdb.com/name/${bio.imdb}/`, 'IMDb', `${who.name} on IMDb`));
  if (bio?.wikipedia) links.push(out(bio.wikipedia, 'Wikipedia', `${who.name} on Wikipedia`));
  P.links.replaceChildren(el('span', 'Also on ', 'k'), ...links.flatMap((a, n) => (n ? [' · ', a] : [a])));
  P.foot.hidden = false;
}

// Their biography on its way, as bioEl lays it out: six lines, More and the credit.
function bioSkeleton() {
  return [skelLines(6, 'p', 't-summary p-text'), skelIn('span', 'p-more', '2.6em'), skelIn('p', 'p-credit', '13em')];
}

// Their biography, the opening of their Wikipedia article: six lines at first, and More for
// the rest when there is more, credited to Wikipedia under CC BY-SA as its licence asks.
function bioEl(bio) {
  const text = el('p', bio.text, 't-summary p-text');
  text.id = 'p-text';
  const more = el('button', '', 'p-more');
  more.type = 'button';
  more.setAttribute('aria-controls', text.id);
  const set = open => {
    P.open.bio = open;
    text.classList.toggle('clamped', !open);
    more.textContent = open ? 'Less' : 'More';
    more.setAttribute('aria-expanded', String(open));
  };
  more.addEventListener('click', () => set(!P.open.bio));
  set(P.open.bio);
  // Whether six lines hold it all, measured once it is on the page and again on a resize.
  P.fitBio = () => {
    if (!text.isConnected) return;
    const was = text.classList.contains('clamped');
    text.classList.add('clamped');
    const over = text.scrollHeight > text.clientHeight + 1;
    text.classList.toggle('clamped', was);
    more.hidden = !over;
    if (!over && P.open.bio) set(false);
  };
  const credit = el('p', '', 'p-credit');
  const link = (href, words) => {
    const a = el('a', words);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  };
  credit.append('Biography from ', bio.wikipedia ? link(bio.wikipedia, 'Wikipedia') : 'Wikipedia', ', ',
    link(LICENSE, 'CC BY-SA 4.0'));
  return [text, more, credit];
}
window.addEventListener('resize', () => requestAnimationFrame(() => P?.fitBio?.()));

// Their roles, their appearances as themselves and the shows they made, each best known
// first (people.py). Each is a poster that opens its title page, or for a show the
// catalogue does not hold yet its name on a tile, with whom they played and when beneath.
function paintCredits() {
  const { person: who } = P.data;
  P.parts.appearances.h.textContent = selfHeading(who.gender);
  for (const part of ['roles', 'appearances', 'crew']) {
    const creditsById=new Map(P.data[part].map(c=>[c.id,c]));
    const list=selectShows(P.data[part].map(c=>({...c,...(c.show||{})})),'person',P.filterQuery||'').map(c=>creditsById.get(c.id)),s=P.parts[part];
    s.box.hidden = !list.length||!!(P.creditRole&&P.creditRole!==part);
    s.more?.parentElement.remove();
    s.more = null;
    s.grid.replaceChildren(...list.map(c => creditCard(c, who.gender)));
    if (snippet(list.length, SNIPPETS[part]) < list.length) {
      s.more = revealButton(s.grid, () => {
        if (busy(s.grid)) return;
        P.open[part] = !P.open[part];
        unfold(s.grid, open => setCredits(part, open), P.open[part], s.more);
      });
      s.box.append(s.more.parentElement);
    }
    setCredits(part, P.open[part]);
  }
  if (!P.data.roles.length && !P.data.appearances.length && !P.data.crew.length) {
    P.parts.roles.box.hidden = false;
    P.parts.roles.grid.replaceChildren(el('li', 'TVmaze lists no shows for them yet.', 'muted p-none'));
  }
  // Someone with no regular role who made shows is best known for those (knownFor), so the
  // shows they made come first, ahead of the parts they guested in.
  if (!P.data.roles.some(r => r.regular) && P.data.crew.length) P.parts.roles.box.before(P.parts.crew.box);
}
function setCredits(part, open) {
  const s = P.parts[part];
  const items = [...s.grid.children];
  const shown = snippet(items.length, SNIPPETS[part]);
  items.forEach((li, n) => { li.hidden = !open && n >= shown; });
  if (!s.more) return;
  s.more.parentElement.hidden = shown === items.length;
  paintReveal(s.more, revealLabel(part, items.length, open), open);
}

function creditCard(c, gender) {
  const li = el('li');
  const { as, when, said } = creditLines(c, gender);
  // A show TVmaze added since the catalogue was built opens its page from TVmaze too, its
  // name on a tile until the nightly refresh brings its poster.
  const card = c.show || (newer(c.id) ? { id: c.id, name: c.name } : null);
  if (card) li.append(cardEl(card, { note: said }));
  else {
    const tile = el('div', '', 'card p-off');
    tile.append(artEl({ id: c.id, name: c.name }, null, false));
    li.append(tile);
  }
  if (!as && !when) return li;
  const caption = el('span', '', 'grid-caption p-caption');
  if (as) caption.append(el('span', as, 'p-as'));
  if (when) {
    // "8 episodes" and "2008–2020" each stay whole on a narrow poster, the dot with the first.
    const line = el('span', '', 'p-when');
    when.split(' · ').forEach((part, n) => line.append(...(n ? ['\u00a0· '] : []), el('span', part, 'p-whole')));
    caption.append(line);
  }
  // A card's own label says all of this already.
  if (card) caption.setAttribute('aria-hidden', 'true');
  li.append(caption);
  return li;
}

// A shared link opens straight to their page, over the home page.
function sharePerson() {
  if (!P) return;
  const name = P.name.textContent || 'Someone';
  shareLink(`${location.origin}/?person=${P.id}`, `${name} on Couchside`, name, 'Link copied. It opens straight to their page.');
}

/* --------------------------------------------------------------- browse */
// Genre tiles can open a shared Browse link. That genre becomes a selection in the
// same filters used by the header, preserving links and Back through those tiles.
let browseKey = null, browseReq = 0, browseShown = null;
const genreLabel = key => boot.genres.find(g => g.key === key)?.label;
const GENRES = genreChoices(boot.genres);
function renderBrowse() {
  const { genre } = where();
  const valid = genreLabel(genre) ? genre : '';
  if (valid !== browseShown) {
    if (valid) {
      const filters = {...filtersFor('browse')};
      delete filters.genres;
      delete filters.format;
      if (['animation', 'documentary', 'unscripted'].includes(valid)) filters.format = valid;
      else filters.genres = [valid];
      setFilters('browse', filters);
      pageFilters.get('browse')?.paint();
    }
    if (browseShown !== null && window.scrollY) window.scrollTo(0, 0);
    browseShown = valid;
  }
  const filters = filtersFor('browse');
  const single = filters.genres?.length === 1 ? filters.genres[0] : filters.format;
  $('browse-h').textContent = genreLabel(single) || 'Browse';
  if (!valid && !filterKey('browse')) {
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
  const key = `${valid}|${JSON.stringify(taste())}${filterKey('browse')}`;
  if (key === browseKey) return;
  browseKey = key;
  loadBrowse(valid || 'all');
}

async function loadBrowse(genre) {
  const id = ++browseReq;
  $('browse-body').replaceChildren(skelRow('section', { title: '12em' }), skelRow('section', { title: '10em' }),
    skelRow('section', { title: '11em' }));
  try {
    const data = await post('/api/browse', { ...taste(), ...await freshFields(), genre, filters:filtersFor('browse'), matrix:matrixPreference() });
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
/* ----------------------------------------------------------- new & popular */
// Until the home page is here, its rows stand in as they will land: the Top 10, new this
// year, Coming soon with its dates and Popular right now.
let newData=null,newKey='',newRequest=0;
function renderNew() {
  const key=JSON.stringify(taste())+filterKey('new');
  const independent=!!(filterKey('home')||filterKey('new'));
  if(independent&&key!==newKey){
    newKey=key;newData=null;const id=++newRequest;
    freshFields().then(ask=>post('/api/home',{...homeBody(state,ask),filters:filtersFor('new')})).then(data=>{
      if(id!==newRequest)return;newData=data;rememberHome(data);if(view==='new')renderNew();
    },e=>{if(id===newRequest){newKey='';$('new-body').replaceChildren(el('p',e.message,'row-empty'));}});
  }
  const feed=independent?newData:home;
  const holder = $('new-body');
  if (!feed) {
    holder.replaceChildren(...(homeFailed ? [el('p', homeFailed, 'row-empty')]
      : [skelRow('section', { kind: 'top10', title: '9em' }), skelRow('section', { title: '12em' }),
        skelRow('section', { kind: 'soon', title: '7em' }), skelRow('section', { title: '9em' })]));
    return;
  }
  const rows = feed.top10.length?[{ key: 'top10', title: 'Top 10 shows today', kind: 'top10', items: feed.top10 }]:[];
  if (feed.fresh.length) {
    rows.push({ key: 'fresh', title: feed.personal ? 'New this year, picked for you' : 'New this year', kind: 'row', items: feed.fresh });
  }
  if (feed.soon.length) rows.push({ key: 'soon', title: 'Coming soon', kind: 'soon', items: feed.soon });
  if (feed.popular?.length) rows.push({ key: 'popular', title: 'Popular right now', kind: 'row', items: feed.popular });
  redraw(holder, () => holder.replaceChildren(...(rows.length?rows.map(rowEl):[el('p','No shows match these filters. Try widening them or clear all.','row-empty')])));
  reveal(holder.children);
}

/* -------------------------------------------------------------- my list */
let ratedFilter = 'all';
// Ratings show RATED_PAGE at a time, so a list of thousands draws as fast as one of dozens.
const RATED_PAGE = 60;
let ratedShown = RATED_PAGE, ratedFind = '', findTimer = 0;
const folded = text => (text || '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim();
const GROUPS = {
  all: ['All', () => true], loved: ['Loved', p => p.weight === 1],
  liked: ['Liked', p => p.weight > 0 && p.weight < 1], down: ['Not for me', p => p.weight < 0],
};
const NOTES = { 1: 'you loved it', '-1': 'not for you' };

// The name under a poster, and under it in a muted line what else the grid says of the
// show, such as its year; already read out as part of the card's own label.
function titledCaption(name, meta) {
  const caption = el('span', '', 'grid-caption titled');
  caption.setAttribute('aria-hidden', 'true');
  caption.append(name, ...(meta ? [meta] : []));
  return caption;
}
const showCaption = (c, also = '') => titledCaption(el('span', c.name, 'cap-name'),
  c.year || also ? el('span', [c.year, also].filter(Boolean).join(' · '), 'cap-meta') : null);

function fill(grid, items, options = () => ({})) {
  redraw(grid, () => grid.replaceChildren(...items.map(c => {
    const li = el('li');
    const o = options(c);
    li.append(cardEl(c, o));
    if (o.titled) {
      li.append(showCaption(c, o.also));
      return li;
    }
    // A caption under the poster, already read out as part of the card's own label.
    if (o.caption) {
      const caption = el('span', o.caption, 'grid-caption');
      caption.setAttribute('aria-hidden', 'true');
      li.append(caption);
    }
    return li;
  })));
}

let listQuery='',listHydrating=false;
const listLoaded=new Set();
function hydrateList(){
  const ids=[...new Set([...state.saved,...state.profile].map(s=>s.id))].filter(id=>!listLoaded.has(id));
  if(listHydrating||!ids.length)return;
  listHydrating=true;
  let more=false;
  post('/api/shows',{ids:ids.slice(0,200),matrix:matrixPreference()}).then(data=>{data.shows.forEach(remember);ids.slice(0,200).forEach(id=>listLoaded.add(id));more=ids.length>200;if(view==='list')renderList();},()=>{}).finally(()=>{listHydrating=false;if(more)hydrateList();});
}
function renderList() {
  hydrateList();
  const saved = selectShows(state.saved.slice().reverse().map(s => ({ ...s, ...(known.get(s.id) || {}) })),'list',listQuery);
  $('list-note').textContent = saved.length
    ? `${saved.length} show${saved.length === 1 ? '' : 's'} saved for later.`
    : state.saved.length?'No saved shows match these filters.':'Nothing saved yet. Tap My List on any show and it waits here.';
  fill($('list-grid'), saved);

  const filters = $('rated-filter');
  filters.replaceChildren(...Object.entries(GROUPS).map(([key, [label, test]]) => {
    const b = button('chip', `${label} ${state.profile.filter(test).length.toLocaleString()}`, () => {
      ratedFilter = key;
      ratedShown = RATED_PAGE;
      renderList();
    });
    b.setAttribute('aria-pressed', String(ratedFilter === key));
    return b;
  }));
  filters.hidden = !state.profile.length;
  // A long list is found by name and shown a page at a time, newest first.
  $('rated-find-box').hidden = state.profile.length <= RATED_PAGE;
  const needle = folded(ratedFind);
  const list = selectShows(state.profile.filter(p => GROUPS[ratedFilter][1](p) && (!needle || folded(known.get(p.id)?.name || p.name).includes(needle)))
    .reverse().map(p=>({...p,...known.get(p.id)})),'list',listQuery);
  const page = list.slice(0, ratedShown);
  $('rated-note').textContent = !state.profile.length ? 'Nothing rated yet. Open a show and tap a thumb or the heart.'
    : !list.length ? (needle ? `No show you rated matches “${ratedFind}”.` : 'Nothing here yet.')
      : `Open any show to change or take back its rating.${list.length > page.length
        ? ` The newest ${page.length.toLocaleString()} of ${list.length.toLocaleString()} are here.` : ''}`;
  const more = $('rated-more');
  more.hidden = list.length <= page.length;
  more.textContent = `Show ${Math.min(RATED_PAGE, list.length - page.length).toLocaleString()} more`;
  const grid = $('rated-grid');
  fill(grid, page.map(p => ({ ...p, ...(known.get(p.id) || {}), match: null })),
    c => ({ note: NOTES[String(rated(c.id))] || 'you liked it' }));
  for (const card of grid.querySelectorAll('.card')) {
    const weight = rated(Number(card.dataset.id));
    const badge = el('span', '', `badge-rate ${weight === 1 ? 'heart' : weight < 0 ? 'down' : 'up'}`);
    badge.setAttribute('aria-hidden', 'true');
    badge.append(icon(weight === 1 ? 'heart' : weight < 0 ? 'down' : 'up'));
    card.append(badge);
  }
}
$('rated-more').addEventListener('click', () => {
  ratedShown += RATED_PAGE;
  renderList();
});
$('rated-find').addEventListener('input', () => {
  clearTimeout(findTimer);
  findTimer = setTimeout(() => {
    ratedFind = $('rated-find').value.trim();
    ratedShown = RATED_PAGE;
    renderList();
  }, 150);
});

/* --------------------------------------------------------------- search */
// searchShown is the search on screen or on its way, and resultsFor the one whose
// results are showing ('' for the suggestions).
let searchReq = 0, searchTimer = 0, searchShown = null, resultsFor = '';
// Posters a search's grid shows while it is on its way: four lines of a phone's three, and
// two of a wide screen's.
const SEARCHING = 12;

// What people are watching comes with the home page, so until it is here posters of its
// shape stand in; the first-visit posters the page carries stand in for good if it cannot
// be had.
function suggestions() {
  resultsFor = '';
  $('search-note').textContent = 'Search by title. Until then, here is what people are watching.';
  const popular = home?.popular || [];
  if (home || homeFailed) fill($('results'), home ? [...home.top10, ...popular] : boot.starters);
  else $('results').replaceChildren(...skelGrid(SEARCHING));
  $('missing').hidden = true;
  showRelated(null);
}

// The server forgives typos, spacing and other titles, and asks TVmaze about shows
// too new for the catalogue, so a search here rarely comes back empty. Beside the titles
// it matches comes a row of shows like it (related.py). What is on screen stays until
// the next answer replaces it, posters and all, so typing never blanks the page. Coming
// back to the search on screen, such as by closing a title opened from it, keeps its results.
function search(q, typed = true) {
  const query = q.trim();
  const input = $('q');
  if (document.activeElement !== input && input.value !== q) input.value = q;
  paintRecent();
  const key=query+filterKey('search');
  if (key === searchShown) return;
  searchShown = key;
  clearTimeout(searchTimer);
  const id = ++searchReq;
  if (!query&&!filterKey('search')) { suggestions(); return; }
  // One character finds only a show of that one letter, such as V, so until one turns
  // up the page keeps its suggestions.
  const quiet = query.length === 1;
  if (quiet) suggestions();
  else {
    $('search-note').textContent = 'Searching…';
    // With nothing on screen for the answer to replace, as when the page opens on a search,
    // the grid shows its shape while it runs.
    if (!$('results').childElementCount) $('results').replaceChildren(...skelGrid(SEARCHING, true));
  }
  searchTimer = setTimeout(async () => {
    try {
      const { shows, missing = [], missing_first: first = false, related = null } =
        await call(`/api/search?q=${encodeURIComponent(query)}&filters=${encodeURIComponent(JSON.stringify(filtersFor('search')))}${matrixPreference()?'&matrix=1':''}`);
      if (id !== searchReq || (quiet && !shows.length)) return;
      shows.forEach(remember);
      resultsFor = query;
      $('search-note').textContent = !query?`${shows.length} shows match these filters.`:searchNote(query, shows.length, missing.length, related?.shows?.length || 0);
      // Every match names its show under its poster, as a poster's art does not always
      // say which show it is: Outer Banks' says OBX 5.
      fill($('results'), shows.map(s => ({ ...s, ...(known.get(s.id) || {}), aka: s.aka })),
        c => ({ titled: true, ...(c.aka ? { note: `also known as ${c.aka}`, also: `also known as ${c.aka}` } : {}) }));
      showMissing(missing, first);
      showRelated(related, query);
    } catch (e) {
      if (id !== searchReq) return;
      searchShown = null;
      if (!quiet) $('search-note').textContent = e.message;
      if ($('results').querySelector('.skel-item')) $('results').replaceChildren();
    }
  }, typed ? 200 : 0);
}

// Shows TVmaze has that the catalogue does not yet, as posters named like the results
// above, each opening a title page of its own from TVmaze (newer), with New for its year
// when it has none yet; ahead of the results when TVmaze ranks one of them first.
function showMissing(missing, first) {
  const box = $('missing');
  box.hidden = !missing.length;
  missing.forEach(m => remember({ ...m, newer: true }));
  fill($('missing-list'), missing, c => ({ titled: true, also: c.year ? '' : 'New', note: 'just added to TVmaze' }));
  $('search').insertBefore(box, first ? $('results') : $('related'));
}

// Shows like the search, under its title matches: More like the show it names, or Shows
// like a topic or anything else it means ("zombies", "mad max"). None, and the row goes,
// but not while the search only grows from the one it was found for (keepsRow).
let relatedFor = '';
function showRelated(related, query = '') {
  const shows = related?.shows || [];
  if (!shows.length && keepsRow(relatedFor, query)) return;
  relatedFor = shows.length ? query : '';
  $('related').hidden = !shows.length;
  if (!shows.length) return;
  shows.forEach(remember);
  $('related-h').textContent = related.title;
  fill($('related-grid'), shows.map(s => ({ ...s, ...(known.get(s.id) || {}) })));
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

// They show on the results page on phones while the header search has focus or is empty,
// and drop from the nav's box on wide screens while it has the focus. Once something is
// typed, only those it begins, or begins a word of, stay.
const holdsFocus = (...nodes) => nodes.some(n => n.contains(document.activeElement));
function paintRecent() {
  const phone = !wide(), page = $('q');
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
  $('q').value = q;
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
for (const box of [$('recent-page'), $('recent-drop')]) {
  const input = $('q');
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
// Search fills the title row while it is in use. Its back arrow restores the
// wordmark and navigation, leaving the query and results in place.
function expandFind(open) {
  $('find').classList.toggle('open', open);
  $('nav').classList.toggle('searching', open);
  $('find-open').replaceChildren(icon(open ? 'left' : 'search'));
  $('find-open').setAttribute('aria-label', open ? 'Close search' : 'Search');
}
function closeFind() {
  $('q').blur();
  expandFind(false);
  document.querySelector('.nav .brand').focus({ preventScroll: true });
  paintRecent();
}
// Keep the expanded row steady while its filters are open; the menu is anchored
// to the funnel. An empty field contracts once its focus has gone elsewhere.
function settleFind() {
  if (!$('q').value && !$('find').contains(document.activeElement)
      && $('filter-open').getAttribute('aria-expanded') !== 'true') expandFind(false);
  paintRecent();
}
for (const area of [$('find'), $('search')]) {
  area.addEventListener('focusin', paintRecent);
  area.addEventListener('focusout', () => requestAnimationFrame(settleFind));
}
window.addEventListener('resize', paintRecent);

$('q').addEventListener('focus', () => {
  expandFind(true);
  if (!wide() && view !== 'search') go('/search');
});
$('q').addEventListener('input', () => { toSearch($('q').value); expandFind(true); });
$('q').addEventListener('keydown', e => {
  const input = $('q');
  if (e.key === 'Enter') { commitSearch(input.value); input.blur(); }
  if (e.key === 'Escape') {
    input.value = '';
    if (view === 'search') toSearch('');
    closeFind();
  }
});
// Opening one of a search's results, or of the shows like it, commits it too.
for (const grid of [$('results'), $('related-grid')]) {
  grid.addEventListener('click', e => { if (e.target.closest('.card-hit, .push')) commitSearch(resultsFor); });
}
$('missing').addEventListener('click', e => { if (e.target.closest('a')) commitSearch(resultsFor); });

// Search from the nav or the dock: coming from another page starts afresh with recent
// searches showing, while on the search page it keeps what is there and takes the focus.
function openSearch() {
  if (view !== 'search') go('/search');
  else window.scrollTo(0, 0);
  expandFind(true);
  $('q').focus();
}
expandFind(false);
$('filter-open').append(icon('filter'));
$('filter-open').addEventListener('click', () => pageFilters.get(view)?.open());
function focusFind() {
  if (!wide()) { openSearch(); return; }
  if (view !== 'search') $('q').value = '';
  expandFind(true);
  $('q').focus();
}
$('find-open').addEventListener('click', () => {
  if ($('find').classList.contains('open')) closeFind();
  else focusFind();
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
  focusFind();
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
      $('found').replaceChildren(...shows.slice(0, 12).map(c => {
        const li = pickTile(remember(c), new Map());
        li.append(showCaption(c));
        return li;
      }));
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
  $('profile-counts').textContent = `${state.profile.length.toLocaleString()} rated · ${state.saved.length} in My List`;
}
for (const avatar of document.querySelectorAll('.avatar')) avatar.append(icon('smile'));
$('account-open').addEventListener('click', () => {
  updateCounts();
  $('account').showModal();
});
$('open-profile').addEventListener('click', () => {
  updateCounts();
  $('account').close();
  $('profile').showModal();
});
$('open-customization').addEventListener('click', () => {
  $('reach').value = String(state.settings.known_min);
  $('account').close();
  $('customization').showModal();
});
$('reach').addEventListener('change', () => {
  state.settings.known_min = Number($('reach').value);
  save();
  toast('Your rows will update.');
  loadHome();
});
$('reset').addEventListener('click', () => {
  $('reset-scope').textContent = accountOwner
    ? 'Clear the ratings and My List shown here and reset your recommendation settings across your signed-in devices. Shows added elsewhere while you do this are kept. Your account and password stay in place.'
    : 'Clear your ratings, My List and recommendation settings on this device, then pick your first shows again.';
  $('account').close();
  $('reset-confirm').showModal();
});
$('confirm-reset').addEventListener('click', () => {
  const wasWelcome = view === 'welcome';
  state = fresh();
  save();
  updateCounts();
  picked.clear();
  clearFound();
  opening.round = 0;
  opening.asked = '';
  ++opening.req;
  home = null;
  homeKey = '';
  $('reset-confirm').close();
  go('/');
  if (wasWelcome) renderWelcome();
  loadHome();
  toast('Your current list is cleared. Pick a few shows to start again.');
});
for (const b of document.querySelectorAll('[data-close]')) b.addEventListener('click', () => b.closest('dialog').close());
for (const d of [$('account'), $('profile'), $('customization'), $('reset-confirm'), $('transfer-replace-confirm'), $('auth'), $('move'), $('about'), $('taste')]) {
  d.addEventListener('click', e => { if (e.target === d) d.close(); });
}
$('open-about').addEventListener('click', () => $('about').showModal());
$('open-taste').addEventListener('click', () => {
  $('account').close();
  void tastePanel.open();
});
$('open-about-2').addEventListener('click', () => { $('account').close(); $('about').showModal(); });

/* ------------------------------------------------------- moving devices */
function moveLink() { return `${location.origin}/#t=${encode(state)}`; }

// Dark modules on white whatever the theme: a camera needs the contrast the spec assumes.
function drawCode(link) {
  const svg = $('qr');
  svg.replaceChildren();
  const grid = link ? matrix(link) : null;
  $('qr-wrap').hidden = !grid;
  // A QR code holds about 2,300 bytes, a list of a few hundred ratings; past that the
  // link, the code or a file carries it.
  $('qr-none').hidden = Boolean(grid) || !link;
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
    ? `${state.profile.length.toLocaleString()} rated and ${state.saved.length} in My List. Signing in on the other device syncs them automatically; these tools transfer a separate copy.`
    : 'Nothing to move yet. Rate a show or add one to My List first.';
  for (const id of ['copy-link', 'copy-code', 'save-file']) $(id).disabled = !code;
  $('copy-said').textContent = '';
  $('move-status').textContent = '';
  $('move-paste').value = '';
  $('move').showModal();
}
$('open-move').addEventListener('click', () => { $('profile').close(); openMove(); });

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

// A list too long for a QR code also moves as a file holding its link: AirDrop it, mail
// it or keep it in a cloud folder, and open it here on the other device.
$('save-file').addEventListener('click', () => {
  const file = URL.createObjectURL(new Blob([`${moveLink()}\n`], { type: 'text/plain' }));
  const link = el('a');
  link.href = file;
  link.download = `couchside-list-${today()}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(file), 10_000);
  $('copy-said').textContent = 'Saved. On the other device, open it here with Open a saved file.';
});
$('open-file').addEventListener('click', () => $('move-file').click());
$('move-file').addEventListener('change', async () => {
  const scope = accountEpoch;
  const file = $('move-file').files[0];
  $('move-file').value = '';
  if (!file) return;
  if (file.size > 200_000) { $('move-status').textContent = 'That file is too big to be a list.'; return; }
  const raw = codeFrom(await file.text());
  if (scope !== accountEpoch) return;
  $('move-paste').value = raw;
  try {
    const found = decode(raw);
    $('move-status').textContent = `This file holds ${found.profile.length.toLocaleString()} rated and ${
      found.saved.length} saved. Add them to your list, or replace your list with them.`;
  } catch (e) {
    $('move-status').textContent = e.message || 'That file does not hold a list.';
  }
});

let transferBusy = false;
let replacement = null;
const transferSnapshot = () => JSON.stringify([state.profile.map(({ id, weight }) => [id, weight]),
  state.saved.map(({ id }) => id), state.settings]);

async function bringIn(replace, incoming = null, expected = null) {
  if (transferBusy) return;
  const raw = codeFrom($('move-paste').value);
  if (!incoming && !raw) { $('move-status').textContent = 'Paste the link or code first.'; return; }
  transferBusy = true;
  for (const id of ['do-merge', 'do-replace']) $(id).disabled = true;
  $('move-status').textContent = 'Reading it…';
  try {
    await apply(incoming || decode(raw), replace, expected);
    $('move').close();
  } catch (e) {
    $('move-status').textContent = e.message || 'That code could not be read.';
  } finally {
    transferBusy = false;
    for (const id of ['do-merge', 'do-replace']) $(id).disabled = false;
  }
}
$('do-merge').addEventListener('click', () => bringIn(false));
$('do-replace').addEventListener('click', () => {
  try {
    replacement = { incoming: decode(codeFrom($('move-paste').value)),
      owner: accountOwner, scope: accountEpoch, snapshot: transferSnapshot() };
    $('transfer-replace-scope').textContent = accountOwner
      ? 'Replace the ratings and My List shown here with this copy, and use its recommendation settings across your signed-in devices. Shows missing from the copy are removed; shows added elsewhere while you do this are kept. Your account and password stay in place.'
      : 'Replace your ratings, My List and recommendation settings on this device with this copy. Shows missing from the copy will be removed.';
    $('transfer-replace-confirm').showModal();
  } catch (e) {
    $('move-status').textContent = e.message || 'Paste a valid link or code first.';
  }
});
$('transfer-replace-confirm').addEventListener('close', () => { replacement = null; });
$('confirm-transfer-replace').addEventListener('click', () => {
  const pending = replacement;
  replacement = null;
  $('transfer-replace-confirm').close();
  if (pending) void bringIn(true, pending.incoming, pending);
});

// Titles and posters are not in the code, so the catalogue fills them back in.
async function apply(incoming, replace, expected = null) {
  const owner = expected ? expected.owner : accountOwner;
  const scope = expected ? expected.scope : accountEpoch;
  const snapshot = expected ? expected.snapshot : transferSnapshot();
  if (owner !== accountOwner || scope !== accountEpoch) throw new Error('Your account changed. Open the transfer again to continue.');
  const ids = [...new Set([...incoming.profile.map(s => s.id), ...incoming.saved.map(s => s.id)])];
  const { shows } = await post('/api/shows', { ids });
  if (owner !== accountOwner || scope !== accountEpoch) throw new Error('Your account changed while reading this list. Open the transfer again to continue.');
  if (replace && snapshot !== transferSnapshot()) throw new Error('Your list changed while reading this copy. Review the transfer again before replacing it.');
  const found = new Map(shows.map(s => [s.id, remember(s)]));
  const ratings = incoming.profile.filter(s => found.has(s.id)).map(s => ({ ...tidy(found.get(s.id)), weight: s.weight }));
  const kept = incoming.saved.filter(s => found.has(s.id)).map(s => tidy(found.get(s.id)));
  if (!ratings.length && !kept.length) throw new Error('None of those shows are in this catalogue.');
  const previous = state;
  if (replace) {
    const reach = incoming.settings.known_min;
    state = {
      version: VERSION, profile: ratings, saved: kept,
      settings: { ...DEFAULTS, known_min: REACH.includes(reach) ? reach : DEFAULTS.known_min }, onboarded: true,
    };
  } else {
    state = mergeTransferredList(state, { profile: ratings, saved: kept });
  }
  save();
  updateCounts();
  go('/');
  loadHome();
  updateListRow();
  const dropped = ids.length - found.size;
  const addedRatings = replace ? ratings.length : state.profile.length - previous.profile.length;
  const addedSaved = replace ? kept.length : state.saved.length - previous.saved.length;
  toast(`${replace ? 'Restored' : 'Added'} ${addedRatings.toLocaleString()} ratings and ${addedSaved} shows in My List`
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
  $('move-status').textContent = `This link holds ${incoming.profile.length.toLocaleString()} rated and ${incoming.saved.length} saved. `
    + 'You already have a list here, so choose what to do with it.';
}

/* ------------------------------------------------------------ connection */
let networkNoticeAt=0,networkNotice='';
function recoverVisible(paths=[]) {
  const affected=route=>!paths.length||paths.some(path=>path.split('?')[0]===route);
  if($('taste').open&&affected('/api/taste'))tastePanel?.refresh(true);
  if((!home||homeFailed)&&affected('/api/home'))loadHome();
  if(view==='browse'&&paths.some(path=>path.startsWith('/api/browse'))){browseKey=null;renderBrowse();}
  if(view==='search'&&paths.some(path=>path.startsWith('/api/search'))){searchShown=null;search($('q').value,false);}
  if(view==='new'&&affected('/api/home')&&!newData){newKey='';renderNew();}
  if(view==='list'&&affected('/api/shows'))hydrateList();
  const t=T;
  if(t) {
    if(t.error&&affected('/api/title'))titleOf(t.id).then(data=>{
      if(T!==t)return;t.error='';t.data=data;remember(data.show);
      [...data.more,...(data.fans||[])].forEach(remember);paintTitle();paintBackdrop();paintMore();
    }).catch(()=>{});
    if(t.liveFailed&&affected('/api/extra'))details(t.id).then(live=>{
      if(T!==t||!live)return;t.liveFailed=false;t.live=live;paintTitle();paintBackdrop();paintEpisodes();
    });
    if(t.ratingsFailed&&affected('/api/episode-ratings'))ratings(t.id).then(data=>{
      if(T!==t)return;t.ratingsFailed=false;t.episodeData=data;paintEpisodes();
    }).catch(()=>{});
    if(paths.includes(`/api/trailer?id=${t.id}`))videosOf(t.id,t.data?.tmdb).then(videos=>{
      if(T!==t)return;t.videos=videos;paintTrailerButton();paintVideos();
    });
    if(paths.includes(`/api/rating?id=${t.id}`))ratingOf(t.id,t.data?.tmdb,true).then(age=>{
      if(T!==t)return;t.age=age;paintTitle();
    });
  }
  if(E?.retry&&affected('/api/episode'))loadEpisode(episodeToken);
  const person=P;
  if(person?.error&&affected('/api/person'))personOf(personId).then(data=>{
    if(P!==person)return;person.error=null;person.data=data;paintPerson();
  }).catch(()=>{});
  if(person&&paths.includes(`/api/biography?id=${personId}`))biographyOf(personId).then(bio=>{
    if(P!==person)return;person.bio=bio;paintAbout();
  });
}
window.addEventListener('couchside-network',event=>{
  const {state,paths=[]}=event.detail;
  if(state==='recover'){recoverVisible(paths);return;}
  const now=Date.now();
  if(now-networkNoticeAt<10000&&(state!=='restored'||networkNotice==='restored'))return;
  const message={retrying:'Connection interrupted. Retrying automatically…',
    failed:'Still having trouble loading data. We will try again shortly.',
    offline:'You are offline. We will retry when your connection returns.',
    restored:'Data is loading again.'}[state];
  if(message){networkNotice=state;networkNoticeAt=now;toast(message,4500);}
});
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
// A wide screen shows the featured show over its TMDB backdrop, so the connection to TMDB's
// image server is made while the page is still being asked for. A phone shows the poster.
if (wide()) {
  const connect = el('link');
  connect.rel = 'preconnect';
  connect.href = 'https://image.tmdb.org';
  connect.crossOrigin = 'anonymous';
  document.head.append(connect);
}
for (const a of document.querySelectorAll('.dock [data-icon]')) a.prepend(icon(a.dataset.icon));
// While the page scrolls the dock folds away and leaves one button, for the section you are
// in; a pause brings the dock back, and so does that button. Not near the top, where there
// is nothing to make room for, nor for anyone who asks for less motion. The empty touchstart
// lets iOS show a pressed tab.
window.addEventListener('scroll', () => {
  if (!motion()) return;
  clearTimeout(dockRest);
  dockAway(window.scrollY > 40);
  dockRest = setTimeout(() => dockAway(false), DOCK_REST);
}, { passive: true });
$('dock-mini').addEventListener('click', () => {
  clearTimeout(dockRest);
  dockAway(false);
});
$('dock').addEventListener('touchstart', () => {}, { passive: true });
for (const b of document.querySelectorAll('.close-btn')) b.append(icon('close'));
for(const [page,anchor] of [['home','rows'],['browse','browse-body'],['new','new-body'],['list','list-note'],['search','recent-page']]){
  const controls=filterBar(page,{genres:boot.genres,languages:boot.languages||[],trigger:$('filter-open'),search:page==='list',onPaint:paintHeaderFilters,onChange:query=>{
    if(page==='home'){homeKey='';loadHome();}
    if(page==='browse'){browseKey=null;if(where().genre)go('/browse');else renderBrowse();}
    if(page==='new'){newKey='';renderNew();}
    if(page==='list'){listQuery=query; ratedShown=RATED_PAGE; renderList();}
    if(page==='search'){searchShown=null;search($('q').value,false);}
  }});
  $(anchor).before(controls.element);
  pageFilters.set(page,controls);
}
function applyAccountState(incoming, context) {
  if (!context.current()) return;
  const metadata = new Map([...state.profile, ...state.saved].map(show => [show.id, show]));
  const describe = show => ({ ...(metadata.get(show.id) || {}), ...(known.get(show.id) || {}), ...show });
  const next = sanitize({ ...incoming, profile: incoming.profile.map(describe), saved: incoming.saved.map(describe) });
  if (JSON.stringify(next) === JSON.stringify(state)) return;
  state = next;
  tastePanel?.refresh();
  // A cached personalised page belongs to the list that produced it.
  homeAbort?.abort();
  ++homeReq;
  home = null;
  homeKey = '';
  homeFailed = '';
  browseKey = null;
  ++browseReq;
  newKey = '';
  newData = null;
  ++newRequest;
  searchShown = null;
  ++searchReq;
  ratedShown = RATED_PAGE;
  try { sessionStorage.removeItem(PAGE_KEY); sessionStorage.removeItem(ANSWERS_KEY); } catch { /* storage unavailable */ }
  answers = {};
  updateCounts();
  for (const id of new Set([...state.profile, ...state.saved, ...metadata.values()].map(show => show.id))) {
    paintRates(id);
    syncList(id);
  }
  if (view) { paintView(view); route(); loadHome(); }
}
tastePanel = mountTaste({ dialog: $('taste'), body: $('taste-body'),
  getProfile: () => state.profile.map(({ id, weight }) => ({ id, weight })),
  getSettings: () => state.settings, getOwner: () => accountOwner, request: post });
accounts = mountAccounts({ getState: () => state, applyState: applyAccountState, fresh, sanitize, toast,
  onStatus: ({ user }) => {
    const owner = user?.id || '';
    if (owner !== accountOwner) {
      accountOwner = owner;
      accountEpoch++;
      tastePanel.refresh();
      replacement = null;
      for (const id of ['reset-confirm', 'transfer-replace-confirm', 'move']) if ($(id).open) $(id).close();
      $('move-link').value = '';
      $('move-paste').value = '';
      $('qr').replaceChildren();
    }
    $('account-counts').textContent = user?.email || 'On this device';
  } });
renderHomeLoading();
await accounts.ready();
updateCounts();
route();
loadHome();
readLink();
