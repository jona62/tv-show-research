// Checks for fresh.js's pure parts: the day, the seed, the memory and what it sends.
//   node app/test_fresh.mjs
import { webcrypto } from 'node:crypto';
if (!globalThis.crypto) globalThis.crypto = webcrypto;
const { today, dayNumber, freshStore, merged, seedFor, beginVisit, noteSeen, noteEngaged, noteRow, noteHero, prune, decayed,
        earlier, freshness, KEEP_TITLES, HALF_LIFE, HEROES_A_DAY } = await import('./fresh.js');

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

// Visits, Couchside's: the times the app is opened in a day, each with a seed of its own.
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const v = freshStore(null);
check('a day\'s visits are numbered from one, and a new day starts again',
  beginVisit(v, '2026-10-05') === 1 && beginVisit(v, '2026-10-05') === 2 && beginVisit(v, '2026-10-06') === 1
  && same(v.visits, { d: dayNumber('2026-10-06'), n: 1 }));
const visitSeed = await seedFor(v.salt, '2026-10-05', 2);
check('a visit\'s seed is its own: not the day\'s, nor another visit\'s, and the same each time it is asked',
  /^[0-9a-f]{16}$/.test(visitSeed) && visitSeed !== await seedFor(v.salt, '2026-10-05')
  && visitSeed !== await seedFor(v.salt, '2026-10-05', 3) && visitSeed === await seedFor(v.salt, '2026-10-05', 2));
const w = freshStore(null);
noteSeen(w, 42, '2026-10-04');
for (const k of [1, 1, 2, 3]) noteSeen(w, 42, '2026-10-05', k);
noteSeen(w, 43, '2026-10-05', 3);
check('a title keeps the visits of its day it was seen on, once each and the last two',
  same(w.titles[42].v, [2, 3]) && same(w.titles[43].v, [3]));
const now5 = dayNumber('2026-10-05');
check('each earlier visit that day adds half a day\'s showing, a whole day\'s at most',
  earlier(w.titles[43], now5, 4) === 0.5 && earlier(w.titles[42], now5, 4) === 1 && earlier(w.titles[42], now5, 3) === 0.5);
check('and nothing comes from the visit itself, a later one, another day or a request without a visit',
  earlier(w.titles[43], now5, 3) === 0 && earlier(w.titles[42], now5 + 1, 1) === 0 && earlier(w.titles[42], now5, 0) === 0);
noteSeen(w, 42, '2026-10-06', 1);
check('a new day starts its title\'s visits again', same(w.titles[42].v, [1]) && w.titles[42].d.length === 3);
check('a store with visits survives a round trip through JSON',
  same(freshStore(JSON.parse(JSON.stringify(w))), w) && freshStore({ ...w, visits: 'x' }).visits.n === 0);
const x = freshStore(null);
noteHero(x, 7, '2026-10-01'); noteHero(x, 8, '2026-10-01');
noteHero(x, 9, '2026-10-05'); noteHero(x, 10, '2026-10-05'); noteHero(x, 9, '2026-10-05');
check('a day\'s heroes are kept in the order they were shown, once each', same(x.heroes[dayNumber('2026-10-05')], [9, 10]));
for (let n = 0; n < HEROES_A_DAY + 5; n++) noteHero(x, 1000 + n, '2026-10-02');
check('and no more than a day\'s worth', x.heroes[dayNumber('2026-10-02')].length === HEROES_A_DAY);
check('a day\'s hero kept as one id, as before visits, reads as that day\'s first',
  same(freshStore({ v: 1, salt: x.salt, heroes: { 20000: 7, 20001: 'x' } }).heroes, { 20000: [7] }));
for (let k = 1; k <= 3; k++) beginVisit(x, '2026-10-05');
noteSeen(x, 50, '2026-10-04');
noteSeen(x, 50, '2026-10-05', 1); noteSeen(x, 51, '2026-10-05', 2); noteSeen(x, 50, '2026-10-05', 2);
noteEngaged(x, 52, '2026-10-05');
const asked4 = await freshness(x, '2026-10-05', 4);
check('a visit\'s request carries the day, the day\'s seed and the visit\'s own',
  asked4.day === '2026-10-05' && asked4.seed === await seedFor(x.salt, '2026-10-05')
  && asked4.visit === await seedFor(x.salt, '2026-10-05', 4));
check('with what earlier visits showed among the counts, on top of earlier days',
  asked4.seen['50'] === Math.round((0.5 ** (1 / HALF_LIFE) + 1) * 10) / 10 && asked4.seen['51'] === 0.5);
check('the heroes they featured among it, as shown by their visit', asked4.seen['9'] === 0.5 && asked4.seen['10'] === 0.5
  && earlier(w.titles[43], now5, 4, true) === 1 && earlier(null, now5, 4, true) === 0.5);
check('and every hero shown that day resting, after the first of each day of the last week',
  same(asked4.resting, [7, 1000, 9, 10]), asked4.resting);
