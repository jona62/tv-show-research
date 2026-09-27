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
