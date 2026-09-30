// Small pure helpers, shared by the page and test_format.mjs.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const PAGES = { '/': 'home', '/new': 'new', '/list': 'list', '/search': 'search', '/welcome': 'welcome', '/browse': 'browse' };

// "2008" while it runs or when it ended the year it began, "2008–2013" otherwise.
export const years = (start, ended) => !start ? '' : ended && ended > start ? `${start}–${ended}` : String(start);

export const runtime = minutes => !minutes ? ''
  : minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h${minutes % 60 ? ` ${minutes % 60}m` : ''}`;

export const seasons = n => !n ? '' : `${n} Season${n === 1 ? '' : 's'}`;

export const joinNames = names => names.length < 2 ? (names[0] || '')
  : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;

// What two shows concretely share, as a phrase: part of Breaking Bad, by Vince Gilligan.
const TIES = { franchise: l => `part of ${l}`, maker: l => `by ${l}`, cast: l => `with ${l}`, network: l => `also on ${l}`,
  fans: () => 'its fans look this up too' };
export const tieText = t => (TIES[t.family] || (l => l))(t.label);

const decade = l => l.startsWith('before') ? l : `the ${l}`;
const theme = l => l.split(' / ')[0];
// A leaning inside a sentence: "fits your taste for crime, HBO and the 2000s".
const WITHIN = {
  language: l => `shows in ${l}`, country: l => `${l} shows`, decade, length: l => `${l} episodes`,
  theme: l => theme(l).toLowerCase(), format: l => l.toLowerCase(), genre: l => l.toLowerCase(),
};
export const leaning = f => (WITHIN[f.family] || (l => l))(f.label);
// A leaning as a heading: "On HBO", "In Korean", "From the 2000s".
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const HEADING = {
  language: l => `In ${l}`, network: l => `On ${l}`, decade: l => `From ${decade(l)}`,
  length: l => `${cap(l)} episodes`, country: l => `${l} shows`, theme: l => theme(l),
};
export const leaningHeading = f => (HEADING[f.family] || cap)(f.label);

// Where the page is: which view, the search terms, the title open over it, one of its
// episodes open over that, and a person open over either.
export function parseRoute(pathname, search) {
  const params = new URLSearchParams(search);
  const id = key => {
    const n = Number(params.get(key));
    return Number.isInteger(n) && n > 0 ? n : null;
  };
  const show = id('show');
  return {
    page: PAGES[pathname] || 'home',
    q: params.get('q') || '',
    genre: params.get('genre') || '',
    show,
    episode: show && id('episode'),
    person: id('person'),
  };
}

// A genre's name on its chip: "Crime TV shows" as "Crime", "Adventures" as it is.
export const shortGenre = label => label.replace(/\s+(TV\s+)?shows$/i, '') || label;

// Every genre and format to browse, A to Z by the name its chip wears.
export const genreChoices = genres => genres.map(g => ({ ...g, short: shortGenre(g.label) }))
  .sort((a, b) => a.short.localeCompare(b.short, 'en', { sensitivity: 'base' }));

// Type-ahead in a list: the next label after `from` that starts with `letter`, going
// round to the start, or -1 when none does.
export function nextByLetter(labels, from, letter) {
  const start = letter.toLowerCase();
  for (let step = 1; step <= labels.length; step++) {
    const n = (from + step) % labels.length;
    if (labels[n].trim().toLowerCase().startsWith(start)) return n;
  }
  return -1;
}

// "https://www.netflix.com/title/1" as "netflix.com".
export function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

// One service when one host sits inside the other, as tv.apple.com does in apple.com.
export const sameService = (a, b) => !!a && !!b && (a === b || a.endsWith(`.${b}`) || b.endsWith(`.${a}`));

// Where to watch: each channel, linked to the show's own page when that page lives on
// the channel's site, then Apple TV when iTunes sells it. One link per place.
export function watchLinks(site, channels, apple) {
  const own = hostOf(site);
  const out = [];
  for (const c of channels || []) {
    const home = hostOf(c.site);
    const href = own && (!home || sameService(own, home)) ? site : c.site;
    if (href) out.push({ name: c.name, kind: c.kind, href, host: hostOf(href) });
  }
  if (apple) out.push({ name: 'Apple TV', kind: 'buy', href: apple, host: 'tv.apple.com' });
  return out.filter((w, n) => out.findIndex(x => x.href === w.href) === n);
}

// How a service offers a show, from TMDB's kinds: the word its pill carries, if any,
// and the sentence its link reads out.
function offer(kinds, show, service) {
  const has = kind => kinds.includes(kind);
  if (has('flatrate')) return ['', `Stream ${show} on ${service}`];
  if (has('free')) return ['Free', `Watch ${show} free on ${service}`];
  if (has('ads')) return ['With ads', `Watch ${show} free with ads on ${service}`];
  if (has('rent') && has('buy')) return ['Rent or buy', `Rent or buy ${show} on ${service}`];
  if (has('rent')) return ['Rent', `Rent ${show} on ${service}`];
  return ['Buy', `Buy ${show} on ${service}`];
}

// Where to watch. TMDB's services when it lists any, in the server's order (streaming
// first), each with its own logo and linking to TMDB's page for the show, since the
// data is JustWatch's and must be credited and linked there. Otherwise TVmaze's
// channels and Apple TV, each with the icon this server fetches for its host.
export function whereToWatch(show, tmdb, site, channels, apple) {
  const listed = tmdb?.link && Array.isArray(tmdb.providers) ? tmdb.providers : [];
  if (listed.length) {
    return {
      credit: true,
      links: listed.map(p => {
        const [note, said] = offer(p.kinds || [], show, p.name);
        return { name: p.name, href: tmdb.link, logo: p.logo || null, note, title: said,
          label: `${said}, listed on TMDB, opens in a new tab` };
      }),
    };
  }
  return {
    credit: false,
    links: watchLinks(site, channels, apple).map(w => {
      const said = w.kind === 'stream' ? `Stream ${show} on ${w.name}`
        : w.kind === 'buy' ? `Buy ${show} on ${w.name}` : `${show} on ${w.name}`;
      return { name: w.name, href: w.href, logo: `/api/icon?host=${encodeURIComponent(w.host)}`,
        note: w.kind === 'buy' ? 'Buy' : '', title: said, label: `${said}, opens in a new tab` };
    }),
  };
}

/* ------------------------------------------------------------ a title page's long parts */
// A season starts with its first three episodes and the trailers with the first two, or a
// wide screen's row of three; a button opens the rest. An episode's guest stars start with
// twelve, four rows of faces on a phone and two on a wide screen. On a person's page, their
// roles start with twelve posters, whole lines of three on a phone and of six on a wide
// screen, and their appearances as themselves and the shows they made with six. Hiding just
// one is not worth a button, so a part only one longer than its snippet shows whole.
export const SNIPPETS = { episodes: 3, clips: 2, clipsWide: 3, guests: 12, roles: 12, appearances: 6, crew: 6 };
export const snippet = (count, most) => (count > most + 1 ? most : count);

// What that button says, opening the part or closing it again.
export function revealLabel(part, count, open) {
  if (part === 'episodes') return open ? 'Show fewer episodes' : `Show all ${count} episodes`;
  if (part === 'guests') return open ? 'Show fewer guest stars' : `Show all ${count} guest stars`;
  return open ? 'Show fewer' : `Show all (${count})`;
}

// What the search page says over its results. Checking the spelling is suggested only
// when neither the catalogue, typos and all, nor TVmaze found anything, and no shows like
// the search were found either; when only those were, they follow the note.
export function searchNote(query, found, missing, related = 0) {
  if (found) return `Shows matching “${query}”`;
  if (missing) return `Nothing in the catalogue matches “${query}” yet.`;
  if (related) return `No titles match “${query}”.`;
  return `Nothing matches “${query}”. Check the spelling.`;
}

// Whether an answer without a row of shows like the search should leave the row on
// screen, found for the search shownFor: only while the search grows from it, letter by
// letter, so the row does not blink out between one letter of a title and the next
// (breaki, breakin, breaking). A search cut back, or another, clears it.
export function keepsRow(shownFor, query) {
  const was = searchText(shownFor).toLowerCase(), now = searchText(query).toLowerCase();
  return !!was && now.length > was.length && now.startsWith(was);
}

// Recent searches: the last RECENT_SEARCHES committed, by pressing Enter or opening one
// of the results, newest first.
export const RECENT_SEARCHES = 10;

// A search as kept: trimmed, each run of spaces made one, and no longer than a box takes.
export const searchText = q => (typeof q === 'string' ? q.trim().replace(/\s+/g, ' ').slice(0, 100) : '');

// One letter, such as V, is too little to be worth offering again.
const worthKeeping = q => [...q].length >= 2;

// Recent searches from storage: two letters or more, newest first, each once whatever its
// case, and RECENT_SEARCHES at most.
export function recentStore(raw) {
  const kept = [], seen = new Set();
  for (const item of Array.isArray(raw) ? raw : []) {
    const q = searchText(item);
    if (!worthKeeping(q) || seen.has(q.toLowerCase())) continue;
    seen.add(q.toLowerCase());
    kept.push(q);
    if (kept.length === RECENT_SEARCHES) break;
  }
  return kept;
}

// The list with a committed search at its head, in the case it was last typed. An empty
// or one-letter search leaves the list as it was.
export const noteSearch = (list, q) => (worthKeeping(searchText(q)) ? recentStore([q, ...list]) : list);

// The list without one search, whatever its case.
export const withoutSearch = (list, q) => list.filter(s => s.toLowerCase() !== searchText(q).toLowerCase());

// The recent searches to offer under a box: every one while it is empty, and once
// something is typed, those that begin with it or have a word that does, other than the
// very search typed.
export function recentMatches(list, typed) {
  const t = searchText(typed).toLowerCase();
  if (!t) return list;
  return list.filter(s => {
    const l = s.toLowerCase();
    return l !== t && (l.startsWith(t) || l.includes(` ${t}`));
  });
}

// A YouTube search for the trailer, for shows no trailer service knows.
export const trailerSearch = (name, year) =>
  `https://www.youtube.com/results?search_query=${encodeURIComponent(`${name}${year ? ` ${year}` : ''} official trailer`)}`;

