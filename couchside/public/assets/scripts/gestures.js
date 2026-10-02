// Gestures and motion, for phones and touch screens. Sheets slide up as they open, follow
// a finger down and go past a distance or a flick, and slide away however they close;
// rows that land on screen ease in; views and the hero crossfade; a long press on a
// poster lifts it into a peek with its quick buttons; and, installed with no browser back
// button, a swipe in from the left edge goes back. Nothing moves under reduced motion,
// and a mouse keeps the hover and pop-ups it has. Rows that run past the screen go round,
// on any screen, with the maths for that here and the rows themselves in main.js. The
// maths is pure and checked by test_gestures.mjs; nothing here touches the page until
// main.js calls it.

/* ------------------------------------------------------------------ maths */
export const LONG_PRESS = 450;  // ms a finger rests on a poster before it peeks
export const SLOP = 10;         // px a resting finger may wander before it is a scroll
export const EDGE = 20;         // px from the left edge where a swipe back begins
export const FLICK = .45;       // px a ms: a sheet thrown down this fast goes, however near
const AHEAD = 180;              // ms of a finger's speed counted as distance still to come

// How far something gives when pulled the way it cannot go: a little, then less and
// less, never as far as `limit`.
export const rubber = (pull, limit, give = .55) =>
  pull > 0 && limit > 0 ? (1 - 1 / (pull * give / limit + 1)) * limit : 0;

// Where a sheet sits `y` px below its place: there, going down; held back, going up.
export const follow = (y, limit) => (y >= 0 ? y : -rubber(-y, limit));

// A finger's speed in px a ms over its last `span` ms before `now`, from [time, position]
// samples; nothing once it has rested that long.
export function speed(samples, now, span = 100) {
  const recent = samples.filter(([t]) => now - t <= span);
  if (recent.length < 2) return 0;
  const [t0, p0] = recent[0], [t1, p1] = recent[recent.length - 1];
  return t1 > t0 ? (p1 - p0) / (t1 - t0) : 0;
}

// Whether a sheet let go `offset` px down, moving at `v`, goes: a quarter of its height
// (80 to 180px) counting where its speed carries it, or a real flick down. A flick back
// up keeps it.
export function dismisses(offset, v, height) {
  if (v <= -.2) return false;
  const far = Math.min(Math.max(height / 4, 80), 180);
  return offset + Math.max(v, 0) * AHEAD >= far || (v >= FLICK && offset >= 12);
}

// How long a sheet takes over its last `distance` px: at the speed it was thrown, never
// slower than a button closes it, and within 120 to 280ms.
export const glide = (distance, v = 0) =>
  Math.round(Math.min(Math.max(distance / Math.max(v, 1.6), 120), 280));

// Which way a finger went first: 'x' across, 'down' or 'up', or '' before it moves.
export function heading(dx, dy) {
  if (!dx && !dy) return '';
  if (Math.abs(dx) > Math.abs(dy)) return 'x';
  return dy > 0 ? 'down' : 'up';
}

// A press that wanders past SLOP is a scroll, not a long press.
export const wandered = (dx, dy) => Math.hypot(dx, dy) > SLOP;

// A swipe back begins at the left edge, and goes back once it has come a third of the way
// across, at most 110px, counting where its speed carries it.
export const fromEdge = x => x <= EDGE;
export const goesBack = (dx, v, width) => v > -.2 && dx + Math.max(v, 0) * AHEAD >= Math.min(width / 3, 110);

// When the nth of a batch starts: `step` ms apart, the last by `most`.
export const stagger = (n, step, most) => Math.min(n * step, most);

// A page is at rest once it has not scrolled for this long.
export const REST = 150;

// Whether a row eases in: only one that arrives on screen while the page is at rest,
// such as the first rows or rows that land while the reader waits at the end. A row
// that arrives below the screen, or while the reader scrolls, is shown at once, since
// fading it in as it comes into view would hold back what the reader came for.
export const easesIn = (onScreen, sinceScroll) => onScreen && sinceScroll >= REST;

