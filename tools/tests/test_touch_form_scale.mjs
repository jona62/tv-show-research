// Page Zoom compensation runs before app modules. Test the actual classic script
// with browser dimensions, without pretending headless WebKit is native iOS.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../shared/client/touch-forms.js', import.meta.url), 'utf8');

function browser({layout = 390, outer = 390, inner = layout, ios = true, ipad = false, viewport = true,
  screen, orientation} = {}) {
  const events = new Map(), writes = [];
  const listen = target => (name, handler, options) => events.set(`${target}:${name}`, {handler, options});
  const root = {clientWidth: layout, style: {
    setProperty(name, value, priority) { writes.push({name, value, priority}); }
  }};
  const window = {outerWidth: outer, innerWidth: inner, screen: screen ? structuredClone(screen) : undefined, orientation,
    visualViewport: viewport ? {scale: 1, addEventListener: listen('viewport')} : undefined,
    addEventListener: listen('window')};
  const document = {documentElement: root,
    addEventListener: listen('document')};
  const navigator = {userAgent: ipad ? 'Mozilla/5.0 (Macintosh)' : ios ? 'Mozilla/5.0 (iPhone)' : 'Mozilla/5.0 (Macintosh)',
    platform: ipad || !ios ? 'MacIntel' : 'iPhone', maxTouchPoints: ipad ? 5 : ios ? 1 : 0};
  vm.runInNewContext(source, {window, document, navigator}, {filename: 'touch-forms.js'});
  return {root, window, writes, events,
    floor() { return writes.at(-1)?.value; },
    listener(name, target = 'window') { return events.get(`${target}:${name}`); },
    fire(name, target = name === 'DOMContentLoaded' ? 'document' : 'window') {
      const event = events.get(`${target}:${name}`);
      assert.ok(event, `Missing ${target} ${name} update`); event.handler();
    }};
}

for (const [percent, layout, expected] of [[100, 390, 16], [125, 312, 16], [85, 459, 19], [75, 520, 22], [50, 780, 32]]) {
  const page = browser({layout});
  assert.equal(page.floor(), `${expected}px`, `Safari Page Zoom ${percent}%`);
  assert.equal(page.writes[0].name, '--touch-form-font-floor');
  assert.equal(page.writes[0].priority, 'important');
  assert.ok(expected * percent / 100 >= 16, `${percent}% must leave at least 16 rendered pixels`);
}

for (const [layout, outer] of [[0, 390], [390, 0], [-1, 390], [390, -1], [NaN, 390], [390, NaN], [Infinity, 390]]) {
  assert.equal(browser({layout, outer}).floor(), '16px', 'Unavailable dimensions must fail safely');
}

// Layout may not be available while the early head script is executing.
const parsing = browser({layout: 0});
parsing.root.clientWidth = 459;
parsing.fire('DOMContentLoaded');
assert.equal(parsing.floor(), '19px');

// Native iPhone Safari keeps outerWidth from the document's initial orientation.
// Its fixed screen dimensions and changing orientation identify physical width.
for (const [type, angle] of [['landscape-primary', 90], ['landscape-secondary', -90]]) {
  const phone = browser({layout: 462, outer: 393, orientation: 0,
    screen: {width: 393, height: 852, orientation: {type: 'portrait-primary', angle: 0}}});
  assert.equal(phone.floor(), '19px');
  phone.root.clientWidth = 1002;
  Object.assign(phone.window.screen.orientation, {type, angle}); phone.window.orientation = angle;
  phone.fire('orientationchange');
  assert.equal(phone.window.outerWidth, 393, 'The fixture retains native Safari’s stale portrait outerWidth');
  assert.equal(phone.floor(), '19px', `${type} uses 852px physical width instead of producing a 41px floor`);
  phone.root.clientWidth = 462;
  Object.assign(phone.window.screen.orientation, {type: 'portrait-secondary', angle: 180}); phone.window.orientation = 180;
  phone.fire('orientationchange');
  assert.equal(phone.floor(), '19px', 'Portrait upside-down restores the 393px physical width');
}

const landscapeFirst = browser({layout: 1002, outer: 852, orientation: 90,
  screen: {width: 393, height: 852, orientation: {type: 'landscape-primary', angle: 90}}});
assert.equal(landscapeFirst.floor(), '19px', 'A document initially loaded in landscape uses its physical landscape width');
landscapeFirst.root.clientWidth = 462;
Object.assign(landscapeFirst.window.screen.orientation, {type: 'portrait-primary', angle: 0}); landscapeFirst.window.orientation = 0;
landscapeFirst.fire('orientationchange');
assert.equal(landscapeFirst.window.outerWidth, 852, 'The opposite rotation retains native Safari’s stale landscape outerWidth');
assert.equal(landscapeFirst.floor(), '19px', 'Rotating a landscape-loaded document to portrait must not drop compensation to 16px');

