import assert from 'node:assert/strict';
import { band, average, compactMatrix, matrixSkeleton, ratings, cachedRatings, matrixRatings, cachedMatrix, ratingSources } from '../client/ratings.js';
import { chart, timelineModel, timelineAxis, smoothPath, nearestRatingPoint } from '../client/episode-timeline.js';

assert.equal(band(9.7).name, 'Absolute cinema');
assert.equal(band(9.7).colour, '#1DA1F2');
assert.equal(band(9.6).name, 'Awesome');
assert.equal(band(8).colour, '#28B463');
assert.equal(band(7).colour, '#F4D03F');
assert.equal(band(6).colour, '#F39C12');
assert.equal(band(4.1).name, 'Bad');
assert.equal(band(4).name, 'Garbage');
assert.equal(band(null).name, 'Unrated');
assert.equal(average([{ rating: 8 }, { rating: null }, { rating: 10 }]), 9);
assert.equal(average([{ rating: null }]), null);

const episodes = [
  { id: 1, season: 1, number: 1, name: '<Pilot>', rating: 7.3 },
  { id: 2, season: 1, number: 3, name: 'Finale', rating: 10 },
  { id: 3, season: 2, number: 1, name: 'New season', rating: null },
];
const matrix = compactMatrix({ episodes });
assert.match(matrix, /viewBox="0 0 3 2"/);
assert.match(matrix, /&lt;Pilot&gt;/);
assert.match(matrix, /x="2" y="0"/); // A missing episode position stays empty.
assert.match(matrix, /fill="#bdbdbd"/);
assert.equal((matrixSkeleton().match(/ratings-mini-cell skel/g) || []).length, 24);
assert.match(matrixSkeleton(), /aria-hidden="true"/);
const timeline = chart(episodes);
assert.match(timeline, /data-min="7"/);
assert.match(timeline, />7.5<\/text>/);
assert.equal((timeline.match(/class="ratings-point-hit"/g) || []).length, 2);
assert.match(timeline, /class="ratings-trend"/);
assert.match(chart([{ rating: null }]), /not been rated/);
assert.match(chart(episodes, [{ season: 1, number: 1, rating: 4.5 }], ['First', 'Second']), /data-min="4.25"/);

const episode=(rating,number=1,season=1)=>({id:season*100+number,season,number,rating});
for(const lowest of [0,1.2,4.5,5.6,6,9.9,10]){
  const model=timelineModel([episode(lowest),episode(10,2)]);
  assert.ok(model.low<=lowest,'the axis includes every real score, including genuine lows');
  assert.equal(model.ticks.at(-1),10,'the exact top of the rating scale is always present');
  assert.ok(model.series[0].points.every(p=>p.y>=36&&p.y<=244),'all points fit inside the episode plot');
}
const padded=chart([episode(6),episode(10,2)]);
assert.match(padded, /data-min="5.75"/);
assert.match(padded, />5.75<\/text>/,'quarter-point floors keep their exact label');
assert.match(padded, />10.0<\/text>/);
assert.match(padded, /class="ratings-trend-plot"/,'the trend has its own plot');
const paddedSeries=timelineModel([episode(6),episode(10,2)]).series[0];
assert.ok(Math.max(...paddedSeries.points.map(p=>p.y))<Math.min(...paddedSeries.trend.flat().map(p=>p.y)),
  'the average occupies a separate plot below the episode connections');

for(const gap of [episode(null,3),episode(8,9),episode(8,1,3)]){
  const before=[episode(6),episode(8,2),gap,episode(7,10,gap.season)];
  const after=before.map((p,i)=>i>=2?{...p,rating:p.rating==null?null:10}:p);
  const firstRun=list=>timelineModel(list).series[0].trend[0].map(p=>p.rating);
  assert.deepEqual(firstRun(before),[7,7]);
  assert.deepEqual(firstRun(after),firstRun(before),'later scores cannot bleed across unrated episodes, missing numbers or seasons');
  assert.equal(timelineModel(before).series[0].runs[0].length,2);
}

