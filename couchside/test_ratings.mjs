import assert from 'node:assert/strict';
import { band, average, compactMatrix, matrixSkeleton, ratings, cachedRatings, matrixRatings, cachedMatrix, ratingSources } from './ratings.js';
import { chart } from './episode-ratings.js';

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
assert.match(timeline, /data-min="6"/);
assert.match(timeline, />6.5<\/text>/);
assert.equal((timeline.match(/class="ratings-point-hit"/g) || []).length, 2);
assert.match(timeline, /class="ratings-trend"/);
assert.match(chart([{ rating: null }]), /not been rated/);
assert.match(chart(episodes, [{ season: 1, number: 1, rating: 4.5 }], ['First', 'Second']), /data-min="3"/);

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
