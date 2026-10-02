import assert from 'node:assert/strict';
import { comparisonText, mountTaste, normalizeTaste, percent, profileKey, radarPoints } from '../client/taste.js';

const dimension = (label, liked, catalog) => ({ key: label, label, liked, catalog, liked_count: 2, catalog_count: 20 });
const picture = (label = 'Crime') => ({ version: 1, context: 'context', date: '2026-10-03',
  counts: { rated: 5, liked: 4, disliked: 1, neutral: 0, loved: 2, good: 2, okay: 0 },
  reference: { shows: 100, minimum_known: 40 },
  genres: { available: 2, coverage: { liked_count: 4, catalog_count: 100 },
    dimensions: [dimension(label, .7, .2), dimension('Drama', .4, .5)] },
  themes: { available: 4, coverage: { liked_count: 3, catalog_count: 80 },
    dimensions: ['Crime / police', 'Family', 'Politics', 'Mystery'].map((name, index) => dimension(name, .5 - index * .1, .2)) },
  taste: { leans: [{ family: 'genre', label, shows: 2, share: 70, base: 20 }],
    avoids: [{ family: 'format', label: 'Reality', why: 'disliked', shows: 2 },
      { family: 'language', label: 'French', why: 'never', shows: 0 }] },
  interests: [{ size: 3, leans: ['Crime'], names: ['PRIVATE SHOW NAME'] }, { size: 2, leans: ['Comedy'] }],
  model: { omitted: 1, interests_omitted: 0 } });

let checks = 0;
async function check(run) { await run(); checks++; }
await check(() => {
  const first = [{ id: 2, weight: .7, name: 'Metadata' }, { id: 1, weight: 1 }];
  assert.equal(profileKey(first, 'alice', { b: 2, a: 1 }), profileKey(first.map(({id,weight})=>({id,weight})), 'alice', { a: 1, b: 2 }));
  assert.notEqual(profileKey(first, 'alice'), profileKey([...first].reverse(), 'alice'), 'Rating order changes recommendation focus.');
  assert.notEqual(profileKey(first, 'alice'), profileKey(first, 'bob'));
  assert.notEqual(profileKey(first, 'alice', { known_min: 85 }), profileKey(first, 'alice', { known_min: 0 }));
  assert.notEqual(profileKey(first, 'alice'), profileKey([{ id: 1, weight: -1 }, first[0]], 'alice'));
});
await check(() => {
  const raw = picture(); raw.genres.dimensions[0].liked = 0; raw.themes.dimensions[0].liked = null;
  const value = normalizeTaste(raw);
  assert.equal(value.genres.available, true, 'Backend available is a dimension count, rather than a boolean.');
  assert.equal(value.genres.dimensions[0].liked, 0);
  assert.equal(value.themes.dimensions[0].liked, null);
  assert.equal(percent(0), '0%'); assert.equal(percent(.375), '37.5%'); assert.equal(percent(null), 'Not available');
});
await check(() => {
  assert.throws(() => normalizeTaste({ ...picture(), version: 2 }), /incomplete/);
  const badShare = picture(); badShare.genres.dimensions[0].liked = 70;
  assert.throws(() => normalizeTaste(badShare), /invalid values/);
  const missingCount = picture(); delete missingCount.counts.liked;
  assert.throws(() => normalizeTaste(missingCount), /counts/);
  const unknownAvoidance = picture(); unknownAvoidance.taste.avoids.push({ family: 'genre', label: 'Horror', why: 'inferred', shows: 0 });
  assert.equal(normalizeTaste(unknownAvoidance).taste.avoids.length, 2);
  const descriptive = picture(); descriptive.taste.leans.push({ family: 'theme', label: 'Mystery', shows: 3, share: 60, base: 20 });
  assert.equal(normalizeTaste(descriptive).taste.leans.length, 1, 'Descriptive themes are not presented as recommendation adjustments.');
});
await check(() => {
  assert.match(comparisonText(dimension('Crime', .7, .2)), /more often/);
  assert.match(comparisonText(dimension('Crime', .1, .2)), /less often/);
  assert.match(comparisonText(dimension('Crime', .202, .2)), /about as often/);
  assert.match(comparisonText(dimension('Crime', null, .2)), /not enough known data/);
  assert.equal(radarPoints([null, .5, .2]), '');
  assert.equal(radarPoints([.5, .2]), '');
  assert.equal(radarPoints([0, 0, 0]), '260.00,210.00 260.00,210.00 260.00,210.00');
  assert.equal(radarPoints([1, 1, 1]).split(' ').length, 3, 'Multiple labels do not need shares summing to 100%.');
});

