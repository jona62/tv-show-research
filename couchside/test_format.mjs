import { years, runtime, seasons, joinNames, parseRoute, withShow, hue, premiere, longDate, airs,
  hostOf, sameService, watchLinks, trailerSearch } from './format.js';
let fails = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + extra}`); if (!ok) fails++; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

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
console.log(fails ? `\n${fails} failed` : '\nall format checks passed');
process.exit(fails ? 1 : 0);
