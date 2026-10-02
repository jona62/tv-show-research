import { fitRows, chooseSpokes, drawFit, short } from './fit.js';
import { encode, decode, LIMITS, packList, codeFrom } from './transfer.js';
import { matrix, svgPath } from './qr.js';
import { prune, few } from './similar.js';
import { today, freshStore, noteSeen, noteEngaged, prune as forget, freshness, watcher, seedFor } from './fresh.js';
import { visitKey, resumable, merge, shownStore, noteShown, pruneShown, lastShown, dayName } from './visits.js';
import { startersQuery, mergeStarters, browserLanguage, MAX_ROUND, MAX_PICKED } from './starters.js';

const boot = JSON.parse(document.getElementById('boot').textContent);
const $ = id => document.getElementById(id);
const KEY = 'next-watch-v1';
const RATINGS = [[1, 'Loved'], [.7, 'Liked'], [.35, 'OK'], [0, 'Meh'], [-1, 'No']];
const SPOKEN = { 1: 'Loved it', .7: 'Liked it', .35: 'It was OK', 0: 'Seen it, no strong feelings', '-1': 'Did not like it' };
const FOCUS = {
  balanced: { text: 40, themes: 35, genres: 25 },
  story: { text: 70, themes: 20, genres: 10 },
  themes: { text: 15, themes: 70, genres: 15 },
  genres: { text: 15, themes: 20, genres: 65 },
};
const FORMATS = ['all', 'scripted', 'animation', 'documentary', 'unscripted'];
const DEFAULTS = {
  text: 40, themes: 35, genres: 25, closest: .3, dislike: .35,
  language: 'all', type: 'all', status: 'all', year_min: 1900, runtime_min: 0,
  rating_min: 0, known_min: 60,
};
const KNOWN = [0, 60, 85, 95];
// Version 2 widened the defaults to fairly known shows of any year, once the ranking
// learned which eras and how well known a list likes.
const VERSION = 2;
const el = (tag, text = '', cls = '') => {
  const n = document.createElement(tag);
  if (text) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
const button = (text, cls, onClick) => {
  const b = el('button', text, cls);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
};
const meta = s => [s.year ?? 'Year unknown', s.channel, s.rating ? '★ ' + s.rating : null].filter(Boolean).join(' · ');

let state = { version: VERSION, profile: [], saved: [], settings: { ...DEFAULTS }, similar_to: [] };
let data = null, tab = 'next', reqId = 0, reqAbort = null, timer = null;
let searchId = 0, searchAbort = null, searchTimer = null, fitPick = null;
let allSignals = false, allRelated = false;

/* ------------------------------------------------------------- storage */
try {
  const saved = JSON.parse(localStorage.getItem(KEY));
  if (saved && Array.isArray(saved.profile)) {
    state = {
      version: VERSION,
      profile: saved.profile.filter(p => Number.isInteger(p.id) && RATINGS.some(([w]) => w === p.weight))
        .slice(0, LIMITS.rated),
      saved: (Array.isArray(saved.saved) ? saved.saved : []).filter(s => Number.isInteger(s.id)).slice(0, LIMITS.saved),
      settings: { ...DEFAULTS, ...(saved.settings || {}) },
      similar_to: Array.isArray(saved.similar_to) ? saved.similar_to.filter(Number.isInteger) : [],
    };
    // A list saved before version 2 held well known shows from 1990 on because those
    // were the defaults, so it moves to the new ones once.
    if (!(saved.version >= 2)) {
      if (state.settings.known_min === 85) state.settings.known_min = DEFAULTS.known_min;
      if (state.settings.year_min === 1990) state.settings.year_min = DEFAULTS.year_min;
    }
    // A list saved before the popularity control existed keeps its old rating floor otherwise.
    if (!KNOWN.includes(state.settings.known_min)) state.settings.known_min = DEFAULTS.known_min;
    state.settings.rating_min = 0;
    // Format used to be a raw catalog type; anything the new grouping cannot show falls back.
    if (!FORMATS.includes(state.settings.type)) state.settings.type = 'all';
  }
} catch { /* first visit, or storage is off */ }
keepSimilar();

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode */ }
}

/* ----------------------------------------------------------- freshness */
// The first five picks hold from day to day and the rest turn over a little (fresh.py).
// This browser keeps which picks were on screen on which days and what you engaged
// with (fresh.js), under a key of its own; a request carries only the day, a seed and
// a decayed count per title. With no storage to keep the seed's salt, there is no seed
// and the picks stay as ranked.
const FRESH_KEY = 'next-watch-fresh';
const fresh = (() => {
  let raw;
  try { raw = localStorage.getItem(FRESH_KEY); } catch { return null; }
  let kept = null;
  try { kept = JSON.parse(raw); } catch { /* damaged: start again */ }
  const store = forget(freshStore(kept), today());
  try { localStorage.setItem(FRESH_KEY, JSON.stringify(store)); } catch { return null; }
  return store;
})();
let freshTimer = 0;
// Impressions come in bursts, so the store is written a second after the last one, and
// at once when the page is left.
function keepFresh(now = false) {
  if (!fresh) return;
  clearTimeout(freshTimer);
  const write = () => { try { localStorage.setItem(FRESH_KEY, JSON.stringify(fresh)); } catch { /* full */ } };
  if (now) write(); else freshTimer = setTimeout(write, 1000);
}
// Opening a title, asking why, saving or rating it spares it two weeks of fatigue.
function engage(id) {
  if (!fresh) return;
  noteEngaged(fresh, id, today());
  keepFresh();
}
// A pick counts as seen once half of it has been on screen for a second, at most once a
// day. Counting only writes the store; it never redraws anything.
const impressions = fresh ? watcher(id => { noteSeen(fresh, id, today()); keepFresh(); }) : null;
async function freshFields() {
  if (!fresh) return {};
  // Without Web Crypto (a page not served over https) there is no seed: the plain ranking.
  try { return await freshness(fresh, today()); } catch { return {}; }
}

/* -------------------------------------------------------------- visits */
// A visit's picks hold still. The last answer, as shown, is kept for this tab, and a
// reload or a return on the same day within half an hour of the last activity, with the
// same list and settings, shows it again instead of asking afresh (visits.js). Actions
// merge into it; a new layout waits for the next visit.
const VISIT_KEY = 'next-watch-visit';
let active = Date.now();
let made = { key: null, day: null };   // what the picks on show were made for
for (const type of ['pointerdown', 'keydown', 'wheel', 'touchstart', 'scroll']) {
  addEventListener(type, () => { active = Date.now(); }, { capture: true, passive: true });
}
function keepVisit() {
  if (!data) return;
  try {
    sessionStorage.setItem(VISIT_KEY, JSON.stringify({ key: made.key, day: made.day, at: active, best, data }));
  } catch { /* storage is off */ }
}
function lastVisit() {
  try {
    const visit = JSON.parse(sessionStorage.getItem(VISIT_KEY));
    return resumable(visit, { key: visitKey(state), day: today(), now: Date.now() }) ? visit : null;
  } catch { return null; }
}
const leave = () => { keepVisit(); keepFresh(true); };
addEventListener('pagehide', leave);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') leave(); });

