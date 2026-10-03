import assert from 'node:assert/strict';
import test from 'node:test';
import { createPollLeadership } from '../client/account-polling.js';
import { watchAccount } from '../client/accounts.js';
const memory = () => { const rows = new Map(); return { rows, getItem:key=>rows.get(key)||null, setItem:(key,value)=>rows.set(key,value),removeItem:key=>rows.delete(key) }; };
const channels = () => {
  const wires = new Map(), messages = [];
  return { messages, make(name) {
    const members = wires.get(name) || new Set(); wires.set(name,members);
    const wire = { onmessage:null, postMessage(data) { messages.push(data); for(const other of members)if(other!==wire)other.onmessage?.({data}); },close(){members.delete(wire);} };
    members.add(wire); return wire;
  } };
};

test('one polling leader per owner shares only hints, releases on hiding and separates accounts', async () => {
  const storage = memory(), bus = channels(), updates=[]; let now=0, calls=0;
  const one = createPollLeadership({storage,channel:bus.make,identity:'tab-one',clock:()=>now});
  const two = createPollLeadership({storage,channel:bus.make,identity:'tab-two',clock:()=>now,changed:data=>updates.push(data)});
  two.select('alice');
  await one.run('alice',60000,async()=>{calls++;});
  assert.equal(await two.run('alice',60000,async()=>{calls++;}),false);
  assert.equal(calls,1); assert.equal(updates.length,1);
  assert.deepEqual(Object.keys(bus.messages[0]).sort(),['at','owner','type'], 'no credentials or list data are broadcast');
  await two.run('bob',60000,async()=>{calls++;}); assert.equal(calls,2,'another owner has an independent lease');
  one.release(); await two.run('alice',60000,async()=>{calls++;}); assert.equal(calls,3,'the remaining visible tab takes over');
  now=200000; await one.run('alice',60000,async()=>{calls++;}); assert.equal(calls,4,'a dead tab cannot hold polling forever');
  one.release(); two.release();
});

test('unavailable local storage preserves authenticated checks instead of assuming a leader', async () => {
  let calls=0;
  const lead=createPollLeadership({storage:{getItem(){throw Error('Blocked');},setItem(){throw Error('Blocked');}},channel:()=>null});
  await lead.run('alice',60000,async()=>{calls++;}); assert.equal(calls,1); lead.release();
});

test('initial sessions always validate, steady polling adapts and hidden tabs release leadership', async () => {
  const storage=memory(),bus=channels(),doc=new EventTarget(),win=new EventTarget(),timers=new Map();
  doc.visibilityState='visible'; let now=0,id=0,reads=0,initial=0;
  const sync={storage,user:{id:'alice'},revision:1,connected:true,status:'saved',pending:false,
    ready:async()=>{initial++;},refresh:async()=>{reads++;},storageChanged:async()=>{}};
  const lead=createPollLeadership({storage,channel:bus.make,clock:()=>now,identity:'one'});
  const stop=watchAccount(sync,{doc,win,clock:()=>now,random:()=>.5,leadership:lead,
    setTimer:(run,delay)=>{timers.set(++id,{run,at:now+delay});return id;},clearTimer:key=>timers.delete(key)});
  const settle=()=>new Promise(resolve=>setImmediate(resolve));
  const advance=async delay=>{now+=delay;for(const [key,timer] of [...timers])if(timer.at<=now){timers.delete(key);timer.run();}await settle();};
  await settle(); assert.equal(initial,1);
  await advance(60000); assert.equal(reads,1); assert.equal([...timers.values()][0].at-now,120000);
  await advance(120000); assert.equal(reads,2); assert.equal([...timers.values()][0].at-now,180000);
  sync.pending=true; win.dispatchEvent(new Event('focus')); await settle();
  assert.equal([...timers.values()][0].at-now,60000,'pending edits and fresh foreground interaction return to the active interval');
  doc.visibilityState='hidden';doc.dispatchEvent(new Event('visibilitychange'));
  assert.equal(timers.size,0);assert.equal(storage.rows.size,0);
  stop();
});
