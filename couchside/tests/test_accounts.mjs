import assert from 'node:assert/strict';
import { AccountSync, AccountRequestError, accountRequest, toWire, sameState, mergeStates,
  mergeGuest, GUEST_KEY, ACTIVE_KEY, accountKey } from '../client/account-state.js';

const fresh = () => ({ version: 3, profile: [], saved: [], settings: { known_min: 85 }, onboarded: false });
const sanitize = raw => ({ ...fresh(), ...raw,
  profile: (raw.profile || []).map(item => ({ name: '', ...item })),
  saved: (raw.saved || []).map(item => ({ name: '', ...(typeof item === 'number' ? { id: item } : item) })),
  settings: { known_min: raw.settings?.known_min ?? 85 } });
const state = (profile = [], saved = []) => sanitize({ ...fresh(),
  profile: profile.map(([id, weight]) => ({ id, weight, name: `Show ${id}` })),
  saved: saved.map(id => ({ id, name: `Show ${id}` })), onboarded: profile.length > 0 });
const user = id => ({ id, email: `${id}@example.com` });
const session = (id, accountState = fresh(), revision = 0) => ({ user: user(id), csrf: `csrf-${id}`,
  state: toWire(accountState), revision });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const memory = () => {
  const map = new Map();
  return { getItem: key => map.get(key) || null, setItem: (key, value) => map.set(key, value),
    removeItem: key => map.delete(key), map };
};
function setup(request, storage = memory(), initial = fresh()) {
  let current = initial;
  const statuses = [];
  const sync = new AccountSync({ getState: () => current, applyState: async (next, context) => {
    if (context.current()) current = next;
  }, fresh, sanitize, request, storage, onStatus: value => statuses.push(value), delay: 600000 });
  return { sync, storage, statuses, get: () => current, change(next) { current = next; sync.changed(); } };
}

// Local deletions, remote additions, and conflicting ratings all survive merging.
{
  const base = state([[1, .7], [4, .7]], [1, 4]);
  const local = state([[2, 1], [4, -1]], [2, 4]);
  const remote = state([[1, 1], [3, .35], [4, 1]], [1, 3, 4]);
  const result = mergeStates(base, local, remote);
  assert.deepEqual(result.profile.map(({ id, weight }) => [id, weight]), [[2, 1], [4, -1], [3, .35]]);
  assert.deepEqual(result.saved.map(({ id }) => id), [2, 4, 3]);
  const mergedGuest = mergeGuest(state([[1, .7]], [1]), state([[1, -1], [2, 1]], [2, 1]));
  assert.deepEqual(mergedGuest.profile.map(({ id, weight }) => [id, weight]), [[1, -1], [2, 1]]);
  assert.deepEqual(mergedGuest.saved.map(({ id }) => id), [1, 2]);
  assert.equal(sameState(state([[1, .7]], [1]), sanitize(toWire(state([[1, .7]], [1])))), true);
  assert.equal(JSON.stringify(toWire(state([[1, .7]], [1]))).includes('Show'), false);
}

// Only guest data belongs in the legacy guest key. Logout restores that copy.
{
  const calls = [];
  const guest = state([[11, .7]], [11]);
  const device = setup(async (path, body, options) => {
    calls.push({ path, body, options });
    if (path === 'session') throw new AccountRequestError('Anonymous', 401);
    if (path === 'signup') return session('alice', body.state, 1);
    if (path === 'state') return { state: body.state, revision: 2 };
    if (path === 'logout') return {};
    throw new Error(`Unexpected request ${path}`);
  }, memory(), guest);
  await device.sync.ready();
  await device.sync.authenticate('signup', { email: 'alice@example.com', password: 'a long passphrase' });
  device.change(state([[11, 1], [12, .7]], [12]));
  await device.sync.flush();
  assert.deepEqual(JSON.parse(device.storage.getItem(GUEST_KEY)).saved.map(item => item.id), [11]);
  assert.equal(JSON.stringify([...device.storage.map.values()]).includes('csrf-alice'), false);
  assert.equal(calls.find(call => call.path === 'state').options.csrf, 'csrf-alice');
  await device.sync.logout();
  assert.deepEqual(device.get().saved.map(item => item.id), [11]);
  assert.equal(device.storage.getItem(accountKey('alice')), null);
  assert.equal(device.storage.getItem(ACTIVE_KEY), null);
  device.sync.destroy();
}

