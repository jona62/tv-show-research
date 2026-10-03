// This cache accepts public show cards and complete episode ratings only. Account
// state and personalised recommendations never enter its storage or request keys.
import { apiFetch } from './network.js?v=4038b4a1107593ef';
const SCHEMA = 1, TTL = 300000, DB = 'couchside-public-data-v1';
const validId = id => Number.isInteger(id) && id > 0 && id <= 2147483647;
const fields = (value, names) => Object.fromEntries(names.filter(key => Object.hasOwn(value, key) &&
  (value[key] == null || ['string', 'number', 'boolean'].includes(typeof value[key]) ||
   key === 'genres' && Array.isArray(value[key]) && value[key].every(item => typeof item === 'string')))
  .map(key => [key, value[key]]));
export function publicRecord(kind, value) {
  if (!value || !validId(value.id)) return null;
  if (kind === 'card') {
    if (typeof value.name !== 'string') return null;
    return fields(value, ['id', 'name', 'year', 'poster', 'art', 'genres', 'runtime', 'type', 'summary', 'badge', 'rank', 'status', 'language']);
  }
  if (kind !== 'ratings' || !Array.isArray(value.episodes) || value.episodes.length > 50000) return null;
  const episodes = [];
  for (const episode of value.episodes) {
    // A compact matrix cannot stand in for a complete record (hover and export
    // use episode identity, summary and imagery). Empty completed shows are valid.
    if (!episode || !validId(episode.id) || !Number.isInteger(episode.season) || episode.season <= 0 ||
        !Number.isInteger(episode.number) || episode.number <= 0 ||
        !(episode.rating == null || Number.isFinite(episode.rating) && episode.rating >= 0 && episode.rating <= 10)) return null;
    episodes.push(fields(episode, ['id', 'season', 'number', 'name', 'rating', 'rating_source', 'rating_votes',
      'image', 'summary', 'airdate', 'airtime', 'runtime', 'url']));
  }
  return { ...fields(value, ['id', 'sources', 'refreshing', 'dataVersion', 'revision', 'fetchedAt', 'expiresAt']), episodes };
}

// Storage failures are ordinary cache misses; the network and in-memory cache
// remain usable in private browsing, under quota pressure and after corruption.
export function indexedPublicStorage(indexed = globalThis.indexedDB) {
  let opening;
  const open = () => opening ||= new Promise((resolve, reject) => {
    if (!indexed) { resolve(null); return; }
    const request = indexed.open(DB, SCHEMA);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (db.objectStoreNames.contains('entries')) db.deleteObjectStore('entries');
      db.createObjectStore('entries', { keyPath: 'key' });
    };
    request.onsuccess = () => { request.result.onversionchange = () => { request.result.close(); opening = null; }; resolve(request.result); };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(Error('Public cache is unavailable.'));
  }).catch(() => null);
  const transaction = async (mode, operation) => {
    const db = await open(); if (!db) return null;
    return new Promise((resolve, reject) => {
      const tx = db.transaction('entries', mode), store = tx.objectStore('entries');
      let value;
      tx.oncomplete = () => resolve(value);
      tx.onerror = tx.onabort = () => reject(tx.error || Error('Public cache is unavailable.'));
      operation(store, result => { value = result; });
    });
  };
  return {
    read: key => transaction('readonly', (store, done) => { const request = store.get(key); request.onsuccess = () => done(request.result); }),
    async write(entries, bytes, count) {
      const save = () => transaction('readwrite', (store) => {
        for (const entry of entries) store.put(entry);
        const request = store.getAll();
        request.onsuccess = () => {
          const rows = request.result.sort((a, b) => b.at - a.at); let used = 0;
          rows.forEach((row, index) => { used += Number(row.bytes) || bytes;
            if (index >= count || used > bytes || entries[0]?.version && row.version !== entries[0].version) store.delete(row.key); });
        };
      });
      try { await save(); } catch {
        // Only this disposable public cache is cleared; private account storage
        // and the image service-worker cache are separate and stay untouched.
        await transaction('readwrite', store => store.clear()).catch(() => {});
        await save().catch(() => {});
      }
    },
  };
}

