// Couchside's service worker: the app starts from what it keeps, and each image is
// fetched once.
//
// The page and its files are kept together under this build's stamp, each checked on the
// way in against what build.py wrote here, so what starts is always one build whole,
// never a page from one deploy with files from another, and it starts without waiting
// for the network. The page kept is fetched again as it is shown, and kept when it is
// still this build, so a refreshed catalogue's date and genres show on the next load. A
// deploy brings a new worker, which keeps its own build beside this one and takes over
// once the page that found it has loaded (main.js asks), so the next load is the new
// build. Away from the app's own pages, or before anything is kept, pages come from the
// network, and without a connection the offline page stands in.
//
// Posters, backdrops, stills and thumbnails outlive builds: cache first, fetched with
// CORS so every copy is readable (Chrome counts an opaque one as about 7 MB of quota),
// and the least recently used go once there are more than 1,000 small images or 40
// large ones, about 30 MB in all. One long scroll down the home page shows 350 posters.
const VERSION = '61278bb1a900';
const FILES = {"/assets/styles/style.css": "778e4abea46882ab", "/assets/scripts/main.js": "48ca59e673065720", "/assets/scripts/format.js": "7ac003cc28be3a47", "/assets/scripts/gestures.js": "c2173468ef22c30e", "/assets/scripts/start.js": "94868a66c8ad1095", "/assets/scripts/ratings.js": "70517fd9f1cddac1", "/assets/scripts/episode-ratings.js": "8440eeb3817e63af", "/assets/scripts/episode-timeline.js": "d5bd5f2216ee1dbd", "/assets/scripts/show-cards.js": "1cbaf89a306b5dd7", "/assets/scripts/title-sections.js": "c735de07fc7f1d99", "/assets/scripts/filter-state.js": "2a62eef7fd5aeeda", "/assets/scripts/filters.js": "a02e985fa09b92be", "/assets/scripts/network.js": "4038b4a1107593ef", "/assets/scripts/accounts.js": "f68e1951bdf329a9", "/assets/scripts/account-state.js": "8a7923884b155f21", "/assets/scripts/account-polling.js": "51e6158044c60f45", "/assets/scripts/features.js": "f67cf12dc64da47a", "/assets/scripts/watch-tracking.js": "e82d5b183ce1a83b", "/assets/scripts/watch-tracking-state.js": "2d55de94e424a726", "/assets/scripts/public-data.js": "52d95472a87de18c", "/assets/scripts/taste.js": "38f3f65aed9cad54", "/assets/scripts/list-transfer.js": "bf96d9f9d5d965e6", "/assets/scripts/compare.js": "db5ee2732b76a522", "/assets/scripts/comparison-timeline.js": "2d20603698429261", "/assets/scripts/compare-timeline-interactions.js": "2065733c29193432", "/assets/scripts/comparison-timeline-export.js": "813a00856f75b802", "/assets/scripts/poster-colours.js": "0a5c074f14836db9", "/assets/scripts/compare-posters.js": "76b3da553b4dd4e8", "/assets/scripts/compare-viewport.js": "caaae4ed372c3b78", "/assets/scripts/rating-views.js": "b273a6ffe2a54e91", "/assets/scripts/rating-snapshots.js": "23b291deea4b25ce", "/assets/scripts/snapshot-images.js": "58ed772a708f7e6c", "/assets/scripts/app-updates.js": "6fd21e40c7dc0bdb", "/assets/scripts/show-artwork.js": "919c7a8ac41304f6", "/assets/scripts/metadata.js": "61237fd7da1aa410", "/assets/scripts/transfer.js": "2bfd019beccdb78d", "/assets/scripts/qr.js": "d7f92f94bb8911ea", "/assets/scripts/fresh.js": "afcc972f76479400", "/assets/scripts/starters.js": "d559e3a61414a450", "/assets/scripts/touch-forms.js": "b396a8dd24140a5f", "/pages/offline.html": "7acd7be28caa3de5", "/assets/icons/favicon.svg": "8a7c0610bab9b7fc", "/assets/icons/icon-192.png": "72daa1f7f1066393", "/assets/images/tmdb.svg": "8e7b30f73a402069"};
const SHELL = `couchside-${VERSION}`;
const IMAGES = 'couchside-images';
// The app's own pages (PAGES in server.py): each is the one page, which routes itself.
const PAGES = ['/', '/index.html', '/new', '/list', '/search', '/browse', '/welcome', '/compare'];
const IMAGE_HOSTS = ['static.tvmaze.com', 'image.tmdb.org', 'i.ytimg.com'];
const MOST_SMALL = 1000, MOST_LARGE = 40;
const BACKDROP_TTL = 86400_000;
const CACHED_AT = 'X-Couchside-Cached-At';
// Load tests opt in through their own page. Counts contain no URLs or user data.
let testCounts = null;
const count = name => { if (testCounts) testCounts[name] = (testCounts[name] || 0) + 1; };
const backdrop = url => new URL(url).pathname === '/api/backdrop';
const bitmap = response => ['image/jpeg', 'image/png', 'image/webp'].includes(
  (response.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase());
// Full-size art and backdrops run to a few hundred KB each; posters, stills and logos to tens.
const large = url => backdrop(url) || /\/original_untouched\/|\/t\/p\/(w1280|original)\//.test(url);

self.addEventListener('install', event => event.waitUntil(keepBuild()));

// Nothing is kept until all of it checks out: each file must hash to what build.py wrote,
// and the page must say it is this build. A deploy landing midway fails the install, and
// the worker before this one carries on. Each file is asked for at the address that names
// its hash, which the server lets the browser keep, so the files the page has just loaded
// come from the browser's cache rather than over the network a second time; the page is
// always checked.
async function keepBuild() {
  const answers = await Promise.all(['/', ...Object.keys(FILES)].map(async path => {
    const response = await (path === '/' ? fetch(path, { cache: 'no-cache' }) : fetch(`${path}?v=${FILES[path]}`));
    const ours = response.ok && (path === '/' ? response.headers.get('X-Build') === VERSION
      : await digest(response.clone()) === FILES[path]);
    if (!ours) throw new Error(`${path} is not build ${VERSION}`);
    return [path, response];
  }));
  const cache = await caches.open(SHELL);
  await Promise.all(answers.map(([path, response]) => cache.put(path, response)));
}

// The first 16 hex digits of a body's SHA-256, as build.py writes them.
async function digest(response) {
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', await response.arrayBuffer()));
  return Array.from(hash.slice(0, 8), b => b.toString(16).padStart(2, '0')).join('');
}

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(key => key.startsWith('couchside-') && key !== SHELL && key !== IMAGES)
      .map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});

