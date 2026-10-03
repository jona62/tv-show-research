import assert from 'node:assert/strict';
import { createTrackingState, TrackingError, trackingRequest, airedEpisodes,
  watchedCount, watchedThrough, isCaughtUp } from '../client/watch-tracking-state.js';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const account = id => ({ user: { id }, csrf: `csrf-${id}` });
const flags = id => ({ userId: id, features: { watch_tracking: Boolean(id) } });
const record = (showId, watched = [], intent = 'watching') => ({ show_id: showId, intent,
  progress_known: true, deleted: false, episode_states: watched.map(episode_id => ({ episode_id, watched: true })) });
const snapshot = (owner = 'alice', revision = 1, records = [record(10)]) => ({ user_id: owner,
  tracking_revision: revision, tracking: records });
const receipt = (body, revision = 2, records = [record(10, [101])]) => ({ ...snapshot('alice', revision, records),
  operation_id: body.operation_id, operation_revision: revision });
function setup(request = async () => snapshot(), options = {}) {
  let context = account('alice'), operations = 0;
  const changes = [];
  const store = createTrackingState({ getAccount: () => context, request,
    operationId: () => `operation-${String(++operations).padStart(16, '0')}`,
    changed: value => changes.push(value), ...options });
  return { store, changes, set: value => { context = value; }, operations: () => operations };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

// Progress remains the last server snapshot until a valid save receipt arrives.
{
  const save = deferred(), calls = [];
  const device = setup(async (path, body, options) => {
    calls.push({ path, body, options });
    return body ? save.promise : snapshot();
  });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  const saving = device.store.mutate(10, 'episode', { episode_id: 101, watched: true });
  assert.equal(device.store.get().busy, true);
  assert.deepEqual(device.store.get().records, [record(10)]);
  assert.equal(device.store.get().revision, 1);
  const body = calls.at(-1).body;
  assert.equal(body.base_revision, 1);
  assert.equal(calls.at(-1).options.csrf, 'csrf-alice');
  await assert.rejects(device.store.mutate(10, 'episode', { episode_id: 102, watched: true }));
  save.resolve(receipt(body));
  await saving;
  assert.equal(device.store.get().busy, false);
  assert.deepEqual(device.store.get().records, [record(10, [101])]);
  assert.equal(device.store.get().revision, 2);
  assert.equal(device.store.get().error, '');
  device.store.destroy();
}

// Disable and account switches clear the prior owner's data synchronously.
// Older read responses cannot repopulate the new owner's snapshot.
{
  const alice = deferred(), bob = deferred();
  let calls = 0;
  const device = setup(() => ++calls === 1 ? alice.promise : bob.promise);
  device.store.activate(flags('alice'));
  const first = device.store.refresh();
  device.set(account('bob'));
  device.store.activate(flags('bob'));
  assert.deepEqual(device.store.get().records, []);
  assert.equal(device.store.get().loaded, false);
  const second = device.store.refresh();
  alice.resolve(snapshot('alice', 9, [record(99)]));
  await first;
  assert.deepEqual(device.store.get().records, []);
  bob.resolve(snapshot('bob', 3, [record(20)]));
  await second;
  assert.deepEqual(device.store.get().records, [record(20)]);
  device.store.activate(flags(null));
  assert.deepEqual(device.store.get(), { owner: '', enabled: false, records: [], revision: 0,
    loaded: false, busy: false, error: '' });
  device.store.destroy();
}

// A save or catalogue request completing after signout is rejected and cannot
// repaint saved state or provide private episode details to the next owner.
{
  const save = deferred(), catalogue = deferred();
  let body;
  const device = setup(async (path, payload) => {
    if (path) return catalogue.promise;
    if (payload) { body = payload; return save.promise; }
    return snapshot();
  });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  const saving = device.store.mutate(10, 'episode', { episode_id: 101, watched: true });
  const loading = device.store.catalogue(10);
  device.set({ user: null, csrf: null });
  device.store.activate(flags(null));
  save.resolve(receipt(body));
  catalogue.resolve({ user_id: 'alice', show_id: 10, episodes: [] });
  await assert.rejects(saving, /account changed/i);
  await assert.rejects(loading, /account changed/i);
  assert.deepEqual(device.store.get().records, []);
  assert.equal(device.store.get().loaded, false);
  assert.equal(device.store.get().busy, false);
  device.store.destroy();
}

// An ambiguous transport failure retries once with the exact same operation,
// so the server can return its receipt without applying the change twice.
{
  const bodies = [];
  const device = setup(async (path, body) => {
    if (!body) return snapshot();
    bodies.push(body);
    if (bodies.length === 1) throw new TrackingError('Connection closed');
    return receipt(body);
  });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  await device.store.mutate(10, 'episode', { episode_id: 101, watched: true });
  assert.equal(bodies.length, 2);
  assert.equal(bodies[0], bodies[1]);
  assert.equal(device.operations(), 1);
  assert.deepEqual(bodies[0], { episode_id: 101, watched: true,
    operation_id: 'operation-0000000000000001', base_revision: 1, show_id: 10, action: 'episode' });
  device.store.destroy();
}

// Transport failures, validation rejection and account expiration never mark
// unsaved episodes watched. Only ambiguous transport failures are retried.
for (const status of [0, 400, 401, 403, 503]) {
  let writes = 0;
  const device = setup(async (path, body) => {
    if (!body) return snapshot();
    writes++;
    throw new TrackingError('Save failed', status);
  });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  await assert.rejects(device.store.mutate(10, 'episode', { episode_id: 101, watched: true }), /Save failed/);
  assert.equal(writes, status === 0 ? 2 : 1);
  assert.deepEqual(device.store.get().records, [record(10)]);
  assert.equal(device.store.get().revision, 1);
  assert.equal(device.store.get().busy, false);
  assert.equal(device.store.get().error, 'Save failed');
  device.store.destroy();
}

// A conflicting save adopts the latest remote state while preserving the
// rejection, then the next deliberate action uses its new base revision.
{
  let calls = 0;
  const remote = snapshot('alice', 4, [record(10, [102], 'paused')]);
  const bodies = [];
  const device = setup(async (path, body) => {
    if (!body) return snapshot();
    bodies.push(body);
    if (++calls === 1) throw new TrackingError('Changed on another device', 409, remote);
    return receipt(body, 5, [record(10, [101, 102])]);
  });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  await assert.rejects(device.store.mutate(10, 'episode', { episode_id: 101, watched: true }), /another device/);
  assert.equal(calls, 1);
  assert.deepEqual(device.store.get().records, remote.tracking);
  assert.equal(device.store.get().revision, 4);
  assert.equal(device.store.get().error, 'Changed on another device');
  await device.store.mutate(10, 'episode', { episode_id: 101, watched: true });
  assert.equal(bodies[1].base_revision, 4);
  assert.notEqual(bodies[0].operation_id, bodies[1].operation_id);
  device.store.destroy();
}

// Mismatched read snapshots cannot leak another user's viewing history.
for (const data of [snapshot('bob'), { ...snapshot(), tracking_revision: -1 },
  { ...snapshot(), tracking: null }]) {
  const device = setup(async () => data);
  device.store.activate(flags('alice'));
  await device.store.refresh();
  assert.deepEqual(device.store.get().records, []);
  assert.equal(device.store.get().loaded, false);
  assert.match(device.store.get().error, /session/i);
  device.store.destroy();
}

// A delayed read must not roll back a successfully accepted newer mutation.
{
  const read = deferred();
  let reads = 0;
  const device = setup(async (path, body) => {
    if (body) return receipt(body, 3, [record(10, [101, 102])]);
    return ++reads === 1 ? snapshot() : read.promise;
  });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  const refreshing = device.store.refresh();
  await device.store.mutate(10, 'episode', { episode_id: 102, watched: true });
  read.resolve(snapshot('alice', 2, [record(10, [101])]));
  await refreshing;
  assert.equal(device.store.get().revision, 3);
  assert.deepEqual(device.store.get().records, [record(10, [101, 102])]);
  device.store.destroy();
}

// An HTTP success needs an acknowledgment of this operation, not merely any
// readable tracking snapshot. Partial or unrelated receipts cannot imply Saved.
for (const invalid of [data => ({ ...data, operation_id: 'different-operation' }),
  data => { const { operation_id, ...rest } = data; return rest; },
  data => ({ ...data, operation_revision: -1 }),
  data => ({ ...data, operation_revision: data.tracking_revision + 1 })]) {
  const device = setup(async (path, body) => body ? invalid(receipt(body)) : snapshot());
  device.store.activate(flags('alice'));
  await device.store.refresh();
  await assert.rejects(device.store.mutate(10, 'episode', { episode_id: 101, watched: true }));
  assert.deepEqual(device.store.get().records, [record(10)]);
  assert.equal(device.store.get().revision, 1);
  assert.equal(device.store.get().busy, false);
  device.store.destroy();
}

// A newer read received while a save is in flight cannot be replaced by an
// older save receipt or cause that unverifiable receipt to report Saved.
{
  const read = deferred(), save = deferred();
  let reads = 0, body;
  const device = setup(async (path, payload) => {
    if (payload) { body = payload; return save.promise; }
    return ++reads === 1 ? snapshot() : read.promise;
  });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  const refreshing = device.store.refresh();
  const saving = device.store.mutate(10, 'episode', { episode_id: 101, watched: true });
  read.resolve(snapshot('alice', 3, [record(10, [102], 'paused')]));
  await refreshing;
  save.resolve(receipt(body, 2));
  await assert.rejects(saving, /verified/i);
  assert.equal(device.store.get().revision, 3);
  assert.deepEqual(device.store.get().records, [record(10, [102], 'paused')]);
  device.store.destroy();
}

// Polling an unchanged remote snapshot does not publish a repaint that could
// remove a focused status/select control. Errors and recovery still publish.
{
  let failure = null;
  const device = setup(async () => { if (failure) throw failure; return snapshot(); });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  const painted = device.changes.length;
  await device.store.refresh();
  assert.equal(device.changes.length, painted);
  failure = new TrackingError('Offline');
  await device.store.refresh();
  assert.equal(device.changes.length, painted + 1);
  await device.store.refresh();
  assert.equal(device.changes.length, painted + 1, 'unchanged failures do not repeatedly remove controls');
  failure = null;
  await device.store.refresh();
  assert.equal(device.changes.length, painted + 2, 'recovery removes the old error');
  device.store.destroy();
}

// Authentication/feature denial prompts eligibility verification, while an
// old owner's denied read never revokes the replacement owner's session.
for (const status of [401, 403, 503]) {
  let denied = 0;
  const device = setup(async () => { throw new TrackingError('Denied', status); },
    { denied: () => denied++ });
  device.store.activate(flags('alice'));
  await device.store.refresh();
  assert.equal(denied, status === 503 ? 0 : 1);
  device.store.destroy();
}
{
  const stale = deferred();
  let reads = 0, denied = 0;
  const device = setup(() => ++reads === 1 ? stale.promise : Promise.resolve(snapshot('bob')),
    { denied: () => denied++ });
  device.store.activate(flags('alice'));
  const first = device.store.refresh();
  device.set(account('bob')); device.store.activate(flags('bob'));
  await device.store.refresh();
  stale.reject(new TrackingError('Old session expired', 401));
  await first;
  assert.equal(denied, 0);
  assert.deepEqual(device.store.get().records, [record(10)]);
  device.store.destroy();
}

// Contiguous progress stops at the first unwatched aired episode, regardless
// of individually watched episodes later in the series or unrecognized IDs.
{
  const episodes = [1, 2, 3, 4].map(id => ({ id, season: 1, number: id, released: id < 4 }));
  const show = { episodes, watched: [1, 3, 4, 99], progress_known: true,
    catalogue: { fresh: true, complete: true } };
  assert.deepEqual(airedEpisodes(show).map(e => e.id), [1, 2, 3]);
  assert.equal(watchedCount(show), 2);
  assert.equal(watchedThrough(show).id, 1);
  assert.equal(isCaughtUp(show), false);
  assert.equal(watchedThrough({ ...show, watched: [2, 3] }), null);
  assert.equal(watchedThrough({ ...show, watched: [1, 2, 3] }).id, 3);
}

// Caught up is a proof over known, fresh, complete regular episodes. An empty,
// stale, partial or uncertain release catalogue cannot claim it.
{
  const show = { episodes: [{ id: 1, released: true }, { id: 2, released: false }],
    watched: [1], progress_known: true, catalogue: { fresh: true, complete: true } };
  assert.equal(isCaughtUp(show), true);
  assert.equal(isCaughtUp({ ...show, progress_known: false }), false);
  assert.equal(isCaughtUp({ ...show, catalogue: { fresh: false, complete: true } }), false);
  assert.equal(isCaughtUp({ ...show, catalogue: { fresh: true, complete: false } }), false);
  assert.equal(isCaughtUp({ ...show, catalogue: { fresh: true, complete: true,
    expires_at: Date.now() / 1000 - 10 } }), false);
  assert.equal(isCaughtUp({ ...show, catalogue: { fresh: true, complete: true,
    expires_at: Date.now() / 1000 + 1000 } }), true);
  assert.equal(isCaughtUp({ ...show, episodes: [] }), false);
  for (const released of [null, undefined, 'true']) {
    assert.equal(isCaughtUp({ ...show, episodes: [...show.episodes, { id: 3, released }] }), false);
  }
}

// Requests keep private state out of shared caches and carry the live CSRF
// token on writes; non-JSON, server and transport failures retain typed status.
{
  const received = [];
  const fetcher = async (url, options) => {
    received.push({ url, options });
    return { ok: true, status: 200, json: async () => snapshot() };
  };
  await trackingRequest('', undefined, { fetcher });
  await trackingRequest('', { action: 'episode' }, { fetcher, csrf: 'session-token' });
  assert.equal(received[0].url, '/api/tracking');
  assert.equal(received[0].options.method, 'GET');
  assert.equal(received[0].options.credentials, 'same-origin');
  assert.equal(received[0].options.cache, 'no-store');
  assert.equal(received[1].options.method, 'POST');
  assert.equal(received[1].options.headers['X-CSRF-Token'], 'session-token');
  assert.equal(received[1].options.headers['X-Account-Request'], '1');
  await assert.rejects(trackingRequest('', {}, { fetcher: async () => ({ ok: false, status: 409,
    json: async () => ({ error: 'Conflict', ...snapshot() }) }) }), failure => failure.status === 409);
  await assert.rejects(trackingRequest('', undefined, { fetcher: async () => ({ ok: true, status: 200,
    json: async () => { throw new Error('Invalid JSON'); } }) }), /unreadable/);
  await assert.rejects(trackingRequest('', undefined, { fetcher: async () => { throw new Error('Offline'); } }),
    failure => failure instanceof TrackingError && failure.status === 0);
}

await settle();
console.log('Viewing progress isolation, saved receipts, conflicts, idempotent retries and conservative episode progress passed.');
