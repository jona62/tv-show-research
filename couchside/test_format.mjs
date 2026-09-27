import { years, runtime, seasons, joinNames, parseRoute, withShow, hue, premiere, longDate, airs } from './format.js';
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
check('home route', same(parseRoute('/', ''), { page: 'home', q: '', show: null }));
check('search route keeps its terms', same(parseRoute('/search', '?q=breaking%20bad'), { page: 'search', q: 'breaking bad', show: null }));
check('a title opens over any page', same(parseRoute('/list', '?show=169'), { page: 'list', q: '', show: 169 }));
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
console.log(fails ? `\n${fails} failed` : '\nall format checks passed');
process.exit(fails ? 1 : 0);
