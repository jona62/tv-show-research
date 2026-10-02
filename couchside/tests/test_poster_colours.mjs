import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { comparisonPosterColours, comparisonShowColour, createPosterColourLoader,
  posterColourFromPixels, validPosterColour } from '../client/poster-colours.js';

const pixels = (...entries) => {
  const data = entries.flatMap(([r, g, b, count = 1, alpha = 255]) => Array.from({ length: count }, () => [r, g, b, alpha]).flat());
  return { data: new Uint8ClampedArray(data), width: data.length / 4, height: 1 };
};
const channels = colour => [1, 3, 5].map(offset => parseInt(colour.slice(offset, offset + 2), 16));
const luminance = colour => channels(colour).map(value => {
  value /= 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
}).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
const contrast = colour => (luminance(colour) + .05) / (luminance('#181818') + .05);
const colourDistance = (a, b) => Math.hypot(...channels(a).map((value, index) => value - channels(b)[index]));

test('represented chromatic families survive dark backgrounds, neutral text and small bright accents', () => {
  const colour = posterColourFromPixels(pixels([2, 5, 3, 100], [20, 92, 40, 200], [245, 245, 245, 50], [240, 20, 20, 4]));
  const [r, g, b] = channels(colour);
  assert.ok(g > r * 1.4 && g > b * 1.4, 'Green field stays green, rather than brown RGB averaging or red logo');
  assert.ok(contrast(colour) >= 4.5, 'Dark poster colours become readable graph lines');
  const red = posterColourFromPixels(pixels([220, 20, 30, 80], [50, 60, 180, 50], [220, 200, 30, 10]));
  assert.ok(channels(red)[0] > channels(red)[2], 'Separate hue families do not average into purple');
});

test('actual Primal and Clone Wars poster histograms retain their distinct colour families', async () => {
  // Quantized samples preserve colour proportions without storing a poster image.
  const fixture = JSON.parse(await readFile(new URL('./fixtures/poster-colours.json', import.meta.url)));
  const primal = posterColourFromPixels(pixels(...fixture.primal.pixels));
  const cloneWars = posterColourFromPixels(pixels(...fixture.clonewars.pixels));
  const [r, g, b] = channels(primal), [cloneRed, cloneGreen, cloneBlue] = channels(cloneWars);
  assert.ok(g > r * 1.5 && g > b * 1.5, `Primal's green eyes and lettering are green, received ${primal}`);
  assert.ok(cloneRed > cloneGreen && cloneRed > cloneBlue, `Clone Wars' warm hue stays warm, received ${cloneWars}`);
  assert.ok(contrast(primal) >= 4.5 && contrast(cloneWars) >= 4.5);
});

test('transparent, grayscale, blank and malformed samples have no invented poster hue', () => {
  for (const sample of [pixels([100, 100, 100, 10]), pixels([0, 0, 0, 10]), pixels([255, 255, 255, 10]),
    pixels([10, 220, 50, 10, 0]), pixels([10, 220, 50, 1]), {}, { data: [1, 2, 3], width: 1, height: 1 }])
    assert.equal(posterColourFromPixels(sample), null);
});

test('fallback is deterministic, safe, legible and retains full-comparison identities', () => {
  const colours = Array.from({ length: 40 }, (_, index) => comparisonShowColour(index + 1));
  assert.equal(new Set(colours).size, 40);
  assert.ok(colours.every(colour => validPosterColour(colour) && contrast(colour) >= 4.5));
  assert.equal(comparisonShowColour(42184), comparisonShowColour('42184'));
  assert.equal(comparisonShowColour({ id: 42184, posterColour: '#66DC55' }), '#66dc55');
  assert.equal(comparisonShowColour({ id: 42184, posterColour: 'red;position:fixed' }), comparisonShowColour(42184));
  assert.equal(validPosterColour('#00ff00;background:red'), false);
  assert.equal(validPosterColour('#123'), false);
  assert.equal(validPosterColour(null), false);
});

