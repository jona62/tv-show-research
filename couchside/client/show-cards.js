import {matrixRatings,cachedMatrix,freshMatrix,ratingSources,compactMatrix,matrixSkeleton,icon,html,esc,acceptMatrices} from './ratings.js';
const KEY='couchside.show-cards';
let matrix=true;
try{matrix=localStorage.getItem(KEY)!=='standard';}catch{}
const customization=document.querySelector('#customization .customization-cards');
const preferences=document.createElement('fieldset');preferences.className='ratings-card-preference';
html(preferences,`<legend>Show cards</legend><div class="ratings-card-choices"><button type="button" data-cards="standard" aria-pressed="${!matrix}">${icon('poster')}<span>Standard</span></button><button type="button" data-cards="matrix" aria-pressed="${matrix}">${icon('grid')}<span>Episode ratings</span></button></div><p>Keep cards focused on the show, or add its episode ratings below the poster.</p>`);
customization.append(preferences);
const pending=[];let running=false,pumpTimer;
const tilesFor=id=>document.querySelectorAll(`.ratings-card-matrix[data-show="${id}"]`);
const drawn=new WeakMap();
const nearTile=node=>{
  if(!node.isConnected||!node.getClientRects().length||node.closest('[inert]'))return false;
  const r=node.getBoundingClientRect();
  return r.top<innerHeight+600&&r.bottom>-600&&r.left<innerWidth+220&&r.right>-220;
};
function paintMatrix(tile,s){
  const signature=s.sources+'|'+s.episodes.map(e=>[e.season,e.number,e.name,e.rating,e.rating_source,e.rating_votes].join('/')).join('|');
  if(drawn.get(tile)===signature)return;
  drawn.set(tile,signature);
  tile.dataset.matrixState='ready';
  tile.setAttribute('aria-busy','false');
  const source=ratingSources(s);
  html(tile,`${compactMatrix(s)}<span class="ratings-mini-caption">${s.episodes.length?`${s.episodes.length} episodes${source?' · '+esc(source):''}`:'No episodes yet'}</span>`);
}
function pump(){
  if(!matrix||document.hidden||running||!pending.length)return;
  const batch=[],ids=new Set();
  while(pending.length&&ids.size<24){
    const foreground=pending.findIndex(node=>{const r=node.getBoundingClientRect();return node.closest('dialog[open]')||(r.top<innerHeight&&r.bottom>0&&r.left<innerWidth&&r.right>0);});
    const [node]=pending.splice(foreground<0?0:foreground,1);
    if(!node.isConnected)continue;
    if(node.dataset.matrixState==='error')continue;
    if(!nearTile(node)){delete node.dataset.matrixAsked;visible.observe(node);continue;}
    if(node.dataset.matrixState!=='ready')node.dataset.matrixState='loading';
    const id=Number(node.dataset.show);
    const cached=freshMatrix(id);
    if(cached){paintMatrix(node,cached);continue;}
    batch.push(node);ids.add(id);
  }
  if(!ids.size)return;
  running=true;
  matrixRatings([...ids]).then(body=>{
    for(const s of body.shows)for(const tile of tilesFor(s.id))paintMatrix(tile,s);
    for(const id of [...body.pending,...body.shows.filter(show=>show.refreshing).map(show=>show.id)]) {
      for(const tile of tilesFor(id))if(tile.isConnected&&!tile.closest('[inert]'))visible.observe(tile);
    }
  }).catch(()=>{
    for(const node of batch)if(node.dataset.matrixState!=='ready'){
      node.dataset.matrixState='error';html(node,'<span class="ratings-mini-empty">Ratings unavailable</span>');
      node.setAttribute('aria-busy','false');
    }
  }).finally(()=>{running=false;pump();});
}

