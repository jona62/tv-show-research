import assert from 'node:assert/strict';
import test from 'node:test';
import { createPublicDataCache, createPublicReader, publicRecord } from '../client/public-data.js';
const episode = id => ({ id: id * 100, season: 1, number: 1, name: 'Pilot', rating: 8,
  image: 'https://static.tvmaze.com/uploads/images/medium_landscape/1/2.jpg', summary: 'The complete episode summary.', runtime: 40 });
const rating = id => ({ id, episodes: [episode(id)], sources: 'TVmaze', refreshing: false, revision: `revision-${id}` });
const card = id => ({ id, name: `Show ${id}`, poster: 'https://static.tvmaze.com/uploads/images/medium_portrait/1/2.jpg' });
const memory = () => {
  const rows = new Map();
  return { rows, read: async key => structuredClone(rows.get(key)), write: async (entries, bytes, count) => {
    entries.forEach(entry => rows.set(entry.key, structuredClone(entry)));
    let used = 0;
    [...rows.values()].sort((a,b)=>b.at-a.at).forEach((entry, i) => {
      used += entry.bytes; if (i >= count || used > bytes || entries[0]?.version && entry.version !== entries[0].version) rows.delete(entry.key);
    });
  } };
};

test('persisted full public records reuse across readers and preserve hover/export fields', async () => {
  const storage = memory(); let now = 1000;
  const first = createPublicDataCache({ storage, now: () => now });
  await first.put('ratings', [rating(82)], 'catalogue-one');
  const reloaded = createPublicDataCache({ storage, now: () => now });
  const value = await reloaded.get('ratings', 82);
  assert.deepEqual(value.episodes, [episode(82)]);
  value.episodes[0].summary = 'Changed by a consumer';
  assert.equal((await reloaded.get('ratings', 82)).episodes[0].summary, episode(82).summary);
  now += 300000;
  assert.equal(await reloaded.get('ratings', 82), null, 'completed persisted ratings expire after five minutes');
});

test('schema corruption, source expiry, stale revisions and refining records cannot become fresh hits', async () => {
  const storage = memory(); let now = 1000000;
  const cache = createPublicDataCache({ storage, now: () => now });
  await cache.put('ratings', [{ ...rating(1), fetchedAt: 1000, expiresAt: 1002 }], 'one');
  await cache.put('ratings', [{ ...rating(1), fetchedAt: 999, episodes: [{ ...episode(1), rating: 1 }] }], 'one');
  assert.equal((await cache.get('ratings', 1)).episodes[0].rating, 8, 'a late older record cannot overwrite a newer revision');
  now += 2000;
  assert.equal(await cache.get('ratings', 1), null, 'source freshness bounds client freshness');
  await cache.put('ratings', [{ ...rating(2), refreshing: true }], 'one');
  assert.equal(await cache.get('ratings', 2), null);
  await cache.put('ratings', [rating(3)], 'one'); storage.rows.get('ratings:3').schema = 99;
  assert.equal(await createPublicDataCache({ storage, now: () => now }).get('ratings', 3), null);
  assert.equal(publicRecord('ratings', { id: 4, episodes: [{ season: 1, number: 1, rating: 8 }] }), null,
    'compact matrices without episode identity are rejected');
});

test('only public projections persist, with bounded storage and catalogue version invalidation', async () => {
  const storage = memory(); let now = 1000;
  const cache = createPublicDataCache({ storage, now: () => now, maxRecords: 2 });
  for (const id of [1,2,3]) { now++; await cache.put('card', [{ ...card(id), email: 'private@example.test', csrf: 'secret', profile: [82], saved: [1] }], 'one'); }
  assert.equal(storage.rows.size, 2);
  assert.doesNotMatch(JSON.stringify([...storage.rows.values()]), /private|secret|profile|saved/);
  await cache.put('account', [{ ...card(4), token: 'secret' }], 'one');
  assert.equal(await cache.get('account', 4), null);
  now++; await cache.put('card', [card(5)], 'two');
  assert.equal(await cache.get('card', 3), null, 'a newly observed catalogue version invalidates older public records');
  assert.equal(storage.rows.size, 1);
});

test('quota and unavailable storage preserve the in-memory cache and network fallback', async () => {
  const cache = createPublicDataCache({ storage: { read: async () => { throw Error('Blocked'); }, write: async () => { throw Error('Quota'); } } });
  await cache.put('ratings', [rating(82)]);
  assert.equal((await cache.get('ratings', 82)).episodes[0].id, 8200);
  assert.equal(await cache.get('ratings', 83), null);
});

