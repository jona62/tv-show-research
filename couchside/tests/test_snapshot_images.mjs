import assert from 'node:assert/strict';
import test from 'node:test';
import { createSnapshotImageLoader } from '../client/snapshot-images.js';

function harness(options = {}) {
  const images = [];
  const probes = [];
  let canvasError = false;
  const loader = createSnapshotImageLoader({
    timeoutMs: 1000,
    createImage() {
      const image = {
        naturalWidth: 600, naturalHeight: 900,
        decode: async () => {},
        set src(value) {
          this.url = value;
          this.atRequest = { crossOrigin: this.crossOrigin, referrerPolicy: this.referrerPolicy };
        },
      };
      images.push(image);
      return image;
    },
    createCanvas() {
      const canvas = {
        getContext: () => ({ drawImage: image => { canvas.image = image; } }),
        toDataURL: () => {
          probes.push(canvas);
          if (canvasError) throw new Error('SecurityError');
          return 'data:image/png;base64,clean';
        },
      };
      return canvas;
    },
    ...options,
  });
  return { loader, images, probes, setCanvasError: value => { canvasError = value; } };
}

const show = (name, poster) => ({ name, poster });
const compare = (...shows) => ({ kind: 'compare', shows });

test('requests anonymous, no-referrer images before src and caches concurrent/successful URLs', async () => {
  const { loader, images, probes } = harness();
  const model = compare(show('First', 'a.jpg'), show('Duplicate', 'a.jpg'));
  const first = loader(model);
  const concurrent = loader({ kind: 'detail', title: 'First', poster: 'a.jpg' });
  assert.equal(images.length, 1);
  assert.deepEqual(images[0].atRequest, { crossOrigin: 'anonymous', referrerPolicy: 'no-referrer' });
  await images[0].onload();
  const result = await first;
  assert.deepEqual([...result.keys()], ['a.jpg']);
  assert.equal(result.get('a.jpg'), images[0]);
  assert.equal((await concurrent).get('a.jpg'), images[0]);
  assert.equal((await loader(model)).get('a.jpg'), images[0]);
  assert.equal(images.length, 1);
  assert.equal(probes.length, 1);
  assert.deepEqual([probes[0].width, probes[0].height], [1, 1]);
});

test('skips missing URLs and preserves captured URLs, names, and order while loading', async () => {
  const { loader, images } = harness();
  assert.equal((await loader(compare(show('Missing'), show('Blank', '  ')))).size, 0);
  assert.equal(images.length, 0);
  const model = compare(show('First', 'a.jpg'), show('Second', 'b.jpg'));
  const loading = loader(model);
  model.shows[0].poster = 'changed.jpg';
  model.shows.reverse();
  await images[1].onload();
  await images[0].onload();
  assert.deepEqual([...((await loading).keys())], ['a.jpg', 'b.jpg']);
  assert.deepEqual(images.map(image => image.url), ['a.jpg', 'b.jpg']);
  assert.deepEqual(model.shows.map(item => item.poster), ['b.jpg', 'changed.jpg']);
});

test('load failures identify the captured show, evict the failed promise, and retry', async () => {
  const { loader, images } = harness();
  const model = { kind: 'detail', title: 'Original show', poster: 'a.jpg' };
  const loading = loader(model);
  const rejected = assert.rejects(loading, /Original show.*could not be loaded/);
  model.title = 'Changed show';
  images[0].onerror();
  await rejected;
  const retry = loader(model);
  assert.equal(images.length, 2);
  await images[1].onload();
  assert.equal((await retry).get('a.jpg'), images[1]);
});

test('a shared failed URL reports each caller’s own show name', async () => {
  const { loader, images } = harness();
  const first = assert.rejects(loader(compare(show('First caller', 'a.jpg'))), /First caller/);
  const second = assert.rejects(loader(compare(show('Second caller', 'a.jpg'))), /Second caller/);
  images[0].onerror();
  await Promise.all([first, second]);
});

test('decode and origin-clean failures reject explicitly and permit retry', async () => {
  for (const failure of ['decode', 'canvas']) {
    const { loader, images, setCanvasError } = harness();
    const loading = loader(compare(show('Chernobyl', 'a.jpg')));
    const rejected = assert.rejects(loading, failure === 'decode' ? /Chernobyl.*decoded/ : /Chernobyl.*blocking image export/);
    if (failure === 'decode') images[0].decode = async () => { throw new Error('Bad image'); };
    else setCanvasError(true);
    await images[0].onload();
    await rejected;
    setCanvasError(false);
    const retry = loader(compare(show('Chernobyl', 'a.jpg')));
    await images[1].onload();
    assert.equal((await retry).get('a.jpg'), images[1]);
  }
});

test('the deadline includes decode and a late completion cannot replace the retry', async () => {
  const { loader, images, probes } = harness({ timeoutMs: 10 });
  const loading = loader(compare(show('Slow show', 'a.jpg')));
  const rejected = assert.rejects(loading, /Slow show.*did not finish loading/);
  let finishDecode;
  images[0].decode = () => new Promise(resolve => { finishDecode = resolve; });
  const lateLoad = images[0].onload();
  await rejected;
  const retry = loader(compare(show('Slow show', 'a.jpg')));
  await images[1].onload();
  finishDecode();
  await lateLoad;
  assert.equal((await retry).get('a.jpg'), images[1]);
  assert.equal((await loader(compare(show('Slow show', 'a.jpg')))).get('a.jpg'), images[1]);
  assert.equal(probes.length, 1);
});


test('rejects a decoded image without usable dimensions and retries', async () => {
  const { loader, images } = harness();
  const loading = loader(compare(show('Broken poster', 'a.jpg')));
  const rejected = assert.rejects(loading, /Broken poster.*no usable image dimensions/);
  images[0].naturalWidth = 0;
  await images[0].onload();
  await rejected;
  const retry = loader(compare(show('Broken poster', 'a.jpg')));
  await images[1].onload();
  assert.equal((await retry).get('a.jpg'), images[1]);
});

test('the poster cache is bounded across repeated snapshot jobs', async () => {
  const { loader, images } = harness();
  for (let index = 0; index < 40; index++) {
    const loading = loader(compare(show('Show ' + index, index + '.jpg')));
    await images[index].onload();
    await loading;
  }
  const recent = await loader(compare(show('Recent', '39.jpg')));
  assert.equal(recent.get('39.jpg'), images[39]);
  const oldest = loader(compare(show('Oldest', '0.jpg')));
  assert.equal(images.length, 41);
  await images[40].onload();
  assert.equal((await oldest).get('0.jpg'), images[40]);
});
