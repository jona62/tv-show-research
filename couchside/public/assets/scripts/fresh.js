// What the browser remembers so each day's picks can be fresh: which titles it showed,
// on which days, and which you engaged with. It stays in this browser; requests carry
// only a decayed count per title (halving every seven days), the ids engaged with in
// the last fourteen days, recent heroes, and rows passed over, plus the day and a seed
// derived from the day and a salt that is never sent. Shared by Next Watch and
// Couchside; fresh.py on the server reads what this sends.
//
// A title counts as seen when at least half of it is on screen for one continuous
// second while the tab is visible, at most once a day (YouTube's and the MRC's rule).
//
// Couchside also counts visits, the times the app is opened in a day (beginVisit), and
// its requests carry the visit's own seed as well. For a visit, each earlier visit the
// same day that showed a title, among its cards or as its hero, counts half a day's
// showing, a whole day's at most, since by the next day that day counts as one; and
// every hero shown earlier the same day rests, as the first hero of each of the last
// week's days does.

export const ROLLOVER_HOURS = 4;      // a day ends at 04:00 local time
export const HALF_LIFE = 7;           // days
export const KEEP_DAYS = 56;
export const KEEP_TITLES = 500;
export const DAYS_PER_TITLE = 10;
export const SEND_TITLES = 300;
export const ENGAGED_DAYS = 14;
export const HERO_REST = 7;           // a hero is not shown again for this many days
export const HEROES_A_DAY = 60;       // heroes kept for a day, which all rest until it ends
export const TIRED_AFTER = 5;         // row days without engagement before a row rests
export const TIRED_WINDOW = 14;
export const TIRED_REST = 7;
export const EARLIER_SHARE = 0.5;     // of a day's showing, for each earlier visit the same day
export const EARLIER_MOST = 2;        // earlier visits counted, a whole day's showing

const MS_PER_DAY = 86_400_000;

// The local date, rolling over at 04:00, as YYYY-MM-DD.
export function today(now = new Date()) {
  const shifted = new Date(now.getTime() - ROLLOVER_HOURS * 3_600_000);
  const pad = n => String(n).padStart(2, '0');
  return `${shifted.getFullYear()}-${pad(shifted.getMonth() + 1)}-${pad(shifted.getDate())}`;
}

// Whole days since 1970-01-01 for a YYYY-MM-DD day.
export const dayNumber = day => Math.round(Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10)) / MS_PER_DAY);

// A title: d, the days it was seen on; e, the day it was last engaged with; and, once
// seen on a counted visit, v, the visits of its latest day it was seen on, the last few.
// A day's heroes are kept in the order they were shown, and visits as the day they were
// counted for and how many it has had.
export function freshStore(raw) {
  const store = raw && typeof raw === 'object' && raw.v === 1 ? raw : {};
  const salt = typeof store.salt === 'string' && /^[0-9a-f]{32}$/.test(store.salt) ? store.salt : newSalt();
  const titles = {}, rows = {}, heroes = {};
  const count = n => Number.isInteger(n) && n > 0;
  for (const [id, t] of Object.entries(store.titles || {})) {
    if (!/^\d{1,9}$/.test(id) || !t || typeof t !== 'object') continue;
    const d = (Array.isArray(t.d) ? t.d : []).filter(Number.isInteger).slice(-DAYS_PER_TITLE);
    const e = Number.isInteger(t.e) ? t.e : null;
    const v = (Array.isArray(t.v) ? t.v : []).filter(count).slice(-EARLIER_MOST);
    if (d.length || e !== null) titles[id] = v.length && d.length ? { d, e, v } : { d, e };
  }
  for (const [key, r] of Object.entries(store.rows || {})) {
    if (!/^[a-z0-9-]{1,60}$/.test(key) || !r || typeof r !== 'object') continue;
    rows[key] = { d: (Array.isArray(r.d) ? r.d : []).filter(Number.isInteger).slice(-TIRED_WINDOW),
                  e: Number.isInteger(r.e) ? r.e : null };
  }
  // A day's hero was once a single id.
  for (const [day, ids] of Object.entries(store.heroes || {})) {
    const kept = [...new Set((Array.isArray(ids) ? ids : [ids]).filter(Number.isInteger))].slice(0, HEROES_A_DAY);
    if (/^\d{1,6}$/.test(day) && kept.length) heroes[day] = kept;
  }
  const visits = store.visits && Number.isInteger(store.visits.d) && Number.isInteger(store.visits.n)
    && store.visits.n >= 0 ? { d: store.visits.d, n: store.visits.n } : { d: 0, n: 0 };
  return { v: 1, salt, titles, rows, heroes, visits };
}

