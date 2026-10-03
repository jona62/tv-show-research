import { icon, code } from './ratings.js?v=70517fd9f1cddac1';
import { showCard } from './public-data.js?v=52d95472a87de18c';
import { createTrackingState, airedEpisodes, watchedEpisode, watchedCount, isCaughtUp, watchedThrough } from './watch-tracking-state.js?v=2d55de94e424a726';

const labels = { watching: 'Watching', paused: 'Paused', completed: 'Finished', dropped: 'Dropped' };
const filters = [['all', 'All'], ['want', 'Want to watch'], ['watching', 'Watching'],
  ['caught', 'Caught up'], ['completed', 'Finished'], ['paused', 'Paused'], ['dropped', 'Dropped']];
let shows = [], filter = 'all', title = null, undo = null, store = null, hooks = null, enabled = false, owner = '', generation = 0;
const catalogues = new Map(), cards = new Map(), flights = new Map();
const catalogueQueue = [];
let catalogueActive = 0;
const visibleCards = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
  for (const entry of entries) if (entry.isIntersecting) {
    visibleCards.unobserve(entry.target);
    const show = shows.find(s => s.id === Number(entry.target.dataset.trackingCard));
    if (enabled && show && !show.catalogue) void hydrateEpisodes(show);
  }
}, { rootMargin: '600px' }) : null;
function catalogueTurn(task, priority) {
  const pending = new Promise((resolve, reject) => catalogueQueue[priority ? 'unshift' : 'push']({ task, resolve, reject }));
  drainCatalogues(); return pending;
}
function drainCatalogues() {
  while (catalogueActive < 2 && catalogueQueue.length) {
    const job = catalogueQueue.shift(); catalogueActive++;
    Promise.resolve().then(job.task).then(job.resolve, job.reject).finally(() => { catalogueActive--; drainCatalogues(); });
  }
}
const node = (tag, cls, text) => {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text) el.textContent = text;
  return el;
};
const action = (label, fn, cls = 'btn ghost') => {
  const b = node('button', cls, label); b.type = 'button'; b.onclick = fn; return b;
};
const available = airedEpisodes, watched = watchedEpisode, count = watchedCount, caught = isCaughtUp;
const next = s => s.progress_known === false ? null : available(s).find(e => !watched(s, e));
const stateLabel = s => !s.intent ? 'Want to watch' : s.intent === 'watching' && caught(s) ? 'Caught up' : labels[s.intent];
const match = s => filter === 'all' ? true : filter === 'want' ? !s.intent && s.saved :
  filter === 'caught' ? s.intent === 'watching' && caught(s) :
  filter === 'watching' ? s.intent === 'watching' && !caught(s) : s.intent === filter;
const through = watchedThrough;
const position = s => {
  if (s.progress_known === false) return 'Episode progress not set';
  if (!s.catalogue) return 'Loading episode details…';
  const e = through(s);
  if (!count(s)) return s.intent ? 'No episodes watched yet' : 'Ready when you are';
  return e ? `Watched through ${code(e)}` : `${count(s)} episodes watched`;
};

