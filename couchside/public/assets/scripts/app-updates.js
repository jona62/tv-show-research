// Modules are ready before main.js starts; poster downloads must not delay updates.
const EDITABLE = 'input,select,textarea,[contenteditable]:not([contenteditable="false"]),[role="textbox"]';
const NON_TEXT = new Set(['hidden','checkbox','radio','range','color','button','submit','reset','image']);
const INTERACTIONS = ['pointerdown','pointermove','pointerup','touchstart','touchmove','touchend',
  'mousedown','keydown','wheel','scroll','click','focusin','beforeinput','input','change',
  'paste','cut','compositionstart','drop'];

function hasFormWork(document) {
  if (document.activeElement?.closest?.(EDITABLE)) return true;
  for (const form of document.querySelectorAll('dialog[open],form,[role="dialog"]')) {
    if (form.getClientRects().length && form.querySelector(EDITABLE)) return true;
  }
  // Autofill or typing before this module arrived must survive, including hidden sheets.
  for (const field of document.querySelectorAll(EDITABLE)) {
    if (field.tagName === 'SELECT') continue;
    if (field.tagName === 'INPUT' && NON_TEXT.has(field.type)) continue;
    if (field.value || field.isContentEditable && field.textContent?.trim()
        || field.getAttribute?.('role') === 'textbox' && field.textContent?.trim()) return true;
  }
  return false;
}

export function startAppUpdates({ window = globalThis.window, document = window?.document,
  navigator = window?.navigator, reload = () => window.location.reload() } = {}) {
  const workers = navigator?.serviceWorker;
  if (!window?.isSecureContext || !workers || !document) return Promise.resolve(null);
  const previous = workers.controller;
  const watched = new WeakSet(), asked = new WeakSet();
  let interacted = false, refreshed = false;
  const markInteraction = () => { interacted = true; };
  for (const type of INTERACTIONS) document.addEventListener(type, markInteraction, { capture: true, passive: true });

  workers.addEventListener('controllerchange', () => {
    if (!previous || !workers.controller || workers.controller === previous || refreshed || interacted) return;
    // Sticky activation also catches gestures before the module loaded. If unavailable,
    // keep this document; its next normal navigation will use the new cached build.
    if (navigator.userActivation?.hasBeenActive !== false || document.visibilityState !== 'visible'
        || window.scrollX || window.scrollY || hasFormWork(document)) return;
    refreshed = true;
    reload();
  });

  const takeOver = worker => {
    if (worker?.state !== 'installed' || asked.has(worker)) return;
    asked.add(worker);
    worker.postMessage('take-over');
  };
  const watch = worker => {
    if (!worker || watched.has(worker)) return;
    watched.add(worker);
    worker.addEventListener('statechange', () => takeOver(worker));
    takeOver(worker);
  };
  return workers.register('/sw.js').then(reg => {
    reg.addEventListener('updatefound', () => watch(reg.installing));
    takeOver(reg.waiting);
    watch(reg.installing);
    return reg;
  }).catch(() => null); // An unavailable worker must not prevent the app from starting.
}
