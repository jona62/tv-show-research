import {chart,nearestRatingPoint} from './episode-timeline.js?v=d5bd5f2216ee1dbd';
export {chart,smoothPath} from './episode-timeline.js?v=d5bd5f2216ee1dbd';
import {esc,score,average,seasons,band,icon,html,legend,ratings,ratingSource,ratingSources} from './ratings.js?v=70517fd9f1cddac1';
import {detailMatrix,ratingTableHTML,seasonName,episodeCode} from './rating-views.js?v=b273a6ffe2a54e91';
const plain = value => new DOMParser().parseFromString(value||'', 'text/html').body.textContent||'';
const layouts=[['list','Episode list'],['grid','Grid'],['wrapped','Wrapped'],['timeline','Timeline']];
const ep = e => ({...e,still:e.image,summary:plain(e.summary)});
const options = (items,value) => items.map(([v,t])=>`<option value="${v}" ${String(v)===String(value)?'selected':''}>${esc(t)}</option>`).join('');

export function ratingDetailView(search,episodes) {
  const params=new URLSearchParams(search),view=params.get('rating-view'),selected=params.get('rating-season');
  return {view:layouts.some(([id])=>id===view)?view:'list',
    season:[...new Set(episodes.map(e=>e.season))].find(n=>String(n)===selected)??'all',
    inverted:params.get('rating-inverted')==='1'};
}

export function ratingDetailSearch(search,state) {
  const params=new URLSearchParams(search);
  for(const [key,value,fallback] of [['rating-view',state.view,'list'],
    ['rating-season',String(state.season),'all'],['rating-inverted',state.inverted?'1':'0','0']]) {
    if(value===fallback)params.delete(key);else params.set(key,value);
  }
  return params.toString();
}

export function ratingDetailSnapshot(t,data,state) {
  const show={...t.card,...t.data?.show,...t.live};
  const episodes=data.episodes.filter(e=>state.season==='all'||e.season===Number(state.season));
  // These are the portrait artwork fields. Backdrops and rendered hero images
  // must never replace the source poster in an exported rating view.
  return structuredClone({kind:'detail',id:t.id,title:show.name||data.name||t.name?.textContent||'This show',
    poster:show.art||show.poster||null,year:show.year??null,status:show.status??null,
    season:state.season,view:state.view,inverted:state.inverted,averages:true,
    episodes,sources:ratingSources({episodes})||data.sources||'',cacheFetchedAt:data.cacheFetchedAt??null});
}

function picker(onChange,value='list') {
  const node=document.createElement('div');node.className='ratings-picker';
  const label=layouts.find(([id])=>id===value)[1];
  html(node,`<button type="button" class="ratings-view-button" aria-label="Episode layout: ${label}" aria-haspopup="listbox" aria-expanded="false" aria-controls="ratings-view-options">${icon(value)}<span>${label}</span>${icon('down')}</button><div id="ratings-view-options" class="ratings-view-options" role="listbox" aria-label="Episode layout" hidden>${layouts.map(([id,label])=>`<button type="button" role="option" aria-selected="${id===value}" data-layout="${id}">${icon(id)}<span>${label}</span>${icon('check')}</button>`).join('')}</div>`);
  const trigger=node.querySelector('.ratings-view-button'),menu=node.querySelector('[role=listbox]');
  const close=()=>{menu.hidden=true;trigger.setAttribute('aria-expanded','false');};
  const open=()=>{menu.hidden=false;trigger.setAttribute('aria-expanded','true');menu.querySelector('[aria-selected=true]').focus();};
  node.setValue=value=>{
    const label=layouts.find(([id])=>id===value)[1];
    node.querySelectorAll('[data-layout]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.layout===value)));
    html(trigger,`${icon(value)}<span>${label}</span>${icon('down')}`);
    trigger.setAttribute('aria-label',`Episode layout: ${label}`);close();
  };
  trigger.onclick=()=>menu.hidden?open():close();
  trigger.onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();open();}};
  node.querySelectorAll('[data-layout]').forEach(button=>button.onclick=()=>{
    node.setValue(button.dataset.layout);trigger.focus();onChange(button.dataset.layout);
  });
  node.onkeydown=e=>{
    if(e.key==='Escape'&&!menu.hidden){e.stopPropagation();close();trigger.focus();}
    if(!menu.hidden&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
      e.preventDefault();const buttons=[...menu.querySelectorAll('button')],i=buttons.indexOf(document.activeElement);
      buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();
    }
  };
  node.addEventListener('keydown',e=>{if(e.key==='Tab')close();});
  node.closestTitleClick=e=>{if(!node.contains(e.target))close();};
  return node;
}
function cell(e) {
  if(!e)return '<span></span>';
  const b=band(e.rating);
  return `<button type="button" class="ratings-cell" style="background:${b.colour};color:${b.text}" data-episode="${e.id}" aria-label="${episodeCode(e)}: ${esc(e.name)}, ${score(e.rating)}${e.rating==null?'':' out of 10'}, ${b.name}">${e.rating==null?'—':score(e.rating)}</button>`;
}
export const ratingDetailGrid=(episodes,inverted=false)=>ratingTableHTML(detailMatrix({episodes,inverted,averages:true}));
function wrapped(es) {
  return [...new Set(es.map(e=>e.season))].map(n=>{const eps=es.filter(e=>e.season===n);return `<section class="ratings-wrapped-season"><div class="ratings-wrapped-heading"><b>${seasonName(n)}</b><span>${score(average(eps))} average</span></div><div class="ratings-wrapped-cells">${eps.map(e=>`<div><span class="ratings-axis">E${e.number}</span>${cell(e)}</div>`).join('')}</div></section>`;}).join('');
}

