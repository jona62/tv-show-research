// Poll leadership contains no credentials or account state. The account's
// existing owner-scoped storage merge carries updates; the channel is a hint.
export function createPollLeadership({ storage, channel = name => typeof BroadcastChannel === 'function' ? new BroadcastChannel(name) : null,
  locks = globalThis.navigator?.locks, clock = Date.now, identity = globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2),
  changed = () => {} } = {}) {
  let owner = null, wire = null;
  const key = value => `couchside-account-poll-v1:${value}`;
  const read = () => {
    try {
      const held = JSON.parse(storage?.getItem(key(owner)) || 'null');
      return typeof held?.leader === 'string' && held.leader.length <= 128 &&
        Number.isFinite(held.expires) && held.expires - clock() <= 916000 ? held : null;
    } catch { return null; }
  };
  function select(value) {
    value = value == null ? null : String(value);
    if (value === owner) return;
    release(); owner = value;
    if (owner && storage) try {
      wire = channel(key(owner));
      if (wire) wire.onmessage = event => {
        const data = event.data;
        if (data?.type === 'checked' && data.owner === owner && Number.isFinite(data.at) &&
            Math.abs(clock() - data.at) < 600000) changed(data);
      };
    } catch { wire = null; }
  }
  function release() {
    if (owner) try { if (read()?.leader === identity) storage?.removeItem(key(owner)); } catch { /* next lease expires */ }
    wire?.close(); wire = null; owner = null;
  }
  const owns = () => !storage || !owner || read()?.leader === identity || !(read()?.expires > clock());
  async function run(value, interval, work) {
    select(value);
    if (!owner || !storage) { await work(); return true; }
    const selected = owner;
    const execute = async () => {
      const held = read(), now = clock();
      if (held?.expires > now && held.leader !== identity) return false;
      try {
        storage.setItem(key(owner), JSON.stringify({ leader: identity, expires: now + Math.max(15000, interval * 3 + 15000) }));
        if (read()?.leader !== identity) return false;
      } catch { await work(); return true; }
      const result = await work();
      if (owner === selected) try { wire?.postMessage({ type: 'checked', owner, at: clock(), ...(result?.verify ? { verify: true } : {}) }); } catch { /* storage events still work */ }
      return true;
    };
    if (locks?.request) return locks.request(key(owner), { ifAvailable: true }, lock => lock ? execute() : false);
    return execute();
  }
  return { select, owns, run, release };
}
