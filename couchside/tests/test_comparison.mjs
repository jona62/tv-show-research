import assert from 'node:assert/strict';
import test from 'node:test';
import { comparisonStateURL, comparisonURL, createComparisonLoader, freezeComparison, moveComparison, parseComparison, validateComparison } from '../client/compare.js';
import { compareMatrix, detailMatrix, episodeCode, ratingTableHTML, seasonCode, seasonName } from '../client/rating-views.js';

const episode = (season, number, rating, id = season * 100 + number) => ({ id, season, number, rating, name: `Episode ${number}` });
const show = (id, episodes) => ({ id, name: `Show ${id}`, poster: `https://static.tvmaze.com/uploads/images/medium_portrait/0/${id}.jpg`, episodes, sources: 'TVmaze' });
const base = { kind: 'compare', mode: 'all', inverted: true, averages: true };
const state = { ids: [1, 2], mode: 'all', inverted: true, averages: true, seasons: { 1: 2, 2: 1 } };
const settle = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test('season labels retain year-valued seasons and inversion preserves every position', () => {
  assert.equal(seasonName(1999), '1999 season'); assert.equal(seasonCode(1999), '1999');
  assert.equal(episodeCode(episode(1999, 52, 8)), '1999 E52');
  const episodes = [episode(1, 1, 7), episode(1, 3, 9), episode(2, 1, null)];
  const row = detailMatrix({ episodes, inverted: false, averages: true });
  const column = detailMatrix({ episodes, inverted: true, averages: true });
  assert.equal(row.rows[0].cells[1], null, 'a missing episode is empty, rather than shifted left');
  assert.equal(column.rows[1].cells[0], null, 'the transposed missing episode stays empty');
  for (let season = 0; season < 2; season++) for (let number = 0; number < 3; number++) {
    assert.deepEqual(row.rows[season].cells[number], column.rows[number].cells[season]);
  }
  assert.equal(row.rows[0].cells[3].rating, 8);
  assert.equal(column.rows[3].cells[1].rating, null, 'an unrated season has no invented mean');
  assert.equal(row.rows[0].cells[3].plain, true);
});

test('comparison distinguishes missing seasons, unrated episodes, and weighted overall averages', () => {
  const a = show(1, [episode(1, 1, 10), episode(2, 1, 6), episode(2, 2, 6), episode(2, 3, null)]);
  const b = show(2, [episode(1, 1, null)]);
  const matrix = compareMatrix({ ...base, shows: [a, b] });
  assert.deepEqual(matrix.headers.map(header => header.label), ['Show 1', 'Show 2']);
  assert.equal(matrix.rows[0].cells[0].rating, 10);
  assert.equal(matrix.rows[1].cells[0].rating, 6);
  assert.equal(matrix.rows[1].cells[0].count, 3); assert.equal(matrix.rows[1].cells[0].ratedCount, 2);
  assert.equal(matrix.rows[0].cells[1].rating, null, 'the episode exists but is unrated');
  assert.equal(matrix.rows[1].cells[1], null, 'a nonexistent season remains absent');
  assert.equal(matrix.rows.at(-1).cells[0].rating, 22 / 3, 'three rated episodes weigh equally; seasons do not');
  assert.equal(matrix.rows.at(-1).cells[0].plain, true);
  assert.equal(matrix.rows.at(-1).cells[1].rating, null);
  const transposed = compareMatrix({ ...base, inverted: false, shows: [a, b] });
  assert.deepEqual(transposed.rows[0].cells[1], matrix.rows[1].cells[0]);
  assert.equal(compareMatrix({ ...base, averages: false, shows: [a, b] }).rows.length, 2);
});

test('a single-season comparison uses each show’s independent season and freezes export data', () => {
  const a = show(1, [episode(1, 1, 4), episode(2, 1, 9), episode(2, 3, 8)]);
  const b = show(2, [episode(1, 1, 6), episode(1, 2, null)]);
  const entries = new Map([[1, { show: a }], [2, { show: b }]]);
  const model = freezeComparison({ ...state, mode: 'single' }, entries), matrix = compareMatrix(model);
  assert.deepEqual(model.shows[0].episodes.map(item => item.season), [2, 2]);
  assert.deepEqual(model.shows[1].episodes.map(item => item.season), [1, 1]);
  assert.equal(matrix.headers[0].sub, 'Season 2'); assert.equal(matrix.headers[1].sub, 'Season 1');
  assert.equal(matrix.rows[0].cells[0].rating, 9); assert.equal(matrix.rows[0].cells[1].rating, 6);
  assert.equal(matrix.rows[1].cells[0], null); assert.equal(matrix.rows[1].cells[1].rating, null);
  a.episodes[1].rating = 1; a.name = 'Changed'; state.ids.reverse();
  assert.equal(model.shows[0].episodes[0].rating, 9); assert.equal(model.shows[0].name, 'Show 1');
  assert.deepEqual(model.shows.map(item => item.id), [1, 2]); state.ids.reverse();
});