// The same place with something opened over it by its id, or closed, and whatever depends
// on what changed closed with it.
function withId(pathname, search, key, id, closes = []) {
  const params = new URLSearchParams(search);
  if (id) params.set(key, String(id)); else params.delete(key);
  for (const other of closes) params.delete(other);
  const query = params.toString();
  return pathname + (query ? `?${query}` : '');
}
// A title opened over the page, or closed; either way no episode stays open, since an
// episode belongs to the title it was opened from.
export const withShow = (pathname, search, id) => withId(pathname, search, 'show', id, ['episode']);
// The same title with one of its episodes opened over it, or closed again.
export const withEpisode = (pathname, search, id) => withId(pathname, search, 'episode', id);
// A person opened over the page, beside the title or episode they were opened from, or closed.
export const withPerson = (pathname, search, id) => withId(pathname, search, 'person', id);

/* ------------------------------------------------------------------- an episode */
// "S2 E5", or "S2 Special" for a special, which TVmaze leaves unnumbered.
export const episodeCode = (season, number) =>
  [season ? `S${season}` : '', number ? `E${number}` : 'Special'].filter(Boolean).join(' ');

// The same as it is read out: "Season 2, episode 5".
export function episodeSaid(season, number) {
  const which = number ? `episode ${number}` : 'special';
  return season ? `Season ${season}, ${which}` : which[0].toUpperCase() + which.slice(1);
}

