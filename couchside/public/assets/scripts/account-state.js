// Account sync keeps a server base and an owner-scoped local copy. Local changes are
// compared with that base so a deletion survives a concurrent edit on another device.
export const GUEST_KEY = 'couchside-v1';
export const ACTIVE_KEY = 'couchside-account-active-v1';
export const accountKey = id => `couchside-account-v1:${id}`;
const LIMITS = { profile: 3000, saved: 200 };
const emptyRemovals = () => ({ profile: [], saved: [] });

const copy = value => JSON.parse(JSON.stringify(value));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const identity = user => user && ['string', 'number'].includes(typeof user.id)
  && String(user.id).length > 0 && String(user.id).length <= 128
  && typeof user.email === 'string' && user.email.length <= 254
  ? { id: String(user.id), email: user.email } : null;

export function toWire(state) {
  return {
    version: 3,
    profile: (state.profile || []).map(({ id, weight }) => ({ id, weight })),
    saved: (state.saved || []).map(show => ({ id: typeof show === 'number' ? show : show.id })),
    settings: { known_min: state.settings?.known_min ?? 85 },
    onboarded: state.onboarded === true,
  };
}

export function sameState(a, b) {
  const canonical = state => {
    const wire = toWire(state);
    wire.profile.sort((left, right) => left.id - right.id);
    wire.saved.sort((left, right) => left.id - right.id);
    return wire;
  };
  return same(canonical(a), canonical(b));
}

function mergeRemovals(...histories) {
  return Object.fromEntries(Object.keys(LIMITS).map(kind => {
    const latest = new Map();
    for (const history of histories) for (const item of history?.[kind] || []) {
      if (Number.isSafeInteger(item?.id) && item.id > 0 && Number.isSafeInteger(item.revision)
        && item.revision > (latest.get(item.id) || 0)) latest.set(item.id, item.revision);
    }
    return [kind, [...latest].sort(([a], [b]) => a - b).map(([id, revision]) => ({ id, revision }))];
  }));
}

function pendingDeleted(history, ...copies) {
  return Object.fromEntries(Object.keys(LIMITS).map(kind => {
    const recorded = new Map((history?.[kind] || []).map(item => [item.id, item.revision]));
    const pending = new Map();
    for (const copy of copies) for (const item of copy?.[kind] || []) {
      if (Number.isSafeInteger(item?.id) && item.id > 0 && typeof item.writer === 'string'
        && /^[A-Za-z0-9_-]{1,128}$/.test(item.writer) && Number.isSafeInteger(item.sequence)
        && item.sequence >= 0 && Number.isSafeInteger(item.revision) && item.revision >= 0
        && (recorded.get(item.id) || 0) <= item.revision) pending.set(item.id, item);
    }
    return [kind, [...pending.values()].sort((a, b) => a.id - b.id)];
  }));
}

const hasDeleted = deleted => Object.keys(LIMITS).some(kind => deleted?.[kind]?.length);
const deletedIds = deleted => Object.fromEntries(Object.keys(LIMITS)
  .map(kind => [kind, (deleted?.[kind] || []).map(item => item.id)]));

function checkCapacity(state) {
  for (const [kind, limit] of Object.entries(LIMITS)) {
    if (state[kind].length > limit) throw new AccountRequestError(
      `Both lists are safe, but together they exceed ${limit.toLocaleString('en-US')} ${kind === 'saved' ? 'shows in My List' : 'ratings'}. Remove a few on this device to finish syncing.`,
      422, { capacity: true });
  }
  return state;
}

function mergeItems(base, local, remote, rating, removed, deleted) {
  const before = new Map(base.map(item => [item.id, item]));
  const ours = new Map(local.map(item => [item.id, item]));
  const theirs = new Map(remote.map(item => [item.id, item]));
  const value = item => item ? rating ? item.weight : true : undefined;
  const merged = new Map();
  for (const id of new Set([...before.keys(), ...ours.keys(), ...theirs.keys()])) {
    const changed = value(ours.get(id)) !== value(before.get(id));
    const changedRemote = value(theirs.get(id)) !== value(before.get(id));
    // An acknowledged removal also covers an add/remove that happened entirely
    // while this device was offline. A later, informed re-add remains possible.
    const conflict = changed && changedRemote;
    const deletedConflict = conflict && before.has(id) && (!ours.has(id) || !theirs.has(id));
    const selected = removed.has(id) ? theirs.get(id) : deleted.has(id) || deletedConflict ? undefined
      : changed && !changedRemote ? ours.get(id) : theirs.get(id);
    if (selected) {
      // Metadata stays local when useful; only IDs and weights go to the server.
      const old = ours.get(id);
      merged.set(id, old?.name && !selected.name ? { ...old, ...selected, name: old.name,
        poster: old.poster, year: old.year } : { ...selected });
    }
  }
  const order = [...local.map(item => item.id), ...remote.map(item => item.id)];
  return [...new Set(order)].filter(id => merged.has(id)).map(id => merged.get(id));
}

