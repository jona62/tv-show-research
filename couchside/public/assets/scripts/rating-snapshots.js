import {average, band, bands, ratingSources, score} from './ratings.js?v=2a0509d86dd759f5';
import {timelineModel, timelineAxis, smoothPath} from './episode-timeline.js?v=803e207689055be8';
import {detailMatrix, compareMatrix, seasonName, episodeCode} from './rating-views.js?v=2168d19db732fbe1';
import {loadSnapshotImages} from './snapshot-images.js?v=58ed772a708f7e6c';
import {comparisonTimelineParts, drawComparisonTimeline, COMPARISON_HEADER_HEIGHT} from './comparison-timeline-export.js?v=849ae6d7d91c88c9';

// Every part stays below common mobile canvas limits, at twice its logical size.
export const SNAPSHOT_LIMITS = Object.freeze({width:1600, height:1800, pixels:12_000_000, scale:2});
const COLORS = {background:'#181818', text:'#ffffff', muted:'#a8a8a8', gold:'#ffb020', line:'#2e2e2e'};
const POSTER = {width:160, height:240};
const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
// Comparison headers need only the wordmark and scope; the show names belong to the posters.
const headerOffset = model => model.kind === 'detail' ? 200 : COMPARISON_HEADER_HEIGHT - 190;
const chunks = (items, size) => Array.from({length:Math.max(1, Math.ceil(items.length / size))},
  (_, index) => items.slice(index * size, (index + 1) * size));
const formatScore = value => value == null ? '—' : score(value);
const seasonNumbers = episodes => [...new Set(episodes.map(episode => episode.season))].sort((a, b) => a - b);
const yearLabel = model => model.year ? `${model.year} · ` : '';
const scopeLabel = model => model.season === 'all' ? 'All seasons' : seasonName(model.season);
const episodeRange = episodes => episodes.length
  ? `${episodeCode(episodes[0])}–${episodeCode(episodes.at(-1))}` : 'No episodes';

function labelParts(parts) {
  return parts.map((part, index) => ({...part,
    label:parts.length > 1 ? `Part ${index + 1} of ${parts.length} · ${part.range}` : part.range,
    continued:parts.length > 1,
  }));
}

function matrixParts(model) {
  const matrix = model.kind === 'compare' ? compareMatrix(model) : detailMatrix(model);
  const showColumns = matrix.headers.some(header => header.show);
  const showRows = matrix.rows.some(row => row.show);
  const columnWidth = showColumns ? 210 : model.inverted ? 100 : 57;
  const labelWidth = showRows ? 350 : 66;
  const rowHeight = showRows ? 260 : 52, headerHeight = showColumns ? 318 : 46;
  const offset = headerOffset(model);
  const maxColumns = Math.max(1, Math.floor((SNAPSHOT_LIMITS.width - 72 - labelWidth) / (columnWidth + 8)));
  const maxRows = Math.max(1, Math.floor((SNAPSHOT_LIMITS.height - 190 - offset - headerHeight - 130) / rowHeight));
  const columnGroups = chunks(matrix.headers, maxColumns), rowGroups = chunks(matrix.rows, maxRows);
  const count = columnGroups.length * rowGroups.length, parts = [];
  for (const [columnIndex, headers] of columnGroups.entries()) for (const rows of rowGroups) {
    const top = (count > 1 ? 190 : 158) + offset;
    const bottom = top + headerHeight + rows.length * rowHeight;
    const range = `${headers[0]?.label || matrix.axis}${headers.length > 1 ? '–' + headers.at(-1).label : ''}` +
      ` · ${rows[0]?.label || ''}${rows.length > 1 ? '–' + rows.at(-1).label : ''}`;
    parts.push({kind:'matrix', matrix, headers, rows, columnStart:columnIndex * maxColumns,
      showRows, columnWidth, labelWidth, rowHeight, headerHeight, top, bottom,
      width:Math.max(880, labelWidth + headers.length * (columnWidth + 8) + 72), height:bottom + 130,
      range:count > 1 ? range : matrix.caption,
    });
  }
  return labelParts(parts);
}

