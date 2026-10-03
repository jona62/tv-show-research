import { cachedMatrix, matrixRatings, compactMatrix, matrixSkeleton, html, icon, code } from '/assets/scripts/ratings.js';

// Local design samples only. None of these actions write account or tracking APIs.
const MODES = {
  panel: ['Right panel', 'A clear season-by-season matrix beside your progress.'],
  backdrop: ['Backdrop', 'The same matrix fades into the right side of the card.'],
  tall: ['Taller card', 'A narrower card with more room for the full matrix.'],
};
const KEY = 'couchside.watch-card-designs.v1';
const statuses = { watching: 'Watching', paused: 'Paused', completed: 'Finished', dropped: 'Dropped' };
let samples = [], originals = [], mode = 'compare', host, grid, toolbar, toast, editor, editorFocus;
const matrices = new Map(), loading = new Set();
const element = (tag, cls, text) => {
  const node = document.createElement(tag); node.className = cls || '';
  if (text) node.textContent = text; return node;
};
const button = (text, fn, cls = '') => {
  const node = element('button', cls, text); node.type = 'button'; node.onclick = fn; return node;
};
const released = show => show.episodes.filter(ep => ep.airdate && ep.airdate <= '2026-10-03');
const watched = show => released(show).filter(ep => show.watched.includes(ep.id));
const next = show => released(show).find(ep => !show.watched.includes(ep.id));
const known = show => show.progress_known !== false;
const caught = show => known(show) && released(show).length > 0 && !next(show);
const label = show => !show.intent ? 'Want to watch' : show.intent === 'watching' && caught(show) ? 'Caught up' : statuses[show.intent];
function position(show) {
  if (!show.intent) return 'Ready when you are';
  if (!known(show)) return 'Finished · exact progress not set';
  const through = released(show).findLast(ep => show.watched.includes(ep.id));
  return through ? `Watched through ${code(through)}` : 'No episodes watched yet';
}
function persist() {
  try { sessionStorage.setItem(KEY, JSON.stringify(samples.map(s => ({ id: s.id, watched: s.watched, intent: s.intent, removed: s.removed })))); } catch { /* Session-only samples. */ }
}
function announce(message, restore = null) {
  toast.replaceChildren(element('span', '', message));
  if (restore) toast.append(button('Undo', restore, 'cdc-undo'));
  toast.hidden = false;
}
function cardFocus() {
  const active = document.activeElement, card = active?.closest('.cdc-card');
  if (!card) return null;
  const control = active.classList.contains('cdc-remove') ? '.cdc-remove' :
    active.classList.contains('cdc-primary') ? '.cdc-primary' : '.cdc-edit-button';
  return { id: card.dataset.cardShow, style: card.dataset.cardStyle, control };
}
function restoreFocus(saved) {
  if (!saved) return;
  const card = grid.querySelector(`[data-card-show="${saved.id}"][data-card-style="${saved.style}"]`)
    || grid.querySelector(`[data-card-show="${saved.id}"]`);
  const control = card?.querySelector(saved.control) || card?.querySelector('.cdc-edit-button')
    || grid.querySelector('.cdc-remove') || toolbar.querySelector('button');
  control?.focus({ preventScroll: true });
}
function change(show, fn, message) {
  const before = structuredClone(samples), focus = editor?.open ? editorFocus : cardFocus(); fn(show); persist(); render();
  announce(message, () => { samples = before; persist(); render(); announce('Restored.'); restoreFocus(focus); });
}
function paintMatrix(slot, show) {
  const value = matrices.get(show.id) || cachedMatrix(show.id);
  if (!value) { html(slot, matrixSkeleton()); slot.setAttribute('aria-busy', 'true'); return; }
  matrices.set(show.id, value); slot.dataset.matrixState = 'ready'; slot.setAttribute('aria-busy', 'false');
  html(slot, compactMatrix(value));
}
function updateMatrices() {
  for (const slot of host.querySelectorAll('.cdc-matrix')) {
    const show = samples.find(s => s.id === Number(slot.dataset.show)); if (show) paintMatrix(slot, show);
  }
}
function loadMatrices(ids) {
  const wanted = ids.filter(id => !loading.has(id) && !matrices.has(id)); if (!wanted.length) return;
  wanted.forEach(id => loading.add(id));
  matrixRatings(wanted).then(body => {
    for (const value of body.shows) matrices.set(value.id, value); updateMatrices();
  }).catch(() => {
    for (const slot of host.querySelectorAll('.cdc-matrix')) if (!matrices.has(Number(slot.dataset.show))) {
      slot.replaceChildren(element('span', 'cdc-matrix-empty', 'Ratings unavailable'));
      slot.setAttribute('aria-busy', 'false'); slot.dataset.matrixState = 'error';
    }
  }).finally(() => wanted.forEach(id => loading.delete(id)));
}
function matrixPanel(show) {
  const panel = element('div', 'cdc-map');
  const heading = element('div', 'cdc-map-heading'); heading.append(element('span', '', 'Episode ratings'));
  heading.append(element('span', 'cdc-map-caption', `${new Set(show.episodes.map(e => e.season)).size} seasons`));
  const slot = element('div', 'cdc-matrix ratings-card-matrix'); slot.dataset.show = show.id; slot.dataset.matrixState = 'loading';
  slot.setAttribute('aria-label', `Episode rating matrix for ${show.name}`); paintMatrix(slot, show);
  const captions = element('div', 'cdc-map-footer');
  captions.append(element('span', '', 'Seasons in rows'), element('span', '', 'Episodes across'));
  panel.append(heading, slot, captions); return panel;
}
function mark(show) {
  const episode = next(show); if (!episode) return;
  change(show, s => { s.intent = 'watching'; s.watched.push(episode.id); }, `${code(episode)} marked watched in the sample.`);
}
function edit(show) {
  editorFocus = cardFocus();
  editor.replaceChildren();
  const close = button('', () => editor.close(), 'cdc-editor-close icon-btn'); html(close, icon('close')); close.setAttribute('aria-label', 'Close progress preview');
  const title = element('h2', '', 'Edit sample progress'); title.id = 'cdc-edit-title';
  const actions = element('div', 'cdc-editor-actions');
  const markNext = button(next(show) ? `Mark ${code(next(show))} watched` : 'All episodes watched', () => { mark(show); editor.close(); }, 'btn primary'); markNext.disabled = !next(show);
  actions.append(markNext, button('Mark all aired watched', () => { change(show, s => { s.intent = 'completed'; s.watched = released(s).map(e => e.id); }, 'Finished in the sample.'); editor.close(); }, 'btn ghost'),
    button('Start again', () => { change(show, s => { s.intent = 'watching'; s.watched = []; }, 'Sample progress reset.'); editor.close(); }, 'btn ghost'));
  editor.append(close, title, element('p', 'note', `${show.name} · sample progress for comparing card designs.`), actions);
  editor.showModal();
}
function card(show, style) {
  const node = element('article', `cdc-card cdc-${style}`); node.dataset.cardShow = show.id; node.dataset.cardStyle = style;
  const remove = button('', event => {
    event.stopPropagation();
    change(show, s => { s.removed = true; }, `${show.name} removed from the sample list.`);
    (grid.querySelector('.cdc-remove') || toolbar.querySelector('button')).focus();
  }, 'cdc-remove'); html(remove, icon('close'));
  remove.title = `Remove ${show.name} from My List`; remove.setAttribute('aria-label', remove.title);
  const poster = element('a', 'cdc-poster'); poster.href = `/list?card-design=${mode}&show=${show.id}`; poster.dataset.link = '';
  const image = element('img'); image.src = show.poster; image.alt = ''; image.loading = 'lazy'; poster.append(image); poster.setAttribute('aria-label', `Open ${show.name}`);
  const content = element('div', 'cdc-copy');
  const status = element('span', `cdc-status cdc-status-${caught(show) ? 'caught' : show.intent || 'want'}`, label(show));
  const name = element('a', 'cdc-name', show.name); name.href = poster.href; name.dataset.link = '';
  content.append(status, name, element('p', 'cdc-position', position(show)));
  const episode = next(show);
  const notes = element('p', 'cdc-next', !show.intent ? `${show.episodes.length} episodes to discover` : caught(show) ? 'All aired episodes watched' : episode ? `Up next: ${code(episode)}` : 'Exact progress not set');
  const progress = element('div', 'cdc-progress');
  if (show.intent && known(show)) {
    const bar = element('div', 'cdc-bar'), fill = element('span'); fill.style.width = `${watched(show).length / Math.max(1, released(show).length) * 100}%`; bar.append(fill);
    progress.append(bar, element('p', 'cdc-count', `${watched(show).length} / ${released(show).length} aired episodes watched`));
  }
  progress.append(notes);
  const actions = element('div', 'cdc-actions');
  if (!show.intent || episode && !caught(show) && show.intent === 'watching') {
    actions.append(button(show.intent ? `Mark ${code(episode)} watched` : 'Start watching', () => !show.intent ? change(show, s => { s.intent = 'watching'; }, 'Started watching in the sample.') : mark(show), 'cdc-primary'));
  } else if (show.intent === 'paused' || show.intent === 'dropped') {
    actions.append(button('Continue watching', () => change(show, s => { s.intent = 'watching'; }, 'Resumed in the sample.'), 'cdc-primary'));
  }
  const editButton = button('Edit progress', () => edit(show), 'cdc-edit-button'); editButton.setAttribute('aria-label', `Edit progress for ${show.name}`); actions.append(editButton);
  node.append(remove, poster, content, matrixPanel(show), progress, actions); return node;
}
function render() {
  const focus = cardFocus();
  for (const control of toolbar.querySelectorAll('[data-card-mode]')) control.setAttribute('aria-pressed', String(control.dataset.cardMode === mode));
  grid.className = `cdc-grid cdc-grid-${mode}`; grid.replaceChildren();
  const visible = samples.filter(show => !show.removed);
  const shown = mode === 'compare' ? visible.filter(s => [618, 82, 16149].includes(s.id)) : visible;
  if (mode === 'compare') {
    for (const [style, [name, description]] of Object.entries(MODES)) {
      const column = element('section', 'cdc-comparison');
      const heading = element('div', 'cdc-variant-head'); heading.append(element('span', 'cdc-variant-index', `0${Object.keys(MODES).indexOf(style) + 1}`), element('h3', '', name), element('p', '', description));
      column.append(heading, ...shown.map(show => card(show, style))); grid.append(column);
    }
  } else grid.append(...visible.map(show => card(show, mode)));
  if (!shown.length) grid.append(element('p', 'note', 'The sample list is empty. Reset examples to restore it.'));
  loadMatrices(shown.map(show => show.id));
  restoreFocus(focus);
}
export async function mountCardDesigns() {
  const list = document.getElementById('list'); if (!list) return;
  const requested = new URLSearchParams(location.search).get('card-design');
  if (!requested) {
    const link = element('a', 'cdc-entry', 'Explore card designs'); link.href = '/list?card-design=compare';
    list.querySelector('#list-h').after(link); return;
  }
  mode = requested in MODES ? requested : 'compare'; document.body.classList.add('watch-card-design-mode');
  host = element('section', 'cdc-lab'); host.setAttribute('aria-label', 'Watch-list card design preview');
  const intro = element('div', 'cdc-intro');
  const copy = element('div'); copy.append(element('p', 'cdc-kicker', 'Card design preview · sample progress'), element('h2', '', 'Your progress, with the whole show in view.'),
    element('p', 'cdc-description', 'Compare three ways to bring episode ratings into your watch list.'));
  const back = element('a', 'cdc-back', 'Back to your list'); back.href = '/list'; intro.append(copy, back);
  toolbar = element('div', 'cdc-toolbar'); toolbar.setAttribute('role', 'group'); toolbar.setAttribute('aria-label', 'Card design');
  for (const [value, title] of [['compare', 'Compare designs'], ...Object.entries(MODES).map(([id, value]) => [id, value[0]])]) {
    const pick = button(title, () => { mode = value; const url = new URL(location.href); url.searchParams.set('card-design', mode); history.replaceState(null, '', url); render(); }, 'cdc-mode'); pick.dataset.cardMode = value; toolbar.append(pick);
  }
  const reset = button('Reset examples', () => { samples = structuredClone(originals); persist(); render(); announce('Sample list restored.'); }, 'cdc-reset'); toolbar.append(reset);
  grid = element('div', 'cdc-grid'); toast = element('div', 'cdc-toast'); toast.hidden = true; toast.setAttribute('role', 'status'); toast.setAttribute('aria-live', 'polite');
  editor = element('dialog', 'cdc-editor modal small'); editor.setAttribute('aria-labelledby', 'cdc-edit-title');
  editor.addEventListener('close', () => restoreFocus(editorFocus));
  host.append(intro, toolbar, grid, toast, editor); list.append(host);
  grid.append(element('p', 'note', 'Loading card examples…'));
  try {
    const response = await fetch('/api/tracking-preview', { cache: 'no-store' }); if (!response.ok) throw Error();
    const body = await response.json(); originals = structuredClone(body.shows); samples = structuredClone(originals);
    try {
      const held = JSON.parse(sessionStorage.getItem(KEY));
      if (Array.isArray(held)) for (const show of samples) {
        const state = held.find(s => s.id === show.id);
        if (state && Array.isArray(state.watched) && state.watched.every(id => show.episodes.some(ep => ep.id === id)) && (!state.intent || state.intent in statuses)) {
          show.watched = state.watched; show.intent = state.intent; show.removed = state.removed === true;
        }
      }
    } catch { /* Fresh preview. */ }
    render();
    window.addEventListener('couchside-matrices', event => {
      for (const value of event.detail?.shows || []) matrices.set(value.id, value); updateMatrices();
    });
    window.addEventListener('couchside-matrices-failed', event => {
      for (const slot of host.querySelectorAll(`.cdc-matrix[data-show="${Number(event.detail)}"]`)) if (!matrices.has(Number(event.detail))) {
        slot.replaceChildren(element('span', 'cdc-matrix-empty', 'Ratings unavailable'));
        slot.setAttribute('aria-busy', 'false'); slot.dataset.matrixState = 'error';
      }
    });
    const navigation = () => {
      const picked = new URLSearchParams(location.search).get('card-design');
      host.hidden = !picked; document.body.classList.toggle('watch-card-design-mode', Boolean(picked));
      if (picked) { mode = picked in MODES ? picked : 'compare'; render(); }
      else if (!list.querySelector('.cdc-entry')) {
        const entry = element('a', 'cdc-entry', 'Explore card designs'); entry.href = '/list?card-design=compare'; list.querySelector('#list-h').after(entry);
      }
    };
    window.addEventListener('popstate', navigation);
    document.addEventListener('click', event => {
      if (event.target.closest('a[data-link]')) queueMicrotask(navigation);
    });
  } catch { grid.replaceChildren(element('p', 'note', 'Could not load card examples. Refresh to try again.')); }
}
