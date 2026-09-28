// What the browser remembers so each day's picks can be fresh: which titles it showed,
// on which days, and which you engaged with. It stays in this browser; requests carry
// only a decayed count per title (halving every seven days), the ids engaged with in
// the last fourteen days, recent heroes, and rows passed over, plus the day and a seed
// derived from the day and a salt that is never sent. Shared by Next Watch and
// Couchside; fresh.py on the server reads what this sends.
//
// A title counts as seen when at least half of it is on screen for one continuous
// second while the tab is visible, at most once a day (YouTube's and the MRC's rule).

export const ROLLOVER_HOURS = 4;      // a day ends at 04:00 local time
export const HALF_LIFE = 7;           // days
export const KEEP_DAYS = 56;
export const KEEP_TITLES = 500;
export const DAYS_PER_TITLE = 10;
export const SEND_TITLES = 300;
export const ENGAGED_DAYS = 14;
export const HERO_REST = 7;           // a hero is not shown again for this many days
export const TIRED_AFTER = 5;         // row days without engagement before a row rests
export const TIRED_WINDOW = 14;
export const TIRED_REST = 7;

const MS_PER_DAY = 86_400_000;

// The local date, rolling over at 04:00, as YYYY-MM-DD.
export function today(now = new Date()) {
  const shifted = new Date(now.getTime() - ROLLOVER_HOURS * 3_600_000);
  const pad = n => String(n).padStart(2, '0');
  return `${shifted.getFullYear()}-${pad(shifted.getMonth() + 1)}-${pad(shifted.getDate())}`;
}

// Whole days since 1970-01-01 for a YYYY-MM-DD day.
export const dayNumber = day => Math.round(Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10)) / MS_PER_DAY);

export function freshStore(raw) {
  const store = raw && typeof raw === 'object' && raw.v === 1 ? raw : {};
  const salt = typeof store.salt === 'string' && /^[0-9a-f]{32}$/.test(store.salt) ? store.salt : newSalt();
  const titles = {}, rows = {}, heroes = {};
  for (const [id, t] of Object.entries(store.titles || {})) {
    if (!/^\d{1,9}$/.test(id) || !t || typeof t !== 'object') continue;
    const d = (Array.isArray(t.d) ? t.d : []).filter(Number.isInteger).slice(-DAYS_PER_TITLE);
    const e = Number.isInteger(t.e) ? t.e : null;
    if (d.length || e !== null) titles[id] = { d, e };
  }
  for (const [key, r] of Object.entries(store.rows || {})) {
    if (!/^[a-z0-9-]{1,60}$/.test(key) || !r || typeof r !== 'object') continue;
    rows[key] = { d: (Array.isArray(r.d) ? r.d : []).filter(Number.isInteger).slice(-TIRED_WINDOW),
                  e: Number.isInteger(r.e) ? r.e : null };
  }
  for (const [day, id] of Object.entries(store.heroes || {})) {
    if (/^\d{1,6}$/.test(day) && Number.isInteger(id)) heroes[day] = id;
  }
  return { v: 1, salt, titles, rows, heroes };
}

export function newSalt() {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
}

