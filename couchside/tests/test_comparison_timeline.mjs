import assert from 'node:assert/strict';
import test from 'node:test';
import { comparisonOverlayHTML, comparisonOverlayPlan, comparisonShowColour } from '../client/comparison-timeline.js';
import { band } from '../client/ratings.js';

const episode = (id, rating, number = id, season = 1) => ({ id, rating, number, season, name: `Episode ${id}` });
const show = (id, episodes) => ({ id, name: `Show ${id}`, year: 2025, season: 1, episodes });
const model = (shows, averages = true) => ({ mode: 'all', averages, shows });
const colourChannels = colour => [1, 3, 5].map(offset => parseInt(colour.slice(offset, offset + 2), 16));
const luminance = colour => colourChannels(colour).map(value => {
  value /= 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
}).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);

test('overlay aligns episode positions, retains complete sequences, and never stretches a shorter show', () => {
  const short = show(16149, [episode(1, 6), episode(2, null), episode(3, 9, 1, 2)]);
  const long = show(1505, Array.from({ length: 1181 }, (_, index) => episode(index + 10, 6, index + 1)));
  const input = model([short, long]), original = structuredClone(input);
  const plan = comparisonOverlayPlan(input, 390);
  assert.equal(plan.low, 5.75); assert.equal(plan.maxCount, 1181); assert.equal(plan.width, 1244);
  assert.equal(plan.spacing, 1); assert.ok(plan.width > plan.viewport);
  assert.deepEqual(plan.series.map(series => series.show.id), [16149, 1505]);
  assert.equal(plan.series[0].points.length, 3, 'All seasons uses every episode, not season means');
  assert.equal(plan.series[1].points.length, 1181);
  assert.equal(plan.series[0].points[0].x, 20);
  assert.equal(plan.series[1].points[0].x, 20);
  assert.equal(plan.series[0].points[2].x, plan.series[1].points[2].x);
  assert.ok(plan.series[0].points.at(-1).x < plan.series[1].points.at(-1).x);
  assert.equal(plan.series[0].points[0].y, plan.series[1].points[0].y, 'Equal scores share a y coordinate');
  assert.equal(plan.series[0].points[1].y, null); assert.equal(plan.series[0].points[1].episodeIndex, 2);
  assert.deepEqual(plan.series[0].runs[0].map(point => point.sampleIndex), [0, 2], 'Known ratings connect across null positions');
  assert.deepEqual(input, original, 'Frozen captures are not mutated');
});

test('five-episode means keep their full-data season and gap boundaries while both lines connect', () => {
  const episodes = [episode(1, 6, 1), episode(2, 8, 2), episode(3, 10, 3), episode(4, 4, 4),
    episode(5, 9, 5), episode(6, null, 6), episode(7, 2, 7), episode(8, 9, 1, 2),
    episode(9, 7, 2, 2), episode(10, 3, 4, 2)];
  const series = comparisonOverlayPlan(model([show(1, episodes)])).series[0];
  assert.equal(series.runs.length, 1); assert.equal(series.trend.length, 1);
  assert.deepEqual(series.trendRuns.map(run => run.map(point => point.id)), [[1, 2, 3, 4, 5], [7], [8, 9], [10]]);
  assert.deepEqual(series.trendPoints.map(point => point.rating), [8, 7, 7.4, 7.75, 23 / 3, 2, 8, 8, 3]);
  assert.deepEqual(series.trendPoints.map(point => point.sampleIndex), [0, 1, 2, 3, 4, 6, 7, 8, 9]);
  assert.ok(series.trendPoints.every(point => Number.isFinite(point.x) && Number.isFinite(point.y)));
  assert.equal(series.mean, 58 / 9, 'Overall mean weights rated episodes, excluding nulls');
});

