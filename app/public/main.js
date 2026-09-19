import { fitRows, chooseSpokes, drawFit, short } from './fit.js';

const boot = JSON.parse(document.getElementById('boot').textContent);
const $ = id => document.getElementById(id);
const KEY = 'next-watch-v1';
const RATINGS = [[1, 'Loved'], [.7, 'Liked'], [.35, 'OK'], [0, 'Meh'], [-1, 'No']];
const SPOKEN = { 1: 'Loved it', .7: 'Liked it', .35: 'It was OK', 0: 'Seen it, no strong feelings', '-1': 'Did not like it' };
const FOCUS = {
  balanced: { text: 40, themes: 35, genres: 25 },
  story: { text: 70, themes: 20, genres: 10 },
  themes: { text: 15, themes: 70, genres: 15 },
  genres: { text: 15, themes: 20, genres: 65 },
};
const FORMATS = ['all', 'scripted', 'animation', 'documentary', 'unscripted'];
const DEFAULTS = {
  text: 40, themes: 35, genres: 25, closest: .3, dislike: .35,
  language: 'all', type: 'all', status: 'all', year_min: 1990, runtime_min: 0,
  rating_min: 0, known_min: 85,
};
const KNOWN = [0, 60, 85, 95];
const el = (tag, text = '', cls = '') => {
  const n = document.createElement(tag);
  if (text) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
const button = (text, cls, onClick) => {
  const b = el('button', text, cls);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
};
const meta = s => [s.year ?? 'Year unknown', s.channel, s.rating ? '★ ' + s.rating : null].filter(Boolean).join(' · ');

let state = { profile: [], saved: [], settings: { ...DEFAULTS } };
let data = null, tab = 'next', reqId = 0, reqAbort = null, timer = null;
let searchId = 0, searchAbort = null, searchTimer = null, fitPick = null;
let allSignals = false, allRelated = false;

/* ------------------------------------------------------------- storage */
try {
  const saved = JSON.parse(localStorage.getItem(KEY));
  if (saved && Array.isArray(saved.profile)) {
    state = {
      profile: saved.profile.filter(p => Number.isInteger(p.id) && RATINGS.some(([w]) => w === p.weight)).slice(0, 60),
      saved: (Array.isArray(saved.saved) ? saved.saved : []).filter(s => Number.isInteger(s.id)).slice(0, 200),
      settings: { ...DEFAULTS, ...(saved.settings || {}) },
    };
    // A lists saved before the popularity control existed keeps its old rating floor otherwise.
    if (!KNOWN.includes(state.settings.known_min)) state.settings.known_min = 85;
    state.settings.rating_min = 0;
    // Format used to be a raw catalog type; anything the new grouping cannot show falls back.
    if (!FORMATS.includes(state.settings.type)) state.settings.type = 'all';
  }
} catch { /* first visit, or storage is off */ }

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode */ }
}

/* --------------------------------------------------------------- theme */
const setTheme = mode => {
  document.documentElement.dataset.theme = mode;
  $('theme').setAttribute('aria-label', mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  try { localStorage.setItem('next-watch-theme', mode); } catch { /* ignore */ }
};
setTheme(localStorage.getItem('next-watch-theme') === 'dark' ? 'dark' : 'light');
$('theme').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

/* ---------------------------------------------------------------- tabs */
function show(name) {
  tab = name;
  for (const section of TABS) $(section).hidden = section !== name;
  for (const t of document.querySelectorAll('.tab')) t.setAttribute('aria-selected', String(t.dataset.tab === name));
  if (name === 'taste') renderFit();
  if (name === 'saved') renderSaved();
  document.documentElement.scrollTop = document.body.scrollTop = 0;
}
const TABS = ['next', 'saved', 'taste', 'shows'];
for (const t of document.querySelectorAll('.tab')) {
  t.addEventListener('click', () => show(t.dataset.tab));
  t.addEventListener('keydown', e => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = TABS[(TABS.indexOf(t.dataset.tab) + step + TABS.length) % TABS.length];
    show(next);
    document.querySelector(`[data-tab="${next}"]`).focus();
  });
}

/* -------------------------------------------------------------- dialogs */
for (const b of document.querySelectorAll('[data-close]')) b.addEventListener('click', () => b.closest('dialog').close());
for (const d of document.querySelectorAll('dialog')) {
  d.addEventListener('click', e => { if (e.target === d) d.close(); });
}
$('open-about').addEventListener('click', () => $('about').showModal());
$('open-tune').addEventListener('click', () => $('tune').showModal());

