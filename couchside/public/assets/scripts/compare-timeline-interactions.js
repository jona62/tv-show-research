import { nearestRatingPoint } from './episode-timeline.js?v=803e207689055be8';
import { band, esc, html, ratingSource, score } from './ratings.js?v=2a0509d86dd759f5';
import { episodeCode, seasonName } from './rating-views.js?v=2168d19db732fbe1';

const plain = value => new DOMParser().parseFromString(value || '', 'text/html').body.textContent || '';

// Multiple shows contribute samples to the same SVG. The native nearest-point
// search requires x order; at identical positions prefer the last painted show.
export function comparisonPointerSamples(node) {
  return [...node.querySelectorAll('.ratings-point-hit[data-episode]')].map((target, index) => {
    const dot = target.querySelector('.ratings-point');
    return { target, index, x: Number(dot?.getAttribute('cx')), y: Number(dot?.getAttribute('cy')) };
  }).filter(point => Number.isFinite(point.x) && Number.isFinite(point.y)).sort((a, b) => a.x - b.x || b.index - a.index);
}

function tooltip(host) {
  const tip = document.createElement('div'); tip.className = 'ratings-tooltip'; tip.id = 'compare-ratings-hover';
  tip.setAttribute('role', 'tooltip'); tip.hidden = true; host.append(tip);
  let active, hideTimer;
  const hide = () => {
    clearTimeout(hideTimer); active?.removeAttribute('aria-describedby'); active = null; tip.hidden = true;
  };
  const leave = () => {
    clearTimeout(hideTimer);
    if (active && active === document.activeElement) return;
    hideTimer = setTimeout(hide, 150);
  };
  const position = () => {
    if (!active?.isConnected) { hide(); return; }
    tip.style.maxHeight = '';
    const bounds = active.getBoundingClientRect(), width = tip.offsetWidth;
    let height = tip.offsetHeight, left = Math.max(12, Math.min(window.innerWidth - width - 12, bounds.left + bounds.width / 2 - width / 2));
    let top = bounds.top - height - 12;
    if (top < 12) {
      if (bounds.bottom + height + 24 <= window.innerHeight) top = bounds.bottom + 12;
      else if (bounds.right + width + 24 <= window.innerWidth) { left = bounds.right + 12; top = window.innerHeight - height - 12; }
      else if (bounds.left - width - 24 >= 0) { left = bounds.left - width - 12; top = window.innerHeight - height - 12; }
      else {
        const above = Math.max(0, bounds.top - 24), below = Math.max(0, window.innerHeight - bounds.bottom - 24);
        tip.style.maxHeight = `${Math.max(1, above, below)}px`; height = tip.offsetHeight;
        top = above > below ? bounds.top - height - 12 : bounds.bottom + 12;
      }
    }
    tip.style.left = `${left}px`; tip.style.top = `${Math.max(12, top)}px`;
  };
  const show = (target, episode, showName) => {
    hide(); active = target;
    const rating = band(episode.rating), summary = plain(episode.summary).trim(), isEpisode = Boolean(episode.number);
    const details = isEpisode ? summary || 'No episode description available.'
      : episode.count != null ? `${episode.ratedCount} rated of ${episode.count} episodes` : '';
    html(tip, `${isEpisode && episode.image ? `<img src="${esc(episode.image)}" alt="" loading="lazy">` : ''}<div class="ratings-tooltip-body"><span class="ratings-tooltip-code">${esc(showName)} · ${isEpisode ? episodeCode(episode) : seasonName(episode.season)}</span><b>${esc(episode.name || (isEpisode ? 'Episode' : 'Season average'))}</b><div class="ratings-tooltip-score"><strong style="background:${rating.colour};color:${rating.text}">${score(episode.rating)}</strong><span>${rating.name}<small>${episode.rating == null ? 'Awaiting audience ratings' : `out of 10 on ${esc(ratingSource(episode))}${episode.rating_votes ? ' · ' + Number(episode.rating_votes).toLocaleString() + ' votes' : ''}`}</small></span></div>${details ? `<p class="ratings-tooltip-summary">${esc(details)}</p>` : ''}</div>`);
    tip.hidden = false; target.setAttribute('aria-describedby', tip.id); position();
  };
  const scrolled = event => {
    if (tip.contains(event.target)) return;
    const viewport = active?.closest('.ratings-chart-wrap,.ratings-grid-scroll'), point = active?.getBoundingClientRect(), bounds = viewport?.getBoundingClientRect();
    if (active === document.activeElement && point && point.bottom > 0 && point.top < window.innerHeight
        && (!bounds || point.right > bounds.left && point.left < bounds.right && point.bottom > bounds.top && point.top < bounds.bottom)) position();
    else hide();
  };
  const escape = event => { if (event.key === 'Escape' && active) { event.preventDefault(); event.stopPropagation(); hide(); } };
  const outside = event => { if (active && !tip.contains(event.target) && !active.contains(event.target)) hide(); };
  tip.onpointerenter = () => clearTimeout(hideTimer); tip.onpointerleave = leave;
  host.addEventListener('keydown', escape); host.addEventListener('scroll', scrolled, true); window.addEventListener('resize', position);
  window.addEventListener('scroll', scrolled, { passive: true }); document.addEventListener('pointerdown', outside);
  return { show, hide, leave, dispose() {
    hide(); tip.remove(); host.removeEventListener('keydown', escape); host.removeEventListener('scroll', scrolled, true); window.removeEventListener('resize', position);
    window.removeEventListener('scroll', scrolled); document.removeEventListener('pointerdown', outside);
  } };
}