export function mountWatchTracking({ features, getAccount, getSaved, getShow, selectLibrary = values => values, onRefresh = () => {}, onExpired = () => {} }) {
  hooks = { getSaved, getShow, selectLibrary, onExpired };
  store = createTrackingState({ getAccount, changed: rebuild, denied: onExpired });
  const unsubscribe = features.subscribe(flags => {
    const id = flags.features?.watch_tracking ? flags.userId : '';
    if (id !== owner) { generation++; owner = id; catalogues.clear(); cards.clear(); flights.clear(); undo = null; filter = 'all'; }
    enabled = Boolean(id); store.activate(flags); rebuild(); onRefresh();
  });
  const refreshRemote = () => {
    if (!enabled || document.visibilityState === 'hidden') return;
    let changed = false;
    for (const [id, value] of catalogues) if (!value.fresh || value.expires_at * 1000 <= Date.now()) { catalogues.delete(id); changed = true; }
    if (changed) rebuild();
    void store.refresh();
  };
  window.addEventListener('focus', refreshRemote); window.addEventListener('online', refreshRemote);
  document.addEventListener('visibilitychange', refreshRemote);
  const timer = setInterval(refreshRemote, 60000);
  return { refresh: rebuild, enabled: () => enabled, destroy() {
    clearInterval(timer); window.removeEventListener('focus', refreshRemote); window.removeEventListener('online', refreshRemote);
    document.removeEventListener('visibilitychange', refreshRemote); unsubscribe();
    enabled = false; generation++; visibleCards?.disconnect(); refresh(); store.destroy();
  } };
}
function rebuild() {
  if (!store || !hooks) return;
  const state = store.get(), saved = hooks.getSaved(), active = state.records.filter(s => !s.deleted);
  const ids = new Set([...saved.map(s => s.id), ...active.map(s => s.show_id), ...(title?.episodes?.isConnected ? [title.id] : [])]);
  shows = [...ids].map(id => {
    const record = active.find(s => s.show_id === id), catalogue = catalogues.get(id);
    return { ...hooks.getShow(id), ...cards.get(id), id, name: cards.get(id)?.name || hooks.getShow(id)?.name || `Show ${id}`,
      saved: saved.some(s => s.id === id), intent: record?.intent || null, progress_known: record?.progress_known !== false,
      watched: (record?.episode_states || []).filter(e => e.watched).map(e => e.episode_id),
      episodes: catalogue?.episodes || [], catalogue, ended: catalogue?.ended === true };
  });
  refresh();
}
async function change(s, actionName, fields, message) {
  const version = generation;
  try {
    const result = await store.mutate(s.id, actionName, fields);
    if (version !== generation || !enabled) return false;
    undo = result.undo ? () => change(s, 'undo', { target_operation_id: result.undo.operation_id }, 'Change undone.') : null;
    notify(typeof message === 'function' ? message(result) : message, Boolean(undo)); return true;
  } catch (failure) {
    if (version !== generation || !enabled) return false;
    if (failure.data?.catalogue_changed) {
      const catalogue = failure.data.catalogue;
      if (catalogue?.show_id === s.id) catalogues.set(s.id, catalogue); else catalogues.delete(s.id);
      const dialog = document.getElementById('tracking-edit'); if (dialog?.open) dialog.close();
      rebuild();
    }
    if (failure.status === 401 || failure.status === 403) hooks.onExpired();
    notify(failure.message); return false;
  }
}
function notify(message, reversible = false) {
  if (!enabled) return;
  let toast = document.getElementById('tracking-toast');
  if (!toast) { toast = node('div', 'tracking-toast'); toast.id = 'tracking-toast'; toast.setAttribute('role', 'status'); document.body.append(toast); }
  const host = document.querySelector('#tracking-edit[open]') || document.querySelector('#title[open]') || document.body;
  if (toast.parentElement !== host) host.append(toast);
  toast.replaceChildren(node('span', '', message));
  if (reversible) toast.append(action('Undo', () => { const fn = undo; undo = null; fn?.(); }, 'tracking-undo'));
  toast.hidden = false;
  clearTimeout(notify.timer); notify.timer = setTimeout(() => { toast.hidden = true; }, 9000);
}
function mark(s, e) {
  if (s.progress_known === false) { edit(s); return; }
  const on = watched(s, e);
  void change(s, 'episode', { episode_id: e.id, watched: !on, establish_progress: true }, `${code(e)} ${on ? 'marked unwatched' : 'marked watched'}.`);
}
function progressBar(s) {
  const all = available(s).length;
  const b = node('div', 'tracking-bar');
  b.setAttribute('role', 'progressbar'); b.setAttribute('aria-label', `${s.name}: episodes watched`);
  b.setAttribute('aria-valuenow', count(s)); b.setAttribute('aria-valuemax', all || 1); b.setAttribute('aria-valuemin', 0);
  const fill = node('span'); fill.style.width = `${all ? count(s) / all * 100 : 0}%`; b.append(fill); return b;
}
function statusTag(s) {
  return node('span', `tracking-status tracking-${s.intent === 'watching' && caught(s) ? 'caught' : s.intent || 'want'}`, stateLabel(s));
}
function openLink(s) {
  const a = node('a', 'tracking-name', s.name); a.href = `${location.pathname}?show=${s.id}`; a.dataset.link = ''; return a;
}

