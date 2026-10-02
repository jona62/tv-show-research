import { createSnapshotImageLoader } from './snapshot-images.js?v=58ed772a708f7e6c';

const SAMPLE_WIDTH = 48, SAMPLE_HEIGHT = 72, MAX_CACHED_COLOURS = 64;
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
export const validPosterColour = value => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
const channels = colour => [1, 3, 5].map(offset => parseInt(colour.slice(offset, offset + 2), 16));
const hex = rgb => '#' + rgb.map(value => Math.round(clamp(value, 0, 255)).toString(16).padStart(2, '0')).join('');

function rgbToHsl(rgb) {
  const [r, g, b] = rgb.map(value => value / 255), high = Math.max(r, g, b), low = Math.min(r, g, b);
  const difference = high - low, lightness = (high + low) / 2;
  if (!difference) return [0, 0, lightness];
  const hue = high === r ? (g - b) / difference + (g < b ? 6 : 0)
    : high === g ? (b - r) / difference + 2 : (r - g) / difference + 4;
  return [hue * 60, difference / (1 - Math.abs(2 * lightness - 1)), lightness];
}

function hslToRgb([hue, saturation, lightness]) {
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const sector = ((hue % 360 + 360) % 360) / 60, second = chroma * (1 - Math.abs(sector % 2 - 1));
  const rgb = sector < 1 ? [chroma, second, 0] : sector < 2 ? [second, chroma, 0]
    : sector < 3 ? [0, chroma, second] : sector < 4 ? [0, second, chroma]
      : sector < 5 ? [second, 0, chroma] : [chroma, 0, second];
  return rgb.map(value => (value + lightness - chroma / 2) * 255);
}

