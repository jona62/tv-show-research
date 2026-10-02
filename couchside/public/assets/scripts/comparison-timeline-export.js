// Render only the captured comparison; live UI changes cannot alter a pending export.
import { comparisonOverlayPlan } from './comparison-timeline.js?v=0c0eea8d96bab16d';
import { smoothPath } from './episode-timeline.js?v=803e207689055be8';
import { band, score } from './ratings.js?v=2a0509d86dd759f5';

const RAW = { top: 36, bottom: 244 }, TREND = { top: 338, bottom: 426 };
export const COMPARISON_HEADER_HEIGHT = 152;
const MARGIN = 36, GAP = 28, HEADER = COMPARISON_HEADER_HEIGHT, FOOTER = 140, AXIS = 46, MAX_PIXELS = 12000000;
const scopeName = (model, show) => model.mode === 'all' ? 'All seasons' : show.season == null ? 'No episodes yet'
  : Number(show.season) >= 1900 ? `${show.season} season` : `Season ${show.season}`;
const ordinate = (rating, low, row) => row.bottom - (rating - low) * (row.bottom - row.top) / (10 - low);

function contextRun(points, start, end, transform) {
  // These actual neighbours retain the cubic controls and connection through gaps.
  const before = points.filter(point => point.sampleIndex < start).slice(-2);
  const owned = points.filter(point => point.sampleIndex >= start && point.sampleIndex < end);
  const after = points.filter(point => point.sampleIndex >= end).slice(0, 2);
  const run = [...before, ...owned, ...after].map(transform);
  return run.length ? [run] : [];
}

function continuationAxis(start, end, width, spacing) {
  const ticks = [], labels = [], count = end - start;
  const position = index => 20 + (index - start) * spacing;
  const tickStep = Math.max(1, Math.ceil(8 / spacing)), labelStep = Math.max(1, Math.ceil(64 / spacing));
  for (let index = start; index < end; index += tickStep) ticks.push({ x: position(index), episodeIndex: index + 1 });
  const add = index => {
    const text = `E${index + 1}`, x = position(index), size = text.length * 8;
    const anchor = index === start ? 'start' : index === end - 1 ? 'end' : 'middle';
    const left = anchor === 'start' ? x : anchor === 'end' ? x - size : x - size / 2, right = left + size;
    if (left < 4 || right > width - 4 || labels.some(label => left < label.right + 8 && right > label.left - 8)) return;
    labels.push({ text, x, y: 268, anchor, left, right, episodeIndex: index + 1 });
  };
  if (count) add(start);
  if (count > 1) add(end - 1);
  for (let index = start + labelStep; index < end - 1; index += labelStep) add(index);
  labels.sort((a, b) => a.x - b.x);
  return { baseline: 244, labels, episodeTicks: ticks };
}

function sliceOverlay(full, start, end, width) {
  const count = end - start, spacing = (width - 64) / Math.max(1, count - 1);
  const transform = point => ({ ...point, x: 20 + (point.sampleIndex - start) * spacing });
  const series = full.series.map(source => ({ ...source,
    points: source.points.filter(point => point.sampleIndex >= start && point.sampleIndex < end).map(transform),
    runs: contextRun(source.points.filter(point => point.rating != null), start, end, transform),
    trendPoints: source.trendPoints.filter(point => point.sampleIndex >= start && point.sampleIndex < end).map(transform),
    trend: contextRun(source.trendPoints, start, end, transform),
  }));
  return { ...full, start, end, count, width, viewport: width, spacing, series,
    axis: continuationAxis(start, end, width, spacing) };
}

