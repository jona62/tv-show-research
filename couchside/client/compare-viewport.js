import { html } from './ratings.js';

const resetIcon = '<svg class="ratings-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11a9 9 0 1 1 2.7 6.4M3 5v6h6"/></svg>';

const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const initial = () => ({ zoomX: 1, startIndex: 0, low: null, high: null });

function bounded(value, source) {
  const last = Math.max(1, source.maxCount - 1), maxZoom = Math.max(1, source.maxCount - 1);
  const zoomX = clamp(value.zoomX || 1, 1, maxZoom), span = last / zoomX;
  const low = Number.isFinite(value.low) ? value.low : source.low;
  const high = Number.isFinite(value.high) ? value.high : 10;
  const ratingSpan = clamp(high - low, .5, 10), floor = clamp(low, 0, 10 - ratingSpan);
  return { zoomX, startIndex: clamp(value.startIndex || 0, 0, Math.max(0, source.maxCount - 1 - span)),
    low: floor, high: floor + ratingSpan, span };
}

function zoomed(value, source, factor, axis, anchor) {
  const before = bounded(value, source), next = { ...before };
  if (axis !== 'ratings') {
    next.zoomX = clamp(before.zoomX * factor, 1, Math.max(1, source.maxCount - 1));
    const span = Math.max(1, source.maxCount - 1) / next.zoomX;
    next.startIndex = anchor.index - (anchor.index - before.startIndex) / before.span * span;
  }
  if (axis !== 'episodes') {
    const span = clamp((before.high - before.low) / factor, .5, 10);
    next.low = anchor.rating - (anchor.rating - before.low) / (before.high - before.low) * span;
    next.high = next.low + span;
  }
  return bounded(next, source);
}