/* --------------------------------------------------------- finding again */
// The picks shown on each of the last three days, names and all, so one that has since
// rotated away can be found again without searching (visits.js).
const SHOWN_KEY = 'next-watch-shown';
const pastPicks = (() => {
  try { return pruneShown(shownStore(JSON.parse(localStorage.getItem(SHOWN_KEY))), today()); } catch { return shownStore(null); }
})();
function keepShown() {
  try { localStorage.setItem(SHOWN_KEY, JSON.stringify(pastPicks)); } catch { /* full or off */ }
}

/* --------------------------------------------------------------- theme */
const setTheme = mode => {
  document.documentElement.dataset.theme = mode;
  $('theme').setAttribute('aria-label', mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  try { localStorage.setItem('next-watch-theme', mode); } catch { /* ignore */ }
};
setTheme(localStorage.getItem('next-watch-theme') === 'dark' ? 'dark' : 'light');
$('theme').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

/* ---------------------------------------------------------------- tabs */
// The tab lives in the path (/saved, /taste, /shows; Watch next is /), so a refresh
// or a bookmark lands on the same one. Replaced in place, so Back still leaves the
// app rather than walking through tabs. The fragment stays for transfer links.
function show(name) {
  tab = name;
  for (const section of TABS) $(section).hidden = section !== name;
  for (const t of document.querySelectorAll('.tab')) t.setAttribute('aria-selected', String(t.dataset.tab === name));
  if (name === 'taste') renderFit();
  if (name === 'saved') renderSaved();
  document.documentElement.scrollTop = document.body.scrollTop = 0;
  const path = name === 'next' ? '/' : `/${name}`;
  if (location.pathname !== path) history.replaceState(null, '', path + location.search + location.hash);
}
const TABS = ['next', 'saved', 'taste', 'shows'];
const firstTab = () => {
  const name = location.pathname.slice(1);
  return TABS.includes(name) ? name : 'next';
};
for (const t of document.querySelectorAll('.tab')) {
  t.addEventListener('click', () => show(t.dataset.tab));
  t.addEventListener('keydown', e => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = TABS[(TABS.indexOf(t.dataset.tab) + step + TABS.length) % TABS.length];
    show(next);
    document.querySelector(`[data-tab="${next}"]`).focus();
  });
}

/* -------------------------------------------------------------- dialogs */
for (const b of document.querySelectorAll('[data-close]')) b.addEventListener('click', () => b.closest('dialog').close());
for (const d of document.querySelectorAll('dialog')) {
  d.addEventListener('click', e => { if (e.target === d) d.close(); });
}
$('open-about').addEventListener('click', () => $('about').showModal());
$('open-tune').addEventListener('click', () => $('tune').showModal());

/* --------------------------------------------------------------- list */
function has(id) { return state.profile.some(p => p.id === id); }

function add(showRow, weight = .7, how = 'merge') {
  if (has(showRow.id)) return;
  state.saved = state.saved.filter(s => s.id !== showRow.id);
  if (state.profile.length >= LIMITS.rated) {
    note(`Your list is full at ${LIMITS.rated.toLocaleString()} shows. Remove one first.`);
    return;
  }
  state.profile.push({ id: showRow.id, name: showRow.name, year: showRow.year, channel: showRow.channel, weight });
  engage(showRow.id);
  save(); renderList(); renderPicks(); run(0, how);
}
function rate(id, weight) {
  const found = state.profile.find(p => p.id === id);
  if (!found) return;
  found.weight = weight;
  engage(id);
  keepSimilar(); save(); renderList(); run(160, 'merge');
}
function remove(id) {
  state.profile = state.profile.filter(p => p.id !== id);
  keepSimilar(); save(); renderList(); renderPicks(); run(0, 'merge');
}

/* ------------------------------------------------------ more like this */
// Which liked shows the picks are matched to. Empty means all of them, which is
// the plain ranking. It lives here and not in settings: it points at rows of the
// list, so it stays on this device and never rides in a transfer link.
function likedShows() { return state.profile.filter(p => p.weight > 0); }

function keepSimilar() { state.similar_to = prune(state.profile, state.similar_to); }
function chooseSimilar(id, on) {
  state.similar_to = on ? [...state.similar_to, id] : state.similar_to.filter(c => c !== id);
  keepSimilar(); save();
  // Updated in place, not rebuilt, so the box a keyboard user just toggled keeps focus.
  $('list').querySelector(`.item[data-id="${id}"]`)?.classList.toggle('chosen', state.similar_to.includes(id));
  renderSimilar();
  run();
}
function useAllShows() {
  state.similar_to = [];
  save(); renderList(); run();
  $(tab).focus();
}
function goChoose(toChosen) {
  show('shows');
  const boxes = [...$('list').querySelectorAll('input[data-similar]')];
  ((toChosen && boxes.find(b => b.checked)) || boxes[0])?.focus();
}
// One line on Watch next saying what the picks are matched to, and its twin on
// Your shows. Both read from state, so a tick shows before the picks arrive.
function renderSimilar() {
  const liked = likedShows();
  const names = state.similar_to.map(id => state.profile.find(p => p.id === id)?.name).filter(Boolean);
  const on = names.length > 0;
  const all = liked.length === 2 ? 'both shows you liked' : `all ${liked.length.toLocaleString()} shows you liked`;
  for (const id of ['scope', 'similar-meta']) {
    $(id).hidden = liked.length < 2;
    $(id).classList.toggle('on', on);
  }
  const said = {
    'scope-said': on ? `Similar to just ${few(names)}. ` : `Similar to ${all}. `,
    'similar-said': on ? `Picks are similar to just ${few(names)}. `
      : `Picks are similar to ${all}. ${liked.length === 2
        ? 'Tick More like this on either one to match just it.'
        : 'Tick More like this on any of them to match just the ones you choose.'}`,
  };
  // #similar-said is a live region: rewritten only when the sentence changes.
  for (const [id, text] of Object.entries(said)) if ($(id).textContent !== text) $(id).textContent = text;
  const acts = $('scope-acts');
  acts.replaceChildren();
  if (on) acts.append(button('Change', 'link', () => goChoose(true)), ' · ', button('Use all my shows', 'link', useAllShows));
  else acts.append(button('Narrow it down', 'link', () => goChoose(false)));
  const mine = $('similar-acts');
  mine.replaceChildren();
  if (on) mine.append(button('See picks', 'link', () => { show('next'); $('next').focus(); }), ' · ',
                      button('Use all my shows', 'link', useAllShows));
}

/* -------------------------------------------------------------- search */
// The server forgives typos, spacing and other titles, and asks TVmaze about shows
// too new for the catalogue, so a search here rarely comes back empty.
$('q').addEventListener('input', () => {
  const query = $('q').value.trim();
  const id = ++searchId;
  clearTimeout(searchTimer); searchAbort?.abort();
  $('clear-q').hidden = !query;
  if (!query) { closeDrop(); return; }
  // One character finds only a show of that one letter, such as V, so it searches
  // quietly and shows the list only when there is one.
  const quiet = query.length < 2;
  if (!quiet) openDrop('Searching…');
  searchTimer = setTimeout(async () => {
    searchAbort = new AbortController();
    try {
      const res = await fetch('/api/search?q=' + encodeURIComponent(query), { signal: searchAbort.signal });
      const body = await res.json();
      if (id !== searchId) return;
      if (!res.ok) throw new Error(body.error || 'Search is unavailable.');
      if (quiet && !body.shows.length) closeDrop();
      else renderHits(body, query);
    } catch (e) {
      if (e.name !== 'AbortError' && id === searchId && !quiet) openDrop(e.message);
    }
  }, 180);
});
$('clear-q').addEventListener('click', () => {
  $('q').value = ''; $('clear-q').hidden = true; closeDrop(); $('q').focus();
});
$('q').addEventListener('keydown', e => {
  if (e.key === 'Escape') { $('q').value = ''; $('clear-q').hidden = true; closeDrop(); }
  if (e.key === 'ArrowDown' && !$('drop').hidden) { e.preventDefault(); stepHits(-1, 1); }
});
// Arrow keys move between results, and up from the first returns to the box.
$('hits').addEventListener('keydown', e => {
  const rows = [...$('hits').querySelectorAll('.hit:not([disabled])')];
  const at = rows.indexOf(document.activeElement);
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); stepHits(at, e.key === 'ArrowDown' ? 1 : -1); }
  if (e.key === 'Escape') { closeDrop(); $('q').focus(); }
});
function stepHits(at, step) {
  const rows = [...$('hits').querySelectorAll('.hit:not([disabled])')];
  const next = at + step;
  if (next < 0) $('q').focus();
  else rows[Math.min(next, rows.length - 1)]?.focus();
}
document.addEventListener('click', e => {
  if (!e.target.closest('.top')) closeDrop();
});