/** Bounded pure layout plan; all N series remain together in each overlay. */
export function planComparisonTimelineExport(model, { maxWidth = 1600, maxHeight = 1800, maxPixels = MAX_PIXELS, scale = 2 } = {}) {
  const layout = ['row', 'side', 'compact'].includes(model.timelineLayout) ? model.timelineLayout : 'row';
  const pointStyle = ['show', 'rating', 'none'].includes(model.pointStyle) ? model.pointStyle : 'show';
  const showTrend = model.averages !== false, shows = model.shows || [];
  const width = Math.floor(Math.min(maxWidth, layout === 'side' ? 1600 : layout === 'compact' ? 1080 : 1280));
  const heightLimit = Math.floor(Math.min(maxHeight, maxPixels / (width * scale ** 2)));
  const posterWidth = layout === 'compact' ? 120 : 160, posterHeight = layout === 'compact' ? 180 : 240;
  const cardHeight = posterHeight + (showTrend ? 132 : 112), contentWidth = width - MARGIN * 2;
  const columns = layout === 'side' ? shows.length >= 3 ? 2 : 1 : Math.max(1, Math.floor((contentWidth + GAP) / (posterWidth + GAP)));
  const galleryWidth = layout === 'side' ? columns * posterWidth + (columns - 1) * GAP : contentWidth;
  const chartWidth = Math.floor(contentWidth - AXIS - (layout === 'side' ? galleryWidth + 36 : 0));
  const chartHeight = showTrend ? 444 : 300;
  const galleryRoom = heightLimit - HEADER - FOOTER - (layout === 'side' ? 0 : chartHeight + GAP);
  const maxGalleryRows = Math.floor((galleryRoom + GAP) / (cardHeight + GAP));
  if (chartWidth < 160 || maxGalleryRows < 1 || HEADER + chartHeight + FOOTER > heightLimit)
    throw new Error('The snapshot limits cannot fit readable graphs and full posters.');
  const posterCapacity = columns * maxGalleryRows;
  const full = comparisonOverlayPlan(model, chartWidth + AXIS);
  const posterGroups = [];
  for (let start = 0; start < Math.max(1, shows.length); start += posterCapacity)
    posterGroups.push({ start, end: Math.min(shows.length, start + posterCapacity), series: full.series.slice(start, start + posterCapacity) });
  const maxSamples = Math.max(1, Math.floor(chartWidth - 64) + 1), ranges = [];
  for (let start = 0; start < Math.max(1, full.maxCount); start += maxSamples)
    ranges.push({ start, end: Math.min(full.maxCount, start + maxSamples) });
  const pages = [];
  // Poster chapters repeat the complete overlay instead of dropping comparison lines.
  ranges.forEach((range, rangeIndex) => posterGroups.forEach((group, groupIndex) => {
    const galleryRows = Math.ceil(group.series.length / columns);
    const galleryHeight = galleryRows * cardHeight + Math.max(0, galleryRows - 1) * GAP;
    const chartY = layout === 'side' ? HEADER : HEADER + galleryHeight + GAP;
    const chartX = MARGIN + AXIS + (layout === 'side' ? galleryWidth + 36 : 0);
    const height = Math.ceil(HEADER + (layout === 'side' ? Math.max(galleryHeight, chartHeight) : galleryHeight + GAP + chartHeight) + FOOTER);
    const cards = group.series.map((series, index) => {
      const row = Math.floor(index / columns), column = index % columns;
      const inRow = Math.min(columns, group.series.length - row * columns);
      const rowWidth = inRow * posterWidth + Math.max(0, inRow - 1) * GAP;
      return { series, x: MARGIN + (galleryWidth - rowWidth) / 2 + column * (posterWidth + GAP),
        y: HEADER + row * (cardHeight + GAP), width: posterWidth, height: cardHeight, posterWidth, posterHeight };
    });
    pages.push({ kind:'comparison-timeline', layout, pointStyle, posterGroups:posterGroups.length,
      width, height, rangeIndex, groupIndex, posterStart: group.start, posterEnd: group.end,
      chartX, chartY, plot: sliceOverlay(full, range.start, range.end, chartWidth), cards });
  }));
  pages.forEach((page, index) => {
    const range = page.plot.count ? `Episodes ${page.plot.start + 1}–${page.plot.end} of ${full.maxCount}` : 'No episodes yet';
    const posterRange = posterGroups.length > 1 ? ` · Posters ${page.posterStart + 1}–${page.posterEnd} of ${shows.length}` : '';
    page.label = `${pages.length > 1 ? `Part ${index + 1} of ${pages.length} · ` : ''}${range}${posterRange}`;
  });
  return { layout, pointStyle, showTrend, maxCount: full.maxCount, low: full.low, ticks: full.ticks, posterGroups: posterGroups.length, pages };
}

function drawPosters(context, page, model, thumbnails, helpers) {
  const { drawText, drawPoster, wrapText, fitText, exportColors } = helpers;
  page.cards.forEach(card => {
    const { series, x, y, width, posterWidth, posterHeight } = card, show = series.show, centre = x + width / 2;
    drawPoster(context, thumbnails.get(show.poster), x, y, posterWidth, posterHeight);
    context.strokeStyle = series.colour; context.lineWidth = 3; context.beginPath();
    context.moveTo(centre - 18, y + posterHeight + 13); context.lineTo(centre + 18, y + posterHeight + 13); context.stroke();
    const titleLines = wrapText(context, show.name, width, 16, 650);
    titleLines.slice(0, 2).forEach((line, index) =>
      drawText(context, fitText(context, line + (index === 1 && titleLines.length > 2 ? '…' : ''), width, 16, 650), centre, y + posterHeight + 35 + index * 20,
        { size: 16, weight: 650, align: 'center' }));
    const scope = [show.year, scopeName(model, show)].filter(Boolean).join(' · ');
    drawText(context, fitText(context, scope, width, 11, 400), centre, y + posterHeight + 77,
      { size: 11, color: exportColors.muted, align: 'center' });
    drawText(context, `${show.episodes.length.toLocaleString('en-US')} ${show.episodes.length === 1 ? 'episode' : 'episodes'}`, centre,
      y + posterHeight + 95, { size: 12, color: exportColors.muted, align: 'center' });
    if (model.averages !== false) drawText(context, `Avg. ${score(series.mean)}`, centre, y + posterHeight + 117,
      { size: 13, weight: 600, align: 'center' });
  });
}