/* ------------------------------------------------------------------ loops */
// A row whose cards run past the screen goes round. Copies of its last cards wait before
// its first, and copies of its first after its last, so a swipe or a page past either end
// carries straight on with the same momentum. Once the row comes to rest it moves by whole
// laps, a lap being its own cards and the gaps after them, back among its own cards,
// where the same cards are in the same places and nothing looks any different. And what
// it shows at rest is always the cards themselves: a card that shows through a copy's
// place trades places with that copy, which is the same size, so nothing else moves.

// How far a looping row carries on past either end before it must rest: four screens,
// and 800px at least. A finger drags a row a screen at most, and Chrome flings it on three
// times its screen at most; Safari, which slows a row that snaps to its cards sooner, less.
export const LOOP_SCREENS = 4;
export const LOOP_LEAST = 800;

// Whether a row goes round: whether its cards, a lap of `lap` px less the `gap` after the
// last, run past its `width` with `pad` px inside either end.
export const goesRound = (lap, gap, pad, width) => lap - gap + 2 * pad > width + 1;

// How many copies a looping row `width` px wide, of cards `pitch` px apart, keeps before
// its first card and after its last: enough to carry it `reach` px either way from
// wherever it rests among its own cards, and after the last, to fill the row past that.
export function loopCopies(width, pitch, reach = Math.max(width * LOOP_SCREENS, LOOP_LEAST)) {
  return { before: Math.ceil(reach / pitch), after: Math.ceil((reach + width) / pitch) };
}

// Which of a row's `n` cards each copy is: `before` of its last cards, in order and round
// again for a short row, then `after` of its first.
export function copiesOf(n, before, after) {
  return {
    before: Array.from({ length: before }, (_, k) => (((k - before) % n) + n) % n),
    after: Array.from({ length: after }, (_, k) => k % n),
  };
}

// How far a row resting `x` px past its first card's own place scrolls to be among its
// own cards again: whole laps, to rest within [0, lap). Half a pixel either way is there.
export const lapHome = (x, lap) => -Math.floor((x + .5) / lap) * lap || 0;

// Where a card shows at rest: the first of its `places`, each [left, right], its own place
// first and then its copies', that shows between `from` and `to`, its own when that
// shows, and its own when none does. Its copies fill the places it leaves.
export function restPlace(places, from, to) {
  const shows = ([left, right]) => right > from + .5 && left < to - .5;
  return shows(places[0]) ? 0 : Math.max(places.findIndex(shows), 0);
}

// How far a row that snaps to its cards has to scroll to rest on one, from their left
// edges `lefts` and its snapping `edge`: nothing when a card is on the edge to a pixel, or
// else to the nearest card it can reach, being `scroll` px along the `most` it scrolls,
// back when negative. A row at either end of its scroll, where a fling that ran out of
// copies stops, reaches the cards back from it.
export function toCard(lefts, edge, scroll, most) {
  let near = 0;
  for (const left of lefts) {
    const by = left - edge;
    if (Math.abs(by) < 1) return 0;
    if (scroll + by >= -1 && scroll + by <= most + 1 && (!near || Math.abs(by) < Math.abs(near))) near = by;
  }
  return near;
}

// A row that stops short of a card, which it does when a finger stops it or while it
// creeps the last pixels on, is given LOOP_WAIT ms from when it last moved to get there,
// since a browser may snap it once its scroll has ended; then it eases there itself.
export const LOOP_WAIT = 600;