check('what was engaged with that day is spared, as before visits', asked4.engaged.includes(52) && !('52' in asked4.seen));
const plainAsk = await freshness(x, '2026-10-05');
check('a request without a visit carries neither its seed nor that day\'s counts and heroes, as Next Watch sends it',
  !('visit' in plainAsk) && !('51' in plainAsk.seen) && !('9' in plainAsk.seen)
  && plainAsk.seen['50'] === Math.round(0.5 ** (1 / HALF_LIFE) * 10) / 10
  && same(plainAsk.resting, [7, 1000]));
prune(x, '2026-10-06');
check('once the day is over only its first hero is kept, and its titles\' visits go',
  same(x.heroes[dayNumber('2026-10-05')], [9]) && !('v' in x.titles[50]) && !('v' in x.titles[51]));
check('so the next day rests it with the others', same((await freshness(x, '2026-10-06', 1)).resting, [7, 1000, 9]));

// Two tabs: each writes what the other wrote joined with its own, never over it.
const tabA = freshStore(null);
beginVisit(tabA, '2026-10-05');
noteSeen(tabA, 60, '2026-10-04'); noteSeen(tabA, 60, '2026-10-05', 1); noteSeen(tabA, 61, '2026-10-05', 1);
noteHero(tabA, 70, '2026-10-05'); noteRow(tabA, 'gems', '2026-10-04');
const tabB = freshStore(JSON.parse(JSON.stringify(tabA)));
beginVisit(tabB, '2026-10-05');
noteSeen(tabB, 60, '2026-10-05', 2); noteSeen(tabB, 62, '2026-10-05', 2); noteEngaged(tabB, 61, '2026-10-05');
noteHero(tabB, 71, '2026-10-05'); noteRow(tabB, 'gems', '2026-10-05', true);
noteSeen(tabA, 63, '2026-10-05', 1);
const both = merged(tabB, tabA);
check('merging another tab\'s memory keeps its visits and heroes, and this tab\'s titles',
  both.visits.n === 2 && same(both.heroes[dayNumber('2026-10-05')], [70, 71]) && both.salt === tabB.salt
  && ['60', '61', '62', '63'].every(id => id in both.titles));
check('a title seen in both keeps every day and the visits of its latest day from each',
  same(both.titles[60].d, [dayNumber('2026-10-04'), dayNumber('2026-10-05')]) && same(both.titles[60].v, [1, 2]));
check('and the later engagement, as a row keeps its days and its engagement',
  both.titles[61].e === dayNumber('2026-10-05') && same(both.rows.gems.d, [dayNumber('2026-10-04'), dayNumber('2026-10-05')])
  && both.rows.gems.e === dayNumber('2026-10-05'));
check('so the next visit is the third, and rests both heroes', beginVisit(both, '2026-10-05') === 3
  && same((await freshness(both, '2026-10-05', 3)).resting, [70, 71]));
check('merging leaves both copies as they were', tabB.visits.n === 2 && !('63' in tabB.titles) && same(tabA.titles[60].v, [1]));

const big = freshStore(null);
for (let i = 0; i < KEEP_TITLES + 50; i++) noteSeen(big, i, i < 50 ? '2026-08-01' : '2026-10-01');
prune(big, '2026-10-02');
check('past the cap, the titles seen longest ago go first', Object.keys(big.titles).length === KEEP_TITLES && !(0 in big.titles));
prune(big, '2026-12-30');
check('days older than eight weeks are forgotten', Object.keys(big.titles).length === 0);

// The impression rule, with stand-ins for the browser's observer and the page's visibility.
const { watcher } = await import('./fresh.js');
const listeners = new Set(), observers = [];
globalThis.document = {
  visibilityState: 'visible',
  addEventListener: (type, fn) => type === 'visibilitychange' && listeners.add(fn),
  removeEventListener: (type, fn) => listeners.delete(fn),
};
globalThis.IntersectionObserver = class {
  constructor(report) { this.report = report; observers.push(this); }
  observe() {} unobserve() {} disconnect() {}
};
const turn = state => { document.visibilityState = state; for (const fn of [...listeners]) fn(); };
const pause = ms => new Promise(done => setTimeout(done, ms));
const counted = [];
const watch = watcher(id => counted.push(id), { dwell: 20 });
const io = observers.at(-1);
const on = (el, ratio) => io.report([{ target: el, isIntersecting: ratio > 0, intersectionRatio: ratio }]);
const [a, b, c, d] = [1, 2, 3, 4].map(id => ({ id, isConnected: true }));
for (const el of [a, b, c, d]) watch.observe(el, el.id);
on(a, 1); on(b, .4); on(c, .6);
await pause(5); on(c, 0);
await pause(60);
check('half on screen for the dwell counts; less, or not for long enough, does not', counted.join() === '1', counted);
on(a, 1); await pause(60);
check('a title counts once', counted.join() === '1', counted);
turn('hidden'); on(d, .8); await pause(60);
check('nothing counts while the tab is hidden', counted.join() === '1', counted);
turn('visible'); await pause(60);
check('coming back to the tab counts what is still on screen', counted.join() === '1,4', counted);
watch.stop();
check('stopping lets go of the page', listeners.size === 0);

console.log(failed ? `${failed} check(s) failed` : 'all fresh checks passed');
process.exit(failed ? 1 : 0);
