import { apiFetch } from './network.js?v=4038b4a1107593ef';
import { esc, html, icon, legend, ratings, ratingSources } from './ratings.js?v=2a0509d86dd759f5';
import { compareMatrix, ratingTableHTML, seasonName } from './rating-views.js?v=2168d19db732fbe1';

const STORAGE_KEY = 'couchside.comparison-v1', MAX_SHOWS = 40;
const validId = id => Number.isInteger(id) && id > 0 && id <= 2147483647;
const validSeason = season => Number.isInteger(season) && season > 0 && season < 10000;
const seasonNumbers = show => [...new Set(show.episodes.map(episode => episode.season))].sort((a, b) => a - b);
const defaults = () => ({ ids: [], mode: 'all', inverted: true, averages: true, seasons: {} });

export function validateComparison(value) {
  const state = defaults();
  if (!value || typeof value !== 'object' || Array.isArray(value)) return state;
  state.ids = [...new Set(Array.isArray(value.ids) ? value.ids.filter(validId) : [])].slice(0, MAX_SHOWS);
  if (value.mode === 'single') state.mode = 'single';
  if (typeof value.inverted === 'boolean') state.inverted = value.inverted;
  if (typeof value.averages === 'boolean') state.averages = value.averages;
  for (const id of state.ids) if (validSeason(value.seasons?.[id])) state.seasons[id] = value.seasons[id];
  return state;
}

function storedComparison(storage) {
  try { return validateComparison(JSON.parse((storage || globalThis.localStorage)?.getItem(STORAGE_KEY))); } catch { return defaults(); }
}
function rememberComparison(state, storage) {
  try { (storage || globalThis.localStorage)?.setItem(STORAGE_KEY, JSON.stringify(validateComparison(state))); } catch { /* The URL still preserves this view. */ }
}

export function parseComparison(search = '', fallback = defaults()) {
  const params = new URLSearchParams(search), state = validateComparison(fallback);
  if (params.has('compare')) state.ids = [...new Set(params.get('compare').split(',').map(Number).filter(validId))].slice(0, MAX_SHOWS);
  if (params.has('mode')) state.mode = params.get('mode') === 'single' ? 'single' : 'all';
  for (const [query, key] of [['compare-inverted', 'inverted'], ['averages', 'averages']]) {
    if (params.get(query) === '0' || params.get(query) === '1') state[key] = params.get(query) === '1';
  }
  if (params.has('seasons')) {
    state.seasons = {};
    for (const entry of params.get('seasons').split(',')) {
      const pieces = entry.split(':'), id = Number(pieces[0]), season = Number(pieces[1]);
      if (pieces.length === 2 && state.ids.includes(id) && validSeason(season)) state.seasons[id] = season;
    }
  }
  return validateComparison(state);
}

export function comparisonStateURL(value) {
  const state = validateComparison(value), params = new URLSearchParams({ compare: state.ids.join(','), mode: state.mode,
    'compare-inverted': state.inverted ? '1' : '0', averages: state.averages ? '1' : '0',
    seasons: state.ids.filter(id => state.seasons[id] != null).map(id => `${id}:${state.seasons[id]}`).join(',') });
  return `/compare?${params}`;
}

export function comparisonURL(addId, currentSearch = '') {
  const state = parseComparison(currentSearch, storedComparison());
  if (validId(addId) && !state.ids.includes(addId)) {
    if (state.ids.length >= MAX_SHOWS) throw Error('Compare up to 40 shows at once. Remove one to add another.');
    state.ids.push(addId);
  }
  rememberComparison(state);
  return comparisonStateURL(state);
}

export function moveComparison(ids, id, destination) {
  const from = ids.indexOf(id);
  if (from < 0 || !Number.isInteger(destination)) return [...ids];
  const result = [...ids], to = Math.max(0, Math.min(result.length - 1, destination));
  result.splice(from, 1); result.splice(to, 0, id);
  return result;
}