// A cached account is restored while offline. Its changes do not merge into a
// different account, even if callers accidentally request guest merging.
{
  const storage = memory();
  storage.setItem(GUEST_KEY, JSON.stringify(state([[99, 1]], [99])));
  storage.setItem(ACTIVE_KEY, JSON.stringify(user('alice')));
  storage.setItem(accountKey('alice'), JSON.stringify({ user: user('alice'), base: toWire(state([[1, .7]], [1])),
    local: state([[1, -1]], []), revision: 7, pending: true }));
  let sessionCalls = 0;
  const device = setup(async path => {
    if (path === 'session') { sessionCalls++; throw new AccountRequestError('Offline'); }
    if (path === 'login') return session('bob', state([[2, 1]], [2]), 4);
    throw new Error(`Unexpected request ${path}`);
  }, storage);
  await device.sync.ready();
  assert.deepEqual(device.get().profile.map(item => item.id), [1]);
  assert.equal(device.sync.pending, true);
  assert.equal(sessionCalls, 1);
  await device.sync.authenticate('login', { email: 'bob@example.com', password: 'a long passphrase', merge: true });
  assert.deepEqual(device.get().profile.map(item => item.id), [2]);
  assert.deepEqual(device.get().saved.map(item => item.id), [2]);
  assert.ok(storage.getItem(accountKey('alice')), 'pending changes for the previous owner remain recoverable');
  assert.deepEqual(JSON.parse(storage.getItem(GUEST_KEY)).saved.map(item => item.id), [99]);
  device.sync.destroy();
}

// Reauthenticating the same owner reconciles pending edits with new remote data.
{
  const storage = memory();
  storage.setItem(ACTIVE_KEY, JSON.stringify(user('alice')));
  storage.setItem(accountKey('alice'), JSON.stringify({ user: user('alice'), base: toWire(state([[1, .7]], [1])),
    local: state([[1, -1]], []), revision: 7, pending: true }));
  let lastSave;
  const device = setup(async (path, body) => {
    if (path === 'session') throw new AccountRequestError('Expired', 401);
    if (path === 'login') return session('alice', state([[1, 1], [2, .7]], [1, 2]), 8);
    if (path === 'state') { lastSave = body; return { state: body.state, revision: 9 }; }
    throw new Error(`Unexpected request ${path}`);
  }, storage);
  await device.sync.ready();
  assert.equal(device.sync.status, 'expired');
  await device.sync.authenticate('login', { email: 'alice@example.com', password: 'a long passphrase' });
  await device.sync.flush();
  assert.equal(lastSave.revision, 8);
  assert.deepEqual(lastSave.state.profile, [{ id: 1, weight: -1 }, { id: 2, weight: .7 }]);
  assert.deepEqual(lastSave.state.saved, [{ id: 2 }]);
  assert.equal(device.sync.pending, false);
  device.sync.destroy();
}

// Edits made while a save is in flight become a later, ordered request.
{
  const firstSave = deferred(), started = deferred();
  const bodies = [];
  const device = setup(async (path, body) => {
    if (path === 'session') return session('alice', state([[1, .7]], [1]), 1);
    if (path === 'state') {
      bodies.push(body);
      if (bodies.length === 1) { started.resolve(); return firstSave.promise; }
      return { state: body.state, revision: 3 };
    }
    throw new Error(`Unexpected request ${path}`);
  });
  await device.sync.ready();
  device.change(state([[1, 1]], [1]));
  const saving = device.sync.flush();
  await started.promise;
  device.change(state([[1, -1], [2, 1]], [2]));
  firstSave.resolve({ state: bodies[0].state, revision: 2 });
  await saving;
  assert.equal(bodies.length, 2);
  assert.equal(bodies[1].revision, 2);
  assert.deepEqual(bodies[1].state.saved, [{ id: 2 }]);
  assert.deepEqual(device.get().profile.map(({ id, weight }) => [id, weight]), [[1, -1], [2, 1]]);
  device.sync.destroy();
}