function drawGraphs(context, page, pointStyle, helpers) {
  const { drawText, exportColors, createPath } = helpers, { plot, chartX, chartY } = page;
  drawText(context, 'Episode ratings', chartX, chartY + 17, { size: 13, color: exportColors.muted, weight: 600 });
  if (plot.showTrend) {
    drawText(context, '5-episode average', chartX, chartY + 317, { size: 13, color: exportColors.muted, weight: 600 });
    drawText(context, 'Within each season', chartX + 144, chartY + 317, { size: 12, color: exportColors.muted });
  }
  [RAW, ...(plot.showTrend ? [TREND] : [])].forEach(row => {
    let previous = Infinity;
    const labels = new Set(plot.ticks.filter((value, index, all) => index === 0 || index === all.length - 1 ||
      Math.abs(ordinate(value, plot.low, row) - ordinate(plot.low, plot.low, row)) >= 18 &&
      Math.abs(ordinate(value, plot.low, row) - ordinate(10, plot.low, row)) >= 18));
    plot.ticks.forEach(value => {
      const y = chartY + ordinate(value, plot.low, row);
      context.strokeStyle = '#ffffff12'; context.lineWidth = 1; context.beginPath();
      context.moveTo(chartX, y); context.lineTo(chartX + plot.width, y); context.stroke();
      if (labels.has(value) && (previous - y >= 18 || value === 10)) {
        drawText(context, value.toFixed(Number.isInteger(value * 2) ? 1 : 2), chartX - 12, y + 4,
          { size: 11, color: exportColors.muted, align: 'right' }); previous = y;
      }
    });
  });
  plot.axis.episodeTicks.forEach(point => {
    context.strokeStyle = '#ffffff0e'; context.lineWidth = 1; context.beginPath();
    context.moveTo(chartX + point.x, chartY + RAW.top); context.lineTo(chartX + point.x, chartY + RAW.bottom); context.stroke();
  });
  plot.axis.labels.forEach(label => drawText(context, label.text, chartX + label.x, chartY + label.y,
    { size: 12, color: exportColors.muted, align: label.anchor === 'start' ? 'left' : label.anchor === 'end' ? 'right' : 'center' }));
  context.save(); context.translate(chartX, chartY); context.beginPath(); context.rect(0, 0, plot.width, plot.height); context.clip();
  const drawSeries = (series, trend) => {
    const points = (trend ? series.trendPoints : series.points.filter(point => point.rating != null));
    context.strokeStyle = series.colour; context.lineWidth = trend ? 2.6 : 1.6;
    (trend ? series.trend : series.runs).forEach(run => context.stroke(createPath(smoothPath(run))));
    if (!trend && pointStyle !== 'none') points.forEach(point => {
      context.fillStyle = pointStyle === 'rating' ? band(point.rating).colour : series.colour;
      context.beginPath(); context.arc(point.x, point.y, Math.max(1.75, Math.min(4, plot.spacing * .45)), 0, Math.PI * 2); context.fill();
      if (pointStyle === 'rating') { context.strokeStyle = series.colour; context.lineWidth = 1.2; context.stroke(); }
    });
    // A line-only average still displays a single actual mean; raw dots obey the picker.
    if (trend && points.length === 1) {
      context.fillStyle = series.colour; context.beginPath(); context.arc(points[0].x, points[0].y, 2, 0, Math.PI * 2); context.fill();
    }
  };
  plot.series.forEach(series => drawSeries(series, false));
  if (plot.showTrend) plot.series.forEach(series => drawSeries(series, true));
  context.restore();
  if (!plot.series.some(series => series.points.some(point => point.rating != null)))
    drawText(context, plot.count ? 'These episodes have not been rated yet.' : 'No episodes yet.', chartX,
      chartY + 120, { size: 13, color: exportColors.muted });
}

// The shared encoder owns allocation, PNG blobs, failure cleanup and ZIP packaging.
export function comparisonTimelineParts(model, limits) {
  return planComparisonTimelineExport(model, limits && {maxWidth:limits.width, maxHeight:limits.height,
    maxPixels:limits.pixels, scale:limits.scale}).pages;
}

export function drawComparisonTimeline(surface, model, page, thumbnails, helpers) {
  const { drawHeader, drawFooter, drawText, fitText, exportColors } = helpers;
  const subtitle = `${model.mode === 'all' ? 'All seasons' : 'Selected seasons'} · Timeline · Episode positions · ${model.shows.length} shows`;
  drawHeader(surface, model, subtitle, thumbnails);
  drawText(surface.context, fitText(surface.context, page.label, page.width - 72, 12, 500), 36, HEADER - 35,
    { size: 12, color: exportColors.muted, weight: 500 });
  const caption = page.posterGroups > 1 ? 'Charts include every compared show · Poster groups continue in this download'
    : 'Each show ends at its last episode';
  drawText(surface.context, caption, 36, HEADER - 16, { size: 12, color: exportColors.muted });
  drawPosters(surface.context, page, model, thumbnails, helpers);
  drawGraphs(surface.context, page, page.pointStyle, helpers);
  drawFooter(surface, model, page.height - 91, { ratingLegend: page.pointStyle === 'rating' });
}
