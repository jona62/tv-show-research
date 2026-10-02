import '/ratings-data.js';
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const score = n => n == null ? 'Unrated' : Number(n).toFixed(1);
export const code = e => `S${e.season} E${e.number}`;
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
const loaded = new Map(window.SHOWS.map(s => [s.id,s]));
export const cachedRatings = id => loaded.get(id);
const cache = new Map(window.SHOWS.map(s => [s.id,Promise.resolve(s)]));
export function ratings(id) {
  if(!cache.has(id)) {
    const request=async attempt=>{
      const response=await fetch(`/api/ratings-preview?id=${id}`),body=await response.json();
      if(response.status===503&&attempt<2){await new Promise(resolve=>setTimeout(resolve,10000));return request(attempt+1);}
      if(!response.ok)throw Error(body.error||'Ratings are unavailable.');loaded.set(id,body);return body;
    };
    const pending=request(0).catch(error=>{cache.delete(id);throw error;});
    cache.set(id,pending);
  }
  return cache.get(id);
}
export function compactMatrix(s) {
  const ss=seasons(s),max=Math.max(1,...s.episodes.map(e=>e.number));
  if(!ss.length)return '<span class="ratings-mini-empty">No episodes yet</span>';
  return `<svg class="ratings-mini" viewBox="0 0 ${max} ${ss.length}" role="img" aria-label="${s.episodes.length} episode ratings, seasons in rows">${s.episodes.map(e=>`<rect x="${e.number-1}" y="${ss.indexOf(e.season)}" width=".82" height=".82" rx=".12" fill="${band(e.rating).colour}"><title>${code(e)} · ${esc(e.name)} · ${score(e.rating)} · ${band(e.rating).name}</title></rect>`).join('')}</svg>`;
}
