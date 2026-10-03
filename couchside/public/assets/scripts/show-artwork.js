// Small cards use the provider's matching display image; snapshots keep show.art.
// Restrict rewriting to genuine raster provider paths, leaving other hosts alone.
export function displayPoster(source) {
  if (typeof source !== 'string' || !source) return '';
  const match = source.match(/^https:\/\/static\.tvmaze\.com\/uploads\/images\/(?:original_untouched|original|o)\/(\d{1,9}\/\d{1,12}\.(?:jpg|jpeg|png|webp))$/);
  return match ? `https://static.tvmaze.com/uploads/images/medium_portrait/${match[1]}` : source;
}

export function comparisonPosterSources(show) {
  const artwork = displayPoster(show.art);
  return [...new Set([artwork && artwork !== show.art ? artwork : show.poster, show.poster, show.art].filter(Boolean))];
}

// Intent and the title page choose the same bounded provider width. On wider or
// denser screens retain w1280; a small 1x viewport can request TMDB's lighter w780.
export function backdropURL(id, { width = globalThis.innerWidth, scale = globalThis.devicePixelRatio || 1 } = {}) {
  if (!Number.isInteger(id) || id <= 0 || id > 999999999) return '';
  const size = Number.isFinite(width) ? (width * scale <= 780 ? 780 : 1280) : null;
  return `/api/backdrop?id=${id}${size ? `&w=${size}` : ''}`;
}

export function createBackdropPrefetcher({ makeImage = () => new Image(), now = Date.now,
  connection = () => navigator.connection, online = () => navigator.onLine !== false,
  schedule = setTimeout, cancel = clearTimeout } = {}) {
  const active = new Set(), waiting = [], kept = new Map();
  const DAY = 86400000, RETRY = 30000;
  function drain() {
    while (active.size < 2 && waiting.length) {
      const url = waiting.shift(), img = makeImage();
      active.add(url);
      let finished = false, timer;
      const done = loaded => {
        if (finished) return;
        finished = true;
        cancel(timer);
        img.onload = img.onerror = null;
        active.delete(url);
        kept.delete(url);
        kept.set(url, now() + (loaded ? DAY : RETRY));
        while (kept.size > 40) kept.delete(kept.keys().next().value);
        drain();
      };
      img.onload = () => done(true);
      img.onerror = () => done(false);
      // A stalled speculative request must not hold the queue indefinitely.
      timer = schedule(() => { img.removeAttribute('src'); done(false); }, 15000);
      img.alt = '';
      img.decoding = 'async';
      img.crossOrigin = 'anonymous';
      img.referrerPolicy = 'no-referrer';
      img.fetchPriority = 'low';
      img.src = url;
    }
  }
  return id => {
    const net = connection(), url = backdropURL(id);
    if (!url || !online() || net?.saveData || ['slow-2g', '2g'].includes(net?.effectiveType)) return;
    if (active.has(url) || kept.get(url) > now()) return;
    const queued = waiting.indexOf(url);
    if (queued >= 0) waiting.splice(queued, 1);
    // Only the latest few intentional hovers wait; sweeping over a row is cheap.
    waiting.push(url);
    if (waiting.length > 4) waiting.shift();
    drain();
  };
}

export function bindBackdropIntent(root, prefetch, { schedule = setTimeout, cancel = clearTimeout } = {}) {
  let hovered = null, timer;
  const cardAt = target => {
    const card = target?.closest?.('.card[data-id]');
    return card && !card.closest('[inert]') ? card : null;
  };
  const stop = () => { cancel(timer); hovered = null; };
  const over = event => {
    if (event.pointerType !== 'mouse') return;
    const card = cardAt(event.target);
    if (!card || card === cardAt(event.relatedTarget)) return;
    stop(); hovered = card;
    timer = schedule(() => { if (hovered?.isConnected) prefetch(Number(hovered.dataset.id)); }, 160);
  };
  const out = event => { if (hovered && cardAt(event.relatedTarget) !== hovered) stop(); };
  const focus = event => {
    const card = cardAt(event.target);
    if (card) { stop(); prefetch(Number(card.dataset.id)); }
  };
  root.addEventListener('pointerover', over, { passive: true });
  root.addEventListener('pointerout', out, { passive: true });
  root.addEventListener('focusin', focus);
  return () => {
    stop();
    root.removeEventListener('pointerover', over);
    root.removeEventListener('pointerout', out);
    root.removeEventListener('focusin', focus);
  };
}
