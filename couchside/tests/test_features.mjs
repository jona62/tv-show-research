import assert from 'node:assert/strict';
import { createFeatureFlags, experimentalKey, featureRequest, mountExperimentalMode } from '../client/features.js';
import { mountAccounts } from '../client/accounts.js';
import { ACTIVE_KEY } from '../client/account-state.js';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const memory = () => {
  const map = new Map();
  return { map, getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value),
    removeItem: key => map.delete(key) };
};
const account = id => ({ user: { id, email: `${id}@example.com` }, csrf: `csrf-${id}` });
const envelope = (id, allowed = true, enabled = true) => ({ user_id: id,
  experimental_allowed: allowed, features: { watch_tracking: enabled } });
const none = () => ({ user: null, csrf: null });
function setup({ storage = memory(), request = async () => envelope('alice'), context = account('alice'), timeout } = {}) {
  let current = context;
  const win = new EventTarget();
  const flags = createFeatureFlags({ getAccount: () => current, request, storage, win, timeout });
  return { flags, storage, win, set: value => { current = value; } };
}
const off = flags => {
  assert.equal(flags.get().experimentalAllowed, false);
  assert.equal(flags.get().experimentalEnabled, false);
  assert.equal(flags.get().features.watch_tracking, false);
};
const settle = () => new Promise(resolve => setImmediate(resolve));

// Verified eligibility still defaults off; only this owner's device preference
// opts in. Guest and cached identity alone cannot request or enable a feature.
{
  let calls = 0;
  const device = setup({ request: async () => { calls++; return envelope('alice'); }, context: none() });
  off(device.flags);
  await device.flags.accountChanged();
  assert.equal(calls, 0);
  device.set({ user: account('alice').user, csrf: null });
  await device.flags.accountChanged();
  assert.equal(calls, 0);
  device.set(account('alice'));
  await device.flags.accountChanged();
  assert.equal(device.flags.get().experimentalAllowed, true);
  assert.equal(device.flags.get().features.watch_tracking, false);
  assert.equal(device.flags.setExperimental(true), true);
  assert.equal(device.flags.get().features.watch_tracking, true);
  assert.equal(device.storage.getItem(experimentalKey('alice')), '1');
  device.flags.setExperimental(false);
  assert.equal(device.flags.get().features.watch_tracking, false);
  device.flags.destroy();
}

// Stored preferences are isolated by owner, remain recoverable after signout,
// and never turn into eligibility for a different account.
{
  const storage = memory();
  storage.setItem(experimentalKey('alice'), '1');
  storage.setItem('couchside-v1', 'guest list');
  const device = setup({ storage, request: async () => envelope(device.flags.get().userId) });
  await device.flags.accountChanged();
  assert.equal(device.flags.get().features.watch_tracking, true);
  device.set(account('bob'));
  const switching = device.flags.accountChanged();
  off(device.flags);
  await switching;
  assert.equal(device.flags.get().experimentalAllowed, true);
  assert.equal(device.flags.get().features.watch_tracking, false);
  assert.equal(storage.getItem(experimentalKey('bob')), null);
  device.set(none());
  await device.flags.accountChanged();
  off(device.flags);
  assert.equal(device.flags.setExperimental(true), false);
  assert.equal(storage.getItem(experimentalKey('alice')), '1');
  assert.equal(storage.getItem('couchside-v1'), 'guest list');
  device.flags.destroy();
}

// A late response from another owner or an older session cannot reveal the
// toggle. Changing auth context closes get() even before notification arrives.
{
  const first = deferred(), second = deferred();
  const signals = [];
  const device = setup({ request: ({ signal }) => {
    signals.push(signal);
    return signals.length === 1 ? first.promise : second.promise;
  } });
  const alice = device.flags.accountChanged();
  await settle();
  device.set(account('bob'));
  const bob = device.flags.accountChanged();
  assert.equal(signals[0].aborted, true);
  await settle();
  first.resolve(envelope('alice'));
  await alice;
  off(device.flags);
  second.resolve(envelope('bob'));
  await bob;
  device.flags.setExperimental(true);
  assert.equal(device.flags.get().features.watch_tracking, true);
  device.set({ ...account('bob'), csrf: 'new-session' });
  off(device.flags);
  assert.equal(device.flags.setExperimental(true), false);
  device.set(none());
  await device.flags.accountChanged();
  off(device.flags);
  device.flags.destroy();
}