function wrappedParts(model) {
  const width = 940, columns = 14, offset = headerOffset(model);
  const available = SNAPSHOT_LIMITS.height - 190 - offset - 112;
  const maxRows = Math.max(1, Math.floor((available - 64) / 76));
  const sections = seasonNumbers(model.episodes).flatMap(season => {
    const selected = model.episodes.filter(episode => episode.season === season);
    return chunks(selected, columns * maxRows).map((episodes, index) => ({
      season, episodes, average:average(selected), continued:index > 0,
      height:64 + Math.ceil(episodes.length / columns) * 76,
    }));
  });
  const groups = []; let group = [], height = 0;
  for (const section of sections) {
    if (group.length && height + section.height > available) { groups.push(group); group = []; height = 0; }
    group.push(section); height += section.height;
  }
  if (group.length) groups.push(group);
  if (!groups.length) groups.push([]);
  return labelParts(groups.map(selected => {
    const top = (groups.length > 1 ? 190 : 158) + offset;
    const range = selected.length ? `${seasonName(selected[0].season)}` +
      (selected.length > 1 ? '–' + seasonName(selected.at(-1).season) : '') : 'No episodes';
    return {kind:'wrapped', width, top, sections:selected,
      height:Math.max(560, top + selected.reduce((sum, section) => sum + section.height, 0) + 112), range};
  }));
}

function listParts(model) {
  const width = 960, rowHeight = 84, offset = headerOffset(model);
  const maxRows = Math.floor((SNAPSHOT_LIMITS.height - 190 - offset - 118) / rowHeight);
  const groups = chunks(model.episodes, maxRows);
  return labelParts(groups.map(episodes => {
    const top = (groups.length > 1 ? 190 : 155) + offset;
    return {kind:'list', episodes, top, rowHeight, width,
      height:Math.max(560, top + episodes.length * rowHeight + 118), range:episodeRange(episodes)};
  }));
}

function timelineParts(model) {
  const global = timelineModel(model.episodes, null, 928), offset = headerOffset(model);
  const width = Math.min(SNAPSHOT_LIMITS.width, Math.max(1000, (global?.width || 882) + 118));
  if (!global) return [{kind:'timeline', global:null, episodes:model.episodes, width, height:360 + offset,
    top:145 + offset, range:'Unrated episodes', label:'Unrated episodes', continued:false}];
  const maxSamples = SNAPSHOT_LIMITS.width - 118 - 64 + 1;
  const groups = chunks(model.episodes, maxSamples);
  return labelParts(groups.map(episodes => {
    const top = (groups.length > 1 ? 190 : 145) + offset;
    return {kind:'timeline', global, episodes, top, width,
      height:Math.max(720 + offset, top + 474 + 130), range:episodeRange(episodes)};
  }));
}

// Planning is independent of the DOM and image loading. It never changes the view.
export function planRatingSnapshot(model) {
  if (model.kind === 'compare' && model.view === 'timeline') return comparisonTimelineParts(model, SNAPSHOT_LIMITS);
  if (model.kind === 'compare' || model.view === 'grid') return matrixParts(model);
  if (model.view === 'wrapped') return wrappedParts(model);
  if (model.view === 'timeline') return timelineParts(model);
  return listParts(model);
}

function canvasSurface(part, createCanvas) {
  const {width, height} = part, scale = SNAPSHOT_LIMITS.scale;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 ||
      width > SNAPSHOT_LIMITS.width || height > SNAPSHOT_LIMITS.height || width * height * scale ** 2 > SNAPSHOT_LIMITS.pixels)
    throw Error('This image must be split into smaller continuation parts.');
  const canvas = createCanvas(); canvas.width = width * scale; canvas.height = height * scale;
  const context = canvas.getContext('2d');
  if (!context) { canvas.width = canvas.height = 1; throw Error('Image export is unavailable in this browser.'); }
  context.scale(scale, scale); context.fillStyle = COLORS.background; context.fillRect(0, 0, width, height);
  return {canvas, context, width, height};
}

function drawText(context, value, x, y, {size=14, color=COLORS.text, weight=400, align='left'}={}) {
  context.fillStyle = color; context.font = `${weight} ${size}px ${FONT}`;
  context.textAlign = align; context.textBaseline = 'alphabetic'; context.fillText(String(value), x, y);
}