async function hydrateEpisodes(s) {
  if (!enabled || flights.has(s.id)) return;
  const version = generation;
  const pending = catalogueTurn(async () => {
    if (version !== generation || !enabled) return;
    try {
      const [catalogue, card] = await Promise.all([store.catalogue(s.id), cards.has(s.id) ? cards.get(s.id) : showCard(s.id).catch(() => null)]);
      if (version !== generation || !enabled) return;
      catalogues.set(s.id, catalogue); if (card) cards.set(s.id, card); rebuild();
    } catch (failure) { if (version === generation) notify(failure.message); }
    finally { if (version === generation) flights.delete(s.id); }
  }, s.id === title?.id);
  flights.set(s.id, pending); await pending;
}
function trackingCard(s, compact = false) {
  const card = node('article', `tracking-card${compact ? ' tracking-card-compact' : ''}`);
  const posterLink = node('a', 'tracking-poster'); posterLink.href = `${location.pathname}?show=${s.id}`; posterLink.dataset.link = '';
  posterLink.setAttribute('aria-label', `Open ${s.name}`);
  const image = node('img'); image.src = s.poster || ''; image.alt = ''; image.loading = 'lazy'; posterLink.append(image);
  const body = node('div', 'tracking-card-body');
  const top = node('div', 'tracking-card-top'); top.append(statusTag(s));
  if (s.saved) top.append(node('span', 'tracking-saved', 'In My List'));
  body.append(top, openLink(s), node('p', 'tracking-position', position(s)));
  const e = next(s);
  const note = !s.intent ? 'Choose a status when you start.' : s.intent === 'completed' ? 'You’ve finished this show.' :
    caught(s) ? 'All aired episodes watched.' : e ? `Up next: ${code(e)}` : 'Waiting for episode details.';
  body.append(node('p', 'tracking-next', note));
  if (s.intent && s.catalogue && s.progress_known !== false) {
    body.append(progressBar(s), node('p', 'tracking-count', `${count(s)} / ${available(s).length} aired episodes watched`));
  }
  const buttons = node('div', 'tracking-card-actions');
  if (s.intent === 'watching' && e) buttons.append(action(`Mark ${code(e)} watched`, () => mark(s, e), 'btn tracking-primary'));
  if (!s.intent) buttons.append(action('Start watching', () => {
    void change(s, 'intent', { intent: 'watching', progress_known: true }, 'Started watching.');
  }));
  if (s.intent === 'paused' || s.intent === 'dropped') buttons.append(action('Continue tracking', () => change(s, 'intent', { intent: 'watching' }, 'Moved to Watching.')));
  const editor = action('Edit progress', () => edit(s), 'tracking-text-button'); editor.dataset.trackingEdit = '';
  buttons.append(editor);
  body.append(buttons); card.append(posterLink, body);
  for (const b of card.querySelectorAll('button')) b.disabled =
    store.get().busy || !store.get().loaded || b.hasAttribute('data-tracking-edit') && !s.catalogue;
  if (!s.catalogue) {
    card.dataset.trackingCard = s.id;
    if (visibleCards) visibleCards.observe(card); else void hydrateEpisodes(s);
  }
  return card;
}