// The episodes either side of one in its season's list, for reading through a season.
// Only those with an id can be opened, so only those are stepped to.
export function neighbours(episodes, id) {
  const open = (Array.isArray(episodes) ? episodes : []).filter(e => Number.isInteger(e?.id));
  const at = open.findIndex(e => e.id === id);
  return at < 0 ? { prev: null, next: null } : { prev: open[at - 1] || null, next: open[at + 1] || null };
}

// Who made an episode, as credits read: directors, then writers, then story and teleplay
// where the writing was split, then any other job, each with everyone who did it.
const CREDITS = { Director: 'Directed by', Writer: 'Written by', Story: 'Story by', Teleplay: 'Teleplay by' };
export function credits(crew) {
  const jobs = new Map();
  for (const c of Array.isArray(crew) ? crew : []) {
    if (!c?.role) continue;
    if (!jobs.has(c.role)) jobs.set(c.role, []);
    jobs.get(c.role).push(c);
  }
  const order = Object.keys(CREDITS);
  const rank = role => (order.includes(role) ? order.indexOf(role) : order.length);
  return [...jobs].sort((a, b) => rank(a[0]) - rank(b[0]))
    .map(([role, people]) => ({ role, label: Object.hasOwn(CREDITS, role) ? CREDITS[role] : `${role}:`, people }));
}

