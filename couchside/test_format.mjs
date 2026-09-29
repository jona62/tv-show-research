import { tieText, leaning, leaningHeading } from './format.js';
import { years, runtime, seasons, joinNames, parseRoute, withShow, hue, premiere, longDate, airs,
  hostOf, sameService, watchLinks, whereToWatch, trailerSearch, searchNote } from './format.js';
let fails = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + extra}`); if (!ok) fails++; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

check('a franchise tie reads as belonging', tieText({ family: 'franchise', label: 'Breaking Bad' }) === 'part of Breaking Bad');
check('a maker tie reads as authorship', tieText({ family: 'maker', label: 'Vince Gilligan' }) === 'by Vince Gilligan');
check('a network tie reads as a channel', tieText({ family: 'network', label: 'HBO' }) === 'also on HBO');
check('any other tie is its label', tieText({ family: 'genre', label: 'mockumentary' }) === 'mockumentary');
check('a reader link says its fans look it up', tieText({ family: 'fans', label: '' }) === 'its fans look this up too');
check('a decade leaning reads in a sentence', leaning({ family: 'decade', label: '2000s' }) === 'the 2000s');
check('the earliest decade has no article', leaning({ family: 'decade', label: 'before 1960' }) === 'before 1960');
check('a language leaning names shows', leaning({ family: 'language', label: 'Korean' }) === 'shows in Korean');
check('a theme leaning is its short name', leaning({ family: 'theme', label: 'Crime / illicit enterprise' }) === 'crime');
check('a network keeps its case', leaning({ family: 'network', label: 'HBO' }) === 'HBO');
check('a network heading says on', leaningHeading({ family: 'network', label: 'HBO' }) === 'On HBO');
check('a subgenre heading is capitalised', leaningHeading({ family: 'subgenre', label: 'police procedural' }) === 'Police procedural');
check('a running show shows its first year', years(2008, null) === '2008');
check('an ended show shows its span', years(2008, 2013) === '2008–2013');
check('a one-year show shows one year', years(2019, 2019) === '2019');
check('no year is blank', years(null, 2013) === '');
check('short runtimes in minutes', runtime(47) === '47m');
check('long runtimes in hours', runtime(60) === '1h' && runtime(95) === '1h 35m');
check('no runtime is blank', runtime(null) === '' && runtime(0) === '');
check('one season is singular', seasons(1) === '1 Season');
check('several seasons are plural', seasons(5) === '5 Seasons');
check('names join in plain English', joinNames(['A']) === 'A' && joinNames(['A', 'B']) === 'A and B'
  && joinNames(['A', 'B', 'C']) === 'A, B and C' && joinNames([]) === '');
check('home route', same(parseRoute('/', ''), { page: 'home', q: '', genre: '', show: null }));
check('search route keeps its terms', same(parseRoute('/search', '?q=breaking%20bad'), { page: 'search', q: 'breaking bad', genre: '', show: null }));
check('a title opens over any page', same(parseRoute('/list', '?show=169'), { page: 'list', q: '', genre: '', show: 169 }));
check('browse keeps its genre', same(parseRoute('/browse', '?genre=Science-Fiction'), { page: 'browse', q: '', genre: 'Science-Fiction', show: null }));
check('a bad title id is ignored', parseRoute('/', '?show=abc').show === null && parseRoute('/', '?show=-4').show === null
  && parseRoute('/', '?show=1.5').show === null);
check('an unknown path falls back to home', parseRoute('/nope', '').page === 'home');
check('opening a title keeps the search', withShow('/search', '?q=bad', 169) === '/search?q=bad&show=169');
check('closing a title leaves a clean path', withShow('/', '?show=169', null) === '/'
  && withShow('/search', '?q=bad&show=169', null) === '/search?q=bad');
check('hues stay on the wheel', [1, 169, 89594].every(id => hue(id) >= 0 && hue(id) < 360));
check('premiere dates read short', premiere('2026-10-07') === 'Oct 7' && premiere('') === '' && premiere('2026-13-01') === '');
check('full dates carry the year', longDate('2008-01-20') === 'Jan 20, 2008' && longDate(null) === '');
check('air days read naturally', airs(['Sunday']) === 'New episodes Sundays'
  && airs(['Monday', 'Thursday']) === 'New episodes Mondays and Thursdays'
  && airs(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']) === 'New episodes weekdays' && airs([]) === '');

check('hosts lose their www', hostOf('https://www.netflix.com/title/1') === 'netflix.com' && hostOf('not a url') === '');
check('a subdomain is the same service', sameService('tv.apple.com', 'apple.com') && !sameService('apple.com', 'pineapple.com') && !sameService('', 'x.com'));
const watch = watchLinks('https://www.netflix.com/title/80057281', [{ name: 'Netflix', kind: 'stream', site: 'https://www.netflix.com/' }], null);
check('a streaming original links to its own page', same(watch, [{ name: 'Netflix', kind: 'stream', href: 'https://www.netflix.com/title/80057281', host: 'netflix.com' }]));
check('a network with no site of its own takes the show page',
  watchLinks('http://www.amc.com/shows/breaking-bad', [{ name: 'AMC', kind: 'network', site: null }], null)[0].href === 'http://www.amc.com/shows/breaking-bad');
check('a show page elsewhere does not stand in for the channel',
  watchLinks('https://www.thepitt.com/', [{ name: 'Max', kind: 'stream', site: 'https://www.max.com/' }], null)[0].href === 'https://www.max.com/');
check('Apple TV joins when iTunes sells it',
  watchLinks(null, [], 'https://itunes.apple.com/us/tv-season/x/id1').map(w => w.host).join() === 'tv.apple.com');
check('nothing to link is nothing', same(watchLinks(null, [{ name: 'X', kind: 'network', site: null }], null), []));
check('trailer searches name the show and year', trailerSearch('The Office', 2005).endsWith('The%20Office%202005%20official%20trailer'));

// Where to watch: TMDB's services first, TVmaze's channels and Apple TV without them.
const LINK = 'https://www.themoviedb.org/tv/66732/watch?locale=US';
const tmdb = { link: LINK, providers: [
  { name: 'Netflix', logo: 'https://image.tmdb.org/t/p/w92/n.jpg', kinds: ['flatrate'] },
  { name: 'Odd One', logo: null, kinds: ['flatrate'] },
  { name: 'Pluto TV', logo: 'https://image.tmdb.org/t/p/w92/p.jpg', kinds: ['free'] },
  { name: 'Tubi', logo: 'https://image.tmdb.org/t/p/w92/t.jpg', kinds: ['ads'] },
  { name: 'Apple TV', logo: 'https://image.tmdb.org/t/p/w92/a.jpg', kinds: ['rent', 'buy'] },
  { name: 'Vudu', logo: 'https://image.tmdb.org/t/p/w92/v.jpg', kinds: ['rent'] },
  { name: 'Amazon Video', logo: 'https://image.tmdb.org/t/p/w92/z.jpg', kinds: ['buy'] },
] };
const channels = [{ name: 'Netflix', kind: 'stream', site: 'https://www.netflix.com/' }];
const listed = whereToWatch('Stranger Things', tmdb, 'https://www.netflix.com/title/80057281', channels, 'https://itunes.apple.com/us/tv-season/x/id1');
check('TMDB\'s services come first, in the order given, and are credited to JustWatch',
  listed.credit && listed.links.map(w => w.name).join() === 'Netflix,Odd One,Pluto TV,Tubi,Apple TV,Vudu,Amazon Video');
check('every service links to TMDB\'s watch page', listed.links.every(w => w.href === LINK));
check('each carries TMDB\'s logo, or none', listed.links[0].logo === 'https://image.tmdb.org/t/p/w92/n.jpg' && listed.links[1].logo === null);
check('streaming goes unmarked and the rest say how', same(listed.links.map(w => w.note),
  ['', '', 'Free', 'With ads', 'Rent or buy', 'Rent', 'Buy']));
check('each link says what it offers and where it leads', listed.links[0].title === 'Stream Stranger Things on Netflix'
  && listed.links[0].label === 'Stream Stranger Things on Netflix, listed on TMDB, opens in a new tab'
  && listed.links[3].title === 'Watch Stranger Things free with ads on Tubi' && listed.links[6].title === 'Buy Stranger Things on Amazon Video');
const fallback = whereToWatch('Stranger Things', { link: LINK, providers: [] }, 'https://www.netflix.com/title/80057281', channels,
  'https://itunes.apple.com/us/tv-season/x/id1');
check('without TMDB\'s services, TVmaze\'s channel and Apple TV, uncredited', !fallback.credit
  && same(fallback.links.map(w => [w.name, w.href, w.note]), [['Netflix', 'https://www.netflix.com/title/80057281', ''],
    ['Apple TV', 'https://itunes.apple.com/us/tv-season/x/id1', 'Buy']]));
check('fallback icons come through this server', fallback.links[0].logo === '/api/icon?host=netflix.com'
  && fallback.links[1].logo === '/api/icon?host=tv.apple.com' && fallback.links[1].title === 'Buy Stranger Things on Apple TV'
  && fallback.links[0].label === 'Stream Stranger Things on Netflix, opens in a new tab');
check('services with no TMDB page to link are not shown', !whereToWatch('X', { link: null, providers: tmdb.providers }, null, [], null).credit);
check('no TMDB data at all is the fallback', same(whereToWatch('X', null, null, [], null), { credit: false, links: [] }));

check('search says what it found', searchNote('lost', 3, 0) === 'Shows matching “lost”'
  && searchNote('lost', 3, 1) === 'Shows matching “lost”');
check('shows only TVmaze has are not in the catalogue yet', searchNote('new show', 0, 1) === 'Nothing in the catalogue matches “new show” yet.');
check('only a search that found nothing anywhere suggests the spelling', searchNote('qzx', 0, 0) === 'Nothing matches “qzx”. Check the spelling.'
  && !searchNote('qzx', 1, 0).includes('spelling') && !searchNote('qzx', 0, 2).includes('spelling'));

// Recent searches: the last ten committed, newest first, once whatever the case, never one letter.
const { RECENT_SEARCHES, searchText, recentStore, noteSearch, withoutSearch, recentMatches } = await import('./format.js');
let searches = noteSearch([], 'breaking bad');
searches = noteSearch(searches, '  The   Office ');
searches = noteSearch(searches, 'Breaking Bad');
check('a committed search goes first, once whatever its case, as it was last typed', same(searches, ['Breaking Bad', 'The Office']));
check('an empty or one-letter search is not kept', noteSearch(searches, '') === searches && noteSearch(searches, '  v ') === searches
  && same(noteSearch([], 'V'), []) && same(noteSearch([], 'Vx'), ['Vx']) && same(noteSearch([], '海'), []));
let many = [];
for (let n = 1; n <= 12; n++) many = noteSearch(many, `show ${n}`);
check('ten are kept, the newest first', RECENT_SEARCHES === 10 && many.length === 10 && many[0] === 'show 12' && many[9] === 'show 3');
check('searches are kept tidy and no longer than a box takes', searchText('  dark \n matter ') === 'dark matter'
  && searchText('x'.repeat(140)).length === 100 && searchText(null) === '');
check('recent searches are read defensively', same(recentStore(['lost', 'LOST', 7, null, 'x', '  ', ' dark  matter ', { q: 'a' }]),
  ['lost', 'dark matter']) && same(recentStore('lost'), []) && same(recentStore(null), [])
  && recentStore(Array.from({ length: 30 }, (_, n) => `q${n}`)).length === 10);
check('one can be taken out whatever its case', same(withoutSearch(['Lost', 'Dark'], ' lost '), ['Dark']));
check('an empty box offers every recent search', same(recentMatches(['Lost', 'Dark', 'The Last of Us'], ' '), ['Lost', 'Dark', 'The Last of Us']));
check('typing offers those it begins, or begins a word of, but not the very search typed',
  same(recentMatches(['Lost', 'Dark', 'The Last of Us', 'Blast'], 'la'), ['The Last of Us'])
  && same(recentMatches(['Lost', 'Lost Girl', 'Dark'], 'LOST'), ['Lost Girl']) && same(recentMatches(['Dark'], 'q'), []));

// Browse: each genre's chip wears its short name, A to Z, and a letter jumps along the list.
const { shortGenre, genreChoices, nextByLetter } = await import('./format.js');
check('a chip drops the shows from a genre\'s name', shortGenre('Crime TV shows') === 'Crime' && shortGenre('Sci-fi shows') === 'Sci-fi'
  && shortGenre('Adventures') === 'Adventures' && shortGenre('Reality and competition') === 'Reality and competition');
const choices = genreChoices([{ key: 'Crime', label: 'Crime TV shows', poster: 'p' }, { key: 'Children', label: 'For the kids' },
  { key: 'animation', label: 'Animated series' }, { key: 'Action', label: 'Action shows' }]);
check('genres go A to Z by the name on their chip, keeping what they carry',
  same(choices.map(g => g.short), ['Action', 'Animated series', 'Crime', 'For the kids'])
  && choices[2].key === 'Crime' && choices[2].label === 'Crime TV shows' && choices[2].poster === 'p');
const letters = ['Action', 'Anime', 'Crime', 'Anthology'];
check('a letter jumps to the next name it begins, going round', nextByLetter(letters, 0, 'a') === 1
  && nextByLetter(letters, 1, 'A') === 3 && nextByLetter(letters, 3, 'a') === 0 && nextByLetter(letters, 0, 'c') === 2);
check('and nowhere when no name begins with it', nextByLetter(letters, 0, 'z') === -1);
// The home page: what a page depends on, when a kept page is shown again, what asking for
// more carries, merging an action, and Recently viewed.
const { pageKey, resumable, keptText, shownRows, withoutCard, viewedStore, noteViewed, recentlyViewed, RESUME_MINUTES, VIEWED_DAYS }
  = await import('./format.js');
const listA = { profile: [{ id: 1, weight: 1 }, { id: 2, weight: .7 }], settings: { known_min: 60, type: 'all' } };
check('a page key ignores the order of settings', pageKey(listA, [5]) === pageKey({ ...listA, settings: { type: 'all', known_min: 60 } }, [5]));
check('a page key changes with a rating or My List', pageKey(listA, [5]) !== pageKey(listA, [5, 6])
  && pageKey(listA, [5]) !== pageKey({ ...listA, profile: [{ id: 1, weight: .7 }, { id: 2, weight: .7 }] }, [5]));
const kept = { v: 1, at: 1_000_000, day: '2026-10-05', key: 'k', home: { rows: [] } };
const now = kept.at + (RESUME_MINUTES - 1) * 60_000;
check('a kept page comes back within half an hour, the same day and list', resumable(kept, { key: 'k', day: '2026-10-05', now }));
check('but not after', !resumable(kept, { key: 'k', day: '2026-10-05', now: kept.at + (RESUME_MINUTES + 1) * 60_000 }));
check('nor on another day or for another list', !resumable(kept, { key: 'k', day: '2026-10-06', now })
  && !resumable(kept, { key: 'other', day: '2026-10-05', now }));
check('nor when it is not a page', !resumable(null, { key: 'k', day: '2026-10-05', now })
  && !resumable({ ...kept, home: null }, { key: 'k', day: '2026-10-05', now }) && !resumable({ ...kept, v: 2 }, { key: 'k', day: '2026-10-05', now }));
const rows = [
  { key: 'top', kind: 'row', items: [1, 2, 3, 4, 5, 6, 7, 8].map(id => ({ id })) },
  { key: 'list', kind: 'list', items: [{ id: 9 }] },
  { key: 'recent', kind: 'recent', items: [{ id: 3 }] },
  { key: 'top10', kind: 'top10', items: [3, 10, 11].map(id => ({ id })) },
];
check('asking for more carries each row\'s key and first six, My List\'s own, and not Recently viewed',
  same(shownRows(rows, [9, 12]), [{ key: 'top', ids: [1, 2, 3, 4, 5, 6] }, { key: 'list', ids: [9, 12] }, { key: 'top10', ids: [3, 10, 11] }]));
check('a row past today\'s rows says which tier it came in, and a row kept from before says none',
  same(shownRows([{ key: 'decade-1990s', kind: 'row', tier: 2, items: [{ id: 4 }] }, { key: 'gems', kind: 'row', items: [{ id: 5 }] }]),
    [{ key: 'decade-1990s', ids: [4], tier: 2 }, { key: 'gems', ids: [5] }]));
const big = { v: 1, at: 1, day: '2026-10-05', key: 'k', home: { more: false, rows: Array.from({ length: 50 }, (_, n) => ({
  key: `r${n}`, kind: 'row', items: Array.from({ length: 20 }, (_, m) => ({ id: n * 100 + m, name: 'A show with a long name' })) })) } };
check('a kept page is stored whole while it fits', keptText(big) === JSON.stringify(big));
const trimmed = JSON.parse(keptText(big, 40_000));
check('past its budget it keeps its first rows and asks for the rest again', keptText(big, 40_000).length <= 40_000
  && trimmed.home.more === true && trimmed.home.rows.length > 1 && trimmed.home.rows.length < 50
  && same(trimmed.home.rows, big.home.rows.slice(0, trimmed.home.rows.length)) && trimmed.key === 'k');
const merged = withoutCard(rows, 3);
check('an acted-on card leaves the rows chosen for you, and every other card keeps its place',
  same(merged[0].items.map(c => c.id), [1, 2, 4, 5, 6, 7, 8]) && merged[0].key === 'top');
check('the Top 10 keeps its ten', same(merged[3].items.map(c => c.id), [3, 10, 11]));
const day = 20_000;
let viewed = viewedStore([{ id: 1, d: day - 20, name: 'Old' }, { id: 2, d: day - 3, name: 'Two', poster: 'javascript:x' }, 'junk',
  { id: 'x', d: day }]);
check('viewed titles are read defensively, posters only from TVmaze', viewed.length === 2 && viewed[1].poster === null);
viewed = noteViewed(viewed, { id: 3, name: 'Three', year: 2020, poster: 'https://static.tvmaze.com/p.jpg' }, day);
viewed = noteViewed(viewed, { id: 2, name: 'Two' }, day);
check('a title opened again moves to the end, once', same(viewed.map(v => v.id), [1, 3, 2]));
check('recently viewed is the last fortnight, newest first', same(recentlyViewed(viewed, day).map(v => v.id), [2, 3])
  && VIEWED_DAYS === 14);
check('rated and listed titles leave it', same(recentlyViewed(viewed, day, { rated: new Set([2]), saved: new Set([3]) }), []));

// Answers kept by what was asked: within their time, shared while in flight, never a failure.
const { keeper, sessionAnswers } = await import('./format.js');
let clock = 1_000;
const asked = keeper({ most: 3, now: () => clock });
let requests = 0;
const answer = value => () => { requests++; return Promise.resolve({ value }); };
const [one, two] = await Promise.all([asked('a', 100, answer(1)), asked('a', 100, answer(2))]);
check('two asking at once share one request', requests === 1 && one === two && one.value === 1);
clock += 99;
check('asking again within its time gets the same answer without a request',
  (await asked('a', 100, answer(3))) === one && requests === 1);
clock += 1;
check('past its time it is asked again', (await asked('a', 100, answer(4))).value === 4 && requests === 2);
check('another question is asked on its own', (await asked('b', 100, answer(5))).value === 5 && requests === 3);
let failed = '';
await asked('c', 100, () => { requests++; return Promise.reject(new Error('down')); }).catch(e => { failed = e.message; });
check('a failure reaches the caller and is not kept', failed === 'down'
  && (await asked('c', 100, answer(6))).value === 6 && requests === 5);
await asked('d', 100, answer(7));
check('past the most it keeps, the oldest go first', (await asked('a', 100, answer(8))).value === 8 && requests === 7
  && (await asked('d', 100, answer(9))).value === 7 && requests === 7);
let thrown = '';
await asked('e', 100, () => { throw new Error('at once'); }).catch(e => { thrown = e.message; });
check('an ask that throws at once fails like any other', thrown === 'at once');
const at = 50_000;
check('answers kept for a reload are read defensively, the newest that are young enough',
  same(sessionAnswers({ '/api/extra?id=1': { at: at - 10, value: { details: 1 } }, '/api/rating?id=2': { at: at - 99_999, value: {} },
    '/api/trailer?id=3': { at: at - 5, value: { videos: [] } }, 'elsewhere': { at, value: {} }, '/api/x': { at, value: 'text' },
    '/api/y': null, '/api/z': { at: at + 5, value: {} } }, at, 60_000, 1), { '/api/trailer?id=3': { at: at - 5, value: { videos: [] } } })
  && same(sessionAnswers(null, at, 1), {}) && same(sessionAnswers([1], at, 1), {}) && same(sessionAnswers('x', at, 1), {}));

// The service worker (sw.js), run against a stand-in for the browser's caches and network.
const { readFileSync } = await import('node:fs');
const { createHash } = await import('node:crypto');
const SITE = 'https://couch.test';
const hash16 = text => createHash('sha256').update(text).digest('hex').slice(0, 16);
function stubWorker({ files, network, build = 'b1', mostSmall = 1000 }) {
  const on = {}, stores = new Map(), fetched = [];
  let tick = 0, skipped = false;
  const key = r => new URL(typeof r === 'string' ? r : r.url, SITE).href;
  const store = name => stores.get(name) || stores.set(name, new Map()).get(name);
  const cache = m => ({
    match: async r => m.get(key(r))?.clone(),
    put: async (r, response) => { m.delete(key(r)); m.set(key(r), response); },
    keys: async () => [...m.keys()].map(url => ({ url })),
    delete: async r => m.delete(key(r)),
  });
  const caches = {
    open: async name => cache(store(name)),
    keys: async () => [...stores.keys()],
    delete: async name => stores.delete(name),
    match: async (r, { cacheName } = {}) => {
      for (const [name, m] of stores) if ((!cacheName || name === cacheName) && m.has(key(r))) return m.get(key(r)).clone();
    },
  };
  const fetch = async (r, init = {}) => {
    const url = key(r);
    fetched.push(`${(typeof r === 'string' ? init.mode : r.mode) || 'cors'} ${url.replace(SITE, '')}`);
    return network(url);
  };
  const self = { addEventListener: (type, fn) => { on[type] = fn; }, location: new URL(SITE), skipWaiting: () => { skipped = true; },
    clients: { claim: async () => {} } };
  const source = readFileSync(new URL('./sw.js', import.meta.url), 'utf8').replace('__BUILD__', build)
    .replace('__FILES__', JSON.stringify(files)).replace('MOST_SMALL = 1000', `MOST_SMALL = ${mostSmall}`);
  new Function('self', 'caches', 'fetch', 'crypto', 'Request', 'Response', 'Date', 'setTimeout', source)(
    self, caches, fetch, globalThis.crypto, Request, Response, { now: () => ++tick }, done => Promise.resolve().then(done));
  const waiting = [];
  const extendable = extra => ({ ...extra, waitUntil: p => waiting.push(p) });
  const settle = async () => { while (waiting.length) await waiting.shift().catch(() => {}); };
  return {
    stores, fetched, skipped: () => skipped,
    install: async () => { const e = extendable(); on.install(e); try { await Promise.all(waiting.splice(0)); return true; } catch { return false; } },
    activate: async () => { on.activate(extendable()); await settle(); },
    message: data => on.message({ data }),
    ask: async (path, { mode = 'no-cors', destination = '' } = {}) => {
      let answer;
      on.fetch(extendable({ request: { method: 'GET', url: new URL(path, SITE).href, mode, destination }, respondWith: p => { answer = p; } }));
      const response = await answer;
      await settle();
      return response;
    },
  };
}
const shellFiles = { '/main.js': 'main build one', '/style.css': 'style build one', '/offline.html': 'offline page' };
const files = Object.fromEntries(Object.entries(shellFiles).map(([path, body]) => [path, hash16(body)]));
const siteOf = (pages, { down = false } = {}) => async url => {
  if (down) throw new TypeError('offline');
  const hit = pages[url.replace(SITE, '')] ?? pages[url];
  if (!hit) return new Response('none', { status: 404 });
  return new Response(hit.body ?? hit, { status: 200, headers: hit.headers ?? {} });
};
const page = (body, build = 'b1', etag = '"p1"') => ({ body, headers: { 'X-Build': build, ETag: etag } });
let net = siteOf({ ...shellFiles, '/': page('the page') });
let sw = stubWorker({ files, network: url => net(url) });
check('the service worker keeps the page and every file of its build, checked first', await sw.install()
  && same([...sw.stores.get('couchside-b1').keys()].map(u => u.replace(SITE, '')).sort(), ['/', '/main.js', '/offline.html', '/style.css']));
net = siteOf({ ...shellFiles, '/main.js': 'main build two', '/': page('the page') });
let mixed = stubWorker({ files, network: url => net(url) });
check('a file from another build fails the install, and nothing is kept', !(await mixed.install()) && !mixed.stores.size);
net = siteOf({ ...shellFiles, '/': page('the next page', 'b2') });
mixed = stubWorker({ files, network: url => net(url) });
check('so does a page from another build', !(await mixed.install()) && !mixed.stores.size);
net = siteOf({ ...shellFiles, '/': page('the page') });
sw.fetched.length = 0;
let got = await sw.ask('/browse?genre=Crime', { mode: 'navigate' });
check('any of the app\'s pages starts from the page kept, and the network is asked for it again behind',
  (await got.text()) === 'the page' && same(sw.fetched, ['cors /']));
net = siteOf({ ...shellFiles, '/': page('the page, a new catalogue', 'b1', '"p2"') });
await sw.ask('/', { mode: 'navigate' });
check('a changed page of the same build is kept for the next load', (await (await sw.ask('/list', { mode: 'navigate' })).text()) === 'the page, a new catalogue');
net = siteOf({ ...shellFiles, '/': page('a page from the next deploy', 'b2', '"p3"') });
await sw.ask('/', { mode: 'navigate' });
check('but never a page from another build', (await (await sw.ask('/', { mode: 'navigate' })).text()) === 'the page, a new catalogue');
sw.fetched.length = 0;
check('the build\'s files come from what it kept', (await (await sw.ask('/main.js', { mode: 'cors' })).text()) === 'main build one'
  && !sw.fetched.length);
net = siteOf({}, { down: true });
check('without a connection, a page that is not the app\'s is the offline page',
  (await (await sw.ask('/nope', { mode: 'navigate' })).text()) === 'offline page');
const poster = n => `https://static.tvmaze.com/uploads/images/medium_portrait/0/${n}.jpg`;
const images = Object.fromEntries([1, 2, 3, 4, 5].map(n => [poster(n), `poster ${n}`]));
net = siteOf({ ...images, [poster(9)]: undefined });
sw = stubWorker({ files, network: url => net(url), mostSmall: 3 });
sw.fetched.length = 0;
const img = { mode: 'no-cors', destination: 'image' };
got = await sw.ask(poster(1), img);
check('an image is fetched with CORS the first time, and kept', (await got.text()) === 'poster 1' && same(sw.fetched, [`cors ${poster(1)}`])
  && sw.stores.get('couchside-images').has(poster(1)));