// Cards and open comparisons share one per-show enrichment scheduler. A ready
// cached matrix stays visible while new scores arrive without per-tile polling.
window.addEventListener('couchside-matrices', event => {
  for (const show of event.detail?.shows || []) for (const tile of tilesFor(show.id)) paintMatrix(tile, show);
});
window.addEventListener('couchside-matrices-failed', event => {
  for (const tile of tilesFor(event.detail)) if (tile.dataset.matrixState !== 'ready') {
    tile.dataset.matrixState = 'error'; tile.setAttribute('aria-busy', 'false');
    html(tile, '<span class="ratings-mini-empty">Ratings unavailable</span>');
  }
});
const visible=new IntersectionObserver(entries=>{
  for(const entry of entries){
    const node=entry.target;
    if(!entry.isIntersecting){
      if(!freshMatrix(Number(node.dataset.show)))delete node.dataset.matrixAsked;
      continue;
    }
    if(entry.isIntersecting&&matrix&&!node.dataset.matrixAsked){
      visible.unobserve(node);node.dataset.matrixAsked='true';
      node.dataset.matrixStarted=String(Date.now());
      if(node.dataset.matrixState!=='ready')node.dataset.matrixState='queued';pending.push(node);
    }
  }
  clearTimeout(pumpTimer);pumpTimer=setTimeout(pump,30);
},{rootMargin:'600px 220px'});
export const matrixPreference=()=>matrix;
export function receiveMatrices(body){
  acceptMatrices(body);
  for(const s of body?.shows||[])for(const tile of tilesFor(s.id))paintMatrix(tile,s);
}
// Called by Couchside's shared card constructor, before rows make inert copies.
export function enhanceShowCard(card,show,related=false){
  const hit=card.querySelector('.card-hit'),meta=card.querySelector('.card-meta');
  if(!hit||!Number(show.id))return;
  if(related&&(show.similar||show.why)){
    const reason=document.createElement('span');reason.className='ratings-card-reason';
    reason.textContent=[show.similar?`${show.similar}% similar`:'',show.why].filter(Boolean).join(' · ');
    meta.querySelector('.card-words').append(reason);
  }
  if(show.summary){
    const summary=document.createElement('p');summary.className='ratings-card-summary';
    summary.textContent=show.summary;meta.append(summary);
  }
  const node=document.createElement('button');node.type='button';node.className='ratings-card-matrix';node.dataset.show=show.id;
  node.dataset.matrixState='idle';
  node.setAttribute('aria-label',`Open episode ratings for ${show.name}`);
  node.setAttribute('aria-busy','true');
  html(node,`${matrixSkeleton()}<span class="ratings-mini-caption">Episode ratings</span>`);
  node.onclick=()=>hit.click();card.append(node);
  const cached=cachedMatrix(Number(show.id));
  if(cached)paintMatrix(node,cached);
  if(matrix)visible.observe(node);
}
function apply(){
  document.body.classList.toggle('ratings-matrix-cards',matrix);
  preferences.querySelectorAll('[data-cards]').forEach(b=>b.setAttribute('aria-pressed',String((b.dataset.cards==='matrix')===matrix)));
  if(matrix){
    document.querySelectorAll('.ratings-card-matrix:not([data-matrix-asked])').forEach(node=>{if(!node.closest('[inert]'))visible.observe(node);});
    pump();
  }else{
    visible.disconnect();
    for(const node of pending.splice(0))delete node.dataset.matrixAsked;
  }
}
preferences.querySelectorAll('[data-cards]').forEach(button=>button.onclick=()=>{
  matrix=button.dataset.cards==='matrix';try{localStorage.setItem(KEY,matrix?'matrix':'standard');}catch{}
  apply();
});
apply();

document.addEventListener('visibilitychange',()=>{
  if(document.hidden)return;
  for(const node of pending)node.dataset.matrixStarted=String(Date.now());
  pump();
});

window.addEventListener('storage',event=>{if(event.key===KEY){matrix=event.newValue!=='standard';apply();}});
window.addEventListener('couchside-network',event=>{
  if(event.detail.state!=='recover'||!matrix)return;
  if(event.detail.paths?.length&&!event.detail.paths.some(path=>path.startsWith('/api/episode-matrices')))return;
  document.querySelectorAll('.ratings-card-matrix[data-matrix-state="error"]').forEach(node=>{
    node.dataset.matrixState='idle';delete node.dataset.matrixAsked;delete node.dataset.matrixRetries;
    node.setAttribute('aria-busy','true');
    html(node,`${matrixSkeleton()}<span class="ratings-mini-caption">Episode ratings</span>`);
    if(!node.closest('[inert]'))visible.observe(node);
  });
});
