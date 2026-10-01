import {ratings,cachedRatings,compactMatrix,icon,html} from './ratings.js';
const KEY='couchside.show-cards';
let matrix=false;
try{matrix=localStorage.getItem(KEY)==='matrix';}catch{}
const account=document.querySelector('#account .menu-sheet');
const preferences=document.createElement('fieldset');preferences.className='ratings-card-preference';
html(preferences,`<legend>Show cards</legend><div class="ratings-card-choices"><button type="button" data-cards="standard" aria-pressed="${!matrix}">${icon('poster')}<span>Standard</span></button><button type="button" data-cards="matrix" aria-pressed="${matrix}">${icon('grid')}<span>Episode matrix</span></button></div><p>Saved on this device</p>`);
account.querySelector('#reach').closest('label').before(preferences);
const pending=[];let running=0;
const tilesFor=id=>document.querySelectorAll(`.ratings-card-matrix[data-show="${id}"]`);
function paintMatrix(tile,s){
  visible.unobserve(tile);tile.dataset.matrixState='ready';
  html(tile,`${compactMatrix(s)}<span class="ratings-mini-caption">${s.episodes.length?`${s.episodes.length} episodes · TVmaze`:'No episodes yet'}</span>`);
}
function pump(){
  while(matrix&&running<2&&pending.length){
    const foreground=pending.findIndex(node=>node.closest('dialog[open]'));
    const [node]=pending.splice(foreground<0?0:foreground,1);
    if(!node.isConnected)continue;
    if(node.dataset.matrixState==='ready'||node.dataset.matrixState==='error')continue;
    if(!node.getClientRects().length){node.dataset.matrixState='idle';visible.observe(node);continue;}
    node.dataset.matrixState='loading';
    const id=Number(node.dataset.show);
    running++;
    ratings(id).then(s=>{
      for(const tile of tilesFor(id))paintMatrix(tile,s);
    }).catch(()=>{
      for(const tile of tilesFor(id)){visible.unobserve(tile);tile.dataset.matrixState='error';html(tile,'<span class="ratings-mini-empty">Ratings unavailable</span>');}
    }).finally(()=>{running--;pump();});
  }
}
const visible=new IntersectionObserver(entries=>{
  for(const entry of entries){
    const node=entry.target;
    if(entry.isIntersecting&&matrix&&node.dataset.matrixState==='idle'){
      visible.unobserve(node);node.dataset.matrixState='queued';pending.push(node);
    }
  }
  pump();
},{rootMargin:'80px'});
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
  html(node,`<span class="ratings-mini-loading" aria-hidden="true"></span><span class="ratings-mini-caption">Episode ratings</span>`);
  node.onclick=()=>hit.click();card.append(node);
  const cached=cachedRatings(Number(show.id));
  if(cached)paintMatrix(node,cached);else if(matrix)visible.observe(node);
}
function apply(){
  document.body.classList.toggle('ratings-matrix-cards',matrix);
  preferences.querySelectorAll('[data-cards]').forEach(b=>b.setAttribute('aria-pressed',String((b.dataset.cards==='matrix')===matrix)));
  if(matrix){
    document.querySelectorAll('.ratings-card-matrix[data-matrix-state="idle"]').forEach(node=>{if(!node.closest('[inert]'))visible.observe(node);});
    pump();
  }
}
preferences.querySelectorAll('[data-cards]').forEach(button=>button.onclick=()=>{
  matrix=button.dataset.cards==='matrix';try{localStorage.setItem(KEY,matrix?'matrix':'standard');}catch{}
  apply();
});
apply();

window.addEventListener('storage',event=>{if(event.key===KEY){matrix=event.newValue==='matrix';apply();}});
