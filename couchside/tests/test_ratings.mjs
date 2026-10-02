import assert from 'node:assert/strict';
import { band, average, compactMatrix, matrixSkeleton, ratings, cachedRatings, matrixRatings, cachedMatrix, ratingSources } from '../client/ratings.js';
import { chart, timelineModel, smoothPath } from '../client/episode-timeline.js';

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
const plot=padded.match(/<g class="ratings-episode-plot">(.*?)<\/g>\s*<text/s)[1];
assert.doesNotMatch(plot, /ratings-trend/,'episode connections do not contain the trend');

for(const gap of [episode(null,3),episode(8,9),episode(8,1,2)]){
  const before=[episode(6),episode(8,2),gap,episode(7,10,gap.season)];
  const after=before.map((p,i)=>i>=2?{...p,rating:p.rating==null?null:10}:p);
  const firstRun=list=>timelineModel(list).series[0].trend[0].map(p=>p.rating);
  assert.deepEqual(firstRun(before),[7,7]);
  assert.deepEqual(firstRun(after),firstRun(before),'later scores cannot bleed across unrated episodes, missing numbers or seasons');
  assert.equal(timelineModel(before).series[0].runs[0].length,2);
}

// Keep long-series samples and missing positions, rather than thinning or overlapping them.
const long=Array.from({length:1181},(_,i)=>episode(i<1168?6+(i%9)/2:null,i+1));
const longModel=timelineModel(long,null,390),longPoints=longModel.series[0].points;
assert.equal(longPoints.length,1181);
assert.equal(longPoints.filter(p=>p.y!=null).length,1168);
assert.equal(new Set(longPoints.filter(p=>p.y!=null).map(p=>p.id)).size,1168);
assert.ok(longPoints.every((p,i)=>!i||p.x-longPoints[i-1].x>=28));
assert.ok(longModel.width>longModel.viewport);
assert.equal(timelineModel(long,null,1280).width,longModel.width,'desktop does not compress a long timeline either');
assert.equal(timelineModel(long.slice(0,5),null,390).width,344,'short shows fit their mobile viewport');

const compared=timelineModel([episode(0),episode(10,2),episode(8,1,2),episode(7,1,3)],
  [episode(9,1),episode(10,1,3)]);
assert.equal(compared.series[0].points[0].rating,5,'comparison plots actual season means');
assert.equal(compared.low,4.75,'comparison scale follows plotted averages rather than individual outliers');
assert.deepEqual(compared.series[1].runs.map(run=>run.map(p=>p.season)),[[1],[3]],'a missing season breaks the comparison line');
assert.equal(compared.series[0].trend.length,0,'season comparisons do not add an episode moving average');

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