function bindTimelineNavigation(node) {
  node.querySelectorAll('.ratings-chart-wrap').forEach(viewport=>viewport.addEventListener('keydown',event=>{
    if(event.target!==viewport||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    if(event.key==='Home')viewport.scrollLeft=0;
    else if(event.key==='End')viewport.scrollLeft=viewport.scrollWidth-viewport.clientWidth;
    else viewport.scrollLeft+=(event.key==='ArrowRight'?1:-1)*Math.min(160,viewport.clientWidth/2);
  }));
  const points=[...node.querySelectorAll('.ratings-point-hit')];
  points.forEach((target,index)=>target.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const next=event.key==='Home'?0:event.key==='End'?points.length-1:
      Math.max(0,Math.min(points.length-1,index+(event.key==='ArrowRight'?1:-1)));
    points[next]?.focus();
  }));
}

function revealTimelinePoint(target) {
  const viewport=target.closest('.ratings-chart-wrap');
  if(!viewport)return;
  const point=target.getBoundingClientRect(),bounds=viewport.getBoundingClientRect();
  if(point.left<bounds.left)viewport.scrollLeft-=bounds.left-point.left+8;
  else if(point.right>bounds.right)viewport.scrollLeft+=point.right-bounds.right+8;
}

function bindTimelinePointer(node,tip) {
  const svg=node.querySelector('.ratings-timeline');
  if(!svg)return;
  const points=[...svg.querySelectorAll('[data-episode]')].map(target=>{
    const dot=target.querySelector('.ratings-point');
    return {target,x:Number(dot.getAttribute('cx')),y:Number(dot.getAttribute('cy'))};
  });
  if(!points.length)return;
  let hovered,frame,down,cancelled=false;
  const nearest=event=>{
    const matrix=svg.getScreenCTM();if(!matrix)return null;
    // Safari truncates pointer coordinates to whole CSS pixels. Resolve that
    // pixel's centre so adjacent ratings remain reachable at fractional offsets.
    const centre=value=>Number.isInteger(value)?value+.5:value;
    const p=new DOMPoint(centre(event.clientX),centre(event.clientY)).matrixTransform(matrix.inverse());
    return nearestRatingPoint(points,p.x,p.y)?.target;
  };
  const clear=()=>{cancelAnimationFrame(frame);hovered?.classList.remove('is-hovered');hovered=null;tip.leave();};
  svg.onpointermove=event=>{
    if(event.pointerType==='touch')return;
    cancelAnimationFrame(frame);
    frame=requestAnimationFrame(()=>{
      if(!svg.isConnected)return;
      const target=nearest(event);if(target===hovered)return;
      hovered?.classList.remove('is-hovered');hovered=target;
      if(target){target.classList.add('is-hovered');target.onpointerenter();}
      else tip.leave();
    });
  };
  svg.onpointerleave=clear;
  svg.onpointercancel=()=>{cancelled=true;down=null;clear();};
  svg.onpointerdown=event=>{cancelled=false;down={x:event.clientX,y:event.clientY,target:nearest(event)};};
  svg.onclick=event=>{
    if(cancelled){cancelled=false;return;}
    if(down&&Math.hypot(event.clientX-down.x,event.clientY-down.y)>8){down=null;return;}
    const target=down?.target||nearest(event);down=null;cancelAnimationFrame(frame);
    if(target){clear();target.onclick();}
  };
}

