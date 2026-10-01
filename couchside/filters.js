import {filtersFor,setFilters} from './filter-state.js';
import {icon,html} from './ratings.js';
const node = (tag,cls,text) => { const n=document.createElement(tag); if(cls)n.className=cls; if(text)n.textContent=text; return n; };
const button = (text,action,cls='chip') => { const b=node('button',cls,text); b.type='button'; b.onclick=action; return b; };
const labels={rating:v=>`TVmaze ${v}+`,length:v=>({short:'Under 30 min',standard:'30–60 min',long:'Over 60 min'})[v],status:v=>v==='Running'?'Ongoing':v,year:v=>`Since ${v}`,language:v=>v,format:v=>({scripted:'Scripted',animation:'Animation',documentary:'Documentary',unscripted:'Unscripted'})[v],episodes:v=>`Up to ${v} episodes`,seasons:v=>`Up to ${v} season${v===1?'':'s'}`,hours:v=>`Up to ${v} hours`};
export function filterBar(page,{genres=[],languages=[],onChange,search=false,compact=false}={}) {
  const bar=node('div',`discovery${compact?' discovery-compact':''}`),tools=node('div','discovery-tools'),active=node('div','discovery-active');
  let find='';
  const changed=()=>{paint();onChange?.(find);};
  if(search){
    const label=node('label','discovery-find'); label.append(node('span','sr','Find a show in your list'));
    const input=node('input'); input.type='search'; input.placeholder='Find a show in your list'; input.maxLength=100;
    input.oninput=()=>{find=input.value;onChange?.(find);};label.append(input);tools.append(label);
  }
  const open=()=>sheet();
  if(!compact){tools.append(button('Genre',()=>sheet('genres'),'chip discovery-quick'),button('Commitment',()=>sheet('commitment'),'chip discovery-quick'));}
  const filters=button('',open,'chip discovery-filter');filters.setAttribute('aria-haspopup','dialog');
  tools.append(filters);
  const sortLabel=node('label','discovery-sort');html(sortLabel,icon('sort'));sortLabel.append(node('span','sr','Sort shows'));
  const sort=node('select');
  const defaultSort={search:'Relevance',list:'Recently added',more:'Most similar',fans:'Fan favorites',person:'Original order'}[page]||'For you';
  for(const [value,label] of [['relevance',defaultSort],['popular','Popularity'],['rating','Highest rated'],['newest','Newest'],['shortest','Shortest watch time'],...(page==='list'?[['name','A–Z']]:[])]){
    const option=node('option','',label);option.value=value;sort.append(option);
  }
  sort.onchange=()=>{setFilters(page,{...filtersFor(page),sort:sort.value});changed();};sortLabel.append(sort);tools.append(sortLabel);
  bar.append(tools,active);
  function paint(){
    const f=filtersFor(page),entries=Object.entries(f).filter(([k])=>k!=='sort');
    const count=entries.reduce((n,[k,v])=>n+(k==='genres'?v.length:1),0);
    html(filters,`${icon('filter')}<span>Filters${count?` (${count})`:''}</span>`);filters.classList.toggle('on',!!count);
    sort.value=f.sort||'relevance';
    active.replaceChildren();
    for(const [key,value] of entries){
      const values=key==='genres'?value:[value];
      for(const v of values){
        const label=key==='genres'?v:labels[key]?.(v);if(!label)continue;
        const b=button('',()=>{const next={...filtersFor(page)};if(key==='genres')next.genres=next.genres.filter(g=>g!==v);else delete next[key];setFilters(page,next);changed();},'chip discovery-applied');
        b.append(document.createTextNode(label));const close=node('span');html(close,icon('close'));b.append(close);b.setAttribute('aria-label',`Remove ${label} filter`);active.append(b);
      }
    }
    if(entries.length)active.append(button('Clear all',()=>{setFilters(page,{});changed();},'link discovery-clear'));
    active.hidden=!entries.length;
  }
  function sheet(focus){
    const draft=structuredClone(filtersFor(page)),dialog=node('dialog','menu discovery-menu'),body=node('div','menu-sheet');
    const head=node('div','menu-head');const title=node('h2','', 'Filter shows');title.id=`discovery-${page}-h`;dialog.setAttribute('aria-labelledby',title.id);
    const close=button('',()=>dialog.close(),'icon-btn close-btn');html(close,icon('close'));close.setAttribute('aria-label','Close filters');head.append(title,close);body.append(head);
    const form=node('form','discovery-fields');
    const select=(key,label,options)=>{
      const field=node('label','discovery-field',label),input=node('select');input.name=key;
      for(const [value,text] of [['', 'Any'],...options]){const o=node('option','',text);o.value=value;input.append(o);}
      input.value=draft[key]||'';input.onchange=()=>{draft[key]=input.value;};field.append(input);form.append(field);return input;
    };
    const group=node('fieldset','discovery-genres');group.id=`discovery-${page}-genres`;group.append(node('legend','','Genre'));
    for(const g of genres){if(['animation','documentary','unscripted'].includes(g.key))continue;
      const label=node('label','discovery-genre'),check=node('input');check.type='checkbox';check.checked=draft.genres?.includes(g.key)||false;
      check.onchange=()=>{draft.genres=check.checked?[...(draft.genres||[]),g.key]:(draft.genres||[]).filter(k=>k!==g.key);};label.append(check,node('span','',g.key));group.append(label);
    }
    form.append(group);
    select('rating','Public rating · TVmaze',[[7,'7 and above'],[8,'8 and above'],[9,'9 and above']]).onchange=e=>{draft.rating=Number(e.target.value)||'';};
    const commitment=node('fieldset','discovery-commitment');commitment.id=`discovery-${page}-commitment`;commitment.append(node('legend','','Commitment'));
    const choices=node('div','discovery-presets');
    const custom=node('div','discovery-limits');
    const inputs={};
    for(const [key,label,max] of [['hours','Total hours',10000],['episodes','Episodes',10000],['seasons','Seasons',200]]){
      const field=node('label','discovery-field',label),input=node('input');input.type='number';input.inputMode='decimal';input.min=1;input.max=max;input.step=key==='hours'?.5:1;input.placeholder='Any';input.value=draft[key]||'';
      input.oninput=()=>{draft[key]=input.value?Number(input.value):'';mark();};inputs[key]=input;field.append(input);custom.append(field);
    }
    const presets=[['Any',{}],['Up to 10 hours',{hours:10}],['One season',{seasons:1}],['20 episodes or fewer',{episodes:20}]];
    const mark=()=>choices.querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(['hours','episodes','seasons'].every(k=>(draft[k]||0)===(presets[i][1][k]||0)))));
    for(const [text,limits] of presets)choices.append(button(text,()=>{for(const k of ['hours','episodes','seasons']){draft[k]=limits[k]||'';inputs[k].value=draft[k];}mark();}));
    mark();commitment.append(choices,custom,node('p','discovery-help','Airing shows count episodes released so far. Watch time is estimated when episode lengths are missing. Shows with unknown counts are left out when a limit is active.'));form.append(commitment);
    select('length','Episode length',[['short','Under 30 minutes'],['standard','30–60 minutes'],['long','Over 60 minutes']]);
    select('status','Status',[['Running','Ongoing'],['Ended','Ended'],['In Development','Coming soon'],['To Be Determined','To be determined']]);
    select('year','Premiered',[[2020,'2020 or later'],[2010,'2010 or later'],[2000,'2000 or later'],[1990,'1990 or later']]).onchange=e=>{draft.year=Number(e.target.value)||'';};
    select('language','Language',languages.map(l=>[l,l]));
    select('format','Format',[['scripted','Scripted'],['animation','Animation'],['documentary','Documentary'],['unscripted','Unscripted']]);
    const foot=node('div','discovery-actions');foot.append(button('Clear filters',()=>{setFilters(page,{});changed();dialog.close();},'btn ghost'));
    const apply=node('button','btn primary','Show matches');apply.type='submit';foot.append(apply);form.append(foot);
    form.onsubmit=e=>{e.preventDefault();setFilters(page,draft);changed();dialog.close();};body.append(form);dialog.append(body);document.body.append(dialog);
    dialog.onclick=e=>{if(e.target===dialog)dialog.close();};dialog.onclose=()=>{dialog.remove();filters.focus({preventScroll:true});};dialog.showModal();
    if(focus)dialog.querySelector(`#discovery-${page}-${focus}`)?.scrollIntoView({block:'start'});
  }
  paint();return {element:bar,paint,query:()=>find};
}