sw.fetched.length = 0;
check('and comes from what was kept after that', (await (await sw.ask(poster(1), img)).text()) === 'poster 1' && !sw.fetched.length);
await sw.ask(poster(9), img);
check('a missing image is not kept', !sw.stores.get('couchside-images').has(poster(9)));
for (const n of [2, 3]) await sw.ask(poster(n), img);
await sw.ask(poster(1), img);
for (const n of [4, 5]) await sw.ask(poster(n), img);
check('past the most it keeps, the least recently shown go', same([...sw.stores.get('couchside-images').keys()].sort(),
  [poster(1), poster(4), poster(5)]));
net = siteOf({}, { down: true });
sw.fetched.length = 0;
let failure = '';
await sw.ask(poster(7), img).catch(e => { failure = e.message; });
check('an image that cannot be fetched with CORS is asked for as the page asked, and never kept', failure === 'offline'
  && same(sw.fetched, [`cors ${poster(7)}`, `no-cors ${poster(7)}`]) && !sw.stores.get('couchside-images').has(poster(7)));
sw.stores.set('couchside-0ld', new Map()).set('couchside-b1', new Map()).set('elsewhere', new Map());
await sw.activate();
check('taking over clears older builds, and keeps its own, the images and what is not its own',
  same([...sw.stores.keys()].sort(), ['couchside-b1', 'couchside-images', 'elsewhere']));
sw.message('take-over');
check('the page that found a new build lets it take over', sw.skipped());

console.log(fails ? `\n${fails} failed` : '\nall format checks passed');
process.exit(fails ? 1 : 0);
