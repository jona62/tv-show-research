import { tieText, leaning, leaningHeading } from '../client/format.js';
import { years, runtime, seasons, joinNames, parseRoute, needsHomeFeed, withShow, hue, premiere, longDate, airs,
  hostOf, sameService, watchLinks, whereToWatch, trailerSearch, searchNote } from '../client/format.js';
import { SNIPPETS, snippet, revealLabel } from '../client/format.js';
import { withPerson, isoDay, yearsBetween, bornOn, diedOn, selfName, selfHeading, creditLines, knownFor } from '../client/format.js';
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
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
check('home route', same(parseRoute('/', ''), { page: 'home', q: '', genre: '', show: null, episode: null, person: null }));
check('only visible recommendation views need the Home feed',
  needsHomeFeed(parseRoute('/', '')) && needsHomeFeed(parseRoute('/new', ''))
  && needsHomeFeed(parseRoute('/search', '?q=x'))
  && ['/compare', '/browse', '/list', '/welcome'].every(path => !needsHomeFeed(parseRoute(path, '')))
  && !needsHomeFeed(parseRoute('/search', '?q=Lost'))
  && !needsHomeFeed(parseRoute('/', '?show=82'))
  && !needsHomeFeed(parseRoute('/', '?person=1'))
  && !needsHomeFeed(parseRoute('/', ''), {onboarded:false})
  && !needsHomeFeed(parseRoute('/new', ''), {independentNew:true}));
check('comparison is its own page and keeps an open title', parseRoute('/compare', '?compare=169,16149&show=169').page === 'compare'
  && parseRoute('/compare', '?compare=169,16149&show=169').show === 169);
check('search route keeps its terms', same(parseRoute('/search', '?q=breaking%20bad'), { page: 'search', q: 'breaking bad', genre: '', show: null, episode: null, person: null }));
check('a title opens over any page', same(parseRoute('/list', '?show=169'), { page: 'list', q: '', genre: '', show: 169, episode: null, person: null }));
check('browse keeps its genre', same(parseRoute('/browse', '?genre=Science-Fiction'), { page: 'browse', q: '', genre: 'Science-Fiction', show: null, episode: null, person: null }));
check('a person opens over the title they were opened from', same(parseRoute('/search', '?q=bad&show=169&person=14245'),
  { page: 'search', q: 'bad', genre: '', show: 169, episode: null, person: 14245 }));
check('and over one of its episodes', same(parseRoute('/', '?show=169&episode=12203&person=14245'),
  { page: 'home', q: '', genre: '', show: 169, episode: 12203, person: 14245 }));
check('and over any page on their own', parseRoute('/', '?person=14245').person === 14245 && parseRoute('/', '?person=14245').show === null);
check('a bad person id is ignored', ['abc', '0', '-3', '1.5', ''].every(id => parseRoute('/', `?person=${id}`).person === null));
check('a bad title id is ignored', parseRoute('/', '?show=abc').show === null && parseRoute('/', '?show=-4').show === null
  && parseRoute('/', '?show=1.5').show === null);
check('an unknown path falls back to home', parseRoute('/nope', '').page === 'home');
check('opening a title keeps the search', withShow('/search', '?q=bad', 169) === '/search?q=bad&show=169');
check('a different title clears the previous episode view and preserves comparison choices',
  withShow('/compare', '?compare=169%2C16149&show=169&rating-view=grid&rating-season=2&rating-inverted=1', 16149)
  === '/compare?compare=169%2C16149&show=16149');
check('the same title keeps its selected view',
  withShow('/', '?show=169&rating-view=grid&rating-season=2&rating-inverted=1', 169)
  === '/?show=169&rating-view=grid&rating-season=2&rating-inverted=1');
check('closing a title leaves a clean path', withShow('/', '?show=169', null) === '/'
  && withShow('/search', '?q=bad&show=169', null) === '/search?q=bad');
check('opening a person keeps the page and the title beneath them',
  withPerson('/search', '?q=bad&show=169', 14245) === '/search?q=bad&show=169&person=14245');
check('closing them goes back to the title, or the page', withPerson('/', '?show=169&person=14245', null) === '/?show=169'
  && withPerson('/', '?person=14245', null) === '/');
check('a title opened from them leaves them out of its address',
  withShow('/', withPerson('', '?show=169&person=14245', null), 568) === '/?show=568'
  && withShow('/', withPerson('', '?person=14245', null), 568) === '/?show=568');
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
check('a search with no title matches but shows like it says so, and blames no spelling',
  searchNote('the matrix', 0, 0, 18) === 'No titles match “the matrix”.' && searchNote('mad max', 1, 0, 18) === 'Shows matching “mad max”');

// A title page's long parts start short.
check('a season starts with three episodes and the trailers with two, or a wide row of three',
  SNIPPETS.episodes === 3 && SNIPPETS.clips === 2 && SNIPPETS.clipsWide === 3);
check('a wide screen shows three trailers of six, and all of four', snippet(6, SNIPPETS.clipsWide) === 3
  && snippet(4, SNIPPETS.clipsWide) === 4);
check('a long part shows its snippet', snippet(10, 3) === 3 && snippet(5, 2) === 2);
check('a part one longer than its snippet, or shorter, shows whole', snippet(4, 3) === 4 && snippet(3, 2) === 3
  && snippet(2, 2) === 2 && snippet(0, 3) === 0);
check('the episodes button says how many it opens, and closes them again',
  revealLabel('episodes', 10, false) === 'Show all 10 episodes' && revealLabel('episodes', 10, true) === 'Show fewer episodes');
check('the trailers button says how many there are', revealLabel('clips', 6, false) === 'Show all (6)'
  && revealLabel('clips', 6, true) === 'Show fewer');
check('no button text carries a dash', ['episodes', 'clips'].every(part => [true, false].every(open =>
  !/[\u2013\u2014]/.test(revealLabel(part, 7, open)))));

// An episode: its address beside its title's, its numbering, its neighbours in the season,
// its credits and when it airs.
const { withEpisode, episodeCode, episodeSaid, neighbours, credits, airing } = await import('../client/format.js');
check('an episode opens over its title, over any page', same(parseRoute('/search', '?q=bad&show=169&episode=12203'),
  { page: 'search', q: 'bad', genre: '', show: 169, episode: 12203, person: null }));
check('a bad episode id is ignored, and so is one without a title', parseRoute('/', '?show=169&episode=abc').episode === null
  && parseRoute('/', '?show=169&episode=-2').episode === null && parseRoute('/', '?show=169&episode=2.5').episode === null
  && parseRoute('/', '?episode=12203').episode === null);
