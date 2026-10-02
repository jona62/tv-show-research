// All API reads share a small queue, fixed pacing and capped retries. POST routes
// here compute answers from the supplied list; they do not mutate server data.
const READ_POSTS = new Set(['/api/home','/api/title','/api/browse','/api/shows','/api/taste']);
const TRANSIENT = new Set([408,429,500,502,503,504]);
const abortError = () => new DOMException('The request was cancelled.','AbortError');
export function retryDelay(value, now=Date.now()) {
  if (!value) return 0;
  const seconds=Number(value);
  const delay=Number.isFinite(seconds)?seconds*1000:Date.parse(value)-now;
  return Number.isFinite(delay)?Math.max(0,delay):0;
}
const emit = detail => {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('couchside-network',{detail}));
};
export function createClient({send=(...args)=>fetch(...args),now=()=>Date.now(),random=Math.random,
  sleep=ms=>new Promise(done=>setTimeout(done,ms)),notify=emit,maxActive=4,gap=75,budget=30000}={}) {
  const queue=[],shared=new Map(),failed=new Map(),rests=new Map();
  let active=0,engineActive=0,next=0,pause=0,timer=null,recovery=null,round=0;
  const engine = path => READ_POSTS.has(path);
  const resting = path => Math.max(pause,rests.get(path.split('?')[0])||0);
  const recoveryLater = () => {
    if(recovery||round>=3||!failed.size||globalThis.navigator?.onLine===false)return;
    recovery=setTimeout(()=>{
      recovery=null;
      const paths=[...failed.values()].filter(path=>resting(path)<=now());
      if(paths.length){round++;notify({state:'recover',paths});}
      recoveryLater();
    },Math.min(2147483647,Math.max(15000*2**round,Math.min(...[...failed.values()].map(path=>resting(path)-now())))+random()*1000));
    recovery.unref?.();
  };
  function pump() {
    clearTimeout(timer);timer=null;
    if(!queue.length||active>=maxActive)return;
    const eligible=queue.filter(job=>!job.engine||engineActive<2);
    if(!eligible.length)return;
    const index=queue.findIndex(job=>(!job.engine||engineActive<2)&&resting(job.path)<=now());
    const delay=Math.max(next,pause,index<0?Math.min(...eligible.map(job=>resting(job.path))):0)-now();
    if(delay>0){timer=setTimeout(pump,Math.min(delay,1000));return;}
    const job=queue.splice(index,1)[0];
    job.detach();
    if(job.signal?.aborted){job.reject(abortError());pump();return;}
    active++;if(job.engine)engineActive++;
    next=now()+gap;
    Promise.resolve().then(job.send).then(job.resolve,job.reject).finally(()=>{
      active--;if(job.engine)engineActive--;
      pump();
    });
    pump();
  }
  const enqueue = (path,options) => new Promise((resolve,reject)=>{
    if(options.signal?.aborted){reject(abortError());return;}
    if(queue.length>=80){const error=Error('Requests are catching up.');error.status=429;reject(error);return;}
    let job;
    const cancel=()=>{const index=queue.indexOf(job);if(index>=0)queue.splice(index,1);job.detach();reject(abortError());pump();};
    job={path,send:()=>send(path,options),engine:engine(path.split('?')[0]),signal:options.signal,resolve,reject,
      detach:()=>options.signal?.removeEventListener('abort',cancel)};
    options.signal?.addEventListener('abort',cancel,{once:true});
    queue.push(job);pump();
  });
  async function run(path,options,key) {
    const safe=(options.method||'GET')==='GET'||READ_POSTS.has(path.split('?')[0]);
    const deadline=now()+budget;
    let response,error,interrupted=false;
    for(let attempt=0;attempt<(safe?3:1);attempt++) {
      if(options.signal?.aborted)throw abortError();
      const remaining=deadline-now();
      if(remaining<=0)break;
      const controller=new AbortController();
      const cancel=()=>controller.abort();
      options.signal?.addEventListener('abort',cancel,{once:true});
      const timeout=setTimeout(()=>controller.abort(),remaining);
      try {
        response=await enqueue(path,{...options,signal:controller.signal});
        // Read now so a dropped connection halfway through JSON can also recover.
        if(response.ok)await response.clone().json();
        if(!TRANSIENT.has(response.status)) {
          if(response.ok){const recovering=failed.delete(key);if(recovering||interrupted)notify({state:'restored',path});}
          else failed.delete(key);
          if(!failed.size){round=0;clearTimeout(recovery);recovery=null;}
          return response;
        }
        const asked=retryDelay(response.headers.get('Retry-After'),now());
        if(response.status===429)pause=Math.max(pause,now()+asked);
        else if(asked)rests.set(path.split('?')[0],now()+asked);
        error=Error('Couchside is temporarily busy.');error.status=response.status;
      } catch(caught) {
        if(options.signal?.aborted)throw abortError();
        error=caught;response=null;
      } finally {
        clearTimeout(timeout);options.signal?.removeEventListener('abort',cancel);
      }
      if(attempt<2&&safe) {
        interrupted=true;
        notify({state:globalThis.navigator?.onLine===false?'offline':'retrying',path});
        const delay=Math.max(500*2**attempt+random()*500,resting(path)-now());
        if(delay>=deadline-now())break;
        await sleep(delay);
      }
    }
    failed.set(key,path);
    while(failed.size>128)failed.delete(failed.keys().next().value);
    notify({state:'failed',path});recoveryLater();
    if(response)return response;
    if(error?.name==='AbortError')error=Error('Couchside took too long to respond.');
    throw error||Error('Couchside could not be reached.');
  }
  function request(path,options={}) {
    const key=JSON.stringify([path,options.method||'GET',options.body||'']);
    // A caller's cancellation must never cancel another reader's shared lookup.
    if(options.signal)return run(path,options,key);
    if(!shared.has(key)){
      const promise=run(path,options,key).finally(()=>shared.delete(key));
      shared.set(key,promise);
    }
    return shared.get(key).then(response=>response.clone());
  }
  return {request,recover(){round=0;notify({state:'recover',paths:[...failed.values()]});recoveryLater();}};
}
const sharedClient=createClient();
export const apiFetch=(path,options)=>sharedClient.request(path,options);
if(typeof window!=='undefined')window.addEventListener('online',()=>sharedClient.recover());