export function renderTrackingList() {
  const list = document.getElementById('list'); if (!list || !enabled) return;
  let panel = document.getElementById('tracking-list');
  if (!panel) {
    panel = node('section', 'tracking-library'); panel.id = 'tracking-list'; panel.setAttribute('aria-label', 'Your watching progress');
    document.getElementById('list-note').before(panel);
    const intro = node('div', 'tracking-intro'); intro.append(node('p', '', 'Your shows, right where you left them.'));
    const tools = node('div', 'tracking-list-tools');
    const chips = node('div', 'tracking-filters'); chips.setAttribute('role', 'group'); chips.setAttribute('aria-label', 'Watching status');
    for (const [key, label] of filters) {
      const b = action(label, () => { filter = key; drawList(); }, 'chip'); b.dataset.trackingFilter = key; chips.append(b);
    }
    tools.append(chips);
    const grid = node('div', 'tracking-grid'); grid.id = 'tracking-grid'; panel.append(intro, tools, grid);
  }
  document.getElementById('list-note').classList.add('tracking-native-saved');
  document.getElementById('list-grid').classList.add('tracking-native-saved');
  drawList();
}
function drawList() {
  const grid = document.getElementById('tracking-grid'); if (!grid) return;
  visibleCards?.disconnect();
  for (const b of document.querySelectorAll('[data-tracking-filter]')) b.setAttribute('aria-pressed', String(b.dataset.trackingFilter === filter));
  const picked = hooks.selectLibrary(shows.filter(s => (s.intent || s.saved) && match(s)));
  grid.replaceChildren(...picked.map(s => trackingCard(s)));
  const status = store.get();
  if (status.error) grid.prepend(node('p', 'tracking-empty', status.error), action('Retry loading progress', () => store.refresh()));
  if (!picked.length) grid.append(node('p', 'tracking-empty', !status.loaded ? 'Loading your viewing progress…' : 'No shows match this view. Start tracking from a show’s details.'));
}

export function mountTrackingTitle(t) {
  title = t; if (enabled) { ensureTitlePanel(t); rebuild(); }
}
function ensureTitlePanel(t) {
  if (t.trackingPanel?.isConnected) return;
  const panel = node('section', 't-section tracking-detail'); panel.setAttribute('aria-label', 'Your progress');
  t.episodes.before(panel); t.trackingPanel = panel;
}
function drawTitle(t) {
  const s = shows.find(s => s.id === t.id), panel = t.trackingPanel;
  if (!s) return;
  if (!s.catalogue) void hydrateEpisodes(s);
  if (!s.intent) {
    panel.replaceChildren(node('h3', '', 'Your progress'), node('p', 'tracking-position', 'Track this show when you start watching.'));
    const start = action('Start watching', () => change(s, 'intent', { intent: 'watching', progress_known: true }, 'Started watching.'));
    start.disabled = store.get().busy || !store.get().loaded; panel.append(start);
    if (store.get().error) panel.append(node('p', 'tracking-position', store.get().error), action('Retry', () => store.refresh()));
    return;
  }
  const header = node('div', 'tracking-detail-head'); header.append(node('h3', '', 'Your progress'));
  const main = node('div', 'tracking-detail-main');
  const status = node('label', 'tracking-status-select', 'Status');
  const select = node('select'); select.setAttribute('aria-label', 'Watching status'); select.id = 'tracking-status';
  for (const [value, label] of [...(!s.intent ? [['', 'Want to watch']] : []), ...Object.entries(labels)]) {
    const option = node('option', '', label); option.value = value; select.append(option);
  }
  select.value = s.intent || '';
  select.onchange = () => change(s, 'intent', { intent: select.value,
    ...(select.value === 'completed' && !caught(s) ? { progress_known: false } : {}) }, `Status changed to ${select.selectedOptions[0].textContent}.`);
  select.disabled = store.get().busy || !store.get().loaded;
  status.append(select);
  const numbers = node('div', 'tracking-detail-numbers'); numbers.append(statusTag(s), node('strong', '', position(s)));
  if (s.catalogue && s.progress_known !== false) numbers.append(node('span', '', `${count(s)} of ${available(s).length} aired episodes watched`), progressBar(s));
  main.append(status, numbers);
  const e = next(s), up = node('div', 'tracking-up-next');
  const words = node('div'); words.append(node('span', 'tracking-eyebrow', e ? 'UP NEXT' : 'YOUR PROGRESS'));
  words.append(node('strong', '', e ? `${code(e)}${e.name ? ' · ' + e.name : ''}` : s.progress_known === false ? 'Set episode progress when you remember' : caught(s) ? 'All aired episodes watched' : 'Episode details unavailable'));
  if (e?.runtime) words.append(node('span', 'tracking-up-runtime', `${e.runtime} min`));
  up.append(words);
  if (e && s.intent !== 'completed') up.append(action('Mark watched', () => mark(s, e), 'btn tracking-primary'));
  const editor = action('Change progress', () => edit(s), 'tracking-text-button'); editor.dataset.trackingEdit = '';
  const footer = node('div', 'tracking-detail-actions'); footer.append(editor,
    action('Remove tracking', () => change(s, 'remove', {}, 'Viewing progress removed. Ratings and My List kept.'), 'tracking-text-button'),
    node('span', '', 'Regular episodes · ratings stay separate'));
  panel.replaceChildren(header, main, up, footer);
  for (const b of panel.querySelectorAll('button')) b.disabled = store.get().busy || !store.get().loaded || b.hasAttribute('data-tracking-edit') && !s.catalogue;
}

