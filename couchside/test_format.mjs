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

console.log(fails ? `\n${fails} failed` : '\nall format checks passed');
process.exit(fails ? 1 : 0);
