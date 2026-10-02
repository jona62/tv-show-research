import {esc,score,code,average,band} from './ratings.js';

const AXIS_WIDTH=46, EPISODE_SPACE=1, SEASON_SPACE=72;
const RAW={top:36,bottom:244}, TREND={top:338,bottom:426};
const ordinate=(value,low,row)=>row.bottom-(value-low)*(row.bottom-row.top)/(10-low);
const tickLabel=value=>value.toFixed(Number.isInteger(value*2)?1:2);

function scale(points) {
  const rated=points.filter(p=>p.rating!=null);
  // Leave a little space below the lowest displayed score without hiding low ratings.
  const low=Math.max(0,Math.min(9,Math.floor((Math.min(...rated.map(p=>p.rating))-.25)*4)/4));
  const ticks=[low];
  for(let value=Math.ceil(low*2)/2;value<=10;value+=.5)if(value!==low)ticks.push(value);
  return {low,ticks};
}

function continuousRuns(points) {
  const rated=points.filter(point=>point.rating!=null);
  return rated.length?[rated]:[];
}

// Windows retain season and number/null boundaries, even though the visible
// lines connect the actual samples on each side of those boundaries.
function averagingRuns(points) {
  const runs=[];
  let run=[];
  for(const point of points){
    const previous=run.at(-1);
    const follows=previous&&point.season===previous.season&&point.number===previous.number+1;
    if(point.rating==null||previous&&!follows){if(run.length)runs.push(run);run=[];}
    if(point.rating!=null)run.push(point);
  }
  if(run.length)runs.push(run);
  return runs;
}

// Keep the overview compact; very long shows gain just enough width to scroll.
export function timelineModel(episodes,other=null,availableWidth=780) {
  const comparison=Boolean(other);
  const seasonNumbers=[...new Set([...episodes,...(other||[])].map(e=>e.season))].sort((a,b)=>a-b);
  const samples=list=>comparison?seasonNumbers.map(season=>({season,
    rating:average(list.filter(e=>e.season===season)),label:`S${season}`})):
    list.map(e=>({...e,label:code(e)}));
  const lists=[samples(episodes),...(comparison?[samples(other)]:[])];
  if(!lists.flat().some(p=>p.rating!=null))return null;
  const {low,ticks}=scale(lists.flat()),count=lists[0].length;
  const viewport=Math.max(96,Math.floor(availableWidth)-AXIS_WIDTH);
  const width=Math.max(viewport,(count-1)*(comparison?SEASON_SPACE:EPISODE_SPACE)+64);
  const spacing=(width-64)/Math.max(1,count-1);
  const series=lists.map(points=>{
    points=points.map((p,i)=>({...p,x:count===1?width/2:20+i*(width-64)/(count-1),
      y:p.rating==null?null:ordinate(p.rating,low,RAW)}));
    // Nulls keep their positions but receive neither dots nor invented scores.
    const runs=continuousRuns(points);
    const trendRuns=comparison?[]:averagingRuns(points);
    const trendPoints=trendRuns.flatMap(run=>run.map((p,i)=>{
      const rating=average(run.slice(Math.max(0,i-2),i+3));
      return {...p,rating,y:ordinate(rating,low,TREND)};
    }));
    const trend=continuousRuns(trendPoints);
    return {points,runs,trendRuns,trendPoints,trend};
  });
  return {comparison,low,ticks,count,width,spacing,viewport,height:comparison?300:444,series};
}

// Dense ratings can overlap visually. Select the nearest actual sample, not the
// last hit circle painted, and leave empty areas of the chart unselected.
export function nearestRatingPoint(points,x,y,radius=12) {
  let left=0,right=points.length;
  while(left<right){const mid=(left+right)>>1;if(points[mid].x<x-radius)left=mid+1;else right=mid;}
  let nearest=null,distance=radius*radius;
  for(let i=left;i<points.length&&points[i].x<=x+radius;i++){
    const point=points[i];if(point.y==null)continue;
    const squared=(point.x-x)**2+(point.y-y)**2;
    if(squared<=distance&&(!nearest||squared<distance)){nearest=point;distance=squared;}
  }
  return nearest;
}

