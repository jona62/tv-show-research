// Shared episode positions and rating scale for live comparisons and snapshots.
import { timelineModel, smoothPath } from './episode-timeline.js';
import { average, band, esc, score } from './ratings.js';
import { comparisonPosterColours } from './poster-colours.js';
export { comparisonShowColour } from './poster-colours.js';

const RAW = { top: 36, bottom: 244 }, TREND = { top: 338, bottom: 426 };
const ordinate = (rating, low, row, high = 10) => row.bottom - (rating - low) * (row.bottom - row.top) / (high - low);
const position = (index, spacing) => 20 + index * spacing;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

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

function fullOverlayPlan(model, availableWidth) {
  const shows = model.shows || [], showTrend = model.averages !== false;
  const colours = comparisonPosterColours(shows);
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
    return { show, colour: colours.get(show.id), points, runs: rated.length ? [rated] : [],
      trendPoints, trend: trendPoints.length ? [trendPoints] : [],
      trendRuns: (native?.series[0].trendRuns || []).map(run => run.map(point => transform(point, indices.get(point.x), TREND))),
      mean: average(show.episodes) };
  });
  return { low, ticks, maxCount, count: maxCount, width, viewport, spacing, height: showTrend ? 444 : 300,
    showTrend, axis: overlayAxis(maxCount, width, spacing), series };
}

function ratingRange(viewport, baseLow) {
  let low = clamp(Number.isFinite(viewport.low) ? viewport.low : baseLow, 0, 10);
  let high = clamp(Number.isFinite(viewport.high) ? viewport.high : 10, 0, 10);
  if (low > high) [low, high] = [high, low];
  if (high - low < .5) {
    low = clamp((low + high) / 2 - .25, 0, 9.5); high = low + .5;
  }
  return { low, high };
}

function rangeTicks(low, high) {
  const step = high - low < 1 ? .1 : high - low < 2 ? .25 : .5, ticks = [low];
  for (let value = Math.ceil(low / step) * step; value < high - 1e-9; value += step)
    if (value > low + 1e-9) ticks.push(Number(value.toFixed(8)));
  ticks.push(high);
  return ticks;
}

function lowerBound(points, index) {
  let first = 0, last = points.length;
  while (first < last) {
    const middle = (first + last) >>> 1;
    if (points[middle].sampleIndex < index) first = middle + 1; else last = middle;
  }
  return first;
}

function visibleSlice(points, start, end, neighbours = 0) {
  const first = lowerBound(points, start), last = lowerBound(points, end + 1e-9);
  return points.slice(Math.max(0, first - neighbours), Math.min(points.length, last + neighbours));
}

function viewportAxis(maxCount, width, spacing, start, end) {
  const first = Math.max(0, Math.ceil(start)), last = Math.min(maxCount - 1, Math.floor(end));
  const labels = [], episodeTicks = [], x = index => position(index - start, spacing);
  const add = index => {
    const text = `E${index + 1}`, at = x(index), size = text.length * 8;
    const anchor = index === first ? 'start' : index === last ? 'end' : 'middle';
    const left = anchor === 'start' ? at : anchor === 'end' ? at - size : at - size / 2, right = left + size;
    if (left < 4 || right > width - 4 || labels.some(label => left < label.right + 8 && right > label.left - 8)) return;
    labels.push({ text, x: at, y: 268, anchor, left, right, episodeIndex: index + 1 });
  };
  const tickStep = Math.max(1, Math.ceil(8 / spacing)), labelStep = Math.max(1, Math.ceil(56 / spacing));
  for (let index = first; index <= last; index += tickStep) episodeTicks.push({ x: x(index), episodeIndex: index + 1 });
  if (last >= first && episodeTicks.at(-1)?.episodeIndex !== last + 1) episodeTicks.push({ x: x(last), episodeIndex: last + 1 });
  if (last >= first) add(first);
  if (last > first) add(last);
  for (let index = Math.ceil((first + 1) / labelStep) * labelStep; index < last; index += labelStep) add(index);
  labels.sort((a, b) => a.x - b.x);
  return { baseline: 244, labelY: 268, episodeTicks, labels };
}

