const DEFAULT_TIMEOUT_MS = 12_000;
const MAX_CACHED_IMAGES = 32;

// A factory keeps browser dependencies replaceable for focused loader tests.
export function createSnapshotImageLoader({
  createImage = () => new Image(),
  createCanvas = () => document.createElement('canvas'),
  timeoutMs = DEFAULT_TIMEOUT_MS,
} = {}) {
  const cache = new Map();

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      let image;
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (image) image.onload = image.onerror = null;
        if (error) reject(error);
        else resolve(image);
      };
      const timer = setTimeout(() => finish(new Error(
        `The poster did not finish loading within ${timeoutMs / 1000} seconds. Please try again.`,
      )), timeoutMs);

      try {
        image = createImage();
        image.crossOrigin = 'anonymous';
        image.referrerPolicy = 'no-referrer';
        image.decoding = 'async';
        image.onerror = () => finish(new Error(
          'The image could not be loaded. Check the connection or the image host’s cross-origin settings.',
        ));
        image.onload = async () => {
          try {
            await image.decode();
          } catch {
            finish(new Error('The image could not be decoded. Please try again.'));
            return;
          }
          if (settled) return;
          if (!image.naturalWidth || !image.naturalHeight) {
            finish(new Error('The poster has no usable image dimensions. Please try again.'));
            return;
          }
          try {
            const canvas = createCanvas();
            canvas.width = canvas.height = 1;
            const context = canvas.getContext('2d');
            if (!context) throw new Error('Canvas is unavailable');
            context.drawImage(image, 0, 0, 1, 1);
            canvas.toDataURL('image/png');
          } catch {
            finish(new Error('The poster could not be saved. The browser or image host may be blocking image export.'));
            return;
          }
          finish();
        };
        image.src = url;
      } catch {
        finish(new Error('The browser could not start loading this poster. Please try again.'));
      }
    });
  }

  function cachedImage(url) {
    let pending = cache.get(url);
    if (!pending) {
      pending = loadImage(url);
      cache.set(url, pending);
      while (cache.size > MAX_CACHED_IMAGES) cache.delete(cache.keys().next().value);
      pending.catch(() => {
        if (cache.get(url) === pending) cache.delete(url);
      });
    }
    return pending;
  }

  return async function loadImages(model) {
    const shows = model.kind === 'compare' ? model.shows : [model];
    const requested = new Map();
    for (const show of shows) {
      const url = show.poster;
      if (typeof url !== 'string' || !url.trim() || requested.has(url)) continue;
      requested.set(url, show.name || show.title || 'this show');
    }
    const loaded = await Promise.all([...requested].map(async ([url, name]) => {
      try {
        return [url, await cachedImage(url)];
      } catch (error) {
        throw new Error(`Unable to load the poster for "${name}". ${error.message}`, { cause: error });
      }
    }));
    return new Map(loaded);
  };
}

const defaultLoader = createSnapshotImageLoader();

export async function loadSnapshotImages(model) {
  return defaultLoader(model);
}