check('opening an episode keeps the page and its title', withEpisode('/search', '?q=bad&show=169', 12203) === '/search?q=bad&show=169&episode=12203');
check('stepping to another replaces it', withEpisode('/', '?show=169&episode=12203', 12204) === '/?show=169&episode=12204');
check('closing it leaves the title open', withEpisode('/list', '?show=169&episode=12203', null) === '/list?show=169');
check('closing the title, or opening another, closes its episode too', withShow('/', '?show=169&episode=12203', null) === '/'
  && withShow('/search', '?q=bad&show=169&episode=12203', 82) === '/search?q=bad&show=82');
check('an episode is numbered S2 E5, and read out in words', episodeCode(2, 5) === 'S2 E5' && episodeSaid(2, 5) === 'Season 2, episode 5');
check('a special says so, with its season when it has one', episodeCode(2, null) === 'S2 Special' && episodeCode(null, null) === 'Special'
  && episodeSaid(2, null) === 'Season 2, special' && episodeSaid(null, null) === 'Special' && episodeSaid(null, 4) === 'Episode 4'
  && episodeCode(null, 4) === 'E4');
const season = [{ id: 1, number: 1 }, { id: null, number: null }, { id: 3, number: 2 }, { id: 4, number: null }, { id: 5, number: 3 }];
check('the episodes either side are the season\'s own, specials and all', same(neighbours(season, 4), { prev: season[2], next: season[4] }));
check('an episode that cannot be opened is stepped over', same(neighbours(season, 3), { prev: season[0], next: season[3] }));
check('the first has nothing before it and the last nothing after',
  neighbours(season, 1).prev === null && neighbours(season, 1).next === season[2] && neighbours(season, 5).next === null);
check('one not in the list, or no list, has neither', same(neighbours(season, 99), { prev: null, next: null })
  && same(neighbours(null, 1), { prev: null, next: null }));
const made = credits([{ id: 1, name: 'A', role: 'Writer' }, { id: 2, name: 'B', role: 'Creator' }, { id: 3, name: 'C', role: 'Director' },
  { id: 4, name: 'D', role: 'Writer' }, { id: 5, name: 'E', role: 'Teleplay' }, { id: 6, name: 'F' }]);
check('credits read directors first, then writers, then the rest, each job with everyone who did it',
  same(made.map(c => [c.label, c.people.map(p => p.name)]),
    [['Directed by', ['C']], ['Written by', ['A', 'D']], ['Teleplay by', ['E']], ['Creator:', ['B']]]));
check('no crew is no credits', same(credits([]), []) && same(credits(null), []));
check('a job named like something every object has is still just a job',
  same(credits([{ id: 1, name: 'A', role: 'constructor' }]).map(c => c.label), ['constructor:']));
const NOW = Date.parse('2026-09-29T12:00:00Z');
check('an episode that aired shows the day it aired', airing('2009-04-05', '2009-04-06T02:00:00+00:00', NOW, 'UTC') === 'Apr 5, 2009'
  && airing('2009-04-05', '', NOW) === 'Apr 5, 2009');
check('one still to come says when it airs, in the reader\'s own time',
  airing('2026-10-06', '2026-10-07T01:00:00+00:00', NOW, 'America/New_York') === 'Airs Tue, Oct 6, 9:00 PM'
  && airing('2026-10-06', '2026-10-07T01:00:00+00:00', NOW, 'Europe/London') === 'Airs Wed, Oct 7, 2:00 AM');
check('and the year, when it is not this one', airing('2027-01-05', '2027-01-06T02:00:00+00:00', NOW, 'America/New_York')
  === 'Airs Tue, Jan 5, 2027, 9:00 PM');
check('one to come without a time says only the day', airing('2026-10-06', '', NOW) === 'Airs Oct 6, 2026');
check('nothing known is nothing said', airing('', '', NOW) === '' && airing('soon', 'later', NOW) === '');
check('the guest stars start with twelve faces, and the button says how many it opens',
  SNIPPETS.guests === 12 && revealLabel('guests', 21, false) === 'Show all 21 guest stars'
  && revealLabel('guests', 21, true) === 'Show fewer guest stars');
check('nothing an episode says carries a dash', ![episodeCode(2, 5), episodeSaid(2, null), revealLabel('guests', 13, false),
  ...made.map(c => c.label), airing('2026-10-06', '2026-10-07T01:00:00+00:00', NOW, 'UTC')].some(t => /[\u2013\u2014]/.test(t)));

// A person's page: when they were born and died, and what each of their credits says.
check('a person\'s roles start with whole lines of posters, three on a phone and six on a wide screen',
  SNIPPETS.roles % 3 === 0 && SNIPPETS.roles % 6 === 0 && SNIPPETS.appearances === 6 && SNIPPETS.crew === 6);
check('their parts open with the same button as a title\'s', revealLabel('roles', 44, false) === 'Show all (44)'
  && revealLabel('roles', 44, true) === 'Show fewer');
check('an age counts whole years, the birthday itself included', yearsBetween('1956-03-07', '2026-03-06') === 69
  && yearsBetween('1956-03-07', '2026-03-07') === 70 && yearsBetween('1956-03-07', '2026-12-31') === 70
  && yearsBetween('2000-02-29', '2026-02-28') === 25);
check('there is no age without both days, or before being born', yearsBetween(null, '2026-01-01') === null
  && yearsBetween('1956-03-07', '') === null && yearsBetween('soon', '2026-01-01') === null && yearsBetween('2030-01-01', '2026-01-01') === null);
check('today is the reader\'s own day', isoDay(new Date(2026, 8, 29, 23, 59)) === '2026-09-29' && isoDay(new Date(2026, 0, 5)) === '2026-01-05');
check('a birth reads with where it was, when both are known',
  bornOn('1956-03-07', 'Hollywood, California, United States') === 'Mar 7, 1956 in Hollywood, California, United States'
  && bornOn('1956-03-07', '') === 'Mar 7, 1956' && bornOn(null, 'Seoul, South Korea') === 'Seoul, South Korea' && bornOn(null, null) === '');
check('a death reads with the age at it', diedOn('1969-08-19', '2023-10-28') === 'Oct 28, 2023 (aged 54)'
  && diedOn(null, '2023-10-28') === 'Oct 28, 2023' && diedOn('1969-08-19', null) === '');