export function mergeStates(base, local, remote, { removals, revision = 0, deleted } = {}) {
  const after = kind => new Set((removals?.[kind] || [])
    .filter(item => item.revision > revision).map(item => item.id));
  const reachChanged = local.settings?.known_min !== base.settings?.known_min;
  const remoteReachChanged = remote.settings?.known_min !== base.settings?.known_min;
  const negative = deletedIds(pendingDeleted(removals, deleted));
  return checkCapacity({
    ...remote,
    profile: mergeItems(base.profile || [], local.profile || [], remote.profile || [], true, after('profile'), new Set(negative.profile)),
    saved: mergeItems(base.saved || [], local.saved || [], remote.saved || [], false, after('saved'), new Set(negative.saved)),
    settings: { ...remote.settings, known_min: reachChanged && !remoteReachChanged
      ? local.settings?.known_min : remote.settings?.known_min },
    onboarded: local.onboarded !== base.onboarded ? local.onboarded : remote.onboarded,
  });
}

export class AccountRequestError extends Error {
  constructor(message, status = 0, data = {}) {
    super(message);
    this.name = 'AccountRequestError';
    this.status = status;
    this.data = data;
  }
}

export async function accountRequest(path, body, { csrf, owner, revision, fetcher = globalThis.fetch, timeout = 12000 } = {}) {
  const abort = new AbortController();
  const deadline = setTimeout(() => abort.abort(), Math.max(1, Math.min(Number(timeout) || 12000, 12000)));
  try {
    const response = await fetcher(`/api/account/${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      signal: abort.signal,
      headers: body === undefined ? owner ? { 'X-Account-Owner': owner, 'X-Account-Revision': String(revision || 0) } : {} : {
        'Content-Type': 'application/json', 'X-Account-Request': '1', ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    let data;
    try { data = await response.json(); }
    catch { throw new AccountRequestError('The account service returned an unreadable response.', response.status); }
    if (!response.ok) throw new AccountRequestError(data.error || 'The account request could not be completed.', response.status, data);
    return data;
  } catch (error) {
    if (error instanceof AccountRequestError) throw error;
    throw new AccountRequestError(error.name === 'AbortError'
      ? 'The account service took too long to respond. Please try again.'
      : 'Unable to connect. Your changes are saved on this device.');
  } finally { clearTimeout(deadline); }
}

export class AccountSync {
  constructor({ getState, applyState, fresh, sanitize, onStatus = () => {}, storage,
    request = accountRequest, delay = 600 }) {
    Object.assign(this, { getState, applyState, fresh, sanitize, onStatus, request, delay });
    try { this.storage = storage === undefined ? globalThis.localStorage : storage; } catch { this.storage = null; }
    this.user = null;
    this.csrf = null;
    this.connected = false;
    this.pending = false;
    this.revision = 0;
    this.removals = emptyRemovals();
    this.deferred = [];
    this.deleted = emptyRemovals();
    this.blocked = false;
    // Tab identity orders only local cache snapshots. It is not a credential or
    // a device clock, and it is never sent to the account server.
    this.writer = globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2);
    this.sequence = 0;
    this.seen = new Map();
    this.generation = 0;
    this.paintVersion = 0;
    this.local = sanitize(getState());
    this.base = copy(this.local);
    this.status = 'checking';
    this.timer = null;
    this.flight = null;
    this.refreshing = null;
    this.authenticating = false;
    this.initialized = false;
  }

  read(key) {
    try { return JSON.parse(this.storage?.getItem(key) || 'null'); } catch { return null; }
  }

  write(key, value) {
    try { this.storage?.setItem(key, JSON.stringify(value)); } catch { /* Storage may be unavailable. */ }
  }

  remove(key) {
    try { this.storage?.removeItem(key); } catch { /* Storage may be unavailable. */ }
  }

  guest() {
    const saved = this.read(GUEST_KEY);
    return saved && typeof saved === 'object' ? this.sanitize(saved) : this.fresh();
  }

  cached(user) {
    const cache = this.read(accountKey(user.id));
    return identity(cache?.user)?.id === user.id && cache.base && cache.local
      && Number.isSafeInteger(cache.revision) && cache.revision >= 0 ? cache : null;
  }

  persist() {
    if (!this.user) { this.write(GUEST_KEY, this.local); return; }
    this.persistCache();
    this.write(ACTIVE_KEY, this.user);
  }

  persistCache() {
    this.seen.set(this.writer, this.sequence);
    const existing = this.cached(this.user);
    // Semantically identical list orders or metadata must not trigger a cycle
    // of storage events and refreshes between two open tabs.
    if (existing && existing.revision === this.revision && existing.pending === this.pending
      && sameState(existing.base, this.base) && sameState(existing.local, this.local)
      && same(mergeRemovals(existing.removals), this.removals)
      && same(existing.deferred || [], this.deferred)
      && same(existing.deleted || emptyRemovals(), this.deleted)
      && same(this.seenWire(existing.seen), this.seenWire())) return;
    // Forwarding another tab's pending edits also publishes a new snapshot.
    // Reusing a prior sequence would let a receiver skip those forwarded edits.
    ++this.sequence;
    this.seen.set(this.writer, this.sequence);
    this.write(accountKey(this.user.id), { user: this.user, base: toWire(this.base), local: this.local,
      revision: this.revision, pending: this.pending, removals: this.removals, deferred: this.deferred,
      writer: this.writer, sequence: this.sequence, seen: this.seenWire(), deleted: this.deleted });
  }

  report(status, message = '') {
    this.status = status;
    this.onStatus({ status, message, user: this.user, pending: this.pending, connected: this.connected });
  }

  async paint() {
    const generation = this.generation, version = ++this.paintVersion;
    await this.applyState(copy(this.local), {
      current: () => generation === this.generation && version === this.paintVersion,
    });
  }

  validSession(data) {
    const user = identity(data?.user);
    if (!user || typeof data.csrf !== 'string' || !data.csrf || !data.state
      || !Number.isSafeInteger(data.revision) || data.revision < 0) {
      throw new AccountRequestError('The account service returned an incomplete session.');
    }
    return user;
  }

  combineDeferred(local, deferred, removals) {
    let deleted = pendingDeleted(removals, this.deleted);
    for (const other of deferred) {
      const previous = local;
      const base = this.sanitize(other.base), pending = this.sanitize(other.local);
      // A forwarded old removal cannot undo a re-add that cleared that intent.
      // Keep already-seen intents only while that exact intent remains pending.
      const incoming = Object.fromEntries(Object.keys(LIMITS).map(kind => [kind,
        (other.deleted?.[kind] || []).filter(item => item.sequence > (this.seen.get(item.writer) ?? -1)
          || deleted[kind].some(live => live.id === item.id && live.writer === item.writer
            && live.sequence === item.sequence))]));
      for (const kind of Object.keys(LIMITS)) {
        const accepted = new Set(incoming[kind].map(item => item.id));
        const present = new Set(pending[kind].map(item => item.id));
        const ignored = new Set((other.deleted?.[kind] || []).filter(item => !accepted.has(item.id))
          .map(item => item.id));
        // Remove the obsolete deletion delta as well as its explicit intent.
        for (const item of base[kind]) if (ignored.has(item.id) && !present.has(item.id)) pending[kind].push(item);
      }
      deleted = pendingDeleted(removals, deleted, incoming);
      local = mergeStates(base, pending, previous,
        { removals, revision: other.revision, deleted });
      for (const kind of Object.keys(LIMITS)) {
        const items = new Map(local[kind].map(item => [item.id, item]));
        const order = new Set([...previous[kind].map(item => item.id), ...items.keys()]);
        local[kind] = [...order].filter(id => items.has(id)).map(id => items.get(id));
      }
    }
    this.deleted = Object.fromEntries(Object.keys(LIMITS).map(kind => {
      const present = new Set(local[kind].map(item => item.id));
      return [kind, deleted[kind].filter(item => !present.has(item.id))];
    }));
    for (const other of deferred) this.learnSeen(other);
    return local;
  }

  seenWire(raw) {
    const source = arguments.length ? raw || {} : Object.fromEntries(this.seen);
    return Object.fromEntries(Object.entries(source).filter(([writer, sequence]) =>
      /^[A-Za-z0-9_-]{1,128}$/.test(writer) && Number.isSafeInteger(sequence) && sequence >= 0)
      .sort(([a], [b]) => a.localeCompare(b)));
  }

  learnSeen(other) {
    for (const [writer, sequence] of Object.entries(this.seenWire(other.seen))) {
      this.seen.set(writer, Math.max(this.seen.get(writer) ?? -1, sequence));
    }
    if (typeof other.writer === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(other.writer)
      && Number.isSafeInteger(other.sequence) && other.sequence >= 0) {
      this.seen.set(other.writer, Math.max(this.seen.get(other.writer) ?? -1, other.sequence));
    }
  }

  rememberDeferred(...copies) {
    const unique = new Map();
    for (const other of copies.flat()) {
      if (!other?.base || !other.local || !Number.isSafeInteger(other.revision) || other.revision < 0) continue;
      const writer = typeof other.writer === 'string' && other.writer.length <= 128 ? other.writer : 'legacy';
      const sequence = Number.isSafeInteger(other.sequence) && other.sequence >= 0 ? other.sequence : 0;
      if (writer === this.writer && sequence <= this.sequence || sequence <= (this.seen.get(writer) ?? -1)) continue;
      const previous = unique.get(writer);
      if (previous && (previous.sequence > sequence
        || previous.sequence === sequence && previous.revision > other.revision)) continue;
      unique.set(writer, { base: toWire(other.base), local: this.sanitize(other.local),
        revision: other.revision, writer, sequence, seen: this.seenWire(other.seen),
        deleted: pendingDeleted(emptyRemovals(), other.deleted) });
    }
    return [...unique.values()].filter(other => {
      if (!sameState(other.base, other.local) || hasDeleted(other.deleted)) return true;
      this.learnSeen(other);
      return false;
    });
  }

  async acceptSession(data) {
    const user = this.validSession(data);
    const remote = this.sanitize(data.state);
    const cache = this.user?.id === user.id
      ? { base: this.base, local: this.local, revision: this.revision,
        removals: this.removals, deferred: this.deferred, seen: this.seenWire(), deleted: this.deleted } : this.cached(user);
    if (this.user?.id !== user.id) {
      this.seen = new Map();
      if (cache) this.learnSeen(cache);
    }
    const removals = mergeRemovals(cache?.removals, data.removals);
    this.deleted = pendingDeleted(removals, cache?.deleted);
    const deferred = this.rememberDeferred(cache?.deferred || []);
    let local;
    try {
      local = cache ? mergeStates(this.sanitize(cache.base), this.sanitize(cache.local), remote,
        { removals, revision: cache.revision, deleted: this.deleted }) : remote;
      local = this.combineDeferred(local, deferred, removals);
    } catch (error) {
      if (!error.data?.capacity || !cache) throw error;
      // The server retains its copy and this device retains its complete pending
      // copy. Never feed an oversized union into the display sanitizer.
      this.user = user;
      this.csrf = data.csrf;
      this.connected = true;
      this.base = this.sanitize(cache.base);
      this.local = this.sanitize(cache.local);
      this.revision = cache.revision;
      this.removals = removals;
      this.deferred = deferred;
      this.pending = !sameState(this.base, this.local) || deferred.length > 0 || hasDeleted(this.deleted);
      this.blocked = true;
      clearTimeout(this.timer);
      this.persist();
      await this.paint();
      this.report('retry', error.message);
      return;
    }
    this.user = user;
    this.csrf = data.csrf;
    this.connected = true;
    this.base = remote;
    this.local = this.sanitize(local);
    this.revision = data.revision;
    this.removals = removals;
    this.deferred = [];
    this.blocked = false;
    this.pending = !sameState(this.base, this.local) || hasDeleted(this.deleted);
    this.persist();
    await this.paint();
    this.report(this.pending ? 'pending' : 'saved');
    if (this.pending) this.schedule();
  }

  ready() {
    if (!this.boot) this.boot = this.initialize();
    return this.boot;
  }

  async initialize() {
    const active = identity(this.read(ACTIVE_KEY));
    const cache = active && this.cached(active);
    if (cache) {
      this.user = active;
      this.local = this.sanitize(cache.local);
      this.base = this.sanitize(cache.base);
      this.revision = cache.revision;
      this.removals = mergeRemovals(cache.removals);
      this.deleted = pendingDeleted(this.removals, cache.deleted);
      this.learnSeen(cache);
      this.deferred = this.rememberDeferred(cache.deferred || []);
      this.pending = !sameState(this.base, this.local) || this.deferred.length > 0 || hasDeleted(this.deleted);
      await this.paint();
    }
    const generation = this.generation;
    try {
      const data = await this.request('session', undefined, { owner: this.user?.id, revision: this.revision });
      if (generation === this.generation) await this.acceptSession(data);
    } catch (error) {
      if (generation !== this.generation) return;
      this.connected = false;
      this.report(this.user ? error.status === 401 ? 'expired' : 'offline' : 'guest',
        error.status === 401 && !this.user ? '' : error.message);
    } finally { this.initialized = true; }
  }

  changed() {
    ++this.paintVersion;
    ++this.sequence;
    const previous = this.local;
    this.local = this.sanitize(this.getState());
    if (this.user) for (const kind of Object.keys(LIMITS)) {
      const present = new Set(this.local[kind].map(item => item.id));
      const deleted = new Map(this.deleted[kind].filter(item => !present.has(item.id)).map(item => [item.id, item]));
      for (const item of previous[kind]) if (!present.has(item.id)) {
        deleted.set(item.id, { id: item.id, writer: this.writer, sequence: this.sequence, revision: this.revision });
      }
      this.deleted[kind] = [...deleted.values()].sort((a, b) => a.id - b.id);
    }
    this.blocked = false;
    if (this.user) this.pending = !sameState(this.base, this.local) || this.deferred.length > 0 || hasDeleted(this.deleted);
    this.persist();
    if (this.user) {
      this.report(this.connected ? this.pending ? 'pending' : 'saved' : this.status === 'expired' ? 'expired' : 'offline');
      if (this.connected && this.initialized) this.schedule();
    }
  }

  schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.timer = null; void this.flush(); }, this.delay);
  }

  async refresh() {
    await this.ready();
    if (this.authenticating) return;
    if (this.refreshing) return this.refreshing;
    this.refreshing = this.refreshSession().finally(() => { this.refreshing = null; });
    return this.refreshing;
  }

  async refreshSession() {
    // Finish a save first so an older GET cannot replace its newer revision.
    if (this.flight) await this.flight;
    const generation = this.generation;
    try {
      const data = await this.request('session', undefined, { owner: this.user?.id, revision: this.revision });
      if (generation === this.generation && !this.authenticating) await this.acceptSession(data);
    } catch (error) {
      if (generation !== this.generation) return;
      this.connected = false;
      this.csrf = null;
      this.report(this.user ? error.status === 401 ? 'expired' : 'offline' : 'guest',
        error.status === 401 && !this.user ? '' : error.message);
    }
  }

  async flush() {
    await this.ready();
    clearTimeout(this.timer);
    this.timer = null;
    if (this.flight) return this.flight;
    if (!this.pending || !this.connected || !this.user || this.authenticating || this.blocked) return;
    // Saves wait for a GET already in progress; refreshSession waits only for a
    // save that existed before that GET, so the two never wait on each other.
    if (this.refreshing) await this.refreshing;
    if (this.flight) return this.flight;
    if (!this.pending || !this.connected || !this.user || this.authenticating || this.blocked) return;
    if (this.deferred.length) {
      try {
        this.local = this.sanitize(this.combineDeferred(this.local, this.deferred, this.removals));
        this.deferred = [];
        this.pending = !sameState(this.base, this.local) || hasDeleted(this.deleted);
        this.persist();
        await this.paint();
      } catch (error) {
        this.blocked = true;
        this.report('retry', error.message);
        return;
      }
    }
    this.flight = this.pushChanges().finally(() => { this.flight = null; });
    return this.flight;
  }

  async pushChanges() {
    const generation = this.generation, owner = this.user.id;
    let conflicts = 0;
    this.report('saving');
    while (this.pending && !this.blocked && generation === this.generation && this.user?.id === owner) {
      const snapshot = copy(this.local);
      // Long offline sessions may cancel more shows than fit in one request.
      // Acknowledge bounded batches; retain every remaining removal for the next save.
      const deleted = Object.fromEntries(Object.entries(LIMITS)
        .map(([kind, limit]) => [kind, copy(this.deleted[kind].slice(0, limit))]));
      try {
        const data = await this.request('state', { state: toWire(snapshot), revision: this.revision,
          sync_version: 2, removed: deletedIds(deleted) }, { csrf: this.csrf });
        if (generation !== this.generation || this.user?.id !== owner) return;
        if (!data.state || !Number.isSafeInteger(data.revision) || data.revision < this.revision) {
          throw new AccountRequestError('The account service returned an incomplete save.');
        }
        const remote = this.sanitize(data.state);
        // Acknowledgment clears only the deletion intents in this request.
        // A newer remove or re-add made during the request stays ordered after it.
        for (const kind of Object.keys(LIMITS)) {
          const sent = new Map(deleted[kind].map(item => [item.id, item]));
          this.deleted[kind] = this.deleted[kind].filter(item => {
            const earlier = sent.get(item.id);
            return !earlier || earlier.writer !== item.writer || earlier.sequence !== item.sequence;
          }).map(item => item.writer === this.writer ? { ...item, revision: data.revision } : item);
        }
        this.local = this.sanitize(mergeStates(snapshot, this.local, remote, { deleted: this.deleted }));
        this.base = remote;
        this.revision = data.revision;
        this.removals = mergeRemovals(this.removals, data.removals);
        this.pending = !sameState(this.base, this.local) || hasDeleted(this.deleted) || this.deferred.length > 0;
        this.persist();
        await this.paint();
      } catch (error) {
        if (generation !== this.generation || this.user?.id !== owner) return;
        if (error.status === 409 && error.data.state && Number.isSafeInteger(error.data.revision)
          && error.data.revision >= this.revision) {
          const remote = this.sanitize(error.data.state);
          const removals = mergeRemovals(this.removals, error.data.removals);
          try {
            this.local = this.sanitize(mergeStates(this.base, this.local, remote,
              { removals, revision: this.revision, deleted: this.deleted }));
          } catch (failure) {
            if (!failure.data?.capacity) throw failure;
            this.blocked = true;
            this.report('retry', failure.message);
            return;
          }
          this.base = remote;
          this.revision = error.data.revision;
          this.removals = removals;
          this.deleted = pendingDeleted(removals, this.deleted);
          this.pending = !sameState(this.base, this.local) || hasDeleted(this.deleted);
          this.persist();
          await this.paint();
          if (++conflicts < 3 && this.pending) continue;
          this.report(this.pending ? 'retry' : 'saved', this.pending
            ? 'Your changes are safe on this device. We will try syncing again shortly.' : '');
          return;
        }
        if (error.data?.upgrade) {
          this.blocked = true;
          this.report('retry', error.message);
        } else if (error.status === 401 || error.status === 403) {
          this.connected = false;
          this.csrf = null;
          this.report('expired', 'Sign in again to sync. Your changes are saved on this device.');
        } else {
          this.report('offline', error.message);
        }
        return;
      }
    }
    if (generation === this.generation && !this.blocked) this.report(this.pending ? 'pending' : 'saved');
  }

  async authenticate(kind, { email, password, current_password } = {}) {
    await this.ready();
    if (this.authenticating) throw new AccountRequestError('An account request is already in progress.');
    if (kind === 'password') {
      await this.flush();
      if (!this.connected) throw new AccountRequestError('Sign in again before changing your password.');
    }
    this.authenticating = true;
    ++this.generation;
    clearTimeout(this.timer);
    // Only a genuine guest list is offered for merging into a different account.
    const guest = !this.user ? this.sanitize(this.getState()) : this.guest();
    if (!this.user) this.write(GUEST_KEY, guest);
    try {
      const body = kind === 'password' ? { current_password, password }
        : kind === 'signup' ? { email, password, state: toWire(guest) }
          : { email, password, ...(!this.user && (guest.profile.length || guest.saved.length)
            ? { guest_state: toWire(guest) } : {}) };
      const data = await this.request(kind, body, { csrf: kind === 'password' ? this.csrf : undefined });
      await this.acceptSession(data);
      return data;
    } catch (error) {
      if (kind === 'password' && [401, 403].includes(error.status)) {
        this.connected = false;
        this.csrf = null;
        this.report('expired', 'Sign in again to continue.');
      }
      throw error;
    } finally { this.authenticating = false; if (this.pending && this.connected && !this.blocked) this.schedule(); }
  }

  async logout() {
    await this.ready();
    if (this.authenticating) throw new AccountRequestError('An account request is already in progress.');
    await this.flush();
    if (this.pending) throw new AccountRequestError('Your changes are safe on this device. Finish syncing before signing out.');
    this.authenticating = true;
    ++this.generation;
    clearTimeout(this.timer);
    try {
      if (this.user) {
        try { await this.request('logout', {}, { csrf: this.csrf }); }
        catch (error) { if (error.status !== 401) throw error; }
      }
      if (this.user) this.remove(accountKey(this.user.id));
      this.remove(ACTIVE_KEY);
      this.user = null;
      this.csrf = null;
      this.connected = false;
      this.pending = false;
      this.blocked = false;
      this.removals = emptyRemovals();
      this.deferred = [];
      this.deleted = emptyRemovals();
      this.seen = new Map();
      this.local = this.guest();
      this.base = copy(this.local);
      await this.paint();
      this.report('guest');
    } finally { this.authenticating = false; }
  }

  async storageChanged(event) {
    if (event.key === ACTIVE_KEY) {
      let active = null;
      try { active = identity(JSON.parse(event.newValue || 'null')); } catch { /* Removed or invalid owner marker. */ }
      if (this.user && active?.id !== this.user.id) {
        // Another tab explicitly signed out or switched accounts. Hide the old
        // account immediately, even offline; pending edits remain owned by it.
        if (this.pending) this.persistCache();
        ++this.generation;
        clearTimeout(this.timer);
        this.user = null;
        this.csrf = null;
        this.connected = false;
        this.pending = false;
        this.blocked = false;
        this.removals = emptyRemovals();
        this.deferred = [];
        this.deleted = emptyRemovals();
        this.seen = new Map();
        this.local = this.guest();
        this.base = copy(this.local);
        await this.paint();
        this.report('guest');
      }
      if (active) await this.refresh();
    } else if (this.user && event.key === accountKey(this.user.id) && event.newValue !== null) {
      let other;
      try { other = JSON.parse(event.newValue); } catch { return; }
      if (identity(other?.user)?.id !== this.user.id || !other.local || !other.base
        || !Number.isSafeInteger(other.revision) || other.revision < 0) return;
      const removals = mergeRemovals(this.removals, other.removals);
      const deferred = this.rememberDeferred(this.deferred, other.deferred || [], other);
      let local;
      try {
        // A tab's acknowledged server base may advance ours. Its pending edits
        // must then be compared with ITS base, never treated as a full account
        // snapshot: unchanged items in an old tab cannot resurrect deletions.
        local = other.revision > this.revision ? mergeStates(this.base, this.local,
          this.sanitize(other.base), { removals, revision: this.revision, deleted: this.deleted }) : this.local;
        local = this.combineDeferred(local, deferred, removals);
      } catch (error) {
        if (!error.data?.capacity) throw error;
        this.deferred = deferred;
        this.removals = removals;
        this.pending = true;
        this.blocked = true;
        clearTimeout(this.timer);
        this.persistCache();
        this.report('retry', error.message);
        return;
      }
      const changed = !sameState(local, this.local);
      this.local = this.sanitize(local);
      if (other.revision > this.revision) {
        this.base = this.sanitize(other.base);
        this.revision = other.revision;
      }
      this.removals = removals;
      this.deferred = [];
      this.blocked = false;
      this.pending = !sameState(this.base, this.local) || hasDeleted(this.deleted);
      this.learnSeen(other);
      this.persistCache();
      if (changed) await this.paint();
      await this.refresh();
    }
  }

  destroy() { clearTimeout(this.timer); ++this.generation; ++this.paintVersion; }
}