// When an episode aired, "Apr 5, 2009"; or, still to come, when it airs in this browser's
// own time, "Airs Tue, Oct 7, 9:00 PM", from TVmaze's timestamp, since its air time is the
// network's and says nothing of where the reader is. `now` and `timeZone` are for tests.
export function airing(airdate, airstamp, now = Date.now(), timeZone = undefined) {
  const at = airstamp ? Date.parse(airstamp) : NaN;
  if (at > now) {
    const said = options => new Intl.DateTimeFormat('en-US', { timeZone, ...options }).format(at);
    const year = new Intl.DateTimeFormat('en-US', { timeZone, year: 'numeric' });
    const soon = year.format(at) === year.format(now);
    return `Airs ${said({ weekday: 'short', month: 'short', day: 'numeric', ...(soon ? {} : { year: 'numeric' }),
      hour: 'numeric', minute: '2-digit' })}`;
  }
  const day = longDate(airdate);
  if (!day) return '';
  return !Number.isFinite(at) && airdate > new Date(now).toISOString().slice(0, 10) ? `Airs ${day}` : day;
}

// A stable colour for a show without a poster, so the fallback tile is not grey.
export const hue = id => (id * 47) % 360;

// "2026-10-07" as "Oct 7".
export function premiere(date) {
  const [, month, day] = (date || '').split('-').map(Number);
  return month >= 1 && month <= 12 && day ? `${MONTHS[month - 1]} ${day}` : '';
}

// "2008-01-20" as "Jan 20, 2008".
export function longDate(date) {
  const short = premiere(date);
  return short ? `${short}, ${date.slice(0, 4)}` : '';
}

// ["Sunday"] as "New episodes Sundays".
export function airs(days) {
  if (!days?.length) return '';
  if (days.length === 7) return 'New episodes daily';
  if (days.length === 5 && !days.includes('Saturday') && !days.includes('Sunday')) return 'New episodes weekdays';
  return `New episodes ${joinNames(days.map(d => `${d}s`))}`;
}

/* ------------------------------------------------------------- a person's page */
// A day as "2026-09-29", in the reader's own time.
export function isoDay(on = new Date()) {
  const pad = n => String(n).padStart(2, '0');
  return `${on.getFullYear()}-${pad(on.getMonth() + 1)}-${pad(on.getDate())}`;
}

// Whole years from one day to another, as an age is counted, or null without both.
export function yearsBetween(from, to) {
  const [a, b] = [from, to].map(day => (/^\d{4}-\d{2}-\d{2}$/.test(day || '') ? day.split('-').map(Number) : null));
  if (!a || !b) return null;
  const years = b[0] - a[0] - (b[1] < a[1] || (b[1] === a[1] && b[2] < a[2]) ? 1 : 0);
  return years >= 0 ? years : null;
}

// When and where someone was born: "Mar 7, 1956 in Hollywood, California, United States",
// or whichever of the two is known.
export function bornOn(birthday, place) {
  const on = longDate(birthday);
  return on && place ? `${on} in ${place}` : on || place || '';
}

// When someone died, and how old they were: "Oct 28, 2023 (aged 54)".
export function diedOn(birthday, deathday) {
  const on = longDate(deathday);
  const age = yearsBetween(birthday, deathday);
  return on && age !== null ? `${on} (aged ${age})` : on;
}

// Someone as themselves, in the words TVmaze's gender gives: "Himself", or else "Self".
export const selfName = gender => ({ Male: 'Himself', Female: 'Herself' }[gender] || 'Self');
// The heading over the shows they were in as themselves.
export const selfHeading = gender => ({ Male: 'As himself', Female: 'As herself' }[gender] || 'As themselves');