// Snapshots keep their full native geometry. Live viewports reuse those complete
// averages and reproject only visible samples plus the cubic paths' neighbours.
export function comparisonOverlayPlan(model, availableWidth = 960, viewport, sourcePlan) {
  const liveWidth = Number.isFinite(availableWidth) ? availableWidth : 960;
  const source = sourcePlan || fullOverlayPlan(model, viewport ? liveWidth : availableWidth);
  if (!viewport) return source;
  const width = Math.max(96, Math.floor(liveWidth) - 46), maxZoom = Math.max(1, source.maxCount - 1);
  const zoomX = clamp(Number.isFinite(viewport.zoomX) ? viewport.zoomX : 1, 1, maxZoom);
  const span = Math.max(1, (source.maxCount - 1) / zoomX);
  const startIndex = clamp(Number.isFinite(viewport.startIndex) ? viewport.startIndex : 0, 0, Math.max(0, source.maxCount - 1 - span));
  const endIndex = startIndex + span, spacing = (width - 64) / span;
  const { low, high } = ratingRange(viewport, source.low);
  const transform = (point, row) => ({ ...point, x: position(point.sampleIndex - startIndex, spacing),
    y: point.rating == null ? null : ordinate(point.rating, low, row, high) });
  const series = source.series.map(original => {
    const points = visibleSlice(original.points, startIndex, endIndex).map(point => transform(point, RAW));
    const rated = visibleSlice(original.runs[0] || [], startIndex, endIndex, 2).map(point => transform(point, RAW));
    const trendPoints = visibleSlice(original.trendPoints, startIndex, endIndex).map(point => transform(point, TREND));
    const trend = visibleSlice(original.trendPoints, startIndex, endIndex, 2).map(point => transform(point, TREND));
    return { ...original, points, runs: rated.length ? [rated] : [], trendPoints,
      trend: trend.length ? [trend] : [], trendCount: original.trendPoints.length,
      trendRuns: original.trendRuns.map(run => visibleSlice(run, startIndex, endIndex).map(point => transform(point, TREND))).filter(run => run.length) };
  });
  return { ...source, live: true, low, high, baseLow: source.low, zoomX, maxZoom, startIndex, endIndex, span,
    raw: { ...RAW }, trend: { ...TREND }, width, viewport: width, spacing,
    ticks: low === source.low && high === 10 ? source.ticks : rangeTicks(low, high),
    axis: viewportAxis(source.maxCount, width, spacing, startIndex, endIndex), series };
}

function tickLabel(value) { return value.toFixed(Number.isInteger(value * 2) ? 1 : 2); }
function axesHTML(plan) {
  const high = plan.high ?? 10;
  return [RAW, ...(plan.showTrend ? [TREND] : [])].map(row => {
    let previous = Infinity;
    const values = plan.ticks.filter((value, index, all) => index === 0 || index === all.length - 1 ||
      Math.abs(ordinate(value, plan.low, row, high) - ordinate(plan.low, plan.low, row, high)) >= 18 &&
      Math.abs(ordinate(value, plan.low, row, high) - ordinate(high, plan.low, row, high)) >= 18);
    return values.map(value => {
      const y = ordinate(value, plan.low, row, high);
      if (previous - y < 18 && value !== high) return '';
      previous = y;
      return `<text class="ratings-tick" x="40" y="${y + 4}" text-anchor="end">${tickLabel(value)}</text>`;
    }).join('');
  }).join('');
}
function gridHTML(plan) {
  return [RAW, ...(plan.showTrend ? [TREND] : [])].map(row => plan.ticks.map(value =>
    `<line x1="0" x2="${plan.width}" y1="${ordinate(value, plan.low, row, plan.high ?? 10)}" y2="${ordinate(value, plan.low, row, plan.high ?? 10)}"/>`).join('')).join('');
}
function axisHTML(plan) {
  const axis = plan.axis;
  return `<g class="ratings-x-axis" aria-hidden="true" pointer-events="none"><g class="ratings-episode-guides">${axis.episodeTicks.map(point => `<line class="ratings-episode-guide" x1="${point.x}" x2="${point.x}" y1="36" y2="244"/>`).join('')}</g><line class="ratings-x-baseline" x1="0" x2="${plan.width}" y1="244" y2="244"/>${axis.episodeTicks.map(point => `<line class="ratings-episode-tick" x1="${point.x}" x2="${point.x}" y1="244" y2="248"/>`).join('')}${axis.labels.map(label => `<text class="ratings-episode-label" x="${label.x}" y="${label.y}" text-anchor="${label.anchor}">${label.text}</text>`).join('')}</g>`;
}
function seriesHTML(series, plan, pointStyle, trend = false) {
  const runs = trend ? series.trend : series.runs;
  const points = (trend ? series.trendPoints : series.points).filter(point => point.rating != null &&
    (!plan.live || point.rating >= plan.low && point.rating <= plan.high));
  const lines = runs.map(run => `<path class="${trend ? 'ratings-trend' : 'ratings-raw-line'}" d="${smoothPath(run)}" fill="none" stroke="${series.colour}" style="stroke:${series.colour}" stroke-width="${trend ? 2.6 : 1.6}"/>`).join('');
  // The lower plot stays a continuous mean line. A genuine singleton mean is
  // visible, while its raw episode remains the only keyboard destination.
  if (trend) return `<g class="comparison-overlay-series" data-show-id="${series.show.id}" data-plot="trend" aria-hidden="true">${lines}${points.length === 1 && (!plan.live || series.trendCount === 1) ? `<circle class="ratings-trend-single" cx="${points[0].x}" cy="${points[0].y}" r="3" fill="${series.colour}" style="fill:${series.colour}"/>` : ''}</g>`;
  const dots = points.map(point => {
    const code = `${Number(point.season) >= 1900 ? point.season : 'S' + point.season} E${point.number}`;
    const label = `${series.show.name}, position ${point.episodeIndex}, ${code}${point.name ? ': ' + point.name : ''}, ${trend ? 'five-episode average ' : ''}${score(point.rating)} out of 10`;
    const colour = pointStyle === 'rating' ? band(point.rating).colour : series.colour;
    return `<g class="ratings-point-hit" data-show-id="${series.show.id}" data-episode="${point.id}" data-sample-index="${point.sampleIndex}" tabindex="0" role="img" aria-label="${esc(label)}"><title>${esc(label)}</title><circle class="ratings-point-target" cx="${point.x}" cy="${point.y}" r="12" fill="transparent"/><circle class="ratings-point${pointStyle === 'none' ? ' comparison-overlay-point-hidden' : ''}"${pointStyle === 'none' ? ' opacity="0"' : ''} cx="${point.x}" cy="${point.y}" r="${Math.max(1.75, Math.min(4, plan.spacing * .45))}" fill="${colour}"${pointStyle === 'rating' ? ` stroke="${series.colour}" style="stroke:${series.colour}"` : ''}/></g>`;
  }).join('');
  return `<g class="comparison-overlay-series" data-show-id="${series.show.id}" data-plot="raw">${lines}${dots}</g>`;
}

