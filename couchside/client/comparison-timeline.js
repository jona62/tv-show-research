// Shared episode positions and rating scale for live comparisons and snapshots.
import { timelineModel, smoothPath } from './episode-timeline.js';
import { average, band, esc, score } from './ratings.js';

const RAW = { top: 36, bottom: 244 }, TREND = { top: 338, bottom: 426 };
const PALETTE = ['#ffb020', '#91b9dc', '#d594d8', '#8bcd9b', '#fb9288', '#7ad7d2',
  '#d7c781', '#b5a3f2', '#efb4cd', '#a8cce8', '#d9b189', '#a7d5bf', '#e6c889',
  '#9fcbd3', '#d2b5e7', '#e5ac9b', '#c2d18e'];
// Keep the approved show identities consistent across rearrangements and exports.
const SHOW_COLOURS = { 169: '#ffb020', 16149: '#d594e8', 30770: '#88bdf2',
  43031: '#71cec4', 1505: '#f58d7b' };
const ordinate = (rating, low, row) => row.bottom - (rating - low) * (row.bottom - row.top) / (10 - low);
const position = (index, spacing) => 20 + index * spacing;

export function comparisonShowColour(showId) {
  if (SHOW_COLOURS[Number(showId)]) return SHOW_COLOURS[Number(showId)];
  let hash = Math.imul(Number(showId) ^ (Number(showId) >>> 16), 0x45d9f3b);
  hash = (hash ^ (hash >>> 16)) >>> 0;
  const base = PALETTE[hash % PALETTE.length];
  // Independent channel tints add identities without changing the muted palette.
  return '#' + [1, 3, 5].map(offset => Math.max(64, Math.min(250,
    parseInt(base.slice(offset, offset + 2), 16) + ((hash >>> (offset * 3)) % 31 - 15))).toString(16).padStart(2, '0')).join('');
}

function overlayAxis(maxCount, width, spacing) {
  const step = Math.max(1, Math.ceil(56 / spacing)), labels = [], episodeTicks = [];
  for (let index = 0; index < maxCount; index += Math.max(1, Math.ceil(8 / spacing)))
    episodeTicks.push({ x: position(index, spacing), episodeIndex: index + 1 });
  if (maxCount && episodeTicks.at(-1)?.episodeIndex !== maxCount)
    episodeTicks.push({ x: position(maxCount - 1, spacing), episodeIndex: maxCount });
  const add = index => {
    const text = `E${index + 1}`, x = position(index, spacing), size = text.length * 8;
    const anchor = index === 0 ? 'start' : index === maxCount - 1 ? 'end' : 'middle';
    const left = anchor === 'start' ? x : anchor === 'end' ? x - size : x - size / 2;
    const right = left + size;
    if (left < 4 || right > width - 4 || labels.some(label => left < label.right + 8 && right > label.left - 8)) return;
    labels.push({ text, x, y: 268, anchor, left, right, episodeIndex: index + 1 });
  };
  if (maxCount) add(0);
  if (maxCount > 1) add(maxCount - 1);
  for (let index = step; index < maxCount - 1; index += step) add(index);
  labels.sort((a, b) => a.x - b.x);
  return { baseline: 244, labelY: 268, episodeTicks, labels };
}