// What a credit's poster says under it: whom they played, or what they did, and then how
// many episodes and when, "Walter White" or "Voice of Bert" over "5 episodes · 1994–1997";
// and the same as its card reads it out, "as Walter White, 5 episodes, 1994–1997".
export function creditLines(c, gender) {
  const as = c.jobs?.length ? c.jobs.join(', ')
    : c.self ? selfName(gender) : c.as ? (c.voice ? `Voice of ${c.as}` : c.as) : c.voice ? 'Voice' : '';
  const role = c.jobs?.length ? as
    : c.self ? selfHeading(gender).toLowerCase()
      : c.as ? (c.voice ? `voice of ${c.as}` : `as ${c.as}`) : c.voice ? 'voice' : '';
  const count = c.episodes ? `${c.episodes} episode${c.episodes === 1 ? '' : 's'}` : '';
  const span = years(c.years?.[0], c.years?.[1]);
  return { as, when: [count, span].filter(Boolean).join(' · '), said: [role, count, span].filter(Boolean).join(', ') };
}

// What someone is known for: their regular roles, which come best known first. Someone with
// none who made shows is known for those, which their page names as created instead, and
// someone with neither for the parts they guested in.
export function knownFor(roles, created = [], most = 3) {
  const regular = roles.filter(r => r.regular);
  const shown = regular.length ? regular : created.length ? [] : roles;
  return joinNames(shown.slice(0, most).map(r => r.name));
}

/* ------------------------------------------------------------ the featured shows */
// The featured shows go round. Their slides sit along a strip, slot k holding slide k mod
// n, and the strip slides under the screen: on from the last slide is the slot after it,
// which holds the first, so the first comes in from the right, and back from the first is
// the slot before, which holds the last. Nothing runs back across the rest and nothing
// jumps, since each slide is drawn in whichever of its slots is nearest where the strip
// is, which is wherever it is next to come. Places on the strip are counted in slots.

// A featured show turns to the next every this many ms, while nothing holds it.
export const TURN_EVERY = 7000;

// Slide k of n, for any whole k.
export const slideIn = (k, n) => ((k % n) + n) % n;

// The slot of slide i nearest the strip's place `at`; halfway round, the one ahead.
export const slotOf = (i, at, n) => i + n * Math.round((at - i) / n);

// The slots a move from `from` to `to` shows on its way: each within a slot of it.
export const slotsShown = (from, to) => Math.ceil(Math.max(from, to)) - Math.floor(Math.min(from, to)) + 1;

// How far toward slot `to` a move from `from` can go with n slides: no further than shows
// each slide once, so none is ever wanted in two slots at once. Only two slides limit it.
export function reach(from, to, n) {
  while (to !== Math.round(from) && slotsShown(from, to) > n) to -= Math.sign(to - from);
  return to;
}

// "2 of 6: Luther", what each slide and its dot are called.
export const slideLabel = (i, n, name) => `${i + 1} of ${n}: ${name}`;

export const TURN = .2;       // the share of the way a swipe comes before it turns the slide
const CARRY = 180;            // ms of a finger's speed counted as distance still to come
const FLICKED = .3;           // px a ms: a flick turns the slide however little it came
const FLICKED_BACK = .2;      // px a ms back the other way keeps it

// The slot a swipe let go at `at` comes to rest in, the finger moving `v` px a ms (to the
// left, toward the slots ahead, is negative) across a strip `width` px wide. One that set
// off from rest in slot `from` goes on to the next slot its way once it has come TURN of
// the way, counting where its speed carries it, or was flicked that way; flicked back, it
// stays. One that caught the strip moving (from null) settles where its speed carries it.
// Either way it rests in a slot now on screen.
export function landing(at, v, width, from = null) {
  const lo = Math.floor(at), hi = Math.ceil(at);
  let to;
  if (from === null || at === from) to = Math.round(at - v * CARRY / width);
  else {
    const way = Math.sign(at - from), along = -v * way;
    const came = Math.abs(at - from) + along * CARRY / width;
    to = along > -FLICKED_BACK && (came >= TURN || along >= FLICKED) ? from + way : from;
  }
  return Math.min(hi, Math.max(lo, to));
}