export function createPublicDataCache({ storage = indexedPublicStorage(), now = Date.now,
  maxBytes = 20 * 1024 * 1024, maxRecords = 600, ttl = TTL } = {}) {
  const memory = new Map();
  const acceptable = (entry, kind, id) => entry?.schema === SCHEMA && entry.key === `${kind}:${id}` &&
    Number.isFinite(entry.at) && entry.at <= now() + 5000 && now() - entry.at < ttl &&
    Number.isFinite(entry.expires) && entry.expires > now() &&
    Number.isFinite(entry.bytes) && entry.bytes > 0 && entry.bytes <= maxBytes &&
    typeof entry.version === 'string' && publicRecord(kind, entry.value) && entry.value.refreshing !== true;
  function trim() {
    let used = 0;
    for (const [index, [key, entry]] of [...memory].reverse().entries()) {
      used += entry.bytes;
      if (used > maxBytes || index >= maxRecords) memory.delete(key);
    }
  }
  return {
    async get(kind, id) {
      if (!['card', 'ratings'].includes(kind) || !validId(id)) return null;
      const key = `${kind}:${id}`;
      let entry = memory.get(key);
      if (!entry) try { entry = await storage.read(key); } catch { /* cache miss */ }
      if (!acceptable(entry, kind, id)) { memory.delete(key); return null; }
      memory.delete(key); memory.set(key, entry); trim();
      return publicRecord(kind, entry.value);
    },
    async put(kind, values, version = '') {
      if (!['card', 'ratings'].includes(kind)) return;
      const entries = [];
      if (version) for (const [key, held] of memory) if (held.version !== String(version)) memory.delete(key);
      for (const raw of values) {
        const value = publicRecord(kind, raw);
        if (!value || value.refreshing === true) continue;
        const expires = Math.min(now() + ttl, Number.isFinite(value.expiresAt) ? value.expiresAt * 1000 : Infinity);
        if (expires <= now()) continue;
        const entry = { key: `${kind}:${value.id}`, schema: SCHEMA, at: now(), expires, version: String(version), value };
        entry.bytes = JSON.stringify(entry).length * 2;
        if (entry.bytes > maxBytes) continue;
        const held = memory.get(entry.key);
        if (held && Number.isFinite(value.fetchedAt) && held.value.fetchedAt > value.fetchedAt) continue;
        memory.delete(entry.key); memory.set(entry.key, entry); entries.push(entry);
      }
      trim();
      if (entries.length) try { await storage.write(entries, maxBytes, maxRecords); } catch { /* memory still works */ }
    },
  };
}