// main.js asks once its page has loaded everything it needs from the build before.
self.addEventListener('message', event => {
  if (event.data === 'take-over') self.skipWaiting();
  if (event.data?.type !== 'load-test-metrics' || !event.ports?.[0]) return;
  try {
    if (new URL(event.source?.url).origin !== self.location.origin) return;
  } catch { return; }
  if (event.data.enabled === true) testCounts ??= {};
  if (event.data.enabled === false) testCounts = null;
  event.ports[0].postMessage({ enabled: testCounts !== null, build: VERSION, counts: { ...testCounts } });
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin === self.location.origin) {
    if (request.mode === 'navigate') event.respondWith(PAGES.includes(url.pathname) ? page(event) : online(request));
    else if (FILES[url.pathname]) event.respondWith(file(request, url.pathname));
    else if (request.destination === 'image' && url.pathname === '/api/backdrop') event.respondWith(image(event, url.href));
  } else if (request.destination === 'image' && IMAGE_HOSTS.includes(url.hostname)) {
    event.respondWith(image(event, url.href));
  }
});

async function page(event) {
  const cache = await caches.open(SHELL);
  const kept = await cache.match('/');
  if (!kept) { count('shell_misses'); return online(event.request); }
  count('shell_hits');
  event.waitUntil(renew(cache, kept));
  return kept;
}

// The page again from the network, kept for the next load when it is still this build
// and has changed, as it does when the catalogue is refreshed.
async function renew(cache, kept) {
  try {
    const response = await fetch('/', { cache: 'no-cache' });
    if (response.ok && response.headers.get('X-Build') === VERSION
        && response.headers.get('ETag') !== kept.headers.get('ETag')) await cache.put('/', response);
  } catch { /* offline: the kept page stands */ }
}

const online = request => fetch(request).catch(() => caches.match('/pages/offline.html').then(hit => hit || Response.error()));