// A small DOM surface checks lifecycle and semantics without adding a runtime
// dependency. Actual SVG layout and touch typography are verified in a browser.
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.attributes = new Map(); this.listeners = new Map(); this.className = ''; this.value = ''; this.hidden = false; }
  classList = { add: name => { this.className += ` ${name}`; } };
  set textContent(value) { this.value = String(value); this.children = []; }
  get textContent() { return this.value + this.children.map(child => child.textContent).join(''); }
  style = {};
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.value = ''; this.children = children; }
  addEventListener(name, action) { this.listeners.set(name, [...(this.listeners.get(name) || []), action]); }
  removeEventListener(name, action) { this.listeners.set(name, (this.listeners.get(name) || []).filter(item => item !== action)); }
  emit(name, values = {}) { for (const action of this.listeners.get(name) || []) action({ target: this, preventDefault() {}, ...values }); }
  focus() { document.activeElement = this; }
}
const walk = element => [element, ...element.children.flatMap(walk)];
const role = (body, value) => walk(body).filter(element => element.getAttribute('role') === value);
globalThis.document = { createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
  createTextNode: value => { const element = new Element('text'); element.textContent = value; return element; } };
function fixture(request) {
  const dialog = new Element('dialog'), body = new Element('div');
  dialog.open = false; dialog.showModal = () => { dialog.open = true; }; dialog.close = () => { dialog.open = false; dialog.emit('close'); };
  let profile = [{ id: 1, weight: 1 }], owner = 'alice', settings = { known_min: 85 };
  const mounted = mountTaste({ dialog, body, getProfile: () => profile, getOwner: () => owner, getSettings: () => settings, request });
  return { mounted, dialog, body, profile: next => { profile = next; }, owner: next => { owner = next; }, settings: next => { settings = next; } };
}
await check(async () => {
  let requests = 0;
  const view = fixture(async () => { requests++; return picture(); });
  try {
    await view.mounted.open();
    const tabs = role(view.body, 'tab'); assert.equal(tabs.length, 3);
    assert.equal(role(view.body, 'tabpanel').filter(panel => !panel.hidden).length, 1);
    tabs[0].emit('keydown', { key: 'ArrowRight' });
    assert.equal(tabs[1].getAttribute('aria-selected'), 'true'); assert.equal(document.activeElement, tabs[1]);
    tabs[1].emit('keydown', { key: 'End' }); assert.equal(tabs[2].getAttribute('aria-selected'), 'true');
    assert.match(view.body.textContent, /Not yet in your likes/);
    assert.doesNotMatch(view.body.textContent, /PRIVATE SHOW NAME/);
    assert.equal(walk(view.body).filter(element => element.tagName === 'SVG').length, 1);
    assert.equal(walk(view.body).filter(element => element.tagName === 'TABLE').length, 1);
    await view.mounted.refresh();
    assert.equal(requests, 1); assert.equal(document.activeElement, tabs[2], 'Unchanged account status does not replace focused tabs.');
  } finally { view.mounted.destroy(); }
});
await check(async () => {
  const raw = picture(); raw.taste = { leans: [], avoids: [] }; raw.interests = [];
  const view = fixture(async () => raw);
  try { await view.mounted.open(); assert.equal(role(view.body, 'tab').length, 2); }
  finally { view.mounted.destroy(); }
});
await check(async () => {
  const arrivals = [];
  const view = fixture((path, body, signal) => new Promise(resolve => { arrivals.push({ path, body, signal, resolve }); }));
  try {
    const old = view.mounted.open(); assert.equal(arrivals[0].path, '/api/taste');
    view.owner('bob'); const current = view.mounted.refresh();
    assert.equal(arrivals[0].signal.aborted, true);
    arrivals[1].resolve(picture('Comedy')); await current;
    arrivals[0].resolve(picture('STALE ACCOUNT')); await old;
    assert.match(view.body.textContent, /Comedy/); assert.doesNotMatch(view.body.textContent, /STALE ACCOUNT/);
    view.settings({ known_min: 0 }); const changed = view.mounted.refresh();
    assert.equal(arrivals[2].body.settings.known_min, 0); assert.doesNotMatch(view.body.textContent, /Comedy/);
    view.mounted.close(); assert.equal(arrivals[2].signal.aborted, true);
    arrivals[2].resolve(picture('CLOSED RESPONSE')); await changed;
    assert.doesNotMatch(view.body.textContent, /CLOSED RESPONSE/);
  } finally { view.mounted.destroy(); }
});
await check(async () => {
  let fail = true;
  const view = fixture(async () => { if (fail) throw new Error('Offline'); return picture(); });
  try {
    await view.mounted.open(); assert.match(view.body.textContent, /could not load/);
    fail = false; await view.mounted.refresh(true); assert.equal(role(view.body, 'tab').length, 3);
    view.profile([]); await view.mounted.refresh(); assert.match(view.body.textContent, /starts with your ratings/);
    assert.equal(role(view.body, 'tab').length, 0);
  } finally { view.mounted.destroy(); }
});
delete globalThis.document;
console.log(`All ${checks} taste checks passed (values, chart semantics, keyboard tabs and request ownership).`);
