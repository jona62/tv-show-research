import { apiFetch } from './network.js?v=4038b4a1107593ef';
import {chart,nearestRatingPoint} from './episode-timeline.js?v=f54d321fe2d8c409';
export {chart,smoothPath} from './episode-timeline.js?v=f54d321fe2d8c409';
import {esc,score,code,average,seasons,band,icon,html,legend,ratings,ratingSource,ratingSources} from './ratings.js?v=2a0509d86dd759f5';
const plain = value => new DOMParser().parseFromString(value||'', 'text/html').body.textContent||'';
const layouts=[['list','Episode list'],['grid','Grid'],['wrapped','Wrapped'],['timeline','Timeline']];
const ep = e => ({...e,still:e.image,summary:plain(e.summary)});
const options = (items,value) => items.map(([v,t])=>`<option value="${v}" ${String(v)===String(value)?'selected':''}>${esc(t)}</option>`).join('');

function picker(onChange) {
  const node=document.createElement('div');node.className='ratings-picker';
  html(node,`<button type="button" class="ratings-view-button" aria-label="Episode layout: Episode list" aria-haspopup="listbox" aria-expanded="false" aria-controls="ratings-view-options">${icon('list')}<span>Episode list</span>${icon('down')}</button><div id="ratings-view-options" class="ratings-view-options" role="listbox" aria-label="Episode layout" hidden>${layouts.map(([id,label])=>`<button type="button" role="option" aria-selected="${id==='list'}" data-layout="${id}">${icon(id)}<span>${label}</span>${icon('check')}</button>`).join('')}</div>`);
  const trigger=node.querySelector('.ratings-view-button'),menu=node.querySelector('[role=listbox]');
  const close=()=>{menu.hidden=true;trigger.setAttribute('aria-expanded','false');};
  const open=()=>{menu.hidden=false;trigger.setAttribute('aria-expanded','true');menu.querySelector('[aria-selected=true]').focus();};
  trigger.onclick=()=>menu.hidden?open():close();
  trigger.onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();open();}};
  node.querySelectorAll('[data-layout]').forEach(button=>button.onclick=()=>{
    node.querySelectorAll('[data-layout]').forEach(b=>b.setAttribute('aria-selected',String(b===button)));
    html(trigger,`${icon(button.dataset.layout)}<span>${button.querySelector('span').textContent}</span>${icon('down')}`);
    trigger.setAttribute('aria-label',`Episode layout: ${button.querySelector('span').textContent}`);
    close();trigger.focus();onChange(button.dataset.layout);
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
  return `<button type="button" class="ratings-cell" style="background:${b.colour};color:${b.text}" data-episode="${e.id}" aria-label="${code(e)}: ${esc(e.name)}, ${score(e.rating)}${e.rating==null?'':' out of 10'}, ${b.name}">${e.rating==null?'—':score(e.rating)}</button>`;
}
function grid(es) {
  const ss=[...new Set(es.map(e=>e.season))],max=Math.max(1,...es.map(e=>e.number));
  let out='<span class="ratings-axis">Season</span>'+Array.from({length:max},(_,i)=>`<span class="ratings-axis">E${i+1}</span>`).join('')+'<span class="ratings-axis">Avg.</span>';
  for(const n of ss){const eps=es.filter(e=>e.season===n);out+=`<span class="ratings-season">S${n}</span>`+Array.from({length:max},(_,i)=>cell(eps.find(e=>e.number===i+1))).join('')+`<span class="ratings-average">${score(average(eps))}</span>`;}
  return `<div class="ratings-grid-scroll" tabindex="0" aria-label="Episode ratings grid; scroll for more episodes"><div class="ratings-grid" style="grid-template-columns:48px repeat(${max},minmax(34px,1fr)) 40px">${out}</div></div>`;
}
function wrapped(es) {
  return [...new Set(es.map(e=>e.season))].map(n=>{const eps=es.filter(e=>e.season===n);return `<section class="ratings-wrapped-season"><div class="ratings-wrapped-heading"><b>Season ${n}</b><span>${score(average(eps))} average</span></div><div class="ratings-wrapped-cells">${eps.map(e=>`<div><span class="ratings-axis">E${e.number}</span>${cell(e)}</div>`).join('')}</div></section>`;}).join('');
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
    html(tip,`${e.image?`<img src="${esc(e.image)}" alt="" loading="lazy">`:''}<div class="ratings-tooltip-body"><span class="ratings-tooltip-code">${showName?esc(showName)+' · ':''}${e.number?code(e):'Season '+e.season}</span><b>${esc(e.name||'Season average')}</b><div class="ratings-tooltip-score"><strong style="background:${b.colour};color:${b.text}">${score(e.rating)}</strong><span>${b.name}<small>${e.rating==null?'Awaiting audience ratings':`out of 10 on ${esc(ratingSource(e))}${e.rating_votes?' · '+Number(e.rating_votes).toLocaleString()+' votes':''}`}</small></span></div>${e.number?`<p class="ratings-tooltip-summary">${esc(summary||'No episode description available.')}</p>`:''}</div>`);
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
function compareSearch(host,s,onPick) {
  html(host,`<div class="ratings-compare-head"><h4>Compare with another show</h4><span class="ratings-compare-selected"></span></div><div class="ratings-search-wrap">${icon('search')}<input type="search" placeholder="Search any show…" aria-label="Find a show to compare" autocomplete="off" aria-controls="ratings-compare-results" aria-expanded="false"><div class="ratings-compare-results" id="ratings-compare-results" hidden></div></div><p class="ratings-search-status" role="status"></p><div class="ratings-comparison"></div>`);
  const input=host.querySelector('input'),results=host.querySelector('.ratings-compare-results'),status=host.querySelector('[role=status]'),selected=host.querySelector('.ratings-compare-selected');
  let timer,token=0;
  const dismiss=()=>{results.hidden=true;input.setAttribute('aria-expanded','false');};
  const choose=async c=>{
    const asked=++token;dismiss();input.value='';status.textContent='Loading '+c.name+'…';
    try{const data=await ratings(c.id);if(asked!==token)return;const other={...data,name:c.name};status.textContent='';onPick(other);html(selected,`<span>${esc(c.name)}</span><button type="button" class="link" aria-label="Remove comparison">${icon('close')}</button>`);selected.querySelector('button').onclick=()=>{token++;selected.replaceChildren();onPick(null);input.focus();};}
    catch(error){if(asked===token){status.textContent=error.message;}}
  };
  input.oninput=()=>{
    clearTimeout(timer);const q=input.value.trim(),asked=++token;dismiss();if(q.length<2){status.textContent='';return;}
    status.textContent='Searching…';
    timer=setTimeout(async()=>{
      try{const response=await apiFetch(`/api/search?q=${encodeURIComponent(q)}`),body=await response.json();if(asked!==token)return;if(!response.ok)throw Error(body.error||'Search is unavailable.');
        const shows=(body.shows||[]).filter(c=>c.id!==s.id).slice(0,8);
        html(results,shows.map(c=>`<button type="button" class="ratings-search-result" data-id="${c.id}">${c.poster?`<img src="${esc(c.poster)}" alt="">`:''}<span><b>${esc(c.name)}</b><small>${esc(c.year||'')}</small></span>${icon('down')}</button>`).join(''));
        results.querySelectorAll('button').forEach(b=>b.onclick=()=>choose(shows.find(c=>c.id===Number(b.dataset.id))));results.hidden=!shows.length;input.setAttribute('aria-expanded',String(Boolean(shows.length)));status.textContent=shows.length?'':'No matching shows.';
      }catch(error){if(asked===token)status.textContent=error.message;}
    },250);
  };
  host.onkeydown=e=>{if(e.key==='Escape'&&!results.hidden){e.stopPropagation();dismiss();}if(e.key==='ArrowDown'&&!results.hidden){e.preventDefault();const bs=[...results.querySelectorAll('button')];bs[(bs.indexOf(document.activeElement)+1)%bs.length]?.focus();}};
  const dialog=host.closest('dialog'),outside=e=>{if(!host.contains(e.target))dismiss();};
  dialog?.addEventListener('pointerdown',outside);
  const comparison=host.querySelector('.ratings-comparison');
  comparison.dispose=()=>{token++;clearTimeout(timer);dialog?.removeEventListener('pointerdown',outside);};
  return comparison;
}
export async function mountEpisodeRatings(t,{openEpisode,episodeEl,revealButton,paintReveal,unfold,busy,snippet,revealLabel},saved=null) {
  if(t.episodes.dataset.ratingsMounted)return;
  t.episodes.dataset.ratingsMounted='true';
  let data;
  try{data=saved||await ratings(t.id);}catch{return;}
  if(!t.episodes.isConnected||!data.episodes.length)return;
  const s={...data,name:t.live?.name||t.name.textContent||data.name||t.card.name||'This show'};
  let layout='list',season='all',expanded=t.open.episodes,other=null;
  const head=t.episodes.querySelector('.t-section-head'),controls=document.createElement('div');controls.className='ratings-controls';
  const view=picker(value=>{layout=value;paint();});
  const filter=document.createElement('select');filter.setAttribute('aria-label','Episode season');filter.innerHTML=options([['all','All seasons'],...seasons(s).map(n=>[n,'Season '+n])],season);
  controls.append(view,filter);head.after(controls);
  const root=document.createElement('div');root.className='episode-ratings';controls.after(root);
  const compare=document.createElement('div');compare.className='ratings-compare';root.after(compare);
  const tip=tooltip(t.episodes);
  const comparison=compareSearch(compare,s,value=>{other=value;paintComparison();});
  const updated=event=>{if(event.detail===s.id||event.detail===other?.id){paint();paintComparison();}};
  window.addEventListener('couchside-ratings',updated);
  let resizeFrame;
  const observer=new ResizeObserver(entries=>{
    const width=entries[0].contentRect.width;
    if(Math.abs(width-observedWidth)<.5)return;
    observedWidth=width;cancelAnimationFrame(resizeFrame);
    resizeFrame=requestAnimationFrame(()=>{
      const hosts=[root,comparison],scrolls=hosts.map(host=>host.querySelector('.ratings-chart-wrap')?.scrollLeft||0);
      const active=document.activeElement,owner=hosts.find(host=>host.contains(active));
      const selector=active?.dataset.episode?`[data-episode="${active.dataset.episode}"]`:
        active?.dataset.season?`[data-season="${active.dataset.season}"][data-show-index="${active.dataset.showIndex}"]`:
        active?.classList.contains('ratings-chart-wrap')?'.ratings-chart-wrap':null;
      if(layout==='timeline')paint();
      if(other)paintComparison();
      hosts.forEach((host,i)=>{const viewport=host.querySelector('.ratings-chart-wrap');if(viewport)viewport.scrollLeft=scrolls[i];});
      if(owner&&selector)owner.querySelector(selector)?.focus();
    });
  });
  let observedWidth=root.clientWidth;observer.observe(root);
  t.ratingsDispose=()=>{observer.disconnect();cancelAnimationFrame(resizeFrame);tip.dispose();comparison.dispose();window.removeEventListener('couchside-ratings',updated);};
  if(t.pick)t.pick.hidden=true;
  t.ratingsUpdate=()=>{t.eps.hidden=true;t.epsMore.parentElement.hidden=true;};
  t.ratingsUpdate();
  t.episodes.addEventListener('click',view.closestTitleClick);
  function bindHover(node){
    bindTimelineNavigation(node);
    node.querySelectorAll('[data-episode]').forEach(target=>{
      const e=s.episodes.find(e=>e.id===Number(target.dataset.episode));if(!e)return;
      target.onpointerenter=()=>tip.show(target,e);target.onpointerleave=tip.leave;target.onfocus=()=>{revealTimelinePoint(target);tip.show(target,e);};target.onblur=tip.hide;
      const open=()=>{tip.hide();openEpisode(ep(e),{show:s.id,number:e.season,episodes:s.episodes.filter(x=>x.season===e.season).map(ep)},target);};
      target.onclick=open;if(target.tagName.toLowerCase()==='g')target.onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();open();}};
    });
    bindTimelinePointer(node,tip);
  }
  function paintComparison(){
    tip.hide();if(!other){comparison.replaceChildren();return;}
    html(comparison,`<p class="ratings-comparison-key"><span>${esc(s.name)}</span><span>${esc(other.name)}</span></p>${chart(s.episodes,other.episodes,[s.name,other.name],comparison.clientWidth)}<p class="ratings-credit">Average episode rating per season · Seasons align by number</p>`);
    bindTimelineNavigation(comparison);
    comparison.querySelectorAll('[data-season]').forEach(target=>{
      const show=Number(target.dataset.showIndex)===0?s:other,n=Number(target.dataset.season),eps=show.episodes.filter(e=>e.season===n),rated=eps.filter(e=>e.rating!=null).length,e={season:n,rating:average(eps),rating_source:ratingSources({episodes:eps}),name:`${rated} rated of ${eps.length} episodes`};
      target.onpointerenter=()=>tip.show(target,e,show.name);target.onpointerleave=tip.leave;target.onfocus=()=>{revealTimelinePoint(target);tip.show(target,e,show.name);};target.onblur=tip.hide;
    });
  }
  function paint(){
    tip.hide();t.ratingsUpdate();const es=s.episodes.filter(e=>season==='all'||e.season===Number(season));
    if(layout==='list'){
      root.replaceChildren();const list=document.createElement('ol');list.className='eps';list.id='ratings-episode-list';
      const rowFor=e=>{
        const row=episodeEl(ep(e),{show:s.id,number:e.season,episodes:s.episodes.filter(x=>x.season===e.season).map(ep)});
        if(season==='all'){const number=row.querySelector('.ep-num');number.textContent=code(e);number.classList.add('ratings-list-code');row.querySelector('.ep-open')?.setAttribute('aria-label',`${code(e)}: ${e.name}`);}
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
        // Build only what is shown. Long-running series can have thousands of rows;
        // constructing them and their images just to hide them stalls the title sheet.
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
    html(root,`${legend()}${layout==='grid'?grid(es):layout==='wrapped'?wrapped(es):chart(es,null,[],root.clientWidth)}<p class="ratings-credit">${esc(ratingSources({episodes:es})||'Audience')} episode ratings · Out of 10</p>`);
    bindHover(root);
  }
  filter.onchange=()=>{season=filter.value;expanded=t.open.episodes=false;paint();};paint();
}