async function file(request, path) {
  const hit = await caches.match(path, { cacheName: SHELL });
  count(hit ? 'file_hits' : 'file_misses');
  return hit || fetch(request);
}

// When each image was last shown while this worker has been running; those it has not
// shown count as older still, oldest kept first.
const used = new Map();
const arriving = new Map();
const imageQueue = [];
let imageActive = 0;
function imageTurn(send, priority = false) {
  return new Promise((resolve,reject)=>{imageQueue.push({send,resolve,reject,priority});drainImages();});
}
function drainImages() {
  while(imageActive<6&&imageQueue.length){
    // A title's background should not wait behind a long row of queued posters.
    // Transfers already running keep their place; both kinds share the same cap.
    const priority = imageQueue.findIndex(job => job.priority);
    const job=imageQueue.splice(priority < 0 ? 0 : priority, 1)[0];imageActive++;
    Promise.resolve().then(job.send).then(job.resolve,job.reject).finally(()=>{imageActive--;drainImages();});
  }
}

async function image(event, url) {
  used.set(url, Date.now());
  let cache, stale = null;
  try {
    cache = await caches.open(IMAGES);
    const hit = await cache.match(url, { ignoreVary: true });
    if (hit && !backdrop(url)) { count('image_hits'); return hit; }
    if (hit?.status === 200 && bitmap(hit)) {
      // The route names a show, whose artwork can change with the catalogue. The
      // timestamp belongs to this stored copy and survives worker upgrades/reloads.
      const at = Number(hit.headers.get(CACHED_AT)), age = Date.now() - at;
      if (at > 0 && age >= 0 && age < BACKDROP_TTL) { count('image_hits'); return hit; }
      count('image_stale');
      stale = hit;
    }
  } catch {
    // Storage pressure must not prevent an available image from loading.
    cache = null;
  }
  count('image_misses');
  if(!arriving.has(url)) {
    const pending=imageTurn(()=>fetchImage(event,url,cache,stale),backdrop(url)).finally(()=>arriving.delete(url));
    arriving.set(url,pending);
  } else count('image_coalesced');
  return (await arriving.get(url)).clone();
}

async function fetchImage(event,url,cache,stale) {
  const { request } = event;
  const ownBackdrop = backdrop(url);
  let response;
  try {
    count('image_fetch_attempts');
    response = await fetch(ownBackdrop || request.mode === 'cors' ? request
      : new Request(url, { mode: 'cors', credentials: 'omit', referrerPolicy: 'no-referrer' }));
  } catch {
    count('image_fetch_errors');
    if (ownBackdrop && stale) { count('image_stale_served'); return stale; }
    if (ownBackdrop) return Response.error();
    // A host that refuses CORS, or no connection: the page's own request, and nothing kept.
    count('image_fetch_attempts');
    return fetch(request);
  }
  if (ownBackdrop && stale && (response.status >= 500 || response.status === 408 || response.status === 429)) {
    count('image_stale_served'); return stale;
  }
  if (cache && response.status === 200 && (!ownBackdrop || bitmap(response))) {
    let kept = response.clone();
    if (ownBackdrop) {
      const headers = new Headers(response.headers);
      headers.set(CACHED_AT, String(Date.now()));
      kept = new Response(kept.body, { status: response.status, statusText: response.statusText, headers });
    }
    event.waitUntil(cache.put(url, kept).then(trimSoon).catch(()=>{}));
  }
  return response;
}

// The least recently used images go a few seconds after new ones start arriving, once
// for the lot.
let trimming = null;
function trimSoon() {
  trimming ??= new Promise(done => setTimeout(done, 3000)).then(trim).finally(() => { trimming = null; });
  return trimming;
}
async function trim() {
  const cache = await caches.open(IMAGES);
  const keys = await cache.keys();
  const ranked = [...keys.filter(key => !used.has(key.url)),
    ...keys.filter(key => used.has(key.url)).sort((a, b) => used.get(a.url) - used.get(b.url))];
  const over = (big, most) => {
    const some = ranked.filter(key => large(key.url) === big);
    return some.slice(0, Math.max(0, some.length - most));
  };
  await Promise.all([...over(false, MOST_SMALL), ...over(true, MOST_LARGE)].map(key => cache.delete(key)));
}