function openDrop(message) {
  $('drop').hidden = false;
  $('q').setAttribute('aria-expanded', 'true');
  $('hint').textContent = message || '';
  if (message) { $('hits').replaceChildren(); $('missing').hidden = true; }
}
function closeDrop() {
  $('drop').hidden = true;
  $('q').setAttribute('aria-expanded', 'false');
}
function renderHits({ shows, missing = [], missing_first: first = false }, query) {
  // Checking the spelling is suggested only when neither the catalogue, typos and all,
  // nor TVmaze found anything.
  openDrop(shows.length ? '' : missing.length ? `Nothing in the catalogue matches “${query}” yet.`
    : `No show matches “${query}”. Check the spelling.`);
  // A show too new for the catalogue goes first when it is TVmaze's best match.
  $('drop').insertBefore($('missing'), first ? $('hits') : null);
  const list = $('hits');
  list.replaceChildren();
  for (const s of shows) {
    const li = el('li');
    const already = has(s.id);
    const row = button('', 'hit', () => { add(s); $('q').value = ''; $('clear-q').hidden = true; closeDrop(); });
    row.append(el('b', s.name), el('small', meta(s)));
    if (s.aka) row.append(el('small', `Also known as ${s.aka}`, 'aka'));
    row.append(el('em', already ? 'Added' : 'Add'));
    row.disabled = already;
    row.setAttribute('role', 'option');
    row.setAttribute('aria-label', [`${already ? 'Already added' : 'Add'} ${s.name}`, s.aka ? `also known as ${s.aka}` : '',
      meta(s)].filter(Boolean).join(', '));
    li.append(row);
    list.append(li);
  }
  renderMissing(missing);
}
// Shows TVmaze has that the catalogue does not yet: named, with a link to TVmaze.
function renderMissing(missing) {
  $('missing').hidden = !missing.length;
  $('missing-list').replaceChildren(...missing.map(m => {
    const li = el('li');
    const link = el('a', 'See it on TVmaze');
    link.href = m.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', `${m.name} on TVmaze, opens in a new tab`);
    li.append(el('b', m.name), el('small', m.year ? String(m.year) : 'New'), link);
    return li;
  }));
}

/* --------------------------------------------------------- quick picks */
// First-visit shows come from /api/starters: drawn for this browser and day across
// distinct kinds of show, three swapping for related and unexplored ones each time a
// show is added (starters.py says how). The quick picks the server filled in stand in
// when the request fails. The strip stays until the list holds ten shows, where five to
// ten gives the sharpest picks, or until Done adding. The day's seed comes from the
// fresh store's salt, like the picks'; without one the server gives the plain screen.
const STARTERS_UNTIL = 10;
const starters = { shows: [], round: 0, asked: '', req: 0, seed: null, done: false };
const startersPicked = () => state.profile.map(p => p.id).slice(0, MAX_PICKED);

function renderPicks() {
  const open = !starters.done && state.profile.length < STARTERS_UNTIL;
  $('starters').hidden = !open;
  if (!open) return;
  const asking = `${starters.round}|${startersPicked().join(',')}`;
  if (asking !== starters.asked) loadStarters(asking);
  drawStarters();
}

async function loadStarters(asking) {
  starters.asked = asking;
  const id = ++starters.req;
  starters.seed ??= fresh ? seedFor(fresh.salt, today()).catch(() => '') : Promise.resolve('');
  const query = startersQuery({ seed: await starters.seed, round: starters.round, picked: startersPicked(),
                                lang: browserLanguage() });
  try {
    const res = await fetch('/api/starters?' + query);
    const body = await res.json();
    if (id !== starters.req) return;
    if (!res.ok) throw new Error(body.error);
    starters.shows = mergeStarters(starters.shows, body.shows, has);
  } catch {
    if (id !== starters.req) return;
    starters.asked = '';
    if (!starters.shows.length) starters.shows = boot.picks;
  }
  drawStarters();
}

function drawStarters() {
  const holder = $('picks');
  holder.replaceChildren();
  for (const s of starters.shows) {
    const chip = button(s.name, 'chip', () => add(s, 1));
    chip.setAttribute('aria-pressed', String(has(s.id)));
    chip.disabled = has(s.id);
    holder.append(chip);
  }
  const n = state.profile.length;
  const hint = !n ? 'Tap to add, or search above.'
    : n < 5 ? `${n} added. Five to ten shows gives the sharpest picks.`
      : `${n} added. Add a few more, or read on.`;
  // A live region, so it is rewritten only when the sentence changes.
  if ($('starters-hint').textContent !== hint) $('starters-hint').textContent = hint;
  $('starters-done').hidden = !n;
}
$('starters-more').addEventListener('click', () => {
  starters.round = (starters.round + 1) % (MAX_ROUND + 1);
  renderPicks();
});
$('starters-done').addEventListener('click', () => {
  starters.done = true;
  renderPicks();
  $('next').focus();
});

/* ------------------------------------------------------------ requests */
function note(text, bad = false) {
  $('next-meta').textContent = text;
  $('next-meta').classList.toggle('error', bad);
}
// How the next answer is shown (visits.js). 'hold', after Seen it or Not for me, keeps
// every other card where it is; 'merge', after a rating or a show added or removed
// elsewhere, keeps where they are the cards the answer still holds; 'full', after
// settings, the shows to match or a list brought in, lays the picks out afresh. A
// stronger one still waiting outlasts a weaker one asked for after it.
const LAYOUTS = ['hold', 'merge', 'full'];
let layout = 'full';
let added = 0;   // picks the last answer added at the end of the list
let best = 1;    // the answer's best score, which every match figure is measured against

