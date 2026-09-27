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
