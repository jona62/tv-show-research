// The refresher's status page: the run buttons, and a light poll that reloads the page
// when a run starts or ends. Everything else is rendered by the server.
const running = document.body.dataset.running === '1';
const message = document.getElementById('msg');
const state = document.getElementById('state');
const buttons = [...document.querySelectorAll('[data-run]')];

function took(seconds) {
  if (seconds < 90) return `${seconds} s`;
  if (seconds < 5400) return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  return `${Math.floor(seconds / 3600)} h ${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')} min`;
}

function describe(run) {
  let text = `Running a ${run.kind} run: ${run.step || 'starting'}`;
  if (run.step_seconds != null) text += `, ${took(run.step_seconds)} in`;
  return text;
}

async function start(step) {
  for (const button of buttons) button.disabled = true;
  message.textContent = 'Starting';
  try {
    const response = await fetch(step ? `/api/run?step=${encodeURIComponent(step)}` : '/api/run', {
      method: 'POST', headers: {'X-Requested-With': 'refresher'}, credentials: 'same-origin',
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 202) {
      location.reload();
      return;
    }
    message.textContent = body.error || `Could not start a run (${response.status}).`;
  } catch (error) {
    message.textContent = 'Could not reach the refresher.';
  }
  for (const button of buttons) button.disabled = running;
}

for (const button of buttons) button.addEventListener('click', () => start(button.dataset.run));

async function poll() {
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    if (response.ok) {
      const status = await response.json();
      if (Boolean(status.running) !== running) {
        location.reload();
        return;
      }
      if (status.running) state.textContent = describe(status.running);
    }
  } catch (error) {
    // The service may be restarting; look again on the next tick.
  }
  setTimeout(poll, running ? 3000 : 30000);
}

setTimeout(poll, running ? 3000 : 30000);
