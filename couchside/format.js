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

// Where the page is: which view, the search terms, and the title open over it.
export function parseRoute(pathname, search) {
  const params = new URLSearchParams(search);
  const show = Number(params.get('show'));
  return {
    page: PAGES[pathname] || 'home',
    q: params.get('q') || '',
    genre: params.get('genre') || '',
    show: Number.isInteger(show) && show > 0 ? show : null,
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

// What the search page says over its results. Checking the spelling is suggested only
// when neither the catalogue, typos and all, nor TVmaze found anything.
export function searchNote(query, found, missing) {
  if (found) return `Shows matching “${query}”`;
  if (missing) return `Nothing in the catalogue matches “${query}” yet.`;
  return `Nothing matches “${query}”. Check the spelling.`;
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

// The same place with a title opened over it, or closed.
export function withShow(pathname, search, id) {
  const params = new URLSearchParams(search);
  if (id) params.set('show', String(id)); else params.delete('show');
  const query = params.toString();
  return pathname + (query ? `?${query}` : '');
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
