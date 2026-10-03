import { leaningHeading } from './format.js?v=7ac003cc28be3a47';

const SVG = 'http://www.w3.org/2000/svg';
const RATES = [-1, 0, .35, .7, 1];
const families = { genre: 'Genre', subgenre: 'Subgenre', theme: 'Theme', language: 'Language',
  country: 'Country', network: 'Network', decade: 'Era', length: 'Episode length', format: 'Format' };
const number = value => value.toLocaleString('en-US');
const plural = (count, word) => `${number(count)} ${word}${count === 1 ? '' : 's'}`;
export const percent = value => value === null ? 'Not available'
  : `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value * 100)}%`;

export function profileKey(profile, owner = '', settings = {}) {
  const ordered = Object.fromEntries(Object.entries(settings || {}).sort(([a], [b]) => a.localeCompare(b)));
  // Recommendation interests use rating order for recency and focus selection.
  return JSON.stringify([String(owner ?? ''), compactProfile(profile), ordered]);
}

function compactProfile(profile) {
  const found = new Map();
  for (const item of Array.isArray(profile) ? profile : []) {
    if (Number.isSafeInteger(item?.id) && item.id > 0 && RATES.includes(item.weight)) {
      found.set(item.id, { id: item.id, weight: item.weight });
    }
  }
  return [...found.values()].slice(0, 3000);
}

const text = value => typeof value === 'string' && value.trim() ? value.trim().slice(0, 200) : null;
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
const fraction = value => value === null || typeof value === 'number' && Number.isFinite(value)
  && value >= 0 && value <= 1;

export function normalizeTaste(raw) {
  if (raw?.version !== 1 || !raw.counts || !raw.reference || !raw.genres || !raw.themes) {
    throw new Error('The taste service returned an incomplete picture.');
  }
  for (const key of ['rated', 'liked', 'disliked']) {
    if (!Number.isSafeInteger(raw.counts[key]) || raw.counts[key] < 0) throw new Error('The taste counts are incomplete.');
  }
  const chart = (value, limit) => {
    if (!Array.isArray(value.dimensions) || !value.coverage) throw new Error('The taste chart is incomplete.');
    for (const key of ['liked_count', 'catalog_count']) {
      if (!Number.isSafeInteger(value.coverage[key]) || value.coverage[key] < 0) throw new Error('The taste coverage is incomplete.');
    }
    const keys = new Set();
    const dimensions = value.dimensions.slice(0, limit).map(item => {
      if (!text(item?.key) || !text(item.label) || !fraction(item.liked) || !fraction(item.catalog)
        || keys.has(item.key)) throw new Error('The taste chart contains invalid values.');
      keys.add(item.key);
      return { ...item, key: text(item.key), label: text(item.label),
        liked_count: count(item.liked_count), catalog_count: count(item.catalog_count) };
    });
    return { dimensions, available: (value.available === true || Number.isSafeInteger(value.available) && value.available > 0) && dimensions.length > 0,
      coverage: { liked_count: count(value.coverage.liked_count), catalog_count: count(value.coverage.catalog_count) } };
  };
  const signals = (values, avoid = false) => (Array.isArray(values) ? values : []).flatMap(item => {
    if (!text(item?.label) || !text(item.family) || avoid && !['disliked', 'never'].includes(item.why)) return [];
    // Theme prevalence is descriptive; this family has no taste-adjustment weight.
    if (item.family === 'theme') return [];
    if (!avoid && (!Number.isFinite(item.share) || item.share < 0 || item.share > 100
      || !Number.isFinite(item.base) || item.base < 0 || item.base > 100)) return [];
    return [{ ...item, label: text(item.label), family: text(item.family), shows: count(item.shows) }];
  });
  return { context: text(raw.context), date: text(raw.date),
    counts: Object.fromEntries(['rated', 'liked', 'disliked', 'neutral', 'loved', 'good', 'okay'].map(key => [key, count(raw.counts[key])])),
    reference: { shows: count(raw.reference.shows), minimum_known: count(raw.reference.minimum_known) },
    genres: chart(raw.genres, 8), themes: chart(raw.themes, 6),
    taste: { leans: signals(raw.taste?.leans), avoids: signals(raw.taste?.avoids, true) },
    interests: (Array.isArray(raw.interests) ? raw.interests : []).flatMap(item => {
      const leans = (Array.isArray(item?.leans) ? item.leans : []).map(text).filter(Boolean).slice(0, 3);
      return leans.length && count(item.size) > 0 ? [{ leans, size: count(item.size) }] : [];
    }),
    model: { omitted: count(raw.model?.omitted), interests_omitted: count(raw.model?.interests_omitted) } };
}