/* ----------------------------------------------------------------- motion */
const OUT = 'cubic-bezier(.22,1,.36,1)';      // quick, then settling
const IN = 'cubic-bezier(.4,0,1,1)';          // gathering speed
const THROWN = 'cubic-bezier(.3,.6,.6,1)';    // going on at the speed it was thrown
const SPRING = 'cubic-bezier(.3,1.4,.55,1)';  // a touch past its place, then home
const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
let browserBack = false;
// Whether the page moves: on phones and touch screens, with motion welcome, and not while
// the browser plays its own animation for a swipe back.
const moving = () => !still() && !browserBack && matchMedia('(max-width: 759px), (pointer: coarse)').matches;
// A backdrop fades with its sheet wherever animations can reach one.
const backdrops = () => typeof KeyframeEffect !== 'undefined' && 'pseudoElement' in KeyframeEffect.prototype;
const offset = node => {
  const t = getComputedStyle(node).transform;
  return t && t !== 'none' ? new DOMMatrixReadOnly(t).m42 : 0;
};
const dimness = d => {
  const o = parseFloat(getComputedStyle(d, '::backdrop').opacity);
  return Number.isFinite(o) ? o : 1;
};
// Runs `then` once when animation `a` finishes, or after `ms` on a hidden page, where
// nothing animates; never if `a` is cancelled first.
function after(a, ms, then) {
  let done = false;
  const run = () => {
    if (done || a.playState === 'idle') return;
    done = true;
    then();
  };
  a.finished.then(run, () => {});
  setTimeout(run, ms);
}

/* ----------------------------------------------------------------- sheets */
const sheetOf = new WeakMap();  // each dialog's sheet: its animations, drag and closing
const own = new WeakSet();      // dialogs that move their own way, such as the peek
let native = null;              // the dialog's own showModal and close
const FIELDS = 'input, textarea, select, [contenteditable]';

// Every <dialog> becomes a sheet: a grab handle, a swipe down to dismiss it on a touch
// screen, and on phones a slide up as it opens and down however it closes. `dismiss(d)`
// is how a swipe closes one, the same way as its close button.
export function sheets(dismiss) {
  native = { showModal: HTMLDialogElement.prototype.showModal, close: HTMLDialogElement.prototype.close };
  new MutationObserver(records => {
    for (const d of new Set(records.map(r => r.target))) {
      if (d.localName !== 'dialog' || own.has(d)) continue;
      const s = sheetOf.get(d) || prepare(d, dismiss);
      if (d.open && !s.shown) { s.shown = true; arrive(d, s); }
      else if (!d.open && s.shown) { s.shown = false; settle(d, s); }
    }
  }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['open'] });
  // A step back the browser animated itself, such as Safari's swipe, needs no second one.
  window.addEventListener('popstate', e => {
    if (!e.hasUAVisualTransition) return;
    browserBack = true;
    setTimeout(() => { browserBack = false; });
  }, true);
  window.addEventListener('resize', () => {
    for (const d of document.querySelectorAll('dialog[open]')) if (sheetOf.has(d)) place(d);
  });
}

// A sheet sliding away, or gone and waiting to close.
export const closing = d => !!sheetOf.get(d)?.leaving;

function prepare(d, dismiss) {
  const s = { shown: false, leaving: false, gone: false, asked: false, value: undefined, move: null, fade: null, drag: null };
  sheetOf.set(d, s);
  const grab = document.createElement('div');
  grab.className = 'grab';
  grab.setAttribute('aria-hidden', 'true');
  d.prepend(grab);
  // However it is asked to close, a sheet slides away first.
  d.close = value => {
    if (!d.open) return;
    s.asked = true;
    s.value = value;
    if (s.gone) shut(d, s);
    else if (!s.leaving) {
      if (moving()) leave(d, s, 0); else shut(d, s);
    }
  };
  // Opened again while it slides away, it comes back instead.
  d.showModal = () => {
    if (s.leaving) stay(d, s); else native.showModal.call(d);
  };
  // Escape, where nothing else handles it, closes the same way.
  d.addEventListener('cancel', e => {
    if (e.defaultPrevented || !e.cancelable || !moving()) return;
    e.preventDefault();
    d.close();
  });
  d.addEventListener('touchstart', e => press(d, s, e), { passive: true });
  d.addEventListener('touchmove', e => drag(d, s, e), { passive: false });
  d.addEventListener('touchend', e => letGo(d, s, e, dismiss), { passive: true });
  d.addEventListener('touchcancel', e => letGo(d, s, e, dismiss), { passive: true });
  return s;
}