test('comparison reads coalesce overlapping IDs into one request per public data kind', async () => {
  const urls = [], storage = memory();
  const fetcher = async url => {
    urls.push(url); const ids = url.split('ids=')[1].split(',').map(Number);
    return new Response(JSON.stringify({ shows: ids.map(url.includes('show-cards') ? card : rating), pending: [], catalogueVersion: 'one' }));
  };
  const reader = createPublicReader({ cache: createPublicDataCache({ storage }), fetcher });
  const results = await Promise.all([reader.read('card',82),reader.read('card',182),reader.read('ratings',82),reader.read('ratings',182),reader.read('ratings',82)]);
  assert.deepEqual(urls, ['/api/show-cards?ids=82,182','/api/episode-ratings-batch?ids=82,182']);
  assert.equal(results[2],results[4], 'shared work has one result without consumer-owned cancellation');
  const reloaded = createPublicReader({ cache: createPublicDataCache({ storage }), fetcher });
  await Promise.all([reloaded.read('card',82),reloaded.read('ratings',82)]);
  assert.equal(urls.length,2, 'warm reload data comes from persisted public records');
  reader.dispose(); reloaded.dispose();
});

test('pending batches retry through one shared bounded queue and preserve successful partial records', async () => {
  let calls = 0, now = 0; const timers = [];
  const reader = createPublicReader({ now: () => now, random: () => .5, schedule: (run, delay) => { timers.push({run,delay});return 1; }, cancel: () => {},
    fetcher: async () => new Response(JSON.stringify(++calls === 1 ? { shows:[rating(1)], pending:[2] } : { shows:[rating(2)], pending:[] })) });
  const one = reader.read('ratings',1), two = reader.read('ratings',2), duplicate = reader.read('ratings',2);
  await new Promise(resolve=>setImmediate(resolve));
  await timers.shift().run();
  assert.equal((await one).id,1); assert.equal(calls,1);
  const retry = timers.shift(); now += retry.delay; retry.run();
  await timers.shift().run();
  assert.equal((await two).id,2); assert.equal(await two,await duplicate); assert.equal(calls,2);
  reader.dispose();
});

test('missing records do not discard valid batch members and disposal settles pending readers', async () => {
  const timers=[];
  const reader=createPublicReader({schedule:run=>{timers.push(run);return 1;},cancel:()=>{},
    fetcher:async()=>new Response(JSON.stringify({shows:[rating(1)],pending:[2],missing:[3]}))});
  const one=reader.read('ratings',1), two=reader.read('ratings',2), three=reader.read('ratings',3);
  const missing=assert.rejects(three,error=>error.missing===true);
  await new Promise(resolve=>setImmediate(resolve)); await timers.shift()();
  assert.equal((await one).id,1); await missing;
  const stopped=assert.rejects(two,/closed/);reader.dispose();await stopped;
});

test('enrichment work is shared per show, paused while hidden and stops after completion', async () => {
  let hidden=true,now=0,calls=0;const timers=[];
  const reader=createPublicReader({visible:()=>!hidden,now:()=>now,random:()=>.5,
    schedule:(run,delay)=>{timers.push({run,delay});return 1;},cancel:()=>{}});
  reader.follow(82,async()=>{calls++;return false;});reader.follow(82,async()=>{calls+=100;return true;});
  const first=timers.shift();now+=first.delay;await first.run();assert.equal(calls,0);
  hidden=false;const second=timers.shift();now+=second.delay;await second.run();
  assert.equal(calls,1);assert.equal(timers.length,0);reader.dispose();
});

test('per-show interest pauses inactive routes and completed records cancel their scheduled retry', async () => {
  let wanted=false,calls=0;const timers=new Map();let next=0;
  const reader=createPublicReader({random:()=>.5,schedule:run=>{timers.set(++next,run);return next;},cancel:id=>timers.delete(id)});
  const runNext=async()=>{const [id,run]=timers.entries().next().value;timers.delete(id);await run();};
  reader.follow(82,async()=>{calls++;return true;},()=>{},()=>wanted);
  await runNext();assert.equal(calls,0,'a visible document does not imply a visible show');
  wanted=true;await runNext();assert.equal(calls,1);
  reader.stopFollowing(82);assert.equal(timers.size,0,'a completed full record cancels an earlier matrix retry');
  reader.follow(82,async()=>{calls++;return false;});await runNext();
  assert.equal(calls,2);assert.equal(timers.size,0,'a later reader can follow that show again without an old job');
  reader.dispose();
});
