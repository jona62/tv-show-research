import { apiFetch } from './network.js';
import {esc,score,code,average,seasons,band,icon,html,legend,ratings,ratingSource,ratingSources} from './ratings.js';
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
// A cubic through the smoothed samples, with bounded control points to prevent overshoot.
export function smoothPath(points) {
  if(!points.length)return '';
  let d=`M${points[0].x},${points[0].y}`;
  for(let i=1;i<points.length;i++){
    const p0=points[Math.max(0,i-2)],p1=points[i-1],p2=points[i],p3=points[Math.min(points.length-1,i+1)];
    const low=Math.min(p1.y,p2.y),high=Math.max(p1.y,p2.y),clamp=y=>Math.max(low,Math.min(high,y));
    d+=` C${p1.x+(p2.x-p0.x)/6},${clamp(p1.y+(p2.y-p0.y)/6)} ${p2.x-(p3.x-p1.x)/6},${clamp(p2.y-(p3.y-p1.y)/6)} ${p2.x},${p2.y}`;
  }
  return d;
}
export function chart(es,other=null,names=[]) {
  const comparison=Boolean(other);
  const points=list=>comparison?[...new Set(list.map(e=>e.season))].map(n=>({season:n,rating:average(list.filter(e=>e.season===n)),label:`S${n}`})):list.map(e=>({...e,label:code(e)}));
  const a=points(es),b=other?points(other):[],all=[...es,...(other||[])].filter(e=>e.rating!=null);
  if(!all.length)return '<p class="ratings-empty">These episodes have not been rated yet.</p>';
  const low=Math.max(0,Math.min(9,Math.floor(Math.min(...all.map(e=>e.rating)))-1));
  const ss=[...new Set([...a,...b].map(p=>p.season))].sort((x,y)=>x-y),count=Math.max(1,a.length,b.length);
  const x=(p,i)=>46+(comparison?ss.indexOf(p.season)/Math.max(1,ss.length-1):i/Math.max(1,count-1))*686;
  const y=v=>270-(v-low)*240/(10-low),ticks=Array.from({length:(10-low)*2+1},(_,i)=>low+i*.5);
  const series=(ps,c,showIndex)=>{
    const pts=ps.map((p,i)=>({...p,x:x(p,i),y:p.rating==null?null:y(p.rating)}));
    const line=pts.map((p,i)=>p.y==null?'':`${i&&pts[i-1].y!=null?'L':'M'}${p.x},${p.y}`).join(' ');
    let out=`<path class="ratings-raw-line" d="${line}" fill="none" stroke="${c}" stroke-width="${comparison?2:1}" opacity="${comparison?'.8':'.3'}"/>`;
    if(!comparison){
      const moving=pts.map((p,i)=>({...p,y:p.rating==null?null:y(average(ps.slice(Math.max(0,i-2),Math.min(ps.length,i+3))))}));
      const segments=[];for(const p of moving){if(p.y==null){if(segments.at(-1)?.length)segments.push([]);}else{if(!segments.length)segments.push([]);segments.at(-1).push(p);}}
      out+=`<path class="ratings-trend" d="${segments.map(smoothPath).join(' ')}" fill="none" stroke="var(--brand)" stroke-width="2.6"/>`;
    }
    out+=pts.map(p=>p.y==null?'':`<g class="ratings-point-hit" ${comparison?`data-season="${p.season}" data-show-index="${showIndex}"`:`data-episode="${p.id}"`} tabindex="0" role="${comparison?'img':'button'}" aria-label="${comparison?esc(names[showIndex])+', ':''}${p.label}${p.name?': '+esc(p.name):''}, ${score(p.rating)} out of 10, ${band(p.rating).name}"><circle class="ratings-point-target" cx="${p.x}" cy="${p.y}" r="9" fill="transparent"/><circle class="ratings-point" cx="${p.x}" cy="${p.y}" r="${comparison?4.5:3.5}" fill="${comparison?c:band(p.rating).colour}"/></g>`).join('');
    return out;
  };
  const labels=comparison?ss.map((n,i)=>({text:'S'+n,x:46+i*686/Math.max(1,ss.length-1)})):a.filter((p,i)=>i===0||p.season!==a[i-1].season).map(p=>({text:p.label,x:x(p,a.indexOf(p))}));
  return `<div class="ratings-chart-wrap"><svg class="ratings-timeline" viewBox="0 0 780 310" role="group" aria-label="${comparison?'Season averages':'Episode ratings'}, scale ${low} to 10 in half-point steps" data-min="${low}">${ticks.map(v=>`<line x1="46" y1="${y(v)}" x2="736" y2="${y(v)}" stroke="#ffffff0c"/><text class="ratings-tick" x="32" y="${y(v)+4}" text-anchor="end">${v.toFixed(1)}</text>`).join('')}${series(a,'#ffb020',0)}${b.length?series(b,'#91b9dc',1):''}${labels.map(p=>`<text x="${p.x}" y="298" text-anchor="middle">${p.text}</text>`).join('')}</svg></div>`;
}