/* --------------------------------------------------------------- list */
function has(id) { return state.profile.some(p => p.id === id); }

function add(showRow, weight = .7) {
  if (has(showRow.id)) return;
  state.saved = state.saved.filter(s => s.id !== showRow.id);
  if (state.profile.length >= 60) { note('Your list is full at 60 shows. Remove one first.'); return; }
  state.profile.push({ id: showRow.id, name: showRow.name, year: showRow.year, channel: showRow.channel, weight });
  save(); renderList(); renderPicks(); run(0);
}
function rate(id, weight) {
  const found = state.profile.find(p => p.id === id);
  if (!found) return;
  found.weight = weight;
  save(); renderList(); run();
}
function remove(id) {
  state.profile = state.profile.filter(p => p.id !== id);
  save(); renderList(); renderPicks(); run(0);
}

/* -------------------------------------------------------------- search */
$('q').addEventListener('input', () => {
  const query = $('q').value.trim();
  const id = ++searchId;
  clearTimeout(searchTimer); searchAbort?.abort();
  $('clear-q').hidden = !query;
  if (query.length < 2) { closeDrop(); return; }
  openDrop('Searching…');
  searchTimer = setTimeout(async () => {
    searchAbort = new AbortController();
    try {
      const res = await fetch('/api/search?q=' + encodeURIComponent(query), { signal: searchAbort.signal });
      const body = await res.json();
      if (id !== searchId) return;
      if (!res.ok) throw new Error(body.error || 'Search is unavailable.');
      renderHits(body.shows);
    } catch (e) {
      if (e.name !== 'AbortError' && id === searchId) openDrop(e.message);
    }
  }, 180);
});
$('clear-q').addEventListener('click', () => {
  $('q').value = ''; $('clear-q').hidden = true; closeDrop(); $('q').focus();
});
$('q').addEventListener('keydown', e => { if (e.key === 'Escape') { $('q').value = ''; closeDrop(); } });
document.addEventListener('click', e => {
  if (!e.target.closest('.top')) closeDrop();
});

function openDrop(message) {
  $('drop').hidden = false;
  $('q').setAttribute('aria-expanded', 'true');
  $('hint').textContent = message || '';
  if (message) $('hits').replaceChildren();
}
function closeDrop() {
  $('drop').hidden = true;
  $('q').setAttribute('aria-expanded', 'false');
}
function renderHits(shows) {
  openDrop(shows.length ? '' : 'No match in this snapshot. Try a shorter title.');
  const list = $('hits');
  list.replaceChildren();
  for (const s of shows) {
    const li = el('li');
    const already = has(s.id);
    const row = button('', 'hit', () => { add(s); $('q').value = ''; $('clear-q').hidden = true; closeDrop(); });
    row.append(el('b', s.name), el('small', meta(s)), el('em', already ? 'Added' : 'Add'));
    row.disabled = already;
    row.setAttribute('role', 'option');
    row.setAttribute('aria-label', `${already ? 'Already added' : 'Add'} ${s.name}, ${meta(s)}`);
    li.append(row);
    list.append(li);
  }
}

/* --------------------------------------------------------- quick picks */
function renderPicks() {
  const holder = $('picks');
  holder.replaceChildren();
  for (const s of boot.picks) {
    const chip = button(s.name, 'chip', () => add(s, 1));
    chip.setAttribute('aria-pressed', String(has(s.id)));
    chip.disabled = has(s.id);
    holder.append(chip);
  }
}

/* ------------------------------------------------------------ requests */
function note(text, bad = false) {
  $('next-meta').textContent = text;
  $('next-meta').classList.toggle('error', bad);
}
function run(delay = 160) {
  const id = ++reqId;
  clearTimeout(timer); reqAbort?.abort();
  const liked = state.profile.filter(p => p.weight > 0).length;
  $('onboard').hidden = liked > 0;
  $('next-body').hidden = liked === 0;
  renderCount();
  if (!liked) { data = null; renderList(); return; }
  note('Working out your picks…');
  timer = setTimeout(async () => {
    reqAbort = new AbortController();
    try {
      const res = await fetch('/api/recommend', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: reqAbort.signal,
        body: JSON.stringify({ profile: state.profile.map(({ id, weight }) => ({ id, weight })), settings: state.settings }),
      });
      const body = await res.json();
      if (id !== reqId) return;
      if (!res.ok) throw new Error(body.error || 'Could not work out your picks.');
      data = body;
      state.settings = body.settings;
      save();
      render();
    } catch (e) {
      if (e.name === 'AbortError' || id !== reqId) return;
      note(e.message || 'Could not reach the recommender.', true);
    }
  }, delay);
}

