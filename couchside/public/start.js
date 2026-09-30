// Where a visit starts: the list and what the browser remembers, read from storage as they
// stand, and the home page asked for at once. The page loads this beside main.js, and it
// runs as soon as it and its few small imports are here, so on a slow connection the home
// page is on its way while main.js and its modules still arrive; main.js reads the same
// list and memory from here, and takes the answer when it asks for the very same page
// (take). homeBody is the one place that says what a request for the home page carries, so
// the two never differ; a field added anywhere else would have main.js ask again.
import { LIMITS, packList } from './transfer.js?v=aca34fe2830e9d29';
import { freshStore, today, prune, freshness } from './fresh.js?v=4fb048095fde4af8';
import { pageKey, resumable } from './format.js?v=23dc0e9fdded4d75';

/* ------------------------------------------------------------- the list */
export const KEY = 'couchside-v1';
export const DEFAULTS = {
  text: 40, themes: 35, genres: 25, closest: .3, dislike: .35, language: 'all', type: 'all',
  status: 'all', year_min: 1900, runtime_min: 0, rating_min: 0, known_min: 60,
};
export const REACH = [85, 60, 0];
// Version 2 widened the default reach to fairly known shows of any year, once the ranking
// learned which eras and how well known a list likes.
export const VERSION = 2;
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

// The list as stored, for main.js to start from.
export const stored = (() => {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY));
    if (raw && typeof raw === 'object') return sanitize(raw);
  } catch { /* first visit, or storage is off */ }
  return fresh();
})();

/* ------------------------------------------------------------ the memory */
// What this browser has shown and what you engaged with (fresh.js), so each day's page
// is fresh: kept under its own key, one salt per browser, pruned on every load, and
// written at once, so the welcome page's starters (starters.js) and main.js find this
// salt, not a second.
export const FRESH_KEY = 'couchside-fresh';
export const remembered = (() => {
  let memory;
  try { memory = freshStore(JSON.parse(localStorage.getItem(FRESH_KEY))); } catch { memory = freshStore(null); }
  prune(memory, today());
  try { localStorage.setItem(FRESH_KEY, JSON.stringify(memory)); } catch { /* private mode, or no storage here */ }
  return memory;
})();

// What a request carries about the day: its date, its seed and the memory's counts. A
// browser without crypto.subtle (a page not served over https) sends none.
export async function freshFields(memory) {
  try { return await freshness(memory, today()); } catch { return {}; }
}
const TAG = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,3}$/;
export const languages = () => (globalThis.navigator?.languages?.length ? [...navigator.languages]
  : [globalThis.navigator?.language || '']).filter(t => TAG.test(t)).slice(0, 8);

/* ------------------------------------------------------- the home page */
export const tasteOf = state => ({ profile: state.profile.map(({ id, weight }) => ({ id, weight })), settings: state.settings });
// What asking for the home page carries: the list, My List, the day and memory, and the
// browser's languages. Asking for more rows adds which rows are shown (main.js).
export async function homeBody(state, memory) {
  return { ...tasteOf(state), list: state.saved.map(s => s.id), ...await freshFields(memory), lang: languages() };
}
// A request's body as sent: the list packed as ids and a character a rating (transfer.js),
// a quarter of the bytes.
export const packed = body => JSON.stringify(Array.isArray(body.profile) ? { ...body, profile: packList(body.profile) } : body);

// The page kept for this tab, which main.js shows again rather than asking (keepPage).
export const PAGE_KEY = 'couchside-home';
function kept(state) {
  try {
    const page = JSON.parse(sessionStorage.getItem(PAGE_KEY));
    return resumable(page, { key: pageKey(tasteOf(state), state.saved.map(s => s.id)), day: today(), now: Date.now() });
  } catch { return false; }
}

// The home page asked for as the page starts, unless the page kept for this tab stands in.
let early = null;
if (globalThis.document && !kept(stored)) {
  early = homeBody(stored, remembered).then(body => {
    const text = packed(body);
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
