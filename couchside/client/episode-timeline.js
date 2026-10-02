import {esc,score,code,average,band} from './ratings.js';

const AXIS_WIDTH=46, EPISODE_SPACE=28, SEASON_SPACE=72;
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

function ratedRuns(points,comparison) {
  const runs=[];
  let run=[];
  for(const point of points){
    const previous=run.at(-1);
    const follows=previous&&(comparison?point.season===previous.season+1:
      point.season===previous.season&&point.number===previous.number+1);
    if(point.rating==null||previous&&!follows){if(run.length)runs.push(run);run=[];}
    if(point.rating!=null)run.push(point);
  }
  if(run.length)runs.push(run);
  return runs;
}

// The geometry is in CSS pixels: long shows grow sideways instead of shrinking their dots.
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
  const series=lists.map(points=>{
    points=points.map((p,i)=>({...p,x:count===1?width/2:20+i*(width-64)/(count-1),
      y:p.rating==null?null:ordinate(p.rating,low,RAW)}));
    const runs=ratedRuns(points,comparison);
    const trend=comparison?[]:runs.map(run=>run.map((p,i)=>({...p,
      rating:average(run.slice(Math.max(0,i-2),i+3)),
      y:ordinate(average(run.slice(Math.max(0,i-2),i+3)),low,TREND)})));
    return {points,runs,trend};
  });
  return {comparison,low,ticks,count,width,viewport,height:comparison?300:444,series};
}

// Bound the cubic controls to their neighbouring samples so a trend never invents peaks.
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
  const line=series.runs.map(run=>run.map((p,i)=>`${i?'L':'M'}${p.x},${p.y}`).join(' ')).join(' ');
  return `<path class="ratings-raw-line" d="${line}" fill="none" stroke="${model.comparison?colour:'var(--muted)'}" stroke-width="${model.comparison?2:1.25}"/>`+
    series.points.map(p=>p.rating==null?'':`<g class="ratings-point-hit" ${model.comparison?`data-season="${p.season}" data-show-index="${index}"`:`data-episode="${p.id}"`} tabindex="0" role="${model.comparison?'img':'button'}" aria-label="${model.comparison?esc(names[index]||'Show')+', ':''}${p.label}${p.name?': '+esc(p.name):''}, ${score(p.rating)} out of 10, ${band(p.rating).name}"><circle class="ratings-point-target" cx="${p.x}" cy="${p.y}" r="12" fill="transparent"/><circle class="ratings-point" cx="${p.x}" cy="${p.y}" r="${model.comparison?4.5:4}" fill="${model.comparison?colour:band(p.rating).colour}"/></g>`).join('');
}

function seasonLabels(model) {
  const starts=model.series[0].points.filter((p,i,points)=>model.comparison||i===0||p.season!==points[i-1].season);
  let previous=-Infinity,row=0;
  return starts.map(p=>{
    row=p.x-previous<64?1-row:0;previous=p.x;
    return `<text class="ratings-season-label" x="${p.x}" y="${270+row*16}" text-anchor="start">S${p.season}</text>`;
  }).join('');
}

function episodeLabels(model) {
  if(model.comparison)return '';
  let seasonStart=-Infinity,season;
  return model.series[0].points.map(p=>{
    if(p.season!==season){season=p.season;seasonStart=p.x;}
    if(p.x-seasonStart<56||model.count>24&&p.number%5!==0)return '';
    return `<text class="ratings-episode-label" x="${p.x}" y="286" text-anchor="middle">E${p.number}</text>`;
  }).join('');
}

export function chart(episodes,other=null,names=[],availableWidth=780) {
  const model=timelineModel(episodes,other,availableWidth);
  if(!model)return '<p class="ratings-empty">These episodes have not been rated yet.</p>';
  const {comparison,low,width,height,series}=model;
  const trend=series[0].trend.map(run=>`<path class="ratings-trend" d="${smoothPath(run)}"/>`+
    (run.length===1?`<circle class="ratings-trend-single" cx="${run[0].x}" cy="${run[0].y}" r="3"/>`:'')).join('');
  const scrolls=width>model.viewport;
  return `<div class="ratings-chart-frame${comparison?' ratings-chart-frame-comparison':''}">
    <p class="ratings-chart-label">${comparison?'Season averages':'Episode ratings'}</p>
    ${comparison?'':'<p class="ratings-chart-label ratings-chart-label-trend">5-episode average <span>Within each season</span></p>'}
    <svg class="ratings-chart-axis" width="46" height="${height}" viewBox="0 0 46 ${height}" aria-hidden="true">${rowAxis(model,RAW)}${comparison?'':rowAxis(model,TREND)}</svg>
    <div class="ratings-chart-wrap" tabindex="0" role="region" aria-label="${comparison?'Season averages':'Episode ratings'} timeline${scrolls?'; scroll horizontally to explore':''}">
      <svg class="ratings-timeline" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="${comparison?'Season averages':'Episode ratings'}, scale ${low} to 10${comparison?'':', with a separate five-episode average below'}" data-min="${low}">
        <g class="ratings-chart-grid">${rowGrid(model,RAW)}${comparison?'':rowGrid(model,TREND)}</g>
        <g class="ratings-episode-plot">${seriesMarkup(series[0],model,'#ffb020',0,names)}${comparison?seriesMarkup(series[1],model,'#91b9dc',1,names):''}</g>
        ${seasonLabels(model)}${episodeLabels(model)}${comparison?'':`<g class="ratings-trend-plot" aria-hidden="true">${trend}</g>`}
      </svg>
    </div>
  </div>${scrolls?`<p class="ratings-scroll-hint">Scroll to explore all ${model.count.toLocaleString('en-US')} ${comparison?'seasons':'episodes'}</p>`:''}`;
}