function tooltip(host) {
  const tip=document.createElement('div');tip.className='ratings-tooltip';tip.id='ratings-hover';tip.setAttribute('role','tooltip');tip.hidden=true;host.append(tip);
  let active=null,hideTimer;
  const hide=()=>{clearTimeout(hideTimer);active=null;tip.hidden=true;host.querySelectorAll('[aria-describedby=ratings-hover]').forEach(e=>e.removeAttribute('aria-describedby'));};
  const leave=()=>{clearTimeout(hideTimer);hideTimer=setTimeout(hide,150);};
  const position=()=>{
    if(!active)return;
    tip.style.maxHeight='';
    const r=active.target.getBoundingClientRect(),width=tip.offsetWidth;
    let height=tip.offsetHeight,left=Math.max(12,Math.min(window.innerWidth-width-12,r.left+r.width/2-width/2));
    let top=r.top-height-12;
    if(top<12){
      if(r.bottom+height+24<=window.innerHeight)top=r.bottom+12;
      else if(r.right+width+24<=window.innerWidth){left=r.right+12;top=window.innerHeight-height-12;}
      else if(r.left-width-24>=0){left=r.left-width-12;top=window.innerHeight-height-12;}
      else {
        const above=Math.max(0,r.top-24),below=Math.max(0,window.innerHeight-r.bottom-24);
        tip.style.maxHeight=`${Math.max(1,above,below)}px`;height=tip.offsetHeight;
        top=above>below?r.top-height-12:r.bottom+12;
      }
    }
    tip.style.left=`${left}px`;tip.style.top=`${Math.max(12,top)}px`;
  };
  const show=(target,e,showName='')=>{
    hide();
    active={target};
    const b=band(e.rating),summary=plain(e.summary).trim();
    html(tip,`${e.image?`<img src="${esc(e.image)}" alt="" loading="lazy">`:''}<div class="ratings-tooltip-body"><span class="ratings-tooltip-code">${showName?esc(showName)+' · ':''}${e.number?episodeCode(e):seasonName(e.season)}</span><b>${esc(e.name||'Season average')}</b><div class="ratings-tooltip-score"><strong style="background:${b.colour};color:${b.text}">${score(e.rating)}</strong><span>${b.name}<small>${e.rating==null?'Awaiting audience ratings':`out of 10 on ${esc(ratingSource(e))}${e.rating_votes?' · '+Number(e.rating_votes).toLocaleString()+' votes':''}`}</small></span></div>${e.number?`<p class="ratings-tooltip-summary">${esc(summary||'No episode description available.')}</p>`:''}</div>`);
    tip.hidden=false;target.setAttribute('aria-describedby',tip.id);
    position();
  };
  tip.onpointerenter=()=>clearTimeout(hideTimer);tip.onpointerleave=leave;
  host.addEventListener('keydown',event=>{if(event.key==='Escape'&&active){event.preventDefault();event.stopPropagation();hide();}});
  const scrolled=event=>{
    if(tip.contains(event.target))return;
    const viewport=active?.target.closest('.ratings-chart-wrap'),point=active?.target.getBoundingClientRect(),bounds=viewport?.getBoundingClientRect();
    if(active?.target===document.activeElement&&(!bounds||point.right>bounds.left&&point.left<bounds.right))position();
    else hide();
  };
  const dialog=host.closest('dialog');
  host.addEventListener('scroll',scrolled,true);dialog?.addEventListener('scroll',scrolled);window.addEventListener('resize',position);
  return {show,hide,leave,dispose:()=>{hide();host.removeEventListener('scroll',scrolled,true);dialog?.removeEventListener('scroll',scrolled);window.removeEventListener('resize',position);}};
}
export async function mountEpisodeRatings(t,{openEpisode,episodeEl,revealButton,paintReveal,unfold,busy,snippet,revealLabel},saved=null) {
  if(t.episodes.dataset.ratingsMounted)return;
  t.episodes.dataset.ratingsMounted='true';
  t.ratingSnapshotReady?.(false);
  let data;
  try{data=saved||await ratings(t.id);}catch{delete t.episodes.dataset.ratingsMounted;return;}
  if(!t.episodes.isConnected||!data.episodes?.length){delete t.episodes.dataset.ratingsMounted;return;}
  const s={...data,id:t.id,name:t.live?.name||t.name.textContent||data.name||t.card?.name||'This show'};
  let state=ratingDetailView(window.location.search,s.episodes),expanded=t.open.episodes,disposed=false;
  const head=t.episodes.querySelector('.t-section-head'),controls=document.createElement('div');controls.className='ratings-controls';
  const persist=()=>{
    const url=new URL(window.location.href);
    if(url.searchParams.get('show')!==String(t.id))return;
    url.search=ratingDetailSearch(url.search,state);
    window.history.replaceState(window.history.state,'',url.pathname+url.search+url.hash);
  };
  const view=picker(value=>{state.view=value;persist();syncControls();paint();},state.view);
  const filter=document.createElement('select');filter.setAttribute('aria-label','Episode season');
  filter.innerHTML=options([['all','All seasons'],...seasons(s).map(n=>[n,seasonName(n)])],state.season);
  const invert=document.createElement('button');invert.type='button';invert.className='chip ratings-invert';
  invert.textContent='Inverted';invert.title='Switch seasons between rows and columns';
  invert.onclick=()=>{state.inverted=!state.inverted;persist();syncControls();paint();};
  controls.append(view,filter,invert);head.after(controls);
  const root=document.createElement('div');root.className='episode-ratings';controls.after(root);
  const annual=seasons(s).filter(n=>n>=1900);
  if(annual.length){
    const note=document.createElement('p');note.className='ratings-credit annual-season-note';
    note.textContent=annual.length===1?`${annual[0]} calendar-year season.`:`Calendar-year seasons, ${annual[0]}–${annual.at(-1)}.`;
    root.before(note);
  }
  const tip=tooltip(t.episodes);
  const updated=event=>{if(event.detail===s.id)paint();};
  window.addEventListener('couchside-ratings',updated);
  let resizeFrame,observedWidth=root.clientWidth;
  const observer=new ResizeObserver(entries=>{
    const width=entries[0].contentRect.width;
    if(Math.abs(width-observedWidth)<.5)return;
    observedWidth=width;cancelAnimationFrame(resizeFrame);
    resizeFrame=requestAnimationFrame(()=>{
      if(disposed||!root.isConnected||state.view!=='timeline')return;
      const scroll=root.querySelector('.ratings-chart-wrap')?.scrollLeft||0;
      const active=document.activeElement;
      const selector=root.contains(active)?active?.dataset.episode?`[data-episode="${active.dataset.episode}"]`:
        active?.classList.contains('ratings-chart-wrap')?'.ratings-chart-wrap':null:null;
      paint();
      const viewport=root.querySelector('.ratings-chart-wrap');if(viewport)viewport.scrollLeft=scroll;
      if(selector)root.querySelector(selector)?.focus();
    });
  });
  observer.observe(root);
  t.ratingsDispose=()=>{
    disposed=true;observer.disconnect();cancelAnimationFrame(resizeFrame);tip.dispose();
    window.removeEventListener('couchside-ratings',updated);
    t.episodes.removeEventListener('click',view.closestTitleClick);
    delete t.ratingSnapshot;delete t.ratingRestore;
    t.ratingSnapshotReady?.(false);
  };
  if(t.pick)t.pick.hidden=true;
  t.ratingsUpdate=()=>{t.eps.hidden=true;t.epsMore.parentElement.hidden=true;};
  t.ratingsUpdate();
  t.episodes.addEventListener('click',view.closestTitleClick);
  t.ratingSnapshot=()=>ratingDetailSnapshot(t,data,state);
  t.ratingRestore=()=>{
    if(disposed||new URL(window.location.href).searchParams.get('show')!==String(t.id))return;
    const restored=ratingDetailView(window.location.search,s.episodes);
    if(restored.view===state.view&&restored.season===state.season&&restored.inverted===state.inverted)return;
    state=restored;syncControls();paint();
  };
  function syncControls(){
    view.setValue(state.view);filter.value=String(state.season);
    invert.hidden=state.view!=='grid';invert.setAttribute('aria-pressed',String(state.inverted));
  }
  function bindHover(node){
    bindTimelineNavigation(node);
    node.querySelectorAll('[data-episode]').forEach(target=>{
      const e=s.episodes.find(e=>e.id===Number(target.dataset.episode));if(!e)return;
      target.onpointerenter=()=>tip.show(target,e);target.onpointerleave=tip.leave;
      target.onfocus=()=>{revealTimelinePoint(target);tip.show(target,e);};target.onblur=tip.hide;
      const open=()=>{tip.hide();openEpisode(ep(e),{show:s.id,number:e.season,episodes:s.episodes.filter(x=>x.season===e.season).map(ep)},target);};
      target.onclick=open;if(target.tagName.toLowerCase()==='g')target.onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();open();}};
    });
    bindTimelinePointer(node,tip);
  }
  function paint(){
    if(disposed)return;
    tip.hide();t.ratingsUpdate();const es=s.episodes.filter(e=>state.season==='all'||e.season===Number(state.season));
    if(state.view==='list'){
      root.replaceChildren();const list=document.createElement('ol');list.className='eps';list.id='ratings-episode-list';
      const rowFor=e=>{
        const row=episodeEl(ep(e),{show:s.id,number:e.season,episodes:s.episodes.filter(x=>x.season===e.season).map(ep)});
        if(state.season==='all'){
          const number=row.querySelector('.ep-num');number.textContent=episodeCode(e);number.classList.add('ratings-list-code');
          row.querySelector('.ep-open')?.setAttribute('aria-label',`${episodeCode(e)}: ${e.name}`);
        }
        const heading=row.querySelector('h4'),meta=document.createElement('span'),badge=document.createElement('span'),b=band(e.rating);
        meta.className='ratings-list-meta';
        const runtime=heading.querySelector('span');if(runtime)meta.append(runtime);
        badge.className='ratings-list-score';badge.style.background=b.colour;badge.style.color=b.text;
        const label=e.rating==null?'Unrated':`${score(e.rating)} out of 10 on ${ratingSource(e)}, ${b.name}`;
        badge.setAttribute('role','img');badge.setAttribute('aria-label',label);badge.title=label;
        html(badge,e.rating==null?'Unrated':`<b>${score(e.rating)}</b><small>/10</small>`);
        meta.append(badge);heading.append(meta);
        return row;
      };
      root.append(list);
      const set=open=>{
        const shown=snippet(es.length,3);
        // Build only visible rows; long series can have thousands of episodes.
        list.replaceChildren(...es.slice(0,open?es.length:shown).map(rowFor));
        more.parentElement.hidden=shown===es.length;
        paintReveal(more,revealLabel('episodes',es.length,open),open);
      };
      const more=revealButton(list,()=>{
        if(busy(list))return;
        expanded=t.open.episodes=!expanded;
        unfold(list,set,expanded,more);
      });
      root.append(more.parentElement);set(expanded);
      return;
    }
    html(root,`${legend()}${state.view==='grid'?ratingDetailGrid(es,state.inverted):state.view==='wrapped'?wrapped(es):chart(es,null,[],root.clientWidth)}<p class="ratings-credit">${esc(ratingSources({episodes:es})||'Audience')} episode ratings · Out of 10</p>`);
    bindHover(root);
  }
  filter.onchange=()=>{state.season=filter.value==='all'?'all':Number(filter.value);expanded=t.open.episodes=false;persist();paint();};
  syncControls();paint();t.ratingSnapshotReady?.(true);
  return t.ratingSnapshot;
}
