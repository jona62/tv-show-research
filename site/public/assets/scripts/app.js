import {drawMap} from './chart.js';
import {createRadar} from './radar.js';
const boot=JSON.parse(document.getElementById('research-data').textContent);
const $=id=>document.getElementById(id), KEY='tv-taste-profile-v1', clone=x=>JSON.parse(JSON.stringify(x));
for(const key of ['language','type','status']){
  const select=$(key+'-filter');for(const value of ['all',...boot.catalog[key],'unknown']){const option=document.createElement('option');option.value=value;option.textContent=value==='all'?'All '+({language:'languages',type:'formats',status:'statuses'}[key]):value==='unknown'?'Unknown':value;select.append(option);}
}
const year=p=>p.year??'Year unknown';
const radar=createRadar();
for(const view of ['radar','map'])$(view+'-view').addEventListener('click',()=>{
  for(const key of ['radar','map']){$(key+'-panel').hidden=key!==view;$(key+'-view').setAttribute('aria-pressed',String(key===view));}
  draw();
});
const ratingOptions=[[1,'Loved'],[.7,'Liked'],[.35,'Somewhat liked'],[0,'Neutral / just watched'],[-1,'Disliked']];
let state={...clone(boot.defaults),isExample:true}, result=null,selected=null,requestId=0,requestController=null,timer=null,searchId=0,searchController=null,searchTimer=null;
let saved=false,storageAvailable=true;
function element(tag,text='',className=''){const e=document.createElement(tag);e.textContent=text;if(className)e.className=className;return e;}
function button(text,action,className='text-button'){const b=element('button',text,className);b.type='button';b.addEventListener('click',action);return b;}
function status(text,error=false){$('calculation-status').textContent=text;$('calculation-status').classList.toggle('error',error);}
try{
  const stored=JSON.parse(localStorage.getItem(KEY));
  if(stored&&stored.version===1&&Array.isArray(stored.profile)&&stored.profile.length<=50){
    const seen=new Set();
    if(!stored.profile.every(p=>Number.isInteger(p.id)&&!seen.has(p.id)&&seen.add(p.id)&&ratingOptions.some(([w])=>w===p.weight)&&typeof p.name==='string'))throw new Error('Invalid saved profile');
    state={profile:stored.profile,settings:{...(stored.isExample?boot.defaults.settings:personalDefaults()),...stored.settings},isExample:!!stored.isExample};saved=true;
  }
}catch{storageAvailable=false;}
function save(){
  try{localStorage.setItem(KEY,JSON.stringify({version:1,...state}));storageAvailable=true;}catch{storageAvailable=false;}
  $('storage-note').textContent=storageAvailable?'Saved in this browser. Calculations run on the server; no account is required.':'Browser storage is unavailable. Your list works now, but may not survive a reload.';
}
function renderProfile(){
  $('profile-kind').textContent=state.isExample?'The original six favorites are loaded as an example. Start your own list to replace them.':`${state.profile.length}/50 watched shows. Mark at least one as liked to find matches.`;
  const list=$('watched-list');list.replaceChildren();
  if(!state.profile.length)list.append(element('p','Your list is empty. Search for a show above.','small'));
  for(const p of state.profile){
    const row=element('div','','watched-row'),title=element('div',p.name,'watched-name');title.append(element('span',`${year(p)}${p.channel?' · '+p.channel:''}`,'year'));row.append(title);
    const select=element('select');select.setAttribute('aria-label',`Your rating for ${p.name} (${year(p)})`);
    for(const [value,label] of ratingOptions){const option=element('option',label);option.value=value;select.append(option);}select.value=p.weight;
    select.addEventListener('change',()=>{state.profile.find(s=>s.id===p.id).weight=Number(select.value);state.isExample=false;save();$('profile-kind').textContent=`${state.profile.length}/50 watched shows`;schedule();});row.append(select);
    const remove=button('Remove',()=>{state.profile=state.profile.filter(s=>s.id!==p.id);state.isExample=false;renderProfile();save();schedule();});remove.setAttribute('aria-label',`Remove ${p.name} (${year(p)})`);row.append(remove);list.append(row);
  }
}
function renderSettings(){document.querySelectorAll('[data-setting]').forEach(input=>{input.value=state.settings[input.dataset.setting];updateOutput(input);});}
function updateOutput(input){const k=input.dataset.setting,o=$(k+'-value');if(o)o.value=['closest','dislike'].includes(k)?Math.round(Number(input.value)*100)+'%':input.value;}
function personalDefaults(){return {...clone(boot.defaults.settings),year_min:1900,runtime_min:0,language:'all',type:'all',status:'all',axis_y:'all'};}
function addShow(show,weight=.7){
  if(state.profile.some(p=>p.id===show.id))return;
  if(state.profile.length>=50){status('Your list has 50 shows. Remove one before adding another.',true);return;}
  if(weight>0&&!state.profile.some(p=>p.weight>0))state.settings.axis_y=show.id;
  state.profile.push({id:show.id,name:show.name,year:show.year,channel:show.channel,weight});state.isExample=false;
  $('show-search').value='';$('search-results').replaceChildren();$('search-status').textContent=`Added ${show.name}.`;searchId++;searchController?.abort();clearTimeout(searchTimer);
  renderProfile();save();schedule();
}
$('show-search').addEventListener('input',()=>{
  const query=$('show-search').value.trim(),id=++searchId;clearTimeout(searchTimer);searchController?.abort();$('search-results').replaceChildren();
  if(query.length<2){$('search-status').textContent='';return;}$('search-status').textContent='Searching…';
  searchTimer=setTimeout(async()=>{
    searchController=new AbortController();
    try{
      const response=await fetch('/api/search?q='+encodeURIComponent(query),{signal:searchController.signal});if(!response.ok)throw new Error('Search is unavailable. Try again.');
      const data=await response.json();if(id!==searchId)return;
      $('search-status').textContent=data.shows.length?`${data.shows.length} matches. Use the year and channel to choose the right version.`:'No matching shows in this snapshot. Try a shorter title.';
      for(const show of data.shows){
        const li=element('li'),name=element('div',show.name);name.append(element('span',`${year(show)} · ${show.language||'Language unknown'} · ${show.type||'Format unknown'} · ${show.channel||'Channel unknown'}`,'year'));li.append(name);if(show.coverage!=='Plot and genres available')name.append(element('span',show.coverage,'small'));
        const exists=state.profile.some(p=>p.id===show.id),add=button(exists?'Added':'Add',()=>addShow(show),'add-show');add.disabled=exists;add.setAttribute('aria-label',`${exists?'Added':'Add'} ${show.name} (${year(show)})`);li.append(add);$('search-results').append(li);
      }
    }catch(e){if(e.name!=='AbortError'&&id===searchId)$('search-status').textContent=e.message;}
  },220);
});
$('start-list').addEventListener('click',()=>{state={profile:[],settings:personalDefaults(),isExample:false};renderProfile();renderSettings();save();schedule();$('show-search').focus();});
$('example-list').addEventListener('click',()=>{state={...clone(boot.defaults),isExample:true};renderProfile();renderSettings();save();schedule();});
$('reset-settings').addEventListener('click',()=>{state.settings=state.isExample?clone(boot.defaults.settings):personalDefaults();renderSettings();save();schedule();});
document.querySelectorAll('[data-setting]').forEach(input=>input.addEventListener('input',()=>{state.settings[input.dataset.setting]=input.tagName==='SELECT'?input.value:Number(input.value);updateOutput(input);save();schedule();}));
for(const axis of ['x','y'])$('axis-'+axis).addEventListener('change',()=>{const v=$('axis-'+axis).value;state.settings['axis_'+axis]=v==='all'?'all':Number(v);save();schedule();});
$('retry').addEventListener('click',()=>schedule(0));
function schedule(delay=180){
  const id=++requestId;clearTimeout(timer);requestController?.abort();$('retry').hidden=true;
  $('results').dataset.updating='true';$('results').inert=true;$('results').setAttribute('aria-busy','true');status('Recalculating your recommendations and charts…');timer=setTimeout(()=>calculate(id),delay);
}
async function calculate(id){
  if([...document.querySelectorAll('[data-setting]')].some(input=>input.value===''||!input.checkValidity())){status('Complete the settings using values within the shown limits.',true);$('results').hidden=true;return;}
  requestController=new AbortController();
  try{
    const response=await fetch('/api/recommend',{method:'POST',headers:{'Content-Type':'application/json'},signal:requestController.signal,body:JSON.stringify({profile:state.profile.map(({id,weight})=>({id,weight})),settings:state.settings})});
    const data=await response.json();if(id!==requestId)return;if(!response.ok)throw new Error(data.error||'Could not calculate recommendations.');
    state.settings=data.settings;state.profile=data.profile;save();renderSettings();renderResults(data);
  }catch(e){if(e.name==='AbortError'||id!==requestId)return;status(e.message||'Could not reach the recommender.',true);$('retry').hidden=false;$('results').hidden=true;}
}
function renderResults(data){
  result=data;$('results').dataset.updating='false';$('results').inert=false;$('results').setAttribute('aria-busy','false');$('results').hidden=data.positive_count===0;
  status(data.message||`Updated for ${data.positive_count} liked shows, ${data.negative_count} dislikes, and ${data.candidate_count.toLocaleString()} eligible unwatched shows.`);if(!data.positive_count)return;
  $('coverage-warning').hidden=!data.warnings.length;$('coverage-warning').textContent=data.warnings.join(' ');
  $('result-count').textContent=`${data.catalog_count.toLocaleString()} shows in the snapshot · ${data.candidate_count.toLocaleString()} eligible · ${data.positive_count} liked`;
  for(const key of ['x','y']){
    const select=$('axis-'+key);select.replaceChildren();const all=element('option','All liked shows');all.value='all';select.append(all);
    for(const p of data.profile.filter(p=>p.weight>0)){const option=element('option',`${p.name} (${year(p)})`);option.value=p.id;select.append(option);}select.value=data.settings['axis_'+key];
  }
  $('axis-note').textContent=data.settings.axis_x===data.settings.axis_y?'Both axes use the same comparison. Choose a different liked show on one axis to explore contrasts.':`Horizontal: ${data.axes.x}. Vertical: ${data.axes.y}.`;
  const showSelect=$('show-select');showSelect.replaceChildren();
  for(const p of [...data.points].sort((a,b)=>(a.rank??99999)-(b.rank??99999))){const option=element('option',`${p.name} (${year(p)})${p.seed?' · liked':''}`);option.value=p.id;showSelect.append(option);}
  if(!data.points.some(p=>p.id===selected))selected=data.recommendations[0]?.id??data.points[0]?.id;
  inspect(selected);renderFeatures(data);renderRanking(data);renderPairs(data);renderCorrelations(data);
}
function inspect(id){
  selected=Number(id);$('show-select').value=selected;const p=result?.points.find(p=>p.id===selected);if(!p)return;
  radar.update(result,p);
  const detail=$('show-detail');detail.replaceChildren();detail.append(element('h3',`${p.name} (${year(p)})`),element('p',`${p.genres.join(' / ')||'No genre tags'} · ${p.runtime??'Unknown'} min · TVmaze ${p.rating??'unrated'}/10`,'small'));
  detail.append(element('p',[p.language||'Language unknown',p.type||'Format unknown',p.status,p.country?'Network country: '+p.country:null].filter(Boolean).join(' · '),'small'));
  if(p.summary)detail.append(element('p',p.summary));
  if(p.detected_themes.length)detail.append(element('p','This show’s theme signals: '+p.detected_themes.join('; ')+'.','small'));
  if(p.keywords.length)detail.append(element('p','Distinctive plot terms: '+p.keywords.join(' · ')+'.','small'));
  if(p.coverage!=='Plot and genres available')detail.append(element('p',p.coverage+'. Missing features contribute zero similarity.','small'));
  detail.append(element('p',p.seed?'A liked show. Its position includes self-similarity.':`Closest like: ${p.nearest}. Similarity ${p.score.toFixed(1)}/100; rank ${p.rank}.`),element('p',`Shared summary evidence: ${p.shared.join('; ')||'no matching theme words'}.`));
  if(p.dislike_penalty>0)detail.append(element('p',`Dislike adjustment: −${p.dislike_penalty.toFixed(1)} points.`,'small'));
  const link=element('a','Read about the show');link.href=p.url;link.target='_blank';link.rel='noopener noreferrer';detail.append(link);draw();
}
$('show-select').addEventListener('change',()=>inspect($('show-select').value));
function draw(){if(result&&!$('results').hidden&&!$('map-panel').hidden)drawMap($('taste-map'),$('map-frame'),$('map-tooltip'),result.points,selected,inspect,result.axes);}
let mapWidth=0;new ResizeObserver(()=>{const w=$('map-frame').clientWidth;if(w!==mapWidth){mapWidth=w;draw();}}).observe($('map-frame'));
$('feature-group').addEventListener('change',()=>{if(result)renderFeatures(result);});
function renderFeatures(data){
  const group=$('feature-group').value;
  const features=data.features.filter(f=>f.liked_count>0&&(group==='content'?['themes','genres'].includes(f.group):f.group===group)).slice(0,12),bars=$('feature-bars');bars.replaceChildren();
  const first=features[0];$('feature-summary').textContent=first?`${first.feature.replace('Genre: ','')} appears in ${first.liked_count} of your ${data.positive_count} liked shows, versus ${first.baseline_pct.toFixed(1)}% of eligible unwatched shows.`:'No recorded features in this category for your liked shows. Missing values are not inferred.';
  for(const f of features){
    const row=element('div','','feature-row');row.append(element('span',f.feature.replace('Genre: ',''),'feature-name'));
    const tracks=element('div','','bars');tracks.setAttribute('role','img');tracks.setAttribute('aria-label',`${f.liked_count} of ${data.positive_count} likes; ${f.baseline_pct.toFixed(1)} percent of eligible unwatched shows`);
    for(const [value,cls] of [[f.liked_pct,'bar'],[f.baseline_pct,'bar baseline']]){const mark=element('span','',cls);mark.style.setProperty('--width',value+'%');tracks.append(mark);}
    row.append(tracks,element('span',`${f.liked_count}/${data.positive_count}`,'feature-count'));bars.append(row);
  }
}
function renderRanking(data){
  const tbody=$('ranking-body');tbody.replaceChildren();$('empty-candidates').hidden=data.recommendations.length>0;$('empty-candidates').textContent=data.message;
  for(const p of data.recommendations){
    const tr=element('tr'),title=element('td');title.append(button(p.name,()=>{inspect(p.id);$('explore').scrollIntoView();},'show-link'),element('span',String(year(p)),'year'));
    const watched=element('td'),action=button('Watched',()=>addShow(p,0));action.setAttribute('aria-label',`Mark ${p.name} (${year(p)}) as watched`);watched.append(action);tr.append(title,element('td',p.score.toFixed(1),'num'),element('td',p.nearest),watched);tbody.append(tr);
  }$('download-results').disabled=!data.recommendations.length;
}
function renderPairs(data){
  const holder=$('pair-matrix');holder.replaceChildren();$('pair-note').textContent=`${data.positive_count>12?'First 12 of '+data.positive_count:data.positive_count} liked shows in list order. Match row and column numbers to the titles below.`;
  const table=element('table','','pair-table'),thead=element('thead'),tr=element('tr');tr.append(element('th','Show'));
  data.pair_labels.forEach((name,i)=>{const th=element('th',String(i+1));th.scope='col';th.title=name;tr.append(th);});thead.append(tr);table.append(thead);
  const tbody=element('tbody');data.pairs.forEach((values,i)=>{const row=element('tr'),th=element('th',String(i+1));th.scope='row';th.title=data.pair_labels[i];row.append(th);values.forEach((v,j)=>{const td=element('td',String(Math.round(v)));td.style.setProperty('--intensity',v*.25+'%');td.title=`${data.pair_labels[i]} / ${data.pair_labels[j]}: ${v.toFixed(1)}`;row.append(td);});tbody.append(row);});table.append(tbody);holder.append(table);
  const labels=element('ol','','pair-key');data.pair_labels.forEach(name=>labels.append(element('li',name)));holder.append(labels);
}
function renderCorrelations(data){
  const holder=$('catalog-correlations');holder.replaceChildren();if(!data.correlations.length){holder.append(element('p','Too few varying features to calculate correlations.','small'));return;}
  const table=element('table'),head=element('thead'),tr=element('tr');['Feature pair','Pearson / phi r'].forEach(t=>tr.append(element('th',t)));head.append(tr);table.append(head);
  const body=element('tbody');for(const p of data.correlations){const row=element('tr');row.append(element('td',`${p.a} / ${p.b}`),element('td',p.r.toFixed(2),'num'));body.append(row);}table.append(body);holder.append(table,element('p',`Five strongest absolute associations across ${data.candidate_count.toLocaleString()} eligible unwatched shows. Descriptive, not causal.`,'small'));
}
$('download-results').addEventListener('click',()=>{
  if(!result)return;
  const quote=v=>'"'+String(v??'').replace(/^[=+@\-\t\r]/,"'"+'$&').replaceAll('"','""')+'"';
  const rows=[['Title','Year','Language','Format','Status','Data coverage','Genres','Detected themes','Distinctive plot terms','Summary excerpt','Similarity','Closest liked show','Dislike penalty','TVmaze URL'],...result.recommendations.map(p=>[p.name,p.year,p.language,p.type,p.status,p.coverage,p.genres.join('; '),p.detected_themes.join('; '),p.keywords.join('; '),p.summary,p.score,p.nearest,p.dislike_penalty,p.url])];
  const blob=new Blob([rows.map(row=>row.map(quote).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='tv-recommendations.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
renderProfile();renderSettings();if(saved)schedule(0);else renderResults(boot.initial);
if(!storageAvailable)$('storage-note').textContent='Could not read a saved list. The example is shown; changes will try to save again.';
