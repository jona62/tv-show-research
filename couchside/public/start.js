// Where a page starts: the list and what the browser remembers, read from storage as they
// stand, the visit the tab is on (begun here when it is a new one), and the home page asked
// for at once. The page loads this beside main.js, and it runs as soon as it and its few
// small imports are here, so on a slow connection the home page is on its way while main.js
// and its modules still arrive; main.js starts from the same list, memory and visit, and
// takes the answer when it asks for the very same page (take). homeBody is the one place
// that says what a request for the home page carries, so the two never differ; a field
// added anywhere else would have main.js ask again.
import { LIMITS, packList } from './transfer.js?v=aca34fe2830e9d29';
import { freshStore, today, prune, beginVisit, freshness } from './fresh.js?v=afcc972f76479400';
import { pageKey, ongoing, resumable } from './format.js?v=e565cc65c0882a95';

/* ------------------------------------------------------------- the list */
export const KEY = 'couchside-v1';
export const DEFAULTS = {
  text: 40, themes: 35, genres: 25, closest: .3, dislike: .35, language: 'all', type: 'all',
  status: 'all', year_min: 1900, runtime_min: 0, rating_min: 0, known_min: 85,
};
export const REACH = [85, 60, 0];
// Version 3 defaults to well-known shows. Existing valid reach choices stay as saved.
export const VERSION = 3;
// Up to 3,000 ratings, as many as someone who watches a great deal has seen.
export const MAX_RATED = LIMITS.rated;
export const WEIGHTS = [1, .7, .35, 0, -1];

export const fresh = () => ({ version: VERSION, profile: [], saved: [], settings: { ...DEFAULTS }, onboarded: false });
export const tidy = s => ({
  id: s.id, name: typeof s.name === 'string' ? s.name : '', year: Number.isInteger(s.year) ? s.year : null,
  poster: typeof s.poster === 'string' && s.poster.startsWith('https://static.tvmaze.com/') ? s.poster : null,
});

// A stored list is read defensively: anything malformed is dropped rather than trusted.
export function sanitize(raw) {
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
  const reach = raw.settings?.known_min;
  return {
    version: VERSION,
    profile, saved, settings: { ...DEFAULTS, known_min: REACH.includes(reach) ? reach : DEFAULTS.known_min },
    onboarded: raw.onboarded === true || profile.length > 0,
  };
}

// The list as stored, for main.js to start from.
export const stored = (() => {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY));
    if (raw && typeof raw === 'object') return sanitize(raw);
  } catch { /* first visit, or storage is off */ }
  return fresh();
})();

/* ------------------------------------------------------------ the memory */
// What this browser has shown and what you engaged with (fresh.js), so each visit's page
// is fresh: kept under its own key, one salt per browser, and pruned on every load.
export const FRESH_KEY = 'couchside-fresh';
// The memory as stored, or null when there is none.
export const readMemory = () => {
  try {
    const raw = JSON.parse(localStorage.getItem(FRESH_KEY));
    return raw ? prune(freshStore(raw), today()) : null;
  } catch { return null; }
};
export const writeMemory = memory => {
  try { localStorage.setItem(FRESH_KEY, JSON.stringify(memory)); } catch { /* private mode, or no storage here */ }
};
// The memory as the page starts, written at once (below), so the welcome page's starters
// (starters.js) find this salt, not a second.
export const remembered = readMemory() || prune(freshStore(null), today());

/* -------------------------------------------------------------- the visit */
// A visit (format.js): the app opened in a tab, or come back to after half an hour away
// or on a new day. It takes the day's next number in the memory, and what its requests
// carry is worked out once as it begins and kept with it for the tab: the day and its
// seed, the visit's own seed, and the memory's counts as they stood, what the day's
// earlier visits showed among them. So a reload goes on with the same visit and gets the
// same page, and nothing a visit shows changes what it asks for; the next visit counts it.
export const VISIT_KEY = 'couchside-visit';
export const keepVisit = visit => {
  try { sessionStorage.setItem(VISIT_KEY, JSON.stringify(visit)); } catch { /* storage is off */ }
};
// Whether the tab still keeps this visit as its own.
const kept = visit => {
  try {
    const own = JSON.parse(sessionStorage.getItem(VISIT_KEY));
    return own?.day === visit.day && own?.n === visit.n;
  } catch { return false; }
};
// A new visit, numbered in the memory (which the caller writes): { visit, ask }, where ask
// is what its requests carry, kept with the visit once worked out, if the tab has not begun
// another meanwhile. A browser without crypto.subtle (a page not served over https) sends
// no seeds, and gets the plain ranking.
export function newVisit(memory) {
  const day = today();
  const visit = { day, n: beginVisit(memory, day), at: Date.now(), ask: null };
  const ask = freshness(memory, day, visit.n).catch(() => ({})).then(found => {
    const own = kept(visit);
    visit.ask = found;
    if (own) keepVisit(visit);
    return found;
  });
  keepVisit(visit);
  return { visit, ask };
}
// The visit this page starts on: the tab's own while it goes on, else a new one.
export const opened = (() => {
  let visit = null;
  try { visit = JSON.parse(sessionStorage.getItem(VISIT_KEY)); } catch { visit = null; }
  const begun = ongoing(visit, { day: today(), now: Date.now() }) && visit.ask && typeof visit.ask === 'object'
    ? { visit, ask: Promise.resolve(visit.ask) } : newVisit(remembered);
  writeMemory(remembered);
  return begun;
})();

/* ------------------------------------------------------- the home page */
export const tasteOf = state => ({ profile: state.profile.map(({ id, weight }) => ({ id, weight })), settings: state.settings });
const TAG = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,3}$/;
export const languages = () => (globalThis.navigator?.languages?.length ? [...navigator.languages]
  : [globalThis.navigator?.language || '']).filter(t => TAG.test(t)).slice(0, 8);
// What asking for the home page carries: the list, My List, what the visit asks with
// (ask) and the browser's languages. Asking for more rows adds which rows are shown (main.js).
export const homeBody = (state, ask) => ({ ...tasteOf(state), list: state.saved.map(s => s.id), ...ask, lang: languages() });
// A request's body as sent: the list packed as ids and a character a rating (transfer.js),
// a quarter of the bytes.
export const packed = body => JSON.stringify(Array.isArray(body.profile) ? { ...body, profile: packList(body.profile) } : body);

// The page kept for this tab, which main.js shows again rather than asking (keepPage).
export const PAGE_KEY = 'couchside-home';
function keptPage(state, visit) {
  try {
    const page = JSON.parse(sessionStorage.getItem(PAGE_KEY));
    return resumable(page, { key: pageKey(tasteOf(state), state.saved.map(s => s.id)), visit }) && page.home.ask;
  } catch { return false; }
}

// The home page asked for as the page starts, unless the page kept for this visit stands in.
let early = null;
if (globalThis.document && !keptPage(stored, opened.visit)) {
  early = opened.ask.then(ask => {
    const text = packed(homeBody(stored, ask));
    return { text, answer: fetch('/api/home', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: text, priority: 'high' }) };
  });
  // A failure is main.js's to report, once it takes the answer.
  early.then(({ answer }) => answer.catch(() => {}), () => {});
}

// The answer to the request asked for as the page started, when text is that request
// (packed), to the first to ask; else null, and main.js asks itself.
export async function take(text) {
  const pending = early;
  early = null;
  const started = await pending;
  return started?.text === text ? started.answer : null;
}
