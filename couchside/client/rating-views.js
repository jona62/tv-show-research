import { average, band, esc, score } from './ratings.js';

export const seasonName = season => Number(season) >= 1900 ? `${season} season` : `Season ${season}`;
export const seasonCode = season => Number(season) >= 1900 ? String(season) : `S${season}`;
export const episodeCode = episode => `${seasonCode(episode.season)} E${episode.number}`;
const seasons = episodes => [...new Set(episodes.map(episode => episode.season))].sort((a, b) => a - b);

// Both the live tables and image export use these cells, including empty positions.
export function detailMatrix(model) {
  const selected = seasons(model.episodes), max = model.episodes.reduce((value, episode) => Math.max(value, episode.number), 1);
  const positions = new Map(model.episodes.map(episode => [`${episode.season}:${episode.number}`, episode]));
  const cellAt = (season, number) => {
    const episode = positions.get(`${season}:${number}`);
    return episode ? { rating: episode.rating, episode } : null;
  };
  const meanAt = season => ({ rating: average(model.episodes.filter(episode => episode.season === season)),
    label: `${seasonName(season)} average`, mean: true, plain: true });
  const numbers = Array.from({ length: max }, (_, index) => index + 1);
  return model.inverted ? {
    axis: 'Episode', caption: 'Episode ratings, seasons in columns', headers: selected.map(season => ({ label: seasonName(season) })),
    rows: [...numbers.map(number => ({ label: `E${number}`, cells: selected.map(season => cellAt(season, number)) })),
      ...(model.averages ? [{ label: 'Avg.', mean: true, cells: selected.map(meanAt) }] : [])],
  } : {
    axis: 'Season', caption: 'Episode ratings, seasons in rows',
    headers: [...numbers.map(number => ({ label: `E${number}` })), ...(model.averages ? [{ label: 'Avg.', mean: true }] : [])],
    rows: selected.map(season => ({ label: seasonCode(season), cells: [...numbers.map(number => cellAt(season, number)),
      ...(model.averages ? [meanAt(season)] : [])] })),
  };
}

export function compareMatrix(model) {
  const all = model.mode === 'all', max = all ? 1 : model.shows.reduce((largest, show) =>
    show.episodes.reduce((value, episode) => Math.max(value, episode.number), largest), 1);
  const samples = all ? seasons(model.shows.flatMap(show => show.episodes)) : Array.from({ length: max }, (_, index) => index + 1);
  const sampleLabel = sample => all ? seasonCode(sample) : `E${sample}`;
  const cellAt = (show, sample) => {
    if (all) {
      const selected = show.episodes.filter(episode => episode.season === sample);
      return selected.length ? { rating: average(selected), label: `${show.name}, ${seasonName(sample)} average`,
        count: selected.length, ratedCount: selected.filter(episode => episode.rating != null).length } : null;
    }
    const episode = show.episodes.find(item => item.number === sample);
    return episode ? { rating: episode.rating, episode, label: `${show.name}, ${episodeCode(episode)}` } : null;
  };
  const showHeader = show => ({ label: show.name, sub: all ? '' : show.season != null ? seasonName(show.season) : 'No episodes yet', show: true, poster: show.poster });
  // Overall averages weight each rated episode equally, rather than each season.
  const meanAt = show => ({ rating: average(show.episodes), label: `${show.name}, average episode rating${all
    ? ' across all seasons' : show.season != null ? ` in ${seasonName(show.season)}` : ''}`, mean: true, plain: true });
  return model.inverted ? {
    axis: all ? 'Season' : 'Episode', caption: `Comparison of ${all ? 'season averages' : 'episodes'}, shows in columns`,
    headers: model.shows.map(showHeader),
    rows: [...samples.map(sample => ({ label: sampleLabel(sample), cells: model.shows.map(show => cellAt(show, sample)) })),
      ...(model.averages ? [{ label: 'Avg.', mean: true, cells: model.shows.map(meanAt) }] : [])],
  } : {
    axis: 'Show', caption: `Comparison of ${all ? 'season averages' : 'episodes'}, shows in rows`,
    headers: [...samples.map(sample => ({ label: sampleLabel(sample) })), ...(model.averages ? [{ label: 'Avg.', mean: true }] : [])],
    rows: model.shows.map(show => ({ ...showHeader(show), cells: [...samples.map(sample => cellAt(show, sample)),
      ...(model.averages ? [meanAt(show)] : [])] })),
  };
}

function cellHTML(cell, row, column) {
  if (!cell) return '<span class="rating-empty" aria-label="No episode at this position">—</span>';
  const colour = band(cell.rating), label = cell.label || (cell.episode ? `${episodeCode(cell.episode)}: ${cell.episode.name}` : 'Average episode rating');
  const value = cell.rating == null ? 'unrated' : `${score(cell.rating)} out of 10`;
  const count = cell.count ? `, ${cell.ratedCount} rated of ${cell.count} episodes` : '';
  if (cell.plain) return `<span class="ratings-average" title="${esc(label)}, ${value}">${score(cell.rating)}</span>`;
  return `<button type="button" class="ratings-cell rating-cell${cell.mean ? ' mean-cell' : ''}${cell.count ? ' has-count' : ''}" style="background:${colour.colour};color:${colour.text}" title="${esc(label)}, ${value}${count}" aria-label="${esc(label)}, ${value}, ${colour.name}${count}" data-cell="${row}:${column}"${cell.episode ? ` data-episode="${cell.episode.id}"` : ''}><span class="rating-score">${cell.rating == null ? '—' : score(cell.rating)}</span>${cell.count ? `<small class="cell-count">${cell.count} eps</small>` : ''}</button>`;
}

export function ratingTableHTML(matrix) {
  const heading = (entry, row = false) => `<th scope="${row ? 'row' : 'col'}" class="${entry.show ? 'show-heading' : row ? 'ratings-season row-heading' : 'ratings-axis axis-heading'}${entry.mean ? ' mean-heading' : ''}"><span>${esc(entry.label)}</span>${entry.sub ? `<small>${esc(entry.sub)}</small>` : ''}</th>`;
  return `<div class="ratings-grid-scroll scroll-board" tabindex="0" role="region" aria-label="${esc(matrix.caption)}; scroll horizontally when needed"><table class="rating-table"><thead><tr><th scope="col" class="ratings-axis axis-heading">${esc(matrix.axis)}</th>${matrix.headers.map(entry => heading(entry)).join('')}</tr></thead><tbody>${matrix.rows.map((row, index) => `<tr${row.mean ? ' class="average-row"' : ''}>${heading(row, true)}${row.cells.map((cell, column) => `<td${cell?.mean ? ' class="mean-column"' : ''}>${cellHTML(cell, index, column)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