// Bound the cubic controls to their neighbouring samples so curves never invent peaks.
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

function rowAxis(model,row) {
  // Keep fractional lower bounds exact, and avoid colliding labels on the shorter trend row.
  const values=model.ticks.filter((v,i,all)=>i===0||i===all.length-1||
    Math.abs(ordinate(v,model.low,row)-ordinate(model.low,model.low,row))>=18&&
    Math.abs(ordinate(v,model.low,row)-ordinate(10,model.low,row))>=18);
  let previous=Infinity;
  return values.map(value=>{
    const y=ordinate(value,model.low,row);
    if(previous-y<18&&value!==10)return '';
    previous=y;
    return `<text class="ratings-tick" x="40" y="${y+4}" text-anchor="end">${tickLabel(value)}</text>`;
  }).join('');
}

function rowGrid(model,row) {
  return model.ticks.map(value=>`<line x1="0" y1="${ordinate(value,model.low,row)}" x2="${model.width}" y2="${ordinate(value,model.low,row)}"/>`).join('');
}

function seriesMarkup(series,model,colour,index,names) {
  const line=series.runs.map(smoothPath).join(' ');
  return `<path class="ratings-raw-line" d="${line}" fill="none" stroke="${model.comparison?colour:'var(--muted)'}" stroke-width="${model.comparison?2:1.25}"/>`+
    series.points.map(p=>p.rating==null?'':`<g class="ratings-point-hit" ${model.comparison?`data-season="${p.season}" data-show-index="${index}"`:`data-episode="${p.id}"`} tabindex="0" role="${model.comparison?'img':'button'}" aria-label="${model.comparison?esc(names[index]||'Show')+', ':''}${p.label}${p.name?': '+esc(p.name):''}, ${score(p.rating)} out of 10, ${band(p.rating).name}"><circle class="ratings-point-target" cx="${p.x}" cy="${p.y}" r="12" fill="transparent"/><circle class="ratings-point" cx="${p.x}" cy="${p.y}" r="${model.comparison?4.5:Math.max(1.75,Math.min(4,model.spacing*.45))}" fill="${model.comparison?colour:band(p.rating).colour}"/></g>`).join('');
}

// Coordinates stay in CSS pixels: a long chart scrolls instead of shrinking its
// labels. Season starts keep their real positions even when text cannot fit.
export function timelineAxis(model) {
  const points=model.series[0].points,seasonTicks=[],episodeTicks=[],labels=[];
  for(const [i,p] of points.entries()){
    if(model.comparison||i===0||p.season!==points[i-1].season)
      seasonTicks.push({x:p.x,season:p.season,number:p.number});
  }
  const bands=seasonTicks.map((p,i)=>({season:p.season,start:p.x,
    end:seasonTicks[i+1]?.x??points.at(-1).x}));
  let seasonIndex=0,lastTick=-Infinity;
  if(!model.comparison)for(const p of points){
    if(p.x===seasonTicks[seasonIndex].x){lastTick=p.x;continue;}
    const nextSeason=seasonTicks[seasonIndex+1];
    if(nextSeason&&p.x>=nextSeason.x){seasonIndex++;lastTick=p.x;continue;}
    if(p.x-lastTick<8||nextSeason&&nextSeason.x-p.x<4)continue;
    episodeTicks.push({x:p.x,season:p.season,number:p.number});lastTick=p.x;
  }
  const labelY=268;
  const addLabel=(p,kind)=>{
    const text=kind==='season'?'S'+p.season:'E'+p.number;
    // A conservative width at the chart's 12px type leaves a readable gutter.
    const size=text.length*8,left=kind==='season'?p.x:p.x-size/2,right=left+size;
    if(left<4||right>model.width-4||labels.some(label=>left<label.right+8&&right>label.left-8))return;
    labels.push({kind,text,x:p.x,y:labelY,anchor:kind==='season'?'start':'middle',left,right});
  };
  seasonTicks.forEach(p=>addLabel(p,'season'));
  episodeTicks.forEach(p=>addLabel(p,'episode'));
  labels.sort((a,b)=>a.x-b.x);
  return {baseline:RAW.bottom,labelY,bands,seasonTicks,episodeTicks,labels};
}

