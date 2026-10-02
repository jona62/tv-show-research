// A first visit's shows, from /api/starters: shared by Next Watch and Couchside. The
// server draws them (starters.py) from the day's seed, the round, the shows picked so
// far and the browser's language; this asks for them and lays them out so a picked show
// never moves. Picks keep their places and every other place takes the next show the
// server sent, so after a pick only the swapped shows change on screen.
import { today, seedFor, freshStore } from './fresh.js';

export const MAX_ROUND = 50;
export const MAX_PICKED = 20;
const SEED = /^[0-9a-f]{16}$/;
const TAG = /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/;

// The day's seed from the salt fresh.js keeps under key, which is written only when it
// is new so nothing else kept there is overwritten. Empty where the browser cannot hash
// (outside a secure context), which the server answers with the plain screen.
export async function daySeed(key, storage = globalThis.localStorage, day = today()) {
  let raw = null;
  try { raw = JSON.parse(storage.getItem(key)); } catch { /* storage is off */ }
  const store = freshStore(raw);
  if (raw?.salt !== store.salt) {
    try { storage.setItem(key, JSON.stringify(store)); } catch { /* private mode */ }
  }
  try { return await seedFor(store.salt, day); } catch { return ''; }
}

// The browser's first language, as navigator.languages gives it.
export const browserLanguage = (nav = globalThis.navigator) => nav?.languages?.[0] || nav?.language || '';

// The query string for a screen. Anything the server would refuse is left out or
// clamped instead, so a request never fails over a detail.
export function startersQuery({ seed = '', round = 0, picked = [], lang = '', count = 24 } = {}) {
  const params = new URLSearchParams();
  if (SEED.test(seed)) params.set('seed', seed);
  params.set('round', String(Math.max(0, Math.min(MAX_ROUND, Math.trunc(round) || 0))));
  const ids = [...new Set(picked.filter(id => Number.isInteger(id) && id > 0))].slice(0, MAX_PICKED);
  if (ids.length) params.set('picked', ids.join(','));
  if (typeof lang === 'string' && lang.length <= 35 && TAG.test(lang)) params.set('lang', lang);
  params.set('count', String(count));
  return params.toString();
}

// Lay a new screen over the one showing: a picked show keeps its place, and each other
// place takes the next show the server sent that is not on screen already.
export function mergeStarters(current, incoming, isPicked) {
  const out = new Array(incoming.length).fill(null);
  const kept = new Set();
  current.forEach((show, k) => {
    if (k < out.length && show && isPicked(show.id)) {
      out[k] = show;
      kept.add(show.id);
    }
  });
  const rest = incoming.filter(show => !kept.has(show.id));
  for (let k = 0; k < out.length; k++) if (!out[k]) out[k] = rest.shift() ?? null;
  return out.filter(Boolean);
}