check('someone as themselves reads by TVmaze\'s gender, or plainly', selfName('Male') === 'Himself' && selfName('Female') === 'Herself'
  && selfName(null) === 'Self' && selfHeading('Female') === 'As herself' && selfHeading('Non-binary') === 'As themselves');
const regular = creditLines({ as: 'Walter White', regular: true, episodes: null, years: [2008, 2013] }, 'Male');
check('a regular part says whom they play and the show\'s years', regular.as === 'Walter White' && regular.when === '2008–2013'
  && regular.said === 'as Walter White, 2008–2013');
const guestPart = creditLines({ as: 'Tim Whatley', episodes: 5, years: [1994, 1997] }, 'Male');
check('a guest part says how many episodes and when they aired', guestPart.when === '5 episodes · 1994–1997'
  && guestPart.said === 'as Tim Whatley, 5 episodes, 1994–1997');
check('one episode is one, and one year is one year', creditLines({ as: 'Ron', episodes: 1, years: [2012, 2012] }).when === '1 episode · 2012');
const voiced = creditLines({ as: 'Bert', voice: true, episodes: 8, years: [2008, 2020] });
check('a part by voice says so', voiced.as === 'Voice of Bert' && voiced.said === 'voice of Bert, 8 episodes, 2008–2020'
  && creditLines({ voice: true, years: [] }).as === 'Voice');
const themselves = creditLines({ self: true, as: '', episodes: 12, years: [2015, 2026] }, 'Female');
check('an appearance as themselves says so', themselves.as === 'Herself' && themselves.said === 'as herself, 12 episodes, 2015–2026');
check('a show they made says what they did', creditLines({ jobs: ['Creator', 'Executive Producer'], years: [2015, 2019] }).as
  === 'Creator, Executive Producer');
check('a show with no years says none', creditLines({ as: 'Someone', years: [] }).when === '' && creditLines({ as: 'Someone' }).when === '');
check('no credit line carries a dash in place of words', [regular, guestPart, voiced, themselves].every(l => !/\u2014/.test(l.as + l.when + l.said)));
check('someone is known for their first three roles, which come best known first',
  knownFor([{ name: 'A' }, { name: 'B' }, { name: 'C' }, { name: 'D' }]) === 'A, B and C' && knownFor([{ name: 'A' }]) === 'A' && knownFor([]) === '');
check('regular roles come before parts they guested in', knownFor([{ name: 'Guest' }, { name: 'Lead', regular: true }]) === 'Lead');
check('someone with no regular role who made shows is known for those, named as created',
  knownFor([{ name: 'Krapopolis' }, { name: 'Community' }], ['Breaking Bad']) === ''
  && knownFor([{ name: 'Lead', regular: true }], ['Breaking Bad']) === 'Lead');

// Recent searches: the last ten committed, newest first, once whatever the case, never one letter.
const { RECENT_SEARCHES, searchText, recentStore, noteSearch, withoutSearch, recentMatches } = await import('../client/format.js');
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

// Shows like a search: a row stays through answers without one only while the search grows.
const { keepsRow } = await import('../client/format.js');
check('a row stays while its search grows letter by letter, whatever the case',
  keepsRow('breaki', 'breakin') && keepsRow('mad m', 'Mad Ma') && keepsRow('game of', 'game of  t'));
check('a row goes for a search cut back, the same search, another, or none shown',
  !keepsRow('zombies', 'zombi') && !keepsRow('zombies', 'zombies') && !keepsRow('mad max', 'dark') && !keepsRow('', 'dark'));

// Browse: each genre's chip wears its short name, A to Z, and a letter jumps along the list.
const { shortGenre, genreChoices, nextByLetter } = await import('../client/format.js');
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
// The home page: what a page depends on, when a visit goes on, when a kept page is shown
// again, what asking for more carries, merging an action, and Recently viewed.
const { pageKey, ongoing, resumable, keptText, shownRows, withoutCard, viewedStore, noteViewed, recentlyViewed, AWAY_MINUTES,
  VIEWED_DAYS } = await import('../client/format.js');
const listA = { profile: [{ id: 1, weight: 1 }, { id: 2, weight: .7 }], settings: { known_min: 60, type: 'all' } };
check('a page key ignores the order of settings', pageKey(listA, [5]) === pageKey({ ...listA, settings: { type: 'all', known_min: 60 } }, [5]));
check('a page key changes with a rating or My List', pageKey(listA, [5]) !== pageKey(listA, [5, 6])
  && pageKey(listA, [5]) !== pageKey({ ...listA, profile: [{ id: 1, weight: .7 }, { id: 2, weight: .7 }] }, [5]));
// A visit, and when the next begins: the tab left for half an hour, or a new day.
const left = 1_000_000;
const visitOn = { day: '2026-10-05', n: 2, at: left, ask: { day: '2026-10-05', seed: 'ab'.repeat(8), visit: 'cd'.repeat(8) } };
check('a visit goes on through a reload, and a return within half an hour of leaving',
  AWAY_MINUTES === 30 && ongoing(visitOn, { day: '2026-10-05', now: left + 1000 })
  && ongoing(visitOn, { day: '2026-10-05', now: left + (AWAY_MINUTES - 1) * 60_000 }));
check('the app opened again after half an hour away is a new visit',
  !ongoing(visitOn, { day: '2026-10-05', now: left + (AWAY_MINUTES + 1) * 60_000 }));
check('and so is the next day, however soon', !ongoing(visitOn, { day: '2026-10-06', now: left + 60_000 }));
check('and a new tab, which keeps no visit, or one kept askew', !ongoing(null, { day: '2026-10-05', now: left })
  && !ongoing({ ...visitOn, n: 0 }, { day: '2026-10-05', now: left }) && !ongoing({ ...visitOn, at: 'x' }, { day: '2026-10-05', now: left })
  && !ongoing(visitOn, { day: '2026-10-05', now: left - 60_000 }));
const kept = { v: 2, at: left, day: '2026-10-05', visit: 2, key: 'k', home: { rows: [], ask: visitOn.ask } };
const thisVisit = { day: '2026-10-05', n: 2 };
check('a kept page comes back in its own visit, for the same list', resumable(kept, { key: 'k', visit: thisVisit }));
check('but never in the next visit, even the same day, nor on another day',
  !resumable(kept, { key: 'k', visit: { day: '2026-10-05', n: 3 } }) && !resumable(kept, { key: 'k', visit: { day: '2026-10-06', n: 2 } }));