// 'resume' shows the visit kept for this tab when it can (see visits).
function run(delay = 160, how = 'full') {
  const id = ++reqId;
  clearTimeout(timer); reqAbort?.abort();
  const liked = state.profile.filter(p => p.weight > 0).length;
  $('onboard').hidden = liked > 0;
  $('next-body').hidden = liked === 0;
  renderCount();
  if (!liked) { data = null; renderList(); return; }
  const visit = how === 'resume' ? lastVisit() : null;
  if (visit) { showAnswer(visit.data, [], { key: visit.key, day: visit.day, top: visit.best }); return; }
  if (LAYOUTS.indexOf(how) > LAYOUTS.indexOf(layout)) layout = how;
  note('Working out your picks…');
  timer = setTimeout(async () => {
    reqAbort = new AbortController();
    const { signal } = reqAbort;
    try {
      // The list goes packed as ids and a character a rating (transfer.js), a quarter of the bytes.
      const ask = { profile: packList(state.profile), settings: state.settings,
                    similar_to: state.similar_to, ...await freshFields() };
      if (id !== reqId) return;
      const res = await fetch('/api/recommend', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal, body: JSON.stringify(ask),
      });
      const body = await res.json();
      if (id !== reqId) return;
      if (!res.ok) throw new Error(body.error || 'Could not work out your picks.');
      // Nothing rated stays on screen, whatever the layout.
      const before = layout === 'full' ? [] : (data?.picks || []).filter(p => !has(p.id));
      const hold = layout === 'hold';
      layout = 'hold';
      state.settings = body.settings;
      save();
      showAnswer(body, before, { key: visitKey(state), day: ask.day || today(), hold });
    } catch (e) {
      if (e.name === 'AbortError' || id !== reqId) return;
      note(e.message || 'Could not reach the recommender.', true);
    }
  }, delay);
}

// An answer on screen: merged into the picks already shown, when there are some to keep
// (visits.js), and kept for this tab so a reload shows the same. `top` is the best score
// of a kept visit's own answer, which its merged picks cannot be relied on to hold.
function showAnswer(answer, before, { key, day, hold = false, top }) {
  best = top > 0 ? top : Math.max(0, ...answer.picks.map(p => p.score)) || 1;
  data = answer;
  const had = new Set(before.map(p => p.id));
  if (before.length) data.picks = merge(before, answer.picks, { hold });
  added = before.length ? data.picks.filter(p => !had.has(p.id)).length : 0;
  made = { key, day };
  render();
  keepVisit();
}

/* -------------------------------------------------------------- render */
function render() {
  renderCards();
  renderTaste();
  renderCount();
  note(data.picks.length
    ? `${data.picks.length} picks from ${data.candidate_count.toLocaleString()} shows that fit your filters.${
      added ? ` ${added === 1 ? 'One new pick' : `${added} new picks`} at the end.` : ''}`
    : '');
}
function renderCount() {
  const n = state.profile.length;
  $('tab-count').textContent = n ? n.toLocaleString() : '';
  $('tab-count').hidden = !n;
  $('saved-count').textContent = state.saved.length || '';
  $('saved-count').hidden = !state.saved.length;
}

function isSaved(id) { return state.saved.some(s => s.id === id); }

function toggleSave(pick) {
  engage(pick.id);
  state.saved = isSaved(pick.id)
    ? state.saved.filter(s => s.id !== pick.id)
    : [...state.saved, { id: pick.id, name: pick.name, year: pick.year, channel: pick.channel,
                         rating: pick.rating, url: pick.url }];
  save();
  renderCount();
  if (data) renderCards();
  renderSaved();
}

function renderSaved() {
  const holder = $('saved-list');
  holder.replaceChildren();
  $('clear-saved').hidden = !state.saved.length;
  $('saved-meta').textContent = state.saved.length
    ? `${state.saved.length} to watch. Rating one moves it into your shows, where it starts shaping the picks.`
    : 'Nothing saved yet. Hit Save on any pick and it waits for you here.';
  for (const s of state.saved) {
    const card = el('article', '', 'card');
    const top = el('div', '', 'card-top');
    const title = el('div', '', 'card-title');
    const heading = el('h3');
    heading.append(tvmaze(s.name, s));
    title.append(heading, el('p', meta(s)));
    top.append(title);
    const acts = el('div', '', 'acts');
    const watched = button('I watched it', 'why', () => { toggleSave(s); add(s, .7); show('shows'); });
    watched.setAttribute('aria-label', `Move ${s.name} into your shows as liked`);
    acts.append(watched, button('Remove', '', () => toggleSave(s)));
    card.append(top, acts);
    holder.append(card);
  }
}
$('clear-saved').addEventListener('click', () => { state.saved = []; save(); renderCount(); renderSaved(); if (data) renderCards(); });

// Theme and genre names overlap ("Crime / illicit enterprise" and the Crime tag): show each once.
function sharedLabels(pick) {
  const out = [];
  for (const name of [...pick.shared_themes.map(short), ...pick.shared_genres]) {
    if (!out.some(seen => seen.toLowerCase() === name.toLowerCase())) out.push(name);
  }
  return out;
}

const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const decadeOf = l => l.startsWith('before') ? l : `the ${l}`;
// A leaning as a heading: networks, languages and decades read as they would aloud.
const HEADING = {
  language: l => `In ${l}`, network: l => `On ${l}`, decade: l => `From ${decadeOf(l)}`,
  length: l => `${cap(l)} episodes`, country: l => `${l} shows`, theme: l => short(l),
};
const heading = f => (HEADING[f.family] || cap)(f.label);
// The same, inside a sentence: "fits your taste for crime, HBO and the 2000s".
const WITHIN = {
  language: l => `shows in ${l}`, network: l => l, decade: l => decadeOf(l), country: l => `${l} shows`,
  length: l => `${l} episodes`, theme: l => short(l).toLowerCase(), format: l => l.toLowerCase(),
  genre: l => l.toLowerCase(),
};
const within = f => (WITHIN[f.family] || (l => l))(f.label);
const listed = words => words.length > 1 ? `${words.slice(0, -1).join(', ')} and ${words.at(-1)}` : words[0] || '';
// What two shows concretely share, as it would be said.
const TIE = {
  franchise: l => `Part of ${l}`, maker: l => `By ${l}`, cast: l => `With ${l}`, fans: () => 'Its fans look this up too',
  network: l => `Also on ${l}`, genre: l => cap(l), subject: l => cap(l),
};
const tie = t => (TIE[t.family] || cap)(t.label);
const interestName = (it, names) => it.leans.length ? it.leans.map(l => cap(short(l))).join(' · ') : `Like ${names[0]}`;

// Measured against the answer's best score, not the first card's: the first five can
// trade places as they are shown day after day.
function matchOf(pick) {
  return Math.max(1, Math.min(99, Math.round(pick.score / best * 99)));
}

// A link to a show's TVmaze page. Opening it, by click or middle click, is engaging with it.
function tvmaze(text, show, label = `${show.name} on TVmaze, opens in a new tab`) {
  const out = el('a', text);
  out.href = show.url; out.target = '_blank'; out.rel = 'noopener noreferrer';
  if (label) out.setAttribute('aria-label', label);
  out.addEventListener('click', () => engage(show.id));
  out.addEventListener('auxclick', e => { if (e.button === 1) engage(show.id); });
  return out;
}

// Seen it and Not for me take the pick off the list at once; the answer that follows
// fills in at the end, and no other card moves.
function dismiss(pick, weight) {
  add(pick, weight, 'hold');
  if (!has(pick.id) || !data) return;   // the list is full, so nothing was added
  data.picks = data.picks.filter(p => p.id !== pick.id);
  renderCards();
}

// The latest details of a pick on screen, which its card may have been drawn before.
const current = pick => data?.picks.find(p => p.id === pick.id) || pick;