export function mountEpisodeProgress(li, ep, season) {
  li.dataset.trackingShow = season.show; li.dataset.trackingEpisode = ep.id;
  if (enabled) paintEpisode(li);
}
function paintEpisode(li) {
  const s = shows.find(s => s.id === Number(li.dataset.trackingShow));
  const ep = s?.episodes.find(e => e.id === Number(li.dataset.trackingEpisode));
  if (!s?.intent || !ep || ep.released !== true) return;
  li.classList.add('tracking-episode');
  if (!li.querySelector('[data-tracking-check]')) {
    const b = action('', () => { const current = shows.find(v => v.id === s.id); if (current) mark(current, ep); }, 'tracking-episode-check');
    b.dataset.trackingCheck = ''; li.append(b);
  }
  updateEpisode(li, s, ep);
}
function updateEpisode(li, s, e) {
  const b = li.querySelector('[data-tracking-check]'); if (!b) return;
  b.disabled = store.get().busy || !store.get().loaded;
  const on = watched(s, e); b.innerHTML = on ? icon('check') : ''; b.setAttribute('aria-pressed', String(on));
  b.setAttribute('aria-label', `${on ? 'Mark unwatched' : 'Mark watched'}: ${code(e)}`);
  li.classList.toggle('tracking-episode-watched', on);
  // Hide spoilers for unwatched tracked episodes.
  li.classList.toggle('tracking-episode-unwatched', !on);
}

