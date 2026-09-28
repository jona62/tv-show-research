// Checks for starters.js: the query a screen asks with, the layout that keeps picks in
// place, and the day's seed from the fresh store's salt.
//   node app/test_starters.mjs
import { webcrypto } from 'node:crypto';
if (!globalThis.crypto) globalThis.crypto = webcrypto;
const { startersQuery, mergeStarters, daySeed, browserLanguage } = await import('./starters.js');
const { freshStore, seedFor } = await import('./fresh.js');

let failed = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + detail}`); if (!ok) failed++; };
const read = query => Object.fromEntries(new URLSearchParams(query));

// The query.
const q = read(startersQuery({ seed: '0123456789abcdef', round: 2, picked: [169, 82], lang: 'en-GB' }));
check('a query carries the seed, round, picks, language and count',
  q.seed === '0123456789abcdef' && q.round === '2' && q.picked === '169,82' && q.lang === 'en-GB' && q.count === '24');
const odd = read(startersQuery({ seed: 'nope', round: 99, picked: [1, 1, 'x', -3, 2.5, 7], lang: 'en_GB!' }));
check('what the server would refuse is left out or clamped',
  !('seed' in odd) && odd.round === '50' && odd.picked === '1,7' && !('lang' in odd), JSON.stringify(odd));
check('picks are capped at twenty', read(startersQuery({ picked: Array.from({ length: 30 }, (_, k) => k + 1) }))
  .picked.split(',').length === 20);
check('a long language tag is left for the header', !('lang' in read(startersQuery({ lang: 'en-' + 'abcdefgh-'.repeat(4) }))));
check('no picks, no picked', !('picked' in read(startersQuery({}))));
check('the browser language is its first', browserLanguage({ languages: ['ko-KR', 'en'] }) === 'ko-KR'
  && browserLanguage({ language: 'fr' }) === 'fr' && browserLanguage(undefined) === '');

// The layout.
const shows = ids => ids.map(id => ({ id, name: `#${id}` }));
const ids = list => list.map(s => s.id).join(',');
check('a first screen is the server\'s order', ids(mergeStarters([], shows([1, 2, 3, 4]), () => false)) === '1,2,3,4');
// Picking 2 swapped 3 for 7: the server's list keeps 2 in place.
check('after a pick only the swapped place changes',
  ids(mergeStarters(shows([1, 2, 3, 4]), shows([1, 2, 7, 4]), id => id === 2)) === '1,2,7,4');
// A new round sends all new shows; the pick stays where it was and the rest fill around it.
check('a new round fills around the picks, which keep their places',
  ids(mergeStarters(shows([1, 2, 3, 4]), shows([5, 6, 7, 8]), id => id === 2)) === '5,2,6,7');
check('a pick the server also sent is not shown twice',
  ids(mergeStarters(shows([1, 2, 3, 4]), shows([2, 6, 7, 8]), id => id === 2)) === '6,2,7,8');
check('a show taken back gives its place to the server\'s next',
  ids(mergeStarters(shows([1, 2, 3, 4]), shows([1, 9, 3, 4]), () => false)) === '1,9,3,4');
check('the screen keeps the server\'s length', mergeStarters(shows([1, 2, 3, 4, 5]), shows([1, 2, 3]), () => true).length === 3);

// The day's seed.
const memory = (start = {}) => {
  const kept = { ...start };
  return { kept, getItem: k => kept[k] ?? null, setItem: (k, v) => { kept[k] = v; } };
};
const empty = memory();
const seed = await daySeed('fresh', empty, '2026-10-05');
const salt = JSON.parse(empty.kept.fresh).salt;
check('a first visit makes and keeps a salt, and the seed comes from it',
  /^[0-9a-f]{16}$/.test(seed) && seed === await seedFor(salt, '2026-10-05'));
check('the same day gives the same seed, another day another',
  seed === await daySeed('fresh', empty, '2026-10-05') && seed !== await daySeed('fresh', empty, '2026-10-06'));
const store = freshStore(null);
store.titles[42] = { d: [20000], e: null };
const held = memory({ fresh: JSON.stringify(store) });
check('an existing store\'s salt is used and nothing in it is rewritten',
  await daySeed('fresh', held, '2026-10-05') === await seedFor(store.salt, '2026-10-05')
  && held.kept.fresh === JSON.stringify(store));
const broken = { getItem() { throw new Error('off'); }, setItem() { throw new Error('off'); } };
check('with storage off there is still a seed for the visit', /^[0-9a-f]{16}$/.test(await daySeed('fresh', broken, '2026-10-05')));
const subtle = globalThis.crypto.subtle;
Object.defineProperty(globalThis.crypto, 'subtle', { value: undefined, configurable: true });
check('without Web Crypto the seed is empty, and the server gives the plain screen',
  await daySeed('fresh', memory(), '2026-10-05') === '');
Object.defineProperty(globalThis.crypto, 'subtle', { value: subtle, configurable: true });

console.log(failed ? `${failed} check(s) failed` : 'all starters checks passed');
process.exit(failed ? 1 : 0);
