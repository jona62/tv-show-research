import assert from 'node:assert/strict';
import {createClient,retryDelay} from './network.js';
const answer=(status=200,headers={})=>new Response(JSON.stringify({ok:true}),{status,headers});
assert.equal(retryDelay('2'),2000);
assert.equal(retryDelay('not a date'),0);
assert.equal(retryDelay('Thu, 01 Oct 2026 12:00:10 GMT',Date.parse('2026-10-01T12:00:00Z')),10000);
let calls=0,now=0,events=[];
const retrying=createClient({gap:0,now:()=>now,sleep:async ms=>{now+=ms;},random:()=>.5,
  notify:e=>events.push(e),send:async()=>{calls++;if(calls===1)throw TypeError('reset');return calls===2?answer(503):answer();}});
assert.equal((await retrying.request('/api/extra?id=1')).status,200);
assert.equal(calls,3);
assert(events.some(e=>e.state==='retrying'));
assert(events.some(e=>e.state==='restored'));
assert(now>=1500);
calls=0;
const limited=createClient({gap:0,budget:100,notify:()=>{},send:async()=>{calls++;return answer(429,{'Retry-After':'120'});}});
assert.equal((await limited.request('/api/home',{method:'POST',body:'{}'})).status,429);
assert.equal(calls,1); // A short deadline cannot cause an early retry.
let routes=[];
const isolated=createClient({gap:0,budget:100,notify:()=>{},send:async path=>{
  routes.push(path);return path.startsWith('/api/trailer')?answer(503,{'Retry-After':'120'}):answer();
}});
assert.equal((await isolated.request('/api/trailer?id=1')).status,503);
assert.equal((await isolated.request('/api/search?q=test')).status,200,'a resting trailer source must not block search');
calls=0;
const permanent=createClient({gap:0,notify:()=>{},send:async()=>{calls++;return answer(400);}});
assert.equal((await permanent.request('/api/title',{method:'POST',body:'{}'})).status,400);
assert.equal(calls,1);
let active=0,peak=0,engines=0,enginePeak=0;
const queue=createClient({gap:0,notify:()=>{},send:async(path,options)=>{
  active++;peak=Math.max(peak,active);
  if(options.method==='POST'){engines++;enginePeak=Math.max(enginePeak,engines);}
  await new Promise(done=>setTimeout(done,5));
  active--;if(options.method==='POST')engines--;
  return answer();
}});
await Promise.all([...Array.from({length:8},(_,id)=>queue.request(`/api/extra?id=${id}`)),
  ...Array.from({length:6},(_,id)=>queue.request('/api/title',{method:'POST',body:JSON.stringify({id})}))]);
assert(peak<=4);assert(enginePeak<=2);
calls=0;
const sharing=createClient({gap:0,notify:()=>{},send:async()=>{calls++;await new Promise(done=>setTimeout(done,5));return answer();}});
const shared=await Promise.all([sharing.request('/api/extra?id=1'),sharing.request('/api/extra?id=1')]);
assert.equal(calls,1);
assert.deepEqual(await shared[0].json(),await shared[1].json());
let release,asked=[];
const cancellation=createClient({gap:0,maxActive:1,notify:()=>{},send:async path=>{
  asked.push(path);if(path==='/api/extra?id=1')await new Promise(done=>{release=done;});return answer();
}});
const first=cancellation.request('/api/extra?id=1');
await new Promise(done=>setTimeout(done,0));
const controller=new AbortController();
const second=cancellation.request('/api/extra?id=2',{signal:controller.signal});
controller.abort();
await assert.rejects(second,error=>error.name==='AbortError');
release();await first;
assert.deepEqual(asked,['/api/extra?id=1']);
calls=0;
const bodyRecovery=createClient({gap:0,notify:()=>{},sleep:async()=>{},send:async()=>{calls++;return calls===1?new Response('broken JSON'):answer();}});
assert.equal((await bodyRecovery.request('/api/home',{method:'POST',body:'{}'})).status,200);
assert.equal(calls,2);
console.log('Network queue, bounded retries, Retry-After, cancellation, shared responses and body recovery passed.');
