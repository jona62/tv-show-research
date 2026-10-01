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
const VERSION = 'a83b5bfa9ea1';
const FILES = {"/style.css": "88c94422136e3262", "/main.js": "816f6e2421fb1998", "/format.js": "e565cc65c0882a95", "/gestures.js": "c2173468ef22c30e", "/start.js": "5402c4619b384072", "/ratings.js": "bd9d1b3ac9a562f7", "/episode-ratings.js": "a6849b3dcf8c367f", "/show-cards.js": "688ac95280287779", "/title-sections.js": "47e93fa931aed0c8", "/filter-state.js": "a30d1a4517a72575", "/filters.js": "7194f66a7f854167", "/transfer.js": "aca34fe2830e9d29", "/qr.js": "d7f92f94bb8911ea", "/fresh.js": "afcc972f76479400", "/starters.js": "d559e3a61414a450", "/offline.html": "ba13942a61d9aa1f", "/favicon.svg": "ec98a59b577360e9", "/icon-192.png": "badf05b3c8dbb5e7", "/tmdb.svg": "8e7b30f73a402069"};
const SHELL = `couchside-${VERSION}`;
const IMAGES = 'couchside-images';
// The app's own pages (PAGES in server.py): each is the one page, which routes itself.
const PAGES = ['/', '/index.html', '/new', '/list', '/search', '/browse', '/welcome'];
const IMAGE_HOSTS = ['static.tvmaze.com', 'image.tmdb.org', 'i.ytimg.com'];
const MOST_SMALL = 1000, MOST_LARGE = 40;
// Full-size art and backdrops run to a few hundred KB each; posters, stills and logos to tens.
const large = url => /\/original_untouched\/|\/t\/p\/(w1280|original)\//.test(url);

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
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin === self.location.origin) {
    if (request.mode === 'navigate') event.respondWith(PAGES.includes(url.pathname) ? page(event) : online(request));
    else if (FILES[url.pathname]) event.respondWith(file(request, url.pathname));
  } else if (request.destination === 'image' && IMAGE_HOSTS.includes(url.hostname)) {
    event.respondWith(image(event, url.href));
  }
});

async function page(event) {
  const cache = await caches.open(SHELL);
  const kept = await cache.match('/');
  if (!kept) return online(event.request);
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

const online = request => fetch(request).catch(() => caches.match('/offline.html').then(hit => hit || Response.error()));

async function file(request, path) {
  return (await caches.match(path, { cacheName: SHELL })) || fetch(request);
}

// When each image was last shown while this worker has been running; those it has not
// shown count as older still, oldest kept first.
const used = new Map();

async function image(event, url) {
  used.set(url, Date.now());
  const cache = await caches.open(IMAGES);
  const hit = await cache.match(url, { ignoreVary: true });
  if (hit) return hit;
  const { request } = event;
  let response;
  try {
    response = await fetch(request.mode === 'cors' ? request
      : new Request(url, { mode: 'cors', credentials: 'omit', referrerPolicy: 'no-referrer' }));
  } catch {
    // A host that refuses CORS, or no connection: the page's own request, and nothing kept.
    return fetch(request);
  }
  if (response.status === 200) event.waitUntil(cache.put(url, response.clone()).then(trimSoon));
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
