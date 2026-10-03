import { apiFetch } from './network.js?v=4038b4a1107593ef';
import { fullRatings, publicData } from './public-data.js?v=52d95472a87de18c';
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const score = n => n == null ? 'Unrated' : Number(n).toFixed(1);
export const code = e => `S${e.season} E${e.number}`;
export const ratingSource = e => e.rating_source || (e.rating != null ? 'TVmaze' : '');
export const ratingSources = s => s.sources || [...new Set(s.episodes.map(ratingSource).filter(Boolean))].join(' / ');
export const average = es => { const rated = es.filter(e => e.rating != null); return rated.length ? rated.reduce((n,e) => n + e.rating, 0) / rated.length : null; };
export const seasons = s => [...new Set(s.episodes.map(e => e.season))];
// SeriesGraph's public-rating palette and one-decimal boundaries, inspected October 1, 2026.
export const bands = [
  {min:9.7, name:'Absolute cinema', colour:'#1DA1F2', text:'#ffffff', range:'9.7–10'},
  {min:9, name:'Awesome', colour:'#186A3B', text:'#ffffff', range:'9–9.6'},
  {min:8, name:'Great', colour:'#28B463', text:'#2a2a2a', range:'8–8.9'},
  {min:7, name:'Good', colour:'#F4D03F', text:'#2a2a2a', range:'7–7.9'},
  {min:6, name:'Average', colour:'#F39C12', text:'#2a2a2a', range:'6–6.9'},
  {min:4.1, name:'Bad', colour:'#E74C3C', text:'#ffffff', range:'4.1–5.9'},
  {min:0, name:'Garbage', colour:'#633974', text:'#ffffff', range:'Up to 4'},
];
export const band = n => n == null || n === 0
  ? {name:'Unrated', colour:'#bdbdbd', text:'#2a2a2a', range:'No rating'}
  : bands.find(b => Number(Number(n).toFixed(1)) >= b.min);