async function answer(path, options = {}) {
  const response = await apiFetch(path, options), body = await response.json();
  if (!response.ok) throw Error(body.error || 'Shows are unavailable. Try again.');
  return body;
}
const post = (path, body, signal) => answer(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
async function loadMetadata(id, signal) {
  const body = await post('/api/shows', { ids: [id] }, signal);
  const show = body.shows?.find(item => item.id === id);
  return show || (await post('/api/title', { id }, signal)).show;
}
function fullPoster(show) {
  if (show.art) return show.art;
  if (!show.poster) return null;
  try {
    const url = new URL(show.poster);
    if (url.hostname === 'static.tvmaze.com') url.pathname = url.pathname.replace('/medium_portrait/', '/original_untouched/');
    return url.href;
  } catch { return show.poster; }
}

// Removing a show invalidates its pending work; a late answer cannot re-add it.
export function createComparisonLoader({ loadRatings = ratings, metadata = loadMetadata, changed = () => {} } = {}) {
  const entries = new Map(), requests = new Map();
  let disposed = false;
  const ensure = (id, retry = false) => {
    if (disposed || !validId(id) || requests.has(id) || (entries.has(id) && !retry)) return;
    const controller = new AbortController(), token = Symbol(id);
    requests.set(id, { controller, token }); entries.set(id, { status: 'loading' }); changed(id);
    Promise.all([loadRatings(id), metadata(id, controller.signal)]).then(([data, card]) => {
      if (disposed || requests.get(id)?.token !== token) return;
      if (!card || card.id !== id || !Array.isArray(data.episodes)) throw Error('This show could not be loaded.');
      entries.set(id, { status: 'ready', show: { ...card, ...data, id, name: card.name || data.name,
        poster: card.poster, art: fullPoster(card), sources: ratingSources(data) } });
    }).catch(error => {
      if (!disposed && requests.get(id)?.token === token) entries.set(id, { status: 'error', error: error.message || 'This show could not be loaded.' });
    }).finally(() => {
      if (!disposed && requests.get(id)?.token === token) { requests.delete(id); changed(id); }
    });
  };
  const remove = id => { requests.get(id)?.controller.abort(); requests.delete(id); entries.delete(id); };
  return { entries, ensure, remove, dispose() { disposed = true; for (const id of requests.keys()) remove(id); entries.clear(); } };
}

const paths = {
  grip: '<circle cx="8" cy="5" r="1"/><circle cx="16" cy="5" r="1"/><circle cx="8" cy="12" r="1"/><circle cx="16" cy="12" r="1"/><circle cx="8" cy="19" r="1"/><circle cx="16" cy="19" r="1"/>',
  left: '<path d="M15 18l-6-6 6-6"/>', right: '<path d="M9 18l6-6-6-6"/>',
  save: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
};
const actionIcon = name => `<svg class="ratings-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
const options = (seasons, selected) => seasons.map(season => `<option value="${season}"${season === selected ? ' selected' : ''}>${seasonName(season)}</option>`).join('');

function cardHTML(id, index, state, entry, grabbed) {
  const show = entry?.show, name = show?.name || `Show ${id}`, ready = entry?.status === 'ready';
  const body = ready ? `<div class="compare-show-title">${show.poster ? `<img class="compare-poster" src="${esc(show.poster)}" alt="" loading="lazy">` : ''}<div><h4><button type="button" class="link compare-title" data-action="open" data-id="${id}">${esc(name)}</button></h4><p class="note">${esc(show.year || '')}${show.year ? ' · ' : ''}${seasonNumbers(show).length} ${seasonNumbers(show).length === 1 ? 'season' : 'seasons'}</p></div></div>`
    : entry?.status === 'error' ? `<p class="note" role="status">${esc(entry.error)}</p><button type="button" class="link" data-action="retry" data-id="${id}">Try again</button>`
      : `<p class="note" role="status">Loading show…</p><span class="skel compare-card-skeleton" aria-hidden="true"></span>`;
  return `<article class="compare-card${grabbed === id ? ' is-grabbed' : ''}" draggable="true" data-show="${id}" aria-label="${esc(name)}"><div class="compare-card-top"><button class="icon-btn compare-reorder-handle" type="button" data-action="grab" data-id="${id}" aria-label="Reorder ${esc(name)}. Press Space to grab, arrow keys to move, Space to drop." aria-pressed="${grabbed === id}" title="Reorder">${actionIcon('grip')}</button><button class="icon-btn compare-remove" type="button" data-action="remove" data-id="${id}" aria-label="Remove ${esc(name)}" title="Remove">${icon('close')}</button></div>${body}<div class="compare-card-bottom"><div class="compare-reorder-actions"><button class="round small" type="button" data-action="move" data-id="${id}" data-direction="-1" aria-label="Move ${esc(name)} earlier" title="Move earlier"${index === 0 ? ' disabled' : ''}>${actionIcon('left')}</button><button class="round small" type="button" data-action="move" data-id="${id}" data-direction="1" aria-label="Move ${esc(name)} later" title="Move later"${index === state.ids.length - 1 ? ' disabled' : ''}>${actionIcon('right')}</button></div>${ready && state.mode === 'single' && seasonNumbers(show).length ? `<select data-compare-season="${id}" aria-label="Season for ${esc(name)}">${options(seasonNumbers(show), state.seasons[id])}</select>` : `<span class="muted">${state.mode === 'all' ? 'All seasons' : ready ? 'No episodes yet' : ''}</span>`}</div></article>`;
}

export function freezeComparison(state, entries) {
  return structuredClone({ kind: 'compare', view: 'grid', title: 'Compare shows', mode: state.mode,
    inverted: state.inverted, averages: state.averages, shows: state.ids.map(id => entries.get(id)?.show).filter(Boolean).map(show => {
      const season = state.seasons[show.id] || seasonNumbers(show)[0];
      return { id: show.id, name: show.name, poster: show.art || show.poster, year: show.year, ...(season != null ? { season } : {}),
        sources: show.sources || ratingSources(show), cacheFetchedAt: show.cacheFetchedAt,
        episodes: state.mode === 'all' ? show.episodes : show.episodes.filter(episode => episode.season === season) };
    }) });
}

export function mountCompare(host, { search = '', replaceURL = () => {}, openShow = () => {}, saveSnapshot = async () => {},
  announce = () => {}, metadata, loadRatings, searchShows = query => answer(`/api/search?q=${encodeURIComponent(query)}`) } = {}) {
  const state = parseComparison(search, storedComparison());
  let disposed = false, grabbed = null, dragId = null, timer, searchToken = 0, saving = false, query = '', found = [], searchMessage = '';
  let matrix;
  html(host, `<section class="compare-page page"><div class="compare-header"><h1 class="page-h">Compare shows</h1><button class="btn primary compare-save" type="button" disabled>${actionIcon('save')}Save image</button></div><div class="ratings-search-wrap compare-search">${icon('search')}<input type="search" id="compare-search" placeholder="Search any show…" aria-label="Find a show to compare" autocomplete="off" role="combobox" aria-autocomplete="list" aria-controls="compare-results" aria-expanded="false"><div class="ratings-compare-results" id="compare-results" hidden></div></div><p class="ratings-search-status compare-search-status" role="status"></p><div class="compare-content"></div><p class="compare-status" role="status" aria-live="polite"></p></section>`);
  const input = host.querySelector('#compare-search'), results = host.querySelector('#compare-results'), searchStatus = host.querySelector('.compare-search-status');
  const content = host.querySelector('.compare-content'), save = host.querySelector('.compare-save'), live = host.querySelector('.compare-status');
  const tell = message => { live.textContent = message; announce(message); };
  const persist = () => { rememberComparison(state); replaceURL(comparisonStateURL(state)); };
  const loader = createComparisonLoader({ metadata, loadRatings, changed: () => { if (!disposed) render(); } });
  const dismiss = () => { results.hidden = true; input.setAttribute('aria-expanded', 'false'); };
  const rememberFocus = () => {
    const active = document.activeElement;
    if (!content.contains(active)) return null;
    return active.dataset.compareSeason ? `[data-compare-season="${active.dataset.compareSeason}"]`
      : active.dataset.action ? ['action', 'id', 'direction', 'mode'].filter(key => active.dataset[key] != null)
        .map(key => `[data-${key}="${active.dataset[key]}"]`).join('') : null;
  };
  function render() {
    const focus = rememberFocus();
    for (const id of state.ids) {
      const show = loader.entries.get(id)?.show;
      if (show) {
        const available = seasonNumbers(show);
        if (!available.length) delete state.seasons[id];
        else if (!available.includes(state.seasons[id])) state.seasons[id] = available[0];
      }
    }
    const model = freezeComparison(state, loader.entries), ready = model.shows.length === state.ids.length;
    matrix = compareMatrix(model);
    const controls = `<div class="ratings-controls compare-toolbar"><div class="ratings-card-choices compare-scope" role="group" aria-label="Comparison scope"><button type="button" data-action="mode" data-mode="all" aria-pressed="${state.mode === 'all'}">All seasons</button><button type="button" data-action="mode" data-mode="single" aria-pressed="${state.mode === 'single'}">Single season</button></div><button class="chip" type="button" data-action="invert" aria-pressed="${state.inverted}">Inverted</button><button class="chip" type="button" data-action="averages" aria-pressed="${state.averages}">Show averages</button></div>`;
    html(content, `<div class="compare-cards" aria-label="Shows in comparison, in order">${state.ids.map((id, index) => cardHTML(id, index, state, loader.entries.get(id), grabbed)).join('')}</div>${controls}${model.shows.length ? `${model.shows.some(show => seasonNumbers(show).some(season => season >= 1900)) ? '<p class="ratings-credit">Calendar-year season labels are preserved.</p>' : ''}${legend()}<div class="compare-board">${ratingTableHTML(matrix)}</div><p class="ratings-credit">${state.mode === 'all' ? 'Average episode rating per season · Seasons align by number' : 'Episode ratings · Each show uses its selected season'}</p><p class="ratings-credit">${esc([...new Set(model.shows.flatMap(show => show.sources.split(' / ')))].filter(Boolean).join(' / '))} episode ratings · Out of 10</p>${ready ? '' : '<p class="note" role="status">Some shows are still loading. Save image is available when all selected shows are ready.</p>'}` : `<p class="note">${state.ids.length ? 'Loading your comparison…' : 'Find a show to compare.'}</p>`}`);
    save.disabled = saving || !state.ids.length || !ready; save.setAttribute('aria-busy', String(saving));
    if (focus) (content.querySelector(focus) || content.querySelector(`[data-action="grab"][data-id="${document.activeElement?.dataset?.id || ''}"]`))?.focus({ preventScroll: true });
    persist();
  }
  function renderSearch() {
    html(results, found.map(show => `<button type="button" class="ratings-search-result" data-add="${show.id}"${state.ids.includes(show.id) ? ' disabled' : ''}>${show.poster ? `<img src="${esc(show.poster)}" alt="">` : ''}<span><b>${esc(show.name)}</b><small>${esc(show.year || '')}</small></span><span class="compare-result-action">${state.ids.includes(show.id) ? 'Added' : 'Add'}</span></button>`).join(''));
    const visible = Boolean(found.length && query.length >= 2);
    results.hidden = !visible; input.setAttribute('aria-expanded', String(visible)); searchStatus.textContent = searchMessage;
  }
  function add(id) {
    if (state.ids.includes(id)) { tell('This show is already in your comparison.'); return; }
    if (state.ids.length >= MAX_SHOWS) { tell('Compare up to 40 shows at once. Remove one to add another.'); return; }
    state.ids.push(id); query = ''; input.value = ''; ++searchToken; found = []; searchMessage = ''; renderSearch();
    render(); loader.ensure(id); input.focus(); tell('Show added to comparison.');
  }
  function move(id, destination) {
    state.ids = moveComparison(state.ids, id, destination); render();
    content.querySelector(`[data-action="grab"][data-id="${id}"]`)?.focus({ preventScroll: true });
    tell(`${loader.entries.get(id)?.show?.name || 'Show'} moved to position ${state.ids.indexOf(id) + 1} of ${state.ids.length}.`);
  }
  input.oninput = () => {
    clearTimeout(timer); const asked = ++searchToken; query = input.value.trim(); found = [];
    searchMessage = query.length < 2 ? '' : 'Searching…'; renderSearch();
    if (query.length < 2) return;
    const requested = query;
    timer = setTimeout(async () => {
      try {
        const body = await searchShows(requested);
        if (disposed || asked !== searchToken) return;
        if (!Array.isArray(body.shows)) throw Error('Search is unavailable. Try again.');
        found = body.shows.filter(show => show && validId(show.id) && typeof show.name === 'string').slice(0, 8);
        searchMessage = found.length ? '' : 'No matching shows.'; renderSearch();
      } catch (error) { if (!disposed && asked === searchToken) { searchMessage = error.message || 'Search is unavailable. Try again.'; renderSearch(); } }
    }, 250);
  };
  input.onfocus = () => { if (found.length) renderSearch(); };
  host.onclick = event => {
    const button = event.target.closest('button'); if (!button || !host.contains(button)) return;
    if (button.dataset.add) { add(Number(button.dataset.add)); return; }
    const id = Number(button.dataset.id);
    switch (button.dataset.action) {
      case 'open': openShow(id); break;
      case 'retry': loader.ensure(id, true); break;
      case 'remove': state.ids = state.ids.filter(value => value !== id); delete state.seasons[id]; loader.remove(id); grabbed = null; render(); input.focus(); tell('Show removed.'); break;
      case 'move': move(id, state.ids.indexOf(id) + Number(button.dataset.direction)); break;
      case 'grab': grabbed = grabbed === id ? null : id; render(); content.querySelector(`[data-action="grab"][data-id="${id}"]`)?.focus(); tell(grabbed ? 'Show grabbed. Use arrow keys to move, Space to drop.' : 'Show position saved.'); break;
      case 'mode': state.mode = button.dataset.mode; render(); break;
      case 'invert': state.inverted = !state.inverted; render(); break;
      case 'averages': state.averages = !state.averages; render(); break;
    }
    if (button.dataset.cell) {
      const [row, column] = button.dataset.cell.split(':').map(Number), cell = matrix.rows[row]?.cells[column];
      if (cell) tell(button.getAttribute('aria-label'));
    }
  };
  host.onchange = event => {
    if (!event.target.dataset.compareSeason) return;
    const id = Number(event.target.dataset.compareSeason), selected = Number(event.target.value);
    if (seasonNumbers(loader.entries.get(id)?.show || { episodes: [] }).includes(selected)) { state.seasons[id] = selected; render(); }
  };
  host.onkeydown = event => {
    const target = event.target;
    if (!results.hidden && ['ArrowDown', 'ArrowUp', 'Escape'].includes(event.key) && (target === input || results.contains(target))) {
      event.preventDefault(); event.stopPropagation();
      if (event.key === 'Escape') { dismiss(); input.focus(); return; }
      const buttons = [...results.querySelectorAll('button:not(:disabled)')], index = buttons.indexOf(target);
      buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus(); return;
    }
    if (target.dataset.action === 'grab' && grabbed === Number(target.dataset.id)) {
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
        event.preventDefault(); move(grabbed, state.ids.indexOf(grabbed) + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1));
      } else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); grabbed = null; render(); tell('Show dropped in its current position.'); }
    }
    const viewport = target.closest('.scroll-board');
    if (target === viewport && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault(); viewport.scrollLeft = event.key === 'Home' ? 0 : event.key === 'End' ? viewport.scrollWidth : viewport.scrollLeft + (event.key === 'ArrowRight' ? 160 : -160);
    }
  };
  host.ondragstart = event => {
    const card = event.target.closest('[data-show]');
    if (!card || event.target.closest('input,select')) { event.preventDefault(); return; }
    dragId = Number(card.dataset.show); card.classList.add('is-dragging');
    event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(dragId));
  };
  host.ondragover = event => { if (dragId && event.target.closest('[data-show]')) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; } };
  host.ondrop = event => {
    const card = event.target.closest('[data-show]'); if (!dragId || !card) return;
    event.preventDefault(); move(dragId, state.ids.indexOf(Number(card.dataset.show))); dragId = null;
  };
  host.ondragend = () => { dragId = null; host.querySelectorAll('.is-dragging').forEach(card => card.classList.remove('is-dragging')); };
  const outside = event => { if (!host.querySelector('.compare-search').contains(event.target)) dismiss(); };
  document.addEventListener('pointerdown', outside);
  save.onclick = async () => {
    if (save.disabled) return;
    const model = freezeComparison(state, loader.entries); saving = true; render();
    try { await saveSnapshot(model); if (!disposed) tell('Snapshot downloaded.'); }
    catch (error) { if (!disposed) tell(`Snapshot could not be created: ${error.message}`); }
    finally { saving = false; if (!disposed) render(); }
  };
  const enriched = event => {
    if (state.ids.includes(event.detail)) { loader.remove(event.detail); loader.ensure(event.detail); }
  };
  window.addEventListener('couchside-ratings', enriched);
  render(); state.ids.forEach(id => loader.ensure(id));
  return () => {
    disposed = true; clearTimeout(timer); ++searchToken; loader.dispose();
    document.removeEventListener('pointerdown', outside); window.removeEventListener('couchside-ratings', enriched);
    host.onclick = host.onchange = host.onkeydown = host.ondragstart = host.ondragover = host.ondrop = host.ondragend = null;
    input.oninput = input.onfocus = save.onclick = null;
  };
}
