// Checks for visits.js: what holds still within a visit and what can be found again.
//   node app/tests/test_visits.mjs
import { visitKey, resumable, merge, shownStore, noteShown, pruneShown, lastShown, dayName, IDLE_MINUTES, SHOWN_PER_DAY }
  from '../client/visits.js';

let failed = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + detail}`); if (!ok) failed++; };
const ids = picks => picks.map(p => p.id).join();

// 1. Merging an answer into the picks on screen.
const pick = (id, score = 50) => ({ id, name: `Show ${id}`, score });
const shown = [1, 2, 3, 4, 5].map(id => pick(id));
const next = [pick(1, 60), pick(3, 55), pick(6, 52), pick(2, 51), pick(5, 40), pick(7, 30)];
const merged = merge(shown, next);
check('the picks still recommended keep the order they were shown in', ids(merged).startsWith('1,2,3,5'));
check('the acted-on pick leaves, with anything the answer dropped', !merged.some(p => p.id === 4));
check('new picks follow at the end, in the order they were ranked', ids(merged) === '1,2,3,5,6,7', ids(merged));
check('every pick carries the new answer\'s details', merged.find(p => p.id === 3).score === 55);
check('the list comes out as long as the answer', merged.length === next.length);
check('with nothing on screen the answer is shown as it is', ids(merge([], next)) === ids(next));
check('an answer with nothing in it empties the list', merge(shown, []).length === 0);
// Seen it on pick 3: it is gone before the answer comes, and the answer drops pick 5 too.
const afterSeen = [pick(1, 61), pick(2, 58), pick(4, 52), pick(6, 50), pick(7, 44)];
const held = merge(shown.filter(p => p.id !== 3), afterSeen, { hold: true });
check('after an action on a card, every other card keeps its place', ids(held).startsWith('1,2,4,5'), ids(held));
check('keeping the details it had when the answer no longer holds it',
  held.find(p => p.id === 5).score === 50 && held.find(p => p.id === 4).score === 52);
check('and new picks only refill the list to the answer\'s length', ids(held) === '1,2,4,5,6', ids(held));
check('a list already that long takes nothing new', ids(merge(shown, afterSeen.slice(0, 3), { hold: true })) === ids(shown));

// 2. When a kept visit can be shown again.
const state = { profile: [{ id: 169, weight: 1, name: 'Breaking Bad' }], settings: { text: 40, facets: 30 }, similar_to: [] };
const key = visitKey(state);
check('a visit\'s key does not care how the settings are ordered',
  key === visitKey({ ...state, settings: { facets: 30, text: 40 } }));
check('but it does care about ratings, settings and the shows to match',
  key !== visitKey({ ...state, profile: [{ id: 169, weight: .7 }] }) && key !== visitKey({ ...state, settings: { text: 70, facets: 30 } })
  && key !== visitKey({ ...state, similar_to: [169] }));
check('names and other details do not count', key === visitKey({ ...state, profile: [{ id: 169, weight: 1 }] }));
const at = Date.UTC(2026, 9, 5, 18, 0);
const visit = { key, day: '2026-10-05', at, data: { picks: shown } };
const now = minutes => ({ key, day: '2026-10-05', now: at + minutes * 60_000 });
check('a reload soon after is the same visit', resumable(visit, now(1)) && resumable(visit, now(IDLE_MINUTES)));
check('half an hour idle ends it', !resumable(visit, now(IDLE_MINUTES + 1)));
check('so does a new day', !resumable(visit, { ...now(1), day: '2026-10-06' }));
check('and a changed list or settings', !resumable(visit, { ...now(1), key: 'other' }));
check('a clock that ran backwards is no visit', !resumable(visit, now(-5)));
check('nothing kept, or something broken, is no visit',
  !resumable(null, now(1)) && !resumable({ ...visit, data: null }, now(1)) && !resumable({ ...visit, at: 'soon' }, now(1)));

// 3. What was shown on each day, for finding a pick again.
const store = shownStore(null);
const full = id => ({ ...pick(id), year: 2020, channel: 'HBO', rating: 8.1, url: `https://www.tvmaze.com/shows/${id}`,
                      summary: 'Long text', score: 90 });
check('a day records its picks once each, first shown first',
  noteShown(store, '2026-10-05', [1, 2, 3].map(full)) === 3 && noteShown(store, '2026-10-05', [3, 4].map(full)) === 1
  && ids(store.days['2026-10-05']) === '1,2,3,4');
check('only what finding one again needs is kept', Object.keys(store.days['2026-10-05'][0]).sort().join()
  === 'channel,id,name,rating,url,year');
check('a day holds at most so many', noteShown(store, '2026-10-04', Array.from({ length: 90 }, (_, n) => full(100 + n)))
  === SHOWN_PER_DAY);
noteShown(store, '2026-10-01', [full(9)]);
noteShown(store, '2026-10-06', [full(2), full(8)]);
check('a store survives a round trip through JSON', JSON.stringify(shownStore(JSON.parse(JSON.stringify(store)))) === JSON.stringify(store));
check('junk is dropped, not trusted', JSON.stringify(shownStore({ days: { nope: [full(1)], '2026-10-05': [{ id: 'x' }, null,
  { id: 3, name: 'Three', url: 'javascript:alert(1)' }] } }).days) === '{"2026-10-05":[{"id":3,"name":"Three","year":null,"channel":null,"rating":null,"url":null}]}');
pruneShown(store, '2026-10-06');
check('only the last three days are kept', Object.keys(store.days).sort().join() === '2026-10-04,2026-10-05,2026-10-06');
const rated = new Set([1]), today = new Set([2, 8]);
const found = lastShown(store, '2026-10-06', p => !rated.has(p.id) && !today.has(p.id));
check('yesterday\'s picks leave out what was rated since and what is on today\'s list',
  found.day === '2026-10-05' && found.ago === 1 && ids(found.picks) === '3,4');
check('with nothing left from the last day there is nothing to show',
  lastShown(store, '2026-10-06', () => false) === null && lastShown(shownStore(null), '2026-10-06', () => true) === null);
check('today\'s own picks are never earlier ones', lastShown({ days: { '2026-10-06': [full(1)] } }, '2026-10-06', () => true) === null);
const gap = lastShown({ days: { '2026-10-03': [full(5)] } }, '2026-10-06', () => true);
check('the last day may be a few days back', gap.day === '2026-10-03' && gap.ago === 3);
check('a day is named yesterday or by its weekday', dayName(found) === 'Yesterday' && dayName(gap) === 'Saturday');

console.log(failed ? `${failed} check(s) failed` : 'all visit checks passed');
process.exit(failed ? 1 : 0);
