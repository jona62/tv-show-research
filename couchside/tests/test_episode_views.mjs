import assert from 'node:assert/strict';
import { ratingDetailView, ratingDetailSearch, ratingDetailSnapshot, ratingDetailGrid } from '../client/episode-ratings.js';
import { timelineModel, chart, smoothPath, nearestRatingPoint } from '../client/episode-timeline.js';

const episodes = [
  {id:1,season:1999,number:1,name:'<Pilot>',rating:6,rating_source:'TVmaze',summary:'First'},
  {id:2,season:1999,number:3,name:'Third',rating:10,rating_source:'TMDB'},
  {id:3,season:2001,number:1,name:'New season',rating:null},
  {id:4,season:2001,number:2,name:'Return',rating:8,rating_source:'TVmaze'},
];
assert.deepEqual(ratingDetailView('?rating-view=grid&rating-season=1999&rating-inverted=1',episodes),
  {view:'grid',season:1999,inverted:true});
assert.deepEqual(ratingDetailView('?view=timeline&season=1999&inverted=1',episodes),
  {view:'list',season:'all',inverted:false},'comparison/unrelated query fields cannot change the detail view');
assert.deepEqual(ratingDetailView('?rating-view=%3Csvg%3E&rating-season=9999&rating-inverted=true',episodes),
  {view:'list',season:'all',inverted:false},'unavailable seasons and layouts use safe defaults');
for(const view of ['list','grid','wrapped','timeline']){
  const before='show=1505&mode=single&seasons=82%3A2&rating-view=list';
  const state={view,season:2001,inverted:true},search=ratingDetailSearch(before,state),params=new URLSearchParams(search);
  assert.equal(params.get('show'),'1505');assert.equal(params.get('mode'),'single');assert.equal(params.get('seasons'),'82:2');
  assert.deepEqual(ratingDetailView(search,episodes),state,'every shared detail view round-trips its scope/orientation');
}
const reset=new URLSearchParams(ratingDetailSearch('?show=1505&rating-view=grid&rating-season=1999&rating-inverted=1&mode=all',
  {view:'list',season:'all',inverted:false}));
assert.equal(reset.get('show'),'1505');assert.equal(reset.get('mode'),'all');
for(const key of ['rating-view','rating-season','rating-inverted'])assert.equal(reset.has(key),false);

const title={id:1505,card:{name:'Card title',poster:'https://example.test/card-portrait.jpg',year:1999},
  data:{show:{name:'Loaded title',art:'https://example.test/full-portrait.jpg',year:1999}},
  live:{name:'Live title',poster:'https://example.test/live-portrait.jpg',backdrop:'https://example.test/landscape.jpg'}};
const data={episodes,sources:'TVmaze / TMDB',cacheFetchedAt:'2026-10-02T12:00:00Z'};
const state={view:'grid',season:1999,inverted:true};
const snapshot=ratingDetailSnapshot(title,data,state);
assert.equal(snapshot.kind,'detail');assert.equal(snapshot.id,1505);assert.equal(snapshot.title,'Live title');
assert.equal(snapshot.poster,'https://example.test/full-portrait.jpg','export uses original portrait artwork, never the backdrop');
assert.equal(snapshot.year,1999);assert.equal(snapshot.view,'grid');assert.equal(snapshot.season,1999);
assert.equal(snapshot.inverted,true);assert.equal(snapshot.averages,true);
assert.deepEqual(snapshot.episodes.map(e=>e.id),[1,2]);assert.equal(snapshot.sources,'TVmaze / TMDB');
snapshot.episodes[0].rating=1;snapshot.episodes[0].summary='Changed exported copy';
assert.equal(episodes[0].rating,6);assert.equal(episodes[0].summary,'First','snapshot edits cannot mutate live/cached episodes');
const full=ratingDetailSnapshot(title,data,{view:'list',season:'all',inverted:false});
assert.equal(full.episodes.length,4,'a collapsed list still exports every episode in its selected scope');
assert.equal(full.episodes[2].rating,null,'unrated samples remain truthful in exported models');
title.live.art='https://example.test/new-original-poster.jpg';
assert.equal(ratingDetailSnapshot(title,data,state).poster,title.live.art,'later metadata is captured when Save is invoked');
assert.equal(ratingDetailSnapshot({id:1,card:{backdrop:'landscape'},live:{backdrop:'other-landscape'}},data,state).poster,null);
assert.equal(ratingDetailSnapshot(title,data,{...state,season:2001}).sources,'TVmaze','credits follow the selected episodes');

