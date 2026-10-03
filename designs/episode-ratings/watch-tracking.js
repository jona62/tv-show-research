import { esc, icon, code } from '/assets/scripts/ratings.js';

// Design-only state: invented personal history on this preview origin.
// Never write the production account state or interpret a rating as watching.
const KEY = 'couchside.watch-tracking-preview.v1';
const labels = { watching: 'Watching', paused: 'Paused', completed: 'Finished', dropped: 'Dropped' };
const filters = [['all', 'All'], ['want', 'Want to watch'], ['watching', 'Watching'],
  ['caught', 'Caught up'], ['completed', 'Finished'], ['paused', 'Paused'], ['dropped', 'Dropped']];
let shows = [], initial = [], filter = 'all', query = '', title = null, undo = null;
const loadingEpisodes = new Set();
const node = (tag, cls, text) => {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text) el.textContent = text;
  return el;
};
const action = (label, fn, cls = 'btn ghost') => {
  const b = node('button', cls, label); b.type = 'button'; b.onclick = fn; return b;
};
const available = s => s.episodes.filter(e => e.airdate && e.airdate < '2026-10-04');
const watched = (s, e) => s.watched.includes(e.id);
const next = s => s.progress_known === false ? null : available(s).find(e => !watched(s, e));
const count = s => available(s).filter(e => watched(s, e)).length;
const caught = s => s.progress_known !== false && available(s).length > 0 && count(s) === available(s).length;
const stateLabel = s => !s.intent ? 'Want to watch' : s.intent === 'watching' && caught(s) ? 'Caught up' : labels[s.intent];
const match = s => filter === 'all' ? true : filter === 'want' ? !s.intent && s.saved_demo :
  filter === 'caught' ? s.intent === 'watching' && caught(s) :
  filter === 'watching' ? s.intent === 'watching' && !caught(s) : s.intent === filter;
const through = s => {
  let last = null;
  for (const e of available(s)) { if (!watched(s, e)) break; last = e; }
  return last;
};
const position = s => {
  if (s.progress_known === false) return 'Episode progress not set';
  const e = through(s);
  if (!count(s)) return s.intent ? 'Episode progress not set' : 'Ready when you are';
  return e ? `Watched through ${code(e)}` : `${count(s)} episodes watched`;
};

const ready = fetch('/api/tracking-preview').then(r => {
  if (!r.ok) throw Error('Preview unavailable'); return r.json();
}).then(data => {
  shows = data.shows;
  initial = structuredClone(shows);
  try {
    const stored = JSON.parse(sessionStorage.getItem(KEY));
    for (const s of shows) {
      const own = stored?.find(v => v.id === s.id);
      if (own) {
        s.intent = own.intent in labels ? own.intent : null;
        s.saved_demo = own.saved_demo === true;
        s.progress_known = own.progress_known !== false;
        s.watched = Array.isArray(own.watched) ? own.watched.filter(id => s.episodes.some(e => e.id === id)) : s.watched;
      }
    }
    for (const own of Array.isArray(stored) ? stored : []) {
      if (!shows.some(s => s.id === own.id) && own.extra?.id === own.id && Array.isArray(own.extra.episodes)) shows.push(own.extra);
    }
  } catch {}
  refresh();
}).catch(error => {
  const list = document.getElementById('tracking-list');
  if (list) list.textContent = error.message;
});

