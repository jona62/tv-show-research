const NS='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id);
function el(tag,text='',cls=''){const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;}
function svgNode(tag,attrs={},text=''){const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);n.textContent=text;return n;}
const title=p=>`${p.name} (${p.year??'Year unknown'})`;
export function featureValue(show,feature){
  if(feature.group==='themes')return show.summary?(show.detected_themes.includes(feature.feature)?100:0):null;
  return show.genres.length?(show.genres.includes(feature.feature.replace('Genre: ',''))?100:0):null;
}
export function radarRows(result,selected,comparison){
  const liked=result.profile.filter(p=>p.weight>0),points=new Map(result.points.map(p=>[p.id,p]));
  const total=liked.reduce((n,p)=>n+p.weight,0);
  return result.features.filter(f=>['themes','genres'].includes(f.group)).map(f=>{
    let sum=0,known=0;
    for(const p of liked){const point=points.get(p.id),v=point?featureValue(point,f):null;if(v!==null){sum+=p.weight*v;known+=p.weight;}}
    return {...f,a:featureValue(selected,f),b:comparison?featureValue(comparison,f):null,
      profile:known?sum/total:null,coverage:total?known/total*100:0};
  });
}
export function createRadar(){
  let result,selected,comparison,rows=[],dimensions=[],custom=false,width=0;
  const compare=$('radar-compare'),preset=$('radar-preset');
  function chooseComparison(){
    const matches=result.points.filter(p=>p.id!==selected.id);
    comparison=compare.value==='closest'?
      matches.find(p=>p.id===selected.nearest_other_id):matches.find(p=>p.id===Number(compare.value));
  }
  function options(){
    const old=compare.value;compare.replaceChildren();
    const auto=el('option','Closest liked show');auto.value='closest';compare.append(auto);
    for(const point of [...result.points].sort((a,b)=>Number(b.seed)-Number(a.seed)||(a.rank??999)-(b.rank??999))){
      if(point.id===selected.id)continue;
      const opt=el('option',title(point)+(point.seed?' · liked':''));opt.value=point.id;compare.append(opt);
    }
    compare.value=[...compare.options].some(o=>o.value===old)?old:'closest';
  }
  function pool(){return rows.filter(f=>preset.value==='mixed'||f.group===preset.value);}
  function suggest(){
    return [...pool()].sort((a,b)=>{
      const priority=f=>(f.a===100&&f.b===100?3:0)+(f.a===100||f.b===100?1:0)+(f.profile??0)/100;
      return priority(b)-priority(a)||a.feature.localeCompare(b.feature);
    }).slice(0,8).map(f=>f.feature);
  }
  function choices(){
    const holder=$('radar-dimensions');holder.replaceChildren();
    for(const group of ['themes','genres']){
      const fields=pool().filter(f=>f.group===group).sort((a,b)=>a.feature.localeCompare(b.feature));if(!fields.length)continue;
      const set=el('fieldset'),legend=el('legend',group==='themes'?'Theme signals':'Genre tags');set.append(legend);
      for(const f of fields){
        const label=el('label'),input=el('input');input.type='checkbox';input.value=f.feature;input.checked=dimensions.includes(f.feature);
        input.addEventListener('change',()=>{
          const n=dimensions.length+(input.checked?1:-1);
          if(n<3||n>12){input.checked=!input.checked;$('radar-dimension-status').textContent='Choose between 3 and 12 dimensions.';return;}
          custom=true;dimensions=input.checked?[...dimensions,f.feature]:dimensions.filter(d=>d!==f.feature);
          $('radar-dimension-status').textContent='Custom dimensions stay fixed as you compare shows.';render();
        });label.append(input,document.createTextNode(f.feature.replace('Genre: ','')));set.append(label);
      }holder.append(set);
    }
  }
  function recalculate(){
    chooseComparison();rows=radarRows(result,selected,comparison);
    if(!custom)dimensions=suggest();
    dimensions=dimensions.filter(d=>rows.some(f=>f.feature===d));
    if(dimensions.length<3){custom=false;dimensions=suggest();}
    choices();render();
  }
  function series(){return [
    {name:'Your liked-show profile',cls:'radar-profile',key:'profile'},
    ...(comparison?[{name:title(comparison),cls:'radar-comparison',key:'b'}]:[]),
    {name:title(selected),cls:'radar-selected',key:'a'}
  ];}
  function render(){
    const active=dimensions.map(d=>rows.find(f=>f.feature===d));
    $('radar-dimension-count').textContent=`(${dimensions.length} of ${pool().length})`;
    const legend=$('radar-legend');legend.replaceChildren();for(const s of series()){const item=el('span',s.name,s.cls);item.prepend(el('i'));legend.append(item);}
    const common=rows.filter(f=>f.a===100&&f.b===100).map(f=>f.feature.replace('Genre: ',''));
    $('radar-summary').textContent=comparison?`${selected.name} and ${comparison.name} share ${common.length} recorded theme/genre signals${common.length?': '+common.slice(0,8).join('; ')+(common.length>8?'; and '+(common.length-8)+' more':''):''}.`:'Add another liked show to compare individual shows. Your liked-show profile is still shown.';
    draw(active);table();
  }
  function table(){
    $('radar-table-summary').textContent=`Read all ${rows.length} dimensions and exact values`;
    const container=$('radar-table');container.replaceChildren();const table=el('table'),head=el('thead'),tr=el('tr');
    for(const name of ['Dimension',title(selected),comparison?title(comparison):'No comparison','Your likes (weighted)']){const th=el('th',name);th.scope='col';tr.append(th);}head.append(tr);table.append(head);
    const body=el('tbody');
    for(const f of [...rows].sort((a,b)=>dimensions.indexOf(a.feature)<0&&dimensions.indexOf(b.feature)>=0?1:dimensions.indexOf(a.feature)>=0&&dimensions.indexOf(b.feature)<0?-1:a.feature.localeCompare(b.feature))){
      const row=el('tr','',dimensions.includes(f.feature)?'on-radar':'');row.dataset.feature=f.feature;
      const th=el('th',f.feature+(dimensions.includes(f.feature)?' · plotted':''));th.scope='row';row.append(th);
      for(const v of [f.a,f.b])row.append(el('td',v===null?'Unknown':v===100?'100 · present':'0 · no signal'));
      const value=el('td',f.profile===null?'Unknown':f.profile.toFixed(1)+'%');
      if(f.coverage<100)value.append(el('span',`${f.coverage.toFixed(1)}% data coverage`,'year'));row.append(value);body.append(row);
    }table.append(body);container.append(table);
  }
  function draw(active){
    const svg=$('taste-radar'),frame=$('radar-frame'),w=frame.clientWidth;if(!w)return;
    const compact=w<520,h=compact?340:470,cx=w/2,cy=h/2,r=compact?Math.min(w/2-34,130):155;
    svg.replaceChildren();svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.setAttribute('height',h);
    svg.append(svgNode('title',{},`${active.length}-dimension feature radar. ${series().map(s=>s.name).join(', ')}. Exact values are in the table below.`));
    const xy=(i,v,extra=0)=>{const angle=i/active.length*Math.PI*2-Math.PI/2;return [cx+Math.cos(angle)*(r*v/100+extra),cy+Math.sin(angle)*(r*v/100+extra)];};
    const polygon=value=>active.map((f,i)=>xy(i,value).join(',')).join(' ');
    for(const v of [25,50,75,100])svg.append(svgNode('polygon',{points:polygon(v),class:'radar-grid'}));
    active.forEach((f,i)=>{const [x,y]=xy(i,100);svg.append(svgNode('line',{x1:cx,y1:cy,x2:x,y2:y,class:'radar-grid'}));});
    for(const v of [0,50,100])svg.append(svgNode('text',{x:cx+5,y:cy-r*v/100-5,class:'radar-scale'},String(v)));
    for(const s of series()){
      const path=svgNode('polygon',{points:active.map((f,i)=>xy(i,f[s.key]??0).join(',')).join(' '),class:s.cls+' radar-shape'});svg.append(path);
      active.forEach((f,i)=>{
        const v=f[s.key],[x,y]=xy(i,v??0),attrs={class:s.cls+' radar-dot'+(v===null?' unknown':''),tabindex:0,'aria-label':`${s.name}, ${f.feature}: ${v===null?'unknown':v.toFixed(1)+' percent'}`};
        const marker=s.key==='a'?svgNode('circle',{...attrs,cx:x,cy:y,r:4}):s.key==='b'?svgNode('rect',{...attrs,x:x-3.5,y:y-3.5,width:7,height:7}):svgNode('path',{...attrs,d:`M${x},${y-5}l4.5,8h-9Z`});
        marker.append(svgNode('title',{},attrs['aria-label']));svg.append(marker);
      });
    }
    const key=$('radar-key');key.replaceChildren();key.hidden=!compact;
    active.forEach((f,i)=>{
      const [x,y]=xy(i,100,compact?18:25),name=f.feature.replace('Genre: ','');
      if(compact){svg.append(svgNode('text',{x,y:y+4,'text-anchor':'middle',class:'radar-label'},String(i+1)));key.append(el('li',name));return;}
      const anchor=x<cx-30?'end':x>cx+30?'start':'middle';const label=svgNode('text',{x,y,'text-anchor':anchor,class:'radar-label'});
      const words=name.split(' ');let lines=[''];for(const word of words){if((lines.at(-1)+' '+word).trim().length>19&&lines.at(-1))lines.push(word);else lines[lines.length-1]=(lines.at(-1)+' '+word).trim();}
      lines.forEach((line,j)=>label.append(svgNode('tspan',{x,dy:j?15:-(lines.length-1)*7},line)));svg.append(label);
    });
  }
  compare.addEventListener('change',()=>recalculate());
  preset.addEventListener('change',()=>{custom=false;$('radar-dimension-status').textContent='Suggested dimensions update with the selected shows.';recalculate();});
  $('radar-suggest').addEventListener('click',()=>{custom=false;$('radar-dimension-status').textContent='Suggested dimensions update with the selected shows.';recalculate();});
  new ResizeObserver(()=>{const w=$('radar-frame').clientWidth;if(w!==width){width=w;if(rows.length)draw(dimensions.map(d=>rows.find(f=>f.feature===d)));}}).observe($('radar-frame'));
  return {update(data,point){result=data;selected=point;options();recalculate();}};
}