function tooltip(host) {
  const tip=document.createElement('div');tip.className='ratings-tooltip';tip.id='ratings-hover';tip.setAttribute('role','tooltip');tip.hidden=true;host.append(tip);
  let active=null,hideTimer;
  const hide=()=>{clearTimeout(hideTimer);active=null;tip.hidden=true;host.querySelectorAll('[aria-describedby=ratings-hover]').forEach(e=>e.removeAttribute('aria-describedby'));};
  const leave=()=>{clearTimeout(hideTimer);hideTimer=setTimeout(hide,150);};
  const position=()=>{
    if(!active)return;
    const r=active.target.getBoundingClientRect(),width=tip.offsetWidth,height=tip.offsetHeight;
    const left=Math.max(12,Math.min(window.innerWidth-width-12,r.left+r.width/2-width/2));
    let top=r.top-height-12;if(top<12)top=Math.min(window.innerHeight-height-12,r.bottom+12);
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
  const scrolled=event=>{if(tip.contains(event.target))return;if(active?.target===document.activeElement)position();else hide();};
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
  t.ratingsDispose=()=>{tip.dispose();comparison.dispose();window.removeEventListener('couchside-ratings',updated);};
  if(t.pick)t.pick.hidden=true;
  t.ratingsUpdate=()=>{t.eps.hidden=true;t.epsMore.parentElement.hidden=true;};
  t.ratingsUpdate();
  t.episodes.addEventListener('click',view.closestTitleClick);
  function bindHover(node){
    node.querySelectorAll('[data-episode]').forEach(target=>{
      const e=s.episodes.find(e=>e.id===Number(target.dataset.episode));if(!e)return;
      target.onpointerenter=()=>tip.show(target,e);target.onpointerleave=tip.leave;target.onfocus=()=>tip.show(target,e);target.onblur=tip.hide;
      const open=()=>{tip.hide();openEpisode(ep(e),{show:s.id,number:e.season,episodes:s.episodes.filter(x=>x.season===e.season).map(ep)},target);};
      target.onclick=open;if(target.tagName.toLowerCase()==='g')target.onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();open();}};
    });
  }
  function paintComparison(){
    tip.hide();if(!other){comparison.replaceChildren();return;}
    html(comparison,`<p class="ratings-comparison-key"><span>${esc(s.name)}</span><span>${esc(other.name)}</span></p>${chart(s.episodes,other.episodes,[s.name,other.name])}<p class="ratings-credit">Average episode rating per season · Seasons align by number</p>`);
    comparison.querySelectorAll('[data-season]').forEach(target=>{
      const show=Number(target.dataset.showIndex)===0?s:other,n=Number(target.dataset.season),eps=show.episodes.filter(e=>e.season===n),e={season:n,rating:average(eps),rating_source:ratingSources({episodes:eps}),name:`${eps.length} episodes`};
      target.onpointerenter=()=>tip.show(target,e,show.name);target.onpointerleave=tip.leave;target.onfocus=()=>tip.show(target,e,show.name);target.onblur=tip.hide;
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
    html(root,`${legend()}${layout==='grid'?grid(es):layout==='wrapped'?wrapped(es):chart(es)}<p class="ratings-credit">${esc(ratingSources({episodes:es})||'Audience')} episode ratings · Out of 10${layout==='timeline'?' · Amber line: smoothed 5-episode average':''}</p>`);
    bindHover(root);
  }
  filter.onchange=()=>{season=filter.value;expanded=t.open.episodes=false;paint();};paint();
}