for (const [type, layout] of [['landscape-secondary', 1002], ['portrait-secondary', 462]]) {
  const flipped = browser({layout, outer: 393, screen: {width: 852, height: 393, orientation: {type}}});
  assert.equal(flipped.floor(), '19px', `${type} also accepts screen dimensions that are already swapped`);
}

for (const angle of [0, 90, -90, 180]) {
  const legacy = browser({layout: Math.abs(angle) === 90 ? 1002 : 462, outer: 393, orientation: angle,
    screen: {width: 393, height: 852}});
  assert.equal(legacy.floor(), '19px', `Legacy window.orientation ${angle} works when screen.orientation is absent`);
}

for (const angle of [undefined, NaN, Infinity, 45, '90']) {
  const unsupported = browser({layout: 524, outer: 393, orientation: angle,
    screen: {width: 393, height: 852, orientation: {type: 'unsupported'}}});
  assert.equal(unsupported.floor(), '22px', 'Unavailable or unsupported orientation falls back to physical window width');
}
for (const [width, height] of [[0, 852], [-1, 852], [NaN, 852], [Infinity, 852], [393, 0], [393, -1], [393, NaN], [393, Infinity]]) {
  assert.equal(browser({layout: 524, outer: 393, screen: {width, height, orientation: {type: 'landscape-primary'}}}).floor(),
    '22px', 'Invalid screen dimensions must retain the window-width fallback');
}

const split = browser({layout: 452, outer: 384, ipad: true,
  screen: {width: 1024, height: 768, orientation: {type: 'portrait-primary'}}});
assert.equal(split.floor(), '19px', 'iPad uses its 384px split window, not the full 1024px screen');
split.root.clientWidth = 603;
split.window.outerWidth = 512;
split.fire('resize');
assert.equal(split.floor(), '19px', 'iPad split view must use window width, not full screen width');

// Safari can change Page Zoom without dispatching window.resize before a tap.
// visualViewport.resize is a trigger, while only stable layout/window widths
// supply the sizing calculation.
const zoomChanged = browser({layout: 462, outer: 390});
assert.equal(zoomChanged.floor(), '19px');
zoomChanged.root.clientWidth = 524;
zoomChanged.fire('resize', 'viewport');
assert.equal(zoomChanged.floor(), '22px', 'A timely visual viewport event must update 85→75% Page Zoom before focus');
assert.equal(zoomChanged.writes.length, 2);

for (const name of ['pointerdown', 'touchstart']) {
  const tap = browser({layout: 462, outer: 390});
  tap.root.clientWidth = 524;
  const event = tap.listener(name, 'document');
  assert.equal(event?.options?.capture, true, `${name} must refresh before the browser’s default focus action`);
  assert.equal(event?.options?.passive, true, `${name} must leave scrolling and tap defaults available`);
  tap.fire(name, 'document');
  assert.equal(tap.floor(), '22px', `${name} covers a Page Zoom change whose observer event has not arrived`);
  assert.equal(tap.listener('focusin', 'document'), undefined, 'Refreshing after focus would be too late');
}

const noViewport = browser({layout: 462, outer: 390, viewport: false});
noViewport.root.clientWidth = 524;
noViewport.fire('touchstart', 'document');
assert.equal(noViewport.floor(), '22px', 'The pre-focus tap guard works without visualViewport support');

// iOS innerWidth can shrink on pinch. Neither it nor visualViewport.scale is a
// Page Zoom signal, and an unchanged layout should not rewrite the CSS property.
const pinch = browser({layout: 462, outer: 393,
  screen: {width: 393, height: 852, orientation: {type: 'portrait-primary'}}});
const before = pinch.writes.length;
pinch.window.innerWidth = 230;
pinch.window.visualViewport.scale = 2;
pinch.fire('resize');
pinch.fire('resize', 'viewport');
pinch.fire('pointerdown', 'document');
pinch.fire('touchstart', 'document');
assert.equal(pinch.floor(), '19px', 'A pinch must not change text sizing');
assert.equal(pinch.writes.length, before, 'An unchanged floor should avoid style/layout churn');
pinch.window.innerWidth = 462;
pinch.window.visualViewport.scale = 1;
pinch.fire('resize');
pinch.fire('resize', 'viewport');
assert.equal(pinch.writes.length, before);

const desktop = browser({layout: 780, ios: false});
assert.equal(desktop.writes.length, 0, 'Ordinary desktop browser zoom must keep its native behavior');

console.log('Page Zoom floor: 50/75/85/100/125%, stale iPhone outer dimensions in both rotations, orientation/screen fallbacks, iPad split view, timely viewport/pre-focus tap refresh and pinch stability passed.');