// The handle sits just inside the sheet's top edge wherever the layout puts it, and below
// the status bar on a sheet that reaches the top of the screen.
function place(d) {
  const grab = d.querySelector(':scope > .grab');
  const sheet = [...d.children].find(n => n !== grab);
  if (!grab || !sheet) return;
  const top = sheet.getBoundingClientRect().top;
  grab.style.setProperty('--grab-top', `${Math.max(0, top - d.getBoundingClientRect().top - d.clientTop + d.scrollTop)}px`);
  d.classList.toggle('at-top', top < 1);
}

function arrive(d, s) {
  place(d);
  if (!moving()) return;
  s.move?.cancel();
  s.fade?.cancel();
  s.move = d.animate([{ transform: 'translateY(100%)' }, { transform: 'none' }], { duration: 280, easing: OUT });
  s.fade = backdrops()
    ? d.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 240, easing: 'ease-out', pseudoElement: '::backdrop' })
    : null;
}

// Moves a sheet from where it is now to `to`, and its backdrop to `opacity`.
function slide(d, s, to, opacity, duration, easing, keep = false) {
  const from = offset(d), dim = backdrops() ? dimness(d) : 1;
  s.move?.cancel();
  s.fade?.cancel();
  d.style.transform = '';
  const fill = keep ? 'forwards' : 'none';
  s.move = d.animate([{ transform: `translateY(${from}px)` }, { transform: to }], { duration, easing, fill });
  s.fade = backdrops()
    ? d.animate([{ opacity: dim }, { opacity }], { duration, easing: 'linear', fill, pseudoElement: '::backdrop' })
    : null;
  return s.move;
}

// Off the bottom from wherever it is, at the speed it was thrown. It closes once asked
// to, and comes back if nothing asks within a second.
function leave(d, s, v) {
  s.leaving = true;
  s.gone = false;
  const rest = Math.max((d.offsetHeight || innerHeight) - offset(d), 0);
  const time = v > 0 ? glide(rest, v) : 240;
  after(slide(d, s, 'translateY(100%)', 0, time, v > 0 ? THROWN : IN, true), time + 200, () => {
    if (!s.leaving) return;
    s.gone = true;
    if (s.asked) shut(d, s);
    else setTimeout(() => { if (s.gone && !s.asked && d.open) stay(d, s); }, 1000);
  });
}

function stay(d, s) {
  s.leaving = s.gone = s.asked = false;
  slide(d, s, 'none', 1, 220, OUT);
}

function shut(d, s) {
  const value = s.value;
  s.leaving = s.gone = s.asked = false;
  s.value = undefined;
  native.close.call(d, value);
  settle(d, s);
}

function settle(d, s) {
  s.move?.cancel();
  s.fade?.cancel();
  s.move = s.fade = s.drag = null;
  s.leaving = s.gone = s.asked = false;
  d.style.transform = '';
}

// Whether anything from a touch up to its sheet is scrolled down, or scrolls across.
const scrolledDown = (node, d) => {
  for (let n = node; n && n !== d.parentNode; n = n.parentElement) if (n.scrollTop > 0) return true;
  return false;
};
const across = (node, d) => {
  for (let n = node; n && n !== d; n = n.parentElement) {
    if (n.scrollWidth > n.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(n).overflowX)) return true;
  }
  return false;
};

function press(d, s, e) {
  s.drag = null;
  if (e.touches.length !== 1 || s.leaving || e.target.closest?.(FIELDS)) return;
  const t = e.touches[0];
  s.drag = { id: t.identifier, x: t.clientX, y: t.clientY, target: e.target, down: false, from: 0, at: 0, height: 0, samples: [] };
}

