import assert from 'node:assert/strict';
import { test } from 'node:test';
import { backdropURL, displayPoster, comparisonPosterSources, createBackdropPrefetcher, bindBackdropIntent } from '../client/show-artwork.js';

function clock() {
  let time = 0, next = 0;
  const timers = new Map();
  return {
    now: () => time,
    schedule: (run, delay) => { const id = ++next; timers.set(id, { run, at: time + delay }); return id; },
    cancel: id => timers.delete(id),
    advance(ms) {
      time += ms;
      for (const [id, timer] of [...timers]) if (timer.at <= time && timers.delete(id)) timer.run();
    },
  };
}
function fixture() {
  const timer = clock(), images = [], net = {}, state = { online: true };
  const makeImage = () => {
    const image = { removeAttribute(name) { delete this[name]; } };
    images.push(image); return image;
  };
  return { timer, images, net, state, warm: createBackdropPrefetcher({ ...timer, makeImage,
    connection: () => net, online: () => state.online }) };
}

test('backdrop addresses accept only catalogue-shaped numeric ids', () => {
  assert.equal(backdropURL(82), '/api/backdrop?id=82');
  for (const id of [0, -1, 1.5, 1000000000, '82', NaN, null]) assert.equal(backdropURL(id), '');
});

test('small comparison posters use matching provider thumbnails, leaving originals for export or fallback', () => {
  const original = 'https://static.tvmaze.com/uploads/images/original_untouched/0/82.jpg';
  const medium = 'https://static.tvmaze.com/uploads/images/medium_portrait/0/82.jpg';
  const show = { art: original, poster: medium };
  assert.equal(displayPoster(original), medium);
  assert.deepEqual(comparisonPosterSources(show), [medium, original]);
  assert.deepEqual(comparisonPosterSources({ art: original, poster: '/alternate.jpg' }), [medium, '/alternate.jpg', original]);
  assert.equal(show.art, original, 'Rendering must not alter the snapshot source');
  for (const source of ['https://static.tvmaze.com.evil.test/uploads/images/original_untouched/0/82.jpg',
    original + '?other=1', original.replace('.jpg', '.svg'), '/fixture/poster.svg']) assert.equal(displayPoster(source), source);
  assert.deepEqual(comparisonPosterSources({ poster: '/preview.svg', art: '/full.svg' }), ['/preview.svg', '/full.svg']);
});

test('backdrop display widths are bounded, account for pixel density and retain exact request identity', () => {
  assert.equal(backdropURL(82, { width: 390, scale: 1 }), '/api/backdrop?id=82&w=780');
  assert.equal(backdropURL(82, { width: 390, scale: 3 }), '/api/backdrop?id=82&w=1280');
  assert.equal(backdropURL(82, { width: 1280, scale: 1 }), '/api/backdrop?id=82&w=1280');
  assert.equal(backdropURL(82, { width: 1920, scale: 3 }), '/api/backdrop?id=82&w=1280');
});

test('repeated intent shares a background request and finished image cache identity', () => {
  const { warm, images } = fixture();
  warm(82); warm(82);
  assert.equal(images.length, 1);
  assert.equal(images[0].src, backdropURL(82));
  assert.equal(images[0].crossOrigin, 'anonymous');
  assert.equal(images[0].fetchPriority, 'low');
  images[0].onload(); warm(82);
  assert.equal(images.length, 1);
});