check('nor for another list', !resumable(kept, { key: 'other', visit: thisVisit }));
check('nor when it is not a page, or a page kept before visits', !resumable(null, { key: 'k', visit: thisVisit })
  && !resumable({ ...kept, home: null }, { key: 'k', visit: thisVisit })
  && !resumable({ v: 1, at: left, day: '2026-10-05', key: 'k', home: { rows: [] } }, { key: 'k', visit: thisVisit }));
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

// The featured shows go round: each slide is drawn in its slot nearest the strip, so after
// the last comes the first, from the right, and before the first the last, from the left.
// A swipe turns the slide a fifth of the way on, or flicked, and no move wants a slide in
// two slots at once.
const { TURN_EVERY, slideIn, slotOf, slotsShown, reach, slideLabel, TURN, landing, TURN_MS, TURN_OWN_MS, glideTime,
  turnTime } = await import('../client/format.js');
check('a featured show turns to the next every seven seconds or so', TURN_EVERY >= 6000 && TURN_EVERY <= 8000);
check('slots go round the slides both ways', same([-7, -6, -1, 0, 5, 6, 13].map(k => slideIn(k, 6)), [5, 0, 5, 0, 5, 0, 1]));
check('after the last of six comes the first, from the right', slotOf(0, 5, 6) === 6 && slotOf(4, 5, 6) === 4
  && slotOf(5, 5, 6) === 5);
check('and before the first comes the last, from the left', slotOf(5, 0, 6) === -1 && slotOf(1, 0, 6) === 1);
check('however far round the strip has gone', slotOf(0, 29, 6) === 30 && slotOf(5, -12, 6) === -13);
const onScreen = at => [0, 1, 2, 3, 4, 5].map(i => slotOf(i, at, 6)).filter(k => Math.abs(k - at) < 1).sort((a, b) => a - b);
check('while it moves, the two slides on screen are neighbours', same(onScreen(5.4), [5, 6]) && same(onScreen(-.3), [-1, 0]));
check('of two slides, the other waits ahead, and moves to whichever side the strip heads',
  slotOf(1, 0, 2) === 1 && slotOf(1, .2, 2) === 1 && slotOf(1, -.2, 2) === -1 && slotOf(0, 1, 2) === 2 && slotOf(0, .8, 2) === 0);
check('a move shows every slot within one of its way', slotsShown(0, 1) === 2 && slotsShown(.4, 2) === 3
  && slotsShown(3, 3) === 1 && slotsShown(2.5, 0) === 4);
check('a move goes as far as it is sent while there are slides enough', reach(0, 3, 6) === 3 && reach(.4, 2, 3) === 2
  && reach(0, -1, 2) === -1);
check('two slides caught on their way go on no further than the next', reach(.4, 2, 2) === 1 && reach(-.4, -2, 2) === -1);
check('a slide is called by its place and name', slideLabel(1, 6, 'Luther') === '2 of 6: Luther');
check('a swipe a fifth of the way on turns the slide', TURN === .2 && landing(.2, 0, 390, 0) === 1
  && landing(-.25, 0, 390, 0) === -1);
check('a shorter one comes back', landing(.1, 0, 390, 0) === 0 && landing(-.15, 0, 390, 0) === 0);
check('its speed counts as distance still to come', landing(.1, -.5, 390, 0) === 1 && landing(-.1, .5, 390, 0) === -1);
check('a flick turns it however little it came', landing(.03, -.35, 1280, 0) === 1);
check('flicked back the other way, it stays', landing(.6, .4, 390, 0) === 0 && landing(-.6, -.4, 390, 0) === 0);
check('caught on its way, it settles where its speed carries it', landing(.6, 0, 390) === 1 && landing(.4, 0, 390) === 0
  && landing(.4, -1, 390) === 1);
check('it comes to rest in a slot on screen, however hard it was thrown', landing(.9, -5, 390, 0) === 1
  && landing(.2, 5, 390) === 0);
check('a swipe comes to rest at the speed it was let go', glideTime(300, -2) === 180 && glideTime(300, 1) === 300
  && glideTime(300, 0) === 375 && glideTime(1000, 0) === 420);
check('a button turns it steadily, a little longer for each slot further', turnTime(1) === TURN_MS
  && turnTime(-3) === TURN_MS + 240 && turnTime(9) === 840 && TURN_OWN_MS > TURN_MS);

// Loading ahead of the reader: a row's posters two screens before it is seen, those it
// shows and the next two, and more rows while three screens of them are still to come.
const { POSTERS_AHEAD, ROWS_AHEAD, CARDS_AHEAD, POSTERS_AT_ONCE, FLUNG, FLUNG_AT_ONCE, STILL_FLUNG, posterPace, SLOW_POSTER,
  postersToLoad, catchingUp, NEXT_ROWS, CATCH_UP_ROWS, rowsToAsk, retryAfter } = await import('../client/format.js');
// A phone's row: 112px posters 8px apart after a 16px gutter, on a screen 390px wide.
const phoneRow = [16, 136, 256, 376, 496, 616, 736, 856];
check('posters start two screens ahead, and rows are asked for three ahead',
  POSTERS_AHEAD === 2 && ROWS_AHEAD === 3 && CARDS_AHEAD === 2);
check('posters ahead go a few at a time, enough to keep a slow connection busy and no more',
  POSTERS_AT_ONCE >= 4 && POSTERS_AT_ONCE <= 8);
check('a page flung past rows moves faster than a reader scrolls, and slower than a flick lands',
  FLUNG > .6 && FLUNG < 2);
check('while it is flung over a slow connection, fewer posters load at once, and some still do',
  FLUNG_AT_ONCE >= 1 && FLUNG_AT_ONCE < POSTERS_AT_ONCE);
check('the first poster sets the pace, and each after moves it a fifth of the way',
  posterPace(0, 300) === 300 && posterPace(300, 800) === 400 && posterPace(400, 400) === 400);
check('a poster from a cache leaves the pace as it was', posterPace(900, 3) === 900 && posterPace(0, 10) === 0);
let pace = 0;
for (const ms of [120, 90, 150, 110, 1400, 100, 130]) pace = posterPace(pace, ms);
check('one slow poster on a fast connection does not make it slow', pace < SLOW_POSTER);
for (const ms of [900, 1300, 700, 1100, 1600]) pace = posterPace(pace, ms);
check('a run of slow ones does', pace > SLOW_POSTER);
check('it counts as flung through the moment a finger lands for the next flick, and not much longer',
  STILL_FLUNG >= 200 && STILL_FLUNG <= 500);
