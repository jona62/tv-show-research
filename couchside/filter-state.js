// Discovery choices belong to this tab's pages, independently of saved taste.
const KEY = 'couchside.page-filters';
let pages = {};
try { const raw = JSON.parse(sessionStorage.getItem(KEY)); if (raw && typeof raw === 'object' && !Array.isArray(raw)) pages = raw; } catch {}
export const filtersFor = page => pages[page] || {};
export function setFilters(page, value) {
  pages[page] = Object.fromEntries(Object.entries(value).filter(([,v]) => v !== '' && v !== 'all' && v !== 'relevance' && v !== 0 && v != null && (!Array.isArray(v) || v.length)));
  try { sessionStorage.setItem(KEY, JSON.stringify(pages)); } catch {}
}
export const filterKey = page => Object.keys(filtersFor(page)).length ? '|' + JSON.stringify(filtersFor(page)) : '';
export const wantsMatrices = () => { try { return localStorage.getItem('couchside.show-cards') === 'matrix'; } catch { return false; } };
export const formats = {scripted:['Scripted'],animation:['Animation'],documentary:['Documentary'],unscripted:['Reality','Variety','Talk Show','Game Show','Panel Show','Award Show','Sports','News']};
export function matches(show, f) {
  if (f.genres?.length && !f.genres.some(g => show.genres?.includes(g))) return false;
  if (f.rating && !(show.rating >= f.rating)) return false;
  if (f.year && !(show.year >= f.year)) return false;
  if (f.status && show.status !== f.status) return false;
  if (f.language && show.language !== f.language) return false;
  if (f.format && !formats[f.format]?.includes(show.type)) return false;
  if (f.length && !(show.runtime > 0 && ({short:show.runtime < 30,standard:show.runtime >= 30 && show.runtime <= 60,long:show.runtime > 60})[f.length])) return false;
  for (const k of ['seasons','episodes']) if (f[k] && !(show[k] > 0 && show[k] <= f[k])) return false;
  if (f.hours && !(show.total_minutes > 0 && show.total_minutes <= f.hours * 60)) return false;
  return true;
}
export function selectShows(items, page, query = '') {
  const f = filtersFor(page), needle = query.trim().toLocaleLowerCase();
  const picked = items.filter(s => matches(s, f) && (!needle || s.name?.toLocaleLowerCase().includes(needle)));
  const sort = f.sort;
  if (sort === 'name') picked.sort((a,b) => a.name.localeCompare(b.name));
  else if (sort === 'shortest') picked.sort((a,b) => (a.total_minutes || Infinity) - (b.total_minutes || Infinity));
  else if (['rating','newest','popular'].includes(sort)) { const key={rating:'rating',newest:'year',popular:'popularity'}[sort]; picked.sort((a,b) => (b[key] || 0) - (a[key] || 0)); }
  return picked;
}
