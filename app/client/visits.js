// What holds still within a visit to Watch next, and what can be found again after it.
// Pure, so test_visits.mjs can hold it to its rules; main.js does the storing.
//
// A visit ends after IDLE_MINUTES without activity, or when the day turns at 04:00
// (fresh.js). Within one, a reload shows the same picks rather than asking afresh, and
// an action merges into what is on screen instead of laying it out again.
import { dayNumber } from './fresh.js';

export const IDLE_MINUTES = 30;
export const SHOWN_DAYS = 3;        // days of shown picks kept, to find one again
export const SHOWN_PER_DAY = 60;

// What a visit's picks depend on, the same however the settings happen to be ordered:
// the list with its ratings, the settings and the liked shows to match.
export function visitKey({ profile, settings, similar_to: similar }) {
  return JSON.stringify([profile.map(p => [p.id, p.weight]),
    Object.keys(settings).sort().map(k => [k, settings[k]]), similar]);
}

// Whether a kept visit can be shown again as it was: made today for the same list and
// settings, with no more than IDLE_MINUTES since the last activity.
export function resumable(visit, { key, day, now }) {
  const idle = now - visit?.at;
  return Boolean(visit && visit.key === key && visit.day === day && idle >= 0 && idle <= IDLE_MINUTES * 60_000
    && Array.isArray(visit.data?.picks));
}

// The picks once an action has changed the list, with the acted-on pick already gone.
// Those the new answer still holds keep the order they were shown in, with its details.
// With `hold` (an action on a card, where the eye is) so do those it no longer holds, as
// they were: a show sliding past a rank boundary elsewhere in the list is no reason for
// its card to vanish. The answer's new picks follow in its order, as many as bring the
// list back to the answer's length, which without `hold` is all of them.
export function merge(shown, next, { hold = false } = {}) {
  const now = new Map(next.map(p => [p.id, p]));
  const kept = shown.filter(p => hold || now.has(p.id)).map(p => now.get(p.id) || p);
  const had = new Set(kept.map(p => p.id));
  const added = next.filter(p => !had.has(p.id));
  return [...kept, ...added.slice(0, Math.max(0, next.length - kept.length))];
}

// A pick cut to what finding it again needs.
const slim = p => ({
  id: p.id, name: p.name, year: Number.isInteger(p.year) ? p.year : null,
  channel: typeof p.channel === 'string' ? p.channel : null,
  rating: typeof p.rating === 'number' ? p.rating : null,
  url: typeof p.url === 'string' && p.url.startsWith('https://') ? p.url : null,
});

// The picks shown on each of the last few days, from storage; junk is dropped.
export function shownStore(raw) {
  const days = {};
  for (const [day, picks] of Object.entries((raw && typeof raw === 'object' && raw.days) || {})) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Array.isArray(picks)) continue;
    days[day] = picks.filter(p => p && Number.isInteger(p.id) && typeof p.name === 'string')
      .slice(0, SHOWN_PER_DAY).map(slim);
  }
  return { v: 1, days };
}

// Adds a day's picks to its record, first shown first. Returns how many were new.
export function noteShown(store, day, picks) {
  const list = store.days[day] || (store.days[day] = []);
  const have = new Set(list.map(p => p.id));
  let added = 0;
  for (const p of picks) {
    if (have.has(p.id) || list.length >= SHOWN_PER_DAY) continue;
    list.push(slim(p));
    have.add(p.id);
    added++;
  }
  return added;
}

// Forgets every day but the last SHOWN_DAYS, today among them.
export function pruneShown(store, day) {
  const now = dayNumber(day);
  for (const d of Object.keys(store.days)) {
    const n = dayNumber(d);
    if (!(n <= now && n > now - SHOWN_DAYS)) delete store.days[d];
  }
  return store;
}

// The picks of the last day before this one that `wanted` keeps (in main.js, those not
// rated since and not in today's list), with how many days ago that was. Null when
// there are none.
export function lastShown(store, day, wanted) {
  const now = dayNumber(day);
  const last = Object.keys(store.days).filter(d => dayNumber(d) < now).sort().at(-1);
  const picks = last ? store.days[last].filter(wanted) : [];
  return picks.length ? { day: last, ago: now - dayNumber(last), picks } : null;
}

// How a day's picks are named: Yesterday's, or the weekday's.
export function dayName({ day, ago }) {
  return ago === 1 ? 'Yesterday'
    : new Date(`${day}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'long', timeZone: 'UTC' });
}
