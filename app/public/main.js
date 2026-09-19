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
const DEFAULTS = {
  text: 40, themes: 35, genres: 25, closest: .3, dislike: .35,
  language: 'all', type: 'all', status: 'all', year_min: 1990, runtime_min: 0, rating_min: 6.5,
};
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

let state = { profile: [], settings: { ...DEFAULTS } };
let data = null, tab = 'next', reqId = 0, reqAbort = null, timer = null;
let searchId = 0, searchAbort = null, searchTimer = null, fitPick = null;

/* ------------------------------------------------------------- storage */
try {
  const saved = JSON.parse(localStorage.getItem(KEY));
  if (saved && Array.isArray(saved.profile)) {
    state = {
      profile: saved.profile.filter(p => Number.isInteger(p.id) && RATINGS.some(([w]) => w === p.weight)).slice(0, 60),
      settings: { ...DEFAULTS, ...(saved.settings || {}) },
    };
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
  document.documentElement.scrollTop = document.body.scrollTop = 0;
}
const TABS = ['next', 'taste', 'shows'];
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
}

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
    acts.append(
      button('Why this?', 'why', () => openWhy(pick)),
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
  $('context').textContent = data.context
    .map(c => `${c.count} of ${c.of} ${c.label === 'format' ? '' : 'in '}${c.value}`.replace('  ', ' '))
    .join(' · ');

  const holder = $('signals');
  holder.replaceChildren();
  const shown = new Set();
  const top = data.features.filter(f => {
    const label = short(f.name).toLowerCase();
    return shown.has(label) ? false : shown.add(label);
  }).slice(0, 8);
  for (const f of top) {
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

  const select = $('fit-pick');
  select.replaceChildren();
  for (const p of data.picks) {
    const option = el('option', `${p.name}${p.year ? ` (${p.year})` : ''}`);
    option.value = p.id;
    select.append(option);
  }
  if (!data.picks.some(p => p.id === fitPick)) fitPick = data.picks[0]?.id ?? null;
  if (fitPick) select.value = fitPick;
  if (tab === 'taste') renderFit();
}

function renderFit() {
  if (!data || !data.picks.length) return;
  const pick = data.picks.find(p => p.id === Number($('fit-pick').value)) || data.picks[0];
  fitPick = pick.id;
  const rows = fitRows(data.liked, pick, $('fit-kind').value, boot.themes, boot.genres);
  const spokes = chooseSpokes(rows);
  drawFit($('fit'), $('fit-frame'), $('fit-key'), spokes);
  $('fit-name').textContent = pick.name;
  const names = list => list.map(s => short(s.name).toLowerCase()).join(', ');
  const strong = spokes.filter(s => s.them && s.you >= 45);
  const fresh = spokes.filter(s => s.them && s.you < 45);
  const absent = spokes.filter(s => !s.them && s.you >= 50);
  $('fit-note').textContent = [
    strong.length ? `Familiar ground: ${names(strong)}.` : '',
    fresh.length ? `New for you: ${names(fresh)}.` : '',
    absent.length ? `Missing your usual ${names(absent)}.` : '',
  ].filter(Boolean).join(' ') || 'This pick matches on plot wording rather than on recorded themes or genres.';
}
$('fit-pick').addEventListener('change', renderFit);
$('fit-kind').addEventListener('change', renderFit);
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
for (const [id, key, values] of [['lang', 'language', boot.meta.language], ['kind', 'type', boot.meta.type], ['stat', 'status', boot.meta.status]]) {
  const select = $(id);
  const labels = { language: 'Any language', type: 'Any format', status: 'Any status' };
  const any = el('option', labels[key]);
  any.value = 'all';
  select.append(any);
  for (const value of values) {
    const option = el('option', value);
    option.value = value;
    select.append(option);
  }
  select.addEventListener('change', () => { state.settings[key] = select.value; save(); run(); });
}
$('year').addEventListener('change', () => { state.settings.year_min = Number($('year').value); save(); run(); });
$('quality').addEventListener('change', () => { state.settings.rating_min = $('quality').checked ? 6.5 : 0; save(); run(); });
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
  $('quality').checked = s.rating_min > 0;
  $('year').value = [1900, 1990, 2000, 2010, 2018].includes(s.year_min) ? s.year_min : 1900;
  $('lang').value = s.language; $('kind').value = s.type; $('stat').value = s.status;
  $('avoid').value = s.dislike;
  $('avoid-out').value = Math.round(s.dislike * 100) + '%';
  $('avoid-row').hidden = !state.profile.some(p => p.weight < 0);
}

/* ---------------------------------------------------------------- start */
renderPicks();
renderList();
syncTune();
show('next');
run(0);