// A drag starts only on a first move down with everything above the finger scrolled to
// the top, so scrolling inside a sheet, and across a row in it, stays as it was.
function drag(d, s, e) {
  const g = s.drag;
  if (!g) return;
  // Closed some other way mid-drag, it goes the way it was sent.
  if (s.leaving) {
    s.drag = null;
    return;
  }
  const t = [...e.touches].find(c => c.identifier === g.id);
  if (!t || e.touches.length > 1) {
    s.drag = null;
    if (g.down) slide(d, s, 'none', 1, 220, OUT);
    return;
  }
  const dx = t.clientX - g.x, dy = t.clientY - g.y;
  if (!g.down) {
    const way = heading(dx, dy);
    if (!way) return;
    if (way !== 'down' || !e.cancelable || scrolledDown(g.target, d) || (across(g.target, d) && dy <= 2 * Math.abs(dx) + 2)) {
      s.drag = null;
      return;
    }
    g.down = true;
    g.from = offset(d);  // caught mid-slide, it goes on from where it is
    g.height = d.offsetHeight || innerHeight;
    s.move?.cancel();
    s.fade?.cancel();
    s.move = null;
    s.fade = backdrops()
      ? d.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 1000, fill: 'both', pseudoElement: '::backdrop' })
      : null;
    s.fade?.pause();
  }
  e.preventDefault();
  g.at = follow(g.from + dy, g.height);
  g.samples.push([performance.now(), g.at]);
  if (g.samples.length > 8) g.samples.shift();
  d.style.transform = `translateY(${g.at}px)`;
  if (s.fade) s.fade.currentTime = Math.min(Math.max(g.at / g.height, 0), 1) * 1000;
}

// Let go past the line, or thrown, the sheet goes the way its close button sends it;
// otherwise it springs back.
function letGo(d, s, e, dismiss) {
  const g = s.drag;
  if (!g || [...e.touches].some(t => t.identifier === g.id)) return;
  s.drag = null;
  if (!g.down || s.leaving) return;
  const v = e.type === 'touchend' ? speed(g.samples, performance.now()) : 0;
  if (e.type === 'touchend' && dismisses(g.at, v, g.height)) {
    if (!still()) leave(d, s, v);
    dismiss(d);
  } else if (still()) {
    s.fade?.cancel();
    s.fade = null;
    d.style.transform = '';
  } else slide(d, s, 'none', 1, 300, SPRING);
}

/* ------------------------------------------------------ rows, views, hero */
const seen = new WeakSet();
const easing = new Set();       // rows' ease-ins under way
let rowWatch = null;
let scrolled = -Infinity;       // when the page last scrolled

// Rows that arrive on screen while the page is at rest ease in, a row at a time with
// their first posters just behind (easesIn); every other row is simply there. A new row
// waits unseen only until the next frame says where it landed, and an ease-in under way
// ends at once when the page moves. A row already given here is left alone.
export function reveal(rows) {
  if (!moving() || !('IntersectionObserver' in window)) return;
  if (!rowWatch) {
    window.addEventListener('scroll', () => {
      scrolled = performance.now();
      for (const a of easing) a.finish();
      easing.clear();
    }, { passive: true });
    rowWatch = new IntersectionObserver(entries => {
      const since = performance.now() - scrolled;
      let n = 0;
      for (const entry of entries) {
        rowWatch.unobserve(entry.target);
        if (easesIn(entry.isIntersecting, since)) easeIn(entry.target, stagger(n++, 60, 180));
        else entry.target.classList.remove('pre');
      }
    });
  }
  for (const row of rows) {
    if (seen.has(row) || row.hidden) continue;
    seen.add(row);
    row.classList.add('pre');
    rowWatch.observe(row);
  }
}

function easeIn(row, delay) {
  row.classList.remove('pre');
  if (!moving()) return;
  const eased = [row.animate([{ opacity: 0, transform: 'translateY(18px)' }, { opacity: 1, transform: 'none' }],
    { duration: 240, delay, easing: OUT, fill: 'backwards' })];
  // The cards rise into their slots, and the slots stay put: a slot is where the row snaps
  // when swiped, and sliding one in from the side made the row snap to it mid-slide, pulling
  // the whole row left and then back. A looping row's copies, which wait off screen, stay still.
  [...row.querySelectorAll('.track > li:not([inert])')].slice(0, 6).forEach((li, i) => {
    for (const part of li.children) eased.push(part.animate(
      [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'none' }],
      { duration: 220, delay: delay + 40 + stagger(i, 25, 100), easing: OUT, fill: 'backwards' }));
  });
  for (const a of eased) {
    easing.add(a);
    a.finished.then(() => easing.delete(a), () => easing.delete(a));
  }
}

