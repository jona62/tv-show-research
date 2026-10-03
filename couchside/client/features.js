// Eligibility comes from the authenticated server session. The device preference
// only opts that owner into features the server has explicitly allowed.
export const experimentalKey = id => `couchside-experimental-v1:${id}`;

const closed = userId => Object.freeze({ userId, experimentalAllowed: false,
  experimentalEnabled: false, features: Object.freeze({ watch_tracking: false }) });

function authenticated(getAccount) {
  const context = getAccount();
  return typeof context?.user?.id === 'string' && context.user.id.length > 0
    && typeof context.csrf === 'string' && context.csrf.length > 0
    ? { id: context.user.id, csrf: context.csrf } : null;
}

export async function featureRequest({ signal, fetcher = globalThis.fetch } = {}) {
  const response = await fetcher('/api/features', { credentials: 'same-origin', cache: 'no-store',
    headers: { Accept: 'application/json' }, signal });
  if (!response.ok) throw new Error('Experimental features are unavailable.');
  return response.json();
}

export function createFeatureFlags({ getAccount, request = featureRequest, storage,
  win = globalThis.window, timeout = 12000 } = {}) {
  try { storage = storage === undefined ? globalThis.localStorage : storage; } catch { storage = null; }
  let owner = null, csrf = null, generation = 0, flight = null, abort = null, stopped = false;
  let snapshot = closed(null), allowed = false, available = false, enabled = false;
  const listeners = new Set();
  const current = () => {
    const account = authenticated(getAccount);
    return !stopped && account?.id === owner && account?.csrf === csrf;
  };
  const get = () => current() ? snapshot : closed(null);
  const preference = () => {
    try { return storage?.getItem(experimentalKey(owner)) === '1'; } catch { return false; }
  };
  function publish() {
    snapshot = allowed ? Object.freeze({ userId: owner, experimentalAllowed: true,
      experimentalEnabled: enabled, features: Object.freeze({ watch_tracking: enabled && available }) })
      : closed(owner);
    for (const listener of listeners) listener(get());
  }
  function invalidate(account) {
    ++generation;
    abort?.abort();
    abort = null; flight = null;
    owner = account?.id || null; csrf = account?.csrf || null;
    allowed = false; available = false; enabled = false;
    publish();
  }
  function refresh() {
    const account = authenticated(getAccount);
    if (stopped) return Promise.resolve(get());
    if (account?.id !== owner || account?.csrf !== csrf) invalidate(account);
    if (!account) return Promise.resolve(get());
    if (flight) return flight;
    // A failed refresh closes the feature even if a previous check allowed it.
    allowed = false; available = false; enabled = false;
    publish();
    const version = ++generation, id = owner, token = csrf;
    const controller = new AbortController();
    abort = controller;
    const timer = setTimeout(() => controller.abort(), timeout);
    flight = Promise.resolve().then(() => request({ signal: controller.signal })).then(data => {
      if (version !== generation || controller.signal.aborted || !current() || owner !== id || csrf !== token) return;
      if (data?.user_id !== id || typeof data.experimental_allowed !== 'boolean'
        || typeof data.features?.watch_tracking !== 'boolean'
        || !data.experimental_allowed && data.features.watch_tracking) return;
      allowed = data.experimental_allowed;
      available = data.features.watch_tracking;
      enabled = allowed && preference();
    }).catch(() => {
      // Network, session, parsing and abort errors all leave eligibility closed.
    }).finally(() => {
      clearTimeout(timer);
      if (version === generation) { flight = null; abort = null; publish(); }
    }).then(get);
    return flight;
  }
  function accountChanged() {
    const account = authenticated(getAccount);
    if (account?.id === owner && account?.csrf === csrf) return flight || Promise.resolve(get());
    invalidate(account);
    return account ? refresh() : Promise.resolve(get());
  }
  function setExperimental(value) {
    if (!current() || !allowed || typeof value !== 'boolean') return false;
    enabled = value;
    try { storage?.setItem(experimentalKey(owner), value ? '1' : '0'); } catch { /* The session can still opt in. */ }
    publish();
    return true;
  }
  function storageChanged(event) {
    if (!current() || !allowed || event.key !== experimentalKey(owner)) return;
    enabled = preference();
    publish();
  }
  win?.addEventListener('storage', storageChanged);
  return {
    get, refresh, accountChanged, setExperimental,
    subscribe(listener) { listeners.add(listener); listener(get()); return () => listeners.delete(listener); },
    destroy() {
      stopped = true;
      invalidate(null);
      listeners.clear();
      win?.removeEventListener('storage', storageChanged);
    },
  };
}

export function mountExperimentalMode(flags, host) {
  if (!host) return () => {};
  const input = host.querySelector('[data-experimental-toggle]');
  const render = state => {
    host.hidden = !state.experimentalAllowed;
    input.disabled = !state.experimentalAllowed;
    input.checked = state.experimentalEnabled;
  };
  const change = () => { flags.setExperimental(input.checked); render(flags.get()); };
  const unsubscribe = flags.subscribe(render);
  input.addEventListener('change', change);
  return () => { unsubscribe(); input.removeEventListener('change', change); };
}