test('nearly identical poster hues separate by tint while reordering and captured exports retain identities', () => {
  const shows = [{ id: 42184, posterColour: '#66dc55' }, { id: 563, posterColour: '#66dc55' },
    { id: 169, posterColour: '#d47e6e' }], original = structuredClone(shows);
  const colours = comparisonPosterColours(shows), reverse = comparisonPosterColours([...shows].reverse());
  assert.deepEqual([...colours], [...reverse]);
  assert.ok(colourDistance(colours.get(42184), colours.get(563)) >= 42);
  for (const id of [42184, 563]) {
    const [r, g, b] = channels(colours.get(id)); assert.ok(g > r && g > b, 'Both related lines remain green');
    assert.ok(contrast(colours.get(id)) >= 4.5);
  }
  const capture = shows.map(show => ({ ...show, colour: colours.get(show.id) }));
  assert.deepEqual([...comparisonPosterColours(capture)], [...colours]);
  assert.equal(comparisonShowColour(capture[0]), colours.get(42184));
  assert.deepEqual(shows, original);
  assert.equal(comparisonPosterColours([{ id: -1 }, { id: '42184' }, null]).size, 0);
});

function loaderHarness() {
  const requested = [], canvases = [], image = { naturalWidth: 1000, naturalHeight: 1500 };
  let error = false, finish;
  const loader = createPosterColourLoader({
    loadImages: async model => { requested.push(model); await new Promise(resolve => { finish = resolve; }); return new Map([[model.poster, image]]); },
    createCanvas() {
      const canvas = { getContext: () => ({ drawImage: (loaded, ...size) => { canvas.drawn = [loaded, ...size]; },
        getImageData: () => { if (error) throw Error('SecurityError'); return pixels([20, 200, 30, canvas.width * canvas.height]); } }) };
      canvases.push(canvas); return canvas;
    },
  });
  return { loader, requested, canvases, image, finish: () => finish(), fail: value => { error = value; } };
}

test('samples matching small artwork, shares concurrent cache and releases bounded canvases', async () => {
  const harness = loaderHarness(), show = { id: 42184, name: 'Primal',
    art: 'https://static.tvmaze.com/uploads/images/original_untouched/608/1521294.jpg',
    poster: 'https://static.tvmaze.com/uploads/images/medium_portrait/608/1521294.jpg' };
  const first = harness.loader(show), second = harness.loader({ ...show });
  assert.equal(harness.requested.length, 1); assert.equal(harness.requested[0].poster, show.poster);
  harness.finish(); const colour = await first;
  assert.equal(await second, colour); assert.equal(await harness.loader(show), colour);
  assert.equal(harness.requested.length, 1);
  assert.deepEqual(harness.canvases[0].drawn.slice(1), [0, 0, 48, 72]);
  assert.deepEqual([harness.canvases[0].width, harness.canvases[0].height], [0, 0]);
  assert.ok(contrast(colour) >= 4.5);
});

test('different artwork never samples the wrong thumbnail and blocked reads degrade safely with retry', async () => {
  const harness = loaderHarness(), show = { name: 'New artwork', art: 'https://static.tvmaze.com/uploads/images/original_untouched/608/1521294.jpg',
    poster: 'https://static.tvmaze.com/uploads/images/medium_portrait/1/50.jpg' };
  harness.fail(true); const failed = harness.loader(show); harness.finish();
  assert.equal(await failed, null); assert.equal(harness.requested[0].poster, show.art);
  assert.deepEqual([harness.canvases[0].width, harness.canvases[0].height], [0, 0]);
  harness.fail(false); const retry = harness.loader(show); harness.finish();
  assert.ok(validPosterColour(await retry)); assert.equal(harness.requested.length, 2);
  assert.equal(await harness.loader({ name: 'No poster' }), null);
});
