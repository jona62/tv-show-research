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

test('stable colors distinguish the five real shows and remain readable on the Couchside background', () => {
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
    assert.ok(Math.hypot(...a.map((value, index) => value - b[index])) >= 50, 'Approved identities must not collapse into nearly identical colors');
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
  const input = model([show(169, [episode(1, 6), episode(2, 10)])]);
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