// Conflicts merge instead of overwriting the other device; repeated conflicts
// stop after three requests with the pending copy still durably owned by Alice.
{
  let saves = 0;
  const device = setup(async (path, body) => {
    if (path === 'session') return session('alice', state([[1, .7]], [1]), 1);
    if (path === 'state') {
      saves++;
      throw new AccountRequestError('Conflict', 409, { state: toWire(state([[1, .7], [3, 1]], [1, 3])), revision: body.revision + 1 });
    }
    throw new Error(`Unexpected request ${path}`);
  });
  await device.sync.ready();
  device.change(state([[1, -1]], []));
  await device.sync.flush();
  assert.equal(saves, 3);
  assert.equal(device.sync.pending, true);
  assert.deepEqual(device.get().saved.map(item => item.id), [3]);
  const stored = JSON.parse(device.storage.getItem(accountKey('alice')));
  assert.equal(stored.pending, true);
  assert.deepEqual(stored.local.profile.map(({ id, weight }) => [id, weight]), [[1, -1], [3, 1]]);
  device.sync.destroy();
}

// Two callers queued behind the same refresh still share one save operation.
{
  const nextSession = deferred(), refreshStarted = deferred(), save = deferred(), saveStarted = deferred();
  let sessions = 0, saves = 0;
  const device = setup(async (path, body) => {
    if (path === 'session') {
      if (++sessions === 1) return session('alice', fresh(), 0);
      refreshStarted.resolve();
      return nextSession.promise;
    }
    if (path === 'state') { saves++; saveStarted.resolve(); return save.promise; }
    throw new Error(`Unexpected request ${path}`);
  });
  await device.sync.ready();
  device.change(state([[1, 1]], [1]));
  const refresh = device.sync.refresh();
  await refreshStarted.promise;
  const one = device.sync.flush(), two = device.sync.flush();
  nextSession.resolve(session('alice', fresh(), 0));
  await saveStarted.promise;
  assert.equal(saves, 1);
  save.resolve({ state: toWire(state([[1, 1]], [1])), revision: 1 });
  await Promise.all([refresh, one, two]);
  assert.equal(saves, 1);
  device.sync.destroy();
}

// A stale refresh for Alice cannot undo a newer successful sign-in as Bob.
{
  const oldSession = deferred(), refreshStarted = deferred();
  let sessions = 0;
  const device = setup(async path => {
    if (path === 'session') {
      if (++sessions === 1) return session('alice', state([[1, .7]], [1]), 1);
      refreshStarted.resolve();
      return oldSession.promise;
    }
    if (path === 'login') return session('bob', state([[2, 1]], [2]), 2);
    throw new Error(`Unexpected request ${path}`);
  });
  await device.sync.ready();
  const refreshing = device.sync.refresh();
  await refreshStarted.promise;
  await device.sync.authenticate('login', { email: 'bob@example.com', password: 'a long passphrase' });
  oldSession.resolve(session('alice', state([[1, 1]], [1]), 8));
  await refreshing;
  assert.equal(device.sync.user.id, 'bob');
  assert.deepEqual(device.get().saved.map(item => item.id), [2]);
  device.sync.destroy();
}

