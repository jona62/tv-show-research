import { createPollLeadership } from './account-polling.js?v=51e6158044c60f45';
import { AccountSync, ACTIVE_KEY } from './account-state.js?v=8a7923884b155f21';

const STATUS = {
  checking: 'Checking your account…',
  guest: 'Save your ratings and My List across devices.',
  saved: 'Up to date. Your ratings and My List sync automatically.',
  pending: 'Your changes are saved on this device and will sync automatically.',
  saving: 'Syncing your changes automatically…',
  retry: 'Couldn’t sync yet. Your changes are saved on this device.',
  offline: 'Your changes are saved on this device. They’ll sync when you reconnect.',
  expired: 'Sign in again to sync. Your changes are saved on this device.',
};

const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
};

const button = (label, handler, className = 'btn ghost') => {
  const node = element('button', className, label);
  node.type = 'button';
  node.addEventListener('click', handler);
  return node;
};

export function watchAccount(sync, { doc = document, win = window, clock = Date.now,
  setTimer = setTimeout, clearTimer = clearTimeout, interval = 60000, random = Math.random, idleLimit = 4,
  leadership: providedLeadership } = {}) {
  let timer = null, flight = null, checked = -Infinity, failures = 0, idle = 0, stopped = false;
  const visible = () => doc.visibilityState !== 'hidden';
  const cancel = () => { clearTimer(timer); timer = null; };
  const leadership = providedLeadership || createPollLeadership({ storage: sync.storage, clock,
    changed: data => {
      if (!sync.user || stopped || data.owner !== String(sync.user.id)) return;
      // Revocation/expiration is a hint to authenticate again, never a remote
      // instruction to trust credentials or replace a local account state.
      if (data.verify) { void sync.refresh(); return; }
      const key = `couchside-account-v1:${sync.user.id}`;
      let newValue; try { newValue = sync.storage?.getItem(key); } catch { return; }
      if (newValue) void sync.storageChanged?.({ key, newValue }, { refresh: false });
    } });
  const delay = () => Math.min(interval * 2 ** failures * (sync.pending ? 1 : 1 + idle), 300000);
  function schedule() {
    cancel();
    if (stopped || !visible()) return;
    leadership.select(sync.user?.id);
    const wait = delay();
    timer = setTimer(() => {
      timer = null;
      if (sync.user && sync.status !== 'expired') void refresh(); else schedule();
    }, wait * (.9 + random() * .2));
  }
  function refresh(force = false) {
    if (stopped || !visible()) return;
    if (flight) return flight;
    if (!force && clock() - checked < 5000) { schedule(); return; }
    checked = clock(); cancel();
    const before = sync.revision;
    flight = Promise.resolve().then(() => leadership.run(sync.user?.id, delay(), async () => {
      await sync.refresh(); return { verify: sync.status === 'expired' };
    })).catch(() => {}).finally(() => {
      failures = sync.user && !sync.connected && sync.status !== 'expired' ? Math.min(failures + 1, 3) : 0;
      idle = !failures && !sync.pending && sync.revision === before ? Math.min(idle + 1, idleLimit) : 0;
      flight = null; if (sync.status === 'expired') leadership.release(); schedule();
    });
    return flight;
  }
  const focus = () => { idle = 0; void refresh(); };
  const online = () => { idle = 0; leadership.release(); void refresh(true); };
  const visibility = () => { if (visible()) focus(); else { cancel(); leadership.release(); } };
  doc.addEventListener('visibilitychange', visibility);
  win.addEventListener('focus', focus); win.addEventListener('online', online);
  // Every tab validates its own initial session. Poll leadership only starts
  // after initialization, so an account marker can never authenticate a tab.
  flight = Promise.resolve().then(() => sync.ready()).catch(() => {}).finally(() => {
    checked = clock(); flight = null; schedule();
  });
  const stop = () => {
    stopped = true; cancel(); leadership.release();
    doc.removeEventListener('visibilitychange', visibility);
    win.removeEventListener('focus', focus); win.removeEventListener('online', online);
  };
  stop.shouldRefresh = () => { leadership.select(sync.user?.id); return leadership.owns(); };
  return stop;
}