function axisMarkup(axis,model) {
  const guide=p=>`x1="${p.x}" x2="${p.x}" y1="${RAW.top}" y2="${axis.baseline}"`;
  const tick=(p,size)=>`x1="${p.x}" x2="${p.x}" y1="${axis.baseline}" y2="${axis.baseline+size}"`;
  return `<g class="ratings-x-axis" aria-hidden="true" pointer-events="none">
    <g class="ratings-season-guides">${axis.seasonTicks.map(p=>`<line class="ratings-season-guide" ${guide(p)}/>`).join('')}</g>
    <g class="ratings-episode-guides">${axis.episodeTicks.map(p=>`<line class="ratings-episode-guide" ${guide(p)}/>`).join('')}</g>
    <line class="ratings-x-baseline" x1="0" x2="${model.width}" y1="${axis.baseline}" y2="${axis.baseline}"/>
    ${axis.seasonTicks.map(p=>`<line class="ratings-season-tick" ${tick(p,8)}/>`).join('')}
    ${axis.episodeTicks.map(p=>`<line class="ratings-episode-tick" ${tick(p,4)}/>`).join('')}
    ${axis.labels.map(p=>`<text class="ratings-${p.kind}-label" x="${p.x}" y="${p.y}" text-anchor="${p.anchor}">${p.text}</text>`).join('')}
  </g>`;
}

export function chart(episodes,other=null,names=[],availableWidth=780) {
  const model=timelineModel(episodes,other,availableWidth);
  if(!model)return '<p class="ratings-empty">These episodes have not been rated yet.</p>';
  const {comparison,low,width,height,series}=model;
  const axis=timelineAxis(model);
  const trend=series[0].trend.map(run=>`<path class="ratings-trend" d="${smoothPath(run)}"/>`+
    (run.length===1?`<circle class="ratings-trend-single" cx="${run[0].x}" cy="${run[0].y}" r="3"/>`:'')).join('');
  const scrolls=width>model.viewport;
  return `<div class="ratings-chart-frame${comparison?' ratings-chart-frame-comparison':''}">
    <p class="ratings-chart-label">${comparison?'Season averages':'Episode ratings'}</p>
    ${comparison?'':'<p class="ratings-chart-label ratings-chart-label-trend">5-episode average <span>Within each season</span></p>'}
    <svg class="ratings-chart-axis" width="46" height="${height}" viewBox="0 0 46 ${height}" aria-hidden="true">${rowAxis(model,RAW)}${comparison?'':rowAxis(model,TREND)}</svg>
    <div class="ratings-chart-wrap" tabindex="0" role="region" aria-label="${comparison?'Season averages':'Episode ratings'} timeline${scrolls?'; scroll horizontally to explore':''}">
      <svg class="ratings-timeline" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="${comparison?'Season averages':'Episode ratings'}, scale ${low} to 10${comparison?'':', with a separate five-episode average below'}" data-min="${low}" style="--ratings-point-stroke:${comparison||model.spacing>=6?1.5:.65}">
        <g class="ratings-season-bands" aria-hidden="true" pointer-events="none">${axis.bands.filter((p,i)=>i%2===1).map(p=>`<rect class="ratings-season-band" x="${p.start}" y="${RAW.top}" width="${p.end-p.start}" height="${RAW.bottom-RAW.top}"/>`).join('')}</g>
        <g class="ratings-chart-grid">${rowGrid(model,RAW)}${comparison?'':rowGrid(model,TREND)}</g>
        <g class="ratings-episode-plot">${seriesMarkup(series[0],model,'#ffb020',0,names)}${comparison?seriesMarkup(series[1],model,'#91b9dc',1,names):''}</g>
        ${axisMarkup(axis,model)}${comparison?'':`<g class="ratings-trend-plot" aria-hidden="true">${trend}</g>`}
      </svg>
    </div>
  </div>${scrolls?`<p class="ratings-scroll-hint">Scroll to explore all ${model.count.toLocaleString('en-US')} ${comparison?'seasons':'episodes'}</p>`:''}`;
}