for(const inverted of [false,true]){
  const markup=ratingDetailGrid(episodes,inverted);
  assert.match(markup,/class="rating-table"/);assert.match(markup,/role="region"/);assert.match(markup,/tabindex="0"/);
  assert.match(markup,inverted?/seasons in columns/:/seasons in rows/);
  const ids=[...markup.matchAll(/data-episode="(\d+)"/g)].map(match=>Number(match[1])).sort((a,b)=>a-b);
  assert.deepEqual(ids,[1,2,3,4],'inversion moves existing cells without dropping or fabricating episodes');
  assert.match(markup,/&lt;Pilot&gt;/);assert.doesNotMatch(markup,/<Pilot>/);
  assert.match(markup,/class="rating-empty"/,'missing episode positions remain empty');
  assert.match(markup,/class="ratings-average"/,'season averages stay neutral and non-interactive');
  assert.equal((markup.match(/<button\b/g)||[]).length,4,'only actual episodes become buttons');
  const headings=markup.slice(0,markup.indexOf('</thead>'));
  assert.match(headings,inverted?/>Episode<\/th>/:/>Season<\/th>/);
  assert.match(headings,inverted?/>1999 season<\/span>/:/>E3<\/span>/);
}
const standardIds=[...ratingDetailGrid(episodes).matchAll(/data-episode="(\d+)"/g)].map(match=>match[1]);
const invertedIds=[...ratingDetailGrid(episodes,true).matchAll(/data-episode="(\d+)"/g)].map(match=>match[1]);
assert.notDeepEqual(standardIds,invertedIds,'the two orientations actually transpose the live rendered cells');

const samples=[
  {id:10,season:1,number:1,rating:6},{id:11,season:1,number:2,rating:8},
  {id:12,season:1,number:3,rating:null},{id:13,season:1,number:5,rating:10},
  {id:14,season:3,number:1,rating:4},{id:15,season:3,number:2,rating:8},
];
const series=timelineModel(samples).series[0];
assert.deepEqual(series.runs[0].map(p=>p.id),[10,11,13,14,15]);
assert.equal(series.runs.length,1);assert.equal(series.trend.length,1);
assert.deepEqual(series.trendRuns.map(run=>run.map(p=>p.id)),[[10,11],[13],[14,15]],
  'connected lines do not let a five-episode window cross a null, number gap, or season');
assert.deepEqual(series.trendPoints.map(p=>p.rating),[7,7,10,6,6]);
assert.equal(series.points[2].y,null);assert.equal(series.trendPoints.some(p=>p.id===12),false);
const altered=samples.map(p=>p.season===3?{...p,rating:10}:p);
assert.deepEqual(timelineModel(altered).series[0].trendPoints.slice(0,3).map(p=>p.rating),[7,7,10]);
const markup=chart(samples);
for(const name of ['ratings-raw-line','ratings-trend']){
  const path=[...markup.matchAll(/<path\b[^>]*>/g)].find(match=>match[0].includes(`class="${name}"`))[0].match(/\bd="([^"]*)"/)[1];
  assert.equal((path.match(/M/g)||[]).length,1,'both panels render one continuous line through their known samples');
  assert.equal((path.match(/ C/g)||[]).length,4);
}
assert.equal((markup.match(/class="ratings-point"/g)||[]).length,5,'no dot is invented for the unrated position');
assert.deepEqual(series.points.map(p=>p.rating),samples.map(p=>p.rating));
for(const point of series.runs[0])assert.equal(nearestRatingPoint(series.points,point.x,point.y).id,point.id);
const singleton=timelineModel([{id:1,season:1,number:1,rating:8}]).series[0];
assert.equal(singleton.trendPoints[0].rating,8);assert.equal((smoothPath(singleton.runs[0]).match(/ C/g)||[]).length,0);
assert.equal(timelineModel([{id:1,season:1,number:1,rating:null}]),null);
const long=Array.from({length:1181},(_,i)=>({id:1000+i,season:1999+Math.floor(i/44),number:i%44+1,rating:i<1168?6+i%5:null}));
for(const width of [390,1280]){
  const model=timelineModel(long,null,width);
  assert.equal(model.width,1244);assert.equal(model.low,5.75);
  assert.equal(model.series[0].runs[0].length,1168);
  assert.equal(model.series[0].trendPoints.length,1168);
}
console.log('Episode detail URL restoration, grid inversion, scoped portrait snapshots, and continuous truthful timeline passed.');