// Each pick's card. One is replaced only when what it shows changed, and moved only when
// out of place, so a merge leaves the rest of the list, and whatever has focus, alone.
let cards = new Map();
function renderCards() {
  const holder = $('cards');
  $('warn').hidden = !data.warning;
  $('warn').textContent = data.warning;
  $('none').hidden = !data.message;
  $('none').textContent = data.message;
  const focus = focusIn(holder);
  const next = new Map();
  for (const pick of data.picks) {
    const card = pickCard(pick), had = cards.get(pick.id);
    next.set(pick.id, had?.outerHTML === card.outerHTML ? had : card);
  }
  for (const [id, card] of cards) if (next.get(id) !== card) card.remove();
  [...next.values()].forEach((card, n) => {
    if (holder.children[n] !== card) holder.insertBefore(card, holder.children[n] || null);
  });
  cards = next;
  refocus(focus, holder);
  for (const [id, card] of cards) impressions?.observe(card, id);
  if (noteShown(pastPicks, today(), data.picks)) keepShown();
  renderEarlier();
}

// Where focus sits among the cards, so it can be handed on when its card is redrawn or leaves.
function focusIn(holder) {
  const now = document.activeElement;
  const card = now && holder.contains(now) ? now.closest('.card') : null;
  return card && { id: Number(card.dataset.id), act: now.dataset.act, at: [...holder.children].indexOf(card) };
}
// Back to the same control on a redrawn card; to the card that took its place when it
// left, or the one before it when it was the last.
function refocus(focus, holder) {
  if (!focus || holder.contains(document.activeElement)) return;
  const same = cards.get(focus.id);
  const target = same ? same.querySelector(`[data-act="${focus.act}"]`) || same
    : holder.children[Math.min(focus.at, holder.children.length - 1)] || $('next');
  target.focus();
}

function pickCard(pick) {
  const different = pick.place === 'different';
  const card = el('article', '', different ? 'card different' : 'card');
  card.dataset.id = pick.id;
  card.tabIndex = -1;
  card.setAttribute('aria-label', pick.name);
  if (different) card.append(el('p', 'A little different', 'kicker'));
  const top = el('div', '', 'card-top');
  const title = el('div', '', 'card-title');
  const heading = el('h3');
  const out = tvmaze(pick.name, pick);
  out.dataset.act = 'title';
  heading.append(out);
  title.append(heading, el('p', [meta(pick), pick.runtime ? pick.runtime + ' min' : null].filter(Boolean).join(' · ')));
  const score = el('div', '', 'score');
  score.append(el('b', String(matchOf(pick))), el('span', 'match'));
  top.append(title, score);

  const because = el('p', '', 'because');
  because.append(document.createTextNode('Closest to '), el('b', pick.because));
  if (pick.ties?.length) because.append(el('span', ` · ${pick.ties.slice(0, 2).map(tie).join(' · ')}`, 'ties'));
  const tags = el('div', '', 'tags');
  for (const name of sharedLabels(pick).slice(0, 3)) tags.append(el('span', name, 'tag'));
  if (!tags.childElementCount) tags.append(el('span', 'a close match on plot wording', 'tag plain'));

  const acts = el('div', '', 'acts');
  const keep = button(isSaved(pick.id) ? 'Saved ✓' : 'Save', '', () => toggleSave(pick));
  keep.classList.toggle('on', isSaved(pick.id));
  keep.setAttribute('aria-pressed', String(isSaved(pick.id)));
  const controls = [['why', button('Why this?', 'why', () => openWhy(current(pick)))], ['save', keep],
    ['seen', button('Seen it', '', () => dismiss(pick, 0))], ['no', button('Not for me', '', () => dismiss(pick, -1))]];
  for (const [act, control] of controls) {
    control.dataset.act = act;
    acts.append(control);
  }

  card.append(top, because, tags);
  if (pick.fits?.length) card.append(el('p', `Fits your taste for ${listed(pick.fits.map(within))}.`, 'fits'));
  if (pick.summary) card.append(el('p', pick.summary, 'blurb'));
  card.append(acts);
  return card;
}

function openWhy(pick) {
  engage(pick.id);
  const body = $('why-body');
  body.replaceChildren();
  body.append(el('h3', pick.name, 'why-head'));
  body.append(el('p', `${matchOf(pick)} match · rank ${pick.rank} · ${meta(pick)}`, 'why-sub'));

  const shared = sharedLabels(pick);
  const block = el('div', '', 'why-block');
  block.append(el('h4', 'Why it surfaced'));
  block.append(el('p', shared.length
    ? `It sits closest to ${pick.because}, sharing ${shared.join(', ').toLowerCase()}.`
    : `It sits closest to ${pick.because} on plot wording rather than on shared themes or genres.`));
  if (pick.ties?.length) {
    block.append(el('p', `Shared with ${pick.because}: ${pick.ties.map(tie).join(' · ')}.`));
  }
  if (pick.fits?.length) {
    block.append(el('p', `It fits what your list leans toward: ${listed(pick.fits.map(within))}.`));
  }
  const interest = data.interests?.length > 1 && pick.interest != null ? data.interests[pick.interest] : null;
  if (interest) {
    const names = interest.shows.map(id => data.liked.find(s => s.id === id)?.name).filter(Boolean);
    // A long list's interest names a dozen of its shows and says how many it holds.
    const size = Math.max(interest.size || 0, names.length);
    const who = `${listed(names.slice(0, 3))}${size > 3 ? ` and ${(size - Math.min(3, names.length)).toLocaleString()} more` : ''}`;
    block.append(el('p', `Your list holds more than one interest, and this pick is for the one ${who} `
      + `${size > 1 ? 'share' : 'stands for'}: ${interestName(interest, names)}.`));
  }
  body.append(block);
  if (pick.place === 'different') {
    const aside = el('div', '', 'why-block');
    aside.append(el('h4', 'A little different'), el('p', 'Two places a day go to shows from a little further down '
      + 'your ranking than the rest, so the list never settles into one groove. This is one of them.'));
    body.append(aside);
  }

  if (pick.keywords.length) {
    const words = el('div', '', 'why-block');
    words.append(el('h4', 'What its plot is about'));
    const tags = el('div', '', 'tags');
    for (const k of pick.keywords) tags.append(el('span', k, 'tag plain'));
    words.append(tags);
    body.append(words);
  }
  if (pick.summary) {
    const plot = el('div', '', 'why-block');
    plot.append(el('h4', 'Summary'), el('p', pick.summary));
    body.append(plot);
  }
  if (pick.penalised) {
    const down = el('div', '', 'why-block');
    down.append(el('h4', 'Held back'), el('p', `Docked ${pick.penalised} points for looking like shows you disliked.`));
    body.append(down);
  }
  const links = el('div', '', 'why-block');
  links.append(tvmaze('Open on TVmaze ↗', pick, null));
  body.append(links);

  const jump = el('div', '', 'why-block');
  jump.append(button('See how it lines up with your taste →', 'link', () => {
    fitPick = pick.id;
    $('fit-pick').value = String(pick.id);
    $('why').close();
    show('taste');
  }));
  body.append(jump);
  $('why').showModal();
}