// Failed, mismatched, malformed and denied envelopes all close eligibility,
// even when the device previously opted in or an allowed refresh failed.
for (const result of [null, {}, envelope('bob'), envelope(null), envelope('alice', false, false),
  envelope('alice', false, true), { ...envelope('alice'), experimental_allowed: 'true' },
  { ...envelope('alice'), features: { watch_tracking: 1 } }, new Error('Offline')]) {
  const storage = memory();
  storage.setItem(experimentalKey('alice'), '1');
  let reply = envelope('alice');
  const device = setup({ storage, request: async () => { if (reply instanceof Error) throw reply; return reply; } });
  await device.flags.accountChanged();
  assert.equal(device.flags.get().features.watch_tracking, true);
  reply = result;
  const refresh = device.flags.refresh();
  off(device.flags);
  await refresh;
  off(device.flags);
  assert.equal(device.flags.setExperimental(true), false);
  assert.equal(storage.getItem(experimentalKey('alice')), '1');
  device.flags.destroy();
}

// Eligibility and a user opt-in cannot activate a feature the server disabled.
{
  const device = setup({ request: async () => envelope('alice', true, false) });
  await device.flags.accountChanged();
  device.flags.setExperimental(true);
  assert.equal(device.flags.get().experimentalEnabled, true);
  assert.equal(device.flags.get().features.watch_tracking, false);
  device.flags.destroy();
}

// Other tabs can change only the current owner's preference. A storage error
// defaults off; a fresh session never inherits an in-memory opt-in.
{
  const device = setup();
  await device.flags.accountChanged();
  const notify = key => device.win.dispatchEvent(Object.assign(new Event('storage'), { key }));
  device.storage.setItem(experimentalKey('bob'), '1');
  notify(experimentalKey('bob'));
  assert.equal(device.flags.get().experimentalEnabled, false);
  device.storage.setItem(experimentalKey('alice'), '1');
  notify(experimentalKey('alice'));
  assert.equal(device.flags.get().features.watch_tracking, true);
  device.storage.removeItem(experimentalKey('alice'));
  notify(experimentalKey('alice'));
  assert.equal(device.flags.get().features.watch_tracking, false);
  device.flags.destroy();
  const unavailable = { getItem() { throw new Error('Denied'); }, setItem() { throw new Error('Denied'); } };
  const privateDevice = setup({ storage: unavailable });
  await privateDevice.flags.accountChanged();
  assert.equal(privateDevice.flags.get().experimentalEnabled, false);
  privateDevice.flags.setExperimental(true);
  assert.equal(privateDevice.flags.get().features.watch_tracking, true);
  privateDevice.flags.destroy();
  const nextSession = setup({ storage: unavailable });
  await nextSession.flags.accountChanged();
  assert.equal(nextSession.flags.get().experimentalEnabled, false);
  nextSession.flags.destroy();
}

// Timed-out and destroyed requests cannot revive eligibility even if an
// injected request ignores its abort signal and resolves afterward.
for (const destroy of [false, true]) {
  const pending = deferred();
  const device = setup({ request: () => pending.promise, timeout: 1 });
  const checking = device.flags.accountChanged();
  if (destroy) device.flags.destroy();
  else await new Promise(resolve => setTimeout(resolve, 5));
  pending.resolve(envelope('alice'));
  await checking;
  off(device.flags);
  device.flags.destroy();
}

// The real request is session-bound and never reuses a cached public response.
{
  let received;
  const signal = new AbortController().signal;
  const result = await featureRequest({ signal, fetcher: async (url, options) => {
    received = { url, options };
    return { ok: true, json: async () => envelope('alice') };
  } });
  assert.deepEqual(result, envelope('alice'));
  assert.equal(received.url, '/api/features');
  assert.equal(received.options.credentials, 'same-origin');
  assert.equal(received.options.cache, 'no-store');
  assert.equal(received.options.signal, signal);
  await assert.rejects(featureRequest({ fetcher: async () => ({ ok: false }) }));
}