check('on a phone a row loads the posters it shows and the next two, its first six', postersToLoad(phoneRow, 390) === 6);
check('swiped along, the two past wherever it has got to', postersToLoad(phoneRow.map(x => x - 250), 390) === 8);
check('a wide screen loads what it shows and two more',
  postersToLoad([58, 242, 426, 610, 794, 978, 1162, 1346, 1530, 1714, 1898, 2082], 1440) === 10);
check('never more than a row holds', postersToLoad([16, 136, 256], 390) === 3 && postersToLoad([], 390) === 0);
// A phone's row of 20 that goes round, with 10 copies of its last cards before it and 13 of
// its first after, `x` px past its first card: each place [left, right, card], in order.
const { loopPosters } = await import('../client/format.js');
const roundRow = x => Array.from({ length: 43 }, (_, k) => {
  const left = 16 + (k - 10) * 120 - x;
  return [left, left + 112, (((k - 10) % 20) + 20) % 20];
});
check('a row that goes round wants what it shows, a sliver of its last card before its first included, and the next two',
  same(loopPosters(roundRow(0), 0, 390), [[19, 0, 1, 2, 3], [4, 5]]));
check('swiped back past its first card, what shows of its last ones, and the two beyond them the way it goes',
  same(loopPosters(roundRow(-240), 0, 390, true), [[17, 18, 19, 0, 1], [16, 15]]));
check('across the loop point, its last cards and, through copies, its first, then the two after',
  same(loopPosters(roundRow(18 * 120), 0, 390), [[17, 18, 19, 0, 1], [2, 3]]));
check('the places are read in the order they are laid out, whatever order they come in',
  same(loopPosters(roundRow(0).reverse(), 0, 390), [[19, 0, 1, 2, 3], [4, 5]]));
check('a card showing twice in a short row is wanted once, and one already shown is not wanted next',
  same(loopPosters([[-104, 8, 1], [16, 128, 0], [136, 248, 1], [256, 368, 0], [376, 488, 1]], 0, 390), [[1, 0], []]));
check('a row showing nothing wants nothing', same(loopPosters(roundRow(0), 5000, 5390), [[], []]));
check('a reader with less than a screen of rows left is catching up', catchingUp(843, 844) && catchingUp(-10, 844)
  && !catchingUp(844, 844) && !catchingUp(2500, 844));
check('a reader well above the end gets six rows, and one catching up the eight the server allows',
  rowsToAsk(1700, 844) === NEXT_ROWS && rowsToAsk(844, 844) === NEXT_ROWS && rowsToAsk(843, 844) === CATCH_UP_ROWS
  && rowsToAsk(-200, 844) === CATCH_UP_ROWS && NEXT_ROWS === 6 && CATCH_UP_ROWS === 8);
check('after failures, more rows are asked for again later each time, a minute at most',
  retryAfter(0) === 0 && retryAfter(1) === 2000 && retryAfter(2) === 4000 && retryAfter(3) === 8000
  && retryAfter(12) === 60_000);

// Answers kept by what was asked: within their time, shared while in flight, never a failure.
const { keeper, sessionAnswers } = await import('../client/format.js');
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
function stubWorker({ files, network, build = 'b1', mostSmall = 1000, mostLarge = 40,
  imageCacheFailure = null, stored = new Map(), now = null }) {
  const on = {}, stores = stored, fetched = [], caching = [];
  let tick = 0, skipped = false;
  const key = r => new URL(typeof r === 'string' ? r : r.url, SITE).href;
  const store = name => stores.get(name) || stores.set(name, new Map()).get(name);
  const cache = (m, name) => ({
    match: async r => {
      if (name === 'couchside-images' && imageCacheFailure === 'match') throw new Error('Image cache unavailable');
      return m.get(key(r))?.clone();
    },
    put: async (r, response) => {
      if (name === 'couchside-images' && imageCacheFailure === 'put') throw new Error('Image cache full');
      m.delete(key(r)); m.set(key(r), response);
    },
    keys: async () => [...m.keys()].map(url => ({ url })),
    delete: async r => m.delete(key(r)),
  });
  const caches = {
    open: async name => {
      if (name === 'couchside-images' && imageCacheFailure === 'open') throw new Error('Image storage unavailable');
      return cache(store(name), name);
    },
    keys: async () => [...stores.keys()],
    delete: async name => stores.delete(name),
    match: async (r, { cacheName } = {}) => {
      for (const [name, m] of stores) if ((!cacheName || name === cacheName) && m.has(key(r))) return m.get(key(r)).clone();
    },
  };
  const fetch = async (r, init = {}) => {
    const url = key(r);
    fetched.push(`${(typeof r === 'string' ? init.mode : r.mode) || 'cors'} ${url.replace(SITE, '')}`);
    caching.push(`${url.replace(SITE, '')} ${init.cache || 'default'}`);
    return network(url);
  };
  const self = { addEventListener: (type, fn) => { on[type] = fn; }, location: new URL(SITE), skipWaiting: () => { skipped = true; },
    clients: { claim: async () => {} } };
  const source = readFileSync(new URL('../client/sw.js', import.meta.url), 'utf8').replace('__BUILD__', build)
    .replace('__FILES__', JSON.stringify(files)).replace('MOST_SMALL = 1000', `MOST_SMALL = ${mostSmall}`)
    .replace('MOST_LARGE = 40', `MOST_LARGE = ${mostLarge}`);
  new Function('self', 'caches', 'fetch', 'crypto', 'Request', 'Response', 'Date', 'setTimeout', source)(
    self, caches, fetch, globalThis.crypto, Request, Response, { now: now || (() => ++tick) }, done => Promise.resolve().then(done));
  const waiting = [];
  const extendable = extra => ({ ...extra, waitUntil: p => waiting.push(p) });
  const settle = async () => { while (waiting.length) await waiting.shift().catch(() => {}); };
  return {
    stores, fetched, caching, skipped: () => skipped,
    install: async () => { const e = extendable(); on.install(e); try { await Promise.all(waiting.splice(0)); return true; } catch { return false; } },
    activate: async () => { on.activate(extendable()); await settle(); },
    message: data => on.message({ data }),
    metrics: (data = {}, source = SITE) => {
      let result;
      on.message({ data: { type: 'load-test-metrics', ...data }, source: { url: source },
        ports: [{ postMessage: value => { result = value; } }] });
      return result;
    },
    ask: async (path, { mode = 'no-cors', destination = '' } = {}) => {
      let answer;
      on.fetch(extendable({ request: { method: 'GET', url: new URL(path, SITE).href, mode, destination }, respondWith: p => { answer = p; } }));
      const response = await answer;
      await settle();
      return response;
    },
  };
}
const shellFiles = { '/assets/scripts/main.js': 'main build one', '/assets/styles/style.css': 'style build one', '/pages/offline.html': 'offline page' };
const files = Object.fromEntries(Object.entries(shellFiles).map(([path, body]) => [path, hash16(body)]));
// The site answers a file asked for by any version (?v=) with the file it holds, as server.py does.
const siteOf = (pages, { down = false } = {}) => async url => {
  if (down) throw new TypeError('offline');
  const hit = pages[url.replace(SITE, '')] ?? pages[url] ?? (url.startsWith(SITE) ? pages[new URL(url).pathname] : undefined);
  if (!hit) return new Response('none', { status: 404 });
  return new Response(hit.body ?? hit, { status: 200, headers: hit.headers ?? {} });
};
const page = (body, build = 'b1', etag = '"p1"') => ({ body, headers: { 'X-Build': build, ETag: etag } });
const metricWorker = stubWorker({ files, network: siteOf({ ...shellFiles, '/': page('the page'),
  'https://static.tvmaze.com/uploads/images/medium_portrait/0/1.jpg': 'poster' }) });