/* ------------------------------------------------------ yesterday's picks */
// The picks of the last day before today that have rotated away since and are not
// rated, so one seen then can be found again: added to your shows once watched, or saved.
function earlierPicks() {
  const showing = new Set(data?.picks.map(p => p.id) || []);
  return lastShown(pastPicks, today(), p => !has(p.id) && !showing.has(p.id));
}
function renderEarlier() {
  const found = earlierPicks();
  $('earlier').hidden = !found;
  if (found) $('open-earlier').textContent = `${dayName(found)}'s picks`;
}
function fillEarlier() {
  const list = $('earlier-list');
  const now = document.activeElement;
  const row = now && list.contains(now) ? now.closest('li') : null;
  const focus = row && { id: Number(row.dataset.id), act: now.dataset.act, at: [...list.children].indexOf(row) };
  const found = earlierPicks();
  if (found) $('earlier-h').textContent = `${dayName(found)}'s picks`;
  list.replaceChildren(...(found?.picks || []).map(p => {
    const item = el('li');
    item.dataset.id = p.id;
    const name = el('div', '', 'earlier-name');
    const title = p.url ? tvmaze(p.name, p) : el('span', p.name);
    title.dataset.act = 'title';
    name.append(title, el('small', meta(p)));
    const adding = button('Add', 'ghost', () => {
      add(p);
      if (has(p.id)) $('earlier-said').textContent = `Added ${p.name} to your shows.`;
      fillEarlier();
    });
    adding.dataset.act = 'add';
    adding.setAttribute('aria-label', `Add ${p.name} to your shows as liked`);
    const keep = button(isSaved(p.id) ? 'Saved ✓' : 'Save', 'ghost', () => { toggleSave(p); fillEarlier(); });
    keep.dataset.act = 'save';
    keep.classList.toggle('on', isSaved(p.id));
    keep.setAttribute('aria-pressed', String(isSaved(p.id)));
    const acts = el('div', '', 'earlier-acts');
    acts.append(adding, keep);
    item.append(name, acts);
    return item;
  }));
  $('earlier-none').hidden = Boolean(found);
  // An added show leaves the list: focus moves to the title of the one that took its
  // place, never to another Add, so a second press cannot add a second show.
  if (focus && !list.contains(document.activeElement)) {
    const same = [...list.children].find(item => Number(item.dataset.id) === focus.id);
    const target = same ? same.querySelector(`[data-act="${focus.act}"]`)
      : list.children[Math.min(focus.at, list.children.length - 1)]?.querySelector('[data-act="title"]');
    (target || $('earlier-sheet').querySelector('[data-close]')).focus();
  }
}
$('open-earlier').addEventListener('click', () => {
  $('earlier-said').textContent = '';
  fillEarlier();
  $('earlier-sheet').showModal();
});

/* --------------------------------------------------------------- taste */
function renderTaste() {
  const themes = data.features.filter(f => f.group === 'themes').slice(0, 3);
  const genre = data.features.find(f => f.group === 'genres');
  const words = themes.map(f => short(f.name).toLowerCase());
  const phrase = words.length > 1 ? words.slice(0, -1).join(', ') + ' and ' + words.at(-1) : words[0];
  $('verdict').textContent = words.length
    ? `Your shows keep coming back to ${phrase}${genre ? `, mostly ${genre.name.toLowerCase()}` : ''}.`
    : 'Rate a few more shows and a pattern will show up here.';
  const [tn, tt] = data.breadth.themes, [gn, gt] = data.breadth.genres;
  $('context').textContent = [
    ...data.context.map(c => `${c.count} of ${c.of} ${c.label === 'format' ? '' : 'in '}${c.value}`.replace('  ', ' ')),
    `spanning ${tn} of ${tt} themes and ${gn} of ${gt} genres`,
  ].join(' · ');
  renderSignals();
  renderLeanings();

  const select = $('fit-pick');
  select.replaceChildren();
  for (const p of data.picks) {
    const option = el('option', `${p.name}${p.year ? ` (${p.year})` : ''}`);
    option.value = p.id;
    select.append(option);
  }
  if (!data.picks.some(p => p.id === fitPick)) fitPick = data.picks[0]?.id ?? null;
  if (fitPick) select.value = fitPick;

  // "Also plot" lets you hold the pick against one show you already rated.
  const against = $('fit-vs');
  const previous = against.value;
  against.replaceChildren();
  const auto = el('option', 'Closest show in your list');
  auto.value = 'closest';
  const none = el('option', 'Nothing');
  none.value = 'none';
  against.append(auto, none);
  for (const s of data.liked) {
    const option = el('option', `${s.name}${s.year ? ` (${s.year})` : ''}`);
    option.value = s.id;
    against.append(option);
  }
  against.value = [...against.options].some(o => o.value === previous) ? previous : 'closest';

  if (tab === 'taste') renderFit();
}

// What the list leans toward and away from, and the interests it holds.
function renderLeanings() {
  const taste = data.taste || { leans: [], avoids: [] };
  const leans = $('leans');
  leans.replaceChildren();
  for (const f of taste.leans) {
    const item = el('li');
    item.append(el('b', heading(f)), el('span', `${f.shows} of your liked shows · ${f.base}% of all shows`));
    leans.append(item);
  }
  $('leans-none').hidden = taste.leans.length > 0;

  const avoids = $('avoids');
  avoids.replaceChildren();
  for (const f of taste.avoids) {
    const item = el('li');
    item.append(el('b', heading(f)), el('span', f.why === 'disliked' ? `You disliked ${f.shows}` : 'None on your list'));
    avoids.append(item);
  }
  $('avoids-box').hidden = taste.avoids.length === 0;

  const interests = $('interests');
  interests.replaceChildren();
  const found = data.interests || [];
  for (const it of found) {
    const names = it.shows.map(id => data.liked.find(s => s.id === id)?.name).filter(Boolean);
    const item = el('li');
    const more = (it.size || 0) > names.length ? ` and ${(it.size - names.length).toLocaleString()} more` : '';
    item.append(el('b', interestName(it, names)), el('span', names.join(', ') + more));
    interests.append(item);
  }
  $('interests-box').hidden = found.length < 2;
}

function renderSignals() {
  const holder = $('signals');
  holder.replaceChildren();
  const shown = new Set();
  const unique = data.features.filter(f => {
    const label = short(f.name).toLowerCase();
    return shown.has(label) ? false : shown.add(label);
  });
  const rows = allSignals ? unique : unique.slice(0, 8);
  for (const f of rows) {
    const row = el('div', '', 'sig');
    row.append(el('span', short(f.name), 'sig-name'),
      el('span', f.lift ? `${f.lift}× typical` : '', 'sig-lift'));
    const track = el('div', '', 'track');
    const fill = el('i');
    fill.style.setProperty('--w', f.share + '%');
    track.append(fill);
    row.append(track);
    row.setAttribute('role', 'img');
    row.setAttribute('aria-label', `${short(f.name)}: in ${f.count} of your ${data.positive_count} liked shows${f.lift ? `, ${f.lift} times the catalog average` : ''}`);
    holder.append(row);
  }
  const more = $('more-signals');
  more.hidden = unique.length <= 8;
  more.textContent = allSignals ? 'Show the strongest 8' : `Show all ${unique.length} signals`;
  more.setAttribute('aria-expanded', String(allSignals));
}
$('more-signals').addEventListener('click', () => { allSignals = !allSignals; renderSignals(); });

