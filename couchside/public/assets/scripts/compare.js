import { apiFetch } from './network.js?v=4038b4a1107593ef';
import { esc, html, icon, legend, ratings, ratingSources } from './ratings.js?v=2a0509d86dd759f5';
import { compareMatrix, ratingTableHTML, seasonName } from './rating-views.js?v=2168d19db732fbe1';
import { comparisonOverlayHTML, comparisonOverlayPlan, comparisonShowColour } from './comparison-timeline.js?v=0c0eea8d96bab16d';
import { bindComparisonMatrix, bindComparisonTimeline } from './compare-timeline-interactions.js?v=7e9cdad202dea29d';
import { comparisonPosterColours, loadPosterColour, validPosterColour } from './poster-colours.js?v=0a5c074f14836db9';
import { createComparisonPosters } from './compare-posters.js?v=2f489d7d10b368a3';
import { createComparisonViewport } from './compare-viewport.js?v=40a2db0add024520';

const STORAGE_KEY = 'couchside.comparison-v1', MAX_SHOWS = 40;
const validId = id => Number.isInteger(id) && id > 0 && id <= 2147483647;
const validSeason = season => Number.isInteger(season) && season > 0 && season < 10000;
const seasonNumbers = show => [...new Set(show.episodes.map(episode => episode.season))].sort((a, b) => a - b);
const layouts = [['grid', 'Episode matrix'], ['timeline', 'Timeline']];
const scopes = [['all', 'All seasons'], ['single', 'Single season']];
const timelineLayouts = [['row', 'Posters in a row'], ['side', 'Posters on the side'], ['compact', 'Compact poster row']];
const pointStyles = [['show', 'Match show lines'], ['rating', 'Rating colors'], ['none', 'Lines only']];
const pickers = {
  mode: { label: 'Comparison scope', choices: scopes },
  view: { label: 'Comparison view', choices: layouts },
  timelineLayout: { label: 'Timeline arrangement', choices: timelineLayouts },
  pointStyle: { label: 'Episode points', choices: pointStyles },
};
const defaults = () => ({ ids: [], mode: 'all', inverted: true, averages: true, seasons: {},
  view: 'grid', timelineLayout: 'row', pointStyle: 'show' });

export function validateComparison(value) {
  const state = defaults();
  if (!value || typeof value !== 'object' || Array.isArray(value)) return state;
  state.ids = [...new Set(Array.isArray(value.ids) ? value.ids.filter(validId) : [])].slice(0, MAX_SHOWS);
  if (value.mode === 'single') state.mode = 'single';
  if (typeof value.inverted === 'boolean') state.inverted = value.inverted;
  if (typeof value.averages === 'boolean') state.averages = value.averages;
  for (const [key, choices] of [['view', layouts], ['timelineLayout', timelineLayouts], ['pointStyle', pointStyles]])
    if (choices.some(([id]) => id === value[key])) state[key] = value[key];
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
  for (const [query, key, choices] of [['compare-view', 'view', layouts], ['timeline-layout', 'timelineLayout', timelineLayouts], ['point-style', 'pointStyle', pointStyles]])
    if (params.has(query)) state[key] = choices.some(([id]) => id === params.get(query)) ? params.get(query) : defaults()[key];
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
    seasons: state.ids.filter(id => state.seasons[id] != null).map(id => `${id}:${state.seasons[id]}`).join(','),
    'compare-view': state.view, 'timeline-layout': state.timelineLayout, 'point-style': state.pointStyle });
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