await metricWorker.install();
check('worker cache measurement is disabled unless a same-origin page opts in', !metricWorker.metrics().enabled
  && metricWorker.metrics({ enabled: true }, 'https://another.test/') === undefined
  && !metricWorker.metrics().enabled);
metricWorker.metrics({ enabled: true });
await metricWorker.ask('/', { mode: 'navigate' });
await metricWorker.ask('/assets/scripts/main.js', { mode: 'cors' });
await metricWorker.ask('https://static.tvmaze.com/uploads/images/medium_portrait/0/1.jpg', { destination: 'image' });
await metricWorker.ask('https://static.tvmaze.com/uploads/images/medium_portrait/0/1.jpg', { destination: 'image' });
check('worker metrics distinguish actual cache hits from worker-delivered network responses',
  same(metricWorker.metrics().counts, { shell_hits: 1, file_hits: 1, image_misses: 1, image_fetch_attempts: 1, image_hits: 1 }));
check('worker metrics contain no URL or profile data and can be disabled',
  !JSON.stringify(metricWorker.metrics()).includes('tvmaze') && !metricWorker.metrics({ enabled: false }).enabled);
let net = siteOf({ ...shellFiles, '/': page('the page') });
let sw = stubWorker({ files, network: url => net(url) });
check('the service worker keeps the page and every file of its build, checked first', await sw.install()
  && same([...sw.stores.get('couchside-b1').keys()].map(u => u.replace(SITE, '')).sort(), ['/', '/assets/scripts/main.js', '/pages/offline.html', '/assets/styles/style.css'].sort()));
check('it asks for each file at the address naming its hash, which the browser may already hold, and checks the page',
  same([...sw.caching].sort(), ['/ no-cache', ...Object.entries(files).map(([path, hash]) => `${path}?v=${hash} default`)].sort()));
net = siteOf({ ...shellFiles, '/assets/scripts/main.js': 'main build two', '/': page('the page') });
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
check('the build\'s files come from what it kept', (await (await sw.ask('/assets/scripts/main.js', { mode: 'cors' })).text()) === 'main build one'
  && !sw.fetched.length);
net = siteOf({}, { down: true });
check('comparison links use the app shell offline',
  (await (await sw.ask('/compare?compare=169,16149', { mode: 'navigate' })).text()) === 'the page, a new catalogue');
check('without a connection, a page that is not the app\'s is the offline page',
  (await (await sw.ask('/nope', { mode: 'navigate' })).text()) === 'offline page');
const poster = n => `https://static.tvmaze.com/uploads/images/medium_portrait/0/${n}.jpg`;
let fetching = 0, imagePeak = 0;
const parallelImages = stubWorker({ files, network: async url => {
  fetching++; imagePeak = Math.max(imagePeak, fetching);
  await new Promise(done => setTimeout(done, 5));
  fetching--;
  return new Response(url);
} });
const simultaneous = await Promise.all([
  ...Array.from({ length: 12 }, (_, n) => parallelImages.ask(poster(n), { destination: 'image' })),
  parallelImages.ask(poster(0), { destination: 'image' }),
]);
check('image downloads share duplicates and never exceed six concurrent transfers',
  imagePeak <= 6 && parallelImages.fetched.length === 12
  && await simultaneous[0].text() === await simultaneous[12].text());
for (const failure of ['open', 'match', 'put']) {
  let active = 0, peak = 0;
  const withoutImageCache = stubWorker({ files, imageCacheFailure: failure, network: async url => {
    active++; peak = Math.max(peak, active);
    await new Promise(done => setTimeout(done, 5));
    active--; return new Response(url);
  } });
  const answers = await Promise.all([
    ...Array.from({ length: 12 }, (_, n) => withoutImageCache.ask(poster(n), { destination: 'image' })),
    withoutImageCache.ask(poster(0), { mode: 'cors', destination: 'image' }),
  ]);
  check(`images still load and share bounded transfers when image cache ${failure} fails`,
    peak <= 6 && withoutImageCache.fetched.length === 12
    && await answers[0].text() === await answers[12].text());
  check(`failed image cache ${failure} writes cannot prevent the next network request`,
    (await (await withoutImageCache.ask(poster(0), { destination: 'image' })).text()) === poster(0)
    && withoutImageCache.fetched.length === 13);
}
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

// Show backdrops share the retained image store, but expire because a catalogue can
// replace a show's art. They must never turn API errors into cached image responses.
const backdropURL = n => `${SITE}/api/backdrop?id=${n}`;
const bitmapAnswer = body => new Response(body, { headers: { 'Content-Type': 'image/jpeg',
  'Cache-Control': 'public, max-age=86400', ETag: `"${body}"` } });
let artworkNow = 1000, artworkBody = 'backdrop one', artworkStatus = 200, artworkOffline = false;
const artworkNetwork = async () => {
  if (artworkOffline) throw TypeError('offline');
  return artworkStatus === 200 ? bitmapAnswer(artworkBody)
    : new Response('No backdrop', { status: artworkStatus, headers: { 'Content-Type': 'application/json' } });
};
let artworkWorker = stubWorker({ files, now: () => artworkNow, network: artworkNetwork });
got = await artworkWorker.ask(backdropURL(82), img);
check('same-origin backdrop images are kept as bitmaps with a local freshness stamp',
  (await got.text()) === artworkBody && artworkWorker.fetched.length === 1
  && artworkWorker.stores.get('couchside-images').get(backdropURL(82)).headers.get('X-Couchside-Cached-At') === '1000');