export function comparisonText(dimension) {
  if (dimension.liked === null || dimension.catalog === null) return 'There is not enough known data to compare this yet.';
  const difference = dimension.liked - dimension.catalog;
  if (Math.abs(difference) < .005) return `${dimension.label} appears about as often in your likes as in the catalog.`;
  return `${dimension.label} appears ${difference > 0 ? 'more' : 'less'} often in your likes than in the catalog.`;
}

export function radarPoints(values, radius = 120, x = 260, y = 210) {
  if (!Array.isArray(values) || values.length < 3 || values.some(value => !fraction(value) || value === null)) return '';
  return values.map((value, index) => {
    const angle = -Math.PI / 2 + index * Math.PI * 2 / values.length;
    return `${(x + Math.cos(angle) * radius * value).toFixed(2)},${(y + Math.sin(angle) * radius * value).toFixed(2)}`;
  }).join(' ');
}

const node = (tag, cls = '', value = '') => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (value) element.textContent = value;
  return element;
};
const svg = (tag, attributes = {}, value = '') => {
  const element = document.createElementNS(SVG, tag);
  for (const [name, item] of Object.entries(attributes)) element.setAttribute(name, item);
  if (value) element.textContent = value;
  return element;
};
const button = (label, action, cls = 'btn ghost') => {
  const element = node('button', cls, label); element.type = 'button';
  element.addEventListener('click', action); return element;
};

function legend() {
  const element = node('div', 'taste-legend');
  for (const [label, cls] of [['Your likes', ''], ['Catalog reference', 'taste-reference-key']]) {
    const item = node('span'), key = node('i', cls); key.setAttribute('aria-hidden', 'true');
    item.append(key, document.createTextNode(label)); element.append(item);
  }
  return element;
}

function coverageNote(chart, data, kind) {
  const source = kind === 'themes' ? 'enough plot text' : 'genre metadata';
  return `${source[0].toUpperCase() + source.slice(1)} is available for ${number(chart.coverage.liked_count)} of your ${plural(data.counts.liked, 'liked show')}. `
    + `The reference covers ${plural(chart.coverage.catalog_count, 'established catalog show')} with the same information.`;
}

function chartEmpty(panel, kind) {
  panel.append(node('p', 'taste-copy', kind === 'themes'
    ? 'Like a few shows with plot descriptions to see the themes they share.'
    : 'Like a few shows with genre information to see your comparison.'));
}

function renderGenres(panel, data) {
  panel.append(node('h3', '', 'Genres in your likes'));
  const chart = data.genres;
  if (!chart.available || !chart.coverage.liked_count) { chartEmpty(panel, 'genres'); return; }
  const leading = chart.dimensions.find(item => item.liked !== null && item.liked_count >= 2);
  panel.append(node('p', 'taste-copy', leading ? comparisonText(leading)
    : `A first picture from ${plural(chart.coverage.liked_count, 'liked show')}.`), legend());
  const rows = node('ol', 'taste-bars');
  for (const dimension of chart.dimensions) {
    if (dimension.liked === null || dimension.catalog === null) continue;
    const row = node('li', 'taste-bar-row'), values = node('span', 'taste-bar-values');
    values.append(node('strong', '', percent(dimension.liked)), node('span', '', `catalog ${percent(dimension.catalog)}`));
    const track = node('div', 'taste-bar-track'), fill = node('span', 'taste-bar-fill'), reference = node('span', 'taste-bar-reference');
    track.setAttribute('aria-hidden', 'true'); fill.style.width = `${dimension.liked * 100}%`;
    reference.style.left = `${dimension.catalog * 100}%`; track.append(fill, reference);
    row.append(node('span', 'taste-bar-label', dimension.label), values, track); rows.append(row);
  }
  const scale = node('div', 'taste-scale'); scale.setAttribute('aria-hidden', 'true');
  scale.append(node('span', '', '0%'), node('span', '', '100%'));
  panel.append(rows, scale,
    node('p', 'taste-note', 'Each bar is a share of your weighted likes. Love this counts more than I like this. Shows can have several genres, so these percentages do not add up to 100%.'),
    node('p', 'taste-note', coverageNote(chart, data, 'genres')));
}