function renderFit() {
  if (!data || !data.picks.length) return;
  const pick = data.picks.find(p => p.id === Number($('fit-pick').value)) || data.picks[0];
  fitPick = pick.id;
  $('fit-score').textContent = `${matchOf(pick)} match · rank ${pick.rank}`;

  const choice = $('fit-vs').value;
  const other = choice === 'none' ? null
    : choice === 'closest' ? data.liked[pick.links.indexOf(Math.max(...pick.links))]
      : data.liked.find(s => s.id === Number(choice));

  const rows = fitRows(data.liked, pick, other, $('fit-kind').value, boot.themes, boot.genres, data.fit);
  const spokes = chooseSpokes(rows, Number($('fit-count').value));
  drawFit($('fit'), $('fit-frame'), $('fit-key'), spokes,
    { you: 'your taste', them: pick.name, vs: other ? other.name : '' });

  $('fit-name').textContent = pick.name;
  $('fit-vs-legend').hidden = !other;
  $('fit-vs-name').textContent = other ? other.name : '';

  const names = list => list.map(s => short(s.name).toLowerCase()).join(', ');
  const strong = spokes.filter(s => s.them && s.you >= 45);
  const fresh = spokes.filter(s => s.them && s.you < 45);
  const absent = spokes.filter(s => !s.them && s.you >= 50);
  const withOther = other ? spokes.filter(s => s.them && s.vs === 100) : [];
  $('fit-note').textContent = [
    strong.length ? `Familiar ground: ${names(strong)}.` : '',
    fresh.length ? `New for you: ${names(fresh)}.` : '',
    absent.length ? `Missing your usual ${names(absent)}.` : '',
    other ? (withOther.length
      ? `Shares ${names(withOther)} with ${other.name}.`
      : `Shares no plotted signal with ${other.name}.`) : '',
  ].filter(Boolean).join(' ') || 'This pick matches on plot wording rather than on recorded themes or genres.';

  renderRelate(pick);
}

// One bar per show you rated: how close the pick sits to each of them.
function renderRelate(pick) {
  const pairs = data.liked
    .map((s, i) => ({ ...s, score: pick.links[i] }))
    .sort((a, b) => b.score - a.score);
  const top = pairs[0]?.score || 1;
  $('relate-note').textContent = pairs.length < 2 ? `${pick.name} against the one show you have rated.`
    : data.similar_to.length && pairs[0].id !== pick.because_id
      ? `${pick.name} was picked for ${pick.because}. Across everything you liked it sits closest to ${pairs[0].name}.`
      : `${pick.name} is closest to ${pairs[0].name} and furthest from ${pairs.at(-1).name}.`;
  const holder = $('relate');
  holder.replaceChildren();
  const rows = allRelated ? pairs : pairs.slice(0, 10);
  for (const s of rows) {
    const row = el('div', '', 'sig rel');
    row.append(el('span', s.name, 'sig-name'), el('span', s.score.toFixed(0), 'sig-lift'));
    const track = el('div', '', 'track');
    const fill = el('i');
    fill.style.setProperty('--w', Math.max(2, s.score / top * 100) + '%');
    if (s.id === pick.because_id) fill.classList.add('lead');
    track.append(fill);
    row.append(track);
    row.setAttribute('role', 'img');
    row.setAttribute('aria-label', `${s.name}: similarity ${s.score.toFixed(0)} out of 100`);
    holder.append(row);
  }
  const more = $('more-relate');
  more.hidden = pairs.length <= 10;
  more.textContent = allRelated ? 'Show the closest 10' : `Show all ${pairs.length} shows`;
  more.setAttribute('aria-expanded', String(allRelated));
}
$('more-relate').addEventListener('click', () => { allRelated = !allRelated; renderFit(); });
$('fit-pick').addEventListener('change', renderFit);
for (const id of ['fit-kind', 'fit-count', 'fit-vs']) $(id).addEventListener('change', renderFit);
let fitWidth = 0;
new ResizeObserver(() => {
  const w = $('fit-frame').clientWidth;
  if (w && w !== fitWidth) { fitWidth = w; if (tab === 'taste') renderFit(); }
}).observe($('fit-frame'));

/* ---------------------------------------------------------- your shows */
// The newest first, LIST_PAGE at a time, so a list of thousands draws as fast as one of
// dozens; a long one can also be searched by name.
const LIST_PAGE = 60;
let listShown = LIST_PAGE, listFind = '', listTimer = 0;
const folded = text => (text || '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim();

function renderList() {
  const holder = $('list');
  holder.replaceChildren();
  const liked = likedShows().length;
  $('shows-meta').textContent = state.profile.length
    ? `${state.profile.length.toLocaleString()} rated · ${liked.toLocaleString()} counted as liked. Ratings shape every pick; nothing you rate is recommended back.`
    : 'Nothing here yet. Search at the top to add what you have watched.';
  $('clear-all').hidden = !state.profile.length;
  $('list-find').hidden = state.profile.length <= LIST_PAGE;
  const needle = folded(listFind);
  const found = state.profile.filter(p => !needle || folded(p.name).includes(needle)).reverse();
  const page = found.slice(0, listShown);
  $('list-note').textContent = !state.profile.length ? ''
    : !found.length ? `No show you rated matches “${listFind}”.`
      : found.length > page.length ? `The newest ${page.length.toLocaleString()} of ${found.length.toLocaleString()}.` : '';
  $('list-more').hidden = found.length <= page.length;
  $('list-more').textContent = `Show ${Math.min(LIST_PAGE, found.length - page.length).toLocaleString()} more`;
  for (const p of page) {
    const item = el('div', '', 'item');
    item.dataset.id = p.id;
    const top = el('div', '', 'item-top');
    top.append(el('span', p.name, 'item-name'));
    if (p.weight > 0 && liked > 1) {
      const wrap = el('label', '', 'similar');
      const box = el('input');
      box.type = 'checkbox';
      box.dataset.similar = p.id;
      box.checked = state.similar_to.includes(p.id);
      box.setAttribute('aria-label', `More like this: ${p.name}`);
      box.addEventListener('change', () => chooseSimilar(p.id, box.checked));
      wrap.append(box, 'More like this');
      top.append(wrap);
      item.classList.toggle('chosen', box.checked);
    }
    top.append(button('Remove', 'drop-show', () => remove(p.id)));
    item.append(top, el('p', meta(p), 'item-meta'));
    const seg = el('div', '', 'seg');
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', `Your rating for ${p.name}`);
    for (const [weight, label] of RATINGS) {
      const b = button(label, '', () => rate(p.id, weight));
      b.setAttribute('aria-pressed', String(p.weight === weight));
      b.setAttribute('aria-label', SPOKEN[weight]);
      seg.append(b);
    }
    item.append(seg);
    holder.append(item);
  }
  renderSimilar();
}
$('clear-all').addEventListener('click', () => {
  state.profile = [];
  keepSimilar(); save(); renderList(); renderPicks(); run(0);
});
$('list-more').addEventListener('click', () => {
  listShown += LIST_PAGE;
  renderList();
});
$('list-q').addEventListener('input', () => {
  clearTimeout(listTimer);
  listTimer = setTimeout(() => {
    listFind = $('list-q').value.trim();
    listShown = LIST_PAGE;
    renderList();
  }, 150);
});

/* ------------------------------------------------------- moving devices */
function moveLink() { return `${location.origin}/#t=${encode(state)}`; }

// The QR always carries dark modules on white, whatever the page theme, because a
// camera needs the contrast the spec assumes.
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
  shape.setAttribute('fill', '#16181d');
  const ground = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  ground.setAttribute('width', size);
  ground.setAttribute('height', size);
  ground.setAttribute('fill', '#fff');
  svg.append(ground, shape);
  const version = (grid.length - 17) / 4;
  $('qr-note').textContent = version > 20
    ? 'Point a camera at this. A list this long makes a dense code, so fill the screen with it or send the link instead.'
    : 'Point the other phone\u2019s camera at this.';
}