export function comparisonSearchResults(body) {
  if (!Array.isArray(body?.shows)) throw Error('Search is unavailable. Try again.');
  const seen = new Set();
  const unique = items => (Array.isArray(items) ? items : []).filter(show => {
    if (!show || !validId(show.id) || typeof show.name !== 'string' || seen.has(show.id)) return false;
    seen.add(show.id); return true;
  });
  // Keep the shared search's ranking, including titles too new for the catalogue.
  const matches = { title: 'Matches', shows: unique(body.shows) };
  const missing = { title: 'Just added to TVmaze', shows: unique(body.missing) };
  const related = { title: typeof body.related?.title === 'string' ? body.related.title : 'Related shows',
    shows: unique(body.related?.shows) };
  return (body.missing_first ? [missing, matches, related] : [matches, missing, related])
    .filter(group => group.shows.length);
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
export function createComparisonLoader({ loadRatings = ratings, metadata = loadMetadata, colourLoader = loadPosterColour, changed = () => {} } = {}) {
  const entries = new Map(), requests = new Map();
  let disposed = false;
  const ensure = (id, retry = false) => {
    if (disposed || !validId(id) || requests.has(id) || (entries.has(id) && !retry)) return;
    const controller = new AbortController(), token = Symbol(id);
    requests.set(id, { controller, token }); entries.set(id, { status: 'loading' }); changed(id);
    Promise.all([loadRatings(id), metadata(id, controller.signal)]).then(([data, card]) => {
      if (disposed || requests.get(id)?.token !== token) return;
      if (!card || card.id !== id || !Array.isArray(data.episodes)) throw Error('This show could not be loaded.');
      const entry = { status: 'ready', show: { ...card, ...data, id, name: card.name || data.name,
        poster: card.poster, art: fullPoster(card), sources: ratingSources(data) } };
      entries.set(id, entry);
      // Show ratings immediately; artwork sampling cannot delay a usable comparison.
      // Entry identity rejects late colours after removal, retry, or disposal.
      Promise.resolve().then(() => colourLoader(entry.show)).then(colour => {
        if (disposed || entries.get(id) !== entry || !validPosterColour(colour)) return;
        entry.show.posterColour = colour.toLowerCase(); changed(id, 'colour');
      }).catch(() => { /* Unavailable artwork retains its stable fallback. */ });
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

function pickerHTML(key, selected) {
  const { label, choices } = pickers[key], name = choices.find(([value]) => value === selected)[1];
  const menuId = `comparison-${key}-options`, view = key === 'view';
  return `<div class="ratings-picker compare-picker${view ? ' compare-view' : ''}" data-picker="${key}"><button type="button" class="ratings-view-button" data-compare-picker="${key}"${view ? ' data-action="view-picker"' : ''} aria-label="${label}: ${name}" aria-haspopup="listbox" aria-expanded="false" aria-controls="${menuId}">${view ? icon(selected) : ''}<span>${name}</span>${icon('down')}</button><div id="${menuId}" class="ratings-view-options" role="listbox" aria-label="${label}" hidden>${choices.map(([value, text]) => `<button type="button" role="option" tabindex="-1" aria-selected="${value === selected}" data-compare-choice="${key}" data-value="${value}"${view ? ` data-action="view" data-view="${value}"` : key === 'mode' ? ` data-action="mode" data-mode="${value}"` : ''}>${view ? icon(value) : ''}<span>${text}</span>${icon('check')}</button>`).join('')}</div></div>`;
}

function controlsHTML(state) {
  const timeline = state.view === 'timeline';
  return `<div class="ratings-controls compare-toolbar"><div class="compare-selector-controls" role="group" aria-label="Comparison scope and view">${pickerHTML('mode', state.mode)}${pickerHTML('view', state.view)}</div><div class="compare-toggle-controls" role="group" aria-label="Comparison display"><button class="chip" type="button" data-action="invert" aria-pressed="${state.inverted}"${timeline ? ' disabled title="Applies to episode matrix" aria-describedby="comparison-invert-note"' : ''}>Inverted</button><button class="chip" type="button" data-action="averages" aria-pressed="${state.averages}">Show averages</button></div></div>${timeline ? `<p id="comparison-invert-note" class="ratings-credit">Inverted applies to the episode matrix.</p><div class="compare-timeline-settings"><div class="compare-setting"><span class="compare-setting-label">Timeline arrangement</span>${pickerHTML('timelineLayout', state.timelineLayout)}</div><div class="compare-setting"><span class="compare-setting-label">Episode points</span>${pickerHTML('pointStyle', state.pointStyle)}</div></div>` : ''}`;
}

function cardHTML(id, index, state, entry, grabbed, colour) {
  const show = entry?.show, name = show?.name || `Show ${id}`, ready = entry?.status === 'ready';
  const seasons = ready ? seasonNumbers(show) : [];
  const artwork = `<span class="compare-poster compare-poster-empty${entry?.status === 'loading' ? ' skel' : ''}" aria-hidden="true"></span>`;
  const title = ready ? `<button type="button" class="link compare-title" data-action="open" data-id="${id}">${esc(name)}</button>` : esc(name);
  const meta = ready ? `${esc(show.year || '')}${show.year ? ' · ' : ''}${seasons.length} ${seasons.length === 1 ? 'season' : 'seasons'}`
    : entry?.status === 'error' ? esc(entry.error) : 'Loading show…';
  const scope = ready && state.mode === 'single' && seasons.length
    ? `<select data-compare-season="${id}" aria-label="Season for ${esc(name)}">${options(seasons, state.seasons[id])}</select>`
    : `<span class="muted">${state.mode === 'all' ? 'All seasons' : ready ? 'No episodes yet' : ''}</span>`;
  return `<article class="compare-card${state.mode === 'all' ? ' compare-card-all' : ''}${grabbed === id ? ' is-grabbed' : ''}" draggable="true" data-show="${id}" aria-label="${esc(name)}" style="--show-colour:${colour || comparisonShowColour(show || id)}">
    <div class="compare-card-top"><button class="icon-btn compare-reorder-handle" type="button" data-action="grab" data-id="${id}" aria-label="Reorder ${esc(name)}. Press Space to grab, arrow keys to move, Space to drop." aria-pressed="${grabbed === id}" title="Reorder">${actionIcon('grip')}</button><button class="icon-btn compare-remove" type="button" data-action="remove" data-id="${id}" aria-label="Remove ${esc(name)}" title="Remove">${icon('close')}</button></div>
    <div class="compare-card-art">${artwork}</div>
    <div class="compare-card-title"><h4>${title}</h4>${entry?.status === 'error' ? `<button type="button" class="link compare-retry" data-action="retry" data-id="${id}">Try again</button>` : ''}</div>
    <p class="note compare-card-meta"${ready ? '' : ' role="status"'}>${meta}</p>
    <div class="compare-card-actions"><div class="compare-reorder-actions"><button class="round small" type="button" data-action="move" data-id="${id}" data-direction="-1" aria-label="Move ${esc(name)} earlier" title="Move earlier"${index === 0 ? ' disabled' : ''}>${actionIcon('left')}</button><button class="round small" type="button" data-action="move" data-id="${id}" data-direction="1" aria-label="Move ${esc(name)} later" title="Move later"${index === state.ids.length - 1 ? ' disabled' : ''}>${actionIcon('right')}</button></div>${state.mode === 'all' ? '<span class="compare-card-all-scope">All seasons</span>' : ''}</div>
    ${state.mode === 'single' ? `<div class="compare-card-scope">${scope}</div>` : ''}
  </article>`;
}

export function freezeComparison(state, entries) {
  state = validateComparison(state);
  const shows = state.ids.map(id => entries.get(id)?.show).filter(Boolean), colours = comparisonPosterColours(shows);
  return structuredClone({ kind: 'compare', view: state.view, timelineLayout: state.timelineLayout, pointStyle: state.pointStyle,
    title: 'Compare shows', mode: state.mode,
    inverted: state.inverted, averages: state.averages, shows: shows.map(show => {
      const season = state.seasons[show.id] || seasonNumbers(show)[0];
      return { id: show.id, name: show.name, colour: colours.get(show.id), poster: show.art || show.poster, year: show.year, ...(season != null ? { season } : {}),
        sources: show.sources || ratingSources(show), cacheFetchedAt: show.cacheFetchedAt,
        episodes: state.mode === 'all' ? show.episodes : show.episodes.filter(episode => episode.season === season) };
    }) });
}

export function mountCompare(host, { search = '', replaceURL = () => {}, openShow = () => {}, saveSnapshot = async () => {},
  announce = () => {}, metadata, loadRatings, colourLoader, searchShows = query => answer(`/api/search?q=${encodeURIComponent(query)}`) } = {}) {
  const state = parseComparison(search, storedComparison());
  let disposed = false, grabbed = null, dragId = null, timer, searchToken = 0, saving = false, query = '', found = [], searchGroups = [], searchMessage = '', searchOpen = false;
  let matrix, timelineModel, timelineSourcePlan, ratingsCleanup = () => {}, resizeFrame, observedWidth = 0;
  html(host, `<section class="compare-page page"><div class="compare-header"><h1 class="page-h">Compare shows</h1><button class="btn primary compare-save" type="button" disabled>${actionIcon('save')}Save image</button></div><div class="ratings-search-wrap compare-search">${icon('search')}<input type="search" id="compare-search" placeholder="Search any show…" aria-label="Find a show to compare" autocomplete="off" maxlength="100" role="combobox" aria-autocomplete="list" aria-haspopup="listbox" aria-controls="compare-results" aria-expanded="false"><div class="ratings-compare-results" id="compare-results" role="listbox" aria-label="Shows to compare" hidden></div></div><p class="ratings-search-status compare-search-status" role="status"></p><div class="compare-content"></div><p class="compare-status" role="status" aria-live="polite"></p></section>`);
  const input = host.querySelector('#compare-search'), results = host.querySelector('#compare-results'), searchStatus = host.querySelector('.compare-search-status');
  const content = host.querySelector('.compare-content'), save = host.querySelector('.compare-save'), live = host.querySelector('.compare-status');
  const posters = createComparisonPosters();
  const timelineView = createComparisonViewport({ changed: () => { if (!disposed) paintTimeline(); } });
  const searchViewport = window.visualViewport;
  function sizeSearchResults() {
    if (results.hidden) return;
    // iOS keyboard height is reflected in visualViewport, not CSS dvh units.
    const bottom = searchViewport ? searchViewport.offsetTop + searchViewport.height : window.innerHeight;
    const available = Math.max(0, Math.floor(bottom - results.getBoundingClientRect().top - 12));
    results.style.setProperty('--compare-search-height', `${available}px`);
  }
  window.addEventListener('resize', sizeSearchResults);
  window.addEventListener('scroll', sizeSearchResults, { passive: true });
  searchViewport?.addEventListener('resize', sizeSearchResults);
  searchViewport?.addEventListener('scroll', sizeSearchResults, { passive: true });
  const tell = message => { live.textContent = message; announce(message); };
  const persist = () => { rememberComparison(state); replaceURL(comparisonStateURL(state)); };
  const loader = createComparisonLoader({ metadata, loadRatings, colourLoader, changed: (id, reason) => {
    if (!disposed) { if (reason === 'colour') refreshPosterColours(); else render(); }
  } });
  const dismiss = () => { searchOpen = false; results.hidden = true; input.setAttribute('aria-expanded', 'false'); };
  const rememberFocus = () => {
    const active = document.activeElement;
    if (!content.contains(active)) return null;
    return active.dataset.compareSeason ? `[data-compare-season="${active.dataset.compareSeason}"]`
      : active.closest('.compare-picker') ? `[data-compare-picker="${active.closest('.compare-picker').dataset.picker}"]`
        : active.dataset.cell ? active.dataset.episode ? `[data-cell][data-episode="${active.dataset.episode}"]`
          : `[data-cell][data-show-id="${active.dataset.showId}"][data-season="${active.dataset.season}"]`
        : active.dataset.zoomAction ? `[data-zoom-action="${active.dataset.zoomAction}"]`
        : active.dataset.episode && active.dataset.showId ? `.ratings-point-hit[data-show-id="${active.dataset.showId}"][data-episode="${active.dataset.episode}"]`
          : active.classList.contains('ratings-chart-wrap') ? '.ratings-chart-wrap'
            : active.dataset.action ? ['action', 'id', 'direction', 'mode', 'view'].filter(key => active.dataset[key] != null)
              .map(key => `[data-${key}="${active.dataset[key]}"]`).join('') : null;
  };
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
    const width = entries[0]?.contentRect.width;
    if (!Number.isFinite(width) || Math.abs(width - observedWidth) < .5) return;
    observedWidth = width; cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => { if (!disposed && state.view === 'timeline') paintTimeline(); });
  });
  function paintTimeline(renew = false) {
    const board = content.querySelector('[data-timeline-board]'); if (!board) return;
    const focus = rememberFocus(), active = document.activeElement;
    ratingsCleanup();
    if (renew || !timelineModel) {
      timelineModel = freezeComparison(state, loader.entries);
      timelineSourcePlan = comparisonOverlayPlan(timelineModel);
    }
    timelineView.prepare(timelineSourcePlan, JSON.stringify([state.ids, state.mode, state.seasons]));
    const availableWidth = Math.max(240, board.clientWidth || content.clientWidth || 960);
    const options = { availableWidth, pointStyle: state.pointStyle, viewport: timelineView.options(), sourcePlan: timelineSourcePlan };
    const plan = comparisonOverlayPlan(timelineModel, availableWidth, options.viewport, timelineSourcePlan);
    const replacement = document.createElement('div');
    html(replacement, comparisonOverlayHTML(timelineModel, options));
    const chart = replacement.querySelector('.comparison-overlay-frame');
    if (chart) {
      const controls = document.createElement('div'); controls.dataset.comparisonZoomControls = '';
      chart.prepend(controls);
      const hint = document.createElement('p'); hint.className = 'ratings-credit comparison-zoom-hint';
      hint.textContent = 'Scroll or pinch to zoom · Drag to move'; chart.after(hint);
    }
    const current = board.querySelector('.ratings-timeline'), next = replacement.querySelector('.ratings-timeline');
    if (current && next) {
      // Keep the SVG and its viewport as gesture targets throughout a touch or drag.
      // Only projected children change; posters and controls never join this redraw.
      for (const selector of ['.ratings-timeline', '.ratings-chart-axis', '.ratings-chart-wrap']) {
        const before = board.querySelector(selector), after = replacement.querySelector(selector);
        for (const attribute of [...before.attributes]) if (!after.hasAttribute(attribute.name)) before.removeAttribute(attribute.name);
        for (const attribute of after.attributes) before.setAttribute(attribute.name, attribute.value);
        if (selector !== '.ratings-chart-wrap') html(before, after.innerHTML);
      }
      for (const selector of ['.comparison-overlay-key', '.comparison-overlay-caption']) {
        const before = board.querySelector(selector), after = replacement.querySelector(selector);
        before?.replaceWith(after);
      }
      const oldTrendLabel = board.querySelector('.ratings-chart-label-trend');
      const nextTrendLabel = replacement.querySelector('.ratings-chart-label-trend');
      if (oldTrendLabel) nextTrendLabel ? oldTrendLabel.replaceWith(nextTrendLabel) : oldTrendLabel.remove();
      else if (nextTrendLabel) board.querySelector('.comparison-overlay-frame').append(nextTrendLabel);
    } else board.replaceChildren(...replacement.childNodes);
    timelineView.bind(board, plan);
    ratingsCleanup = bindComparisonTimeline(board, timelineModel, host.querySelector('.compare-page'));
    if (focus && document.activeElement !== active) (board.querySelector(focus) || board.querySelector('.ratings-chart-wrap'))?.focus({ preventScroll: true });
    if (!renew) { const tip = host.querySelector('.ratings-tooltip'); if (tip) tip.hidden = true; }
  }
  function refreshPosterColours() {
    const model = freezeComparison(state, loader.entries);
    for (const show of model.shows) content.querySelector(`.compare-card[data-show="${show.id}"]`)?.style.setProperty('--show-colour', show.colour);
    // Sampling must not replace cards or close a menu while someone is using it.
    if (state.view === 'timeline') paintTimeline(true);
  }
  const closePicker = (picker, focus = false) => {
    const trigger = picker?.querySelector('[data-compare-picker]'), menu = picker?.querySelector('[role="listbox"]');
    if (menu) menu.hidden = true;
    if (trigger) { trigger.setAttribute('aria-expanded', 'false'); if (focus) trigger.focus({ preventScroll: true }); }
  };
  const closePickers = () => content.querySelectorAll('.compare-picker').forEach(picker => closePicker(picker));
  const openPicker = picker => {
    closePickers();
    const trigger = picker.querySelector('[data-compare-picker]'), menu = picker.querySelector('[role="listbox"]');
    menu.hidden = false; trigger.setAttribute('aria-expanded', 'true'); menu.querySelector('[aria-selected="true"]')?.focus({ preventScroll: true });
  };
  function choose(button) {
    const key = button.dataset.compareChoice, value = button.dataset.value;
    if (!pickers[key]?.choices.some(([choice]) => choice === value)) return;
    closePickers(); state[key] = value;
    // Restore the closed trigger, never a replacement option or native picker.
    render(`[data-compare-picker="${key}"]`);
  }
  function render(focusOverride) {
    const focus = focusOverride || rememberFocus(), scroll = content.querySelector('.ratings-chart-wrap')?.scrollLeft || 0,
      posterScroll = content.querySelector('.compare-cards')?.scrollLeft || 0;
    ratingsCleanup(); ratingsCleanup = () => {}; timelineView.suspend(); observer?.disconnect(); cancelAnimationFrame(resizeFrame);
    for (const id of state.ids) {
      const show = loader.entries.get(id)?.show;
      if (show) {
        const available = seasonNumbers(show);
        if (!available.length) delete state.seasons[id];
        else if (!available.includes(state.seasons[id])) state.seasons[id] = available[0];
      }
    }
    const model = freezeComparison(state, loader.entries), ready = model.shows.length === state.ids.length;
    const timeline = state.view === 'timeline', controls = controlsHTML(state);
    matrix = timeline ? null : compareMatrix(model);
    const colours = new Map(model.shows.map(show => [show.id, show.colour]));
    const cards = !state.ids.length ? '' : `<div class="compare-cards compare-timeline-posters${state.mode === 'all' ? ' scope-all' : ''}" aria-label="Shows in comparison, in order">${state.ids.map((id, index) => cardHTML(id, index, state, loader.entries.get(id), grabbed, colours.get(id))).join('')}</div>`;
    const plot = timeline ? `${state.pointStyle === 'rating' ? legend() : ''}<div class="compare-board" data-timeline-board></div>`
      : `${legend()}<div class="compare-board">${ratingTableHTML(matrix)}</div>`;
    const board = `<div class="compare-timeline-layout layout-${state.timelineLayout}">${cards}<div class="compare-timeline-plots">${plot}</div></div>`;
    html(content, `${controls}${model.shows.length ? `${model.shows.some(show => seasonNumbers(show).some(season => season >= 1900)) ? '<p class="ratings-credit">Calendar-year season labels are preserved in episode descriptions.</p>' : ''}${board}<p class="ratings-credit">${timeline ? 'Episode ratings · Same rating scale · Each show ends at its last episode' : state.mode === 'all' ? 'Average episode rating per season · Seasons align by number' : 'Episode ratings · Each show uses its selected season'}</p><p class="ratings-credit">${esc([...new Set(model.shows.flatMap(show => show.sources.split(' / ')))].filter(Boolean).join(' / '))} episode ratings · Out of 10</p>${ready ? '' : '<p class="note" role="status">Some shows are still loading. Save image is available when all selected shows are ready.</p>'}` : `<div class="compare-timeline-layout layout-${state.timelineLayout}">${cards}</div><p class="note">${state.ids.length ? 'Loading your comparison…' : 'Find a show to compare.'}</p>`}`);
    posters.paint(content, state.ids.map(id => loader.entries.get(id)?.show).filter(Boolean));
    if (timeline) {
      paintTimeline(true);
      const plots = content.querySelector('.compare-timeline-plots');
      if (plots) { observedWidth = plots.clientWidth; observer?.observe(plots); }
      const viewport = content.querySelector('.ratings-chart-wrap'); if (viewport) viewport.scrollLeft = scroll;
    } else ratingsCleanup = bindComparisonMatrix(content.querySelector('.compare-board'), matrix, model, host.querySelector('.compare-page'));
    const gallery = content.querySelector('.compare-cards'); if (gallery) gallery.scrollLeft = posterScroll;
    save.disabled = saving || !state.ids.length || !ready; save.setAttribute('aria-busy', String(saving));
    if (focus) (content.querySelector(focus) || content.querySelector(`[data-action="grab"][data-id="${document.activeElement?.dataset?.id || ''}"]`))?.focus({ preventScroll: true });
    persist();
  }
  function renderSearch() {
    html(results, searchGroups.map(group => `<div role="group" aria-label="${esc(group.title)}">${searchGroups.length > 1 || group.title !== 'Matches' ? `<p class="compare-search-group" aria-hidden="true">${esc(group.title)}</p>` : ''}${group.shows.map(show => `<button type="button" role="option" aria-selected="false" class="ratings-search-result" data-add="${show.id}"${state.ids.includes(show.id) ? ' disabled aria-disabled="true"' : ''}>${show.poster ? `<img src="${esc(show.poster)}" alt="" loading="lazy">` : ''}<span class="compare-result-label"><b>${esc(show.name)}</b><small>${esc([show.year, typeof show.aka === 'string' && show.aka ? `Also known as ${show.aka}` : ''].filter(Boolean).join(' · '))}</small></span><span class="compare-result-action">${state.ids.includes(show.id) ? 'Added' : 'Add'}</span></button>`).join('')}</div>`).join(''));
    const visible = Boolean(searchOpen && found.length && query.length);
    results.hidden = !visible; input.setAttribute('aria-expanded', String(visible)); searchStatus.textContent = searchMessage;
    sizeSearchResults();
  }
  function add(id) {
    if (state.ids.includes(id)) { tell('This show is already in your comparison.'); return; }
    if (state.ids.length >= MAX_SHOWS) { tell('Compare up to 40 shows at once. Remove one to add another.'); return; }
    state.ids.push(id); query = ''; input.value = ''; ++searchToken; found = []; searchGroups = []; searchOpen = false; searchMessage = ''; renderSearch();
    render(); loader.ensure(id); input.focus(); tell('Show added to comparison.');
  }
  function move(id, destination) {
    state.ids = moveComparison(state.ids, id, destination); render();
    content.querySelector(`[data-action="grab"][data-id="${id}"]`)?.focus({ preventScroll: true });
    tell(`${loader.entries.get(id)?.show?.name || 'Show'} moved to position ${state.ids.indexOf(id) + 1} of ${state.ids.length}.`);
  }
  input.oninput = () => {
    clearTimeout(timer); const asked = ++searchToken; query = input.value.trim(); found = []; searchGroups = []; searchOpen = Boolean(query);
    searchMessage = query ? 'Searching…' : ''; renderSearch();
    if (!query) return;
    const requested = query;
    timer = setTimeout(async () => {
      try {
        const body = await searchShows(requested);
        if (disposed || asked !== searchToken) return;
        searchGroups = comparisonSearchResults(body); found = searchGroups.flatMap(group => group.shows);
        searchMessage = found.length ? '' : 'No matching shows.'; renderSearch();
      } catch (error) { if (!disposed && asked === searchToken) { searchMessage = error.message || 'Search is unavailable. Try again.'; renderSearch(); } }
    }, 250);
  };
  input.onfocus = () => { searchOpen = Boolean(query); if (found.length) renderSearch(); };
  const failedSearchImage = event => {
    if (event.target instanceof HTMLImageElement && results.contains(event.target)) event.target.remove();
  };
  results.addEventListener('error', failedSearchImage, true);
  results.onmousedown = event => {
    // Match the app's recent-search buttons: keep focus until the suggestion click.
    if (event.target.closest('button[data-add]')) event.preventDefault();
  };
  host.onclick = event => {
    const button = event.target.closest('button'); if (!button || !host.contains(button)) return;
    if (button.dataset.compareChoice) { event.preventDefault(); event.stopPropagation(); choose(button); return; }
    if (button.dataset.comparePicker) {
      event.preventDefault(); event.stopPropagation();
      const picker = button.closest('.compare-picker');
      picker.querySelector('[role="listbox"]').hidden ? openPicker(picker) : closePicker(picker);
      return;
    }
    if (button.dataset.add) { add(Number(button.dataset.add)); return; }
    const id = Number(button.dataset.id);
    switch (button.dataset.action) {
      case 'open': openShow(id); break;
      case 'retry': loader.ensure(id, true); break;
      case 'remove': state.ids = state.ids.filter(value => value !== id); delete state.seasons[id]; loader.remove(id); grabbed = null; render(); input.focus(); tell('Show removed.'); break;
      case 'move': move(id, state.ids.indexOf(id) + Number(button.dataset.direction)); break;
      case 'grab': grabbed = grabbed === id ? null : id; render(); content.querySelector(`[data-action="grab"][data-id="${id}"]`)?.focus(); tell(grabbed ? 'Show grabbed. Use arrow keys to move, Space to drop.' : 'Show position saved.'); break;
      case 'invert': if (state.view === 'grid') { state.inverted = !state.inverted; render(); } break;
      case 'averages':
        state.averages = !state.averages;
        if (state.view === 'timeline') {
          button.setAttribute('aria-pressed', String(state.averages)); paintTimeline(true); persist();
        } else render();
        break;
    }
    if (button.dataset.cell) {
      const [row, column] = button.dataset.cell.split(':').map(Number), cell = matrix.rows[row]?.cells[column];
      if (cell) tell(button.getAttribute('aria-label'));
    }
  };
  host.onchange = event => {
    if (!event.target.dataset.compareSeason) return;
    const id = Number(event.target.dataset.compareSeason), selected = Number(event.target.value);
    if (!seasonNumbers(loader.entries.get(id)?.show || { episodes: [] }).includes(selected)) return;
    state.seasons[id] = selected;
    // Keep Safari's just-dismissed select in place; refocusing a new select reopens it.
    if (state.view === 'timeline') paintTimeline(true);
    else {
      ratingsCleanup();
      const model = freezeComparison(state, loader.entries), board = content.querySelector('.compare-board');
      matrix = compareMatrix(model); html(board, ratingTableHTML(matrix));
      ratingsCleanup = bindComparisonMatrix(board, matrix, model, host.querySelector('.compare-page'));
    }
    persist();
  };
  host.onkeydown = event => {
    const target = event.target, picker = target.closest('.compare-picker');
    if (picker) {
      const menu = picker.querySelector('[role="listbox"]');
      if (target.dataset.comparePicker && ['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); openPicker(picker); return; }
      if (!menu.hidden && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closePicker(picker, true); return; }
      if (!menu.hidden && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const buttons = [...menu.querySelectorAll('button')], index = buttons.indexOf(target);
        buttons[event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus(); return;
      }
      if (target.dataset.compareChoice && ['Enter', ' '].includes(event.key)) {
        // Prevent the browser's pending activation from clicking the restored trigger.
        event.preventDefault(); event.stopPropagation(); choose(target); return;
      }
      if (!menu.hidden && event.key === 'Tab') closePicker(picker, true);
    }
    if (query && event.key === 'Escape' && (target === input || results.contains(target))) {
      event.preventDefault(); event.stopPropagation(); input.focus(); dismiss(); return;
    }
    if (event.key === 'Tab' && (target === input || results.contains(target))) dismiss();
    if (!results.hidden && ['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key) && (target === input || results.contains(target))) {
      if (event.key === 'Enter' && target !== input) return;
      event.preventDefault(); event.stopPropagation();
      const buttons = [...results.querySelectorAll('button:not(:disabled)')], index = buttons.indexOf(target);
      if (event.key === 'Enter') { buttons[0]?.click(); return; }
      const next = target === input ? (event.key === 'ArrowDown' ? 0 : buttons.length - 1)
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus(); return;
    }
    if (target.dataset.action === 'grab' && grabbed === Number(target.dataset.id)) {
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
        event.preventDefault(); move(grabbed, state.ids.indexOf(grabbed) + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1));
      } else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); grabbed = null; render(); tell('Show dropped in its current position.'); }
    }
    if (target.matches('.ratings-point-hit[data-episode]') && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const series = timelineSourcePlan?.series.find(item => item.show.id === Number(target.dataset.showId));
      const points = series?.runs.flat() || [], index = points.findIndex(point => point.id === Number(target.dataset.episode));
      const next = points[event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1 : Math.max(0, Math.min(points.length - 1, index + (event.key === 'ArrowRight' ? 1 : -1)))];
      if (next) {
        timelineView.reveal(next.sampleIndex, next.rating);
        content.querySelector(`.ratings-point-hit[data-show-id="${series.show.id}"][data-episode="${next.id}"]`)?.focus({ preventScroll: true });
      }
      return;
    }
    const viewport = target.closest('.scroll-board,.ratings-chart-wrap');
    if (target === viewport && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault(); viewport.scrollLeft = event.key === 'Home' ? 0 : event.key === 'End' ? viewport.scrollWidth - viewport.clientWidth : viewport.scrollLeft + (event.key === 'ArrowRight' ? 1 : -1) * Math.min(160, viewport.clientWidth / 2);
    }
  };
  host.onfocusout = event => {
    const picker = event.target.closest('.compare-picker');
    if (picker && !picker.contains(event.relatedTarget)) closePicker(picker);
    const search = host.querySelector('.compare-search');
    // Safari suggestion taps blur to no element before the click. Outside
    // pointerdown and Tab already dismiss; keep this click target available.
    if (search.contains(event.target) && event.relatedTarget && !search.contains(event.relatedTarget)) dismiss();
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
  const outside = event => {
    if (!host.querySelector('.compare-search').contains(event.target)) dismiss();
    content.querySelectorAll('.compare-picker').forEach(picker => { if (!picker.contains(event.target)) closePicker(picker); });
  };
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
    disposed = true; clearTimeout(timer); ++searchToken; loader.dispose(); posters.dispose(); timelineView.dispose(); observer?.disconnect(); cancelAnimationFrame(resizeFrame); ratingsCleanup();
    results.removeEventListener('error', failedSearchImage, true);
    document.removeEventListener('pointerdown', outside); window.removeEventListener('couchside-ratings', enriched);
    window.removeEventListener('resize', sizeSearchResults); window.removeEventListener('scroll', sizeSearchResults);
    searchViewport?.removeEventListener('resize', sizeSearchResults); searchViewport?.removeEventListener('scroll', sizeSearchResults);
    host.onclick = host.onchange = host.onkeydown = host.onfocusout = host.ondragstart = host.ondragover = host.ondrop = host.ondragend = null;
    input.oninput = input.onfocus = results.onmousedown = save.onclick = null;
  };
}