function labelLines(label) {
  const lines = [];
  for (const word of label.split(/\s+/)) {
    if (!lines.length || lines.at(-1).length + word.length + 1 > 10) lines.push(word);
    else lines[lines.length - 1] += ` ${word}`;
  }
  return lines;
}

function renderThemes(panel, data, uid) {
  panel.append(node('h3', '', 'Themes in your liked shows'));
  const chart = data.themes;
  if (!chart.available || !chart.coverage.liked_count) { chartEmpty(panel, 'themes'); return; }
  const dimensions = chart.dimensions.filter(item => item.liked !== null && item.catalog !== null);
  panel.append(node('p', 'taste-copy', 'Plot descriptions offer clues about the stories you enjoy. Compare your likes with the same themes across the catalog.'), legend());
  if (dimensions.length >= 3) {
    const image = svg('svg', { viewBox: '0 0 520 420', class: 'taste-radar', role: 'img',
      'aria-labelledby': `${uid}-radar-title ${uid}-radar-desc` });
    image.append(svg('title', { id: `${uid}-radar-title` }, 'Themes in your weighted likes compared with the catalog'),
      svg('desc', { id: `${uid}-radar-desc` }, 'Amber is your weighted likes; the dashed line is the catalog reference. Every axis runs from 0 to 100 percent. Exact values follow in the table.'));
    for (const level of [.25, .5, .75, 1]) {
      image.append(svg('polygon', { points: radarPoints(dimensions.map(() => level)), class: 'taste-radar-grid' }),
        svg('text', { x: 266, y: 210 - 120 * level + 11, class: 'taste-radar-scale' }, `${level * 100}%`));
    }
    dimensions.forEach((dimension, index) => {
      const angle = -Math.PI / 2 + index * Math.PI * 2 / dimensions.length;
      const dx = Math.cos(angle), dy = Math.sin(angle);
      image.append(svg('line', { x1: 260, y1: 210, x2: 260 + dx * 120, y2: 210 + dy * 120, class: 'taste-radar-axis' }));
      const label = svg('text', { x: 260 + dx * 158, y: 210 + dy * 158,
        'text-anchor': Math.abs(dx) < .1 ? 'middle' : dx > 0 ? 'start' : 'end', class: 'taste-radar-label' });
      labelLines(dimension.label).forEach((line, lineIndex) => label.append(svg('tspan', {
        x: 260 + dx * 158, dy: lineIndex ? '1.2em' : '0', }, line)));
      image.append(label);
    });
    image.append(svg('polygon', { points: radarPoints(dimensions.map(item => item.catalog)), class: 'taste-radar-reference' }),
      svg('polygon', { points: radarPoints(dimensions.map(item => item.liked)), class: 'taste-radar-liked' }));
    for (const point of radarPoints(dimensions.map(item => item.liked)).split(' ')) {
      const [cx, cy] = point.split(','); image.append(svg('circle', { cx, cy, r: 3.5, class: 'taste-radar-point' }));
    }
    panel.append(image);
  }
  const table = node('table', 'taste-values'), head = node('thead'), heading = node('tr'), body = node('tbody');
  table.append(node('caption', '', 'Share of shows with each theme, with your likes weighted by rating.'));
  for (const label of ['Theme', 'Your likes', 'Catalog']) { const cell = node('th', '', label); cell.scope = 'col'; heading.append(cell); }
  head.append(heading);
  for (const dimension of dimensions) {
    const row = node('tr'), label = node('th', '', dimension.label); label.scope = 'row';
    row.append(label, node('td', '', percent(dimension.liked)), node('td', '', percent(dimension.catalog))); body.append(row);
  }
  table.append(head, body);
  panel.append(table,
    node('p', 'taste-note', 'Themes are clues found in plot text, rather than a complete description of a show. This view describes your likes; it is not a match score or a direct theme boost to recommendations.'),
    node('p', 'taste-note', coverageNote(chart, data, 'themes')));
}