// The memory another tab wrote (stored) with this tab's (mine) joined in: every day a
// title or row was seen on, the later engagement, the visits of a title's latest day,
// each day's heroes in the order either showed them, and the later count of visits, all
// under the stored salt. A tab that writes this never loses another tab's visits, heroes
// or titles seen to its own older copy.
export function merged(stored, mine) {
  const out = freshStore(stored);
  const later = (x, y) => (x === null ? y : y === null ? x : Math.max(x, y));
  const days = (x, y, most) => [...new Set([...x, ...y])].sort((p, q) => p - q).slice(-most);
  for (const [id, t] of Object.entries(mine.titles)) {
    const o = out.titles[id];
    if (!o) {
      out.titles[id] = { d: [...t.d], e: t.e, ...(t.v ? { v: [...t.v] } : {}) };
      continue;
    }
    const last = Math.max(o.d.at(-1) ?? -Infinity, t.d.at(-1) ?? -Infinity);
    const v = [...(o.d.at(-1) === last ? o.v || [] : []), ...(t.d.at(-1) === last ? t.v || [] : [])];
    o.d = days(o.d, t.d, DAYS_PER_TITLE);
    o.e = later(o.e, t.e);
    if (v.length) o.v = days(v, [], EARLIER_MOST); else delete o.v;
  }
  for (const [key, r] of Object.entries(mine.rows)) {
    const o = out.rows[key];
    out.rows[key] = o ? { d: days(o.d, r.d, TIRED_WINDOW), e: later(o.e, r.e) } : { d: [...r.d], e: r.e };
  }
  for (const [day, ids] of Object.entries(mine.heroes)) {
    out.heroes[day] = [...new Set([...(out.heroes[day] || []), ...ids])].slice(0, HEROES_A_DAY);
  }
  const { d, n } = mine.visits;
  if (d > out.visits.d || (d === out.visits.d && n > out.visits.n)) out.visits = { d, n };
  return out;
}

export function newSalt() {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
}