test('an enlarged viewport can warm the larger variant without suppressing it as already cached', () => {
  const originalWidth = Object.getOwnPropertyDescriptor(globalThis, 'innerWidth');
  const originalScale = Object.getOwnPropertyDescriptor(globalThis, 'devicePixelRatio');
  try {
    Object.defineProperty(globalThis, 'innerWidth', { configurable: true, writable: true, value: 600 });
    Object.defineProperty(globalThis, 'devicePixelRatio', { configurable: true, value: 1 });
    const { warm, images } = fixture();
    warm(82); images[0].onload();
    assert.equal(images[0].src, '/api/backdrop?id=82&w=780');
    globalThis.innerWidth = 1200;
    warm(82);
    assert.equal(images.length, 2);
    assert.equal(images[1].src, backdropURL(82));
    assert.equal(images[1].src, '/api/backdrop?id=82&w=1280');
  } finally {
    if (originalWidth) Object.defineProperty(globalThis, 'innerWidth', originalWidth); else delete globalThis.innerWidth;
    if (originalScale) Object.defineProperty(globalThis, 'devicePixelRatio', originalScale); else delete globalThis.devicePixelRatio;
  }
});

test('only two images run and the latest four waiting shows survive a long row sweep', () => {
  const { warm, images } = fixture();
  for (let id = 1; id <= 9; id++) warm(id);
  assert.equal(images.length, 2);
  images[0].onload(); images[1].onload();
  assert.deepEqual(images.map(image => image.src), [1, 2, 6, 7].map(backdropURL));
  images[2].onload(); images[3].onload();
  assert.deepEqual(images.map(image => image.src), [1, 2, 6, 7, 8, 9].map(backdropURL));
});

test('failures retry after a short cooldown and stalled images release waiting work', () => {
  const { warm, images, timer } = fixture();
  warm(1); images[0].onerror(); warm(1);
  assert.equal(images.length, 1);
  timer.advance(30000); warm(1); warm(2); warm(3);
  assert.equal(images.length, 3);
  timer.advance(15000);
  assert.equal(images.length, 4);
  assert.equal(images[3].src, backdropURL(3));
  assert.equal(images[1].src, undefined);
});

test('successful intent expires after a day and its memory remains bounded', () => {
  const { warm, images, timer } = fixture();
  warm(1); images.at(-1).onload();
  timer.advance(86400000); warm(1);
  assert.equal(images.length, 2); images.at(-1).onload();
  for (let id = 2; id <= 41; id++) { warm(id); images.at(-1).onload(); }
  warm(1);
  assert.equal(images.length, 43, 'older images leave the intent memory after forty other shows');
});

test('offline, Save-Data and very slow networks skip speculative artwork only', () => {
  const { warm, images, net, state } = fixture();
  state.online = false; warm(1); state.online = true;
  net.saveData = true; warm(2); net.saveData = false;
  net.effectiveType = '2g'; warm(3); net.effectiveType = 'slow-2g'; warm(4);
  assert.equal(images.length, 0);
  net.effectiveType = '4g'; warm(1); assert.equal(images.length, 1);
});

test('hover waits for intent, focus starts immediately, touch hover and inert copies do nothing', () => {
  const root = new EventTarget(), timer = clock(), warmed = [];
  const card = { dataset: { id: '82' }, isConnected: true, closest: () => null };
  const child = { closest: () => card };
  const inert = { closest: () => ({ dataset: { id: '2' }, closest: () => ({}) }) };
  const send = (type, target, options = {}) => {
    const event = new Event(type);
    Object.defineProperties(event, { target: { value: target }, pointerType: { value: options.pointerType || 'mouse' },
      relatedTarget: { value: options.relatedTarget || null } });
    root.dispatchEvent(event);
  };
  const dispose = bindBackdropIntent(root, id => warmed.push(id), timer);
  send('pointerover', child); timer.advance(100);
  send('pointerout', child); timer.advance(100);
  assert.deepEqual(warmed, []);
  send('pointerover', child); send('pointerover', child, { relatedTarget: child }); timer.advance(160);
  assert.deepEqual(warmed, [82]);
  send('focusin', child); assert.deepEqual(warmed, [82, 82]);
  send('pointerover', child, { pointerType: 'touch' }); send('focusin', inert); timer.advance(160);
  assert.deepEqual(warmed, [82, 82]);
  send('pointerover', child); dispose(); timer.advance(160); send('focusin', child);
  assert.deepEqual(warmed, [82, 82]);
});