// State and event targets live outside the SVG that is reprojected on each frame.
export function createComparisonViewport({ changed = () => {} } = {}) {
  let view = initial(), source, plan, scope, board, controller, frame, drag, touch, gesture;
  let suppressClick = 0, disposed = false, foreignTouch = false, nativeTouchCount = 0;
  const controls = document.createElement('div');
  controls.className = 'comparison-zoom-controls'; controls.dataset.comparisonZoomControls = '';
  html(controls, `<button class="round small comparison-zoom-reset" type="button" data-zoom-action="reset" aria-label="Reset timeline zoom" title="Reset timeline zoom">${resetIcon}</button><p class="ratings-credit comparison-zoom-range" role="status" aria-live="polite"></p>`);
  const hideTip = () => { const tip = board?.closest('.compare-page')?.querySelector('.ratings-tooltip'); if (tip) tip.hidden = true; };
  const publish = (immediate = false) => {
    hideTip(); cancelAnimationFrame(frame);
    if (immediate) changed(); else frame = requestAnimationFrame(() => { if (!disposed) changed(); });
  };
  const update = (next, immediate = false) => {
    const before = bounded(view, source), after = bounded(next, source);
    if (['zoomX', 'startIndex', 'low', 'high'].every(key => Math.abs(before[key] - after[key]) < 1e-9)) return;
    view = after; publish(immediate);
  };
  const reset = () => { view = initial(); publish(true); };
  const centre = () => {
    const current = bounded(view, source);
    return { index: current.startIndex + current.span / 2, rating: (current.low + current.high) / 2 };
  };
  const keyboardZoom = factor => update(zoomed(view, source, factor, 'both', centre()), true);
  const inChart = target => target instanceof Element && board?.contains(target) && !target.closest('.comparison-zoom-controls') && Boolean(target.closest('.comparison-overlay-frame'));
  function location(clientX, clientY) {
    const svg = board.querySelector('.ratings-timeline'), bounds = svg.getBoundingClientRect();
    if (!Number.isFinite(clientX)) clientX = bounds.left + bounds.width / 2;
    if (!Number.isFinite(clientY)) clientY = bounds.top + (plan.raw.top + plan.raw.bottom) / 2;
    const matrix = svg.getScreenCTM();
    const point = matrix ? new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse())
      : { x: clientX - bounds.left, y: clientY - bounds.top };
    const row = plan.showTrend && point.y > (plan.raw.bottom + plan.trend.top) / 2 ? plan.trend : plan.raw;
    const fraction = clamp((row.bottom - point.y) / (row.bottom - row.top), 0, 1);
    return { index: plan.startIndex + clamp((point.x - 20) / plan.spacing, 0, plan.span),
      rating: plan.low + fraction * (plan.high - plan.low), rowHeight: row.bottom - row.top,
      inAxis: clientX < bounds.left, inXAxis: point.y > plan.raw.bottom && point.y < 290, x: point.x, y: point.y };
  }
  function pan(before, geometry, dx, dy, horizontalOnly = false) {
    const current = bounded(before, source), next = { ...current };
    next.startIndex -= dx / geometry.spacing;
    if (!horizontalOnly) { const shift = dy / geometry.rowHeight * (current.high - current.low); next.low += shift; next.high += shift; }
    update(next);
  }
  function wheel(event) {
    if (!inChart(event.target) || !plan?.live || !event.cancelable) return;
    event.preventDefault();
    const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 300 : 1;
    if (!event.ctrlKey && !event.metaKey && Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      const current = bounded(view, source); update({ ...current, startIndex: current.startIndex + event.deltaX * units / plan.spacing }); return;
    }
    const anchor = location(event.clientX, event.clientY), direction = event.shiftKey || anchor.inAxis ? 'ratings' : anchor.inXAxis ? 'episodes' : 'both';
    update(zoomed(view, source, Math.exp(-clamp(event.deltaY * units, -160, 160) * .005), direction, anchor));
  }
  function pointerDown(event) {
    if (event.pointerType === 'touch' || event.button !== 0 || !inChart(event.target)) return;
    const point = location(event.clientX, event.clientY);
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, before: bounded(view, source),
      spacing: plan.spacing, rowHeight: point.rowHeight, moved: false };
  }
  function pointerMove(event) {
    if (!drag || drag.id !== event.pointerId) return;
    // A press can leave the chart before capture begins and release elsewhere.
    if (!event.buttons) { drag = null; board.classList.remove('is-panning'); return; }
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 8) return;
    if (!drag.moved) { drag.moved = true; board.setPointerCapture?.(event.pointerId); }
    event.preventDefault(); event.stopPropagation(); board.classList.add('is-panning');
    pan(drag.before, drag, dx, dy);
  }
  function pointerEnd(event) {
    if (!drag || drag.id !== event.pointerId) return;
    if (drag.moved) { suppressClick = performance.now() + 400; event.preventDefault(); event.stopPropagation(); }
    if (board.hasPointerCapture?.(event.pointerId)) board.releasePointerCapture(event.pointerId);
    drag = null; board.classList.remove('is-panning');
  }
  const touches = event => [...event.touches].slice(0, 2).map(item => ({ x: item.clientX, y: item.clientY }));
  const midpoint = points => ({ x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 });
  const distance = points => Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y);
  function touchStart(event) {
    if (!inChart(event.target) || !plan?.live) return;
    foreignTouch = event.touches.length > 2 || [...event.touches].some(item => !board.contains(item.target) || !inChart(item.target));
    if (foreignTouch) { touch = gesture = null; return; }
    const points = touches(event), middle = points.length === 2 ? midpoint(points) : points[0];
    const anchor = location(middle.x, middle.y);
    touch = { points, middle, anchor, before: bounded(view, source), spacing: plan.spacing, moved: false };
    if (points.length === 2 && event.cancelable) { event.preventDefault(); hideTip(); suppressClick = performance.now() + 400; }
  }
  function touchMove(event) {
    if (!touch) return;
    // Another finger can begin outside the board without sending touchstart here.
    foreignTouch = event.touches.length > 2 || [...event.touches].some(item => !board.contains(item.target) || !inChart(item.target));
    if (foreignTouch) { touch = gesture = null; return; }
    const points = touches(event);
    if (points.length === 2 && touch.points.length === 2) {
      if (event.cancelable) event.preventDefault(); event.stopPropagation();
      const middle = midpoint(points), ratio = distance(points) / Math.max(24, distance(touch.points));
      const next = zoomed(touch.before, source, clamp(ratio, .05, 20), 'both', touch.anchor);
      const spacing = (plan.width - 64) / next.span;
      next.startIndex -= (middle.x - touch.middle.x) / spacing;
      const shift = (middle.y - touch.middle.y) / touch.anchor.rowHeight * (next.high - next.low);
      next.low += shift; next.high += shift;
      touch.moved = true; suppressClick = performance.now() + 400; update(next); return;
    }
    if (points.length !== 1 || touch.points.length !== 1) return;
    const dx = points[0].x - touch.points[0].x, dy = points[0].y - touch.points[0].y;
    if (!touch.moved && Math.abs(dy) > 8 && Math.abs(dy) > Math.abs(dx)) { touch = null; return; }
    if (!touch.moved && Math.abs(dx) < 8) return;
    if (event.cancelable) event.preventDefault(); event.stopPropagation(); touch.moved = true;
    suppressClick = performance.now() + 400;
    pan(touch.before, { spacing: touch.spacing, rowHeight: touch.anchor.rowHeight }, dx, 0, true);
  }
  function touchEnd(event) {
    if (touch?.moved) suppressClick = performance.now() + 400; touch = null;
    if (!event.touches.length) foreignTouch = false;
  }
  function gestureStart(event) {
    // Native pinches belong to touchMove; this fallback is for a trackpad.
    if (nativeTouchCount || foreignTouch || !inChart(event.target) || !plan?.live) return;
    if (event.cancelable) event.preventDefault();
    gesture = { before: bounded(view, source), anchor: location(event.clientX, event.clientY) };
  }
  function gestureMove(event) {
    if (!gesture || nativeTouchCount || foreignTouch) return;
    if (event.cancelable) event.preventDefault();
    if (touch?.points.length === 2) return;
    suppressClick = performance.now() + 400;
    update(zoomed(gesture.before, source, clamp(event.scale || 1, .05, 20), 'both', gesture.anchor));
  }
  function keydown(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (controls.contains(event.target)) return;
    if (!event.target.matches('.ratings-chart-wrap')) return;
    const current = bounded(view, source), next = { ...current }, step = current.span * .15;
    if (['+', '='].includes(event.key)) keyboardZoom(1.5);
    else if (event.key === '-') keyboardZoom(1 / 1.5);
    else if (event.key === '0') reset();
    else if (event.key === 'Home') next.startIndex = 0;
    else if (event.key === 'End') next.startIndex = Math.max(0, source.maxCount - 1 - current.span);
    else if (['ArrowLeft', 'ArrowRight'].includes(event.key)) next.startIndex += event.key === 'ArrowRight' ? step : -step;
    else if (['ArrowUp', 'ArrowDown'].includes(event.key)) { const shift = (current.high - current.low) * (event.key === 'ArrowUp' ? .15 : -.15); next.low += shift; next.high += shift; }
    else return;
    event.preventDefault(); event.stopPropagation();
    if (!['+', '=', '-', '0'].includes(event.key)) update(next, true);
  }
  function click(event) {
    if (performance.now() < suppressClick && inChart(event.target)) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    const button = event.target.closest('button'); if (!button || !controls.contains(button)) return;
    if (button.dataset.zoomAction === 'reset') { event.preventDefault(); reset(); }
  }
  function updateControls() {
    if (!source || !plan) return;
    controls.hidden = !board?.querySelector('.ratings-timeline');
    const lastPlot = plan.showTrend ? plan.trend : plan.raw;
    controls.style.setProperty('--comparison-zoom-bottom', `${plan.height - lastPlot.bottom + 12}px`);
    const current = bounded(view, source);
    controls.querySelector('.comparison-zoom-range').textContent = `Episodes ${Math.floor(current.startIndex) + 1}–${Math.min(source.maxCount, Math.ceil(current.startIndex + current.span) + 1)} of ${source.maxCount} · Ratings ${current.low.toFixed(2).replace(/\.00$/, '')}–${current.high.toFixed(2).replace(/\.00$/, '')}`;
  }
  // A released or scrolling finger can leave the board's local event stream.
  const nativeTouches = event => {
    nativeTouchCount = event.touches.length; gesture = null;
    if (!nativeTouchCount) {
      if (touch?.moved) suppressClick = performance.now() + 400;
      touch = null; foreignTouch = false;
    }
  };
  for (const name of ['touchstart', 'touchend', 'touchcancel']) document.addEventListener(name, nativeTouches, { capture: true, passive: true });
  return {
    prepare(nextSource, nextScope) {
      source = nextSource;
      if (scope !== nextScope) { scope = nextScope; view = initial(); drag = touch = gesture = null; foreignTouch = false; board?.classList.remove('is-panning'); }
    },
    options() { return Number.isFinite(view.low) ? bounded(view, source) : { zoomX: 1, startIndex: 0 }; },
    bind(nextBoard, nextPlan) {
      plan = nextPlan;
      nextBoard.querySelector('[data-comparison-zoom-controls]')?.replaceWith(controls);
      if (board !== nextBoard) {
        controller?.abort(); board = nextBoard; controller = new AbortController();
        const listen = (name, handler, options = {}) => board.addEventListener(name, handler, { ...options, signal: controller.signal });
        listen('wheel', wheel, { passive: false }); listen('click', click, { capture: true }); listen('keydown', keydown);
        listen('pointerdown', pointerDown, { capture: true }); listen('pointermove', pointerMove, { capture: true });
        listen('pointerup', pointerEnd, { capture: true }); listen('pointercancel', pointerEnd, { capture: true });
        listen('touchstart', touchStart, { passive: false }); listen('touchmove', touchMove, { passive: false });
        listen('touchend', touchEnd); listen('touchcancel', touchEnd);
        listen('gesturestart', gestureStart, { passive: false }); listen('gesturechange', gestureMove, { passive: false });
        listen('gestureend', () => { gesture = null; });
      }
      updateControls();
    },
    reveal(index, rating) {
      const current = bounded(view, source), next = { ...current };
      if (index < current.startIndex || index > current.startIndex + current.span) next.startIndex = index - current.span / 2;
      if (rating < current.low || rating > current.high) { next.low = rating - (current.high - current.low) / 2; next.high = next.low + current.high - current.low; }
      update(next, true);
    },
    suspend() {
      cancelAnimationFrame(frame); controller?.abort(); board?.classList.remove('is-panning'); board = null;
      drag = touch = gesture = null; foreignTouch = false;
    },
    dispose() {
      disposed = true; cancelAnimationFrame(frame); controller?.abort();
      for (const name of ['touchstart', 'touchend', 'touchcancel']) document.removeEventListener(name, nativeTouches, true);
      nativeTouchCount = 0;
      drag = touch = gesture = null; controls.remove();
    },
  };
}