export function comparisonOverlayHTML(model, { availableWidth = 960, pointStyle = model.pointStyle || 'show', viewport, sourcePlan } = {}) {
  if (!['show', 'rating', 'none'].includes(pointStyle)) pointStyle = 'show';
  const plan = comparisonOverlayPlan(model, availableWidth, viewport, sourcePlan);
  const key = `<div class="comparison-overlay-key" aria-label="Show colours">${plan.series.map(series => `<span class="comparison-overlay-key-item" style="--comparison-show-colour:${series.colour}"><i class="comparison-overlay-swatch" style="background:${series.colour}" aria-hidden="true"></i><span class="comparison-overlay-name">${esc(series.show.name)}</span>${plan.showTrend ? `<span class="comparison-overlay-mean">Avg. ${series.mean == null ? 'Unrated' : score(series.mean)}</span>` : ''}</span>`).join('')}</div>`;
  const caption = `<p class="ratings-credit comparison-overlay-caption">Episode position ${model.mode === 'single' ? 'within selected seasons' : 'in watch order'} · Each show ends at its last episode</p>`;
  if (!plan.series.some(series => series.runs.length)) return `<div class="comparison-overlay">${key}${caption}<p class="ratings-empty">These episodes have not been rated yet.</p></div>`;
  const scrolls = plan.width > plan.viewport;
  const clipId = `comparison-${plan.width}-${plan.low}-${plan.high}`.replace(/[^a-zA-Z0-9-]/g, '-');
  const clips = plan.live ? `<defs><clipPath id="${clipId}-raw"><rect x="0" y="${RAW.top}" width="${plan.width}" height="${RAW.bottom - RAW.top}"/></clipPath>${plan.showTrend ? `<clipPath id="${clipId}-trend"><rect x="0" y="${TREND.top}" width="${plan.width}" height="${TREND.bottom - TREND.top}"/></clipPath>` : ''}</defs>` : '';
  const clip = row => plan.live ? ` clip-path="url(#${clipId}-${row})"` : '';
  const geometry = plan.live ? ` data-start-index="${plan.startIndex}" data-end-index="${plan.endIndex}" data-span="${plan.span}" data-zoom-x="${plan.zoomX}"` : '';
  return `<div class="comparison-overlay">${key}${caption}<div class="ratings-chart-frame ratings-chart-frame-comparison comparison-overlay-frame"><p class="ratings-chart-label comparison-overlay-label">Episode ratings</p>${plan.showTrend ? '<p class="ratings-chart-label ratings-chart-label-trend comparison-overlay-label">5-episode average within each season</p>' : ''}<svg class="ratings-chart-axis" width="46" height="${plan.height}" viewBox="0 0 46 ${plan.height}" aria-hidden="true">${axesHTML(plan)}</svg><div class="ratings-chart-wrap" tabindex="0" role="region" aria-label="Comparison timeline${scrolls ? '; scroll horizontally to explore' : ''}"><svg class="ratings-timeline" width="${plan.width}" height="${plan.height}" viewBox="0 0 ${plan.width} ${plan.height}" role="group" aria-label="Episode ratings comparison, scale ${plan.low} to ${plan.high ?? 10}${plan.showTrend ? ', with separate five-episode averages below' : ''}" data-min="${plan.low}" data-max="${plan.high ?? 10}"${geometry} style="--ratings-point-stroke:${plan.spacing >= 6 ? 1.5 : .65}">${clips}<g class="ratings-chart-grid">${gridHTML(plan)}</g><g class="ratings-episode-plot"${clip('raw')}>${plan.series.map(series => seriesHTML(series, plan, pointStyle)).join('')}</g>${axisHTML(plan)}${plan.showTrend ? `<g class="ratings-trend-plot"${clip('trend')}>${plan.series.map(series => seriesHTML(series, plan, pointStyle, true)).join('')}</g>` : ''}</svg></div></div>${scrolls ? `<p class="ratings-scroll-hint">Scroll to explore all ${plan.maxCount.toLocaleString('en-US')} episode positions</p>` : ''}</div>`;
}
