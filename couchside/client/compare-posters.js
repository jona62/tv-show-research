import { comparisonPosterSources, displayPoster } from './show-artwork.js';

// Keep decoded posters through comparison redraws, as the app's title cards do.
export function createComparisonPosters() {
  const kept = new Map();
  let disposed = false;

  function create(show) {
    const art = document.createElement('div');
    art.className = 'compare-card-art';
    const box = document.createElement('span');
    box.className = 'compare-poster'; box.setAttribute('role', 'img');
    const name = document.createElement('span');
    name.className = 'compare-poster-name'; name.setAttribute('aria-hidden', 'true');
    box.append(name); art.append(box);
    const sources = comparisonPosterSources(show);
    const entry = { art, box, name, sources, limited: displayPoster(show.art) !== show.art,
      failed: new Set(), images: new Map(), stopped: false };
    entry.load = url => {
      if (disposed || entry.stopped || entry.images.has(url)) return;
      const image = new Image();
      image.className = `compare-poster-image is-loading${url === show.art ? ' compare-poster-full' : ''}`;
      image.alt = ''; image.loading = 'lazy'; image.decoding = 'async';
      image.crossOrigin = 'anonymous'; image.referrerPolicy = 'no-referrer';
      const failed = () => {
        image.onload = image.onerror = null; image.remove(); entry.images.delete(url);
        if (!entry.stopped) entry.failed.add(url);
        box.classList.toggle('has-image', [...entry.images.values()].some(img => !img.classList.contains('is-loading')));
        const next = entry.sources.find(source => !entry.failed.has(source));
        if (next && !entry.stopped) entry.load(next);
      };
      image.onerror = failed;
      image.onload = () => {
        if (disposed || entry.stopped) return;
        if (!image.naturalWidth || !image.naturalHeight) { failed(); return; }
        image.classList.remove('is-loading'); entry.failed.delete(url); box.classList.add('has-image');
      };
      entry.images.set(url, image); box.append(image); image.src = url;
    };
    entry.stop = () => {
      entry.stopped = true;
      for (const image of entry.images.values()) image.onload = image.onerror = null;
      entry.images.clear(); entry.failed.clear();
    };
    return entry;
  }

  const retry = () => {
    for (const entry of kept.values()) for (const url of entry.failed) entry.load(url);
  };
  window.addEventListener('online', retry);
  return {
    paint(content, shows) {
      if (disposed) return;
      const ids = new Set(shows.map(show => show.id));
      for (const [id, entry] of kept) if (!ids.has(id)) { entry.stop(); kept.delete(id); }
      for (const show of shows) {
        const placeholder = content.querySelector(`[data-show="${show.id}"] .compare-card-art`);
        if (!placeholder) continue;
        const sources = comparisonPosterSources(show);
        let entry = kept.get(show.id);
        if (entry && (entry.sources.length !== sources.length || entry.sources.some((url, index) => url !== sources[index]))) {
          entry.stop(); kept.delete(show.id); entry = null;
        }
        if (!entry) { entry = create(show); kept.set(show.id, entry); }
        entry.name.textContent = show.name;
        entry.box.setAttribute('aria-label', `${show.name} poster`);
        placeholder.replaceWith(entry.art);
        // TVmaze's matching card image is sufficient here; its original is only
        // a failure fallback. Other providers retain their existing preview.
        if (entry.limited) {
          const source = entry.sources.find(url => !entry.failed.has(url));
          if (source) entry.load(source);
        } else for (const source of entry.sources) if (!entry.failed.has(source)) entry.load(source);
      }
    },
    dispose() {
      disposed = true; window.removeEventListener('online', retry);
      for (const entry of kept.values()) entry.stop();
      kept.clear();
    },
  };
}
