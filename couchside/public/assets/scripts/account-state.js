// Account sync keeps a server base and an owner-scoped local copy. Local changes are
// compared with that base so a deletion survives a concurrent edit on another device.
export const GUEST_KEY = 'couchside-v1';
export const ACTIVE_KEY = 'couchside-account-active-v1';
export const accountKey = id => `couchside-account-v1:${id}`;

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

function mergeItems(base, local, remote, rating) {
  const before = new Map(base.map(item => [item.id, item]));
  const ours = new Map(local.map(item => [item.id, item]));
  const theirs = new Map(remote.map(item => [item.id, item]));
  const value = item => item ? rating ? item.weight : true : undefined;
  const merged = new Map();
  for (const id of new Set([...before.keys(), ...ours.keys(), ...theirs.keys()])) {
    const changed = value(ours.get(id)) !== value(before.get(id));
    const selected = changed ? ours.get(id) : theirs.get(id);
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

export function mergeStates(base, local, remote) {
  return {
    ...remote,
    profile: mergeItems(base.profile || [], local.profile || [], remote.profile || [], true),
    saved: mergeItems(base.saved || [], local.saved || [], remote.saved || [], false),
    settings: { ...remote.settings, known_min: local.settings?.known_min !== base.settings?.known_min
      ? local.settings?.known_min : remote.settings?.known_min },
    onboarded: local.onboarded !== base.onboarded ? local.onboarded : remote.onboarded,
  };
}

export function mergeGuest(account, guest) {
  const profile = new Map((account.profile || []).map(item => [item.id, item]));
  const saved = new Map((account.saved || []).map(item => [item.id, item]));
  for (const item of guest.profile || []) profile.set(item.id, item);
  for (const item of guest.saved || []) if (!saved.has(item.id)) saved.set(item.id, item);
  return { ...account, profile: [...profile.values()], saved: [...saved.values()],
    onboarded: account.onboarded || guest.onboarded };
}

export class AccountRequestError extends Error {
  constructor(message, status = 0, data = {}) {
    super(message);
    this.name = 'AccountRequestError';
    this.status = status;
    this.data = data;
  }
}

export async function accountRequest(path, body, { csrf, fetcher = globalThis.fetch, timeout = 12000 } = {}) {
  const abort = new AbortController();
  const deadline = setTimeout(() => abort.abort(), Math.max(1, Math.min(Number(timeout) || 12000, 12000)));
  try {
    const response = await fetcher(`/api/account/${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      signal: abort.signal,
      headers: body === undefined ? {} : {
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
    const existing = this.cached(this.user);
    // Semantically identical list orders or metadata must not trigger a cycle
    // of storage events and refreshes between two open tabs.
    if (existing && existing.revision === this.revision && existing.pending === this.pending
      && sameState(existing.base, this.base) && sameState(existing.local, this.local)) return;
    this.write(accountKey(this.user.id), { user: this.user, base: toWire(this.base), local: this.local,
      revision: this.revision, pending: this.pending });
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

  async acceptSession(data, { guest = null } = {}) {
    const user = this.validSession(data);
    const remote = this.sanitize(data.state);
    const cache = this.user?.id === user.id
      ? { base: this.base, local: this.local, revision: this.revision } : this.cached(user);
    let local = cache ? mergeStates(this.sanitize(cache.base), this.sanitize(cache.local), remote) : remote;
    if (guest) local = mergeGuest(local, guest);
    this.user = user;
    this.csrf = data.csrf;
    this.connected = true;
    this.base = remote;
    this.local = this.sanitize(local);
    this.revision = data.revision;
    this.pending = !sameState(this.base, this.local);
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
      this.pending = !sameState(this.base, this.local);
      await this.paint();
    }
    const generation = this.generation;
    try {
      const data = await this.request('session');
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
    this.local = this.sanitize(this.getState());
    if (this.user) this.pending = !sameState(this.base, this.local);
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
      const data = await this.request('session');
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
    if (!this.pending || !this.connected || !this.user || this.authenticating) return;
    // Saves wait for a GET already in progress; refreshSession waits only for a
    // save that existed before that GET, so the two never wait on each other.
    if (this.refreshing) await this.refreshing;
    if (this.flight) return this.flight;
    if (!this.pending || !this.connected || !this.user || this.authenticating) return;
    this.flight = this.pushChanges().finally(() => { this.flight = null; });
    return this.flight;
  }

  async pushChanges() {
    const generation = this.generation, owner = this.user.id;
    let conflicts = 0;
    this.report('saving');
    while (this.pending && generation === this.generation && this.user?.id === owner) {
      const snapshot = copy(this.local);
      try {
        const data = await this.request('state', { state: toWire(snapshot), revision: this.revision }, { csrf: this.csrf });
        if (generation !== this.generation || this.user?.id !== owner) return;
        if (!data.state || !Number.isSafeInteger(data.revision) || data.revision < this.revision) {
          throw new AccountRequestError('The account service returned an incomplete save.');
        }
        const remote = this.sanitize(data.state);
        this.local = this.sanitize(mergeStates(snapshot, this.local, remote));
        this.base = remote;
        this.revision = data.revision;
        this.pending = !sameState(this.base, this.local);
        this.persist();
        await this.paint();
      } catch (error) {
        if (generation !== this.generation || this.user?.id !== owner) return;
        if (error.status === 409 && error.data.state && Number.isSafeInteger(error.data.revision)
          && error.data.revision >= this.revision) {
          const remote = this.sanitize(error.data.state);
          this.local = this.sanitize(mergeStates(this.base, this.local, remote));
          this.base = remote;
          this.revision = error.data.revision;
          this.pending = !sameState(this.base, this.local);
          this.persist();
          await this.paint();
          if (++conflicts < 3 && this.pending) continue;
          this.report(this.pending ? 'pending' : 'saved', this.pending
            ? 'Your changes are saved on this device. Tap Sync now to try again.' : '');
          return;
        }
        if (error.status === 401 || error.status === 403) {
          this.connected = false;
          this.csrf = null;
          this.report('expired', 'Sign in again to sync. Your changes are saved on this device.');
        } else {
          this.report('offline', error.message);
        }
        return;
      }
    }
    if (generation === this.generation) this.report('saved');
  }

  async authenticate(kind, { email, password, merge = false, current_password } = {}) {
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
        : kind === 'signup' ? { email, password, state: toWire(guest) } : { email, password };
      const data = await this.request(kind, body, { csrf: kind === 'password' ? this.csrf : undefined });
      await this.acceptSession(data, { guest: kind === 'login' && merge && !this.user ? guest : null });
      return data;
    } catch (error) {
      if (kind === 'password' && [401, 403].includes(error.status)) {
        this.connected = false;
        this.csrf = null;
        this.report('expired', 'Sign in again to continue.');
      }
      throw error;
    } finally { this.authenticating = false; if (this.pending && this.connected) this.schedule(); }
  }

  async logout() {
    await this.ready();
    if (this.authenticating) throw new AccountRequestError('An account request is already in progress.');
    await this.flush();
    if (this.pending) throw new AccountRequestError('Sync your changes before signing out. Your changes are saved on this device.');
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
      const local = this.sanitize(mergeStates(this.base, this.local, this.sanitize(other.local)));
      if (!sameState(local, this.local)) {
        this.local = local;
        this.pending = !sameState(this.base, this.local);
        this.persistCache();
        await this.paint();
      }
      await this.refresh();
    }
  }

  destroy() { clearTimeout(this.timer); ++this.generation; ++this.paintVersion; }
}