function renderLeanings(panel, data) {
  panel.append(node('h3', '', 'How your ratings shape your rows'),
    node('p', 'taste-copy', 'Repeated patterns in your likes pull recommendations toward them. Not for me ratings push similar shows back.'));
  const section = (title, signals, cls, detail) => {
    if (!signals.length) return;
    const group = node('section', 'taste-signal-section'), list = node('ul', 'taste-signals');
    group.append(node('h4', '', title));
    for (const signal of signals) {
      const item = node('li', `taste-signal ${cls}`);
      item.append(node('span', 'taste-family', families[signal.family] || signal.family),
        node('strong', '', leaningHeading(signal)), node('p', '', detail(signal))); list.append(item);
    }
    group.append(list); panel.append(group);
  };
  section('Pulling your rows toward', data.taste.leans, '', signal =>
    `${plural(signal.shows, 'liked show')} support this pattern. A ${signal.share}% weighted share, compared with ${signal.base}% of the reference.`);
  section('Signals from Not for me', data.taste.avoids.filter(signal => signal.why === 'disliked'), 'avoid', signal =>
    `Shared by ${plural(signal.shows, 'show')} you marked Not for me.`);
  section('Not yet in your likes', data.taste.avoids.filter(signal => signal.why === 'never'), 'absent', () =>
    'Common in the catalog, but missing from your likes. An absence is a weaker clue than a Not for me rating.');
  if (data.interests.length > 1) {
    const group = node('section', 'taste-signal-section');
    group.append(node('h4', '', 'Different sides of your taste'));
    for (const interest of data.interests) {
      const row = node('div', 'taste-interest'); row.append(node('strong', '', interest.leans.join(' · ')),
        node('span', '', plural(interest.size, 'liked show'))); group.append(row);
    }
    group.append(node('p', 'taste-note', 'Couchside shares your recommendation rows across these interests, so one side of your taste does not crowd out the others.'));
    panel.append(group);
  }
  if (data.model.omitted) panel.append(node('p', 'taste-note', `${plural(data.model.omitted, 'rating')} ${data.model.omitted === 1 ? 'is' : 'are'} outside the recommendation model shown here. The charts still include liked shows with the relevant genre or plot data.`));
  if (data.model.interests_omitted) panel.append(node('p', 'taste-note', `${plural(data.model.interests_omitted, 'more interest')} ${data.model.interests_omitted === 1 ? 'is' : 'are'} outside this compact view.`));
  panel.append(node('p', 'taste-note', 'Shares exclude shows missing that kind of information. These patterns compare your ratings with the catalog and soften small samples. They help explain your rows; they do not define everything you might enjoy.'));
}