test('different show floors still share raw and average coordinates for equal scores', () => {
  const a = show(1, [episode(1, 8)]);
  const b = show(2, [episode(2, 4, 1), episode(3, 8, 2), episode(4, null, 3), episode(5, 8, 4)]);
  const plan = comparisonOverlayPlan(model([a, b]));
  assert.equal(plan.low, 3.75);
  assert.equal(plan.series[0].points[0].y, plan.series[1].points[1].y);
  assert.equal(plan.series[0].trendPoints[0].y, plan.series[1].trendPoints.at(-1).y);
  assert.ok(plan.series.every(series => series.points.every(point => point.y == null || point.y >= 36 && point.y <= 244)));
  assert.ok(plan.series.every(series => series.trendPoints.every(point => point.y >= 338 && point.y <= 426)));
});

test('fallback colors distinguish shows without artwork and remain readable on the Couchside background', () => {
  const fixtures = [169, 16149, 30770, 43031, 1505].map(id => show(id, [episode(id, 6), episode(id + 1, 9, 2)]));
  const plan = comparisonOverlayPlan(model(fixtures)), reversed = comparisonOverlayPlan(model([...fixtures].reverse()));
  const colours = plan.series.map(series => series.colour);
  assert.equal(new Set(colours).size, 5);
  for (const series of plan.series) {
    assert.equal(reversed.series.find(item => item.show.id === series.show.id).colour, series.colour);
    assert.ok((luminance(series.colour) + .05) / (luminance('#181818') + .05) >= 3);
  }
  for (let first = 0; first < colours.length; first++) for (let second = first + 1; second < colours.length; second++) {
    const a = colourChannels(colours[first]), b = colourChannels(colours[second]);
    assert.ok(Math.hypot(...a.map((value, index) => value - b[index])) >= 42, 'Fallback lines must not collapse into nearly identical colors');
  }
  assert.equal(comparisonShowColour(901234), comparisonShowColour('901234'), 'Generic IDs also use stable identities');
  const catalogueColours = Array.from({ length: 40 }, (_, index) => comparisonShowColour(index + 1));
  assert.equal(new Set(catalogueColours).size, 40, 'A full comparison can distinguish its catalog identities');
  assert.ok(catalogueColours.every(colour => (luminance(colour) + .05) / (luminance('#181818') + .05) >= 3));
  const markup = comparisonOverlayHTML(model(fixtures));
  assert.equal((markup.match(/class="ratings-raw-line"/g) || []).length, 5);
  assert.equal((markup.match(/class="ratings-trend"/g) || []).length, 5);
  assert.equal((markup.match(/class="comparison-overlay-name"/g) || []).length, 5);
});

