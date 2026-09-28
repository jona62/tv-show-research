// Checks for fresh.js's pure parts: the day, the seed, the memory and what it sends.
//   node app/test_fresh.mjs
import { webcrypto } from 'node:crypto';
if (!globalThis.crypto) globalThis.crypto = webcrypto;
const { today, dayNumber, freshStore, seedFor, noteSeen, noteEngaged, noteRow, noteHero, prune, decayed, freshness,
        KEEP_TITLES, HALF_LIFE } = await import('./fresh.js');

let failed = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + detail}`); if (!ok) failed++; };

check('a day rolls over at 04:00, not midnight',
  today(new Date(2026, 9, 5, 3, 59)) === '2026-10-04' && today(new Date(2026, 9, 5, 4, 0)) === '2026-10-05');
check('day numbers count whole days', dayNumber('1970-01-02') === 1 && dayNumber('2026-10-05') - dayNumber('2026-10-04') === 1);

const store = freshStore(null);
check('a new store makes a 32-digit salt', /^[0-9a-f]{32}$/.test(store.salt));
check('a store survives a round trip through JSON', JSON.stringify(freshStore(JSON.parse(JSON.stringify(store)))) === JSON.stringify(store));
check('junk is dropped, not trusted', Object.keys(freshStore({ v: 1, salt: 'x', titles: { abc: { d: [1] }, 5: 'no' } }).titles).length === 0);

const seedA = await seedFor(store.salt, '2026-10-05'), seedB = await seedFor(store.salt, '2026-10-06');
check('a seed is 16 hex digits', /^[0-9a-f]{16}$/.test(seedA));
check('the same day gives the same seed', seedA === await seedFor(store.salt, '2026-10-05'));
check('another day gives another seed', seedA !== seedB);
check('another browser gives another seed', seedA !== await seedFor(freshStore(null).salt, '2026-10-05'));

const s = freshStore(null);
noteSeen(s, 42, '2026-10-01'); noteSeen(s, 42, '2026-10-01'); noteSeen(s, 42, '2026-10-02');
check('a title counts once a day', s.titles[42].d.length === 2);
check('nothing counts on the day it was seen', decayed(s.titles[42], dayNumber('2026-10-02')) === 0.5 ** (1 / HALF_LIFE) * 1);
const week = decayed({ d: [dayNumber('2026-10-01')] }, dayNumber('2026-10-08'));
check('a day seen counts half a week later', Math.abs(week - 0.5) < 1e-9, week);

const f = await freshness(s, '2026-10-03');
check('a request carries the day and its seed', f.day === '2026-10-03' && /^[0-9a-f]{16}$/.test(f.seed));
check('seen counts go as decimals keyed by id', typeof f.seen['42'] === 'number' && f.seen['42'] > 1.5 && f.seen['42'] < 2);
noteEngaged(s, 42, '2026-10-03');
const g = await freshness(s, '2026-10-04');
check('an engaged title is exempt from fatigue', g.engaged.includes(42) && !('42' in g.seen));

noteHero(s, 7, '2026-10-02'); noteHero(s, 8, '2026-10-04');
const h = await freshness(s, '2026-10-04');
check('yesterday\'s heroes rest, today\'s does not', h.resting.includes(7) && !h.resting.includes(8));

const r = freshStore(null);
for (let d = 1; d <= 5; d++) noteRow(r, 'genre-drama', `2026-10-0${d}`);
check('a row passed over on five days rests', (await freshness(r, '2026-10-06')).tired.includes('genre-drama'));
noteRow(r, 'genre-drama', '2026-10-06', true);
check('engaging with a row wakes it', !(await freshness(r, '2026-10-07')).tired.includes('genre-drama'));

const big = freshStore(null);
for (let i = 0; i < KEEP_TITLES + 50; i++) noteSeen(big, i, i < 50 ? '2026-08-01' : '2026-10-01');
prune(big, '2026-10-02');
check('past the cap, the titles seen longest ago go first', Object.keys(big.titles).length === KEEP_TITLES && !(0 in big.titles));
prune(big, '2026-12-30');
check('days older than eight weeks are forgotten', Object.keys(big.titles).length === 0);

console.log(failed ? `${failed} check(s) failed` : 'all fresh checks passed');
process.exit(failed ? 1 : 0);