export function createPublicReader({ cache = createPublicDataCache(), fetcher = apiFetch, schedule = setTimeout,
  cancel = clearTimeout, now = Date.now, visible = () => globalThis.document?.hidden !== true,
  random = Math.random } = {}) {
  const flights = new Map(), queued = new Map(), refreshes = new Map(), retries = new Set(), pendingJobs = new Map();
  let timer, disposed = false;
  const routes = { card: '/api/show-cards', ratings: '/api/episode-ratings-batch' };
  function retryJobs(jobs, delay) {
    const retryTimer = schedule(() => {
      retries.delete(retryTimer);
      if (disposed) return;
      if (!visible()) { jobs.forEach(job => { job.started = now(); }); retryJobs(jobs, 5000); return; }
      for (const job of jobs) queued.set(job.key, job);
      if (!timer) timer = schedule(drain, 15);
    }, delay);
    retries.add(retryTimer); retryTimer?.unref?.();
  }
  async function loadBatch(kind, jobs) {
    const ids = jobs.map(job => job.id).sort((a, b) => a - b);
    try {
      const response = await fetcher(`${routes[kind]}?ids=${ids.join(',')}`), body = await response.json();
      if (!response.ok || !Array.isArray(body.shows)) throw Error(body.error || 'Shows are unavailable. Try again.');
      const values = new Map(body.shows.map(value => [value.id, publicRecord(kind, value)])), retry = [];
      await cache.put(kind, [...values.values()].filter(Boolean), body.catalogueVersion || body.dataVersion || '');
      for (const job of jobs) {
        const value = values.get(job.id);
        if (value) job.resolve(value);
        else if (body.pending?.includes(job.id) && now() - job.started < 120000) { job.attempts++; retry.push(job); }
        else { const error = Error('This show is unavailable. Try again in a moment.'); error.missing = body.missing?.includes(job.id); job.reject(error); }
      }
      if (retry.length) retryJobs(retry, Math.min(15000, 1000 * 2 ** Math.min(retry[0].attempts, 4)) * (.9 + random() * .2));
      for (const job of jobs) if (!retry.includes(job)) { flights.delete(job.key); pendingJobs.delete(job.key); }
    } catch (error) { jobs.forEach(job => { flights.delete(job.key); pendingJobs.delete(job.key); job.reject(error); }); }
  }
  async function drain() {
    timer = null;
    const batches = [];
    for (const kind of Object.keys(routes)) {
      const waiting = [...queued.values()].filter(job => job.kind === kind);
      for (let start = 0; start < waiting.length; start += 40) {
        const jobs = waiting.slice(start, start + 40);
        jobs.forEach(job => queued.delete(job.key)); batches.push(loadBatch(kind, jobs));
      }
    }
    await Promise.all(batches);
    if (queued.size && !timer) timer = schedule(drain, 15);
  }
  function read(kind, id) {
    if (disposed) return Promise.reject(Error('Public data reader was closed.'));
    if (!routes[kind] || !validId(id)) return Promise.reject(Error('Choose a valid show.'));
    const key = `${kind}:${id}`;
    if (!flights.has(key)) {
      const pending = cache.get(kind, id).then(value => {
        if (disposed) throw Error('Public data reader was closed.');
        if (value) { flights.delete(key); return value; }
        return new Promise((resolve, reject) => {
          const job = { key, kind, id, resolve, reject, started: now(), attempts: 0 };
          queued.set(key, job); pendingJobs.set(key, job);
          if (!timer) timer = schedule(drain, 15);
        });
      });
      flights.set(key, pending);
    }
    // No caller owns cancellation of shared public work. Consumers reject late
    // generations in their own view, without cancelling other readers.
    return flights.get(key);
  }
  function stopFollowing(id) {
    const state = refreshes.get(id);
    if (state) cancel(state.timer);
    refreshes.delete(id);
  }
  function follow(id, run, expired = () => {}, wanted = () => true) {
    if (refreshes.has(id)) return;
    const state = { started: now(), attempts: 0, timer: null };
    refreshes.set(id, state);
    const turn = async () => {
      if (refreshes.get(id) !== state) return;
      const active = visible() && wanted(id);
      if (!active) state.started = now();
      if (now() - state.started > 120000) { stopFollowing(id); expired(id); return; }
      if (active) {
        try {
          const again = await run(id);
          if (refreshes.get(id) !== state) return;
          if (!again) { stopFollowing(id); return; }
        } catch { /* bounded retry */ }
        if (refreshes.get(id) !== state) return;
        state.attempts++;
      }
      state.timer = schedule(turn, Math.min(30000, 4000 * 2 ** Math.min(state.attempts, 3)) * (.9 + random() * .2));
      state.timer?.unref?.();
    };
    state.timer = schedule(turn, 4000 * (.9 + random() * .2)); state.timer?.unref?.();
  }
  return { read, follow, stopFollowing, cache, dispose() {
    disposed = true; cancel(timer); for (const handle of retries) cancel(handle); retries.clear();
    for (const job of pendingJobs.values()) job.reject(Error('Public data reader was closed.'));
    pendingJobs.clear(); queued.clear(); flights.clear();
    for (const state of refreshes.values()) cancel(state.timer); refreshes.clear();
  } };
}
export const publicData = createPublicReader();
export const showCard = id => publicData.read('card', id);
export const fullRatings = id => publicData.read('ratings', id);
