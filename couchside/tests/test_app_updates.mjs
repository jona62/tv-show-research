import assert from 'node:assert/strict';
import { startAppUpdates } from '../client/app-updates.js';

class Worker extends EventTarget {
  constructor(state = 'installing') { super(); this.state = state; this.messages = []; }
  postMessage(message) { this.messages.push(message); }
  change(state) { this.state = state; this.dispatchEvent(new Event('statechange')); }
}
class Registration extends EventTarget {
  waiting = null;
  installing = null;
  found(worker) { this.installing = worker; this.dispatchEvent(new Event('updatefound')); }
}
function browser({ controlled = true, activation = false, waiting = null, installing = null, fail = false } = {}) {
  const document = new EventTarget();
  const fields = [], forms = [];
  Object.assign(document, { readyState: 'loading', visibilityState: 'visible', activeElement: null,
    querySelectorAll: selector => selector.startsWith('dialog') ? forms : fields });
  const registration = new Registration();
  Object.assign(registration, { waiting, installing });
  const workers = new EventTarget(), calls = [];
  Object.assign(workers, { controller: controlled ? new Worker('activated') : null,
    register: async path => { calls.push(path); if (fail) throw Error('offline'); return registration; } });
  const navigator = { serviceWorker: workers, userActivation: { hasBeenActive: activation } };
  const window = { document, navigator, isSecureContext: true, scrollX: 0, scrollY: 0 };
  let reloads = 0;
  return { window, document, navigator, registration, calls, fields, forms,
    start: () => startAppUpdates({ window, reload: () => { reloads++; } }),
    control(worker = new Worker('activated')) { workers.controller = worker; workers.dispatchEvent(new Event('controllerchange')); },
    interact(type) { document.dispatchEvent(new Event(type)); },
    reloads: () => reloads };
}

const held = browser({ waiting: new Worker('installed') });
const heldReady = held.start();
assert.deepEqual(held.calls, ['/sw.js'], 'registration starts while load remains held');
await heldReady;
assert.equal(held.document.readyState, 'loading');
assert.deepEqual(held.registration.waiting.messages, ['take-over']);
assert.equal(held.reloads(), 0, 'a waiting worker alone must not reload the page');
held.control();
assert.equal(held.reloads(), 1, 'a genuine update refreshes an untouched initial navigation');
held.control();
assert.equal(held.reloads(), 1, 'multiple controller events cannot make a reload loop');

const installing = new Worker(), existing = browser({ installing });
await existing.start();
assert.equal(installing.messages.length, 0);
installing.change('installed');
assert.deepEqual(installing.messages, ['take-over'], 'an installation already underway is observed');
installing.change('installed');
assert.equal(installing.messages.length, 1);

const future = browser();
await future.start();
const upcoming = new Worker();
future.registration.found(upcoming);
upcoming.change('installed');
assert.deepEqual(upcoming.messages, ['take-over'], 'later updatefound installations are observed');
const alreadyDone = new Worker('installed');
future.registration.found(alreadyDone);
assert.deepEqual(alreadyDone.messages, ['take-over'], 'an update that finished before observation is taken over');

const first = browser({ controlled: false, waiting: new Worker('installed') });
await first.start();
first.control();
assert.equal(first.reloads(), 0, 'first installation and clients.claim must not reload a new visitor');
assert.deepEqual(first.registration.waiting.messages, ['take-over']);
const unchanged = browser();
await unchanged.start();
unchanged.control(unchanged.navigator.serviceWorker.controller);
assert.equal(unchanged.reloads(), 0, 'unchanged or absent controllers are not updates');
unchanged.control(null);
assert.equal(unchanged.reloads(), 0);

const whileRegistering = browser();
let finishRegistration;
whileRegistering.navigator.serviceWorker.register = () => new Promise(resolve => { finishRegistration = resolve; });
const registering = whileRegistering.start();
whileRegistering.interact('input');
finishRegistration(whileRegistering.registration);
await registering;
whileRegistering.control();
assert.equal(whileRegistering.reloads(), 0, 'typing while registration is pending is preserved');

for (const type of ['pointerdown','pointermove','pointerup','touchstart','touchmove','touchend',
  'keydown','wheel','scroll','click','focusin','beforeinput','input','change','paste','compositionstart','drop']) {
  const active = browser({ waiting: new Worker('installed') });
  await active.start();
  active.interact(type);
  active.control();
  assert.equal(active.reloads(), 0, `${type} permanently prevents an automatic refresh`);
  assert.deepEqual(active.registration.waiting.messages, ['take-over'], 'interaction does not block the next navigation from updating');
}
for (const activation of [true, undefined]) {
  const earlier = browser();
  earlier.navigator.userActivation = activation === undefined ? undefined : { hasBeenActive: activation };
  await earlier.start();
  earlier.control();
  assert.equal(earlier.reloads(), 0, 'earlier gestures or unavailable activation tracking fail closed');
}

const focused = browser();
focused.document.activeElement = { closest: () => ({}) };
await focused.start();
focused.control();
assert.equal(focused.reloads(), 0, 'an editable focus is preserved without relying on input events');
const form = browser();
form.forms.push({ getClientRects: () => [{}], querySelector: () => ({}) });
await form.start();
form.control();
assert.equal(form.reloads(), 0, 'an open editable sheet is preserved even without editable focus');
for (const field of [
  { tagName: 'INPUT', type: 'password', value: 'autofilled password' },
  { tagName: 'INPUT', type: 'search', value: 'earlier search' },
  { tagName: 'TEXTAREA', value: 'pasted list' },
  { tagName: 'DIV', isContentEditable: true, textContent: 'earlier editable text' },
  { tagName: 'DIV', getAttribute: name => name === 'role' ? 'textbox' : null, textContent: 'earlier custom field' },
]) {
  const populated = browser();
  populated.fields.push(field);
  await populated.start();
  populated.control();
  assert.equal(populated.reloads(), 0, 'earlier text and credentials must not be erased');
}
const scrolled = browser();
scrolled.window.scrollY = 50;
await scrolled.start();
scrolled.control();
assert.equal(scrolled.reloads(), 0, 'a page already scrolled must not be interrupted');
const background = browser();
background.document.visibilityState = 'hidden';
await background.start();
background.control();
assert.equal(background.reloads(), 0);
const failed = browser({ fail: true });
assert.equal(await failed.start(), null, 'registration failures do not stop the app');
const unsupported = browser();
unsupported.window.isSecureContext = false;
assert.equal(await unsupported.start(), null);
assert.equal(unsupported.calls.length, 0);
const untouched = browser();
untouched.fields.push({ tagName: 'INPUT', type: 'range', value: '50' },
  { tagName: 'INPUT', type: 'hidden', value: 'metadata' }, { tagName: 'SELECT', value: 'all' });
untouched.forms.push({ getClientRects: () => [], querySelector: () => ({}) });
await untouched.start();
untouched.control();
assert.equal(untouched.reloads(), 1, 'default controls and closed sheets do not block an untouched navigation');
console.log('App updates: held load, waiting/existing/future installations, controller handoff and form/interaction safety passed.');