function luminance(rgb) {
  return rgb.map(value => {
    value /= 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
}

function readableHsl(hue, saturation, lightness = .63) {
  saturation = clamp(saturation, .45, .8);
  let rgb = hslToRgb([hue, saturation, lightness]);
  // Preserve the poster's hue while making thin lines visible on #181818.
  while ((luminance(rgb) + .05) / (luminance([24, 24, 24]) + .05) < 4.5 && lightness < .82) {
    lightness += .02; rgb = hslToRgb([hue, saturation, lightness]);
  }
  return hex(rgb);
}

function hueDistance(a, b) { return Math.min(Math.abs(a - b), 360 - Math.abs(a - b)); }

/** Choose one represented chromatic family instead of averaging unrelated colours. */
export function posterColourFromPixels({ data, width, height } = {}) {
  if (!data || !Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 ||
      data.length !== width * height * 4) return null;
  const bins = Array.from({ length: 36 }, () => ({ weight: 0, count: 0 })), pixels = [];
  for (let index = 0; index < data.length; index += 4) {
    const rgb = [data[index], data[index + 1], data[index + 2]], high = Math.max(...rgb) / 255;
    const low = Math.min(...rgb) / 255, saturation = high ? (high - low) / high : 0;
    if (data[index + 3] < 192 || high < .1 || low > .92 || saturation < .18) continue;
    const [hue] = rgbToHsl(rgb), weight = saturation ** 2 * Math.min(1, high * 2) * data[index + 3] / 255;
    const bin = Math.round(hue / 10) % 36;
    bins[bin].weight += weight; bins[bin].count++;
    pixels.push({ rgb, hue, weight });
  }
  if (pixels.length < Math.max(2, width * height * .015)) return null;
  let chosen = -1, maximum = 0;
  for (let bin = 0; bin < bins.length; bin++) {
    const neighbours = [bins[(bin + 35) % 36], bins[bin], bins[(bin + 1) % 36]];
    // A tiny bright logo cannot displace a colour spread through the poster.
    if (neighbours.reduce((sum, item) => sum + item.count, 0) < Math.max(2, pixels.length * .06)) continue;
    const weight = neighbours[1].weight + (neighbours[0].weight + neighbours[2].weight) * .65;
    if (weight > maximum) { maximum = weight; chosen = bin; }
  }
  if (chosen < 0) return null;
  const matching = pixels.filter(pixel => hueDistance(pixel.hue, chosen * 10) <= 20);
  const weight = matching.reduce((sum, pixel) => sum + pixel.weight, 0);
  if (!weight) return null;
  const rgb = [0, 1, 2].map(channel => matching.reduce((sum, pixel) => sum + pixel.rgb[channel] * pixel.weight, 0) / weight);
  const [hue, saturation] = rgbToHsl(rgb);
  return readableHsl(hue, saturation);
}

function sameTvmazeArtwork(first, second) {
  try {
    const a = new URL(first), b = new URL(second);
    const image = url => url.hostname === 'static.tvmaze.com' && url.protocol === 'https:'
      ? url.pathname.match(/^\/uploads\/images\/(?:medium_portrait|original_untouched)\/(\d+\/\d+\.jpg)$/)?.[1] : null;
    return Boolean(image(a) && image(a) === image(b));
  } catch { return false; }
}

export function createPosterColourLoader({
  loadImages = createSnapshotImageLoader({ timeoutMs: 8_000 }),
  createCanvas = () => document.createElement('canvas'),
} = {}) {
  const cache = new Map();
  return async function loadColour(show) {
    const artwork = show?.art || show?.poster;
    if (typeof artwork !== 'string' || !artwork.trim()) return null;
    let pending = cache.get(artwork);
    if (!pending) {
      const poster = show.poster && sameTvmazeArtwork(artwork, show.poster) ? show.poster : artwork;
      pending = (async () => {
        const images = await loadImages({ name: show.name, poster }), image = images.get(poster);
        if (!image?.naturalWidth || !image.naturalHeight) return null;
        const scale = Math.min(SAMPLE_WIDTH / image.naturalWidth, SAMPLE_HEIGHT / image.naturalHeight);
        const canvas = createCanvas();
        canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
        try {
          const context = canvas.getContext('2d', { willReadFrequently: true });
          if (!context) return null;
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          return posterColourFromPixels(context.getImageData(0, 0, canvas.width, canvas.height));
        } finally { canvas.width = canvas.height = 0; }
      })();
      cache.set(artwork, pending);
      while (cache.size > MAX_CACHED_COLOURS) cache.delete(cache.keys().next().value);
      pending.catch(() => { if (cache.get(artwork) === pending) cache.delete(artwork); });
    }
    try { return await pending; } catch { return null; }
  };
}

export const loadPosterColour = createPosterColourLoader();

/** This fallback applies only while artwork is unavailable or has no chromatic family. */
export function comparisonShowColour(showOrId) {
  if (showOrId && typeof showOrId === 'object') {
    if (validPosterColour(showOrId.colour)) return showOrId.colour.toLowerCase();
    if (validPosterColour(showOrId.posterColour)) return showOrId.posterColour.toLowerCase();
  }
  const id = Number(typeof showOrId === 'object' ? showOrId?.id : showOrId) || 0;
  let hash = Math.imul(id ^ (id >>> 16), 0x45d9f3b);
  hash = (hash ^ (hash >>> 16)) >>> 0;
  return readableHsl(hash % 360, .5 + (hash >>> 9) % 26 / 100, .63 + (hash >>> 17) % 11 / 100);
}

const distance = (first, second) => Math.hypot(...channels(first).map((value, index) => value - channels(second)[index]));

/** Resolve near-identical lines within the poster's hue family, independent of order. */
export function comparisonPosterColours(shows = []) {
  const result = new Map(), assigned = [];
  const sorted = [...shows].filter(show => Number.isInteger(show?.id) && show.id > 0).sort((a, b) => a.id - b.id);
  for (const show of sorted) {
    let colour = comparisonShowColour(show);
    if (!validPosterColour(show.colour) && assigned.some(other => distance(colour, other) < 42)) {
      const [hue, saturation] = rgbToHsl(channels(colour));
      let best = Math.min(...assigned.map(other => distance(colour, other)));
      for (const shift of [0, -8, 8, -14, 14]) for (const lightness of [.55, .7, .78, .6])
        for (const saturationShift of [0, -.15, .15]) {
          const candidate = readableHsl(hue + shift, saturation + saturationShift, lightness);
          const minimum = Math.min(...assigned.map(other => distance(candidate, other)));
          if (minimum > best) { best = minimum; colour = candidate; }
        }
    }
    result.set(show.id, colour); assigned.push(colour);
  }
  return result;
}
