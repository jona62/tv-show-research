import {filtersFor,setFilters} from './filter-state.js?v=2a62eef7fd5aeeda';
import {icon,html} from './ratings.js?v=70517fd9f1cddac1';

const node = (tag,cls,text) => { const n=document.createElement(tag); if(cls)n.className=cls; if(text)n.textContent=text; return n; };
const button = (text,action,cls='menu-item') => { const b=node('button',cls,text); b.type='button'; b.onclick=action; return b; };
const labels={rating:v=>`TVmaze ${v}+`,length:v=>({short:'Under 30 min',standard:'30–60 min',long:'Over 60 min'})[v],status:v=>v==='Running'?'Ongoing':v,year:v=>`Since ${v}`,language:v=>v,format:v=>({scripted:'Scripted',animation:'Animation',documentary:'Documentary',unscripted:'Unscripted'})[v],episodes:v=>`Up to ${v} episodes`,seasons:v=>`Up to ${v} season${v===1?'':'s'}`,hours:v=>`Up to ${v} hours`};

export function filterBar(page,{genres=[],languages=[],onChange,onPaint,search=false,compact=false,trigger=null,extra=[]}={}) {
  const bar=node('div',`discovery${compact?' discovery-compact':''}`),tools=node('div','discovery-tools');
  const applied=node('div','discovery-active'),description=node('span','discovery-description');
  let find='',count=0,opened=null;
  const changed=()=>{paint();onChange?.(find);};
  if(search){
    const label=node('label','discovery-find');label.append(node('span','sr','Find a show in your list'));
    const input=node('input');input.type='search';input.placeholder='Find a show in your list';input.maxLength=100;
    input.oninput=()=>{find=input.value;onChange?.(find);};label.append(input);tools.append(label);
  }
  const filters=button('',()=>sheet(),'genre-chip genre-all');
  filters.hidden=!!trigger;
  filters.setAttribute('aria-haspopup','dialog');filters.setAttribute('aria-expanded','false');
  tools.append(filters);
  applied.append(description,button('Clear',()=>{clear();(trigger||filters).focus({preventScroll:true});},'link discovery-clear'));
  bar.append(tools,applied);
  const defaultSort={search:'Relevance',list:'Recently added',more:'Most similar',fans:'Fan favorites',person:'Original order'}[page]||'For you';
  const sorts=[['',defaultSort],['popular','Popularity'],['rating','Highest rated'],['newest','Newest'],['shortest','Shortest watch time'],...(page==='list'?[['name','A–Z']]:[])];
  const summary=(f,keys)=>keys.flatMap(k=>k==='genres'?(f.genres||[]):f[k]?[labels[k]?.(f[k])||sorts.find(([v])=>v===f[k])?.[1]].filter(Boolean):[]).join(', ');
  function clear(){setFilters(page,{});extra.forEach(f=>f.apply(''));changed();}
  function paint(){
    const f=filtersFor(page);count=Object.entries(f).reduce((n,[k,v])=>n+(k==='genres'?v.length:1),0)+extra.filter(f=>f.get()).length;
    html(filters,`<span>Filters${count?` (${count})`:''}</span>${icon('down')}`);
    filters.classList.toggle('on',!!count);
    description.textContent=[summary(f,Object.keys(f)),...extra.map(f=>f.options.find(([v])=>v===f.get()&&v)?.[1])].filter(Boolean).join(' · ');
    applied.hidden=!count;
    tools.hidden=!!trigger&&!search;
    bar.hidden=!!trigger&&!search&&!count;
    onPaint?.();
  }
  function sheet(anchor=trigger||filters){
    if(opened)return;
    const draft=structuredClone(filtersFor(page)),extras=new Map(extra.map(f=>[f.name,f.get()]));
    const dialog=node('dialog','menu genre-menu discovery-menu'),body=node('div','menu-sheet');
    const head=node('div','menu-head'),title=node('h2','','Filters');title.id=`discovery-${page}-h`;
    dialog.setAttribute('aria-labelledby',title.id);
    const close=button('',()=>dialog.close(),'icon-btn close-btn');html(close,icon('close'));close.setAttribute('aria-label','Close filters');head.append(title,close);body.append(head);
    const form=node('form','discovery-form'),sections=node('div','discovery-sections'),groups=[];
    const update=()=>{groups.forEach(g=>{g.value.textContent=g.read()||g.empty;});all.setAttribute('aria-pressed',String(!draft.genres?.length));};
    const group=(label,read,empty='Any')=>{
      const details=node('details','discovery-group'),toggle=node('summary','menu-item discovery-toggle');
      const value=node('span','discovery-value'),arrow=node('span');html(arrow,icon('down'));
      toggle.append(node('span','',label),value,arrow);details.append(toggle);
      const options=node('div','discovery-options');details.append(options);sections.append(details);groups.push({details,value,read,empty});
      details.addEventListener('toggle',()=>{if(details.open)groups.forEach(g=>{if(g.details!==details)g.details.open=false;});place();});
      return options;
    };
    const option=(box,name,value,text,read,write,type='radio')=>{
      const label=node('label','genre-opt discovery-option'),input=node('input','sr');
      input.type=type;input.name=`${page}-${name}`;input.value=value;input.checked=type==='checkbox'?read().includes(value):read()===value;
      const check=node('span','discovery-check');html(check,icon('check'));
      input.onchange=()=>{write(value,input.checked);update();};label.append(input,node('span','',text),check);box.append(label);return input;
    };
    const choose=(box,key,options,empty='Any')=>{
      for(const [value,text] of [['',empty],...options])option(box,key,value,text,()=>draft[key]||'',v=>{draft[key]=v;});
    };
    const select=(box,key,label,options,read=()=>draft[key]||'',write=v=>{draft[key]=v;})=>{
      const field=node('label','menu-item menu-field',label),input=node('select');input.name=key;
      for(const [value,text] of [['','Any'],...options]){const o=node('option','',text);o.value=value;input.append(o);}
      input.value=read();input.onchange=()=>{write(input.value);update();};field.append(input);box.append(field);
    };
    const genre=group('Genre',()=>summary(draft,['genres']),'All genres');
    const all=button('All genres',()=>{draft.genres=[];genre.querySelectorAll('input').forEach(i=>{i.checked=false;});update();},'genre-opt');
    const allCheck=node('span','discovery-check');html(allCheck,icon('check'));all.append(allCheck);
    genre.append(all);
    for(const g of genres){
      if(['animation','documentary','unscripted'].includes(g.key))continue;
      option(genre,'genres',g.key,g.short||g.label,()=>draft.genres||[],(v,checked)=>{draft.genres=checked?[...(draft.genres||[]),v]:(draft.genres||[]).filter(k=>k!==v);},'checkbox');
    }
    const rating=group('Rating',()=>summary(draft,['rating']));
    for(const [value,text] of [['','Any rating'],[7,'7 and above'],[8,'8 and above'],[9,'9 and above']]){
      option(rating,'rating',value,text,()=>draft.rating||'',v=>{draft.rating=Number(v)||'';});
    }
    rating.append(node('p','discovery-help','Overall show ratings from TVmaze.'));
    const commitment=group('Commitment',()=>summary(draft,['hours','episodes','seasons']));
    const presets=[['Any length',{}],['Up to 10 hours',{hours:10}],['One season',{seasons:1}],['20 episodes or fewer',{episodes:20}]],inputs={};
    const preset=()=>presets.findIndex(([,f])=>['hours','episodes','seasons'].every(k=>(draft[k]||0)===(f[k]||0)));
    const presetInputs=[];
    presets.forEach(([text,limits],i)=>presetInputs.push(option(commitment,'commitment',i,text,preset,()=>{
      for(const k of ['hours','episodes','seasons']){draft[k]=limits[k]||'';inputs[k].value=draft[k];}
    })));
    const custom=node('details','discovery-custom'),customToggle=node('summary','menu-item discovery-toggle');
    const customArrow=node('span');html(customArrow,icon('down'));customToggle.append(node('span','','Custom limits'),customArrow);custom.append(customToggle);custom.open=preset()<0;
    custom.addEventListener('toggle',place);
    for(const [key,label,max] of [['hours','Total hours, up to',10000],['episodes','Episodes, up to',10000],['seasons','Seasons, up to',200]]){
      const field=node('label','menu-item menu-field',label),input=node('input');input.type='number';input.inputMode=key==='hours'?'decimal':'numeric';input.min=key==='hours'?.5:1;input.max=max;input.step=key==='hours'?.5:1;input.placeholder='Any';input.value=draft[key]||'';
      input.oninput=()=>{draft[key]=input.value?Number(input.value):'';presetInputs.forEach((p,i)=>{p.checked=i===preset();});update();};inputs[key]=input;field.append(input);custom.append(field);
    }
    commitment.append(custom);
    commitment.append(node('p','discovery-help','Airing shows count released episodes. Watch time may be estimated. Shows with unknown counts are left out when a limit is set.'));
    const more=group('More filters',()=>summary(draft,['length','status','year','language','format']));
    select(more,'length','Episode length',[['short','Under 30 minutes'],['standard','30–60 minutes'],['long','Over 60 minutes']]);
    select(more,'status','Status',[['Running','Ongoing'],['Ended','Ended'],['In Development','Coming soon'],['To Be Determined','To be determined']]);
    select(more,'year','Premiered',[[2020,'2020 or later'],[2010,'2010 or later'],[2000,'2000 or later'],[1990,'1990 or later']],()=>draft.year||'',v=>{draft.year=Number(v)||'';});
    select(more,'language','Language',languages.map(l=>[l,l]));
    select(more,'format','Format',[['scripted','Scripted'],['animation','Animation'],['documentary','Documentary'],['unscripted','Unscripted']]);
    const sort=group('Sort',()=>sorts.find(([v])=>v===(draft.sort||''))?.[1],defaultSort);choose(sort,'sort',sorts.slice(1),defaultSort);
    for(const f of extra){
      const box=group(f.label,()=>f.options.find(([v])=>v===extras.get(f.name))?.[1],f.options[0][1]);
      for(const [value,text] of f.options)option(box,f.name,value,text,()=>extras.get(f.name)||'',v=>{extras.set(f.name,v);});
    }
    update();
    const foot=node('div','discovery-actions');foot.append(button('Clear filters',()=>{clear();dialog.close();},'btn ghost'));
    const apply=node('button','btn primary','Show matches');apply.type='submit';foot.append(apply);
    form.append(sections,foot);form.onsubmit=e=>{e.preventDefault();setFilters(page,draft);extra.forEach(f=>f.apply(extras.get(f.name)));changed();dialog.close();};body.append(form);dialog.append(body);document.body.append(dialog);
    function place(){
      if(innerWidth<760)return;
      const r=anchor.getBoundingClientRect(),width=Math.min(360,innerWidth-32);
      const height=Math.min(640,innerHeight-32,sections.scrollHeight+head.getBoundingClientRect().height+foot.getBoundingClientRect().height);
      const y=innerHeight-r.bottom-16>=height?r.bottom+8:r.top-16>=height?r.top-height-8:Math.max(16,innerHeight-height-16);
      dialog.style.setProperty('--x',`${Math.max(16,Math.min(r.left,innerWidth-width-16))}px`);
      dialog.style.setProperty('--y',`${y}px`);
    }
    dialog.onclick=e=>{if(e.target===dialog)dialog.close();};
    dialog.onclose=()=>{window.removeEventListener('resize',place);window.removeEventListener('scroll',place);dialog.remove();opened=null;anchor.setAttribute('aria-expanded','false');anchor.focus({preventScroll:true});};
    window.addEventListener('resize',place);window.addEventListener('scroll',place,{passive:true});dialog.showModal();opened=dialog;place();anchor.setAttribute('aria-expanded','true');
  }
  paint();return {element:bar,paint,open:sheet,count:()=>count,query:()=>find};
}