test('table headings and descriptions escape content and detail averages do not become buttons', () => {
  const matrix = detailMatrix({ episodes: [{ ...episode(1, 1, 8), name: '<script>"bad"</script>' }], inverted: false, averages: true });
  const markup = ratingTableHTML(matrix);
  assert.match(markup, /scope="row"/); assert.match(markup, /scope="col"/);
  assert.match(markup, /&lt;script&gt;&quot;bad&quot;&lt;\/script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
  assert.equal((markup.match(/<button/g) || []).length, 1, 'only the episode cell can receive focus');
  assert.match(markup, /class="ratings-average"/);
});

test('a show with no episodes has a clear single-season subtitle in both orientations', () => {
  const empty = show(1, []), entries = new Map([[1, { show: empty }]]);
  const model = freezeComparison({ ids: [1], mode: 'single', inverted: true, averages: true, seasons: {} }, entries);
  assert.equal(Object.hasOwn(model.shows[0], 'season'), false);
  assert.equal(compareMatrix(model).headers[0].sub, 'No episodes yet');
  assert.equal(compareMatrix({ ...model, inverted: false }).rows[0].sub, 'No episodes yet');
  assert.doesNotMatch(ratingTableHTML(compareMatrix(model)), /Season undefined/);
});

test('shared URLs round-trip order and settings while rejecting malformed or excessive stored data', () => {
  const original = { ids: [169, 16149], mode: 'single', inverted: false, averages: false, seasons: { 169: 4, 16149: 2 } };
  assert.deepEqual(parseComparison(comparisonStateURL(original).split('?')[1]), original);
  assert.deepEqual(parseComparison('?compare=2,2,-1,0,foo,1&mode=wrong&seasons=2:1999,1:0,99:5,2:4:5'),
    { ids: [2, 1], mode: 'all', inverted: true, averages: true, seasons: { 2: 1999 } });
  assert.deepEqual(validateComparison(null), { ids: [], mode: 'all', inverted: true, averages: true, seasons: {} });
  const many = validateComparison({ ids: [1, 1, '2', -4, ...Array.from({ length: 60 }, (_, index) => index + 3)], inverted: 'false', averages: 0, seasons: { 1: 2, 3: '4', 999: 1 } });
  assert.equal(many.ids.length, 40); assert.equal(new Set(many.ids).size, 40); assert.equal(many.inverted, true);
  assert.deepEqual(many.seasons, { 1: 2 });
  assert.deepEqual(parseComparison('?compare=', original).ids, [], 'an explicitly empty URL clears a previous comparison');
});

test('adding from a title preserves comparison settings without adding a duplicate or touching account lists', () => {
  const writes = [], original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => JSON.stringify(state), setItem: (key, value) => writes.push([key, value]) } });
  try {
    const duplicated = parseComparison(comparisonURL(1).split('?')[1]);
    assert.deepEqual(duplicated.ids, [1, 2]); assert.equal(duplicated.seasons[1], 2);
    assert.deepEqual(parseComparison(comparisonURL(3).split('?')[1]).ids, [1, 2, 3]);
    assert.deepEqual(parseComparison(comparisonURL(9, '?compare=8&mode=single&compare-inverted=0').split('?')[1]).ids, [8, 9]);
    assert.ok(writes.every(([key]) => key === 'couchside.comparison-v1'));
  } finally { if (original) Object.defineProperty(globalThis, 'localStorage', original); else delete globalThis.localStorage; }
});

test('reordering preserves unique IDs and clamps keyboard moves at the edges', () => {
  const ids = [1, 2, 3, 4];
  assert.deepEqual(moveComparison(ids, 1, 3), [2, 3, 4, 1]);
  assert.deepEqual(moveComparison(ids, 4, -1), [4, 1, 2, 3]);
  assert.deepEqual(moveComparison(ids, 1, -1), ids); assert.deepEqual(moveComparison(ids, 2, 50), [1, 3, 4, 2]);
  assert.deepEqual(moveComparison(ids, 999, 0), ids); assert.deepEqual(ids, [1, 2, 3, 4]);
});

test('adding beyond the comparison cap reports the limit while an existing show remains usable', () => {
  const ids = Array.from({ length: 40 }, (_, index) => index + 1), query = `?compare=${ids.join(',')}`;
  assert.throws(() => comparisonURL(41, query), /Compare up to 40 shows.*Remove one/);
  assert.deepEqual(parseComparison(comparisonURL(1, query).split('?')[1]).ids, ids);
});

test('a removed show’s late answer cannot replace a newer request or resurrect a disposed comparison', async () => {
  const old = deferred(), newer = deferred(); let calls = 0, changed = 0;
  const loader = createComparisonLoader({ loadRatings: () => (++calls === 1 ? old.promise : newer.promise),
    metadata: async id => show(id, []), changed: () => changed++ });
  loader.ensure(1); loader.ensure(1); assert.equal(calls, 1, 'concurrent requests share a pending slot');
  loader.remove(1); loader.ensure(1); newer.resolve(show(1, [episode(1, 1, 9)])); await settle();
  assert.equal(loader.entries.get(1).show.episodes[0].rating, 9);
  old.resolve(show(1, [episode(1, 1, 1)])); await settle();
  assert.equal(loader.entries.get(1).show.episodes[0].rating, 9, 'the old generation cannot overwrite its replacement');
  const pending = deferred(), other = createComparisonLoader({ loadRatings: () => pending.promise, metadata: async id => show(id, []), changed: () => changed++ });
  other.ensure(2); other.dispose(); const before = changed;
  pending.resolve(show(2, [episode(1, 1, 7)])); await settle();
  assert.equal(other.entries.size, 0); assert.equal(changed, before, 'unmounted comparisons stop notifying'); loader.dispose();
});

test('failed loads can retry and exports use the original full portrait', async () => {
  let calls = 0;
  const loader = createComparisonLoader({ loadRatings: async () => { if (++calls === 1) throw Error('Offline'); return show(1, [episode(1, 1, 8)]); }, metadata: async id => show(id, []) });
  loader.ensure(1); await settle(); assert.equal(loader.entries.get(1).status, 'error');
  assert.equal(loader.entries.get(1).error, 'Offline');
  loader.ensure(1, true); await settle(); assert.equal(loader.entries.get(1).status, 'ready');
  assert.equal(loader.entries.get(1).show.art, 'https://static.tvmaze.com/uploads/images/original_untouched/0/1.jpg');
  loader.dispose();
});