// The day's seed: the first 16 hex digits of SHA-256(salt | day), and a visit's, of
// SHA-256(salt | day | visit). The salt never leaves the browser, so no two seeds can be
// linked to each other or to a person, and a visit's says nothing of how many came before.
export async function seedFor(salt, day, visit = 0) {
  const data = new TextEncoder().encode(visit ? `${salt}|${day}|${visit}` : `${salt}|${day}`);
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', data));
  return [...digest.slice(0, 8)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// A new visit on the day: its number, one more than the visits the day has had.
export function beginVisit(store, day) {
  const n = dayNumber(day);
  store.visits = { d: n, n: store.visits?.d === n ? store.visits.n + 1 : 1 };
  return store.visits.n;
}

// A title half on screen for a second, on the day and, for Couchside, on the visit.
export function noteSeen(store, id, day, visit = 0) {
  const n = dayNumber(day);
  const t = store.titles[id] || (store.titles[id] = { d: [], e: null });
  if (!t.d.includes(n)) {
    t.d.push(n);
    if (t.d.length > DAYS_PER_TITLE) t.d.splice(0, t.d.length - DAYS_PER_TITLE);
    delete t.v;
  }
  if (visit && t.d.at(-1) === n && !t.v?.includes(visit)) t.v = [...(t.v || []), visit].slice(-EARLIER_MOST);
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

// A hero shown on the day, after those shown on it before.
export function noteHero(store, id, day) {
  const heroes = store.heroes[String(dayNumber(day))] ||= [];
  if (!heroes.includes(id) && heroes.length < HEROES_A_DAY) heroes.push(id);
}

// Forget days older than KEEP_DAYS and, past KEEP_TITLES, the titles seen longest ago;
// of an earlier day's visits, and of its heroes but the first, nothing counts any more.
export function prune(store, day) {
  const now = dayNumber(day), oldest = now - KEEP_DAYS;
  for (const [id, t] of Object.entries(store.titles)) {
    t.d = t.d.filter(n => n >= oldest);
    if (t.e !== null && t.e < oldest) t.e = null;
    if (t.v && t.d.at(-1) !== now) delete t.v;
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
  for (const [k, ids] of Object.entries(store.heroes)) {
    if (+k < now - KEEP_DAYS) delete store.heroes[k];
    else if (+k < now) store.heroes[k] = ids.slice(0, 1);
  }
  return store;
}

// A title's decayed count of days shown before today: nothing moves within a day.
export function decayed(t, now) {
  return t.d.filter(n => n < now).reduce((sum, n) => sum + 0.5 ** ((now - n) / HALF_LIFE), 0);
}

// What the visits of today before `visit` add to a title's count: EARLIER_SHARE of a
// day's showing for each that showed it, among its cards or as its hero (featured),
// EARLIER_MOST of them at most.
export function earlier(t, now, visit, featured = false) {
  if (!visit) return 0;
  const cards = t && t.d.at(-1) === now ? (t.v || []).filter(k => k < visit).length : 0;
  return EARLIER_SHARE * Math.min(EARLIER_MOST, cards + (featured ? 1 : 0));
}

// What a request carries: the day, its seed, and the store reduced to what fresh.py reads.
// For a visit (Couchside's), its seed too, the counts with what the day's earlier visits
// showed, their heroes the first thing each showed, and those heroes among the resting.
export async function freshness(store, day, visit = 0) {
  const now = dayNumber(day);
  const seen = [];
  const engaged = [];
  const featured = new Set(visit ? (store.heroes[now] || []).map(String) : []);
  for (const [id, t] of Object.entries(store.titles)) {
    if (t.e !== null && t.e >= now - ENGAGED_DAYS) engaged.push(+id);
    else {
      const n = Math.round((decayed(t, now) + earlier(t, now, visit, featured.has(id))) * 10) / 10;
      if (n >= 0.1) seen.push([id, Math.min(n, 50)]);
    }
  }
  for (const id of featured) if (!(id in store.titles)) seen.push([id, earlier(null, now, visit, true)]);
  seen.sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  // The first hero of each of the last week's days, then, for a visit, every hero of today.
  const days = Object.keys(store.heroes).map(Number).sort((a, b) => a - b);
  const resting = [
    ...days.filter(k => k < now && k >= now - HERO_REST).map(k => store.heroes[k][0]),
    ...(visit ? store.heroes[now] || [] : []),
  ];
  const tired = Object.entries(store.rows).filter(([, r]) => {
    const recent = r.d.filter(n => n < now && n >= now - TIRED_WINDOW);
    const engagedLately = r.e !== null && r.e >= now - TIRED_WINDOW;
    const restingSince = recent.length >= TIRED_AFTER ? recent[TIRED_AFTER - 1] : null;
    return !engagedLately && restingSince !== null && now - restingSince <= TIRED_REST;
  }).map(([key]) => key);
  return {
    day, seed: await seedFor(store.salt, day), ...(visit ? { visit: await seedFor(store.salt, day, visit) } : {}),
    seen: Object.fromEntries(seen.slice(0, SEND_TITLES)),
    engaged: engaged.slice(-300), resting: [...new Set(resting)].slice(-60), tired: tired.slice(0, 40),
  };
}

// Watch elements for the one-second, half-visible rule; onSeen(id) fires at most once
// per element. Returns observe(element, id) and a stop() for tearing down.
export function watcher(onSeen, { threshold = 0.5, dwell = 1000 } = {}) {
  if (typeof IntersectionObserver === 'undefined') return { observe() {}, stop() {} };
  // showing: elements at least half on screen now, whether or not the tab is visible.
  const timers = new Map(), ids = new WeakMap(), done = new WeakSet(), showing = new Set();
  const visible = () => document.visibilityState === 'visible';
  const start = el => {
    if (!timers.has(el)) timers.set(el, setTimeout(() => {
      timers.delete(el);
      if (!el.isConnected || !visible()) return;
      done.add(el);
      showing.delete(el);
      io.unobserve(el);
      onSeen(ids.get(el));
    }, dwell));
  };
  const io = new IntersectionObserver(entries => {
    for (const entry of entries) {
      const el = entry.target;
      if (done.has(el)) continue;
      if (entry.isIntersecting && entry.intersectionRatio >= threshold) {
        showing.add(el);
        if (visible()) start(el);
      } else {
        showing.delete(el);
        if (timers.has(el)) {
          clearTimeout(timers.get(el));
          timers.delete(el);
        }
      }
    }
  }, { threshold: [0, threshold, 1] });
  // A hidden tab stops every clock; coming back starts them again for what is still on
  // screen, which the observer would not report again since nothing moved.
  const onVisibility = () => {
    if (visible()) for (const el of showing) start(el);
    else { for (const t of timers.values()) clearTimeout(t); timers.clear(); }
  };
  document.addEventListener('visibilitychange', onVisibility);
  return {
    observe(el, id) { if (!done.has(el)) { ids.set(el, id); io.observe(el); } },
    stop() {
      io.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
      showing.clear();
    },
  };
}