export function icon(name) {
  const paths={
    grid:'<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    wrapped:'<rect x="3" y="4" width="5" height="5" rx="1"/><rect x="11" y="4" width="5" height="5" rx="1"/><rect x="19" y="4" width="2" height="5" rx="1"/><rect x="3" y="13" width="5" height="5" rx="1"/><rect x="11" y="13" width="5" height="5" rx="1"/>',
    timeline:'<path d="M3 3v18h18M5 15l5-6 5 3 6-8"/><circle cx="10" cy="9" r="1"/><circle cx="15" cy="12" r="1"/>',
    list:'<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    down:'<path d="M6 9l6 6 6-6"/>',check:'<path d="M20 6L9 17l-5-5"/>',
    search:'<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5l-4.3-4.3"/>',
    close:'<path d="M18 6L6 18M6 6l12 12"/>',
    poster:'<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 16l5-5 4 4 2-2 3 3"/>',
    filter:'<path d="M4 7h16M7 12h10M10 17h4"/>',
    sort:'<path d="M8 4v16m-4-4 4 4 4-4M15 5h6M15 10h4M15 15h2"/>',
  };
  return `<svg class="ratings-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.grid}</svg>`;
}
export function html(node, markup) {
  node.innerHTML=markup.replace(/\sstyle=/g,' data-style=');
  node.querySelectorAll('[data-style]').forEach(el => {el.style.cssText=el.dataset.style;el.removeAttribute('data-style');});
}
export function legend() {
  return `<div class="ratings-key" aria-label="Episode rating key">${[...bands,band(null)].map(b=>`<span title="${b.range}"><i style="background:${b.colour}"></i>${b.name}<small>${b.range||'No rating'}</small></span>`).join('')}</div>`;
}
const loaded = new Map();
const MAX_CACHED = 160;
const CACHED_FOR = 5 * 60 * 1000;
export const cachedRatings = id => {
  const held = loaded.get(id);
  if (held && Date.now() - held.at < CACHED_FOR &&
      (!Number.isFinite(held.value.expiresAt) || Date.now() < held.value.expiresAt * 1000)) return held.value;
  if (held) { loaded.delete(id); cache.delete(id); }
};
const cache = new Map();
const MATRIX_KEY = 'couchside.episode-matrices-v1';
const matrices = new Map();
const MAX_MATRICES = 400;
let saveTimer;
function saveMatrices() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const save = () => {
      // A bounded byte budget matters more than the number of shows for long soaps.
      const kept = [...matrices];
      let text = JSON.stringify(kept);
      while (text.length > 1800000 && kept.length) { kept.shift(); text = JSON.stringify(kept); }
      try { localStorage.setItem(MATRIX_KEY, text); } catch { /* Server cache still works. */ }
    };
    if (globalThis.requestIdleCallback) requestIdleCallback(save, {timeout: 2000}); else save();
  }, 500);
}
try {
  const saved = JSON.parse(localStorage.getItem(MATRIX_KEY));
  if (Array.isArray(saved)) for (const [id, held] of saved) {
    const es=held?.value?.episodes;
    if (Number.isInteger(id) && id>0 && held?.value?.id===id && Date.now() - held?.at < 7 * 86400000
        && Array.isArray(es) && es.every(e=>e&&Number.isInteger(e.season)&&e.season>0&&Number.isInteger(e.number)&&e.number>0
          &&(e.rating===null||(Number.isFinite(e.rating)&&e.rating>0&&e.rating<=10)))) matrices.set(id, held);
  }
  while(matrices.size>MAX_MATRICES)matrices.delete(matrices.keys().next().value);
} catch { /* First visit, unavailable storage, or a malformed cache. */ }
export const cachedMatrix = id => {
  const full=cachedRatings(id);if(full)return full;
  const held=matrices.get(id);
  if(held&&Date.now()-held.at<7*86400000)return held.value;
  if(held)matrices.delete(id);
};
export const freshMatrix = id => {
  const held=matrices.get(id),full=cachedRatings(id);
  return full&&!full.refreshing?full:held&&Date.now()-held.at<CACHED_FOR&&!held.value.refreshing?held.value:null;
};
const matrixFlights = new Map(), matrixQueue = new Map();
let matrixTimer;
async function drainMatrices() {
  matrixTimer = null;
  const jobs = [...matrixQueue.values()]; matrixQueue.clear();
  for (let offset = 0; offset < jobs.length; offset += 40) {
    const batch = jobs.slice(offset, offset + 40), ids = batch.map(job => job.id).sort((a, b) => a - b);
    try {
      const response = await apiFetch(`/api/episode-matrices?ids=${ids.join(',')}`), body = await response.json();
      if (!response.ok || !Array.isArray(body.shows) || !Array.isArray(body.pending)) throw Error(body.error || 'Ratings are unavailable.');
      acceptMatrices(body);
      for (const job of batch) job.resolve({ show: body.shows.find(show => show.id === job.id), pending: body.pending.includes(job.id) });
    } catch (error) { batch.forEach(job => job.reject(error)); }
    finally { batch.forEach(job => matrixFlights.delete(job.id)); }
  }
}
export async function matrixRatings(ids, { refresh = false } = {}) {
  const unique = [...new Set(ids)].slice(0, 40);
  if (unique.some(id => !Number.isInteger(id) || id <= 0)) throw Error('Choose valid shows.');
  const result = await Promise.all(unique.map(id => {
    const held = !refresh && freshMatrix(id);
    if (held) return { show: held, pending: false };
    if (!matrixFlights.has(id)) {
      matrixFlights.set(id, new Promise((resolve, reject) => {
        matrixQueue.set(id, { id, resolve, reject });
        if (!matrixTimer) matrixTimer = setTimeout(drainMatrices, 30);
      }));
    }
    return matrixFlights.get(id);
  }));
  const body = { shows: result.map(value => value.show).filter(Boolean), pending: unique.filter((id, i) => result[i].pending) };
  if (!refresh) for (const id of [...body.pending, ...body.shows.filter(show => show.refreshing).map(show => show.id)]) followEnrichment(id);
  return body;
}
// Feed answers carry saved matrices so card construction does not need another trip.
export function acceptMatrices(body) {
  if (!body || !Array.isArray(body.shows)) return;
  for (const value of body.shows) {
    matrices.delete(value.id);matrices.set(value.id, {at:Date.now(),value});
    if (!value.refreshing) publicData.stopFollowing(value.id);
    const full = cachedRatings(value.id);
    if (full) {
      let changed=full.sources!==value.sources;
      const scores = new Map(value.episodes.map(e=>[`${e.season}:${e.number}`,e]));
      for (const e of full.episodes) {
        const picked=scores.get(`${e.season}:${e.number}`);
        if(picked){
          changed ||= ['rating','rating_source','rating_votes'].some(key=>e[key]!==picked[key]);
          Object.assign(e,{rating:picked.rating,rating_source:picked.rating_source,rating_votes:picked.rating_votes});
        }
      }
      full.sources=value.sources; full.refreshing=value.refreshing === true;
      if(changed&&typeof window!=='undefined')window.dispatchEvent(new CustomEvent('couchside-ratings',{detail:value.id}));
    }
  }
  while (matrices.size > MAX_MATRICES) matrices.delete(matrices.keys().next().value);
  saveMatrices();
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('couchside-matrices', { detail: body }));
}
function ratingsVisible(id) {
  const doc = globalThis.document;
  if (!doc?.querySelectorAll) return true;
  const cards = doc.querySelectorAll(`.ratings-card-matrix[data-show="${id}"], .compare-card[data-show="${id}"]`);
  for (const node of cards) {
    if (!node.isConnected || node.closest('[inert]') || !node.getClientRects().length) continue;
    if (node.classList.contains('compare-card')) return true;
    const bounds = node.getBoundingClientRect();
    if (bounds.top < innerHeight + 600 && bounds.bottom > -600 && bounds.left < innerWidth + 220 && bounds.right > -220) return true;
  }
  return Boolean(doc.querySelector('#title[open]') &&
    Number(new URLSearchParams(globalThis.location?.search || '').get('show')) === id);
}
function followEnrichment(id) {
  publicData.follow(id, async () => {
    const full = cachedRatings(id);
    if (full && !full.refreshing) return false;
    const body = await matrixRatings([id], { refresh: true });
    return body.pending.includes(id) || body.shows.some(show => show.id === id && show.refreshing);
  }, failed => { if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('couchside-matrices-failed', { detail: failed })); }, ratingsVisible);
}
export function ratings(id) {
  const held = cachedRatings(id);
  if (held) return Promise.resolve(held);
  if(!cache.has(id)) {
    const request=async()=>{
      const body = await fullRatings(id);
      if(!Array.isArray(body.episodes))throw Error('Ratings are unavailable.');
      loaded.set(id,{at:Date.now(),value:body});
      while(loaded.size>MAX_CACHED){const oldest=loaded.keys().next().value;loaded.delete(oldest);cache.delete(oldest);}
      if(body.refreshing)followEnrichment(id);else publicData.stopFollowing(id);
      if(typeof window!=='undefined')window.dispatchEvent(new CustomEvent('couchside-matrices',{detail:{shows:[body],pending:[]}}));
      return body;
    };
    const pending=request().catch(error=>{cache.delete(id);throw error;});
    cache.set(id,pending);
  }
  return cache.get(id);
}
export function compactMatrix(s) {
  const ss=seasons(s),max=Math.max(1,...s.episodes.map(e=>e.number)),rows=new Map(ss.map((n,i)=>[n,i]));
  if(!ss.length)return '<span class="ratings-mini-empty">No episodes yet</span>';
  return `<svg class="ratings-mini" viewBox="0 0 ${max} ${ss.length}" role="img" aria-label="${s.episodes.length} episode ratings, seasons in rows">${s.episodes.map(e=>`<rect x="${e.number-1}" y="${rows.get(e.season)}" width=".82" height=".82" rx=".12" fill="${band(e.rating).colour}"><title>${code(e)} · ${esc(e.name)} · ${score(e.rating)} · ${band(e.rating).name}${ratingSource(e)?' · '+esc(ratingSource(e)):''}</title></rect>`).join('')}</svg>`;
}
export function matrixSkeleton() {
  return `<span class="ratings-mini-loading" aria-hidden="true">${'<span class="ratings-mini-cell skel"></span>'.repeat(24)}</span>`;
}