// How long the strip takes to come to rest: a swipe's last `distance` px at the speed it
// was let go, 180 to 420ms; a turn by a button, a key or a dot TURN_MS, a little longer for
// each slot past the first; and one of its own, unhurried, TURN_OWN_MS.
export const TURN_MS = 480;
export const TURN_OWN_MS = 760;
export const glideTime = (distance, v) => Math.round(Math.min(Math.max(distance / Math.max(Math.abs(v), .8), 180), 420));
export const turnTime = slots => Math.min(TURN_MS + 120 * (Math.abs(slots) - 1), 840);

/* ---------------------------------------------------------------- the home page */
// What a home page depends on, the same however the settings happen to be ordered: the
// ratings, the settings and My List.
export function pageKey({ profile, settings }, list) {
  return JSON.stringify([profile.map(p => [p.id, p.weight]),
    Object.keys(settings).sort().map(k => [k, settings[k]]), list]);
}

export const RESUME_MINUTES = 30;

// Whether a kept page can be shown again as it was: made today for the same list and My
// List, and in use within the last RESUME_MINUTES.
export function resumable(kept, { key, day, now }) {
  const idle = now - kept?.at;
  return Boolean(kept && kept.v === 1 && kept.key === key && kept.day === day && idle >= 0
    && idle <= RESUME_MINUTES * 60_000 && Array.isArray(kept.home?.rows));
}

// A kept page runs to this many characters at most, some two hundred rows.
export const KEEP_CHARS = 1_000_000;

// A kept page as stored: whole, or, past `most` characters, without its last rows and
// asking for them again, since the same list on the same day gets the same rows back.
export function keptText(kept, most = KEEP_CHARS) {
  const text = JSON.stringify(kept);
  if (text.length <= most) return text;
  const rows = kept.home.rows;
  let over = text.length - most, n = rows.length;
  while (n > 1 && over > 0) over -= JSON.stringify(rows[--n]).length + 1;
  return JSON.stringify({ ...kept, home: { ...kept.home, rows: rows.slice(0, n), more: true } });
}

// The rows a page shows, as the server asks to be told them when it is asked for more:
// each row's key, the ids of its first six cards and, for a row past today's, the tier
// it came in. My List's are the list's own, and rows the browser makes itself, such as
// Recently viewed, are not sent.
export function shownRows(rows, listIds = []) {
  return rows.filter(r => r.kind !== 'recent').map(r => ({
    key: r.key, ids: (r.kind === 'list' ? listIds : r.items.map(c => c.id)).slice(0, 6),
    ...(r.tier ? { tier: r.tier } : {}),
  }));
}

// The rows once a card has been acted on: it leaves every row the page chose for you,
// while the Top 10 keeps its ten and My List follows the list itself.
export const withoutCard = (rows, id) =>
  rows.map(r => (r.kind === 'row' ? { ...r, items: r.items.filter(c => c.id !== id) } : r));

// How far ahead of the reader the home page loads, in screens: a row's posters start
// two screens before it comes into view, and more rows are asked for while three
// screens of them are still to come.
export const POSTERS_AHEAD = 2;
export const ROWS_AHEAD = 3;
// Past the posters a row shows, the next two load with them, and as it is swiped along,
// the next two past wherever it has got to.
export const CARDS_AHEAD = 2;
// Posters load this many at a time, nearest the screen first, so on a slow connection
// those ahead of the reader never crowd out the ones on screen, which may start as many
// again at once.
export const POSTERS_AT_ONCE = 6;
// A page moving faster than this, in px a ms, is being flung past rows rather than read.
// Over a slow connection its posters, those flying past included, then load only
// FLUNG_AT_ONCE at a time, leaving it to the rows the reader is heading for. It is still
// flung for STILL_FLUNG ms after, since a finger landing for the next flick stops it for
// a moment.
export const FLUNG = 1.2;
export const FLUNG_AT_ONCE = 2;
export const STILL_FLUNG = 300;

// How long posters take, as a running average of each one's ms, and past what a
// connection counts as slow. A poster in within CACHED ms came from a cache, such as a
// show a row above already has, and says nothing about the connection.
export const CACHED = 50;
export const posterPace = (pace, ms) => (ms < CACHED ? pace : pace ? pace + (ms - pace) / 5 : ms);
export const SLOW_POSTER = 500;