function persist() {
  try { sessionStorage.setItem(KEY, JSON.stringify(shows.map(s => ({ id: s.id, intent: s.intent,
    watched: s.watched, saved_demo: s.saved_demo, progress_known: s.progress_known, ...(!initial.some(i => i.id === s.id) ? { extra: s } : {}) })))); } catch {}
}
function change(s, fn, message) {
  const before = structuredClone(s);
  fn(); persist(); refresh();
  undo = () => { Object.assign(s, before); persist(); refresh(); notify('Change undone.'); };
  notify(message, true);
}
function notify(message, reversible = false) {
  let toast = document.getElementById('tracking-toast');
  if (!toast) { toast = node('div', 'tracking-toast'); toast.id = 'tracking-toast'; toast.setAttribute('role', 'status'); document.body.append(toast); }
  const host = document.querySelector('#title[open]') || document.body;
  if (toast.parentElement !== host) host.append(toast);
  toast.replaceChildren(node('span', '', message));
  if (reversible) toast.append(action('Undo', () => { const fn = undo; undo = null; fn?.(); }, 'tracking-undo'));
  toast.hidden = false;
  clearTimeout(notify.timer); notify.timer = setTimeout(() => { toast.hidden = true; }, 9000);
}
function mark(s, e) {
  if (s.progress_known === false) { edit(s); return; }
  change(s, () => {
    const on = watched(s, e);
    s.watched = on ? s.watched.filter(id => id !== e.id) : [...s.watched, e.id];
    if (!on && !s.intent) s.intent = 'watching';
  }, `${code(e)} ${watched(s, e) ? 'marked unwatched' : 'marked watched'}.`);
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

function ensureShow(c) {
  let s = shows.find(s => s.id === c.id);
  if (!s) { s = { ...c, episodes: [], watched: [], intent: null, saved_demo: false }; shows.push(s); }
  return s;
}
async function hydrateEpisodes(s, t = null) {
  if (s.episodes.length || loadingEpisodes.has(s.id)) return;
  loadingEpisodes.add(s.id);
  try {
    const response = await fetch(`/api/episode-ratings?id=${s.id}`);
    if (!response.ok) throw Error('Episode details are unavailable. Try again shortly.');
    const data = await response.json();
    s.episodes = (data.episodes || []).filter(e => e.id && e.season && e.number);
    s.ended_demo = (t?.live?.status || t?.card?.status || s.status) === 'Ended';
    persist(); refresh();
  } catch (error) { notify(error.message); }
  finally { loadingEpisodes.delete(s.id); }
}

export function trackingListButton(c, kind, nativeIcon, getShow = () => c) {
  const cls = kind === 'btn' ? 'btn' : kind === 'wide' ? 'btn primary' : kind === 'tiny' ? 'round tiny' : 'round small';
  const b = action('', () => {
    const s = ensureShow(getShow());
    change(s, () => { s.saved_demo = !s.saved_demo; }, s.saved_demo ? `Removed ${s.name} from My List. Progress kept.` : `Added ${s.name} to My List.`);
  }, cls);
  b.dataset.trackingSave = c.id;
  b.paintTrackingBookmark = () => {
    const on = shows.find(s => s.id === c.id)?.saved_demo === true;
    b.replaceChildren(nativeIcon(on ? 'check' : 'plus'));
    if (b.classList.contains('round')) b.setAttribute('aria-label', `My List: ${getShow().name || 'show'}`);
    else b.append(document.createTextNode('My List'));
    b.setAttribute('aria-pressed', String(on));
  };
  b.paintTrackingBookmark(); ready.then(() => b.paintTrackingBookmark()); return b;
}
function trackingCard(s, compact = false) {
  const card = node('article', `tracking-card${compact ? ' tracking-card-compact' : ''}`);
  const posterLink = node('a', 'tracking-poster'); posterLink.href = `${location.pathname}?show=${s.id}`; posterLink.dataset.link = '';
  posterLink.setAttribute('aria-label', `Open ${s.name}`);
  const image = node('img'); image.src = s.poster || ''; image.alt = ''; image.loading = 'lazy'; posterLink.append(image);
  const body = node('div', 'tracking-card-body');
  const top = node('div', 'tracking-card-top'); top.append(statusTag(s));
  if (s.saved_demo) top.append(node('span', 'tracking-saved', 'In My List'));
  body.append(top, openLink(s), node('p', 'tracking-position', position(s)));
  const e = next(s);
  const note = !s.intent ? 'Choose a status when you start.' : s.intent === 'completed' ? 'You’ve finished this show.' :
    caught(s) ? 'All aired episodes watched.' : e ? `Up next: ${code(e)}` : 'Waiting for episode details.';
  body.append(node('p', 'tracking-next', note));
  if (s.intent && s.progress_known !== false) {
    body.append(progressBar(s), node('p', 'tracking-count', `${count(s)} / ${available(s).length} aired episodes watched`));
  }
  const buttons = node('div', 'tracking-card-actions');
  if (s.intent === 'watching' && e) buttons.append(action(`Mark ${code(e)} watched`, () => mark(s, e), 'btn tracking-primary'));
  if (!s.intent) buttons.append(action('Start watching', () => {
    change(s, () => { s.intent = 'watching'; }, 'Started watching.'); void hydrateEpisodes(s);
  }));
  if (s.intent === 'paused' || s.intent === 'dropped') buttons.append(action('Continue tracking', () => change(s, () => { s.intent = 'watching'; }, 'Moved to Watching.')));
  buttons.append(action('Edit progress', () => edit(s), 'tracking-text-button'));
  body.append(buttons); card.append(posterLink, body); return card;
}

export function renderTrackingList() {
  const list = document.getElementById('list');
  if (!list) return;
  let panel = document.getElementById('tracking-list');
  if (!panel) {
    panel = node('section', 'tracking-library'); panel.id = 'tracking-list'; panel.setAttribute('aria-label', 'Your watching progress');
    document.getElementById('list-note').before(panel);
    const intro = node('div', 'tracking-intro'); intro.append(node('p', '', 'Your shows, right where you left them.'), node('span', 'tracking-sample', 'Sample progress'));
    const tools = node('div', 'tracking-list-tools');
    const chips = node('div', 'tracking-filters'); chips.setAttribute('role', 'group'); chips.setAttribute('aria-label', 'Watching status');
    for (const [key, label] of filters) {
      const b = action(label, () => { filter = key; drawList(); }, 'chip'); b.dataset.trackingFilter = key; chips.append(b);
    }
    const find = node('label', 'tracking-find'); find.innerHTML = `${icon('search')}<span class="sr">Find one of your shows</span>`;
    const search = node('input'); search.type = 'search'; search.placeholder = 'Find in My List'; search.id = 'tracking-find';
    search.oninput = () => { query = search.value; drawList(); }; find.append(search);
    tools.append(chips, find);
    const grid = node('div', 'tracking-grid'); grid.id = 'tracking-grid';
    panel.append(intro, tools, grid);
  }
  document.getElementById('list-note').classList.add('tracking-native-saved');
  document.getElementById('list-grid').classList.add('tracking-native-saved');
  drawList();
}
function drawList() {
  const grid = document.getElementById('tracking-grid'); if (!grid) return;
  for (const b of document.querySelectorAll('[data-tracking-filter]')) b.setAttribute('aria-pressed', String(b.dataset.trackingFilter === filter));
  const picked = shows.filter(s => (s.intent || s.saved_demo) && match(s) && s.name.toLowerCase().includes(query.toLowerCase()));
  grid.replaceChildren(...picked.map(s => trackingCard(s)));
  if (!picked.length) grid.append(node('p', 'tracking-empty', shows.length ? 'No shows match this view.' : 'Loading your shows…'));
}

export function mountTrackingTitle(t) {
  title = t;
  const panel = node('section', 't-section tracking-detail'); panel.setAttribute('aria-label', 'Your progress');
  t.episodes.before(panel); t.trackingPanel = panel;
  ready.then(() => { if (t.trackingPanel.isConnected) drawTitle(t); });
}
function drawTitle(t) {
  let s = shows.find(s => s.id === t.id);
  const panel = t.trackingPanel;
  if (!s) {
    panel.replaceChildren(node('h3', '', 'Your progress'), node('p', 'tracking-position', 'Track this show when you start watching.'));
    panel.append(action('Start watching', async () => {
      s = ensureShow(t.card);
      Object.assign(s, { id: t.id, intent: 'watching', ended_demo: (t.live?.status || t.card?.status) === 'Ended' });
      persist(); refresh(); notify('Started watching.');
      await hydrateEpisodes(s, t);
    }));
    return;
  }
  if (!s.episodes.length) void hydrateEpisodes(s, t);
  const header = node('div', 'tracking-detail-head'); header.append(node('h3', '', 'Your progress'), node('span', 'tracking-sample', 'Sample progress'));
  const main = node('div', 'tracking-detail-main');
  const status = node('label', 'tracking-status-select', 'Status');
  const select = node('select'); select.setAttribute('aria-label', 'Watching status'); select.id = 'tracking-status';
  for (const [value, label] of [...(!s.intent ? [['', 'Want to watch']] : []), ...Object.entries(labels)]) {
    const option = node('option', '', label); option.value = value; select.append(option);
  }
  select.value = s.intent || '';
  select.onchange = () => change(s, () => {
    if (select.value === 'completed' && !caught(s)) s.progress_known = false;
    s.intent = select.value || null;
    if (!s.intent) s.saved_demo = true;
  }, `Status changed to ${select.selectedOptions[0].textContent}.`);
  status.append(select);
  const numbers = node('div', 'tracking-detail-numbers'); numbers.append(statusTag(s), node('strong', '', position(s)));
  if (s.progress_known !== false) numbers.append(node('span', '', `${count(s)} of ${available(s).length} aired episodes watched`), progressBar(s));
  main.append(status, numbers);
  const e = next(s), up = node('div', 'tracking-up-next');
  const words = node('div'); words.append(node('span', 'tracking-eyebrow', e ? 'UP NEXT' : 'YOUR PROGRESS'));
  words.append(node('strong', '', e ? `${code(e)}${e.name ? ' · ' + e.name : ''}` : s.progress_known === false ? 'Set episode progress when you remember' : caught(s) ? 'All aired episodes watched' : 'Episode details unavailable'));
  if (e?.runtime) words.append(node('span', 'tracking-up-runtime', `${e.runtime} min`));
  up.append(words);
  if (e && s.intent !== 'completed') up.append(action('Mark watched', () => mark(s, e), 'btn tracking-primary'));
  const footer = node('div', 'tracking-detail-actions'); footer.append(action('Change progress', () => edit(s), 'tracking-text-button'),
    node('span', '', 'Regular episodes · ratings stay separate'));
  panel.replaceChildren(header, main, up, footer);
}

export function mountEpisodeProgress(li, ep, season) {
  ready.then(() => {
    const s = shows.find(s => s.id === season.show); if (!s || !ep.id || !s.episodes.some(e => e.id === ep.id)) return;
    li.classList.add('tracking-episode'); li.dataset.trackingShow = s.id; li.dataset.trackingEpisode = ep.id;
    const b = action('', () => mark(s, ep), 'tracking-episode-check'); b.dataset.trackingCheck = '';
    li.append(b); updateEpisode(li, s, ep);
  });
}
function updateEpisode(li, s, e) {
  const b = li.querySelector('[data-tracking-check]'); if (!b) return;
  const on = watched(s, e); b.innerHTML = on ? icon('check') : ''; b.setAttribute('aria-pressed', String(on));
  b.setAttribute('aria-label', `${on ? 'Mark unwatched' : 'Mark watched'}: ${code(e)}`);
  li.classList.toggle('tracking-episode-watched', on);
  // Existing summaries and stills can contain spoilers; the preview masks unwatched ones.
  li.classList.toggle('tracking-episode-unwatched', !on);
}

function edit(s) {
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
  const save = action('Save progress', () => {
    const i = available(s).findIndex(e => e.id === Number(select.value));
    change(s, () => {
      s.watched = available(s).slice(0, i + 1).map(e => e.id);
      s.progress_known = true;
      if (!s.intent && i >= 0) s.intent = 'watching';
    }, 'Episode progress updated.'); dialog.close();
  }, 'btn tracking-primary'); buttons.append(save);
  const finish = action('Mark all aired episodes watched', () => {
    change(s, () => {
      s.watched = available(s).map(e => e.id);
      s.progress_known = true;
      if (s.ended_demo) s.intent = 'completed'; else s.intent = 'watching';
    }, s.ended_demo ? 'Marked Finished.' : 'You’re caught up.'); dialog.close();
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
  renderTrackingList(); drawHome();
  if (title?.trackingPanel.isConnected) drawTitle(title);
  for (const b of document.querySelectorAll('[data-tracking-save]')) b.paintTrackingBookmark?.();
  for (const li of document.querySelectorAll('[data-tracking-episode]')) {
    const s = shows.find(s => s.id === Number(li.dataset.trackingShow));
    const e = s?.episodes.find(e => e.id === Number(li.dataset.trackingEpisode)); if (e) updateEpisode(li, s, e);
  }
}
const strip = node('aside', 'tracking-preview-strip');
strip.innerHTML = `<span><b>Watch tracking</b><span class="tracking-preview-label">Design preview</span></span><nav aria-label="Tracking mockups"><a href="/list" data-link>My List</a><a href="/list?show=618" data-link>Show detail</a><a href="/" data-link>Home</a></nav>`;
strip.append(action('Reset sample', () => { shows = structuredClone(initial); persist(); refresh(); notify('Sample progress restored.'); }, 'tracking-reset'));
document.body.prepend(strip);

// Optional native Safari proof overlay, absent from the review UI.
if (new URLSearchParams(location.search).get('watch-focus') === '1') {
  const metrics = node('pre', 'tracking-focus-metrics'); metrics.id = 'tracking-focus-metrics'; document.body.append(metrics);
  const reveal = action('Show progress controls', () => document.getElementById('tracking-status')?.scrollIntoView({ block: 'center' }), 'tracking-focus-tools');
  document.body.append(reveal);
  let before = window.visualViewport?.scale || 1;
  document.addEventListener('pointerdown', e => {
    if (e.target.matches('input,select')) before = window.visualViewport?.scale || 1;
  }, { capture: true, passive: true });
  function report() {
    const a = document.activeElement;
    const host = document.querySelector('#tracking-edit[open]') || document.querySelector('#title[open]') || document.body;
    if (metrics.parentElement !== host) host.append(metrics);
    if (reveal.parentElement !== host) host.append(reveal);
    metrics.style.top = `${(window.visualViewport?.offsetTop || 0) + 8}px`;
    metrics.style.left = `${host === document.body ? 8 : host.getBoundingClientRect().left + 8}px`;
    metrics.style.maxWidth = `${Math.min(host.clientWidth - 16, 398)}px`;
    reveal.style.top = `${(window.visualViewport?.offsetTop || 0) + 56}px`;
    reveal.hidden = host.id === 'tracking-edit';
    metrics.textContent = `${a?.id || a?.tagName} · before ${before.toFixed(5)} · scale ${(window.visualViewport?.scale || 1).toFixed(5)}\n` +
      `font ${a ? getComputedStyle(a).fontSize : ''} · floor ${document.documentElement.style.getPropertyValue('--touch-form-font-floor')} · width ${document.documentElement.clientWidth} · ${window.screen.orientation?.type}`;
  }
  document.addEventListener('focusin', report); window.visualViewport?.addEventListener('resize', report);
  window.visualViewport?.addEventListener('scroll', report);
  window.addEventListener('orientationchange', report); report();
}