check('the backdrop endpoint stays outside the image cache when requested as API data',
  await artworkWorker.ask(backdropURL(82), { mode: 'cors' }) === undefined && artworkWorker.fetched.length === 1);
const artworkStores = artworkWorker.stores;
artworkWorker = stubWorker({ files, build: 'b2', stored: artworkStores, now: () => artworkNow, network: artworkNetwork });
artworkStores.set('couchside-b1', new Map()).set('couchside-b2', new Map());
await artworkWorker.activate();
check('backdrops survive worker upgrades and come from the retained copy after reload',
  (await (await artworkWorker.ask(backdropURL(82), img)).text()) === artworkBody
  && !artworkWorker.fetched.length && !artworkStores.has('couchside-b1'));
artworkNow += 86400_000; artworkBody = 'backdrop two';
check('a day-old backdrop is fetched again and replaced with the new artwork',
  (await (await artworkWorker.ask(backdropURL(82), img)).text()) === artworkBody
  && artworkWorker.fetched.length === 1
  && artworkStores.get('couchside-images').get(backdropURL(82)).headers.get('X-Couchside-Cached-At') === String(artworkNow));
const lastArtworkStamp = String(artworkNow);
artworkNow += 86400_000; artworkOffline = true;
check('expired backdrop artwork remains usable offline without becoming fresh',
  (await (await artworkWorker.ask(backdropURL(82), img)).text()) === artworkBody
  && artworkStores.get('couchside-images').get(backdropURL(82)).headers.get('X-Couchside-Cached-At') === lastArtworkStamp);
artworkOffline = false; artworkStatus = 503;
check('a temporary backdrop outage serves the retained image without caching the error',
  (await (await artworkWorker.ask(backdropURL(82), img)).text()) === artworkBody
  && artworkStores.get('couchside-images').get(backdropURL(82)).headers.get('X-Couchside-Cached-At') === lastArtworkStamp);
artworkStatus = 404;
check('a missing backdrop is returned as missing instead of replacing it with stale artwork',
  (await artworkWorker.ask(backdropURL(82), img)).status === 404);
for (const status of [404, 503]) {
  const noBackdrop = stubWorker({ files, network: async () => new Response('none', { status }) });
  await noBackdrop.ask(backdropURL(1), img); await noBackdrop.ask(backdropURL(1), img);
  check(`a backdrop ${status} is never stored as an image and can recover on the next request`,
    noBackdrop.fetched.length === 2 && !noBackdrop.stores.get('couchside-images').size);
}
const wrongBackdrop = stubWorker({ files, network: async () => new Response('<html>Proxy error</html>',
  { headers: { 'Content-Type': 'text/html' } }) });
await wrongBackdrop.ask(backdropURL(1), img);
check('even a successful HTML error page is never stored as backdrop artwork',
  !wrongBackdrop.stores.get('couchside-images').size);
const boundedBackdrops = stubWorker({ files, mostSmall: 3, mostLarge: 2, network: async url =>
  url.includes('/api/backdrop') ? bitmapAnswer(url) : new Response(url) });
for (const n of [1, 2, 3]) await boundedBackdrops.ask(poster(n), img);
for (const n of [1, 2, 3]) await boundedBackdrops.ask(backdropURL(n), img);
check('backdrop eviction uses the large-image allowance without evicting small posters',
  same([...boundedBackdrops.stores.get('couchside-images').keys()].sort(),
    [poster(1), poster(2), poster(3), backdropURL(2), backdropURL(3)].sort()));
const sharingBackdrops = stubWorker({ files, network: async () => {
  await new Promise(done => setTimeout(done, 5)); return bitmapAnswer('shared backdrop');
} });
const sharedBackdrops = await Promise.all([sharingBackdrops.ask(backdropURL(1), img), sharingBackdrops.ask(backdropURL(1), img)]);
check('prefetched and visible requests for the same backdrop share one transfer',
  sharingBackdrops.fetched.length === 1 && await sharedBackdrops[0].text() === await sharedBackdrops[1].text());
const priorityStarted = [], priorityReleases = [];
const priorityImages = stubWorker({ files, network: async url => {
  priorityStarted.push(url);
  if (priorityStarted.length <= 6) await new Promise(done => priorityReleases.push(done));
  return bitmapAnswer(url);
} });
const firstPosters = Array.from({ length: 6 }, (_, n) => priorityImages.ask(poster(n), img));
await new Promise(done => setTimeout(done, 0));
const nextPosters = [priorityImages.ask(poster(6), img), priorityImages.ask(poster(7), img)];
const priorityBackdrop = priorityImages.ask(backdropURL(82), img);
await new Promise(done => setTimeout(done, 0));
check('queued backdrop priority does not interrupt or exceed six active transfers',
  priorityStarted.length === 6 && same(priorityStarted, Array.from({ length: 6 }, (_, n) => poster(n))));
priorityReleases.shift()();
await new Promise(done => setTimeout(done, 0));
check('a backdrop takes the first free image slot ahead of waiting poster rows',
  priorityStarted[6] === backdropURL(82));
for (const release of priorityReleases) release();
await Promise.all([...firstPosters, ...nextPosters, priorityBackdrop]);
for (const failure of ['open', 'match', 'put']) {
  const noBackdropCache = stubWorker({ files, imageCacheFailure: failure, network: async () => bitmapAnswer('available backdrop') });
  check(`backdrop artwork still loads when cache ${failure} fails`,
    (await (await noBackdropCache.ask(backdropURL(1), img)).text()) === 'available backdrop');
}