const rawMoveCount=markup=>[...markup.matchAll(/<path\b([^>]*class="ratings-raw-line"[^>]*)>/g)]
  .reduce((count,match)=>count+(match[1].match(/\bd="([^"]*)"/)?.[1].match(/M/g)||[]).length,0);
const runCodes=runs=>runs.map(run=>run.map(p=>`S${p.season}E${p.number}`));

// Season changes are part of the episode run; averages retain season boundaries.
for(const nextNumber of [1,3]){
  const joined=[episode(6),episode(8,2),episode(10,nextNumber,2),episode(10,nextNumber+1,2)];
  const series=timelineModel(joined).series[0];
  assert.equal(series.runs.length,1,'ordinary reset or absolute episode numbering connects across a season boundary');
  assert.deepEqual(series.trendRuns.map(run=>run.length),[2,2]);
  assert.deepEqual(series.trend.map(run=>run.map(p=>p.rating)),[[7,7],[10,10]],
    'the next season cannot change the preceding season average');
  assert.equal(rawMoveCount(chart(joined)),1,'the rendered raw line also remains continuous');
}
const years=[episode(6,51,2000),episode(8,52,2000),episode(10,53,2001),episode(10,54,2001)];
assert.equal(timelineModel(years).series[0].runs.length,1,'year-valued seasons can continue absolute episode numbers');
assert.deepEqual(runCodes(timelineModel(years).series[0].trendRuns),
  [['S2000E51','S2000E52'],['S2001E53','S2001E54']]);

for(const [name,list,expected] of [
  ['an explicit unrated episode',[episode(7),episode(null,2),episode(9,3)],[['S1E1'],['S1E3']]],
  ['a missing episode number',[episode(7),episode(9,3)],[['S1E1'],['S1E3']]],
  ['a missing season',[episode(7),episode(9,1,3)],[['S1E1'],['S3E1']]],
  ['a missing year',[episode(7,52,2000),episode(9,1,2002)],[['S2000E52'],['S2002E1']]],
  ['a gap at a season change',[episode(7,6),episode(9,3,2)],[['S1E6'],['S2E3']]],
]){
  const model=timelineModel(list);
  assert.deepEqual(runCodes(model.series[0].runs),expected,`${name} breaks the raw line`);
  assert.deepEqual(runCodes(model.series[0].trendRuns),expected,`${name} also breaks the average`);
  assert.equal(rawMoveCount(chart(list)),expected.length,`${name} stays broken in the rendered path`);
  assert.equal(model.series[0].points.length,list.length,'unrated entries keep their ordinal position');
}

function checkSharedAxis(list,availableWidth,label){
  const model=timelineModel(list,null,availableWidth),axis=timelineAxis(model),points=model.series[0].points;
  const starts=points.filter((p,i)=>!i||p.season!==points[i-1].season);
  assert.deepEqual(axis.seasonTicks.map(({x,season,number})=>({x,season,number})),
    starts.map(({x,season,number})=>({x,season,number})),`${label}: all real season starts retain their marks`);
  assert.equal(axis.bands.length,starts.length,`${label}: season bands follow the actual feed grouping`);
  assert.ok(axis.labels.some(p=>p.kind==='season'),`${label}: at least one season is identified`);
  assert.ok(axis.labels.every(p=>p.y===axis.labelY),`${label}: season and episode labels share one row`);
  const labels=[...axis.labels].sort((a,b)=>a.left-b.left);
  for(const [i,p] of labels.entries()){
    assert.ok([p.left,p.right,p.x,p.y].every(Number.isFinite),`${label}: label geometry is finite`);
    assert.ok(p.left>=0&&p.right<=model.width&&p.left<=p.right,`${label}: labels stay inside the plot`);
    if(i)assert.ok(p.left>=labels[i-1].right,`${label}: neighboring labels cannot overlap`);
    if(p.kind==='season'){
      const tick=axis.seasonTicks.find(t=>t.x===p.x);
      assert.ok(tick,`${label}: season labels attach to their true starts`);
      assert.equal(p.text,`S${tick.season}`,`${label}: provider season numbers are preserved`);
    }
  }
  for(const [i,tick] of axis.episodeTicks.entries()){
    if(i)assert.ok(tick.x-axis.episodeTicks[i-1].x>=8-1e-7,`${label}: minor guides thin in dense views`);
    assert.ok(axis.seasonTicks.every(major=>Math.abs(tick.x-major.x)>=4),`${label}: minor guides leave room for season marks`);
  }
  const markup=chart(list,null,[],availableWidth);
  assert.equal((markup.match(/class="ratings-x-axis"/g)||[]).length,1,`${label}: the rendered chart has one shared x-axis`);
  const renderedLabels=[...markup.matchAll(/<text\b([^>]*)>([^<]*)<\/text>/g)]
    .filter(match=>/class="ratings-(?:season|episode)-label"/.test(match[1]));
  assert.equal(renderedLabels.length,axis.labels.length,`${label}: rendered labels match the selected geometry`);
  assert.ok(renderedLabels.every(match=>Number(match[1].match(/\by="([^"]+)"/)[1])===axis.labelY),
    `${label}: the SVG does not add a second season or episode label row`);
  return {model,axis};
}

// Short series fit, while labels adapt to space instead of staggering into two rows.
for(const count of [4,5,7,10,12,14]){
  const list=Array.from({length:count},(_,i)=>episode(7+(i%6)/2,i+1));
  for(const width of [320,390,1280]){
    const {model,axis}=checkSharedAxis(list,width,`${count} episodes at ${width}px`);
    assert.equal(model.width,model.viewport,'short shows do not gain unnecessary horizontal scrolling');
    assert.equal(model.series[0].points.length,count,'label thinning cannot remove episode samples');
    assert.deepEqual(axis.labels.filter(p=>p.kind==='season').map(p=>p.text),['S1']);
  }
}
for(const firstSeason of [1,1999]){
  const twoSeasons=Array.from({length:12},(_,i)=>episode(7+(i%6)/2,i%6+1,firstSeason+Math.floor(i/6)));
  for(const width of [320,390,1280]){
    const {axis}=checkSharedAxis(twoSeasons,width,`two seasons beginning at ${firstSeason}, ${width}px`);
    assert.deepEqual(axis.labels.filter(p=>p.kind==='season').map(p=>p.text),[`S${firstSeason}`,`S${firstSeason+1}`],
      'season names take priority over neighboring episode labels');
    assert.ok(axis.labels.some(p=>p.kind==='episode'),'episode labels remain available wherever they fit');
  }
}

for(const list of [[episode(8)],Array.from({length:14},(_,i)=>episode(8,i+1)),
  [episode(null),episode(8,2),episode(null,3)]]){
  const {model}=checkSharedAxis(list,390,'single, flat or sparsely rated series');
  assert.ok(model.series[0].points.filter(p=>p.rating!=null).every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
  assert.doesNotMatch(chart(list),/NaN|Infinity/,'single and equal ratings never generate invalid paths');
}
assert.equal(timelineModel([episode(null)]),null,'all-unrated input has no invented chart');
const sparse=Array.from({length:1214},(_,i)=>episode(i===321?5.5:null,i%40+1,1996+Math.floor(i/40)));
const sparseSeries=checkSharedAxis(sparse,390,'a long series with only one known rating').model.series[0];
assert.equal(sparseSeries.points.length,1214,'a sparse feed keeps its known episode positions');
assert.equal(sparseSeries.points.filter(p=>p.y!=null).length,1);
assert.deepEqual(runCodes(sparseSeries.runs),[['S2004E2']]);
assert.deepEqual(runCodes(sparseSeries.trendRuns),[['S2004E2']]);
assert.equal(rawMoveCount(chart(sparse)),1,'a lone known rating never connects across unknown episodes');

// Keep all samples in a compact overview, with modest scrolling for very long shows.
const long=Array.from({length:1181},(_,i)=>episode(i<1168?6+(i%9)/2:null,i+1));
const longModel=timelineModel(long,null,390),longPoints=longModel.series[0].points;
assert.equal(longPoints.length,1181);
assert.equal(longPoints.filter(p=>p.y!=null).length,1168);
assert.equal(new Set(longPoints.filter(p=>p.y!=null).map(p=>p.id)).size,1168);
assert.ok(longPoints.every((p,i)=>!i||p.x-longPoints[i-1].x>=1));
assert.ok(longModel.width>longModel.viewport);
assert.ok(longModel.width<1500,'a long show stays near the original overview instead of stretching into dozens of screens');
assert.equal(timelineModel(long,null,1280).width,longModel.width,'desktop does not compress a long timeline either');
assert.equal(timelineModel(long.slice(0,5),null,390).width,344,'short shows fit their mobile viewport');
const annual=long.map((p,i)=>({...p,id:10000+i,season:1999+Math.min(27,Math.floor(i/42)),number:i<1134?i%42+1:i-1133}));
for(const width of [390,1280]){
  for(const [name,list] of [['single-season',long],['annual seasons',annual]]){
    const {model}=checkSharedAxis(list,width,`${name}, 1181 episodes at ${width}px`);
    assert.ok(model.width>=1240&&model.width<1500,'long shows keep a compact scrollable overview');
    assert.equal(model.series[0].points.length,1181);
    assert.equal(model.series[0].points.filter(p=>p.y!=null).length,1168);
    assert.equal(model.low,5.75,'axis and guide changes preserve the adaptive score floor');
  }
}

const dense=[{id:1,x:10,y:80},{id:2,x:11,y:100},{id:3,x:12,y:null},{id:4,x:13,y:100}];
assert.equal(nearestRatingPoint(dense,10,80).id,1,'overlapping hit targets cannot steal a point at its actual centre');
assert.equal(nearestRatingPoint(dense,10.1,100).id,2,'vertical distance matters as well as episode order');
assert.equal(nearestRatingPoint(dense,12,100).id,2,'equal-distance ties are stable');
assert.equal(nearestRatingPoint(dense,12,0),null,'blank plot space does not select a distant rating');
assert.equal(nearestRatingPoint([{x:1,y:null}],1,0),null,'unrated positions are never pointer targets');
for(const p of longPoints.filter(p=>p.y!=null))assert.equal(nearestRatingPoint(longPoints,p.x,p.y).id,p.id,'every dense rating can still be picked at its centre');

const compared=timelineModel([episode(0),episode(10,2),episode(8,1,2),episode(7,1,3)],
  [episode(9,1),episode(10,1,3)]);
assert.equal(compared.series[0].points[0].rating,5,'comparison plots actual season means');
assert.equal(compared.low,4.75,'comparison scale follows plotted averages rather than individual outliers');
assert.deepEqual(compared.series[1].runs.map(run=>run.map(p=>p.season)),[[1],[3]],'a missing season breaks the comparison line');
assert.equal(compared.series[0].trend.length,0,'season comparisons do not add an episode moving average');
assert.equal(compared.series[0].trendRuns.length,0);
const comparedAxis=timelineAxis(compared);
assert.deepEqual(comparedAxis.seasonTicks.map(p=>p.season),[1,2,3]);
assert.ok(comparedAxis.labels.every(p=>p.kind==='season'&&p.y===comparedAxis.labelY),
  'the comparison keeps season-only labels on one row');
assert.equal((chart([episode(7),episode(9,1,2)],[episode(8),episode(10,1,3)],['First','Second'])
  .match(/class="ratings-x-axis"/g)||[]).length,1,'comparisons also share one season axis');

const samples=[{x:0,y:4},{x:28,y:10},{x:56,y:3},{x:84,y:7}];
const curves=[...smoothPath(samples).matchAll(/ C([^,]+),([^ ]+) ([^,]+),([^ ]+) ([^,]+),([^ ]+)/g)];
assert.equal(curves.length,3);
curves.forEach((curve,i)=>{
  const low=Math.min(samples[i].y,samples[i+1].y),high=Math.max(samples[i].y,samples[i+1].y);
  for(const control of [Number(curve[2]),Number(curve[4])])assert.ok(control>=low&&control<=high,'the trend cannot invent peaks beyond its neighbouring averages');
});

let calls = 0;
let answer;
globalThis.fetch = () => { calls++; return new Promise(resolve => { answer = resolve; }); };
const first = ratings(169), second = ratings(169);
await new Promise(done=>setTimeout(done,0));
assert.equal(calls, 1, 'concurrent cards and title views share one request');
answer(new Response(JSON.stringify({id:169,episodes})));
assert.equal(await first, await second);
assert.deepEqual(cachedRatings(169).episodes, episodes);
await ratings(169);
assert.equal(calls, 1, 'completed data is reused by new cards');

globalThis.fetch = async () => new Response(JSON.stringify({error:'Unavailable'}),{status:502});
await assert.rejects(ratings(82), /Unavailable/);
assert.equal(cachedRatings(82), undefined);
globalThis.fetch = async () => new Response(JSON.stringify({id:82,episodes:[]}));
assert.deepEqual((await ratings(82)).episodes, [], 'a failed request can be retried');
let batchUrl;
globalThis.fetch = async url => {
  batchUrl=url;
  return new Response(JSON.stringify({shows:[{id:169,sources:'TMDB',episodes:[
    {season:1,number:1,name:'<Pilot>',rating:9.1,rating_source:'TMDB',rating_votes:100},
  ]}],pending:[526]}));
};
const batch=await matrixRatings([169,526,169]);
assert.equal(batchUrl,'/api/episode-matrices?ids=169,526');
assert.deepEqual(batch.pending,[526]);
assert.equal(cachedMatrix(169).episodes[0].rating,9.1);
assert.equal(cachedRatings(169).episodes[0].name,'<Pilot>');
assert.equal(cachedRatings(169).episodes[0].rating_source,'TMDB');
assert.match(compactMatrix(cachedMatrix(169)),/TMDB/);
assert.equal(ratingSources(batch.shows[0]),'TMDB');
console.log('Episode palette, charts, missing data, shared request cache and compact batches passed.');
