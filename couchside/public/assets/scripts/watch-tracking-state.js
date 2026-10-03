// Private viewing history lives on the account server, never in the public cache.
export class TrackingError extends Error {
  constructor(message, status = 0, data = {}) { super(message); this.status = status; this.data = data; }
}

export async function trackingRequest(path, body, { csrf, fetcher = globalThis.fetch, timeout = 15000 } = {}) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeout);
  try {
    const response = await fetcher(`/api/tracking${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', signal: abort.signal,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json', 'X-Account-Request': '1', 'X-CSRF-Token': csrf || '' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    let data;
    try { data = await response.json(); } catch { throw new TrackingError('Viewing progress returned an unreadable response.', response.status); }
    if (!response.ok) throw new TrackingError(data.error || 'Could not save viewing progress.', response.status, data);
    return data;
  } catch (error) {
    if (error instanceof TrackingError) throw error;
    throw new TrackingError('Could not reach Couchside. Check your connection and try again.');
  } finally { clearTimeout(timer); }
}

export const airedEpisodes = show => (show.episodes || []).filter(e => e.released === true);
export const watchedEpisode = (show, episode) => show.watched.includes(episode.id);
export const watchedCount = show => airedEpisodes(show).filter(e => watchedEpisode(show, e)).length;
export const isCaughtUp = show => show.progress_known !== false && show.catalogue?.fresh === true
  && (!Number.isFinite(show.catalogue.expires_at) || show.catalogue.expires_at * 1000 > Date.now())
  && show.catalogue?.complete === true && show.episodes.every(e => typeof e.released === 'boolean')
  && airedEpisodes(show).length > 0 && watchedCount(show) === airedEpisodes(show).length;
export function watchedThrough(show) {
  let last = null;
  for (const episode of airedEpisodes(show)) { if (!watchedEpisode(show, episode)) break; last = episode; }
  return last;
}

function snapshot(data, owner) {
  if (data?.user_id !== owner || !Number.isSafeInteger(data.tracking_revision) || data.tracking_revision < 0
      || !Array.isArray(data.tracking)) throw new TrackingError('Viewing progress belongs to a different session. Refresh and try again.');
  return { revision: data.tracking_revision, records: data.tracking };
}

export function createTrackingState({ getAccount, request = trackingRequest, changed = () => {}, denied = () => {},
  operationId = () => crypto.randomUUID() } = {}) {
  let owner = '', enabled = false, epoch = 0, records = [], revision = 0, loaded = false, busy = false, error = '', flight = null;
  const get = () => ({ owner, enabled, records, revision, loaded, busy, error });
  const publish = () => changed(get());
  const current = (id, version) => enabled && owner === id && epoch === version && getAccount()?.user?.id === id;
  function accept(data, id) {
    const value = snapshot(data, id);
    if (value.revision < revision) return false;
    const updated = !loaded || error !== '' || value.revision !== revision || JSON.stringify(records) !== JSON.stringify(value.records);
    records = value.records; revision = value.revision; loaded = true; error = '';
    return updated;
  }
  async function refresh() {
    if (!enabled || busy || flight) return flight;
    const id = owner, version = epoch;
    flight = (async () => {
      let updated = false;
      try {
        const data = await request('');
        if (current(id, version)) updated = accept(data, id);
      } catch (failure) {
        if (current(id, version)) {
          updated = error !== failure.message; error = failure.message;
          if (failure.status === 401 || failure.status === 403) denied();
        }
      } finally { if (current(id, version)) { flight = null; if (updated) publish(); } }
    })();
    return flight;
  }
  function activate(flags) {
    const id = flags.features?.watch_tracking ? flags.userId : '';
    if (id === owner && enabled === Boolean(id)) return;
    ++epoch; owner = id || ''; enabled = Boolean(id); records = []; revision = 0; loaded = false; busy = false; error = ''; flight = null;
    publish();
    if (enabled) void refresh();
  }
  async function mutate(showId, action, fields = {}) {
    if (!enabled || !loaded || busy) throw new TrackingError('Wait for your viewing progress to finish loading.');
    const id = owner, version = epoch, context = getAccount();
    if (context?.user?.id !== id || !context.csrf) throw new TrackingError('Sign in again to save viewing progress.');
    busy = true; error = ''; publish();
    const body = { ...fields, operation_id: operationId(), base_revision: revision, show_id: showId, action };
    try {
      let data;
      // Reusing the operation ID makes an ambiguous connection failure safe to retry.
      try { data = await request('', body, { csrf: context.csrf }); }
      catch (failure) {
        if (failure.status !== 0 || !current(id, version)) throw failure;
        data = await request('', body, { csrf: context.csrf });
      }
      if (!current(id, version)) throw new TrackingError('Your account changed before this save finished.');
      if (data.operation_id !== body.operation_id || !Number.isSafeInteger(data.operation_revision)
          || data.operation_revision < 0 || data.operation_revision > data.tracking_revision || data.tracking_revision < revision)
        throw new TrackingError('The viewing-progress save could not be verified. Refresh and try again.');
      accept(data, id); return data;
    } catch (failure) {
      if (current(id, version)) {
        if (failure.status === 409 && failure.data?.tracking) accept(failure.data, id);
        error = failure.message;
      }
      throw failure;
    } finally { if (current(id, version)) { busy = false; publish(); } }
  }
  return { get, activate, refresh, mutate,
    async catalogue(showId) {
      const id = owner, version = epoch;
      const data = await request(`/catalogue?id=${showId}`);
      if (!current(id, version) || data.user_id !== id || data.show_id !== showId || !Array.isArray(data.episodes))
        throw new TrackingError('Your account changed while episode details loaded.');
      return data;
    },
    destroy() { ++epoch; enabled = false; owner = ''; records = []; revision = 0; loaded = false; busy = false; error = ''; flight = null; },
  };
}