function openMove() {
  const code = state.profile.length || state.saved.length ? moveLink() : '';
  drawCode(code);
  $('move-link').value = code;
  $('move-count').textContent = code
    ? `${state.profile.length.toLocaleString()} rated and ${state.saved.length} saved, packed into ${
      code.length.toLocaleString()} characters.`
    : 'Nothing to move yet. Rate or save a show first.';
  for (const id of ['copy-link', 'copy-code', 'save-file']) $(id).disabled = !code;
  $('copy-said').textContent = '';
  $('move-status').textContent = '';
  $('move-paste').value = '';
  $('move').showModal();
}
$('open-move').addEventListener('click', openMove);

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
  link.download = `next-watch-list-${today()}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(file), 10_000);
  $('copy-said').textContent = 'Saved. On the other device, open it here with Open a saved file.';
});
$('open-file').addEventListener('click', () => $('move-file').click());
$('move-file').addEventListener('change', async () => {
  const file = $('move-file').files[0];
  $('move-file').value = '';
  if (!file) return;
  if (file.size > 200_000) { $('move-status').textContent = 'That file is too big to be a list.'; return; }
  const raw = codeFrom(await file.text());
  $('move-paste').value = raw;
  try {
    const found = decode(raw);
    $('move-status').textContent = `This file holds ${found.profile.length.toLocaleString()} rated and ${
      found.saved.length} saved. Add them to your list, or replace your list with them.`;
  } catch (e) {
    $('move-status').textContent = e.message || 'That file does not hold a list.';
  }
});

// A pasted link or a bare code both carry the same payload (codeFrom, in transfer.js).

async function bringIn(replace) {
  const raw = codeFrom($('move-paste').value);
  if (!raw) { $('move-status').textContent = 'Paste the link or code first.'; return; }
  $('move-status').textContent = 'Reading it\u2026';
  try {
    await apply(decode(raw), replace);
    $('move').close();
    show('next');
  } catch (e) {
    $('move-status').textContent = e.message || 'That code could not be read.';
  }
}
$('do-merge').addEventListener('click', () => bringIn(false));
$('do-replace').addEventListener('click', () => bringIn(true));

// Titles are not in the code, so the catalog fills them back in on arrival.
async function apply(incoming, replace) {
  const ids = [...new Set([...incoming.profile.map(s => s.id), ...incoming.saved.map(s => s.id)])];
  const res = await fetch('/api/shows', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || 'Could not look those shows up.');
  const known = new Map(body.shows.map(s => [s.id, s]));
  const rated = incoming.profile.filter(s => known.has(s.id))
    .map(s => ({ ...known.get(s.id), weight: s.weight }));
  const kept = incoming.saved.filter(s => known.has(s.id)).map(s => known.get(s.id));
  if (!rated.length && !kept.length) throw new Error('None of those shows are in this catalog.');

  if (replace) {
    state = { profile: rated, saved: kept, settings: { ...DEFAULTS, ...incoming.settings }, similar_to: [] };
  } else {
    const mine = new Set(state.profile.map(s => s.id));
    // Your own ratings win, so merging twice never rewrites what you decided here.
    const profile = [...state.profile, ...rated.filter(s => !mine.has(s.id))];
    const held = new Set(state.saved.map(s => s.id));
    const saved = [...state.saved, ...kept.filter(s => !held.has(s.id))];
    if (profile.length > LIMITS.rated || saved.length > LIMITS.saved)
      throw new Error('Together these lists exceed 3,000 ratings or 200 saved shows. Your current list has not changed. Remove a few shows before adding this copy.');
    state = { ...state, profile, saved };
  }
  keepSimilar(); save(); renderList(); renderSaved(); renderPicks(); syncTune(); run(0);
  const dropped = ids.length - known.size;
  note(`Brought in ${rated.length.toLocaleString()} rated and ${kept.length} saved`
    + `${dropped ? `, and skipped ${dropped} no longer in the catalog` : ''}.`);
}

// A shared link lands here. Pasting one while the app is already open changes the
// fragment without reloading, so the same read runs on hashchange too.
window.addEventListener('hashchange', () => readLink());

async function readLink() {
  const raw = location.hash.startsWith('#t=') ? location.hash.slice(3) : '';
  if (!raw) return;
  history.replaceState(null, '', location.pathname);
  let incoming;
  try {
    incoming = decode(raw);
  } catch (e) {
    note(e.message || 'That shared link could not be read.', true);
    return;
  }
  if (!state.profile.length && !state.saved.length) {
    try {
      await apply(incoming, true);
    } catch (e) {
      $('move-status').textContent = e.message || 'That shared link could not be read.';
      $('move').showModal();
    }
    return;
  }
  $('move-paste').value = raw;
  $('move-status').textContent = `This link holds ${incoming.profile.length.toLocaleString()} rated and `
    + `${incoming.saved.length} saved. You already have a list here, so choose what to do with it.`;
  $('move-link').value = moveLink();
  $('move-count').textContent = `${state.profile.length.toLocaleString()} rated and ${state.saved.length} saved on this device.`;
  $('move').showModal();
}

/* ---------------------------------------------------------------- tune */
// Format is a fixed grouping of the catalogue's 11 television types; the rest are
// filled from the snapshot.
for (const [id, key, values, any] of [['lang', 'language', boot.meta.language, 'Any language'],
                                      ['stat', 'status', boot.meta.status, 'Any status']]) {
  const select = $(id);
  const option = el('option', any);
  option.value = 'all';
  select.append(option);
  for (const value of values) {
    const item = el('option', value);
    item.value = value;
    select.append(item);
  }
}
for (const [id, key] of [['lang', 'language'], ['kind', 'type'], ['stat', 'status']]) {
  $(id).addEventListener('change', () => { state.settings[key] = $(id).value; save(); run(); });
}
$('year').addEventListener('change', () => { state.settings.year_min = Number($('year').value); save(); run(); });
$('known').addEventListener('change', () => { state.settings.known_min = Number($('known').value); save(); run(); });
$('avoid').addEventListener('input', () => {
  state.settings.dislike = Number($('avoid').value);
  $('avoid-out').value = Math.round(state.settings.dislike * 100) + '%';
  save(); run();
});
for (const b of document.querySelectorAll('[data-focus]')) {
  b.addEventListener('click', () => {
    Object.assign(state.settings, FOCUS[b.dataset.focus]);
    syncTune(); save(); run();
  });
}
$('reset').addEventListener('click', () => { state.settings = { ...DEFAULTS }; syncTune(); save(); run(); });

function syncTune() {
  const s = state.settings;
  const focus = Object.entries(FOCUS).find(([, v]) => v.text === s.text && v.themes === s.themes && v.genres === s.genres)?.[0];
  for (const b of document.querySelectorAll('[data-focus]')) b.setAttribute('aria-pressed', String(b.dataset.focus === focus));
  $('known').value = s.known_min;
  $('year').value = [1900, 1990, 2000, 2010, 2018].includes(s.year_min) ? s.year_min : 1900;
  $('lang').value = s.language; $('kind').value = s.type; $('stat').value = s.status;
  $('avoid').value = s.dislike;
  $('avoid-out').value = Math.round(s.dislike * 100) + '%';
  $('avoid-row').hidden = !state.profile.some(p => p.weight < 0);
}

/* ---------------------------------------------------------------- start */
renderPicks();
renderList();
renderSaved();
syncTune();
show(firstTab());
run(0, 'resume');
readLink();