// Failed saves are never blindly retried or discarded, and logout cannot claim
// to have succeeded while changes remain unsynced.
{
  let saves = 0, logouts = 0;
  const device = setup(async path => {
    if (path === 'session') return session('alice', fresh(), 0);
    if (path === 'state') { saves++; throw new AccountRequestError('Offline'); }
    if (path === 'logout') { logouts++; return {}; }
    throw new Error(`Unexpected request ${path}`);
  });
  await device.sync.ready();
  device.change(state([[1, 1]], [1]));
  await device.sync.flush();
  assert.equal(saves, 1);
  await assert.rejects(device.sync.logout(), /Sync your changes before signing out/);
  assert.equal(logouts, 0);
  assert.equal(device.sync.user.id, 'alice');
  assert.equal(JSON.parse(device.storage.getItem(accountKey('alice'))).pending, true);
  device.sync.destroy();
}

// Other-tab pending additions are merged locally before an offline refresh so
// one tab cannot erase another tab's unsent copy in shared browser storage.
{
  const device = setup(async path => {
    if (path === 'session') return session('alice', fresh(), 0);
    throw new Error(`Unexpected request ${path}`);
  });
  await device.sync.ready();
  device.change(state([[1, 1]], [1]));
  device.sync.request = async () => { throw new AccountRequestError('Offline'); };
  const other = { user: user('alice'), base: toWire(fresh()), local: state([[2, .7]], [2]), revision: 0, pending: true };
  device.storage.setItem(accountKey('alice'), JSON.stringify(other));
  await device.sync.storageChanged({ key: accountKey('alice'), newValue: JSON.stringify(other) });
  assert.deepEqual(device.get().saved.map(item => item.id), [1, 2]);
  assert.deepEqual(JSON.parse(device.storage.getItem(accountKey('alice'))).local.saved.map(item => item.id), [1, 2]);
  assert.equal(sameState(state([[1, 1], [2, .7]], [1, 2]), state([[2, .7], [1, 1]], [2, 1])), true);
  device.sync.destroy();
}

// Explicit signout in another tab immediately hides account state. A pending
// copy remains inactive and recoverable without recreating the active marker.
{
  const storage = memory();
  storage.setItem(GUEST_KEY, JSON.stringify(state([[9, .7]], [9])));
  const device = setup(async path => {
    if (path === 'session') return session('alice', state([[1, 1]], [1]), 1);
    throw new Error(`Unexpected request ${path}`);
  }, storage);
  await device.sync.ready();
  device.change(state([[1, -1]], []));
  storage.removeItem(ACTIVE_KEY);
  storage.removeItem(accountKey('alice'));
  await device.sync.storageChanged({ key: ACTIVE_KEY, newValue: null });
  assert.equal(device.sync.user, null);
  assert.deepEqual(device.get().saved.map(item => item.id), [9]);
  assert.equal(storage.getItem(ACTIVE_KEY), null);
  assert.equal(JSON.parse(storage.getItem(accountKey('alice'))).pending, true);
  device.change(state([[9, -1]], []));
  assert.equal(storage.getItem(ACTIVE_KEY), null, 'guest edits cannot resurrect a signed-out account');
  device.sync.destroy();
}

// Requests carry only same-origin cookies and the explicit CSRF header; a
// deadline aborts a hung request without resending a mutation.
{
  let captured;
  const result = await accountRequest('state', { state: toWire(fresh()), revision: 0 }, {
    csrf: 'token', fetcher: async (url, options) => {
      captured = { url, options };
      return { ok: true, status: 200, json: async () => ({ revision: 1, state: toWire(fresh()) }) };
    },
  });
  assert.equal(result.revision, 1);
  assert.equal(captured.options.credentials, 'same-origin');
  assert.equal(captured.options.cache, 'no-store');
  assert.equal(captured.options.headers['X-Account-Request'], '1');
  assert.equal(captured.options.headers['X-CSRF-Token'], 'token');
  let attempts = 0;
  await assert.rejects(accountRequest('state', {}, { timeout: 5, fetcher: (_url, options) => {
    attempts++;
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => {
      const error = new Error('Aborted'); error.name = 'AbortError'; reject(error);
    }));
  } }), /took too long/);
  assert.equal(attempts, 1);
}

console.log('Account isolation, guest restoration, deletion-aware merges, ordered saves, bounded conflicts, expiration recovery and request security passed.');