// start.js reads the list and memory as a page starts and asks for the home page at once,
// handing the answer to the first to ask for the very same page. Each import of it below is
// a page starting afresh, with storage and fetch standing in for the browser's; it is the
// built one, beside the modules from Next Watch it imports.
const storage = entries => {
  const m = new Map(Object.entries(entries));
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), m };
};
const realFetch = globalThis.fetch;
const storedList = { version: 2, profile: [{ id: 169, weight: 1, name: 'Breaking Bad' }, { id: 82, weight: 0.7 }, { id: 82, weight: 1 },
  { id: -3, weight: 1 }, { id: 526, weight: 0.5 }], saved: [{ id: 2993, poster: 'https://elsewhere.test/x.jpg' }], settings: { known_min: 85 },
onboarded: true };
const starting = async (tag, { session = {}, list = storedList, remembered = null, path = '/' } = {}) => {
  const asked = [];
  Object.assign(globalThis, {
    document: {}, location: new URL(path, 'https://couchside.test'), sessionStorage: storage(session),
    localStorage: storage({ 'couchside-v1': JSON.stringify(list), ...(remembered ? { 'couchside-fresh': remembered } : {}) }),
    fetch: async (path, init) => { asked.push({ path, ...init }); return new Response(JSON.stringify({asked:asked.length})); },
  });
  const start = await import(new URL(`../public/assets/scripts/start.js?${tag}`, import.meta.url).href);
  await new Promise(done => setTimeout(done, 150));
  return { start, asked };
};
const { start, asked: askedEarly } = await starting('early');
check('the list is read as main.js keeps it: malformed and repeated ratings dropped, and posters from TVmaze only', same(
  start.stored.profile.map(p => [p.id, p.weight]), [[169, 1], [82, 0.7]]) && start.stored.saved[0].poster === null
  && start.stored.settings.known_min === 85 && start.stored.onboarded === true);
const firstVisit = JSON.parse(sessionStorage.getItem('couchside-visit'));
const memoryAfter = localStorage.getItem('couchside-fresh');
check('a tab with no visit going on begins one, the day\'s first, and writes the memory at once for main.js and the starters',
  start.opened.visit.n === 1 && /^[0-9a-f]{32}$/.test(start.remembered.salt)
  && JSON.parse(localStorage.getItem('couchside-fresh')).salt === start.remembered.salt
  && JSON.parse(localStorage.getItem('couchside-fresh')).visits.n === 1
  && firstVisit.n === 1 && typeof firstVisit.ask === 'object' && firstVisit.ask.day === firstVisit.day);
const homeAsked = start.homeBody(start.stored, await start.opened.ask);
check('asking for the home page carries the list, My List, the visit\'s day and seeds, and the languages', same(
  Object.keys(homeAsked).slice(0, 4), ['profile', 'settings', 'list', 'day']) && same(homeAsked.list, [2993])
  && /^[0-9a-f]{16}$/.test(homeAsked.seed) && /^[0-9a-f]{16}$/.test(homeAsked.visit) && Array.isArray(homeAsked.lang));
check('the home page is asked for as the page starts, packed as main.js packs it', askedEarly.length === 1
  && askedEarly[0].path === '/api/home' && askedEarly[0].method === 'POST' && askedEarly[0].body === start.packed(homeAsked)
  && typeof JSON.parse(askedEarly[0].body).profile.ids === 'object');
const taken = await start.take(start.packed(homeAsked));
check('and its answer goes to the first to ask for that very page, once', (await taken?.json())?.asked === 1
  && (await start.take(start.packed(homeAsked))) === null);
const other = await starting('other');
check('a request for any other page asks again itself', (await other.start.take(other.start.packed({ ...homeAsked, lang: ['xx'] }))) === null
  && other.asked.length === 1);
const going = { ...firstVisit, at: Date.now() };
const reload = await starting('reload', { session: { 'couchside-visit': JSON.stringify(going) }, remembered: memoryAfter });
check('a reload goes on with the tab\'s visit and asks for its very page', reload.start.opened.visit.n === 1
  && reload.asked.length === 1 && reload.asked[0].body === start.packed(homeAsked)
  && JSON.parse(localStorage.getItem('couchside-fresh')).visits.n === 1);
const keptPage = JSON.stringify({ v: 2, at: Date.now(), day: going.day, visit: going.n, key: pageKey(start.tasteOf(start.stored), [2993]),
  home: { rows: [], ask: going.ask } });
const reloaded = await starting('kept', { session: { 'couchside-visit': JSON.stringify(going), 'couchside-home': keptPage },
  remembered: memoryAfter });
check('a tab that keeps its page for this visit and list asks for nothing', reloaded.asked.length === 0
  && (await reloaded.start.take(reloaded.start.packed(homeAsked))) === null);
const later = await starting('later', { session: { 'couchside-visit': JSON.stringify({ ...going, at: Date.now() - 31 * 60_000 }),
  'couchside-home': keptPage }, remembered: memoryAfter });
check('but a tab come back to after half an hour away begins the day\'s next visit, and asks for its page',
  later.start.opened.visit.n === 2 && later.asked.length === 1 && JSON.parse(later.asked[0].body).visit !== homeAsked.visit
  && JSON.parse(later.asked[0].body).seed === homeAsked.seed);
check('new lists default to well-known shows, while saved choices are preserved', start.fresh().settings.known_min === 85
  && start.sanitize({}).settings.known_min === 85
  && start.sanitize({ version: 1, settings: { known_min: 85 } }).settings.known_min === 85
  && start.sanitize({ version: 2, settings: { known_min: 60 } }).settings.known_min === 60
  && start.sanitize({ version: 2, settings: { known_min: 0 } }).settings.known_min === 0);
for (const path of ['/compare?compare=82,182', '/browse?genre=drama', '/list', '/?show=82', '/search?q=Lost']) {
  const result = await starting('no-home-' + encodeURIComponent(path), {path});
  check(`opening ${path} does not request hidden Home recommendations`, result.asked.length === 0);
}
const firstSetup = await starting('first-setup', {list: {profile:[], saved:[], onboarded:false}});
check('first-time setup leaves Home loading until setup finishes', firstSetup.asked.length === 0);
for (const name of ['document', 'location', 'localStorage', 'sessionStorage']) delete globalThis[name];
globalThis.fetch = realFetch;

// Every script the page loads parses as the browser parses it: its modules as modules and the
// service worker as a classic script. main.js needs a page to run, so nothing above imports
// it, and without this a merge that left it unparseable would pass every check here.
const PUBLIC = new URL('../public/', import.meta.url);
const builtScripts = readdirSync(new URL('assets/scripts/', PUBLIC)).filter(n => n.endsWith('.js')).sort();
for (const [name, kind] of [...builtScripts.map(name => [`assets/scripts/${name}`, 'module']), ['sw.js', 'commonjs']]) {
  const parsed = spawnSync(process.execPath, [`--input-type=${kind}`, '--check'],
    { input: readFileSync(new URL(name, PUBLIC), 'utf8'), encoding: 'utf8' });
  check(`${name} parses as a ${kind === 'module' ? 'module' : 'classic script'}`, parsed.status === 0,
    parsed.stderr.trim().split('\n').slice(0, 4).join(' '));
}

console.log(fails ? `\n${fails} failed` : '\nall format checks passed');
process.exit(fails ? 1 : 0);