export function comparisonOverlayPlan(model, availableWidth = 960) {
  const shows = model.shows || [], showTrend = model.averages !== false;
  const maxCount = shows.reduce((maximum, show) => Math.max(maximum, show.episodes.length), 0);
  const lowest = shows.reduce((minimum, show) => show.episodes.reduce((value, episode) =>
    Number.isFinite(episode.rating) ? Math.min(value, episode.rating) : value, minimum), Infinity);
  const low = lowest === Infinity ? 0 : Math.max(0, Math.min(9, Math.floor((lowest - .25) * 4) / 4));
  const ticks = [low];
  for (let value = Math.ceil(low * 2) / 2; value <= 10; value += .5) if (value !== low) ticks.push(value);
  const viewport = Math.max(96, Math.floor(availableWidth) - 46);
  const width = Math.max(viewport, Math.max(0, maxCount - 1) + 64), spacing = (width - 64) / Math.max(1, maxCount - 1);
  const series = shows.map(show => {
    const native = timelineModel(show.episodes, null, availableWidth);
    const nativePoints = native?.series[0].points || show.episodes.map(episode => ({ ...episode, y: null }));
    const indices = new Map(nativePoints.map((point, index) => [point.x, index]));
    // Native averaging stays intact; reproject both rows onto this common scale.
    const transform = (point, index, row = RAW) => ({ ...point, sampleIndex: index, episodeIndex: index + 1,
      x: position(index, spacing), y: point.rating == null ? null : ordinate(point.rating, low, row) });
    const points = nativePoints.map((point, index) => transform(point, index)), rated = points.filter(point => point.rating != null);
    const trendPoints = (native?.series[0].trendPoints || []).map(point => transform(point, indices.get(point.x), TREND));
    return { show, colour: comparisonShowColour(show.id), points, runs: rated.length ? [rated] : [],
      trendPoints, trend: trendPoints.length ? [trendPoints] : [],
      trendRuns: (native?.series[0].trendRuns || []).map(run => run.map(point => transform(point, indices.get(point.x), TREND))),
      mean: average(show.episodes) };
  });
  return { low, ticks, maxCount, count: maxCount, width, viewport, spacing, height: showTrend ? 444 : 300,
    showTrend, axis: overlayAxis(maxCount, width, spacing), series };
}

function tickLabel(value) { return value.toFixed(Number.isInteger(value * 2) ? 1 : 2); }
function axesHTML(plan) {
  return [RAW, ...(plan.showTrend ? [TREND] : [])].map(row => {
    let previous = Infinity;
    const values = plan.ticks.filter((value, index, all) => index === 0 || index === all.length - 1 ||
      Math.abs(ordinate(value, plan.low, row) - ordinate(plan.low, plan.low, row)) >= 18 &&
      Math.abs(ordinate(value, plan.low, row) - ordinate(10, plan.low, row)) >= 18);
    return values.map(value => {
      const y = ordinate(value, plan.low, row);
      if (previous - y < 18 && value !== 10) return '';
      previous = y;
      return `<text class="ratings-tick" x="40" y="${y + 4}" text-anchor="end">${tickLabel(value)}</text>`;
    }).join('');
  }).join('');
}
function gridHTML(plan) {
  return [RAW, ...(plan.showTrend ? [TREND] : [])].map(row => plan.ticks.map(value =>
    `<line x1="0" x2="${plan.width}" y1="${ordinate(value, plan.low, row)}" y2="${ordinate(value, plan.low, row)}"/>`).join('')).join('');
}
function axisHTML(plan) {
  const axis = plan.axis;
  return `<g class="ratings-x-axis" aria-hidden="true" pointer-events="none"><g class="ratings-episode-guides">${axis.episodeTicks.map(point => `<line class="ratings-episode-guide" x1="${point.x}" x2="${point.x}" y1="36" y2="244"/>`).join('')}</g><line class="ratings-x-baseline" x1="0" x2="${plan.width}" y1="244" y2="244"/>${axis.episodeTicks.map(point => `<line class="ratings-episode-tick" x1="${point.x}" x2="${point.x}" y1="244" y2="248"/>`).join('')}${axis.labels.map(label => `<text class="ratings-episode-label" x="${label.x}" y="${label.y}" text-anchor="${label.anchor}">${label.text}</text>`).join('')}</g>`;
}
function seriesHTML(series, plan, pointStyle, trend = false) {
  const runs = trend ? series.trend : series.runs, points = trend ? series.trendPoints : series.points.filter(point => point.rating != null);
  const lines = runs.map(run => `<path class="${trend ? 'ratings-trend' : 'ratings-raw-line'}" d="${smoothPath(run)}" fill="none" stroke="${series.colour}" style="stroke:${series.colour}" stroke-width="${trend ? 2.6 : 1.6}"/>`).join('');
  // The lower plot stays a continuous mean line. A genuine singleton mean is
  // visible, while its raw episode remains the only keyboard destination.
  if (trend) return `<g class="comparison-overlay-series" data-show-id="${series.show.id}" data-plot="trend" aria-hidden="true">${lines}${points.length === 1 ? `<circle class="ratings-trend-single" cx="${points[0].x}" cy="${points[0].y}" r="3" fill="${series.colour}" style="fill:${series.colour}"/>` : ''}</g>`;
  const dots = points.map(point => {
    const code = `${Number(point.season) >= 1900 ? point.season : 'S' + point.season} E${point.number}`;
    const label = `${series.show.name}, position ${point.episodeIndex}, ${code}${point.name ? ': ' + point.name : ''}, ${trend ? 'five-episode average ' : ''}${score(point.rating)} out of 10`;
    const colour = pointStyle === 'rating' ? band(point.rating).colour : series.colour;
    return `<g class="ratings-point-hit" data-show-id="${series.show.id}" data-episode="${point.id}" data-sample-index="${point.sampleIndex}" tabindex="0" role="img" aria-label="${esc(label)}"><title>${esc(label)}</title><circle class="ratings-point-target" cx="${point.x}" cy="${point.y}" r="12" fill="transparent"/><circle class="ratings-point${pointStyle === 'none' ? ' comparison-overlay-point-hidden' : ''}"${pointStyle === 'none' ? ' opacity="0"' : ''} cx="${point.x}" cy="${point.y}" r="${Math.max(1.75, Math.min(4, plan.spacing * .45))}" fill="${colour}"${pointStyle === 'rating' ? ` stroke="${series.colour}" style="stroke:${series.colour}"` : ''}/></g>`;
  }).join('');
  return `<g class="comparison-overlay-series" data-show-id="${series.show.id}" data-plot="raw">${lines}${dots}</g>`;
}