/* -------------------------------------------------------------- render */
function render() {
  renderCards();
  renderTaste();
  renderList();
  renderCount();
}
function renderCount() {
  const n = state.profile.length;
  $('tab-count').textContent = n || '';
  $('tab-count').hidden = !n;
  $('saved-count').textContent = state.saved.length || '';
  $('saved-count').hidden = !state.saved.length;
}

function isSaved(id) { return state.saved.some(s => s.id === id); }

function toggleSave(pick) {
  state.saved = isSaved(pick.id)
    ? state.saved.filter(s => s.id !== pick.id)
    : [...state.saved, { id: pick.id, name: pick.name, year: pick.year, channel: pick.channel,
                         rating: pick.rating, url: pick.url }];
  save();
  renderCount();
  if (data) renderCards();
  renderSaved();
}

function renderSaved() {
  const holder = $('saved-list');
  holder.replaceChildren();
  $('clear-saved').hidden = !state.saved.length;
  $('saved-meta').textContent = state.saved.length
    ? `${state.saved.length} to watch. Rating one moves it into your shows, where it starts shaping the picks.`
    : 'Nothing saved yet. Hit Save on any pick and it waits for you here.';
  for (const s of state.saved) {
    const card = el('article', '', 'card');
    const top = el('div', '', 'card-top');
    const title = el('div', '', 'card-title');
    const heading = el('h3');
    const out = el('a', s.name);
    out.href = s.url; out.target = '_blank'; out.rel = 'noopener noreferrer';
    out.setAttribute('aria-label', `${s.name} on TVmaze, opens in a new tab`);
    heading.append(out);
    title.append(heading, el('p', meta(s)));
    top.append(title);
    const acts = el('div', '', 'acts');
    const watched = button('I watched it', 'why', () => { toggleSave(s); add(s, .7); show('shows'); });
    watched.setAttribute('aria-label', `Move ${s.name} into your shows as liked`);
    acts.append(watched, button('Remove', '', () => toggleSave(s)));
    card.append(top, acts);
    holder.append(card);
  }
}
$('clear-saved').addEventListener('click', () => { state.saved = []; save(); renderCount(); renderSaved(); if (data) renderCards(); });

// Theme and genre names overlap ("Crime / illicit enterprise" and the Crime tag): show each once.
function sharedLabels(pick) {
  const out = [];
  for (const name of [...pick.shared_themes.map(short), ...pick.shared_genres]) {
    if (!out.some(seen => seen.toLowerCase() === name.toLowerCase())) out.push(name);
  }
  return out;
}

function matchOf(pick) {
  const best = data.picks[0]?.score || 1;
  return Math.max(1, Math.min(99, Math.round(pick.score / best * 99)));
}

function renderCards() {
  const holder = $('cards');
  holder.replaceChildren();
  $('warn').hidden = !data.warning;
  $('warn').textContent = data.warning;
  $('none').hidden = !data.message;
  $('none').textContent = data.message;
  note(data.picks.length
    ? `${data.picks.length} picks from ${data.candidate_count.toLocaleString()} shows that fit your filters.`
    : '');
  for (const pick of data.picks) {
    const card = el('article', '', 'card');
    const top = el('div', '', 'card-top');
    const title = el('div', '', 'card-title');
    const heading = el('h3');
    const out = el('a', pick.name);
    out.href = pick.url; out.target = '_blank'; out.rel = 'noopener noreferrer';
    out.setAttribute('aria-label', `${pick.name} on TVmaze, opens in a new tab`);
    heading.append(out);
    title.append(heading, el('p', [meta(pick), pick.runtime ? pick.runtime + ' min' : null].filter(Boolean).join(' · ')));
    const score = el('div', '', 'score');
    score.append(el('b', String(matchOf(pick))), el('span', 'match'));
    top.append(title, score);

    const because = el('p', '', 'because');
    because.append(document.createTextNode('Closest to '), el('b', pick.because));
    const tags = el('div', '', 'tags');
    for (const name of sharedLabels(pick).slice(0, 3)) tags.append(el('span', name, 'tag'));
    if (!tags.childElementCount) tags.append(el('span', 'a close match on plot wording', 'tag plain'));

    const acts = el('div', '', 'acts');
    const keep = button(isSaved(pick.id) ? 'Saved ✓' : 'Save', '', () => toggleSave(pick));
    keep.classList.toggle('on', isSaved(pick.id));
    keep.setAttribute('aria-pressed', String(isSaved(pick.id)));
    acts.append(
      button('Why this?', 'why', () => openWhy(pick)),
      keep,
      button('Seen it', '', () => add(pick, 0)),
      button('Not for me', '', () => add(pick, -1)),
    );

    card.append(top, because, tags);
    if (pick.summary) card.append(el('p', pick.summary, 'blurb'));
    card.append(acts);
    holder.append(card);
  }
}