export function mountAccounts({ getState, applyState, fresh, sanitize, toast = () => {}, onStatus = () => {},
  onContext = () => {} }) {
  const panel = document.getElementById('account-access');
  const dialog = document.getElementById('auth');
  const body = document.getElementById('auth-body');
  const heading = document.getElementById('auth-h');
  let formBusy = false;
  let formVersion = 0;
  let contextSuspensions = 0;
  const sync = new AccountSync({ getState, applyState: (state, options) => {
    // Revoke feature access before the old owner's asynchronous UI paint ends.
    notifyContext();
    return applyState(state, options);
  }, fresh, sanitize, onStatus: status => {
    renderPanel(status);
    notifyContext();
    onStatus(status);
  } });

  const context = () => sync.connected && sync.csrf && !contextSuspensions
    ? { user: sync.user, csrf: sync.csrf } : { user: null, csrf: null };
  function notifyContext() { onContext(context()); }
  async function accountTransition(action) {
    ++contextSuspensions;
    notifyContext();
    try { return await action(); }
    finally { --contextSuspensions; notifyContext(); }
  }

  function renderPanel({ status = sync.status, message = '', user = sync.user, connected = sync.connected } = {}) {
    const section = element('div', 'account-panel');
    if (user) section.append(element('p', 'account-email', user.email));
    const note = element('p', 'account-status', message || STATUS[status] || STATUS.guest);
    note.setAttribute('role', 'status');
    section.append(note);
    const actions = element('div', 'account-actions');
    if (user) {
      if (status === 'expired') actions.append(button('Sign in again', () => openForm('login'), 'btn primary'));
      if (status === 'retry' || status === 'offline') actions.append(button('Try again', async event => {
        event.currentTarget.disabled = true;
        try {
          await sync.refresh();
          await sync.flush();
        } catch (error) {
          toast(error.message);
        } finally {
          renderPanel();
        }
      }));
      if (connected) actions.append(button('Change password', () => openForm('password')));
      actions.append(button('Sign out', async event => {
        event.currentTarget.disabled = true;
        try { await accountTransition(() => sync.logout()); toast('Signed out. This device’s guest list is restored.'); }
        catch (error) { toast(error.message); renderPanel(); }
      }));
    } else {
      actions.append(button('Create account', () => openForm('signup'), 'btn primary'));
      actions.append(button('Sign in', () => openForm('login')));
    }
    for (const action of actions.children) action.disabled = status === 'checking';
    section.append(actions);
    panel.replaceChildren(section);
  }

  function field(form, label, name, { type = 'text', autocomplete, minLength, maxLength, value = '' } = {}) {
    const wrapper = element('label', 'field', label);
    const input = element('input');
    input.id = `auth-${name}`;
    input.name = name;
    input.type = type;
    input.required = true;
    input.value = value;
    if (autocomplete) input.autocomplete = autocomplete;
    if (minLength) input.minLength = minLength;
    if (maxLength) input.maxLength = maxLength;
    wrapper.htmlFor = input.id;
    wrapper.append(input);
    form.append(wrapper);
    return input;
  }

  function openForm(kind) {
    if (formBusy) return;
    const version = ++formVersion;
    for (const id of ['account', 'profile']) document.getElementById(id)?.close();
    heading.textContent = kind === 'signup' ? 'Create your account'
      : kind === 'password' ? 'Change your password' : 'Sign in to Couchside';
    body.replaceChildren();
    body.append(element('p', 'note', kind === 'signup'
      ? sync.user ? 'Keep your ratings and My List together on every device. The guest list saved on this device will be added to your new account.'
        : 'Keep your ratings and My List together on every device. Your list on this device will be saved to your account.'
      : kind === 'password' ? 'Choose a password you do not use elsewhere.'
        : 'Use your email and password to pick up where you left off.'));
    const form = element('form', 'auth-form');
    const isNewPassword = kind !== 'login';
    let email = null, current = null, confirm = null;
    if (kind !== 'password') {
      email = field(form, 'Email address', 'email', { type: 'email', autocomplete: 'username', maxLength: 254,
        value: kind === 'login' ? sync.user?.email || '' : '' });
      email.inputMode = 'email';
      email.autocapitalize = 'none';
      email.spellcheck = false;
      email.pattern = '[^\\s@]+@[^\\s@]+\\.[^\\s@]+';
      email.title = 'Use an email address with a complete domain, such as name@example.com.';
    } else {
      current = field(form, 'Current password', 'current-password', {
        type: 'password', autocomplete: 'current-password', maxLength: 128,
      });
    }
    const password = field(form, kind === 'password' ? 'New password' : 'Password', 'password', {
      type: 'password', autocomplete: isNewPassword ? 'new-password' : 'current-password',
      minLength: isNewPassword ? 15 : undefined, maxLength: 128,
    });
    if (isNewPassword) {
      form.append(element('p', 'note auth-password-note', 'Use at least 15 characters. A passphrase works well.'));
      confirm = field(form, 'Confirm password', 'confirm-password', {
        type: 'password', autocomplete: 'new-password', minLength: 15, maxLength: 128,
      });
      confirm.addEventListener('input', () => confirm.setCustomValidity(''));
      password.addEventListener('input', () => confirm.setCustomValidity(''));
    }
    if (kind === 'login' && !sync.user && (getState().profile.length || getState().saved.length)) {
      form.append(element('p', 'note', 'This device’s shows will join your account. Shows already there stay once, with your account’s ratings.'));
    }
    const error = element('p', 'auth-error');
    error.setAttribute('role', 'alert');
    error.hidden = true;
    form.append(error);
    const submit = element('button', 'btn primary', kind === 'signup' ? 'Create account'
      : kind === 'password' ? 'Save password' : 'Sign in');
    submit.type = 'submit';
    form.append(submit);
    if (kind !== 'password') {
      const switcher = element('p', 'note auth-switch', kind === 'signup' ? 'Already have an account? ' : 'New to Couchside? ');
      switcher.append(button(kind === 'signup' ? 'Sign in' : 'Create account',
        () => openForm(kind === 'signup' ? 'login' : 'signup'), 'link'));
      form.append(switcher);
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (formBusy) return;
      if (confirm && confirm.value !== password.value) {
        confirm.setCustomValidity('The passwords do not match.');
        confirm.reportValidity();
        return;
      }
      if (!form.reportValidity()) return;
      error.hidden = true;
      formBusy = true;
      submit.textContent = kind === 'signup' ? 'Creating account…' : kind === 'password' ? 'Saving password…' : 'Signing in…';
      const payload = { email: email?.value.trim(), password: password.value,
        current_password: current?.value };
      for (const input of form.querySelectorAll('input,button')) input.disabled = true;
      try {
        await accountTransition(() => sync.authenticate(kind, payload));
        if (version === formVersion) dialog.close();
        toast(kind === 'signup' ? 'Your account is ready.' : kind === 'password' ? 'Password changed.' : 'Signed in.');
      } catch (failure) {
        if (version === formVersion) {
          error.textContent = failure.message;
          error.hidden = false;
        }
      } finally {
        formBusy = false;
        for (const input of form.querySelectorAll('input,button')) input.disabled = false;
        submit.textContent = kind === 'signup' ? 'Create account' : kind === 'password' ? 'Save password' : 'Sign in';
        // Passwords never leave the submitted request or survive a closed dialog.
        if (!dialog.open) form.reset();
      }
    });
    body.append(form);
    if (!dialog.open) dialog.showModal();
    (email || current || password).focus();
  }

  const closeForm = () => {
    if (!formBusy) body.querySelector('form')?.reset();
  };
  const otherTab = event => {
    const update = () => sync.storageChanged(event, { refresh: stopWatching.shouldRefresh() });
    let owner = null;
    if (event.key === ACTIVE_KEY) {
      try { owner = JSON.parse(event.newValue || 'null')?.id; } catch { /* Invalid owner marker. */ }
    }
    // Storage notifications can switch owners before storageChanged finishes
    // painting. Suspend feature access synchronously at that boundary.
    if (event.key === ACTIVE_KEY && String(owner ?? '') !== String(sync.user?.id ?? '')) {
      void accountTransition(update);
    } else { void update(); }
  };
  dialog.addEventListener('close', closeForm);
  window.addEventListener('storage', otherTab);
  const stopWatching = watchAccount(sync);
  renderPanel();

  return {
    changed: () => sync.changed(),
    ready: () => sync.ready(),
    refresh: () => sync.refresh(),
    sync: () => sync.flush(),
    context,
    destroy() {
      sync.destroy();
      stopWatching();
      dialog.removeEventListener('close', closeForm);
      window.removeEventListener('storage', otherTab);
    },
  };
}