function fitText(context, value, width, size=14, weight=400) {
  context.font = `${weight} ${size}px ${FONT}`;
  let label = String(value ?? '');
  if (context.measureText(label).width <= width) return label;
  while (label.length && context.measureText(label + '…').width > width) label = label.slice(0, -1);
  return label + '…';
}

function wrapText(context, value, width, size=14, weight=400) {
  context.font = `${weight} ${size}px ${FONT}`;
  const lines = []; let line = '';
  for (const word of String(value ?? '').split(/\s+/)) {
    const next = line ? `${line} ${word}` : word;
    if (context.measureText(next).width > width && line) { lines.push(line); line = word; }
    else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

function drawLines(context, value, x, y, width, {size=14, weight=400, color=COLORS.text, align='left', leading=20}={}) {
  const lines = wrapText(context, value, width, size, weight);
  lines.slice(0, 2).forEach((line, index) => {
    const suffix = index === 1 && lines.length > 2 ? '…' : '';
    drawText(context, fitText(context, line + suffix, width, size, weight), x, y + index * leading,
      {size, weight, color, align});
  });
  return Math.min(2, lines.length);
}

function roundRect(context, x, y, width, height, radius=5) {
  context.beginPath(); context.roundRect(x, y, width, height, radius); context.fill();
}

function drawBrand(context) {
  const label = 'COUCHSIDE', size = 26, tracking = size * .07;
  context.save(); context.font = `900 ${size}px ${FONT}`;
  context.textAlign = 'left'; context.textBaseline = 'alphabetic';
  const width = context.measureText(label).width + tracking * (label.length - 1);
  const gradient = context.createLinearGradient(36, 0, 36 + width, 0);
  gradient.addColorStop(0, '#ffb020'); gradient.addColorStop(1, '#ff6a3d'); context.fillStyle = gradient;
  if ('letterSpacing' in context) { context.letterSpacing = `${tracking}px`; context.fillText(label, 36, 42); }
  else {
    let x = 36;
    for (const letter of label) { context.fillText(letter, x, 42); x += context.measureText(letter).width + tracking; }
  }
  context.restore();
}

function drawPoster(context, image, x, y, boxWidth=POSTER.width, boxHeight=POSTER.height) {
  if (!image) return;
  // Contain the original artwork so faces and printed titles are never cropped.
  const scale = Math.min(boxWidth / image.naturalWidth, boxHeight / image.naturalHeight);
  const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
  const left = x + (boxWidth - width) / 2, top = y + (boxHeight - height) / 2;
  context.save(); context.beginPath(); context.roundRect(left, top, width, height, 8); context.clip();
  context.drawImage(image, left, top, width, height); context.restore();
}

function drawHeader(surface, model, subtitle, images) {
  const {context, width} = surface; drawBrand(context);
  if (model.kind === 'detail') {
    const image = images.get(model.poster), x = image ? 220 : 36, textWidth = width - x - 36;
    drawPoster(context, image, 36, 66);
    const lines = drawLines(context, model.title, x, 145, textWidth, {size:38, weight:800, leading:44});
    drawText(context, fitText(context, subtitle, textWidth), x, 180 + Math.max(0, lines - 1) * 44,
      {color:COLORS.muted});
  } else {
    drawText(context, fitText(context, subtitle, width - 72, 13), 36, 109 + headerOffset(model),
      {size:13, color:COLORS.muted});
  }
  context.fillStyle = COLORS.line; context.fillRect(36, 129 + headerOffset(model), width - 72, 1);
}

function drawFooter(surface, model, y, {ratingLegend=true}={}) {
  const {context, width, height} = surface; let left = 36, rowY = y;
  for (const item of ratingLegend ? [...bands, band(null)] : []) {
    const label = `${item.name} ${item.range}`; context.font = `400 10px ${FONT}`;
    const textWidth = context.measureText(label).width + 22;
    if (left + textWidth > width - 36) { left = 36; rowY += 23; }
    context.fillStyle = item.colour; roundRect(context, left, rowY - 8, 8, 8, 2);
    drawText(context, label, left + 14, rowY, {size:10, color:COLORS.muted}); left += textWidth + 14;
  }
  const shows = model.kind === 'compare' ? model.shows : [model];
  const sources = [...new Set(shows.flatMap(show => ratingSources(show).split(' / ')).filter(Boolean))].join(' / ');
  const text = `${sources || 'Public'} episode ratings · Out of 10 · Averages exclude unrated episodes`;
  const lines = wrapText(context, text, width - 190, 11);
  lines.slice(0, 2).forEach((line, index) => drawText(context, fitText(context, line, width - 190, 11),
    36, height - 39 + index * 14, {size:11, color:COLORS.muted}));
  drawText(context, 'Couchside', width - 36, height - 39, {size:12, color:COLORS.gold, weight:700, align:'right'});
}

function drawCell(context, cell, x, y, width, height) {
  if (!cell) { drawText(context, '—', x + width / 2, y + height / 2 + 5, {size:15, color:'#666666', align:'center'}); return; }
  if (cell.plain) { drawText(context, cell.rating == null ? 'Unrated' : score(cell.rating), x + width / 2,
    y + height / 2 + 5, {size:13, weight:700, align:'center'}); return; }
  const item = band(cell.rating); context.fillStyle = item.colour; roundRect(context, x, y, width, height);
  drawText(context, formatScore(cell.rating), x + width / 2, y + (cell.count ? 18 : height / 2 + 5),
    {size:16, color:item.text, weight:750, align:'center'});
  if (cell.count) drawText(context, `${cell.count} eps`, x + width / 2, y + 33,
    {size:9, color:item.text, weight:500, align:'center'});
}

function drawContinuation(surface, model, part) {
  if (!part.continued) return;
  drawText(surface.context, fitText(surface.context, part.label, surface.width - 72, 12, 600),
    36, 160 + headerOffset(model), {size:12, color:COLORS.gold, weight:600});
}

function drawMatrix(surface, model, part, images) {
  const {context, width} = surface;
  const {matrix, top, headers, rows, columnWidth, labelWidth, headerHeight, rowHeight} = part;
  const subtitle = model.kind === 'compare'
    ? `${model.mode === 'all' ? 'All seasons · Season averages' : 'Selected seasons · Episode ratings'} · Shows in ${model.inverted ? 'columns' : 'rows'}`
    : `${yearLabel(model)}${scopeLabel(model)} · Grid · Seasons in ${model.inverted ? 'columns' : 'rows'}`;
  drawHeader(surface, model, subtitle, images); drawContinuation(surface, model, part);
  drawText(context, matrix.axis, 36, top + 25, {size:12, color:COLORS.muted});
  headers.forEach((header, index) => {
    const x = 36 + labelWidth + index * (columnWidth + 8), textX = x + columnWidth / 2;
    drawPoster(context, images.get(header.poster), x + (columnWidth - POSTER.width) / 2, top + 8);
    drawLines(context, header.label, textX, top + (header.show ? 270 : 23), columnWidth - 16,
      {size:header.show ? 16 : 12, weight:header.show ? 650 : 400,
        color:header.show ? COLORS.text : COLORS.muted, align:'center'});
    if (header.sub) drawText(context, fitText(context, header.sub, columnWidth - 16, 12),
      textX, top + 310, {size:12, color:COLORS.muted, align:'center'});
  });
  rows.forEach((row, index) => {
    const y = top + headerHeight + index * rowHeight;
    if (row.mean) { context.fillStyle = COLORS.line; context.fillRect(36, y - 4, width - 72, 1); }
    const image = images.get(row.poster), x = image ? 212 : 36, textWidth = labelWidth - (image ? 191 : 15);
    drawPoster(context, image, 36, y + 10);
    drawLines(context, row.label, x, y + (row.show ? 126 : 23), textWidth,
      {size:row.show ? 16 : 13, weight:row.mean || row.show ? 650 : 500, color:row.show || row.mean ? COLORS.text : COLORS.muted});
    if (row.sub) drawText(context, fitText(context, row.sub, textWidth, 12), x, y + 166, {size:12, color:COLORS.muted});
    row.cells.slice(part.columnStart, part.columnStart + headers.length).forEach((cell, cellIndex) =>
      drawCell(context, cell, 36 + labelWidth + cellIndex * (columnWidth + 8),
        y + (part.showRows ? (rowHeight - 40) / 2 : 4), columnWidth, 40));
  });
  drawFooter(surface, model, part.bottom + 39);
}

function drawWrapped(surface, model, part, images) {
  const {context, width} = surface;
  drawHeader(surface, model, `${yearLabel(model)}${scopeLabel(model)} · Wrapped episode ratings`, images);
  drawContinuation(surface, model, part); let top = part.top;
  for (const section of part.sections) {
    drawText(context, `${seasonName(section.season)}${section.continued ? ' · Continued' : ''}`,
      36, top + 22, {size:18, weight:650});
    drawText(context, `${formatScore(section.average)} average`, width - 36, top + 22,
      {size:13, color:COLORS.muted, align:'right'});
    section.episodes.forEach((episode, index) => {
      const x = 36 + (index % 14) * 62, y = top + 45 + Math.floor(index / 14) * 76;
      drawText(context, `E${episode.number}`, x + 27, y + 11, {size:11, color:COLORS.muted, align:'center'});
      drawCell(context, {rating:episode.rating}, x, y + 22, 54, 38);
    }); top += section.height;
  }
  if (!part.sections.length) drawText(context, 'No episodes yet.', 36, top + 30, {color:COLORS.muted});
  drawFooter(surface, model, Math.max(top + 21, surface.height - 91));
}

function drawList(surface, model, part, images) {
  const {context, width} = surface;
  drawHeader(surface, model, `${yearLabel(model)}${scopeLabel(model)} · Episode list · ${model.episodes.length} episodes`, images);
  drawContinuation(surface, model, part);
  part.episodes.forEach((episode, index) => {
    const y = part.top + index * part.rowHeight;
    context.fillStyle = COLORS.line; context.fillRect(36, y + part.rowHeight - 6, width - 72, 1);
    drawText(context, episodeCode(episode), 36, y + 30, {size:12, color:COLORS.muted, weight:650});
    drawLines(context, episode.name || 'Episode', 132, y + 25, 590, {size:16, weight:600, leading:19});
    const meta = `${episode.airdate || 'Air date to be announced'}${episode.runtime ? ' · ' + episode.runtime + ' min' : ''}`;
    drawText(context, fitText(context, meta, 590, 11), 132, y + 64, {size:11, color:COLORS.muted});
    drawCell(context, {rating:episode.rating}, width - 110, y + 14, 74, 38);
  });
  if (!part.episodes.length) drawText(context, 'No episodes yet.', 36, part.top + 30, {color:COLORS.muted});
  drawFooter(surface, model, surface.height - 91);
}

function drawChartAxes(surface, plot, top) {
  const {context} = surface, x = 82, raw = {top:36, bottom:244}, trend = {top:338, bottom:426};
  drawText(context, 'Episode ratings', x, top + 17, {size:13, color:COLORS.muted, weight:600});
  drawText(context, '5-episode average', x, top + 317, {size:13, color:COLORS.muted, weight:600});
  drawText(context, 'Within each season', x + 144, top + 317, {size:12, color:COLORS.muted});
  for (const row of [raw, trend]) {
    let previous = -Infinity;
    for (const value of plot.ticks) {
      const y = top + row.bottom - (value - plot.low) * (row.bottom - row.top) / (10 - plot.low);
      context.strokeStyle = '#ffffff12'; context.lineWidth = 1;
      context.beginPath(); context.moveTo(x, y); context.lineTo(x + plot.width, y); context.stroke();
      if (Math.abs(y - previous) >= 18 || value === 10) {
        drawText(context, value.toFixed(Number.isInteger(value * 2) ? 1 : 2), x - 12, y + 4,
          {size:11, color:COLORS.muted, align:'right'}); previous = y;
      }
    }
  }
  const axis = timelineAxis(plot);
  for (const [ticks, color] of [[axis.seasonTicks, '#ffffff30'], [axis.episodeTicks, '#ffffff0e']]) for (const point of ticks) {
    context.strokeStyle = color; context.beginPath(); context.moveTo(x + point.x, top + raw.top);
    context.lineTo(x + point.x, top + axis.baseline); context.stroke();
  }
  for (const label of axis.labels) drawText(context, label.text.replace(/\bS((?:19|20)\d{2})\b/g, '$1'),
    x + label.x, top + label.y, {size:12, color:COLORS.muted, weight:label.kind === 'season' ? 650 : 400,
      align:label.anchor === 'start' ? 'left' : label.anchor === 'end' ? 'right' : 'center'});
}

function drawTimeline(surface, model, part, images, createPath) {
  const {context} = surface;
  drawHeader(surface, model, `${yearLabel(model)}${scopeLabel(model)} · Episode ratings`, images);
  drawContinuation(surface, model, part);
  const plot = part.global && timelineModel(part.episodes, null, surface.width - 72);
  if (!plot) {
    drawText(context, 'These episodes have not been rated yet.', 36, part.global ? part.top + 60 : 400,
      {color:COLORS.muted}); drawFooter(surface, model, surface.height - 91); return;
  }
  const points = new Map(part.global.series[0].points.map(point => [point.id, point]));
  const trends = new Map(part.global.series[0].trend.flat().map(point => [point.id, point]));
  plot.low = part.global.low; plot.ticks = part.global.ticks;
  for (const point of plot.series[0].points) point.y = points.get(point.id)?.y ?? null;
  // Keep the original window at a continuation boundary, rather than averaging a cropped season.
  for (const point of plot.series[0].trend.flat()) {
    const original = trends.get(point.id);
    if (original) { point.rating = original.rating; point.y = original.y; }
  }
  drawChartAxes(surface, plot, part.top);
  context.save(); context.translate(82, part.top); context.strokeStyle = COLORS.muted; context.lineWidth = 1.25;
  for (const run of plot.series[0].runs) context.stroke(createPath(smoothPath(run)));
  for (const point of plot.series[0].points.filter(point => point.y != null)) {
    context.fillStyle = band(point.rating).colour; context.beginPath();
    context.arc(point.x, point.y, Math.max(1.75, Math.min(4, plot.spacing * .45)), 0, Math.PI * 2); context.fill();
  }
  context.strokeStyle = COLORS.gold; context.lineWidth = 2.6;
  for (const run of plot.series[0].trend) {
    context.stroke(createPath(smoothPath(run)));
    if (run.length === 1) { context.fillStyle = COLORS.gold; context.beginPath(); context.arc(run[0].x, run[0].y, 3, 0, Math.PI * 2); context.fill(); }
  }
  context.restore(); drawFooter(surface, model, surface.height - 91);
}

function encodePNG(canvas) {
  return new Promise((resolve, reject) => {
    try { canvas.toBlob(blob => blob ? resolve(blob) : reject(Error('The browser could not save this image. Please try again.')), 'image/png'); }
    catch { reject(Error('The image could not be saved. The browser or image host may be blocking image export.')); }
  });
}

export async function renderRatingSnapshot(model, images, {
  createCanvas=() => document.createElement('canvas'), createPath=value => new Path2D(value),
}={}) {
  const pages = [];
  for (const part of planRatingSnapshot(model)) {
    const surface = canvasSurface(part, createCanvas);
    try {
      if (part.kind === 'matrix') drawMatrix(surface, model, part, images);
      else if (part.kind === 'comparison-timeline') drawComparisonTimeline(surface, model, part, images,
        {drawText, drawPoster, wrapText, fitText, drawHeader, drawFooter, exportColors:COLORS, createPath});
      else if (part.kind === 'wrapped') drawWrapped(surface, model, part, images);
      else if (part.kind === 'timeline') drawTimeline(surface, model, part, images, createPath);
      else drawList(surface, model, part, images);
      const blob = await encodePNG(surface.canvas);
      pages.push({blob, width:surface.width * 2, height:surface.height * 2, label:part.label});
    } finally {
      // Release the expensive backing bitmap even when drawing or encoding fails.
      surface.canvas.width = surface.canvas.height = 1;
    }
  }
  return pages;
}

function snapshotName(model) {
  const title = model.kind === 'compare' ? model.shows.map(show => show.name).join(' × ') : model.title;
  const suffix = model.kind === 'compare' ? `${model.view === 'timeline' ? 'timeline-' : ''}${model.mode === 'all' ? 'all-seasons' : 'single-season'}` : model.view;
  const slug = String(title || 'ratings').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 140) || 'ratings';
  return {title, base:`couchside-${slug}-${suffix}`};
}

// The clone runs before the first await: a slow image can never capture a later view or order.
export async function prepareRatingSnapshot(model, {loadImages=loadSnapshotImages, ...renderOptions}={}) {
  const captured = structuredClone(model), {title, base} = snapshotName(captured);
  const images = await loadImages(captured), pages = await renderRatingSnapshot(captured, images, renderOptions);
  pages.forEach((page, index) => { page.filename = `${base}${pages.length > 1 ? '-part-' + String(index + 1).padStart(2, '0') : ''}.png`; });
  const blob = pages.length > 1 ? await pngArchive(pages) : pages[0].blob;
  return {model:captured, title, pages, blob, filename:`${base}${pages.length > 1 ? '-all-parts.zip' : '.png'}`};
}

export async function downloadRatingSnapshot(model) {
  const snapshot = await prepareRatingSnapshot(model);
  const url = URL.createObjectURL(snapshot.blob), link = document.createElement('a');
  link.href = url; link.download = snapshot.filename; link.rel = 'noopener';
  document.body.append(link);
  try { link.click(); } finally {
    link.remove();
    // Safari may read the URL after the click handler returns. Keep it alive briefly.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
  return snapshot;
}

// PNG already has compression; ZIP's stored format gathers all parts without another dependency.
const CRC_TABLE = Uint32Array.from({length:256}, (_, value) => {
  let crc = value;
  for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
  return crc >>> 0;
});
const crc32 = bytes => {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 255] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
};

export async function pngArchive(pages, now=new Date()) {
  if (pages.length > 65535) throw Error('There are too many image parts to package in one download.');
  const encoder = new TextEncoder(), files = [], central = [];
  const year = Math.max(1980, Math.min(2107, now.getFullYear()));
  const date = ((year - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
  const time = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2);
  let offset = 0;
  for (const page of pages) {
    const name = encoder.encode(page.filename), bytes = new Uint8Array(await page.blob.arrayBuffer()), crc = crc32(bytes);
    if (offset + bytes.length + 30 + name.length > 0xffffffff) throw Error('These images are too large to package in one download.');
    const header = new Uint8Array(30 + name.length), view = new DataView(header.buffer);
    view.setUint32(0, 0x04034b50, true); view.setUint16(4, 20, true); view.setUint16(6, 0x0800, true);
    view.setUint16(10, time, true); view.setUint16(12, date, true); view.setUint32(14, crc, true);
    view.setUint32(18, bytes.length, true); view.setUint32(22, bytes.length, true); view.setUint16(26, name.length, true);
    header.set(name, 30); files.push(header, page.blob);
    const directory = new Uint8Array(46 + name.length), entry = new DataView(directory.buffer);
    entry.setUint32(0, 0x02014b50, true); entry.setUint16(4, 20, true); entry.setUint16(6, 20, true);
    entry.setUint16(8, 0x0800, true); entry.setUint16(12, time, true); entry.setUint16(14, date, true);
    entry.setUint32(16, crc, true); entry.setUint32(20, bytes.length, true); entry.setUint32(24, bytes.length, true);
    entry.setUint16(28, name.length, true); entry.setUint32(42, offset, true); directory.set(name, 46);
    central.push(directory); offset += header.length + bytes.length;
  }
  const size = central.reduce((sum, bytes) => sum + bytes.length, 0), end = new Uint8Array(22), view = new DataView(end.buffer);
  view.setUint32(0, 0x06054b50, true); view.setUint16(8, pages.length, true); view.setUint16(10, pages.length, true);
  view.setUint32(12, size, true); view.setUint32(16, offset, true);
  return new Blob([...files, ...central, end], {type:'application/zip'});
}