function openWhy(pick) {
  const body = $('why-body');
  body.replaceChildren();
  body.append(el('h3', pick.name, 'why-head'));
  body.append(el('p', `${matchOf(pick)} match · rank ${pick.rank} · ${meta(pick)}`, 'why-sub'));

  const shared = sharedLabels(pick);
  const block = el('div', '', 'why-block');
  block.append(el('h4', 'Why it surfaced'));
  block.append(el('p', shared.length
    ? `It sits closest to ${pick.because}, sharing ${shared.join(', ').toLowerCase()}.`
    : `It sits closest to ${pick.because} on plot wording rather than on shared themes or genres.`));
  body.append(block);

  if (pick.keywords.length) {
    const words = el('div', '', 'why-block');
    words.append(el('h4', 'What its plot is about'));
    const tags = el('div', '', 'tags');
    for (const k of pick.keywords) tags.append(el('span', k, 'tag plain'));
    words.append(tags);
    body.append(words);
  }
  if (pick.summary) {
    const plot = el('div', '', 'why-block');
    plot.append(el('h4', 'Summary'), el('p', pick.summary));
    body.append(plot);
  }
  if (pick.penalised) {
    const down = el('div', '', 'why-block');
    down.append(el('h4', 'Held back'), el('p', `Docked ${pick.penalised} points for looking like shows you disliked.`));
    body.append(down);
  }
  const links = el('div', '', 'why-block');
  const site = el('a', 'Open on TVmaze ↗');
  site.href = pick.url; site.target = '_blank'; site.rel = 'noopener noreferrer';
  links.append(site);
  body.append(links);

  const jump = el('div', '', 'why-block');
  jump.append(button('See how it lines up with your taste →', 'link', () => {
    fitPick = pick.id;
    $('fit-pick').value = String(pick.id);
    $('why').close();
    show('taste');
  }));
  body.append(jump);
  $('why').showModal();
}

/* --------------------------------------------------------------- taste */
function renderTaste() {
  const themes = data.features.filter(f => f.group === 'themes').slice(0, 3);
  const genre = data.features.find(f => f.group === 'genres');
  const words = themes.map(f => short(f.name).toLowerCase());
  const phrase = words.length > 1 ? words.slice(0, -1).join(', ') + ' and ' + words.at(-1) : words[0];
  $('verdict').textContent = words.length
    ? `Your shows keep coming back to ${phrase}${genre ? `, mostly ${genre.name.toLowerCase()}` : ''}.`
    : 'Rate a few more shows and a pattern will show up here.';
  const [tn, tt] = data.breadth.themes, [gn, gt] = data.breadth.genres;
  $('context').textContent = [
    ...data.context.map(c => `${c.count} of ${c.of} ${c.label === 'format' ? '' : 'in '}${c.value}`.replace('  ', ' ')),
    `spanning ${tn} of ${tt} themes and ${gn} of ${gt} genres`,
  ].join(' · ');
  renderSignals();

  const select = $('fit-pick');
  select.replaceChildren();
  for (const p of data.picks) {
    const option = el('option', `${p.name}${p.year ? ` (${p.year})` : ''}`);
    option.value = p.id;
    select.append(option);
  }
  if (!data.picks.some(p => p.id === fitPick)) fitPick = data.picks[0]?.id ?? null;
  if (fitPick) select.value = fitPick;

  // "Also plot" lets you hold the pick against one show you already rated.
  const against = $('fit-vs');
  const previous = against.value;
  against.replaceChildren();
  const auto = el('option', 'Closest show in your list');
  auto.value = 'closest';
  const none = el('option', 'Nothing');
  none.value = 'none';
  against.append(auto, none);
  for (const s of data.liked) {
    const option = el('option', `${s.name}${s.year ? ` (${s.year})` : ''}`);
    option.value = s.id;
    against.append(option);
  }
  against.value = [...against.options].some(o => o.value === previous) ? previous : 'closest';

  if (tab === 'taste') renderFit();
}