let mountId = 0;
export function mountTaste({ dialog, body, getProfile, getOwner = () => '', getSettings = () => ({}), request }) {
  const uid = `taste-${++mountId}`;
  let token = 0, controller = null, cached = null, cachedKey = '', paintedKey = '', requestedKey = '', selected = 'genres', destroyed = false;
  body.classList.add('taste-view');
  function cancel() { ++token; controller?.abort(); controller = null; requestedKey = ''; }
  function status(kind, heading, message) {
    paintedKey = ''; body.replaceChildren(); body.setAttribute('aria-busy', String(kind === 'loading'));
    const content = node('div', 'taste-status'); content.setAttribute('role', 'status');
    if (kind === 'loading') {
      const bars = node('div', 'taste-loading-bars'); bars.setAttribute('aria-hidden', 'true');
      for (let index = 0; index < 4; index++) bars.append(node('span')); content.append(bars);
    }
    content.append(node('h3', '', heading), node('p', '', message));
    if (kind === 'error') content.append(button('Try again', () => refresh(true)));
    body.append(content);
  }
  function render(data) {
    paintedKey = cachedKey;
    body.replaceChildren(); body.setAttribute('aria-busy', 'false');
    body.append(node('p', 'taste-intro', 'Your ratings, in perspective. Amber shows your likes, compared with a reference of established catalog shows.'));
    const counts = node('div', 'taste-counts');
    for (const [value, label] of [[data.counts.liked, 'liked'], [data.counts.disliked, 'not for you']]) {
      const item = node('span'); item.append(node('strong', '', number(value)), document.createTextNode(label)); counts.append(item);
    }
    body.append(counts);
    const hasLeanings = data.taste.leans.length || data.taste.avoids.length || data.interests.length > 1;
    if (!data.counts.liked && !hasLeanings) {
      status('empty', 'Start with a few shows you like', 'Rate shows with I like this or Love this. Their genres and themes will appear here.'); return;
    }
    const views = [['genres', 'Genres', renderGenres], ['themes', 'Themes', renderThemes],
      ...(hasLeanings ? [['leanings', 'Leanings', renderLeanings]] : [])];
    if (!views.some(([key]) => key === selected)) selected = 'genres';
    const tabs = node('div', 'taste-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Your taste views');
    const pairs = [];
    const activate = (key, focus = false) => {
      selected = key;
      for (const [name, tab, panel] of pairs) {
        const active = name === key; tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
        panel.hidden = !active; if (active && focus) tab.focus();
      }
    };
    for (const [key, label, paint] of views) {
      const tab = button(label, () => activate(key), 'taste-tab'), panel = node('section', 'taste-panel');
      tab.id = `${uid}-tab-${key}`; panel.id = `${uid}-panel-${key}`; tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', panel.id); panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', tab.id); panel.tabIndex = 0;
      tab.addEventListener('keydown', event => {
        const index = views.findIndex(([name]) => name === selected);
        const next = event.key === 'ArrowRight' ? (index + 1) % views.length
          : event.key === 'ArrowLeft' ? (index + views.length - 1) % views.length
            : event.key === 'Home' ? 0 : event.key === 'End' ? views.length - 1 : null;
        if (next !== null) { event.preventDefault(); activate(views[next][0], true); }
      });
      paint(panel, data, uid); pairs.push([key, tab, panel]); tabs.append(tab);
    }
    body.append(tabs, ...pairs.map(([, , panel]) => panel)); activate(selected);
  }
  async function refresh(force = false) {
    if (destroyed) return;
    const profile = compactProfile(getProfile()), settings = { ...getSettings() }, key = profileKey(profile, getOwner(), settings);
    if (!force && key === requestedKey && controller) return;
    if (!force && key === cachedKey && cached) { if (dialog.open && paintedKey !== key) render(cached); return; }
    cancel(); cached = null; cachedKey = '';
    if (!dialog.open) { paintedKey = ''; body.replaceChildren(); body.setAttribute('aria-busy', 'false'); return; }
    if (!profile.length) { status('empty', 'Your taste starts with your ratings', 'Like or love a few shows to see what connects them.'); return; }
    requestedKey = key; controller = new AbortController();
    const current = token, signal = controller.signal;
    status('loading', 'Finding your patterns', 'Comparing your ratings with the catalog.');
    try {
      const answer = await request('/api/taste', { profile, settings }, signal);
      if (destroyed || current !== token || signal.aborted || !dialog.open
        || profileKey(getProfile(), getOwner(), getSettings()) !== key) return;
      cached = normalizeTaste(answer); cachedKey = key; requestedKey = ''; controller = null;
      render(cached);
    } catch (error) {
      if (destroyed || current !== token || signal.aborted || !dialog.open) return;
      controller = null; requestedKey = '';
      status('error', 'Your taste could not load', 'Check your connection and try again.');
    }
  }
  function closed() { cancel(); body.setAttribute('aria-busy', 'false'); }
  dialog.addEventListener('close', closed);
  return { open() { if (destroyed) return; if (!dialog.open) dialog.showModal(); return refresh(); }, refresh,
    close() { cancel(); if (dialog.open) dialog.close(); },
    destroy() { destroyed = true; cancel(); cached = null; body.replaceChildren(); dialog.removeEventListener('close', closed); } };
}