// Puts `nodes` in `box` in place of what it holds, crossfading from the old to the new;
// into an empty box they fade in.
export function crossfade(box, ...nodes) {
  const old = [...box.childNodes];
  box.replaceChildren(...nodes);
  if (!moving()) return;
  if (!old.length) {
    box.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, easing: 'ease-out' });
    return;
  }
  const ghost = document.createElement('div');
  ghost.className = 'swap-ghost';
  ghost.setAttribute('aria-hidden', 'true');
  ghost.inert = true;
  ghost.append(...old);
  box.append(ghost);
  after(ghost.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 320, easing: 'ease-in-out' }), 520, () => ghost.remove());
}

/* ------------------------------------------------------------------- peek */
// A long press on a poster, on a touch screen, lifts it into a peek. `build(card, close)`
// makes what the peek holds: a .peek-art poster over a .peek-panel of buttons, where
// close(true) shuts it at once. The finger that peeked never also taps the poster.
export function peeks(build) {
  let press = null, peek = null, shutting = false, swallow = 0;
  const dialog = () => {
    if (peek) return peek;
    peek = document.createElement('dialog');
    peek.className = 'peek';
    own.add(peek);
    peek.addEventListener('click', e => { if (e.target === peek) close(); });
    peek.addEventListener('cancel', e => { e.preventDefault(); close(); });
    peek.addEventListener('close', () => peek.replaceChildren());
    // Dragging on the dimmed page around a peek scrolls nothing beneath it.
    peek.addEventListener('touchmove', e => { if (e.target === peek && e.cancelable) e.preventDefault(); }, { passive: false });
    document.body.append(peek);
    return peek;
  };
  function open(card) {
    if (!card.isConnected || document.querySelector('dialog[open]')) return false;
    const d = dialog();
    const box = build(card, close);
    d.replaceChildren(box);
    const name = box.querySelector('h2');
    if (name) {
      name.id = 'peek-h';
      d.setAttribute('aria-labelledby', name.id);
    }
    try { navigator.vibrate?.(12); } catch { /* not allowed before a first tap */ }
    d.showModal();
    if (!still()) lift(d, card);
    return true;
  }
  // The poster rises from its place in the row to its place in the peek.
  function lift(d, card) {
    const from = card.querySelector('.art')?.getBoundingClientRect();
    const art = d.querySelector('.peek-art');
    const to = art?.getBoundingClientRect();
    if (from && to?.width) {
      art.animate([
        { transformOrigin: '0 0', transform: `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${from.width / to.width})` },
        { transformOrigin: '0 0', transform: 'none' },
      ], { duration: 300, easing: OUT });
    }
    d.querySelector('.peek-panel')?.animate([{ opacity: 0, transform: 'translateY(14px) scale(.96)' }, { opacity: 1, transform: 'none' }],
      { duration: 240, delay: 70, easing: OUT, fill: 'backwards' });
    if (backdrops()) d.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, easing: 'ease-out', pseudoElement: '::backdrop' });
  }
  function close(now = false) {
    const d = peek;
    if (!d?.open || shutting) return;
    if (now === true || still()) { d.close(); return; }
    shutting = true;
    const fade = d.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(.94)' }],
      { duration: 160, easing: IN, fill: 'forwards' });
    const dim = backdrops()
      ? d.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, fill: 'forwards', pseudoElement: '::backdrop' })
      : null;
    after(fade, 360, () => {
      d.close();
      fade.cancel();
      dim?.cancel();
      shutting = false;
    });
  }
  const cancel = () => {
    if (!press || press.fired) return;
    clearTimeout(press.timer);
    press = null;
  };
  document.addEventListener('touchstart', e => {
    swallow = 0;
    if (press?.fired) press = null;
    cancel();
    const card = e.touches.length === 1 && e.target.closest?.('.card');
    if (!card || !card.querySelector(':scope > .card-hit') || card.closest('dialog')) return;
    const t = e.touches[0];
    const p = { id: t.identifier, x: t.clientX, y: t.clientY, fired: false, timer: 0 };
    p.timer = setTimeout(() => {
      if (press !== p) return;
      p.fired = open(card);
      if (!p.fired) press = null;
    }, LONG_PRESS);
    press = p;
  }, { passive: true });
  // Moving, scrolling or a second finger means it was never a long press.
  document.addEventListener('touchmove', e => {
    if (!press || press.fired) return;
    const t = [...e.touches].find(c => c.identifier === press.id);
    if (!t || e.touches.length > 1 || wandered(t.clientX - press.x, t.clientY - press.y)) cancel();
  }, { passive: true });
  document.addEventListener('scroll', cancel, { capture: true, passive: true });
  document.addEventListener('touchcancel', () => { if (press?.fired) press = null; else cancel(); }, { passive: true });
  document.addEventListener('touchend', e => {
    if (!press?.fired) { cancel(); return; }
    press = null;
    // Lifting the finger that peeked is not a tap; where that cannot be stopped at the
    // source, the click it leaves is.
    if (e.cancelable) e.preventDefault(); else swallow = performance.now() + 500;
  }, { passive: false });
  document.addEventListener('contextmenu', e => { if (press || performance.now() < swallow) e.preventDefault(); });
  window.addEventListener('click', e => {
    if (performance.now() >= swallow) return;
    swallow = 0;
    e.preventDefault();
    e.stopPropagation();
  }, true);
}