function edit(s) {
  if (!s.catalogue?.fresh || !s.catalogue.complete) { notify('Episode details need refreshing before you can set exact progress.'); catalogues.delete(s.id); void hydrateEpisodes(s); return; }
  let dialog = document.getElementById('tracking-edit');
  if (!dialog) {
    dialog = node('dialog', 'tracking-edit'); dialog.id = 'tracking-edit'; document.body.append(dialog);
    dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
  }
  dialog.setAttribute('aria-labelledby', 'tracking-edit-heading');
  const head = node('div', 'tracking-edit-head'); const h = node('h2', '', 'Change progress'); h.id = 'tracking-edit-heading';
  const close = action('', () => dialog.close(), 'icon-btn'); close.innerHTML = icon('close'); close.setAttribute('aria-label', 'Close progress editor'); head.append(h, close);
  const detail = node('p', 'tracking-edit-show', s.name);
  const form = node('form'); form.method = 'dialog';
  const label = node('label', 'tracking-edit-field', 'I’ve watched through');
  const select = node('select'); select.id = 'tracking-through';
  const zero = node('option', '', 'No episodes yet'); zero.value = ''; select.append(zero);
  for (const e of available(s)) { const o = node('option', '', `${code(e)}${e.name ? ' · ' + e.name : ''}`); o.value = e.id; select.append(o); }
  select.value = through(s)?.id || ''; label.append(select);
  const hint = node('p', 'tracking-edit-hint', 'This sets earlier regular episodes to watched and later episodes to unwatched.');
  const total = node('p', 'tracking-edit-total');
  const update = () => { const i = available(s).findIndex(e => e.id === Number(select.value)); total.textContent = `${i + 1} episodes watched · you can undo this change`; };
  select.onchange = update; update();
  const buttons = node('div', 'tracking-edit-buttons');
  buttons.append(action('Cancel', () => dialog.close()));
  const save = action('Save progress', async () => {
    save.disabled = true; finish.disabled = true;
    const ok = await change(s, 'replace', { through_episode_id: Number(select.value) || null, catalogue_revision: s.catalogue.catalogue_revision }, 'Episode progress updated.');
    if (ok && dialog.open) dialog.close(); else { save.disabled = false; finish.disabled = false; }
  }, 'btn tracking-primary'); buttons.append(save);
  const finish = action('Mark all aired episodes watched', async () => {
    save.disabled = true; finish.disabled = true;
    const ok = await change(s, 'all', { catalogue_revision: s.catalogue.catalogue_revision }, result => {
      const record = result.tracking.find(v => v.show_id === s.id);
      return record?.intent === 'completed' ? 'Marked Finished.' : s.episodes.every(e => typeof e.released === 'boolean')
        ? 'You’re caught up.' : 'Marked all known aired episodes watched.';
    });
    if (ok && dialog.open) dialog.close(); else { save.disabled = false; finish.disabled = false; }
  }, 'tracking-text-button tracking-mark-all');
  finish.disabled = !available(s).length;
  form.append(label, hint, total, buttons, finish); dialog.replaceChildren(head, detail, form); dialog.showModal();
}

function drawHome() {
  const rows = document.getElementById('rows'); if (!rows) return;
  let shelf = document.getElementById('tracking-continue');
  if (!shelf) { shelf = node('section', 'tracking-continue'); shelf.id = 'tracking-continue'; rows.before(shelf); }
  const head = node('div', 'tracking-home-head'); head.append(node('h2', '', 'Continue watching'));
  const link = node('a', 'tracking-text-button', 'View your progress'); link.href = '/list'; link.dataset.link = ''; head.append(link);
  const rail = node('div', 'tracking-continue-rail');
  rail.append(...shows.filter(s => s.intent === 'watching' && !caught(s)).map(s => trackingCard(s, true)));
  shelf.hidden = !rail.children.length; shelf.replaceChildren(head, rail);
}
function refresh() {
  if (!enabled) {
    visibleCards?.disconnect();
    for (const id of ['tracking-list', 'tracking-continue', 'tracking-toast']) document.getElementById(id)?.remove();
    const dialog = document.getElementById('tracking-edit'); if (dialog?.open) dialog.close(); dialog?.remove();
    title?.trackingPanel?.remove();
    for (const id of ['list-note', 'list-grid']) document.getElementById(id)?.classList.remove('tracking-native-saved');
    for (const li of document.querySelectorAll('[data-tracking-episode]')) {
      li.querySelector('[data-tracking-check]')?.remove();
      li.classList.remove('tracking-episode', 'tracking-episode-watched', 'tracking-episode-unwatched');
    }
    return;
  }
  renderTrackingList(); drawHome();
  if (title?.episodes.isConnected) { ensureTitlePanel(title); drawTitle(title); }
  for (const li of document.querySelectorAll('[data-tracking-episode]')) paintEpisode(li);
}