class Node {
  constructor(tag = '') { this.tag = tag; this.children = []; this.listeners = new Map(); this.hidden = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute() {}
  addEventListener(kind, handler) { this.listeners.set(kind, handler); }
  removeEventListener(kind) { this.listeners.delete(kind); }
  async fire(kind) { return this.listeners.get(kind)?.({ currentTarget: this }); }
}

// The rendered toggle starts hidden, exposes only verified eligibility, follows
// opt-out/signout immediately, and detaches its observer when unmounted.
{
  const device = setup();
  const input = new Node('input'), host = new Node('section');
  host.querySelector = () => input;
  const unmount = mountExperimentalMode(device.flags, host);
  assert.equal(host.hidden, true);
  assert.equal(input.disabled, true);
  await device.flags.accountChanged();
  assert.equal(host.hidden, false);
  assert.equal(input.checked, false);
  input.checked = true;
  await input.fire('change');
  assert.equal(device.flags.get().features.watch_tracking, true);
  device.set(none());
  await device.flags.accountChanged();
  assert.equal(host.hidden, true);
  assert.equal(input.checked, false);
  unmount();
  assert.equal(input.listeners.has('change'), false);
  device.flags.destroy();
}

// Exercise the actual account mount: logout and cross-tab owner changes revoke
// feature access before a delayed server response or UI paint can complete.
{
  const previous = { document: globalThis.document, window: globalThis.window,
    localStorage: globalThis.localStorage, fetch: globalThis.fetch };
  const doc = new EventTarget(), win = new EventTarget(), nodes = new Map();
  doc.visibilityState = 'visible';
  doc.createElement = tag => new Node(tag);
  doc.getElementById = id => {
    if (!nodes.has(id)) nodes.set(id, new Node());
    return nodes.get(id);
  };
  const storage = memory(), logout = deferred(), paint = deferred();
  let owner = 'alice', holdPaint = false, flags, accounts;
  const fresh = () => ({ version: 3, profile: [], saved: [], settings: { known_min: 85 }, onboarded: false });
  let state = fresh();
  Object.assign(globalThis, { document: doc, window: win, localStorage: storage,
    fetch: async url => {
      if (url.endsWith('/logout')) await logout.promise;
      return { ok: true, json: async () => url.endsWith('/logout') ? {}
        : { user: account(owner).user, csrf: account(owner).csrf, revision: 0, state: fresh() } };
    } });
  try {
    accounts = mountAccounts({ getState: () => state, fresh, sanitize: value => value,
      applyState: async value => { if (holdPaint) await paint.promise; state = value; },
      onContext: () => { void flags?.accountChanged(); } });
    flags = createFeatureFlags({ getAccount: () => accounts.context(), storage, win,
      request: async () => envelope(owner) });
    await accounts.ready();
    await flags.accountChanged();
    flags.setExperimental(true);
    assert.equal(flags.get().features.watch_tracking, true);
    const section = nodes.get('account-access').children[0];
    const signout = section.children.at(-1).children.find(node => node.textContent === 'Sign out');
    const signingOut = signout.fire('click');
    off(flags);
    assert.deepEqual(accounts.context(), none());
    logout.resolve();
    await signingOut;
    assert.deepEqual(accounts.context(), none());

    await accounts.refresh();
    await flags.accountChanged();
    assert.equal(flags.get().features.watch_tracking, true, 'same owner keeps its device preference');
    holdPaint = true; owner = 'bob';
    win.dispatchEvent(Object.assign(new Event('storage'), { key: ACTIVE_KEY,
      newValue: JSON.stringify(account('bob').user) }));
    off(flags);
    assert.deepEqual(accounts.context(), none());
    paint.resolve();
    await settle();
    await accounts.refresh();
    await flags.accountChanged();
    assert.equal(accounts.context().user.id, 'bob');
    assert.equal(flags.get().experimentalAllowed, true);
    assert.equal(flags.get().features.watch_tracking, false, 'new owner never inherits Alice’s opt-in');
  } finally {
    accounts?.destroy(); flags?.destroy();
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[key]; else globalThis[key] = value;
    }
  }
}

console.log('Experimental eligibility, session isolation, race rejection, device opt-in and account-transition revocation passed.');