/* -------------------------------------------------------------- edge back */
// Installed with no browser back button, a swipe in from the left edge goes back, as
// Safari's own does in a tab. `can()` says whether there is somewhere to go back to,
// and `back()` goes there.
export function edgeBack(can, back) {
  const installed = ['standalone', 'fullscreen'].some(m => matchMedia(`(display-mode: ${m})`).matches)
    || navigator.standalone === true;
  if (!installed) return;
  const chip = document.createElement('div');
  chip.className = 'edge-back';
  chip.setAttribute('aria-hidden', 'true');
  chip.innerHTML = '<svg viewBox="0 0 24 24" focusable="false"><path d="M15 18l-6-6 6-6"/></svg>';
  const reach = () => Math.min(innerWidth / 3, 110);
  let g = null;
  document.addEventListener('touchstart', e => {
    g = null;
    const t = e.touches[0];
    if (e.touches.length !== 1 || !fromEdge(t.clientX)) return;
    g = { id: t.identifier, x: t.clientX, y: t.clientY, back: false, dx: 0, samples: [] };
  }, { passive: true });
  document.addEventListener('touchmove', e => {
    if (!g) return;
    const t = [...e.touches].find(c => c.identifier === g.id);
    if (!t || e.touches.length > 1) {
      g = null;
      chip.remove();
      return;
    }
    const dx = t.clientX - g.x, dy = t.clientY - g.y;
    if (!g.back) {
      const way = heading(dx, dy);
      if (!way) return;
      if (way !== 'x' || dx < 0 || !e.cancelable || !can()) {
        g = null;
        return;
      }
      g.back = true;
      // Over an open title page too, which sits above the rest of the page, and over an
      // episode open above that, which comes after it in the page.
      ([...document.querySelectorAll('dialog[open]')].at(-1) || document.body).append(chip);
    }
    e.preventDefault();
    g.dx = Math.max(dx, 0);
    g.samples.push([performance.now(), g.dx]);
    if (g.samples.length > 8) g.samples.shift();
    const shown = Math.min(g.dx, reach());
    chip.style.transform = `translate(${shown + 6}px, ${t.clientY}px)`;
    chip.style.opacity = String(shown / reach());
    chip.classList.toggle('ready', g.dx >= reach());
  }, { passive: false });
  const end = e => {
    if (!g || [...e.touches].some(t => t.identifier === g.id)) return;
    const goes = g.back && e.type === 'touchend' && goesBack(g.dx, speed(g.samples, performance.now()), innerWidth);
    g = null;
    chip.remove();
    chip.classList.remove('ready');
    if (goes) back();
  };
  document.addEventListener('touchend', end, { passive: true });
  document.addEventListener('touchcancel', end, { passive: true });
}