// The day's seed: the first 16 hex digits of SHA-256(salt | day). The salt never leaves
// the browser, so two days' seeds cannot be linked to each other or to a person.
export async function seedFor(salt, day) {
  const data = new TextEncoder().encode(`${salt}|${day}`);
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', data));
  return [...digest.slice(0, 8)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export function noteSeen(store, id, day) {
  const n = dayNumber(day);
  const t = store.titles[id] || (store.titles[id] = { d: [], e: null });
  if (!t.d.includes(n)) {
    t.d.push(n);
    if (t.d.length > DAYS_PER_TITLE) t.d.splice(0, t.d.length - DAYS_PER_TITLE);
  }
}

export function noteEngaged(store, id, day) {
  const t = store.titles[id] || (store.titles[id] = { d: [], e: null });
  t.e = dayNumber(day);
}

export function noteRow(store, key, day, engaged = false) {
  const n = dayNumber(day);
  const r = store.rows[key] || (store.rows[key] = { d: [], e: null });
  if (!r.d.includes(n)) r.d.push(n);
  if (r.d.length > TIRED_WINDOW) r.d.splice(0, r.d.length - TIRED_WINDOW);
  if (engaged) r.e = n;
}

export function noteHero(store, id, day) { store.heroes[String(dayNumber(day))] = id; }

// Forget days older than KEEP_DAYS and, past KEEP_TITLES, the titles seen longest ago.
export function prune(store, day) {
  const now = dayNumber(day), oldest = now - KEEP_DAYS;
  for (const [id, t] of Object.entries(store.titles)) {
    t.d = t.d.filter(n => n >= oldest);
    if (t.e !== null && t.e < oldest) t.e = null;
    if (!t.d.length && t.e === null) delete store.titles[id];
  }
  const ids = Object.keys(store.titles);
  if (ids.length > KEEP_TITLES) {
    const last = id => Math.max(store.titles[id].e ?? -Infinity, ...store.titles[id].d, -Infinity);
    ids.sort((a, b) => last(a) - last(b));
    for (const id of ids.slice(0, ids.length - KEEP_TITLES)) delete store.titles[id];
  }
  for (const [key, r] of Object.entries(store.rows)) {
    r.d = r.d.filter(n => n >= now - TIRED_WINDOW - TIRED_REST);
    if (!r.d.length) delete store.rows[key];
  }
  for (const k of Object.keys(store.heroes)) if (+k < now - KEEP_DAYS) delete store.heroes[k];
  return store;
}

// A title's decayed count of days shown before today: nothing moves within a day.
export function decayed(t, now) {
  return t.d.filter(n => n < now).reduce((sum, n) => sum + 0.5 ** ((now - n) / HALF_LIFE), 0);
}

// What a request carries: the day, its seed, and the store reduced to what fresh.py reads.
export async function freshness(store, day) {
  const now = dayNumber(day);
  const seen = [];
  const engaged = [];
  for (const [id, t] of Object.entries(store.titles)) {
    if (t.e !== null && t.e >= now - ENGAGED_DAYS) engaged.push(+id);
    else {
      const n = Math.round(decayed(t, now) * 10) / 10;
      if (n >= 0.1) seen.push([id, Math.min(n, 50)]);
    }
  }
  seen.sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  const resting = Object.entries(store.heroes)
    .filter(([k]) => +k < now && +k >= now - HERO_REST).map(([, id]) => id);
  const tired = Object.entries(store.rows).filter(([, r]) => {
    const recent = r.d.filter(n => n < now && n >= now - TIRED_WINDOW);
    const engagedLately = r.e !== null && r.e >= now - TIRED_WINDOW;
    const restingSince = recent.length >= TIRED_AFTER ? recent[TIRED_AFTER - 1] : null;
    return !engagedLately && restingSince !== null && now - restingSince <= TIRED_REST;
  }).map(([key]) => key);
  return {
    day, seed: await seedFor(store.salt, day),
    seen: Object.fromEntries(seen.slice(0, SEND_TITLES)),
    engaged: engaged.slice(-300), resting: [...new Set(resting)].slice(-60), tired: tired.slice(0, 40),
  };
}

// Watch elements for the one-second, half-visible rule; onSeen(id) fires at most once
// per element. Returns observe(element, id) and a stop() for tearing down.
export function watcher(onSeen, { threshold = 0.5, dwell = 1000 } = {}) {
  if (typeof IntersectionObserver === 'undefined') return { observe() {}, stop() {} };
  const timers = new Map(), ids = new WeakMap(), done = new WeakSet();
  const visible = () => document.visibilityState === 'visible';
  const io = new IntersectionObserver(entries => {
    for (const entry of entries) {
      const el = entry.target;
      if (done.has(el)) continue;
      if (entry.isIntersecting && entry.intersectionRatio >= threshold && visible()) {
        if (!timers.has(el)) timers.set(el, setTimeout(() => {
          timers.delete(el);
          if (!el.isConnected || !visible()) return;
          done.add(el);
          io.unobserve(el);
          onSeen(ids.get(el));
        }, dwell));
      } else if (timers.has(el)) {
        clearTimeout(timers.get(el));
        timers.delete(el);
      }
    }
  }, { threshold: [0, threshold, 1] });
  document.addEventListener('visibilitychange', () => {
    if (!visible()) { for (const t of timers.values()) clearTimeout(t); timers.clear(); }
  });
  return {
    observe(el, id) { if (!done.has(el)) { ids.set(el, id); io.observe(el); } },
    stop() { io.disconnect(); for (const t of timers.values()) clearTimeout(t); timers.clear(); },
  };
}