test('point styles preserve identity, accessible raw targets, and a distinct line-only average plot', () => {
  const input = model([{ ...show(169, [episode(1, 6), episode(2, 10)]), colour: '#ffb020' }]);
  const showDots = comparisonOverlayHTML(input), ratingDots = comparisonOverlayHTML(input, { pointStyle: 'rating' });
  const lines = comparisonOverlayHTML(input, { pointStyle: 'none' });
  assert.match(showDots, /class="ratings-point"[^>]*fill="#ffb020"/);
  assert.ok(ratingDots.includes(`fill="${band(6).colour}" stroke="#ffb020" style="stroke:#ffb020"`));
  assert.equal((lines.match(/class="ratings-point-hit"/g) || []).length, 2, 'Lines only remains keyboard and tap accessible');
  assert.equal((lines.match(/class="ratings-point comparison-overlay-point-hidden" opacity="0"/g) || []).length, 2);
  assert.match(lines, /data-show-id="169" data-plot="raw"/);
  const lower = lines.split('<g class="ratings-trend-plot">')[1];
  assert.match(lower, /data-show-id="169" data-plot="trend" aria-hidden="true"/);
  assert.doesNotMatch(lower, /tabindex="0"|ratings-point-hit|ratings-point"/);
  assert.match(showDots, /Show 169, position 1, S1 E1: Episode 1, 6\.0 out of 10/);
  assert.match(showDots, /Show 169, position 2, S1 E2: Episode 2, 10\.0 out of 10/);
  assert.match(showDots, /5-episode average/);
});

test('selected seasons remain independent and disabling averages preserves frozen trend data without rendering them', () => {
  const a = show(1, [episode(1, 6, 1, 2), episode(2, 10, 2, 2)]), b = show(2, [episode(3, 8, 1, 2024)]);
  a.season = 2; b.season = 2024;
  const input = { mode: 'single', averages: false, pointStyle: 'rating', shows: [a, b] };
  const plan = comparisonOverlayPlan(input);
  assert.equal(plan.height, 300); assert.equal(plan.showTrend, false);
  assert.deepEqual(plan.series[0].points.map(point => point.season), [2, 2]);
  assert.deepEqual(plan.series[1].points.map(point => point.season), [2024]);
  assert.deepEqual(plan.series[0].trendPoints.map(point => point.rating), [8, 8]);
  const markup = comparisonOverlayHTML(input);
  assert.match(markup, /Episode position within selected seasons/); assert.match(markup, /2024 E1/);
  assert.doesNotMatch(markup, /ratings-trend-plot|5-episode average|comparison-overlay-mean/);
  assert.ok(markup.includes(`fill="${band(6).colour}"`), 'The model point style applies when no argument overrides it');
});

test('responsive common axis labels fit, retain endpoints, and avoid collisions on long and short charts', () => {
  for (const availableWidth of [300, 390, 960]) for (const count of [1, 2, 12, 1181, 10000]) {
    const plan = comparisonOverlayPlan(model([show(1, Array.from({ length: count }, (_, index) => episode(index + 1, 6)))]), availableWidth);
    assert.equal(plan.axis.labels[0].text, 'E1');
    assert.equal(plan.axis.labels.at(-1).text, `E${count}`);
    assert.equal(plan.axis.episodeTicks.at(-1).episodeIndex, count);
    assert.ok(plan.axis.labels.every(label => label.left >= 4 && label.right <= plan.width - 4));
    for (let index = 1; index < plan.axis.labels.length; index++)
      assert.ok(plan.axis.labels[index].left >= plan.axis.labels[index - 1].right + 8);
  }
});

test('empty, unrated and one-episode captures stay truthful, finite, and escaped', () => {
  const empty = show(1, []), unrated = show(2, [episode(1, null)]);
  const plan = comparisonOverlayPlan(model([empty, unrated]));
  assert.equal(plan.maxCount, 1); assert.equal(plan.low, 0);
  assert.equal(plan.series[0].points.length, 0); assert.equal(plan.series[1].points[0].y, null);
  const emptyHTML = comparisonOverlayHTML(model([empty, unrated]));
  assert.match(emptyHTML, /These episodes have not been rated yet/);
  assert.doesNotMatch(emptyHTML, /ratings-raw-line|NaN|Infinity/);
  const one = show(3, [episode(8, 0)]); one.name = '<img src=x onerror="bad">';
  const singleton = comparisonOverlayPlan(model([one]));
  assert.equal(singleton.series[0].points[0].x, 20);
  assert.equal(singleton.series[0].points[0].y, 244);
  assert.equal(singleton.series[0].trendPoints[0].x, 20);
  const markup = comparisonOverlayHTML(model([one]), { pointStyle: 'none' });
  assert.match(markup, /&lt;img src=x onerror=&quot;bad&quot;&gt;/);
  assert.match(markup, /ratings-trend-single/); assert.match(markup, /comparison-overlay-point-hidden/);
  assert.doesNotMatch(markup, /NaN|Infinity/);
});

test('live fit uses a bounded SVG without changing the unzoomed snapshot plan', () => {
  const input = model([show(1, [episode(1, 6), episode(2, null), episode(3, 8)]),
    show(2, Array.from({ length: 1181 }, (_, index) => episode(index + 10, 6, index + 1)))]);
  const source = comparisonOverlayPlan(input, 390), preserved = structuredClone(source);
  assert.deepEqual(Object.keys(source), ['low', 'ticks', 'maxCount', 'count', 'width', 'viewport', 'spacing', 'height', 'showTrend', 'axis', 'series']);
  const live = comparisonOverlayPlan(input, 390, {}, source);
  assert.equal(source.width, 1244); assert.equal(source.spacing, 1);
  assert.equal(live.width, 344); assert.equal(live.viewport, 344);
  assert.equal(live.zoomX, 1); assert.equal(live.startIndex, 0); assert.equal(live.endIndex, 1180);
  assert.equal(live.baseLow, source.low); assert.deepEqual(live.ticks, source.ticks);
  assert.equal(live.series[0].points[0].x, 20); assert.equal(live.series[1].points.at(-1).x, 300);
  assert.equal(live.series[0].points[2].x, live.series[1].points[2].x);
  assert.ok(live.series[0].points.at(-1).x < live.series[1].points.at(-1).x);
  assert.deepEqual(source, preserved, 'Reprojection does not mutate the cached full plan');
  assert.deepEqual(comparisonOverlayPlan(input, 390), preserved, 'The export path still receives exactly the original shape and values');
});

test('fractional live pan retains ordinal slots, two boundary neighbours, and independently ending shows', () => {
  const a = show(1, Array.from({ length: 101 }, (_, index) => episode(index + 1, index === 42 ? null : 8, index + 1)));
  const b = show(2, Array.from({ length: 40 }, (_, index) => episode(index + 200, 8, index + 1)));
  const input = model([a, b]), source = comparisonOverlayPlan(input, 390);
  const live = comparisonOverlayPlan(input, 390, { zoomX: 10, startIndex: 37.5 }, source);
  assert.equal(live.span, 10); assert.equal(live.startIndex, 37.5); assert.equal(live.endIndex, 47.5);
  assert.equal(live.spacing, 28); assert.equal(live.width, 344);
  assert.deepEqual(live.series[0].points.map(point => point.sampleIndex), [38, 39, 40, 41, 42, 43, 44, 45, 46, 47]);
  assert.equal(live.series[0].points.find(point => point.sampleIndex === 42).y, null);
  assert.deepEqual(live.series[0].runs[0].map(point => point.sampleIndex), [36, 37, 38, 39, 40, 41, 43, 44, 45, 46, 47, 48, 49]);
  assert.deepEqual(live.series[1].points.map(point => point.sampleIndex), [38, 39]);
  assert.equal(live.series[1].points[0].x, live.series[0].points[0].x);
  assert.equal(live.series[1].points.at(-1).x, 62, 'The short series ends at its actual episode position');
  assert.equal(live.axis.labels[0].text, 'E39'); assert.equal(live.axis.labels.at(-1).text, 'E48');
  assert.ok(live.axis.episodeTicks.every(tick => tick.episodeIndex >= 39 && tick.episodeIndex <= 48));
});

test('cached live reprojecting preserves full-data means and avoids reading or averaging the shows again', () => {
  const input = model([show(1, [episode(1, 6), episode(2, 8), episode(3, 10), episode(4, 4),
    episode(5, 9), episode(6, null), episode(7, 2), episode(8, 9, 1, 2), episode(9, 7, 2, 2), episode(10, 3, 4, 2)])]);
  const source = comparisonOverlayPlan(input, 960), preserved = structuredClone(source);
  const cachedInput = { mode: 'all', averages: true };
  Object.defineProperty(cachedInput, 'shows', { get() { throw Error('A gesture must reuse its full-data source plan'); } });
  const live = comparisonOverlayPlan(cachedInput, 390, { zoomX: 3, startIndex: 3 }, source);
  const originalMeans = new Map(source.series[0].trendPoints.map(point => [point.id, point.rating]));
  for (const point of live.series[0].trend[0]) assert.equal(point.rating, originalMeans.get(point.id));
  assert.equal(live.series[0].mean, 58 / 9);
  assert.deepEqual(live.series[0].trendPoints.map(point => point.id), [4, 5, 7]);
  assert.deepEqual(source, preserved);
  const html = comparisonOverlayHTML(cachedInput, { availableWidth: 390, viewport: { zoomX: 3, startIndex: 3 }, sourcePlan: source });
  assert.match(html, /data-start-index="3" data-end-index="6" data-span="3" data-zoom-x="3"/);
});

test('rating zoom shares both panel domains, clips paths instead of flattening them, and excludes invisible targets', () => {
  const input = model([show(1, [episode(1, 4), episode(2, 8), episode(3, 10)]),
    show(2, [episode(11, 8), episode(12, 8), episode(13, 8)])]);
  const viewport = { low: 7, high: 9 }, plan = comparisonOverlayPlan(input, 390, viewport);
  assert.equal(plan.low, 7); assert.equal(plan.high, 9);
  assert.equal(plan.ticks[0], 7); assert.equal(plan.ticks.at(-1), 9);
  assert.equal(plan.series[0].points[1].y, 140); assert.equal(plan.series[1].points[0].y, 140);
  assert.equal(plan.series[1].trendPoints[0].y, 382);
  assert.equal((plan.raw.bottom - 140) / (plan.raw.bottom - plan.raw.top), (plan.trend.bottom - 382) / (plan.trend.bottom - plan.trend.top));
  assert.ok(plan.series[0].runs[0][0].y > plan.raw.bottom, 'Low real samples stay below the plot instead of forming a border plateau');
  assert.ok(plan.series[0].runs[0].at(-1).y < plan.raw.top, 'High real samples stay above the plot');
  const html = comparisonOverlayHTML(input, { availableWidth: 390, viewport });
  assert.match(html, /<rect x="0" y="36" width="344" height="208"/);
  assert.match(html, /<rect x="0" y="338" width="344" height="88"/);
  assert.match(html, /class="ratings-episode-plot" clip-path=/); assert.match(html, /class="ratings-trend-plot" clip-path=/);
  assert.match(html, /data-min="7" data-max="9"/); assert.match(html, /scale 7 to 9/);
  assert.doesNotMatch(html, /data-episode="1"|data-episode="3"/);
  assert.match(html, /data-episode="2"/);
  assert.match(html, /class="ratings-chart-axis" width="46"/);
  assert.match(html, /comparison-overlay-label">5-episode average within each season<\/p>/);
  assert.doesNotMatch(html, /5-episode average <span/);
});

test('cropped raw and trend curves retain real neighbours across season and unrated gaps', () => {
  const input = model([show(1, [episode(1, 6), episode(2, null), episode(3, 8), episode(4, null),
    episode(5, 7), episode(6, null), episode(7, 9, 1, 2), episode(8, null, 2, 2), episode(9, 5, 3, 2)])]);
  const source = comparisonOverlayPlan(input, 390), live = comparisonOverlayPlan(input, 390, { zoomX: 8, startIndex: 3.5 }, source);
  assert.deepEqual(live.series[0].points.map(point => point.id), [5]);
  assert.deepEqual(live.series[0].runs[0].map(point => point.id), [1, 3, 5, 7, 9]);
  assert.deepEqual(live.series[0].trend[0].map(point => point.id), [1, 3, 5, 7, 9]);
  for (const point of live.series[0].trend[0]) assert.equal(point.rating, source.series[0].trendPoints.find(original => original.id === point.id).rating);
  const html = comparisonOverlayHTML(input, { availableWidth: 390, viewport: { zoomX: 8, startIndex: 3.5 }, sourcePlan: source });
  assert.equal((html.match(/class="ratings-point-hit"/g) || []).length, 1);
  assert.doesNotMatch(html, /ratings-trend-single/, 'A cropped mean line does not gain a fabricated singleton marker');
});

test('live bounds stay finite, retain minimum spans, and never pan outside the complete selected scope', () => {
  const input = model([show(1, Array.from({ length: 101 }, (_, index) => episode(index + 1, 6)))]);
  const source = comparisonOverlayPlan(input, 390);
  for (const viewport of [{ zoomX: 0, startIndex: -3 }, { zoomX: 1e9, startIndex: 1e9, low: 10, high: 10 },
    { zoomX: NaN, startIndex: Infinity, low: Infinity, high: NaN }, { low: 9, high: 4 }, { low: -10, high: -3 }]) {
    const live = comparisonOverlayPlan(input, 390, viewport, source);
    assert.ok(live.zoomX >= 1 && live.zoomX <= 100); assert.ok(live.span >= 1);
    assert.ok(live.startIndex >= 0 && live.endIndex <= 100);
    assert.ok(live.low >= 0 && live.high <= 10 && live.high - live.low >= .5 - 1e-9);
    assert.ok([live.width, live.spacing, live.low, live.high, live.startIndex, live.endIndex].every(Number.isFinite));
    assert.ok(live.ticks.every((tick, index, ticks) => tick >= live.low && tick <= live.high && (!index || tick > ticks[index - 1])));
  }
  const maximum = comparisonOverlayPlan(input, 390, { zoomX: 1e9, startIndex: 1e9 }, source);
  assert.equal(maximum.zoomX, 100); assert.equal(maximum.span, 1); assert.equal(maximum.startIndex, 99); assert.equal(maximum.endIndex, 100);
  for (const episodes of [[], [episode(1, null)], [episode(1, 8)]]) {
    const tiny = model([show(1, episodes)]), plan = comparisonOverlayPlan(tiny, NaN, { zoomX: 10, startIndex: 100, low: 8, high: 8 });
    assert.equal(plan.zoomX, 1); assert.equal(plan.startIndex, 0); assert.equal(plan.span, 1);
    assert.ok(Number.isFinite(plan.spacing));
    assert.doesNotMatch(comparisonOverlayHTML(tiny, { availableWidth: NaN, viewport: { zoomX: 10, low: 8, high: 8 } }), /NaN|Infinity/);
  }
});

test('long live domains render bounded samples at deep zoom and use truthful collision-free visible ticks', () => {
  const input = model([show(1, Array.from({ length: 10000 }, (_, index) => episode(index + 1, 6)))]);
  const source = comparisonOverlayPlan(input, 390);
  for (const width of [300, 390, 960]) for (const zoomX of [1, 2, 250, 9999]) {
    const live = comparisonOverlayPlan(input, width, { zoomX, startIndex: 4000.25 }, source);
    assert.equal(live.width, Math.max(96, width - 46));
    assert.ok(live.axis.labels.every(label => label.left >= 4 && label.right <= live.width - 4));
    assert.ok(live.axis.episodeTicks.every(tick => tick.episodeIndex - 1 >= live.startIndex && tick.episodeIndex - 1 <= live.endIndex));
    for (let index = 1; index < live.axis.labels.length; index++) assert.ok(live.axis.labels[index].left >= live.axis.labels[index - 1].right + 8);
    if (zoomX === 9999) {
      assert.ok(live.series[0].points.length <= 2); assert.ok(live.series[0].runs[0].length <= 6);
      assert.ok(live.series[0].trend[0].length <= 6);
    }
  }
});

test('zoomed rating axes keep both endpoints and readable labels in the shorter average panel', () => {
  const input = model([show(1, [episode(1, 4), episode(2, 8), episode(3, 10)])]);
  for (const viewport of [{ low: 0, high: 10 }, { low: 7.7, high: 8.2 }, { low: 9.6, high: 10 }, { low: 3.77, high: 9.99 }]) {
    const plan = comparisonOverlayPlan(input, 390, viewport);
    const html = comparisonOverlayHTML(input, { availableWidth: 390, viewport });
    const axis = html.match(/<svg class="ratings-chart-axis"[\s\S]*?<\/svg>/)[0];
    const labels = [...axis.matchAll(/class="ratings-tick" x="40" y="([^"]+)"[^>]*>([^<]+)<\/text>/g)]
      .map(match => ({ y: Number(match[1]) - 4, text: match[2] }));
    for (const row of [plan.raw, plan.trend]) {
      const inRow = labels.filter(label => label.y >= row.top - 1e-8 && label.y <= row.bottom + 1e-8).sort((a, b) => a.y - b.y);
      assert.equal(inRow[0].y, row.top); assert.equal(inRow.at(-1).y, row.bottom);
      assert.equal(Number(inRow[0].text), Number(plan.high.toFixed(2)));
      assert.equal(Number(inRow.at(-1).text), Number(plan.low.toFixed(2)));
      for (let index = 1; index < inRow.length; index++) assert.ok(inRow[index].y - inRow[index - 1].y >= 18 - 1e-8);
    }
  }
});