function revealPoint(target) {
  const viewport = target.closest('.ratings-chart-wrap,.ratings-grid-scroll'); if (!viewport) return;
  const point = target.getBoundingClientRect(), bounds = viewport.getBoundingClientRect();
  if (point.left < bounds.left) viewport.scrollLeft -= bounds.left - point.left + 8;
  else if (point.right > bounds.right) viewport.scrollLeft += point.right - bounds.right + 8;
}

export function bindComparisonMatrix(node, matrix, model, tipHost) {
  const targets = [...(node?.querySelectorAll('.rating-cell[data-cell]') || [])];
  if (!targets.length) return () => {};
  const tip = tooltip(tipHost), titles = new Map();
  const seasons = [...new Set(model.shows.flatMap(show => show.episodes.map(episode => episode.season)))].sort((a, b) => a - b);
  for (const target of targets) {
    const [row, column] = target.dataset.cell.split(':').map(Number), cell = matrix.rows[row]?.cells[column];
    const show = model.shows[model.inverted ? column : row];
    if (!cell || !show) continue;
    const season = cell.episode?.season ?? seasons[model.inverted ? row : column];
    let sample = cell.episode;
    if (!sample) {
      const episodes = show.episodes.filter(episode => episode.season === season);
      sample = { season, name: 'Season average', rating: cell.rating, count: cell.count, ratedCount: cell.ratedCount,
        rating_source: [...new Set(episodes.filter(episode => episode.rating != null).map(ratingSource).filter(Boolean))].join(' / ') };
    }
    target.dataset.showId = show.id; target.dataset.season = season;
    titles.set(target, target.getAttribute('title')); target.removeAttribute('title');
    const showDetails = () => tip.show(target, sample, show.name);
    target.onpointerenter = event => { if (event.pointerType !== 'touch') showDetails(); }; target.onpointerleave = tip.leave;
    target.onfocus = () => { revealPoint(target); showDetails(); }; target.onblur = tip.hide;
    target.onclick = event => { event.stopPropagation(); target.focus({ preventScroll: true }); showDetails(); };
    target.onkeydown = event => {
      if (['Enter', ' '].includes(event.key)) { event.preventDefault(); event.stopPropagation(); showDetails(); }
    };
  }
  return () => {
    tip.dispose();
    for (const [target, title] of titles) {
      target.onpointerenter = target.onpointerleave = target.onfocus = target.onblur = target.onclick = target.onkeydown = null;
      target.removeAttribute('data-show-id'); target.removeAttribute('data-season');
      if (title != null) target.setAttribute('title', title);
    }
  };
}

export function bindComparisonTimeline(node, model, tipHost) {
  const svg = node.querySelector('.ratings-timeline'); if (!svg) return () => {};
  const tip = tooltip(tipHost), samples = comparisonPointerSamples(svg), activate = new Map();
  const shows = new Map(model.shows.map(show => [show.id, { ...show, episodesById: new Map(show.episodes.map(episode => [episode.id, episode])) }]));
  let hovered, frame, down, cancelled = false;
  for (const { target } of samples) {
    const show = shows.get(Number(target.dataset.showId)), episode = show?.episodesById.get(Number(target.dataset.episode));
    if (!episode) continue;
    target.onpointerenter = () => tip.show(target, episode, show.name); target.onpointerleave = tip.leave;
    target.onfocus = () => { revealPoint(target); tip.show(target, episode, show.name); }; target.onblur = tip.hide;
    activate.set(target, () => { target.focus({ preventScroll: true }); tip.show(target, episode, show.name); });
    target.onkeydown = event => {
      if (['Enter', ' '].includes(event.key)) { event.preventDefault(); tip.show(target, episode, show.name); }
    };
  }
  const nearest = event => {
    const matrix = svg.getScreenCTM(); if (!matrix) return null;
    const centre = value => Number.isInteger(value) ? value + .5 : value;
    const point = new DOMPoint(centre(event.clientX), centre(event.clientY)).matrixTransform(matrix.inverse());
    return nearestRatingPoint(samples, point.x, point.y)?.target;
  };
  const clear = () => { cancelAnimationFrame(frame); hovered?.classList.remove('is-hovered'); hovered = null; tip.leave(); };
  svg.onpointermove = event => {
    if (event.pointerType === 'touch') return;
    cancelAnimationFrame(frame); frame = requestAnimationFrame(() => {
      if (!svg.isConnected) return;
      const target = nearest(event); if (target === hovered) return;
      hovered?.classList.remove('is-hovered'); hovered = target;
      if (target) { target.classList.add('is-hovered'); target.onpointerenter?.(); } else tip.leave();
    });
  };
  svg.onpointerleave = clear;
  svg.onpointercancel = () => { cancelled = true; down = null; clear(); };
  svg.onpointerdown = event => { cancelled = false; down = { x: event.clientX, y: event.clientY, target: nearest(event) }; };
  svg.onclick = event => {
    event.stopPropagation();
    if (cancelled) { cancelled = false; return; }
    if (down && Math.hypot(event.clientX - down.x, event.clientY - down.y) > 8) { down = null; return; }
    const target = down?.target || nearest(event); down = null; clear(); activate.get(target)?.();
  };
  return () => { clear(); tip.dispose(); svg.onpointermove = svg.onpointerleave = svg.onpointercancel = svg.onpointerdown = svg.onclick = null; };
}