// How many of a row's posters to load: those starting before its right `edge`, from
// their left edges in order, and CARDS_AHEAD more.
export function postersToLoad(lefts, edge, ahead = CARDS_AHEAD) {
  let shown = 0;
  while (shown < lefts.length && lefts[shown] < edge) shown++;
  return Math.min(lefts.length, shown + ahead);
}

// A reader with less than a screen of rows left below them is catching up with the page,
// and waits for the next rows.
export const catchingUp = (left, screen) => left < screen;

// The rows to ask for next: six, or the eight the server allows at most for a reader
// catching up.
export const NEXT_ROWS = 6;
export const CATCH_UP_ROWS = 8;
export const rowsToAsk = (left, screen) => (catchingUp(left, screen) ? CATCH_UP_ROWS : NEXT_ROWS);

// How long to wait before asking again for more rows after `failures` failed in a row:
// at once after none, then 2 seconds, doubling to a minute at most.
export const retryAfter = failures => (failures > 0 ? Math.min(2000 * 2 ** (failures - 1), 60_000) : 0);

export const VIEWED_DAYS = 14;
export const VIEWED_KEEP = 40;

// Titles opened lately, from storage: junk is dropped and posters come only from TVmaze.
export function viewedStore(raw) {
  return (Array.isArray(raw) ? raw : []).filter(v => v && Number.isInteger(v.id) && v.id > 0 && Number.isInteger(v.d))
    .slice(-VIEWED_KEEP).map(v => ({
      id: v.id, d: v.d, name: typeof v.name === 'string' ? v.name : '', year: Number.isInteger(v.year) ? v.year : null,
      poster: typeof v.poster === 'string' && v.poster.startsWith('https://static.tvmaze.com/') ? v.poster : null,
    }));
}

// The list with a title opened on day number `now` added last, once.
export const noteViewed = (viewed, card, now) => viewedStore([...viewed.filter(v => v.id !== card.id),
  { id: card.id, d: now, name: card.name, year: card.year, poster: card.poster }]);

// Recently viewed: titles whose page was opened in the last VIEWED_DAYS days and that
// have been neither rated nor added to My List since, most recent first.
export function recentlyViewed(viewed, now, { rated = new Set(), saved = new Set(), most = 20 } = {}) {
  const out = [];
  for (const v of [...viewed].reverse()) {
    if (now - v.d > VIEWED_DAYS || v.d > now || rated.has(v.id) || saved.has(v.id)) continue;
    out.push(v);
    if (out.length === most) break;
  }
  return out;
}

// Answers the page has already been given, kept by what was asked: asking again within
// its time limit gets the same answer without a request, and two asking at once share
// one. A failure is not kept, so the next ask tries again, and past `most` the oldest go.
export function keeper({ most = 150, now = Date.now } = {}) {
  const kept = new Map();
  return (key, ms, ask) => {
    const held = kept.get(key);
    if (held && (held.pending || now() - held.at < ms)) return held.answer;
    const entry = { at: now(), pending: true };
    entry.answer = Promise.resolve().then(ask).then(value => {
      Object.assign(entry, { at: now(), pending: false });
      return value;
    }, error => {
      if (kept.get(key) === entry) kept.delete(key);
      throw error;
    });
    kept.delete(key);
    kept.set(key, entry);
    for (const old of kept.keys()) {
      if (kept.size <= most) break;
      kept.delete(old);
    }
    return entry.answer;
  };
}

// Answers kept across a reload of the tab, from sessionStorage, read defensively: each is
// { at, value } under the api request it answered, and only those younger than `ms`
// stay, the `most` newest.
export function sessionAnswers(raw, now, ms, most = 40) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw)
    .filter(([key, a]) => key.startsWith('/api/') && a && Number.isFinite(a.at) && a.at <= now && now - a.at < ms
      && a.value && typeof a.value === 'object')
    .sort((a, b) => b[1].at - a[1].at).slice(0, most)
    .map(([key, a]) => [key, { at: a.at, value: a.value }]));
}
