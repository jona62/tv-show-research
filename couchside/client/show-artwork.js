// The same address warms and displays a show's background. The server chooses
// TMDB or TVmaze; the browser and service worker keep its readable image bytes.
export function backdropURL(id) {
  return Number.isInteger(id) && id > 0 && id <= 999999999 ? `/api/backdrop?id=${id}` : '';
}

export function createBackdropPrefetcher({ makeImage = () => new Image(), now = Date.now,
  connection = () => navigator.connection, online = () => navigator.onLine !== false,
  schedule = setTimeout, cancel = clearTimeout } = {}) {
  const active = new Set(), waiting = [], kept = new Map();
  const DAY = 86400000, RETRY = 30000;
  function drain() {
    while (active.size < 2 && waiting.length) {
      const id = waiting.shift(), img = makeImage();
      active.add(id);
      let finished = false, timer;
      const done = loaded => {
        if (finished) return;
        finished = true;
        cancel(timer);
        img.onload = img.onerror = null;
        active.delete(id);
        kept.delete(id);
        kept.set(id, now() + (loaded ? DAY : RETRY));
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
      img.src = backdropURL(id);
    }
  }
  return id => {
    const net = connection();
    if (!backdropURL(id) || !online() || net?.saveData || ['slow-2g', '2g'].includes(net?.effectiveType)) return;
    if (active.has(id) || kept.get(id) > now()) return;
    const queued = waiting.indexOf(id);
    if (queued >= 0) waiting.splice(queued, 1);
    // Only the latest few intentional hovers wait; sweeping over a row is cheap.
    waiting.push(id);
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