function renderSignals() {
  const holder = $('signals');
  holder.replaceChildren();
  const shown = new Set();
  const unique = data.features.filter(f => {
    const label = short(f.name).toLowerCase();
    return shown.has(label) ? false : shown.add(label);
  });
  const rows = allSignals ? unique : unique.slice(0, 8);
  for (const f of rows) {
    const row = el('div', '', 'sig');
    row.append(el('span', short(f.name), 'sig-name'),
      el('span', f.lift ? `${f.lift}× typical` : '', 'sig-lift'));
    const track = el('div', '', 'track');
    const fill = el('i');
    fill.style.setProperty('--w', f.share + '%');
    track.append(fill);
    row.append(track);
    row.setAttribute('role', 'img');
    row.setAttribute('aria-label', `${short(f.name)}: in ${f.count} of your ${data.positive_count} liked shows${f.lift ? `, ${f.lift} times the catalog average` : ''}`);
    holder.append(row);
  }
  const more = $('more-signals');
  more.hidden = unique.length <= 8;
  more.textContent = allSignals ? 'Show the strongest 8' : `Show all ${unique.length} signals`;
  more.setAttribute('aria-expanded', String(allSignals));
}
$('more-signals').addEventListener('click', () => { allSignals = !allSignals; renderSignals(); });

function renderFit() {
  if (!data || !data.picks.length) return;
  const pick = data.picks.find(p => p.id === Number($('fit-pick').value)) || data.picks[0];
  fitPick = pick.id;
  $('fit-score').textContent = `${matchOf(pick)} match · rank ${pick.rank}`;

  const choice = $('fit-vs').value;
  const other = choice === 'none' ? null
    : choice === 'closest' ? data.liked.find(s => s.id === pick.because_id)
      : data.liked.find(s => s.id === Number(choice));

  const rows = fitRows(data.liked, pick, other, $('fit-kind').value, boot.themes, boot.genres);
  const spokes = chooseSpokes(rows, Number($('fit-count').value));
  drawFit($('fit'), $('fit-frame'), $('fit-key'), spokes,
    { you: 'your taste', them: pick.name, vs: other ? other.name : '' });

  $('fit-name').textContent = pick.name;
  $('fit-vs-legend').hidden = !other;
  $('fit-vs-name').textContent = other ? other.name : '';

  const names = list => list.map(s => short(s.name).toLowerCase()).join(', ');
  const strong = spokes.filter(s => s.them && s.you >= 45);
  const fresh = spokes.filter(s => s.them && s.you < 45);
  const absent = spokes.filter(s => !s.them && s.you >= 50);
  const withOther = other ? spokes.filter(s => s.them && s.vs === 100) : [];
  $('fit-note').textContent = [
    strong.length ? `Familiar ground: ${names(strong)}.` : '',
    fresh.length ? `New for you: ${names(fresh)}.` : '',
    absent.length ? `Missing your usual ${names(absent)}.` : '',
    other ? (withOther.length
      ? `Shares ${names(withOther)} with ${other.name}.`
      : `Shares no plotted signal with ${other.name}.`) : '',
  ].filter(Boolean).join(' ') || 'This pick matches on plot wording rather than on recorded themes or genres.';

  renderRelate(pick);
}

// One bar per show you rated: how close the pick sits to each of them.
function renderRelate(pick) {
  const pairs = data.liked
    .map((s, i) => ({ ...s, score: pick.links[i] }))
    .sort((a, b) => b.score - a.score);
  const top = pairs[0]?.score || 1;
  $('relate-note').textContent = pairs.length > 1
    ? `${pick.name} is closest to ${pairs[0].name} and furthest from ${pairs.at(-1).name}.`
    : `${pick.name} against the one show you have rated.`;
  const holder = $('relate');
  holder.replaceChildren();
  const rows = allRelated ? pairs : pairs.slice(0, 10);
  for (const s of rows) {
    const row = el('div', '', 'sig rel');
    row.append(el('span', s.name, 'sig-name'), el('span', s.score.toFixed(0), 'sig-lift'));
    const track = el('div', '', 'track');
    const fill = el('i');
    fill.style.setProperty('--w', Math.max(2, s.score / top * 100) + '%');
    if (s.id === pick.because_id) fill.classList.add('lead');
    track.append(fill);
    row.append(track);
    row.setAttribute('role', 'img');
    row.setAttribute('aria-label', `${s.name}: similarity ${s.score.toFixed(0)} out of 100`);
    holder.append(row);
  }
  const more = $('more-relate');
  more.hidden = pairs.length <= 10;
  more.textContent = allRelated ? 'Show the closest 10' : `Show all ${pairs.length} shows`;
  more.setAttribute('aria-expanded', String(allRelated));
}
$('more-relate').addEventListener('click', () => { allRelated = !allRelated; renderFit(); });
$('fit-pick').addEventListener('change', renderFit);
for (const id of ['fit-kind', 'fit-count', 'fit-vs']) $(id).addEventListener('change', renderFit);
let fitWidth = 0;
new ResizeObserver(() => {
  const w = $('fit-frame').clientWidth;
  if (w && w !== fitWidth) { fitWidth = w; if (tab === 'taste') renderFit(); }
}).observe($('fit-frame'));

