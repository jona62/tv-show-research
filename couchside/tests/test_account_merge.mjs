import assert from 'node:assert/strict';
import { AccountSync, AccountRequestError, accountKey, mergeStates, toWire } from '../client/account-state.js';
// The built module has the shared dependencies supplied by Couchside's build.
// Use its real limits instead of a permissive test-only sanitizer.
import { fresh, sanitize } from '../public/assets/scripts/start.js';

const state = (profile = [], saved = []) => sanitize({ ...fresh(),
  profile: profile.map(([id, weight]) => ({ id, weight, name: `Show ${id}` })),
  saved: saved.map(id => ({ id, name: `Show ${id}` })), onboarded: profile.length > 0 });
const ids = items => items.map(item => item.id).sort((a, b) => a - b);
const user = { id: 'alice', email: 'alice@example.com' };
const noRemovals = () => ({ profile: [], saved: [] });
const session = (value, revision, removals = noRemovals()) => ({
  user, csrf: 'alice-csrf', state: toWire(value), revision, removals,
});
const memory = () => {
  const values = new Map();
  return { getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
};
function device(request, initial = fresh(), storage = memory(), writer) {
  let current = initial;
  const statuses = [];
  const sync = new AccountSync({ getState: () => current,
    applyState: async (next, context) => { if (context.current()) current = next; },
    fresh, sanitize, request, storage, delay: 600000,
    onStatus: value => statuses.push(value) });
  if (writer) { sync.writer = writer; sync.sequence = 0; }
  return { sync, storage, statuses, get: () => current,
    change(next) { current = next; sync.changed(); } };
}

let passed = 0;
const failures = [];
async function check(name, run) {
  try { await run(); passed++; }
  catch (error) { failures.push(name); console.error(`${name}: ${error.stack || error}`); }
}

await check('Sign-in accepts the atomic server import without replaying guest ratings', async () => {
  const guest = state([[1, -1], [2, .7]], [3]);
  const account = state([[1, 1], [2, .7]], [4, 3]);
  let logins = 0, saves = 0;
  const client = device(async (path, body) => {
    if (path === 'session') throw new AccountRequestError('Anonymous', 401);
    if (path === 'login') {
      logins++;
      assert.deepEqual(body.guest_state, toWire(guest));
      assert.equal(Object.hasOwn(body, 'merge'), false);
      return session(account, 5);
    }
    if (path === 'state') { saves++; throw new Error('Atomic sign-in must not rewrite the imported account.'); }
    throw new Error(`Unexpected request ${path}`);
  }, guest);
  try {
    await client.sync.ready();
    await client.sync.authenticate('login', { email: user.email, password: 'a sufficiently long passphrase' });
    await client.sync.flush();
    assert.equal(logins, 1);
    assert.equal(saves, 0);
    assert.equal(client.sync.pending, false);
    assert.equal(client.get().profile.find(item => item.id === 1).weight, 1);
    assert.deepEqual(ids(client.get().profile), [1, 2]);
    assert.deepEqual(ids(client.get().saved), [3, 4]);
  } finally { client.sync.destroy(); }
});

await check('Concurrent same-show changes preserve the account choice and independent additions', () => {
  const base = state([[1, .7]], [1]);
  const local = state([[1, -1], [2, .35]], [1, 2]);
  const remote = state([[1, 1], [3, .7]], [1, 3]);
  const merged = mergeStates(base, local, remote, { removals: noRemovals(), revision: 1 });
  assert.equal(merged.profile.find(item => item.id === 1).weight, 1);
  assert.deepEqual(ids(merged.profile), [1, 2, 3]);
  assert.deepEqual(ids(merged.saved), [1, 2, 3]);
});

await check('Hidden remote add/remove history suppresses an older offline addition', () => {
  const removals = { profile: [{ id: 1, revision: 2 }], saved: [{ id: 1, revision: 2 }] };
  const pending = state([[1, 1], [2, .7]], [1, 2]);
  const merged = mergeStates(fresh(), pending, fresh(), { removals, revision: 0 });
  assert.deepEqual(ids(merged.profile), [2]);
  assert.deepEqual(ids(merged.saved), [2]);
});

await check('A re-add made after observing the removal remains a new choice', () => {
  const removals = { profile: [{ id: 1, revision: 2 }], saved: [{ id: 1, revision: 2 }] };
  const merged = mergeStates(fresh(), state([[1, .7]], [1]), fresh(), { removals, revision: 2 });
  assert.deepEqual(ids(merged.profile), [1]);
  assert.deepEqual(ids(merged.saved), [1]);
});

await check('A 201-show union is rejected before production validation can trim it', () => {
  const common = Array.from({ length: 199 }, (_, index) => index + 1);
  const base = state([], common);
  const local = state([], [...common, 500]);
  const remote = state([], [...common, 600]);
  const before = JSON.stringify({ base, local, remote });
  assert.throws(() => mergeStates(base, local, remote), error =>
    error instanceof AccountRequestError && error.status === 422 && error.data.capacity === true);
  assert.equal(JSON.stringify({ base, local, remote }), before);
  assert.equal(local.saved.length, 200);
  assert.equal(remote.saved.length, 200);
  assert.equal(local.saved.some(item => item.id === 500), true);
  assert.equal(remote.saved.some(item => item.id === 600), true);
});

await check('An oversized refresh preserves pending work and retries safely after making room', async () => {
  const common = Array.from({ length: 199 }, (_, index) => index + 1);
  const base = state([], common);
  const local = state([], [...common, 500]);
  let serverState = state([], [...common, 600]), serverRevision = 2;
  let reads = 0, attempts = 0, commits = 0;
  const client = device(async (path, body) => {
    if (path === 'session') return reads++ === 0 ? session(base, 1) : session(serverState, serverRevision);
    if (path === 'state') {
      attempts++;
      if (body.revision !== serverRevision) throw new AccountRequestError('Conflict', 409, {
        state: toWire(serverState), revision: serverRevision, removals: noRemovals(),
      });
      assert.equal(body.state.saved.length, 200);
      assert.equal(body.state.saved.some(item => item.id === 500), true);
      assert.equal(body.state.saved.some(item => item.id === 600), true);
      assert.equal(body.state.saved.some(item => item.id === 1), false);
      serverState = body.state;
      commits++;
      return { state: serverState, revision: ++serverRevision,
        removals: { profile: [], saved: commits === 1 ? [{ id: 1, revision: serverRevision }] : [] } };
    }
    throw new Error(`Unexpected request ${path}`);
  });
  try {
    await client.sync.ready();
    client.change(local);
    const cacheBefore = client.storage.getItem(accountKey(user.id));
    await client.sync.refresh();
    assert.equal(client.sync.blocked, true);
    assert.equal(client.sync.connected, true);
    assert.equal(client.sync.pending, true);
    assert.equal(client.sync.revision, 1);
    assert.deepEqual(toWire(client.sync.base), toWire(base));
    assert.deepEqual(toWire(client.get()), toWire(local));
    assert.equal(client.storage.getItem(accountKey(user.id)), cacheBefore);
    await client.sync.flush();
    assert.equal(attempts, 0, 'A capacity warning must not upload a clipped list.');
    assert.equal(serverState.saved.some(item => item.id === 600), true);

    client.change(state([], local.saved.filter(item => item.id !== 1).map(item => item.id)));
    await client.sync.flush();
    assert.equal(attempts, 2, 'The old revision must reconcile before a successful retry.');
    assert.equal(commits, 1);
    assert.equal(client.sync.blocked, false);
    assert.equal(client.sync.pending, false);
    assert.equal(client.get().saved.length, 200);
    assert.deepEqual(ids(client.get().saved), ids(serverState.saved));
  } finally { client.sync.destroy(); }
});

await check('A stale other-tab cache contributes only its real edits', async () => {
  let online = true;
  const removals = { profile: [{ id: 1, revision: 2 }], saved: [{ id: 1, revision: 2 }] };
  const client = device(async path => {
    if (!online) throw new AccountRequestError('Offline');
    if (path === 'session') return session(fresh(), 2, removals);
    throw new Error(`Unexpected request ${path}`);
  });
  try {
    await client.sync.ready();
    online = false;
    const other = { user, base: toWire(state([[1, .7]], [1])),
      local: state([[1, .7], [3, -1]], [1, 2]), revision: 1, pending: true };
    await client.sync.storageChanged({ key: accountKey(user.id), newValue: JSON.stringify(other) });
    assert.equal(client.sync.revision, 2);
    assert.equal(client.sync.pending, true);
    assert.deepEqual(ids(client.get().profile), [3]);
    assert.deepEqual(ids(client.get().saved), [2]);
    const retained = JSON.parse(client.storage.getItem(accountKey(user.id)));
    assert.deepEqual(ids(retained.local.profile), [3]);
    assert.deepEqual(ids(retained.local.saved), [2]);
  } finally { client.sync.destroy(); }
});

await check('A newer tab snapshot cancels its older deferred addition, including later echoes', async () => {
  const common = Array.from({ length: 199 }, (_, index) => index + 1);
  const base = state([], common), storage = memory();
  let serverState = base, serverRevision = 1, online = true, commits = 0;
  const request = async (path, body) => {
    if (path === 'session') {
      if (!online) throw new AccountRequestError('Offline');
      return session(serverState, serverRevision);
    }
    if (path === 'state') {
      assert.equal(body.revision, serverRevision);
      assert.equal(body.state.saved.some(item => item.id === 600), false,
        'Another tab withdrew this addition before it was acknowledged.');
      serverState = body.state;
      commits++;
      return { state: serverState, revision: ++serverRevision,
        removals: { profile: [], saved: [{ id: 1, revision: serverRevision }] } };
    }
    throw new Error(`Unexpected request ${path}`);
  };
  const a = device(request, fresh(), storage, 'tab-a');
  const b = device(request, fresh(), storage, 'tab-b');
  try {
    await a.sync.ready();
    await b.sync.ready();
    a.change(state([], [...common, 500]));
    b.change(state([], [...common, 600]));
    const first = JSON.parse(storage.getItem(accountKey(user.id)));
    assert.equal(first.writer, 'tab-b');
    assert.equal(Number.isSafeInteger(first.sequence) && first.sequence > 0, true);
    online = false;
    await a.sync.storageChanged({ key: accountKey(user.id), newValue: JSON.stringify(first) });
    assert.equal(a.sync.blocked, true);

    b.change(base);
    const canceled = JSON.parse(storage.getItem(accountKey(user.id)));
    assert.equal(canceled.writer, 'tab-b');
    assert.equal(canceled.sequence > first.sequence, true);
    await a.sync.storageChanged({ key: accountKey(user.id), newValue: JSON.stringify(canceled) });
    a.change(state([], [...common.filter(id => id !== 1), 500]));
    online = true;
    await a.sync.refresh();
    await a.sync.flush();
    assert.equal(commits, 1);
    assert.equal(a.get().saved.length, 199);
    assert.equal(a.get().saved.some(item => item.id === 500), true);
    assert.equal(a.get().saved.some(item => item.id === 600), false);

    // A third tab can carry an old deferred B snapshot after B's cancellation
    // has already been applied. The cancellation receipt must survive reload.
    const restarted = device(request, fresh(), storage, 'tab-a-reloaded');
    try {
      await restarted.sync.ready();
      const echo = { user, writer: 'tab-c', sequence: 1, base: toWire(serverState),
        local: state([], [...serverState.saved.map(item => item.id), 700]),
        revision: serverRevision, pending: true, deferred: [first] };
      await restarted.sync.storageChanged({ key: accountKey(user.id), newValue: JSON.stringify(echo) });
      assert.equal(restarted.sync.blocked, false, 'An old nested snapshot must not cause another capacity warning.');
      assert.equal(restarted.get().saved.some(item => item.id === 700), true);
      assert.equal(restarted.get().saved.some(item => item.id === 600), false);
      await restarted.sync.flush();
      assert.equal(commits, 2);
      assert.equal(serverState.saved.length, 200);
    } finally { restarted.sync.destroy(); }
  } finally { a.sync.destroy(); b.sync.destroy(); }
});

await check('Independent deferred writers with the same base both survive recovery', async () => {
  const common = Array.from({ length: 199 }, (_, index) => index + 1);
  const base = state([], common), storage = memory();
  let serverState = base, serverRevision = 1, commits = 0;
  const request = async (path, body) => {
    if (path === 'session') return session(serverState, serverRevision);
    if (path === 'state') {
      assert.equal(body.revision, serverRevision);
      assert.deepEqual(ids(body.state.saved), [...common.filter(id => ![1, 2].includes(id)), 500, 600, 700]);
      serverState = body.state;
      commits++;
      return { state: serverState, revision: ++serverRevision,
        removals: { profile: [], saved: [1, 2].map(id => ({ id, revision: serverRevision })) } };
    }
    throw new Error(`Unexpected request ${path}`);
  };
  const a = device(request, fresh(), storage, 'tab-a');
  const b = device(request, fresh(), storage, 'tab-b');
  const c = device(request, fresh(), storage, 'tab-c');
  try {
    await a.sync.ready(); await b.sync.ready(); await c.sync.ready();
    a.change(state([], [...common, 500]));
    b.change(state([], [...common, 600]));
    await a.sync.storageChanged({ key: accountKey(user.id), newValue: storage.getItem(accountKey(user.id)) });
    c.change(state([], [...common, 700]));
    await a.sync.storageChanged({ key: accountKey(user.id), newValue: storage.getItem(accountKey(user.id)) });
    assert.equal(a.sync.blocked, true);
    assert.deepEqual(a.sync.deferred.map(item => item.writer).sort(), ['tab-b', 'tab-c']);
    a.change(state([], [...common.filter(id => ![1, 2].includes(id)), 500]));
    await a.sync.flush();
    assert.equal(commits, 1);
    assert.equal(a.sync.pending, false);
    assert.equal(a.sync.deferred.length, 0);
    assert.equal(a.get().saved.length, 200);
  } finally { a.sync.destroy(); b.sync.destroy(); c.sync.destroy(); }
});

await check('A tab ignores its own older edit echoed through another tab after cancellation', async () => {
  const base = fresh(), storage = memory();
  let serverState = base, serverRevision = 1, commits = 0;
  const client = device(async (path, body) => {
    if (path === 'session') return session(serverState, serverRevision);
    if (path === 'state') {
      assert.equal(body.revision, serverRevision);
      assert.deepEqual(ids(body.state.profile), [700]);
      assert.deepEqual(ids(body.state.saved), [700]);
      serverState = body.state;
      commits++;
      return { state: serverState, revision: ++serverRevision, removals: noRemovals() };
    }
    throw new Error(`Unexpected request ${path}`);
  }, base, storage, 'tab-own');
  try {
    await client.sync.ready();
    client.change(state([[600, .7]], [600]));
    const older = JSON.parse(storage.getItem(accountKey(user.id)));
    assert.equal(older.writer, 'tab-own');
    assert.equal(Number.isSafeInteger(older.sequence) && older.sequence > 0, true);
    client.change(base);
    assert.equal(client.sync.sequence > older.sequence, true);
    assert.equal(client.sync.pending, true, 'The cancellation remains pending until its deletion is acknowledged.');

    const echo = { user, writer: 'tab-other', sequence: 1, base: toWire(base),
      local: state([[700, 1]], [700]), revision: 1, pending: true, deferred: [older] };
    await client.sync.storageChanged({ key: accountKey(user.id), newValue: JSON.stringify(echo) });
    assert.deepEqual(ids(client.get().profile), [700]);
    assert.deepEqual(ids(client.get().saved), [700]);
    assert.equal(client.sync.deferred.length, 0);
    assert.equal(client.sync.blocked, false);
    await client.sync.flush();
    assert.equal(commits, 1);
    assert.equal(client.sync.pending, false);
  } finally { client.sync.destroy(); }
});

await check('A republished offline snapshot carries additions from another writer', async () => {
  const storage = memory();
  let online = true;
  const request = async path => {
    if (!online) throw new AccountRequestError('Offline');
    if (path === 'session') return session(fresh(), 1);
    throw new Error(`Unexpected request ${path}`);
  };
  const a = device(request, fresh(), storage, 'tab-a');
  const b = device(request, fresh(), storage, 'tab-b');
  const c = device(request, fresh(), storage, 'tab-c');
  try {
    await a.sync.ready(); await b.sync.ready(); await c.sync.ready();
    online = false;
    a.change(state([[500, .7]], [500]));
    const first = storage.getItem(accountKey(user.id));
    await c.sync.storageChanged({ key: accountKey(user.id), newValue: first });
    b.change(state([[600, 1]], [600]));
    const original = storage.getItem(accountKey(user.id));
    await a.sync.storageChanged({ key: accountKey(user.id), newValue: original });
    assert.deepEqual(ids(a.get().saved), [500, 600]);

    // A reader may receive the combined cache before the origin event. A's
    // receipt for B is valid only if B's pending delta travels with it.
    const republished = storage.getItem(accountKey(user.id));
    await c.sync.storageChanged({ key: accountKey(user.id), newValue: republished });
    assert.deepEqual(ids(c.get().profile), [500, 600]);
    assert.deepEqual(ids(c.get().saved), [500, 600]);
    const retained = JSON.parse(storage.getItem(accountKey(user.id)));
    assert.deepEqual(ids(retained.local.saved), [500, 600]);
    await c.sync.storageChanged({ key: accountKey(user.id), newValue: original });
    assert.deepEqual(ids(c.get().saved), [500, 600]);
  } finally { a.sync.destroy(); b.sync.destroy(); c.sync.destroy(); }
});

await check('A newer source snapshot retracts its already-applied pending addition', async () => {
  const storage = memory();
  let online = true, commits = 0;
  const request = async (path, body) => {
    if (path === 'session') {
      if (!online) throw new AccountRequestError('Offline');
      return session(fresh(), 1);
    }
    if (path === 'state') {
      commits++;
      assert.equal(body.state.profile.some(item => item.id === 600), false);
      assert.equal(body.state.saved.some(item => item.id === 600), false);
      assert.deepEqual(body.removed, { profile: [600], saved: [600] });
      return { state: body.state, revision: 2,
        removals: { profile: [{ id: 600, revision: 2 }], saved: [{ id: 600, revision: 2 }] } };
    }
    throw new Error(`Unexpected request ${path}`);
  };
  const a = device(request, fresh(), storage, 'tab-a');
  const b = device(request, fresh(), storage, 'tab-b');
  try {
    await a.sync.ready(); await b.sync.ready();
    online = false;
    a.change(state([[600, .7]], [600]));
    const added = JSON.parse(storage.getItem(accountKey(user.id)));
    await b.sync.storageChanged({ key: accountKey(user.id), newValue: JSON.stringify(added) });
    assert.deepEqual(ids(b.get().saved), [600]);
    a.change(fresh());
    const canceled = JSON.parse(storage.getItem(accountKey(user.id)));
    assert.equal(canceled.sequence > added.sequence, true);
    await b.sync.storageChanged({ key: accountKey(user.id), newValue: JSON.stringify(canceled) });
    assert.deepEqual(ids(b.get().profile), []);
    assert.deepEqual(ids(b.get().saved), []);
    assert.equal(b.sync.pending, true, 'The vanished addition must still publish its removal intent.');
    online = true;
    await b.sync.refresh();
    await b.sync.flush();
    assert.equal(commits, 1, 'An empty-state commit records the cancellation for future devices.');
    assert.equal(b.sync.pending, false);
  } finally { a.sync.destroy(); b.sync.destroy(); }
});

await check('An informed re-add survives acknowledgment of its earlier in-flight deletion', async () => {
  let release, started, firstBody;
  const firstStarted = new Promise(resolve => { started = resolve; });
  let commits = 0;
  const client = device(async (path, body) => {
    if (path === 'session') return session(state([[600, .7]], [600]), 1);
    if (path === 'state') {
      commits++;
      if (commits === 1) {
        firstBody = body;
        return new Promise(resolve => { release = resolve; started(); });
      }
      assert.equal(body.revision, 2);
      assert.deepEqual(ids(body.state.profile), [600]);
      assert.deepEqual(ids(body.state.saved), [600]);
      assert.equal(body.state.profile[0].weight, 1);
      assert.deepEqual(body.removed, { profile: [], saved: [] });
      return { state: body.state, revision: 3, removals: noRemovals() };
    }
    throw new Error(`Unexpected request ${path}`);
  });
  try {
    await client.sync.ready();
    client.change(fresh());
    const saving = client.sync.flush();
    await firstStarted;
    assert.equal(firstBody.revision, 1);
    assert.deepEqual(ids(firstBody.state.profile), []);
    assert.deepEqual(ids(firstBody.state.saved), []);
    assert.deepEqual(firstBody.removed, { profile: [600], saved: [600] });
    client.change(state([[600, 1]], [600]));
    release({ state: toWire(fresh()), revision: 2,
      removals: { profile: [{ id: 600, revision: 2 }], saved: [{ id: 600, revision: 2 }] } });
    await saving;
    assert.equal(commits, 2);
    assert.equal(client.sync.pending, false);
    assert.deepEqual(ids(client.get().profile), [600]);
    assert.deepEqual(ids(client.get().saved), [600]);
    assert.equal(client.get().profile[0].weight, 1);
  } finally { client.sync.destroy(); }
});

await check('An older forwarded addition cannot erase a pending cancellation', async () => {
  const storage = memory();
  let online = true;
  const request = async path => {
    if (!online) throw new AccountRequestError('Offline');
    if (path === 'session') return session(fresh(), 1);
    throw new Error(`Unexpected request ${path}`);
  };
  const a = device(request, fresh(), storage, 'tab-a');
  const b = device(request, fresh(), storage, 'tab-b');
  try {
    await a.sync.ready(); await b.sync.ready();
    online = false;
    a.change(state([[600, .7]], [600]));
    await b.sync.storageChanged({ key: accountKey(user.id), newValue: storage.getItem(accountKey(user.id)) });
    const forwarded = storage.getItem(accountKey(user.id));
    assert.equal(JSON.parse(forwarded).writer, 'tab-b');
    a.change(fresh());
    await a.sync.storageChanged({ key: accountKey(user.id), newValue: forwarded });
    assert.deepEqual(ids(a.get().profile), []);
    assert.deepEqual(ids(a.get().saved), []);
    assert.equal(a.sync.pending, true);
    const retained = JSON.parse(storage.getItem(accountKey(user.id)));
    assert.deepEqual(retained.deleted.profile.map(item => item.id), [600]);
    assert.deepEqual(retained.deleted.saved.map(item => item.id), [600]);
  } finally { a.sync.destroy(); b.sync.destroy(); }
});

await check('More than 200 pending saved cancellations are acknowledged in complete batches', async () => {
  const batches = [];
  let serverRevision = 1;
  const client = device(async (path, body) => {
    if (path === 'session') return session(fresh(), serverRevision);
    if (path === 'state') {
      assert.equal(body.revision, serverRevision);
      assert.deepEqual(ids(body.state.saved), []);
      assert.deepEqual(body.removed.profile, []);
      assert.equal(body.removed.saved.length > 0 && body.removed.saved.length <= 200, true);
      batches.push([...body.removed.saved]);
      return { state: body.state, revision: ++serverRevision,
        removals: { profile: [], saved: body.removed.saved.map(id => ({ id, revision: serverRevision })) } };
    }
    throw new Error(`Unexpected request ${path}`);
  });
  try {
    await client.sync.ready();
    client.change(state([], Array.from({ length: 200 }, (_, index) => index + 1)));
    client.change(fresh());
    client.change(state([], [201]));
    client.change(fresh());
    assert.equal(client.sync.deleted.saved.length, 201);
    assert.equal(client.sync.pending, true);
    await client.sync.flush();
    assert.deepEqual(batches.map(batch => batch.length), [200, 1]);
    assert.deepEqual(batches.flat().sort((a, b) => a - b), Array.from({ length: 201 }, (_, index) => index + 1));
    assert.equal(client.sync.deleted.saved.length, 0);
    assert.equal(client.sync.pending, false);
    assert.deepEqual(ids(client.get().saved), []);
  } finally { client.sync.destroy(); }
});

await check('An older forwarded deletion cannot undo an in-flight explicit re-add', async () => {
  const storage = memory();
  let serverState = state([[600, .7]], [600]), serverRevision = 1, commits = 0;
  let release, started, firstBody;
  const firstStarted = new Promise(resolve => { started = resolve; });
  const request = async (path, body) => {
    if (path === 'session') return session(serverState, serverRevision, serverRevision > 1
      ? { profile: [{ id: 600, revision: 2 }], saved: [{ id: 600, revision: 2 }] } : noRemovals());
    if (path === 'state') {
      commits++;
      if (commits === 1) {
        firstBody = body;
        return new Promise(resolve => {
          release = () => {
            serverState = fresh(); serverRevision = 2;
            resolve({ state: toWire(serverState), revision: serverRevision,
              removals: { profile: [{ id: 600, revision: 2 }], saved: [{ id: 600, revision: 2 }] } });
          };
          started();
        });
      }
      assert.equal(body.revision, 2);
      assert.deepEqual(ids(body.state.saved), [600]);
      assert.deepEqual(ids(body.state.profile), [600]);
      assert.equal(body.state.profile[0].weight, 1);
      assert.deepEqual(body.removed, { profile: [], saved: [] });
      serverState = body.state; serverRevision = 3;
      return { state: serverState, revision: serverRevision, removals: noRemovals() };
    }
    throw new Error(`Unexpected request ${path}`);
  };
  const a = device(request, fresh(), storage, 'tab-a');
  const b = device(request, fresh(), storage, 'tab-b');
  try {
    await a.sync.ready(); await b.sync.ready();
    a.change(fresh());
    await b.sync.storageChanged({ key: accountKey(user.id), newValue: storage.getItem(accountKey(user.id)) });
    const forwarded = storage.getItem(accountKey(user.id));
    assert.equal(JSON.parse(forwarded).writer, 'tab-b');
    const saving = a.sync.flush();
    await firstStarted;
    assert.deepEqual(firstBody.removed, { profile: [600], saved: [600] });
    a.change(state([[600, 1]], [600]));
    const receiving = a.sync.storageChanged({ key: accountKey(user.id), newValue: forwarded });
    release();
    await saving;
    await receiving;
    assert.equal(commits, 2);
    assert.deepEqual(ids(a.get().saved), [600]);
    assert.deepEqual(ids(a.get().profile), [600]);
    assert.equal(a.get().profile[0].weight, 1);
    assert.equal(a.sync.pending, false);
  } finally { a.sync.destroy(); b.sync.destroy(); }
});

if (failures.length) throw new Error(`${failures.length} account merge regression(s) failed: ${failures.join('; ')}`);
console.log(`All ${passed} account merge regressions passed with production state validation.`);