export function comparisonOverlayHTML(model, { availableWidth = 960, pointStyle = model.pointStyle || 'show' } = {}) {
  if (!['show', 'rating', 'none'].includes(pointStyle)) pointStyle = 'show';
  const plan = comparisonOverlayPlan(model, availableWidth);
  const key = `<div class="comparison-overlay-key" aria-label="Show colours">${plan.series.map(series => `<span class="comparison-overlay-key-item" style="--comparison-show-colour:${series.colour}"><i class="comparison-overlay-swatch" style="background:${series.colour}" aria-hidden="true"></i><span class="comparison-overlay-name">${esc(series.show.name)}</span>${plan.showTrend ? `<span class="comparison-overlay-mean">Avg. ${series.mean == null ? 'Unrated' : score(series.mean)}</span>` : ''}</span>`).join('')}</div>`;
  const caption = `<p class="ratings-credit comparison-overlay-caption">Episode position ${model.mode === 'single' ? 'within selected seasons' : 'in watch order'} · Each show ends at its last episode</p>`;
  if (!plan.series.some(series => series.runs.length)) return `<div class="comparison-overlay">${key}${caption}<p class="ratings-empty">These episodes have not been rated yet.</p></div>`;
  const scrolls = plan.width > plan.viewport;
  return `<div class="comparison-overlay">${key}${caption}<div class="ratings-chart-frame ratings-chart-frame-comparison comparison-overlay-frame"><p class="ratings-chart-label">Episode ratings</p>${plan.showTrend ? '<p class="ratings-chart-label ratings-chart-label-trend">5-episode average <span>Within each season</span></p>' : ''}<svg class="ratings-chart-axis" width="46" height="${plan.height}" viewBox="0 0 46 ${plan.height}" aria-hidden="true">${axesHTML(plan)}</svg><div class="ratings-chart-wrap" tabindex="0" role="region" aria-label="Comparison timeline${scrolls ? '; scroll horizontally to explore' : ''}"><svg class="ratings-timeline" width="${plan.width}" height="${plan.height}" viewBox="0 0 ${plan.width} ${plan.height}" role="group" aria-label="Episode ratings comparison, scale ${plan.low} to 10${plan.showTrend ? ', with separate five-episode averages below' : ''}" data-min="${plan.low}" style="--ratings-point-stroke:${plan.spacing >= 6 ? 1.5 : .65}"><g class="ratings-chart-grid">${gridHTML(plan)}</g><g class="ratings-episode-plot">${plan.series.map(series => seriesHTML(series, plan, pointStyle)).join('')}</g>${axisHTML(plan)}${plan.showTrend ? `<g class="ratings-trend-plot">${plan.series.map(series => seriesHTML(series, plan, pointStyle, true)).join('')}</g>` : ''}</svg></div></div>${scrolls ? `<p class="ratings-scroll-hint">Scroll to explore all ${plan.maxCount.toLocaleString('en-US')} episode positions</p>` : ''}</div>`;
}