/* ---------------------------------------------------------- your shows */
function renderList() {
  const holder = $('list');
  holder.replaceChildren();
  const liked = state.profile.filter(p => p.weight > 0).length;
  $('shows-meta').textContent = state.profile.length
    ? `${state.profile.length} rated · ${liked} counted as liked. Ratings shape every pick; nothing you rate is recommended back.`
    : 'Nothing here yet. Search at the top to add what you have watched.';
  $('clear-all').hidden = !state.profile.length;
  for (const p of state.profile) {
    const item = el('div', '', 'item');
    const top = el('div', '', 'item-top');
    top.append(el('span', p.name, 'item-name'), button('Remove', 'drop-show', () => remove(p.id)));
    item.append(top, el('p', meta(p), 'item-meta'));
    const seg = el('div', '', 'seg');
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', `Your rating for ${p.name}`);
    for (const [weight, label] of RATINGS) {
      const b = button(label, '', () => rate(p.id, weight));
      b.setAttribute('aria-pressed', String(p.weight === weight));
      b.setAttribute('aria-label', SPOKEN[weight]);
      seg.append(b);
    }
    item.append(seg);
    holder.append(item);
  }
}
$('clear-all').addEventListener('click', () => {
  state.profile = [];
  save(); renderList(); renderPicks(); run(0);
});

/* ---------------------------------------------------------------- tune */
// Format is a fixed grouping of the catalogue's 11 television types; the rest are
// filled from the snapshot.
for (const [id, key, values, any] of [['lang', 'language', boot.meta.language, 'Any language'],
                                      ['stat', 'status', boot.meta.status, 'Any status']]) {
  const select = $(id);
  const option = el('option', any);
  option.value = 'all';
  select.append(option);
  for (const value of values) {
    const item = el('option', value);
    item.value = value;
    select.append(item);
  }
}
for (const [id, key] of [['lang', 'language'], ['kind', 'type'], ['stat', 'status']]) {
  $(id).addEventListener('change', () => { state.settings[key] = $(id).value; save(); run(); });
}
$('year').addEventListener('change', () => { state.settings.year_min = Number($('year').value); save(); run(); });
$('known').addEventListener('change', () => { state.settings.known_min = Number($('known').value); save(); run(); });
$('avoid').addEventListener('input', () => {
  state.settings.dislike = Number($('avoid').value);
  $('avoid-out').value = Math.round(state.settings.dislike * 100) + '%';
  save(); run();
});
for (const b of document.querySelectorAll('[data-focus]')) {
  b.addEventListener('click', () => {
    Object.assign(state.settings, FOCUS[b.dataset.focus]);
    syncTune(); save(); run();
  });
}
$('reset').addEventListener('click', () => { state.settings = { ...DEFAULTS }; syncTune(); save(); run(); });

function syncTune() {
  const s = state.settings;
  const focus = Object.entries(FOCUS).find(([, v]) => v.text === s.text && v.themes === s.themes && v.genres === s.genres)?.[0];
  for (const b of document.querySelectorAll('[data-focus]')) b.setAttribute('aria-pressed', String(b.dataset.focus === focus));
  $('known').value = s.known_min;
  $('year').value = [1900, 1990, 2000, 2010, 2018].includes(s.year_min) ? s.year_min : 1900;
  $('lang').value = s.language; $('kind').value = s.type; $('stat').value = s.status;
  $('avoid').value = s.dislike;
  $('avoid-out').value = Math.round(s.dislike * 100) + '%';
  $('avoid-row').hidden = !state.profile.some(p => p.weight < 0);
}

/* ---------------------------------------------------------------- start */
renderPicks();
renderList();
renderSaved();
syncTune();
show('next');
run(0);
